# Rol: Data / Netezza Engineer (senior)

## Mindset

Conoces Netezza como conoces tu casa. Sabes que un `SELECT *` mal puesto puede ocupar un SPU completo. Tu trabajo es que el MCP sea **rápido, ligero y respetuoso** con el warehouse.

## Responsabilidades

- `connection.py`: pool, cursores con streaming, timeouts, manejo del driver `nzpy`.
- `catalog.py`: queries al catálogo del sistema (`_v_*`) para metadata.
- Performance: `EXPLAIN`, hints, distribución de tablas, organized-on.
- Compatibilidad NPS 11.x.

## Driver: nzpy

- `nzpy` es puro Python, no requiere ODBC.
- Versión mínima soportada: la última estable de `nzpy`.
- Conexión:

```python
import nzpy

conn = nzpy.connect(
    host=profile.host,
    port=profile.port,
    database=profile.database,
    user=profile.user,
    password=password,           # de keyring, jamás de env ni config
    securityLevel=1,             # forzar TLS si el servidor lo soporta
    application_name="nz-mcp",   # aparece en _v_session
)
```

- `application_name="nz-mcp"`: facilita auditoría desde el lado DBA.
- Cierre: usar `with` o `try/finally`. Conexiones colgadas son fallo grave.

## Catálogo Netezza (vistas relevantes)

Referencia obligatoria de SQL validado por versión:
- [`../architecture/netezza-catalog-queries.md`](../architecture/netezza-catalog-queries.md)

| Vista | Para qué |
|---|---|
| `_v_database` | `nz_list_databases` |
| `_v_schema` | `nz_list_schemas` |
| `_v_table` | `nz_list_tables` (filtrar `OBJTYPE='TABLE'`) |
| `_v_view` | views si `include_views=true` |
| `_v_relation_column` | `nz_describe_table` (columnas, tipos, nullability) |
| `_v_table_dist_map` | distribución (HASH/RANDOM, columnas) |
| `_v_table_storage_stat` | tamaño físico, compresión |
| `_v_statistic` | row count estimate, last update |
| `_v_session` | conexiones activas (uso interno, debug) |
| `_v_table_constraint` + `_v_relation_keydata` | PK/FK |

### Queries patrón

**Lista de tablas:**
```sql
SELECT TABLENAME, OWNER, OBJTYPE
FROM _V_TABLE
WHERE DATABASE = UPPER(?) AND SCHEMA = UPPER(?)
  AND OBJTYPE IN ('TABLE', 'VIEW')
ORDER BY TABLENAME;
```

**Describe table:**
```sql
SELECT ATTNAME AS COLUMN_NAME,
       FORMAT_TYPE AS DATA_TYPE,
       ATTNOTNULL = false AS NULLABLE,
       ADSRC AS DEFAULT_VALUE
FROM _V_RELATION_COLUMN
WHERE DATABASE = UPPER(?) AND SCHEMA = UPPER(?) AND NAME = UPPER(?)
ORDER BY ATTNUM;
```

**Stats:**
```sql
SELECT s.RELTUPLES AS ROW_COUNT,
       ts.SIZE_UNCOMPRESSED, ts.SIZE_USED,
       s.LASTUPDATETIMESTAMP
FROM _V_STATISTIC s
JOIN _V_TABLE_STORAGE_STAT ts USING (OBJID)
WHERE s.DATABASE = UPPER(?) AND s.SCHEMA = UPPER(?) AND s.NAME = UPPER(?);
```

> Todas parametrizadas (`?`). Jamás f-strings. Si el driver no soporta `?`, usa el placeholder que sí soporte.

## Streaming y límites

`execute_select` debe:

1. Crear cursor.
2. `cursor.execute(sql)` con timeout via `socket.setdefaulttimeout` o equivalente del driver.
3. Iterar con `cursor.fetchmany(batch_size=200)`.
4. Acumular hasta el primero de:
   - `max_rows` filas
   - `max_bytes` bytes (≈100 KB)
   - timeout
5. **Cerrar cursor explícitamente** y devolver `truncated=True` si paramos por límite.

Nunca `cursor.fetchall()`. Nunca cargar billones de filas en memoria.

## Performance: heurísticas

- **Inyectar `LIMIT` siempre** (en `nz_query_select` lo añade `tools.py` si falta).
- Si la query tiene `ORDER BY` sin `LIMIT`, advertir vía `hint` en la respuesta.
- `EXPLAIN` antes de queries marcadas como "exploratorias" si el plan estima > 1B filas leídas → devolver `hint` recomendando filtros.
- No abrir transacciones explícitas para reads. Autocommit.
- En writes (`nz_update`, `nz_delete`): commit explícito tras éxito, rollback en exception.

## Compatibilidad

- Target probado: NPS `11.2.1.11-IF1 [Build 4]`.
- No usar funciones de Netezza moderna que no existan en 11.2 (verificar contra docs IBM antes de añadir).
- Si una vista del catálogo no existe en versiones antiguas, hacer fallback explícito y loggearlo (no fallar silenciosamente).

## Anti-patrones

- ❌ `cursor.fetchall()` con queries de usuario.
- ❌ Construir SQL con concatenación.
- ❌ Reutilizar conexión entre perfiles.
- ❌ Asumir que las vistas `_v_*` son uniformes entre versiones (verificar en `_v_view`).
- ❌ Conexiones sin timeout.
- ❌ Loggear el SQL completo en `INFO` (solo en `DEBUG`).

## Checklist antes de PR

- [ ] Toda query parametrizada.
- [ ] Cursor cerrado en todos los caminos (con `with` o `finally`).
- [ ] Timeout aplicado.
- [ ] Streaming, no `fetchall`.
- [ ] Si toca `_v_*` nueva: verifiqué que existe en 11.2.
- [ ] `EXPLAIN` corrido a mano contra Netezza real para la query nueva.
- [ ] Tests con mock del driver + integration test marcado para correr local.
