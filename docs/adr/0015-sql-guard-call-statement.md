# 15. `CALL` como operación EXECUTE en `sql_guard`, gated a admin

Date: 2026-07-09

## Status

Accepted

## Context

`nz-mcp` podía leer, clonar y (con #147) compilar procedimientos, pero no **ejecutarlos**. El issue [#148](https://github.com/Oscarsp15/nz-mcp/issues/148) pide una tool `nz_call_procedure` que haga `CALL schema.proc(args)` y devuelva el return code + los mensajes `NOTICE`/`RAISE` del SP.

`CALL` no encaja en las clases de statement que el `sql_guard` ya maneja (`SELECT`/DML/DDL). Es una operación **EXECUTE**: ejecuta código arbitrario del procedimiento (que a su vez puede hacer DML/DDL). Además, `sqlglot` **no** parsea `CALL`: cae a un `Command` genérico y emite un warning de "unsupported syntax" a stderr (problemático en transporte MCP stdio). Introducir un `kind` nuevo en la barrera de seguridad requiere ADR y no debe relajar la estrictez de ningún kind existente (regla de `security-model.md`).

## Decision

Añadimos `StatementKind.CALL` y lo permitimos **solo en modo `admin`**, mismo tier que la DDL.

### Ruta dedicada de regex (no vía `sqlglot`)

Igual que las rutas ya existentes para `CREATE ... LANGUAGE NZPLSQL AS` y `DROP TABLE … IF EXISTS` (formas que `sqlglot` no parsea), interceptamos `CALL` con un patrón dedicado **antes** de llamar a `sqlglot`:

```
^\s*CALL\s+<sch>\.<proc>\s*\(\s*<args>\)\s*$      con args ∈ [?\s,]*
```

- **Solo acepta placeholders `?` como argumentos.** Un argumento literal (`CALL P(1)`, `CALL P('x')`) **no** matchea el intercept, cae a `sqlglot` → `Command` → `UNKNOWN` → rechazado. Esto **fuerza la parametrización** (regla inviolable: "sin SQL concatenado"): los valores viajan como bind params del driver, nunca inline.
- Los identificadores `<sch>` / `<proc>` se validan con `validate_catalog_identifier` (mismas reglas que el catálogo).
- Evita el warning de `sqlglot` a stderr para el camino normal de la tool (el SQL siempre matchea el intercept).
- El apilamiento (`CALL P(); DROP TABLE t`) no matchea (tiene `;`) → cae a `sqlglot` → `STACKED_NOT_ALLOWED`.

### Gate a admin

`CALL` ejecuta código arbitrario del SP; se rechaza en `read`/`write` con `STATEMENT_NOT_ALLOWED` (código estable ya existente) y se permite solo en `admin`. No se toca ninguna regla de los kinds previos.

### Mitigaciones de riesgo (defensa en capas)

`CALL` es potente (el SP puede hacer cualquier cosa que permitan los grants del usuario de servicio). Se acota con:
1. **`admin`** requerido (barrera 1 tool + barrera 2 guard).
2. **`dry_run` por defecto** en la tool: devuelve el `call_sql` sin ejecutar; `confirm=true` obligatorio para ejecutar.
3. **`assert_env_safe`** (ADR 0014): un `CALL` a un SP `PROD_*` desde un perfil no productivo se rechaza.
4. **Args parametrizados** (bind del driver), nunca concatenados.
5. **Barrera 3**: los grants del usuario Netezza siguen aplicando.

## Alternatives considered

1. **Clasificar `CALL` vía el `Command` de `sqlglot`** — rechazada: emite un warning a stderr en cada llamada (rompe UIs de cliente que renderizan stderr, `security-model.md`) y acepta argumentos literales (no fuerza parametrización).
2. **Permitir `CALL` también en `write`** — rechazada: `CALL` ejecuta código con potencial DDL/DROP dentro del SP; el tier correcto es `admin`, igual que la DDL.
3. **Aceptar argumentos literales en el intercept** — rechazada: viola la regla de parametrización y abre superficie de inyección.
4. **No pasar el `CALL` por `sql_guard`** (construirlo y ejecutarlo directo, ya que la tool controla el texto) — rechazada: rompe la invariante "todo SQL ejecutable pasa por `sql_guard`" (barrera 2).

## Consequences

### Positivas
- `nz_call_procedure` puede ejecutar SPs y capturar `NOTICE`/`RAISE` (witness E2E: `DBO.NZMCP_SMOKE_CALL(5)` en `nzsaas` devolvió `return_value=50` y `messages=['nz-mcp: recibido 5', 'nz-mcp: paso 2 ok']`).
- El intercept fuerza args parametrizados: propiedad de seguridad fuerte y auditable.
- Cero ruido de `sqlglot` en stderr para el camino normal.
- Cobertura del código nuevo de `sql_guard.py` con tests adversariales (literal rechazado, stacked, read/write rechazados).

### Costes / negativas
- Un kind nuevo en la barrera de seguridad → más superficie que mantener. Mitigación: ruta dedicada pequeña y con tests adversariales; no se relaja ninguna regla previa.
- Un `CALL` con args literales (algún caller futuro) sería rechazado como `UNKNOWN`. Es intencional; si se necesitara, el fix sería añadir soporte de literales *parametrizándolos*, no aceptándolos inline.

### Qué monitorizar
- Si aparece un caso legítimo de `CALL` que el intercept rechace por forma (p. ej. args nombrados), evaluar extender el patrón manteniendo la parametrización.

## References

- Issue #148 (GitHub) — spec y criterios de aceptación.
- ADR 0014 — `nz_execute_ddl` + `assert_env_safe` (reutilizada aquí).
- `docs/architecture/security-model.md` — barreras, matriz por modo, "no relajar estrictez sin ADR".
- `docs/actions/modify-sql-guard.md` — playbook de cambios al guard.
- `docs/architecture/tools-contract.md` § 33 — contrato de `nz_call_procedure`.
