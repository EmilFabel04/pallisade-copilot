"""Tests that FreshnessMonitor fails loudly when no timestamp_column is set,
instead of silently falling back to a hardcoded "updated_at" — which produced
false-positive "freshness monitor failing" findings whenever the LLM ran
run_coverage_monitor inline against a table that has no updated_at column.
"""
import pytest

from scanner.monitors.freshness import FreshnessMonitor


class TestFreshnessFailLoudWhenNoColumn:
    def test_build_query_raises_when_no_timestamp_column_configured(self):
        """No timestamp_column → must raise a clear error, not silently use 'updated_at'."""
        monitor = FreshnessMonitor(config={"max_hours": 24})

        with pytest.raises(ValueError) as exc_info:
            monitor.build_query("acme-484520", "analytics", "daily_revenue", dialect="bigquery")

        msg = str(exc_info.value)
        # Error must name the table so the caller knows which monitor is misconfigured
        assert "daily_revenue" in msg
        # Error must call out the missing field
        assert "timestamp_column" in msg
        # Error must NOT recommend / fabricate "updated_at" as if it were a default
        assert "updated_at" not in msg.lower() or "fallback" in msg.lower() or "not" in msg.lower()

    def test_build_query_raises_for_empty_string_column(self):
        """timestamp_column='' is the same as not configured."""
        monitor = FreshnessMonitor(config={"timestamp_column": "", "max_hours": 24})

        with pytest.raises(ValueError):
            monitor.build_query("db", "schema", "tbl", dialect="bigquery")

    def test_build_query_succeeds_when_column_is_configured(self):
        """Sanity: with a real column, build_query still works."""
        monitor = FreshnessMonitor(config={"timestamp_column": "created_at"})

        sql = monitor.build_query("db", "schema", "tbl", dialect="bigquery")

        assert "created_at" in sql
        assert "MAX(created_at)" in sql

    def test_build_query_works_after_discovery_sets_column(self):
        """If discovery sets the column on the instance, build_query works."""
        monitor = FreshnessMonitor(config={})
        monitor.timestamp_column = "_loaded_at"  # discovery would set this

        sql = monitor.build_query("db", "schema", "tbl", dialect="bigquery")

        assert "_loaded_at" in sql
