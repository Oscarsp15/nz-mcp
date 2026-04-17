"""Rebuild CREATE TABLE DDL text from structured catalog metadata."""

from __future__ import annotations

from typing import Any


def build_create_table_ddl(
    *,
    fq_name: str,
    columns: list[dict[str, Any]],
    distribution: dict[str, Any],
    primary_key: list[str],
    foreign_keys: list[dict[str, Any]],
    include_constraints: bool,
) -> str:
    """Return a ``CREATE TABLE`` statement for Netezza-style DDL (uppercase identifiers)."""
    lines: list[str] = []
    for col in columns:
        nm = str(col["name"])
        dt = str(col["type"])
        nullable = bool(col.get("nullable", True))
        default = col.get("default")
        segment = f"  {nm} {dt}"
        if not nullable:
            segment += " NOT NULL"
        if default not in (None, ""):
            segment += f" DEFAULT {default}"
        lines.append(segment)

    if include_constraints and primary_key:
        cols = ", ".join(primary_key)
        lines.append(f"  PRIMARY KEY ({cols})")

    if include_constraints:
        for fk in foreign_keys:
            name = str(fk["name"])
            local_cols = ", ".join(str(x) for x in fk["columns"])
            ref = fk["references"]
            rs = str(ref["schema"])
            rt = str(ref["table"])
            rcols = ", ".join(str(x) for x in ref["columns"])
            lines.append(
                f"  CONSTRAINT {name} FOREIGN KEY ({local_cols}) REFERENCES {rs}.{rt} ({rcols})",
            )

    inner = ",\n".join(lines)
    dist_type = str(distribution.get("type", "RANDOM")).upper()
    dist_cols = distribution.get("columns") or []
    if dist_type == "HASH" and isinstance(dist_cols, list) and len(dist_cols) > 0:
        dist_clause = f"DISTRIBUTE ON HASH ({', '.join(str(c) for c in dist_cols)})"
    else:
        dist_clause = "DISTRIBUTE ON RANDOM"

    return f"CREATE TABLE {fq_name} (\n{inner}\n)\n{dist_clause};"
