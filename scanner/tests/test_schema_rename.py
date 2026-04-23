"""Tests for schema monitor rename suspicion detection (Stage 4A)."""

from scanner.monitors.schema import SchemaMonitor


def _baseline(*cols):
    """Build baseline_columns from (name, type) tuples."""
    return [{"column_name": n, "data_type": t, "is_nullable": "YES"} for n, t in cols]


def _current(*cols):
    """Build query_results from (name, type) tuples."""
    return [
        {"column_name": n, "data_type": t, "is_nullable": "YES", "ordinal_position": i + 1}
        for i, (n, t) in enumerate(cols)
    ]


class TestRenameSuspicion:
    """Stage 4A: Conservative rename detection."""

    def test_simple_rename_detected(self):
        """user_name → username with same type → suspected rename."""
        monitor = SchemaMonitor({
            "baseline_columns": _baseline(("id", "integer"), ("user_name", "text")),
        })
        result = monitor.evaluate(
            _current(("id", "integer"), ("username", "text")),
            "db.public.users",
        )
        renames = [c for c in result.details["changes"] if c["change_type"] == "suspected_rename"]
        assert len(renames) == 1
        assert renames[0]["old_column"] == "user_name"
        assert renames[0]["new_column"] == "username"
        assert renames[0]["severity"] == "low"
        assert renames[0]["similarity"] > 0.6

    def test_incompatible_types_no_rename(self):
        """Different types should not be flagged as rename."""
        monitor = SchemaMonitor({
            "baseline_columns": _baseline(("id", "integer"), ("status", "integer")),
        })
        result = monitor.evaluate(
            _current(("id", "integer"), ("state", "text")),
            "db.public.orders",
        )
        renames = [c for c in result.details["changes"] if c["change_type"] == "suspected_rename"]
        assert len(renames) == 0

    def test_low_similarity_no_rename(self):
        """Very different names should not be flagged."""
        monitor = SchemaMonitor({
            "baseline_columns": _baseline(("id", "integer"), ("foo", "text")),
        })
        result = monitor.evaluate(
            _current(("id", "integer"), ("bar_baz_qux", "text")),
            "db.public.t",
        )
        renames = [c for c in result.details["changes"] if c["change_type"] == "suspected_rename"]
        assert len(renames) == 0

    def test_one_to_one_matching(self):
        """Multiple candidates should match one-to-one (greedy best match)."""
        monitor = SchemaMonitor({
            "baseline_columns": _baseline(
                ("id", "integer"),
                ("user_email", "text"),
                ("user_name", "text"),
            ),
        })
        result = monitor.evaluate(
            _current(
                ("id", "integer"),
                ("email_user", "text"),
                ("name_user", "text"),
            ),
            "db.public.users",
        )
        renames = [c for c in result.details["changes"] if c["change_type"] == "suspected_rename"]
        # Should get at most 2 renames, each used once
        matched_old = {r["old_column"] for r in renames}
        matched_new = {r["new_column"] for r in renames}
        assert len(matched_old) == len(renames)  # no duplicates
        assert len(matched_new) == len(renames)

    def test_rename_with_custom_threshold(self):
        """Custom similarity threshold."""
        monitor = SchemaMonitor({
            "baseline_columns": _baseline(("id", "integer"), ("created_at", "timestamp")),
            "rename_similarity_threshold": 0.9,
        })
        result = monitor.evaluate(
            _current(("id", "integer"), ("created_date", "timestamp")),
            "db.public.t",
        )
        renames = [c for c in result.details["changes"] if c["change_type"] == "suspected_rename"]
        # created_at vs created_date may not reach 0.9 threshold
        # The exact result depends on similarity score, but threshold should be respected
        for r in renames:
            assert r["similarity"] >= 0.9

    def test_rename_in_summary(self):
        """Suspected renames should appear in the summary message."""
        monitor = SchemaMonitor({
            "baseline_columns": _baseline(("id", "integer"), ("user_name", "text")),
        })
        result = monitor.evaluate(
            _current(("id", "integer"), ("username", "text")),
            "db.public.users",
        )
        assert "rename" in result.message.lower()

    def test_no_rename_when_no_added_or_removed(self):
        """If schema matches, no rename detection runs."""
        monitor = SchemaMonitor({
            "baseline_columns": _baseline(("id", "integer"), ("name", "text")),
        })
        result = monitor.evaluate(
            _current(("id", "integer"), ("name", "text")),
            "db.public.t",
        )
        assert result.status.value == "pass"
