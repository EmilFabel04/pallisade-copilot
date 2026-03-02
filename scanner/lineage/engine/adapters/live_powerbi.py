"""
Live Power BI Adapter — extracts lineage from Power BI reports and datasets.

Discovers Power BI reports as REPORT nodes and datasets as DATASET nodes
on the BI domain, then creates edges from reports to datasets (TOOL level)
and from datasets to warehouse tables (TABLE level, CROSS plane) when
datasource information is available.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, normalize_identifier

logger = logging.getLogger(__name__)


class LivePowerBIAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Power BI reports and datasets,
    and extracts lineage between them and to warehouse tables.

    Config keys:
        namespace: Identifier for this Power BI tenant (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        powerbi_config: Dict with tenant_id, client_id, client_secret, workspace_id
    """

    def __init__(self, adapter_id: str = "live_powerbi", **kwargs):
        super().__init__(adapter_id, **kwargs)

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.GET_BI_EXPOSURES,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover Power BI reports and datasets."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "powerbi")
        integration_id = config.get("integration_id")
        workspace_id = config.get("powerbi_config", {}).get("workspace_id", "")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Discover reports
        try:
            reports = client.get_reports_in_workspace(workspace_id)
        except Exception as e:
            logger.error(f"[LivePowerBI] Failed to get reports: {e}")
            reports = []

        for report_data in reports:
            node = self._make_report_node(
                report_data, namespace, integration_id, now,
            )
            if node:
                nodes.append(node)

        # Discover datasets
        try:
            datasets = client.get_datasets_in_workspace(workspace_id)
        except Exception as e:
            logger.error(f"[LivePowerBI] Failed to get datasets: {e}")
            datasets = []

        for dataset_data in datasets:
            node = self._make_dataset_node(
                dataset_data, namespace, integration_id, now,
            )
            if node:
                nodes.append(node)

        logger.info(
            f"[LivePowerBI] Discovered {len(nodes)} assets "
            f"({len(reports)} reports, {len(datasets)} datasets)"
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract report->dataset and dataset->warehouse table edges."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "powerbi")
        workspace_id = config.get("powerbi_config", {}).get("workspace_id", "")
        now = datetime.utcnow()
        edges: List[LineageEdge] = []

        # Get reports for report -> dataset edges
        try:
            reports = client.get_reports_in_workspace(workspace_id)
        except Exception:
            reports = []

        # Get datasets for dataset -> warehouse table edges
        try:
            datasets = client.get_datasets_in_workspace(workspace_id)
        except Exception:
            datasets = []

        # Report -> Dataset edges (DATA plane, TOOL level, confidence 1.0)
        for report_data in reports:
            report_id = report_data.get("id", "")
            dataset_id = report_data.get("datasetId") or report_data.get("dataset_id")
            if not report_id or not dataset_id:
                continue

            report_asset_id = generate_asset_id(
                "bi", "powerbi", namespace, "", f"report_{report_id}",
            )
            dataset_asset_id = generate_asset_id(
                "bi", "powerbi", namespace, "", f"dataset_{dataset_id}",
            )

            source_ref = f"powerbi:report:{report_id}:reads_dataset:{dataset_id}"
            edge = self._make_edge(
                dataset_asset_id, report_asset_id,
                EdgeType.READS_FROM, LineageLevel.TOOL,
                confidence=1.0,
                source_ref=source_ref,
                now=now,
                plane=LinePlane.DATA,
            )
            edges.append(edge)

        # Dataset -> Warehouse table edges (CROSS plane, TABLE level, confidence 0.7)
        for dataset_data in datasets:
            ds_id = dataset_data.get("id", "")
            if not ds_id:
                continue

            dataset_asset_id = generate_asset_id(
                "bi", "powerbi", namespace, "", f"dataset_{ds_id}",
            )

            # Fetch datasource info for this dataset
            try:
                datasources = client.get_dataset_datasources(workspace_id, ds_id)
            except Exception:
                datasources = []

            for ds_source in datasources:
                table_edges = self._extract_warehouse_edges(
                    ds_source, dataset_asset_id, ds_id, namespace, now,
                )
                edges.extend(table_edges)

        logger.info(f"[LivePowerBI] Extracted {len(edges)} edges")
        return edges

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get or create a PowerBIClient."""
        if config.get("client"):
            return config["client"]

        powerbi_config = config.get("powerbi_config", {})
        if not powerbi_config.get("tenant_id"):
            logger.warning("[LivePowerBI] No powerbi_config with tenant_id provided")
            return None

        try:
            from scanner.integrations.powerbi import PowerBIClient
        except ImportError:
            from integrations.powerbi import PowerBIClient

        return PowerBIClient(
            tenant_id=powerbi_config.get("tenant_id", ""),
            client_id=powerbi_config.get("client_id", ""),
            client_secret=powerbi_config.get("client_secret", ""),
        )

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_report_node(
        self, report_data: Dict, namespace: str,
        integration_id: Optional[str], now: datetime,
    ) -> Optional[LineageNode]:
        """Create a node for a Power BI report."""
        report_id = report_data.get("id", "")
        name = report_data.get("name", "")
        if not report_id:
            return None

        workspace_name = report_data.get("workspaceName", "") or report_data.get("workspace_name", "")
        dataset_id = report_data.get("datasetId") or report_data.get("dataset_id")
        web_url = report_data.get("webUrl") or report_data.get("web_url")

        asset_id = generate_asset_id(
            "bi", "powerbi", namespace, "", f"report_{report_id}",
        )

        return LineageNode(
            id=asset_id,
            name=name or f"Report {report_id}",
            fqn=f"powerbi.{namespace}.report.{report_id}",
            node_type=NodeType.REPORT,
            platform="powerbi",
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.REPORT,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "workspace_name": workspace_name,
                "dataset_id": dataset_id,
                "web_url": web_url,
            },
        )

    def _make_dataset_node(
        self, dataset_data: Dict, namespace: str,
        integration_id: Optional[str], now: datetime,
    ) -> Optional[LineageNode]:
        """Create a node for a Power BI dataset."""
        dataset_id = dataset_data.get("id", "")
        name = dataset_data.get("name", "")
        if not dataset_id:
            return None

        workspace_name = dataset_data.get("workspaceName", "") or dataset_data.get("workspace_name", "")
        storage_mode = dataset_data.get("targetStorageMode") or dataset_data.get("target_storage_mode", "")
        refresh_status = dataset_data.get("lastRefreshStatus") or dataset_data.get("last_refresh_status", "")
        configured_by = dataset_data.get("configuredBy") or dataset_data.get("configured_by")

        # Normalize refresh_status to string if it's an enum
        if hasattr(refresh_status, "value"):
            refresh_status = refresh_status.value

        asset_id = generate_asset_id(
            "bi", "powerbi", namespace, "", f"dataset_{dataset_id}",
        )

        return LineageNode(
            id=asset_id,
            name=name or f"Dataset {dataset_id}",
            fqn=f"powerbi.{namespace}.dataset.{dataset_id}",
            node_type=NodeType.DATASET,
            platform="powerbi",
            platform_domain=PlatformDomain.BI,
            asset_kind=AssetKind.DATASET,
            namespace=namespace,
            owner=configured_by,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "workspace_name": workspace_name,
                "storage_mode": storage_mode,
                "refresh_status": refresh_status,
                "configured_by": configured_by,
            },
        )

    # ------------------------------------------------------------------
    # Warehouse edge extraction
    # ------------------------------------------------------------------

    def _extract_warehouse_edges(
        self, datasource: Dict, dataset_asset_id: str,
        dataset_id: str, namespace: str, now: datetime,
    ) -> List[LineageEdge]:
        """
        Extract dataset -> warehouse table edges from datasource metadata.

        Power BI datasources contain connection details that may reference
        specific database tables (server, database, table path).
        """
        edges: List[LineageEdge] = []
        hint = self.case_hint

        conn_details = datasource.get("connectionDetails", {})
        if not conn_details:
            return edges

        server = conn_details.get("server", "")
        database = conn_details.get("database", "")
        path = conn_details.get("path", "")

        # Try to extract table reference from connection details
        # Power BI datasources may have server + database, or a path
        table_ref = self._parse_table_ref(server, database, path)
        if not table_ref:
            return edges

        db = normalize_identifier(table_ref.get("database", ""), hint)
        schema = normalize_identifier(table_ref.get("schema", ""), hint)
        table_name = normalize_identifier(table_ref.get("table", ""), hint)

        if not table_name:
            return edges

        container = f"{db}.{schema}"

        table_asset_id = generate_asset_id(
            "warehouse", "powerbi", namespace, container, table_name,
        )

        source_ref = f"powerbi:dataset:{dataset_id}:reads:{db}.{schema}.{table_name}"
        edge = self._make_edge(
            table_asset_id, dataset_asset_id,
            EdgeType.READS_FROM, LineageLevel.TABLE,
            confidence=0.7,
            source_ref=source_ref,
            now=now,
            plane=LinePlane.CROSS,
        )
        edges.append(edge)

        return edges

    def _parse_table_ref(
        self, server: str, database: str, path: str,
    ) -> Optional[Dict[str, str]]:
        """
        Parse a table reference from Power BI datasource connection details.

        Handles common patterns:
        - server + database => database-level reference
        - path like "schema.table" or "database.schema.table"
        """
        if path:
            parts = path.replace("`", "").replace('"', "").replace("[", "").replace("]", "").split(".")
            if len(parts) >= 3:
                return {"database": parts[0], "schema": parts[1], "table": parts[2]}
            elif len(parts) == 2:
                return {"database": database, "schema": parts[0], "table": parts[1]}
            elif len(parts) == 1 and parts[0]:
                return {"database": database, "schema": "", "table": parts[0]}

        if database:
            # Only database-level info — not enough for a table edge
            return None

        return None

        edge_id = generate_edge_id(
            source_id, target_id,
            edge_type.value, level.value,
            source_ref,
        )
        return LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            lineage_level=level,
            confidence=confidence,
            discovered_from=source_ref,
            discovered_at=now,
            evidence=[ev],
            plane=plane,
        )
