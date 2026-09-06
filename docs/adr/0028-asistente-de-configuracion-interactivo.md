# ADR 0028 — El asistente de configuración es la única excepción al ADR 0005

- **Fecha**: 2026-09-06
- **Estado**: aceptado — **enmienda el [ADR 0005](0005-sin-frontend.md)**, que sigue vigente en todo lo demás
- **Decidido por**: DX Engineer (IA) + validación humana (auditor: Security Engineer)
- **Issue**: [#221](https://github.com/Oscarsp15/nz-mcp/issues/221)
- **Alcance**: **qué** se permite y bajo qué condiciones. Con **qué librería** lo decide el
  [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md).

## Contexto

Decisión de producto del owner, del 2026-09-06, literal: *"queria que fuera interactiva la
configuracion, llama la atencion al usuario"* y *"configurar sus credenciales seria mas
intuitivo, ya no tendria que ingresar comandos"*.

Este ADR **no discute el si**. Eso está decidido. Discute el *hasta dónde* y el *a qué precio*,
que es lo que un ADR puede aportar a una decisión de producto ya tomada.

### Lo que dice hoy el ADR 0005, y por qué no basta con ignorarlo

El ADR 0005 lista, entre "la UX que sí poseemos": *"CLI de configuración (`nz-mcp init`, etc.) —
texto puro, sin TUI"*. Y su alternativa 3 rechaza expresamente *"TUI con `textual` para `nz-mcp
init`"* con este argumento: *"bonito pero añade dep grande para un wizard de 5 preguntas"*.

Ese argumento merece que se le responda pieza a pieza antes de enmendarlo, porque una de sus dos
piezas sigue viva:

| Pieza del 0005 | ¿Sigue siendo cierta hoy? |
|---|---|
| *"un wizard de 5 preguntas"* | **No.** El asistente pregunta **ocho** campos (`_DRAFT_FIELDS` en `cli.py`: host, puerto, base de datos, usuario, password, modo, `security_level`, `ca_certs`), valida en tres niveles contra el servidor y ofrece cuatro salidas ante un fallo. No es un formulario de cinco líneas: es una máquina de estados con borrador. |
| *"añade dep grande"* | **Sí, sigue siendo cierta**, y es exactamente el motivo por el que este ADR no elige librería: lo hace el 0029, con la factura enumerada. |

Es decir: la enmienda no dice que el 0005 se equivocara. Dice que **el objeto que describía ha
crecido** y que la decisión de producto cambió el criterio.

### Por qué el asistente es la excepción y los otros diez comandos no

El CLI tiene once comandos. Diez de ellos comparten una forma: **se invocan con todo lo que
necesitan, imprimen y terminan**. No hay nada entre el principio y el final que la persona pueda
recorrer, cambiar de opinión sobre, o volver atrás a corregir. Un interfaz navegable sobre ellos
no tendría nada que navegar: sería una ventana alrededor de un `print`.

| Comando | Qué hay entre entrada y salida | ¿Hay estado que navegar? |
|---|---|---|
| `test-connection` | una conexión y un veredicto | No |
| `list-profiles` | una lectura de TOML | No |
| `switch-profile` | una escritura de TOML | No |
| `remove-profile` | una confirmación y dos borrados | No |
| `edit-profile` | los campos llegan en la línea de órdenes | No |
| `doctor` | comprobaciones locales, milisegundos | No |
| `probe-catalog` | 14 consultas y un informe | No: se mira, no se toca |
| `version` | una cadena | No |
| `serve` | el protocolo MCP por stdout | No, y además prohibido |
| `add-profile` | entra siempre al asistente | es el asistente |
| **`init`** | **ocho campos, un borrador vivo, tres validaciones y cuatro salidas** | **Sí** |

El asistente es el **único momento** en que hay algo que sostener: ocho respuestas que existen a
la vez, que se relacionan entre sí (el `security_level` decide si `ca_certs` tiene sentido), que
pueden estar incompletas, y que sobreviven a un fallo de validación para poder corregirse. Eso ya
es un modelo de estado; hoy se recorre de la única forma que permite un flujo de preguntas
encadenadas —de arriba abajo, una vez— y esa es precisamente la limitación que el owner señala.

Es también el único momento en que una persona **se sienta de verdad** delante de este programa.
Todo lo demás lo teclea de paso.

## Decisión

**Se enmienda el ADR 0005 para un solo comando.** El asistente interactivo de configuración
—`nz-mcp init` y la rama interactiva de `nz-mcp add-profile`, que es el mismo código
(`_add_profile_interactive` en `cli.py`)— puede presentarse como un **interfaz de pantalla
completa navegable**: campos que se recorren, se corrigen sin rehacer los anteriores, muestran
qué falta y se validan antes de guardar.

Fuera de ese comando, el ADR 0005 **no cambia en nada**.

### Qué NO cambia — enumerado por nombre, para que nadie lo lea como permiso general

1. **`test-connection`, `list-profiles`, `switch-profile`, `edit-profile`, `remove-profile`,
   `doctor`, `probe-catalog`, `version` y `serve` siguen siendo texto puro.** Se ejecutan,
   imprimen y terminan. Ninguno captura el teclado, ninguno dibuja pantallas, ninguno abre un modo
   alterno de terminal.
2. **`serve` no se toca ni de lejos.** Su stdout es el canal JSON-RPC. La reserva de descriptor de
   `cli_output.stdout_reserved_for_protocol()` sigue siendo la garantía, y el asistente
   interactivo no se importa desde su camino: lo vigila el detector AST de
   `tests/contract/test_serve_stdout_protocol_only.py` (ver ADR 0029, condición 2).
3. **Sigue sin haber frontend, UI web, assets HTML/CSS/JS ni MCP UI resources.** Todo lo que decide
   el ADR 0005 sobre eso queda intacto: cero superficie de XSS, CORS o content security.
4. **No hay dashboard de administración ni servidor HTTP.** Sigue fuera de alcance.
5. **Las tools MCP no cambian.** No ganan interfaz, ni progreso, ni presentación: su lector es un
   modelo que paga tokens por cada carácter.
6. **El diseño de `docs/architecture/cli-experience.md` sigue vigente en sus trece prohibiciones**,
   salvo la nº 1 (*"ni TUI, ni menús navegables, ni captura de teclado"*), que queda acotada por
   esta enmienda al asistente y **solo** al asistente. Las demás —sin barra sin denominador, sin
   banner, sin emoji de estado, sin color como único portador de significado, sin byte decorativo
   por el stdout de `serve`, sin `--quiet`, sin traducir superficies de máquina— se aplican también
   dentro del asistente.
7. **La regla del rol se actualiza, no se levanta.** `docs/roles/dx-engineer.md` dice hoy que el rol
   *"no enmienda el ADR 0005"*. Sigue siendo verdad: **no lo enmienda el rol, lo enmienda este
   ADR**, y la restricción dura R3 de ese documento pasa a leerse *"sin TUI salvo el asistente de
   configuración, en las condiciones del ADR 0028"*.

### Condición 1 — la degradación es un requisito, no una cortesía

Es la condición más importante y la que puede tumbar la implementación entera.

**Nadie puede quedarse sin poder configurar nz-mcp porque el interfaz no arranque.** Si el entorno
no soporta el modo navegable, el comando **cae al asistente de texto actual** —el de preguntas
encadenadas, con sus tres niveles de validación y sus cuatro salidas— y configura **igual de
bien**: mismo resultado en `profiles.toml`, misma password en el keyring, mismo perfil activo.

La caída ocurre, sin preguntar y sin fallar, en al menos estos casos:

| Disparador | Cómo se detecta |
|---|---|
| Sin TTY: salida redirigida, tubería, CI, ejecución desde otro proceso | `isatty()` sobre entrada **y** salida, en `cli_output` |
| `TERM=dumb` | variable de entorno |
| Ventana por debajo del mínimo declarado | ancho y alto de la terminal en el arranque |
| Consola sin secuencias VT (Windows heredado) | la misma detección que ya usa la capa de salida |
| Petición explícita: `NZ_MCP_NO_TUI=1` | variable de entorno, escotilla documentada |

Tres precisiones que impiden que esto se quede en una frase bonita:

- **La detección es nuestra, no de la librería.** Comprobado sobre `textual` 8.2.8: no hay ni una
  aparición de `dumb` en su código, y el único `isatty` de sus drivers (`linux_driver.py`) sirve
  para decidir cómo leer la entrada, no para negarse a arrancar. Una librería de TUI **intentará**
  pintar en un `TERM=dumb`. La puerta la ponemos nosotros, antes de construir nada.
- **El camino de texto no es una reliquia congelada**: es el camino por defecto en cuanto falta un
  TTY, y por tanto el que corre en CI y en cualquier automatización. Se mantiene vivo y probado.
- **La degradación se prueba, no se promete.** Sin TTY, con `TERM=dumb`, con `NZ_MCP_NO_TUI=1` y
  con una ventana mínima, hay test de que se ejecuta el camino de texto y de que el perfil
  resultante es idéntico.

### Condición 2 — no se pierde nada de lo que ya funciona

El asistente actual costó una auditoría entera (issue #168, PR #174) y hace tres cosas que la
versión interactiva **conserva, sin reinventar**:

1. **Validación en tres niveles antes de persistir** (`_run_ladder` sobre `iter_checks`): conexión,
   catálogo, y visibilidad de esquemas en la base elegida.
2. **Cuatro salidas ante un fallo sin perder lo escrito**: reintentar, corregir un solo campo,
   guardar igualmente, cancelar. El borrador (`_ProfileDraft`) es lo que las hace posibles.
3. **Explicar antes de preguntar**: `WIZARD_MODE_EXPLAIN`, `WIZARD_SECURITY_EXPLAIN`,
   `WIZARD_CA_CERTS_EXPLAIN` y compañía, con paridad i18n ES/EN.

La lógica de validación y de guardado **no se duplica**: el interfaz recoge el borrador y llama a
las mismas funciones que hoy. Si aparece una segunda implementación de la escalera, la enmienda se
ha aplicado mal.

### Condición 3 — la password

La credencial se escribe **enmascarada** y no vive en el estado del interfaz. La regla concreta,
con su medición, está en el [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md),
condición 5, porque depende del comportamiento de la librería. Lo que este ADR fija es el techo:
**una interfaz con estado no puede empeorar lo que el
[ADR 0026](0026-secret-sin-password-en-trazas.md) ya consiguió.**

### Condición 4 — se adapta al ancho

El interfaz declara un tamaño mínimo, y por debajo de él no se encoge: **degrada** (condición 1).
Entre el mínimo y una ventana grande, se adapta. Esto no es teoría: la tabla de `list-profiles` ya
sufre en ventanas estrechas (issue [#220](https://github.com/Oscarsp15/nz-mcp/issues/220)) y una
pantalla completa lo sufre más.

## Riesgos, enumerados aquí para no descubrirlos después

Escritos sin maquillar. Cada uno con lo que lo contiene.

1. **`cmd.exe` heredado y codificaciones antiguas.** El owner ya ve acentos rotos en algunos
   contextos, y está verificado en el diseño del CLI: en una consola de Windows con página de
   códigos heredada, la raya de `doctor` sale como `?`. Un interfaz de pantalla completa multiplica
   la superficie: bordes, marcos, indicadores de foco. **Contención**: marcadores y bordes en ASCII
   dentro del asistente, igual que en el resto del CLI; y si la consola no habla VT, se degrada al
   camino de texto en vez de pintar basura. El riesgo **no desaparece**: se convierte en un caso de
   degradación más.
2. **Sesiones remotas por SSH con ventanas pequeñas.** Es un escenario real para un producto que
   habla con bases de datos corporativas. Un interfaz a pantalla completa por una conexión con
   latencia repinta más y responde peor que ocho preguntas. **Contención**: el mínimo de tamaño de
   la condición 4, y la escotilla `NZ_MCP_NO_TUI=1`, que alguien con una sesión mala puede fijar en
   su perfil de shell de una vez por todas.
3. **Coste de mantener una superficie viva.** Esto es lo que más caro sale y lo que menos se ve al
   decidir. Un texto que se imprime no tiene ciclo de vida; un interfaz sí: eventos, foco, redibujo,
   composición, y una librería que se mueve por debajo. **Contención**: la superficie se acota a un
   comando y a un paquete propio (ADR 0029, condición 2), el modelo de estado no se duplica
   (condición 2 de arriba), y todo camino tiene test. Aun así, se asume: **este ADR crea trabajo
   recurrente donde no lo había**, y quien lo acepta lo acepta a sabiendas.
4. **Que la interfaz tape errores que hoy se leen de un vistazo.** Es el riesgo más insidioso. Hoy,
   si la validación falla, el fallo queda escrito en el desplazamiento de la terminal: se puede
   copiar, pegar en un issue y releer. Un interfaz de pantalla completa **borra la pantalla al
   salir** y el diagnóstico se va con ella. **Contención**, y es vinculante: todo resultado de la
   escalera de validación y todo error se **reescriben por `cli_output` en la terminal normal al
   terminar el asistente**, no solo dentro del interfaz. Lo que se pega en un issue sigue siendo la
   salida de siempre; el interfaz añade navegación, no sustituye el registro.
5. **Que el interfaz se convierta en la puerta de entrada de la próxima excepción.** El precedente
   es el riesgo. **Contención**: la lista "Qué NO cambia" de arriba, por nombre. Cualquier segundo
   comando que quiera interfaz necesita su propia enmienda y sus propios argumentos; este ADR no
   sirve de jurisprudencia.
6. **Una dependencia grande y de cadencia rápida.** Enumerada y acotada en el ADR 0029. Se nombra
   aquí porque es un riesgo **de esta decisión**, no de aquélla: sin esta enmienda no haría falta.

## Alternativas consideradas

1. **Dejar el ADR 0005 intacto y mejorar el asistente de texto** (recapitulación previa, indicador
   de progreso, un solo siguiente paso). Es lo que ya prevé
   `docs/architecture/cli-experience.md`, y **se hace igualmente**, porque es el camino de
   degradación de la condición 1. Lo que no hace es cumplir la decisión de producto: unas preguntas
   encadenadas mejores siguen sin permitir volver a un campo anterior sin rehacer el resto. Se
   rechaza **como sustituto**; se adopta **como base**.
2. **Enmendar el 0005 en general** ("el CLI puede ser interactivo donde convenga"). Se rechaza: es
   una puerta sin marco. Diez de los once comandos no tienen estado que navegar, y una enmienda
   general invitaría a envolver `print`s en ventanas. La excepción vale porque es una excepción.
3. **Reemplazar el ADR 0005 por uno nuevo.** Se rechaza: el 0005 acierta en todo lo que dice sobre
   frontend, UI web y MCP UI resources, y ese contenido no ha caducado. Reemplazarlo tiraría
   decisiones válidas para cambiar una línea. Se enmienda la línea.
4. **Hacer el asistente interactivo y retirar el camino de texto.** Se rechaza sin discusión: es
   exactamente lo que la condición 1 prohíbe. Dos caminos cuestan más que uno; que alguien no pueda
   configurar el producto cuesta más que los dos.

## Consecuencias

### Positivas

- La configuración —el único momento con estado real, y el primero que alguien toca— deja de ser un
  cuestionario de ida y vuelta única.
- El camino de texto gana un dueño explícito: deja de ser "el asistente" para ser "el asistente y
  su modo de degradación", y como tal se prueba en escenarios donde antes nadie miraba (sin TTY,
  `TERM=dumb`, ventana mínima).
- La frontera queda escrita. Antes, "sin TUI" y "el rol no lo enmienda" convivían con una decisión
  de producto contraria; ahora hay un documento que dice qué se permite y qué no.

### Negativas y costes

- **Dos caminos que mantener y probar** para la misma tarea, para siempre. El interfaz no es un
  reemplazo, es un añadido.
- **Una dependencia nueva y grande** (ADR 0029) para un solo comando.
- **Una superficie viva**, con su propio ciclo de vida y sus propios modos de fallo, en el comando
  que peor tolera fallar: el primero que se ejecuta.
- **El riesgo 4 se contiene, no se elimina.** Un interfaz siempre esconderá algo que una lista de
  líneas enseñaba.

### Qué monitorizar para saber si fue buena idea

- Que ningún comando distinto de `init` y `add-profile` adquiera interfaz sin su propia enmienda.
- Que la degradación siga probada, y no solo declarada, en cada uno de los disparadores de la
  condición 1.
- Que el perfil resultante por el camino interactivo y por el de texto sea **el mismo**: es lo que
  hace aceptable la degradación.
- Issues de instalación que mencionen acentos rotos, bordes rotos o pantallas ilegibles: si
  aparecen, el disparador que faltaba se añade a la tabla de degradación.
- El coste real de mantenimiento a lo largo de un año: si un major de la librería obliga a rehacer
  el interfaz, este ADR se revisa con esa factura delante.

## Lo que este ADR no decide

- **No elige librería.** Lo hace el [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md).
- **No decide qué se muestra ni en qué orden.** Eso es del rol DX y del diseño de la experiencia.
- **No cambia el modelo de seguridad.** Ni `sql_guard`, ni permisos de perfil, ni el manejo de la
  credencial más allá del techo de la condición 3.
- **No implementa nada.** Esta fase es decisión.

## Referencias

- [ADR 0005](0005-sin-frontend.md) — enmendado por éste, vigente en todo lo demás
- [ADR 0026](0026-secret-sin-password-en-trazas.md) — la password como `Secret`
- [ADR 0027](0027-adoptar-rich-para-la-presentacion-del-cli.md) — `rich` acotado y confinado a la capa de salida
- [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md) — la librería y su coste
- [docs/architecture/cli-experience.md](../architecture/cli-experience.md) — §2 restricciones, §6 lo que no se hace
- [docs/roles/dx-engineer.md](../roles/dx-engineer.md) — restricción dura R3, acotada por esta enmienda
- Issue [#168](https://github.com/Oscarsp15/nz-mcp/issues/168) y PR #174 — la escalera de tres niveles y las cuatro salidas
- Issues [#220](https://github.com/Oscarsp15/nz-mcp/issues/220) y [#221](https://github.com/Oscarsp15/nz-mcp/issues/221)
- `src/nz_mcp/cli.py` (`_add_profile_interactive`, `_ProfileDraft`, `_run_ladder`) y
  `src/nz_mcp/cli_output.py` — el asistente y la capa de salida de hoy
