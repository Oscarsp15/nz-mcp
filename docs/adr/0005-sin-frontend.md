# ADR 0005 — Sin frontend ni UI propia

- **Fecha**: 2026-04-16
- **Estado**: aceptado
- **Decidido por**: Tech Lead (IA) + validación humana

## Contexto

El protocolo MCP define tools, resources y prompts como JSON-RPC sobre transporte (stdio en nuestro caso). El cliente MCP (Claude Desktop, Claude Code, Cursor, etc.) renderiza:
- Diálogos de aprobación de tools.
- Resultados como Markdown.
- Listas de resources/prompts.

Algunos clientes experimentales soportan "MCP UI resources" (HTML/widgets embebidos), pero esto fragmenta soporte y multiplica superficie.

## Decisión

`nz-mcp` **no** incluye frontend, UI propia, ni assets HTML/CSS/JS. Todo lo que el usuario ve viene del cliente MCP renderizando nuestros outputs estructurados.

La "UX" que sí poseemos:
- Formato de outputs (tablas, JSON estructurado, hints).
- Descripciones de tools (lo que ve la IA).
- Mensajes de error i18n (lo que ve el usuario tras un fallo).
- CLI de configuración (`nz-mcp init`, etc.) — texto puro, sin TUI.

## Alternativas consideradas

1. **Soportar MCP UI resources** — innovador pero solo lo soportan algunos clientes en alpha; sumaría dep a frameworks web sin retorno claro. Diferido.
2. **Dashboard HTTP de admin** (logs, métricas) — sería app aparte, no parte del MCP; fuera de alcance de v0.1.
3. **TUI con `textual` para `nz-mcp init`** — bonito pero añade dep grande para un wizard de 5 preguntas. Rechazado.

## Consecuencias

- ✅ Cero deps frontend.
- ✅ Cero superficie de XSS, content security, CORS.
- ✅ El MCP sigue siendo "headless" y portable.
- ⚠️ Si en v1+ surge demanda real de UI embebida, este ADR se reemplaza tras evaluación.

## Monitorizar

- Adopción de MCP UI resources entre clientes (Claude Desktop, etc.).
- Issues que pidan dashboard / UI.
