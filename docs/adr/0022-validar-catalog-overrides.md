# 22. Validar el SQL de `catalog_overrides` con `sql_guard`

Date: 2026-09-05

## Status

Accepted

## Context

`resolve_query` devolvía el texto de `catalog_overrides` **verbatim** y los consumidores lo pasaban directo a `cursor.execute()`. El único control era que el `query_id` existiera en `CATALOG_QUERY_MAP`. El propio `config.py` lo admitía por escrito: *"Catalog overrides run as-is and do not go through sql_guard"*. En las rutas de catálogo, nominalmente de solo lectura, había un camino de ejecución que saltaba las barreras 1 y 2 del modelo de tres capas (issue #139).

### Quién es el atacante

Conviene no inflarlo ni minimizarlo. `profiles.toml` lo escribe el propio usuario, y quien puede editarlo puede además poner `mode = "admin"`: **esto no es una escalada de privilegios** y no hay ningún vector remoto. El valor del cambio es otro:

1. **La promesa de `mode = "read"` era falsa.** Un perfil en modo lectura le promete al usuario que la IA no puede escribir. Un `catalog_overrides` con un `DELETE` rompía esa promesa **sin tocar `mode`**, que es justo el campo que el usuario mira cuando quiere saber qué puede llegar a pasar.
2. **Config copiada de terceros.** El caso realista no es alguien saboteando su propio fichero, sino un `catalog_overrides` pegado desde un blog, un README de empresa o el `profiles.toml` de un compañero, que se ejecuta a ciegas porque nadie vuelve a leerlo. Mismo vector que un script descargado y ejecutado sin leer, con la diferencia de que aquí el disparador es una IA.
3. **Quien dispara es la IA, no el humano.** Cualquier tool de catálogo (`nz_list_tables`, `nz_describe_table`) ejecutaba el override. Un override malicioso convertía una tool de lectura en una mutación, y ni el modelo ni el usuario veían el SQL real.
4. **Otro proceso puede escribir el fichero.** Un agente con acceso al sistema de archivos (otro servidor MCP, un script de provisioning, una plantilla generada) puede añadir un override sin pasar por el asistente. Validar en runtime hace que, aun así, las rutas de catálogo solo puedan leer.
5. **Superficie real.** El paquete está publicado en PyPI: esto ya no afecta solo al entorno del owner.

Lo que **no** resuelve: `catalog_overrides` sigue siendo una feature basada en la confianza en el usuario. Quien controla el fichero controla el modo, el host y el usuario de conexión.

## Decision

### Qué se valida

`sql_guard.validate_catalog_override(sql, *, query_id, profile)`:

1. Pasa el SQL por `validate(..., mode="read")`: la misma barrera que cualquier otra sentencia. Sentencias apiladas, comentarios con `;`, DML, DDL, `CALL`, CTE con mutación y sentencias no clasificables quedan fuera.
2. Exige además que la clase sea **`SELECT`**. `mode="read"` también admite `SHOW` y `EXPLAIN`, que no devuelven las columnas que los consumidores desempaquetan: un override de catálogo es siempre una consulta de filas.
3. Rechaza un `SELECT` con destino `INTO`: materializa una tabla, es una escritura disfrazada de lectura.
4. Los marcadores `<BD>..` se renderizan contra un nombre de base de datos ficticio **solo para parsear**; el texto almacenado se devuelve intacto. Un `<BD>` que no sea el centinela `<BD>..` se rechaza, porque habría llegado al driver sin resolver.

### Compatibilidad: qué overrides dejan de funcionar

Verificado contra las queries reales: las **14** registradas en `CATALOG_QUERY_MAP` pasan la validación (test parametrizado sobre `ALL_QUERIES`, que es a la vez red de seguridad para catálogos futuros). Ninguna usa `WITH` ni `SHOW`.

- **`WITH ... SELECT` no se rompe.** El guard pliega el CTE y clasifica el statement por su cuerpo, así que `WITH s AS (SELECT ...) SELECT ... FROM s` es `SELECT`. Lo mismo con `UNION` / `UNION ALL` de ramas `SELECT` y con los placeholders `?` que el driver parametriza. Un `WITH` cuyo CTE muta (`WITH x AS (DELETE ... RETURNING *) SELECT * FROM x`) sí se rechaza, que es exactamente el objetivo.
- **`SHOW` y `EXPLAIN` sí se rompen**, y es deliberado. Son lecturas legales en `mode="read"`, pero los consumidores de catálogo desempaquetan columnas concretas por posición: un `SHOW` sustituyendo `list_tables` no habría devuelto nada usable ni antes del cambio. El coste de compatibilidad es teórico; el beneficio es que la regla queda en una sola frase ("un override es un `SELECT`") en vez de en una lista de excepciones.
- **`SELECT ... INTO` se rompe**, y también es deliberado: es una escritura.

Nadie se queda a ciegas: un override que deja de funcionar produce un error que **nombra el `query_id` y el perfil** y, por el mecanismo de hints de la ADR 0023, un `hint_es` / `hint_en` que apunta a la clave exacta de `profiles.toml` (`catalog_overrides.<query_id>` bajo `[profiles.<perfil>]`) y dice que borrarla devuelve la consulta integrada. No hay fallo genérico ni caída silenciosa a la query original: caer de vuelta en silencio ocultaría que la configuración del usuario está rota.

### Cuándo se valida

En **`resolve_query`**, el punto de resolución, no al cargar el perfil:

- `config.py` **no puede** importar `sql_guard` (`sql_guard` importa `config`: ciclo de imports), y un parser de SQL no pertenece a la capa de configuración.
- Validar al cargar no cubriría más: `get_active_profile` relee `profiles.toml` en cada llamada de tool, así que la carga ocurre prácticamente en cada ejecución. Sí dejaría fuera los perfiles construidos en memoria (asistente de `add-profile`, tests, código que instancia `Profile` directamente).
- En el punto de resolución **ninguna ruta lo esquiva**: es el mismo sitio donde ya se valida el `query_id`, y por él pasan las tools MCP, `nz-mcp probe-catalog` y la escalera de `profile_check`.
- Se validan **todos** los overrides del perfil, no solo el que se resuelve. Mismo criterio que la comprobación de claves desconocidas que ya existía: una entrada rota rompe el perfil entero, el usuario recibe el diagnóstico completo en la primera llamada y una entrada maliciosa no queda latente hasta que alguien invoque justo esa tool.

### Cómo se comunica el rechazo

`GuardRejectedError` con `code="CATALOG_OVERRIDE_REJECTED"` y contexto `query_id`, `profile`, `reason` y —solo cuando aplica— `statement_kind`.

`reason` es siempre un **token estable** (`NOT_A_SELECT`, `SELECT_INTO`, `UNRESOLVED_BD_MARKER`, o el código con el que el guard rechazó el SQL: `STACKED_NOT_ALLOWED`, `STATEMENT_NOT_ALLOWED`, `PERMISSION_DENIED`…). El detalle extra viaja en su propia clave de contexto, nunca concatenado al `reason`: quien ramifique sobre él no debe tener que parsearlo.

El reparto entre mensaje y hint sigue la ADR 0023:

- **Mensaje** (`GUARD_REJECTED.CATALOG_OVERRIDE_REJECTED`, ES/EN): el hecho. Qué override, de qué perfil, y por qué no se ejecuta.
- **Hint** (`…HINT.NOT_A_SELECT`, `…HINT.SELECT_INTO`, `…HINT.UNRESOLVED_BD_MARKER`, `…HINT.GUARD`), promocionado al nivel superior del payload: la salida. Nombra la clave exacta a editar y, en `NOT_A_SELECT`, qué clase de sentencia se encontró. Sin `query_id` y `profile` no hay clave que señalar y **no se emite hint**, según la regla de la ADR 0023 (específico o nada).

**El SQL ofensivo no se devuelve** en el mensaje ni en el hint: es configuración del usuario y puede contener nombres de objetos internos. Un test adversarial lo fija.

## Alternatives considered

- **Validar solo el override que se resuelve.** Más barato, pero deja una entrada maliciosa latente hasta que alguien llame justo a esa tool, y el usuario descubre los fallos de uno en uno. Descartado.
- **Validar al cargar el perfil (`config.py`).** Requeriría que la capa de configuración importe el parser de SQL (ciclo de imports con `sql_guard`, que importa `config`) y aun así dejaría fuera los `Profile` construidos en memoria. Descartado.
- **Aceptar cualquier statement que pase `mode="read"` (incluidos `SHOW` / `EXPLAIN`).** Más permisivo y menos código, pero la regla deja de ser enunciable en una frase y admite formas que el consumidor no sabe desempaquetar. Descartado por la heurística "estricto > permisivo".
- **Caer en silencio a la query integrada cuando el override no valida.** Nunca rompería a nadie, pero oculta que la configuración del usuario está rota y hace que la salida dependa de un fallo invisible. Descartado: errores explícitos sobre silencios.
- **Quitar `catalog_overrides`.** Es una vía de escape legítima para catálogos de NPS que difieren entre versiones. Descartado.

## Consequences

**Positivas**

- Las rutas de catálogo dejan de tener un camino de ejecución que salta las barreras 1 y 2. `sql_guard` vuelve a ser la única puerta a `connection.execute()`, sin excepciones documentadas.
- La promesa de `mode = "read"` se sostiene sin depender de que el usuario relea su propio fichero.
- `nz-mcp probe-catalog` diagnostica el override roto como `config_error` en vez de mandarlo al servidor.

**Negativas**

- Un override con `SHOW` / `EXPLAIN` / `SELECT ... INTO` que hoy exista deja de funcionar (**cambio observable**, entrada en el CHANGELOG).
- Cada `resolve_query` parsea todos los overrides del perfil. Coste medido: irrelevante frente al round-trip de red, y el guard prohíbe explícitamente cachear el resultado de `validate()`.
- La superficie de `sql_guard` crece con una función más, que queda cubierta al 100 % y con tests adversariales propios.

**Mitigaciones**

- Test parametrizado sobre `ALL_QUERIES`: si una query de catálogo futura no pasara la validación de override, el CI lo dice antes de que un usuario la copie para retocarla.
- Batería adversarial dedicada en `tests/unit/test_sql_guard_adversarial.py` (DML, DDL, apiladas, `GRANT`, `CALL`, CTAS, CTE con mutación, `SELECT INTO`, cuerpo NZPLSQL, `SHOW`, `EXPLAIN`, vacío y basura) más el caso legítimo que debe seguir pasando.
