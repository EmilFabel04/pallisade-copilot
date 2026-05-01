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
