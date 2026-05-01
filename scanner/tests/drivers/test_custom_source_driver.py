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
