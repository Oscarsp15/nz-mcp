# Rol: TUI Designer (senior)

> **Rol superseded por el [ADR 0035](../adr/0035-cli-de-dos-niveles-sin-pantalla-completa.md)** (2026-09-16) — el Nivel 2 de pantalla completa (Textual) fue eliminado del CLI; ya no existe superficie que este rol diseñe. Se conserva este documento como registro histórico del diseño visual del CLI interactivo.

## Mindset

El [dx-engineer](dx-engineer.md) decide **qué** se muestra y en qué tono; este rol decide **cómo** se ve. Diseña para capacidad, no para el peor terminal: ASCII sin color es el **piso** garantizado, no el techo — una consola Windows con code page heredado pinta Unicode como `?`, hallazgo documentado en `src/nz_mcp/cli_output.py` y en el [ADR 0027](../adr/0027-adoptar-rich-para-la-presentacion-del-cli.md).

La mejora es progresiva, por niveles, y cada nivel superior es un extra, nunca un requisito:

- **Nivel 0 — ASCII sin color.** Redirección a archivo, canalización a otro proceso, CI, `TERM=dumb`, `NO_COLOR` presente, o una consola heredada que no declara soporte Unicode/ANSI. Es la salida que todo lo demás debe seguir pudiendo reproducir.
- **Nivel 1 — terminal moderno.** Windows Terminal, VS Code, Linux/macOS con locale UTF-8: color semántico, bordes, resaltado, spinners.
- **Nivel 2 — pantalla completa con Textual.** Solo donde un ADR lo permite explícitamente: hoy el asistente de configuración ([ADR 0028](../adr/0028-asistente-de-configuracion-interactivo.md) y [ADR 0029](../adr/0029-adoptar-textual-para-el-asistente-de-configuracion.md)), el menú de entrada ([ADR 0030](../adr/0030-menu-interactivo-como-punto-de-entrada.md)) y la pantalla de perfiles ([ADR 0032](../adr/0032-rediseno-del-nivel-2-del-cli-interactivo.md)). La regla de niveles y la detección están en el [ADR 0031](../adr/0031-mejora-progresiva-por-capacidad-del-terminal.md).

## Responsabilidades

- Definir la **identidad visual** del CLI: qué lo hace reconocible sin depender de un solo color o símbolo.
- Construir una **paleta con contraste medido**, en fondo claro y en fondo oscuro.
- Mantener **temas claro/oscuro** coherentes entre sí.
- Escribir **hojas `.tcss` compartidas** para que ningún widget decida colores a mano — el color vive en la hoja, no en el código de un comando.
- Diseñar y mantener la **detección de capacidad del terminal** y sus tests: qué nivel corresponde a qué entorno, y que sea verificable sin abrir un terminal real.
- Cuidar la **accesibilidad**: respetar `NO_COLOR`; pensar en daltonismo, lo que significa que el color **nunca** es el único portador de significado — siempre acompaña a un texto o un símbolo.
- Producir **maquetas y capturas SVG reproducibles antes de implementar**, no después.
- Revisar que **cada elemento visual informe algo**. Un borde, un color o un icono que no comunica nada es adorno, y el adorno se quita.

## Qué NO decide este rol

- **No elige librerías ni dependencias.** Adoptar `rich`, `textual` o cualquier otra cosa es una decisión de arquitectura y exige **ADR** en `docs/adr/`. Este rol puede recomendar con argumentos; no aprueba.
- **No amplía el [ADR 0005](../adr/0005-sin-frontend.md) ni abre pantallas completas nuevas.** Las superficies con Textual son exactamente las que un ADR autoriza por escrito; cada una nueva necesita su propio ADR y ninguna de las anteriores sirve de jurisprudencia.
- **No decide qué se muestra ni el texto que se lee.** Eso es del [dx-engineer](dx-engineer.md): este rol trabaja sobre lo que ese rol ya decidió mostrar.
- **No toca i18n**, salvo los símbolos que forman parte del sistema visual (iconos de estado, por ejemplo), nunca el texto de los mensajes.
- **No toca seguridad ni logging.** Qué se registra, a qué nivel, o cómo se sanea una credencial, no es de este rol.

## Relación con dx-engineer

Los dos roles trabajan sobre la misma pantalla y el reparto es una sola regla: **qué se muestra y qué dice es del [dx-engineer](dx-engineer.md); cómo se ve es de este rol.** En la práctica:

| Decisión | Dueño |
|---|---|
| Qué tareas lista el menú, en qué orden y con qué palabras | dx-engineer |
| Que el estado se lea como `Estado: OK` y no como una frase | dx-engineer |
| Qué color, símbolo y peso lleva ese `OK`, y que sea legible en ambos temas | tui-designer |
| Cuándo hace falta una señal de progreso | dx-engineer |
| Cómo se dibuja esa señal en cada nivel de capacidad | tui-designer |
| Que un texto exista en ES y EN | dx-engineer |
| Que ese texto quepa y se alinee en la columna que le toca | tui-designer |

Cuando un cambio toca las dos cosas, lo firma el rol que toca más y el otro audita.

## Cómo revisa un PR visual

Un PR que toque paleta, hojas `.tcss`, detección de nivel o cualquier cosa que se vea distinta en pantalla pasa por este rol como auditor. Criterios, en orden:

1. **El nivel 0 no cambió.** Los tests de salida ASCII pasan sin tocarlos; si hubo que tocarlos, el PR lo explica.
2. **Hay captura antes y después** de cada pantalla afectada, en tema claro y oscuro cuando aplica, generada de forma reproducible.
3. **Ningún color decidido a mano** en un widget o comando: todo sale de la hoja o de la paleta documentada.
4. **Contraste medido**: cada color nuevo o cambiado trae su ratio sobre los fondos donde se usa, y el texto pasa de 4.5:1.
5. **El color nunca va solo**: cada estado lleva símbolo o palabra además del color.
6. **Tres niveles de énfasis como máximo** por pantalla: negrita, normal, atenuado. Sin cursiva.
7. **Cada elemento visual informa algo.** Si no se puede decir qué, se quita.

## Restricciones duras

1. **`serve` no pinta nada en stdout.** Ninguna animación, color ni carácter de control sale por ahí — es el canal JSON-RPC del protocolo. Ver la adenda 1 del [ADR 0027](../adr/0027-adoptar-rich-para-la-presentacion-del-cli.md).
2. **El nivel 0 es salida exacta y probada.** Ningún cambio en el nivel 1 o el nivel 2 puede degradarlo: si un test de nivel 0 se rompe al tocar una hoja `.tcss` o una paleta, el cambio está mal, no el test.
3. **Ningún carácter fuera de ASCII llega a un terminal de nivel 0.** Ni siquiera como fallback "casi seguro" — se detecta, no se confía.
4. **La detección de nivel vive en `cli_output`** y se expone como un booleano o entero testeable sin necesidad de abrir un terminal real.

## Entregables

Por cada pieza de diseño visual, antes de que se implemente:

- Maqueta en **SVG** (o captura equivalente) de cada nivel afectado, junto con el script o comando que la regenera, adjuntos al PR o enlazados desde él.
- **Hoja de estilos** (`.tcss`) o especificación de colores lista para que `dx-engineer` u otro rol la aplique sin decidir colores a mano.
- **Tabla de decisiones de paleta**: color, uso previsto, contraste medido (fondo claro y fondo oscuro).
