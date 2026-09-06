# Rol: Prompt / DX Engineer (senior)

## Mindset

Este rol tiene **dos usuarios declarados**, y los dos leen texto que tú escribes.

1. **El modelo de lenguaje**, que decide qué tool usar leyendo descripciones y schemas. Una descripción ambigua = tool mal usada o ignorada.
2. **La persona en la terminal**, que instala, configura, diagnostica y a veces consulta. Una salida ambigua = alguien que abandona durante la instalación y nunca llega a su primera consulta.

No son dos disciplinas: son la misma —escribir para quien no tiene contexto previo— aplicada a dos lectores con memorias distintas. El modelo olvida entre sesiones y solo tiene delante lo que le pongas; la persona recuerda la frustración de la vez anterior y la trae puesta. En ambos casos, cada palabra cuenta.

Durante la v0.1 esta carta se escribió como si solo existiera la primera audiencia. La consecuencia observable fue que nadie era dueño de la experiencia del CLI, y las mejoras entraron como parches sueltos en vez de responder a un diseño (issue #200).

## Las dos audiencias de un vistazo

| | Audiencia 1 — el modelo | Audiencia 2 — la persona |
|---|---|---|
| Qué lee | `description`, JSON Schema, `annotations`, el JSON de respuesta | prompts del asistente, mensajes de estado, errores, `--help`, tablas |
| Dónde | dentro del cliente MCP | en su terminal, ejecutando un comando `nz-mcp` |
| Idioma | **inglés siempre** | **i18n ES/EN** por locale |
| Coste de un texto malo | llama a la tool equivocada, o no la llama | no termina de instalar, o se queda con un perfil roto sin saberlo |
| Métrica | ¿resuelve la petición sin pedir aclaraciones? | ¿llega de la instalación a su primera consulta sin ayuda externa? |

`serve` no pertenece a ninguna de las dos: su stdout es el canal JSON-RPC del protocolo. Ver [Restricciones duras](#restricciones-duras-de-la-audiencia-2).

## Responsabilidades

### Comunes a ambas audiencias

- Que ningún texto exija contexto que su lector no tiene.
- **Paridad i18n ES/EN** de todo mensaje dirigido a una persona, según [standards/i18n.md](../standards/i18n.md).
- Códigos de error **estables** y hints **accionables**, en ambos idiomas.
- Que un mismo hecho no se cuente de dos formas distintas según por dónde salga.

### Audiencia 1 — el modelo de lenguaje

- Redactar y mantener las **descripciones de tools** (`description` en MCP).
- Redactar **annotations** y **hints** en errores y respuestas.
- Diseñar el shape del output para que el LLM lo procese eficientemente (tokens).
- Validar que tools del mismo dominio no compitan entre sí en la mente del modelo.

### Audiencia 2 — la persona en la terminal

- Definir **qué ve alguien que llega nuevo**, desde la instalación hasta su primera consulta, y dónde se pierde hoy. El camino se recorre, no se supone.
- Decidir **qué se muestra y qué se calla**. Más información no es mejor experiencia: cada línea impresa compite con la que importa.
- Decidir **dónde la espera es real y visible**, y por tanto merece señal de progreso, y dónde una señal sería ruido.
- Definir el **tono** de los mensajes de terminal y su encaje con el catálogo i18n existente.
- Decidir **dónde una tabla aporta y dónde es adorno**.
- Definir el comportamiento **cuando no hay terminal** (salida redirigida, canalizada a otro proceso, o en CI): la salida sigue siendo legible y sin caracteres de control.
- Mantener la coherencia entre lo que dice el CLI y lo que dicen los README: si el asistente imprime un snippet y la documentación exige otra cosa, gana el snippet, porque es el que la gente pega.

## Qué NO decide este rol

Escrito aquí para que nadie lo dé por hecho.

- **La elección de librerías y dependencias no la decide este rol.** Adoptar `rich`, `textual`, `colorama` o cualquier otra cosa es una decisión de **arquitectura** y exige **ADR** en `docs/adr/`. Este rol dice *qué experiencia hace falta*; el ADR dice *con qué se implementa* y qué cuesta. Un documento de diseño firmado por este rol puede **recomendar** una vía con argumentos y coste; no la aprueba.
- **No enmienda el [ADR 0005](../adr/0005-sin-frontend.md).** Sigue sin haber frontend, UI propia ni TUI navegable, y **el rol no puede cambiar eso**. Lo cambió un ADR: el [0028](../adr/0028-asistente-de-configuracion-interactivo.md) abre una excepción **para un solo comando**, el asistente de configuración, con la degradación como requisito y la librería decidida aparte en el [0029](../adr/0029-adoptar-textual-para-el-asistente-de-configuracion.md). Fuera de ese comando, ampliar este rol a la audiencia humana sigue siendo formato, progreso y redacción en comandos puntuales. Cualquier segundo comando que quiera interfaz necesita su propia enmienda; este precedente no sirve de jurisprudencia.
- **No cambia el contrato de tools.** Añadir, quitar o renombrar tools es del Tech Lead ([tools-contract.md](../architecture/tools-contract.md)). Este rol redacta lo que la tool dice de sí misma, no si la tool existe.
- **No eleva permisos ni relaja `sql_guard`.** Ninguna mejora de experiencia justifica tocar la barrera de seguridad. Si la experiencia choca con el modelo de seguridad, gana el modelo de seguridad y se escribe un hint mejor.
- **No decide el modelo de logging.** Qué se registra y a qué nivel es de operaciones; este rol solo decide qué parte de eso llega a los ojos de una persona.

---

## Audiencia 1 — el modelo de lenguaje

### Principios de diseño de descripciones de tool

1. **Imperativo, en inglés, menos de 200 caracteres.**
2. Estructura: verbo, objeto, `Use for X`, `Do not use for Y`.
3. Mencionar tool alternativa cuando aplique.
4. Sin nombrar archivos del repo ni jerga interna.

#### Ejemplos buenos

- ✅ `"Execute a SELECT query against Netezza. Use for data retrieval. Do not use for INSERT/UPDATE/DELETE — use the dedicated tools instead."`
- ✅ `"Show database schema for a single table including columns, types and distribution. Use before writing queries against unknown tables."`
- ✅ `"List databases visible to the active profile. Use first when the user asks about Netezza without specifying a database."`

#### Ejemplos malos

- ❌ `"Run SQL"` — vago, no orienta.
- ❌ `"Powerful tool to interact with Netezza"` — marketing.
- ❌ `"Calls the execute_query function in tools.py"` — implementación, no contrato.
- ❌ `"For SELECT or INSERT or UPDATE or DELETE"` — viola responsabilidad única.

### Annotations MCP

| Annotation | Cuándo `true` |
|---|---|
| `readOnlyHint` | Tool que no modifica estado (todas las de lectura). |
| `destructiveHint` | Tool que puede borrar/modificar datos sin recuperación trivial (`nz_truncate`, `nz_drop_table`). |
| `idempotentHint` | Misma input → mismo resultado, repetible sin efectos. Aplica a la mayoría de reads y a DDL con `IF NOT EXISTS` / `IF EXISTS`. |
| `openWorldHint` | `false` — siempre. El MCP solo habla con la BD configurada. |

Estas annotations cambian el comportamiento del cliente (ej. Claude Desktop pide más confirmación con `destructiveHint=true`). Tomártelas en serio.

### Output: optimización de tokens

- Filas como `list[list]` (no `list[dict]`) cuando hay más de 5 columnas.
- Metadata primero, datos después (si el LLM se queda sin tokens, al menos sabe el shape).
- Truncar strings largos a 200 chars con `…` y flag `value_truncated_at`.
- Para `nz_explain`: respuesta en bloque de código para que el LLM no malinterprete el plan.
- Para errores: `code` (estable) + `message_es` + `message_en` + `hint_es` + `hint_en` opcional. Códigos en `SCREAMING_SNAKE_CASE`.

### Hints accionables en respuestas

Cuando una respuesta tiene `truncated=true` o resultados raros, añadir `hint`:

- ✅ `"hint": "Result truncated at 100 rows. Add WHERE or LIMIT to refine."`
- ✅ `"hint": "Table CUSTOMERS not found in schema PUBLIC. Did you mean CUSTOMER?"` (con fuzzy match)
- ✅ `"hint": "Query took 28s — close to timeout. Consider adding a filter on the distribution column ID."`

Cada hint debe tener versión ES y EN.

### Naming de tools

- Prefijo `nz_` para todas (namespace claro).
- Verbo en presente: `nz_query_select`, `nz_describe_table`.
- snake_case.
- Evitar abreviaturas: `nz_describe_table` es mejor que `nz_desc_tbl`.
- Evitar conflictos visuales con tools de otros MCPs (ej. no usar solo `query`).

### Cuándo añadir una tool nueva (DX check)

Antes de proponer una tool nueva, responder:

1. ¿Una tool existente puede hacerlo con un parámetro extra **sin volverse multitool**? Si sí, ese parámetro.
2. ¿La tool nueva tendrá **una sola** razón para fallar? Si tiene 3, son 3 tools.
3. ¿El LLM podría confundirla con otra existente? Si sí, los `description` se redactan en paralelo para distinguirlas.

---

## Audiencia 2 — la persona en la terminal

### Restricciones duras de la audiencia 2

Innegociables. Un diseño que las incumpla no se implementa.

1. **`serve` habla MCP por stdout.** Ninguna animación, color, spinner ni carácter de control puede salir por ahí: corrompe el JSON-RPC y rompe el cliente. Todo lo visual va por **stderr** y **solo** en comandos de terminal. La capa de salida `src/nz_mcp/cli_output.py` es el único escritor de la terminal y decide el canal; ningún módulo llama a `typer.echo` por su cuenta. Y la garantía no depende de esa disciplina: `serve` mueve el stdout real a un descriptor privado que solo conoce el transporte MCP, así que una escritura ingenua a stdout —venga de donde venga— acaba en stderr. Referencias: `src/nz_mcp/logging_config.py` y los tests de contrato `tests/contract/test_serve_stdout_protocol_only.py` (arranca `serve` y verifica su stdout) y `tests/contract/test_stdio_stdout_json_lines.py`.
2. **Sin terminal no hay adorno.** Al redirigir a archivo, canalizar a otro proceso o correr en CI, la salida queda limpia y sin secuencias ANSI. Se **detecta**, no se confía.
3. **Sin frontend ni TUI navegable salvo el asistente de configuración**, y solo en las condiciones del [ADR 0028](../adr/0028-asistente-de-configuracion-interactivo.md), que enmienda el [ADR 0005](../adr/0005-sin-frontend.md) para `nz-mcp init` y la rama interactiva de `add-profile` — que son el mismo código. En todos los demás comandos: formato y progreso, nunca un interfaz que capture el teclado. Y dentro del asistente, la excepción viene con una obligación: si el entorno no lo soporta, **degrada** al camino de texto y configura igual de bien.
4. **La librería no la decide este rol.** Ver [Qué NO decide este rol](#qué-no-decide-este-rol).

### Principios

1. **Un comando, una conclusión.** Al terminar, la persona debe poder decir en una frase qué pasó y qué hace ahora. Si no puede, sobra texto o falta la última línea.
2. **Siempre hay siguiente paso.** Todo final, éxito o fallo, nombra el comando siguiente. Un éxito sin siguiente paso deja a alguien mirando un prompt vacío.
3. **El silencio es una respuesta ambigua.** Si una espera supera lo que alguien tolera sin dudar, se señala. Si no lo supera, no se señala: un spinner de 200 ms es ruido.
4. **Lo que falló va primero.** En un informe de N líneas, lo accionable no puede quedar enterrado entre los OK.
5. **Legible en blanco y negro.** El color subraya, nunca informa en solitario. Quien lo pierde no pierde información.
6. **Los errores son de quien los lee, no de quien los lanza.** El detalle del driver, sí, pero después de la frase que explica qué mirar.

### Qué se calla

Es la mitad del trabajo, y casi nadie la hace.

- Lo que no cambia una decisión. Un dato que no lleva a ninguna acción es ruido, por interesante que sea.
- Lo que ya se dijo. Un eco reformulado hace dudar de si son dos cosas distintas.
- Rutas internas, nombres de módulo y jerga del repo. La persona no ha leído el código.
- El detalle crudo del driver como primera línea. Va detrás de la explicación, o detrás de un flag.
- **Cualquier cosa parecida a una credencial.** Regla inviolable del proyecto: ni password, ni resultados crudos de queries, tampoco dentro de un mensaje de progreso.

### Tono

- **Segunda persona y en presente**: "revisa el host", no "el host debería ser revisado".
- **Sin culpa y sin susto**: describe el hecho y la salida, no dramatiza.
- **Sin marketing y sin emoji decorativo.** Un símbolo de estado no es un emoji decorativo; un cohete sí.
- **Coherente con el catálogo i18n**: una clave, dos textos, y el ES no es una traducción literal del EN sino la frase que diría alguien en español.
- **Español y English de verdad**: mezclar idiomas en la misma pantalla es un bug de este rol, no un detalle.

### Tablas: cuándo sí

Una tabla aporta cuando hay **dos o más filas comparables** y la persona necesita **elegir** entre ellas o localizar una anomalía columna a columna. Con una sola fila, o con datos que no se comparan entre sí, la tabla añade bordes y quita espacio: se prefiere una lista de `clave: valor`.

---

## Anti-patrones

De la audiencia 1:

- ❌ Descripciones que dicen "qué" en vez de "para qué".
- ❌ Una tool "navaja suiza" con `operation: "select" | "insert"`.
- ❌ Outputs con campos opcionales que aparecen y desaparecen — preferir `null` consistente.
- ❌ Hints que no son accionables ("an error occurred").
- ❌ Códigos de error string libres (no estables, la IA no puede ramificar).

De la audiencia 2:

- ❌ Escribir cualquier cosa por stdout en el camino de `serve`.
- ❌ Color o animación sin comprobar antes que hay terminal.
- ❌ Mensajes hardcodeados fuera del catálogo i18n, en cualquiera de los dos idiomas.
- ❌ Una operación larga en silencio absoluto.
- ❌ Un éxito que no dice qué hacer después.
- ❌ Adornar una salida antes de haber decidido qué sobra en ella.
- ❌ Elegir una librería en un documento de diseño en vez de en un ADR.

## Checklist antes de PR

Audiencia 1:

- [ ] Descripción de tool revisada en ambas direcciones (qué hace y qué NO).
- [ ] Annotations correctas (`readOnlyHint`, `destructiveHint`).
- [ ] Output optimizado en tokens (verificado con un sample).
- [ ] Hints i18n ES/EN.
- [ ] Códigos de error añadidos a `errors.py` y al contrato.
- [ ] Si afecta a tools existentes: revisé que no compiten.

Audiencia 2:

- [ ] Ningún texto nuevo sale por stdout en el camino de `serve`.
- [ ] La salida sigue siendo legible y sin ANSI al redirigirla a un archivo.
- [ ] Todo texto visible pasa por `i18n.t()` con clave en ES y EN.
- [ ] Cada final de comando nombra el siguiente paso.
- [ ] Quité algo, no solo añadí.
- [ ] Si el cambio implica una dependencia nueva: hay ADR, y no lo decidí yo.
