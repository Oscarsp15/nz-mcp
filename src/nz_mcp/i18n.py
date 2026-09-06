"""Bilingual (ES/EN) message catalog.

Rule: every key MUST have both ``es`` and ``en``. ``test_i18n.py`` enforces parity.
"""

from __future__ import annotations

import locale as _std_locale
import os
from typing import Final, Literal, TypedDict

Locale = Literal["es", "en"]
DEFAULT_LOCALE: Final[Locale] = "en"


class Message(TypedDict):
    es: str
    en: str


MESSAGES: Final[dict[str, Message]] = {
    # GuardRejectedError reasons
    "GUARD_REJECTED.STACKED_NOT_ALLOWED": {
        "es": "No se permiten múltiples sentencias en una sola llamada.",
        "en": "Multiple statements in a single call are not allowed.",
    },
    "GUARD_REJECTED.STATEMENT_NOT_ALLOWED": {
        "es": "El tipo de sentencia '{kind}' no está permitido para el modo '{mode}'.",
        "en": "Statement kind '{kind}' is not allowed for mode '{mode}'.",
    },
    "GUARD_REJECTED.UPDATE_REQUIRES_WHERE": {
        "es": "Las sentencias UPDATE requieren cláusula WHERE.",
        "en": "UPDATE statements require a WHERE clause.",
    },
    "GUARD_REJECTED.DELETE_REQUIRES_WHERE": {
        "es": "Las sentencias DELETE requieren cláusula WHERE.",
        "en": "DELETE statements require a WHERE clause.",
    },
    "GUARD_REJECTED.WHERE_ALWAYS_TRUE": {
        "es": (
            "El predicado WHERE de la sentencia '{kind}' es siempre verdadero, así que "
            "afectaría a todas las filas de la tabla. Si es intencionado, repite la "
            "llamada con confirm_full_table=true."
        ),
        "en": (
            "The WHERE predicate of the '{kind}' statement is always true, so it would "
            "affect every row in the table. If that is intended, repeat the call with "
            "confirm_full_table=true."
        ),
    },
    "GUARD_REJECTED.UNKNOWN_STATEMENT": {
        "es": "No se pudo clasificar la sentencia SQL recibida.",
        "en": "Could not classify the received SQL statement.",
    },
    "GUARD_REJECTED.EMPTY_STATEMENT": {
        "es": "La sentencia SQL está vacía.",
        "en": "The SQL statement is empty.",
    },
    "GUARD_REJECTED.WRONG_STATEMENT_FOR_TOOL": {
        "es": "La tool '{tool}' no acepta sentencias del tipo '{kind}'.",
        "en": "Tool '{tool}' does not accept '{kind}' statements.",
    },
    "GUARD_REJECTED.LIMIT_NOT_A_LITERAL": {
        "es": (
            "El LIMIT de la consulta tiene que ser un literal entero o ALL. nz-mcp acota "
            "el resultado reescribiendo ese valor sobre el SQL original, y no puede "
            "hacerlo con una expresión calculada ni con un parámetro: sustitúyelo por un "
            "número (por ejemplo LIMIT 100) y repite la llamada."
        ),
        "en": (
            "The query's LIMIT must be an integer literal or ALL. nz-mcp bounds the result "
            "by rewriting that value in the original SQL, and cannot do so for a computed "
            "expression or a parameter: replace it with a number (for example LIMIT 100) "
            "and call again."
        ),
    },
    "GUARD_REJECTED.CATALOG_OVERRIDE_REJECTED": {
        "es": (
            "El override de catálogo '{query_id}' del perfil '{profile}' no es una consulta "
            "SELECT de solo lectura, así que no se ejecuta (motivo: {reason})."
        ),
        "en": (
            "Catalog override '{query_id}' of profile '{profile}' is not a read-only SELECT, "
            "so it does not run (reason: {reason})."
        ),
    },
    # One hint per rejection reason: each names the exact profiles.toml key to edit,
    # because nz-mcp cannot fix the user's own config for them (see error_hints).
    "GUARD_REJECTED.CATALOG_OVERRIDE_REJECTED.HINT.NOT_A_SELECT": {
        "es": (
            "Esa entrada es una sentencia {statement_kind}, y un override de catálogo tiene "
            "que devolver filas: solo se admite SELECT (incluidos 'WITH ... SELECT' y las "
            "uniones de SELECT). Corrige catalog_overrides.{query_id} en "
            "[profiles.{profile}] de profiles.toml, o borra la entrada para volver a la "
            "consulta integrada."
        ),
        "en": (
            "That entry is a {statement_kind} statement, and a catalog override has to "
            "return rows: only SELECT is accepted ('WITH ... SELECT' and unions of SELECTs "
            "included). Fix catalog_overrides.{query_id} under [profiles.{profile}] in "
            "profiles.toml, or delete the entry to fall back to the built-in query."
        ),
    },
    "GUARD_REJECTED.CATALOG_OVERRIDE_REJECTED.HINT.SELECT_INTO": {
        "es": (
            "Esa entrada es un 'SELECT ... INTO': materializa una tabla, o sea que escribe. "
            "Quita la cláusula INTO de catalog_overrides.{query_id} en [profiles.{profile}] "
            "de profiles.toml, o borra la entrada para volver a la consulta integrada."
        ),
        "en": (
            "That entry is a 'SELECT ... INTO': it materializes a table, which is a write. "
            "Drop the INTO clause from catalog_overrides.{query_id} under "
            "[profiles.{profile}] in profiles.toml, or delete the entry to fall back to the "
            "built-in query."
        ),
    },
    "GUARD_REJECTED.CATALOG_OVERRIDE_REJECTED.HINT.UNRESOLVED_BD_MARKER": {
        "es": (
            "El único marcador de base de datos que nz-mcp sustituye es '<BD>..' (con los "
            "dos puntos); cualquier otro '<BD>' llegaría al driver sin resolver. Corrígelo "
            "en catalog_overrides.{query_id} de [profiles.{profile}] en profiles.toml."
        ),
        "en": (
            "The only database marker nz-mcp substitutes is '<BD>..' (with the two dots); "
            "any other '<BD>' would reach the driver unresolved. Fix it in "
            "catalog_overrides.{query_id} under [profiles.{profile}] in profiles.toml."
        ),
    },
    "GUARD_REJECTED.CATALOG_OVERRIDE_REJECTED.HINT.GUARD": {
        "es": (
            "sql_guard rechazó ese SQL con el código {reason}, igual que si lo hubieras "
            "enviado por una tool. Corrige catalog_overrides.{query_id} en "
            "[profiles.{profile}] de profiles.toml hasta que sea un SELECT de solo lectura, "
            "o borra la entrada para volver a la consulta integrada."
        ),
        "en": (
            "sql_guard rejected that SQL with code {reason}, exactly as if you had sent it "
            "through a tool. Fix catalog_overrides.{query_id} under [profiles.{profile}] in "
            "profiles.toml until it is a read-only SELECT, or delete the entry to fall back "
            "to the built-in query."
        ),
    },
    "GUARD_REJECTED.PROD_REF_IN_NONPROD": {
        "es": (
            "El SQL referencia identificadores de producción ({refs}) pero el perfil "
            "activo apunta a una base de datos no productiva ({active_database}). "
            "Rechazado para evitar operaciones cross-entorno."
        ),
        "en": (
            "The SQL references production identifiers ({refs}) but the active profile "
            "targets a non-production database ({active_database}). "
            "Rejected to prevent cross-environment operations."
        ),
    },
    # Permissions
    "PERMISSION_DENIED.MODE_TOO_LOW": {
        "es": "La operación requiere modo '{required}' pero el perfil tiene '{actual}'.",
        "en": "Operation requires mode '{required}' but the profile has '{actual}'.",
    },
    # Profile / config
    "PROFILE_NOT_FOUND": {
        "es": "No existe el perfil '{profile}'.{hint_es} Crea uno con: nz-mcp add-profile.",
        "en": "Profile '{profile}' does not exist.{hint_en} Create one with: nz-mcp add-profile.",
    },
    "INVALID_CONFIG": {
        "es": "El archivo de configuración es inválido: {detail}",
        "en": "The configuration file is invalid: {detail}",
    },
    "INVALID_DATABASE_NAME": {
        "es": "Nombre de base de datos inválido para interpolación de catálogo: {detail}",
        "en": "Invalid database name for catalog interpolation: {detail}",
    },
    "CONNECTION_FAILED": {
        "es": "No se pudo abrir conexión a Netezza ({host}:{port}/{database}): {detail}",
        "en": "Could not open Netezza connection ({host}:{port}/{database}): {detail}",
    },
    # One actionable hint per connection failure cause (see connection.CAUSE_*).
    "CONNECTION_FAILED.HINT.AUTH_REJECTED": {
        "es": "Netezza rechazó las credenciales del usuario '{user}'. Vuelve a guardar la contraseña con 'nz-mcp add-profile' y comprueba que la cuenta no esté bloqueada o caducada.",
        "en": "Netezza rejected the credentials for user '{user}'. Store the password again with 'nz-mcp add-profile' and check the account is not locked or expired.",
    },
    "CONNECTION_FAILED.HINT.DATABASE_UNAVAILABLE": {
        "es": "La base de datos '{database}' no existe o el usuario '{user}' no tiene permiso sobre ella. Verifica el nombre en el perfil y los grants del usuario.",
        "en": "Database '{database}' does not exist or user '{user}' has no permission on it. Check the name in the profile and the user's grants.",
    },
    "CONNECTION_FAILED.HINT.HOST_UNREACHABLE": {
        "es": "No hubo respuesta de {host}:{port}. Comprueba la VPN, que el host resuelva por DNS y que el puerto esté abierto.",
        "en": "No response from {host}:{port}. Check the VPN, that the host resolves via DNS, and that the port is open.",
    },
    "CONNECTION_FAILED.HINT.TLS_FAILED": {
        "es": "Falló la negociación TLS con {host}:{port}. Revisa 'ca_certs' del perfil o ajusta 'security_level' si el servidor no ofrece SSL.",
        "en": "TLS negotiation with {host}:{port} failed. Review the profile 'ca_certs' or adjust 'security_level' if the server does not offer SSL.",
    },
    "CONNECTION_FAILED.HINT.UNKNOWN": {
        "es": "No se pudo clasificar el fallo de conexión a {host}:{port}/{database}. Ejecuta 'nz-mcp test-connection' y revisa el detalle del driver.",
        "en": "The connection failure against {host}:{port}/{database} could not be classified. Run 'nz-mcp test-connection' and review the driver detail.",
    },
    "NETEZZA_ERROR": {
        "es": "Netezza devolvió un error durante '{operation}': {detail}",
        "en": "Netezza returned an error during '{operation}': {detail}",
    },
    # One hint per Netezza error pattern the AI can actually fix (see error_hints).
    "NETEZZA_ERROR.HINT.MULTI_ROW_VALUES": {
        "es": "Netezza no acepta listas VALUES de varias filas. Inserta con nz_insert (que emite un único UNION ALL) o con nz_insert_select.",
        "en": "Netezza does not accept multi-row VALUES lists. Insert with nz_insert (it emits a single UNION ALL) or with nz_insert_select.",
    },
    "NETEZZA_ERROR.HINT.RELATION_NOT_FOUND": {
        "es": "La relación no existe en la base de datos activa. Comprueba el nombre con nz_list_tables y cualifícalo como BD.ESQUEMA.TABLA si vive en otra base.",
        "en": "The relation does not exist in the active database. Check the name with nz_list_tables and qualify it as DB.SCHEMA.TABLE if it lives in another database.",
    },
    "NETEZZA_ERROR.HINT.ATTRIBUTE_NOT_FOUND": {
        "es": "Esa columna no existe en la tabla. Pide los nombres exactos con nz_describe_table antes de reintentar.",
        "en": "That column does not exist on the table. Get the exact names with nz_describe_table before retrying.",
    },
    "NETEZZA_ERROR.HINT.PERMISSION_DENIED": {
        "es": "El usuario de Netezza del perfil no tiene el privilegio necesario. nz-mcp no puede concederlo: mira con qué usuario operas con nz_current_profile y pide el grant a un DBA.",
        "en": "The profile's Netezza user lacks the required privilege. nz-mcp cannot grant it: check which user you are running as with nz_current_profile and ask a DBA for the grant.",
    },
    # Tool input validation
    "INVALID_INPUT": {
        "es": "Argumento inválido: {detail}",
        "en": "Invalid argument: {detail}",
    },
    "INVALID_INPUT.HINT.MISSING_FIELDS": {
        "es": "Faltan argumentos obligatorios: {fields}. Añádelos y repite la llamada.",
        "en": "Missing required arguments: {fields}. Add them and call the tool again.",
    },
    "INVALID_INPUT.HINT.UNEXPECTED_FIELDS": {
        "es": "Argumentos no reconocidos: {fields}. La tool los rechaza; quítalos o usa el nombre del esquema de entrada.",
        "en": "Unknown arguments: {fields}. The tool rejects them; drop them or use the name from its input schema.",
    },
    "OBJECT_NOT_FOUND": {
        "es": "Objeto no encontrado: {detail}",
        "en": "Object not found: {detail}",
    },
    "OBJECT_NOT_FOUND.HINT.TABLE": {
        "es": "Lista los nombres reales con nz_list_tables(database='{database}', schema='{schema}'); Netezza guarda los identificadores en mayúsculas salvo que se crearan entrecomillados.",
        "en": "List the real names with nz_list_tables(database='{database}', schema='{schema}'); Netezza stores identifiers in upper case unless they were created quoted.",
    },
    "OBJECT_NOT_FOUND.HINT.PROCEDURE": {
        "es": "Lista los procedimientos reales con nz_list_procedures(database='{database}', schema='{schema}'); el nombre debe coincidir con el catálogo, incluidas mayúsculas.",
        "en": "List the real procedures with nz_list_procedures(database='{database}', schema='{schema}'); the name must match the catalog, casing included.",
    },
    # Auth
    "KEYRING_UNAVAILABLE": {
        "es": "El backend de keyring no está disponible en este sistema.",
        "en": "The keyring backend is unavailable on this system.",
    },
    "CREDENTIAL_NOT_FOUND": {
        "es": "No se encontró credencial para el perfil '{profile}'.",
        "en": "No credential found for profile '{profile}'.",
    },
    "SECTION_NOT_FOUND": {
        "es": "La sección solicitada no existe en el cuerpo del procedimiento (section={section}).",
        "en": "The requested section does not exist in the procedure body (section={section}).",
    },
    "OVERLOAD_AMBIGUOUS": {
        "es": "Hay varias sobrecargas para el procedimiento '{procedure}'; indica proceduresignature.",
        "en": "Multiple overloads exist for procedure '{procedure}'; specify proceduresignature.",
    },
    "PROCEDURE_ALREADY_EXISTS": {
        "es": "El procedimiento ya existe en el destino (database={database}, schema={schema}, "
        "procedure={procedure}).",
        "en": "The procedure already exists on the target (database={database}, schema={schema}, "
        "procedure={procedure}).",
    },
    "CONFIRM_REQUIRED": {
        "es": "Se requiere confirm=true para ejecutar la mutación con dry_run=false.",
        "en": "confirm=true is required to run the mutation with dry_run=false.",
    },
    "RESPONSE_TOO_LARGE": {
        "es": (
            "La respuesta excede el límite ({size_kb} KB > {cap_kb} KB). "
            "Filtra por kinds o usa nz_get_procedure_section."
        ),
        "en": (
            "Response exceeds the cap ({size_kb} KB > {cap_kb} KB). "
            "Filter by kinds or use nz_get_procedure_section."
        ),
    },
    "INPUT_TOO_BROAD": {
        "es": (
            "El escaneo abarcaría {scanned} procedimientos (cap {cap}). "
            "Refina la búsqueda con el parámetro 'pattern'."
        ),
        "en": (
            "The scan would cover {scanned} procedures (cap {cap}). "
            "Narrow it with the 'pattern' parameter."
        ),
    },
    # Hints
    "HINT.RESULT_TRUNCATED_BY_ROWS": {
        "es": "Resultado truncado en {n} filas. Añade WHERE o LIMIT para refinar.",
        "en": "Result truncated at {n} rows. Add WHERE or LIMIT to refine.",
    },
    "HINT.TIMEOUT_NEAR": {
        "es": "La query tardó {ms}ms, cerca del timeout. Considera filtrar más.",
        "en": "Query took {ms}ms, near timeout. Consider filtering further.",
    },
    "HINT.RESULT_TRUNCATED_BY_BYTES": {
        "es": "Resultado truncado por tamaño de salida (~{max_kb} KB). Use SELECT con menos columnas o filtre.",
        "en": "Result truncated by output size (~{max_kb} KB). Use an explicit SELECT with fewer columns or add filters.",
    },
    "HINT.RESULT_TRUNCATED_BY_TIMEOUT": {
        "es": "Se alcanzó el límite de tiempo ({timeout_s}s). El resultado puede estar incompleto.",
        "en": "Execution time limit ({timeout_s}s) was reached. The result may be incomplete.",
    },
    "HINT.PROCEDURE_LIST_TRUNCATED": {
        "es": "Lista truncada en {n} de {total} procedimientos. Acota con 'pattern' o sube 'max_rows' (máx {cap}).",
        "en": "List truncated at {n} of {total} procedures. Narrow it with 'pattern' or raise 'max_rows' (max {cap}).",
    },
    "HINT.PROCEDURE_DDL_TRUNCATED": {
        "es": "DDL truncado a {returned_kb} KB de {total_kb} KB (tope max_bytes={max_kb} KB). Llama a nz_get_procedure_size para dimensionar el SP y lee el resto con nz_get_procedure_section(section='range', from_line={from_line}, to_line={to_line}), avanzando de {step} en {step} líneas.",
        "en": "DDL truncated to {returned_kb} KB of {total_kb} KB (max_bytes cap {max_kb} KB). Call nz_get_procedure_size to size the SP up and read the rest with nz_get_procedure_section(section='range', from_line={from_line}, to_line={to_line}), advancing {step} lines at a time.",
    },
    "NOTE.DDL_RECONSTRUCTED": {
        "es": "DDL reconstruido desde catálogo (SHOW TABLE no disponible en este servidor).",
        "en": "DDL reconstructed from catalogs (SHOW TABLE not available on this server).",
    },
    "NOTE.DDL_RECONSTRUCTED_DETAIL": {
        "es": "DDL reconstruido desde _v_relation_column + _v_table_dist_map + restricciones de catálogo.",
        "en": "DDL reconstructed from _v_relation_column + _v_table_dist_map + catalog constraints.",
    },
    "NOTE.DDL_WITH_DATA_CAVEAT": {
        "es": "Las cláusulas WITH DATA / STATISTICS pueden diferir del CREATE original.",
        "en": "WITH DATA / STATISTICS clauses may differ from the original CREATE.",
    },
    "EXPORT_DDL.SUMMARY_LINE": {
        "es": "DDL exportado: {object_type} {schema}.{name} ({duration_ms} ms). El bloque resource incluye el texto SQL.",
        "en": "Exported DDL: {object_type} {schema}.{name} ({duration_ms} ms). The resource block holds the SQL text.",
    },
    "EXPORT_DDL.WROTE_FILE": {
        "es": "Archivo escrito: {path} ({bytes_written} bytes, sha256={sha256}).",
        "en": "File written: {path} ({bytes_written} bytes, sha256={sha256}).",
    },
    # nz-mcp profile lifecycle (CLI wizard: add-profile / remove-profile)
    "CLI.PROFILE_ALREADY_EXISTS": {
        "es": "El perfil '{profile}' ya existe en {path}.",
        "en": "Profile '{profile}' already exists in {path}.",
    },
    "CLI.PROFILE_OVERWRITE_CONFIRM": {
        "es": (
            "¿Sobrescribirlo? Se reemplazarán host, puerto, base de datos, usuario, "
            "modo y password; el resto de campos del perfil se conserva"
        ),
        "en": (
            "Overwrite it? Host, port, database, user, mode and password will be "
            "replaced; every other profile field is kept"
        ),
    },
    "CLI.PROFILE_OVERWRITE_CANCELLED": {
        "es": (
            "Cancelado: el perfil '{profile}' no se ha modificado. "
            "Cambia campos sueltos con: nz-mcp edit-profile {profile} --mode read. "
            "Bórralo con: nz-mcp remove-profile {profile}."
        ),
        "en": (
            "Cancelled: profile '{profile}' was left unchanged. "
            "Change single fields with: nz-mcp edit-profile {profile} --mode read. "
            "Delete it with: nz-mcp remove-profile {profile}."
        ),
    },
    "CLI.PROFILE_SAVED": {
        "es": "Perfil '{profile}' guardado en {path}.",
        "en": "Profile '{profile}' saved to {path}.",
    },
    "CLI.PROFILE_NEXT_STEP": {
        "es": "Siguiente paso: prueba la conexión con: nz-mcp test-connection --profile {profile}",
        "en": "Next step: verify the connection with: nz-mcp test-connection --profile {profile}",
    },
    "CLI.PROFILE_REMOVE_CONFIRM": {
        "es": "Se borrará el perfil '{profile}' de {path} y su password del keyring. ¿Continuar?",
        "en": (
            "Profile '{profile}' will be deleted from {path} and its password removed "
            "from the keyring. Continue?"
        ),
    },
    "CLI.PROFILE_REMOVE_CANCELLED": {
        "es": "Cancelado: el perfil '{profile}' sigue configurado.",
        "en": "Cancelled: profile '{profile}' is still configured.",
    },
    "CLI.PROFILE_REMOVED": {
        "es": "Perfil '{profile}' eliminado de {path}.",
        "en": "Profile '{profile}' removed from {path}.",
    },
    "CLI.PROFILE_PASSWORD_DELETED": {
        "es": "Password del perfil '{profile}' borrada del keyring.",
        "en": "Password of profile '{profile}' deleted from the keyring.",
    },
    "CLI.PROFILE_PASSWORD_DELETE_FAILED": {
        "es": (
            "No se pudo borrar la password del perfil '{profile}' del keyring: {detail}. "
            "Bórrala a mano en el gestor de credenciales del sistema."
        ),
        "en": (
            "Could not delete the password of profile '{profile}' from the keyring: {detail}. "
            "Delete it by hand in your OS credential manager."
        ),
    },
    "CLI.ACTIVE_PROFILE_CLEARED": {
        "es": (
            "Era el perfil activo: ya no hay ninguno. Si queda más de un perfil, elige cuál "
            "usar con la variable NZ_MCP_PROFILE o con el campo 'active' de {path}."
        ),
        "en": (
            "It was the active profile: there is none now. If more than one profile remains, "
            "pick one with the NZ_MCP_PROFILE variable or the 'active' field in {path}."
        ),
    },
    "CLI.PROFILE_SWITCHED": {
        "es": (
            "Perfil activo: '{profile}' (modo {mode}). Los procesos nz-mcp que arranques "
            "a partir de ahora lo usarán."
        ),
        "en": (
            "Active profile: '{profile}' (mode {mode}). Every nz-mcp process you start "
            "from now on will use it."
        ),
    },
    # nz-mcp init / add-profile (guided wizard: one explanation per non-obvious concept)
    "CLI.INIT_INTRO": {
        "es": "Esto crea el primer perfil. La password irá al keyring de tu sistema operativo.",
        "en": "This creates the first profile. The password goes to your OS keyring.",
    },
    "CLI.INIT_NAME_PROMPT": {
        "es": "Nombre del perfil",
        "en": "Profile name",
    },
    "CLI.WIZARD_INTRO": {
        "es": (
            "Configurando el perfil '{profile}'. Nada se guarda hasta el final: primero "
            "pregunto los datos, después los valido contra Netezza."
        ),
        "en": (
            "Configuring profile '{profile}'. Nothing is saved until the end: I ask for the "
            "data first, then validate it against Netezza."
        ),
    },
    "CLI.WIZARD_HOST_PROMPT": {
        "es": "Host de Netezza",
        "en": "Netezza host",
    },
    "CLI.WIZARD_PORT_PROMPT": {
        "es": "Puerto",
        "en": "Port",
    },
    "CLI.WIZARD_DATABASE_EXPLAIN": {
        "es": (
            "La base de datos por defecto es contra la que se resuelven los nombres sin "
            "calificar; puedes cambiarla luego sin rehacer el perfil."
        ),
        "en": (
            "The default database is the one unqualified names resolve against; you can "
            "change it later without recreating the profile."
        ),
    },
    "CLI.WIZARD_DATABASE_PROMPT": {
        "es": "Base de datos por defecto",
        "en": "Default database",
    },
    "CLI.WIZARD_USER_PROMPT": {
        "es": "Usuario",
        "en": "User",
    },
    "CLI.WIZARD_PASSWORD_EXPLAIN": {
        "es": "La password nunca se escribe en profiles.toml: se guarda en el keyring del SO.",
        "en": "The password is never written to profiles.toml: it is stored in the OS keyring.",
    },
    "CLI.WIZARD_PASSWORD_PROMPT": {
        "es": "Password",
        "en": "Password",
    },
    "CLI.WIZARD_MODE_EXPLAIN": {
        "es": (
            "El modo limita lo que la IA podrá hacer con este perfil: 'read' solo consultas, "
            "'write' añade escritura de datos (INSERT/UPDATE/DELETE), 'admin' añade DDL "
            "(CREATE/ALTER/DROP). El modo no otorga permisos en Netezza: solo recorta los "
            "que ya tenga tu usuario."
        ),
        "en": (
            "The mode limits what the AI may do with this profile: 'read' queries only, "
            "'write' adds data writes (INSERT/UPDATE/DELETE), 'admin' adds DDL "
            "(CREATE/ALTER/DROP). The mode grants no Netezza privilege: it only narrows the "
            "ones your user already has."
        ),
    },
    "CLI.WIZARD_MODE_PROMPT": {
        "es": "Modo (read|write|admin)",
        "en": "Mode (read|write|admin)",
    },
    "CLI.WIZARD_MODE_INVALID": {
        "es": "Modo inválido: {value}. Usa read, write o admin.",
        "en": "Invalid mode: {value}. Use read, write or admin.",
    },
    "CLI.WIZARD_SECURITY_EXPLAIN": {
        "es": (
            "El nivel de seguridad decide si la conexión viaja cifrada (TLS): 0 prefiere sin "
            "cifrar, 1 solo sin cifrar (red de laboratorio), 2 prefiere cifrado y cae a claro "
            "si el servidor no lo ofrece (recomendado), 3 exige cifrado (SaaS/nube)."
        ),
        "en": (
            "The security level decides whether the connection is encrypted (TLS): 0 prefers "
            "unsecured, 1 unsecured only (lab network), 2 prefers encryption and falls back to "
            "cleartext when the server offers none (recommended), 3 requires encryption "
            "(SaaS/cloud)."
        ),
    },
    "CLI.WIZARD_SECURITY_PROMPT": {
        "es": "Nivel de seguridad de la conexión (0-3)",
        "en": "Connection security level (0-3)",
    },
    "CLI.WIZARD_SECURITY_INVALID": {
        "es": "Nivel de seguridad inválido: {value}. Usa un entero de 0 a 3.",
        "en": "Invalid security level: {value}. Use an integer from 0 to 3.",
    },
    "CLI.WIZARD_CA_CERTS_EXPLAIN": {
        "es": (
            "Un bundle CA (archivo PEM) permite verificar el certificado del servidor. Sin él "
            "el canal sigue cifrado, pero no se comprueba con quién hablas. Es opcional: pulsa "
            "Enter para omitirlo."
        ),
        "en": (
            "A CA bundle (PEM file) lets nz-mcp verify the server certificate. Without it the "
            "channel is still encrypted, but you do not check who you are talking to. It is "
            "optional: press Enter to skip it."
        ),
    },
    "CLI.WIZARD_CA_CERTS_PROMPT": {
        "es": "Ruta al bundle CA en PEM (Enter para omitir)",
        "en": "Path to the PEM CA bundle (Enter to skip)",
    },
    # Validation ladder run before persisting the profile
    "CLI.VALIDATE_ASK": {
        "es": (
            "¿Valido el perfil contra Netezza antes de guardarlo? Necesita red o VPN; si "
            "respondes que no, se guarda sin comprobar"
        ),
        "en": (
            "Validate the profile against Netezza before saving it? It needs network or VPN; "
            "answering no saves it unchecked"
        ),
    },
    "CLI.VALIDATE_HEADER": {
        "es": "Validando en tres niveles (todavía no se ha guardado nada):",
        "en": "Validating in three levels (nothing has been saved yet):",
    },
    # Shown while a ladder level is running; the result line below replaces it.
    "CLI.VALIDATE_CONNECT_RUNNING": {
        "es": "1/3 Conexión: abriendo sesión contra {host}:{port}",
        "en": "1/3 Connection: opening the session to {host}:{port}",
    },
    "CLI.VALIDATE_CATALOG_RUNNING": {
        "es": "2/3 Lectura del catálogo: consultando las bases de datos visibles",
        "en": "2/3 Catalog read: querying the visible databases",
    },
    "CLI.VALIDATE_DATABASE_RUNNING": {
        "es": "3/3 Visibilidad en {database}: consultando los esquemas",
        "en": "3/3 Visibility in {database}: querying the schemas",
    },
    "CLI.TEST_CONNECTION_RUNNING": {
        "es": "Conectando con {host}:{port} como {user}",
        "en": "Connecting to {host}:{port} as {user}",
    },
    "CLI.VALIDATE_CONNECT_OK": {
        "es": "1/3 Conexión: OK — Netezza responde: {detail}",
        "en": "1/3 Connection: OK — Netezza answers: {detail}",
    },
    "CLI.VALIDATE_CONNECT_FAIL": {
        "es": (
            "1/3 Conexión: FALLA — {detail}. Significa que no se pudo abrir la sesión: revisa "
            "host, puerto, usuario, password, la VPN y el nivel de seguridad."
        ),
        "en": (
            "1/3 Connection: FAIL — {detail}. It means the session could not be opened: check "
            "host, port, user, password, the VPN and the security level."
        ),
    },
    "CLI.VALIDATE_CATALOG_OK": {
        "es": "2/3 Lectura del catálogo: OK — el usuario ve {count} bases de datos.",
        "en": "2/3 Catalog read: OK — the user sees {count} databases.",
    },
    "CLI.VALIDATE_CATALOG_FAIL": {
        "es": (
            "2/3 Lectura del catálogo: FALLA — {detail}. Significa que la sesión abre pero la "
            "consulta a _v_database no funciona: revisa los permisos de lectura del catálogo."
        ),
        "en": (
            "2/3 Catalog read: FAIL — {detail}. It means the session opens but the _v_database "
            "query does not work: check the catalog read privileges."
        ),
    },
    "CLI.VALIDATE_CATALOG_EMPTY": {
        "es": (
            "2/3 Lectura del catálogo: FALLA — el usuario no ve ninguna base de datos. La "
            "cuenta existe pero no tiene permisos reales de lectura: pídeselos al DBA."
        ),
        "en": (
            "2/3 Catalog read: FAIL — the user sees no database at all. The account exists but "
            "holds no real read privilege: ask your DBA for one."
        ),
    },
    "CLI.VALIDATE_CATALOG_SKIPPED": {
        "es": "2/3 Lectura del catálogo: omitido porque falló el nivel anterior.",
        "en": "2/3 Catalog read: skipped because the previous level failed.",
    },
    "CLI.VALIDATE_DATABASE_OK": {
        "es": "3/3 Visibilidad en {database}: OK — el usuario ve {count} esquemas.",
        "en": "3/3 Visibility in {database}: OK — the user sees {count} schemas.",
    },
    "CLI.VALIDATE_DATABASE_FAIL": {
        "es": (
            "3/3 Visibilidad en {database}: FALLA — {detail}. Significa que no se pudieron "
            "listar los esquemas de esa base: comprueba que el nombre existe y que tu usuario "
            "puede leerla."
        ),
        "en": (
            "3/3 Visibility in {database}: FAIL — {detail}. It means the schemas of that "
            "database could not be listed: check that the name exists and that your user can "
            "read it."
        ),
    },
    "CLI.VALIDATE_DATABASE_EMPTY": {
        "es": (
            "3/3 Visibilidad en {database}: FALLA — el usuario no ve ningún esquema ahí. "
            "Conecta bien, pero no tiene GRANT sobre nada de esa base: pide permisos o elige "
            "otra base por defecto."
        ),
        "en": (
            "3/3 Visibility in {database}: FAIL — the user sees no schema there. It connects "
            "fine but holds no GRANT on anything in that database: ask for privileges or pick "
            "another default database."
        ),
    },
    "CLI.VALIDATE_DATABASE_SKIPPED": {
        "es": "3/3 Visibilidad en {database}: omitido porque falló un nivel anterior.",
        "en": "3/3 Visibility in {database}: skipped because an earlier level failed.",
    },
    "CLI.VALIDATE_ALL_OK": {
        "es": "Validación completa: los tres niveles han pasado.",
        "en": "Validation complete: the three levels passed.",
    },
    "CLI.VALIDATE_NOT_RUN": {
        "es": "Validación omitida: el perfil se guarda sin comprobar.",
        "en": "Validation skipped: the profile is saved unchecked.",
    },
    "CLI.VALIDATE_MENU": {
        "es": (
            "Nada de lo que has escrito se pierde. Puedes: [r] reintentar, [c] corregir un "
            "campo, [g] guardar de todos modos, [x] cancelar."
        ),
        "en": (
            "Nothing you typed is lost. You can: [r] retry, [c] fix one field, [g] save "
            "anyway, [x] cancel."
        ),
    },
    "CLI.VALIDATE_MENU_PROMPT": {
        "es": "Opción [r/c/g/x]",
        "en": "Choice [r/c/g/x]",
    },
    "CLI.VALIDATE_MENU_INVALID": {
        "es": "Opción no válida: {value}. Usa r, c, g o x.",
        "en": "Invalid choice: {value}. Use r, c, g or x.",
    },
    "CLI.VALIDATE_FIELD_PROMPT": {
        "es": "Campo a corregir ({fields})",
        "en": "Field to fix ({fields})",
    },
    "CLI.VALIDATE_FIELD_INVALID": {
        "es": "Campo desconocido: {value}. Campos válidos: {fields}.",
        "en": "Unknown field: {value}. Valid fields: {fields}.",
    },
    "CLI.VALIDATE_SAVED_ANYWAY": {
        "es": (
            "Guardado pese al fallo de validación: es lo normal si aún no tienes la VPN "
            "levantada. Cuando la tengas: nz-mcp test-connection --profile {profile}"
        ),
        "en": (
            "Saved despite the failed validation: that is expected when the VPN is not up "
            "yet. Once it is: nz-mcp test-connection --profile {profile}"
        ),
    },
    "CLI.WIZARD_CANCELLED": {
        "es": "Cancelado: no se ha escrito nada en {path} ni en el keyring.",
        "en": "Cancelled: nothing was written to {path} nor to the keyring.",
    },
    "CLI.CLAUDE_CONFIG_HEADER": {
        "es": (
            "Último paso — pega esto en claude_desktop_config.json (Claude Desktop > Ajustes > "
            "Desarrollador > Editar configuración) y reinicia Claude Desktop:"
        ),
        "en": (
            "Last step — paste this into claude_desktop_config.json (Claude Desktop > Settings "
            "> Developer > Edit config) and restart Claude Desktop:"
        ),
    },
    "CLI.CLAUDE_CONFIG_PATH_PLACEHOLDER": {
        "es": "<ruta absoluta de nz-mcp>",
        "en": "<absolute path to nz-mcp>",
    },
    "CLI.CLAUDE_CONFIG_PATH_UNKNOWN": {
        "es": (
            "No se ha podido determinar la ruta del ejecutable, así que 'command' lleva un "
            "marcador. Obtén la ruta con '{command}' y sustitúyelo antes de pegar el bloque: "
            "Claude Desktop no arranca con el PATH de tu terminal, y un 'nz-mcp' a secas no le "
            "funciona."
        ),
        "en": (
            "The executable path could not be determined, so 'command' carries a placeholder. "
            "Get the path with '{command}' and replace it before pasting the block: Claude "
            "Desktop does not start with your terminal PATH, and a bare 'nz-mcp' will not work "
            "for it."
        ),
    },
    "CLI.PROBE_SUGGESTION": {
        "es": (
            "Opcional, solo si algo se comporta raro: 'nz-mcp probe-catalog --profile {profile}' "
            "ejecuta todas las consultas del catálogo (lento y verboso; no hace falta para "
            "empezar)."
        ),
        "en": (
            "Optional, only if something behaves oddly: 'nz-mcp probe-catalog --profile "
            "{profile}' runs every catalog query (slow and noisy; not needed to get started)."
        ),
    },
    # nz-mcp doctor (CLI diagnostics — no secrets)
    "DOCTOR.HEADER": {
        "es": "Diagnóstico local (nz-mcp doctor)",
        "en": "Local diagnostics (nz-mcp doctor)",
    },
    "DOCTOR.BOOL_YES": {
        "es": "sí",
        "en": "yes",
    },
    "DOCTOR.BOOL_NO": {
        "es": "no",
        "en": "no",
    },
    "DOCTOR.NONE": {
        "es": "(ninguno)",
        "en": "(none)",
    },
    "DOCTOR.LABEL.NZ_MCP_VERSION": {
        "es": "Versión nz-mcp",
        "en": "nz-mcp version",
    },
    "DOCTOR.LABEL.PYTHON_VERSION": {
        "es": "Versión de Python",
        "en": "Python version",
    },
    "DOCTOR.LABEL.PLATFORM": {
        "es": "Plataforma",
        "en": "Platform",
    },
    "DOCTOR.LABEL.CONFIG_DIR": {
        "es": "Directorio de configuración",
        "en": "Configuration directory",
    },
    "DOCTOR.LABEL.EXISTS": {
        "es": "Existe",
        "en": "Exists",
    },
    "DOCTOR.LABEL.WRITABLE": {
        "es": "Escribible",
        "en": "Writable",
    },
    "DOCTOR.LABEL.PROFILES_PATH": {
        "es": "Ruta de perfiles",
        "en": "Profiles path",
    },
    "DOCTOR.LABEL.PROFILES_LOAD_OK": {
        "es": "Carga de perfiles OK",
        "en": "Profiles load OK",
    },
    "DOCTOR.LABEL.PROFILES_COUNT": {
        "es": "Número de perfiles",
        "en": "Profile count",
    },
    "DOCTOR.LABEL.PROFILES_NAMES": {
        "es": "Nombres de perfiles",
        "en": "Profile names",
    },
    "DOCTOR.LABEL.ACTIVE_PROFILE": {
        "es": "Perfil activo",
        "en": "Active profile",
    },
    "DOCTOR.LABEL.KEYRING_BACKEND": {
        "es": "Backend de keyring",
        "en": "Keyring backend",
    },
    "DOCTOR.LABEL.AVAILABLE": {
        "es": "Disponible",
        "en": "Available",
    },
    "DOCTOR.LABEL.LOCALE": {
        "es": "Idioma (locale)",
        "en": "Locale",
    },
    "DOCTOR.CRITICAL_HEADER": {
        "es": "Problemas críticos detectados:",
        "en": "Critical issues detected:",
    },
    "DOCTOR.CRITICAL.CONFIG_DIR_NOT_WRITABLE": {
        "es": "El directorio de configuración no es escribible.",
        "en": "The configuration directory is not writable.",
    },
    "DOCTOR.CRITICAL.KEYRING_UNAVAILABLE": {
        "es": "El backend de keyring no está disponible.",
        "en": "The keyring backend is unavailable.",
    },
    # probe-catalog CLI
    "PROBE_CATALOG.HEADER": {
        "es": "Diagnóstico de catálogo — perfil: {profile}",
        "en": "Catalog probe — profile: {profile}",
    },
    "PROBE_CATALOG.CONFIG_ERROR": {
        "es": "No se pudo ejecutar el probe de catálogo: {detail}",
        "en": "Cannot run catalog probe: {detail}",
    },
    "PROBE_CATALOG.LINE_OK": {
        "es": "[OK] {query_id} — {ms:.1f} ms, {rows} filas",
        "en": "[OK] {query_id} — {ms:.1f} ms, {rows} rows",
    },
    "PROBE_CATALOG.LINE_FAIL": {
        "es": "[FAIL] {query_id}: {detail}",
        "en": "[FAIL] {query_id}: {detail}",
    },
    "PROBE_CATALOG.LINE_WARN": {
        "es": "[WARN] {query_id} — no validado (falta objeto real): {detail}",
        "en": "[WARN] {query_id} — not validated (needs real object): {detail}",
    },
}


def resolve_locale(explicit: Locale | None = None) -> Locale:
    """Resolve locale: explicit > NZ_MCP_LANG env > LANG env > default."""
    if explicit in ("es", "en"):
        return explicit
    for env in ("NZ_MCP_LANG", "LANG"):
        value = os.environ.get(env, "").lower()
        if value.startswith("es"):
            return "es"
        if value.startswith("en"):
            return "en"
    try:
        loc = _std_locale.getdefaultlocale()[0]
        if loc and str(loc).lower().startswith("es"):
            return "es"
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return DEFAULT_LOCALE


def t(key: str, locale: Locale | None = None, **fmt: object) -> str:
    """Translate ``key`` to the target locale, formatting with ``fmt`` if needed.

    Raises ``KeyError`` if the key is unknown — fail loud, not silent.
    """
    msg = MESSAGES[key]
    loc = resolve_locale(locale)
    text = msg[loc]
    return text.format(**fmt) if fmt else text


def both(key: str, **fmt: object) -> dict[str, str]:
    """Return ``{"es": ..., "en": ...}`` rendered with ``fmt``."""
    msg = MESSAGES[key]
    return {
        "es": msg["es"].format(**fmt) if fmt else msg["es"],
        "en": msg["en"].format(**fmt) if fmt else msg["en"],
    }
