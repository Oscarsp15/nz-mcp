# Modelo de Seguridad

> **Público objetivo**: agente IA asumiendo el rol de Security Engineer senior.
> Antes de modificar `sql_guard.py`, `auth.py`, `connection.py` o cualquier flujo de credenciales, lee este documento entero.

## Threat model resumido

| Amenaza | Mitigación principal |
|---|---|
| IA ejecuta SQL destructivo por error o prompt injection | `sql_guard` + tools con responsabilidad única + modos de perfil |
| Credenciales de Netezza filtradas en logs o repo | `keyring` OS-native + sanitizer + test que falla si hay password en output |
| SQL injection en queries construidas dinámicamente | Parámetros del driver (nunca concatenación de strings) |
| Denegación de servicio accidental (full table scan en billones de filas) | `LIMIT` forzado + `timeout_s` + cap de bytes en respuesta |
| Exfiltración de datos masiva vía prompt injection | Cap bytes + logging estructurado + modo por perfil |
| Escalación de privilegios por la IA | `switch_profile` jamás eleva `mode`; el humano edita `profiles.toml` |
| Supply chain (dependencia comprometida) | Deps pineadas, Dependabot, review de ADR para cada dep nueva |

## Las 3 barreras defensivas

```
┌─────────────────────────────────────────────────────────┐
│ Barrera 1: Tool de responsabilidad única                │
│   nz_query_select solo acepta SELECT                    │
│   nz_update requiere WHERE y dry_run por defecto        │
│   nz_drop_table requiere confirm=true explícito         │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ Barrera 2: sql_guard                                    │
│   Parsea con sqlglot, clasifica el statement            │
│   Rechaza según modo del perfil (read/write/admin)      │
│   Rechaza stacked statements (; múltiples)              │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ Barrera 3: Permisos del usuario Netezza                 │
│   El usuario de servicio solo tiene los grants mínimos  │
│   Aunque la IA burle barreras 1 y 2, la BD rechaza      │
└─────────────────────────────────────────────────────────┘
```

**Ninguna barrera es suficiente por sí sola.** Si una se rompe, las otras deben sostener. Jamás eliminar una barrera por "redundancia".

## sql_guard: especificación

### Responsabilidad

`sql_guard.validate(sql: str, mode: PermissionMode) -> ParsedStatement` es la única puerta legal a `connection.execute()`.

### Implementación

- Librería: **`sqlglot`** con dialect `postgres` (Netezza usa SQL muy cercano a Postgres).
- Retorna un `ParsedStatement` tipado: `{ kind: Enum, tables: list, has_where: bool, raw: str }`.
- Lanza `GuardRejectedError` con `code` y `hint` i18n.

#### Procedimientos `CREATE ... LANGUAGE NZPLSQL AS`

`sqlglot` no clasifica cuerpos NZPLSQL reales (`DECLARE`, `BEGIN`/`END`, cursores, etc.). Para sentencias que contienen el marcador `LANGUAGE NZPLSQL AS`, el guard **no** intenta parsear el cuerpo: valida la cabecera con regex (firma `schema.procedimiento`, sin `;` en la cabecera) y los identificadores con las mismas reglas que el catálogo. El cuerpo se trata como **opaco**; no es texto libre arbitrario del LLM en los flujos soportados (p. ej. clonado desde DDL ya obtenido del catálogo del propio servidor). El riesgo de inyección se concentra en la cabecera; ahí se exige `admin` y se rechazan cabeceras malformadas o apiladas.

#### ``DROP TABLE`` con ``IF EXISTS`` en sufijo (Netezza)

NPS 11.x usa ``DROP TABLE esquema.tabla IF EXISTS``, no el orden ANSI ``DROP TABLE IF EXISTS esquema.tabla``. ``sqlglot`` no parsea la forma sufijo; el guard la reconoce con un patrón dedicado (identificadores validados, sin apilamiento) y la clasifica como ``DROP`` en modo ``admin``, igual que el resto de DDL administrativo.

### Reglas por modo

| Statement kind | `read` | `write` | `admin` |
|---|---|---|---|
| `SELECT`, `WITH` (solo SELECT), `EXPLAIN`, `SHOW` | ✅ | ✅ | ✅ |
| `INSERT` | ❌ | ✅ | ✅ |
| `UPDATE` (con `WHERE`) | ❌ | ✅ | ✅ |
| `UPDATE` sin `WHERE` | ❌ | ❌ | ❌ |
| `DELETE` (con `WHERE`) | ❌ | ✅ | ✅ |
| `DELETE` sin `WHERE` | ❌ | ❌ | ❌ |
| `CREATE TABLE` | ❌ | ❌ | ✅ |
| `TRUNCATE` | ❌ | ❌ | ✅ |
| `DROP TABLE` | ❌ | ❌ | ✅ |
| `DROP DATABASE`, `DROP USER`, `GRANT`, `REVOKE` | ❌ | ❌ | ❌ |
| Stacked (`; ...;`) | ❌ | ❌ | ❌ |
| Comentarios `--` o `/* */` con statements dentro | sanear antes de parsear | | |
| Cualquier statement no reconocido | ❌ | ❌ | ❌ |

### Casos adversariales que el guard DEBE bloquear

Los tests en `tests/unit/test_sql_guard_adversarial.py` deben incluir (al menos):

```
SELECT 1; DROP TABLE t;
SELECT /*; DROP TABLE t; */ 1;
SELECT 1 -- ; DROP TABLE t
WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x;
UPDATE t SET a=1;                        -- sin WHERE
DELETE FROM t;                            -- sin WHERE
SELECT * FROM t; SELECT * FROM t2;        -- stacked
BEGIN; DELETE FROM t; COMMIT;             -- transacción con DML
```

Cobertura obligatoria de `sql_guard.py`: **100 %**.

## auth.py: credenciales

### Flujo

1. `nz-mcp init` lanza wizard interactivo → pide host, port, database, user, password, mode.
2. Password va directo a `keyring.set_password("nz-mcp", f"profile:{name}", password)`.
3. Metadatos no secretos van a `~/.nz-mcp/profiles.toml`:

```toml
[profiles.prod]
host = "nz-prod.example.com"
port = 5480
database = "DEV"
user = "svc_claude"
mode = "read"
max_rows_default = 100
timeout_s_default = 30

[profiles.dev]
host = "nz-dev.example.com"
port = 5480
database = "DEV"
user = "svc_claude"
mode = "write"
```

4. Al conectar: `password = keyring.get_password("nz-mcp", f"profile:{profile_name}")`.

### Reglas

- `profiles.toml` **nunca** contiene password.
- Test unitario: parsear `profiles.toml` y afirmar que ninguna clave tenga nombre conteniendo `pass`, `pwd`, `secret`, `token`, `key`.
- Sanitizer de logs: regex que borra valores tras `password=`, `pwd=`, etc., más comparación contra el password conocido del perfil activo (si aparece en log → panic).
- Permisos de archivo: `profiles.toml` se crea con `0600` en Unix; en Windows, con ACL restringida al usuario actual.

### Qué NO usar (anti-patrones)

- ❌ `.env` plano con password.
- ❌ Password como arg CLI (`--password xxx`).
- ❌ Password en variables de entorno del cliente MCP (aparece en `ps`, logs del cliente).
- ❌ Base64 "por seguridad" — es ofuscación, no cifrado.
- ❌ Generar un keyfile propio en vez de usar `keyring`.

## Streaming y límites

| Límite | Default | Cap duro | Justificación |
|---|---|---|---|
| `max_rows` | 100 | 1000 | Proteger tokens del LLM |
| Tamaño respuesta | — | 100 KB | ≈25k tokens, evita cortar contexto |
| Timeout query | 30 s | 300 s | Proteger warehouse |
| Conexiones concurrentes | 1 | 4 | MCP stdio es single-client |

`connection.py` debe usar cursor streaming y **parar de iterar** al llegar al primero de estos límites.

## Logging

- Formato: **JSON line** (`jsonl`), una línea por evento.
- Ubicación: `~/.nz-mcp/logs/queries.jsonl` (rotación por tamaño, 10 MB, 5 archivos).
- Campos: `ts`, `profile`, `tool`, `duration_ms`, `rows`, `truncated`, `sql_hash` (SHA-256 corto), `error_code` (si aplica).
- En `DEBUG`: se añade `sql` completo. Nunca en `INFO` o superior.
- **Nunca**: resultados de queries, credenciales, contenido de `set`/`where` de INSERT/UPDATE/DELETE.

El sanitizer vive en `i18n.py`-adjacent o en un helper `logging_utils.py`; debe tener test que meta un password conocido en un dict y verifique que el log output no lo contiene.

## Cross-database identifier interpolation

Las queries de catálogo cross-database usan el sentinel interno `<BD>..` y se renderizan
en runtime antes del `cursor.execute()`. Como `nzpy` no parametriza identificadores
(solo valores), el nombre de base de datos se valida con regex estricta:

- Patrón obligatorio: `^[A-Z][A-Z0-9_]{0,127}$`
- Normalización previa permitida: `database.strip().upper()`
- Si falla, lanzar `InvalidInputError(code="INVALID_DATABASE_NAME")`
- El helper debe fallar si queda cualquier `<BD>` sin reemplazar en el SQL final

Invariante de seguridad: no concatenar identifiers sin pasar por este validador.
Relajar este patrón requiere ADR y aprobación humana explícita.

## Catalog overrides por perfil

Los perfiles pueden declarar `catalog_overrides` en `profiles.toml` para reemplazar
queries de catálogo por `query_id`.

Riesgo explícito:

- El SQL de `catalog_overrides` se ejecuta tal cual.
- Estas queries de catálogo no pasan por `sql_guard`.
- Se asume que el humano controla su propio `profiles.toml` y sus permisos.

Controles implementados:

- Solo se aceptan `query_id` existentes en `CATALOG_QUERY_MAP`.
- Overrides con `query_id` desconocido fallan con `InvalidProfileError`.
- Si un override incluye `<BD>..` en una query no cross-db, se emite warning.

## Checklist para Security Engineer antes de commit

- [ ] Todo SQL ejecutable pasa por `sql_guard.validate()` en el camino.
- [ ] Cualquier string de usuario que llegue a SQL va parametrizado, no concatenado.
- [ ] Ninguna rama nueva de `sql_guard` reduce estrictez sin ADR.
- [ ] Tests adversariales de la lista cubren los casos añadidos.
- [ ] `grep -i "password\|secret\|token"` en mi diff no muestra nada sospechoso.
- [ ] Si añadí un logger, el sanitizer cubre el caso.
- [ ] `mypy --strict` limpio.
- [ ] Documenté la decisión en un ADR si cambié el modelo.
