"""
Test that ALL registered drivers have correct graph domain behavior.

This test loads the full registry and verifies:
1. Every CONTROL_PLANE driver returns empty lineage
2. Every DATA_PLANE driver's graph_domain is correct
3. The full registry loads without errors
"""

import pytest
from scanner.drivers.loader import register_all_drivers, reset_loaded_flag
from scanner.drivers.registry import DriverRegistry
from scanner.drivers.base import GraphDomain


@pytest.fixture(autouse=True)
def load_all():
    """Ensure all drivers are registered."""
    DriverRegistry.reset()
    reset_loaded_flag()
    register_all_drivers()
    yield
    DriverRegistry.reset()
    reset_loaded_flag()


class TestAllDriversLoaded:
    def test_minimum_driver_count(self):
        """We expect at least 42 drivers."""
        supported = DriverRegistry.list_supported()
        assert len(supported) >= 42, f"Only {len(supported)} drivers loaded: {supported}"

    def test_data_plane_count(self):
        dp = DriverRegistry.list_data_plane()
        assert len(dp) >= 29, f"Only {len(dp)} DATA_PLANE drivers"

    def test_control_plane_count(self):
        cp = DriverRegistry.list_control_plane()
        assert len(cp) >= 13, f"Only {len(cp)} CONTROL_PLANE drivers"


class TestControlPlaneEnforcement:
    """Every CONTROL_PLANE driver MUST return empty lineage."""

    def test_all_control_plane_return_empty_lineage(self):
        for key in DriverRegistry.list_control_plane():
            driver = DriverRegistry.create(key)
            nodes, edges = driver.extract_lineage({})
            assert nodes == [], f"{key} CONTROL_PLANE driver returned non-empty nodes"
            assert edges == [], f"{key} CONTROL_PLANE driver returned non-empty edges"


class TestDataPlaneDriverMetadata:
    """DATA_PLANE drivers must have correct metadata."""

    def test_all_data_plane_have_capabilities(self):
        for key in DriverRegistry.list_data_plane():
            driver = DriverRegistry.create(key)
            caps = driver.capabilities()
            assert caps is not None, f"{key} returned None capabilities"

    def test_all_drivers_have_identity(self):
        for key in DriverRegistry.list_supported():
            driver = DriverRegistry.create(key)
            assert driver.id(), f"{key} has empty id()"
            assert driver.integration_type(), f"{key} has empty integration_type()"
            assert driver.layer() is not None, f"{key} has None layer()"
            assert driver.graph_domain() is not None, f"{key} has None graph_domain()"


class TestKnownDriverDomains:
    """Verify specific domain assignments are correct."""

    @pytest.mark.parametrize("key", [
        "BIGQUERY", "SNOWFLAKE", "POSTGRES", "REDSHIFT", "DATABRICKS",
        "FIVETRAN", "AIRBYTE", "DBT_CLOUD", "DBT_CORE", "AIRFLOW",
        "LOOKER", "TABLEAU", "METABASE", "POWERBI",
        "MONTE_CARLO", "BIGEYE", "SODA", "ELEMENTARY",
        "AMAZON_S3", "GCS", "ADLS",
    ])
    def test_data_plane_tools(self, key):
        driver = DriverRegistry.create(key)
        assert driver.graph_domain() == GraphDomain.DATA_PLANE, f"{key} should be DATA_PLANE"

    @pytest.mark.parametrize("key", [
        "GITHUB", "GITHUB_ISSUES", "GITLAB", "BITBUCKET",
        "SLACK", "TEAMS", "PAGERDUTY", "OPSGENIE",
        "JIRA", "LINEAR", "ASANA",
        "LINUX_SERVER", "CUSTOM_WEBHOOK",
    ])
    def test_control_plane_tools(self, key):
        driver = DriverRegistry.create(key)
        assert driver.graph_domain() == GraphDomain.CONTROL_PLANE, f"{key} should be CONTROL_PLANE"
