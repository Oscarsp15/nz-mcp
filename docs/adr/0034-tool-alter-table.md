# ADR 0034 — Añadir `nz_alter_table` para `ALTER TABLE` aditivos y `StatementKind.ALTER` al `sql_guard`

- **Fecha**: 2026-09-14
- **Estado**: aceptado
- **Decidido por**: Tech Lead (IA) + validación humana
- **Issue**: [#259](https://github.com/Oscarsp15/nz-mcp/issues/259)
- **Alcance**: si el MCP puede aplicar `ALTER TABLE` aditivos sobre una tabla existente y cómo lo valida el guard. No decide `CREATE TABLE` (`nz_create_table`), ni `DROP` (`nz_drop_table`), ni la compilación de SP/vistas (`nz_execute_ddl`).

## Contexto

Un pase de REN/batch empieza con `ALTER TABLE ... ADD COLUMN`: la tabla destino ya existe y solo hay que sumarle columnas (o ajustar su default) antes de que corra la carga. Hasta ahora ese primer paso no tenía tool.

El hueco era real, no cosmético:

- Netezza **no permite** `ADD COLUMN` dentro de un SP, así que el `ALTER` no puede esconderse en un procedimiento que el MCP compile o invoque.
- `nz_execute_ddl` solo acepta `procedure` / `view`; no hay ruta para DDL de tabla escrito por el usuario.
- Consecuencia operativa: el `ALTER` había que lanzarlo **a mano, fuera del MCP**, justo en el arranque del flujo que se quería automatizar. El resto del pase sí pasaba por las tools.

El issue [#259](https://github.com/Oscarsp15/nz-mcp/issues/259) pide cerrar ese hueco con la misma seguridad que el resto de las tools de escritura (dry_run por defecto, `confirm` bajo `admin`) y sin abrir una puerta de SQL crudo.

## Decisión

Añadimos `nz_alter_table(database, schema, table, add_columns?, set_defaults?, drop_defaults?, rename_columns?, dry_run=true, confirm=false)`, `mode="admin"`.

### Tool dedicada, no un modo de `nz_execute_ddl`

`ALTER TABLE` de tabla es una operación distinta de compilar un objeto de código. `nz_execute_ddl` resuelve texto DDL contra el perfil activo (su intent es "compilar lo que mantengo en git"); `nz_alter_table` aplica cambios incrementales a una tabla concreta con un esquema de input propio. Extender `nz_execute_ddl` con un `statement_type="alter_table"` lo convertiría en multi-tool y rompería la responsabilidad única (ADR 0006).

### Input estructurado, no SQL crudo

El caller declara la operación como datos, no como texto: `add_columns` (`{name, type, nullable, default}`), `set_defaults` (`{column, default}`), `drop_defaults` (`[column]`) y `rename_columns` (`{from, to}`). La tool construye cada sentencia con identificadores validados por el validador de catálogo y tipos validados por el mismo helper que usa `nz_create_table`. Es el patrón del repo para DDL de tabla; la superficie de inyección de un `ALTER` con SQL libre no se abre.

### Solo acciones aditivas/seguras

La allowlist es **cerrada**: `ADD COLUMN`, `SET DEFAULT`, `DROP DEFAULT` y `RENAME COLUMN`. Quedan **fuera** `DROP COLUMN` (destructivo) y `ALTER VIEW`. Cualquier acción no listada se rechaza antes de tocar la BD.

### Varias sentencias, una sola conexión

El caller puede combinar operaciones; la tool emite N sentencias y las ejecuta **secuencialmente en una única conexión**, en el orden canónico `ADD COLUMN` → `SET DEFAULT` → `DROP DEFAULT` → `RENAME COLUMN`. Cada sentencia pasa por `sql_guard.validate(mode="admin")` y por la guarda de entorno antes de la ejecución.

### Respuesta de solo metadatos

En ejecución real la tool **no devuelve el DDL** (`statements_to_execute: null`); devuelve `executed`, `statements_executed` y `duration_ms`. El preview vive en el dry-run, que es su razón de ser: con `dry_run=true` (default) se listan las sentencias sin ejecutar y sin abrir conexión.

### `sql_guard` gana `StatementKind.ALTER`, gated a admin

El guard reconoce `ALTER` como un kind DDL más (`_DDL_KINDS`), permitido **solo en `admin`**. Pero un `ALTER` válido no basta: `_assert_safe_alter` exige que el target sea `TABLE` (un `ALTER VIEW` se rechaza) y que **cada** acción pertenezca a `_ALTER_SAFE_ACTIONS` (`ColumnDef`, `AlterColumn`, `RenameColumn`). Es **default-deny**: `DROP COLUMN` parsea como `exp.Drop`, `RENAME TO` de tabla/vista como `exp.AlterRename`, `ADD CONSTRAINT` como `exp.AddConstraint`, etc., y todos caen fuera de la allowlist. Dentro de `AlterColumn`, `_assert_alter_column_is_default_only` acepta **solo** `SET DEFAULT` con expresión o `DROP DEFAULT`; los cambios de tipo y los cambios de `NOT NULL` se rechazan. Cualquier violación devuelve el código estable **`ALTER_ACTION_NOT_ALLOWED`**.

## Alternativas consideradas

1. **Extender `nz_execute_ddl` con `statement_type="alter_table"`** — rechazada: convierte la tool en multi-tool (dos intents distintos bajo un mismo nombre), contra el ADR 0006, y obligaría a meter SQL crudo de tabla por una puerta pensada para objetos de código.
2. **Tool que acepte SQL crudo (`nz_alter_table(sql)`)** — rechazada: la superficie de inyección es mayor y el patrón del repo para DDL de tabla es input estructurado (ver `nz_create_table`). Construir las sentencias desde datos validados permite además la allowlist por acción en el guard.
3. **Permitir `DROP COLUMN`** — rechazada: es destructivo y queda fuera del alcance de este issue. Si se necesita, va con su propia decisión (y probablemente su propia guarda de confirmación).
4. **Reutilizar la guarda de entorno de compilación** — no aplica: aquí no se compila código que apunte a `PROD_`; se ejecuta DDL contra la tabla nombrada. Se invoca `assert_env_safe` sobre cada sentencia para mantener la misma política, pero el flujo es de ejecución, no de compilación.

## Consecuencias

### Positivas

- El arranque del pase de REN/batch deja de requerir un `ALTER` manual fuera del MCP: el flujo queda dentro de las tools y con dry-run por defecto.
- El guard gana una allowlist de `ALTER` explícita y default-deny, con código de rechazo estable (`ALTER_ACTION_NOT_ALLOWED`), en vez de permitir `ALTER` en bloque.
- La respuesta de ejecución es de solo metadatos, así que aplicar N sentencias no arrastra el DDL completo al contexto del caller.

### Negativas y costes

- Superficie nueva en `sql_guard.py` (kind `ALTER`, `_assert_safe_alter`, `_assert_alter_column_is_default_only`) y un módulo de catálogo/tool nuevos; cobertura al 100 % en el código del guard.
- La allowlist es conservadora: una acción legítima no prevista hoy se rechaza hasta añadirla con su ADR.

### Limitación conocida (aplicación parcial)

Netezza **auto-commitea DDL**: cada sentencia queda aplicada al terminar. Si una de las N sentencias falla, **las anteriores ya se aplicaron** y la respuesta no señala aplicación parcial (no hay campo `statements_applied`). El caller que necesite certeza debe verificar el catálogo (p. ej. `nz_describe_table`) tras un fallo. Como caso concreto, un `ADD COLUMN ... NOT NULL` **sin `DEFAULT`** sobre una tabla con filas lo rechaza el servidor en el momento de ejecutar; en dry-run no se detecta porque no hay conexión.

### Qué monitorizar

- Fallos en mitad de un lote multi-sentencia: si se vuelven frecuentes, evaluar un campo de resultado que exponga cuántas sentencias se aplicaron antes del fallo.
- Peticiones de `DROP COLUMN`: hoy fuera de alcance; si llegan, abrir decisión propia.

## Aprobación humana

Pendiente (@Oscarsp15). El cambio toca `sql_guard` (archivo de alta sensibilidad), así que requiere validación humana explícita antes del merge.

## Referencias

- Issue [#259](https://github.com/Oscarsp15/nz-mcp/issues/259) — spec y criterios de aceptación.
- ADR 0006 — Tools con responsabilidad única (justifica una tool dedicada).
- ADR 0014 — `nz_execute_ddl` (precedente de DDL de código y guarda de entorno `PROD_`).
- ADR 0024 — El SQL que se ejecuta es el que validó el guard.
- `docs/architecture/tools-contract.md` § 36 — contrato de la tool.
- `docs/architecture/security-model.md` — barreras defensivas y regla "no relajar estrictez sin ADR".
