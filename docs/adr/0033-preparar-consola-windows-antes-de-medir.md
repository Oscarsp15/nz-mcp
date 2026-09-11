# ADR 0033 test
# ADR 0033 — El CLI prepara la consola de Windows antes de medir su capacidad

- **Fecha**: 2026-09-11
- **Estado**: aceptado — **enmienda el [ADR 0031](0031-mejora-progresiva-por-capacidad-del-terminal.md)** en un punto de orden: la señal 7 de su punto 2 (Windows sin `WT_SESSION` y sin code page 65001) pasa a evaluarse **después** de intentar mejorar la consola, no antes. La lógica de la señal no cambia una línea; lo que cambia es qué consola se le pregunta. El resto del ADR 0031 sigue vigente sin cambios.
- **Decidido por**: TUI Designer (IA) + validación humana (auditor: Security Engineer)
- **Issue**: [#255](https://github.com/Oscarsp15/nz-mcp/issues/255)
- **Alcance**: si el CLI puede **mejorar** la consola de Windows antes de preguntarle qué sabe hacer, qué toca al hacerlo, qué restaura y qué queda deliberadamente fuera. No decide qué se dibuja en cada nivel (ADR 0031) ni toca el modelo del menú (ADR 0030, punto 1: elige y no hospeda).

## Contexto

Validación humana del rediseño, 2026-09-11. El owner ejecutó `nz-mcp` en la consola clásica de
Windows (`cmd.exe`, no Git Bash) y vio **la ayuda en texto plano**, no el menú. Su consola arranca
en **code page 850** — el valor por defecto de un Windows en español — y sin `WT_SESSION`, así que
el ADR 0031 la clasifica, correctamente según sus propias reglas, como nivel 0. La degradación
funciona exactamente como se decidió: el problema no es un bug del detector, es que **detecta bien
un hecho que no tenía por qué seguir siendo cierto**.

La consecuencia es seria: **una parte grande de los usuarios de Windows no verá nunca el
rediseño**, y va a concluir, en carne propia y sin forma de saber que se equivoca, que el programa
no tiene menú. El owner lo comprobó dos veces, sabiendo cómo funciona por dentro.

La comparación que lo motiva es `opencode`, que en esa misma consola, con esa misma code page, se
dibuja perfecto. La diferencia no es el lenguaje ni el framework: los binarios nativos que se
comportan así **configuran la consola al arrancar** — activan el modo de terminal virtual y ponen
la salida en UTF-8 — en vez de rendirse ante lo que encuentran y dejar que el usuario cargue con la
diferencia. El ADR 0031 midió el entorno y degradó con corrección; lo que le faltaba era intentar
cambiarlo primero.

Decisión del owner el 2026-09-11: **camino A** — el CLI prepara la consola antes de medirla. No es
el camino B (cambiar cuándo o cómo se abre el menú), que queda fuera de este ADR a propósito.

## Decisión

### 1. Un intento, antes de la primera pregunta

`cli.entry_point()` — el callback que corre antes de cualquier subcomando — llama a
`cli_output.prepare_windows_console()` como su primera línea, salvo cuando el subcomando invocado
es `serve` (punto 5). Ninguna otra función de este módulo pregunta antes: `terminal_level()`,
`interactive_ui_blocker()`, `color_enabled()` y `animation_enabled()` no cambian ni una línea de su
lógica — siguen preguntando exactamente lo mismo que preguntaban — lo único que cambia es que, para
cuando preguntan, la consola ya tuvo su oportunidad de responder distinto.

Esto es, literalmente, la enmienda a la señal 7 del ADR 0031: la señal seguía pidiendo `WT_SESSION`
o code page 65001; ahora, en el caso corriente, **ella misma** encuentra 65001 porque este ADR ya
lo puso ahí. La función que mide (`_windows_console_renders_unicode()`) no se toca.

### 2. Qué se toca, y solo cuando hay una consola real de por medio

Tres gestos, en este orden, y solo en Windows (`os.name == "nt"`) y solo cuando `sys.stdout` o
`sys.stderr` responden `isatty()` — sin eso no hay consola que mejorar, y tocar la code page de un
proceso sin terminal no tiene destinatario:

1. **`SetConsoleOutputCP(65001)`** — la misma constante que `_windows_console_renders_unicode()`
   ya comparaba, ahora escrita en vez de solo leída.
2. **`ENABLE_VIRTUAL_TERMINAL_PROCESSING`** añadido al modo de consola de **los dos** manejadores
   de salida, `STD_OUTPUT_HANDLE` y `STD_ERROR_HANDLE` — el menú dibuja en el primero, `status()` y
   sus atajos dibujan en el segundo, y una consola que interprete secuencias ANSI en uno pero no en
   el otro dejaría la mitad de la salida en basura literal (`\x1b[...`).
3. **`sys.stdout.reconfigure(encoding="utf-8")` y lo mismo para `sys.stderr`**, cuando el flujo lo
   soporta. Es el paso que un cambio de code page por sí solo no cubre: Python ya abrió esos dos
   flujos contra la code page **anterior**, así que cambiar la consola sin reconfigurarlos deja
   exactamente el mojibake que esto existe para evitar — la propia salida de Python, no solo la de
   la API de consola, tiene que enterarse del cambio.

**Nada de esto se intenta si no hay una consola real detrás.** Redirigido a archivo, canalizado a
otro proceso, en CI: la comprobación de `isatty()` ya lo dice y no hay handle de consola al que
pedirle nada.

### 3. Qué se restaura, y con qué mecanismo

**Todo lo que el punto 2 cambió — la code page y los dos modos de consola — vuelve exactamente a
su valor de antes al terminar el proceso, pase lo que pase.** No solo la code page: dejar el modo
VT encendido después de salir sería un efecto secundario en una consola que el usuario no le pidió
a este programa que le tocara para siempre, y el mismo argumento que pide restaurar la code page
pide restaurar el modo.

El mecanismo es `atexit.register()`, elegido explícitamente frente a un `try`/`finally` alrededor
del comando: **el callback de entrada y el cuerpo del subcomando no comparten un único bloque** —
`click` los invoca como dos pasos seguidos de `MultiCommand.invoke()`, no uno anidado dentro del
otro — así que un `finally` escrito en el callback nunca vería un fallo del subcomando. `atexit`
no tiene ese problema: se registra en el momento en que la consola cambia y corre en el cierre
normal del intérprete, que es exactamente lo que ocurre tanto si el comando termina bien como si
una excepción se escapa sin capturar, como si el usuario pulsa **Ctrl+C** — `KeyboardInterrupt` sin
capturar todavía es un cierre normal del intérprete a efectos de `atexit`. Lo único que de verdad
se lo salta es que maten el proceso desde fuera (`taskkill /F`, un corte de energía), y frente a
eso ningún mecanismo dentro del propio proceso puede prometer nada.

Restaurar es la única responsabilidad de la función que `atexit` guarda: no reintenta, no avisa,
no lanza — si la propia restauración falla (la consola ya no existe, por ejemplo) se traga en
silencio, por la misma razón del punto 4.

### 4. Cualquier fallo se traga, siempre, sin ruido

Falta de permisos, una consola que se cerró o se redirigió a mitad de camino, una versión de
Windows sin la función, `ctypes.windll` inexistente: **ningún camino de este código lanza**.
Preparar la consola es una mejora opcional, nunca un requisito — el mismo principio que ya rige
`interactive_ui_blocker()` y `_console_output_code_page()` — así que cualquier fallo deja al
proceso exactamente donde estaría si este ADR no existiese: nivel 0, sin excepción y sin una línea
de aviso que nadie pidió leer.

### 5. `serve` queda fuera, sin excepción

La reserva de `stdout_reserved_for_protocol()` — adenda 1 del ADR 0027, el contrato del #203 — no
se toca, no se adelanta y no se relaja. `cli.entry_point()` solo llama a
`prepare_windows_console()` cuando `ctx.invoked_subcommand != "serve"`; para `serve`, y para
`serve --help`, la función ni se importa en ese camino de ejecución. La razón es de orden, no de
oportunidad: `ctx.invoked_subcommand` ya vale `"serve"` en el momento en que `click` invoca el
callback del grupo — antes de tocar nada del subcomando — así que la exclusión ocurre por nombre de
comando conocido, no por adivinar si stdout ya está reservado. `prepare_windows_console()` en sí
misma tampoco sabe nada de `stdout_reserved_for_protocol()`: ni la importa, ni la llama, ni podría
tocarla por accidente. Dos guardas independientes, cualquiera de las dos basta.

### 6. Variable de escape: `NZ_MCP_NO_CONSOLE_PREP`

Mismo patrón que `NZ_MCP_NO_TUI` (ADR 0028): cualquier valor cuenta como *sí* salvo `"0"` y
`"false"`, para que `NZ_MCP_NO_CONSOLE_PREP=1` haga lo obvio y `NZ_MCP_NO_CONSOLE_PREP=0` no
desactive en silencio algo que alguien quería. Quien la ponga no ve tocada su consola en absoluto:
ni code page, ni modo VT, ni reconfiguración de `sys.stdout`/`sys.stderr` — el CLI sigue
funcionando exactamente como hoy, con la degradación de siempre.

**Es independiente de `NZ_MCP_UI_LEVEL`.** `NZ_MCP_UI_LEVEL=0` fuerza el **dibujo** al piso —nada
de lo que se pinta usa un carácter fuera de ASCII ni una secuencia de escape—, pero no le pide nada
a la consola en sí: un `65001` de fondo no cambia ni un byte de una salida que ya es ASCII puro,
así que dejar la preparación activa bajo `NZ_MCP_UI_LEVEL=0` no contradice esa promesa. Quien
además no quiera que se le toque la consola —por ejemplo, porque un script externo depende de la
code page previa— tiene su propia variable, y las dos se pueden combinar.

**No es una tercera puerta del nivel 2.** No abre ni cierra la pantalla completa; solo decide si
este ADR hace algo antes de que `terminal_level()` y `interactive_ui_blocker()` pregunten lo suyo.

### 7. Lo que deliberadamente no se toca ni se restaura

- **La code page de *entrada* (`SetConsoleCP`) y `sys.stdin`.** El problema medido es de
  **dibujo**: el owner vio ayuda en vez de menú, no escribió un carácter acentuado que se
  corrompiera. Tocar la entrada es una superficie distinta — con su propio riesgo si alguien tiene
  un script que envía bytes en la code page antigua por `stdin` — y no tiene un caso medido detrás
  todavía. El día que aparezca uno, se decide con él.
- **El título de la ventana, el tamaño del búfer, la fuente de la consola.** Ninguno de los tres
  afecta a si un carácter se pinta bien o mal; tocar cosas que no hacen falta para resolver el
  problema medido es exactamente el código "porsiacaso" que este proyecto prohíbe.
- **Cualquier otro proceso que comparta la consola.** `SetConsoleOutputCP` y el modo VT son
  propiedades de la consola entera, no del proceso — un `cmd.exe` que lanzó `nz-mcp` y sigue vivo
  después hereda el cambio hasta que la restauración de este ADR lo deshaga al salir. Es el mismo
  trade-off que ya acepta cualquier programa que cambie la code page de una consola compartida;
  restaurar al terminar es lo que lo hace transitorio.

## Alternativas consideradas

1. **No hacer nada — dejar el ADR 0031 tal cual.** Es el statu quo que el owner rechazó al
   comprobar el problema en su propia consola. El detector sigue siendo correcto y la mayoría de
   usuarios de Windows en español sigue sin ver el rediseño.
2. **Camino B: cambiar cuándo se ofrece el menú** (por ejemplo, avisar en texto de que existe un
   modo mejor y cómo activarlo). Decidido explícitamente en contra por el owner el 2026-09-11: no
   arregla el problema, lo documenta. Sigue disponible como discusión futura si el camino A no
   bastase, pero no es este ADR.
3. **Preparar la consola siempre, sin comprobar `isatty()`.** Serían escrituras a una API de
   consola sin consola detrás — inofensivas casi siempre porque fallarían y se tragarían (punto 4),
   pero sin ningún beneficio y con una comprobación gratis que ya existe en el módulo
   (`_is_a_terminal`) para evitarlo.
4. **No restaurar, dejar el cambio para toda la sesión de la consola.** Se rechaza porque una
   consola compartida (punto 7) no le pertenece a este proceso, y un programa que cambia
   propiedades ajenas y no las devuelve es exactamente el tipo de sorpresa que un usuario de la
   consola clásica de Windows no está esperando de una herramienta de línea de comandos.
5. **Un `try`/`finally` en `entry_point()` en vez de `atexit`.** Descartado en el punto 3: el
   callback y el subcomando no están anidados en el mismo bloque de `click`, así que un `finally`
   ahí nunca vería una excepción del subcomando.

## Consecuencias

### Positivas

- **El escenario medido se arregla en el sitio donde se midió**: `cmd.exe`, code page 850, sin
  `WT_SESSION`, pasa de nivel 0 a nivel 1 sin que el usuario haga nada.
- La enmienda a la señal 7 del ADR 0031 es de una frase: ninguna prueba de ese ADR cambia su
  resultado, porque la función que miden no se toca.
- La restauración con `atexit` es reutilizable: cualquier preparación futura de este tipo (si
  alguna vez hiciera falta otra) tiene ya el patrón escrito.

### Negativas y costes

- **Una API de sistema más de la que depender**, aunque tolerada por completo: cinco funciones de
  `kernel32` en vez de una.
- **Una consola compartida se ve afectada hasta que el proceso termina.** Aceptado y documentado en
  el punto 7; es el precio de cualquier programa que cambie una propiedad de consola.
- **Dos variables de entorno de escape para el mismo subsistema** (`NZ_MCP_NO_CONSOLE_PREP` y
  `NZ_MCP_UI_LEVEL`), con la relación entre ambas para documentar y no confundir — se explica en el
  punto 6 y queda en el CHANGELOG.

### Qué monitorizar

- Issues de *"la consola quedó rara después de cerrar `nz-mcp`"* — indicaría que la restauración no
  cubre algún camino de salida.
- Cualquier reporte de mojibake en Windows **después** de este ADR sería más grave que antes,
  porque significaría que el code page cambió sin que los flujos de Python se enterasen: es
  exactamente el punto 2.3 y tiene que seguir cubierto por un test.

## Lo que este ADR no decide

- **No decide qué se dibuja en cada nivel.** Eso sigue siendo del ADR 0031 y no cambia una línea.
- **No cambia el modelo del menú.** El menú sigue eligiendo y no hospedando (ADR 0030, punto 1);
  es el camino B, explícitamente fuera de alcance.
- **No toca la reserva de stdout de `serve`.** Punto 5: la exclusión es total.
- **No añade una dependencia.** `ctypes` es de la librería estándar, ya se importa en el mismo
  módulo para `_console_output_code_page()`, y sigue confinado al camino de Windows.

## Referencias

- [ADR 0031](0031-mejora-progresiva-por-capacidad-del-terminal.md) — la regla de niveles que este
  ADR enmienda en un punto de orden, no de lógica
- [ADR 0027](0027-adoptar-rich-para-la-presentacion-del-cli.md), adenda 1 — la reserva de stdout
  que este ADR no toca
- [ADR 0028](0028-asistente-de-configuracion-interactivo.md) — origen de `NZ_MCP_NO_TUI`, el
  patrón que copia `NZ_MCP_NO_CONSOLE_PREP`
- `docs/roles/tui-designer.md` — el rol que redacta este ADR
- `src/nz_mcp/cli_output.py` — `prepare_windows_console()`, `_windows_console_renders_unicode()`,
  `stdout_reserved_for_protocol()`
- `src/nz_mcp/cli.py` — `entry_point()`, el único llamador
- Issue [#255](https://github.com/Oscarsp15/nz-mcp/issues/255)
