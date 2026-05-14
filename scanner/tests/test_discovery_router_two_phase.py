from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _ensure_scanner_api_routers_discovery():
    """Import scanner.api.routers.discovery without triggering the scanner.api
    package __init__, which eagerly calls create_app() and requires the full
    copilot/scheduler dependency tree.

    Strategy: pre-populate sys.modules with stub entries for scanner.api and
    scanner.api.routers so that `from ..auth import ...` inside discovery.py
    resolves to a real scanner.api.auth (loaded standalone), not via __init__.
    """
    if "scanner.api.routers.discovery" in sys.modules:
        return sys.modules["scanner.api.routers.discovery"]

    # --- stub scanner.api (just a namespace — avoids running __init__.py) ---
    if "scanner.api" not in sys.modules:
        api_stub = types.ModuleType("scanner.api")
        api_stub.__path__ = []  # mark it as a package
        sys.modules["scanner.api"] = api_stub

    # --- load scanner.api.auth directly (no side effects) ---
    if "scanner.api.auth" not in sys.modules:
        import importlib.util, os
        auth_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scanner", "api", "auth.py",
        )
        spec = importlib.util.spec_from_file_location("scanner.api.auth", auth_path)
        auth_mod = importlib.util.module_from_spec(spec)
        sys.modules["scanner.api.auth"] = auth_mod
        spec.loader.exec_module(auth_mod)
        # Attach to the stub package so relative imports resolve
        sys.modules["scanner.api"].auth = auth_mod

    # --- stub scanner.api.routers (package namespace) ---
    if "scanner.api.routers" not in sys.modules:
        routers_stub = types.ModuleType("scanner.api.routers")
        routers_stub.__path__ = []
        sys.modules["scanner.api.routers"] = routers_stub
        sys.modules["scanner.api"].routers = routers_stub

    # --- load _lineage_cache (imported by discovery.py from . import _lineage_cache) ---
    if "scanner.api.routers._lineage_cache" not in sys.modules:
        import importlib.util, os
        cache_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scanner", "api", "routers", "_lineage_cache.py",
        )
        spec = importlib.util.spec_from_file_location("scanner.api.routers._lineage_cache", cache_path)
        cache_mod = importlib.util.module_from_spec(spec)
        sys.modules["scanner.api.routers._lineage_cache"] = cache_mod
        spec.loader.exec_module(cache_mod)

    # --- now load discovery.py itself ---
    import importlib.util, os
    discovery_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scanner", "api", "routers", "discovery.py",
    )
    spec = importlib.util.spec_from_file_location("scanner.api.routers.discovery", discovery_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["scanner.api.routers.discovery"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client():
    """Build a minimal TestClient with only the discovery router mounted.

    Avoids importing the full app (which requires copilot/scheduler deps).
    Pre-stubs scanner.api in sys.modules so the relative auth import inside
    discovery.py does not trigger the package __init__ create_app() call.
    """
    from fastapi import FastAPI

    discovery_mod = _ensure_scanner_api_routers_discovery()
    app = FastAPI()
    app.include_router(discovery_mod.router, prefix="/api/v1")
    return TestClient(app)


def test_analyze_route_returns_ready_for_confident_pick(client, monkeypatch):
    from scanner.api.routers import discovery as router_mod
    from scanner.lineage.sla_analysis import AnalysisPlan, AnalyzeResult

    plan = AnalysisPlan(
        table_fqn="proj.ds.t",
        warehouse_ancestor_fqn=None,
        volume_timestamp_pick={"column": "loaded_at", "confidence": 0.9},
        volume_timestamp_candidates=[],
        schema_snapshot={"columns": []},
        row_count=100,
        unsupported=False,
        skipped_reason=None,
    )

    stub_adapter = MagicMock()

    def fake_create(_platform, _credentials):
        return stub_adapter

    monkeypatch.setattr(router_mod, "_create_warehouse_adapter", fake_create)

    # Patch the lazy import target inside the route body:
    monkeypatch.setattr(
        "scanner.lineage.sla_analysis.analyze_sla",
        lambda **kw: AnalyzeResult("proj.ds.t", plan, "ready", []),
    )

    r = client.post(
        "/api/v1/discovery/analyze",
        json={
            "platform": "bigquery",
            "tableFqn": "proj.ds.t",
            "credentials": {"project_id": "x"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["clarification_ids"] == []
    assert body["plan"]["table_fqn"] == "proj.ds.t"


def test_compute_route_rejects_mismatched_plan(client, monkeypatch):
    from scanner.api.routers import discovery as router_mod

    stub_adapter = MagicMock()
    monkeypatch.setattr(router_mod, "_create_warehouse_adapter", lambda p, c: stub_adapter)

    body = {
        "platform": "bigquery",
        "tableFqn": "proj.ds.t",
        "credentials": {"project_id": "x"},
        "plan": {
            "table_fqn": "proj.ds.OTHER",
            "warehouse_ancestor_fqn": None,
            "volume_timestamp_pick": None,
            "volume_timestamp_candidates": [],
            "schema_snapshot": {"columns": []},
            "row_count": None,
            "unsupported": False,
            "skipped_reason": None,
        },
        "answers": {},
    }
    r = client.post("/api/v1/discovery/compute", json=body)
    assert r.status_code == 400, r.text
    assert "does not match" in r.json().get("detail", "")


def test_analyze_bulk_route(client, monkeypatch):
    from scanner.api.routers import discovery as router_mod
    from scanner.lineage.sla_analysis import AnalysisPlan, AnalyzeResult

    stub_adapter = MagicMock()
    monkeypatch.setattr(router_mod, "_create_warehouse_adapter", lambda p, c: stub_adapter)

    def fake_analyze(*, table_fqn, **kw):
        plan = AnalysisPlan(
            table_fqn=table_fqn,
            warehouse_ancestor_fqn=None,
            volume_timestamp_pick={"column": "loaded_at", "confidence": 0.9},
            volume_timestamp_candidates=[],
            schema_snapshot={"columns": []},
            row_count=100,
            unsupported=False,
            skipped_reason=None,
        )
        return AnalyzeResult(table_fqn, plan, "ready", [])

    monkeypatch.setattr("scanner.lineage.sla_analysis.analyze_sla", fake_analyze)

    r = client.post(
        "/api/v1/discovery/analyze-bulk",
        json={
            "platform": "bigquery",
            "tableFqns": ["proj.ds.a", "proj.ds.b"],
            "credentials": {"project_id": "x"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["results"]) == 2
    assert {item["table_fqn"] for item in body["results"]} == {"proj.ds.a", "proj.ds.b"}
