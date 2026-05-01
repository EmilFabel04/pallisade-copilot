from datetime import datetime, timezone

import responses

from scanner.adapters.http_probe import HttpProbeAdapter, MetricBundle


def test_metric_bundle_holds_only_derived_metrics():
    """Sanity: MetricBundle never holds row data."""
    bundle = MetricBundle(
        probed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        row_count=42,
        latest_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
        column_schema=[{"name": "id", "data_type": "int", "is_nullable": False}],
        null_counts={"id": 0},
        distinct_counts={"id": 42},
        value_fingerprints={"id": b"\x00" * 8},
        min_max_numeric={"id": (1.0, 42.0)},
    )
    assert bundle.row_count == 42
    assert "rows" not in bundle.__dict__
    assert "data" not in bundle.__dict__


@responses.activate
def test_probe_with_bearer_auth_computes_metrics():
    """A successful bearer-auth probe returns a MetricBundle."""
    responses.add(
        responses.GET,
        "https://api.example.com/v1/readings",
        json=[
            {"id": 1, "sensor": "A", "reading_at": "2026-04-30T12:00:00Z", "value": 10.0},
            {"id": 2, "sensor": "B", "reading_at": "2026-04-30T13:00:00Z", "value": 20.0},
            {"id": 3, "sensor": None, "reading_at": "2026-04-30T14:00:00Z", "value": 30.0},
        ],
        status=200,
    )

    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "test-token"},
    )
    bundle = adapter.probe({
        "endpoint": "/readings",
        "timestamp_column": "reading_at",
    })

    assert bundle.row_count == 3
    assert bundle.null_counts["sensor"] == 1
    assert bundle.null_counts["id"] == 0
    assert bundle.column_schema  # non-empty
    assert bundle.latest_timestamp is not None
    # Authorization header was sent
    sent_auth = responses.calls[0].request.headers.get("Authorization")
    assert sent_auth == "Bearer test-token"


@responses.activate
def test_probe_with_api_key_uses_default_header():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[{"id": 1}], status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "api_key", "secret": "abc123"},
    )
    adapter.probe({"endpoint": "/readings"})
    assert responses.calls[0].request.headers.get("X-API-Key") == "abc123"


@responses.activate
def test_probe_with_api_key_custom_header_name():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[{"id": 1}], status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "api_key", "secret": "abc", "header_name": "X-Auth"},
    )
    adapter.probe({"endpoint": "/readings"})
    assert responses.calls[0].request.headers.get("X-Auth") == "abc"


@responses.activate
def test_probe_with_basic_auth_sends_authorization_header():
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        json=[{"id": 1}], status=200,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "basic", "username": "user", "secret": "pw"},
    )
    adapter.probe({"endpoint": "/readings"})
    auth_header = responses.calls[0].request.headers.get("Authorization", "")
    assert auth_header.startswith("Basic ")


@responses.activate
def test_probe_raises_auth_failed_on_401():
    from scanner.adapters.http_probe import ProbeError
    responses.add(
        responses.GET, "https://api.example.com/v1/readings",
        status=401,
    )
    adapter = HttpProbeAdapter(
        base_url="https://api.example.com/v1",
        auth={"kind": "bearer", "secret": "bad"},
    )
    import pytest
    with pytest.raises(ProbeError) as exc:
        adapter.probe({"endpoint": "/readings"})
    assert exc.value.code == "auth_failed"
