"""
Cross-Tool Lineage Orchestrator

Coordinates lineage extraction from all connected tools and synthesizes
cross-tool edges to create a unified lineage graph.

Flow:
1. Extract from each tool in parallel
2. Merge all graphs
3. Resolve canonical identities & deduplicate
4. Synthesize cross-tool edges
5. Compute graph metrics
"""

import asyncio
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import logging

from .graph import LineageGraph, LineageNode, LineageEdge, NodeType
from .canonical import CanonicalResolver, normalize_to_canonical_fqn
from .cross_tool import CrossToolEdgeSynthesizer, SynthesisStats
from .parsers import (
    DbtManifestParser,
    BigQueryParser,
    SnowflakeQueryParser,
    SQLServerParser,
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result from extracting lineage from a single tool."""

    integration_id: str
    integration_type: str
    success: bool
    graph: Optional[LineageGraph] = None
    error: Optional[str] = None
    node_count: int = 0
    edge_count: int = 0
    duration_ms: int = 0


@dataclass
class OrchestrationResult:
    """Result from the full orchestration."""

    success: bool
    graph: LineageGraph
    extraction_results: List[ExtractionResult] = field(default_factory=list)
    synthesis_stats: Optional[SynthesisStats] = None
    total_nodes: int = 0
    total_edges: int = 0
    duration_ms: int = 0
    errors: List[str] = field(default_factory=list)


class CrossToolLineageOrchestrator:
    """
    Orchestrates lineage extraction across all connected tools.

    Supports:
    - Warehouses: BigQuery, Snowflake, Postgres, Redshift
    - Transformation: dbt Cloud, dbt Core
    - Orchestration: Airflow (via OpenLineage)
    - BI: Looker, Tableau, Power BI (via metadata)
    """

    # Tool type to parser mapping
    WAREHOUSE_TYPES = {"BIGQUERY", "SNOWFLAKE", "POSTGRES", "REDSHIFT"}
    DBT_TYPES = {"DBT_CLOUD", "DBT_CORE"}
    ORCHESTRATOR_TYPES = {"AIRFLOW", "DAGSTER", "PREFECT"}
    BI_TYPES = {"LOOKER", "TABLEAU", "POWERBI", "METABASE"}

    def __init__(
        self,
        organization_id: str,
        integrations: List[Dict[str, Any]],
        dbt_manifest: Dict[str, Any] = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            organization_id: Organization ID
            integrations: List of integration configs with connection details
            dbt_manifest: Optional pre-loaded dbt manifest
        """
        self.org_id = organization_id
        self.integrations = integrations
        self.dbt_manifest = dbt_manifest

        self.graph = LineageGraph()
        self.resolver = CanonicalResolver()
        self.extraction_results: List[ExtractionResult] = []
        self.errors: List[str] = []

    async def extract_all(self) -> OrchestrationResult:
        """
        Extract lineage from all connected integrations.

        Returns:
            OrchestrationResult with unified graph
        """
        start_time = datetime.utcnow()
        logger.info(f"Starting cross-tool lineage extraction for org {self.org_id}")
        logger.info(f"Processing {len(self.integrations)} integrations")

        try:
            # Step 1: Extract from all tools in parallel
            tool_graphs = await self._extract_from_all_tools()

            # Step 2: Merge all graphs
            for result in tool_graphs:
                if result.success and result.graph:
                    self._merge_graph(result.graph)
                    self.extraction_results.append(result)
                elif result.error:
                    self.errors.append(f"{result.integration_type}: {result.error}")
                    self.extraction_results.append(result)

            # Step 3: Register dbt sources for canonical resolution
            self._register_dbt_sources()

            # Step 4: Synthesize cross-tool edges
            synthesizer = CrossToolEdgeSynthesizer(
                self.graph,
                self.resolver,
                self.dbt_manifest,
            )
            synthesis_stats = synthesizer.synthesize_all()

            # Step 5: Compute graph metrics
            self.graph.compute_depths()
            self.graph.built_at = datetime.utcnow()

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            logger.info(
                f"Cross-tool lineage complete: {len(self.graph.nodes)} nodes, "
                f"{len(self.graph.edges)} edges in {duration_ms}ms"
            )

            return OrchestrationResult(
                success=True,
                graph=self.graph,
                extraction_results=self.extraction_results,
                synthesis_stats=synthesis_stats,
                total_nodes=len(self.graph.nodes),
                total_edges=len(self.graph.edges),
                duration_ms=duration_ms,
                errors=self.errors,
            )

        except Exception as e:
            logger.exception("Failed to extract cross-tool lineage")
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return OrchestrationResult(
                success=False,
                graph=self.graph,
                extraction_results=self.extraction_results,
                total_nodes=len(self.graph.nodes),
                total_edges=len(self.graph.edges),
                duration_ms=duration_ms,
                errors=[str(e)] + self.errors,
            )

    async def _extract_from_all_tools(self) -> List[ExtractionResult]:
        """Extract from all tools in parallel."""
        tasks = []

        for integration in self.integrations:
            if integration.get("status") != "ACTIVE":
                continue

            int_type = integration.get("type", "").upper()
            int_id = integration.get("id", "unknown")

            if int_type in self.WAREHOUSE_TYPES:
                tasks.append(self._extract_warehouse(integration))
            elif int_type in self.DBT_TYPES:
                tasks.append(self._extract_dbt(integration))
            elif int_type in self.ORCHESTRATOR_TYPES:
                tasks.append(self._extract_orchestrator(integration))
            elif int_type in self.BI_TYPES:
                tasks.append(self._extract_bi_tool(integration))
            else:
                logger.warning(f"Unknown integration type: {int_type}")

        if not tasks:
            logger.warning("No active integrations to extract from")
            return []

        # Run all extractions in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                int_info = self.integrations[i] if i < len(self.integrations) else {}
                processed_results.append(
                    ExtractionResult(
                        integration_id=int_info.get("id", "unknown"),
                        integration_type=int_info.get("type", "unknown"),
                        success=False,
                        error=str(result),
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    async def _extract_warehouse(self, integration: Dict) -> ExtractionResult:
        """Extract lineage from a warehouse."""
        start_time = datetime.utcnow()
        int_id = integration.get("id", "unknown")
        int_type = integration.get("type", "").upper()
        config = integration.get("config", {})

        logger.info(f"Extracting lineage from {int_type} ({int_id})")

        try:
            graph = None

            if int_type == "BIGQUERY":
                parser = BigQueryParser(config=config)
                graph = parser.parse()

            elif int_type == "SNOWFLAKE":
                parser = SnowflakeQueryParser(config=config)
                graph = parser.parse()

            elif int_type == "POSTGRES" or int_type == "REDSHIFT":
                # Use SQL parser for Postgres/Redshift
                # TODO: Add dedicated Postgres parser
                graph = LineageGraph()

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            if graph:
                # Tag nodes with integration info
                for node in graph.nodes.values():
                    node.integration_id = int_id
                    node.dialect = int_type.lower()

                return ExtractionResult(
                    integration_id=int_id,
                    integration_type=int_type,
                    success=True,
                    graph=graph,
                    node_count=len(graph.nodes),
                    edge_count=len(graph.edges),
                    duration_ms=duration_ms,
                )
            else:
                return ExtractionResult(
                    integration_id=int_id,
                    integration_type=int_type,
                    success=False,
                    error="Parser returned no graph",
                    duration_ms=duration_ms,
                )

        except Exception as e:
            logger.exception(f"Failed to extract from {int_type}")
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return ExtractionResult(
                integration_id=int_id,
                integration_type=int_type,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def _extract_dbt(self, integration: Dict) -> ExtractionResult:
        """Extract lineage from dbt."""
        start_time = datetime.utcnow()
        int_id = integration.get("id", "unknown")
        int_type = integration.get("type", "").upper()
        config = integration.get("config", {})

        logger.info(f"Extracting lineage from {int_type} ({int_id})")

        try:
            manifest = self.dbt_manifest

            # If no manifest provided, try to fetch from dbt Cloud
            if not manifest and int_type == "DBT_CLOUD":
                manifest = await self._fetch_dbt_cloud_manifest(config)

            if not manifest:
                return ExtractionResult(
                    integration_id=int_id,
                    integration_type=int_type,
                    success=False,
                    error="No dbt manifest available",
                    duration_ms=0,
                )

            # Determine target dialect from manifest
            target_type = manifest.get("metadata", {}).get("adapter_type", "bigquery")

            parser = DbtManifestParser(manifest=manifest, dialect=target_type)
            graph = parser.parse()

            # Store manifest for resolver
            self.dbt_manifest = manifest

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            if graph:
                # Tag nodes with integration info
                for node in graph.nodes.values():
                    node.integration_id = int_id

                return ExtractionResult(
                    integration_id=int_id,
                    integration_type=int_type,
                    success=True,
                    graph=graph,
                    node_count=len(graph.nodes),
                    edge_count=len(graph.edges),
                    duration_ms=duration_ms,
                )
            else:
                return ExtractionResult(
                    integration_id=int_id,
                    integration_type=int_type,
                    success=False,
                    error="Parser returned no graph",
                    duration_ms=duration_ms,
                )

        except Exception as e:
            logger.exception(f"Failed to extract from {int_type}")
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return ExtractionResult(
                integration_id=int_id,
                integration_type=int_type,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def _fetch_dbt_cloud_manifest(self, config: Dict) -> Optional[Dict]:
        """Fetch manifest from dbt Cloud API."""
        try:
            from integrations.dbt import DbtCloudClient

            api_token = config.get("api_token") or config.get("access_token")
            account_id = config.get("account_id")

            if not api_token or not account_id:
                return None

            client = DbtCloudClient(api_token=api_token, account_id=account_id)

            # Get most recent successful run
            jobs = client.get_jobs()
            if not jobs:
                return None

            for job in jobs:
                runs = client.get_runs(job["id"], limit=1)
                if runs and runs[0].get("status") == "Success":
                    manifest = client.get_run_artifact(runs[0]["id"], "manifest.json")
                    if manifest:
                        return manifest

            return None
        except Exception as e:
            logger.warning(f"Failed to fetch dbt Cloud manifest: {e}")
            return None

    async def _extract_orchestrator(self, integration: Dict) -> ExtractionResult:
        """Extract lineage from orchestrator (Airflow, etc.)."""
        start_time = datetime.utcnow()
        int_id = integration.get("id", "unknown")
        int_type = integration.get("type", "").upper()

        logger.info(f"Extracting lineage from {int_type} ({int_id})")

        # TODO: Implement OpenLineage event consumption
        # For now, return empty graph
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        return ExtractionResult(
            integration_id=int_id,
            integration_type=int_type,
            success=True,
            graph=LineageGraph(),
            node_count=0,
            edge_count=0,
            duration_ms=duration_ms,
        )

    async def _extract_bi_tool(self, integration: Dict) -> ExtractionResult:
        """Extract lineage from BI tool (Looker, etc.)."""
        start_time = datetime.utcnow()
        int_id = integration.get("id", "unknown")
        int_type = integration.get("type", "").upper()

        logger.info(f"Extracting lineage from {int_type} ({int_id})")

        # TODO: Implement BI tool lineage extraction
        # For now, return empty graph
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        return ExtractionResult(
            integration_id=int_id,
            integration_type=int_type,
            success=True,
            graph=LineageGraph(),
            node_count=0,
            edge_count=0,
            duration_ms=duration_ms,
        )

    def _merge_graph(self, source_graph: LineageGraph) -> None:
        """Merge a source graph into the main graph."""
        # Add all nodes
        for node in source_graph.nodes.values():
            if node.id not in self.graph.nodes:
                self.graph.add_node(node)

        # Add all edges
        for edge in source_graph.edges.values():
            if edge.id not in self.graph.edges:
                # Verify both nodes exist
                if edge.source_id in self.graph.nodes and edge.target_id in self.graph.nodes:
                    self.graph.add_edge(edge)

    def _register_dbt_sources(self) -> None:
        """Register dbt sources with the canonical resolver."""
        if not self.dbt_manifest:
            return

        # Register sources
        sources = self.dbt_manifest.get("sources", {})
        self.resolver.register_dbt_sources(sources)

        # Register model targets
        nodes = self.dbt_manifest.get("nodes", {})
        self.resolver.register_dbt_model_targets(nodes)

        logger.info(
            f"Registered {len(sources)} dbt sources and {len(nodes)} model targets"
        )

    def get_synthesis_stats(self) -> Optional[Dict]:
        """Get synthesis statistics if available."""
        # This would be set during synthesize_all()
        return None


async def extract_unified_lineage(
    organization_id: str,
    integrations: List[Dict[str, Any]],
    dbt_manifest: Dict[str, Any] = None,
) -> OrchestrationResult:
    """
    Convenience function for extracting unified lineage.

    Args:
        organization_id: Organization ID
        integrations: List of integration configs
        dbt_manifest: Optional dbt manifest

    Returns:
        OrchestrationResult with unified graph
    """
    orchestrator = CrossToolLineageOrchestrator(
        organization_id=organization_id,
        integrations=integrations,
        dbt_manifest=dbt_manifest,
    )

    return await orchestrator.extract_all()
