# ADR 0018 — Acotar la salida de `nz_list_procedures` y `nz_get_procedure_ddl`

- **Fecha**: 2026-09-04
- **Estado**: aceptado
- **Decidido por**: Backend Developer (IA) + validación humana

## Contexto

Medición contra un Netezza real (2026-09-04, esquema con 714 procedimientos):

| Llamada | Tokens devueltos |
|---|---|
| `nz_list_procedures` de un esquema | 31.040 |
| `nz_get_procedure_ddl` del SP más grande | 147.039 |

Eran las dos únicas tools de lectura sin tope de tamaño. El resto respeta
`max_rows_default` (100) y el `RESPONSE_BYTES_CAP` de 100 KB de `catalog/execute.py`.
`nz_get_procedure_ddl` solo emitía un `warning` cuando el DDL superaba 100 KB y
devolvía el texto completo igualmente.

Una respuesta de 147 k tokens no encarece la sesión: la termina. Ya existían
`nz_get_procedure_size` (dimensionar sin traer el cuerpo) y
`nz_get_procedure_section` (leer por secciones o por rangos de hasta 500 líneas),
pero nada empujaba a la IA hacia ellas: la ruta barata era opcional y la cara era
el default.

## Decisión

Ambas tools acotan su salida por defecto y, al truncar, devuelven un `hint` i18n
con la ruta concreta para obtener el resto.

1. `nz_list_procedures` acepta `max_rows` opcional con el mismo default
   (`max_rows_default` del perfil, 100) y el mismo cap (`MAX_ROWS_CAP`, 1000) que
   el resto de tools de lectura. Al truncar devuelve `truncated=true` y un `hint`
   con el total real y las dos salidas accionables: acotar con `pattern` o subir
   `max_rows`.

2. `nz_get_procedure_ddl` aplica un tope duro `max_bytes` con **default 100 KB**
   (`RESPONSE_BYTES_CAP`) y **máximo 200 KB** (`PROC_TABLE_LOGIC_MAX_RESPONSE_BYTES`).
   Al truncar devuelve `truncated=true` y un `hint` que remite explícitamente a
   `nz_get_procedure_size` y a `nz_get_procedure_section` con `section='range'`,
   `from_line` y `to_line` concretos.

3. El corte se hace en frontera de línea, no de byte, y el `hint` expresa
   `from_line` en numeración de `PROCEDURESOURCE` (descontando las líneas de
   cabecera que añade la reconstrucción del `CREATE OR REPLACE PROCEDURE`), de
   modo que el parámetro sugerido sirve tal cual en la llamada siguiente.

### Por qué esos valores

- **Default 100 KB** = `RESPONSE_BYTES_CAP`. Es el cap de respuesta que la spec
  congelada de `AGENTS.md` ya fija para todo el servidor (~100 KB, unos 25 k tokens)
  y es exactamente el umbral en el que la tool **ya** emitía `warning`. Elegirlo
  significa que el comportamiento solo cambia para los SPs que el propio código ya
  declaraba demasiado grandes: no se introduce una clase nueva de truncado.
- **Máximo 200 KB** = `PROC_TABLE_LOGIC_MAX_RESPONSE_BYTES`, el techo de respuesta
  más alto ya aceptado en el repo (`nz_get_procedure_table_logic`, ADR 0011).
  Permite subir el tope de forma deliberada sin inventar un máximo nuevo.
- **Mínimo 1 KB** para el parámetro: por debajo el fragmento deja de ser útil.
- Coherencia con el tope de 500 líneas de `nz_get_procedure_section`: 100 KB de
  NZPLSQL son del orden de 1.500-2.000 líneas, es decir 3-4 llamadas de sección. El
  tope por defecto no vuelve absurda la paginación existente ni la duplica: da un
  primer bloque grande y el `hint` encadena el resto en bloques de 500 líneas.

## Alternativas consideradas

1. **Devolver todo y confiar en el `warning`** — es el estado actual y es justo lo
   que falla: el `warning` llega *después* de haber gastado los tokens.
2. **Rechazar con `RESPONSE_TOO_LARGE`** (patrón de `nz_get_procedure_table_logic`)
   — fuerza a la IA a reintentar con otra tool sin darle nada. Truncar más `hint`
   es estrictamente más informativo con el mismo coste acotado.
3. **Paginar `nz_get_procedure_ddl` con `offset`** — duplicaría
   `nz_get_procedure_section(section='range')`, que ya hace exactamente eso. Se
   prefiere empujar a la tool existente antes que crear una segunda forma de
   paginar el mismo texto.
4. **Añadir `offset` a `nz_list_procedures`** — el catálogo no garantiza un orden
   estable para paginar con seguridad; `pattern` ya permite acotar y es la salida
   correcta cuando un esquema tiene cientos de SPs.

## Consecuencias

- Positivas: ninguna llamada de lectura de procedimientos puede agotar la ventana
  de contexto por accidente; la IA recibe la ruta paginada en el propio `hint`;
  `size_bytes_raw` y `size_bytes_clean` siguen reportando el tamaño **completo**,
  así que el cliente sabe cuánto falta sin una llamada extra.
- Negativas / costes: **cambio observable** — `nz_get_procedure_ddl` puede devolver
  DDL truncado donde antes devolvía el texto entero. Un caller que necesite el DDL
  completo de un SP de más de 100 KB debe subir `max_bytes` (hasta 200 KB) o
  reconstruirlo con `nz_get_procedure_section`.
- Con `variant="clean"` y DDL por encima del tope, el presupuesto se gasta sobre el
  prefijo **raw** y los comentarios se eliminan después; el resultado puede quedar
  por debajo de `max_bytes`. Se prefiere una numeración de línea correcta sobre
  exprimir el último KB.
- Qué monitorizar: frecuencia de `truncated=true` en uso real. Si la mayoría de las
  llamadas truncan, el default es demasiado bajo para el parque de SPs y toca
  revisar el valor (no el mecanismo).
- Sin dependencias nuevas. Sin cambios en `sql_guard.py` ni en `auth.py`.

## Referencias

- Issue #165.
- `docs/adr/0011-tool-procedure-table-logic.md` (cap de 200 KB).
- `docs/adr/0010-tool-procedure-size.md` (tools de dimensionado y sección).
- `src/nz_mcp/catalog/execute.py` (`RESPONSE_BYTES_CAP`, patrón de `hint`).
