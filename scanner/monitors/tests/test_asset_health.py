"""Tests for asset_health scoring utility."""

import pytest
from scanner.monitors.asset_health import (
    compute_asset_health_score,
    compute_asset_coverage,
    compute_monitor_scoring,
    resolve_asset_category,
    health_status_from_score,
    APPLICABLE_MONITORS,
)


# ---------------------------------------------------------------------------
# Health scoring
# ---------------------------------------------------------------------------

class TestComputeAssetHealthScore:
    def test_single_pass(self):
        score, status = compute_asset_health_score(["PASS"])
        assert score == 100.0
        assert status == "healthy"

    def test_single_warn(self):
        score, status = compute_asset_health_score(["WARN"])
        assert score == 50.0
        assert status == "at_risk"

    def test_single_fail(self):
        score, status = compute_asset_health_score(["FAIL"])
        assert score == 0.0
        assert status == "unhealthy"

    def test_single_error(self):
        score, status = compute_asset_health_score(["ERROR"])
        assert score == 0.0
        assert status == "unhealthy"

    def test_pass_pass_warn(self):
        score, status = compute_asset_health_score(["PASS", "PASS", "WARN"])
        assert abs(score - 83.3) < 0.5
        assert status == "degraded"

    def test_pass_fail(self):
        score, _ = compute_asset_health_score(["PASS", "FAIL"])
        assert score == 50.0

    def test_warn_fail_error(self):
        score, status = compute_asset_health_score(["WARN", "FAIL", "ERROR"])
        assert abs(score - 16.7) < 0.5
        assert status == "unhealthy"

    def test_all_skipped_running(self):
        score, status = compute_asset_health_score(["SKIPPED", "RUNNING"])
        assert score is None
        assert status == "unmonitored"

    def test_skipped_excluded(self):
        score, _ = compute_asset_health_score(["PASS", "SKIPPED"])
        assert score == 100.0

    def test_running_excluded(self):
        score, _ = compute_asset_health_score(["PASS", "RUNNING"])
        assert score == 100.0

    def test_none_status_excluded(self):
        score, _ = compute_asset_health_score(["PASS", None])
        assert score == 100.0

    def test_empty_list(self):
        score, status = compute_asset_health_score([])
        assert score is None
        assert status == "unmonitored"


class TestHealthStatusFromScore:
    def test_healthy(self):
        assert health_status_from_score(90) == "healthy"
        assert health_status_from_score(100) == "healthy"

    def test_degraded(self):
        assert health_status_from_score(70) == "degraded"
        assert health_status_from_score(89) == "degraded"

    def test_at_risk(self):
        assert health_status_from_score(40) == "at_risk"
        assert health_status_from_score(69) == "at_risk"

    def test_unhealthy(self):
        assert health_status_from_score(0) == "unhealthy"
        assert health_status_from_score(39) == "unhealthy"


# ---------------------------------------------------------------------------
# Coverage scoring
# ---------------------------------------------------------------------------

class TestComputeAssetCoverage:
    def test_warehouse_full_coverage(self):
        result = compute_asset_coverage(
            {
                "FRESHNESS", "VOLUME", "SCHEMA_CHANGE", "NULL_CHECK",
                "UNIQUENESS_CHECK", "REFERENTIAL", "RANGE_VALIDATION",
                "ACCEPTED_VALUES", "DATE_CONSISTENCY", "DATA_TYPE_VALIDATION",
                "OUTLIER_DETECTION",
            },
            "warehouse",
        )
        assert result["coveragePct"] == 100
        assert result["coverageStatus"] == "good"
        assert result["missingTypes"] == []

    def test_warehouse_core_monitors_good(self):
        """Core monitors (9 of 11) hit >= 80% threshold."""
        result = compute_asset_coverage(
            {
                "FRESHNESS", "VOLUME", "SCHEMA_CHANGE", "NULL_CHECK",
                "UNIQUENESS_CHECK", "REFERENTIAL", "RANGE_VALIDATION",
                "ACCEPTED_VALUES", "OUTLIER_DETECTION",
            },
            "warehouse",
        )
        assert result["coveragePct"] >= 80
        assert result["coverageStatus"] == "good"

    def test_warehouse_few_monitors_partial(self):
        result = compute_asset_coverage(
            {"FRESHNESS", "VOLUME", "SCHEMA_CHANGE"},
            "warehouse",
        )
        assert result["coveragePct"] < 80
        assert result["coverageStatus"] == "partial"

    def test_warehouse_none(self):
        result = compute_asset_coverage(set(), "warehouse")
        assert result["coveragePct"] == 0
        assert result["coverageStatus"] == "none"

    def test_legacy_type_aliases_expand(self):
        """Legacy types (NULL_RATE, ANOMALY) expand to canonical equivalents."""
        result = compute_asset_coverage(
            {"FRESHNESS", "VOLUME", "SCHEMA_CHANGE", "NULL_RATE", "ANOMALY"},
            "warehouse",
        )
        # NULL_RATE → NULL_CHECK, ANOMALY → OUTLIER_DETECTION
        assert result["configured"] >= 5

    def test_bi_full(self):
        result = compute_asset_coverage(
            {"BI_FRESHNESS_PROXY", "BI_CONTENT_HEALTH", "BI_UPSTREAM_BREAK_RISK", "BI_REFRESH_FAILURE"},
            "bi",
        )
        assert result["coveragePct"] == 100
        assert result["coverageStatus"] == "good"

    def test_bi_partial(self):
        result = compute_asset_coverage(
            {"BI_FRESHNESS_PROXY", "BI_CONTENT_HEALTH"},
            "bi",
        )
        assert result["coveragePct"] == 50
        assert result["coverageStatus"] == "partial"

    def test_orchestration_2_of_3(self):
        result = compute_asset_coverage(
            {"DAG_LAST_RUN", "DAG_SCHEDULE_LAG"},
            "orchestration",
        )
        assert abs(result["coveragePct"] - 66.7) < 0.5

    def test_non_applicable_types_ignored(self):
        result = compute_asset_coverage(
            {"FRESHNESS", "CUSTOM_SQL"},
            "warehouse",
        )
        assert result["configured"] == 1


# ---------------------------------------------------------------------------
# Category resolver
# ---------------------------------------------------------------------------

class TestResolveAssetCategory:
    def test_warehouse_domain(self):
        assert resolve_asset_category(platform_domain="warehouse") == "warehouse"

    def test_bi_domain(self):
        assert resolve_asset_category(platform_domain="bi") == "bi"

    def test_reporting_domain(self):
        assert resolve_asset_category(platform_domain="reporting") == "bi"

    def test_ingestion_domain(self):
        assert resolve_asset_category(platform_domain="ingestion") == "ingestion"

    def test_transform_domain(self):
        assert resolve_asset_category(platform_domain="transform") == "dbt_transform"

    def test_layer_fallback(self):
        assert resolve_asset_category(layer="WAREHOUSE") == "warehouse"
        assert resolve_asset_category(layer="REPORTING") == "bi"

    def test_unknown(self):
        assert resolve_asset_category(platform_domain="other", layer="UNKNOWN") is None


# ---------------------------------------------------------------------------
# Combined scoring
# ---------------------------------------------------------------------------

class TestComputeMonitorScoring:
    def test_orchestration_all_pass(self):
        result = compute_monitor_scoring(
            [
                {"monitorType": "DAG_LAST_RUN", "lastStatus": "PASS"},
                {"monitorType": "DAG_SCHEDULE_LAG", "lastStatus": "PASS"},
                {"monitorType": "TASK_FAILURE_RATE", "lastStatus": "PASS"},
            ],
            "orchestration",
        )
        assert result["coveragePct"] == 100
        assert result["coverageStatus"] == "good"
        assert result["healthScore"] == 100.0
        assert result["healthStatus"] == "healthy"

    def test_bi_partial(self):
        result = compute_monitor_scoring(
            [
                {"monitorType": "BI_FRESHNESS_PROXY", "lastStatus": "PASS"},
                {"monitorType": "BI_CONTENT_HEALTH", "lastStatus": "WARN"},
            ],
            "bi",
        )
        assert result["healthScore"] == 75.0
        assert result["healthStatus"] == "degraded"
        assert result["coveragePct"] == 50.0
        assert result["coverageStatus"] == "partial"

    def test_watch_backed_monitor_counts(self):
        """Watch-backed monitors count the same as standalone ones."""
        result = compute_monitor_scoring(
            [
                {"monitorType": "SYNC_LAG", "lastStatus": "PASS"},
                {"monitorType": "FAILED_SYNCS", "lastStatus": "PASS"},
                {"monitorType": "CONNECTOR_SCHEMA_DRIFT", "lastStatus": "PASS"},
            ],
            "ingestion",
        )
        assert result["coveragePct"] == 100
        assert result["healthScore"] == 100.0
