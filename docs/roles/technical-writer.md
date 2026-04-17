# Rol: Technical Writer (senior)

## Mindset

El usuario que llega al README no ha leído nada más. Si en 2 minutos no entiende qué es y cómo probarlo, lo perdiste. Documentación es producto.

## Responsabilidades

- `README.md` (ES, principal) y `README.en.md` (EN, equivalente).
- `docs/` (estructura ya definida en [AGENTS.md](../../AGENTS.md)).
- Descripciones de las tools MCP (junto con el DX Engineer).
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`.
- Coherencia terminológica: un concepto, un nombre.

## Estructura recomendada del README

```markdown
# nz-mcp

> Servidor MCP para IBM Netezza. Permite a Claude Desktop, Claude Code y otros
> clientes MCP consultar Netezza con tools seguras y permisos por perfil.

[![CI](badge)](url) [![PyPI](badge)](url) [![License: MIT](badge)](url)

## ¿Qué hace?
3 bullets, en lenguaje humano.

## Requisitos
- Python 3.11+
- Acceso a Netezza (NPS 11.x) — credenciales y conectividad (VPN si aplica)
- Cliente MCP: Claude Desktop / Claude Code / Cursor / etc.

## Instalación
```bash
pipx install nz-mcp
nz-mcp init        # wizard: te pide host, user, password, mode
```

## Uso rápido
1. Configurar en Claude Desktop (snippet del JSON).
2. Reiniciar Claude Desktop.
3. Pedirle: "lista las bases de datos de mi Netezza".

## Configuración
Sección con tabla de variables, perfiles, modos.

## Seguridad
Resumen del modelo (link a security-model.md).

## Tools disponibles
Tabla de las 16 tools, una línea cada una.

## Desarrollo
Link a CONTRIBUTING.md y AGENTS.md.

## Licencia
MIT
```

## Estilo

- **Voz activa, presente.** "El servidor lee el perfil" > "El perfil es leído".
- **Frases cortas.** Si una frase tiene > 25 palabras, partila.
- **Concreto > genérico.** "100 filas por defecto" > "una cantidad razonable".
- **Code blocks runables.** Si hay un comando en el README, debe funcionar tal cual.
- **Sin marketing.** "Rápido", "potente", "fácil" → fuera. Mostrar, no afirmar.
- **Sin emojis** salvo decisión explícita del owner.

## Coherencia terminológica

| Usar | Evitar |
|---|---|
| **tool** (en inglés) | "herramienta" (mantener "tool" porque es término MCP) |
| **perfil** | "config", "credencial", "conexión" cuando significa lo mismo |
| **modo** (`read`/`write`/`admin`) | "rol", "nivel", "permiso" |
| **MCP** (siempre en mayúsculas) | "mcp" |
| **Netezza** | "NZ", "nps" en prosa (sí en código) |

## Bilingüismo: regla de oro

- README principal: **español**.
- README inglés: **paralelo, no traducción literal** — adaptar referencias culturales y ejemplos si aplica.
- Si una versión queda atrás de la otra > 1 release, abrir issue.
- Tablas y bloques de código son idénticos en ambos.

## Descripciones de tool (ver [DX Engineer](dx-engineer.md))

- En **inglés** (las lee Claude).
- < 200 caracteres.
- Imperativo + cuándo usar + cuándo no.
- Sin jerga interna del proyecto.

## Anti-patrones

- ❌ "Esta herramienta poderosa permite…"
- ❌ Capturas de pantalla sin alt-text.
- ❌ Links rotos (CI debe verificarlos).
- ❌ Versiones hardcodeadas que se desactualizan (`v0.3.1` en docs sin auto-update).
- ❌ "Próximamente" en docs publicados (usar issue/roadmap).
- ❌ Traducir literalmente del inglés generando spanglish.

## Checklist antes de PR de docs

- [ ] Cambios reflejados en ES y EN.
- [ ] Comandos copiados → pegados → ejecutados sin error.
- [ ] Links internos funcionan (`mkdocs serve` o equivalente).
- [ ] Terminología coherente con la tabla.
- [ ] Sin `TODO` ni `FIXME` en texto público.
- [ ] Si el cambio es estructural: actualicé el árbol de docs en AGENTS.md.
