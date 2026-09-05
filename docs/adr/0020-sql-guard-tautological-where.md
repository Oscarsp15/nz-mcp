# ADR 0020 — Rechazar predicados WHERE siempre verdaderos salvo confirmación explícita

- Estado: aceptado
- Fecha: 2026-09-04
- Issue: [#140](https://github.com/Oscarsp15/nz-mcp/issues/140)

## Contexto

`sql_guard` exigía que todo `UPDATE` / `DELETE` tuviera cláusula `WHERE`
(`UPDATE_REQUIRES_WHERE` / `DELETE_REQUIRES_WHERE`). La comprobación era puramente
sintáctica: bastaba con que el nodo `where` existiera en el AST.

`DELETE FROM T WHERE 1=1` tiene `WHERE`, pasa el guard y borra la tabla entera. La
barrera protegía contra el olvido de escribir `WHERE`, no contra el borrado masivo,
que es el daño del que existe para proteger. Un LLM que quiere "borrar todo" escribe
`WHERE 1=1` con total naturalidad, sin ninguna intención adversarial.

Las otras defensas no cubren el hueco:

- `dry_run` + `COUNT` da visibilidad, pero el modelo puede ignorar el número y llamar
  con `confirm=true` igualmente. Es UX, no un límite estructural.
- Los permisos del usuario Netezza (barrera 3) no distinguen entre borrar 1 fila y
  borrar 40 millones.

## Problema de fondo: la tautología es indecidible

Decidir si un predicado SQL arbitrario es verdadero para toda fila es indecidible en
el caso general (involucra los datos, funciones definidas por el usuario, aritmética
de precisión arbitraria y semántica ternaria con `NULL`). Cualquier detector completo
es imposible; cualquier detector práctico deja huecos.

Por tanto la decisión **no** es "detectar tautologías", sino "detectar un conjunto
cerrado y explícito de formas triviales, y decir con exactitud qué queda fuera".

## Decisión

### 1. Qué se detecta (constant folding sobre el AST de `sqlglot`)

Se añade `_static_truth(node) -> bool | None` (`None` = "no se puede decidir"), que
**solo** pliega:

| Forma | Ejemplo | Resultado |
|---|---|---|
| Literal booleano | `WHERE TRUE` | bloqueado |
| Literal numérico como predicado | `WHERE 1` | bloqueado (`WHERE 0` → falso, pasa) |
| Comparación entre dos literales del mismo tipo (`=`, `<>`, `>`, `>=`, `<`, `<=`) | `WHERE 1=1`, `WHERE 2>1`, `WHERE 'a'='a'`, `WHERE 'x'<>'y'` | bloqueado si evalúa a verdadero |
| Negativo literal | `WHERE -1 < 1` | bloqueado |
| Paréntesis | `WHERE (1=1)` | bloqueado |
| `NOT` de una constante decidible | `WHERE NOT FALSE`, `WHERE NOT (1=2)` | bloqueado |
| `AND` / `OR` con lógica ternaria | `WHERE id=5 OR 1=1`, `WHERE 1=1 AND 2>1` | bloqueado |
| Comparación de una columna consigo misma (`=`) | `WHERE id = id` | bloqueado |

Los números se comparan con `Decimal` (no con el texto del literal), para que
`WHERE 9 < 10` se plieguen bien. Las cadenas se comparan como cadenas. Las
comparaciones entre tipos distintos (`'1' = 1`) **no** se pliegan.

`WHERE id = id` no es, en rigor, una tautología: para filas con `id NULL` evalúa a
`NULL` y no selecciona. Se incluye a propósito como **sobre-aproximación**: no
restringe nada más allá de los `NULL` y no tiene uso legítimo conocido. Al ser una
puerta de confirmación y no un rechazo definitivo (ver punto 2), el coste de un falso
positivo es un parámetro extra, no un bloqueo.

### 2. Qué se hace: confirmación explícita, no rechazo definitivo

`validate()` gana `confirm_full_table: bool = False`. Con el default, un predicado
plegable a verdadero se rechaza con el código `WHERE_ALWAYS_TRUE`. Con
`confirm_full_table=True` se permite.

Se eligió confirmación sobre rechazo duro porque:

- Actualizar o borrar la tabla entera es una operación legítima y frecuente (recargas,
  limpieza de staging). Un rechazo absoluto empuja al usuario a evadir la tool (p. ej.
  `WHERE id > -999999999`), que es peor: el guard deja de ver la intención.
- **El consumidor es un LLM, no una persona.** Un parámetro que el modelo debe emitir
  explícitamente es una barrera real: obliga a declarar la intención, no se satisface
  por accidente al copiar un predicado, y queda registrada en los argumentos de la
  llamada (auditable en el log de la tool).
- No reduce estrictez respecto a `main`: todo lo que pasaba antes con `WHERE 1=1` ahora
  necesita un parámetro adicional. Es estrictamente más restrictivo.

`confirm_full_table` **no** eleva privilegios ni exime del `WHERE`: en modo `read` un
`DELETE` sigue rechazado (`STATEMENT_NOT_ALLOWED`) y `DELETE FROM t` sin `WHERE` sigue
siendo `DELETE_REQUIRES_WHERE`. La comprobación se aplica solo a `UPDATE` / `DELETE`;
un `SELECT * FROM t WHERE 1=1` no es destructivo y no se toca.

### 3. Qué NO se detecta (límite honesto de la garantía)

Todo predicado que dependa de datos o que requiera evaluación semántica queda
**UNDECIDED** y pasa el guard:

- Constantes tras una función: `WHERE ABS(1) = 1`, `WHERE UPPER('a') = 'A'`.
- Predicados prácticamente universales pero dependientes de datos:
  `WHERE id > -2147483648`, `WHERE name LIKE '%'`, `WHERE id IS NOT NULL`.
- Comparaciones entre tipos distintos: `WHERE '1' = 1`.
- Subconsultas: `WHERE id IN (SELECT id FROM t)`.
- Aritmética: `WHERE 1+1 = 2`.
- `CASE`, `COALESCE`, casts y cualquier expresión no listada en el punto 1.

**Esta ADR no promete "el guard impide borrar la tabla entera".** Promete que las
formas triviales y habituales de neutralizar el `WHERE` obligan a declarar la
intención. Un llamante decidido a saltarse la comprobación puede hacerlo; lo que se
elimina es el caso accidental, que es el que produce el daño real.

## Alternativas consideradas

- **Rechazo duro sin escape**: rompe casos legítimos y empuja a evadir la comprobación
  con predicados que el guard no puede ver. Peor postura de seguridad.
- **Umbral por `COUNT` estimado** (propuesto en el issue): requiere una ida a la base
  antes de cada mutación (coste y latencia en tablas grandes), el umbral es arbitrario
  y depende de los datos, y no distingue "borrar 10 M de filas a propósito" de un
  accidente. Se descarta como mecanismo principal; el `dry_run` + `COUNT` existente ya
  aporta esa señal informativa.
- **Regex sobre el texto** (`\bWHERE\s+1\s*=\s*1\b`): prohibido por el modelo de
  seguridad (anti-patrón explícito) y trivialmente evadible (`WHERE 1 = 1.0`).
- **Normalizar con el simplificador de `sqlglot`** (`sqlglot.optimizer.simplify`):
  detectaría más casos, pero es una superficie mucho mayor, con reescrituras cuyo
  comportamiento no controlamos, dentro del módulo más sensible del proyecto. Se
  prefiere un plegado propio de ~60 líneas, legible y con cobertura del 100 %.

## Consecuencias

- **Positivas**: el escenario del issue (`WHERE 1=1`, `WHERE true`, `WHERE 2>1`) deja
  de pasar en silencio; la intención de tocar la tabla entera queda registrada en la
  llamada; la barrera 2 vuelve a significar lo que decía significar.
- **Negativas**: superficie nueva en `sql_guard.py` (~60 líneas) y un parámetro más en
  `nz_update` / `nz_delete`; posibles falsos positivos en `col = col`.
- **Cambio observable**: `nz_update` / `nz_delete` con un `WHERE` siempre verdadero
  devuelven ahora `WHERE_ALWAYS_TRUE` en vez de ejecutarse. Documentado en el CHANGELOG.
- **Mitigaciones**: 38 casos adversariales nuevos (bloqueados, no bloqueados y huecos
  conocidos documentados como tales), cobertura de `sql_guard.py` al 100 %.

## Validación humana

Pendiente: el owner debe confirmar que ningún flujo propio dependía de `WHERE 1=1`
como forma habitual de recargar una tabla; en ese caso el flujo debe pasar a enviar
`confirm_full_table=true` (o a usar `nz_truncate`, modo `admin`).
