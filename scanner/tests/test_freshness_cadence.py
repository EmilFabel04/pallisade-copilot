"""Tests for cadence-aware freshness monitoring."""

from __future__ import annotations

from scanner.monitors.freshness import FreshnessMonitor
from scanner.monitors.base import MonitorStatus


class TestCadenceAwareFreshness:
    """Test that freshness monitor learns and enforces update cadence."""

    def _gaps_every_6h(self, count: int = 20) -> list[float]:
        """Generate gaps centered around 6 hours."""
        import random
        random.seed(42)
        return [6.0 + random.uniform(-0.5, 0.5) for _ in range(count)]

    def test_within_cadence_passes(self):
        """Current age within learned cadence should PASS."""
        gaps = self._gaps_every_6h()
        monitor = FreshnessMonitor(config={
            "timestamp_column": "created_at",
            "max_hours": 24,
            "cadence_aware": True,
            "cadence_gaps": gaps,
        })

        result = monitor.evaluate(
            [{"hours_since_update": 5.0, "last_value": "2025-01-01", "total_rows": 100}],
            "db.schema.table",
        )

        assert result.status == MonitorStatus.PASS
        assert result.details["cadence_aware"] is True
        assert "learned cadence" in result.message

    def test_exceeding_cadence_warns(self):
        """Exceeding median * multiplier but not p95 * multiplier should WARN."""
        # Use wider variance so p95 is distinctly higher than median
        gaps = [6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 7.0, 8.0, 10.0, 12.0, 14.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0]
        monitor = FreshnessMonitor(config={
            "timestamp_column": "created_at",
            "max_hours": 48,
            "cadence_aware": True,
            "cadence_gaps": gaps,
            "cadence_multiplier": 2.0,
        })

        # median ~6h, p95 ~13h. 13h > 6*2=12 (median*mult) but < 13*2=26 (p95*mult) → WARN
        result = monitor.evaluate(
            [{"hours_since_update": 13.0, "last_value": "2025-01-01", "total_rows": 100}],
            "db.schema.table",
        )

        assert result.status == MonitorStatus.WARN
        assert result.details["cadence_aware"] is True
        assert "exceeding" in result.message.lower()

    def test_significantly_exceeding_cadence_fails(self):
        """Significantly exceeding p95 * multiplier should FAIL."""
        gaps = self._gaps_every_6h()
        monitor = FreshnessMonitor(config={
            "timestamp_column": "created_at",
            "max_hours": 48,
            "cadence_aware": True,
            "cadence_gaps": gaps,
            "cadence_multiplier": 2.0,
        })

        # 30h >> p95 * 2 (~13h)
        result = monitor.evaluate(
            [{"hours_since_update": 30.0, "last_value": "2025-01-01", "total_rows": 100}],
            "db.schema.table",
        )

        assert result.status == MonitorStatus.FAIL
        assert result.details["cadence_aware"] is True
        assert "significantly" in result.message.lower()

    def test_cadence_disabled_uses_static_threshold(self):
        """Without cadence_aware, should use static max_hours."""
        monitor = FreshnessMonitor(config={
            "timestamp_column": "created_at",
            "max_hours": 24,
            "cadence_aware": False,
        })

        # 5h old — well within 24h static threshold
        result = monitor.evaluate(
            [{"hours_since_update": 5.0, "last_value": "2025-01-01", "total_rows": 100}],
            "db.schema.table",
        )

        assert result.status == MonitorStatus.PASS
        assert result.details.get("cadence_aware") is None or result.details.get("cadence_aware") is False

    def test_insufficient_samples_falls_through(self):
        """With fewer gaps than cadence_min_samples, should fall through to static."""
        monitor = FreshnessMonitor(config={
            "timestamp_column": "created_at",
            "max_hours": 24,
            "cadence_aware": True,
            "cadence_gaps": [6.0, 6.0, 6.0],  # Only 3, need 5
            "cadence_min_samples": 5,
        })

        # 20h — exceeds 6h cadence but not 24h static
        result = monitor.evaluate(
            [{"hours_since_update": 20.0, "last_value": "2025-01-01", "total_rows": 100}],
            "db.schema.table",
        )

        # Falls through to static: 20h < 24h = WARN (between warn_hours=18 and max=24)
        assert result.status == MonitorStatus.WARN
        assert result.details.get("cadence_aware") is None or result.details.get("cadence_aware") is False

    def test_cadence_details_include_learned_stats(self):
        """Cadence result should include learned median and p95 gaps."""
        gaps = [4.0, 5.0, 6.0, 6.0, 6.0, 6.0, 7.0, 7.0, 8.0, 12.0]
        monitor = FreshnessMonitor(config={
            "timestamp_column": "created_at",
            "max_hours": 48,
            "cadence_aware": True,
            "cadence_gaps": gaps,
        })

        result = monitor.evaluate(
            [{"hours_since_update": 5.0, "last_value": "2025-01-01", "total_rows": 100}],
            "db.schema.table",
        )

        assert result.status == MonitorStatus.PASS
        assert "learned_median_gap_hours" in result.details
        assert "learned_p95_gap_hours" in result.details
        assert "cadence_samples" in result.details
        assert result.details["cadence_samples"] == 10

    def test_custom_multiplier(self):
        """Custom cadence_multiplier should adjust the expected max."""
        gaps = [6.0] * 20  # Consistent 6h cadence
        monitor = FreshnessMonitor(config={
            "timestamp_column": "created_at",
            "max_hours": 48,
            "cadence_aware": True,
            "cadence_gaps": gaps,
            "cadence_multiplier": 1.5,  # Tighter: 6h * 1.5 = 9h max
        })

        # 10h exceeds 9h expected max
        result = monitor.evaluate(
            [{"hours_since_update": 10.0, "last_value": "2025-01-01", "total_rows": 100}],
            "db.schema.table",
        )

        assert result.status in (MonitorStatus.WARN, MonitorStatus.FAIL)
        assert result.details["expected_max_hours"] == 9.0
