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
from lineage.engine.store import GraphStore

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
    project: Optional[str] = None  # BigQuery project ID (catalog)
    warehouse_type: Optional[str] = None  # BIGQUERY, SNOWFLAKE, etc.

    def to_prompt_string(self) -> str:
        """Format table schema for LLM prompt."""
        cols = ", ".join([f"{c['name']} ({c['type']})" for c in self.columns[:20]])
        if len(self.columns) > 20:
            cols += f", ... (+{len(self.columns) - 20} more)"

        # Include full path for BigQuery (project.dataset.table)
        if self.project and self.warehouse_type == "BIGQUERY":
            full_path = f"`{self.project}.{self.dataset}.{self.name}`"
        else:
            full_path = f"`{self.dataset}.{self.name}`"

        return f"  - {full_path}: {cols}"


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

    # Engine-powered graph store (adds filtering, evidence, confidence, explain_edge)
    engine_store: Optional[GraphStore] = None

    # Relevant nodes for current query
    relevant_nodes: List[LineageNode] = field(default_factory=list)
    
    # Available tools based on integrations
    available_tools: List[str] = field(default_factory=list)
    
    # Pipeline context (if discussing specific pipeline)
    pipeline_stack_id: Optional[str] = None
    focused_node_ids: List[str] = field(default_factory=list)
    referenced_entities: List[str] = field(default_factory=list)

    # Pre-fetched warehouse schema (tables and columns)
    warehouse_schema: Dict[str, List[TableSchema]] = field(default_factory=dict)  # dataset -> tables

    # Interaction mode
    mode: str = "ask"
    mode_config: Optional[Any] = None  # ModeConfig from modes.py

    # Pipeline context from onboarding (learned knowledge about user's setup)
    pipeline_context: Optional[Dict[str, Any]] = None

    # MCP (Model Context Protocol) — set to True when MCP servers are active
    mcp_enabled: bool = False

    def has_integration(self, integration_type: str) -> bool:
        """Check if a specific integration type is connected."""
        return integration_type.upper() in self.integration_types
    
    def has_warehouse(self) -> bool:
        """Check if any warehouse is connected."""
        warehouse_types = {"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT", "SQLSERVER", "AZURE_SQL"}
        return bool(self.integration_types & warehouse_types)
    
    def has_orchestrator(self) -> bool:
        """Check if any orchestrator is connected."""
        orchestrator_types = {"AIRFLOW", "DAGSTER", "PREFECT", "N8N"}
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

        # Add lineage node catalog so LLM can use lineage tools
        if self.graph and self.graph.nodes:
            lines.append(self._build_lineage_prompt_section(query))
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

        # Add @mentioned entities for focused context
        if self.referenced_entities:
            lines.append("### Referenced Entities (from @mentions)")
            lines.append("The user specifically referenced these entities. Prioritize them in your response:")
            for entity in self.referenced_entities:
                lines.append(f"  - `{entity}`")
            lines.append("")

        # Add MCP dynamic exploration guidance
        if self.mcp_enabled:
            lines.append("### Dynamic Exploration (MCP)")
            lines.append("You have access to MCP tools for on-demand exploration beyond the pre-loaded context above:")
            lines.append("- **Warehouse tools** (`mcp_snowflake__*`, `mcp_bigquery__*`, `mcp_postgres__*`): Browse schemas, run queries, inspect objects dynamically")
            lines.append("- **dbt tools** (`mcp_dbt__*`): Explore models, tests, docs, semantic layer, and column-level lineage via the Discovery API")
            lines.append("- **Orchestration tools** (`mcp_airflow__*`): Inspect DAGs, task logs, and system health")
            lines.append("- **Lineage tools** (`mcp_lineage__*`): Traverse upstream/downstream, explain edge evidence and confidence, blast radius analysis, column-level tracing")
            lines.append("")
            lines.append("Use these MCP tools to explore deeper when the pre-loaded context above is insufficient. "
                         "For lineage queries, prefer `mcp_lineage__get_upstream` / `mcp_lineage__get_downstream` for interactive traversal "
                         "and `mcp_lineage__explain_edge` to understand edge provenance and confidence.")
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

    def _build_lineage_prompt_section(self, query: str = "") -> str:
        """
        Build a compact node catalog for the LLM system prompt.

        Groups nodes by graph role (sources → intermediates → outputs)
        and shows adjacency so the LLM can construct valid tool calls.

        Tiered truncation:
          ≤50 nodes  — full catalog with adjacency
          51-150     — roots/leaves + query-relevant with adjacency, rest as compact list
          150+       — top 50 relevant + roots/leaves, summary for rest
        """
        graph = self.graph
        if not graph or not graph.nodes:
            return ""

        total_nodes = len(graph.nodes)
        total_edges = len(graph.edges)

        lines = [f"### Lineage Graph ({total_nodes} nodes, {total_edges} edges)", ""]
        lines.append("Use node names or FQNs (shown in backticks as `fqn: ...`) below as `node_id` for get_upstream, get_downstream, get_node_details, and analyze_change_impact. Platform tags like {airflow}, {dbt}, {bigquery} show which system owns each node. If a tool returns 'not found', use `search_lineage` with a wildcard pattern to find the correct node ID.")
        lines.append("")

        # Classify nodes into sources, intermediates, outputs
        roots = set(n.id for n in graph.get_roots())
        leaves = set(n.id for n in graph.get_leaves())

        sources = []
        intermediates = []
        outputs = []
        for nid, node in graph.nodes.items():
            if nid in roots:
                sources.append(node)
            elif nid in leaves:
                outputs.append(node)
            else:
                intermediates.append(node)

        # Sort each group alphabetically by name
        sources.sort(key=lambda n: n.name.lower())
        intermediates.sort(key=lambda n: n.name.lower())
        outputs.sort(key=lambda n: n.name.lower())

        def _node_type_label(node: LineageNode) -> str:
            """Short type label for a node."""
            if hasattr(node, 'raw_metadata') and node.raw_metadata.get('dbt_resource_type'):
                return node.raw_metadata['dbt_resource_type']
            return node.node_type.value if hasattr(node.node_type, 'value') else str(node.node_type)

        def _short_name(node: LineageNode) -> str:
            """Shortest useful name — last 2 parts of FQN or just name."""
            name = node.fqn or node.name
            parts = name.split('.')
            if len(parts) > 2:
                return '.'.join(parts[-2:])
            return name

        def _adjacency_str(node: LineageNode, max_neighbors: int = 3) -> str:
            """Build <- upstream -> downstream string."""
            parts = []

            # Upstream
            up_ids = list(graph._upstream.get(node.id, set()))[:max_neighbors]
            up_names = [_short_name(graph.nodes[uid]) for uid in up_ids if uid in graph.nodes]
            up_extra = len(graph._upstream.get(node.id, set())) - len(up_names)
            if up_names:
                up_str = ", ".join(up_names)
                if up_extra > 0:
                    up_str += f" +{up_extra}"
                parts.append(f"<- {up_str}")

            # Downstream
            down_ids = list(graph._downstream.get(node.id, set()))[:max_neighbors]
            down_names = [_short_name(graph.nodes[did]) for did in down_ids if did in graph.nodes]
            down_extra = len(graph._downstream.get(node.id, set())) - len(down_names)
            if down_names:
                down_str = ", ".join(down_names)
                if down_extra > 0:
                    down_str += f" +{down_extra}"
                parts.append(f"-> {down_str}")

            return " ".join(parts)

        def _format_node(node: LineageNode, show_adjacency: bool = True) -> str:
            """Format a single node line with platform and FQN."""
            type_label = _node_type_label(node)
            name = _short_name(node)
            # Show platform/system so LLM knows what produced the node
            platform_tag = ""
            if node.platform:
                platform_tag = f" {{{node.platform}}}"
            # Show full FQN if different from short name (so LLM can use it in tool calls)
            fqn_hint = ""
            full_fqn = node.fqn or node.name
            if full_fqn != name and len(full_fqn) <= 80:
                fqn_hint = f" (fqn: `{full_fqn}`)"
            line = f"  {name} [{type_label}]{platform_tag}{fqn_hint}"
            if show_adjacency:
                adj = _adjacency_str(node)
                if adj:
                    line += f" {adj}"
            return line

        if total_nodes <= 50:
            # Full catalog with adjacency
            if sources:
                lines.append("**Sources** (roots — no upstream):")
                for node in sources:
                    lines.append(_format_node(node))
                lines.append("")
            if intermediates:
                lines.append("**Transformations:**")
                for node in intermediates:
                    lines.append(_format_node(node))
                lines.append("")
            if outputs:
                lines.append("**Outputs** (leaves — no downstream):")
                for node in outputs:
                    lines.append(_format_node(node))
                lines.append("")

        elif total_nodes <= 150:
            # Roots and leaves with adjacency + query-relevant nodes
            relevant_ids = set()
            if query:
                relevant_nodes = CopilotContextBuilder._find_relevant_nodes_static(graph, query)
                relevant_ids = set(n.id for n in relevant_nodes)

            if sources:
                lines.append("**Sources** (roots):")
                for node in sources:
                    lines.append(_format_node(node))
                lines.append("")

            # Show query-relevant intermediates with adjacency
            relevant_intermediates = [n for n in intermediates if n.id in relevant_ids]
            other_intermediates = [n for n in intermediates if n.id not in relevant_ids]
            if relevant_intermediates:
                lines.append("**Relevant Transformations:**")
                for node in relevant_intermediates:
                    lines.append(_format_node(node))
                lines.append("")
            if other_intermediates:
                names = ", ".join(_short_name(n) for n in other_intermediates[:30])
                extra = len(other_intermediates) - 30
                lines.append(f"**Other Transformations** ({len(other_intermediates)}):")
                lines.append(f"  {names}{'...' if extra > 0 else ''}")
                lines.append("")

            if outputs:
                lines.append("**Outputs** (leaves):")
                for node in outputs:
                    lines.append(_format_node(node))
                lines.append("")

        else:
            # 150+ nodes: top 50 relevant + roots/leaves, summary for rest
            relevant_nodes = CopilotContextBuilder._find_relevant_nodes_static(graph, query) if query else []
            relevant_ids = set(n.id for n in relevant_nodes)

            # Show up to 10 sources, 10 outputs
            lines.append(f"**Sources** ({len(sources)} total, showing top {min(10, len(sources))}):")
            for node in sources[:10]:
                lines.append(_format_node(node))
            if len(sources) > 10:
                lines.append(f"  ... +{len(sources) - 10} more sources")
            lines.append("")

            if relevant_nodes:
                lines.append(f"**Query-Relevant Nodes** (top {len(relevant_nodes)}):")
                for node in relevant_nodes:
                    if node.id not in roots and node.id not in leaves:
                        lines.append(_format_node(node))
                lines.append("")

            lines.append(f"**Outputs** ({len(outputs)} total, showing top {min(10, len(outputs))}):")
            for node in outputs[:10]:
                lines.append(_format_node(node))
            if len(outputs) > 10:
                lines.append(f"  ... +{len(outputs) - 10} more outputs")
            lines.append("")

            remaining = total_nodes - len(sources[:10]) - len(outputs[:10]) - len([n for n in relevant_nodes if n.id not in roots and n.id not in leaves])
            if remaining > 0:
                lines.append(f"_{remaining} more nodes not shown. Use `search_lineage` to find specific nodes._")
                lines.append("")

        # Engine coverage stats
        if self.engine_store:
            try:
                stats = self.engine_store.get_stats()
                stat_parts = []
                if stats.coverage_table:
                    stat_parts.append(f"Table coverage: {stats.coverage_table:.0%}")
                if stats.coverage_column:
                    stat_parts.append(f"Column coverage: {stats.coverage_column:.0%}")
                if stats.edges_by_level:
                    level_parts = [f"{v} {k}" for k, v in stats.edges_by_level.items()]
                    stat_parts.append(f"Edges: {', '.join(level_parts)}")
                if stat_parts:
                    lines.append(" | ".join(stat_parts))
            except Exception:
                pass

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
        referenced_entities: Optional[List[str]] = None,
        integrations_data: Optional[List[Dict[str, Any]]] = None,
        mode: str = "ask",
        mode_config: Optional[Any] = None,
        lineage_data: Optional[Dict[str, Any]] = None,
        engine_graph: Optional[LineageGraph] = None,
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
            lineage_data: Optional pre-fetched lineage data from database
            engine_graph: Optional in-process engine graph (preferred over lineage_data)

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

        # 2. Build lineage graph — prefer in-process engine graph (richest),
        #    then pre-fetched Prisma data, then integration-based extraction.
        graph = None
        if engine_graph and engine_graph.nodes:
            graph = engine_graph
            logger.info(f"[Lineage] Using in-process engine graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
        elif lineage_data and (lineage_data.get('nodes') or lineage_data.get('edges')):
            logger.info(f"[Lineage] Building from pre-fetched data: {len(lineage_data.get('nodes', []))} nodes, {len(lineage_data.get('edges', []))} edges")
            graph = self._build_lineage_from_data(lineage_data)
        else:
            # Fall back to integration-based lineage (currently TODO stubs)
            graph = await self._build_lineage_graph(org_id, integrations)
        
        # 3. Wrap graph in engine GraphStore for filtering/evidence/explain
        engine_store = None
        if graph and graph.nodes:
            try:
                engine_store = GraphStore()
                engine_store.graph = graph
                logger.info(f"[Engine] GraphStore initialized: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
            except Exception as e:
                logger.warning(f"[Engine] Failed to initialize GraphStore: {e}")
                engine_store = None

        # 4. Find relevant nodes based on query
        relevant_nodes = []
        if query and graph:
            relevant_nodes = self._find_relevant_nodes(graph, query)

        # 5. Determine available tools based on integrations
        available_tools = self._get_available_tools(integration_types)

        # 6. Build context
        context = CopilotContext(
            org_id=org_id,
            query=query,
            integrations=integrations,
            integration_types=integration_types,
            graph=graph,
            engine_store=engine_store,
            relevant_nodes=relevant_nodes,
            available_tools=available_tools,
            pipeline_stack_id=pipeline_stack_id,
            focused_node_ids=node_ids or [],
            referenced_entities=referenced_entities or [],
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
        Build unified cross-tool lineage graph from all connected integrations.

        Uses the CrossToolLineageOrchestrator to:
        1. Extract lineage from each tool in parallel
        2. Merge and deduplicate nodes across tools
        3. Synthesize cross-tool edges (dbt source -> warehouse table, etc.)
        """
        try:
            from lineage.orchestrator import CrossToolLineageOrchestrator
        except ImportError:
            logger.warning("CrossToolLineageOrchestrator not available, using legacy method")
            return await self._build_lineage_graph_legacy(org_id, integrations)

        # Convert integrations to dict format for orchestrator
        integration_dicts = [
            {
                "id": i.id,
                "type": i.type,
                "status": "ACTIVE" if i.is_active else i.status,
                "config": i.config,
            }
            for i in integrations
            if i.is_active
        ]

        if not integration_dicts:
            logger.info("No active integrations for lineage extraction")
            return None

        try:
            orchestrator = CrossToolLineageOrchestrator(
                organization_id=org_id,
                integrations=integration_dicts,
            )

            result = await orchestrator.extract_all()

            if result.success and result.graph and result.graph.nodes:
                logger.info(
                    f"[Lineage] Cross-tool extraction complete: "
                    f"{result.total_nodes} nodes, {result.total_edges} edges"
                )
                if result.synthesis_stats:
                    logger.info(
                        f"[Lineage] Synthesis: {result.synthesis_stats.nodes_merged} nodes merged, "
                        f"{result.synthesis_stats.total_edges_created} edges synthesized"
                    )
                return result.graph
            else:
                if result.errors:
                    logger.warning(f"[Lineage] Extraction errors: {result.errors}")
                return None

        except Exception as e:
            logger.error(f"[Lineage] Cross-tool extraction failed: {e}", exc_info=True)
            # Fall back to legacy method
            return await self._build_lineage_graph_legacy(org_id, integrations)

    async def _build_lineage_graph_legacy(
        self,
        org_id: str,
        integrations: List[IntegrationInfo]
    ) -> Optional[LineageGraph]:
        """
        Legacy lineage graph building (per-tool extraction without cross-tool synthesis).

        Used as fallback when orchestrator is not available.
        """
        graph = LineageGraph()

        for integration in integrations:
            if not integration.is_active:
                continue

            try:
                # Get lineage from each integration type
                if integration.type in ("SNOWFLAKE", "BIGQUERY", "POSTGRES"):
                    warehouse_graph = await self._get_warehouse_lineage(integration)
                    if warehouse_graph:
                        self._merge_graphs(graph, warehouse_graph)

                elif integration.type in ("DBT_CLOUD", "DBT_CORE"):
                    dbt_graph = await self._get_dbt_lineage(integration)
                    if dbt_graph:
                        self._merge_graphs(graph, dbt_graph)

                elif integration.type == "AIRFLOW":
                    airflow_graph = await self._get_airflow_lineage(integration)
                    if airflow_graph:
                        self._merge_graphs(graph, airflow_graph)

            except Exception as e:
                logger.warning(f"Failed to get lineage from {integration.name}: {e}")

        return graph if graph.nodes else None

    async def _get_warehouse_lineage(self, integration: IntegrationInfo) -> Optional[LineageGraph]:
        """Get lineage from warehouse query history."""
        try:
            if integration.type == "BIGQUERY":
                from lineage.parsers.bigquery import BigQueryParser

                config = integration.config
                project_id = config.get("project_id") or config.get("project")
                if not project_id:
                    return None

                # Create BigQuery client
                from google.cloud import bigquery
                from google.oauth2 import service_account
                import json

                credentials_json = config.get("credentials_json") or config.get("credentials")
                if credentials_json:
                    if isinstance(credentials_json, str):
                        credentials_dict = json.loads(credentials_json)
                    else:
                        credentials_dict = credentials_json
                    credentials = service_account.Credentials.from_service_account_info(credentials_dict)
                    client = bigquery.Client(project=project_id, credentials=credentials)
                else:
                    client = bigquery.Client(project=project_id)

                parser = BigQueryParser(
                    client=client,
                    project_id=project_id,
                    region=config.get("region", "auto"),
                    days_back=config.get("days_back", 30),
                )
                return parser.parse()

            elif integration.type == "SNOWFLAKE":
                from lineage.parsers.snowflake import SnowflakeQueryParser

                parser = SnowflakeQueryParser(config=integration.config)
                return parser.parse()

        except Exception as e:
            logger.warning(f"Failed to get warehouse lineage from {integration.name}: {e}")

        return None

    async def _get_dbt_lineage(self, integration: IntegrationInfo) -> Optional[LineageGraph]:
        """Get lineage from dbt manifest."""
        try:
            from lineage.parsers.dbt import DbtManifestParser

            config = integration.config

            # Try to fetch manifest from dbt Cloud
            if integration.type == "DBT_CLOUD":
                from integrations.dbt import DbtCloudClient

                api_token = config.get("api_token") or config.get("access_token")
                account_id = config.get("account_id")

                if api_token and account_id:
                    client = DbtCloudClient(api_token=api_token, account_id=account_id)
                    jobs = client.get_jobs()

                    for job in jobs[:3]:  # Try first 3 jobs
                        runs = client.get_runs(job["id"], limit=1)
                        if runs and runs[0].get("status") == "Success":
                            manifest = client.get_run_artifact(runs[0]["id"], "manifest.json")
                            if manifest:
                                parser = DbtManifestParser(manifest=manifest)
                                return parser.parse()

            # If manifest provided directly in config
            elif config.get("manifest"):
                parser = DbtManifestParser(manifest=config["manifest"])
                return parser.parse()

        except Exception as e:
            logger.warning(f"Failed to get dbt lineage from {integration.name}: {e}")

        return None

    async def _get_airflow_lineage(self, integration: IntegrationInfo) -> Optional[LineageGraph]:
        """Get lineage from Airflow DAGs via OpenLineage events."""
        # OpenLineage integration would be handled by the orchestrator
        # This is a placeholder for direct Airflow API access if needed
        return None

    def _build_lineage_from_data(self, lineage_data: Dict[str, Any]) -> Optional[LineageGraph]:
        """
        Build lineage graph from pre-fetched database data.

        This is used when lineage is passed from the Next.js frontend,
        which fetches it from the Prisma database.
        """
        from lineage.graph import LineageEdge, NodeType, EdgeType

        graph = LineageGraph()

        # Map node types from database to enum
        node_type_map = {
            'table': NodeType.TABLE,
            'view': NodeType.VIEW,
            'model': NodeType.MODEL,
            'source': NodeType.SOURCE,
            'snapshot': NodeType.SNAPSHOT,
            'seed': NodeType.SEED,
            'dashboard': NodeType.DASHBOARD,
            'materialized_view': NodeType.MATERIALIZED_VIEW,
        }

        edge_type_map = {
            'depends_on': EdgeType.DEPENDS_ON,
            'derived_from': EdgeType.DERIVED_FROM,
            'joins': EdgeType.JOINS,
            'references': EdgeType.REFERENCES,
            'triggers': EdgeType.TRIGGERS,
            'populates': EdgeType.POPULATES,
        }

        # Add nodes
        for node_data in lineage_data.get('nodes', []):
            node_type_str = node_data.get('node_type', node_data.get('nodeType', 'table'))
            node_type = node_type_map.get(node_type_str.lower(), NodeType.TABLE)

            node = LineageNode(
                id=node_data['id'],
                name=node_data['name'],
                fqn=node_data.get('fqn', node_data['name']),
                node_type=node_type,
                database=node_data.get('database'),
                schema=node_data.get('schema'),
                description=node_data.get('description'),
                upstream_count=node_data.get('upstream_count', node_data.get('upstreamCount', 0)),
                downstream_count=node_data.get('downstream_count', node_data.get('downstreamCount', 0)),
            )
            graph.add_node(node)

        # Add edges
        for edge_data in lineage_data.get('edges', []):
            edge_type_str = edge_data.get('edge_type', edge_data.get('edgeType', 'depends_on'))
            edge_type = edge_type_map.get(edge_type_str.lower(), EdgeType.DEPENDS_ON)

            edge = LineageEdge(
                id=edge_data['id'],
                source_id=edge_data.get('source_id', edge_data.get('sourceId', edge_data.get('source'))),
                target_id=edge_data.get('target_id', edge_data.get('targetId', edge_data.get('target'))),
                edge_type=edge_type,
                columns=edge_data.get('columns', []),
            )
            graph.add_edge(edge)

        logger.info(f"[Lineage] Built graph from data: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
        return graph if graph.nodes else None

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

    @staticmethod
    def _find_relevant_nodes_static(
        graph: LineageGraph,
        query: str,
        limit: int = 10,
    ) -> List[LineageNode]:
        """Static version of _find_relevant_nodes for use from CopilotContext."""
        query_lower = query.lower()
        query_tokens = set(_tokenize_query(query_lower))

        if not query_tokens:
            return []

        scored: List[Tuple[int, LineageNode]] = []
        for node in graph.nodes.values():
            score = 0
            node_lower = node.name.lower()
            node_parts = set(re.findall(r'[a-z][a-z0-9]*', node_lower))

            if node_lower in query_lower:
                score += 10
            overlap = query_tokens & node_parts
            score += len(overlap) * 5
            for token in query_tokens:
                if token in node_lower and token not in node_parts:
                    score += 1
            if node.description:
                desc_lower = node.description.lower()
                for token in query_tokens:
                    if token in desc_lower:
                        score += 2

            if score > 0:
                scored.append((score, node))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in scored[:limit]]

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

        # n8n tools
        if "N8N" in integration_types:
            tools.extend([
                "get_n8n_workflows",
                "get_n8n_workflow_details",
                "get_n8n_executions",
                "get_n8n_execution_details",
                "get_n8n_recent_failures",
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

        # Coverage tools (always available — they use the lineage graph
        # to compute scores/gaps/recommendations, no extra integration needed)
        tools.extend([
            "get_coverage_report",
            "get_coverage_gaps",
            "get_node_coverage",
            "get_monitor_recommendations",
        ])

        # run_coverage_monitor needs a warehouse to execute SQL
        warehouse_types = {"SNOWFLAKE", "BIGQUERY", "POSTGRES", "REDSHIFT",
                          "SQLSERVER", "AZURE_SQL", "AZURE_SYNAPSE"}
        if integration_types & warehouse_types:
            tools.append("run_coverage_monitor")

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

        # Infrastructure tools (SSH-based server inspection)
        if "LINUX_SERVER" in integration_types:
            tools.extend([
                "check_server_health",
                "check_certificates",
                "analyze_server_logs",
                "list_server_services",
            ])

        return tools
