# ADR 0032 — Rediseñar el nivel 2 del CLI interactivo como un producto único

- **Fecha**: 2026-09-09
- **Estado**: aceptado — **amplía el [ADR 0028](0028-asistente-de-configuracion-interactivo.md) y el [ADR 0030](0030-menu-interactivo-como-punto-de-entrada.md)**, que siguen vigentes en todo lo demás
- **Decidido por**: TUI Designer (IA) + DX Engineer (IA) + validación humana (auditor: Tech Lead)
- **Issue**: [#235](https://github.com/Oscarsp15/nz-mcp/issues/235)
- **Alcance**: **cómo se ve y qué se muestra** en el nivel 2 —la ruta de pantalla completa—, y qué superficie nueva se autoriza. La librería sigue siendo la del [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md); los niveles 0 y 1 los gobierna el ADR 0031, *mejora progresiva por capacidad del terminal* (issue [#234](https://github.com/Oscarsp15/nz-mcp/issues/234)), y este ADR no los toca.

## Contexto

Decisión de producto del owner, del 2026-09-09, literal: *"bien, aprobado. Cascadia Code, bien, a desarrollar"*, tras revisar tres direcciones de rediseño dibujadas como maquetas y elegir la primera.

Las dos pantallas que existen se ganaron una a una, y eso fue lo correcto: el [ADR 0028](0028-asistente-de-configuracion-interactivo.md) abrió la excepción para el asistente y el [ADR 0030](0030-menu-interactivo-como-punto-de-entrada.md) tuvo que escribir su propia enmienda para el menú porque el primero se negaba a servir de jurisprudencia. El precio de ganarlas por separado se ve ahora, con las dos delante:

| Síntoma | Dónde está hoy |
|---|---|
| Cada aplicación lleva su propia hoja de estilos incrustada | `CSS: ClassVar[str]` en `src/nz_mcp/menu/app.py` y en `src/nz_mcp/wizard/app.py`: dos bloques distintos que ya divergen en el tratamiento de la lista, del pie y del foco |
| El menú lista **comandos**, no tareas | `Option(entry.command, ...)` en `menu/app.py`: lo que se lee es `init`, `add-profile`, `probe-catalog`, que son nombres del programa, no cosas que alguien quiera hacer |
| No hay tema, hay defectos heredados | Ambas pantallas pintan sobre `$surface` y `$text-muted` de Textual; nadie ha medido nunca el contraste de lo que sale |
| El texto mezcla registros | `Estado: ● OK` convive con frases explicativas de ochenta caracteres |

Tres tensiones que este ADR tiene que resolver **antes** de que se escriba una línea de código:

1. **El menú por tareas exige una pantalla nueva.** "Ver perfiles" no es un comando que se lanza y termina: es una lista con un elemento activo sobre la que se actúa. Y la regla del rol TUI Designer (`docs/roles/tui-designer.md`, issue [#233](https://github.com/Oscarsp15/nz-mcp/issues/233)) prohíbe abrir una tercera superficie sin ADR propio, porque el 0028 y el 0030 **no hacen jurisprudencia**: los dos lo dicen por escrito.
2. **Un tema compartido solo se sostiene si ningún widget decide colores a mano.** Hoy eso no es una regla escrita sino una costumbre, y una costumbre no sobrevive al tercer PR.
3. **La accesibilidad no puede quedarse en intención.** La paleta se midió; si el ADR la describe con adjetivos, la medición se pierde y nadie puede comprobar una regresión.

## Decisión

**El nivel 2 se rediseña como un producto único**: el menú de inicio pasa a listar tareas en vez de comandos, `?` es el único sitio donde aparece un comando, se autoriza la pantalla "Ver perfiles" como **tercera y última** excepción que este ADR abre al [ADR 0005](0005-sin-frontend.md), el asistente adopta el lenguaje visual común, y todo ello se pinta desde **una sola hoja `.tcss` con dos temas propios**, `nz-dark` y `nz-light`.

Fuera de eso, el ADR 0005, el 0028 y el 0030 no cambian en nada.

### 1. El menú lista tareas, no comandos

Seis entradas, cada una empezando por un verbo, en el orden en que se necesitan:

| Entrada | Qué abre |
|---|---|
| Configurar una conexión | el asistente (ADR 0028 / 0029) |
| Ver perfiles | la pantalla nueva de la decisión 3 |
| Probar la conexión | la validación contra el perfil activo |
| Iniciar el servidor MCP | el servidor, cerrando antes la pantalla (ADR 0030, decisión 1) |
| Diagnosticar la instalación | las comprobaciones locales |
| Ver herramientas | el catálogo de tools |

**En las pantallas de trabajo no aparece ni un nombre de comando ni una bandera.** No es purismo: es que `add-profile` y `probe-catalog` obligan a saber cómo se llama el programa por dentro para saber qué hace, y quien acaba de instalar no lo sabe. El nombre del comando no desaparece del producto —vive en `?`, decisión 2— pero deja de ser la etiqueta con la que se elige.

Esto **cambia** el punto 4 del ADR 0030, que decía que las entradas se construyen desde los comandos que `typer` tiene registrados para no escribir el texto dos veces. Ese argumento era bueno y el coste de dejarlo se asume con los ojos abiertos: seis tareas son ahora una lista propia, con sus claves i18n propias, y un comando nuevo **no** aparece solo. Lo que lo contiene es la ayuda: `?` sí se sigue construyendo desde los comandos registrados, así que la correspondencia tarea → comando se rompe de forma **visible** —una tarea que apunta a un comando que ya no existe— en vez de en silencio.

A la derecha, un panel con el contexto del perfil activo, en formato `Etiqueta: valor` y en columna:

```
Perfil:  prod_dw
Host:    nz-prod-01.corp.local
Base:    DWH_PROD
Modo:    read
Estado:  ● OK · hace 2 min
```

**El modo se escribe siempre como valor de configuración —`read`, `write`, `admin`— y nunca como prosa.** Es el valor que hay en `profiles.toml`, es el que hay que teclear para cambiarlo y es el que aparece en los mensajes del guard. "Solo lectura" obliga a traducir de vuelta y abre la puerta a que alguien crea que hay un cuarto modo. La maqueta de referencia todavía escribe `Modo: solo lectura` en el panel de contexto: **la maqueta se equivoca ahí y esta decisión la corrige**.

`Estado` es lo único del panel que no es un dato de configuración sino una medición, y por eso lleva su antigüedad pegada: un `● OK` sin fecha envejece en silencio.

### 2. Los comandos viven en un solo sitio: `?`

Desde cualquier pantalla del nivel 2, `?` abre un modal con **la correspondencia tarea → comando CLI equivalente**, y Escape lo cierra. Es el único lugar del nivel 2 donde se ve un comando.

Esto no esconde el CLI: lo ordena. Quien quiere automatizar necesita el comando **una vez**, para copiarlo a un script; quien está eligiendo qué hacer no lo necesita nunca. Ponerlo en cada fila cobra a los dos el precio del primero.

Su equivalente no interactivo es el subcomando **`nz-mcp help`**, que imprime la misma lista en texto. Convive con el `--help` de Typer, **que no cambia**: `--help` es la referencia del programa —opciones, argumentos, formato de invocación— y `help` es la traducción entre lo que alguien quiere hacer y el comando que lo hace. Son dos preguntas distintas y hoy solo la primera tiene respuesta.

### 3. Tercera excepción al ADR 0005: la pantalla "Ver perfiles"

Se autoriza **una tercera superficie de pantalla completa**, y se nombra: la lista de perfiles.

El argumento del ADR 0028 para negarle interfaz a nueve de los once comandos sigue en pie palabra por palabra —*"se invocan con todo lo que necesitan, imprimen y terminan; no hay nada que navegar: sería una ventana alrededor de un `print`"*—, y por eso hay que explicar por qué lo que se autoriza **no es `list-profiles`**:

| | `nz-mcp list-profiles` | Pantalla "Ver perfiles" |
|---|---|---|
| Qué hace | lee el TOML y lo imprime | muestra los perfiles y **actúa sobre uno** |
| Qué hay que navegar | nada | cuál es el activo, y qué se le hace |
| Cómo termina | imprimiendo | usando, probando, editando o borrando |
| Qué sustituye | nada: el comando sigue siendo texto puro | cuatro comandos que hoy piden el nombre del perfil tecleado a mano |

Hoy, cambiar de perfil desde el menú del ADR 0030 obliga a que la pantalla se cierre y **pregunte el nombre en texto plano** (decisión 5 de aquel ADR), porque `switch-profile` lleva el nombre como argumento obligatorio. Esa pregunta existe precisamente porque falta esta pantalla: hay una lista de nombres que la persona acaba de leer y a la que no puede señalar.

Forma concreta: un `DataTable` con **perfil, host, base, modo y estado**, un `▸` delante del activo, y `Enter` sobre una fila abre las cuatro acciones —**usar, probar, editar, borrar**—. El estado de cada fila sigue la regla de la decisión 7: forma, palabra y color.

**Y sigue sin haber jurisprudencia.** Esta es la tercera excepción y **la última que este ADR abre**. Ni el 0028, ni el 0030, ni este documento autorizan una cuarta pantalla: cada superficie nueva exige **su propio ADR con sus propios argumentos**, y "ya hay tres" no es uno.

Los ocho disparadores de degradación del ADR 0028 y del 0030 se aplican a esta pantalla **igual que a las otras dos**, con la misma puerta (`cli_output.interactive_ui_blocker`) y sin una segunda implementación de nada. Sin terminal, ver los perfiles es `nz-mcp list-profiles`, que no cambia.

### 4. El asistente adopta el lenguaje común, sin tocar su flujo

Tres cambios de forma sobre lo que ya funciona (ADR 0028, condición 2: la lógica de borrador, validación y guardado **no se toca**):

- **Stepper**: `● 1 Conexión · ○ 2 Credenciales · ○ 3 Confirmar`, y **sigue al foco** en vez de ser una barra que avanza sola. Es el mismo criterio que la prohibición nº 2 de `cli-experience.md` §6: nada de progreso sin denominador; aquí el denominador es real y son tres.
- **Errores de campo en registro de log**: `vacío`, `fuera de rango (1-65535)`, junto al campo y en minúscula. Sin disculpas, sin "por favor" y sin una frase donde cabe un dato.
- **Toast de una línea al guardar**: `Perfil guardado: <nombre>`. El detalle sigue reescribiéndose en la terminal normal al cerrar la pantalla, que es la contención vinculante del riesgo 4 del ADR 0028 y **no cambia**.

**La degradación sin terminal del ADR 0028 no cambia en nada**: sin TTY, con `TERM=dumb`, en segundo plano o con la ventana por debajo del mínimo, sigue corriendo el asistente de preguntas encadenadas y el perfil resultante sigue siendo idéntico.

### 5. Un sistema visual, no tres hojas

**Una sola hoja `.tcss`, con dos temas propios: `nz-dark` y `nz-light`. `F2` alterna.** Las tres pantallas la cargan; ninguna lleva `CSS` incrustado.

Y la regla dura, escrita aquí para que deje de ser una costumbre:

> **Ningún widget decide colores a mano.** Ni un literal hexadecimal, ni un nombre de color, ni un estilo con color en el código de una pantalla. El color entra por variable de tema, siempre. Un PR que meta un color en el código de una pantalla se rechaza sin discutir el tono.

El tema claro **se diseña, no se invierte**. Invertir el oscuro produce grises sucios y pierde la jerarquía de superficies: en claro, las tarjetas van **por encima** del fondo (`#FCFEFD` sobre `#E9EFED`) y los campos editables **por debajo** (`#D5DEDB`), que es al revés de lo que hace un tema oscuro, donde todo sube.

### 6. La paleta, con sus valores y su medición

Criterio: **todo lo que porta significado supera 4.5:1 (WCAG 2.1) contra cualquier superficie en la que pueda caer**. Bordes y bandas quedan por debajo a propósito: se ven, no se leen, y nada se escribe encima de una banda sin volver a superar 4.5:1 contra esa banda.

**`nz-dark`** — fondo `#10171A`:

| Papel | Valor | Contraste sobre el fondo |
|---|---|---|
| Texto | `#D6E0E2` | 13.47:1 |
| Acento (teal) | `#5EEAD4` | 12.24:1 |
| OK | `#4ADE80` | 10.39:1 |
| Aviso | `#FBBF24` | 10.85:1 |
| Error | `#F87171` | 6.55:1 |

**`nz-light`** — fondo `#E9EFED`, tarjetas `#FCFEFD` (por encima), campos `#D5DEDB` (por debajo):

| Papel | Valor | Sobre fondo | Sobre tarjeta | Sobre campo |
|---|---|---|---|---|
| Texto | `#111A18` | 15.22:1 | 17.50:1 | 12.91:1 |
| Acento (teal) | `#0B6B63` | 5.47:1 | 6.29:1 | 4.64:1 |
| OK | `#166534` | 6.12:1 | 7.04:1 | 5.20:1 |
| Aviso | `#92400E` | 6.09:1 | 7.00:1 | 5.17:1 |
| Error | `#B91C1C` | 5.56:1 | 6.39:1 | 4.71:1 |

**Un solo acento**, el teal. `ok` / `aviso` / `error` son el trío semántico y el acento nunca compite con ellos: si el acento significara algo, un mensaje de error sobre un botón acentuado tendría dos colores discutiendo.

Los números de arriba están calculados sobre estos valores exactos, no estimados. Son la línea base contra la que se comprueba una regresión: si alguien cambia un tono, el número cambia y se ve.

### 7. Estados, énfasis, ritmo y texto

**Estados — siempre forma + palabra + color, y solo estos tres**: `● OK`, `▲ Aviso`, `✕ Error`. Quien no distingue colores lee la palabra; quien mira de reojo ve la forma; el color solo confirma. Es la prohibición nº 5 de `cli-experience.md` §6 aplicada dentro del nivel 2.

**Tres niveles de énfasis, nunca un cuarto**:

| Nivel | Cómo | Para qué |
|---|---|---|
| 1 | negrita | título de pantalla y elemento con el foco, nada más |
| 2 | normal | valores y verbos |
| 3 | atenuado | etiquetas, metadatos y pie |

El color semántico va **encima** de esa escala; no es un cuarto nivel y nunca sustituye a la palabra que tiene al lado. **Sin cursiva**: muchos terminales la fingen o la descartan, y una jerarquía que a veces no se dibuja no es una jerarquía.

**Ritmo**: una línea en blanco entre grupos, **ninguna dentro** de un grupo; márgenes de dos columnas; etiquetas de ancho fijo con los valores alineados en columna. **El pie lleva tres atajos como máximo** — el cuarto no se lee, estorba.

**Texto**: técnico y escueto, `Etiqueta: valor`, mayúscula inicial. Prohibidos "todo bien", "listo", "genial" y la familia entera: no dicen qué está bien, y en un producto que habla con bases de datos de producción una tranquilidad sin dato es una tranquilidad sin fundamento.

### 8. El Unicode del nivel 2 no se hereda

Dentro del nivel 2 **se permite Unicode**: bordes redondeados, `▸`, `●`, `▲`, `✕`. Se puede porque llegar al nivel 2 ya exige un terminal moderno: la puerta de entrada sigue siendo exactamente la del ADR 0028 y el 0030 —`isatty` sobre los tres descriptores, `NO_COLOR`, `TERM=dumb`, segundo plano, terminfo, consola heredada de Windows, tamaño mínimo al arrancar y a mitad de sesión—, y ninguna de las tres pantallas se construye antes de que esa puerta diga que sí.

Esto **acota**, y no deroga, la contención del riesgo 1 del ADR 0028 (*"marcadores y bordes en ASCII dentro del asistente"*): el ASCII deja de ser el techo del nivel 2 y pasa a ser el **piso** del producto, en otra ruta de dibujo. El nivel 0 —ASCII sin color— es esa ruta, la gobierna el **ADR 0031, *mejora progresiva por capacidad del terminal*** (issue #234, que enmienda el 0027), y **no lee esta hoja**. Que aquí haya un borde redondeado no autoriza uno en la salida de `doctor`.

### 9. La fuente la pone el terminal

nz-mcp **no distribuye ni exige una fuente**. Se recomienda en la documentación —Windows Terminal con **Cascadia Code**, que trae los glifos de esta hoja— y esa recomendación vive en `docs/`, no en `pyproject.toml`. **No es una dependencia** y no puede convertirse en una: si un glifo solo se ve bien con una fuente concreta, el glifo está mal elegido.

### 10. Quién decide qué, y el idioma

- **TUI Designer** — cómo se ve: paleta, contraste medido, temas, la hoja `.tcss`, las capturas reproducibles.
- **DX Engineer** — qué se muestra y con qué palabras: entradas del menú, orden, textos, tono.

Cuando los dos roles chocan, gana el que tenga el número: un contraste medido vence a una preferencia de redacción, y un texto que se entiende vence a una alineación bonita.

**El i18n sigue vigente para todo texto nuevo**, sin excepción: las seis tareas, los rótulos del panel de contexto, las cabeceras de la tabla de perfiles, el stepper, los errores de campo y el toast se añaden en **ES y EN** a la vez (`docs/standards/i18n.md`). Lo que **no** se traduce sigue sin traducirse: nombres de comandos, valores de modo (`read` / `write` / `admin`) y códigos de error son superficie de máquina.

## Referencia visual

Las maquetas que el owner aprobó el 2026-09-09, guardadas para que esta decisión se pueda leer contra algo dibujado:

- [`home_dark.svg`](../design/adr-0032/home_dark.svg) — menú por tareas y panel de contexto, tema `nz-dark`
- [`home_light.svg`](../design/adr-0032/home_light.svg) — la misma pantalla en `nz-light`
- [`profiles.svg`](../design/adr-0032/profiles.svg) — "Ver perfiles", con `▸` en el activo y los tres estados
- [`wizard_dark.svg`](../design/adr-0032/wizard_dark.svg) — el asistente con stepper y estado
- [`theme-reference.tcss`](../design/adr-0032/theme-reference.tcss) — la hoja de la **maqueta**

**Son referencia, no contrato.** No son código del producto, no se cargan en tiempo de ejecución y sus selectores no obligan a nada. Donde una maqueta y este ADR discrepan, manda el ADR: la maqueta escribe `Modo: solo lectura` y dibuja el fondo oscuro como `#0E1416`; lo que se implementa es `Modo: read` y `#10171A`.

## Riesgos

1. **Las seis tareas se separan de los once comandos.** Es el coste directo de abandonar el punto 4 del ADR 0030. Un comando nuevo no aparece en el menú solo, y una tarea puede quedar apuntando a un comando renombrado. **Contención**: `?` sí se construye desde los comandos registrados, así que la rotura se ve en pantalla en vez de esconderse; y son seis entradas, no cincuenta.
2. **Una tercera superficie viva que mantener y degradar.** Eventos, foco, redibujo y ocho disparadores, ahora por triplicado. Se asume: la decisión 3 lo dice y la contención es que sea **la última** que este ADR abre.
3. **El Unicode se filtra al nivel 0.** Es el riesgo más probable de todos: alguien copia un marcador de una pantalla a un mensaje de `doctor`. **Contención**: la decisión 8, el ADR 0031 como dueño de esa ruta, y que el nivel 0 no lea esta hoja.
4. **Que el color vuelva a los widgets.** Una hoja compartida dura hasta el primer PR con prisa. **Contención**: la regla dura de la decisión 5, y una comprobación automática que busque literales de color en el código de las pantallas — eso es implementación (#238), pero el ADR lo pide.
5. **La hoja `.tcss` tiene que viajar en el wheel.** Un fichero que no es `.py` se olvida en el empaquetado y falla en casa del usuario, no en CI. **Contención**: queda escrito como requisito de #238, con test de que se puede leer desde el paquete instalado.
6. **Que `?` esté demasiado escondido.** Si nadie encuentra el comando equivalente, el modal no está resolviendo el problema, solo escondiéndolo. **Contención**: `?` aparece siempre en el pie, y es uno de los tres atajos.

## Alternativas consideradas

Tres direcciones dibujadas como maqueta antes de decidir. Se eligió la **A**, que es lo que fija este ADR.

1. **B — navegación lateral fija, estilo `k9s`.** Un raíl de secciones permanente a la izquierda. Se rechaza por medición: el raíl se come **22 columnas** que en la ventana mínima —50 de ancho para el menú, 60 para el asistente— hacen falta para los valores. Y encaja en herramientas que se dejan **abiertas horas**, donde el coste del raíl se amortiza saltando entre secciones cien veces; nz-mcp se abre, se hace una cosa y se cierra —el ADR 0030 lo fijó: el menú elige y no hospeda—, así que se pagaría el ancho sin usar la navegación.
2. **C — una columna con búsqueda, estilo lanzador.** Se rechaza por el tamaño del problema: **con seis tareas, teclear para filtrar es más trabajo que bajar dos veces**. La búsqueda paga cuando hay decenas de opciones. No se descarta para siempre: se puede añadir **encima** de A el día que haya suficientes cosas que buscar, sin rehacer nada, porque A no impide filtrar.
3. **Ampliar el menú sin ADR.** Se rechaza: viola la regla del propio rol TUI Designer y deja la tercera superficie sin justificación escrita; la siguiente IA la tomaría como precedente para una cuarta.
4. **Convertir cada comando en pantalla.** Se rechaza, y ya se rechazó en el issue [#226](https://github.com/Oscarsp15/nz-mcp/issues/226): las pantallas se ganan de una en una y por necesidad, no por uniformidad. "Ver perfiles" entra por lo que se **hace** en ella, no por simetría.
5. **Mantener el CSS dentro de cada `App`.** Es lo que hay hoy. Con dos temas y tres pantallas garantiza deriva de color entre pantallas y hace imposible medir el contraste en un solo sitio; ya divergen con dos.
6. **Usar los temas que trae Textual.** Se rechaza: no cumplen la paleta medida y no garantizan que el color deje de ser el único portador de significado. Además atan la identidad del producto a la cadencia de una librería.
7. **Distribuir o exigir una fuente.** Se rechaza: es peso, es licencia y es un problema de instalación para arreglar un glifo mal elegido. Se recomienda y punto (decisión 9).

## Consecuencias

### Positivas

- **Una sola fuente de color y de contraste**, en un fichero, medible con un test en vez de con la vista.
- **Un menú que se entiende sin saber cómo se llama el comando**, que es exactamente el estado de quien acaba de instalar.
- **La ayuda deja de estar duplicada por pantallas**: un modal, un subcomando, la misma lista.
- **Cambiar de perfil deja de exigir teclear su nombre** después de haberlo leído en pantalla.

### Negativas y costes

- **Una superficie Textual más** que mantener, probar y degradar, con sus ocho disparadores.
- **Una hoja `.tcss` que hay que empaquetar en el wheel** y que falla, si falla, en casa del usuario.
- **El compromiso de que ninguna pantalla nueva escape del tema**, que hay que sostener PR a PR.
- **Seis textos de menú que ya no se derivan de los comandos** y que hay que mantener en ES y EN.

### Qué monitorizar

- PRs que vuelvan a meter color en el código de un widget.
- Peticiones de una cuarta pantalla: cada una exige su ADR, y la respuesta por defecto es no.
- Quejas de que no se encuentra el comando equivalente — señal de que `?` está demasiado escondido.
- Issues sobre glifos rotos o bordes convertidos en `?`: significarían que la puerta del nivel 2 dejó pasar un terminal que no debía, y el disparador que falta se añade a la tabla del ADR 0028.
- Que el contraste medido de la decisión 6 siga siendo el que dice la tabla después de la primera ronda de retoques.

## Issues derivados

| Issue | Qué implementa |
|---|---|
| [#238](https://github.com/Oscarsp15/nz-mcp/issues/238) | la hoja `.tcss` compartida y los dos temas, con su empaquetado y su comprobación de contraste |
| [#239](https://github.com/Oscarsp15/nz-mcp/issues/239) | el menú por tareas, el panel de contexto, `?` y el subcomando `nz-mcp help` |
| [#240](https://github.com/Oscarsp15/nz-mcp/issues/240) | la pantalla "Ver perfiles" |
| [#241](https://github.com/Oscarsp15/nz-mcp/issues/241) | el asistente: stepper, errores de campo y toast |
| [#242](https://github.com/Oscarsp15/nz-mcp/issues/242) | la documentación, incluida la recomendación de Windows Terminal + Cascadia Code |

## Lo que este ADR no decide

- **No elige librería.** Es `textual`, con el tope y el confinamiento del ADR 0029.
- **No toca los niveles 0 y 1.** Son del ADR 0031 (issue #234).
- **No autoriza una cuarta pantalla.** Ni por uniformidad, ni por parecido, ni por "ya hay tres".
- **No cambia la degradación.** Los disparadores del ADR 0028 y del 0030 siguen intactos y ahora aplican también a "Ver perfiles".
- **No cambia el modelo de seguridad.** Ni `sql_guard`, ni permisos de perfil, ni el manejo de la credencial: la password sigue sin entrar en el árbol de widgets (ADR 0029, condición 5 y su adenda 2).
- **No implementa nada.** Esta fase es decisión: ni una línea de `src/`, ni dependencias nuevas.

## Referencias

- [ADR 0005](0005-sin-frontend.md) — sin frontend ni UI propia, vigente salvo las tres excepciones
- [ADR 0027](0027-adoptar-rich-para-la-presentacion-del-cli.md) — `rich` acotado y confinado a la capa de salida
- [ADR 0028](0028-asistente-de-configuracion-interactivo.md) — la primera excepción, los disparadores de degradación y el riesgo 5
- [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md) — la librería, su coste y su confinamiento
- [ADR 0030](0030-menu-interactivo-como-punto-de-entrada.md) — la segunda excepción; su punto 4 lo cambia este ADR
- ADR 0031 — *mejora progresiva por capacidad del terminal*, niveles 0 y 1, enmienda el 0027 (issue [#234](https://github.com/Oscarsp15/nz-mcp/issues/234))
- `docs/roles/tui-designer.md` — el rol y la regla de que cada superficie nueva exige ADR (issue [#233](https://github.com/Oscarsp15/nz-mcp/issues/233))
- [docs/roles/dx-engineer.md](../roles/dx-engineer.md) — qué se muestra y con qué palabras
- [docs/standards/i18n.md](../standards/i18n.md) — ES/EN para todo texto nuevo
- [docs/architecture/cli-experience.md](../architecture/cli-experience.md) — §2 restricciones, §6 lo que no se hace
- [docs/design/adr-0032/](../design/adr-0032/) — las maquetas aprobadas y la hoja de referencia
- `src/nz_mcp/menu/app.py` y `src/nz_mcp/wizard/app.py` — las dos pantallas de hoy, con su `CSS` incrustado
