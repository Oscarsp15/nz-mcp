# ADR 0009 — Expand tool catalog with bulk INSERT…SELECT and CTAS

- **Date**: 2026-04-17
- **Status**: accepted
- **Decided by**: Tech Lead (IA) + human validation via PR

## Context

Issue #85 requires `nz_insert_select` and `nz_create_table_as` for Netezza-parallel bulk patterns. The frozen `AGENTS.md` line cited “24 tools”; the live contract in `tools-contract.md` already grew with prior features (e.g. export DDL).

## Decision

Treat the **tool count** as documented in `docs/architecture/tools-contract.md` as the source of truth for the MCP surface. Update `AGENTS.md` to match the current catalog size when adding approved tools. No version bump of the product spec is required for additive tools.

## Consequences

- Positive: Clear alignment between router doc, contract, and registry.
- Negative: `AGENTS.md` must be updated when the tool count changes (same PR as contract).

## References

- Issue #85 (GitHub)
- `docs/architecture/tools-contract.md`
