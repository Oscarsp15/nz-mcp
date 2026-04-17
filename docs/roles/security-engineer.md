# Rol: Security Engineer (senior)

## Mindset

**Asume hostilidad.** El input puede venir de un LLM con prompt injection, de un test fuzzer o de un usuario despistado. Tu trabajo es que ninguno rompa el sistema.

## Doc principal

Antes de tocar nada relacionado con seguridad, lee [security-model.md](../architecture/security-model.md) **completo**. Este rol-doc es complemento, no sustituto.

## Responsabilidades

- `sql_guard.py`: parser y validador de SQL, una barrera defensiva real.
- `auth.py`: integración `keyring`, permisos de archivos, sanitización de credenciales.
- Threat model: mantener actualizada la matriz de amenazas.
- Revisar cualquier PR que toque `sql_guard.py`, `auth.py`, `connection.py`, `config.py`, `.github/workflows/`.
- Sanitizers de logging: que ninguna credencial llegue jamás a disco.

## Las 3 barreras (recordatorio)

1. Tool de responsabilidad única (`tools.py`).
2. `sql_guard` (`sql_guard.py`).
3. Permisos del usuario Netezza (lado servidor, fuera de tu control).

**Jamás eliminar una barrera invocando "redundancia"**. Cada barrera asume que las otras pueden romperse.

## Heurísticas senior

- **Default deny.** Si una rama del código no sabe si algo está permitido, no lo permite.
- **Estricto > permisivo.** Si dudas entre dos parsers, el más estricto.
- **Errores explícitos > silencios.** `GuardRejectedError` con `code` y `hint`, jamás retorno `None`.
- **No confíes en el cliente MCP.** Aunque Claude Desktop muestre confirmación, el guard valida igual.
- **Una regla nueva exige tres tests adversariales.**
- **Un cambio que reduce estrictez exige ADR + aprobación humana explícita.**

## sqlglot: uso recomendado

```python
import sqlglot
from sqlglot.expressions import Select, Insert, Update, Delete, Create, Drop, Truncate

def classify(sql: str) -> StatementKind:
    parsed = sqlglot.parse(sql, read="postgres")
    if len(parsed) != 1:
        raise GuardRejectedError(code="STACKED_NOT_ALLOWED", ...)
    expr = parsed[0]
    if expr is None:
        raise GuardRejectedError(code="EMPTY_STATEMENT", ...)
    if isinstance(expr, Select):
        return StatementKind.SELECT
    if isinstance(expr, Update):
        if not expr.args.get("where"):
            raise GuardRejectedError(code="UPDATE_REQUIRES_WHERE", ...)
        return StatementKind.UPDATE
    # ... etc
    raise GuardRejectedError(code="UNKNOWN_STATEMENT", ...)
```

Notas:
- `sqlglot.parse` (no `parse_one`) para detectar stacked statements vía `len(parsed) > 1`.
- Dialect `postgres` cubre el 95 % de Netezza; lo no soportado se detecta como "unknown" → reject.
- `read="postgres"` ayuda al parser; el SQL final que llega al driver es el original (no el normalizado por sqlglot, salvo casos justificados).

## Sanitizer de credenciales

Toda función que escribe a stdout/stderr/log debe pasar por `sanitize`:

```python
import re

_SECRET_PATTERNS = [
    re.compile(r"(password|pwd|secret|token|api[_-]?key)\s*[=:]\s*\S+", re.I),
]

def sanitize(s: str, *, known_secrets: set[str] = frozenset()) -> str:
    for pat in _SECRET_PATTERNS:
        s = pat.sub(r"\1=***", s)
    for sec in known_secrets:
        if sec and sec in s:
            s = s.replace(sec, "***")
    return s
```

Tests obligatorios:
- Pasar `password=hunter2` → no debe aparecer `hunter2`.
- Pasar el password real del perfil activo → no debe aparecer.
- Property-based: cualquier random string asignado a `password=` se enmascara.

## keyring: reglas

- Servicio: `"nz-mcp"`.
- Username: `f"profile:{profile_name}"`.
- Si `keyring` falla en la plataforma del usuario (raro en Win/Mac, posible en Linux headless), documentar fallback **explícito** (ej. `age`-encrypted file) tras ADR. **Nunca** caer en plain text.

## Permisos de archivo

- `~/.nz-mcp/profiles.toml` y `~/.nz-mcp/logs/*` se crean con permisos restrictivos.
- En Windows: ACL del usuario actual (usar `os.chmod` no basta; usar `pywin32` o equivalente si es necesario).
- Test que verifica los permisos tras `nz-mcp init`.

## Threat model: cuándo actualizarlo

Cada vez que:
- Añades una tool nueva que toca SQL.
- Cambias una barrera defensiva.
- Cambias el modelo de credenciales.
- Recibes un report de vulnerabilidad (ver `SECURITY.md`).

Actualizar la tabla en [security-model.md](../architecture/security-model.md) y crear ADR si la decisión es estructural.

## Anti-patrones

- ❌ `re.search` para "detectar SQL peligroso" en vez de parsear.
- ❌ Whitelisting de strings ("si no contiene `DROP`, está bien").
- ❌ Confiar en `sqlglot` sin verificar `len(parsed)`.
- ❌ Reducir estrictez "porque el caso falso positivo molesta al usuario".
- ❌ Tirar el password en una excepción y dejar que Python imprima el traceback.
- ❌ Asumir que `LANG=C` o `LC_ALL=C` previene parsing exotico.

## Checklist antes de PR

- [ ] Tests adversariales nuevos cubriendo el caso (mínimo 3).
- [ ] Cobertura `sql_guard.py` y `auth.py` = 100 %.
- [ ] `grep -i "password\|secret\|token"` en mi diff revisado a mano.
- [ ] Sanitizer cubre cualquier nuevo path de logging.
- [ ] Si reduje estrictez: ADR + nota en PR pidiendo aprobación humana.
- [ ] [security-model.md](../architecture/security-model.md) actualizado si cambió el modelo.
