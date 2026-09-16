# Propuesta: una sola dirección coherente para el CLI

- **Fecha**: 2026-09-16
- **Estado**: propuesta — pendiente de decisión de Oscar
- **Rol**: UX/CLI (Pam), fase de análisis, sin tocar código de producción
- **Build auditado**: código en `main` de este repo (`e2bcd45`, 2026-09-11), no una versión empaquetada
- **Relación con trabajo previo**: no reemplaza [`docs/architecture/cli-experience.md`](../architecture/cli-experience.md) ni los ADR 0027-0033; los da por buenos y por implementados, y responde a una pregunta distinta que ese documento no cierra — **¿por qué, tras implementarlos, el CLI se sigue sintiendo híbrido, y qué se hace al respecto?**

## 0. Encargo

Oscar no está conforme con el CLI: lo describe como **híbrido** — a veces menú interactivo, a veces no — e inconsistente. Pide: (1) auditar dónde es interactivo y dónde no, con referencias concretas; (2) una única dirección coherente, con veredicto honesto de viabilidad, sobre todo en Windows.

Los ADR 0027-0033 y `feat/236,237,239,240,255` + `refactor/238,241` **ya están mergeados en `main`** (verificado: `git log --oneline` sobre `src/nz_mcp/cli.py` los muestra como commits reales, no como ramas pendientes). No hay migración que rescatar de una rama; el diseño de tres niveles ya es el código que corre hoy. Por eso la pregunta no es "¿qué falta construir?", es "¿el diseño ya construido es la dirección correcta, o hay que cambiarla?".

## 1. Auditoría: qué es interactivo hoy, y dónde vive

| Comando / superficie | Modo | Qué pasa | Referencia |
|---|---|---|---|
| `nz-mcp` (sin argumentos) | **Pantalla completa condicional** | Abre un menú Textual navegable de 6 tareas si el terminal cumple nivel 1 y el tamaño mínimo; si no, cae a `--help` de texto (código de salida 2) | `cli.py:446-479` (`_no_arguments`), ADR 0030 |
| `init` | **Híbrido en dos capas** | Un `out.ask` de texto para el nombre del perfil, y luego delega en `_add_profile_interactive`, que abre un asistente Textual de pantalla completa (nivel 2) **o** una cadena de `out.ask`/`out.confirm` secuenciales si degrada | `cli.py:170-177`, `cli.py:994` (`_add_profile_interactive`), ADR 0028 |
| `add-profile <name>` | **Igual que `init`, sin el prompt del nombre** | El nombre llega por argumento, pero el resto es la misma bifurcación pantalla-completa/texto | `cli.py:275-285` |
| `edit-profile` | **100% flags, cero prompts** | Todo por `--mode`, `--database`, etc.; si falta algo, no pregunta, no cambia nada y lo dice (`EDIT_PROFILE_NO_CHANGES`) | `cli.py:288-321` |
| `remove-profile <name>` | **No interactivo, salvo un `confirm` bloqueante sin bypass** | Un único `out.confirm(..., default=False)` en stderr, y no existe `--yes`/`--force` para saltarlo | `cli.py:340` |
| `switch-profile`, `test-connection`, `doctor`, `probe-catalog`, `version`, `serve`, `help` | **100% no interactivo** | Solo flags/argumentos, sin ningún prompt | `cli.py:225-434` |
| "Ver perfiles" (tarea del menú) | **Pantalla completa distinta de `list-profiles`** | El menú no ejecuta `list-profiles`: abre una pantalla Textual con tabla y 4 acciones (activar/editar/probar/borrar), que cierra y **entonces** invoca el comando real (`switch-profile`, `remove-profile`, …) sobre la terminal ordinaria | `cli.py:482-515` (`_open_profiles_screen`), ADR 0032 |

Con eso, el reparto real es: **8 de 12 comandos son puro texto sin ningún prompt** (`switch-profile`, `test-connection`, `edit-profile`, `doctor`, `probe-catalog`, `version`, `serve`, `help`); **1 no tiene pantalla completa pero sí un prompt bloqueante** (`remove-profile`); **2 alternan entre pantalla completa y una cadena de prompts de texto según el terminal** (`init`, `add-profile`); y **la entrada sin argumentos** abre una superficie de pantalla completa que no es ningún comando, sino un lanzador de comandos.

## 2. Las cuatro inconsistencias concretas

Cuatro, verificadas leyendo el código, no supuestas:

1. **La misma tarea tiene una UI distinta según por dónde se entra.** "Ver perfiles" desde el menú abre una tabla con acciones (activar, editar, probar, borrar) en pantalla completa; escrito a mano, `list-profiles` es una tabla de solo lectura sin ninguna acción. No es un bug — el ADR 0032 lo decide así a propósito y el propio código lo documenta (`cli.py:438-443`) — pero es exactamente la clase de sorpresa que hace sentir "híbrido": la persona que aprende el menú y luego escribe el comando de memoria encuentra dos productos distintos con el mismo nombre.

2. **Ningún comando con un `confirm` tiene forma de saltarlo.** `remove-profile` (`cli.py:340`), la confirmación de sobrescritura del asistente (`cli.py:941`) y la pregunta "¿validar antes de guardar?" del asistente (`cli.py:1256`) son los tres únicos `out.confirm` de todo `cli.py`, y ninguno tiene `--yes`/`--force`. Once de los doce comandos declaran ser scripteables (README, `--json` en `probe-catalog`, códigos de salida documentados); estos tres no lo son — `typer.confirm` con stdin cerrado o sin tty aborta (`click.exceptions.Abort`), así que **automatizar el borrado o la creación de un perfil desde CI no tiene camino hoy**, ni con flags ni con variable de entorno.

3. **La decisión de "¿hay pantalla completa o no?" se toma más de una vez por proceso, y puede cambiar a media sesión.** El propio docstring de `_open_profiles_screen` lo admite: se vuelve a preguntar `interactive_ui_enabled()` porque esa pantalla "abre estrictamente más tarde que el menú, y una ventana puede haberse encogido entre medias" (`cli.py:490-493`). Es decir: en una misma ejecución, el menú puede salir en pantalla completa y, dos segundos después, "Ver perfiles" caer a texto plano porque alguien redimensionó la terminal. El comportamiento es intencional y está probado, pero es el tipo de inconsistencia que nadie predice sin leer el código.

4. **`init` reparte la misma acción entre dos paradigmas dentro del mismo comando.** El nombre del perfil se pide con un `out.ask` de una sola línea (paradigma texto-secuencial, siempre); el resto — host, puerto, usuario, contraseña, modo — se pide con un asistente de pantalla completa en nivel 2, o con la misma secuencia de `out.ask` en nivel 0/1. Quien ejecuta `init` en una terminal moderna ve un prompt de texto seguido de una aplicación de pantalla completa, en ese orden, dentro de un único comando.

Ninguna de las cuatro es un error de implementación: cada una está decidida por un ADR y tiene test. Son inconsistencias de **diseño**, no de código — el código hace fielmente lo que los ADR piden, y lo que los ADR piden, sumado, no se siente como una sola cosa.

## 3. Las tres direcciones, evaluadas

### (a) TUI completo interactivo, siempre

Una sola aplicación de pantalla completa que sustituye a los once comandos.

**Veredicto: no viable, y no es una opinión — está descartado por las mismas restricciones que ya rigen este repo.**

- El ADR 0005 (sin frontend) sigue vigente y las tres excepciones que lo abren (0028, 0030, 0032) lo hacen **una superficie a la vez**, nunca "todo el CLI", precisamente porque `nz-mcp` se usa por SSH, dentro de contenedores y como subproceso de otros programas (Claude Desktop lo invoca así) — los tres casos donde una TUI permanente se rompe, documentado en `docs/architecture/cli-experience.md` §6.1.
- En Windows específicamente: el ADR 0033 ya tuvo que construir `prepare_windows_console()` para que el **nivel 1** (color, no pantalla completa) llegue de forma fiable a una consola heredada. Elevar eso a "toda interacción es pantalla completa" multiplica esa superficie de fragilidad por once comandos en vez de tres.
- Cualquier uso desde un script, un pipe, o `serve` (que Claude Desktop lanza como subproceso sin tty) necesitaría un modo de escape — es decir, dejaría de ser "siempre TUI" en la práctica.

### (b) CLI plano, cien por cien scripteable, sin ninguna pantalla completa

Eliminar el menú, el asistente de pantalla completa y "Ver perfiles"; todo por flags y prompts de texto lineales como mucho.

**Veredicto: viable técnicamente, y el más simple de razonar — pero tiene un coste real que hay que nombrar.** Es un giro de vuelta sobre una dirección de producto que Oscar mismo dio por escrito el 2026-09-05 (citada en `cli-experience.md` §0: *"que se vea muy bien estéticamente y amigable... llamativo"*) y sobre la que se abrieron y cerraron tres ADR con trabajo real detrás (#223, #228, #240). No es que (b) sea peor en abstracto: es que elegirla hoy tira ~2 semanas de diseño e implementación ya aprobadas, no codigo especulativo.

### (c) Separación clara: núcleo scripteable siempre + una superficie interactiva opcional, nunca obligatoria

Esto es, con dos correcciones, **lo que ya existe**: once comandos con nombre son y siguen siendo texto plano, controlables por flags de principio a fin; la única superficie de pantalla completa vive detrás de un único punto de entrada (`nz-mcp` sin argumentos) que **elige un comando y se cierra** — nunca reemplaza lo que ese comando hace ni cambia su salida.

**Veredicto: viable, y es lo único de las tres opciones que no exige deshacer trabajo ya aprobado ni chocar con el ADR 0005.** Lo que falta no es arquitectura nueva: es que las cuatro inconsistencias de la sección 2 dejen de existir, para que la regla se cumpla sin excepciones y alguien pueda describirla en una frase.

## 4. Recomendación

**(c), con la regla escrita como invariante y las cuatro inconsistencias cerradas — no una reconstrucción.**

La regla, en una frase, para que quede citable en una revisión de PR:

> **Todo comando invocado por nombre tiene un camino completo por flags/argumentos que no requiere terminal. Ninguna pantalla completa cambia lo que un comando hace: elige uno, se cierra, y ese comando corre exactamente igual que si se hubiera escrito a mano.**

La segunda mitad de la regla ya es cierta hoy (`_launch`, `cli.py:681-696`, lo aplica por construcción: nunca reimplementa una acción, siempre despacha al comando real). La primera mitad tiene tres huecos, que son exactamente los hallazgos 1, 2 y 3:

1. **`remove-profile` y los dos `confirm` del asistente ganan un bypass.** Un `--yes` en `remove-profile`, y que el asistente respete una variable ya prevista para no-interactivo (o un flag equivalente) en sus dos confirmaciones. Sin esto, "Todo comando... no requiere terminal" es falso para tres casos concretos.
2. **"Ver perfiles" deja de ser una segunda UI para la misma tarea, o se nombra como lo que es.** Dos caminos honestos: (i) el menú deja de decidir por la persona y "Ver perfiles" lanza `list-profiles` sin acciones, igual que el resto de tareas del menú; o (ii) se acepta que "Ver perfiles" es una tarea distinta con más funcionalidad que el comando homónimo, y se le da un nombre que no prometa ser lo mismo. La opción (i) es más barata y más coherente con la regla; la opción (ii) conserva las cuatro acciones pero cuesta romper la promesa implícita del nombre compartido. Recomiendo (i) salvo que Oscar valore más las acciones en pantalla que la previsibilidad del nombre.
3. **La comprobación de nivel de terminal se congela una vez por proceso.** Calcularla al arrancar (ya se hace para el menú) y pasarla como valor a `_open_profiles_screen` en vez de volver a preguntarla — quita el caso, ya documentado como conocido, de que la pantalla completa aparezca y desaparezca dentro de la misma sesión.

El hallazgo 4 (`init` reparte nombre-por-texto + resto-por-pantalla-completa) no se corrige: es el mismo patrón que el propio `cli-experience.md` ya aceptó para el asistente completo (pedir el nombre antes de decidir si hay pantalla completa evita crear un perfil "sin nombre" mientras se decide el modo), y tocarlo significa reabrir el ADR 0028. Se documenta como decisión consciente, no como pendiente.

## 5. Boceto de migración

No hay rediseño de UI que dibujar: es cerrar tres huecos de comportamiento y escribir la regla donde ya se escriben las demás (`cli-experience.md` §2, como "R0").

| Paso | Qué cambia | Tipo | Toca |
|---|---|---|---|
| 1 | `--yes`/`-y` en `remove-profile`; salta el `confirm` de `cli.py:340` | `feat(cli)` | `cli.py`, `tests/unit/test_cli.py` |
| 2 | Bypass no interactivo para los dos `confirm` del asistente (`cli.py:941`, `cli.py:1256`) — mismo mecanismo que el paso 1, no uno nuevo | `feat(cli)` | `cli.py`, `tests/unit/test_cli_wizard*.py` |
| 3 | Decidir si "Ver perfiles" lanza `list-profiles` sin acciones (opción i) o se renombra (opción ii) — **requiere decisión de Oscar, no es técnico** | `docs(adr)` primero, `refactor(cli)` después | ADR nuevo que enmiende el 0032, `cli.py:482-515` |
| 4 | Congelar `interactive_ui_enabled()` una vez por proceso y pasarlo como parámetro a `_open_profiles_screen` | `refactor(cli)` | `cli.py:459-515` |
| 5 | Escribir la regla del §4 como "R0" en `cli-experience.md` §2, con un test de contrato que recorra los doce comandos con `stdin` cerrado y compruebe que cada uno o bien termina (con o sin `--yes`), o bien falla con un mensaje, pero nunca queda colgado esperando una tecla | `docs` + `test(cli)` | `cli-experience.md`, nuevo `tests/contract/test_cli_no_tty.py` |

Nada de esto toca el asistente Textual, el menú, ni el stylesheet de `refactor/238`: el diseño visual ya aprobado se conserva entero. Es cerrar comportamiento, no rehacer pantallas.

## 6. Riesgos

- **Riesgo de alcance**: el paso 3 es el único que no es puramente técnico — depende de qué valora más Oscar (previsibilidad del nombre vs. las cuatro acciones en pantalla). Sin esa decisión, los pasos 1, 2, 4 y 5 se pueden hacer igual; no dependen entre sí.
- **Riesgo de regresión en tests**: `tests/unit/test_cli_wizard*.py` y `test_cli_profiles_screen.py` ya fijan el comportamiento actual carácter a carácter (ver cómo lo hace `test_cli_output.py` para el nivel 0, citado en `cli-experience.md`); añadir bypasses no interactivos es aditivo si se hace bien, pero cualquier cambio al flujo de `_open_profiles_screen` (paso 3 y 4) toca esos tests directamente.
- **Riesgo de nombre**: si se elige la opción (i) del paso 3, `PROFILES_TASK_COMMAND` deja de necesitar ser un caso especial (`cli.py:443`) — es una simplificación, no solo una corrección, y vale la pena confirmarla antes de tocar el ADR 0032.
- **Nada de esto es Netezza ni producción**: es CLI local y perfiles; el riesgo de romper algo en vivo es nulo.

## Referencias

- [`docs/architecture/cli-experience.md`](../architecture/cli-experience.md) — el diseño de experiencia vigente, que esta propuesta no reabre
- [ADR 0005](../adr/0005-sin-frontend.md), [0028](../adr/0028-asistente-de-configuracion-interactivo.md), [0030](../adr/0030-menu-interactivo-como-punto-de-entrada.md), [0031](../adr/0031-mejora-progresiva-por-capacidad-del-terminal.md), [0032](../adr/0032-rediseno-del-nivel-2-del-cli-interactivo.md), [0033](../adr/0033-preparar-consola-windows-antes-de-medir.md)
- `src/nz_mcp/cli.py`, `src/nz_mcp/cli_output.py`
