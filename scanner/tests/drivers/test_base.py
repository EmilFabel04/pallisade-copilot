"""Tests for IntegrationDriver ABC and graph domain enforcement."""

import pytest
from scanner.drivers.base import (
    ConfigValidation,
    ConnectionResult,
    DriverCapabilities,
    GraphDomain,
    IntegrationDriver,
    IntegrationLayer,
)


class ConcreteDataPlaneDriver(IntegrationDriver):
    """A DATA_PLANE driver that returns real lineage."""

    def id(self): return "test_data"
    def integration_type(self): return "TEST_DATA"
    def layer(self): return IntegrationLayer.WAREHOUSE
    def graph_domain(self): return GraphDomain.DATA_PLANE

    def validate_config(self, config):
        return ConfigValidation(valid=True)

    def test_connection(self, config):
        return ConnectionResult(ok=True, message="ok")

    def capabilities(self):
        return DriverCapabilities(can_extract_lineage=True)

    def _extract_lineage_impl(self, config):
        return (["node1"], ["edge1"])


class ConcreteControlPlaneDriver(IntegrationDriver):
    """A CONTROL_PLANE driver that tries to return lineage (should be blocked)."""

    def id(self): return "test_control"
    def integration_type(self): return "TEST_CONTROL"
    def layer(self): return IntegrationLayer.NOTIFICATIONS
    def graph_domain(self): return GraphDomain.CONTROL_PLANE

    def validate_config(self, config):
        return ConfigValidation(valid=True)

    def test_connection(self, config):
        return ConnectionResult(ok=True, message="ok")

    def capabilities(self):
        return DriverCapabilities(can_write=True)

    def _extract_lineage_impl(self, config):
        # This SHOULD NEVER be called thanks to the guard
        return (["bad_node"], ["bad_edge"])


class TestGraphDomainEnforcement:
    """CRITICAL: Verify CONTROL_PLANE tools cannot create lineage."""

    def test_data_plane_returns_lineage(self):
        driver = ConcreteDataPlaneDriver()
        nodes, edges = driver.extract_lineage({})
        assert nodes == ["node1"]
        assert edges == ["edge1"]

    def test_control_plane_returns_empty(self):
        driver = ConcreteControlPlaneDriver()
        nodes, edges = driver.extract_lineage({})
        assert nodes == []
        assert edges == []

    def test_control_plane_impl_never_called(self):
        """Even if _extract_lineage_impl returns data, the guard blocks it."""
        driver = ConcreteControlPlaneDriver()
        # Directly calling _extract_lineage_impl would return data
        raw_nodes, raw_edges = driver._extract_lineage_impl({})
        assert raw_nodes == ["bad_node"]

        # But extract_lineage() enforces the guard
        nodes, edges = driver.extract_lineage({})
        assert nodes == []
        assert edges == []


class TestDriverIdentity:
    def test_to_dict(self):
        driver = ConcreteDataPlaneDriver()
        d = driver.to_dict()
        assert d["id"] == "test_data"
        assert d["integration_type"] == "TEST_DATA"
        assert d["layer"] == "WAREHOUSE"
        assert d["graph_domain"] == "DATA_PLANE"
        assert d["capabilities"]["can_extract_lineage"] is True

    def test_health_check_defaults_to_test_connection(self):
        driver = ConcreteDataPlaneDriver()
        result = driver.health_check({})
        assert result.ok is True

    def test_default_empty_methods(self):
        driver = ConcreteDataPlaneDriver()
        assert driver.extract_metadata({}) == []
        assert driver.fetch_logs({}) == []
        assert driver.events_emitted() == []
        assert driver.contract_schema() is None
        assert driver.ui_config_schema() is None
        assert driver.recommended_monitors() == []


class TestConfigValidation:
    def test_config_validation_to_dict(self):
        cv = ConfigValidation(valid=False, errors=["missing host"], warnings=["no port"])
        d = cv.to_dict()
        assert d["valid"] is False
        assert "missing host" in d["errors"]
        assert "no port" in d["warnings"]

    def test_connection_result_to_dict(self):
        cr = ConnectionResult(ok=True, message="connected", latency_ms=42)
        d = cr.to_dict()
        assert d["ok"] is True
        assert d["latency_ms"] == 42
