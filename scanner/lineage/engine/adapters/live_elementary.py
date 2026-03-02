"""
Live Elementary Adapter — enriches lineage graph with data quality metadata.

Elementary is a dbt-native observability tool that stores test results and
anomaly detection data directly in the warehouse. This adapter reads
Elementary tables and:
  1. Creates MONITOR nodes for test suites
  2. Creates MONITORS edges linking monitors to the tables they test
  3. Enriches existing table nodes with health_status and active_findings
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    HealthStatus,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id

logger = logging.getLogger(__name__)


class LiveElementaryAdapter(BaseLineageAdapter):
    """
    Adapter that reads Elementary test results from the warehouse and
    creates quality/observability nodes + edges in the lineage graph.

    Config keys:
        namespace: Warehouse identifier
        integration_id: Pallisade integration ID
        elementary_config: Dict with:
            schema: Elementary schema name (default: "elementary")
            warehouse_adapter: Warehouse adapter instance for queries
            warehouse_type: "snowflake" | "bigquery" | "postgres"
    """

    def __init__(self, adapter_id: str = "live_elementary", **kwargs):
        super().__init__(adapter_id, **kwargs)

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TABLE_LINEAGE,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover Elementary test suites as MONITOR nodes."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "elementary")
        integration_id = config.get("integration_id")
        elem_config = config.get("elementary_config", {})
        schema = elem_config.get("schema", "elementary")
        now = datetime.utcnow()
        nodes: List[LineageNode] = []

        # Query distinct test suites from elementary_test_results
        try:
            query = self._build_test_suites_query(schema)
            results = client.execute_query(query)
        except Exception as e:
            logger.error(f"[LiveElementary] Failed to query test suites: {e}")
            return []

        for row in results:
            test_name = row.get("test_unique_id") or row.get("test_name", "")
            table_name = row.get("table_name", "")
            test_type = row.get("test_type", "generic")
            if not test_name:
                continue

            asset_id = generate_asset_id(
                "catalog", "elementary", namespace, schema, test_name,
            )
            nodes.append(LineageNode(
                id=asset_id,
                name=test_name,
                fqn=f"elementary.{namespace}.{test_name}",
                node_type=NodeType.MONITOR,
                platform="elementary",
                platform_domain=PlatformDomain.CATALOG,
                asset_kind=AssetKind.MONITOR,
                namespace=namespace,
                observed_at=now,
                sources=[self._id],
                integration_id=integration_id,
                raw_metadata={
                    "test_type": test_type,
                    "table_name": table_name,
                    "schema": schema,
                },
            ))

        logger.info(f"[LiveElementary] Discovered {len(nodes)} monitor nodes")
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Create MONITORS edges from test nodes to the tables they test."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "elementary")
        elem_config = config.get("elementary_config", {})
        schema = elem_config.get("schema", "elementary")
        now = datetime.utcnow()
        edges: List[LineageEdge] = []

        try:
            query = self._build_test_results_query(schema)
            results = client.execute_query(query)
        except Exception as e:
            logger.error(f"[LiveElementary] Failed to query test results: {e}")
            return []

        # Group by test → table for edge creation
        seen_edges: Set[str] = set()
        for row in results:
            test_name = row.get("test_unique_id") or row.get("test_name", "")
            table_name = row.get("table_name", "")
            schema_name = row.get("schema_name", "")
            database_name = row.get("database_name", "")
            if not test_name or not table_name:
                continue

            monitor_id = generate_asset_id(
                "catalog", "elementary", namespace, schema, test_name,
            )

            # Build table asset ID to match warehouse adapter conventions
            container = f"{database_name}.{schema_name}"
            table_asset_id = generate_asset_id(
                "warehouse", "elementary", namespace, container, table_name,
            )

            edge_key = f"{monitor_id}:{table_asset_id}"
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            source_ref = f"elementary:test:{test_name}:monitors:{table_name}"
            edges.append(self._make_edge(
                monitor_id, table_asset_id,
                EdgeType.MONITORS, LineageLevel.TABLE,
                confidence=1.0,
                source_ref=source_ref,
                now=now,
                plane=LinePlane.DATA,
            ))

        logger.info(f"[LiveElementary] Extracted {len(edges)} monitor edges")
        return edges

    def get_health_enrichment(self, config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Query recent test results and return health enrichment data per table.

        Returns:
            Dict mapping table_fqn → {health_status, active_findings, failure_count}
        """
        client = self._get_client(config)
        if not client:
            return {}

        elem_config = config.get("elementary_config", {})
        schema = elem_config.get("schema", "elementary")
        enrichment: Dict[str, Dict[str, Any]] = {}

        try:
            query = self._build_health_query(schema)
            results = client.execute_query(query)
        except Exception as e:
            logger.error(f"[LiveElementary] Failed to query health data: {e}")
            return {}

        for row in results:
            table_name = row.get("table_name", "")
            schema_name = row.get("schema_name", "")
            database_name = row.get("database_name", "")
            if not table_name:
                continue

            fqn = ".".join(p for p in [database_name, schema_name, table_name] if p)
            total_tests = int(row.get("total_tests", 0))
            failed_tests = int(row.get("failed_tests", 0))
            warn_tests = int(row.get("warn_tests", 0))

            if failed_tests > 0:
                status = HealthStatus.FAILING
            elif warn_tests > 0:
                status = HealthStatus.DEGRADED
            elif total_tests > 0:
                status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN

            enrichment[fqn] = {
                "health_status": status,
                "total_tests": total_tests,
                "failed_tests": failed_tests,
                "warn_tests": warn_tests,
            }

        return enrichment

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]):
        """Get the warehouse adapter used to query Elementary tables."""
        elem_config = config.get("elementary_config", {})
        adapter = elem_config.get("warehouse_adapter")
        if adapter:
            return adapter

        # If no adapter provided directly, try config-based init
        if config.get("client"):
            return config["client"]

        logger.warning("[LiveElementary] No warehouse_adapter in elementary_config")
        return None

    # ------------------------------------------------------------------
    # Query builders (warehouse-agnostic)
    # ------------------------------------------------------------------

    def _build_test_suites_query(self, schema: str) -> str:
        return f"""
            SELECT DISTINCT
                test_unique_id,
                test_name,
                test_type,
                table_name
            FROM {schema}.elementary_test_results
            WHERE detected_at >= CURRENT_DATE - INTERVAL '7' DAY
            ORDER BY test_unique_id
        """

    def _build_test_results_query(self, schema: str) -> str:
        return f"""
            SELECT DISTINCT
                test_unique_id,
                test_name,
                table_name,
                schema_name,
                database_name
            FROM {schema}.elementary_test_results
            WHERE detected_at >= CURRENT_DATE - INTERVAL '7' DAY
        """

    def _build_health_query(self, schema: str) -> str:
        return f"""
            SELECT
                table_name,
                schema_name,
                database_name,
                COUNT(*) as total_tests,
                SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) as failed_tests,
                SUM(CASE WHEN status = 'warn' THEN 1 ELSE 0 END) as warn_tests
            FROM {schema}.elementary_test_results
            WHERE detected_at >= CURRENT_DATE - INTERVAL '7' DAY
            GROUP BY table_name, schema_name, database_name
        """

    def _build_test_query(self, schema: str) -> str:
        """Simple test query to verify Elementary tables exist."""
        return f"SELECT 1 FROM {schema}.elementary_test_results LIMIT 1"

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
