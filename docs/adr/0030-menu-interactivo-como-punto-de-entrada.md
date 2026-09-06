# ADR 0030 — El menú interactivo es la segunda excepción al ADR 0005, y no una tercera puerta

- **Fecha**: 2026-09-06
- **Estado**: aceptado — **amplía el [ADR 0028](0028-asistente-de-configuracion-interactivo.md)**, que sigue vigente en todo lo demás
- **Decidido por**: DX Engineer (IA) + validación humana (auditor: QA Engineer)
- **Issue**: [#226](https://github.com/Oscarsp15/nz-mcp/issues/226)
- **Alcance**: **qué** se permite ahora que hay una segunda pantalla, y con qué límites. La librería sigue siendo la del [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md); este ADR no vuelve a elegirla.

## Contexto

Decisión de producto del owner, del 2026-09-06, literal: *"no me cuadra que al poner `nz-mcp` aparezca una lista, luego el comando, y luego en el comando está lo interactivo. Debería ser todo interactivo"*.

Este ADR existe porque el propio ADR 0028 lo exige. Su riesgo 5 dice, con nombre y apellidos:

> **Que el interfaz se convierta en la puerta de entrada de la próxima excepción.** El precedente es el riesgo. **Contención**: la lista "Qué NO cambia" de arriba, por nombre. Cualquier segundo comando que quiera interfaz necesita **su propia enmienda y sus propios argumentos**; este ADR no sirve de jurisprudencia.

Así que esto no es un permiso heredado. Es la enmienda propia, con sus argumentos propios.

### Lo primero: el menú no es un comando

La lista "Qué NO cambia" del ADR 0028 enumera nueve comandos que siguen siendo texto puro. **Este ADR no toca ninguno de los nueve.** Lo que gana pantalla no es un comando: es el hueco que queda cuando no se escribe ninguno.

| | ADR 0028 | Este ADR |
|---|---|---|
| Qué gana pantalla | `nz-mcp init` y la rama interactiva de `add-profile` | `nz-mcp` **sin argumentos** |
| Qué sustituye | ocho preguntas encadenadas | la lista de ayuda que se imprimía y se acababa |
| Qué hace la pantalla | recoge ocho respuestas con estado vivo | elige **una** de once cosas y se cierra |
| Qué pasa con los once comandos | nueve siguen siendo texto | **los once** siguen siendo texto |

El argumento del ADR 0028 para negarle interfaz a los diez comandos era que *"se invocan con todo lo que necesitan, imprimen y terminan; no hay nada que navegar: sería una ventana alrededor de un `print`"*. Ese argumento sigue en pie y este ADR no lo contradice: **el menú no envuelve ningún `print`**. Envuelve una elección entre once, que es exactamente la clase de cosa que un interfaz hace mejor que un texto, y que hoy se resuelve leyendo una lista y volviendo a teclear.

### El síntoma que arregla

Hoy `nz-mcp` a secas imprime la ayuda y termina con código 2. Quien acaba de instalar lee once nombres, elige uno mentalmente y **vuelve a escribir**. Es el punto que el owner señala: la lista no lleva a ninguna parte.

## Decisión

**`nz-mcp` sin argumentos abre un menú de pantalla completa**, desde el que se elige un comando; el menú se cierra y el comando se ejecuta en la terminal de siempre. Fuera de eso, el ADR 0005 y el ADR 0028 no cambian en nada.

### 1. El menú elige, no hospeda

Es la decisión de forma más importante y la que evita casi todos los problemas.

Al elegir, **la pantalla se cierra y el comando corre en la terminal normal**, con su salida en el desplazamiento, donde se lee, se copia y se pega en un issue. **No se vuelve al menú.** Volver sería repintar una pantalla completa encima de la salida que la persona acaba de pedir, que es el riesgo 4 del ADR 0028 —*"un interfaz de pantalla completa borra la pantalla al salir y el diagnóstico se va con ella"*— cometido a propósito.

Consecuencias, todas queridas:

- **El proceso termina con el código de salida del comando**, igual que si se hubiera tecleado.
- **No hay reentrada**: no existe el caso "menú dentro de menú", ni una sesión larga que mantener viva.
- **Elegir `serve` desde el menú es idéntico a teclear `nz-mcp serve`**, y esto merece decirse porque la alternativa era peor. Excluirlo por nombre sería una lista negra, y una lista negra por nombre es exactamente lo que este proyecto ya ha visto fallar. No hace falta: la reserva de descriptor que protege el protocolo ocurre **después** de que la pantalla se haya ido, y el menú no tiene ningún privilegio que la persona no tenga con el teclado.

### 2. La degradación es un requisito, no una cortesía

Los disparadores del ADR 0028 se aplican igual, con la misma puerta (`cli_output.interactive_ui_blocker`) y sin una segunda implementación de nada. **Este PR añade el octavo**, que la auditoría encontró y que ninguno de los siete anteriores veía:

| Disparador | Cómo se detecta |
|---|---|
| `NZ_MCP_NO_TUI` | variable de entorno |
| `TERM=dumb` | variable de entorno |
| Sin TTY en entrada, salida o error | `isatty()` sobre las tres |
| **Proceso en segundo plano de la terminal** (`nz-mcp &`, `nohup`, `setsid`) | `os.tcgetpgrp(stdin)` frente a `os.getpgrp()` — **solo POSIX** |
| `TERM` vacío, sin definir o desconocido para terminfo (POSIX) | `curses.setupterm` y la capacidad `cup` |
| Consola de Windows sin secuencias VT | `rich.console.detect_legacy_windows` |
| Ventana por debajo del mínimo al arrancar | tamaño de la terminal |
| Ventana achicada por debajo del mínimo **a mitad de sesión** | `on_resize` dentro de la aplicación |

El de segundo plano merece su párrafo porque **es el que peor falla**. Un proceso lanzado con `&`, o que heredó los descriptores por `nohup` o `setsid`, tiene las tres TTY válidas, un `TERM` de verdad y una ventana correcta: **ninguno de los otros siete dice nada**. Si la pantalla arranca, leer el teclado provoca `SIGTTIN`, el proceso **se detiene con la pantalla alternativa abierta** y quien estuviera sentado delante se queda con la terminal inservible. Negarse a arrancar cuesta una pantalla de ayuda; equivocarse cuesta la terminal. Lo que no se puede preguntar —un flujo sin descriptor porque alguien lo sustituyó, un descriptor que no es una terminal— cuenta como *"no es nuestra"*, por el mismo cálculo.

**En Windows no aplica, y se dice en voz alta en vez de dejarlo implícito.** No hay grupos de proceso POSIX, no hay terminal que poseer y no existe `SIGTTIN`: allí un proceso desatendido no tiene consola —eso es el tercer disparador, `isatty` en falso— y uno lanzado con la consola compartida no se detiene por leerla. La plataforma se comprueba con `sys.platform` y no con `os.name` porque es la forma que el verificador de tipos estrecha, así que la rama POSIX ni siquiera se analiza en una compilación de Windows.

**Con cualquiera de los ocho, `nz-mcp` imprime la ayuda de siempre.** No una ayuda parecida: la misma. La pantalla no se reconstruye —se llama a `ctx.get_help()`, que es lo que `click` llamaba— y el código de salida sigue siendo **2**, el que devolvía `no_args_is_help`. Está comprobado byte a byte contra la salida anterior a este cambio.

Cada disparador tiene su test, y cada test arranca desde una **puerta abierta del todo**, para que ninguno pase en verde porque saltó otro; y cada uno comprueba además que **no se construyó nada** antes de decidir.

### 3. El mínimo es suyo, no el del asistente

`50x20`, frente a `60x21` del asistente. No es un número copiado: esta pantalla lleva once nombres cortos, una frase y una línea de teclas, y cabe en menos. Usar el mínimo del asistente sería rechazar ventanas en las que el menú funciona perfectamente. Hay test de que se le pregunta a la puerta por **este** mínimo, y de que en él no se cae nada fuera de pantalla.

### 4. El texto no se escribe dos veces

Las entradas del menú **no son una lista propia**: se construyen a partir de los comandos que `typer` tiene registrados. De ahí salen el orden —el orden de uso que ya ordena la ayuda (issue #209)— y la frase de cada uno, que es el `help=` del comando y viene del catálogo i18n (issue #217). Un comando nuevo aparece en los dos sitios o en ninguno.

El menú añade **dos claves i18n en total**: su título y su línea de teclas. Nada más.

### 5. Lo que la línea de órdenes no puede omitir se pregunta en texto plano

Cuatro comandos llevan el nombre de un perfil como argumento obligatorio. Lanzados en seco darían un error de uso, y un menú que no pudiera ofrecer `switch-profile` sería un menú sin lo que más se busca en un menú.

Se pregunta **después de cerrar la pantalla**, con el mismo `cli_output.ask()` de las preguntas encadenadas, y el texto de la pregunta es la ayuda del propio parámetro, ya escrita y ya traducida. Lo que **no** es: darle pantalla a ningún comando. El comando sigue siendo texto puro y recibe exactamente los argumentos que una persona habría tecleado.

Y se decide por lo que `click` sabe de cada parámetro, no por una tabla de nombres: un parámetro que deje de ser obligatorio desaparece de ahí solo, y uno que pase a serlo se pregunta sin que nadie se acuerde de volver.

### 6. Es la carcasa, y la costura está declarada

El acuerdo con el owner es que el menú es el paso 1 y **la carcasa donde luego enchufan las pantallas de cada comando**. Para que eso sea verdad y no una intención, la costura está en un sitio concreto: **el menú devuelve el nombre de un comando y nada más**. Decidir qué significa esa elección vive fuera del paquete, en el punto de entrada. El día que un comando tenga pantalla propia, el punto de entrada despacha hacia ella y `menu/` no cambia.

Lo que este ADR **no** concede: que ese día llegue por uniformidad. Convertir un comando en pantalla se decide **de uno en uno y por necesidad**, con su argumento y, si toca, su enmienda. Este ADR tampoco sirve de jurisprudencia.

### 7. Qué NO cambia, por nombre, otra vez

1. **Los once comandos siguen siendo texto puro.** `init` y `add-profile` conservan la excepción del ADR 0028 y ninguno de los otros nueve gana nada.
2. **`nz-mcp --help` y `nz-mcp <comando>` no cambian**, ni en salida ni en código de salida. Es lo que ve quien canaliza y lo que dice la documentación.
3. **`serve` no se toca.** Su stdout sigue siendo el canal JSON-RPC y la reserva de descriptor sigue siendo la garantía.
4. **Nada visual toca stdout.** La capa de salida sigue mandando y el detector AST del PR #211 también: `textual` gana una segunda casa (`menu/`) y sigue sin poder aparecer en ninguna otra parte.
5. **Sigue sin haber frontend, UI web ni assets.** El ADR 0005 sigue vigente en todo lo que dice sobre eso.
6. **Ninguna dependencia nueva.** `textual` ya estaba, con su tope de un major (ADR 0029).

## Riesgos

1. **Dos aplicaciones de pantalla completa en el mismo proceso.** Elegir `init` cierra el menú y abre el asistente. Es secuencial —`App.run()` devuelve con la terminal restaurada— pero es un camino que ningún test sin terminal cubre del todo. **Contención**: el menú se cierra entero antes de lanzar nada, y esto queda como punto explícito de validación humana.
2. **Que el menú se lea como "ahora todo es interactivo".** **Contención**: la lista de arriba, por nombre, y el punto 6.
3. **Una segunda superficie viva que mantener.** Es real y se asume: eventos, foco y redibujo para once entradas. Se acota a un paquete con la misma forma que `wizard/` y con tests por camino.
4. **El código de salida 0 al pulsar Esc**, donde antes siempre había un 2. Es deliberado —salir a propósito no es un error de uso— y solo ocurre en un caso que antes no existía: el 2 sigue siendo el de siempre cuando no hay menú, que es el caso que cualquier script ve.

## Alternativas consideradas

1. **Dejarlo como está y mejorar la ayuda.** Se rechaza como sustituto: por buena que sea una lista, hay que volver a teclear. Se conserva como base, porque es el camino de degradación obligatorio.
2. **Que el menú se quede abierto y vuelva a él tras cada comando.** Se rechaza: repintaría la pantalla encima de la salida recién pedida (riesgo 4 del ADR 0028), obligaría a decidir qué hacer con el código de salida y abriría la puerta a reentradas. Un lanzador que se aparta es más sobrio y más útil.
3. **Un menú con nombre y descripción en dos columnas.** Se rechaza por medición, no por gusto: en la ventana mínima la columna de la frase se queda en unas treinta celdas para frases de hasta ochenta caracteres, así que **las once filas acabarían recortadas**. Una descripción entera, la de la fila que se está leyendo, dice más que once cortadas por la mitad, y es lo que el asistente ya hace con la explicación del campo enfocado.
4. **Esconder del menú los comandos que necesitan argumentos.** Se rechaza: dejaría fuera `switch-profile`, que es de lo más útil que puede tener un menú. Preguntar lo que falta en texto plano cuesta doce líneas y no le da pantalla a nadie.
5. **Excluir `serve` del menú.** Se rechaza: es una lista negra por nombre, y no hace falta ninguna. Ver la decisión 1.
6. **Lanzar el comando en un subproceso.** Se rechaza: arranca un intérprete entero, hay que adivinar cómo se invoca a uno mismo, y no aporta nada que la pantalla ya cerrada no dé.

## Consecuencias

### Positivas

- El primer contacto con el producto deja de ser una lista que no lleva a ninguna parte.
- La degradación gana un segundo cliente, así que la puerta de `cli_output` se prueba dos veces desde dos sitios y sigue sin importar `textual`.
- La carcasa existe, con la costura escrita, para cuando algún comando merezca pantalla.

### Negativas y costes

- Una segunda superficie viva, con su ciclo de vida y sus modos de fallo.
- Un camino más que mantener en el punto de entrada: menú, ayuda, y comando lanzado.
- El precedente. Este ADR es la segunda excepción; la tercera necesitará la suya, y el argumento tendrá que ser mejor que *"ya hay dos"*.

## Qué monitorizar

- Que ningún comando gane pantalla sin su propia enmienda.
- Que los ocho disparadores sigan probados, y no solo declarados, para el menú **y** para el asistente. Y que el de segundo plano siga preguntándole a la terminal por su grupo en primer plano: es el único que no se puede deducir de una variable de entorno.
- Que las entradas se sigan construyendo desde los comandos registrados. Una lista escrita a mano en `menu/entries.py` es el primer síntoma de que el menú y la ayuda se van a separar.
- Que `nz-mcp` sin menú siga imprimiendo exactamente la ayuda de siempre, con su código 2.

## Lo que este ADR no decide

- **No elige librería.** Es la del ADR 0029, con su tope y su confinamiento.
- **No autoriza pantalla para ningún comando.** Ni siquiera para los que el menú lanza.
- **No cambia el modelo de seguridad.** Ni `sql_guard`, ni permisos de perfil, ni el manejo de la credencial.

## Referencias

- [ADR 0005](0005-sin-frontend.md) — sin frontend ni TUI, vigente salvo las dos excepciones
- [ADR 0028](0028-asistente-de-configuracion-interactivo.md) — la primera excepción, y el riesgo 5 que obliga a escribir ésta
- [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md) — la librería, su coste y su confinamiento
- [docs/architecture/cli-experience.md](../architecture/cli-experience.md) §6 — lo que no se hace, vigente dentro del menú
- Issues [#209](https://github.com/Oscarsp15/nz-mcp/issues/209) y [#217](https://github.com/Oscarsp15/nz-mcp/issues/217) — el orden y las frases que el menú reutiliza
- `src/nz_mcp/menu/`, `src/nz_mcp/cli.py` (`entry_point`, `_no_arguments`, `_launch`) y `src/nz_mcp/cli_output.py` (la puerta)
