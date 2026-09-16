# ADR 0035 — El CLI pasa a dos niveles; se elimina la pantalla completa

- **Fecha**: 2026-09-16
- **Estado**: aceptado — **supersede por completo el [ADR 0030](0030-menu-interactivo-como-punto-de-entrada.md) y el [ADR 0032](0032-rediseno-del-nivel-2-del-cli-interactivo.md)**; **enmienda el [ADR 0028](0028-asistente-de-configuracion-interactivo.md)** (pierde su excepción de pantalla completa; el resto del ADR sigue vigente) y **enmienda el punto 9 del [ADR 0031](0031-mejora-progresiva-por-capacidad-del-terminal.md)** (el nivel 2 deja de existir, así que ese punto queda sin objeto). El [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md) (adopción de `textual`) queda **retirado**: sin nivel 2, no hay ninguna superficie que lo use.
- **Decidido por**: Oscar (owner), directamente — no es una recomendación de análisis de rol, es una decisión de producto que revierte la recomendación de `docs/design/cli-redesign-proposal.md`
- **Issue**: [#280](https://github.com/Oscarsp15/nz-mcp/issues/280)
- **Alcance**: cuántos niveles hay y qué le pasa al código que implementaba el tercero. No reabre la detección de nivel 0/1 (ADR 0031, puntos 1-8), que sigue exactamente igual.

## Contexto

`docs/design/cli-redesign-proposal.md` (Pam, rol UX/CLI, 2026-09-16) auditó las cuatro inconsistencias del CLI de tres niveles y recomendó la opción (c): conservarlo, cerrando tres huecos de comportamiento (bypass de los `confirm`, consistencia de "Ver perfiles", congelar la detección de nivel a mitad de proceso). Esa recomendación se apoyaba en un argumento real: los ADR 0027-0033 representan ~2 semanas de diseño e implementación ya aprobadas, y deshacerlas tiene un coste que no es cero.

Oscar revisó esa propuesta y decidió lo contrario: **"bonito pero simple"**. No quiere una tercera superficie que mantener, aunque esté bien hecha. Prefiere dos niveles — uno con estilo, uno sin — y ningún salto a una aplicación de pantalla completa. Esta decisión **no es un desacuerdo técnico con el análisis de Pam**: el análisis identificó correctamente el coste de cada opción; Oscar, con ese coste ya nombrado, eligió pagar el de deshacer el nivel 2 en vez de el de mantenerlo. Un ADR no argumenta contra una decisión de producto ya tomada por su dueño; documenta lo que cambia y por qué queda así.

### Lo que no cambia, y por qué esto es más pequeño de lo que parece

El ADR 0031 ya separaba con nitidez dos preguntas distintas: *"¿qué llega entero por esta línea?"* (`terminal_level()`, 0 o 1 — lo que este ADR llama **Nivel B** y **Nivel A**) frente a *"¿puedo tomar la terminal entera?"* (`interactive_ui_blocker()`, la puerta del nivel 2). Esa separación, hecha con esta más adelante en mente o no, es la que hace que eliminar el nivel 2 no toque el nivel 0/1: **`terminal_level()`, sus siete señales y la paleta de nivel 1 no se tocan una línea.**

Y el ADR 0028 ya construyó y probó la degradación de `init`/`add-profile` a una cadena de `out.ask`/`out.confirm` secuenciales para cuando el nivel 2 no puede abrirse. Ese camino existe, corre en Nivel A o Nivel B según el terminal, y tiene tests. Eliminar el nivel 2 no es diseñar una interfaz de texto nueva: es **borrar la rama que competía con una que ya funcionaba**, y dejar que esa gane siempre.

## Decisión

**El CLI tiene dos niveles, nunca tres.**

| | Antes (ADR 0031) | Ahora |
|---|---|---|
| Nivel 0 — plano | Piso garantizado, sin color | **Nivel B** — igual, sin cambios |
| Nivel 1 — inline con estilo | Color, bordes, spinner, sobre la terminal de siempre | **Nivel A** — igual, sin cambios |
| Nivel 2 — pantalla completa | Menú (ADR 0030), asistente (ADR 0028/0029), pantalla de perfiles (ADR 0032) | **Eliminado.** No hay nivel 3 que lo sustituya; sus tareas se reparten entre Nivel A y Nivel B de los comandos planos existentes |

### 1. `nz-mcp` sin argumentos deja de abrir un menú

Vuelve al comportamiento que el ADR 0030 sustituyó: imprime la ayuda (`ctx.get_help()`) y termina con **código de salida 2**. Es, letra por letra, el camino de degradación que el propio ADR 0030 ya escribió para cuando el menú no puede abrirse — con esta decisión, ese camino deja de ser una excepción y pasa a ser el único comportamiento. `src/nz_mcp/menu/` se elimina: no queda ningún import de `textual` fuera de lo que retira el punto 3.

### 2. `init` y `add-profile` dejan de tener una rama de pantalla completa

`_add_profile_interactive` deja de decidir entre "abrir el asistente Textual" y "preguntar en texto plano": **siempre pregunta en texto plano**, con `out.ask`/`out.confirm` en Nivel A si el terminal da color y bordes, en Nivel B si no. Es la misma cadena de preguntas que el ADR 0028 ya implementó como degradación (host, puerto, base, usuario, password, modo) y que ya está probada; deja de ser un camino secundario y pasa a ser el único.

El bypass `--yes` de las dos confirmaciones del asistente (issue #274, PR #279) sigue aplicando exactamente igual: no depende de qué rama abría la pregunta, solo de que hay una pregunta.

### 3. "Ver perfiles" deja de ser una pantalla

No hay menú desde el que lanzarla, así que la pregunta que el ADR 0032 y la propuesta de Pam dejaban abierta — *¿se pliega en `list-profiles` o se le da su propio nombre?* — se resuelve sola: **no hay ninguna superficie que no sea `list-profiles`**. Quien quiera activar, editar, probar o borrar un perfil teclea el comando de siempre (`switch-profile`, `edit-profile`, `test-connection --profile`, `remove-profile`), cada uno ya 100% scripteable (y, desde el PR #279, sin ningún `confirm` bloqueante sin bypass).

`_open_profiles_screen` se elimina junto con `menu/`. La preocupación del hallazgo 3 de la propuesta de Pam — *"la detección de nivel se re-pregunta a mitad de proceso y puede cambiar de resultado dentro de la misma sesión"* — queda resuelta por eliminación: esa doble pregunta solo existía porque `_open_profiles_screen` abría **después** del menú y podía ver un terminal redimensionado entre medias. Sin una segunda superficie que abrir tarde, no hay una segunda pregunta que hacer: `terminal_level()` se sigue evaluando donde ya se evaluaba (una vez por invocación de comando), y eso ya era y sigue siendo estable dentro de una misma ejecución de un comando plano.

### 4. `interactive_ui_blocker()` y sus ocho disparadores quedan sin objeto

La función que decidía si el nivel 2 podía abrirse no tiene ya ninguna puerta que guardar. Se elimina junto con `menu/` y la rama Textual del asistente, y con ella los ocho disparadores documentados en el ADR 0030 (§2) y el punto 9 del ADR 0031. Las variables de entorno que solo tenían sentido para el nivel 2 (`NZ_MCP_NO_TUI`) se retiran; `NZ_MCP_UI_LEVEL` (Nivel A/B) se conserva sin cambios, porque sigue gobernando algo real.

### 5. `textual` deja de ser una dependencia de este proyecto

El ADR 0029 adoptó `textual` en exclusiva para el nivel 2. Sin nivel 2, no queda ningún consumidor: se retira de `pyproject.toml`. `rich` (ADR 0027, base del Nivel A/B) no se toca — es una dependencia distinta, con un consumidor que sigue vivo.

## Qué se conserva, sin excepción

1. **La detección `terminal_level()` (0/1) y sus siete señales** — ADR 0031, puntos 1-8. Ni una línea.
2. **La paleta de Nivel A, sus cinco colores y su listón de contraste 3:1** — ADR 0031, punto 7.
3. **El bypass `--yes` de los tres `confirm`** (issue #274, PR #279) y el mensaje `CLI.CONFIRM_NO_TTY` cuando no hay `--yes` y no hay terminal.
4. **`prepare_windows_console()`** (ADR 0033) — sigue preparando la consola de Windows antes de medir el Nivel A/B; no tenía nada que ver con el nivel 2.
5. **`doctor` informando del nivel de terminal** (issue #254) — se adapta para dejar de mencionar por qué la pantalla completa no abre (ya no existe la pregunta), y sigue informando Nivel A/B.
6. **Los once comandos con nombre, su superficie 100% scripteable y sus tests de contrato.**

## Riesgos

1. **Se pierde trabajo de diseño ya aprobado y con tests.** Es el coste que Pam nombró y Oscar decidió pagar. Contención: nada de ese código se pierde sin registro — queda en el historial de git de `main` y en los ADR 0028-0030/0032, marcados como superseded/enmendados, no borrados de `docs/`.
2. **Los tests que fijaban el comportamiento del nivel 2 carácter a carácter dejan de tener sujeto.** Se retiran explícitamente por PR, nombrados uno a uno, no se dejan como `xfail` ni se silencian.
3. **Alguien vuelve a pedir pantalla completa más adelante.** Si ocurre, es una nueva excepción con su propio ADR y su propio argumento — exactamente la disciplina que el ADR 0028 (riesgo 5) ya exigía y que este ADR no relaja.

## Alternativas consideradas

1. **La opción (c) de `cli-redesign-proposal.md`: conservar 3 niveles, cerrar los 3 huecos.** Es la recomendación del análisis. Rechazada por decisión directa de Oscar: quiere menos superficie que mantener, no más consistencia sobre la misma superficie.
2. **Conservar el nivel 2 pero apagarlo por defecto (flag para reactivarlo).** Rechazada: mantiene el coste de mantenimiento (código, tests, `textual` como dependencia) sin el beneficio; es la peor combinación de las dos opciones.
3. **Migrar las cuatro acciones de "Ver perfiles" a flags de `list-profiles`.** Se consideró y se descarta por ahora: nadie ha pedido activar/editar/probar/borrar sin pasar por su comando dedicado, y añadir flags sin un caso de uso concreto es exactamente el código "porsiacaso" que este repo evita. Si aparece la necesidad, es un issue propio.

## Consecuencias

### Positivas
- Una superficie menos que mantener: sin `textual`, sin `menu/`, sin la rama Textual del asistente.
- El CLI vuelve a tener una sola pregunta por hacer (*"¿el terminal da para color?"*), no dos (*"¿da para color?"* y *"¿da para pantalla completa?"*).
- Todo comando sigue siendo 100% scripteable de punta a punta, y ahora sin ninguna superficie que prometa algo distinto según por dónde se entre (la inconsistencia 1 de la propuesta de Pam desaparece por eliminación del lado que la causaba).

### Negativas y costes
- Se descarta trabajo real y ya probado (ADR 0028-0030, 0032; issues #221, #226, #235, #240 y otros).
- Migración: los 19+ archivos de test que cubren menú/asistente/pantalla de perfiles se retiran o se adaptan PR a PR.
- Quien ya se acostumbró al menú o al asistente visual pierde esa experiencia; se documenta en el CHANGELOG como cambio observable, no como regresión silenciosa.

## Qué monitorizar
- Que ningún comando recupere una rama de pantalla completa sin una nueva excepción y su propio ADR.
- Que `nz-mcp` sin argumentos siga imprimiendo exactamente la ayuda de `click`, código 2, sin variación.
- Que `pyproject.toml` no vuelva a listar `textual` sin que exista antes un consumidor real.

## Lo que este ADR no decide
- **No cambia la detección de Nivel A/B.** Sigue siendo el ADR 0031, puntos 1-8, intacto.
- **No cambia el modelo de seguridad**, ni `sql_guard`, ni el manejo de credenciales.
- **No prohíbe una futura pantalla completa.** Solo exige que, si llega, llegue con su propia excepción y su propio argumento — la misma disciplina que ya regía antes de este ADR.

## Referencias
- [`docs/design/cli-redesign-proposal.md`](../design/cli-redesign-proposal.md) — el análisis que este ADR revierte en su recomendación (c), conservando su auditoría de las cuatro inconsistencias como diagnóstico válido
- [ADR 0005](0005-sin-frontend.md) — sin frontend ni TUI; con este ADR, las dos excepciones que quedaban (0028, 0030) se retiran y el 0005 vuelve a aplicar sin excepciones activas
- [ADR 0028](0028-asistente-de-configuracion-interactivo.md), [ADR 0029](0029-adoptar-textual-para-el-asistente-de-configuracion.md), [ADR 0030](0030-menu-interactivo-como-punto-de-entrada.md), [ADR 0032](0032-rediseno-del-nivel-2-del-cli-interactivo.md) — lo que este ADR enmienda o supersede
- [ADR 0031](0031-mejora-progresiva-por-capacidad-del-terminal.md) — el Nivel A/B que este ADR conserva sin cambios, salvo su punto 9 (queda sin objeto)
- [ADR 0033](0033-preparar-consola-windows-antes-de-medir.md) — sigue vigente sin cambios
- Issue [#280](https://github.com/Oscarsp15/nz-mcp/issues/280) — el trabajo de ejecución de este ADR
- Issue [#274](https://github.com/Oscarsp15/nz-mcp/issues/274) / PR #279 — el bypass `--yes`, conservado sin cambios
