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
    # Permissions
    "PERMISSION_DENIED.MODE_TOO_LOW": {
        "es": "La operación requiere modo '{required}' pero el perfil tiene '{actual}'.",
        "en": "Operation requires mode '{required}' but the profile has '{actual}'.",
    },
    # Profile / config
    "PROFILE_NOT_FOUND": {
        "es": "No existe el perfil '{profile}'. Crea uno con: nz-mcp add-profile.",
        "en": "Profile '{profile}' does not exist. Create one with: nz-mcp add-profile.",
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
    "NETEZZA_ERROR": {
        "es": "Netezza devolvió un error durante '{operation}': {detail}",
        "en": "Netezza returned an error during '{operation}': {detail}",
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
    "NOTE.DDL_RECONSTRUCTED": {
        "es": "DDL reconstruido desde catálogo (SHOW TABLE no disponible en este servidor).",
        "en": "DDL reconstructed from catalogs (SHOW TABLE not available on this server).",
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
