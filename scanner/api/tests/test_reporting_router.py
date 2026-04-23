"""
Tests for the reporting metadata router.

Covers:
1. Each tool_type returns normalized data (dashboards + datasources)
2. Unsupported tool_type returns error with valid shape
3. Client connection failure returns success=False with error message
"""

import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _create_test_client():
    """Create a FastAPI test client with just the reporting router."""
    from fastapi import FastAPI
    from scanner.api.routers.reporting import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


PATCH_TARGET = "scanner.api.routers.reporting._FETCHERS"


# ======================================================================
# Looker Tests
# ======================================================================


class TestLookerMetadata:

    def test_looker_returns_dashboards_and_datasources(self):
        def mock_looker(config):
            return {
                "dashboards": [
                    {"id": "1", "name": "Revenue", "type": "dashboard", "view_count": 42},
                ],
                "datasources": [
                    {"id": "model1", "name": "Finance Model", "type": "model"},
                ],
            }

        with patch(PATCH_TARGET, {"looker": mock_looker, "tableau": MagicMock(), "powerbi": MagicMock(), "metabase": MagicMock()}):
            client = _create_test_client()
            resp = client.post("/api/v1/reporting/metadata", json={
                "tool_type": "looker",
                "connection_config": {"host": "x", "client_id": "y", "client_secret": "z"},
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["tool_type"] == "looker"
        assert len(data["dashboards"]) == 1
        assert len(data["datasources"]) == 1


# ======================================================================
# Tableau Tests
# ======================================================================


class TestTableauMetadata:

    def test_tableau_returns_workbooks_and_datasources(self):
        def mock_tableau(config):
            return {
                "dashboards": [
                    {"id": "wb-001", "name": "Revenue Dashboard", "type": "workbook"},
                ],
                "datasources": [
                    {"id": "ds-001", "name": "Sales Data", "type": "snowflake"},
                ],
            }

        with patch(PATCH_TARGET, {"looker": MagicMock(), "tableau": mock_tableau, "powerbi": MagicMock(), "metabase": MagicMock()}):
            client = _create_test_client()
            resp = client.post("/api/v1/reporting/metadata", json={
                "tool_type": "tableau",
                "connection_config": {"server": "x", "token_name": "y", "token_secret": "z"},
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["tool_type"] == "tableau"
        assert len(data["dashboards"]) == 1


# ======================================================================
# Power BI Tests
# ======================================================================


class TestPowerBIMetadata:

    def test_powerbi_returns_reports_and_datasets(self):
        def mock_powerbi(config):
            return {
                "dashboards": [
                    {"id": "r-001", "name": "Sales Report", "type": "report", "workspace": "Finance"},
                ],
                "datasources": [
                    {"id": "ds-001", "name": "Sales Dataset", "type": "dataset", "workspace": "Finance"},
                ],
            }

        with patch(PATCH_TARGET, {"looker": MagicMock(), "tableau": MagicMock(), "powerbi": mock_powerbi, "metabase": MagicMock()}):
            client = _create_test_client()
            resp = client.post("/api/v1/reporting/metadata", json={
                "tool_type": "powerbi",
                "connection_config": {"tenant_id": "x", "client_id": "y", "client_secret": "z"},
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["dashboards"]) == 1
        assert len(data["datasources"]) == 1


# ======================================================================
# Metabase Tests
# ======================================================================


class TestMetabaseMetadata:

    def test_metabase_returns_dashboards_and_cards(self):
        def mock_metabase(config):
            return {
                "dashboards": [
                    {"id": 1, "name": "KPI Dashboard", "type": "dashboard"},
                ],
                "datasources": [
                    {"id": 10, "name": "Revenue Card", "type": "query", "display": "bar"},
                ],
            }

        with patch(PATCH_TARGET, {"looker": MagicMock(), "tableau": MagicMock(), "powerbi": MagicMock(), "metabase": mock_metabase}):
            client = _create_test_client()
            resp = client.post("/api/v1/reporting/metadata", json={
                "tool_type": "metabase",
                "connection_config": {"host": "x", "username": "y", "password": "z"},
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["tool_type"] == "metabase"
        assert len(data["dashboards"]) == 1


# ======================================================================
# Error Cases
# ======================================================================


class TestErrorCases:

    def test_unsupported_tool_type(self):
        client = _create_test_client()
        resp = client.post("/api/v1/reporting/metadata", json={
            "tool_type": "unknown_tool",
            "connection_config": {},
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "unsupported" in data["error"].lower()
        assert data["dashboards"] == []
        assert data["datasources"] == []

    def test_connection_failure_returns_error(self):
        def boom(config):
            raise Exception("Connection refused")

        with patch(PATCH_TARGET, {"looker": boom, "tableau": MagicMock(), "powerbi": MagicMock(), "metabase": MagicMock()}):
            client = _create_test_client()
            resp = client.post("/api/v1/reporting/metadata", json={
                "tool_type": "looker",
                "connection_config": {"host": "bad", "client_id": "y", "client_secret": "z"},
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Connection refused" in data["error"]
        assert data["dashboards"] == []

    def test_empty_config_returns_valid_shape(self):
        """Even with bad config, response shape is stable."""
        client = _create_test_client()
        resp = client.post("/api/v1/reporting/metadata", json={
            "tool_type": "unknown",
            "connection_config": {},
        })

        data = resp.json()
        assert "dashboards" in data
        assert "datasources" in data
        assert "success" in data
        assert "tool_type" in data


# ======================================================================
# Capability Declaration Tests
# ======================================================================


class TestCapabilityDeclarations:
    """Verify BI tools have correct capabilities declared (tested via import)."""

    def test_powerbi_has_lineage_capability(self):
        """Power BI lineage engine adapter declares lineage capability."""
        from scanner.lineage.engine.adapters.live_powerbi import LivePowerBIAdapter
        from scanner.lineage.engine.adapter import Capability

        adapter = LivePowerBIAdapter()
        caps = adapter.capabilities()
        assert Capability.EXTRACT_TABLE_LINEAGE in caps

    def test_metabase_has_lineage_capability(self):
        """Metabase lineage engine adapter declares lineage capability."""
        from scanner.lineage.engine.adapters.live_metabase import LiveMetabaseAdapter
        from scanner.lineage.engine.adapter import Capability

        adapter = LiveMetabaseAdapter()
        caps = adapter.capabilities()
        assert Capability.EXTRACT_TABLE_LINEAGE in caps
