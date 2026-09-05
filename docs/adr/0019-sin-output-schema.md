# ADR 0019 — Dejar de declarar `outputSchema` en `tools/list`

- **Fecha**: 2026-09-04
- **Estado**: aceptado
- **Decidido por**: Backend Developer (IA) + validación humana

## Contexto

El catálogo de `tools/list` se inyecta entero en cada sesión del cliente MCP: es coste fijo,
recurrente y anterior a cualquier trabajo útil. La carga diferida de tools es un mecanismo del
cliente, no del servidor, y Claude Desktop no la aplica; la única palanca del proyecto es que el
catálogo pese menos.

Medición del payload real (35 tools, 2026-09-04, JSON compacto; tokens estimados a 3,6 chars/token):

| Parte | Antes (chars) | Antes (tok) | Después (chars) | Después (tok) |
|---|---|---|---|---|
| Catálogo `tools/list` | 73.679 | 20.466 | 35.391 | 9.831 |
| — `inputSchema` | 22.236 | 6.177 | 22.236 | 6.177 |
| — `outputSchema` | 37.764 | 10.490 | 0 | 0 |
| — `description` | 8.078 | 2.244 | 8.078 | 2.244 |
| Respuesta `nz_export_ddl` | 3.933 | 1.092 | 2.257 | 627 |
| — `structuredContent` | 2.296 | 638 | 620 | 172 |

El `outputSchema` era el 51 % del catálogo. Además, en las tools de bloques (`output_kind` =
`content_blocks`) el servidor construía un `structuredContent` con los bloques re-serializados más
`meta`, y lo enviaba junto a `content` con esos mismos bloques: la misma información viajaba dos
veces en cada respuesta.

La spec MCP 2025-06-18 (sección Structured Content) declara `outputSchema` **opcional**; si se
declara, el servidor MUST devolver un `structuredContent` conforme y SHOULD acompañarlo de la
representación serializada en un bloque de texto. Duplicar los bloques completos va más allá de eso.

## Decisión

El servidor no declara `outputSchema` en `tools/list`, y en las tools de bloques `structuredContent`
lleva únicamente `meta`, sin re-serializar los bloques que ya viajan en `content`.

## Alternativas consideradas

1. **Mantener el esquema tal cual** — descartada: es el mayor coste recurrente por sesión y su único
   beneficio (validación en el cliente) no lo ejerce ningún cliente soportado hoy; el esquema es
   además un envoltorio `oneOf result/error` genérico, poco informativo por tool.
2. **Publicar un esquema minimizado** (solo `oneOf` de `result`/`error` sin propiedades) — descartada:
   conserva la obligación de emitir `structuredContent` conforme, no aporta pistas de tipo reales y
   sigue costando tokens en cada sesión.
3. **Quitar solo la duplicación y mantener el esquema** — descartada: dejaría declarado un esquema que
   ya no describe lo que se envía en las tools de bloques, e incumpliría el MUST de conformidad.

## Consecuencias

- Positivas: el catálogo baja de 20.466 a 9.831 tokens estimados (−52 %); la respuesta de
  `nz_export_ddl` baja de 1.092 a 627 (−43 %). El ahorro del catálogo es por sesión, no por llamada.
- Negativas / costes: se pierde la validación de salida del lado del cliente (y la que el SDK hacía
  contra el esquema declarado) y las pistas de tipo que el modelo podía leer antes de llamar. El
  contrato de salida sigue documentado en `docs/architecture/tools-contract.md`, que pasa a ser la
  única fuente de verdad de la forma del output.
- Cambio observable: un cliente que validase respuestas contra `outputSchema` deja de tener esquema;
  ninguno falla por su ausencia, porque la spec la contempla.
- Qué monitorizar: que ningún cliente soportado exija `outputSchema`, y que el modelo no aumente los
  errores de interpretación de salidas al no tener el esquema delante.

## Referencias

- Issue #166.
- Spec MCP 2025-06-18, sección Structured Content (`outputSchema` opcional).
- `src/nz_mcp/server.py` (`_to_mcp_tool`, handler de `tools/call`).
- Método de medición: script reproducible incluido en el PR (invoca los handlers de `tools/list` y
  `tools/call` en proceso y mide el JSON compacto resultante; no vuelca payloads).
