# ADR 0026 — La password viaja como `Secret`, nunca como `str` desnuda

- Estado: aceptado
- Fecha: 2026-09-05
- Issue: [#191](https://github.com/Oscarsp15/nz-mcp/issues/191)

## Contexto

Al desbloquear los tests de integración (#190 / PR #192) apareció una fuga que llevaba
latente desde el primer día: cuando algo falla dentro de `open_connection`, la traza
imprime **los argumentos de cada frame**, y uno de ellos es la password del perfil.

```
password = 'la-password-real-del-perfil'

    def open_connection(profile: Profile, password: str) -> object:
```

Medido en local sobre `main` (fallo real de conexión, formateado con el mismo
`ExceptionInfo.getrepr(style="long", funcargs=True, chain=True)` que usa pytest), la
credencial aparecía **seis veces** en una sola traza:

| Frame | Por qué |
|---|---|
| `nz_mcp.connection.open_connection` | argumento `password` |
| `nzpy.connect` | argumento `password` |
| `nzpy.core.Connection.__init__` | argumento `password` |
| los tres anteriores otra vez | la excepción encadenada (`raise ... from exc`) se repinta |

El repositorio es **público** y desde #192 los tests de integración por fin se ejecutan,
así que cualquier fallo (VPN caída, timeout, credencial rechazada) produce una salida que
un humano puede pegar en un issue pidiendo ayuda. Contradice la regla inviolable nº 1 de
`AGENTS.md`.

Lo incoherente del caso: el proyecto ya sanea con cuidado **todo lo que escribe**
(`sanitize(..., known_secrets={password})` en el detalle del error, en los hints y en cada
capa de catálogo). Pero el sanitizador solo ve los textos que construimos nosotros; la
traza la pinta el intérprete a partir de los objetos vivos del frame, por detrás de
cualquier saneado.

## Decisión

**La password deja de existir como `str` desnuda dentro del proceso.** Se introduce
`nz_mcp/secret.py` con `Secret`, una **subclase de `str`** cuyo renderizado está
redactado, y se aplica en los dos sitios que lo hacen estructural:

1. `auth.get_password()` devuelve `Secret`. Es la única puerta por la que la credencial
   entra al proceso desde el keyring, así que las ~30 funciones de `catalog/*`, `cli.py` y
   `profile_check.py` que la reciben quedan cubiertas **sin tocarlas ni pedirles que se
   acuerden**.
2. `connection.open_connection()` y `profile_check.run_checks()` **re-ligan su propio
   argumento** (`password = Secret(password)`) como primera sentencia. Cubre al llamante
   que aún tenga un `str` (un test, un script, código futuro) y, sobre todo, hace que los
   frames de `nzpy` reciban ya el objeto redactado.

`Secret` redacta `__repr__`, `__str__`, `__format__` y `encode()`; esta última devuelve
`SecretBytes` porque `nzpy` re-liga su propio argumento a `password.encode('utf8')` y unos
`bytes` normales volverían a meter la credencial en un frame. El valor real solo se obtiene
por la puerta explícita `reveal()`, que se usa en un único sitio: `store_password`, donde
el backend de keyring necesita el texto de verdad.

## Por qué una subclase de `str` y no un envoltorio tipo `SecretStr`

La propuesta del issue era un envoltorio opaco que se desenvuelve al llamar a
`nzpy.connect`. **No habría bastado**: en el momento en que escribes
`nzpy.connect(password=secret.reveal())`, el `str` desnudo que devuelve `reveal()` pasa a
ser el argumento del frame de `nzpy.connect` y de `Connection.__init__`. Es decir, taparía
1 de las 6 apariciones medidas y dejaría vivas las 5 del driver, que son justamente las que
el usuario no controla.

La subclase de `str` viaja **entera** por el driver (`isinstance(password, str)` sigue
siendo cierto, `encode` sigue funcionando) y por el sanitizador (`known_secrets={password}`
compara y reemplaza sobre el valor real), así que la redacción alcanza a todos los frames
sin adaptadores ni conversiones.

## Qué sacrificamos

- **`str(password)` ya no devuelve la credencial.** Es deliberado: `f"{password}"`,
  `"%s" % password` y `logger.info("%s", password)` imprimen `***`. Quien necesite el texto
  plano tiene que escribir `reveal()`, y eso se ve en un diff. El modo de fallo es ruidoso
  y seguro (la conexión fallaría con un `***` inútil), nunca silencioso.
- **No protege los valores derivados.** `password[:4]`, `password + "x"` o
  `json.dumps(password)` vuelven a ser `str`/`bytes` normales. La redacción de renderizado
  es la primera barrera; `sanitize(..., known_secrets=...)` sigue siendo la segunda para
  los textos que construimos. No se elimina ninguna.
- **No protege el frame de un llamante que fabrique su propia `str`.** Si un script hace
  `def helper(password): open_connection(p, password)` con un literal, el frame de `helper`
  seguirá enseñándolo. Por eso el wrapping se hace en `get_password`: en el código de
  producción no queda ningún punto donde exista una `str` desnuda con la credencial.
- **Un tipo propio en vez de `pydantic.SecretStr`.** `SecretStr` no es un `str`, así que
  arrastraría un `.get_secret_value()` en cada frontera — el problema del envoltorio, otra
  vez — además de romper `known_secrets`. El módulo son 25 líneas y no añade dependencias.

## Alternativas descartadas

### `__tracebackhide__ = True` en `open_connection`

Es una convención **solo de pytest** (ni el intérprete ni un log la respetan) y oculta el
frame entero: perderíamos la línea que falló. Además no toca los frames de `nzpy`, que son
la mayoría de las copias. Arregla la superficie de tests y deja viva la fuga real.

### Capturar y re-lanzar con la traza saneada (`raise ... from None`)

Cortar el `__cause__` esconde las apariciones del driver, pero también el diagnóstico
técnico que la ADR 0021 se esforzó en recuperar, y no protege ninguna otra ruta que reciba
la password. Es tratar el síntoma en un único punto.

### Arreglar solo la superficie de tests (fixture que redacta la salida de pytest)

El alcance real no es pytest: es **cualquier** traza que atraviese la ruta de conexión —
un `nz-mcp test-connection` que revienta en la terminal del usuario, un cliente MCP que
vuelca `stderr` a su log, un futuro reporter de errores. Un fixture protege un escenario y
depende de que nadie lo desactive; la subclase protege el objeto, y el objeto es el que
viaja en el argumento.

### Dejar de pasar la credencial como argumento (variable de entorno, singleton, contextvar)

Sacar la password del argumento la saca del `repr` del frame, pero la mete en un estado
global compartido: peor para la concurrencia (ver `_DriverDiagnosticsHandler`), peor para
los tests y, en el caso de la variable de entorno, anti-patrón explícito del modelo de
seguridad (`ps` la muestra).

## Consecuencias

- Cobertura: `secret.py` 100 %, `auth.py` del 79 % al 100 % (las ramas `KeyringError` no
  estaban cubiertas y ahora lo están).
- `tests/unit/test_no_password_in_traceback.py` provoca un fallo **real** dentro de
  `open_connection` (puerto local cerrado: sin red, sin VPN, sin mock del driver) y
  renderiza la excepción con el formateador de pytest en los cinco estilos de `--tb`. Falla
  en `main` y pasa con este cambio. Comprueba además que host, puerto, base y usuario
  siguen visibles: redactar no puede costar diagnóstico.
- `tests/unit/test_secret.py` cubre cada ruta de renderizado (repr, str, f-string, `%`,
  `logging`, contenedores, `encode`) más una propiedad con `hypothesis`.
- Verificado en vivo contra el Netezza real (VPN): con password incorrecta — el servidor
  rechaza la autenticación, así que se recorre el handshake entero — y con la credencial
  real contra una base inexistente, la traza completa con `funcargs`, `showlocals` y
  `chain` no contiene la credencial en ningún frame; solo `password = Secret(***)`.
- Queda una dependencia del detalle interno de `nzpy` (que hace `encode('utf8')`): si el
  driver cambiara su forma de codificar, la protección de **sus** frames podría degradarse.
  La de los nuestros no depende de él, y el test de traza lo detectaría.
