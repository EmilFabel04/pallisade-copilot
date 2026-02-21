"""
Live n8n Adapter — extracts lineage from n8n workflows.

Discovers workflows as WORKFLOW nodes and their internal nodes as TASK nodes
on the ORCHESTRATION domain. Parses HTTP Request and DB nodes for cross-plane
edges to warehouse tables and external APIs.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, generate_edge_id

logger = logging.getLogger(__name__)

# n8n node types that interact with databases
_DB_NODE_TYPES = {
    "postgres", "mysql", "microsoftsql", "mongodb",
    "snowflake", "redis", "elasticsearch",
    "googleBigQuery", "awsDynamoDb",
}

# n8n node types that read/write data
_DATA_NODE_TYPES = {
    "httpRequest", "webhook", "s3", "googleSheets",
    "ftp", "sftp", "readBinaryFiles", "writeBinaryFile",
}


class LiveN8nAdapter(BaseLineageAdapter):
    """
    Adapter that discovers n8n workflows and extracts lineage.

    Config keys:
        namespace: Identifier for this n8n instance
        integration_id: Pallisade integration ID
        n8n_config: Dict with base_url, api_key
    """

    def __init__(self, adapter_id: str = "live_n8n", **kwargs):
        self._id = adapter_id

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.GET_RUNS_LOGS,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover n8n workflows and their internal nodes."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "n8n")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        try:
            workflows = client.get_workflows()
        except Exception as e:
            logger.error(f"[LiveN8n] Failed to get workflows: {e}")
            return []

        for wf in workflows:
            # Workflow node (like a DAG)
            wf_asset_id = generate_asset_id(
                "orchestration", "n8n", namespace, "", f"workflow_{wf.id}",
            )
            nodes.append(LineageNode(
                id=wf_asset_id,
                name=wf.name,
                fqn=f"n8n.{namespace}.workflow.{wf.id}",
                node_type=NodeType.WORKFLOW,
                platform="n8n",
                platform_domain=PlatformDomain.ORCHESTRATION,
                asset_kind=AssetKind.WORKFLOW,
                namespace=namespace,
                observed_at=now,
                sources=[self._id],
                integration_id=integration_id,
                raw_metadata={
                    "workflow_id": wf.id,
                    "active": wf.active,
                    "node_count": wf.node_count,
                    "tags": [t.get("name", "") for t in wf.tags],
                    "created_at": wf.created_at.isoformat() if wf.created_at else None,
                    "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
                },
            ))

            # Internal nodes (like tasks)
            for n8n_node in wf.nodes:
                task_asset_id = generate_asset_id(
                    "orchestration", "n8n", namespace,
                    f"workflow_{wf.id}", n8n_node.name,
                )
                nodes.append(LineageNode(
                    id=task_asset_id,
                    name=n8n_node.name,
                    fqn=f"n8n.{namespace}.workflow.{wf.id}.{n8n_node.name}",
                    node_type=NodeType.TASK,
                    platform="n8n",
                    platform_domain=PlatformDomain.ORCHESTRATION,
                    asset_kind=AssetKind.TASK,
                    namespace=namespace,
                    observed_at=now,
                    sources=[self._id],
                    integration_id=integration_id,
                    raw_metadata={
                        "workflow_id": wf.id,
                        "node_type": n8n_node.type,
                        "short_type": n8n_node.short_type,
                    },
                ))

        logger.info(f"[LiveN8n] Discovered {len(nodes)} assets from {len(workflows)} workflows")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract workflow→task edges and cross-plane edges to data assets."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "n8n")
        now = datetime.utcnow()
        edges: List[LineageEdge] = []

        try:
            workflows = client.get_workflows()
        except Exception:
            return []

        for wf in workflows:
            wf_asset_id = generate_asset_id(
                "orchestration", "n8n", namespace, "", f"workflow_{wf.id}",
            )

            for n8n_node in wf.nodes:
                task_asset_id = generate_asset_id(
                    "orchestration", "n8n", namespace,
                    f"workflow_{wf.id}", n8n_node.name,
                )

                # Workflow → Task (CONTROL plane)
                edges.append(self._make_edge(
                    wf_asset_id, task_asset_id,
                    EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=f"n8n:workflow:{wf.id}:node:{n8n_node.name}",
                    now=now,
                    plane=LinePlane.CONTROL,
                ))

                # Cross-plane edges: DB nodes → warehouse tables
                short_type = n8n_node.short_type.lower()
                if short_type in _DB_NODE_TYPES:
                    table_refs = self._extract_db_table_refs(n8n_node)
                    for table_ref, is_write in table_refs:
                        table_asset_id = generate_asset_id(
                            "warehouse", "n8n", namespace, "", table_ref,
                        )
                        if is_write:
                            edges.append(self._make_edge(
                                task_asset_id, table_asset_id,
                                EdgeType.WRITES_TO, LineageLevel.TABLE,
                                confidence=0.7,
                                source_ref=f"n8n:workflow:{wf.id}:node:{n8n_node.name}:writes:{table_ref}",
                                now=now,
                                plane=LinePlane.CROSS,
                            ))
                        else:
                            edges.append(self._make_edge(
                                table_asset_id, task_asset_id,
                                EdgeType.READS_FROM, LineageLevel.TABLE,
                                confidence=0.7,
                                source_ref=f"n8n:workflow:{wf.id}:node:{n8n_node.name}:reads:{table_ref}",
                                now=now,
                                plane=LinePlane.CROSS,
                            ))

        logger.info(f"[LiveN8n] Extracted {len(edges)} edges")
        return edges

    def fetch_context(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch recent execution history."""
        client = self._get_client(config)
        if not client:
            return {}

        try:
            executions = client.get_executions(limit=50)
            return {
                "recent_executions": [
                    {
                        "id": ex.id,
                        "workflow_id": ex.workflow_id,
                        "workflow_name": ex.workflow_name,
                        "status": ex.status.value,
                        "started_at": ex.started_at.isoformat() if ex.started_at else None,
                        "duration_seconds": ex.duration_seconds,
                    }
                    for ex in executions
                ]
            }
        except Exception as e:
            logger.error(f"[LiveN8n] Failed to fetch context: {e}")
            return {}

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        if config.get("client"):
            return config["client"]

        n8n_config = config.get("n8n_config", {})
        if not n8n_config.get("base_url") and not n8n_config.get("host"):
            logger.warning("[LiveN8n] No n8n_config with base_url provided")
            return None

        try:
            from scanner.integrations.n8n import N8nIntegration
        except ImportError:
            from integrations.n8n import N8nIntegration

        return N8nIntegration(n8n_config)

    # ------------------------------------------------------------------
    # Parse DB node parameters for table references
    # ------------------------------------------------------------------

    def _extract_db_table_refs(self, node) -> List[tuple]:
        """
        Extract table references from n8n DB node parameters.

        Returns list of (table_ref, is_write) tuples.
        """
        params = node.parameters
        results = []

        # Common parameter patterns
        table = params.get("table") or params.get("tableName") or ""
        schema = params.get("schema") or params.get("schemaName") or ""
        operation = (params.get("operation") or params.get("command") or "select").lower()
        is_write = operation in ("insert", "update", "upsert", "delete", "create")

        if table:
            ref = f"{schema}.{table}" if schema else table
            results.append((ref, is_write))

        # Check for raw SQL queries
        query = params.get("query") or params.get("sql") or ""
        if query and not table:
            table_pattern = re.compile(
                r"(?:FROM|JOIN|INTO|UPDATE|INSERT\s+INTO)\s+([^\s,();]+)",
                re.IGNORECASE,
            )
            for match in table_pattern.finditer(query):
                ref = match.group(1).strip('`"[]')
                if ref.upper() not in ("SELECT", "WHERE", "SET"):
                    has_write = bool(re.search(r"INSERT|UPDATE|DELETE|MERGE", query, re.IGNORECASE))
                    results.append((ref, has_write))

        return results

    # ------------------------------------------------------------------
    # Edge helper
    # ------------------------------------------------------------------

    def _make_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        level: LineageLevel,
        confidence: float,
        source_ref: str,
        now: datetime,
        plane: LinePlane = LinePlane.CONTROL,
    ) -> LineageEdge:
        ev = Evidence(
            adapter_id=self._id,
            source_ref=source_ref,
            observed_at=now,
        )
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
