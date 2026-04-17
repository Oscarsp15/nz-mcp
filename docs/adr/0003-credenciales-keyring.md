# ADR 0003 — Credenciales en `keyring` OS-native, metadata en TOML

- **Fecha**: 2026-04-16
- **Estado**: aceptado
- **Decidido por**: Security Engineer + Tech Lead (IA) + validación humana

## Contexto

El MCP necesita persistir credenciales del usuario para reconectar a Netezza entre sesiones. Opciones consideradas:

- `.env` plano: estándar pero filtra credenciales fácilmente (logs, copias, `git add` accidental).
- Variables de entorno del cliente MCP (Claude Desktop): aparecen en `ps`, en logs del cliente, sin cifrado.
- Keychain del SO vía `keyring`: cifrado nativo, sin archivo plano.
- Vault/cloud secret manager: overkill para uso individual.

El usuario también tiene **múltiples perfiles** (dev, prod, etc.).

## Decisión

- **Password**: `keyring` (Windows Credential Manager / macOS Keychain / Linux Secret Service), una entrada por perfil con clave `(service="nz-mcp", username=f"profile:{name}")`.
- **Metadata** (host, port, database, user, mode, defaults): archivo TOML en `~/.nz-mcp/profiles.toml` con permisos restrictivos (`0600` Unix, ACL usuario actual en Windows).
- **Wizard CLI** (`nz-mcp init`, `add-profile`) gestiona ambos.
- **Prohibido** cualquier flujo que ponga la password en `.env`, env var del cliente, o arg CLI.

## Alternativas consideradas

1. **`.env` con `python-dotenv`** — convención común pero sustituye seguridad por conveniencia. Rechazado.
2. **Env vars del cliente MCP** — visible en `ps`, persistido en config JSON del cliente. Rechazado.
3. **Archivo cifrado con `age`** — requiere passphrase manual cada uso o key management propio. Diferido como fallback documentado para entornos sin keyring.
4. **HashiCorp Vault / AWS Secrets Manager** — overkill para uso individual. No descartado para v1+ (perfil corporativo).

## Consecuencias

- ✅ Cero archivos planos con secretos.
- ✅ Estándar OS, sin que reinventemos cripto.
- ✅ Multi-perfil natural.
- ⚠️ Linux headless puede no tener Secret Service → documentar fallback (`keyring` con backend de archivo cifrado, o `age`).
- ⚠️ Migrar entre máquinas requiere reconfigurar perfiles (intencional: no exportar password en claro).

## Monitorizar

- Issues sobre fallos de `keyring` en distintas plataformas.
- Casos de Linux server / WSL sin backend.
- Demanda de export/import de perfiles (sin password).
