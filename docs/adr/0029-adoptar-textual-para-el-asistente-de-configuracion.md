# ADR 0029 — Adoptar `textual` acotado y confinado para el asistente de configuración

- **Fecha**: 2026-09-06
- **Estado**: aceptado
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
