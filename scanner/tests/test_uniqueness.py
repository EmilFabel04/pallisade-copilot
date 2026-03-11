"""Tests for UniquenessMonitor (Stage 5)."""

from scanner.monitors.uniqueness import UniquenessMonitor


class TestUniquenessBasic:
    """Basic uniqueness evaluation."""

    def test_pass_with_stable_baseline(self):
        monitor = UniquenessMonitor({
            "column": "user_id",
            "historical_values": [0.95, 0.96, 0.94, 0.95, 0.96, 0.95, 0.94],
        })
        results = [{"metric_value": 0.95, "distinct_count": 950, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        assert result.status.value == "pass"
        assert result.details["column"] == "user_id"
        assert result.details["likely_key"] is False

    def test_anomaly_detected_on_drop(self):
        monitor = UniquenessMonitor({
            "column": "user_id",
            "historical_values": [0.95, 0.96, 0.94, 0.95, 0.96, 0.95, 0.94],
        })
        # Dramatic drop in uniqueness
        results = [{"metric_value": 0.50, "distinct_count": 500, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        assert result.status.value in ("fail", "warn")
        assert "anomaly" in result.message.lower() or "below" in result.message.lower()

    def test_insufficient_baseline_passes(self):
        monitor = UniquenessMonitor({"column": "user_id"})
        results = [{"metric_value": 0.95, "distinct_count": 950, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        assert result.status.value == "pass"
        assert result.details.get("anomaly_ready") is False

    def test_no_results_returns_error(self):
        monitor = UniquenessMonitor({"column": "user_id"})
        result = monitor.evaluate([], "db.public.users")
        assert result.status.value == "error"


class TestLikelyKeyDetection:
    """Stage 5A: auto-tighten threshold for key columns."""

    def test_auto_detects_likely_key(self):
        """All baseline values > 0.99 → auto-detected as likely key."""
        monitor = UniquenessMonitor({
            "column": "id",
            "historical_values": [1.0, 1.0, 0.999, 1.0, 0.998, 1.0, 0.999],
        })
        # Small drop below 1.0 — should trigger with tighter threshold
        results = [{"metric_value": 0.99, "distinct_count": 990, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        assert result.details["likely_key"] is True
        # Threshold should be tightened to 2.0
        assert result.details["threshold_used"] <= 2.0

    def test_explicit_likely_key_config(self):
        """Config likely_key=True overrides auto-detection."""
        monitor = UniquenessMonitor({
            "column": "id",
            "likely_key": True,
            "historical_values": [0.90, 0.91, 0.89, 0.90, 0.91, 0.90, 0.89],
        })
        results = [{"metric_value": 0.90, "distinct_count": 900, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        assert result.details["likely_key"] is True
        assert result.details["threshold_used"] <= 2.0

    def test_not_a_key_column(self):
        """Baseline with values < 0.99 → not a key."""
        monitor = UniquenessMonitor({
            "column": "status",
            "historical_values": [0.05, 0.05, 0.06, 0.05, 0.04, 0.05, 0.06],
        })
        results = [{"metric_value": 0.05, "distinct_count": 5, "total_count": 100}]
        result = monitor.evaluate(results, "db.public.orders")

        assert result.details["likely_key"] is False


class TestTrendDetection:
    """Stage 5A: trend direction analysis."""

    def test_degrading_trend_detected(self):
        """Declining distinct_rate series → 'degrading' trend."""
        monitor = UniquenessMonitor({
            "column": "email",
            "historical_values": [
                0.98, 0.97, 0.96, 0.95, 0.94, 0.93, 0.92,
                0.91, 0.90, 0.89, 0.88, 0.87, 0.86, 0.85,
            ],
        })
        results = [{"metric_value": 0.84, "distinct_count": 840, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        assert result.details["trend_direction"] == "degrading"
        assert result.details["trend_slope"] < 0

    def test_stable_trend(self):
        """Stable series → 'stable' trend."""
        monitor = UniquenessMonitor({
            "column": "user_id",
            "historical_values": [0.95, 0.96, 0.95, 0.94, 0.95, 0.96, 0.95],
        })
        results = [{"metric_value": 0.95, "distinct_count": 950, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        assert result.details["trend_direction"] == "stable"

    def test_improving_trend(self):
        """Increasing distinct_rate → 'improving' trend."""
        monitor = UniquenessMonitor({
            "column": "email",
            "historical_values": [
                0.85, 0.86, 0.87, 0.88, 0.89, 0.90, 0.91,
                0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98,
            ],
        })
        results = [{"metric_value": 0.99, "distinct_count": 990, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        assert result.details["trend_direction"] == "improving"
        assert result.details["trend_slope"] > 0


class TestConfidenceInfo:
    """Standardized confidence reporting."""

    def test_confidence_info_present(self):
        monitor = UniquenessMonitor({
            "column": "user_id",
            "historical_values": [0.95, 0.96, 0.94, 0.95, 0.96, 0.95, 0.94],
        })
        results = [{"metric_value": 0.95, "distinct_count": 950, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        ci = result.details["confidence_info"]
        assert ci["confidence_pct"] == 50  # 7 points → 50%
        assert ci["baseline_count"] == 7
        assert ci["evaluation_mode"] == "statistical"
        assert ci["downgraded"] is False

    def test_confidence_info_for_likely_key(self):
        monitor = UniquenessMonitor({
            "column": "id",
            "historical_values": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        })
        results = [{"metric_value": 1.0, "distinct_count": 1000, "total_count": 1000}]
        result = monitor.evaluate(results, "db.public.users")

        ci = result.details["confidence_info"]
        assert ci["evaluation_mode"] == "likely_key"


class TestQueryBuild:
    """Query generation."""

    def test_simple_query(self):
        monitor = UniquenessMonitor({"column": "email"})
        sql = monitor.build_query("db", "public", "users")
        assert "DISTINCT" in sql.upper()
        assert "email" in sql

    def test_time_series_query_postgres(self):
        monitor = UniquenessMonitor({
            "column": "email",
            "timestamp_column": "created_at",
            "lookback_days": 30,
        })
        sql = monitor.build_query("db", "public", "users")
        assert "bucket_date" in sql
        assert "DISTINCT" in sql.upper()

    def test_time_series_query_bigquery(self):
        monitor = UniquenessMonitor({
            "column": "email",
            "timestamp_column": "created_at",
            "lookback_days": 30,
        })
        sql = monitor.build_query("project", "dataset", "users", dialect="bigquery")
        assert "bucket_date" in sql
        assert "DATE_SUB" in sql

    def test_raises_without_column(self):
        monitor = UniquenessMonitor({})
        try:
            monitor.build_query("db", "public", "users")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestTimeSeriesEvaluation:
    """Evaluation from time-series query results."""

    def test_eval_from_time_series(self):
        monitor = UniquenessMonitor({
            "column": "email",
            "timestamp_column": "created_at",
        })
        results = [
            {"bucket_date": "2026-02-01", "metric_value": 0.95, "distinct_count": 950, "total_count": 1000},
            {"bucket_date": "2026-02-02", "metric_value": 0.96, "distinct_count": 960, "total_count": 1000},
            {"bucket_date": "2026-02-03", "metric_value": 0.94, "distinct_count": 940, "total_count": 1000},
            {"bucket_date": "2026-02-04", "metric_value": 0.95, "distinct_count": 950, "total_count": 1000},
        ]
        result = monitor.evaluate(results, "db.public.users")
        assert result.status.value == "pass"
        assert result.value == 0.95
