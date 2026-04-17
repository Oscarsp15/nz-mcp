# ADR 0002 — Usar nzpy como driver primario de Netezza

- **Fecha**: 2026-04-16
- **Estado**: aceptado
- **Decidido por**: Tech Lead + Data Engineer (IA) + validación humana

## Contexto

Necesitamos un driver Python para conectar a IBM Netezza Performance Server (target probado: NPS 11.2.1.11-IF1). Las opciones realistas:

- `nzpy`: driver puro Python publicado por IBM, sin dependencias nativas.
- `pyodbc` + driver ODBC de IBM: requiere instalar el driver ODBC, configurar DSN.
- `JayDeBeApi` + JDBC: requiere JVM, complejo de empaquetar.

El proyecto se distribuye a comunidad y se ejecuta en la máquina del usuario final (con su VPN).

## Decisión

Usar **`nzpy`** como driver primario. Documentar `pyodbc` como alternativa opcional para usuarios que ya tienen el ODBC de IBM instalado.

## Alternativas consideradas

1. **`pyodbc` primario** — mejor performance, pero fricción de instalación (driver ODBC IBM, configuración DSN). Mata la UX `pipx install nz-mcp && nz-mcp init`.
2. **JDBC** — requiere JVM, multiplica complejidad de packaging para distro Python. Descartado.
3. **Multi-driver desde día 1** — duplica superficie de tests sin demanda comprobada. Diferido.

## Consecuencias

- ✅ Instalación `pipx install nz-mcp` cero-fricción.
- ✅ Cross-OS sin pasos extra.
- ⚠️ Performance ligeramente menor que ODBC (no significativo para nuestro tamaño de respuesta).
- ⚠️ Si IBM deja de mantener `nzpy`, fallback documentado a `pyodbc` (requiere refactor de `connection.py`).

## Monitorizar

- Frecuencia de releases de `nzpy` en GitHub/PyPI.
- Issues de comunidad pidiendo ODBC.
- Bugs específicos de `nzpy` con NPS 11.x.
