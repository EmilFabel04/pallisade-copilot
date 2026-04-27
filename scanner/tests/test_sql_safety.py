"""Tests for the SQL identifier and string-literal escaping helpers."""

from __future__ import annotations

import pytest

from scanner.adapters.sql_safety import (
    escape_string_literal,
    join_quoted_identifiers,
    quote_identifier,
)


# ---------------------------------------------------------------------------
# quote_identifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,dialect,expected",
    [
        ("events", "postgres", '"events"'),
        ("Events", "snowflake", '"Events"'),
        ("events", "bigquery", "`events`"),
        ("project-id.dataset.table", "bigquery", "`project-id`.`dataset`.`table`"),
        ("my_db.public.users", "postgres", '"my_db"."public"."users"'),
        ("MY_DB.PUBLIC.USERS", "redshift", '"MY_DB"."PUBLIC"."USERS"'),
        ("col_$1", "bigquery", "`col_$1`"),  # dollar allowed (BQ partition)
        ("events_2024", "postgres", '"events_2024"'),
        ("_underscore_lead", "postgres", '"_underscore_lead"'),
    ],
)
def test_quote_identifier_accepts_legitimate(name, dialect, expected):
    assert quote_identifier(name, dialect) == expected


@pytest.mark.parametrize(
    "payload",
    [
        "evil; DROP TABLE users",         # statement injection
        "evil/*x*/",                       # block comment
        "evil OR 1=1",                     # space + boolean injection
        "evil`",                           # backtick (BQ quote char)
        'evil"',                           # double-quote (PG quote char)
        "evil'",                           # single quote
        "evil)",                           # paren — function-call break
        "evil(",
        "1leading_digit",                  # SQL identifier rule
        "",                                # empty
        " leading_space",
        "trailing_space ",
        "with space",                      # space disallowed (use quoted form via DB tools, not free FQN)
        "UNION SELECT",                    # not a single atom anyway, but reject
        "evil\x00null",                    # NUL byte
        "evil\nlf",                        # newline
        "evil\rcr",
        "evil\t",                          # tab also rejected for safety
    ],
)
def test_quote_identifier_rejects_injection(payload):
    with pytest.raises(ValueError):
        quote_identifier(payload, "postgres")


def test_quote_identifier_rejects_none():
    with pytest.raises(ValueError):
        quote_identifier(None, "postgres")  # type: ignore[arg-type]


def test_quote_identifier_rejects_overlong():
    with pytest.raises(ValueError):
        quote_identifier("a" * 256, "postgres")


def test_quote_identifier_dotted_part_rejection():
    # Each atom validated independently — so even one bad atom kills the whole.
    with pytest.raises(ValueError):
        quote_identifier("good.bad evil.also_good", "postgres")


def test_quote_identifier_unknown_dialect_defaults_to_double_quote():
    # We don't error on unknown dialect; we fall back to ANSI double-quote.
    assert quote_identifier("foo", "weird-warehouse") == '"foo"'


def test_quote_identifier_sqlserver_uses_brackets():
    assert quote_identifier("dbo.events", "sqlserver") == "[dbo].[events]"
    assert quote_identifier("dbo.events", "mssql") == "[dbo].[events]"


def test_quote_identifier_allows_dashes_for_bigquery_projects():
    # BigQuery project IDs commonly contain dashes, including consecutive
    # ones in user-chosen names. Inside backticks these are safe — the
    # comment-terminator only fires outside a quoted identifier.
    assert (
        quote_identifier("my-project-1.dataset.table", "bigquery")
        == "`my-project-1`.`dataset`.`table`"
    )


# ---------------------------------------------------------------------------
# escape_string_literal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("simple", "simple"),
        ("with space", "with space"),
        ("O'Brien", "O''Brien"),
        ("multi'quote'string", "multi''quote''string"),
        ("", ""),
        ("ünicode", "ünicode"),  # non-ASCII letters preserved
        ("123-456", "123-456"),
    ],
)
def test_escape_string_literal_doubles_quotes(raw, expected):
    assert escape_string_literal(raw) == expected


@pytest.mark.parametrize(
    "payload",
    [
        "x\x00y",   # NUL
        "line\nbreak",
        "carriage\rreturn",
        "bell\x07",
    ],
)
def test_escape_string_literal_rejects_control_chars(payload):
    with pytest.raises(ValueError):
        escape_string_literal(payload)


def test_escape_string_literal_does_not_escape_backslashes():
    # SQL standard: backslash is literal in single-quoted strings (Postgres
    # standard_conforming_strings=on). We deliberately don't touch them.
    assert escape_string_literal(r"path\to\thing") == r"path\to\thing"


def test_escape_string_literal_handles_none():
    assert escape_string_literal(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# join_quoted_identifiers
# ---------------------------------------------------------------------------


def test_join_quoted_identifiers_basic():
    assert (
        join_quoted_identifiers(["my_db", "public", "events"], "postgres")
        == '"my_db"."public"."events"'
    )
    assert (
        join_quoted_identifiers(["proj-id", "dataset", "table"], "bigquery")
        == "`proj-id`.`dataset`.`table`"
    )


def test_join_quoted_identifiers_rejects_empty():
    with pytest.raises(ValueError):
        join_quoted_identifiers([], "postgres")


def test_join_quoted_identifiers_rejects_bad_atom():
    with pytest.raises(ValueError):
        join_quoted_identifiers(["good", "bad evil"], "postgres")
