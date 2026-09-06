# Diseño de la experiencia del CLI

- **Fecha**: 2026-09-05
- **Estado**: propuesto — pendiente de validación del owner
- **Issue**: [#201](https://github.com/Oscarsp15/nz-mcp/issues/201) (depende de [#200](https://github.com/Oscarsp15/nz-mcp/issues/200))
- **Rol**: DX Engineer, con el alcance ampliado en [roles/dx-engineer.md](../roles/dx-engineer.md) (auditor: Tech Lead)
- **Alcance**: qué experiencia hace falta. **No** decide con qué librería se implementa; eso es un ADR aparte.

## 0. Dirección y método

Dirección del owner, literal, del 2026-09-05: *"me gustaría que se vea muy bien estéticamente y amigable, buenas animaciones lo necesario, llamativo"*. Es una decisión de producto y este documento diseña para ella.

Método: en vez de suponer, se recorrió el camino leyendo `src/nz_mcp/cli.py`, `README.md`, `README.en.md` y `docs/guides/claude-desktop-setup.md`, y se ejecutó el CLI. Todo lo que este documento afirma sobre el estado actual está verificado; donde hay una duda, se dice que la hay.

Un aviso sobre la palabra *llamativo*: el modo barato de cumplirla es pintar. El modo caro, y el que se propone aquí, es que el CLI parezca que sabe lo que hace. Un producto se ve bien cuando no te deja solo, no cuando tiene más colores. Por eso la mitad de este documento es la sección 4, la de lo que se calla.

---

## 1. Qué siente alguien que llega nuevo

Recorrido real desde `pipx install` hasta la primera consulta. Siete paradas, y se pierde en cinco.

### Parada 1 — `pipx install nz-mcp` falla

La versión publicada es `0.1.0a3`, una prerelease, y `pip` no instala prereleases por defecto. El README abre con un bloque titulado "Camino automático (tres comandos)" cuyo **primer comando no funciona**, y pone la salvedera (`--pip-args=--pre`) en una cita, **después** del bloque. Alguien que copia los tres comandos —que es exactamente lo que invita a hacer un bloque titulado así— recibe un error de resolución antes de haber visto nada del producto.

Lo mismo en `README.en.md`. El primer contacto con nz-mcp es, hoy, un fallo.

### Parada 2 — `nz-mcp` a secas no orienta

`no_args_is_help=True`, así que se ve la ayuda. Tres problemas, todos verificados ejecutándola:

- **Está en inglés siempre**, incluso con `NZ_MCP_LANG=es`. Los textos vienen de los docstrings de las funciones, que por la regla del proyecto van en inglés y no pasan por el catálogo i18n. Dos minutos después, el asistente le hablará en español. La primera impresión es un producto que no sabe en qué idioma habla.
- **No hay punto de entrada.** Los once comandos salen en orden de registro: el primero es `version` y el último `serve`. Nada dice "empieza por `init`". El comando más importante para quien acaba de instalar es el segundo de una lista alfabéticamente arbitraria.
- **Filtra jerga interna.** `switch-profile` se describe como *"same logic as the nz_switch_profile tool"* —un nombre de tool MCP que esta persona no ha visto nunca— y `test-connection` muestra literalmente los dobles backticks de reStructuredText: *"run ``VERSION()``"*. Ambas cosas incumplen la regla 4 de descripciones del propio rol.

Y un cuarto, de plataforma: en una consola de Windows con página de códigos heredada, la raya de `doctor` sale como `?` (*"keyring ? no Netezza"*). Comprobado en este entorno. El texto no ASCII no es seguro por defecto en el destino principal de este producto.

### Parada 3 — `nz-mcp init`: la mejor parte, y aun así a oscuras

El asistente es lo más cuidado del CLI y este diseño no lo desmonta. Explica cada concepto no obvio antes de preguntarlo (`WIZARD_MODE_EXPLAIN`, `WIZARD_SECURITY_EXPLAIN`, `WIZARD_CA_CERTS_EXPLAIN`), guarda un borrador en memoria y, si la validación falla, deja reintentar, corregir un solo campo, guardar igualmente o cancelar sin perder nada. Eso está bien resuelto y se conserva.

Lo que falla es el ritmo:

- Ocho preguntas seguidas **sin noción de cuántas quedan**. No se sabe si esto dura treinta segundos o cinco minutos.
- Antes de validar, **no hay recapitulación**. Se acaba de teclear un host, un puerto y un usuario y no se vuelven a ver juntos nunca.

### Parada 4 — la escalera de validación: el silencio más largo del producto

`_validate_before_saving` imprime la cabecera *"Validando en tres niveles"* y a continuación llama a `run_checks`, que abre una sesión TCP contra Netezza, normalmente a través de una VPN. **Ahí no sale nada.** Si el host no responde, el silencio dura hasta que expira el timeout del driver. Cuando por fin aparece algo, aparecen las tres líneas de golpe.

Es la espera más larga de todo el recorrido y es la única sin ninguna señal. Alguien con la VPN caída no puede distinguir "está intentándolo" de "se ha colgado", y la reacción natural —Ctrl+C— tira a la basura las ocho respuestas.

### Parada 5 — el final del asistente: tres siguientes pasos a la vez

Al guardar, se imprimen cuatro bloques seguidos:

1. `PROFILE_SAVED` — perfil guardado.
2. `PROFILE_NEXT_STEP` — *"Siguiente paso: prueba la conexión con `nz-mcp test-connection`"*.
3. `CLAUDE_CONFIG_HEADER` + el JSON — *"**Último paso** — pega esto en `claude_desktop_config.json`"*.
4. `PROBE_SUGGESTION` — *"Opcional, solo si algo se comporta raro: `nz-mcp probe-catalog`"*.

Hay un "siguiente paso" y un "último paso" que se contradicen entre sí, más un tercer comando opcional, todo en el momento en que la persona lleva ocho preguntas encima y menos ganas tiene de elegir. Tres llamadas a la acción compitiendo equivalen a ninguna.

### Parada 6 — el snippet que se pega está mal (defecto real)

Es el hallazgo más caro del recorrido. `_claude_desktop_snippet` genera:

```json
{ "mcpServers": { "netezza": { "command": "nz-mcp", "args": ["serve"], ... } } }
```

Y `docs/guides/claude-desktop-setup.md`, línea 22, dice lo contrario con todas las letras: *"`command` apunta a **esa ruta completa**, no a un `nz-mcp` cualquiera del `PATH`: Claude Desktop no arranca con el `PATH` de tu terminal"*. El README repite la advertencia.

O sea: **la documentación sabe que un `command` sin ruta absoluta falla, y el asistente imprime exactamente eso**, ya formateado y listo para copiar. Y el snippet gana siempre, porque es lo que se pega y la advertencia es lo que se salta. El fallo además es silencioso y diferido: Claude Desktop simplemente no arranca el servidor, y el diagnóstico está a tres capas de distancia, en un log de la aplicación.

### Parada 7 — la primera consulta ocurre donde el CLI ya no está

La primera consulta se hace en Claude Desktop, no en la terminal. El CLI acompaña hasta la puerta y ahí suelta la mano: no dice qué frase pedirle al asistente para comprobar que funciona. El README sí lo dice (*"lista las bases de datos de mi Netezza"*), pero para entonces ya nadie está leyendo el README, está mirando la terminal.

### Diagnóstico en una frase

El CLI no es feo: **es mudo en los tres momentos que deciden si alguien se queda** —cuando espera, cuando termina y cuando entrega el snippet que hay que pegar— y esos tres momentos no se arreglan con color.

---

## 2. Restricciones que este diseño no se salta

### R1 — `serve` habla MCP por stdout

Nada visual puede salir por stdout en el camino de `serve`. Ni animación, ni color, ni un byte de más: corrompe el JSON-RPC y rompe el cliente.

**Estado hoy, verificado — y es un hallazgo:**

- `serve_cmd` llama primero a `configure_logging_for_stdio()`, que manda el logging estándar y structlog a stderr y baja a WARNING los loggers ruidosos (`nzpy`, `mcp`). Correcto.
- `serve_cmd` no imprime nada por su cuenta. Correcto.
- Existe el test de contrato `tests/contract/test_stdio_stdout_json_lines.py`, que comprueba que structlog no ensucia stdout.

Pero:

- **La separación existe de hecho, no por construcción.** No hay ninguna capa de salida: `cli.py` llama a `typer.echo` / `typer.secho` directamente en más de veinte sitios, y ambas escriben a **stdout** por defecto. Que `serve` esté limpio depende de que nadie añada un `typer.echo` en su camino, ni en él ni en ningún módulo que importe.
- **El test existente cubre structlog, no el comando.** Verifica que una llamada a structlog no acabe en stdout; no ejecuta `nz-mcp serve` ni comprueba que ese comando no emita nada antes del primer byte JSON-RPC. La regresión que este rediseño hace más probable —un adorno mal ubicado— no la detectaría.

Conclusión: **hoy está bien, y hoy está desprotegido.** Pintar el CLI sin poner antes la barrera es exactamente el orden equivocado. Por eso el primer issue de implementación es la barrera, no la pintura.

### R2 — Sin terminal, la salida queda limpia

Al redirigir a archivo, canalizar a otro proceso o correr en CI: sin ANSI, sin animación, sin caracteres de control. Se detecta, no se confía.

Media buena noticia verificada: `typer.secho` delega en `click.echo`, que **ya** elimina los códigos ANSI cuando el destino no es un terminal. Ese comportamiento se hereda gratis hoy y se conserva. Pero solo cubre lo que pasa por `click.echo`: un spinner escrito a mano o un renderizador de terceros no lo heredan, y ahí es donde se rompería. La detección tiene que vivir en la capa de salida, en un solo sitio, y respetar además `NO_COLOR` y `TERM=dumb`.

### R3 — ADR 0005 sigue vigente

Sin frontend, sin UI propia, sin TUI navegable. Esto es formato y progreso en comandos puntuales. Nada de este diseño captura el teclado, dibuja pantallas ni ofrece menús navegables. El menú de cuatro opciones del asistente, que ya existe, es un `prompt` de una letra, no una TUI.

> **Enmienda posterior (2026-09-06).** El [ADR 0028](../adr/0028-asistente-de-configuracion-interactivo.md) permite un interfaz de pantalla completa **en el asistente de configuración y solo en él**, con la degradación al camino de texto como requisito. Todo lo que este documento decide sobre los otros diez comandos sigue igual, y el menú de cuatro opciones sigue existiendo: es el que corre cuando el asistente degrada, y el que se ejecuta tras la escalera de validación en los dos caminos.

### R4 — La librería no la decide este documento

Ver sección 7.

---

## 3. Dónde la espera es real, y qué se enseña mientras

Regla, para no poner indicadores porque sí: **se señala una espera cuando puede superar aproximadamente un segundo y el CLI no puede saber de antemano cuánto va a durar.** Por debajo de eso, un indicador es parpadeo, no información.

| Momento | ¿Espera real? | Qué se muestra |
|---|---|---|
| Escalera del asistente, nivel 1 (conexión) | **Sí**, la peor: red + VPN + TLS, hasta el timeout | Indicador indeterminado nombrando el nivel en curso, que la línea de resultado sustituye al terminar |
| Escalera, niveles 2 y 3 (catálogo, esquemas) | **Sí**, una consulta cada uno | Igual, uno cada vez |
| `test-connection` | **Sí**, es el nivel 1 solo | Indicador indeterminado |
| `probe-catalog` | **Sí, la más larga**: 14 consultas seguidas, hoy en silencio absoluto | Progreso **determinado** `n/14` y cada consulta impresa al terminar, no al final |
| `doctor` | No: todo local, milisegundos | Nada. Ni spinner ni barra |
| `list-profiles`, `version`, `switch-profile`, `edit-profile` | No: leen o escriben un TOML | Nada |
| Preguntas del asistente | No: la espera es humana | Nada. Un spinner mientras alguien piensa es una falta de respeto |
| Exportaciones de DDL grandes | **No aplica** | Ver más abajo |

Tres decisiones de fondo:

**`probe-catalog` es el caso donde una barra es honesta.** El total es conocido —14 consultas registradas en `ALL_QUERIES`— así que `n/14` no se lo inventa nadie. Es el único sitio del CLI con un denominador real. En todos los demás, Netezza no informa del avance de una consulta y una barra con porcentaje sería una mentira animada; se usa indicador indeterminado.

**Lo importante de `probe-catalog` no es el spinner, es que hoy imprime tarde.** `run_probe_catalog` devuelve el `ProbeRun` completo y solo entonces se imprime nada: durante las catorce consultas la pantalla está vacía. Emitir cada línea según se resuelve vale más que cualquier animación, porque además dice *en cuál* se ha atascado. Es la diferencia entre decorar la espera y quitarla.

**Las exportaciones de DDL grandes, que el issue listaba como candidato, no son una superficie del CLI.** Comprobado: `nz_export_ddl` es una tool MCP y no existe ningún comando de terminal equivalente entre los once. Su "progreso" se lo comería el contexto del modelo, que paga tokens por él. **No se les pone indicador y no se abre issue.** Es el candidato que este diseño descarta.

---

## 4. Qué se muestra y qué se calla

La parte que casi nadie diseña. Cada línea impresa compite con la línea que importa, así que aquí hay tanto de quitar como de poner.

### Se calla: nueve de cada catorce líneas de `probe-catalog`

Hoy imprime las catorce, la mayoría `[OK]`, y entierra los fallos entre ellas. Propuesta:

- Por defecto: los `[FAIL]` y los `[WARN]` **primero**, y una sola línea de cierre —*"11 de 14 consultas OK"*—. Lo accionable arriba, lo tranquilizador en resumen.
- `--verbose`: las catorce, en tabla.
- `--json`: **intacto**. Es superficie de máquina y no se toca ni se traduce.

### Se calla: la sugerencia de `probe-catalog` al final del asistente

`PROBE_SUGGESTION` se imprime siempre, en el camino de éxito, y su propio texto reconoce que no hace falta (*"Opcional, solo si algo se comporta raro"*). Un consejo que solo sirve cuando algo va mal no se da cuando todo ha ido bien: se da cuando algo va mal. **Se elimina del final feliz** y se mueve a donde la validación falla, que es donde tiene sentido. Un mensaje menos en el peor momento posible para leer.

### Se calla: el detalle crudo del driver como primera línea

`test-connection` imprime hoy `FAIL: {detail}` con el texto del driver por delante. Se invierte: primero la causa clasificada y qué hacer, después el detalle. La clasificación ya existe (`AUTH_REJECTED`, `HOST_UNREACHABLE`, `TLS_FAILED`, `DATABASE_UNAVAILABLE`, `UNKNOWN`, documentada en el README) y hoy se desaprovecha por el orden.

### Se calla: el ruido interno en la ayuda

Nombres de tools MCP, nombres de archivo internos y marcas de reStructuredText fuera de `--help`. Quien lee la ayuda no ha leído el código.

### Se muestra más: la conclusión, en todas partes

- `doctor` termina hoy en *"Idioma (locale): es"* y el veredicto vive solo en el código de salida, que nadie mira. **El informe completo se conserva** —está pensado para pegarlo en un issue y ahí la completitud es la gracia—, pero gana una primera línea con el veredicto y una última con el siguiente paso.
- El asistente gana una recapitulación antes de validar: host, puerto, base de datos, usuario y modo juntos. **Nunca la password**, ni enmascarada: la regla inviolable no admite matices y una máscara sigue siendo una invitación a comprobar por encima del hombro. Esto habla de la **recapitulación**, no del campo donde se escribe: desde la [adenda 2 del ADR 0029](../adr/0029-adoptar-textual-para-el-asistente-de-configuracion.md#adenda-2-2026-09-06--la-cláusula-2-se-abre-un-campo-que-guarda-un-número) el asistente de pantalla completa tiene un campo propio que sí dibuja una máscara —**solo mientras tiene el foco**, es decir mientras la persona está mirando su teclado—, y que sin foco vuelve a decir únicamente *"definida / sin definir"*. La pantalla que alguien deja atrás sigue sin llevar ni la longitud.
- Cada comando termina nombrando **un** siguiente paso. Uno.

### Se muestra más: dónde está apuntando

`list-profiles` imprime solo nombres. Con dos perfiles no se sabe cuál está activo ni contra qué host apunta, que es justo lo que se quiere saber antes de dejar que una IA escriba en una base de datos. Esto lo pide ya el issue #169 y **este diseño lo confirma**, con una precisión: la tabla es para dos o más perfiles; con uno solo, una tabla de una fila es burocracia y se prefiere `clave: valor`.

### Regla general de tablas

| Sitio | ¿Tabla? | Por qué |
|---|---|---|
| `list-profiles`, 2+ perfiles | **Sí** | Filas comparables entre las que hay que elegir |
| `list-profiles`, 1 perfil | No | Una fila no se compara con nada |
| `probe-catalog --verbose` | **Sí** | 14 filas homogéneas, se busca la anómala por columnas |
| `probe-catalog` por defecto | No | El resumen es una frase, no una matriz |
| `doctor` | **No** | Una entidad con muchos atributos: eso es `clave: valor`, no una tabla |
| `test-connection` | No | Un solo resultado |

### Qué se sacrifica primero cuando no cabe

> Añadido el 2026-09-06 al cerrar el issue [#220](https://github.com/Oscarsp15/nz-mcp/issues/220). La tabla se construía a ancho fijo y nunca consultaba el de la consola: con `COLUMNS=40` imprimía exactamente lo mismo que en una terminal ancha, así que la partía el terminal por donde le tocaba.

El issue ofrecía tres candidatos —encoger la columna de host, recortar por el medio, esconder columnas por importancia— y pedía elegir. **Se eligen el primero y el segundo, y se rechaza el tercero.** El orden es éste, y cada escalón tiene test:

1. **No desaparece nada.** Ni una columna ni una fila. Esconder una columna se lleva por delante la única pista de que existía: es la pérdida que nadie puede notar y nadie puede deshacer. Un valor recortado, en cambio, lleva escrito que le falta algo.
2. **Ninguna columna baja de su propia cabecera.** Las cabeceras salen enteras, así que la tabla sigue leyéndose *como* tabla por muy apretada que esté. `Base de datos` ocupa trece celdas y ése es su suelo.
3. **Paga la columna más ancha**, celda a celda, hasta que la fila entra. Hoy es el host y en el informe de `probe-catalog --verbose` será el identificador de consulta; lo que **nunca** es, es `Modo` o `Activo` —cortas porque sus valores son cortos—. La regla se escribe por anchura y no por nombre para que no haya que volver aquí cada vez que una tabla gane una columna.
4. **La celda que tiene que perder caracteres los pierde por el medio.** `10.51.10.242` y `10.51.10.243` se distinguen por el final; `nz-prod-01.corp.example.com` y `nz-prod-02.corp.example.com`, por el principio. Cortar la cola convierte la pregunta que la tabla existe para responder —*¿cuál es éste?*— en una adivinanza. Se conservan las dos puntas y `...` dice qué pasó. El marcador es ASCII por lo de siempre: una consola de Windows con página de códigos heredada dibuja `…` como `?`.
5. **Por debajo del ancho de las cabeceras deja de ser una tabla.** Cada fila sale como bloque `clave: valor`, que es la forma que `list-profiles` ya usa con un solo perfil, así que no hay nada nuevo que aprender. Ahí no se recorta nada: sin columnas que alinear no hay nada que proteger, y una línea larga la parte el terminal sin perder un carácter.

**Sin terminal no se adivina ningún ancho.** Redirigido, canalizado o en CI se usa un valor fijo y las columnas se siguen dimensionando por su contenido, así que un archivo recibe exactamente los mismos bytes que antes de todo esto. Un archivo se guarda y se lee después, en una ventana que no tiene nada que ver con aquélla; encogerlo a una terminal que no está sería perder datos para beneficio de nadie.

Las otras dos salidas anchas se revisaron con el mismo criterio y **no cambian**:

| Salida | Veredicto |
|---|---|
| La ayuda (`nz-mcp --help`) | Ya se adapta: la dibuja `typer` con `rich`, que lee `COLUMNS`. No es código nuestro, pero queda un test que lo fija, porque una revisión que no cambia nada tiene que dejar rastro o el siguiente cambio de paneles la rompe en silencio |
| `probe-catalog --verbose` | Es una tabla y hereda el orden de arriba sin tocar nada, con una precisión: se ajusta al ancho de **stderr**, que es por donde sale, y no al de stdout |
| `doctor` | Es `clave: valor`, no hay columnas que alinear. No se recorta ningún valor: el informe está pensado para pegarlo en un issue y una ruta a la que le falta el medio no le sirve a nadie. Una línea larga la parte el terminal, y partir conserva todos los caracteres |

---

## 5. Tono, y cómo encaja con el i18n existente

El catálogo de `src/nz_mcp/i18n.py` ya tiene el tono correcto y este diseño lo toma como referencia, no como algo a reemplazar. Comparar estas dos, ambas reales:

- ✅ `CLI.VALIDATE_DATABASE_EMPTY`: *"3/3 Visibilidad en {database}: FALLA — el usuario no ve ningún esquema ahí. Conecta bien, pero no tiene GRANT sobre nada de esa base: pide permisos o elige otra."* Dice qué pasó, qué significa y qué hacer.
- ❌ `"Invalid --mode: use read | write | admin."`, hardcodeada en inglés en `edit_profile_cmd`.

El tono ya está inventado dentro de casa. El problema no es de estilo, es de **cobertura**.

### Cobertura i18n: el estado real

Verificado leyendo `cli.py` de arriba abajo:

| Texto | Hoy | Debe ser |
|---|---|---|
| Prompts y mensajes del asistente | i18n ES/EN, buen tono | igual |
| `PROBE_CATALOG.*` | i18n ES/EN | igual |
| `edit-profile`: tres mensajes | **inglés hardcodeado** | i18n |
| `test-connection`: `OK:`, `FAIL:`, `HINT:` | **inglés hardcodeado**, con el hint sí traducido al lado | i18n entero |
| `list-profiles` vacío | **español hardcodeado**, el único del archivo | i18n |
| `--help` de los once comandos y sus opciones | **inglés siempre**, vía docstring | i18n |

El resultado hoy es una pantalla bilingüe: `OK: connected to ... as ...` seguido de `HINT: revisa el host...`. Eso no es un detalle de estilo, es un bug de este rol.

### Decisión sobre `--help`: se traduce

Podría argumentarse que la ayuda se queda en inglés por coherencia con los nombres de comando. **Se rechaza.** Alguien que ha puesto `NZ_MCP_LANG=es` y recibe prompts en español no entiende por qué la ayuda le habla en inglés, y la ayuda es la primera pantalla del producto (parada 2). El coste son unas cuarenta claves nuevas, no una arquitectura nueva: los textos pasan de docstring a `help=` resuelto desde el catálogo.

Con dos límites: **no se traducen** nombres de comandos, nombres de tools, códigos de error ni el JSON de `--json`; y la ayuda se reescribe sin jerga interna al mismo tiempo, porque traducir *"same logic as the nz_switch_profile tool"* sería traducir un problema.

### Reglas de tono, resumidas

Segunda persona y presente. Sin culpa ni dramatismo. Sin marketing y sin emoji decorativo. El ES es la frase que diría alguien en español, no la traducción literal del EN. Y marcadores de estado en **ASCII** (`OK`, `WARN`, `FAIL`), por lo visto en la parada 2: en una consola de Windows con página de códigos heredada, lo bonito se convierte en `?`.

---

## 6. Qué NO se va a hacer, y por qué

Un diseño que solo suma no es un diseño.

1. **Ni TUI, ni menús navegables, ni captura de teclado.** ADR 0005. Y el CLI se usa por SSH, dentro de contenedores y desde otros procesos; una TUI se rompe en los tres. **Acotado desde el 2026-09-06 por el [ADR 0028](../adr/0028-asistente-de-configuracion-interactivo.md)**, que abre la excepción para el asistente de configuración —y solo para él— con la degradación como requisito: los tres escenarios de arriba son precisamente los que la disparan. Las otras doce prohibiciones de esta lista se aplican también dentro del asistente.
2. **Ni una barra de porcentaje donde no hay denominador.** Netezza no informa del avance de una consulta. Una barra que avanza sola miente, y una mentira animada es peor que una espera honesta. Indeterminado salvo en `probe-catalog`, donde el 14 es real.
3. **Ni banner, ni logo ASCII, ni versión en cada arranque.** Es la forma más barata y peor de ser *llamativo*: cuesta líneas en **cada** invocación, ensucia todos los logs pegados en issues, y solo entretiene la primera vez. Lo llamativo se gana en los momentos de la sección 1, no en la cabecera.
4. **Ni emoji como marcador de estado.** Roto en la consola de Windows por página de códigos (comprobado), ilegible por lectores de pantalla, y de ancho impredecible al alinear columnas. ASCII.
5. **Ni color como único portador de significado.** Quien no ve color, o redirige a un archivo, no pierde ni un dato. El color subraya lo que el texto ya dice.
6. **Ni un byte decorativo por el stdout de `serve`.** Nunca, bajo ninguna bandera, ni siquiera detrás de una comprobación de terminal.
7. **Ni indicador de progreso en `doctor`, `list-profiles`, `version`, `switch-profile` o `edit-profile`.** Son locales e instantáneos; un spinner ahí es parpadeo.
8. **Ni progreso en `nz_export_ddl` ni en ninguna tool.** No son superficie de terminal, y su lector es un modelo que paga tokens por cada carácter.
9. **Ni sugerencia que se autoejecute.** Si alguien escribe `nz-mcp list-profile`, se propone `list-profiles`; no se ejecuta en su nombre. Este producto habla con bases de datos de producción; adivinar no es amabilidad.
10. **Ni bandera `--quiet`.** Dos ejes de verbosidad para un CLI de once comandos es un mando que nadie toca; para scripts ya están los códigos de salida y `--json`. Se deja fuera a propósito; si alguien la pide con un caso real, se revisa.
11. **Ni traducción de superficies de máquina.** Códigos de error, nombres de comandos y tools, y el JSON de `--json`, estables y en inglés.
12. **Ni adopción de `rich` en este documento.** Sección 7.
13. **Ni tocar el rediseño del asistente más allá del ritmo.** Su lógica de borrador, reintento y corrección de un campo funciona; este diseño le añade recapitulación, progreso y un solo final, y no le cambia el flujo.

---

## 7. Sobre la implementación: recomendación, no decisión

**Dato verificado el 2026-09-05**: `rich` **no está instalado ni declarado** en `pyproject.toml`, y no se puede importar desde el entorno del proyecto (`ModuleNotFoundError`). No es "ya lo tenemos". Adoptarlo es una dependencia nueva, y la regla inviolable 5 de `AGENTS.md` exige ADR.

> Nota para quien lea el issue #169: ahí se afirma que *"`rich` ya está disponible como dependencia transitiva de `typer`"*. Esa premisa es falsa hoy, y conviene no arrastrarla a un PR.

| Vía | Qué resuelve | Qué cuesta |
|---|---|---|
| **Con `rich`** | Tablas, spinners, barras, detección de terminal, `NO_COLOR` y habilitación de VT en Windows, todo hecho y probado. Es la vía coherente con la dirección estética del owner, y Typer sabe usarlo para sus paneles de ayuda | Una dependencia directa **y su cierre transitivo, que el ADR debe enumerar**. Y un riesgo concreto: `rich` escribe por **stdout** por defecto, así que cada consola construida hay que fijarla a stderr. Es decir, la librería que mejor cumple el objetivo estético es también la que más fácil hace violar R1 |
| **Sin dependencias** | Un spinner propio a stderr son unas veinte líneas y cubre "no parece colgado". La detección de terminal es `isatty` más `NO_COLOR` | No da formato serio. Las tablas se alinean a mano, y alinear a mano con texto en dos idiomas y anchos de carácter variables es una fuente de bugs, no un ahorro |

**Recomendación de este rol, para que la decida un ADR: `rich`**, dada la dirección explícita del owner y el coste real de hacer tablas a mano. **Condicionada** a dos cosas que el ADR debe fijar por escrito:

1. Toda consola se construye contra **stderr**, sin excepción, y eso queda cubierto por un test.
2. La barrera de la sección 2 (capa de salida + test de contrato de `serve`) **se implementa antes**. Primero la protección, después la pintura. Ese orden no es burocracia: es que la librería que más ayuda es la que más fácil rompe el protocolo.

Este documento no aprueba la dependencia. Lo dicho en `roles/dx-engineer.md`: el rol dice qué experiencia hace falta; el ADR dice con qué se implementa y qué cuesta.

---

## 8. Issues de implementación que salen de aquí

Uno por intención, todos referenciando el #201.

| Intención | Tipo | Depende de |
|---|---|---|
| Capa de salida única (stderr, detección de terminal, `NO_COLOR`) más test de contrato que ejecute `serve` y verifique que su stdout solo lleva JSON-RPC | `feat(cli)` | — **primero** |
| ADR que decida si se adopta `rich`, con las dos condiciones de la sección 7 | `docs(adr)` | informado por la capa de salida |
| Indicador de progreso en las esperas reales: escalera del asistente y `test-connection` | `feat(cli)` | capa de salida + ADR |
| `probe-catalog`: salida progresiva, un solo flujo, resumen por defecto y `--verbose` | `refactor(cli)` | capa de salida |
| El snippet de Claude Desktop se imprime sin ruta absoluta y contradice a la documentación | `fix(cli)` | — |
| Un solo siguiente paso al terminar el asistente, con recapitulación previa | `refactor(cli)` | — |
| Ayuda de los comandos sin jerga interna y ordenada por el recorrido de uso | `refactor(cli)` | — |

**No se duplican dos issues que ya existen:**

- **#169** (tabla en `list-profiles` e i18n de todo `cli.py`) queda **confirmado y ampliado**, no absorbido: se le añade el matiz de una fila, la traducción de `--help`, y la corrección de su premisa sobre `rich`. Se comenta en él en vez de abrir uno nuevo.
- **#195** (recuento de tools desincronizado entre README ES, EN, `AGENTS.md` y el registro) toca la misma primera pantalla que la parada 1 de este recorrido, pero es de documentación y ya tiene dueño. Se comenta la relación; no cambia de alcance.

## 9. Cómo se sabe si esto salió bien

- Alguien que instala por primera vez llega de `pipx install` a su primera consulta **sin abrir el README ni preguntar a nadie**.
- Ningún comando deja la pantalla quieta más de un segundo sin decir qué está haciendo.
- `nz-mcp <cualquier comando> | cat` y `... > salida.txt` producen texto plano y legible.
- El stdout de `serve` sigue siendo JSON-RPC puro, y ahora hay un test que lo rompe si deja de serlo.
- Una misma pantalla no mezcla nunca español e inglés.

## Referencias

- [roles/dx-engineer.md](../roles/dx-engineer.md) — las dos audiencias del rol (issue #200)
- [adr/0005-sin-frontend.md](../adr/0005-sin-frontend.md) — sin frontend ni TUI
- [standards/i18n.md](../standards/i18n.md) — catálogo ES/EN, paridad de claves
- [guides/claude-desktop-setup.md](../guides/claude-desktop-setup.md) — la ruta absoluta que el snippet incumple
- `src/nz_mcp/cli.py`, `src/nz_mcp/logging_config.py`, `tests/contract/test_stdio_stdout_json_lines.py`
