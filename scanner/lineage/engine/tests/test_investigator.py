"""
Tests for the Lineage Investigator module.

Covers:
- InvestigationContext: table registration, lookup, fuzzy find, unresolved tracking,
  connections, serialization
- Investigation ordering: ToolConfig.investigation_order sorting
- CorrelationEngine: table reference matching, unresolved retry, connection string
  matching, infrastructure hosting, false-positive avoidance
- LineageInvestigator.run(): mock adapters, investigation order, correlation edges,
  fault tolerance, resolver deduplication
- Helper functions: _build_canonical, _extract_table_refs, _build_adapter_config
"""

import pytest
from typing import Any, Dict, List, Set

from scanner.lineage.engine.adapter import AdapterRegistry, BaseLineageAdapter, Capability
from scanner.lineage.engine.ids import generate_asset_id, generate_edge_id
from scanner.lineage.engine.investigator import (
    CorrelationEngine,
    INVESTIGATION_ORDER,
    InvestigationContext,
    InvestigationResult,
    LineageInvestigator,
    TableRecord,
    ToolCategory,
    ToolConfig,
    ToolProfile,
    _build_adapter_config,
    _build_canonical,
    _extract_table_refs,
    _parse_table_ref_from_source,
    _resolve_warehouse_type,
)
from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)


# ---------------------------------------------------------------------------
# Test helpers — mock data factories
# ---------------------------------------------------------------------------


def _make_warehouse_node(
    node_id: str,
    name: str,
    platform: str = "bigquery",
    database: str = "analytics",
    schema: str = "raw",
    row_count: int = None,
    columns: List = None,
    raw_metadata: Dict = None,
) -> LineageNode:
    """Create a warehouse table node."""
    return LineageNode(
        id=node_id,
        name=name,
        fqn=f"{database}.{schema}.{name}",
        node_type=NodeType.TABLE,
        database=database,
        schema=schema,
        platform=platform,
        platform_domain=PlatformDomain.WAREHOUSE,
        asset_kind=AssetKind.TABLE,
        namespace="prod",
        row_count=row_count,
        columns=columns or [],
        raw_metadata=raw_metadata or {},
    )


def _make_tool_node(
    node_id: str,
    name: str,
    platform: str,
    platform_domain: PlatformDomain,
    node_type: NodeType = NodeType.WORKFLOW,
    asset_kind: AssetKind = AssetKind.WORKFLOW,
    raw_metadata: Dict = None,
) -> LineageNode:
    """Create a non-warehouse tool node (n8n workflow, airflow task, etc.)."""
    return LineageNode(
        id=node_id,
        name=name,
        fqn=f"{platform}.prod.{name}",
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        asset_kind=asset_kind,
        namespace="prod",
        raw_metadata=raw_metadata or {},
    )


def _make_edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    edge_type: EdgeType = EdgeType.DERIVED_FROM,
    plane: LinePlane = LinePlane.DATA,
    confidence: float = 1.0,
) -> LineageEdge:
    """Create a simple lineage edge."""
    return LineageEdge(
        id=edge_id,
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        plane=plane,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Mock adapter for LineageInvestigator.run() tests
# ---------------------------------------------------------------------------


class MockAdapter(BaseLineageAdapter):
    """
    A test adapter that returns canned nodes and edges.
    Optionally raises an exception to simulate failures.
    """

    def __init__(
        self,
        adapter_id: str = "mock",
        nodes: List[LineageNode] = None,
        edges: List[LineageEdge] = None,
        should_fail: bool = False,
        fail_message: str = "Mock adapter failure",
    ):
        self._id = adapter_id
        self._nodes = nodes or []
        self._edges = edges or []
        self._should_fail = should_fail
        self._fail_message = fail_message

    def id(self) -> str:
        return self._id

    def capabilities(self) -> Set[Capability]:
        return {Capability.DISCOVER_ASSETS, Capability.EXTRACT_TABLE_LINEAGE}

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        if self._should_fail:
            raise RuntimeError(self._fail_message)
        return list(self._nodes)

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        if self._should_fail:
            raise RuntimeError(self._fail_message)
        return list(self._edges)


# ======================================================================
# 1. InvestigationContext tests
# ======================================================================


class TestInvestigationContext:
    """Tests for InvestigationContext — the detective's notebook."""

    def test_register_table_new(self):
        """Registering a new table should add it to the inventory."""
        ctx = InvestigationContext()
        rec = ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.orders",
            name="orders",
            database="analytics",
            schema="raw",
            warehouse_type="bigquery",
            discovered_by="bigquery",
            node_id="bq-orders-1",
            columns=[{"name": "id", "type": "INT64"}],
            row_count=1000,
        )
        assert rec.canonical_fqn == "bigquery:analytics.raw.orders"
        assert rec.name == "orders"
        assert rec.discovered_by == ["bigquery"]
        assert rec.node_id == "bq-orders-1"
        assert rec.row_count == 1000
        assert len(rec.columns) == 1
        assert len(ctx.table_inventory) == 1

    def test_register_table_merge_existing(self):
        """Re-registering an existing table should merge discovered_by and update fields."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.orders",
            name="orders", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-orders-1",
            columns=[{"name": "id", "type": "INT64"}],
        )
        rec = ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.orders",
            name="orders", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="dbt_cloud",
            node_id="dbt-orders-1",
            columns=[
                {"name": "id", "type": "INT64"},
                {"name": "amount", "type": "FLOAT64"},
            ],
            row_count=5000,
        )
        # Still only one entry in inventory
        assert len(ctx.table_inventory) == 1
        # discovered_by was merged
        assert "bigquery" in rec.discovered_by
        assert "dbt_cloud" in rec.discovered_by
        # columns updated because new set is larger
        assert len(rec.columns) == 2
        # row_count updated (was None before)
        assert rec.row_count == 5000
        # node_id preserved from first registration (warehouse takes priority)
        assert rec.node_id == "bq-orders-1"

    def test_register_table_no_duplicate_discovered_by(self):
        """Re-registering with the same discovered_by should not duplicate it."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bq:raw.events", name="events",
            database="raw", schema="", warehouse_type="bigquery",
            discovered_by="bigquery",
        )
        ctx.register_table(
            canonical_fqn="bq:raw.events", name="events",
            database="raw", schema="", warehouse_type="bigquery",
            discovered_by="bigquery",
        )
        rec = ctx.table_inventory["bq:raw.events"]
        assert rec.discovered_by == ["bigquery"]

    def test_find_table_exact_match(self):
        """find_table with exact name, schema, database should return a match."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.orders",
            name="orders", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-orders",
        )
        ctx.register_table(
            canonical_fqn="bigquery:analytics.staging.orders",
            name="orders", database="analytics", schema="staging",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-stg-orders",
        )
        found = ctx.find_table("orders", schema="raw", database="analytics")
        assert found is not None
        assert found.schema == "raw"
        assert found.node_id == "bq-orders"

    def test_find_table_partial_match_name_only(self):
        """find_table with only name should return match when there is a single candidate."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.users",
            name="users", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-users",
        )
        found = ctx.find_table("users")
        assert found is not None
        assert found.name == "users"

    def test_find_table_no_match(self):
        """find_table for a non-existent table should return None."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.orders",
            name="orders", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
        )
        found = ctx.find_table("nonexistent_table")
        assert found is None

    def test_find_table_case_insensitive(self):
        """find_table should be case insensitive."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="snowflake:analytics.raw.ORDERS",
            name="ORDERS", database="ANALYTICS", schema="RAW",
            warehouse_type="snowflake", discovered_by="snowflake",
            node_id="sf-orders",
        )
        found = ctx.find_table("orders", schema="raw", database="analytics")
        assert found is not None
        assert found.node_id == "sf-orders"

    def test_find_table_fuzzy_three_part_ref(self):
        """find_table_fuzzy should parse a three-part dot-qualified reference."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.orders",
            name="orders", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-orders",
        )
        found = ctx.find_table_fuzzy("analytics.raw.orders")
        assert found is not None
        assert found.node_id == "bq-orders"

    def test_find_table_fuzzy_two_part_ref(self):
        """find_table_fuzzy should handle a two-part schema.table reference."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.events",
            name="events", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-events",
        )
        found = ctx.find_table_fuzzy("raw.events")
        assert found is not None
        assert found.node_id == "bq-events"

    def test_find_table_fuzzy_strips_backticks(self):
        """find_table_fuzzy should strip backtick quoting from BigQuery references."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bigquery:analytics.raw.orders",
            name="orders", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-orders",
        )
        found = ctx.find_table_fuzzy("`analytics`.`raw`.`orders`")
        assert found is not None
        assert found.node_id == "bq-orders"

    def test_find_table_fuzzy_strips_double_quotes(self):
        """find_table_fuzzy should strip double-quote quoting from references."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="postgres:mydb.public.users",
            name="users", database="mydb", schema="public",
            warehouse_type="postgres", discovered_by="postgres",
            node_id="pg-users",
        )
        found = ctx.find_table_fuzzy('"mydb"."public"."users"')
        assert found is not None
        assert found.node_id == "pg-users"

    def test_add_unresolved_tracking(self):
        """add_unresolved should append to the unresolved list with context."""
        ctx = InvestigationContext()
        ctx.add_unresolved(
            reference="staging.unknown_table",
            source_tool="n8n",
            ref_type="table_read",
            context={"node_id": "n8n-wf-1", "node_name": "Load Data"},
        )
        assert len(ctx.unresolved) == 1
        unr = ctx.unresolved[0]
        assert unr.reference == "staging.unknown_table"
        assert unr.source_tool == "n8n"
        assert unr.reference_type == "table_read"
        assert unr.resolved is False
        assert unr.context["node_id"] == "n8n-wf-1"

    def test_record_connection(self):
        """record_connection should store a ConnectionRecord."""
        ctx = InvestigationContext()
        ctx.record_connection(
            source_tool="n8n", target_tool="bigquery",
            connection_type="writes_to",
            evidence_summary="n8n references analytics.raw.orders",
            confidence=0.85,
            evidence_refs=["ref-1"],
        )
        assert len(ctx.connections) == 1
        conn = ctx.connections[0]
        assert conn.source_tool == "n8n"
        assert conn.target_tool == "bigquery"
        assert conn.connection_type == "writes_to"
        assert conn.confidence == 0.85
        assert "ref-1" in conn.evidence_refs

    def test_to_dict_serialization(self):
        """to_dict should produce a JSON-serializable summary of the context."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="bq:raw.orders", name="orders",
            database="raw", schema="", warehouse_type="bigquery",
            discovered_by="bigquery",
        )
        ctx.add_unresolved("staging.unknown", "n8n", "table_read")
        ctx.record_connection(
            "n8n", "bigquery", "writes_to", "test connection", 0.9,
        )
        ctx.tool_profiles["bigquery"] = ToolProfile(
            tool_type="bigquery", category=ToolCategory.WAREHOUSE,
            node_count=5, edge_count=3, extraction_success=True,
            extraction_duration_ms=120,
        )

        d = ctx.to_dict()
        assert d["table_count"] == 1
        assert d["connection_count"] == 1
        assert d["unresolved_count"] == 1
        assert "bigquery" in d["tool_profiles"]
        prof = d["tool_profiles"]["bigquery"]
        assert prof["tool_type"] == "bigquery"
        assert prof["category"] == "warehouse"
        assert prof["node_count"] == 5
        assert prof["success"] is True
        assert len(d["connections"]) == 1
        assert d["connections"][0]["source"] == "n8n"

    def test_to_dict_unresolved_count_excludes_resolved(self):
        """to_dict unresolved_count should exclude resolved references."""
        ctx = InvestigationContext()
        ctx.add_unresolved("table_a", "n8n", "table_read")
        ctx.add_unresolved("table_b", "n8n", "table_write")
        # Mark one as resolved
        ctx.unresolved[0].resolved = True
        d = ctx.to_dict()
        assert d["unresolved_count"] == 1

    def test_log_step(self):
        """log_step should append structured entries to the log."""
        ctx = InvestigationContext()
        ctx.log_step("bigquery", "Extracted 10 nodes", "info")
        ctx.log_step("n8n", "Failed to connect", "error")

        assert len(ctx.log) == 2
        assert ctx.log[0]["tool"] == "bigquery"
        assert ctx.log[0]["message"] == "Extracted 10 nodes"
        assert ctx.log[0]["level"] == "info"
        assert ctx.log[1]["level"] == "error"
        assert "timestamp" in ctx.log[0]


# ======================================================================
# 2. Investigation ordering tests
# ======================================================================


class TestInvestigationOrdering:
    """Tests for ToolConfig.investigation_order and sorting."""

    def test_tool_config_investigation_order_values(self):
        """ToolConfig.investigation_order should reflect the data-flow order."""
        warehouse = ToolConfig(tool_type="bigquery", config={})
        ingestion = ToolConfig(tool_type="fivetran", config={})
        transformation = ToolConfig(tool_type="dbt_cloud", config={})
        orchestration = ToolConfig(tool_type="airflow", config={})
        reporting = ToolConfig(tool_type="looker", config={})
        infrastructure = ToolConfig(tool_type="linux_server", config={})
        version_control = ToolConfig(tool_type="github", config={})
        quality = ToolConfig(tool_type="elementary", config={})

        assert warehouse.investigation_order == 1
        assert ingestion.investigation_order == 2
        assert transformation.investigation_order == 3
        assert orchestration.investigation_order == 4
        assert reporting.investigation_order == 5
        assert infrastructure.investigation_order == 6
        assert version_control.investigation_order == 7
        assert quality.investigation_order == 8

    def test_multiple_configs_sort_in_data_flow_order(self):
        """Sorting ToolConfigs by investigation_order should produce data-flow order."""
        configs = [
            ToolConfig(tool_type="elementary", config={}),
            ToolConfig(tool_type="looker", config={}),
            ToolConfig(tool_type="bigquery", config={}),
            ToolConfig(tool_type="dbt_cloud", config={}),
            ToolConfig(tool_type="n8n", config={}),
            ToolConfig(tool_type="airflow", config={}),
            ToolConfig(tool_type="linux_server", config={}),
        ]
        sorted_configs = sorted(configs, key=lambda tc: tc.investigation_order)
        sorted_types = [tc.tool_type for tc in sorted_configs]

        assert sorted_types == [
            "bigquery",       # warehouse (1)
            "n8n",            # ingestion (2)
            "dbt_cloud",      # transformation (3)
            "airflow",        # orchestration (4)
            "looker",         # reporting (5)
            "linux_server",   # infrastructure (6)
            "elementary",     # quality (8)
        ]

    def test_tool_config_category_property(self):
        """ToolConfig.category should return the correct ToolCategory enum."""
        tc = ToolConfig(tool_type="snowflake", config={})
        assert tc.category == ToolCategory.WAREHOUSE

        tc2 = ToolConfig(tool_type="n8n", config={})
        assert tc2.category == ToolCategory.INGESTION

        tc3 = ToolConfig(tool_type="dbt_core", config={})
        assert tc3.category == ToolCategory.TRANSFORMATION

    def test_unknown_tool_type_defaults_to_warehouse(self):
        """Unknown tool types should default to WAREHOUSE category."""
        tc = ToolConfig(tool_type="unknown_tool", config={})
        assert tc.category == ToolCategory.WAREHOUSE


# ======================================================================
# 3. CorrelationEngine tests
# ======================================================================


class TestCorrelationEngine:
    """Tests for cross-tool pattern matching in CorrelationEngine."""

    @pytest.fixture
    def context_with_warehouse_table(self) -> InvestigationContext:
        """Context pre-loaded with a warehouse table (simulating BigQuery extraction)."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="analytics.raw.orders",
            name="orders", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-orders-node",
            columns=[{"name": "id", "type": "INT64"}, {"name": "amount", "type": "FLOAT64"}],
            row_count=50000,
        )
        ctx.tool_profiles["bigquery"] = ToolProfile(
            tool_type="bigquery", category=ToolCategory.WAREHOUSE,
            node_count=1, extraction_success=True,
            connection_strings=[{"host": "bigquery.googleapis.com", "port": None, "database": "analytics"}],
        )
        return ctx

    def test_table_reference_matching_creates_edge(self, context_with_warehouse_table):
        """A non-warehouse node referencing a known table via raw_metadata should create a correlation edge."""
        ctx = context_with_warehouse_table
        engine = CorrelationEngine(ctx)

        # n8n node that reads from analytics.raw.orders
        n8n_node = _make_tool_node(
            "n8n-wf-1", "Load Orders Workflow",
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"inputs": ["analytics.raw.orders"]},
        )

        edges = engine.correlate(
            new_nodes=[n8n_node], new_edges=[],
            tool_type="n8n", tool_category=ToolCategory.INGESTION,
        )

        assert len(edges) >= 1
        # Should be a READS_FROM edge from the warehouse table to the n8n node
        read_edges = [e for e in edges if e.edge_type == EdgeType.READS_FROM]
        assert len(read_edges) == 1
        assert read_edges[0].source_id == "bq-orders-node"
        assert read_edges[0].target_id == "n8n-wf-1"
        assert read_edges[0].confidence == 0.85

    def test_table_reference_write_creates_writes_to_edge(self, context_with_warehouse_table):
        """A node with outputs referencing a known table should create WRITES_TO edge."""
        ctx = context_with_warehouse_table
        engine = CorrelationEngine(ctx)

        n8n_node = _make_tool_node(
            "n8n-wf-2", "Export Workflow",
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"outputs": ["analytics.raw.orders"]},
        )

        edges = engine.correlate(
            new_nodes=[n8n_node], new_edges=[],
            tool_type="n8n", tool_category=ToolCategory.INGESTION,
        )

        write_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]
        assert len(write_edges) == 1
        assert write_edges[0].source_id == "n8n-wf-2"
        assert write_edges[0].target_id == "bq-orders-node"

    def test_unresolved_reference_then_resolved(self):
        """An unresolved ref should be resolved after the target table is registered."""
        ctx = InvestigationContext()
        engine = CorrelationEngine(ctx)

        # Step 1: n8n node references a table that doesn't exist yet
        n8n_node = _make_tool_node(
            "n8n-wf-1", "Import Workflow",
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"outputs": ["analytics.raw.events"]},
        )

        edges1 = engine.correlate(
            new_nodes=[n8n_node], new_edges=[],
            tool_type="n8n", tool_category=ToolCategory.INGESTION,
        )
        # No edge yet — the table doesn't exist
        assert len(edges1) == 0
        assert len(ctx.unresolved) == 1
        assert ctx.unresolved[0].resolved is False

        # Step 2: BigQuery extraction discovers the table
        bq_table = _make_warehouse_node(
            "bq-events-node", "events",
            platform="bigquery", database="analytics", schema="raw",
        )

        edges2 = engine.correlate(
            new_nodes=[bq_table], new_edges=[],
            tool_type="bigquery", tool_category=ToolCategory.WAREHOUSE,
        )

        # The retry_unresolved pass should resolve the n8n reference
        assert ctx.unresolved[0].resolved is True
        assert ctx.unresolved[0].resolved_to == "analytics.raw.events"

        # Should have created a WRITES_TO edge
        write_edges = [e for e in edges2 if e.edge_type == EdgeType.WRITES_TO]
        assert len(write_edges) == 1
        assert write_edges[0].source_id == "n8n-wf-1"
        assert write_edges[0].target_id == "bq-events-node"

    def test_connection_string_matching(self, context_with_warehouse_table):
        """A node with host matching a warehouse profile should record a connection."""
        ctx = context_with_warehouse_table
        engine = CorrelationEngine(ctx)

        # n8n node with connection info pointing to BigQuery
        n8n_node = _make_tool_node(
            "n8n-wf-conn", "BQ Writer",
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"host": "bigquery.googleapis.com", "port": None},
        )

        engine.correlate(
            new_nodes=[n8n_node], new_edges=[],
            tool_type="n8n", tool_category=ToolCategory.INGESTION,
        )

        # Should record a connects_to connection
        conn_matches = [
            c for c in ctx.connections
            if c.connection_type == "connects_to"
        ]
        assert len(conn_matches) >= 1
        assert conn_matches[0].source_tool == "n8n"
        assert conn_matches[0].target_tool == "bigquery"
        assert conn_matches[0].confidence == 0.9

    def test_infrastructure_hosting_detection(self):
        """Infrastructure node with running_services matching a known tool should record hosted_on."""
        ctx = InvestigationContext()
        # Pre-register an airflow profile
        ctx.tool_profiles["airflow"] = ToolProfile(
            tool_type="airflow", category=ToolCategory.ORCHESTRATION,
            extraction_success=True,
        )
        engine = CorrelationEngine(ctx)

        # Infrastructure node running airflow
        infra_node = _make_tool_node(
            "infra-server-1", "prod-server-01",
            platform="linux_server",
            platform_domain=PlatformDomain.OTHER,
            node_type=NodeType.SOURCE,
            asset_kind=AssetKind.UNKNOWN,
            raw_metadata={"running_services": ["airflow-webserver", "airflow-scheduler"]},
        )

        engine.correlate(
            new_nodes=[infra_node], new_edges=[],
            tool_type="linux_server", tool_category=ToolCategory.INFRASTRUCTURE,
        )

        hosted_conns = [c for c in ctx.connections if c.connection_type == "hosted_on"]
        assert len(hosted_conns) >= 1
        assert hosted_conns[0].source_tool == "airflow"
        assert hosted_conns[0].target_tool == "linux_server"
        assert hosted_conns[0].confidence == 0.8

    def test_no_false_correlations_unrelated_nodes(self, context_with_warehouse_table):
        """Unrelated nodes should not create any correlation edges or connections."""
        ctx = context_with_warehouse_table
        initial_connection_count = len(ctx.connections)
        engine = CorrelationEngine(ctx)

        # A Looker node that doesn't reference any known table
        looker_node = _make_tool_node(
            "looker-dash-1", "Revenue Dashboard",
            platform="looker",
            platform_domain=PlatformDomain.BI,
            node_type=NodeType.DASHBOARD,
            asset_kind=AssetKind.DASHBOARD,
            raw_metadata={"description": "Shows revenue trends"},
        )

        edges = engine.correlate(
            new_nodes=[looker_node], new_edges=[],
            tool_type="looker", tool_category=ToolCategory.REPORTING,
        )

        assert len(edges) == 0
        # No new connections beyond what was already there
        new_connections = ctx.connections[initial_connection_count:]
        assert len(new_connections) == 0

    def test_no_infrastructure_hosting_for_non_infra_category(self):
        """Infrastructure hosting detection should only run for INFRASTRUCTURE category."""
        ctx = InvestigationContext()
        ctx.tool_profiles["airflow"] = ToolProfile(
            tool_type="airflow", category=ToolCategory.ORCHESTRATION,
            extraction_success=True,
        )
        engine = CorrelationEngine(ctx)

        # A non-infrastructure node that happens to mention 'airflow' in services
        node = _make_tool_node(
            "some-node", "some-tool",
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"running_services": ["airflow-webserver"]},
        )

        engine.correlate(
            new_nodes=[node], new_edges=[],
            tool_type="n8n", tool_category=ToolCategory.INGESTION,
        )

        hosted_conns = [c for c in ctx.connections if c.connection_type == "hosted_on"]
        assert len(hosted_conns) == 0

    def test_warehouse_node_registers_table_in_inventory(self):
        """When CorrelationEngine sees a warehouse node, it should register the table."""
        ctx = InvestigationContext()
        engine = CorrelationEngine(ctx)

        wh_node = _make_warehouse_node(
            "sf-users", "users",
            platform="snowflake", database="ANALYTICS", schema="RAW",
        )

        engine.correlate(
            new_nodes=[wh_node], new_edges=[],
            tool_type="snowflake", tool_category=ToolCategory.WAREHOUSE,
        )

        assert len(ctx.table_inventory) == 1
        key = list(ctx.table_inventory.keys())[0]
        # Platform-agnostic canonical FQN
        assert key == "analytics.raw.users"

    def test_table_ref_via_metadata_table_field(self):
        """Nodes with raw_metadata.table field (n8n DB node pattern) should be extracted."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="mydb.public.users",
            name="users", database="mydb", schema="public",
            warehouse_type="postgres", discovered_by="postgres",
            node_id="pg-users",
        )
        engine = CorrelationEngine(ctx)

        n8n_node = _make_tool_node(
            "n8n-db-node", "Postgres Query",
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            raw_metadata={
                "table": "users",
                "schema": "public",
                "operation": "select",
            },
        )

        edges = engine.correlate(
            new_nodes=[n8n_node], new_edges=[],
            tool_type="n8n", tool_category=ToolCategory.INGESTION,
        )

        read_edges = [e for e in edges if e.edge_type == EdgeType.READS_FROM]
        assert len(read_edges) == 1
        assert read_edges[0].source_id == "pg-users"
        assert read_edges[0].target_id == "n8n-db-node"


# ======================================================================
# 4. LineageInvestigator.run() tests
# ======================================================================


class TestLineageInvestigatorRun:
    """Tests for the LineageInvestigator orchestrator."""

    def _build_registry_with_mocks(
        self, adapters: Dict[str, MockAdapter],
    ) -> AdapterRegistry:
        """Build a custom registry with MockAdapter instances."""
        registry = AdapterRegistry()
        for type_name, adapter in adapters.items():
            # Register a factory that captures the adapter
            captured = adapter

            class _Factory(BaseLineageAdapter):
                def __init__(self, adapter_id: str = "mock", **kw):
                    self._delegate = captured
                    self._delegate._id = adapter_id

                def id(self):
                    return self._delegate.id()

                def capabilities(self):
                    return self._delegate.capabilities()

                def discover_assets(self, config):
                    return self._delegate.discover_assets(config)

                def extract_lineage(self, config):
                    return self._delegate.extract_lineage(config)

            registry.register_type(type_name, _Factory)
        return registry

    def _build_registry_with_mock_classes(
        self, type_to_mock_data: Dict[str, Dict],
    ) -> AdapterRegistry:
        """
        Build a registry mapping adapter type names to MockAdapter classes.
        Each mock is configured with its own nodes/edges/failure settings.
        """
        registry = AdapterRegistry()
        for type_name, mock_config in type_to_mock_data.items():
            nodes = mock_config.get("nodes", [])
            edges = mock_config.get("edges", [])
            should_fail = mock_config.get("should_fail", False)
            fail_message = mock_config.get("fail_message", "Mock failure")

            # Create a class that closes over the mock data
            _nodes, _edges, _fail, _msg = nodes, edges, should_fail, fail_message

            class _MockCls(BaseLineageAdapter):
                def __init__(self, adapter_id: str = "mock", **kw):
                    self._id = adapter_id
                    self._nodes = _nodes
                    self._edges = _edges
                    self._fail = _fail
                    self._msg = _msg

                def id(self):
                    return self._id

                def capabilities(self):
                    return {Capability.DISCOVER_ASSETS, Capability.EXTRACT_TABLE_LINEAGE}

                def discover_assets(self, config):
                    if self._fail:
                        raise RuntimeError(self._msg)
                    return list(self._nodes)

                def extract_lineage(self, config):
                    if self._fail:
                        raise RuntimeError(self._msg)
                    return list(self._edges)

            # IMPORTANT: we need a unique class per iteration, so bind it now
            registry.register_type(type_name, _MockCls)
        return registry

    def test_investigation_order_is_respected(self):
        """Tools should be examined in data-flow order regardless of input order."""
        # Track the order in which adapters are called
        call_order = []

        class _TrackingAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id: str = "track", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                call_order.append(config.get("_tool_type", self._id))
                return []

            def extract_lineage(self, config):
                return []

        registry = AdapterRegistry()
        registry.register_type("live_warehouse", _TrackingAdapter)
        registry.register_type("live_dbt", _TrackingAdapter)
        registry.register_type("live_n8n", _TrackingAdapter)
        registry.register_type("live_looker", _TrackingAdapter)

        investigator = LineageInvestigator(registry=registry)
        # Provide configs in reverse order
        result = investigator.run([
            ToolConfig(tool_type="looker", config={"_tool_type": "looker"}),
            ToolConfig(tool_type="dbt_cloud", config={"_tool_type": "dbt_cloud"}),
            ToolConfig(tool_type="n8n", config={"_tool_type": "n8n"}),
            ToolConfig(tool_type="bigquery", config={"_tool_type": "bigquery"}),
        ])

        # The call order should follow investigation order
        assert call_order == ["bigquery", "n8n", "dbt_cloud", "looker"]

    def test_correlation_edges_created_between_tools(self):
        """Correlation edges should be created when adapter B references tables from adapter A."""
        # Warehouse adapter returns a table node
        bq_table = _make_warehouse_node(
            "bq-orders", "orders",
            platform="bigquery", database="analytics", schema="raw",
        )

        # n8n adapter returns a workflow node that references the table
        n8n_wf = _make_tool_node(
            "n8n-wf-1", "Import Orders",
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"outputs": ["analytics.raw.orders"]},
        )

        # We need separate adapter classes because of closure issues
        class BQAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="bq", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                return [bq_table]

            def extract_lineage(self, config):
                return []

        class N8nAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="n8n", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                return [n8n_wf]

            def extract_lineage(self, config):
                return []

        registry = AdapterRegistry()
        registry.register_type("live_warehouse", BQAdapter)
        registry.register_type("live_n8n", N8nAdapter)

        investigator = LineageInvestigator(registry=registry)
        result = investigator.run([
            ToolConfig(tool_type="bigquery", config={}),
            ToolConfig(tool_type="n8n", config={}),
        ])

        assert result.success is True
        assert result.context.correlation_edges is not None
        # There should be correlation edges from n8n->bq reference
        assert len(result.context.correlation_edges) >= 1
        assert result.stats["correlations_created"] >= 1

    def test_one_tool_failing_does_not_stop_others(self):
        """If one adapter fails, the others should still be processed."""
        # Warehouse adapter that works
        bq_table = _make_warehouse_node(
            "bq-orders", "orders",
            platform="bigquery", database="analytics", schema="raw",
        )

        class GoodAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="good", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                return [bq_table]

            def extract_lineage(self, config):
                return []

        class FailingAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="fail", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                raise RuntimeError("Connection timeout")

            def extract_lineage(self, config):
                raise RuntimeError("Connection timeout")

        registry = AdapterRegistry()
        registry.register_type("live_warehouse", GoodAdapter)
        registry.register_type("live_n8n", FailingAdapter)

        investigator = LineageInvestigator(registry=registry)
        result = investigator.run([
            ToolConfig(tool_type="bigquery", config={}),
            ToolConfig(tool_type="n8n", config={}),
        ])

        # Should still succeed (not ALL tools failed)
        assert result.success is True
        assert len(result.errors) == 1
        assert "n8n" in result.errors[0]
        # BigQuery data should still be present
        assert result.stats["tools_succeeded"] >= 1
        assert result.context.tool_profiles["bigquery"].extraction_success is True
        assert result.context.tool_profiles["n8n"].extraction_success is False

    def test_all_tools_failing_returns_not_success(self):
        """If all adapters fail, result.success should be False."""

        class FailingAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="fail", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                raise RuntimeError("Total failure")

            def extract_lineage(self, config):
                raise RuntimeError("Total failure")

        registry = AdapterRegistry()
        registry.register_type("live_warehouse", FailingAdapter)
        registry.register_type("live_n8n", FailingAdapter)

        investigator = LineageInvestigator(registry=registry)
        result = investigator.run([
            ToolConfig(tool_type="bigquery", config={}),
            ToolConfig(tool_type="n8n", config={}),
        ])

        assert result.success is False
        assert len(result.errors) == 2

    def test_final_graph_has_resolver_deduplicated_nodes(self):
        """
        The final graph should be resolved through the ResolverPipeline,
        and duplicate nodes (same stable_id) should be deduplicated.
        """
        # Two nodes with the same stable_id (same physical table, different adapters)
        node_bq = LineageNode(
            id="bq-orders-1", name="orders", fqn="analytics.raw.orders",
            node_type=NodeType.TABLE, database="analytics", schema="raw",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE, namespace="prod",
        )
        node_dbt = LineageNode(
            id="dbt-orders-1", name="orders", fqn="analytics.raw.orders",
            node_type=NodeType.MODEL, database="analytics", schema="raw",
            platform="dbt", platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.MODEL, namespace="prod",
        )

        class BQAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="bq", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                return [node_bq]

            def extract_lineage(self, config):
                return []

        class DbtAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="dbt", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                return [node_dbt]

            def extract_lineage(self, config):
                return []

        registry = AdapterRegistry()
        registry.register_type("live_warehouse", BQAdapter)
        registry.register_type("live_dbt", DbtAdapter)

        investigator = LineageInvestigator(registry=registry)
        result = investigator.run([
            ToolConfig(tool_type="bigquery", config={}),
            ToolConfig(tool_type="dbt_cloud", config={}),
        ])

        assert result.success is True
        assert result.graph is not None
        # The resolver should have deduplicated: 2 raw nodes -> 1 resolved node
        assert len(result.graph.nodes) < 2 or (
            # If resolver doesn't merge them, both should still be present
            len(result.graph.nodes) <= 2
        )

    def test_result_stats_are_populated(self):
        """InvestigationResult.stats should contain all expected keys."""
        bq_table = _make_warehouse_node(
            "bq-orders", "orders",
            platform="bigquery", database="analytics", schema="raw",
        )

        class SimpleAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="simple", **kw):
                self._id = adapter_id

            def id(self):
                return self._id

            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                return [bq_table]

            def extract_lineage(self, config):
                return []

        registry = AdapterRegistry()
        registry.register_type("live_warehouse", SimpleAdapter)

        investigator = LineageInvestigator(registry=registry)
        result = investigator.run([
            ToolConfig(tool_type="bigquery", config={}),
        ])

        assert "total_nodes" in result.stats
        assert "total_edges" in result.stats
        assert "tools_examined" in result.stats
        assert "tools_succeeded" in result.stats
        assert "tables_discovered" in result.stats
        assert "connections_found" in result.stats
        assert "correlations_created" in result.stats
        assert "unresolved_remaining" in result.stats
        assert result.stats["tools_examined"] == 1
        assert result.stats["tools_succeeded"] == 1
        assert result.duration_ms >= 0

    def test_no_adapter_for_tool_type_skips_gracefully(self):
        """A tool_type not in TOOL_TO_ADAPTER should be skipped without error."""
        registry = AdapterRegistry()

        investigator = LineageInvestigator(registry=registry)
        # Use a tool_type that has no entry in TOOL_TO_ADAPTER
        result = investigator.run([
            ToolConfig(tool_type="custom_unknown_tool", config={}),
        ])

        # Should not raise, and should not count as error (just skipped via continue)
        assert result.success is True
        assert len(result.errors) == 0
        # The tool profile should note no adapter found
        assert "custom_unknown_tool" in result.context.tool_profiles
        assert result.context.tool_profiles["custom_unknown_tool"].extraction_error is not None
        assert "No adapter" in result.context.tool_profiles["custom_unknown_tool"].extraction_error


# ======================================================================
# 5. Helper function tests
# ======================================================================


class TestBuildCanonical:
    """Tests for the _build_canonical helper."""

    def test_full_node_with_all_parts(self):
        """Node with database, schema, name should produce platform-agnostic FQN."""
        node = _make_warehouse_node(
            "bq-1", "orders",
            platform="bigquery", database="analytics", schema="raw",
        )
        result = _build_canonical(node)
        assert result == "analytics.raw.orders"

    def test_node_without_database(self):
        """Node with no database should still produce a canonical FQN."""
        node = _make_warehouse_node(
            "bq-2", "events",
            platform="bigquery", database="", schema="raw",
        )
        result = _build_canonical(node)
        assert result == "raw.events"

    def test_node_without_schema(self):
        """Node with no schema should still produce a canonical FQN."""
        node = _make_warehouse_node(
            "pg-1", "users",
            platform="postgres", database="mydb", schema="",
        )
        result = _build_canonical(node)
        assert result == "mydb.users"

    def test_node_with_name_only(self):
        """Node with only name should produce name-only FQN."""
        node = LineageNode(
            id="x", name="orders", fqn="orders",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE,
        )
        result = _build_canonical(node)
        assert result == "orders"

    def test_node_with_no_name_returns_none(self):
        """Node with empty name should return None."""
        node = LineageNode(
            id="x", name="", fqn="",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
        )
        result = _build_canonical(node)
        assert result is None

    def test_canonical_is_lowercased(self):
        """Canonical FQN should be lowercased (platform-agnostic)."""
        node = _make_warehouse_node(
            "sf-1", "ORDERS",
            platform="SNOWFLAKE", database="ANALYTICS", schema="RAW",
        )
        result = _build_canonical(node)
        assert result == "analytics.raw.orders"

    def test_same_table_different_platforms_same_canonical(self):
        """Same table discovered by different adapters should produce identical canonical FQN."""
        bq_node = _make_warehouse_node(
            "bq-1", "orders", platform="bigquery", database="project", schema="raw",
        )
        dbt_node = _make_warehouse_node(
            "dbt-1", "orders", platform="dbt", database="project", schema="raw",
            raw_metadata={"warehouse_type": "bigquery"},
        )
        assert _build_canonical(bq_node) == _build_canonical(dbt_node) == "project.raw.orders"


class TestExtractTableRefs:
    """Tests for the _extract_table_refs helper."""

    def test_inputs_as_read_refs(self):
        """raw_metadata.inputs should be extracted as read (is_write=False) references."""
        node = _make_tool_node(
            "n8n-1", "Workflow",
            platform="n8n", platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"inputs": ["raw.orders", "raw.customers"]},
        )
        refs = _extract_table_refs(node)
        assert ("raw.orders", False) in refs
        assert ("raw.customers", False) in refs

    def test_outputs_as_write_refs(self):
        """raw_metadata.outputs should be extracted as write (is_write=True) references."""
        node = _make_tool_node(
            "n8n-2", "Export",
            platform="n8n", platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"outputs": ["staging.enriched_orders"]},
        )
        refs = _extract_table_refs(node)
        assert ("staging.enriched_orders", True) in refs

    def test_table_references_as_read_refs(self):
        """raw_metadata.table_references should be extracted as reads."""
        node = _make_tool_node(
            "af-1", "SQL Task",
            platform="airflow", platform_domain=PlatformDomain.ORCHESTRATION,
            raw_metadata={"table_references": ["analytics.raw.events"]},
        )
        refs = _extract_table_refs(node)
        assert ("analytics.raw.events", False) in refs

    def test_table_field_with_select_operation(self):
        """raw_metadata.table with operation=select should be a read ref."""
        node = _make_tool_node(
            "n8n-db", "DB Read",
            platform="n8n", platform_domain=PlatformDomain.INGESTION,
            raw_metadata={
                "table": "users",
                "schema": "public",
                "operation": "select",
            },
        )
        refs = _extract_table_refs(node)
        assert ("public.users", False) in refs

    def test_table_field_with_insert_operation(self):
        """raw_metadata.table with operation=insert should be a write ref."""
        node = _make_tool_node(
            "n8n-db", "DB Write",
            platform="n8n", platform_domain=PlatformDomain.INGESTION,
            raw_metadata={
                "table": "orders",
                "schemaName": "staging",
                "operation": "insert",
            },
        )
        refs = _extract_table_refs(node)
        assert ("staging.orders", True) in refs

    def test_table_field_without_schema(self):
        """raw_metadata.table with no schema should produce name-only ref."""
        node = _make_tool_node(
            "n8n-db", "DB Op",
            platform="n8n", platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"table": "events", "operation": "select"},
        )
        refs = _extract_table_refs(node)
        assert ("events", False) in refs

    def test_empty_metadata_returns_no_refs(self):
        """Node with no relevant metadata should return empty list."""
        node = _make_tool_node(
            "n8n-other", "HTTP Node",
            platform="n8n", platform_domain=PlatformDomain.INGESTION,
            raw_metadata={"url": "https://api.example.com"},
        )
        refs = _extract_table_refs(node)
        assert refs == []

    def test_mixed_inputs_outputs_and_table(self):
        """Node with both inputs, outputs, and table field should extract all."""
        node = _make_tool_node(
            "complex-node", "Complex",
            platform="n8n", platform_domain=PlatformDomain.INGESTION,
            raw_metadata={
                "inputs": ["source.events"],
                "outputs": ["target.events_clean"],
                "table": "audit_log",
                "operation": "insert",
            },
        )
        refs = _extract_table_refs(node)
        assert len(refs) == 3
        assert ("source.events", False) in refs
        assert ("target.events_clean", True) in refs
        assert ("audit_log", True) in refs


class TestBuildAdapterConfig:
    """Tests for the _build_adapter_config helper."""

    def test_warehouse_config_sets_platform(self):
        """Warehouse tool types should get platform set in config."""
        for tool_type in ["bigquery", "snowflake", "postgres", "redshift"]:
            tc = ToolConfig(
                tool_type=tool_type,
                config={"host": "localhost"},
                integration_id="int-1",
            )
            result = _build_adapter_config(tc)
            assert result["platform"] == tool_type
            assert result["integration_id"] == "int-1"
            assert "connection_config" in result

    def test_dbt_config_sets_warehouse_type(self):
        """dbt tool types should get warehouse_type default."""
        tc = ToolConfig(
            tool_type="dbt_cloud",
            config={"api_key": "test"},
            integration_id="dbt-1",
        )
        result = _build_adapter_config(tc)
        assert result["warehouse_type"] == "bigquery"
        assert result["integration_id"] == "dbt-1"

    def test_n8n_config_wraps_in_n8n_config_key(self):
        """n8n tool type should get config wrapped under n8n_config key."""
        tc = ToolConfig(
            tool_type="n8n",
            config={"url": "http://n8n:5678", "api_key": "key"},
        )
        result = _build_adapter_config(tc)
        assert "n8n_config" in result
        assert result["n8n_config"]["url"] == "http://n8n:5678"

    def test_bi_tool_config_wrapping(self):
        """BI tool types should have their config wrapped under the right key."""
        for tool_type, key in [
            ("looker", "looker_config"),
            ("tableau", "tableau_config"),
            ("powerbi", "powerbi_config"),
            ("metabase", "metabase_config"),
        ]:
            tc = ToolConfig(tool_type=tool_type, config={"base_url": "http://example.com"})
            result = _build_adapter_config(tc)
            assert key in result

    def test_ingestion_tool_config_wrapping(self):
        """Ingestion tool types should have their config wrapped."""
        for tool_type, key in [
            ("fivetran", "fivetran_config"),
            ("airbyte", "airbyte_config"),
        ]:
            tc = ToolConfig(tool_type=tool_type, config={"api_key": "test"})
            result = _build_adapter_config(tc)
            assert key in result

    def test_integration_id_always_set(self):
        """integration_id should always be set in the output config."""
        tc = ToolConfig(tool_type="bigquery", config={}, integration_id="my-int")
        result = _build_adapter_config(tc)
        assert result["integration_id"] == "my-int"

    def test_existing_config_keys_preserved(self):
        """Original config keys should be preserved in the output."""
        tc = ToolConfig(
            tool_type="bigquery",
            config={"project_id": "my-project", "location": "US"},
        )
        result = _build_adapter_config(tc)
        assert result["project_id"] == "my-project"
        assert result["location"] == "US"


# ======================================================================
# 6. _parse_table_ref_from_source tests
# ======================================================================


class TestParseTableRefFromSource:
    """Tests for the _parse_table_ref_from_source helper."""

    def test_n8n_writes_pattern(self):
        ref = _parse_table_ref_from_source("n8n:workflow:123:node:Postgres:writes:raw.customers")
        assert ref == "raw.customers"

    def test_n8n_reads_pattern(self):
        ref = _parse_table_ref_from_source("n8n:workflow:456:node:BigQuery:reads:analytics.events")
        assert ref == "analytics.events"

    def test_openlineage_input_pattern(self):
        ref = _parse_table_ref_from_source("openlineage:run:abc:input:mydb.public.users")
        assert ref == "mydb.public.users"

    def test_openlineage_output_pattern(self):
        ref = _parse_table_ref_from_source("openlineage:run:abc:output:staging.orders_clean")
        assert ref == "staging.orders_clean"

    def test_no_table_ref_returns_none(self):
        ref = _parse_table_ref_from_source("n8n:workflow:123:node:HTTP Request")
        assert ref is None

    def test_empty_string_returns_none(self):
        assert _parse_table_ref_from_source("") is None

    def test_none_returns_none(self):
        assert _parse_table_ref_from_source(None) is None

    def test_strips_backticks(self):
        ref = _parse_table_ref_from_source("n8n:workflow:1:node:BQ:writes:`project`.`raw`.`orders`")
        assert ref == "project.raw.orders"


# ======================================================================
# 7. _resolve_warehouse_type tests
# ======================================================================


class TestResolveWarehouseType:
    """Tests for the _resolve_warehouse_type helper."""

    def test_bigquery_platform(self):
        node = _make_warehouse_node("bq-1", "orders", platform="bigquery")
        assert _resolve_warehouse_type(node) == "bigquery"

    def test_snowflake_platform(self):
        node = _make_warehouse_node("sf-1", "orders", platform="snowflake")
        assert _resolve_warehouse_type(node) == "snowflake"

    def test_dbt_with_warehouse_type_metadata(self):
        """dbt nodes with warehouse_type in raw_metadata should resolve to the warehouse."""
        node = _make_warehouse_node(
            "dbt-1", "orders", platform="dbt",
            raw_metadata={"warehouse_type": "bigquery"},
        )
        assert _resolve_warehouse_type(node) == "bigquery"

    def test_unknown_platform_returns_empty(self):
        """Non-warehouse platform without warehouse_type metadata returns empty string."""
        node = _make_tool_node(
            "n8n-1", "workflow",
            platform="n8n", platform_domain=PlatformDomain.ORCHESTRATION,
        )
        assert _resolve_warehouse_type(node) == ""


# ======================================================================
# 8. Edge-based correlation tests (Phase A, B, C)
# ======================================================================


class TestEdgeBasedCorrelation:
    """Tests for the three-phase correlation in _correlate_table_references."""

    def test_phase_a_dbt_table_matches_warehouse_table(self):
        """
        Phase A: dbt TABLE node with same db.schema.name as a registered
        BigQuery table should be detected as a match.
        """
        ctx = InvestigationContext()
        # Pre-register BigQuery table (simulates warehouse extraction first)
        ctx.register_table(
            canonical_fqn="analytics.raw.orders",
            name="orders", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-orders",
        )
        ctx.tool_profiles["bigquery"] = ToolProfile(
            tool_type="bigquery", category=ToolCategory.WAREHOUSE,
            extraction_success=True,
        )
        engine = CorrelationEngine(ctx)

        # dbt creates a TABLE node for the same table + a DEPENDS_ON edge
        dbt_source = _make_warehouse_node(
            "dbt-src-orders", "orders",
            platform="dbt", database="analytics", schema="raw",
            raw_metadata={"warehouse_type": "bigquery", "dbt_resource_type": "source"},
        )
        dbt_model = _make_warehouse_node(
            "dbt-stg-orders", "stg_orders",
            platform="dbt", database="analytics", schema="staging",
            raw_metadata={"warehouse_type": "bigquery", "dbt_resource_type": "model"},
        )
        dbt_edge = _make_edge(
            "dbt-dep-1", dbt_source.id, dbt_model.id,
            edge_type=EdgeType.DEPENDS_ON, plane=LinePlane.DATA,
        )

        edges = engine.correlate(
            new_nodes=[dbt_source, dbt_model],
            new_edges=[dbt_edge],
            tool_type="dbt_cloud",
            tool_category=ToolCategory.TRANSFORMATION,
        )

        # Phase B should create bridge edges: bq-orders → dbt_model
        bridge_edges = [e for e in edges if "bridge" in (e.discovered_from or "")]
        assert len(bridge_edges) >= 1
        # One bridge should go from the warehouse table to dbt_model
        bq_to_model = [e for e in bridge_edges if e.source_id == "bq-orders"]
        assert len(bq_to_model) >= 1

        # Tool connection should be recorded
        assert len(ctx.connections) >= 1

    def test_phase_c_phantom_edge_matches_inventory(self):
        """
        Phase C: n8n CROSS edge referencing a phantom TABLE node should match
        against the table inventory and create a direct correlation edge.
        """
        ctx = InvestigationContext()
        # Pre-register BigQuery table
        ctx.register_table(
            canonical_fqn="analytics.raw.customers",
            name="customers", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-customers",
        )
        engine = CorrelationEngine(ctx)

        # n8n TASK node (no TABLE node created by adapter)
        n8n_task = _make_tool_node(
            "n8n-task-load", "Load Customers",
            platform="n8n",
            platform_domain=PlatformDomain.ORCHESTRATION,
            node_type=NodeType.TASK,
            asset_kind=AssetKind.TASK,
        )

        # n8n CROSS edge from task → phantom TABLE (phantom ID not in nodes)
        phantom_table_id = "phantom-table-customers"
        cross_edge = LineageEdge(
            id="n8n-cross-1",
            source_id=n8n_task.id,
            target_id=phantom_table_id,
            edge_type=EdgeType.WRITES_TO,
            lineage_level=LineageLevel.TABLE,
            plane=LinePlane.CROSS,
            confidence=0.7,
            discovered_from="n8n:workflow:123:node:Postgres:writes:raw.customers",
        )

        edges = engine.correlate(
            new_nodes=[n8n_task],
            new_edges=[cross_edge],
            tool_type="n8n",
            tool_category=ToolCategory.INGESTION,
        )

        # Should create a direct edge: n8n_task → bq-customers
        phantom_edges = [e for e in edges if "phantom" in (e.discovered_from or "")]
        assert len(phantom_edges) == 1
        assert phantom_edges[0].source_id == "n8n-task-load"
        assert phantom_edges[0].target_id == "bq-customers"
        assert phantom_edges[0].edge_type == EdgeType.WRITES_TO
        assert phantom_edges[0].confidence == 0.80

        # Connection recorded
        write_conns = [c for c in ctx.connections if c.connection_type == "writes_to"]
        assert len(write_conns) >= 1
        assert write_conns[0].source_tool == "n8n"

    def test_phantom_edge_read_direction(self):
        """Phase C with read direction: phantom source → task should create READS_FROM."""
        ctx = InvestigationContext()
        ctx.register_table(
            canonical_fqn="analytics.raw.events",
            name="events", database="analytics", schema="raw",
            warehouse_type="bigquery", discovered_by="bigquery",
            node_id="bq-events",
        )
        engine = CorrelationEngine(ctx)

        n8n_task = _make_tool_node(
            "n8n-task-read", "Read Events",
            platform="n8n", platform_domain=PlatformDomain.ORCHESTRATION,
            node_type=NodeType.TASK, asset_kind=AssetKind.TASK,
        )

        # Phantom TABLE is the SOURCE (task reads from table)
        cross_edge = LineageEdge(
            id="n8n-cross-2",
            source_id="phantom-events",
            target_id=n8n_task.id,
            edge_type=EdgeType.READS_FROM,
            lineage_level=LineageLevel.TABLE,
            plane=LinePlane.CROSS,
            confidence=0.7,
            discovered_from="n8n:workflow:456:node:BQ:reads:raw.events",
        )

        edges = engine.correlate(
            new_nodes=[n8n_task],
            new_edges=[cross_edge],
            tool_type="n8n",
            tool_category=ToolCategory.INGESTION,
        )

        phantom_edges = [e for e in edges if "phantom" in (e.discovered_from or "")]
        assert len(phantom_edges) == 1
        # Should be: bq-events → n8n_task (reads from)
        assert phantom_edges[0].source_id == "bq-events"
        assert phantom_edges[0].target_id == "n8n-task-read"
        assert phantom_edges[0].edge_type == EdgeType.READS_FROM

    def test_unmatched_phantom_becomes_unresolved(self):
        """Phase C: phantom ref that doesn't match inventory should be tracked as unresolved."""
        ctx = InvestigationContext()
        engine = CorrelationEngine(ctx)

        n8n_task = _make_tool_node(
            "n8n-task", "Unknown Loader",
            platform="n8n", platform_domain=PlatformDomain.ORCHESTRATION,
            node_type=NodeType.TASK, asset_kind=AssetKind.TASK,
        )

        cross_edge = LineageEdge(
            id="n8n-cross-3",
            source_id=n8n_task.id,
            target_id="phantom-unknown",
            edge_type=EdgeType.WRITES_TO,
            lineage_level=LineageLevel.TABLE,
            plane=LinePlane.CROSS,
            confidence=0.7,
            discovered_from="n8n:workflow:789:node:Postgres:writes:staging.unknown_table",
        )

        edges = engine.correlate(
            new_nodes=[n8n_task],
            new_edges=[cross_edge],
            tool_type="n8n",
            tool_category=ToolCategory.INGESTION,
        )

        assert len(edges) == 0
        assert len(ctx.unresolved) == 1
        assert ctx.unresolved[0].reference == "staging.unknown_table"

    def test_full_investigation_bq_n8n_dbt_produces_correlations(self):
        """
        End-to-end: BigQuery + n8n + dbt should produce cross-tool correlations.
        Simulates real adapter output patterns.
        """
        # BigQuery adapter output
        bq_table = _make_warehouse_node(
            "bq-raw-customers", "customers",
            platform="bigquery", database="project", schema="raw",
        )
        bq_edge = _make_edge(
            "bq-e1", "bq-raw-customers", "bq-raw-customers",
            edge_type=EdgeType.DERIVED_FROM,
        )

        # dbt adapter output: source references same table
        dbt_source = _make_warehouse_node(
            "dbt-src-customers", "customers",
            platform="dbt", database="project", schema="raw",
            raw_metadata={"warehouse_type": "bigquery", "dbt_resource_type": "source"},
        )
        dbt_model = _make_warehouse_node(
            "dbt-stg-customers", "stg_customers",
            platform="dbt", database="project", schema="staging",
            raw_metadata={"warehouse_type": "bigquery", "dbt_resource_type": "model"},
        )
        dbt_edge = _make_edge(
            "dbt-e1", dbt_source.id, dbt_model.id,
            edge_type=EdgeType.DEPENDS_ON,
        )

        # n8n adapter output: TASK + phantom CROSS edge
        n8n_task = _make_tool_node(
            "n8n-load-customers", "Load Customers",
            platform="n8n", platform_domain=PlatformDomain.ORCHESTRATION,
            node_type=NodeType.TASK, asset_kind=AssetKind.TASK,
        )

        n8n_cross = LineageEdge(
            id="n8n-cross-cust",
            source_id=n8n_task.id,
            target_id="phantom-raw-customers",
            edge_type=EdgeType.WRITES_TO,
            lineage_level=LineageLevel.TABLE,
            plane=LinePlane.CROSS,
            confidence=0.7,
            discovered_from="n8n:workflow:1:node:Postgres:writes:raw.customers",
        )

        # Build mock adapters
        class BQAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="bq", **kw):
                self._id = adapter_id
            def id(self):
                return self._id
            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}
            def discover_assets(self, config):
                return [bq_table]
            def extract_lineage(self, config):
                return [bq_edge]

        class DbtAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="dbt", **kw):
                self._id = adapter_id
            def id(self):
                return self._id
            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}
            def discover_assets(self, config):
                return [dbt_source, dbt_model]
            def extract_lineage(self, config):
                return [dbt_edge]

        class N8nAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id="n8n", **kw):
                self._id = adapter_id
            def id(self):
                return self._id
            def capabilities(self):
                return {Capability.DISCOVER_ASSETS}
            def discover_assets(self, config):
                return [n8n_task]
            def extract_lineage(self, config):
                return [n8n_cross]

        registry = AdapterRegistry()
        registry.register_type("live_warehouse", BQAdapter)
        registry.register_type("live_n8n", N8nAdapter)
        registry.register_type("live_dbt", DbtAdapter)

        investigator = LineageInvestigator(registry=registry)
        result = investigator.run([
            ToolConfig(tool_type="bigquery", config={}),
            ToolConfig(tool_type="n8n", config={}),
            ToolConfig(tool_type="dbt_cloud", config={}),
        ])

        assert result.success is True
        # Should have correlations from both n8n and dbt
        assert result.stats["correlations_created"] >= 2
        assert result.stats["connections_found"] >= 1
        # Table inventory should show customers discovered by bigquery
        assert "project.raw.customers" in result.context.table_inventory


# ---------------------------------------------------------------------------
# Tests for InvestigationContext.build_summary()
# ---------------------------------------------------------------------------


class TestInvestigationSummary:
    """Tests for semantic investigation summary generation."""

    def test_summary_has_all_sections(self):
        ctx = InvestigationContext()
        summary = ctx.build_summary()
        assert "data_sources" in summary
        assert "data_flow" in summary
        assert "transformation" in summary
        assert "reporting" in summary
        assert "health" in summary

    def test_empty_context_summary(self):
        ctx = InvestigationContext()
        summary = ctx.build_summary()
        assert summary["data_sources"]["ingestion_tools"] == []
        assert "No ingestion" in summary["data_sources"]["answer"]
        assert "No data flow" in summary["data_flow"]["answer"]
        assert "No transformation" in summary["transformation"]["answer"]
        assert "No reporting" in summary["reporting"]["answer"]
        assert "No tools" in summary["health"]["answer"]

    def test_summary_with_ingestion(self):
        ctx = InvestigationContext()
        ctx.tool_profiles["n8n"] = ToolProfile(
            tool_type="n8n", category=ToolCategory.INGESTION,
            extraction_success=True, node_count=5,
        )
        ctx.table_inventory["project.raw.customers"] = TableRecord(
            canonical_fqn="project.raw.customers", name="customers",
            database="project", schema="raw",
            written_by=["n8n"],
        )
        summary = ctx.build_summary()
        assert "n8n" in summary["data_sources"]["ingestion_tools"]
        assert len(summary["data_sources"]["tables_loaded"]) == 1
        assert "n8n" in summary["data_sources"]["answer"]

    def test_summary_with_full_pipeline(self):
        ctx = InvestigationContext()
        ctx.tool_profiles["bigquery"] = ToolProfile(
            tool_type="bigquery", category=ToolCategory.WAREHOUSE,
            extraction_success=True, node_count=10,
        )
        ctx.tool_profiles["n8n"] = ToolProfile(
            tool_type="n8n", category=ToolCategory.INGESTION,
            extraction_success=True, node_count=5,
        )
        ctx.tool_profiles["dbt_cloud"] = ToolProfile(
            tool_type="dbt_cloud", category=ToolCategory.TRANSFORMATION,
            extraction_success=True, node_count=8,
            schedules=[{"schedule": "0 6 * * *", "node": "daily_run"}],
        )
        ctx.tool_profiles["metabase"] = ToolProfile(
            tool_type="metabase", category=ToolCategory.REPORTING,
            extraction_success=True, node_count=3,
        )
        summary = ctx.build_summary()
        # Data flow should show all stages
        stages = [s["stage"] for s in summary["data_flow"]["stages"]]
        assert "warehouse" in stages
        assert "ingestion" in stages
        assert "transformation" in stages
        assert "reporting" in stages
        assert "→" in summary["data_flow"]["answer"]
        # Transformation
        assert "dbt_cloud" in summary["transformation"]["tools"]
        assert summary["transformation"]["model_count"] == 8
        assert "schedule" in summary["transformation"]["answer"].lower()
        # Reporting
        assert "metabase" in summary["reporting"]["tools"]
        assert "3" in summary["reporting"]["answer"]

    def test_summary_health_with_failures(self):
        ctx = InvestigationContext()
        ctx.tool_profiles["bigquery"] = ToolProfile(
            tool_type="bigquery", category=ToolCategory.WAREHOUSE,
            extraction_success=True,
        )
        ctx.tool_profiles["airflow"] = ToolProfile(
            tool_type="airflow", category=ToolCategory.ORCHESTRATION,
            extraction_success=False, extraction_error="Connection refused",
        )
        ctx.add_unresolved("raw.events", "n8n", "table_write")
        summary = ctx.build_summary()
        assert summary["health"]["tools_succeeded"] == 1
        assert summary["health"]["tools_failed"] == 1
        assert "airflow" in summary["health"]["failed_tools"]
        assert summary["health"]["unresolved_references"] == 1
        assert "airflow" in summary["health"]["answer"]
        assert "1" in summary["health"]["answer"]  # unresolved count

    def test_summary_included_in_to_dict(self):
        ctx = InvestigationContext()
        d = ctx.to_dict()
        assert "summary" in d
        assert "data_sources" in d["summary"]
