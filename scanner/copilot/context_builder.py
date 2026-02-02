"""
Co-Pilot Context Builder

Dynamically builds AI context from user's integrations.
The context adapts based on what tools are connected.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum
import json
import logging

from lineage.graph import LineageGraph, LineageNode
from lineage.builder import LineageBuilder

logger = logging.getLogger(__name__)


class IntegrationLayer(Enum):
    """Layers in the data stack."""
    INGESTION = "ingestion"
    TRANSFORMATION = "transformation"
    WAREHOUSE = "warehouse"
    REPORTING = "reporting"


@dataclass
class IntegrationInfo:
    """Information about a connected integration."""
    id: str
    name: str
    type: str
    layer: IntegrationLayer
    status: str
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"


@dataclass
class CopilotContext:
    """
    Context for the AI co-pilot.
    
    Contains everything the LLM needs to understand the user's
    data stack and answer questions intelligently.
    """
    # Organization info
    org_id: str
    
    # Connected integrations
    integrations: List[IntegrationInfo] = field(default_factory=list)
    integration_types: Set[str] = field(default_factory=set)
    
    # Lineage graph
    graph: Optional[LineageGraph] = None
    
    # Relevant nodes for current query
    relevant_nodes: List[LineageNode] = field(default_factory=list)
    
    # Available tools based on integrations
    available_tools: List[str] = field(default_factory=list)
    
    # Pipeline context (if discussing specific pipeline)
    pipeline_stack_id: Optional[str] = None
    focused_node_ids: List[str] = field(default_factory=list)
    
    def has_integration(self, integration_type: str) -> bool:
        """Check if a specific integration type is connected."""
        return integration_type.upper() in self.integration_types
    
    def has_warehouse(self) -> bool:
        """Check if any warehouse is connected."""
        warehouse_types = {"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "SQLSERVER", "AZURE_SQL"}
        return bool(self.integration_types & warehouse_types)
    
    def has_orchestrator(self) -> bool:
        """Check if any orchestrator is connected."""
        orchestrator_types = {"AIRFLOW", "DAGSTER", "PREFECT"}
        return bool(self.integration_types & orchestrator_types)
    
    def has_transformation(self) -> bool:
        """Check if dbt or similar is connected."""
        return self.has_integration("DBT_CLOUD") or self.has_integration("DBT_CORE")
    
    def has_ingestion(self) -> bool:
        """Check if any ingestion tool is connected."""
        ingestion_types = {"FIVETRAN", "AIRBYTE", "STITCH"}
        return bool(self.integration_types & ingestion_types)
    
    def get_integrations_by_layer(self, layer: IntegrationLayer) -> List[IntegrationInfo]:
        """Get all integrations for a specific layer."""
        return [i for i in self.integrations if i.layer == layer and i.is_active]
    
    def to_system_prompt_context(self) -> str:
        """
        Generate context string for the LLM system prompt.
        Only includes information about what the user has connected.
        """
        lines = []
        
        # Describe connected stack
        lines.append("## User's Data Stack\n")
        
        if not self.integrations:
            lines.append("No integrations connected yet.")
            return "\n".join(lines)
        
        # Group by layer
        for layer in IntegrationLayer:
            layer_integrations = self.get_integrations_by_layer(layer)
            if layer_integrations:
                lines.append(f"### {layer.value.title()} Layer")
                for integration in layer_integrations:
                    lines.append(f"- **{integration.name}** ({integration.type})")
                lines.append("")
        
        # Add lineage summary if available
        if self.graph and self.graph.nodes:
            lines.append(f"### Lineage Graph")
            lines.append(f"- {len(self.graph.nodes)} nodes tracked")
            lines.append(f"- {len(self.graph.edges)} edges (dependencies)")
            
            roots = self.graph.get_roots()
            leaves = self.graph.get_leaves()
            lines.append(f"- {len(roots)} source nodes (roots)")
            lines.append(f"- {len(leaves)} output nodes (leaves)")
            lines.append("")
        
        # Add focused context if any
        if self.focused_node_ids:
            lines.append(f"### Current Focus")
            lines.append(f"User is looking at: {', '.join(self.focused_node_ids)}")
            lines.append("")
        
        return "\n".join(lines)


class CopilotContextBuilder:
    """
    Builds AI context dynamically from user's integrations.
    
    The key principle: the context only contains information
    about what the user has actually connected. If they only
    have Snowflake, the co-pilot only knows about Snowflake.
    """
    
    # Mapping of integration types to layers
    INTEGRATION_LAYERS = {
        # Warehouse
        "SNOWFLAKE": IntegrationLayer.WAREHOUSE,
        "BIGQUERY": IntegrationLayer.WAREHOUSE,
        "POSTGRES": IntegrationLayer.WAREHOUSE,
        "REDSHIFT": IntegrationLayer.WAREHOUSE,
        "SQLSERVER": IntegrationLayer.WAREHOUSE,
        "AZURE_SQL": IntegrationLayer.WAREHOUSE,
        "AZURE_SYNAPSE": IntegrationLayer.WAREHOUSE,
        # Ingestion
        "FIVETRAN": IntegrationLayer.INGESTION,
        "AIRBYTE": IntegrationLayer.INGESTION,
        "STITCH": IntegrationLayer.INGESTION,
        # Transformation
        "DBT_CLOUD": IntegrationLayer.TRANSFORMATION,
        "DBT_CORE": IntegrationLayer.TRANSFORMATION,
        "AIRFLOW": IntegrationLayer.TRANSFORMATION,
        "DAGSTER": IntegrationLayer.TRANSFORMATION,
        "PREFECT": IntegrationLayer.TRANSFORMATION,
        # Reporting
        "TABLEAU": IntegrationLayer.REPORTING,
        "LOOKER": IntegrationLayer.REPORTING,
        "POWERBI": IntegrationLayer.REPORTING,
        "METABASE": IntegrationLayer.REPORTING,
    }
    
    def __init__(self, db_session=None):
        self.db = db_session
        self._lineage_builder = LineageBuilder()
    
    async def build_context(
        self,
        org_id: str,
        query: str = "",
        pipeline_stack_id: Optional[str] = None,
        node_ids: Optional[List[str]] = None,
        integrations_data: Optional[List[Dict[str, Any]]] = None
    ) -> CopilotContext:
        """
        Build the AI context for a given organization.
        
        Args:
            org_id: Organization ID
            query: User's query (used to find relevant nodes)
            pipeline_stack_id: Optional specific pipeline to focus on
            node_ids: Optional specific nodes to focus on
            integrations_data: Optional pre-fetched integrations from frontend
            
        Returns:
            CopilotContext with all relevant information
        """
        # 1. Get user's active integrations (use passed data if available)
        if integrations_data:
            integrations = [
                IntegrationInfo(
                    id=i["id"],
                    name=i["name"],
                    type=i["type"].upper(),
                    layer=self.INTEGRATION_LAYERS.get(i["type"].upper(), IntegrationLayer.WAREHOUSE),
                    status="ACTIVE" if i["status"] == "ACTIVE" else i["status"],
                    config=i.get("config", {}),
                )
                for i in integrations_data
            ]
        else:
            integrations = await self._get_integrations(org_id)
        integration_types = {i.type.upper() for i in integrations if i.is_active}
        
        # 2. Build lineage graph from all connected sources
        graph = await self._build_lineage_graph(org_id, integrations)
        
        # 3. Find relevant nodes based on query
        relevant_nodes = []
        if query and graph:
            relevant_nodes = self._find_relevant_nodes(graph, query)
        
        # 4. Determine available tools based on integrations
        available_tools = self._get_available_tools(integration_types)
        
        # 5. Build context
        context = CopilotContext(
            org_id=org_id,
            integrations=integrations,
            integration_types=integration_types,
            graph=graph,
            relevant_nodes=relevant_nodes,
            available_tools=available_tools,
            pipeline_stack_id=pipeline_stack_id,
            focused_node_ids=node_ids or [],
        )
        
        return context
    
    async def _get_integrations(self, org_id: str) -> List[IntegrationInfo]:
        """
        Get all integrations for an organization.
        
        In production, this queries the database.
        """
        # TODO: Query database for integrations
        # For now, return mock data structure
        integrations = []
        
        if self.db:
            # Query from database
            # rows = await self.db.fetch(
            #     "SELECT * FROM Integration WHERE organizationId = $1",
            #     org_id
            # )
            # for row in rows:
            #     integrations.append(IntegrationInfo(
            #         id=row["id"],
            #         name=row["name"],
            #         type=row["type"],
            #         layer=self.INTEGRATION_LAYERS.get(row["type"], IntegrationLayer.WAREHOUSE),
            #         status=row["status"],
            #         config=row.get("config", {}),
            #         metadata=row.get("metadata", {}),
            #     ))
            pass
        
        return integrations
    
    async def _build_lineage_graph(
        self,
        org_id: str,
        integrations: List[IntegrationInfo]
    ) -> Optional[LineageGraph]:
        """
        Build unified lineage graph from all connected integrations.
        
        Each integration contributes its portion of the lineage.
        """
        graph = LineageGraph()
        
        for integration in integrations:
            if not integration.is_active:
                continue
            
            try:
                # Get lineage from each integration type
                if integration.type in ("SNOWFLAKE", "BIGQUERY", "POSTGRES"):
                    # Warehouse lineage from query history
                    warehouse_graph = await self._get_warehouse_lineage(integration)
                    if warehouse_graph:
                        self._merge_graphs(graph, warehouse_graph)
                
                elif integration.type in ("DBT_CLOUD", "DBT_CORE"):
                    # dbt lineage from manifest
                    dbt_graph = await self._get_dbt_lineage(integration)
                    if dbt_graph:
                        self._merge_graphs(graph, dbt_graph)
                
                elif integration.type == "AIRFLOW":
                    # Airflow lineage from DAGs
                    airflow_graph = await self._get_airflow_lineage(integration)
                    if airflow_graph:
                        self._merge_graphs(graph, airflow_graph)
                
                # Add more integration types as needed
                
            except Exception as e:
                logger.warning(f"Failed to get lineage from {integration.name}: {e}")
        
        return graph if graph.nodes else None
    
    async def _get_warehouse_lineage(self, integration: IntegrationInfo) -> Optional[LineageGraph]:
        """Get lineage from warehouse query history."""
        # TODO: Implement warehouse lineage extraction
        return None
    
    async def _get_dbt_lineage(self, integration: IntegrationInfo) -> Optional[LineageGraph]:
        """Get lineage from dbt manifest."""
        # TODO: Implement dbt lineage extraction
        return None
    
    async def _get_airflow_lineage(self, integration: IntegrationInfo) -> Optional[LineageGraph]:
        """Get lineage from Airflow DAGs."""
        # TODO: Implement Airflow lineage extraction
        return None
    
    def _merge_graphs(self, target: LineageGraph, source: LineageGraph) -> None:
        """Merge source graph into target graph."""
        # Add all nodes
        for node in source.nodes.values():
            if node.id not in target.nodes:
                target.add_node(node)
        
        # Add all edges
        for edge in source.edges.values():
            if edge.id not in target.edges:
                target.add_edge(edge)
    
    def _find_relevant_nodes(
        self,
        graph: LineageGraph,
        query: str
    ) -> List[LineageNode]:
        """
        Find nodes relevant to the user's query.
        
        Uses simple keyword matching for now.
        Could be enhanced with semantic search.
        """
        relevant = []
        query_lower = query.lower()
        
        for node in graph.nodes.values():
            # Check if query mentions this node
            if (node.name.lower() in query_lower or
                query_lower in node.name.lower() or
                (node.description and query_lower in node.description.lower())):
                relevant.append(node)
        
        return relevant[:10]  # Limit to top 10
    
    def _get_available_tools(self, integration_types: Set[str]) -> List[str]:
        """
        Determine which tools are available based on connected integrations.
        
        Tools are only available if the required integration is connected.
        """
        tools = []
        
        # Always available (if any integration)
        if integration_types:
            tools.extend([
                "search_lineage",
                "get_node_details",
            ])
        
        # Warehouse tools
        warehouse_types = {"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "SQLSERVER", "AZURE_SQL"}
        if integration_types & warehouse_types:
            tools.extend([
                "get_upstream",
                "get_downstream",
                "get_column_lineage",
                "query_warehouse",
                "get_table_stats",
            ])
        
        # Snowflake/BigQuery specific
        if "SNOWFLAKE" in integration_types or "BIGQUERY" in integration_types:
            tools.append("get_query_history")
        
        # dbt tools
        if "DBT_CLOUD" in integration_types or "DBT_CORE" in integration_types:
            tools.extend([
                "get_dbt_model",
                "get_dbt_run_history",
                "get_dbt_test_results",
                "get_dbt_lineage",
            ])
        
        # Airflow tools
        if "AIRFLOW" in integration_types:
            tools.extend([
                "get_airflow_dag_status",
                "get_airflow_task_logs",
                "get_airflow_recent_failures",
            ])
        
        # Dagster tools
        if "DAGSTER" in integration_types:
            tools.extend([
                "get_dagster_asset_status",
                "get_dagster_run_history",
            ])
        
        # Prefect tools
        if "PREFECT" in integration_types:
            tools.extend([
                "get_prefect_flow_status",
                "get_prefect_flow_runs",
            ])
        
        # Fivetran tools
        if "FIVETRAN" in integration_types:
            tools.extend([
                "get_fivetran_connector_status",
                "get_fivetran_sync_logs",
                "get_fivetran_schema_changes",
            ])
        
        # Airbyte tools
        if "AIRBYTE" in integration_types:
            tools.extend([
                "get_airbyte_connection_status",
                "get_airbyte_sync_history",
            ])
        
        # Looker tools
        if "LOOKER" in integration_types:
            tools.extend([
                "get_looker_dashboard_status",
                "get_looker_model_info",
            ])
        
        return tools
