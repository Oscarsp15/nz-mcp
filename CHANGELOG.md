# Changelog

Todos los cambios notables a este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y este proyecto adhiere a [SemVer](https://semver.org/spec/v2.0.0.html).

Cada entrada se documenta en **español** y **english**.

## [Unreleased]

### Added
- ES: comando CLI `nz-mcp doctor` con diagnóstico local (sin red/Netezza) e informe i18n ES/EN.
- EN: `nz-mcp doctor` CLI for local diagnostics (no network/Netezza) with ES/EN i18n report.
- ES: estructura inicial del repositorio con `AGENTS.md` como router de despacho para agentes IA.
- EN: initial repository scaffolding with `AGENTS.md` as dispatch router for AI agents.
- ES: docs completas de arquitectura, roles senior (×8), estándares y ADRs (×7).
- EN: complete docs for architecture, senior roles (x8), standards and ADRs (x7).
- ES: contrato de tools v0.1 con 24 tools de responsabilidad única.
- EN: v0.1 tools contract with 24 single-responsibility tools.
- ES: estándar de issues AI-pickup-ready con templates y labels canónicos.
- EN: AI-pickup-ready issue standard with templates and canonical labels.
- ES: tools `nz_current_profile` y `nz_switch_profile` (sesión).
- EN: `nz_current_profile` and `nz_switch_profile` tools (session).
- ES: módulo `sql_guard` con clasificación basada en `sqlglot` y modos `read`/`write`/`admin`.
- EN: `sql_guard` module with `sqlglot`-based classification and `read`/`write`/`admin` modes.
- ES: gestión de credenciales con `keyring` OS-native + perfiles en TOML.
- EN: credentials management via OS-native `keyring` + TOML profiles.
- ES: catálogo i18n ES/EN para mensajes de error y hints.
- EN: ES/EN i18n catalog for error messages and hints.
- ES: CLI `nz-mcp init`, `add-profile`, `list-profiles`, `doctor`, `test-connection`, `serve`.
- EN: `nz-mcp init`, `add-profile`, `list-profiles`, `doctor`, `test-connection`, `serve` CLI.
- ES: CI con lint, type-check, tests y validación de convenciones (branches, commits, PRs).
- EN: CI with lint, type-check, tests and convention validation (branches, commits, PRs).
