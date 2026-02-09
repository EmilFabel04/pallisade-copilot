"""
Co-Pilot Context Builder

Dynamically builds AI context from user's integrations.
The context adapts based on what tools are connected.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple
from enum import Enum
import re
import logging

from lineage.graph import LineageGraph, LineageNode
from lineage.builder import LineageBuilder

logger = logging.getLogger(__name__)


# ==========================================
# Query-relevance scoring helpers
# ==========================================

# Common English words that don't help identify tables/columns
_STOP_WORDS = frozenset({
    "what", "which", "how", "many", "much", "show", "me", "my", "the",
    "a", "an", "is", "are", "was", "were", "do", "does", "did", "can",
    "get", "find", "list", "all", "from", "for", "in", "of", "to",
    "and", "or", "by", "with", "that", "this", "on", "at", "have",
    "has", "had", "be", "been", "being", "i", "we", "you", "they",
    "it", "its", "most", "least", "top", "bottom", "give", "tell",
    "about", "any", "some", "each", "every", "per", "total", "count",
    "number", "average", "sum", "min", "max", "between",
})


def _tokenize_query(text: str) -> List[str]:
    """Split query into meaningful tokens, removing stop words."""
    tokens = re.findall(r'[a-z][a-z0-9_]*', text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def _score_table_relevance(
    table: 'TableSchema',
    dataset: str,
    query_lower: str,
    query_tokens: Set[str],
) -> int:
    """
    Score how relevant a table is to the user's query.

    Scoring:
      - Exact table name mentioned in query: +10
      - Table name partially matches a query token: +5
      - A query token appears in a column name: +3
      - Dataset name mentioned in query: +2
      - A query token is a substring of the table name: +1
    """
    score = 0
    table_lower = table.name.lower()
    dataset_lower = dataset.lower()

    # Exact table name in query
    if table_lower in query_lower:
        score += 10

    # Dataset name in query
    if dataset_lower in query_lower:
        score += 2

    # Tokenized table name parts (e.g. "fct_orders" -> ["fct", "orders"])
    table_parts = set(re.findall(r'[a-z][a-z0-9]*', table_lower))

    for token in query_tokens:
        # Token matches a table name part
        if token in table_parts:
            score += 5
        # Token is substring of table name
        elif token in table_lower:
            score += 1
        # Token matches a column name
        for col in table.columns:
            col_lower = col.get('name', '').lower()
            if token == col_lower or token in set(re.findall(r'[a-z][a-z0-9]*', col_lower)):
                score += 3
                break  # Only count once per token

    return score


class IntegrationLayer(Enum):
    """Layers in the data stack."""
    INGESTION = "ingestion"
    TRANSFORMATION = "transformation"
    WAREHOUSE = "warehouse"
    REPORTING = "reporting"
    OBSERVABILITY = "observability"


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
class TableSchema:
    """Schema information for a table."""
    name: str
    dataset: str
    columns: List[Dict[str, str]] = field(default_factory=list)  # [{name, type, description}]
    row_count: Optional[int] = None
    
    def to_prompt_string(self) -> str:
        """Format table schema for LLM prompt."""
        cols = ", ".join([f"{c['name']} ({c['type']})" for c in self.columns[:20]])
        if len(self.columns) > 20:
            cols += f", ... (+{len(self.columns) - 20} more)"
        return f"  - `{self.dataset}.{self.name}`: {cols}"


@dataclass
class CopilotContext:
    """
    Context for the AI co-pilot.
    
    Contains everything the LLM needs to understand the user's
    data stack and answer questions intelligently.
    """
    # Organization info
    org_id: str

    # The user's current query (used for relevance filtering)
    query: str = ""

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
    
    # Pre-fetched warehouse schema (tables and columns)
    warehouse_schema: Dict[str, List[TableSchema]] = field(default_factory=dict)  # dataset -> tables

    # Interaction mode
    mode: str = "ask"
    mode_config: Optional[Any] = None  # ModeConfig from modes.py

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

    def has_observability(self) -> bool:
        """Check if any data observability tool is connected."""
        observability_types = {"MONTE_CARLO", "BIGEYE", "SODA", "ELEMENTARY"}
        return bool(self.integration_types & observability_types)
    
    def get_integrations_by_layer(self, layer: IntegrationLayer) -> List[IntegrationInfo]:
        """Get all integrations for a specific layer."""
        return [i for i in self.integrations if i.layer == layer and i.is_active]
    
    def to_system_prompt_context(self, query: str = "") -> str:
        """
        Generate context string for the LLM system prompt.
        Only includes information about what the user has connected.

        When a query is provided, prioritizes relevant tables in the schema
        to keep the prompt focused and within token limits.
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
                    # Include relevant config details for the AI
                    if integration.config:
                        config = integration.config
                        if config.get('project_id') or config.get('project'):
                            project = config.get('project_id') or config.get('project')
                            lines.append(f"  - Project: `{project}`")
                        if config.get('datasets'):
                            datasets = config.get('datasets')
                            if isinstance(datasets, list):
                                lines.append(f"  - Datasets: {', '.join([f'`{d}`' for d in datasets])}")
                            else:
                                lines.append(f"  - Dataset: `{datasets}`")
                        if config.get('database'):
                            lines.append(f"  - Database: `{config.get('database')}`")
                        if config.get('schema'):
                            lines.append(f"  - Schema: `{config.get('schema')}`")
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

        # Add warehouse schema with relevance filtering
        if self.warehouse_schema:
            lines.append("### Database Schema (EXACT column names - USE THESE!)")
            lines.append("**IMPORTANT**: Use ONLY these column names when writing queries. Do NOT guess or assume other column names exist.\n")

            if query:
                # Partition tables into relevant and other
                relevant, other = self._partition_schema_by_relevance(query)

                if relevant:
                    lines.append("**Most Relevant Tables for Your Question:**")
                    for _ds, table in relevant:
                        lines.append(table.to_prompt_string())
                    lines.append("")

                if other:
                    lines.append("**Other Available Tables:**")
                    for _ds, table in other:
                        lines.append(table.to_prompt_string())
                    lines.append("")
            else:
                for schema_key, tables in self.warehouse_schema.items():
                    wh_type, dataset_name = self._parse_schema_key(schema_key)
                    if wh_type:
                        lines.append(f"**[{wh_type}] Dataset: `{dataset_name}`**")
                    else:
                        lines.append(f"**Dataset: `{dataset_name}`**")
                    for table in tables:
                        lines.append(table.to_prompt_string())
                    lines.append("")

        # Add focused context if any
        if self.focused_node_ids:
            lines.append(f"### Current Focus")
            lines.append(f"User is looking at: {', '.join(self.focused_node_ids)}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _parse_schema_key(key: str) -> tuple:
        """
        Parse a compound schema key like 'BIGQUERY:raw' into (warehouse_type, dataset_name).
        Returns (None, key) if not a compound key.
        """
        if ':' in key:
            wh_type, dataset_name = key.split(':', 1)
            return wh_type, dataset_name
        return None, key

    def _partition_schema_by_relevance(
        self,
        query: str,
    ) -> tuple:
        """
        Partition schema tables into (relevant, other) based on query.

        Relevant tables are shown with full column detail.
        Other tables are listed compactly so the LLM knows they exist
        without consuming excessive tokens.

        Returns:
            Tuple of (relevant_list, other_list) where each item is (dataset, TableSchema).
        """
        query_lower = query.lower()
        query_tokens = set(_tokenize_query(query_lower))

        scored: list = []
        for schema_key, tables in self.warehouse_schema.items():
            _wh_type, dataset_name = self._parse_schema_key(schema_key)
            for table in tables:
                score = _score_table_relevance(table, dataset_name, query_lower, query_tokens)
                scored.append((score, dataset_name, table))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Top tables with any relevance signal get full detail (up to 15)
        relevant = [(ds, t) for score, ds, t in scored if score > 0][:15]
        other = [(ds, t) for score, ds, t in scored if score == 0]

        # If nothing matched, show all tables (fallback)
        if not relevant:
            relevant = [(ds, t) for _, ds, t in scored]
            other = []

        return relevant, other


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
        # Observability
        "MONTE_CARLO": IntegrationLayer.OBSERVABILITY,
        "BIGEYE": IntegrationLayer.OBSERVABILITY,
        "SODA": IntegrationLayer.OBSERVABILITY,
        "ELEMENTARY": IntegrationLayer.OBSERVABILITY,
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
        integrations_data: Optional[List[Dict[str, Any]]] = None,
        mode: str = "ask",
        mode_config: Optional[Any] = None,
    ) -> CopilotContext:
        """
        Build the AI context for a given organization.

        Args:
            org_id: Organization ID
            query: User's query (used to find relevant nodes)
            pipeline_stack_id: Optional specific pipeline to focus on
            node_ids: Optional specific nodes to focus on
            integrations_data: Optional pre-fetched integrations from frontend
            mode: Interaction mode (ask, debug, plan, create, etc.)
            mode_config: Mode configuration from modes.py

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
                    metadata=i.get("metadata", {}),
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
            query=query,
            integrations=integrations,
            integration_types=integration_types,
            graph=graph,
            relevant_nodes=relevant_nodes,
            available_tools=available_tools,
            pipeline_stack_id=pipeline_stack_id,
            focused_node_ids=node_ids or [],
            mode=mode,
            mode_config=mode_config,
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

        Uses tokenized fuzzy matching: splits both the query and node names
        into parts and scores overlap, so "orders" matches "fct_orders",
        "stg_orders", "raw.orders", etc.
        """
        query_lower = query.lower()
        query_tokens = set(_tokenize_query(query_lower))

        if not query_tokens:
            return []

        scored: List[Tuple[int, LineageNode]] = []
        for node in graph.nodes.values():
            score = 0
            node_lower = node.name.lower()
            # Break node name into parts (e.g. "project.analytics.fct_orders" -> ["project","analytics","fct","orders"])
            node_parts = set(re.findall(r'[a-z][a-z0-9]*', node_lower))

            # Exact name in query
            if node_lower in query_lower:
                score += 10

            # Token overlap between query and node name parts
            overlap = query_tokens & node_parts
            score += len(overlap) * 5

            # Substring match (query token is part of node name)
            for token in query_tokens:
                if token in node_lower and token not in node_parts:
                    score += 1

            # Description match
            if node.description:
                desc_lower = node.description.lower()
                for token in query_tokens:
                    if token in desc_lower:
                        score += 2

            if score > 0:
                scored.append((score, node))

        # Sort by score descending, return top 10
        scored.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in scored[:10]]
    
    def _get_available_tools(self, integration_types: Set[str]) -> List[str]:
        """
        Determine which tools are available based on connected integrations.
        
        Tools are only available if the required integration is connected.
        """
        tools = []

        # Always available (no integration required)
        tools.append("search_knowledge_base")

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

        # Observability tools (Monte Carlo, Bigeye, Soda, Elementary)
        observability_types = {"MONTE_CARLO", "BIGEYE", "SODA", "ELEMENTARY"}
        if integration_types & observability_types:
            tools.extend([
                "get_active_incidents",
                "get_asset_quality",
                "trace_incident_root_cause",
                "get_quality_checks",
                "get_incident_details",
            ])

        # Change plan tools (always available - core copilot functionality)
        tools.extend([
            "create_change_plan",
            "validate_change_plan",
            "get_change_plan",
            "apply_change_plan",
            "list_change_plans",
        ])

        # GitHub tools (for reading repo contents and lineage mapping)
        if "GITHUB" in integration_types:
            tools.extend([
                "list_github_repos",
                "get_github_tree",
                "get_github_file",
            ])

        return tools
