# ADR 0031 — El CLI dibuja por niveles de capacidad, y el ASCII pasa de techo a piso

- **Fecha**: 2026-09-10 (decisión del owner sobre las maquetas: 2026-09-09)
- **Estado**: aceptado — **enmienda el [ADR 0027](0027-adoptar-rich-para-la-presentacion-del-cli.md)** en un punto: su ASCII sin color deja de ser *la* salida y pasa a ser **el piso garantizado**. Todo lo demás del 0027, y sus dos adendas, sigue vigente.
- **Decidido por**: TUI Designer (IA) + validación humana (auditor: Tech Lead)
- **Issue**: [#234](https://github.com/Oscarsp15/nz-mcp/issues/234)
- **Alcance**: **cuántos niveles hay, con qué señal se decide cada uno y qué puede pintar cada uno**. Con qué librería se pinta lo decidieron el [ADR 0027](0027-adoptar-rich-para-la-presentacion-del-cli.md) y el [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md); **qué** se muestra sigue siendo del rol DX. Este ADR no elige contenido ni librería.

## Contexto

El 2026-09-09, con el CLI ya terminado y funcionando, el owner lo resumió en una palabra:
**"opaco"**. No es un juicio estético suelto. Es lo que se ve al abrir Windows Terminal, VS Code,
iTerm o cualquier terminal de un escritorio Linux y encontrarse con marcos `+---+`, marcadores
`[OK]` y tres colores de los ocho de siempre — exactamente la misma salida que se enviaría por una
tubería a un fichero. Estamos dibujando para un terminal que, en la mayoría de los casos, no es el
que hay delante. El rediseño se aprobó ese mismo día sobre maquetas hechas fuera del repo
(boceto A), y este ADR es la regla escrita de la que cuelga.

### Por qué el ADR 0027 acertó, y por qué aun así hay que enmendarlo

El 0027 llegó a su ASCII sin color por un caso **real y medido**, no por prudencia genérica: una
consola de Windows con una code page heredada renderiza como `?` cualquier carácter de caja
Unicode, y una secuencia ANSI escrita en un fichero redirigido es basura que alguien tiene que
limpiar a mano. Ese razonamiento sigue siendo correcto.

El error no está en la conclusión, está en su alcance. El 0027 aplicó a **toda** la salida la
respuesta que hacía falta para **el peor** de los entornos, y eso convirtió el mínimo común
denominador en el techo del producto. La consecuencia es la que el owner señaló: el 90 % de las
terminales, donde nada obliga a degradar, reciben igualmente la salida degradada.

La tensión que este ADR resuelve es exactamente ésa: **no romper el piso** —nadie puede quedarse
sin poder leer la salida— **y a la vez aprovechar el terminal moderno cuando lo hay**.

### Qué mide un "nivel", y qué no

Un nivel no mide si el terminal es bonito. Mide **qué llega entero**: si un carácter fuera de
ASCII se pinta o se convierte en `?`, y si una secuencia de escape se interpreta o se escribe
literal. Son dos preguntas de transporte, no de gusto, y por eso se pueden responder con señales
del entorno en vez de con una bandera que el usuario tenga que descubrir.

Dato medido en la máquina del owner, y motivo de que la comprobación de Windows no pueda reducirse
a "es Windows": en Git Bash sobre Windows 11, `GetConsoleOutputCP()` devuelve **850** y
`WT_SESSION` no está definida, mientras que `TERM` vale `xterm-256color`. Un detector que solo
mirase `TERM` daría por bueno un terminal que va a pintar `?` en cada `✔`.

## Decisión

### 1. Tres niveles, y una sola función que decide

**`cli_output.terminal_level(stream=None) -> Literal[0, 1]`**. Una función **pura**: lee variables
de entorno y pregunta `isatty()` al flujo de destino. No abre terminal, no escribe nada, no
construye ninguna consola y no guarda estado. Se puede probar entera con `monkeypatch` sobre el
entorno y un doble de flujo, que es la única forma de tener una matriz de entornos en un CI que no
tiene ninguno.

- **Nivel 0 — ASCII sin color.** El piso. Marcos ASCII, marcadores en texto, **cero secuencias de
  escape**: ni color, ni negrita, ni movimiento de cursor.
- **Nivel 1 — terminal moderno.** Color semántico de la paleta medida, bordes redondeados, glifos
  Unicode e indicador de actividad fluido.
- **Nivel 2 — pantalla completa.** Ya existe y ya tiene dueño: es el asistente de los ADR
  [0028](0028-asistente-de-configuracion-interactivo.md) y
  [0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md) y el menú del
  [ADR 0030](0030-menu-interactivo-como-punto-de-entrada.md). **`terminal_level()` no lo decide**
  —ver el punto 9—, y por eso su tipo de retorno es `Literal[0, 1]` y no un entero cualquiera: un
  nivel que esta función no puede devolver no se puede colar por descuido.

El destino por omisión es **stderr**, que es donde pinta esta capa, igual que `color_enabled()` y
`animation_enabled()`. Un llamante que renderice para otro canal pregunta por ese canal, como ya
hace `display_width()`.

### 2. Las señales, en orden, y por qué ese orden

Se evalúan de arriba abajo; la primera que responde manda. **Cualquier duda cae a 0**: el nivel se
degrada, nunca se adivina hacia arriba.

| # | Señal | Cómo se detecta | Resultado | Por qué |
|---|---|---|---|---|
| 1 | `NZ_MCP_UI_LEVEL` con valor válido | variable de entorno | el que diga | Es la única señal explícita y la única que puede forzar hacia arriba. Ver el punto 3 |
| 2 | `NO_COLOR` presente | variable de entorno, con cualquier valor incluido el vacío | **0** | Convención establecida, y ya respetada por `color_enabled()` |
| 3 | `TERM=dumb` | variable de entorno | **0** | Un terminal que declara no saber nada no sabe de `\r` ni de ANSI |
| 4 | `CI` presente | variable de entorno | **0** | Un log de build es un fichero que alguien lee un mes después. Se comprueba aunque el paso 5 casi siempre lo cubra: hay corredores que asignan una pseudo-terminal, y ahí `isatty()` dice que sí y miente |
| 5 | El destino no es una terminal | `isatty()` sobre el flujo, con `ValueError` y `OSError` tratados como "no" | **0** | Redirección, tubería, descriptor sustituido. Es el caso que el 0027 protegía |
| 6 | POSIX: `TERM` vacío, sin definir o desconocido para terminfo | `curses.setupterm` y la capacidad `cup`, reutilizando `_terminal_type_is_capable()` | **0** | Ya existe, ya está probado y ya se usa para el nivel 2. Es deliberadamente conservador: a un tipo de terminal que terminfo no conoce no le vamos a dibujar bordes redondeados |
| 7 | Windows sin `WT_SESSION` **y** sin code page 65001 | variable de entorno y `GetConsoleOutputCP()` vía `ctypes` | **0** | Es el caso original del 0027, medido: con cp850 cada glifo fuera de ASCII sale como `?`. Basta cualquiera de las dos para saber que el Unicode llega entero |
| — | Nada de lo anterior | — | **1** | |

Consecuencia explícita y buscada: **la consola de Windows con code page 850 recibe exactamente la
salida de hoy**, byte a byte. Lo mismo el `nz-mcp list-profiles > perfiles.txt` de cualquier
plataforma.

### 3. `NZ_MCP_UI_LEVEL`: qué acepta, y quién gana

- **Valores aceptados**: `"0"` y `"1"`, tras recortar espacios. Nada más.
- **Funciona en los dos sentidos**: `1` fuerza el nivel 1 donde la detección habría dado 0
  —incluido un terminal que la heurística no reconoce pero su dueño sí—, y `0` fuerza el piso
  donde la detección habría dado 1. Sin las dos direcciones no es una salida de emergencia, es
  media.
- **Valor inválido** (`"2"`, `"si"`, `"true"`, vacío, cualquier otra cosa): **se trata como
  ausente** y la detección sigue su curso. Ni excepción, ni nivel inventado. La función es pura y
  no avisa: se lee en cada comando, y un aviso por invocación sería ruido permanente por una
  errata de una sola vez. `2` no es válido a propósito —el nivel 2 tiene su propia puerta— y por
  eso cae en el mismo saco.
- **Precedencia sobre `NO_COLOR`: gana `NZ_MCP_UI_LEVEL`.** Es la decisión que el issue pedía
  justificar. `NO_COLOR` es una convención **global** sobre el color, escrita una vez en un perfil
  de shell y heredada por decenas de programas; `NZ_MCP_UI_LEVEL` **nombra a este programa** y no
  puede haber llegado ahí por herencia. Entre una regla general y una excepción específica que la
  contradice a la cara, gana la específica: quien la escribe está diciendo *"para nz-mcp, esta
  vez, no"*, y la forma de volver atrás es borrarla. Fuera de esa colisión deliberada, `NO_COLOR`
  gana a todo lo demás, incluida la detección de terminal.

### 4. El nivel 0 es un contrato, y se verifica

**La salida del nivel 0 es la de hoy, carácter a carácter** — la de hoy en un entorno donde
`color_enabled()` ya es falso, que es el mismo conjunto de entornos que ahora dan nivel 0. Ninguna
mejora de un nivel superior puede modificarla. En particular:

1. **Cero secuencias de escape.** Ni `\x1b[`, ni negrita, ni cursor. La negrita también es una
   secuencia: una consola sin VT la escupe como basura y un redirect la deja escrita en el
   fichero.
2. **Solo ASCII imprimible.** Los marcos de `box.ASCII`, los marcadores en texto (`OK`, `WARN`,
   `FAIL`), el `...` de truncado y los fotogramas `- \ | /` del indicador.
3. **`serve` sigue sin pintar nada en stdout.** La adenda 1 del ADR 0027 —*ninguna consola escribe
   a stdout*— y la reserva de descriptor del #203 no se tocan. Los niveles son una decisión sobre
   **stderr**; stdout es del protocolo y de `emit()`, y ahí no hay niveles.

**Cómo se verifica** —trabajo del issue [#236](https://github.com/Oscarsp15/nz-mcp/issues/236), no
de éste:

- Una prueba por cada una de las siete señales de la tabla, cada una arrancando desde un entorno
  que daría nivel 1, para que ninguna pase en verde porque saltó otra.
- Texto de referencia capturado de `main` para las superficies del punto 5, comparado carácter a
  carácter con lo que el nivel 0 produce después del cambio.
- Una aserción **estructural**, no una lista de nombres: la salida del nivel 0 no contiene `\x1b`
  ni ningún carácter con `ord() > 126`. Este proyecto ya ha visto fallar dos barreras el mismo día
  por prohibir cosas por nombre; aquí se prohíbe la forma, y así una mejora futura que se filtre
  hacia abajo rompe el CI en vez de romperle la consola a alguien.

### 5. Qué superficie recibe nivel 1, y cuál no

| Superficie | Nivel 0 | Nivel 1 |
|---|---|---|
| Cabecera del comando | línea de texto | regla con el acento y el nombre del comando |
| Tabla de `list-profiles` | `box.ASCII`, sin color | borde redondeado, cabecera con acento, marcador `●` en el perfil activo |
| Estado por fila (activo, con aviso, con error) | `OK`, `WARN`, `FAIL` | `✔`, `▲`, `✖` **con el mismo texto al lado** |
| Escalera de `doctor` y `probe-catalog` | `[OK]` y contador `n/14` | glifo, color semántico y barra de progreso |
| Indicador de espera | `- \ \| /` sobre `\r` | spinner fluido de `rich` |
| Mensajes de `status`, `success`, `warn` y `fail` | texto plano | color de la paleta del punto 7 |
| Ayuda de `typer` | como hoy | como hoy: la pinta `typer`, y este ADR no la toca |
| Carga útil por stdout (`emit()`) | sin cambios | **sin cambios**: no hay niveles en stdout |
| Resaltado de SQL y DDL | **no existe** | **no existe** — punto 6 |

Los glifos del nivel 1 aparecen siempre **acompañados de texto**. Ver el punto 7.

### 6. El resaltado de SQL no se implementa, porque no hay dónde ponerlo

Comprobado sobre el código, no supuesto: **ningún comando del CLI muestra SQL o DDL a una
persona**. `cli.py` no imprime SQL en ninguno de sus once comandos, y `catalog/probe.py` —el único
que maneja SQL en el camino del CLI— lo **ejecuta** para validarlo y reporta el resultado, sin
enseñar la sentencia. El DDL que produce nz-mcp sale por las tools MCP, y ahí lo lee un modelo, no
un par de ojos: colorearlo sería gastar bytes en quien no los mira.

Así que la decisión es explícita: **no se implementa resaltado de sintaxis**. Ni un renderer, ni
un tema, ni un `Syntax` detrás de una bandera. Un renderer sin consumidor es exactamente el código
"porsiacaso" que el flujo de trabajo de este repo prohíbe, y además pondría a trabajar los 8,2 MB
de lexers de `pygments` que el ADR 0027 ya se resignó a llevar sin usar.

El día que exista una superficie que enseñe SQL a una persona, esa superficie llegará con su issue
y su justificación, y entonces el resaltado se decide con ella. Lo que ese día **no** habrá que
volver a descubrir son las dos trampas del punto 8, que ya están medidas y escritas.

La maqueta del boceto A incluye una pantalla de DDL resaltado (`level1_c`, no copiada a este
repositorio a propósito). **Es una maqueta, no un compromiso.** El issue
[#237](https://github.com/Oscarsp15/nz-mcp/issues/237) implementa el nivel 1 **sin** resaltado.

### 7. La paleta del nivel 1, medida

Cinco colores. Ni uno más, y cada uno con un trabajo.

| Uso | Color | Sobre blanco | Sobre negro | ≥ 3:1 en los dos |
|---|---|---|---|---|
| acento (cabeceras, bordes, foco) | `#00A3A3` | 3,10:1 | 6,77:1 | sí |
| ok | `#1F9D55` | 3,49:1 | 6,01:1 | sí |
| aviso | `#B26B00` | 4,20:1 | 5,00:1 | sí |
| error | `#C62828` | 5,62:1 | 3,74:1 | sí |
| atenuado | `#6E7781` | 4,55:1 | 4,62:1 | sí |

**El listón es 3:1, y es una decisión, no una rebaja perezosa.** Un terminal no nos dice de qué
color tiene el fondo, así que el mismo byte se pinta sobre blanco y sobre negro. Pedir 4,5:1
—el umbral WCAG AA para texto normal— **simultáneamente** contra los dos extremos es imposible:
los dos requisitos se cruzan en una franja vacía. 3:1 es el umbral AA para texto grande y para
componentes de interfaz, y es el máximo que se puede garantizar sin saber el fondo. Los números de
arriba son reproducibles: los calcula el script de la maqueta con la fórmula de luminancia
relativa de WCAG 2.1.

Tres reglas que acompañan a la paleta:

1. **El color nunca es el único portador de significado.** Cada estado lleva además texto o
   símbolo: `✔ activo`, `▲ sin probar`, `✖ error`. Quien no distingue rojo de verde, quien lee por
   un lector de pantalla y quien está en nivel 0 reciben la misma información. Esto es lo que hace
   que degradar a nivel 0 no pierda **nada** salvo el adorno.
2. **Los identificadores no se colorean.** Nombres de perfil, de base de datos, de tabla y de
   columna heredan el color de texto del terminal, que es el único que siempre contrasta con su
   propio fondo. El color se gasta en lo que distingue una línea de otra, no en lo que ya se
   distingue solo.
3. **Sin fondos de color.** Pintar el fondo de una celda es apostar por un tema concreto; el
   acento en el texto y en el borde, no.

### 8. Dos trampas ya medidas, y por eso escritas aquí

Ninguna de las dos es un bug de `rich`: son comportamientos reales que cuestan una tarde cada uno
cuando se descubren dibujando. Quedan como **restricciones** para los issues
[#236](https://github.com/Oscarsp15/nz-mcp/issues/236) y
[#237](https://github.com/Oscarsp15/nz-mcp/issues/237).

1. **`PygmentsSyntaxTheme` inventa `#000000`.** Cuando el estilo de `pygments` no dice nada de un
   token, el tema de `rich` no devuelve *"sin color"*: devuelve negro explícito. Combinado con un
   fondo `default` —el que deja respirar el bloque sobre el fondo real del terminal— eso pinta
   cada identificador de **negro sobre negro** en cualquier tema oscuro, y hace desaparecer la
   mitad de un DDL. Si algún día hay resaltado, ese negro por omisión tiene que volverse
   *ausencia* de color, no otro color.
2. **`Console(no_color=True)` no quita la negrita.** Suprime los colores y deja pasar `\x1b[1m`.
   El nivel 0 exige cero secuencias de escape, así que `no_color=True` **no basta** para
   producirlo: el nivel 0 se construye sin pedir negrita en origen, y la aserción estructural del
   punto 4 es lo que lo comprueba.

### 9. El nivel 2 tiene su propia puerta, y esta función no la abre

`terminal_level()` devuelve 0 o 1. El nivel 2 —pantalla completa— lo autorizan los ADR 0028, 0029
y 0030 para dos superficies concretas, y lo decide `cli_output.interactive_ui_blocker()` con sus
ocho disparadores, que preguntan cosas que esta función no pregunta: tamaño de ventana, grupo de
proceso en primer plano, capacidad `cup`. **No se unifican**: son dos preguntas distintas —*"¿qué
llega entero por esta línea?"* frente a *"¿puedo tomar la terminal entera?"*— y fundirlas haría que
arreglar una rompiese la otra.

Con una excepción, que es de coherencia y se decide aquí:

- **`NZ_MCP_UI_LEVEL=0` cierra también la puerta del nivel 2**, como noveno disparador de
  `interactive_ui_blocker()`. Si "forzar el piso" dejase salir una aplicación de pantalla
  completa, forzar el piso sería una mentira.
- **`NZ_MCP_UI_LEVEL=1` no la abre.** Un nivel superior no se puede forzar contra una terminal que
  no lo aguanta: ahí el precio de equivocarse es una terminal inservible —el `SIGTTIN` del ADR
  0030—, no un carácter feo.

### 10. Qué se enmienda del ADR 0027, exactamente

Una frase de alcance, no el documento. El 0027 decía que el ASCII sin color es *la* salida; a
partir de aquí es **el piso garantizado y probado**. Se le añade una nota de enmienda en la
cabecera y se marca su estado en el índice. **Su contenido histórico no se reescribe**: acierta en
todo lo demás, y sus dos adendas —ninguna consola escribe a stdout; el suelo de `rich` es 14.2—
siguen vigentes sin cambios. Tampoco cambia el confinamiento: `rich` se sigue importando solo
desde `cli_output.py`, y la detección de nivel vive ahí por el mismo motivo.

### 11. Quién es el dueño

- **TUI Designer**: la paleta y sus medidas, los glifos por nivel, la detección y los tests que
  fijan el nivel 0.
- **DX Engineer**: **qué** se muestra, en qué orden y con qué palabras. Un nivel no añade ni quita
  información; solo cambia con qué se dibuja la que el rol DX decidió.
- **Tech Lead**: firma la enmienda del ADR 0027 y la coherencia con la spec congelada.

## Referencia visual

Las dos capturas son del boceto A aprobado el 2026-09-09, y son **reproducibles**: las genera el
script de la maqueta con una consola de `rich` que graba en memoria y exporta a SVG, con
`force_terminal=True` y ancho fijo de 100 columnas, de modo que no dependen de la terminal de
quien las mira.

| Nivel | Captura | Qué enseña |
|---|---|---|
| 0 | [`level0_b.svg`](../design/adr-0031/level0_b.svg) | `nz-mcp list-profiles` en el piso: `box.ASCII`, marcadores de texto, cero color |
| 1 | [`level1_b.svg`](../design/adr-0031/level1_b.svg) | El mismo comando en nivel 1: borde redondeado, acento en la cabecera, glifos con su texto al lado |

La comparación entre las dos es el argumento entero de este ADR: **la misma información, las
mismas columnas, las mismas palabras**. Lo único que cambia es con qué se dibujan. Si al mirarlas
alguien ve un dato en una que no está en la otra, es un bug del nivel 1, no una mejora.

Las otras dos pantallas de la maqueta (`level*_a` y `level*_d`) y la de DDL resaltado (`level*_c`)
**no se copian a este repositorio**: la primera pareja no añade nada a la decisión, y la de DDL
enseña algo que el punto 6 decide **no** implementar. Una captura de algo que no existe es una
promesa, y las promesas en `docs/` envejecen mal.

## Alternativas consideradas

1. **Dejar el ADR 0027 como está.** El CLI se ve igual de opaco en el 90 % de las terminales donde
   nada obliga a ello. Es el statu quo que el owner rechazó explícitamente el 2026-09-09.
2. **Color y Unicode siempre, sin detección.** Reintroduce exactamente el fallo que motivó el
   0027: `?` en la consola heredada, secuencias ANSI dentro de ficheros redirigidos, ruido en los
   logs de CI. Se rechaza por romper el piso, que es lo único que este ADR no negocia.
3. **Una bandera manual `--color` o `--rich`.** Traslada al usuario un dato que el proceso puede
   averiguar solo, y no arregla el caso que importa —quien nunca leerá la documentación—, porque
   una bandera solo la encuentra quien ya sabe que existe. Se conserva **como salida de
   emergencia**, y en forma de variable de entorno (`NZ_MCP_UI_LEVEL`) en vez de bandera: se
   escribe una vez en el perfil del shell y vale para los once comandos, mientras que una bandera
   habría que repetirla en cada invocación y añadirla a cada comando.
4. **Delegar la decisión a `rich`** (`Console` con autodetección). `rich` decide *colores*, no
   decide niveles, y no sabe nada de nuestro caso de la code page 65001. Además repartiría el
   criterio por cada punto de llamada en lugar de concentrarlo en uno, que es justo lo que el ADR
   0027 acababa de arreglar con el confinamiento.
5. **Dos temas explícitos, claro y oscuro, elegidos por el usuario.** Se rechaza por ahora: exige
   preguntar algo que casi nadie sabe responder, o adivinar el fondo del terminal con una consulta
   OSC que muchos emuladores no contestan y que deja basura en pantalla cuando falla. Una paleta
   que cumple 3:1 en los dos fondos resuelve todos los casos sin preguntar nada. Si algún día
   aparece una medición que diga que no basta, ese día se decide, con datos.

## Consecuencias

### Positivas

- Una sola función decide la capacidad y ningún comando repite la comprobación. Cambiar la regla
  es cambiar un archivo.
- **El nivel 0 pasa de costumbre a contrato verificable.** Hoy nadie prueba que la salida
  degradada sea la de ayer; a partir de este ADR, sí.
- El resto del rediseño —issues #236 y #237, y el nivel 2 del #235— cuelga de una regla escrita en
  vez de de criterios sueltos por PR.
- La accesibilidad deja de depender de la buena voluntad de quien escribe cada línea: el listón de
  contraste está medido y el color nunca va solo.

### Negativas y costes

- **Una matriz de entornos que probar** en lugar de una sola salida. Siete señales, cada una con
  su prueba, y ninguna de ellas ejecutable contra una terminal real en CI.
- **Riesgo real de que una mejora del nivel 1 se filtre al nivel 0** sin querer, que es la forma en
  que este tipo de decisiones se muere en silencio. Por eso el nivel 0 se fija con tests y con una
  aserción estructural, no con una revisión atenta.
- **Una variable de entorno pública más que mantener**, con su documentación y su compatibilidad
  hacia atrás a partir del primer release que la incluya.
- **Dos preguntas parecidas conviviendo** (`terminal_level` e `interactive_ui_blocker`). Está
  justificado en el punto 9, pero alguien lo confundirá; el enlace entre las dos es el noveno
  disparador y conviene que siga siendo el único punto de contacto.

### Qué monitorizar

- Issues de *"se ve mal"* o *"salen `?`"* tras el primer release con nivel 1. Cero es el objetivo;
  el primero que aparezca dirá qué señal falta en la tabla del punto 2.
- **Cualquier PR que necesite tocar los tests que fijan el nivel 0.** Es la señal, y no hay otra
  mejor, de que la mejora se está filtrando hacia abajo.
- Que la paleta siga siendo de cinco colores y que sus medidas se puedan recalcular. Un sexto
  color sin número de contraste al lado es el principio del final.
- Que nadie añada un renderer de resaltado antes de que exista la superficie que lo consume.

## Lo que este ADR no decide

- **No decide qué se muestra.** Sigue siendo del rol DX y del diseño de la experiencia. Los
  niveles cambian el dibujo, nunca el contenido.
- **No elige librería ni añade dependencias.** `rich` ya está adoptado y acotado por el ADR 0027,
  con `pygments` dentro de su cierre transitivo. Este ADR no toca `pyproject.toml`.
- **No toca `src/`.** La implementación es de los issues #236 y #237.
- **No decide nada del nivel 2**, que es del issue #235 y de los ADR 0028, 0029 y 0030, salvo el
  único punto de contacto del punto 9.
- **No cambia el modelo de seguridad**, ni `sql_guard`, ni el manejo de la credencial, ni el
  contrato de stdout de `serve`.

## Referencias

- [ADR 0027](0027-adoptar-rich-para-la-presentacion-del-cli.md) — adopta y acota `rich`; este ADR enmienda su alcance: el ASCII pasa de techo a piso
- [ADR 0028](0028-asistente-de-configuracion-interactivo.md), [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md) y [ADR 0030](0030-menu-interactivo-como-punto-de-entrada.md) — el nivel 2 y sus ocho disparadores
- [ADR 0005](0005-sin-frontend.md) — sin frontend ni UI propia, vigente salvo las dos excepciones
- [docs/architecture/cli-experience.md](../architecture/cli-experience.md) §2 (R2: sin terminal, la salida queda limpia) y §4 (qué se muestra y qué se calla)
- `docs/roles/tui-designer.md` (issue [#233](https://github.com/Oscarsp15/nz-mcp/issues/233)) — el rol que redacta este ADR y que es dueño de la paleta y de la detección
- [docs/roles/dx-engineer.md](../roles/dx-engineer.md) y [docs/roles/tech-lead.md](../roles/tech-lead.md)
- `src/nz_mcp/cli_output.py` — `color_enabled()`, `animation_enabled()`, `display_width()` e `interactive_ui_blocker()`, que es donde encaja `terminal_level()`
- Issues [#236](https://github.com/Oscarsp15/nz-mcp/issues/236) (detección y tests del nivel 0), [#237](https://github.com/Oscarsp15/nz-mcp/issues/237) (dibujo del nivel 1) y [#235](https://github.com/Oscarsp15/nz-mcp/issues/235) (nivel 2)
- [`docs/design/adr-0031/`](../design/adr-0031/) — las dos capturas del boceto A aprobado el 2026-09-09
