# Arquitectura — Visión general

## Propósito

`nz-mcp` es un servidor MCP que traduce llamadas a **tools** (JSON-RPC sobre stdio) en queries seguras contra IBM Netezza Performance Server, devolviendo resultados compactos y tipados aptos para que un LLM razone sobre ellos.

## Principios de diseño (jerarquía, no negociable)

1. **Seguridad primero**: cualquier SQL pasa por `sql_guard` antes de tocar la red.
2. **Responsabilidad única por tool**: una tool ejecuta **un** tipo de operación. Un `nz_query_select` que reciba un `DELETE` rechaza con error tipado.
3. **Determinismo y observabilidad**: toda acción produce un log estructurado (sin PII ni credenciales) que permita reproducir el comportamiento.
4. **Tokens como recurso escaso**: respuestas compactas, truncadas con hint, metadata antes que filas.
5. **Fallo explícito**: errores tipados en `errors.py`, nunca `except Exception: pass`, nunca retornos silenciosos.
6. **Idempotencia en lectura**: las tools de lectura son idempotentes y seguras de reintentar.

## Capas

```
┌───────────────────────────────────────────────────────────┐
│  Cliente MCP  (Claude Desktop / Claude Code / Cursor…)    │
└───────────────────────────┬───────────────────────────────┘
                            │  JSON-RPC stdio
┌───────────────────────────▼───────────────────────────────┐
│  server.py  (mcp SDK)                                     │
│  - handshake, discovery, despacho de tools                │
└───────────────────────────┬───────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────┐
│  tools.py  (registro y schemas JSON)                      │
│  - valida input → delega → formatea output                │
└───────┬──────────────────────────────────────┬────────────┘
        │                                      │
        ▼                                      ▼
┌────────────────┐                    ┌────────────────────┐
│  sql_guard.py  │                    │   catalog.py       │
│  valida SQL    │                    │   queries a _v_*   │
└───────┬────────┘                    └──────────┬─────────┘
        │                                        │
        └────────────────┬───────────────────────┘
                         ▼
            ┌────────────────────────────┐
            │   connection.py            │
            │   pool nzpy + streaming    │
            └────────────┬───────────────┘
                         │
                         ▼
            ┌────────────────────────────┐
            │   IBM Netezza (vía VPN)    │
            └────────────────────────────┘

        ┌─────────────────────────────────────┐
        │ auth.py  +  config.py               │
        │ keyring + ~/.nz-mcp/profiles.toml   │
        └─────────────────────────────────────┘
                 (transversal a todas las capas)
```

## Módulos

| Módulo | Responsabilidad | No hace |
|---|---|---|
| `server.py` | Arranca MCP por stdio, registra tools, maneja señales | Ejecutar SQL, validar permisos |
| `tools.py` | Define schemas, valida inputs, formatea outputs | Conocer detalles del driver |
| `sql_guard.py` | Parsea SQL con `sqlglot`, aplica reglas por modo | Ejecutar SQL |
| `auth.py` | Lee/escribe credenciales en `keyring`, valida perfil | Loggear password |
| `config.py` | Carga `~/.nz-mcp/profiles.toml`, expone perfil activo | Persistir password (eso es `auth.py`) |
| `connection.py` | Pool de conexiones `nzpy`, cursores con timeout, streaming | Decidir si la query es legal |
| `catalog.py` | Queries a `_v_database`, `_v_table`, `_v_relation_column`, etc. | Ejecutar queries del usuario |
| `i18n.py` | Resuelve mensajes por locale (`en`, `es`) | Formatear datos |
| `errors.py` | Excepciones tipadas: `GuardRejectedError`, `AuthError`, `TimeoutError`, etc. | Decidir cómo mostrar |

## Flujo de una tool (`nz_query_select` ejemplo)

```
1. server.py recibe call → delega a tools.py
2. tools.py valida input JSON-Schema
3. tools.py → sql_guard.validate(sql, mode='read')
     ↳ si falla: GuardRejectedError → respuesta MCP error
4. tools.py → connection.execute(sql, max_rows, timeout)
     ↳ inyecta LIMIT si falta
     ↳ usa cursor streaming, para al llegar a max_rows o cap bytes
5. tools.py formatea resultado:
     { "columns": [...], "rows": [...], "truncated": bool,
       "row_count": N, "duration_ms": T }
6. server.py devuelve al cliente MCP
7. Log estructurado: { tool, profile, duration_ms, rows, truncated, sql_hash }
     ↳ SQL completo solo en DEBUG; nunca resultados.
```

## Netezza target

- **NPS 11.2.1.11-IF1 [Build 4]** (instancia de referencia del mantenedor).
- Compatibilidad declarada: **NPS 11.x**.
- Catálogo usado: `_v_database`, `_v_schema`, `_v_table`, `_v_view`, `_v_relation_column`, `_v_table_storage_stat`, `_v_statistic`.
- No se usan características específicas de IPS/PureData Analytics modernas que rompan con 11.x.

## Decisiones diferidas (ver `docs/adr/`)

- Self-hosted runner para integration tests en CI → **fase 2**.
- Publicación en PyPI con Trusted Publishing OIDC → **fase 1.5** (tras primeros usuarios externos).
- Streaming de resultados a archivo local para queries masivas → evaluar tras feedback real.
- Soporte `pyodbc` como driver alternativo → documentado, no implementado en v0.1.

## Referencias cruzadas

- Contrato de tools: [tools-contract.md](tools-contract.md)
- Modelo de seguridad: [security-model.md](security-model.md)
- Estándares: `../standards/`
- Roles: `../roles/`
