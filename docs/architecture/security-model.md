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

`sqlglot` no clasifica cuerpos NZPLSQL reales (`DECLARE`, `BEGIN`/`END`, cursores, etc.). Para sentencias que contienen el marcador `LANGUAGE NZPLSQL AS`, el guard **no** intenta parsear el cuerpo: valida la cabecera con regex (firma `schema.procedimiento`, lista de parámetros con **paréntesis anidados de un nivel** para tipos como `VARCHAR(n)` / `NUMERIC(p,s)`, sin `;` en la cabecera) y los identificadores con las mismas reglas que el catálogo. El cuerpo se trata como **opaco**; no es texto libre arbitrario del LLM en los flujos soportados (p. ej. clonado desde DDL ya obtenido del catálogo del propio servidor). El riesgo de inyección se concentra en la cabecera; ahí se exige `admin` y se rechazan cabeceras malformadas o apiladas.

#### ``DROP TABLE`` con ``IF EXISTS`` en sufijo (Netezza)

NPS 11.x usa ``DROP TABLE esquema.tabla IF EXISTS``, no el orden ANSI ``DROP TABLE IF EXISTS esquema.tabla``. ``sqlglot`` no parsea la forma sufijo; el guard la reconoce con un patrón dedicado (identificadores validados, sin apilamiento) y la clasifica como ``DROP`` en modo ``admin``, igual que el resto de DDL administrativo.

#### Predicados `WHERE` siempre verdaderos (`UPDATE` / `DELETE`)

Exigir la **presencia** de `WHERE` no protege de nada: `DELETE FROM T WHERE 1=1` la
tiene y borra la tabla entera. El guard pliega el predicado sobre el AST (constant
folding propio, sin regex) y rechaza con `WHERE_ALWAYS_TRUE` las formas triviales:
literales booleanos, literal numérico como predicado, comparaciones entre dos
literales del mismo tipo, `NOT` de una constante decidible, `AND`/`OR` con lógica
ternaria y `col = col`. El llamante puede seguir afectando a toda la tabla, pero
**solo declarando la intención** con `confirm_full_table=true` (parámetro de
`nz_update` / `nz_delete`), que queda registrado en los argumentos de la llamada y
no eleva privilegios ni exime del `WHERE`.

Decidir tautología en el caso general es **indecidible**: no se detectan constantes
tras funciones (`ABS(1)=1`), predicados dependientes de datos (`id > -2147483648`,
`name LIKE '%'`), comparaciones entre tipos distintos, aritmética ni subconsultas.
Alcance exacto y límites en
[`../adr/0020-sql-guard-tautological-where.md`](../adr/0020-sql-guard-tautological-where.md).

#### ``CALL`` (ejecución de procedimientos)

``sqlglot`` no parsea ``CALL`` (cae a un ``Command`` genérico y emite warning a stderr). El guard lo intercepta con un patrón dedicado que **solo acepta placeholders ``?`` como argumentos**: ``CALL esquema.proc(?, …)``. Un argumento literal (``CALL P(1)``) **no** matchea y se rechaza como ``UNKNOWN_STATEMENT``, forzando la parametrización vía bind params del driver. Es una operación **EXECUTE** (el SP ejecuta código arbitrario) y se gatea a ``admin``, mismo tier que la DDL. Ver [`../adr/0015-sql-guard-call-statement.md`](../adr/0015-sql-guard-call-statement.md).

### Reglas por modo

| Statement kind | `read` | `write` | `admin` |
|---|---|---|---|
| `SELECT`, `WITH` (solo SELECT), `UNION` / `UNION ALL` (solo ramas `SELECT`), `EXPLAIN`, `SHOW` | ✅ | ✅ | ✅ |
| `INSERT` | ❌ | ✅ | ✅ |
| `UPDATE` (con `WHERE` selectivo) | ❌ | ✅ | ✅ |
| `UPDATE` sin `WHERE` | ❌ | ❌ | ❌ |
| `DELETE` (con `WHERE` selectivo) | ❌ | ✅ | ✅ |
| `DELETE` sin `WHERE` | ❌ | ❌ | ❌ |
| `UPDATE` / `DELETE` con `WHERE` siempre verdadero (`1=1`, `TRUE`, `id=5 OR 1=1`, …) | ❌ | ❌ | ❌ |
| Ídem con `confirm_full_table=true` (intención declarada por el llamante) | ❌ | ✅ | ✅ |
| `CREATE TABLE` | ❌ | ❌ | ✅ |
| `TRUNCATE` | ❌ | ❌ | ✅ |
| `DROP TABLE` | ❌ | ❌ | ✅ |
| `CALL schema.proc(?, …)` (EXECUTE; solo placeholders) | ❌ | ❌ | ✅ |
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
DELETE FROM t WHERE 1=1;                  -- WHERE tautológico
UPDATE t SET a=1 WHERE TRUE;              -- idem
DELETE FROM t WHERE id=5 OR 1=1;          -- OR que neutraliza el predicado
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
security_level = 3          # only-secured (SSL required); recomendado para SaaS/nube
max_rows_default = 100
timeout_s_default = 30

[profiles.dev]
host = "nz-dev.example.com"
port = 5480
database = "DEV"
user = "svc_claude"
mode = "write"
# security_level omitido → default 2 (preferred-secured: negocia SSL, con fallback)
```

### SSL / `security_level`

`connection.py` propaga `profile.security_level` a `nzpy.connect` (`securityLevel`). Valores: `0` preferred-unsecured, `1` only-unsecured, `2` preferred-secured (default), `3` only-secured. El **default es `2`** (secure-by-default): negocia TLS y hace fallback a claro solo si el servidor no ofrece SSL, así que es seguro y no rompe on-prem sin TLS. `1` (tráfico en claro) es **opt-in explícito** y solo para una red de laboratorio confiable. Instancias SaaS/nube deben usar `3`. Ver [`../adr/0017-connection-security-level.md`](../adr/0017-connection-security-level.md).

**Verificación del certificado** (nzpy >= 1.17.7): es **opt-in** mediante el campo opcional `ca_certs = "/ruta/ca.pem"` del perfil, con el que `connection.py` pasa `ssl={"ca_certs": …}` y exige `CERT_REQUIRED`. Sin `ca_certs`, se pasa `skipCertVerification=True`: el canal va cifrado pero el certificado del servidor no se valida (misma exposición a MITM con certificado falso que con nzpy 1.17.4; aceptable en redes on-prem controladas). Ver enmienda #160 en la ADR 0017.

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
