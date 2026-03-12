"""Tests for BI / Reporting monitors."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from ..base import MonitorStatus
from ..bi import (
    BIFreshnessProxyMonitor,
    BIUpstreamBreakRiskMonitor,
    BIContentHealthMonitor,
    BIRefreshFailureMonitor,
    BI_MONITOR_TYPES,
    BI_MONITOR_REGISTRY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_bi_client(**overrides):
    client = MagicMock()
    client.get_asset_metadata.return_value = {
        "title": "Sales Dashboard",
        "last_updated": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        **overrides,
    }
    return client


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestBIRegistry:

    def test_all_types_registered(self):
        for t in BI_MONITOR_TYPES:
            assert t in BI_MONITOR_REGISTRY

    def test_registry_count(self):
        assert len(BI_MONITOR_REGISTRY) == 4


# ---------------------------------------------------------------------------
# BI_FRESHNESS_PROXY
# ---------------------------------------------------------------------------

class TestBIFreshnessProxy:

    def test_pass_fresh_asset(self):
        client = _mock_bi_client()
        monitor = BIFreshnessProxyMonitor({"asset_id": "dash/1", "max_stale_hours": 24})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.PASS
        assert "fresh" in result.message.lower()

    def test_fail_stale_asset(self):
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        client = _mock_bi_client(last_updated=stale_time)
        monitor = BIFreshnessProxyMonitor({"asset_id": "dash/1", "max_stale_hours": 24})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.FAIL
        assert result.value > 24

    def test_warn_approaching_stale(self):
        # 75% of 24h = 18h, so 20h should trigger warn
        approaching_time = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
        client = _mock_bi_client(last_updated=approaching_time)
        monitor = BIFreshnessProxyMonitor({"asset_id": "dash/1", "max_stale_hours": 24})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.WARN

    def test_fail_asset_not_found(self):
        client = MagicMock()
        client.get_asset_metadata.return_value = None
        monitor = BIFreshnessProxyMonitor({"asset_id": "dash/missing"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.FAIL

    def test_error_no_asset_id(self):
        monitor = BIFreshnessProxyMonitor({})
        result = monitor.execute(MagicMock())
        assert result.status == MonitorStatus.ERROR

    def test_error_api_failure(self):
        client = MagicMock()
        client.get_asset_metadata.side_effect = Exception("API timeout")
        monitor = BIFreshnessProxyMonitor({"asset_id": "dash/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.ERROR
        assert "timeout" in result.message.lower()


# ---------------------------------------------------------------------------
# BI_UPSTREAM_BREAK_RISK
# ---------------------------------------------------------------------------

class TestBIUpstreamBreakRisk:

    def test_skip_without_store(self):
        monitor = BIUpstreamBreakRiskMonitor({"asset_id": "dash/1"})
        result = monitor.execute()
        assert result.status == MonitorStatus.SKIPPED

    def test_pass_no_upstream(self):
        store = MagicMock()
        store.get_upstream.return_value = []
        history_func = MagicMock(return_value=[])
        monitor = BIUpstreamBreakRiskMonitor({"asset_id": "dash/1"})
        result = monitor.execute(engine_store=store, monitor_history_func=history_func)
        assert result.status == MonitorStatus.PASS

    def test_pass_healthy_upstream(self):
        node = MagicMock()
        node.fqn = "proj.raw.orders"
        node.name = "orders"
        store = MagicMock()
        store.get_upstream.return_value = [node]
        history_func = MagicMock(return_value=[{"status": "PASS"}])
        monitor = BIUpstreamBreakRiskMonitor({"asset_id": "dash/1"})
        result = monitor.execute(engine_store=store, monitor_history_func=history_func)
        assert result.status == MonitorStatus.PASS

    def test_warn_one_failing_upstream(self):
        node = MagicMock()
        node.fqn = "proj.raw.orders"
        node.name = "orders"
        store = MagicMock()
        store.get_upstream.return_value = [node]
        history_func = MagicMock(return_value=[{"status": "FAIL"}])
        monitor = BIUpstreamBreakRiskMonitor({"asset_id": "dash/1"})
        result = monitor.execute(engine_store=store, monitor_history_func=history_func)
        assert result.status == MonitorStatus.WARN

    def test_fail_many_failing_upstreams(self):
        nodes = []
        for i in range(3):
            n = MagicMock()
            n.fqn = f"proj.raw.table_{i}"
            n.name = f"table_{i}"
            nodes.append(n)
        store = MagicMock()
        store.get_upstream.return_value = nodes
        history_func = MagicMock(return_value=[{"status": "FAIL"}])
        monitor = BIUpstreamBreakRiskMonitor({"asset_id": "dash/1"})
        result = monitor.execute(engine_store=store, monitor_history_func=history_func)
        assert result.status == MonitorStatus.FAIL
        assert result.value == 3.0


# ---------------------------------------------------------------------------
# BI_CONTENT_HEALTH
# ---------------------------------------------------------------------------

class TestBIContentHealth:

    def test_pass_healthy_asset(self):
        client = _mock_bi_client()
        monitor = BIContentHealthMonitor({"asset_id": "dash/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.PASS

    def test_fail_asset_not_found(self):
        client = MagicMock()
        client.get_asset_metadata.return_value = None
        monitor = BIContentHealthMonitor({"asset_id": "dash/missing"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.FAIL
        assert "not found" in result.message.lower() or "deleted" in result.message.lower()

    def test_fail_api_error(self):
        client = MagicMock()
        client.get_asset_metadata.side_effect = Exception("Forbidden")
        monitor = BIContentHealthMonitor({"asset_id": "dash/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.FAIL
        assert "inaccessible" in result.message.lower()

    def test_warn_failing_deliveries(self):
        client = _mock_bi_client()
        client.get_delivery_status.return_value = [
            {"status": "completed"},
            {"status": "failed"},
        ]
        monitor = BIContentHealthMonitor({"asset_id": "dash/1", "check_deliveries": True})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.WARN
        assert "delivery" in result.message.lower()

    def test_pass_no_delivery_check(self):
        client = _mock_bi_client()
        monitor = BIContentHealthMonitor({"asset_id": "dash/1", "check_deliveries": False})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.PASS

    def test_error_no_asset_id(self):
        monitor = BIContentHealthMonitor({})
        result = monitor.execute(MagicMock())
        assert result.status == MonitorStatus.ERROR


# ---------------------------------------------------------------------------
# BI_REFRESH_FAILURE
# ---------------------------------------------------------------------------

class TestBIRefreshFailure:

    def test_pass_all_succeeded(self):
        client = MagicMock()
        client.get_refresh_history.return_value = [
            {"status": "completed"},
            {"status": "completed"},
        ]
        monitor = BIRefreshFailureMonitor({"asset_id": "dataset/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.PASS
        assert result.value == 0.0

    def test_warn_partial_failure(self):
        client = MagicMock()
        client.get_refresh_history.return_value = [
            {"status": "completed"},
            {"status": "failed"},
        ]
        monitor = BIRefreshFailureMonitor({"asset_id": "dataset/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.WARN

    def test_fail_all_failed(self):
        client = MagicMock()
        client.get_refresh_history.return_value = [
            {"status": "failed"},
            {"status": "failed"},
        ]
        monitor = BIRefreshFailureMonitor({"asset_id": "dataset/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.FAIL

    def test_warn_no_refreshes(self):
        client = MagicMock()
        client.get_refresh_history.return_value = []
        monitor = BIRefreshFailureMonitor({"asset_id": "dataset/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.WARN

    def test_skip_unsupported_platform(self):
        client = MagicMock(spec=[])  # No get_refresh_history
        monitor = BIRefreshFailureMonitor({"asset_id": "dataset/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.SKIPPED

    def test_error_no_asset_id(self):
        monitor = BIRefreshFailureMonitor({})
        result = monitor.execute(MagicMock())
        assert result.status == MonitorStatus.ERROR

    def test_error_api_failure(self):
        client = MagicMock()
        client.get_refresh_history.side_effect = Exception("API error")
        monitor = BIRefreshFailureMonitor({"asset_id": "dataset/1"})
        result = monitor.execute(client)
        assert result.status == MonitorStatus.ERROR
