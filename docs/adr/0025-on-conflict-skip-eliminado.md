# ADR 0025 — Eliminar `on_conflict="skip"` de `nz_insert`

- Estado: aceptado
- Fecha: 2026-09-05
- Issue: [#134](https://github.com/Oscarsp15/nz-mcp/issues/134)

## Contexto

`nz_insert` aceptaba `on_conflict="error"` (default) o `"skip"`. La rama `skip` insertaba
las filas **una a una** y, cuando el driver lanzaba una excepción cuyo texto contenía
`duplicate`, `unique` o `23505`, se saltaba esa fila y seguía.

Netezza / PureData **no impone** restricciones `UNIQUE` ni `PRIMARY KEY`: se declaran, se
guardan en el catálogo (`_v_table_constraint`, `_v_relation_keydata`) y las usa el
optimizador, pero el motor no rechaza un `INSERT` que las viola. Es decir, la excepción
que la rama `skip` esperaba **no llega nunca**: se insertan todas las filas, duplicados
incluidos, y la tool responde `inserted = N` con éxito.

La opción prometía una protección que no existía. Para un llamante que es un LLM esto es
peor que no ofrecerla: `skip` se lee como "es seguro reintentar", y el resultado real es
duplicar datos silenciosamente.

Otros dos defectos de la misma rama, independientes de si el motor valida o no:

- La detección era una búsqueda de subcadenas en el mensaje de error. Cualquier fallo cuyo
  texto contuviera la palabra `unique` se habría tragado como "duplicado".
- La salida no tenía campo `skipped`. Aun funcionando, el llamante no podía saber cuántas
  filas se descartaron: solo veía `inserted` sin referencia contra la que compararlo.
- Rompe la atomicidad del camino `error`, que manda una única sentencia: `skip` hacía
  hasta 500 viajes de ida y vuelta y podía quedarse a medias.

## Decisión

**Se elimina el modo `skip`.**

- `InsertInput.on_conflict` pasa a `Literal["error"]`. El esquema JSON que ve el modelo ya
  no ofrece `skip`, así que no puede pedirlo por lectura del contrato.
- Un `on_conflict="skip"` explícito (cliente antiguo, documentación antigua, memoria del
  modelo) **no** cae en un error genérico de validación: un validador `mode="before"`
  responde con el motivo y con la alternativa que sí funciona.
- `execute_insert` pierde el parámetro `on_conflict`, la función `_is_duplicate_row_error`
  y el bucle fila a fila. Queda una única sentencia parametrizada, como en el camino
  `error` (ver issue #133).

Se mantiene el campo `on_conflict` con un único valor legal, en lugar de borrarlo, para que
las llamadas que ya pasan el default explícito (`"error"`) sigan funcionando: con
`extra="forbid"`, quitar el campo convertiría esas llamadas en `unexpected argument`.

## Alternativas descartadas

### Implementar el `skip` real con un anti-join contra la PK declarada

`INSERT INTO t (cols) SELECT ?, ... FROM _v_dual WHERE NOT EXISTS (SELECT 1 FROM t WHERE
pk = ?)`. Descartada:

- **No hay clave en la que apoyarse.** La PK es declarativa y puede no existir: en la
  instancia de desarrollo consultada solo **una** tabla de todo el esquema tenía un
  `PRIMARY KEY` en `_v_table_constraint`. Y `nz_create_table`, la tool con la que se crean
  tablas desde este servidor, **no permite declarar** `PRIMARY KEY` ni `UNIQUE`, así que
  ninguna tabla creada por nz-mcp tendría clave contra la que hacer el anti-join.
- **Cambiaría la semántica sin decirlo.** Sin PK habría que definir el duplicado como
  "fila idéntica en las columnas enviadas", que no es lo que significa `on_conflict`, y
  que además se comporta raro con `NULL` (`c = ?` nunca es cierto con `NULL`).
- **Es otra funcionalidad, no un arreglo.** Un anti-join por fila son N viajes y N escaneos
  del destino; merece su propio issue, su propio contrato (¿qué columnas forman la clave?
  ¿se devuelve `skipped`?) y su propio ADR.
- **Ya se puede componer hoy, explícitamente.** `nz_insert_select` acepta un `SELECT`
  arbitrario validado por el guard, así que el usuario escribe su propio anti-join y decide
  él cuál es la clave:

  ```sql
  SELECT s.* FROM ORIGEN s
  WHERE NOT EXISTS (SELECT 1 FROM ESQUEMA.DESTINO t WHERE t.CLAVE = s.CLAVE)
  ```

  Es exactamente el anti-join del issue, con la ventaja de que la clave es una decisión
  visible del llamante y no una inferencia del servidor.

### Dejar `skip` y documentar que no hace nada

Descartada: el daño de esta opción es precisamente que el llamante no lee la letra
pequeña. Una opción que el usuario cree que le protege y no hace nada es peor que su
ausencia.

## Consecuencias

- **Cambio observable**: `nz_insert(on_conflict="skip")` pasa de "insertar todo y decir que
  fue bien" a fallar con un mensaje que explica el porqué y qué usar en su lugar.
- `nz_insert` vuelve a tener un solo camino de ejecución: una sentencia, atómica.
- La deduplicación sigue siendo posible vía `nz_insert_select` con `NOT EXISTS`.
- **Limitación de la verificación**: la no-imposición de `UNIQUE` / `PRIMARY KEY` en NPS
  está documentada por IBM y es consistente con lo observado en el catálogo de la
  instancia de desarrollo, pero **no** se ha ejecutado un `INSERT` duplicado contra el
  motor para comprobarlo en vivo (esta rama se limitó a lecturas). Es la única afirmación
  del ADR que se apoya en documentación y no en una prueba propia.
