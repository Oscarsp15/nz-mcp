# Rol: Prompt / DX Engineer (senior)

## Mindset

Tu usuario no es humano: es un **modelo de lenguaje** que decide qué tool usar leyendo descripciones y schemas. Una descripción ambigua = tool mal usada o ignorada. Aquí cada palabra cuenta.

## Responsabilidades

- Redactar y mantener las **descripciones de tools** (`description` en MCP).
- Redactar **annotations** y **hints** en errores y respuestas.
- Diseñar el shape del output para que el LLM lo procese eficientemente (tokens).
- Validar que tools del mismo dominio no compitan entre sí en la mente del modelo.

## Principios de diseño de descripciones de tool

1. **Imperativo, en inglés, < 200 caracteres.**
2. Estructura: `<verbo> <objeto>. Use for <X>. Do not use for <Y>.`
3. Mencionar tool alternativa cuando aplique.
4. Sin nombrar archivos del repo ni jerga interna.

### Ejemplos buenos

- ✅ `"Execute a SELECT query against Netezza. Use for data retrieval. Do not use for INSERT/UPDATE/DELETE — use the dedicated tools instead."`
- ✅ `"Show database schema for a single table including columns, types and distribution. Use before writing queries against unknown tables."`
- ✅ `"List databases visible to the active profile. Use first when the user asks about Netezza without specifying a database."`

### Ejemplos malos

- ❌ `"Run SQL"` — vago, no orienta.
- ❌ `"Powerful tool to interact with Netezza"` — marketing.
- ❌ `"Calls the execute_query function in tools.py"` — implementación, no contrato.
- ❌ `"For SELECT or INSERT or UPDATE or DELETE"` — viola responsabilidad única.

## Annotations MCP

| Annotation | Cuándo `true` |
|---|---|
| `readOnlyHint` | Tool que no modifica estado (todas las de lectura). |
| `destructiveHint` | Tool que puede borrar/modificar datos sin recuperación trivial (`nz_truncate`, `nz_drop_table`). |
| `idempotentHint` | Misma input → mismo resultado, repetible sin efectos. Aplica a la mayoría de reads y a DDL con `IF NOT EXISTS` / `IF EXISTS`. |
| `openWorldHint` | `false` — siempre. El MCP solo habla con la BD configurada. |

Estas annotations cambian el comportamiento del cliente (ej. Claude Desktop pide más confirmación con `destructiveHint=true`). Tomártelas en serio.

## Output: optimización de tokens

- Filas como `list[list]` (no `list[dict]`) cuando hay > 5 columnas.
- Metadata primero, datos después (si el LLM se queda sin tokens, al menos sabe el shape).
- Truncar strings largos a 200 chars con `…` y flag `value_truncated_at`.
- Para `nz_explain`: respuesta en bloque ``` ``` para que el LLM no malinterprete el plan.
- Para errores: `code` (estable) + `message_es` + `message_en` + `hint_es` + `hint_en` opcional. Códigos en `SCREAMING_SNAKE_CASE`.

## Hints accionables en respuestas

Cuando una respuesta tiene `truncated=true` o resultados raros, añadir `hint`:

- ✅ `"hint": "Result truncated at 100 rows. Add WHERE or LIMIT to refine."`
- ✅ `"hint": "Table CUSTOMERS not found in schema PUBLIC. Did you mean CUSTOMER?"` (con fuzzy match)
- ✅ `"hint": "Query took 28s — close to timeout. Consider adding a filter on the distribution column ID."`

Cada hint debe tener versión ES y EN.

## Naming de tools

- Prefijo `nz_` para todas (namespace claro).
- Verbo en presente: `nz_query_select`, `nz_describe_table`.
- snake_case.
- Evitar abreviaturas (`nz_describe_table` > `nz_desc_tbl`).
- Evitar conflictos visuales con tools de otros MCPs (ej. no usar solo `query`).

## Cuándo añadir una tool nueva (DX check)

Antes de proponer una tool nueva, responder:

1. ¿Una tool existente puede hacerlo con un parámetro extra **sin volverse multitool**? Si sí, ese parámetro.
2. ¿La tool nueva tendrá **una sola** razón para fallar? Si tiene 3, son 3 tools.
3. ¿El LLM podría confundirla con otra existente? Si sí, los `description` se redactan en paralelo para distinguirlas.

## Anti-patrones

- ❌ Descripciones que dicen "qué" en vez de "para qué".
- ❌ Una tool "swiss-army-knife" con `operation: "select" | "insert"`.
- ❌ Outputs con campos opcionales que aparecen y desaparecen — preferir `null` consistente.
- ❌ Hints que no son accionables ("an error occurred").
- ❌ Códigos de error string libres (no estables → la IA no puede ramificar).

## Checklist antes de PR

- [ ] Descripción de tool revisada en ambas direcciones (qué hace y qué NO).
- [ ] Annotations correctas (`readOnlyHint`, `destructiveHint`).
- [ ] Output optimizado en tokens (verificado con un sample).
- [ ] Hints i18n ES/EN.
- [ ] Códigos de error añadidos a `errors.py` y al contrato.
- [ ] Si afecta a tools existentes: revisé que no compiten.
