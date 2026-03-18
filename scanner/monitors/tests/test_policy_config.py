"""Tests for policy_config module."""
import pytest
from scanner.monitors.policy_config import sensitivity_to_zscore, merge_policy_config, is_less_strict


class TestSensitivityToZscore:
    def test_max_sensitivity(self):
        assert sensitivity_to_zscore(0.99) == 2.0

    def test_standard_sensitivity(self):
        assert sensitivity_to_zscore(0.95) == 3.0

    def test_low_sensitivity(self):
        assert sensitivity_to_zscore(0.50) == 5.0

    def test_clamp_above_1(self):
        assert sensitivity_to_zscore(1.5) == 2.0

    def test_clamp_below_0(self):
        assert sensitivity_to_zscore(-0.1) == 5.0

    def test_interpolation(self):
        assert sensitivity_to_zscore(0.90) == 3.5


class TestMergePolicyConfig:
    def test_policy_values_used_when_no_overrides(self):
        merged, prov = merge_policy_config(
            monitor_type="FRESHNESS",
            config={"timestamp_column": "_loaded_at"},
            policy_config={"max_hours": 2, "warning_hours": 1},
            policy_overrides=[],
        )
        assert merged["max_hours"] == 2
        assert merged["warning_hours"] == 1
        assert merged["timestamp_column"] == "_loaded_at"
        assert prov["max_hours"] == "policy"
        assert prov["timestamp_column"] == "config"

    def test_override_wins_over_policy(self):
        merged, prov = merge_policy_config(
            monitor_type="FRESHNESS",
            config={"max_hours": 6, "timestamp_column": "_loaded_at"},
            policy_config={"max_hours": 2, "warning_hours": 1},
            policy_overrides=["max_hours"],
        )
        assert merged["max_hours"] == 6
        assert merged["warning_hours"] == 1
        assert prov["max_hours"] == "override"
        assert prov["warning_hours"] == "policy"

    def test_no_policy_config_uses_config_as_is(self):
        merged, prov = merge_policy_config(
            monitor_type="FRESHNESS",
            config={"max_hours": 6},
            policy_config=None,
            policy_overrides=[],
        )
        assert merged["max_hours"] == 6
        assert prov["max_hours"] == "config"

    def test_unknown_monitor_type_uses_config(self):
        merged, prov = merge_policy_config(
            monitor_type="CUSTOM_SQL",
            config={"sql": "SELECT 1"},
            policy_config={"max_hours": 2},
            policy_overrides=[],
        )
        assert merged["sql"] == "SELECT 1"
        assert "max_hours" not in merged

    def test_anomaly_sensitivity_conversion(self):
        merged, prov = merge_policy_config(
            monitor_type="OUTLIER_DETECTION",
            config={},
            policy_config={"anomaly_threshold": 0.95},
            policy_overrides=[],
        )
        assert merged["anomaly_threshold"] == 3.0
        assert prov["anomaly_threshold"] == "policy"


class TestIsLessStrict:
    def test_higher_max_hours_is_less_strict(self):
        assert is_less_strict("max_hours", 2, 6) is True

    def test_lower_max_hours_is_not_less_strict(self):
        assert is_less_strict("max_hours", 6, 2) is False

    def test_equal_values_not_less_strict(self):
        assert is_less_strict("max_hours", 2, 2) is False

    def test_lower_min_rows_is_less_strict(self):
        assert is_less_strict("min_rows", 100, 1) is True

    def test_higher_anomaly_threshold_is_less_strict(self):
        assert is_less_strict("anomaly_threshold", 3.0, 4.0) is True

    def test_strictness_enum_relaxed_vs_strict(self):
        assert is_less_strict("strictness", "strict", "warn") is True
        assert is_less_strict("strictness", "strict", "ignore") is True
        assert is_less_strict("strictness", "warn", "strict") is False

    def test_failure_tolerance_enum(self):
        assert is_less_strict("failure_tolerance", "strict", "normal") is True
        assert is_less_strict("failure_tolerance", "strict", "relaxed") is True
        assert is_less_strict("failure_tolerance", "relaxed", "strict") is False
