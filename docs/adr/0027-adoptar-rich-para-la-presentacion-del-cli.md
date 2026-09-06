# ADR 0027 — Adoptar `rich` como dependencia directa acotada para la presentación del CLI

- **Fecha**: 2026-09-05 (adenda 1: 2026-09-06)
- **Estado**: aceptado, con una adenda que precisa la condición 1 — ver [Adenda 1](#adenda-1-2026-09-06--la-condición-1-pasa-a-ser-ninguna-consola-escribe-a-stdout)
- **Decidido por**: Tech Lead (IA) + validación humana (auditor: DX Engineer)
- **Issue**: [#204](https://github.com/Oscarsp15/nz-mcp/issues/204) · sale de [`docs/architecture/cli-experience.md`](../architecture/cli-experience.md) §7

## Contexto

La dirección del owner para el CLI, del 2026-09-05, es explícita: *"me gustaría que se vea muy
bien estéticamente y amigable, buenas animaciones lo necesario, llamativo"*. El diseño de la
experiencia de terminal traduce eso a cosas concretas —indicadores de espera, tabla en
`list-profiles` y en `probe-catalog --verbose`, ayuda sin jerga— y deja escrito que **no** elige
librería: eso es arquitectura y la regla inviolable nº 5 de `AGENTS.md` exige ADR.

### La premisa de partida era falsa, y el problema real es otro

El diseño §7 y el propio issue #204 afirman que `rich` *"no está instalado ni declarado y no se
puede importar desde el entorno del proyecto (`ModuleNotFoundError`)"*, y desmienten con eso al
issue #169. **Comprobado hoy sobre el entorno del proyecto, es al revés**:

```
typer 0.25.0   Requires-Dist: click>=8.2.1, shellingham>=1.3.0, rich>=13.8.0, annotated-doc>=0.0.2
rich  15.0.0   importable:  .venv/Lib/site-packages/rich/__init__.py
```

`typer` dejó de tener `rich` detrás de un extra: la distribución `typer` **exige** `rich>=13.8.0`
de forma dura (quien no lo quiere instala `typer-slim`). Como `pyproject.toml` declara
`typer>=0.15`, **cada instalación de nz-mcp que existe hoy ya trae `rich` dentro**, junto con
`markdown-it-py`, `mdurl` y `pygments`. La premisa correcta es la del #169.

Eso cambia la pregunta. No es *"¿pagamos una dependencia nueva?"*, porque ya la estamos pagando.
Es *"¿la declaramos y la acotamos, o seguimos usándola de prestado?"*. Y el estado actual es el
peor de los tres posibles:

- **Sin declarar**: si `typer` vuelve a mover `rich` a un extra, o pasa a basarse en
  `typer-slim`, `rich` desaparece del cierre transitivo y cualquier `import rich` revienta en
  tiempo de ejecución, en el arranque del CLI, en casa del usuario.
- **Sin suelo**: el `rich>=13.8.0` lo fija `typer`, no nosotros. Si mañana `typer` baja ese
  suelo, nz-mcp hereda el cambio sin enterarse.
- **Sin tope**: nada impide que un `pip install nz-mcp` resuelva `rich 16.x` el día que salga.

Ese último punto ya ha costado dos veces en este repo. El PR #163 tuvo que acotar tres
dependencias de golpe porque el CI resolvía cualquier versión, y el #187 tuvo que **subir** el
suelo de `sqlglot` porque una versión que el rango permitía rompía `sql_guard` en silencio. Un
rango sin tope no es flexibilidad: es deuda con intereses.

### Lo que el CLI necesita de verdad

Sale del diseño, secciones 3 y 4:

| Necesidad | ¿La cubren veinte líneas propias? |
|---|---|
| Indicador indeterminado a stderr mientras se abre la sesión | **Sí.** Un carácter que rota sobre `\r`, un hilo y un `isatty` |
| Progreso determinado `n/14` en `probe-catalog` | **Sí**, con esfuerzo |
| Tabla de perfiles y tabla de `probe-catalog --verbose` | **No** |
| Alinear columnas con texto ES/EN y anchos de carácter variables | **No** |
| Habilitar VT en consolas de Windows heredadas | **No** |
| Matriz `isatty` × `NO_COLOR` × `TERM=dumb` × `FORCE_COLOR` × CI, ya probada | **No** |
| Paneles de ayuda de Typer | **No**: los pinta `rich`, o no se pintan |

## Decisión

**Se adopta `rich` como dependencia directa de nz-mcp, declarada en `pyproject.toml` y acotada a
`rich>=13.8,<16`**, con cuatro condiciones que forman parte de la decisión y no de su
implementación:

1. **Toda consola se construye contra `stderr`.** Sin excepción, sin bandera que lo cambie, ni
   siquiera detrás de una comprobación de terminal. `rich.console.Console()` escribe por
   **stdout** por defecto: es exactamente el byte que rompe el JSON-RPC de `serve`. Solo se
   admite `Console(stderr=True)`, y eso queda cubierto por un test.
   > **Precisada por la [Adenda 1](#adenda-1-2026-09-06--la-condición-1-pasa-a-ser-ninguna-consola-escribe-a-stdout)**:
   > la condición vigente es *"ninguna consola escribe a stdout"*, que admite además la consola
   > contra un buffer en memoria. Léase esa adenda antes de aplicar esta cláusula.
2. **`rich` se importa únicamente desde `src/nz_mcp/cli_output.py`.** Ningún otro módulo lo
   nombra. Lo vigila el detector AST de `tests/contract/test_serve_stdout_protocol_only.py`, que
   ya rechaza rutas directas a la salida estándar fuera de la capa; el día que se use `rich` se
   le añade a esa lista, de modo que un `from rich.console import Console` fuera de la capa
   rompe el CI en vez de romper a un usuario.
3. **La capa de salida expone su propio vocabulario** (`status`, `progress`, `table`), no el de
   `rich`. El resto del código pide *"indicador indeterminado"*, no `Console.status`. Es lo que
   convierte un cambio de major en el trabajo de un módulo en vez de en una migración.
4. **La barrera va antes que la pintura.** El #203 —capa de salida única y test de contrato que
   arranca `serve` de verdad— **ya está mergeado** (PR #211) y es requisito previo de cualquier
   uso de `rich`. Ese orden no es burocracia: la librería que mejor cumple el objetivo estético
   es la que más fácil hace violar el contrato de `serve`.

### Rango elegido, y por qué ese

- **Suelo `>=13.8`**: es el mismo que `typer` exige hoy, así que no introduce un conflicto de
  resolución, y es la primera versión que este proyecto puede garantizar que trae lo que usa
  (`Console(stderr=True)`, `Console.status`, `NO_COLOR` y `TERM=dumb` respetados). Bajar de ahí
  sería declarar un suelo que nadie ha probado.
- **Tope `<16`**: `rich` sube de major cada año o poco más (13 → 14 → 15) y cada major toca la
  API de consola. El tope no dice "`rich 16` es malo"; dice "`rich 16` no lo ha leído nadie
  todavía". Subirlo es un PR con la suite en verde, que es exactamente el trabajo que el #187
  demostró que hace falta hacer a mano.

### Cierre transitivo, enumerado

Lo que entra al declarar `rich>=13.8,<16`, medido sobre la resolución actual del proyecto:

| Paquete | Versión resuelta hoy | Por qué está | Peso en disco | `py.typed` |
|---|---|---|---|---|
| `rich` | 15.0.0 | la dependencia que decide este ADR | 3,0 MB | sí |
| `markdown-it-py` | 4.0.0 | `rich` lo exige (`>=2.2.0`): renderiza Markdown | 789 KB | sí |
| `mdurl` | 0.1.2 | `markdown-it-py` lo exige (`~=0.1`) | 68 KB | no |
| `pygments` | 2.20.0 | `rich` lo exige (`>=2.13.0,<3`): resaltado de sintaxis | 9,5 MB | no |

**Total ≈ 13,4 MB**, de los cuales **8,2 MB son los lexers de `pygments`**, que nz-mcp no va a
usar jamás porque no resalta sintaxis en ningún sitio. Es un coste feo y se escribe aquí sin
maquillarlo.

Lo que lo hace aceptable es que **el coste marginal de esta decisión es cero bytes**: esos
13,4 MB ya están instalados en toda instalación de nz-mcp por la vía de `typer`, y lo seguirían
estando aunque este ADR decidiera lo contrario. Renunciar a `rich` no ahorraría un byte a nadie;
solo nos privaría de usar lo que el usuario ya se ha descargado.

## Alternativas consideradas

1. **No adoptar nada y escribir veinte líneas propias.** Es la alternativa seria, y cubre *una*
   de las siete necesidades de la tabla de arriba: el indicador indeterminado. De hecho el
   indicador del #205 se implementa así a propósito, porque un `\r` con un hilo y un `isatty` no
   necesita 13 MB. Donde se cae es en el formato. Alinear columnas a mano con texto en dos
   idiomas obliga a medir anchos de carácter, decidir el truncado columna a columna, tratar el
   ancho doble y volver a hacerlo entero cada vez que aparece una tabla nueva. Eso no son veinte
   líneas: es un módulo de formato con sus propios bugs y sus propios tests, mantenido por
   nosotros, para reimplementar algo que ya viene instalado. Se rechaza por eso, no por
   comodidad.
2. **Seguir usando `rich` sin declararlo** (el estado de hecho de hoy, y el que quedaría vigente
   si este ADR no existiera). Es la peor opción: depender de un paquete que otro proyecto decide
   por nosotros, sin suelo propio, sin tope y sin aviso el día que `typer` cambie de opinión. Se
   rechaza.
3. **Declararlo sin tope (`rich>=13.8`).** Es lo que hacía el proyecto antes del #163 con tres
   dependencias, y el #187 enseñó la factura. Se rechaza.
4. **`colorama`.** Solo resuelve ANSI en Windows: ni tablas, ni indicadores, ni medición de
   ancho. `rich` lo subsume y además ya está descargado. Se rechaza.
5. **`textual`.** Es un framework de TUI y chocaría de frente con el
   [ADR 0005](0005-sin-frontend.md). Se rechaza sin más análisis.

## Consecuencias

### Positivas

- El CLI puede cumplir la dirección estética del owner sin que el proyecto se convierta en
  mantenedor accidental de una librería de formato de terminal.
- Lo que hoy es una dependencia de prestado pasa a tener suelo, tope y dueño. Dependabot ve
  `rich` en `pyproject.toml` y propone sus subidas como propone las demás.
- La detección de terminal deja de ser cosa nuestra en el camino visual: comprobado sobre `rich`
  15.0.0, `Console.status()` con destino no-terminal escribe **cero bytes**, y
  `Console(stderr=True, force_terminal=True)` sigue respetando `NO_COLOR`. Es la restricción R2
  del diseño, ya implementada y probada por terceros.
- `rich` trae `py.typed`, así que `mypy --strict` no necesita `ignore_missing_imports` para él.

### Negativas y costes

- **13,4 MB de cierre transitivo**, con 8,2 MB de lexers de `pygments` que no se usan. El coste
  marginal es cero hoy, pero deja de serlo el día que `typer` deje de exigir `rich`: a partir de
  ahí lo pagamos nosotros, y con este ADR lo pagamos a sabiendas.
- **Superficie de mantenimiento.** Un major de `rich` es trabajo real. Acotado, eso sí, a un
  archivo (`cli_output.py`) y a un rango en `pyproject.toml`, porque la condición 2 impide que
  el resto del código lo importe. El plan ante `rich 16` es leer su changelog, subir el tope y
  correr la suite; si algo se rompe, se rompe en un módulo y con nombre y apellidos.
- **`pygments` no trae `py.typed`.** Si algún día se importara directamente haría falta un
  `ignore_missing_imports`. Hoy no se importa y no debe importarse.
- **El riesgo de stdout es real y permanente.** `Console()` por defecto escribe a stdout, así
  que la librería que mejor sirve al objetivo es la que más fácil rompe `serve`. La condición 1
  y el detector AST son la respuesta: el riesgo no desaparece, se le pone un test delante.

### Qué monitorizar para saber si fue buena idea

- Que `pyproject.toml` no acabe con `rich` sin tope después de un merge de Dependabot.
- Que ningún módulo fuera de `cli_output.py` importe `rich`.
- Que el stdout de `serve` siga siendo JSON-RPC puro (test de contrato del #203).
- Si `typer` deja de exigir `rich`, revisar si los 13,4 MB siguen compensando o si conviene
  volver a la alternativa 1 para lo poco que quedaría por cubrir.

## Lo que este ADR no decide

- **No enmienda el [ADR 0005](0005-sin-frontend.md).** Sigue sin haber frontend, UI propia ni
  TUI navegable. Se adopta `rich` como librería de **formato y progreso en comandos puntuales**;
  no se adopta `rich.live` para dibujar pantallas, ni `rich.prompt` para capturar el teclado, ni
  nada que convierta el CLI en un interfaz. Un modo interactivo sería una enmienda aparte al
  0005, con argumentos propios.
- **No decide qué se muestra.** Eso es del diseño de la experiencia y del rol DX. Este ADR dice
  con qué se pinta y qué cuesta, no qué se pinta.
- **No obliga a usar `rich` donde no aporta.** El indicador indeterminado del #205 se implementa
  sin él y está bien así: la decisión es *poder* usarlo con red de seguridad, no usarlo en todas
  partes.

## Adenda 1 (2026-09-06) — la condición 1 pasa a ser "ninguna consola escribe a stdout"

- **Origen**: primera implementación de la decisión, en el PR de la tabla de `list-profiles`
  ([#169](https://github.com/Oscarsp15/nz-mcp/issues/169)). Propuesta por el rol DX, confirmada
  por la auditoría.
- **Estado**: aceptada. Sustituye a la redacción original de la condición 1; el resto del ADR no
  cambia.

**Redacción anterior**: *"Toda consola se construye contra `stderr`. Sin excepción, sin bandera
que lo cambie, ni siquiera detrás de una comprobación de terminal."*

**Redacción vigente**: **ninguna consola de `rich` escribe a stdout.** En la práctica eso deja
dos formas admitidas de construirla, y solo dos:

1. `Console(stderr=True)`, cuando lo que se pinta va a la pantalla en el momento.
2. `Console(file=<buffer en memoria>)`, cuando lo que se quiere es **texto** y el canal lo decide
   quien llama. Es lo que hace `cli_output.table()`, que devuelve una cadena en vez de escribir.

Ambas siguen cubiertas por test, y la condición 2 —`rich` solo se importa desde
`cli_output.py`— se mantiene intacta: fuera de la capa no se construye ninguna consola de
ninguna de las dos formas.

**Por qué la nueva redacción no relaja nada, sino que protege más.** Lo que la condición
original perseguía era que ningún byte de `rich` pudiera acabar en el descriptor 1, que es por
donde `serve` habla JSON-RPC. Medido sobre el comportamiento real:

| | `Console(stderr=True)` | `Console(file=io.StringIO())` |
|---|---|---|
| ¿Mantiene viva una referencia a un descriptor del proceso? | **Sí**, al 2 | **No**, a ninguno |
| ¿Puede escribir a stdout? | No | No |
| ¿Puede escribir a stderr? | Sí, es su trabajo | **No** |
| `isatty()` del destino | depende del entorno | siempre falso |

Es decir: la consola contra un buffer es un **superconjunto estricto** de la protección. No
puede escribir a stdout —lo que la condición exigía— y además no puede escribir a ningún otro
sitio, porque no posee ningún descriptor. La redacción original la habría prohibido sin ganar
nada de seguridad a cambio, y habría obligado a que la única forma de tener una tabla fuese
pintarla directamente en pantalla, cerrando la puerta a que el mismo renderizador sirva para
carga útil por stdout (que sale por `emit()`, protegido aparte por la reserva de descriptor) y
para informe humano por stderr.

**Consecuencia práctica**: el vocabulario de la capa gana funciones que *devuelven texto* además
de las que *escriben*. `table()` es la primera; la regla para cualquier otra es la misma —si
devuelve texto, su consola va contra un buffer; si escribe, va contra stderr.

## Referencias

- [docs/architecture/cli-experience.md](../architecture/cli-experience.md) §2, §3 y §7 — restricciones y recomendación
- [docs/roles/dx-engineer.md](../roles/dx-engineer.md) — "Qué NO decide este rol": la librería la decide un ADR
- [ADR 0005](0005-sin-frontend.md) — sin frontend ni TUI
- `src/nz_mcp/cli_output.py` y `tests/contract/test_serve_stdout_protocol_only.py` — la barrera del #203 (PR #211)
- Issues [#169](https://github.com/Oscarsp15/nz-mcp/issues/169), [#201](https://github.com/Oscarsp15/nz-mcp/issues/201), [#204](https://github.com/Oscarsp15/nz-mcp/issues/204) y [#205](https://github.com/Oscarsp15/nz-mcp/issues/205)
- PR #163 (acotar rangos de dependencias) y PR #187 (subir el suelo de `sqlglot`) — el precedente de los rangos sin tope
