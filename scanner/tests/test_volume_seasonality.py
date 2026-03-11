"""Tests for volume monitor weekday seasonality (Stage 1A)."""

from datetime import date, timedelta

from scanner.monitors.volume import VolumeMonitor


def _make_results(start_date: date, counts: list[int]) -> list[dict]:
    """Build query_results with bucket_date and row_count."""
    results = []
    for i, count in enumerate(counts):
        d = start_date + timedelta(days=i)
        results.append({"bucket_date": d, "row_count": count})
    return results


class TestWeekdaySeasonality:
    """Stage 1A: day-of-week filtered baseline for volume."""

    def test_seasonal_baseline_filters_to_same_dow(self):
        """When seasonality=day_of_week, baseline should only use same weekday."""
        # Build 28 days (4 full weeks) of data where Mondays have ~1000
        # and other days have ~500.  Latest day is a Monday with 1050.
        start = date(2026, 2, 9)  # Monday
        counts = []
        for i in range(28):
            d = start + timedelta(days=i)
            if d.weekday() == 0:  # Monday
                counts.append(1000)
            else:
                counts.append(500)
        # Latest is day 28 = another Monday, slightly elevated
        counts.append(1050)  # 29th entry, Monday

        monitor = VolumeMonitor({
            "time_bucket_column": "created_at",
            "seasonality": "day_of_week",
            "anomaly_threshold": 3.0,
        })
        results = _make_results(start, counts)
        result = monitor.evaluate(results, "test.table")

        # 1050 compared to Monday baseline [1000, 1000, 1000, 1000] → normal
        assert result.status.value == "pass"
        assert result.details["seasonal_filtered"] is True
        assert result.details["confidence_info"]["evaluation_mode"] == "seasonal_dow"

    def test_seasonal_anomaly_detected(self):
        """A Monday with 100 rows when baseline Mondays have ~1000 → anomaly."""
        start = date(2026, 2, 9)  # Monday
        counts = []
        for i in range(28):
            d = start + timedelta(days=i)
            if d.weekday() == 0:
                counts.append(1000)
            else:
                counts.append(500)
        counts.append(100)  # Monday with massive drop

        monitor = VolumeMonitor({
            "time_bucket_column": "created_at",
            "seasonality": "day_of_week",
            "anomaly_threshold": 3.0,
        })
        results = _make_results(start, counts)
        result = monitor.evaluate(results, "test.table")

        assert result.status.value in ("fail", "warn")
        assert result.details["seasonal_filtered"] is True

    def test_falls_back_to_full_baseline_when_insufficient_dow(self):
        """If less than 3 same-DOW points, fall back to full baseline."""
        # Only 10 days → less than 3 Mondays.  Add variance to avoid constant_baseline.
        start = date(2026, 2, 9)  # Monday
        counts = [490, 510, 505, 495, 500, 510, 495, 505, 500, 490] + [505]

        monitor = VolumeMonitor({
            "time_bucket_column": "created_at",
            "seasonality": "day_of_week",
            "anomaly_threshold": 3.0,
        })
        results = _make_results(start, counts)
        result = monitor.evaluate(results, "test.table")

        assert result.status.value == "pass"
        assert result.details["seasonal_filtered"] is False

    def test_no_seasonality_uses_full_baseline(self):
        """Without seasonality config, all days are in baseline."""
        start = date(2026, 2, 9)
        counts = []
        for i in range(28):
            d = start + timedelta(days=i)
            if d.weekday() == 0:
                counts.append(1000)
            else:
                counts.append(500)
        counts.append(1050)

        monitor = VolumeMonitor({
            "time_bucket_column": "created_at",
            "anomaly_threshold": 3.0,
        })
        results = _make_results(start, counts)
        result = monitor.evaluate(results, "test.table")

        # Without seasonality, baseline includes all 28 days (mean ~571)
        # 1050 against that wider baseline may or may not flag depending on stats
        assert result.details["seasonal_filtered"] is False

    def test_seasonal_with_string_dates(self):
        """Handles bucket_date as ISO string."""
        start = date(2026, 2, 9)
        counts = []
        for i in range(28):
            d = start + timedelta(days=i)
            if d.weekday() == 0:
                counts.append(1000)
            else:
                counts.append(500)
        counts.append(1020)

        monitor = VolumeMonitor({
            "time_bucket_column": "created_at",
            "seasonality": "day_of_week",
        })
        # Use string dates
        results = []
        for i, count in enumerate(counts):
            d = start + timedelta(days=i)
            results.append({"bucket_date": d.isoformat(), "row_count": count})

        result = monitor.evaluate(results, "test.table")
        assert result.status.value == "pass"
        assert result.details["seasonal_filtered"] is True

    def test_confidence_info_present(self):
        """All time-series results include confidence_info."""
        start = date(2026, 2, 9)
        counts = [500] * 10 + [510]

        monitor = VolumeMonitor({
            "time_bucket_column": "created_at",
        })
        results = _make_results(start, counts)
        result = monitor.evaluate(results, "test.table")

        ci = result.details["confidence_info"]
        assert "confidence_pct" in ci
        assert "baseline_count" in ci
        assert "evaluation_mode" in ci
        assert "downgraded" in ci
