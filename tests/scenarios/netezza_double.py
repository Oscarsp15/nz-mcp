"""In-memory Netezza driver double shared by every role scenario.

Scenario tests run the real stack -- server dispatch, permission gate, tool, sql_guard,
catalog layer -- and replace only ``nzpy.connect``, the same boundary the unit suite
mocks. This module is the single place where that double lives; scenario files never
define their own.

Behaviours reproduced on purpose, because scenarios assert on them:

* ``_V_PROCEDURE.PROCEDURESOURCE`` stores the procedure **body only**. nz-mcp rebuilds
  the ``CREATE OR REPLACE PROCEDURE`` header on top of it, so DDL line numbers are
  offset from source line numbers, while the truncation hint of ``nz_get_procedure_ddl``
  speaks *source* numbering. Without that skew the maintainer scenario would be
  worthless.
* Rows are tuples in the column order declared by each catalog query in
  ``nz_mcp.catalog.queries``, the way nzpy delivers them.
* Statements executed by one tool are visible to the next one, so a scenario can
  create an object and then read it back through a different tool.

Anything the double does not understand raises `FakeNetezzaError`: a scenario must
never pass because the double silently returned an empty result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

_IDENT: Final[str] = r"[A-Za-z][A-Za-z0-9_$]*"
_RELATION: Final[re.Pattern[str]] = re.compile(
    rf"(?:(?P<db>{_IDENT})\.\.)?(?P<schema>{_IDENT})\.(?P<name>{_IDENT})",
)
_PROC_DELIMITERS: Final[re.Pattern[str]] = re.compile(
    r"^\s*BEGIN_PROC\b(?P<body>.*?)\bEND_PROC\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_FAKE_CREATE_DATE: Final[str] = "2026-01-15 09:00:00"

Row = tuple[Any, ...]
Key = tuple[str, str, str]


class FakeNetezzaError(RuntimeError):
    """Raised for anything the double cannot answer faithfully."""


@dataclass(frozen=True, slots=True)
class FakeColumn:
    name: str
    type: str
    nullable: bool = True
    default: str | None = None


@dataclass(slots=True)
class FakeTable:
    columns: list[FakeColumn]
    rows: list[Row] = field(default_factory=list)
    distribution: tuple[str, ...] = ()
    primary_key: tuple[str, ...] = ()
    owner: str = "ADMIN"

    def index_of(self, column: str) -> int:
        upper = column.upper()
        for index, col in enumerate(self.columns):
            if col.name.upper() == upper:
                return index
        raise FakeNetezzaError(f"column {column!r} does not exist")


@dataclass(slots=True)
class FakeProcedure:
    """A ``_V_PROCEDURE`` row. ``source`` is the body only, as Netezza stores it."""

    name: str
    arguments: str
    returns: str
    signature: str
    source: str
    owner: str = "ADMIN"


@dataclass(frozen=True, slots=True)
class ExecutedStatement:
    database: str
    sql: str


def catalog_source(body: str) -> str:
    """Return what ``PROCEDURESOURCE`` would store for a full procedure body."""
    match = _PROC_DELIMITERS.match(body.strip())
    if match is None:
        return body
    return match.group("body")


def _like(value: str, pattern: str | None) -> bool:
    """Netezza ``LIKE`` against an uppercased value; ``None`` means no filter."""
    if pattern is None:
        return True
    regex = "^" + re.escape(pattern.upper()).replace("%", ".*").replace("_", ".") + "$"
    return re.match(regex, value.upper()) is not None


def _param(params: Any, index: int) -> str | None:
    if not isinstance(params, (tuple, list)) or index >= len(params):
        return None
    cell = params[index]
    return None if cell is None else str(cell)


def _balanced(text: str, open_at: int) -> tuple[str, int]:
    """Content of the parenthesis group opening at ``open_at``, plus its closing index."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : i], i
    raise FakeNetezzaError(f"unbalanced parenthesis in: {text[:80]!r}")


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


class FakeNetezza:
    """The in-memory server. One instance backs one scenario."""

    def __init__(self) -> None:
        self.databases: dict[str, str] = {}
        self.schemas: dict[tuple[str, str], str] = {}
        self.tables: dict[Key, FakeTable] = {}
        self.procedures: dict[Key, FakeProcedure] = {}
        self.executed: list[ExecutedStatement] = []
        self.connections_opened: list[str] = []

    # -- setup ----------------------------------------------------------------

    def add_database(self, database: str, *, owner: str = "ADMIN") -> None:
        self.databases[database.upper()] = owner

    def add_schema(self, database: str, schema: str, *, owner: str = "ADMIN") -> None:
        self.schemas[(database.upper(), schema.upper())] = owner

    def add_table(self, database: str, schema: str, table: str, value: FakeTable) -> None:
        self.tables[(database.upper(), schema.upper(), table.upper())] = value

    def add_procedure(self, database: str, schema: str, procedure: FakeProcedure) -> None:
        key = (database.upper(), schema.upper(), procedure.name.upper())
        self.procedures[key] = procedure

    # -- driver surface -------------------------------------------------------

    def connect(self, **kwargs: Any) -> FakeConnection:
        database = str(kwargs.get("database", "")).upper()
        if database not in self.databases:
            raise FakeNetezzaError(f"database {database!r} is not visible")
        self.connections_opened.append(database)
        return FakeConnection(self, database)

    # -- assertion helpers ----------------------------------------------------

    def statements(self, *, starting_with: str) -> list[str]:
        head = starting_with.upper()
        return [e.sql for e in self.executed if " ".join(e.sql.split()).upper().startswith(head)]

    def table(self, database: str, schema: str, table: str) -> FakeTable | None:
        return self.tables.get((database.upper(), schema.upper(), table.upper()))

    def procedure(self, database: str, schema: str, name: str) -> FakeProcedure | None:
        return self.procedures.get((database.upper(), schema.upper(), name.upper()))


class FakeConnection:
    def __init__(self, server: FakeNetezza, database: str) -> None:
        self.server = server
        self.database = database
        self.closed = False

    def cursor(self) -> FakeCursor:
        if self.closed:
            raise FakeNetezzaError("cursor requested on a closed connection")
        return FakeCursor(self.server, self)

    def close(self) -> None:
        self.closed = True


class FakeCursor:
    def __init__(self, server: FakeNetezza, connection: FakeConnection) -> None:
        self.server = server
        self.connection = connection
        self.description: list[tuple[str, str]] | None = None
        self.rowcount: int = -1
        self.closed = False
        self._rows: list[Row] = []
        self._offset = 0

    # -- DB-API surface -------------------------------------------------------

    def execute(self, sql: str, params: Any = None) -> None:
        self.server.executed.append(ExecutedStatement(self.connection.database, sql))
        self.description = None
        self.rowcount = -1
        self._offset = 0
        self._rows = self._run(sql, params)

    def fetchall(self) -> list[Row]:
        out = self._rows[self._offset :]
        self._offset = len(self._rows)
        return out

    def fetchmany(self, size: int) -> list[Row]:
        out = self._rows[self._offset : self._offset + size]
        self._offset += len(out)
        return out

    def fetchone(self) -> Row | None:
        if self._offset >= len(self._rows):
            return None
        out = self._rows[self._offset]
        self._offset += 1
        return out

    def close(self) -> None:
        self.closed = True

    # -- dispatch -------------------------------------------------------------

    def _run(self, sql: str, params: Any) -> list[Row]:
        text = " ".join(sql.split())
        upper = text.upper()

        if "VERSION()" in upper:
            self.description = [("VERSION", "varchar")]
            return [("Release 11.2.1.11-IF1 [Build 4] (double)",)]
        if "_V_" in upper:
            return self._catalog_read(text, params)
        if upper.startswith("EXPLAIN"):
            return self._explain(text)
        if upper.startswith("SELECT"):
            return self._select(text)
        if upper.startswith("CREATE TABLE"):
            return self._create_table(text)
        if upper.startswith("INSERT INTO"):
            return self._insert(text)
        if upper.startswith("TRUNCATE TABLE"):
            return self._truncate(text)
        if upper.startswith("DROP TABLE"):
            return self._drop_table(text)
        if re.match(r"^CREATE\s+(OR\s+REPLACE\s+)?PROCEDURE\b", upper):
            return self._create_procedure(sql)
        raise FakeNetezzaError(f"statement not supported by the double: {text[:120]!r}")

    # -- catalog views --------------------------------------------------------

    def _catalog_database(self, text: str) -> str:
        match = re.search(rf"({_IDENT})\.\._V_", text)
        return match.group(1).upper() if match else self.connection.database

    def _catalog_read(self, text: str, params: Any) -> list[Row]:
        upper = text.upper()
        database = self._catalog_database(text)
        if "_V_TABLE_STORAGE_STAT" in upper:
            return self._stats_rows(database, params)
        if "_V_TABLE_DIST_MAP" in upper:
            return self._dist_rows(params)
        if "_V_RELATION_KEYDATA" in upper:
            return self._keydata_rows(database, upper, params)
        if "_V_RELATION_COLUMN" in upper:
            return self._column_rows(database, params)
        if "_V_PROCEDURE" in upper:
            return self._procedure_rows(database, upper, params)
        if "_V_DATABASE" in upper:
            return self._database_rows(params)
        if "_V_SCHEMA" in upper:
            return self._schema_rows(database, params)
        if "_V_TABLE" in upper:
            return self._table_rows(database, params)
        raise FakeNetezzaError(f"catalog view not supported by the double: {text[:120]!r}")

    def _database_rows(self, params: Any) -> list[Row]:
        pattern = _param(params, 0)
        return [
            (name, owner)
            for name, owner in sorted(self.server.databases.items())
            if _like(name, pattern)
        ]

    def _schema_rows(self, database: str, params: Any) -> list[Row]:
        pattern = _param(params, 0)
        return [
            (schema, owner)
            for (db, schema), owner in sorted(self.server.schemas.items())
            if db == database and _like(schema, pattern)
        ]

    def _table_rows(self, database: str, params: Any) -> list[Row]:
        schema = (_param(params, 0) or "").upper()
        pattern = _param(params, 1)
        return [
            (name, table.owner)
            for (db, sch, name), table in sorted(self.server.tables.items())
            if (db, sch) == (database, schema) and _like(name, pattern)
        ]

    def _require_table(self, database: str, params: Any, *, schema_at: int = 0) -> FakeTable:
        schema = (_param(params, schema_at) or "").upper()
        name = (_param(params, schema_at + 1) or "").upper()
        table = self.server.tables.get((database, schema, name))
        if table is None:
            raise FakeNetezzaError(f"relation {database}.{schema}.{name} does not exist")
        return table

    def _column_rows(self, database: str, params: Any) -> list[Row]:
        table = self._require_table(database, params)
        return [
            (col.name, col.type, not col.nullable, col.default, index)
            for index, col in enumerate(table.columns, start=1)
        ]

    def _dist_rows(self, params: Any) -> list[Row]:
        database = (_param(params, 0) or "").upper()
        table = self._require_table(database, params, schema_at=1)
        return [(col, seq) for seq, col in enumerate(table.distribution, start=1)]

    def _keydata_rows(self, database: str, upper: str, params: Any) -> list[Row]:
        if "'F'" in upper:
            return []
        table = self._require_table(database, params)
        name = (_param(params, 1) or "").upper()
        return [(f"{name}_PK", col, seq) for seq, col in enumerate(table.primary_key, start=1)]

    def _stats_rows(self, database: str, params: Any) -> list[Row]:
        table = self._require_table(database, params)
        used = 1024 * (len(table.rows) + 1)
        return [(len(table.rows), used, used * 2, 0.0, _FAKE_CREATE_DATE)]

    def _procedure_rows(self, database: str, upper: str, params: Any) -> list[Row]:
        schema = (_param(params, 0) or "").upper()
        wants_source = "PROCEDURESOURCE" in upper
        listing = "NUMARGS" in upper
        if listing or "CREATEDATE" in upper:
            pattern = _param(params, 1)
            selected = [
                proc
                for (db, sch, name), proc in sorted(self.server.procedures.items())
                if (db, sch) == (database, schema) and _like(name, pattern)
            ]
        else:
            name = (_param(params, 1) or "").upper()
            found = self.server.procedures.get((database, schema, name))
            selected = [] if found is None else [found]
        if listing:
            return [
                (p.name, p.owner, p.arguments, p.returns, p.signature, p.arguments.count(",") + 1)
                for p in selected
            ]
        rows = [(p.name, p.owner, p.arguments, p.returns, p.source, p.signature) for p in selected]
        if "CREATEDATE" in upper:
            return [(*row, _FAKE_CREATE_DATE) for row in rows]
        if not wants_source:
            raise FakeNetezzaError(f"_v_procedure projection not supported: {upper[:120]!r}")
        return rows

    # -- user SQL -------------------------------------------------------------

    def _resolve(self, text: str, *, at: int = 0) -> tuple[str, str, str]:
        match = _RELATION.search(text, at)
        if match is None:
            raise FakeNetezzaError(f"could not find a qualified relation in: {text[:120]!r}")
        database = (match.group("db") or self.connection.database).upper()
        return database, match.group("schema").upper(), match.group("name").upper()

    def _select(self, text: str) -> list[Row]:
        match = re.match(r"^SELECT\s+(?P<cols>.+?)\s+FROM\s+(?P<rest>.+)$", text, re.IGNORECASE)
        if match is None:
            raise FakeNetezzaError(f"SELECT not supported by the double: {text[:120]!r}")
        rest = match.group("rest")
        limit_match = re.search(r"\bLIMIT\s+(\d+)\s*$", rest, re.IGNORECASE)
        limit = int(limit_match.group(1)) if limit_match else None
        relation_text = rest[: limit_match.start()] if limit_match else rest
        if re.search(r"\b(WHERE|JOIN|GROUP BY|ORDER BY|HAVING)\b", relation_text, re.IGNORECASE):
            raise FakeNetezzaError(f"SELECT clause not supported by the double: {text[:120]!r}")
        database, schema, name = self._resolve(relation_text)
        table = self.server.tables.get((database, schema, name))
        if table is None:
            raise FakeNetezzaError(f"relation {database}.{schema}.{name} does not exist")

        cols = match.group("cols").strip()
        if re.match(r"^COUNT\s*\(\s*\*\s*\)", cols, re.IGNORECASE):
            self.description = [("COUNT", "bigint")]
            return [(len(table.rows),)]
        if cols == "*":
            self.description = [(c.name, c.type) for c in table.columns]
            return list(table.rows)
        names = [c.split()[0].strip('"') for c in _split_top_level(cols)]
        indexes = [table.index_of(n) for n in names]
        self.description = [(table.columns[i].name, table.columns[i].type) for i in indexes]
        rows = [tuple(row[i] for i in indexes) for row in table.rows]
        return rows if limit is None else rows[:limit]

    def _explain(self, text: str) -> list[Row]:
        inner = re.sub(r"^EXPLAIN\s+(VERBOSE\s+)?", "", text, flags=re.IGNORECASE)
        database, schema, name = self._resolve(inner)
        self.description = [("PLAN", "varchar")]
        return [(f"QUERY PLAN: sequential scan on {database}.{schema}.{name} (double)",)]

    def _create_table(self, text: str) -> list[Row]:
        open_at = text.index("(")
        head = text[:open_at]
        database, schema, name = self._resolve(head)
        if (database, schema) not in self.server.schemas:
            raise FakeNetezzaError(f"schema {database}.{schema} does not exist")
        body, close_at = _balanced(text, open_at)
        tail = text[close_at + 1 :].upper()
        columns = [_parse_column(chunk) for chunk in _split_top_level(body)]
        distribution: tuple[str, ...] = ()
        dist_match = re.search(r"DISTRIBUTE ON HASH\s*\(([^)]*)\)", tail)
        if dist_match:
            distribution = tuple(c.strip().upper() for c in dist_match.group(1).split(","))
        key = (database, schema, name)
        if key in self.server.tables and "IF NOT EXISTS" not in text.upper():
            raise FakeNetezzaError(f"relation {schema}.{name} already exists")
        self.server.tables[key] = FakeTable(columns=columns, distribution=distribution)
        return []

    def _insert(self, text: str) -> list[Row]:
        database, schema, name = self._resolve(text, at=len("INSERT INTO"))
        target = self.server.tables.get((database, schema, name))
        if target is None:
            raise FakeNetezzaError(f"relation {database}.{schema}.{name} does not exist")
        select_at = text.upper().index("SELECT")
        columns_text = text[:select_at]
        open_at = columns_text.find("(")
        if open_at < 0:
            target_columns = [c.name for c in target.columns]
        else:
            inner, _ = _balanced(columns_text, open_at)
            target_columns = [c.strip().upper() for c in _split_top_level(inner)]
        source_rows = self._select(" ".join(text[select_at:].split()))
        positions = [target.index_of(c) for c in target_columns]
        for source in source_rows:
            if len(source) != len(positions):
                raise FakeNetezzaError("INSERT column count does not match the SELECT list")
            cells: list[Any] = [None] * len(target.columns)
            for position, value in zip(positions, source, strict=True):
                cells[position] = value
            target.rows.append(tuple(cells))
        self.rowcount = len(source_rows)
        return []

    def _truncate(self, text: str) -> list[Row]:
        database, schema, name = self._resolve(text)
        table = self.server.tables.get((database, schema, name))
        if table is None:
            raise FakeNetezzaError(f"relation {database}.{schema}.{name} does not exist")
        table.rows.clear()
        return []

    def _drop_table(self, text: str) -> list[Row]:
        database, schema, name = self._resolve(text)
        key = (database, schema, name)
        if key not in self.server.tables and "IF EXISTS" not in text.upper():
            raise FakeNetezzaError(f"relation {schema}.{name} does not exist")
        self.server.tables.pop(key, None)
        return []

    def _create_procedure(self, sql: str) -> list[Row]:
        head_match = re.match(
            rf"^\s*CREATE\s+(OR\s+REPLACE\s+)?PROCEDURE\s+"
            rf"(?:(?P<db>{_IDENT})\.\.)?(?P<schema>{_IDENT})\.(?P<name>{_IDENT})\s*\(",
            sql,
            re.IGNORECASE,
        )
        if head_match is None:
            raise FakeNetezzaError(f"CREATE PROCEDURE not parseable: {sql[:120]!r}")
        arguments, close_at = _balanced(sql, sql.index("(", head_match.end() - 1))
        rest = sql[close_at + 1 :]
        returns_match = re.search(r"RETURNS\s+(?P<type>[^\n]+)", rest, re.IGNORECASE)
        marker = re.search(r"LANGUAGE\s+NZPLSQL\s+AS\s*\n", rest, re.IGNORECASE)
        if marker is None:
            raise FakeNetezzaError("CREATE PROCEDURE without LANGUAGE NZPLSQL AS marker")
        body = rest[marker.end() :]
        database = (head_match.group("db") or self.connection.database).upper()
        schema = head_match.group("schema").upper()
        name = head_match.group("name").upper()
        if (database, schema) not in self.server.schemas:
            raise FakeNetezzaError(f"schema {database}.{schema} does not exist")
        self.server.procedures[(database, schema, name)] = FakeProcedure(
            name=name,
            arguments=f"({arguments})",
            returns=returns_match.group("type").strip() if returns_match else "",
            signature=f"{name}({arguments})",
            # Netezza keeps the body only: the delimiters are not persisted.
            source=catalog_source(body),
        )
        return []


def _parse_column(chunk: str) -> FakeColumn:
    upper = chunk.upper()
    tokens = chunk.split()
    if len(tokens) < 2:
        raise FakeNetezzaError(f"column definition not parseable: {chunk!r}")
    name = tokens[0].strip('"')
    type_tokens: list[str] = []
    for token in tokens[1:]:
        if token.upper() in ("NOT", "NULL", "DEFAULT"):
            break
        type_tokens.append(token)
    default: str | None = None
    default_match = re.search(r"DEFAULT\s+(?P<value>.+)$", chunk, re.IGNORECASE)
    if default_match:
        default = default_match.group("value").strip()
    return FakeColumn(
        name=name.upper(),
        type=" ".join(type_tokens).upper(),
        nullable="NOT NULL" not in upper,
        default=default,
    )
