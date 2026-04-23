"""
Cross-Tool Edge Synthesis for Unified Lineage

Automatically creates edges across tool boundaries:
- dbt sources → warehouse tables
- dbt models → materialization targets
- BI dashboards → warehouse tables
- Views → base tables
"""

from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass
import logging
import hashlib

from .graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType, PlatformDomain
from .canonical import CanonicalResolver, CanonicalIdentity, normalize_to_canonical_fqn

logger = logging.getLogger(__name__)


@dataclass
class SynthesisStats:
    """Statistics from edge synthesis."""

    dbt_source_edges: int = 0
    dbt_model_edges: int = 0
    bi_warehouse_edges: int = 0
    view_base_edges: int = 0
    orchestrator_edges: int = 0
    ingestion_edges: int = 0
    nodes_merged: int = 0
    total_edges_created: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "dbt_source_edges": self.dbt_source_edges,
            "dbt_model_edges": self.dbt_model_edges,
            "bi_warehouse_edges": self.bi_warehouse_edges,
            "view_base_edges": self.view_base_edges,
            "orchestrator_edges": self.orchestrator_edges,
            "ingestion_edges": self.ingestion_edges,
            "nodes_merged": self.nodes_merged,
            "total_edges_created": self.total_edges_created,
        }


class CrossToolEdgeSynthesizer:
    """
    Synthesizes edges across tool boundaries.

    Edge Synthesis Rules:
    1. dbt source → warehouse table (represents)
    2. warehouse table → dbt model (derived_from, when model SELECTs FROM)
    3. dbt model → warehouse table (writes_to, materialization target)
    4. warehouse table → BI dashboard/report (reads_from)
    5. base table → view (depends_on, from view definition)
    """

    def __init__(
        self,
        graph: LineageGraph,
        resolver: CanonicalResolver = None,
        dbt_manifest: Dict[str, Any] = None,
    ):
        """
        Initialize the synthesizer.

        Args:
            graph: The lineage graph to enhance
            resolver: Canonical resolver for matching nodes
            dbt_manifest: Optional dbt manifest for source/model info
        """
        self.graph = graph
        self.resolver = resolver or CanonicalResolver()
        self.dbt_manifest = dbt_manifest or {}
        self.stats = SynthesisStats()

        # Build indexes for fast lookup
        self._build_indexes()

    def _build_indexes(self) -> None:
        """Build indexes for efficient node lookup."""
        self._by_canonical: Dict[str, List[str]] = {}  # canonical_fqn -> [node_ids]
        self._by_platform: Dict[str, Set[str]] = {}  # platform -> {node_ids}
        self._by_type: Dict[NodeType, Set[str]] = {}  # type -> {node_ids}

        for node_id, node in self.graph.nodes.items():
            # Index by platform
            platform = node.platform or "unknown"
            if platform not in self._by_platform:
                self._by_platform[platform] = set()
            self._by_platform[platform].add(node_id)

            # Index by type
            if node.node_type not in self._by_type:
                self._by_type[node.node_type] = set()
            self._by_type[node.node_type].add(node_id)

            # Index by canonical FQN
            canonical = self._get_canonical_fqn(node)
            if canonical:
                if canonical not in self._by_canonical:
                    self._by_canonical[canonical] = []
                self._by_canonical[canonical].append(node_id)

    # Platforms that are NOT warehouse types — use raw_metadata to find the real warehouse
    _NON_WAREHOUSE_PLATFORMS = {
        "dbt", "looker", "tableau", "powerbi",
        "airflow", "dagster", "prefect",
        "fivetran", "airbyte",
    }

    def _get_canonical_fqn(self, node: LineageNode) -> Optional[str]:
        """Get canonical FQN for a node."""
        # If node has a stored canonical FQN, use it
        if hasattr(node, "canonical_fqn") and node.canonical_fqn:
            return node.canonical_fqn

        # Determine actual warehouse type (dbt nodes store it in raw_metadata)
        warehouse_type = (
            node.raw_metadata.get("warehouse_type")
            or node.raw_metadata.get("loader_type")
            or node.dialect
            or (node.platform if node.platform not in self._NON_WAREHOUSE_PLATFORMS else None)
            or "bigquery"
        )
        if node.database and node.schema:
            return normalize_to_canonical_fqn(
                warehouse_type, node.database, node.schema, node.name
            )
        elif node.fqn:
            parts = node.fqn.replace("`", "").replace('"', "").split(".")
            if len(parts) >= 3:
                return normalize_to_canonical_fqn(
                    warehouse_type, parts[-3], parts[-2], parts[-1]
                )
            elif len(parts) == 2:
                return normalize_to_canonical_fqn(warehouse_type, "", parts[0], parts[1])

        return None

    def _find_matching_node(
        self, canonical_fqn: str, exclude_platforms: List[str] = None
    ) -> Optional[LineageNode]:
        """Find a node matching the canonical FQN."""
        exclude_platforms = exclude_platforms or []

        if canonical_fqn in self._by_canonical:
            for node_id in self._by_canonical[canonical_fqn]:
                node = self.graph.nodes.get(node_id)
                if node and node.platform not in exclude_platforms:
                    return node

        return None

    def _find_matching_node_fuzzy(
        self, database: str, name: str, exclude_platforms: List[str] = None
    ) -> Optional[LineageNode]:
        """
        Fallback: find by database + name when schema differs.

        Handles generate_schema_name mismatches where dbt says
        'analytics_staging' but BQ shows 'analytics'.
        """
        exclude_platforms = exclude_platforms or []
        db_lower = (database or "").lower()
        name_lower = (name or "").lower()

        for node in self.graph.nodes.values():
            if node.platform in exclude_platforms:
                continue
            if (node.database or "").lower() == db_lower and (node.name or "").lower() == name_lower:
                return node

        return None

    def _create_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        synthesized: bool = True,
        synthesis_source: str = None,
    ) -> Optional[LineageEdge]:
        """Create and add an edge to the graph."""
        # Check if edge already exists
        edge_id = hashlib.md5(f"{source_id}:{target_id}:{edge_type.value}".encode()).hexdigest()[:16]

        if edge_id in self.graph.edges:
            return None  # Edge already exists

        # Verify nodes exist
        if source_id not in self.graph.nodes or target_id not in self.graph.nodes:
            return None

        edge = LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            discovered_from=synthesis_source or "cross_tool_synthesis",
        )

        self.graph.add_edge(edge)
        self.stats.total_edges_created += 1

        return edge

    def synthesize_dbt_source_edges(self) -> int:
        """
        Create edges between dbt sources and their warehouse tables.

        dbt source represents a warehouse table, so:
        warehouse_table → dbt_source (represents)

        This allows lineage to flow from raw warehouse tables
        through dbt transformations.
        """
        edges_created = 0
        dbt_nodes = self._by_platform.get("dbt", set())

        for node_id in dbt_nodes:
            node = self.graph.nodes.get(node_id)
            if not node or node.node_type != NodeType.SOURCE:
                continue

            # Get the source's warehouse table reference
            source_info = node.raw_metadata.get("source_info", {})
            database = source_info.get("database") or node.database
            schema = source_info.get("schema") or node.schema
            table = source_info.get("identifier") or node.name

            if not (database or schema):
                continue

            # Find the matching warehouse table
            warehouse_type = (
                node.raw_metadata.get("warehouse_type")
                or source_info.get("loader_type")
                or "bigquery"
            ).lower()
            canonical = normalize_to_canonical_fqn(warehouse_type, database, schema, table)

            warehouse_node = self._find_matching_node(canonical, exclude_platforms=["dbt"])

            # Fallback: match by database + name when schema differs
            if not warehouse_node:
                warehouse_node = self._find_matching_node_fuzzy(
                    database, table, exclude_platforms=["dbt"]
                )

            if warehouse_node:
                edge = self._create_edge(
                    warehouse_node.id,
                    node_id,
                    EdgeType.DERIVED_FROM,
                    synthesis_source="dbt_source_mapping",
                )
                if edge:
                    edges_created += 1
                    logger.debug(
                        f"Synthesized edge: {warehouse_node.fqn} → {node.fqn} (dbt source)"
                    )

        self.stats.dbt_source_edges = edges_created
        return edges_created

    def synthesize_dbt_model_materialization_edges(self) -> int:
        """
        Create edges from dbt models to their materialization targets.

        When a dbt model is materialized as a table/view:
        dbt_model → warehouse_table (writes_to)
        """
        edges_created = 0
        dbt_nodes = self._by_platform.get("dbt", set())

        for node_id in dbt_nodes:
            node = self.graph.nodes.get(node_id)
            if not node or node.node_type not in (NodeType.MODEL, NodeType.SNAPSHOT):
                continue

            # Get materialization info — skip only ephemeral (no warehouse object)
            materialization = node.raw_metadata.get("materialized", "view")
            if materialization == "ephemeral":
                continue

            # Get target location
            target_database = node.raw_metadata.get("database") or node.database
            target_schema = node.raw_metadata.get("schema") or node.schema
            target_alias = node.raw_metadata.get("alias") or node.name

            if not target_schema:
                continue

            # Find the matching warehouse table
            dialect = (
                node.raw_metadata.get("warehouse_type")
                or node.dialect
                or "bigquery"
            )
            canonical = normalize_to_canonical_fqn(
                dialect, target_database, target_schema, target_alias
            )

            warehouse_node = self._find_matching_node(canonical, exclude_platforms=["dbt"])

            # Fallback: match by database + name when schema differs
            if not warehouse_node:
                warehouse_node = self._find_matching_node_fuzzy(
                    target_database, target_alias, exclude_platforms=["dbt"]
                )

            if warehouse_node:
                edge = self._create_edge(
                    node_id,
                    warehouse_node.id,
                    EdgeType.WRITES_TO,
                    synthesis_source="dbt_materialization",
                )
                if edge:
                    edges_created += 1
                    logger.debug(
                        f"Synthesized edge: {node.fqn} → {warehouse_node.fqn} (materialization)"
                    )

        self.stats.dbt_model_edges = edges_created
        return edges_created

    def synthesize_bi_warehouse_edges(self) -> int:
        """
        Create edges from warehouse tables to BI dashboards/reports.

        BI tools read from warehouse tables:
        warehouse_table → bi_dashboard (reads_from)
        """
        edges_created = 0
        bi_types = {NodeType.DASHBOARD, NodeType.REPORT, NodeType.EXPLORE, NodeType.DATASET}

        bi_node_ids = set()
        for node_type in bi_types:
            bi_node_ids.update(self._by_type.get(node_type, set()))

        for node_id in bi_node_ids:
            node = self.graph.nodes.get(node_id)
            if not node:
                continue

            # Get table references from BI tool metadata
            table_refs = self._extract_bi_table_references(node)

            for table_ref in table_refs:
                # Resolve to canonical FQN
                identity = self.resolver.resolve(
                    table_ref,
                    context={"platform": node.platform},
                    platform=node.platform,
                )

                if not identity:
                    continue

                # Find matching warehouse node
                warehouse_node = self._find_matching_node(
                    identity.canonical_fqn, exclude_platforms=["looker", "tableau", "powerbi"]
                )

                if warehouse_node:
                    edge = self._create_edge(
                        warehouse_node.id,
                        node_id,
                        EdgeType.READS_FROM,
                        synthesis_source="bi_table_reference",
                    )
                    if edge:
                        edges_created += 1
                        logger.debug(
                            f"Synthesized edge: {warehouse_node.fqn} → {node.fqn} (BI reads)"
                        )

        self.stats.bi_warehouse_edges = edges_created
        return edges_created

    def _extract_bi_table_references(self, node: LineageNode) -> List[str]:
        """Extract table references from BI tool node metadata."""
        refs = []

        # Looker explores
        if node.raw_metadata.get("explores"):
            for explore in node.raw_metadata["explores"]:
                if explore.get("from"):
                    refs.append(explore["from"])

        # Generic table references
        if node.raw_metadata.get("table_references"):
            refs.extend(node.raw_metadata["table_references"])

        # SQL-based BI tools
        if node.raw_metadata.get("sql"):
            # Could parse SQL to extract tables
            pass

        return refs

    def synthesize_view_base_table_edges(self) -> int:
        """
        Create edges from base tables to views.

        When a view is defined on a base table:
        base_table → view (depends_on)
        """
        edges_created = 0
        view_node_ids = self._by_type.get(NodeType.VIEW, set())

        for node_id in view_node_ids:
            node = self.graph.nodes.get(node_id)
            if not node:
                continue

            # Get base table references from view definition
            base_tables = node.raw_metadata.get("base_tables", [])
            view_sql = node.raw_metadata.get("view_definition", "")

            # If we have base tables listed, use them
            for base_table in base_tables:
                # Resolve to find matching node
                identity = self.resolver.resolve(
                    base_table,
                    context={
                        "warehouse_type": node.dialect,
                        "database": node.database,
                        "schema": node.schema,
                    },
                    platform=node.platform,
                )

                if identity:
                    base_node = self._find_matching_node(identity.canonical_fqn)
                    if base_node and base_node.id != node_id:
                        edge = self._create_edge(
                            base_node.id,
                            node_id,
                            EdgeType.DEPENDS_ON,
                            synthesis_source="view_definition",
                        )
                        if edge:
                            edges_created += 1

        self.stats.view_base_edges = edges_created
        return edges_created

    def synthesize_orchestrator_edges(self) -> int:
        """
        Create edges for orchestrator nodes (Airflow DAGs, Prefect flows).

        task → output_table (writes_to)
        input_table → task (reads_from)
        """
        edges_created = 0
        orchestrator_types = {NodeType.TASK, NodeType.DAG, NodeType.FLOW, NodeType.PIPELINE}

        orch_node_ids = set()
        for node_type in orchestrator_types:
            orch_node_ids.update(self._by_type.get(node_type, set()))

        for node_id in orch_node_ids:
            node = self.graph.nodes.get(node_id)
            if not node:
                continue

            # Get inputs and outputs from metadata
            inputs = node.raw_metadata.get("inputs", [])
            outputs = node.raw_metadata.get("outputs", [])

            # Create edges for inputs
            for input_ref in inputs:
                identity = self.resolver.resolve(input_ref, platform=node.platform)
                if identity:
                    input_node = self._find_matching_node(identity.canonical_fqn)
                    if input_node:
                        edge = self._create_edge(
                            input_node.id,
                            node_id,
                            EdgeType.READS_FROM,
                            synthesis_source="orchestrator_input",
                        )
                        if edge:
                            edges_created += 1

            # Create edges for outputs
            for output_ref in outputs:
                identity = self.resolver.resolve(output_ref, platform=node.platform)
                if identity:
                    output_node = self._find_matching_node(identity.canonical_fqn)
                    if output_node:
                        edge = self._create_edge(
                            node_id,
                            output_node.id,
                            EdgeType.WRITES_TO,
                            synthesis_source="orchestrator_output",
                        )
                        if edge:
                            edges_created += 1

        self.stats.orchestrator_edges = edges_created
        return edges_created

    def synthesize_ingestion_edges(self) -> int:
        """
        Create edges for ingestion tool nodes (Fivetran, Airbyte).

        Two matching paths:
        1. Synced table nodes (node_role=synced_table) → match by table name
           to warehouse tables. Creates direct synced_table → warehouse_table.
        2. Connector/source nodes → match by connector metadata to warehouse
           tables (legacy path for adapters that still emit connector nodes).

        synced_table / connector → warehouse_table (POPULATES)
        """
        from .engine.platforms import INGESTION_PLATFORMS
        edges_created = 0
        ingestion_platforms = INGESTION_PLATFORMS

        # Find synced table nodes (individual source tables from ingestion)
        synced_table_ids = set()
        # Find ingestion source/pipeline nodes (connector-level)
        ingestion_connector_ids = set()

        for node_type in (NodeType.SOURCE, NodeType.PIPELINE):
            for node_id in self._by_type.get(node_type, set()):
                node = self.graph.nodes.get(node_id)
                if node and node.platform in ingestion_platforms:
                    ingestion_connector_ids.add(node_id)

        for node_id in self._by_type.get(NodeType.TABLE, set()):
            node = self.graph.nodes.get(node_id)
            if (node and node.platform in ingestion_platforms
                    and node.raw_metadata.get("node_role") == "synced_table"):
                synced_table_ids.add(node_id)

        # Find warehouse table nodes (from any platform).
        # Include NodeType.SOURCE because dbt sources represent physical
        # warehouse tables (they have platform_domain=WAREHOUSE).
        warehouse_table_ids = set()
        for node_type in (NodeType.TABLE, NodeType.VIEW, NodeType.MATERIALIZED_VIEW, NodeType.SOURCE):
            for node_id in self._by_type.get(node_type, set()):
                node = self.graph.nodes.get(node_id)
                if not node or node.platform in ingestion_platforms:
                    continue
                # For SOURCE nodes, only include those representing warehouse
                # assets (e.g. dbt sources), not ingestion/API sources.
                if node_type == NodeType.SOURCE and node.platform_domain != PlatformDomain.WAREHOUSE:
                    continue
                warehouse_table_ids.add(node_id)

        logger.info(
            "[CrossTool] Ingestion synthesis: %d synced tables, %d connectors, %d warehouse targets",
            len(synced_table_ids), len(ingestion_connector_ids), len(warehouse_table_ids),
        )

        # Path 1: Direct synced_table → warehouse_table — container-aware matching
        # Build warehouse indexes for tiered lookup
        wh_by_name: dict[str, list[str]] = {}
        wh_by_container_name: dict[tuple[str, str], list[str]] = {}
        for table_id in warehouse_table_ids:
            node = self.graph.nodes.get(table_id)
            if node and node.name:
                name_lower = node.name.lower()
                schema_lower = (node.schema or "").lower()
                wh_by_name.setdefault(name_lower, []).append(table_id)
                if schema_lower:
                    wh_by_container_name.setdefault(
                        (schema_lower, name_lower), [],
                    ).append(table_id)

        for synced_id in synced_table_ids:
            synced_node = self.graph.nodes.get(synced_id)
            if not synced_node or not synced_node.name:
                continue

            name_lower = synced_node.name.lower()
            schema_lower = (synced_node.schema or "").lower()

            # Tier 1: Full container match (schema + name)
            if schema_lower:
                container_candidates = wh_by_container_name.get(
                    (schema_lower, name_lower), [],
                )
                for wh_id in container_candidates:
                    wh_node = self.graph.nodes.get(wh_id)
                    if not wh_node:
                        continue
                    edge = self._create_edge(
                        synced_id, wh_id,
                        EdgeType.POPULATES,
                        synthesis_source="ingestion_synced_table_container",
                    )
                    if edge:
                        edges_created += 1
                        logger.info(
                            "[CrossTool] Synthesized edge: %s → %s (synced_table, container match)",
                            synced_node.fqn, wh_node.fqn,
                        )
                continue  # Container match found or attempted; skip name-only

            # Tier 2: Name-only match — only if unique across warehouse
            name_candidates = wh_by_name.get(name_lower, [])
            if len(name_candidates) == 1:
                wh_id = name_candidates[0]
                wh_node = self.graph.nodes.get(wh_id)
                if wh_node:
                    edge = self._create_edge(
                        synced_id, wh_id,
                        EdgeType.POPULATES,
                        synthesis_source="ingestion_synced_table_name_only",
                    )
                    if edge:
                        edges_created += 1
                        logger.info(
                            "[CrossTool] Synthesized edge: %s → %s "
                            "(synced_table, name-only unique match)",
                            synced_node.fqn, wh_node.fqn,
                        )
            elif len(name_candidates) > 1:
                logger.info(
                    "[CrossTool] Skipping ambiguous synced_table match: "
                    "'%s' found in %d warehouse schemas — need container info",
                    name_lower, len(name_candidates),
                )

        # Path 2: Connector-level matching (legacy path)
        for ingestion_id in ingestion_connector_ids:
            ingestion_node = self.graph.nodes.get(ingestion_id)
            if not ingestion_node:
                continue

            connector_name = (
                ingestion_node.raw_metadata.get("connector_name")
                or ingestion_node.raw_metadata.get("connection_name")
                or ingestion_node.name
            )
            ingestion_schema = (
                ingestion_node.raw_metadata.get("schema", "")
                or ingestion_node.raw_metadata.get("connector_schema", "")
            ).lower()

            for table_id in warehouse_table_ids:
                table_node = self.graph.nodes.get(table_id)
                if not table_node:
                    continue

                if self._is_ingestion_destination(table_node, connector_name, ingestion_schema, ingestion_node, wh_by_name):
                    edge = self._create_edge(
                        ingestion_id,
                        table_id,
                        EdgeType.POPULATES,
                        synthesis_source="ingestion_connector",
                    )
                    if edge:
                        edges_created += 1
                        logger.info(
                            f"[CrossTool] Synthesized edge: {ingestion_node.fqn} → {table_node.fqn} (ingestion)"
                        )

        self.stats.ingestion_edges = edges_created
        return edges_created

    def _is_ingestion_destination(
        self,
        table_node: LineageNode,
        connector_name: str,
        ingestion_schema: str,
        ingestion_node: LineageNode,
        wh_by_name: Optional[Dict[str, list]] = None,
    ) -> bool:
        """Stack-agnostic check: was this table populated by this ingestion connector?

        Uses multiple matching strategies so that the match works regardless
        of whether nodes were merged (losing metadata) or not.

        Strategies are container-aware: name-only matching (Strategy 5) is
        only used when the table name is unique across the warehouse OR
        the connector's destination schema matches the table's schema.
        """
        meta = table_node.raw_metadata
        ingestion_platform = ingestion_node.platform

        # Strategy 1: explicit metadata — works when ingestion adapter set it
        # or when the resolver preserved it during merge (Step 7)
        table_connector = (
            meta.get("ingestion_connector")
            or meta.get("connector_name")
            or meta.get("connection_name")
            or ""
        )
        discovered_via = meta.get("discovered_via", "")
        if (
            discovered_via in ("fivetran_connector", "airbyte_connection")
            and table_connector == connector_name
        ):
            return True

        # Strategy 2: ingestion_platform metadata matches (set during merge)
        if (
            meta.get("ingestion_platform") == ingestion_platform
            and table_connector
            and table_connector == connector_name
        ):
            return True

        # Strategy 3: ingestion connector's schema matches table's schema
        # Fivetran creates schemas named after the connector (e.g., "stripe"),
        # Airbyte uses source namespace. If connector name matches table schema,
        # the table likely came from that connector.
        if (
            ingestion_schema
            and table_node.schema
            and table_node.schema.lower() == ingestion_schema
        ):
            return True

        # Strategy 4: connector name matches table schema
        # Common pattern: Fivetran connector "google_ads" → schema "google_ads"
        if (
            connector_name
            and table_node.schema
            and table_node.schema.lower() == connector_name.lower()
        ):
            return True

        # Strategy 5: table name appears in connector's synced_tables list
        # Container-aware: only match if the connector's destination schema
        # matches the table's schema, OR if the table name is unique across
        # all warehouse schemas.
        synced_tables = ingestion_node.raw_metadata.get("synced_tables", [])
        if synced_tables and table_node.name:
            table_name_lower = table_node.name.lower()
            if table_name_lower in synced_tables:
                # Check if connector declares a destination schema
                dest_schema = (
                    ingestion_node.raw_metadata.get("dest_schema", "")
                    or ingestion_node.raw_metadata.get("destination_schema", "")
                )
                if dest_schema and table_node.schema:
                    # Container-confirmed match
                    if table_node.schema.lower() == dest_schema.lower():
                        return True
                    # Container mismatch — do not match
                    return False
                # No destination schema known — check uniqueness
                if wh_by_name:
                    name_candidates = wh_by_name.get(table_name_lower, [])
                    if len(name_candidates) == 1:
                        return True  # Unique across warehouse
                    # Ambiguous — skip
                    logger.debug(
                        "[CrossTool] Skipping ambiguous synced_table match: "
                        "'%s' from connector '%s' found in %d schemas",
                        table_name_lower, connector_name, len(name_candidates),
                    )
                    return False
                # No index available — fall through to legacy behavior
                return True

        return False

    def merge_duplicate_nodes(self) -> int:
        """
        Merge nodes that refer to the same physical table.

        When multiple tools discover the same table, merge them into one node
        with combined metadata.
        """
        nodes_merged = 0

        for canonical_fqn, node_ids in self._by_canonical.items():
            if len(node_ids) <= 1:
                continue

            # Sort by priority: warehouse > dbt > bi
            def priority(node_id: str) -> int:
                node = self.graph.nodes.get(node_id)
                if not node:
                    return 99
                platform = (node.platform or "").lower()
                if platform in ("bigquery", "snowflake", "postgres", "redshift"):
                    return 1
                elif platform == "dbt":
                    return 2
                else:
                    return 3

            sorted_ids = sorted(node_ids, key=priority)
            primary_id = sorted_ids[0]
            primary_node = self.graph.nodes[primary_id]

            # Merge other nodes into primary
            for other_id in sorted_ids[1:]:
                if other_id == primary_id:
                    continue

                other_node = self.graph.nodes.get(other_id)
                if not other_node:
                    continue

                # Merge metadata
                self._merge_node_metadata(primary_node, other_node)

                # Redirect edges
                self._redirect_edges(other_id, primary_id)

                # Remove duplicate node
                del self.graph.nodes[other_id]
                nodes_merged += 1

                logger.debug(f"Merged node {other_id} into {primary_id} ({canonical_fqn})")

        self.stats.nodes_merged = nodes_merged
        return nodes_merged

    def _merge_node_metadata(self, primary: LineageNode, secondary: LineageNode) -> None:
        """Merge metadata from secondary node into primary."""
        # Prefer dbt descriptions over warehouse
        if secondary.description and not primary.description:
            primary.description = secondary.description
        elif secondary.description and secondary.platform == "dbt":
            primary.description = secondary.description

        # Prefer dbt owner
        if secondary.owner and secondary.platform == "dbt":
            primary.owner = secondary.owner

        # Merge tags
        primary.tags = list(set(primary.tags + secondary.tags))

        # Prefer warehouse row count (more accurate)
        if secondary.row_count and not primary.row_count:
            primary.row_count = secondary.row_count

        # Prefer warehouse freshness
        if secondary.last_updated and not primary.last_updated:
            primary.last_updated = secondary.last_updated

        # Merge columns (prefer warehouse schema)
        if secondary.columns and not primary.columns:
            primary.columns = secondary.columns

        # Track discovery sources
        discovered_by = set(primary.raw_metadata.get("discovered_by", [primary.platform]))
        discovered_by.add(secondary.platform)
        primary.raw_metadata["discovered_by"] = list(discovered_by)

    def _redirect_edges(self, old_id: str, new_id: str) -> None:
        """Redirect edges from old node to new node."""
        edges_to_update = []

        for edge_id, edge in self.graph.edges.items():
            if edge.source_id == old_id:
                edges_to_update.append((edge_id, "source", new_id))
            if edge.target_id == old_id:
                edges_to_update.append((edge_id, "target", new_id))

        for edge_id, field, new_value in edges_to_update:
            edge = self.graph.edges[edge_id]
            if field == "source":
                edge.source_id = new_value
            else:
                edge.target_id = new_value

    def synthesize_all(self) -> SynthesisStats:
        """Run all edge synthesis algorithms."""
        logger.info("Starting cross-tool edge synthesis...")

        # Order matters: merge duplicates first
        self.merge_duplicate_nodes()

        # Rebuild indexes after merge
        self._build_indexes()

        # Run synthesis algorithms
        self.synthesize_dbt_source_edges()
        self.synthesize_dbt_model_materialization_edges()
        self.synthesize_orchestrator_edges()
        self.synthesize_ingestion_edges()
        self.synthesize_bi_warehouse_edges()
        self.synthesize_view_base_table_edges()

        logger.info(
            f"Edge synthesis complete: {self.stats.total_edges_created} edges created, "
            f"{self.stats.nodes_merged} nodes merged"
        )

        return self.stats
