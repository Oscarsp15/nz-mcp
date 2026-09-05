# ADR 0024 — El SQL que se ejecuta es el que validó el guard, nunca uno re-serializado

- Estado: aceptado
- Fecha: 2026-09-05
- Issue: [#137](https://github.com/Oscarsp15/nz-mcp/issues/137)

## Contexto

`nz_query_select` y `nz_get_table_sample` acotan el resultado llamando a
`inject_limit(parsed.raw, max_rows)`. La implementación original reparseaba el SQL con
`sqlglot`, añadía el `LIMIT` sobre el árbol y devolvía `limited.sql(dialect="postgres")`.

Es decir: el texto que llegaba a Netezza **no** era el que el usuario escribió ni el que
`sql_guard` validó, sino lo que `sqlglot` reimprime en dialecto PostgreSQL. Netezza no es
PostgreSQL, y `sqlglot` no tiene dialecto Netezza.

Reescrituras observadas con `sqlglot` 30.18.0 (verificadas contra NPS real, perfil
`uaipscrea1` / `DESA_MOTOR`, en solo lectura):

| El usuario escribe | Netezza recibe |
|---|---|
| `NVL(a, b)` | `COALESCE(a, b)` |
| `DECODE(e, 1, 'A', 'Z')` | `CASE WHEN e = 1 THEN 'A' ELSE 'Z' END` |
| `NVL2(a, b, c)` | `CASE WHEN NOT a IS NULL THEN b ELSE c END` |
| `STRPOS(s, x)` / `INSTR(s, x)` | `POSITION(x IN s)` |
| `LAST_DAY(f)` | `CAST(DATE_TRUNC('MONTH', f) + INTERVAL '1 MONTH' - INTERVAL '1 DAY' AS DATE)` |
| `DATE_PART('year', f)` | `EXTRACT(YEAR FROM f)` |
| `SUBSTR(s, 2, 3)` | `SUBSTRING(s FROM 2 FOR 3)` |
| `regexp_like(s, p)` | `s ~ p` |
| `ORDER BY c NULLS LAST` (ASC) | `ORDER BY c` |
| `LIMIT 3` con `max_rows=100` | `LIMIT 100` |

Las nueve primeras hoy dan el mismo resultado en NPS 11.2 —Netezza es bastante compatible
con PostgreSQL— pero eso es suerte, no una garantía: dependen de la versión de `sqlglot`,
que cambia sus reglas de reescritura entre releases, y del catálogo de funciones de la
instancia. La décima es un fallo observable **ya**: `SELECT TABLENAME FROM _V_TABLE LIMIT 3`
devolvía 100 filas, porque el literal del `LIMIT` se leía de `Limit.this` cuando `sqlglot`
lo guarda en `Limit.expression`; `current` siempre valía `None` y el `LIMIT` del usuario se
sustituía por `max_rows`.

El problema de fondo es de modelo de seguridad, no de compatibilidad: la barrera 2
(`sql_guard`) valida un texto y la capa de ejecución manda otro. Cualquier razonamiento
sobre lo que el guard aprueba deja de aplicar al texto que corre.

## Decisión

**El texto que llega a `cursor.execute()` es el que validó `sql_guard`.** `inject_limit`
deja de re-serializar el árbol:

1. `sqlglot` solo **lee**: `parse_one` sigue confirmando que la sentencia es `SELECT` o
   `UNION`, y el tokenizador localiza el `LIMIT` de nivel superior (profundidad de
   paréntesis 0; los `LIMIT` de subconsultas y CTE no se tocan).
2. Sin `LIMIT` propio → se **añade** ` LIMIT n` al final del texto original, en una línea
   nueva (un comentario `--` final se tragaría la cláusula en la misma línea).
3. Con `LIMIT` propio menor o igual que `max_rows` → el SQL se devuelve **intacto**.
4. Con `LIMIT` propio mayor, o `LIMIT ALL` → se reescribe **solo el literal**, usando los
   offsets del token en el texto original. `OFFSET` y el resto de la sentencia sobreviven.
5. Un `;` final se recorta antes de anexar (el guard lo acepta y Netezza no lo necesita).

## Alternativas descartadas

- **Añadir un dialecto Netezza a `sqlglot` (o depender de uno de terceros)**: sería una
  dependencia nueva y, sobre todo, seguiría reimprimiendo el SQL. Un round-trip perfecto
  para SQL arbitrario no es un objetivo alcanzable ni necesario aquí.
- **Envolver la query (`SELECT * FROM (<sql>) t LIMIT n`)**: preserva el texto pero cambia
  la sentencia (proyecciones duplicadas, `ORDER BY` dentro de una tabla derivada) y hace
  el SQL menos legible en los logs de Netezza.
- **No inyectar `LIMIT` y confiar solo en el corte por `max_rows` del streaming**: el corte
  cliente ya existe, pero perder el `LIMIT` quita a Netezza la única pista para no
  materializar el resultado completo.

## Consecuencias

- Los `hint` y `truncated` no cambian: el corte por filas, bytes y timeout sigue en
  `execute_select`.
- `nz_query_select` respeta un `LIMIT` del usuario más restrictivo que `max_rows`
  (cambio observable).
- La salida de `inject_limit` deja de estar normalizada; los tests comparan contra el texto
  original más la cláusula, no contra una forma canónica.
- `sqlglot` sigue siendo la única dependencia de parseo. No se añade ninguna.
