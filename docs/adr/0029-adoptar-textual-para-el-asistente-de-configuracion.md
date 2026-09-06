# ADR 0029 — Adoptar `textual` acotado y confinado para el asistente de configuración

- **Fecha**: 2026-09-06 (adenda 1: 2026-09-06; adenda 2: 2026-09-06)
- **Estado**: aceptado, con dos adendas — la [1](#adenda-1-2026-09-06--qué-garantiza-de-verdad-la-condición-5)
  precisa qué garantiza la condición 5, y la [2](#adenda-2-2026-09-06--la-cláusula-2-se-abre-un-campo-que-guarda-un-número)
  abre su cláusula 2 a un campo interactivo que no guarda la credencial
- **Decidido por**: DX Engineer (IA) + validación humana (auditor: Security Engineer)
- **Issue**: [#221](https://github.com/Oscarsp15/nz-mcp/issues/221)
- **Depende de**: [ADR 0028](0028-asistente-de-configuracion-interactivo.md), que abre la excepción
  al [ADR 0005](0005-sin-frontend.md). Sin esa enmienda, este ADR no tendría objeto.

## Contexto

El ADR 0028 decide que el asistente de configuración —y solo él— puede ser un interfaz de pantalla
completa navegable. Este ADR decide **con qué se construye y qué cuesta**.

`textual` es la candidata natural: viene de la misma casa que `rich`, que el
[ADR 0027](0027-adoptar-rich-para-la-presentacion-del-cli.md) ya adoptó y acotó. Eso es un
argumento de familia, no una medición. Aquí está la medición.

> Todo lo que sigue está comprobado el **2026-09-06** sobre CPython 3.11.5 en Windows, resolviendo
> con `uv` contra las nueve dependencias de ejecución que declara `pyproject.toml`. Donde hay una
> duda, se dice que la hay.

### Punto de partida: `textual` no está, y esta vez la premisa es la buena

El ADR 0027 tuvo que corregir una premisa falsa: se creía que `rich` no estaba instalado y resultó
que `typer` lo exige de forma dura, así que **ya se pagaba**. Con `textual` no ocurre lo mismo, y
conviene decirlo antes de que alguien traslade el argumento por analogía:

```
$ uv run --no-sync python -c "import textual"
ModuleNotFoundError: No module named 'textual'
```

**El coste marginal de `textual` no es cero.** Es una dependencia nueva de verdad, con paquetes
nuevos de verdad, y esa es la diferencia esencial con el ADR 0027.

### Qué necesita el asistente de la librería

Sale del ADR 0028 y del issue #221: campos que se recorren, se corrigen sin rehacer los anteriores,
enseñan qué falta y se validan antes de guardar; que se adapte al ancho; que degrade; y que se
pueda **probar automáticamente**, porque una interfaz que no se prueba se rompe en silencio.

Traducido a piezas: un bucle de eventos, un modelo de foco, edición de texto con cursor y
selección, composición y redibujo, reacción al cambio de tamaño de la ventana, y un arnés de
pruebas. Ninguna de esas piezas la tiene `rich`, que es un renderizador sin entrada.

## Decisión

**Se adopta `textual` como dependencia directa de nz-mcp, declarada en `pyproject.toml` y acotada
a `textual>=8.2,<9`**, con cinco condiciones que forman parte de la decisión y no de su
implementación.

### Condición 1 — `textual` solo se usa en el asistente, y solo cuando el entorno lo permite

La aplicación se construye **después** de que la puerta de degradación del ADR 0028 (condición 1)
haya dicho que sí. Esa puerta vive en `cli_output`, que es donde ya está toda la detección de
terminal del proyecto (`isatty`, `NO_COLOR`, `TERM=dumb`), y **no importa `textual`**: decide un
booleano, no construye nada.

Que la puerta sea nuestra no es un capricho de arquitectura, es una necesidad medida:

| Comprobación sobre `textual` 8.2.8 | Resultado |
|---|---|
| ¿Comprueba `TERM=dumb` en algún sitio? | **No.** Cero apariciones de `dumb` en todo el paquete |
| ¿Se niega a arrancar sin TTY? | **No.** El único `isatty` de sus drivers (`linux_driver.py:60`) decide *cómo* leer la entrada, no *si* arrancar |

Una librería de TUI intentará pintar donde le dejen. La decisión de no dejarla es del proyecto.

### Condición 2 — `textual` se importa únicamente desde el paquete del asistente

Ningún otro módulo lo nombra. Y **no se mete en `cli_output.py`**: la capa de salida es el escritor
único de la terminal en comandos puntuales, y meterle dentro una aplicación con widgets la
convertiría en dos cosas a la vez. El asistente vive en su propio paquete
(`src/nz_mcp/wizard/`), y la regla queda al revés que la de `rich`:

| Paquete | Único sitio donde puede importarse |
|---|---|
| `rich` | `src/nz_mcp/cli_output.py` (ADR 0027, condición 2) |
| `textual` | `src/nz_mcp/wizard/` |

Lo vigila el mismo detector AST que ya confina `rich`:
`tests/contract/test_serve_stdout_protocol_only.py`, cuyo `_LAYER_ONLY_MODULES` pasa de ser un
conjunto de módulos con un único destino permitido (`_OUTPUT_LAYER = "cli_output.py"`) a ser un mapa
de módulo a destino. Un `from textual.app import App` en `cli.py`, en `server.py` o en cualquier
`catalog/*` rompe el CI, no a un usuario.

Y el paquete del asistente **tampoco importa `rich`**: lo recibe por dentro de `textual`, que lo usa
en 48 de sus módulos de primer nivel y mide anchos de carácter con `rich.cells.cell_len`
(`textual/_cells.py`). Es la misma pila de renderizado que ya usa `cli_output`, no una segunda.

### Condición 3 — la barrera de `serve` no se relaja, y aquí importa el detalle

`textual` escribe a **`sys.__stdout__`**, no a `sys.stdout`: `drivers/windows_driver.py:36`
(`self._file = sys.__stdout__`) y `drivers/win32.py:166` (`terminal_out = sys.__stdout__`). Una
protección que reasignara `sys.stdout` por nombre **no lo cubriría**.

La que tenemos sí: `cli_output.stdout_reserved_for_protocol()` trabaja a nivel de **descriptor** —
duplica el descriptor 1 a uno privado que solo conoce el transporte MCP y apunta el 1 a stderr—,
así que `sys.__stdout__` resuelve a stderr como cualquier otra escritura ingenua. La garantía se
mantiene por construcción, no por disciplina. El asistente, además, nunca se ejecuta dentro de
`serve`: son comandos distintos, y la condición 2 impide que uno importe al otro.

### Condición 4 — el vocabulario del asistente es suyo, no el de `textual`

Igual que la condición 3 del ADR 0027 para `rich`: el resto del código pide *"pide el borrador del
perfil a la persona"*, no `App.run_async`. La frontera del paquete `wizard/` es una función que
recibe lo que hace falta y devuelve un borrador o nada. Es lo que convierte un cambio de major en el
trabajo de un paquete en vez de en una migración, y lo que permite que el camino de texto y el
interactivo sean intercambiables desde fuera.

### Condición 5 — la password no entra en el árbol de widgets

Ésta es nueva y no la cubre ningún ADR anterior. El [ADR 0026](0026-secret-sin-password-en-trazas.md)
protege **trazas y renderizados** de un programa que imprime y muere; una aplicación con estado en
memoria es otro problema, y el propio 0026 lo anticipa cuando avisa de que *"no protege los valores
derivados"*. En un interfaz, el valor derivado no es un caso raro: **es el camino normal**, porque el
widget es el editor.

Medido sobre `textual` 8.2.8, con un `Input(password=True)`:

| Prueba | Resultado |
|---|---|
| Teclear `hunter2` y leer `Input.value` | `type` es `str`, `repr` es `'hunter2'`. La credencial en claro |
| Asignar un `Secret` a `Input.value` | Sobrevive como `Secret`… hasta la primera pulsación |
| Pulsar una tecla más | `_input.py` reconstruye el valor con `f"{value[:start]}{text}{value[end:]}"` y el resultado es una `str` desnuda |
| `export_screenshot()` del campo enmascarado | **No** contiene el texto. El enmascarado de pantalla sí funciona |

O sea: `Input(password=True)` protege la **pantalla**, y `Secret` protege el **objeto**, pero el
widget destruye el tipo en cuanto se edita. `password = reactive(False)` es una decisión de
renderizado; el valor es y será una `str` viva dentro del DOM durante toda la sesión.

Decisión, en tres cláusulas verificables:

1. **El modelo de estado del asistente no tiene campo de password.** El interfaz recoge los siete
   campos restantes y expone, como mucho, un booleano *"contraseña: definida / sin definir"*.
2. **Ningún `Input` del asistente recibe nunca la credencial**, ni siquiera con `password=True`. Se
   pide fuera del árbol de widgets: dentro de un bloque `App.suspend()` (existe en 8.2.8,
   `app.py:4718`) o después de que la aplicación termine, siempre por
   `cli_output.ask_secret()` —que ya oculta el eco y pide confirmación— y siempre envuelta en
   `Secret` antes de viajar a `run_checks` y al keyring. Enmascarada, como pide el issue, pero en el
   único sitio donde el tipo sobrevive.
3. **Ni devtools ni capturas en el camino de producción.** El asistente no arranca bajo
   `TEXTUAL=devtools` ni llama a `save_screenshot()` / `export_screenshot()` fuera de tests. La
   medición de arriba dice que hoy una captura no filtraría el campo enmascarado; dice también que
   filtraría cualquier otro estado, y esa medición vale para 8.2.8, no para siempre.

Con las tres, la propiedad que el ADR 0026 consiguió —**en el código de producción no queda ningún
punto donde exista una `str` desnuda con la credencial**— sigue siendo cierta con un interfaz
delante. Sin ellas, dejaría de serlo, y el test de traza no lo vería, porque el problema no estaría
en una traza sino en un objeto vivo.

> **Precisado por la [adenda 1](#adenda-1-2026-09-06--qué-garantiza-de-verdad-la-condición-5).**
> Las tres cláusulas siguen siendo la decisión; lo que cambia es qué las sostiene. Un análisis
> estático del paquete **no puede impedir** que la credencial entre —cayó tres veces durante la
> implementación—, así que la garantía es el test que ejecuta la aplicación y busca el valor real,
> y el guardarraíl estático es defensa en profundidad.

> **Modificado por la [adenda 2](#adenda-2-2026-09-06--la-cláusula-2-se-abre-un-campo-que-guarda-un-número).**
> La cláusula 2 decía *"se pide fuera del árbol de widgets"* como si fuera la única forma de
> cumplir la condición. No lo es: lo que la condición prohíbe es **guardar** la credencial en un
> widget, y eso admite un widget que no guarda nada. Las cláusulas 1 y 3 no cambian; la 2 se
> reescribe en la adenda 2, con la suspensión conservada como red.

## Rango elegido, y por qué ése

**`textual>=8.2,<9`.**

- **Suelo `>=8.2`**: es la serie sobre la que está medido todo este documento (`App.run_test`,
  `Pilot.resize_terminal`, `App.suspend`, el comportamiento de `Input`). Declarar un suelo más bajo
  sería declarar algo que nadie ha ejecutado.
- **Tope `<9`**: un solo major, el actual. Y aquí el precedente del proyecto pesa más que en el
  0027. Los PR #163 y #187 tuvieron que acotar cuatro dependencias porque un rango abierto dejó
  entrar versiones que rompían el CI y el guard. La cadencia de `textual` convierte eso en cuestión
  de meses:

| Major | Primera publicación |
|---|---|
| 1 | 2024-12-12 |
| 2 | 2025-02-16 |
| 3 | 2025-03-27 |
| 4 | 2025-07-12 |
| 5 | 2025-07-25 |
| 6 | 2025-08-31 |
| 7 | 2026-01-03 |
| 8 | 2026-02-16 |

Ocho majors en catorce meses, sobre 254 publicaciones desde 2021. `rich`, en comparación, va por
uno al año (13 → 14 → 15) y por eso el ADR 0027 pudo permitirse un tope holgado. Aquí no. **Un
rango sin tope, o con dos majores de margen, sería deuda con intereses a plazo corto.** Subir el
tope es un PR con la suite en verde y el changelog leído: exactamente el trabajo que el #187
demostró que hay que hacer a mano.

### Efecto secundario que hay que declarar: sube el suelo de `rich`

`textual` 8.2.8 exige `rich>=14.2.0`. El ADR 0027 declaró `rich>=13.8,<16` porque 13.8 era lo que
`typer` exigía. En cuanto entre `textual`, ese 13.8 deja de poder resolverse y pasa a ser una
ficción en el archivo. **La implementación de este ADR sube el suelo a `rich>=14.2,<16`**, para que
siga siendo nuestro y siga siendo cierto. No es un cambio de criterio del 0027: es la consecuencia
aritmética de esta decisión, escrita aquí para que no aparezca como sorpresa en un `pip install`.

## Cierre transitivo, enumerado y medido

Resolución de las nueve dependencias de ejecución de nz-mcp, con y sin `textual`:

| | Paquetes | `site-packages` |
|---|---|---|
| Hoy | 54 | 55 973 KB |
| Con `textual>=8.2,<9` | 58 | 59 877 KB |
| **Diferencia** | **+4** | **+3 904 KB (≈3,8 MB)** |

Lo que entra, uno a uno:

| Paquete | Versión resuelta | Por qué está | Peso en disco | `py.typed` |
|---|---|---|---|---|
| `textual` | 8.2.8 | la dependencia que decide este ADR | 3 353 KB | sí |
| `mdit-py-plugins` | 0.6.1 | `textual` lo exige: extensiones del widget `Markdown` | 283 KB | sí |
| `platformdirs` | 4.11.7 | `textual` lo exige (`>=3.6,<5`): rutas de caché y config | 162 KB | sí |
| `linkify-it-py` | 2.2.0 | `textual` pide `markdown-it-py[linkify]`: detecta URLs en texto | 88 KB | **no** |

Lo que **no** entra, porque ya se paga: `rich` 15.0.0, `pygments` 2.21.0 (5,1 MB), `markdown-it-py`
4.2.0, `mdurl` 0.1.2 y `typing-extensions` 4.16.0. Los 5,1 MB de lexers de `pygments` que el ADR
0027 se resignó a pagar siguen siendo los mismos: `textual` los reutiliza, no los duplica.

Tres cosas que hay que decir de esta tabla sin maquillarlas:

- **3,8 MB nuevos para un solo comando.** Es la cifra honesta y no admite el consuelo del ADR 0027:
  aquí nadie los tenía ya descargados.
- **`mdit-py-plugins` y `linkify-it-py` no los quiere nadie.** Entran porque el widget `Markdown` de
  `textual` existe, no porque el asistente vaya a renderizar Markdown. Son 371 KB de dependencia
  que se paga por vivir en el mismo paquete que una funcionalidad que no se usa. Feo, pequeño, y se
  escribe.
- **`linkify-it-py` no trae `py.typed`.** Hoy no se importa y no debe importarse; si algún día se
  importara haría falta `ignore_missing_imports` en `mypy --strict`. `textual` sí lo trae, así que
  el paquete del asistente se tipa sin excepciones.

## Se puede testear, y es la razón principal de la elección

Criterio de descarte, no detalle. Comprobado ejecutando de verdad, no leyendo la documentación:

`App.run_test(headless=True, size=(w, h))` es un gestor de contexto asíncrono que arranca la
aplicación **sin terminal** y devuelve un `Pilot` con `press`, `click`, `double_click`, `hover`,
`resize_terminal`, `pause`, `wait_for_animation` y `exit`. La prueba que se ejecutó teclea en un
campo, lee su valor, encoge la ventana a 20×5 y comprueba el nuevo ancho:

```
async with app.run_test(size=(80, 24)) as pilot:
    app.set_focus(app.query_one("#host", Input))
    await pilot.press(*"nz.example.com")
    assert app.query_one("#host", Input).value == "nz.example.com"
    await pilot.resize_terminal(20, 5)
    await pilot.pause()
    assert app.size.width == 20
```

Pasa bajo pytest en 0,5 s, sin TTY y sin proceso hijo. Lo que se afirma con eso:

- **Las aserciones van contra el estado, no contra píxeles.** Y el estado es justo lo que hay que
  probar: los ocho campos, qué falta, las tres validaciones y las cuatro salidas del ADR 0028 son
  una máquina de estados. Se consulta el DOM con `query_one` como se consultaría un objeto.
- **`resize_terminal` prueba la condición 4 del ADR 0028** —adaptarse al ancho— sin abrir una
  terminal ni redimensionar nada a mano.
- **Cero dependencias de desarrollo nuevas.** `pytest-asyncio>=0.23` ya está declarada en
  `pyproject.toml`; hoy no hay ni un test asíncrono en la suite, pero el plugin está. Basta con
  marcar los tests nuevos con `@pytest.mark.asyncio`, que `--strict-markers` acepta porque lo
  registra el propio plugin.
- **No se adopta `pytest-textual-snapshot`.** Es el plugin oficial de capturas SVG y arrastraría
  `syrupy` 4.8.0, `jinja2` 3.1.6 y `markupsafe` 3.0.3, y —medido— **degradaría `pytest` de 9.1.1 a
  8.4.2**, porque fija `pytest<9`. Bajar la versión de pytest de todo el proyecto para poder
  comparar imágenes de una pantalla es un intercambio malo: las capturas se rompen con cada cambio
  de estilo y no dicen si la lógica funciona. Se rechaza.

## Alternativas consideradas

1. **Seguir con prompts encadenados, mejor pulidos.** Es la alternativa seria y **se conserva**: es
   el camino de degradación obligatorio del ADR 0028, así que no se tira nada. Lo que no hace es
   cumplir la decisión de producto. Un flujo de preguntas encadenadas no permite volver a un campo
   anterior sin rehacer los siguientes, ni ver los ocho a la vez, ni señalar cuál falta antes de
   validar; y el asistente ya ofrece *"corregir un campo"* —solo que después de un fallo, que es
   demasiado tarde. Se rechaza como sustituto y se adopta como base.
2. **Solo `rich`, con lectura de teclas escrita por nosotros.** Es la que más apetece porque no suma
   dependencias. `rich` tiene `Live` para repintar, pero **no tiene entrada**: no hay bucle de
   eventos, ni foco, ni edición de texto, ni gestión de redimensionado. Haría falta escribir un
   lector de teclas por plataforma (`msvcrt` en Windows, `termios` más `tty` en POSIX), decodificar
   secuencias de escape a mano, mantener el cursor y la selección de un campo de texto, y detectar
   el cambio de tamaño sin `SIGWINCH`, que en Windows no existe. Eso no es *usar `rich`*: es
   escribir un framework de TUI y llamarle *"unas líneas"*. Es el mismo argumento con el que el ADR
   0027 rechazó hacer tablas a mano, un orden de magnitud más caro, y además sin arnés de pruebas:
   habría que inventarlo. Se rechaza.
3. **`prompt_toolkit` (con o sin `questionary` encima).** Es la alternativa técnica real y **gana en
   estabilidad**: la serie 3.0 lleva desde 2019, su última publicación es 3.0.53 (2026-07-26) y solo
   ha tenido cuatro majors en toda su vida, frente a los ocho de `textual` en catorce meses. En
   tamaño empatan: `prompt_toolkit` 1 659 KB más `wcwidth` 1 860 KB son ≈3,5 MB, contra los 3,8 MB
   de `textual`. Se rechaza por tres razones, en este orden:
   - **Traería una segunda pila de terminal.** `wcwidth` mide anchos de carácter, que es
     exactamente lo que `rich.cells` ya hace y lo que `textual` reutiliza; y `prompt_toolkit` trae
     su propio renderizador y su propio sistema de estilos. El CLI acabaría con dos motores de
     pintado, dos formas de decidir el color y dos formas de medir un carácter ancho, con la
     garantía de que se desincronizan. `textual` **es** `rich` por debajo.
   - **Su capa de widgets es más baja.** Una aplicación de pantalla completa en `prompt_toolkit` se
     escribe con `Layout`, `Window` y `BufferControl`: el modelo de campos, foco y validación
     visible lo pondríamos nosotros. `questionary`, que sí lo pone, solo ofrece prompts
     encadenados, que es la alternativa 1.
   - **El arnés de pruebas es peor para lo que hay que probar.** `prompt_toolkit` se prueba con
     `create_pipe_input()` y `DummyOutput()`, empujando bytes de teclas crudos; `textual` da un
     `Pilot` que pulsa, redimensiona y deja consultar el árbol. Lo que hay que asegurar es una
     máquina de estados, y una se afirma sobre objetos y la otra sobre bytes.
4. **`urwid`.** Resuelve en un solo paquete y es maduro, pero su modelo es de los años del
   `curses`, su soporte de Windows llegó tarde y su ecosistema y documentación están muy por detrás.
   Adoptarlo nos dejaría solos ante el destino principal de este producto, que es una consola de
   Windows. Se rechaza.
5. **No hacer nada y dejar el ADR 0005 intacto.** Ya se rechazó en el ADR 0028; se nombra aquí para
   que este documento se lea entero sin ir a buscar aquél.

## Consecuencias

### Positivas

- El asistente puede cumplir la decisión de producto del owner con una librería que ya trae resuelto
  todo lo que habría que escribir a mano: eventos, foco, edición, composición, redimensionado.
- **La interfaz se puede probar**, y con las mismas herramientas de siempre: `pytest` y una marca
  `asyncio`. Cero dependencias de desarrollo nuevas.
- **Una sola pila de renderizado.** `textual` pinta con `rich`, así que el ancho de carácter, el
  color y el comportamiento sin terminal se deciden en el mismo código que ya usa `cli_output`.
- El confinamiento es simétrico al que ya funciona: `rich` en `cli_output.py`, `textual` en
  `wizard/`, y un detector AST que rompe el CI si alguno se escapa.
- `textual` trae `py.typed`, así que `mypy --strict` no necesita `ignore_missing_imports`.

### Negativas y costes

- **3,8 MB y cuatro paquetes nuevos** de coste marginal real, para un solo comando, de los cuales
  371 KB (`mdit-py-plugins` y `linkify-it-py`) son para un widget de Markdown que no se va a usar.
- **La cadencia.** Ocho majors en catorce meses. Un tope `<9` significa que este proyecto va a mirar
  un changelog de `textual` con cierta frecuencia, y que Dependabot va a proponer subidas que no se
  pueden mergear a ciegas.
- **Sube el suelo de `rich` a 14.2** para todo el proyecto, no solo para el asistente.
- **Una superficie viva** con su ciclo de vida: es el coste que el ADR 0028 ya asumió y que este
  concreta en un paquete y una librería.
- **La password necesita una regla propia** (condición 5) porque el `Secret` del ADR 0026 no
  sobrevive dentro de un widget. Es una restricción de diseño permanente, no un detalle de
  implementación.

### Qué monitorizar para saber si fue buena idea

- Que `pyproject.toml` no acabe con `textual` sin tope después de un merge de Dependabot, y que el
  suelo de `rich` siga siendo `>=14.2` o superior.
- Que ningún módulo fuera de `src/nz_mcp/wizard/` importe `textual`, y que ese paquete no importe
  `rich`.
- Que el stdout de `serve` siga siendo JSON-RPC puro.
- Que la condición 5 siga cumpliéndose: ni un `Input` con la credencial, ni un campo de password en
  el modelo de estado.
- Cuánto cuesta el primer salto de major. Si obliga a rehacer el interfaz en vez de a ajustarlo,
  este ADR se revisa con esa factura delante y `prompt_toolkit` vuelve a la mesa.

## Lo que este ADR no decide

- **No decide que haya interfaz.** Eso lo decide el [ADR 0028](0028-asistente-de-configuracion-interactivo.md).
- **No decide qué se muestra ni en qué orden.** Eso es del rol DX y del diseño de la experiencia.
- **No autoriza `textual` en ningún otro comando.** El confinamiento de la condición 2 es la
  decisión, no una recomendación.
- **No implementa nada.** Esta fase es decisión.

## Adenda 1 (2026-09-06) — qué garantiza de verdad la condición 5

Esta adenda existe porque **la implementación descubrió que la condición 5 prometía de
más**, y un ADR que promete lo que no cumple es peor que uno que no dice nada.

### Lo que decía, y por qué no se sostiene

El comentario del issue [#221](https://github.com/Oscarsp15/nz-mcp/issues/221) pedía *"un
chequeo automatizado que lo impida"*, y esta condición se leyó como que un análisis
estático del paquete podía **impedir** que la credencial entrara en un widget. No puede.

Durante la implementación (PR #223) el guardarraíl estático cayó **tres veces**, en tres
auditorías seguidas, y siempre por el mismo motivo:

1. Perseguía nombres sospechosos (`password`, `secret`, `credential`). Se esquivó llamando
   `auth_material` a la credencial.
2. Se reescribió como listas blancas de la superficie del paquete —imports, parámetros,
   atributos, campos, constantes, y lo que puede llegar a un widget—. Se esquivó con
   `setattr` sobre un widget ya construido, que ninguna regla miraba.
3. Eso se cubrió, y sigue sin cubrir `widget.update(x)`, porque saber que `widget` es un
   widget exige inferencia de tipos que ese archivo no hace.

No es mala suerte tres veces: **una propiedad negativa no se demuestra mirando la forma
del código fuente**. Es exactamente la lección que el proyecto ya había aprendido con la
barrera de stdout, donde lo que aguanta no es el detector AST sino la reserva de
descriptor — y el propio detector lo dice de sí mismo: *"es una lista negra y por
naturaleza incompleta"*.

### Lo que la condición 5 garantiza, y con qué

Las tres cláusulas de la condición 5 **no cambian**: siguen siendo la decisión de diseño.
Lo que se corrige es **con qué se sostienen**, por orden de fuerza:

1. **Por construcción, y es lo único que no depende de nadie**: la única puerta hacia
   `src/nz_mcp/wizard/` es `ask_password: Callable[[], bool]`. Esa firma no puede
   transportar una cadena. Mientras la puerta no se ensanche, la credencial no entra, y
   eso no es un test sino un tipo.
2. **Por ejecución**: el test que arranca la aplicación real, recorre el camino real de la
   credencial con un valor real y busca ese valor en el árbol de widgets terminado, en los
   atributos de la aplicación y en su valor de retorno. Comprueba **el hecho**, no cómo
   está escrito el código, así que ninguna forma de escribirlo se le escapa. **Es la
   garantía.** Es el test que le faltaba a la regresión del `Secret` del PR #193.
3. **Por análisis, como defensa en profundidad**: las listas blancas del guardarraíl.
   Sirven para que un error se detecte **antes**, en el diff, en vez de al ejecutar. Es
   valioso y es barato. **No es una demostración**, y a partir de aquí no se presenta como
   tal.

### La regla que queda escrita

- El chequeo automatizado que pedía la auditoría del PR #222 **existe**, y son los dos
  puntos 2 y 3 juntos: uno detecta antes, el otro garantiza.
- Si alguna vez alguien **debilita, acota o borra el test de ejecución**, el guardarraíl
  estático **no lo sustituye**. Quedaría un chequeo que está de acuerdo con el código en
  vez de uno que lo contradice.
- El guardarraíl estático puede crecer cuando aparezca una vía nueva, pero perseguir una
  quinta no es la respuesta a que hayan aparecido cuatro. La respuesta es no confiar en él
  como si fuera exhaustivo.

### Qué monitorizar, corregido

Donde arriba se dice *"que la condición 5 siga cumpliéndose: ni un `Input` con la
credencial, ni un campo de password en el modelo de estado"*, léase también: **que el test
de ejecución siga ejercitando el camino real y siga buscando un valor real**. Si ese test
deja de ejecutar la aplicación de verdad, la condición 5 ha dejado de estar comprobada,
aunque el guardarraíl estático siga en verde.

## Adenda 2 (2026-09-06) — la cláusula 2 se abre: un campo que guarda un número

Esta adenda existe porque el owner miró el asistente terminado y vio la costura: al llegar a
la contraseña **la interfaz se suspende** y la pregunta se hace fuera. Su pregunta, literal:
*"cómo harías lo de la contraseña sin perder lo interactivo?"* ([issue #224](https://github.com/Oscarsp15/nz-mcp/issues/224)).

La respuesta corta es que la condición 5 prohíbe menos de lo que su cláusula 2 daba a entender.
Lo prohibido es **que la credencial se guarde en un widget**. Un widget que no guarda nada no
está prohibido, solo no se había escrito.

### Lo que se midió esta vez, sobre `textual` 8.2.8

| Prueba | Resultado |
|---|---|
| `events.Key` de una tecla imprimible | `character` es una `str` de **un** carácter, y `is_printable` la distingue de las teclas de control sin heurística nuestra |
| `Input(password=True)` recibe un pegado | `Input.value` pasa a ser la cadena pegada completa, en claro. Confirma la medición original |
| `events.Paste` | `Paste(text: str)`: el pegado llega **entero**, como `str` desnuda, construido por el parser de la terminal **antes** de que corra ningún manejador nuestro |
| Vida del mensaje `Paste` tras el manejador | Con `weakref`: **sigue vivo** después del despacho y después de 300 ms de inactividad. Solo se recoge cuando se procesa **otro** mensaje |
| ¿Se puede soltar esa referencia? | **Sí.** `Paste.text` es un atributo escribible: vaciarlo tras consumirlo deja el mensaje sin la credencial, y su `__rich_repr__` —lo que imprimiría una consola de devtools— pasa a estar vacío |
| ¿Queda alguna copia más? | **Sí, y no es nuestra.** `pasted_text`, un local del frame suspendido del generador del parser (`parser._gen.gi_frame.f_locals`), conserva una copia completa hasta el siguiente pegado con corchetes |
| `export_screenshot()` con el campo nuevo lleno | No contiene la credencial. Contiene la máscara |
| Recorrido del grafo de objetos desde `App` y desde `Screen`, sin tope práctico de profundidad, siguiendo `__dict__`, `__slots__`, `__closure__`, `__self__` y `__func__` | **Limpio.** El único camino que aparece a la credencial pasa por `sys.modules` hasta la variable del propio script de ataque |

### Qué cambia

**La cláusula 2 de la condición 5 se reescribe así:**

> Ningún `Input` del asistente recibe nunca la credencial, ni siquiera con `password=True`. El
> asistente puede tener un campo propio para la contraseña siempre que **su estado no contenga
> texto**: `SecretField` guarda tres enteros (cuántos caracteres hay, dónde está el cursor, dónde
> empezó la selección) y un booleano, dibuja la máscara a partir del contador, y entrega cada
> pulsación —tecleada o pegada— a un `CredentialSink` que vive fuera del árbol. Ese protocolo es
> **de solo escritura**: acepta un carácter en una posición, borra un rango y olvida; no se le
> puede preguntar qué tiene. La suspensión con `App.suspend()` y `cli_output.ask_secret()`
> **se conserva como red**, en Ctrl+P, para quien prefiera no escribirla en pantalla.

Consecuencias que hay que declarar sin adornos:

1. **Ahora hay dos puertas, no una.** La adenda 1 apoyaba parte de la garantía en que
   `ask_password: Callable[[], bool]` *no puede transportar una cadena*. Sigue siendo cierto de
   esa puerta, pero la segunda —`insert(index, character)`— **sí transporta texto**: un carácter,
   en dirección widget → fuera. El argumento "por construcción" se debilita ahí y se refuerza en
   otro sitio: el sumidero **no tiene método de lectura**, así que nada que alcance al widget
   puede reconstruir la credencial a través de él.
2. **La credencial no existe entera mientras la pantalla está abierta.** El sumidero guarda
   `list[str]` de un carácter, y se une **una sola vez**, al final, dentro de un `Secret`. No es
   una astucia para pasar un test: un búfer `str` construiría una copia completa de la credencial
   en cada pulsación, que es exactamente lo que esta ADR midió dentro de `Input` y la razón por la
   que se descartó ese widget. La lista es la estructura correcta y la no contigüidad es su
   consecuencia. También vale la pena decir qué **no** es: no es cifrado. Un volcado de memoria la
   recompone. La propiedad que se afirma es de alcanzabilidad entre objetos, la misma clase de
   propiedad que afirma la [ADR 0026](0026-secret-sin-password-en-trazas.md).
3. **El pegado se permite, y se acepta un riesgo estrecho por escrito.** Aquí la primera versión de
   esta adenda decía que se prohibía, y estaba equivocada por exceso de celo. Lo que hay que
   revisar no es la medición, que sigue en pie, sino **la promesa que se le exigía**.

   *Qué se acepta*: la cadena pegada existe entera, como `str` desnuda, durante un instante y
   dentro de objetos que no son nuestros. No podemos evitar que se cree: la construye el parser
   antes de que corra ninguna línea nuestra.

   *Cuál es la exposición concreta*. Son **dos** copias, no una, y la lista tiene que estar
   completa o no sirve de nada. La auditoría del PR #225 señaló que la primera redacción declaraba
   solo la segunda:

   1. **El propio `event`, en un frame nuestro.** `on_paste` recibe el evento como argumento, así
      que mientras la llamada esté en la pila el texto es alcanzable por cualquier renderizado que
      muestre argumentos o locales —pytest por defecto, y el manejador de fallos de `textual`—. La
      auditoría lo **reprodujo ejecutando**: con un pegado real y el sumidero fallando en el sexto
      carácter, la traza mostraba `event = Paste(text='<la credencial>')`. Estaba en el camino
      feliz, que es el error que este proyecto ya ha cometido antes. Se corrige con un `finally`
      que vacía la referencia pase lo que pase, y hay un test que provoca la excepción de verdad y
      lee la traza en los cinco estilos de `--tb`. **La ventana se reduce al bloque `try` completo, que incluye las llamadas previas al bucle y no solo su cuerpo (medido: un frame capturado dentro de `credential.clear()`, que corre antes del bucle, todavía alcanza `event.text` entero);
      no desaparece**: un fallo *dentro* del bucle sigue teniendo el evento vivo en ese instante,
      solo que ya no queda nada después.
   2. **`pasted_text`, en un frame que no es nuestro.** Un local del frame suspendido del generador
      del parser de `textual` conserva una copia completa hasta el siguiente pegado con corchetes.
      Una traza con locales que pasara por ahí la mostraría, porque ese frame no lo escribimos
      nosotros y no lleva `Secret`. No hay forma de alcanzarlo desde este paquete.

   *Qué sí está en nuestra mano, y se hace*: soltar la referencia en cuanto se consume.
   `Paste.text` es escribible, así que el manejador la vacía **en un `finally`** después de
   recorrerla, y el mensaje que el bus conserva deja de llevar la credencial —igual que su
   `__rich_repr__`, que es lo que imprimiría una consola de devtools o un log de mensajes—. Es
   todo lo que se puede estrechar el instante; lo demás no depende de nosotros y así está dicho.

   *Por qué se acepta*: la molestia de no poder pegar es **diaria y segura** —un gestor de
   contraseñas es la forma normal de escribir una credencial— y el riesgo es **estrecho y raro**.
   Y hay un argumento que cierra la incoherencia: **`Secret` tampoco protege la memoria**. Guarda
   el texto real en un `str` y lo que controla es cómo se renderiza. Exigirle al evento de pegado
   una garantía que nuestro propio tipo no da era pedir de más.

   *Qué sigue garantizado*, que es lo que el modelo de amenaza pide de verdad: no se muestra en
   pantalla, no entra en registros, no sale en una captura y no aparece en ningún mensaje de error
   construido por **nuestro** código —incluidos los que se construyen cuando algo falla a mitad de
   un pegado, que es justo lo que la auditoría encontró roto y ahora tiene test propio—.

   La regla estática que prohibía leer `.text` se **acota** en vez de retirarse: ahora prohíbe
   *copiarlo* —ligarlo a un nombre, guardarlo en un atributo o pasarlo a una llamada, se escriba
   con punto o con `getattr`— y permite las dos formas que sí tienen sentido, recorrerlo en el
   sitio y vaciarlo. Sigue siendo análisis estático y sigue teniendo agujeros conocidos; están
   enumerados en el propio archivo del guardarraíl, que es donde se leen.
4. **La máscara enseña la longitud, y solo mientras el campo tiene el foco.** `cli-experience.md`
   §4 dice que ni enmascarada se muestra la password, y esa frase se refiere a la **recapitulación**
   —seguir sin mostrarla ahí—; un campo de entrada es otra cosa, es el editor. Aun así la longitud
   es información, así que el campo dibuja la máscara **solo con el foco puesto** y, sin foco,
   vuelve a decir únicamente *"definida / sin definir"*. Una pantalla que alguien deja atrás no
   lleva ni la longitud. Y si la credencial se dio por Ctrl+P, el campo **no aprende su longitud**:
   se queda en cero y lo dice con palabras.
5. **El test de ejecución se amplía y se endurece, que es lo que pedía la adenda 1.**
   `test_the_real_wizard_never_lets_the_credential_into_a_widget` ahora recorre **los dos** caminos
   —tecleado carácter a carácter y Ctrl+P—, busca el valor en el árbol de widgets, en el estado de
   la aplicación, en el resultado y en una **captura del framework**; y su búsqueda sigue ahora
   closures, métodos ligados y funciones, porque el diseño nuevo entrega a un widget un objeto que
   escribe en el almacén: no seguir los invocables sería estar de acuerdo con el código en vez de
   comprobarlo. La captura limpia se acompaña de su control negativo: la misma captura, con el
   valor escrito a mano en un campo, **sí** lo contiene.

### Qué no cambia

- **Cláusula 1**: el modelo de estado del asistente sigue sin campo de password. `DraftFields`
  tiene siete campos y ninguno es la credencial; lo que viaja al lado es un booleano.
- **Cláusula 3**: ni devtools ni capturas en el camino de producción. La captura de arriba se toma
  **en un test**, que es donde el guardarraíl estático la permite y la producción no.
- **La suspensión sigue existiendo** como red: es la alternativa para quien prefiera no teclear
  una credencial en una pantalla completa, y el camino que queda si el campo no está disponible.
- **La adenda 1 sigue mandando** sobre qué garantiza qué: el test de ejecución es la garantía, el
  guardarraíl estático es defensa en profundidad, y esta adenda no lo presenta como demostración
  aunque haya crecido con dos reglas nuevas.

### Qué monitorizar, ampliado

- Que el estado de `SecretField` siga siendo enteros y un booleano. Está fijado por nombre y por
  anotación en las listas blancas del guardarraíl.
- Que `CredentialSink` **no gane un método de lectura**. El día que lo gane, el argumento "de
  construcción" de esta adenda desaparece.
- Que el test de ejecución siga recorriendo los dos caminos y siga siguiendo closures. Si vuelve a
  buscar solo en `__dict__`, la condición 5 deja de estar comprobada para el diseño nuevo.
- Si una versión futura de `textual` deja de vaciarse cuando le vaciamos `Paste.text`, o deja de
  soltar `pasted_text` en el frame del parser, **el riesgo aceptado en la decisión 3 cambia de
  tamaño** y hay que volver a medirlo. Está aceptado con las cifras de 8.2.8 delante, no en
  abstracto.

## Referencias

- [ADR 0028](0028-asistente-de-configuracion-interactivo.md) — la enmienda al 0005 que abre la puerta
- [ADR 0027](0027-adoptar-rich-para-la-presentacion-del-cli.md) — `rich` acotado, confinado y su cierre transitivo
- [ADR 0026](0026-secret-sin-password-en-trazas.md) — `Secret` y sus límites declarados
- [ADR 0005](0005-sin-frontend.md) — sin frontend ni TUI, salvo la excepción del 0028
- [docs/architecture/cli-experience.md](../architecture/cli-experience.md) §7 — la librería la decide un ADR
- `src/nz_mcp/cli_output.py` y `tests/contract/test_serve_stdout_protocol_only.py` — la capa de
  salida, la reserva de descriptor y el detector AST
- PR #163 (acotar rangos de dependencias) y PR #187 (subir el suelo de `sqlglot`) — el precedente de
  los rangos sin tope
