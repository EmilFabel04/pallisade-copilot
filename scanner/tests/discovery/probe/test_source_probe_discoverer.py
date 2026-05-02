"""
Tests for SourceProbeDiscoverer (Path 1 — HTTP probe).

Covers:
1. Top-level JSON array → 1 candidate with endpoint, timestamp_column, confidence.
2. Nested array under data.items → 1 candidate with json_root.
3. HTTP 401 → (candidates == [], error.code == 'auth_failed').
4. HTML response (non-JSON) → (candidates == [], error.code == 'malformed_json').
"""

from __future__ import annotations

import responses as responses_lib

from scanner.discovery.probe.source_probe_discoverer import SourceProbeDiscoverer


BASE_URL = "https://api.example.com"
AUTH = {"kind": "bearer", "secret": "test-token"}


@responses_lib.activate
def test_top_level_array_yields_one_candidate():
    """Top-level JSON array → 1 candidate with endpoint='/sensors', timestamp_column='reading_at', confidence=0.7."""
    responses_lib.add(
        responses_lib.GET,
        "https://api.example.com/sensors",
        json=[
            {"id": 1, "reading_at": "2026-04-30T12:00:00Z", "value": 10.0},
            {"id": 2, "reading_at": "2026-04-30T13:00:00Z", "value": 20.0},
        ],
        status=200,
    )

    discoverer = SourceProbeDiscoverer()
    candidates, error = discoverer.discover(
        base_url=BASE_URL,
        endpoint="/sensors",
        auth=AUTH,
    )

    assert error is None
    assert len(candidates) == 1
    c = candidates[0]
    assert c.endpoint == "/sensors"
    assert c.timestamp_column == "reading_at"
    assert c.confidence == 0.7
    assert c.source == "probe"


@responses_lib.activate
def test_nested_array_uses_json_root():
    """Nested array under data.items → 1 candidate with json_root == 'data.items'."""
    responses_lib.add(
        responses_lib.GET,
        "https://api.example.com/readings",
        json={
            "meta": {"total": 2},
            "data": {
                "items": [
                    {"id": 1, "created_at": "2026-04-30T12:00:00Z"},
                    {"id": 2, "created_at": "2026-04-30T13:00:00Z"},
                ]
            },
        },
        status=200,
    )

    discoverer = SourceProbeDiscoverer()
    candidates, error = discoverer.discover(
        base_url=BASE_URL,
        endpoint="/readings",
        auth={"kind": "api_key", "secret": "key-abc"},
    )

    assert error is None
    assert len(candidates) == 1
    c = candidates[0]
    assert c.json_root == "data.items"


@responses_lib.activate
def test_http_401_yields_auth_failed_error():
    """HTTP 401 → candidates == [], error.code == 'auth_failed'."""
    responses_lib.add(
        responses_lib.GET,
        "https://api.example.com/sensors",
        json={"error": "unauthorized"},
        status=401,
    )

    discoverer = SourceProbeDiscoverer()
    candidates, error = discoverer.discover(
        base_url=BASE_URL,
        endpoint="/sensors",
        auth=AUTH,
    )

    assert candidates == []
    assert error is not None
    assert error.code == "auth_failed"


@responses_lib.activate
def test_html_response_yields_malformed_json_error():
    """HTML response (non-JSON) → candidates == [], error.code == 'malformed_json'."""
    responses_lib.add(
        responses_lib.GET,
        "https://api.example.com/sensors",
        body="<html><body>Not JSON</body></html>",
        content_type="text/html",
        status=200,
    )

    discoverer = SourceProbeDiscoverer()
    candidates, error = discoverer.discover(
        base_url=BASE_URL,
        endpoint="/sensors",
        auth=AUTH,
    )

    assert candidates == []
    assert error is not None
    assert error.code == "malformed_json"
