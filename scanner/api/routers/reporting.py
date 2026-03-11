"""
Reporting Metadata Router - Fetch live metadata from BI/reporting tools
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class ReportingConfig(BaseModel):
    """Reporting tool connection configuration."""
    tool_type: str  # looker, tableau, powerbi, metabase
    connection_config: Dict[str, Any]


def _get_looker_metadata(config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch metadata from Looker."""
    try:
        from integrations.looker import LookerClient
    except ImportError:
        from scanner.integrations.looker import LookerClient

    client = LookerClient(
        host=config.get("host", config.get("base_url", "")),
        client_id=config.get("client_id", ""),
        client_secret=config.get("client_secret", ""),
        port=config.get("port", 19999),
        verify_ssl=config.get("verify_ssl", True),
    )

    dashboards_raw = client.get_all_dashboards()
    models_raw = client.get_all_models()

    dashboards = [
        {
            "id": d.get("id"),
            "name": d.get("title", d.get("id")),
            "type": "dashboard",
            "view_count": d.get("view_count", 0),
            "favorite_count": d.get("favorite_count", 0),
            "last_accessed_at": d.get("last_accessed_at"),
            "folder": d.get("folder", {}).get("name") if isinstance(d.get("folder"), dict) else None,
        }
        for d in dashboards_raw
    ]

    datasources = [
        {
            "id": m.get("name"),
            "name": m.get("label", m.get("name")),
            "type": "model",
            "explores": [e.get("name") for e in m.get("explores", [])],
            "project": m.get("project_name"),
            "has_content": m.get("has_content"),
        }
        for m in models_raw
    ]

    return {"dashboards": dashboards, "datasources": datasources}


def _get_tableau_metadata(config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch metadata from Tableau."""
    try:
        from integrations.tableau import TableauClient
    except ImportError:
        from scanner.integrations.tableau import TableauClient

    client = TableauClient(
        server=config.get("server", config.get("server_url", "")),
        token_name=config.get("token_name", ""),
        token_secret=config.get("token_secret", config.get("token_value", "")),
        site_id=config.get("site_id", ""),
    )

    workbooks_raw = client.get_all_workbooks()
    datasources_raw = client.get_all_datasources()

    dashboards = [
        {
            "id": w.get("id"),
            "name": w.get("name"),
            "type": "workbook",
            "project": w.get("project", {}).get("name") if isinstance(w.get("project"), dict) else w.get("project"),
            "owner": w.get("owner", {}).get("name") if isinstance(w.get("owner"), dict) else w.get("owner"),
            "created_at": w.get("createdAt"),
            "updated_at": w.get("updatedAt"),
        }
        for w in workbooks_raw
    ]

    datasources = [
        {
            "id": ds.get("id"),
            "name": ds.get("name"),
            "type": ds.get("type", "datasource"),
            "project": ds.get("project", {}).get("name") if isinstance(ds.get("project"), dict) else ds.get("project"),
            "has_extracts": ds.get("hasExtracts"),
            "updated_at": ds.get("updatedAt"),
        }
        for ds in datasources_raw
    ]

    return {"dashboards": dashboards, "datasources": datasources}


def _get_powerbi_metadata(config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch metadata from Power BI."""
    try:
        from integrations.powerbi import PowerBIClient
    except ImportError:
        from scanner.integrations.powerbi import PowerBIClient

    client = PowerBIClient(
        tenant_id=config.get("tenant_id", ""),
        client_id=config.get("client_id", ""),
        client_secret=config.get("client_secret", ""),
        use_admin_api=config.get("use_admin_api", True),
    )

    workspaces = client.get_workspaces()

    dashboards: List[Dict[str, Any]] = []
    datasources: List[Dict[str, Any]] = []

    for ws in workspaces:
        ws_id = ws.get("id")
        ws_name = ws.get("name")

        reports = client.get_reports_in_workspace(ws_id)
        for r in reports:
            dashboards.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "type": "report",
                "workspace": ws_name,
                "web_url": r.get("webUrl"),
            })

        datasets = client.get_datasets_in_workspace(ws_id)
        for ds in datasets:
            datasources.append({
                "id": ds.get("id"),
                "name": ds.get("name"),
                "type": "dataset",
                "workspace": ws_name,
                "is_refreshable": ds.get("isRefreshable"),
                "configured_by": ds.get("configuredBy"),
            })

    return {"dashboards": dashboards, "datasources": datasources}


def _get_metabase_metadata(config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch metadata from Metabase."""
    try:
        from integrations.metabase import MetabaseClient
    except ImportError:
        from scanner.integrations.metabase import MetabaseClient

    client = MetabaseClient(
        host=config.get("host", ""),
        username=config.get("username"),
        password=config.get("password"),
        api_key=config.get("api_key"),
    )

    dashboards_raw = client.get_dashboards()
    cards_raw = client.get_cards()

    dashboards = [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "type": "dashboard",
            "collection": d.get("collection", {}).get("name") if isinstance(d.get("collection"), dict) else d.get("collection"),
            "creator": d.get("creator", {}).get("common_name") if isinstance(d.get("creator"), dict) else None,
        }
        for d in dashboards_raw
    ]

    datasources = [
        {
            "id": c.get("id"),
            "name": c.get("name"),
            "type": c.get("query_type", "card"),
            "display": c.get("display"),
            "database_id": c.get("database_id"),
            "collection": c.get("collection", {}).get("name") if isinstance(c.get("collection"), dict) else c.get("collection"),
            "archived": c.get("archived", False),
        }
        for c in cards_raw
        if not c.get("archived", False)
    ]

    return {"dashboards": dashboards, "datasources": datasources}


_FETCHERS = {
    "looker": _get_looker_metadata,
    "tableau": _get_tableau_metadata,
    "powerbi": _get_powerbi_metadata,
    "metabase": _get_metabase_metadata,
}


@router.post("/reporting/metadata")
async def get_reporting_metadata(config: ReportingConfig) -> Dict[str, Any]:
    """
    Fetch live metadata from a reporting/BI tool.

    Supports: Looker, Tableau, Power BI, Metabase
    """
    tool_type = config.tool_type.lower()
    logger.info(f"Fetching reporting metadata for {tool_type}")

    fetcher = _FETCHERS.get(tool_type)
    if not fetcher:
        return {
            "success": False,
            "error": f"Unsupported reporting tool: {tool_type}. Supported: {list(_FETCHERS.keys())}",
            "dashboards": [],
            "datasources": [],
            "tool_type": tool_type,
        }

    try:
        result = fetcher(config.connection_config)
        return {
            "success": True,
            "dashboards": result.get("dashboards", []),
            "datasources": result.get("datasources", []),
            "tool_type": tool_type,
        }
    except Exception as e:
        logger.error(f"Reporting metadata fetch failed for {tool_type}: {e}")
        return {
            "success": False,
            "error": str(e),
            "dashboards": [],
            "datasources": [],
            "tool_type": tool_type,
        }
