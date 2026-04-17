# Mantenibilidad y escalabilidad

## Principios

1. **Coste total < beneficio total.** Cada línea, dep, tool o abstracción cuesta para siempre. Justifícala.
2. **Un módulo, una razón de cambio.** Si un módulo cambia por dos motivos no relacionados, son dos módulos.
3. **Cambios locales > cambios globales.** Diseña para que añadir una tool nueva toque < 4 archivos.
4. **Open/Closed pragmático.** El registro de tools es abierto a extensión, cerrado a modificación. El `sql_guard` es cerrado a relajación, abierto a más estrictez.
5. **Velocidad sostenida > velocidad inicial.** Una decisión que ahorra 1 día hoy y cuesta 5 días en 6 meses es mala.

## Límites de complejidad

| Métrica | Umbral | Acción al pasar |
|---|---|---|
| Líneas por función | 50 | Refactorizar |
| Líneas por clase | 300 | Partir |
| Argumentos por función | 4 | Pasar dataclass / pydantic |
| Profundidad de anidamiento | 3 | Early returns / extraer función |
| Dependencias en `pyproject.toml` | 12 directas | ADR para añadir más |
| Diff por PR (líneas, sin tests/docs) | 400 | Justificar o partir |
| Cobertura | < 85 % | CI rojo |

`ruff` configurado para detectar funciones largas (`PLR0915`) y complejidad ciclomática (`C901`).

## Estructura escalable: añadir una tool nueva

Estos son los **únicos** archivos que deberían tocarse al añadir una tool:

1. `docs/architecture/tools-contract.md` — primero, antes de código.
2. `src/nz_mcp/tools.py` — registro + handler.
3. `src/nz_mcp/catalog.py` o `connection.py` — si necesita queries nuevas.
4. `src/nz_mcp/i18n.py` — si necesita mensajes nuevos.
5. `tests/unit/test_tools_<nombre>.py` — tests.
6. `CHANGELOG.md`.

Si añadir una tool obliga a tocar `server.py`, `sql_guard.py` o `auth.py`, **algo está mal en el diseño** — abrir issue y discutir antes.

## Registro extensible de tools

`tools.py` usa decoradores para registro:

```python
TOOLS: dict[str, Tool] = {}

def tool(*, name: str, description: str, mode: PermissionMode,
         input_model: type[BaseModel], output_model: type[BaseModel],
         annotations: dict | None = None):
    def deco(fn):
        TOOLS[name] = Tool(
            name=name, description=description, mode=mode,
            input_model=input_model, output_model=output_model,
            annotations=annotations or {}, handler=fn,
        )
        return fn
    return deco
```

Añadir una tool = añadir un decorador. Sin tocar el dispatcher.

## Catálogo de queries: separación

`catalog.py` agrupa queries al sistema (`_v_*`) por dominio:

```python
# catalog/databases.py    → list_databases, ...
# catalog/schemas.py      → list_schemas, ...
# catalog/tables.py       → list_tables, describe_table, get_table_ddl, ...
# catalog/views.py        → list_views, get_view_ddl
# catalog/procedures.py   → list_procedures, get_procedure_ddl, ...
# catalog/stats.py        → table_stats
```

(En v0.1 puede vivir todo en `catalog.py` único; partir cuando supere ~300 líneas.)

## Deuda técnica

- **Visible**: si haces atajo, abre issue con label `tech-debt` **en el mismo PR**.
- **Acotada**: cada deuda lleva trigger de pago ("cuando llegue X usuario", "antes de v1.0", "si bug Y reaparece").
- **Sin deuda silenciosa**: `# TODO` solo si referencia issue (`# TODO(#123): ...`).

## Cambios incompatibles

- Cualquier cambio observable por usuario (tool removida, schema cambiado, código de error renombrado) requiere:
  - ADR explicando por qué.
  - Bumpear `MINOR` en v0.x o `MAJOR` en v1+.
  - Entrada `Changed` o `Removed` en CHANGELOG con migración.
  - Ventana de deprecación de al menos una `MINOR` cuando sea posible.

## Refactor seguro

- Refactor = cambio de forma sin cambio de comportamiento. Tests verdes antes y después.
- PR de refactor **no** mezcla cambios funcionales. Si encuentras un bug refactorizando, abre PR aparte.
- Si refactor toca > 5 archivos: ADR.

## Performance

- Optimizar **después** de medir, nunca antes.
- Si añades una optimización: micro-benchmark en tests (`pytest-benchmark` opcional, marcar `@pytest.mark.slow`).
- Documentar el "antes" y el "después" en el PR.

## Observabilidad incremental

v0.1: logs estructurados. Suficiente para auditar y depurar.
v0.2+ (cuando justifique): métricas (tools llamadas, duración, errores) → expuestas como `nz_self_metrics` tool. ADR primero.

## Archivos prohibidos en el repo

Las IAs tienden a fabricar archivos de "auto-ayuda" mientras trabajan: `notes.md` para pensar, `plan.md` para estructurarse, `scratch.py` para probar, `analysis.md` para razonar. **Ninguno entra al repo**.

### Defensa en profundidad (4 capas)

1. **Whitelist explícita** de paths permitidos en `scripts/check_no_scratch.py`:
   - **Root**: `AGENTS.md`, `README.md`, `README.en.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `LICENSE`, `SECURITY.md`, `pyproject.toml`, `.gitignore`, `.python-version`, `.pre-commit-config.yaml`, `.secrets.baseline`.
   - **Directorios top-level**: `src/`, `tests/`, `docs/`, `.github/`, `scripts/`.
2. **Blacklist de patrones** de nombre y directorios (regex case-insensitive). Cubre `notes`, `notas`, `scratch`, `todo`, `plan`, `wip`, `draft`, `borrador`, `analysis`, `tmp`, `temp`, `debug`, `sandbox`, `playground`, `local_test`, `test_local`, `deleteme`, `borrame`, `untitled`, sufijos `*.bak/.orig/.swp/.tmp/.log`, dirs `.scratch/`, `.aider/`, `.cursor/`, `agent_workspace/`, etc.
3. **Hook pre-commit** (`no-scratch-files`) rechaza el commit local antes del push.
4. **CI obligatorio** (`No scratch files` en `validate-conventions.yml`) bloquea el merge incluso si el dev usa `--no-verify`.

### ¿Y si necesito pensar?

- **Sí**: usa `/tmp/<algo>.md`, tu área de runtime, comentarios en el PR, o un issue de tracking en GitHub.
- **No**: nada dentro del clone del repo, aunque esté en `.gitignore` (lo correcto: que ni exista en el directorio).

### ¿Y si añado una capacidad nueva legítima que no encaja en la whitelist?

1. Abre PR que **añade el path a la whitelist** en `scripts/check_no_scratch.py`.
2. Justifica con ADR (`type/adr` issue + ADR en `docs/adr/`).
3. Owner aprueba expansión de la whitelist.

**Whitelists son contrato, no impulso. Cada nueva entrada se debate.**

### Anti-patrones rechazados automáticamente

- ❌ `notes.md`, `plan.md`, `analysis.md` en root o dentro de cualquier dir.
- ❌ `scratch.py`, `tmp.py`, `playground/`, `sandbox.py`.
- ❌ `TODO.md`, `WIP.txt`, `borrador.md`, `untitled.md`.
- ❌ Backups: `*.bak`, `*.orig`, `*.swp`, `*.tmp`, `*.log`, `*~`.
- ❌ Dirs de IA: `.scratch/`, `.aider/`, `.cursor/`, `.windsurf/`, `agent_workspace/`.
- ❌ Cualquier dir top-level fuera de `src/tests/docs/.github/scripts/`.

## Qué NO hacer (anti-patrones de mantenibilidad)

- ❌ Helper "utils.py" cajón de sastre.
- ❌ Configuración por subclase (en vez de composición).
- ❌ Singletons ocultos (módulos con estado mutable global).
- ❌ Magic strings repetidos (extraer a `Final` constants).
- ❌ Romper la convención "un PR, una intención".
- ❌ Refactor "preventivo" sin caso de uso.
- ❌ Añadir framework para 1 caso ("por si lo necesitamos en el futuro").

## Crecimiento esperado y plan

| Fase | Objetivo | Rango de tools | Cuándo |
|---|---|---|---|
| v0.1 | MVP read+write+DDL+SP/views | ~22 | Primera release |
| v0.2 | Hardening, métricas internas, observabilidad básica | +3 | Tras feedback inicial |
| v0.3 | Self-hosted runner para integration en CI | mismo | Cuando haya contributors |
| v1.0 | Estabilización contrato, ventana de deprecaciones | estable | Tras 3 meses de uso real |

## Checklist (mantenibilidad)

- [ ] Mi PR cae en los archivos esperados según [límites de complejidad](#estructura-escalable-añadir-una-tool-nueva).
- [ ] No añadí abstracción sin tercer caso de uso.
- [ ] No añadí dep nueva sin ADR.
- [ ] No subí complejidad ciclomática de un módulo.
- [ ] No introduje deuda silenciosa.
- [ ] CHANGELOG refleja cualquier cambio observable.
