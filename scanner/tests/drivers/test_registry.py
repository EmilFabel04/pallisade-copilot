"""Tests for DriverRegistry."""

import pytest
from scanner.drivers.base import (
    ConfigValidation,
    ConnectionResult,
    DriverCapabilities,
    GraphDomain,
    IntegrationDriver,
    IntegrationLayer,
)
from scanner.drivers.registry import DriverRegistry


class DummyDataDriver(IntegrationDriver):
    def id(self): return "dummy_data"
    def integration_type(self): return "DUMMY_DATA"
    def layer(self): return IntegrationLayer.WAREHOUSE
    def graph_domain(self): return GraphDomain.DATA_PLANE
    def validate_config(self, config): return ConfigValidation(valid=True)
    def test_connection(self, config): return ConnectionResult(ok=True, message="ok")
    def capabilities(self): return DriverCapabilities()


class DummyControlDriver(IntegrationDriver):
    def id(self): return "dummy_ctrl"
    def integration_type(self): return "DUMMY_CTRL"
    def layer(self): return IntegrationLayer.NOTIFICATIONS
    def graph_domain(self): return GraphDomain.CONTROL_PLANE
    def validate_config(self, config): return ConfigValidation(valid=True)
    def test_connection(self, config): return ConnectionResult(ok=True, message="ok")
    def capabilities(self): return DriverCapabilities(can_write=True)


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset the registry before each test."""
    DriverRegistry.reset()
    yield
    DriverRegistry.reset()


class TestRegistration:
    def test_register_and_get(self):
        DriverRegistry.register("DUMMY_DATA", DummyDataDriver)
        cls = DriverRegistry.get("DUMMY_DATA")
        assert cls is DummyDataDriver

    def test_get_case_insensitive(self):
        DriverRegistry.register("dummy_data", DummyDataDriver)
        assert DriverRegistry.get("DUMMY_DATA") is DummyDataDriver

    def test_get_unknown_returns_none(self):
        assert DriverRegistry.get("NONEXISTENT") is None

    def test_create(self):
        DriverRegistry.register("DUMMY_DATA", DummyDataDriver)
        driver = DriverRegistry.create("DUMMY_DATA")
        assert driver.id() == "dummy_data"

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown integration type"):
            DriverRegistry.create("NONEXISTENT")


class TestFiltering:
    def test_list_supported(self):
        DriverRegistry.register("DUMMY_DATA", DummyDataDriver)
        DriverRegistry.register("DUMMY_CTRL", DummyControlDriver)
        supported = DriverRegistry.list_supported()
        assert "DUMMY_CTRL" in supported
        assert "DUMMY_DATA" in supported

    def test_list_data_plane(self):
        DriverRegistry.register("DUMMY_DATA", DummyDataDriver)
        DriverRegistry.register("DUMMY_CTRL", DummyControlDriver)
        dp = DriverRegistry.list_data_plane()
        assert "DUMMY_DATA" in dp
        assert "DUMMY_CTRL" not in dp

    def test_list_control_plane(self):
        DriverRegistry.register("DUMMY_DATA", DummyDataDriver)
        DriverRegistry.register("DUMMY_CTRL", DummyControlDriver)
        cp = DriverRegistry.list_control_plane()
        assert "DUMMY_CTRL" in cp
        assert "DUMMY_DATA" not in cp

    def test_for_layer(self):
        DriverRegistry.register("DUMMY_DATA", DummyDataDriver)
        DriverRegistry.register("DUMMY_CTRL", DummyControlDriver)
        wh = DriverRegistry.for_layer(IntegrationLayer.WAREHOUSE)
        assert "DUMMY_DATA" in wh
        notif = DriverRegistry.for_layer(IntegrationLayer.NOTIFICATIONS)
        assert "DUMMY_CTRL" in notif


class TestSupportMatrix:
    def test_get_support_matrix(self):
        DriverRegistry.register("DUMMY_DATA", DummyDataDriver)
        DriverRegistry.register("DUMMY_CTRL", DummyControlDriver)
        matrix = DriverRegistry.get_support_matrix()
        assert len(matrix) == 2
        data_row = next(r for r in matrix if r["id"] == "dummy_data")
        assert data_row["graph_domain"] == "DATA_PLANE"
        ctrl_row = next(r for r in matrix if r["id"] == "dummy_ctrl")
        assert ctrl_row["graph_domain"] == "CONTROL_PLANE"
        assert ctrl_row["can_write"] is True
