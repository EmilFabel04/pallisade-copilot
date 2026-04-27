"""End-to-end tests that build_query rejects SQL injection payloads.

These exercise the validation path from the monitor's public surface
(`build_query(database, schema, table, dialect)`) through `_fqn` /
`_validate_column` to the underlying `quote_identifier` helper.
"""

from __future__ import annotations

import pytest

from scanner.monitors.null_check import NullCheckMonitor
from scanner.monitors.uniqueness_check import UniquenessCheckMonitor
from scanner.monitors.volume import VolumeMonitor
from scanner.monitors.freshness import build_discovery_query


# Payloads that an attacker might supply via `targetFqn` (split into
# database.schema.table parts by the executor) or via monitor.columns.
# Note: dashes (e.g. "users--") are allowed in identifier atoms because
# BigQuery project IDs contain them; once quoted as `users--` the comment
# semantics no longer fire. The payloads below all contain SQL meta-
# characters that the strict regex genuinely refuses.
INJECTION_PAYLOADS = [
    "users; DROP TABLE secrets",
    "users/*x*/",
    "users' OR '1'='1",
    "1 UNION SELECT password FROM users",
    "users`evil",
    'users"evil',
    "users)",
    "users(",
    "users\x00",
    "users\nlf",
    " leading_space",
]


# ---------------------------------------------------------------------------
# fqn parts (database / schema / table) — common to all monitors via _fqn
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_null_check_rejects_injected_table(payload):
    m = NullCheckMonitor({"columns": ["email"]})
    with pytest.raises(ValueError):
        m.build_query("mydb", "public", payload, dialect="postgres")


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_null_check_rejects_injected_schema(payload):
    m = NullCheckMonitor({"columns": ["email"]})
    with pytest.raises(ValueError):
        m.build_query("mydb", payload, "users", dialect="postgres")


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_null_check_rejects_injected_database(payload):
    m = NullCheckMonitor({"columns": ["email"]})
    with pytest.raises(ValueError):
        m.build_query(payload, "public", "users", dialect="postgres")


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_uniqueness_rejects_injected_table(payload):
    m = UniquenessCheckMonitor({"columns": ["id"]})
    with pytest.raises(ValueError):
        m.build_query("db", "public", payload, dialect="bigquery")


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_volume_rejects_injected_table(payload):
    m = VolumeMonitor({"time_bucket_column": "created_at"})
    with pytest.raises(ValueError):
        m.build_query("db", "public", payload, dialect="postgres")


# ---------------------------------------------------------------------------
# Column names — interpolated raw into expressions and aliases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_null_check_rejects_injected_column(payload):
    m = NullCheckMonitor({"columns": [payload]})
    with pytest.raises(ValueError):
        m.build_query("db", "s", "users", dialect="postgres")


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_null_check_rejects_injected_timestamp_column(payload):
    m = NullCheckMonitor({"columns": ["email"], "timestamp_column": payload})
    with pytest.raises(ValueError):
        m.build_query("db", "s", "users", dialect="postgres")


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_uniqueness_rejects_injected_column(payload):
    m = UniquenessCheckMonitor({"columns": [payload]})
    with pytest.raises(ValueError):
        m.build_query("db", "s", "users", dialect="postgres")


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_volume_rejects_injected_time_bucket_column(payload):
    m = VolumeMonitor({"time_bucket_column": payload})
    with pytest.raises(ValueError):
        m.build_query("db", "s", "users", dialect="postgres")


# ---------------------------------------------------------------------------
# freshness.build_discovery_query — INFORMATION_SCHEMA query
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_freshness_discovery_rejects_injected_database(payload):
    with pytest.raises(ValueError):
        build_discovery_query(payload, "public", "users", dialect="bigquery")


def test_freshness_discovery_bigquery_table_in_string_literal_is_safe():
    # In BigQuery's discovery query the table flows ONLY into the string
    # literal `WHERE table_name = '<value>'`. SQL injection there requires
    # breaking out of the literal, which `escape_string_literal` prevents
    # by doubling apostrophes and rejecting control chars. Verify that a
    # value with a single quote round-trips as `''` (escaped, not raised).
    sql = build_discovery_query("proj", "ds", "user's", dialect="bigquery")
    assert "table_name = 'user''s'" in sql
    # Critical: no actual injection — the closing-quote of the literal
    # comes only after the doubled apostrophe.
    assert "user's'" not in sql.replace("user''s", "X")


def test_freshness_discovery_string_literal_rejects_control_chars():
    # Control characters in the string literal context are still rejected.
    with pytest.raises(ValueError):
        build_discovery_query("proj", "ds", "users\nbad", dialect="bigquery")
    with pytest.raises(ValueError):
        build_discovery_query("proj", "ds", "users\x00", dialect="bigquery")


def test_freshness_discovery_passes_normal_input():
    # Sanity: legitimate input produces output that contains the validated
    # parts in their proper identifier-quoted form.
    sql = build_discovery_query("my-project", "analytics", "events", dialect="bigquery")
    assert "`my-project`.`analytics`" in sql
    assert "table_name = 'events'" in sql


def test_null_check_normal_input_produces_quoted_fqn():
    m = NullCheckMonitor({"columns": ["email"]})
    sql = m.build_query("mydb", "public", "users", dialect="postgres")
    assert '"mydb"."public"."users"' in sql


def test_uniqueness_check_normal_input_produces_backtick_fqn_for_bigquery():
    m = UniquenessCheckMonitor({"columns": ["id"]})
    sql = m.build_query("project", "dataset", "events", dialect="bigquery")
    assert "`project`.`dataset`.`events`" in sql
