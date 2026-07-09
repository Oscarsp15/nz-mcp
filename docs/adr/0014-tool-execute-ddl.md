# 14. `nz_execute_ddl` compila procedimientos/vistas y guarda de entorno `PROD_`

Date: 2026-07-09

## Status

Accepted

## Context

`nz-mcp` podía **leer** y **clonar** procedimientos (`nz_get_procedure_*`, `nz_clone_procedure`) pero no **compilar DDL de código escrita por el usuario**: un `CREATE OR REPLACE PROCEDURE` completo mantenido en un archivo `.sql`, o una vista. El clonado reconstruye el DDL desde el catálogo del propio servidor (fuente confiable); no cubre el flujo de "mantengo el SP en git y lo compilo contra el entorno activo" (incluida la nube `nzsaas`).

El issue [#147](https://github.com/Oscarsp15/nz-mcp/issues/147) pide una tool `nz_execute_ddl` con la misma seguridad que las tools de escritura existentes (dry_run por defecto, confirm bajo `admin`) y una **guarda de entorno** nueva: que una sesión de desarrollo no pueda compilar código que apunta a producción.

## Decision

Añadimos `nz_execute_ddl(sql? | input_path?, statement_type ∈ {procedure, view}, dry_run=true, confirm=false)`, `mode="admin"`.

### Una tool con `statement_type`, no dos tools

`procedure` y `view` comparten exactamente el mismo flujo (resolver texto → validar forma → `sql_guard` → guarda de entorno → dry_run/confirm → ejecutar). La única razón de fallo es "compilar un objeto de código". Separarlas en `nz_execute_procedure_ddl` / `nz_execute_view_ddl` duplicaría el flujo sin ganar claridad. `statement_type` no es un parámetro "operación" (anti-patrón de ADR 0006): no cambia la operación, solo declara la forma esperada del DDL para validarla contra el texto (procedure ⇒ marcador `LANGUAGE NZPLSQL AS`; view ⇒ `CREATE [OR REPLACE] VIEW`). Un desajuste declara `INVALID_INPUT` antes de tocar la BD.

### Reutiliza la ruta NZPLSQL del `sql_guard`, no la relaja

El cuerpo NZPLSQL sigue siendo **opaco** para `sqlglot`; se valida por la ruta de cabecera existente (`_validate_nzplsql_procedure`, exige `admin`, rechaza cabeceras apiladas/malformadas). Las vistas caen en la ruta `sqlglot` estándar → kind `CREATE`, permitido solo en `admin`. No se añade ninguna rama que **reduzca** estrictez (regla del modelo de seguridad).

### Guarda de entorno `assert_env_safe` (compartida)

`sql_guard.assert_env_safe(sql, active_database)`: si `active_database` **no** empieza con `PROD_`, cualquier identificador `PROD_*` (regex `\bPROD_[A-Za-z0-9_]*\b`, case-insensitive) en el SQL → `GuardRejectedError(code="PROD_REF_IN_NONPROD")`. Coincide con el naming real del proyecto (`DESA_MODELOS` vs `PROD_ANALITICA`).

- **Por qué prefijo de database y no un campo `environment` nuevo**: cero configuración, funciona con los perfiles existentes, y el prefijo `PROD_` ya es la convención operativa. Decisión tomada con el owner.
- **Conservador a propósito (falla cerrado)**: el escaneo es textual; un literal de cadena que contenga `PROD_` también dispara. Preferimos un falso positivo (rechazo) a compilar accidentalmente contra producción. Si aparece fricción real, se abre follow-up para excluir literales/comentarios.
- Vive en `sql_guard.py` (barrera 2) porque es una política sobre el contenido SQL; se reutiliza desde `nz_call_procedure` (issue #148). Cobertura del nuevo código en `sql_guard.py`: 100% (tests adversariales en `test_sql_guard_env.py`).

### `input_path` con lector seguro aislado

`input_path` se lee con `io/safe_read.py::read_input_ddl`, que reutiliza la misma `_validate_path_policy` de `safe_write.py` (absoluto, sin `..`, sin `~`, sin control chars), exige que el archivo exista y aplica un cap de 1 MiB (el DDL es código, no un dump). Aislado y con cobertura 100%, espejo de `safe_write.py`.

### Ejecuta en la BD del perfil activo

No hay parámetro `database` cross-DB: `nz_execute_ddl` compila contra la BD del perfil activo (patrón de las tools de escritura), evitando ambigüedad de "compilo aquí pero apunto allá".

## Alternatives considered

1. **Dos tools separadas (procedure/view)** — rechazada: duplican el flujo; el intent es único.
2. **Extender `nz_clone_procedure`** — rechazada: clona desde catálogo (fuente confiable); compilar texto arbitrario del usuario es otra fuente de riesgo y otro intent.
3. **Campo `environment` en `profiles.toml`** — rechazada por ahora: más configuración que mantener (incluido el perfil de nube) sin beneficio vs. el prefijo `PROD_` que ya usan. Sería aditivo si se necesitara.
4. **Guarda de entorno en la capa de tool, no en `sql_guard`** — rechazada: la política sobre contenido SQL pertenece a la barrera 2 y debe reutilizarse desde varias tools sin duplicarla.
5. **Excluir literales/comentarios del escaneo `PROD_`** — diferido: añade complejidad; el comportamiento fail-closed es aceptable como v1.

## Consequences

### Positivas
- Flujo "SP/vista en archivo → compilar contra el entorno activo" cubierto, incluida la nube.
- Guarda de entorno reutilizable protege a todas las tools de escritura/ejecución que la invoquen.
- `safe_read.py` queda como módulo aislado reusable, espejo de `safe_write.py`.

### Costes / negativas
- La guarda `PROD_` es conservadora: puede rechazar SQL legítimo con la subcadena `PROD_` en un literal. Mitigación: documentado; follow-up si molesta.
- `sql_guard.py` gana una función pública nueva (`assert_env_safe`) — cubierta al 100% y sin relajar reglas.

### Qué monitorizar
- Reportes de falsos positivos de la guarda `PROD_` en literales/comentarios (≥3 ⇒ excluir strings del escaneo).
- Si aparece necesidad de compilar cross-DB explícito, evaluar un parámetro `database` con su propia guarda.

## References

- Issue #147 (GitHub) — spec y criterios de aceptación.
- ADR 0006 — Tools de responsabilidad única (justifica una tool con `statement_type`, no un parámetro "operación").
- ADR 0013 — `safe_write.py` (precedente de política de paths aislada, reutilizada por `safe_read.py`).
- `docs/architecture/security-model.md` — barreras defensivas y regla "no relajar estrictez sin ADR".
- `docs/architecture/tools-contract.md` § 32 — contrato de la tool.
