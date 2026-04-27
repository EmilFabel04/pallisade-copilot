"""
SQL identifier and literal escaping helpers.

The monitor SQL builders and adapter `quote_identifier` methods both feed
user-controlled values (table names, schema names, column names from
`targetFqn` and monitor.columns) into SQL. Without validation+escaping
these are SQL injection sinks.

Two contexts are guarded here:

- **Identifier context** — a name appearing where SQL expects a table /
  schema / database / column. Different dialects use different quote
  characters (BigQuery: backtick; Postgres/Snowflake/Redshift/MSSQL:
  double-quote). We validate against a strict character set, reject
  anything else, and additionally double-up the dialect's quote char as
  defence in depth.

- **String literal context** — a value appearing inside `'...'`, e.g.
  `WHERE table_name = '<value>'` in INFORMATION_SCHEMA queries. SQL-
  standard escape is `'` → `''`. The monitors don't have parameterized
  query plumbing yet, so we apply the textual escape here.
"""

from __future__ import annotations

import re
from typing import Iterable

# Allowed characters for an identifier "atom" (one segment of a possibly-
# dotted name like `project.dataset.table`). Letters, digits, underscore,
# dollar (BigQuery date-partition suffix), and dash (BigQuery project IDs).
# A leading digit is rejected to match SQL's identifier rules.
_IDENT_ATOM = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]*$")

# Quote pair per dialect: (open, close, escape-by-doubling-of). For most
# dialects the open and close are the same character (`"`, `` ` ``); SQL
# Server uses bracketed identifiers and escapes the closing bracket.
_QUOTE: dict[str, tuple[str, str, str]] = {
    "bigquery": ("`", "`", "`"),
    "postgres": ('"', '"', '"'),
    "postgresql": ('"', '"', '"'),
    "snowflake": ('"', '"', '"'),
    "redshift": ('"', '"', '"'),
    "databricks": ("`", "`", "`"),
    "sqlserver": ("[", "]", "]"),
    "mssql": ("[", "]", "]"),
}


def _quote_pair(dialect: str) -> tuple[str, str, str]:
    return _QUOTE.get((dialect or "").lower(), ('"', '"', '"'))


def _validate_atom(atom: str) -> None:
    if not isinstance(atom, str) or not atom:
        raise ValueError("identifier must be a non-empty string")
    if len(atom) > 255:
        raise ValueError("identifier is too long")
    if not _IDENT_ATOM.match(atom):
        # Don't echo the offending value — it may already be hostile and we
        # don't want it round-tripping through error messages or logs.
        raise ValueError("identifier contains disallowed characters")


def quote_identifier(name: str, dialect: str = "postgres") -> str:
    """Validate and quote a (possibly dotted) SQL identifier for *dialect*.

    Multi-part names are split on `.` and each atom is validated separately,
    e.g. ``project.dataset.table`` for BigQuery. Quote-character collisions
    inside atoms are escaped (defence in depth — the validator already
    rejects them, but doubling-up keeps us safe if the regex is ever
    loosened).
    """
    if name is None:
        raise ValueError("identifier is required")
    parts = str(name).split(".")
    for atom in parts:
        _validate_atom(atom)
    open_q, close_q, esc = _quote_pair(dialect)
    escaped = [a.replace(esc, esc + esc) for a in parts]
    return ".".join(f"{open_q}{a}{close_q}" for a in escaped)


def escape_string_literal(value: str, dialect: str = "postgres") -> str:
    """Escape *value* for inclusion inside a single-quoted SQL string.

    Returns the *body* — the caller wraps it in `'…'`. Rejects strings
    that contain NUL bytes (some drivers terminate on \\0 inside a literal,
    leading to truncation-based bypasses) and bytes outside printable
    ASCII + common Unicode letters (we accept Unicode but not control
    chars). Backslash escaping is dialect-dependent and intentionally NOT
    applied — SQL standard is `'` → `''` only; backslashes are literal.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    if "\x00" in value:
        raise ValueError("string literal contains NUL byte")
    # Reject other ASCII control characters — line terminators, carriage
    # returns, BEL, etc. Real identifiers don't contain them.
    if any(ord(c) < 0x20 and c != "\t" for c in value):
        raise ValueError("string literal contains control characters")
    return value.replace("'", "''")


def join_quoted_identifiers(parts: Iterable[str], dialect: str = "postgres") -> str:
    """Quote each part separately and join with dots.

    Convenience for callers that already have the segments as a list,
    e.g. ``join_quoted_identifiers(["my_db", "public", "events"], "postgres")``.
    """
    parts = list(parts)
    if not parts:
        raise ValueError("at least one identifier part is required")
    for atom in parts:
        _validate_atom(atom)
    open_q, close_q, esc = _quote_pair(dialect)
    escaped = [a.replace(esc, esc + esc) for a in parts]
    return ".".join(f"{open_q}{a}{close_q}" for a in escaped)
