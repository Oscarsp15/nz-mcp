# 23. Mensajes de error accionables: detalle localizado + hint específico o nada

Date: 2026-09-05

## Status

Accepted

## Context

El payload de error es **todo** el diagnóstico que recibe una IA: no ve el stack, ni los logs, ni el código. Dos huecos lo dejaban inservible justo en el fallo más frecuente:

- `_i18n_key_for` no mapeaba `INVALID_INPUT` ni `OBJECT_NOT_FOUND` (issue #142), así que `message_es` y `message_en` llegaban con el literal `"INVALID_INPUT"`. El motivo real ("Column default must be a string, number, or boolean") solo vivía dentro de `context.detail`. Son ~65 puntos de `raise` en el código y, sobre todo, **todo** `ValidationError` de pydantic al validar los argumentos de una tool: el error número uno cuando un modelo arma mal una llamada.
- El contrato documentaba `hint_es` / `hint_en` en la respuesta de error desde v0.1, pero el servidor no los emitía nunca (issue #141). Los hints que ya existían (truncado, causa de fallo de conexión) o iban dentro del `context` o no salían del módulo que los construía.

## Decision

### 1. `INVALID_INPUT` y `OBJECT_NOT_FOUND` entran al catálogo i18n

Dos claves nuevas (`"Argumento inválido: {detail}"` / `"Objeto no encontrado: {detail}"`) que **incrustan el `detail`** en el mensaje localizado, igual que ya hacían `INVALID_CONFIG` y `NETEZZA_ERROR`. El `detail` sigue en inglés porque lo escribe el código (regla de idioma de `AGENTS.md`) o lo produce pydantic; lo que se traduce es el marco, no el diagnóstico técnico.

### 2. El `ValidationError` de pydantic se resume, no se incrusta

`str(exc)` es un volcado multilínea que por cada campo repite una URL de la documentación de pydantic y **devuelve el valor de entrada**. Ninguna de las dos cosas ayuda a corregir la llamada, y el valor de entrada puede ser dato de negocio. Se sustituye por `campo: motivo` separado por `; `, construido desde `exc.errors(include_url=False, include_input=False)`, acotado a 5 campos más `(+N more)`.

Medido con `nz_describe_table({"database": "DEV", "tabla": "CLIENTES"})`: el payload pasa de 772 a 615 chars (−20 %) y **a la vez** gana el mensaje localizado y el hint. Resumir era además la única opción compatible con "cada token cuenta": incrustar el volcado entero habría triplicado el payload al duplicarlo en ES y EN.

### 3. Un hint es específico o no existe

`hint_es` / `hint_en` van **siempre** en la respuesta de error, con valor `null` cuando ninguna regla aplica (un campo que aparece y desaparece es más difícil de ramificar para un modelo que un `null`). No se emite ningún hint genérico tipo "revisa los argumentos": ruido que se paga en tokens en cada llamada fallida. Reglas con las que sí se emite:

- **Faltan argumentos obligatorios** → se nombran. Gana sobre "sobran argumentos": quitar los desconocidos no haría que la llamada funcione si falta uno obligatorio.
- **Sobran argumentos desconocidos** y no falta ninguno → se nombran los que hay que quitar.
- **`OBJECT_NOT_FOUND` con `object_type` y coordenadas** → remite a la tool de listado que responde a la pregunta, con sus argumentos ya puestos (`nz_list_tables(database='DEV', schema='PUBLIC')`).
- **`NETEZZA_ERROR` que casa un patrón conocido** → hint por patrón, con la misma tabla de reglas ordenadas que usa `classify_connection_failure` (ADR 0021): añadir un mensaje nuevo del driver cuesta una entrada en la tupla, no una rama.

Un tipo de dato equivocado, un `object_type` sin tool de listado (`database`: `nz_switch_database` ya devuelve las bases visibles en su `detail`) o un texto de Netezza no visto antes se quedan **sin hint**, a propósito.

### 4. Los hints construidos en el punto de `raise` se promocionan una sola vez

`CONNECTION_FAILED` ya construye `hint_es` / `hint_en` en `connection.py` y los mete en el `context`. El servidor los saca del `context` y los publica en el nivel superior del error. Viajan una vez, en el sitio donde todos los clientes los leen. `PROFILE_NOT_FOUND` es la excepción explícita: su hint es un fragmento interpolado dentro del propio mensaje, así que no se promociona (duplicaría el texto).

## Alternatives considered

1. **Incrustar `str(exc)` tal cual en el mensaje** — rechazada: multiplica por dos el volcado (ES + EN), arrastra una URL por error y devuelve al modelo los valores que él mismo mandó.
2. **Devolver `exc.errors()` estructurado en `context`** — rechazada: un modelo lee el mensaje, no reprocesa una lista de dicts; y el `context` ya carga el `detail`.
3. **Hint genérico cuando no hay regla** ("revisa el esquema de la tool") — rechazada: no es accionable, se repetiría en cada error y entrena al modelo a ignorar el campo.
4. **Omitir `hint_*` cuando no hay hint** — rechazada por el anti-patrón de `roles/dx-engineer.md`: campos opcionales que aparecen y desaparecen; `null` consistente es más barato de ramificar.
5. **Clasificar el error de Netezza en cada punto de `raise`** — rechazada: son ~15 sitios y el hint depende solo del texto ya saneado; clasificar en el servidor lo resuelve en un único lugar.
6. **Fuzzy match del nombre del objeto ("¿querías decir CUSTOMER?")** — diferida: exige una consulta extra al catálogo justo cuando algo ha fallado. El hint remite a la tool de listado, que da la respuesta exacta y la paga el modelo solo si la quiere.

## Consequences

- El mensaje que recibe la IA deja de ser un código en los dos errores más frecuentes. Medido: `nz_create_table` con un `default` inválido pasa de `message_es: "INVALID_INPUT"` a `"Argumento inválido: Column default must be a string, number, or boolean."`.
- El payload crece en los casos con hint (tabla no encontrada: 301 → 875 chars) porque el hint viaja en ES y EN. Es el intercambio buscado: una llamada mal repetida cuesta mucho más que ~140 tokens.
- Los `detail` de "objeto no encontrado" se reescriben a una frase corta (`Table 'X' does not exist in DB.SCHEMA or is not visible to this profile.`) y las coordenadas pasan también al `context` como datos (`object_type`, `database`, `schema`, `table`), que es lo que compone el hint.
- Un `raise` futuro de `InvalidInputError` u `ObjectNotFoundError` **sin** `detail` rompería el `.format()` del mensaje. Es la misma condición que ya tenían `INVALID_CONFIG` y `NETEZZA_ERROR`, y el catálogo prefiere fallar ruidoso a mentir en silencio.
- `error_hints.py` es un módulo nuevo con una sola razón de cambio (el texto que ve el modelo cuando algo falla); `server.py` no gana lógica de clasificación.
