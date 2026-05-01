from scanner.drivers.source.custom_source_driver import CustomSourceDriver
from scanner.drivers.base import GraphDomain, IntegrationLayer


def test_driver_identity():
    d = CustomSourceDriver()
    assert d.id() == "custom_source"
    assert d.integration_type() == "CUSTOM_SOURCE"
    assert d.layer() == IntegrationLayer.SOURCE
    assert d.graph_domain() == GraphDomain.DATA_PLANE


def test_validate_config_requires_base_url_and_auth_and_datasets():
    d = CustomSourceDriver()
    res = d.validate_config({})
    assert not res.valid
    assert any("base_url" in e for e in res.errors)
    assert any("auth.kind" in e for e in res.errors)
    assert any("datasets" in e for e in res.errors)


def test_validate_config_requires_https():
    d = CustomSourceDriver()
    res = d.validate_config({
        "name": "x",
        "base_url": "http://insecure.example.com",
        "auth": {"kind": "bearer", "secret_ref": "s"},
        "datasets": [{"id": "d", "endpoint": "/r", "timestamp_column": "t"}],
    })
    assert not res.valid
    assert any("https" in e.lower() for e in res.errors)


def test_validate_config_passes_minimal_valid_input():
    d = CustomSourceDriver()
    res = d.validate_config({
        "name": "MyCiti",
        "base_url": "https://portal.example.com/api/v1",
        "auth": {"kind": "bearer", "secret_ref": "secret-id"},
        "datasets": [{
            "id": "water",
            "endpoint": "/readings",
            "timestamp_column": "reading_at",
        }],
    })
    assert res.valid


import responses
from scanner.drivers.source.custom_source_driver import CustomSourceDriver


@responses.activate
def test_test_connection_ok_when_first_dataset_responds():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[{"id": 1}], status=200,
    )
    d = CustomSourceDriver()
    config = {
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret": "t"},
        "datasets": [{"id": "x", "endpoint": "/readings", "timestamp_column": "id"}],
    }
    result = d.test_connection(config)
    assert result.ok is True


@responses.activate
def test_test_connection_fails_on_401():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        status=401,
    )
    d = CustomSourceDriver()
    config = {
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret": "bad"},
        "datasets": [{"id": "x", "endpoint": "/readings", "timestamp_column": "id"}],
    }
    result = d.test_connection(config)
    assert result.ok is False
    assert "auth" in result.message.lower() or "401" in result.message


def test_extract_metadata_returns_one_summary_per_dataset():
    d = CustomSourceDriver()
    config = {
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret": "t"},
        "datasets": [
            {"id": "water", "endpoint": "/water", "timestamp_column": "t"},
            {"id": "air", "endpoint": "/air", "timestamp_column": "t"},
        ],
    }
    summaries = d.extract_metadata(config)
    assert len(summaries) == 2
    assert any(s.asset_type == "dataset" and "water" in s.sample_names for s in summaries)


def test_extract_lineage_emits_one_node_per_dataset_no_edges_without_lands_in():
    d = CustomSourceDriver()
    config = {
        "platform_label": "MyCiti",
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret_ref": "s"},
        "datasets": [
            {"id": "water", "endpoint": "/w", "timestamp_column": "t"},
        ],
    }
    nodes, edges = d.extract_lineage(config)
    assert len(nodes) == 1
    assert nodes[0].name == "water"
    assert edges == []


def test_extract_lineage_emits_edge_when_lands_in_set():
    d = CustomSourceDriver()
    config = {
        "platform_label": "MyCiti",
        "base_url": "https://api.example.com/v1",
        "auth": {"kind": "bearer", "secret_ref": "s"},
        "datasets": [{
            "id": "water",
            "endpoint": "/w",
            "timestamp_column": "t",
            "lands_in": "snowflake.raw.water_meters",
        }],
    }
    nodes, edges = d.extract_lineage(config)
    assert len(nodes) == 1
    assert len(edges) == 1


def test_driver_registered_in_loader():
    """CustomSourceDriver is discoverable via the integration_type registry."""
    from scanner.drivers.loader import register_all_drivers, reset_loaded_flag
    from scanner.drivers.registry import DriverRegistry

    # Ensure registry is populated (idempotent — register_all_drivers
    # short-circuits if already loaded; reset_loaded_flag forces a fresh
    # registration in case a prior test reset the registry).
    reset_loaded_flag()
    DriverRegistry.reset()
    register_all_drivers()

    driver_cls = DriverRegistry.get("CUSTOM_SOURCE")
    assert driver_cls is not None
    driver = driver_cls()
    assert driver.__class__.__name__ == "CustomSourceDriver"
    assert driver.integration_type() == "CUSTOM_SOURCE"
