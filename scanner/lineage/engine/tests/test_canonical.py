"""
Tests for scanner.lineage.engine.canonical

Covers:
- NodeType → CanonicalNodeType mapping (including ambiguous cases)
- EdgeType → CanonicalEdgeType mapping
- URN generation determinism
- infer_canonical_edge_type() semantic overrides
- canonicalize_graph_in_place() end-to-end
- is_needs_mapping() detection
"""

import pytest

from scanner.lineage.graph import (
    EdgeType,
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.canonical import (
    CanonicalEdgeType,
    CanonicalNodeType,
    canonicalize_graph_in_place,
    generate_urn,
    get_layer,
    get_layer_order,
    infer_canonical_edge_type,
    is_needs_mapping,
    map_edge_type,
    map_node_type,
)


# ---- Helpers ----

def _make_node(
    name: str,
    node_type: NodeType,
    platform_domain: PlatformDomain = PlatformDomain.OTHER,
    platform: str = "test",
    namespace: str = "",
    fqn: str = "",
    database: str = None,
    schema: str = None,
) -> LineageNode:
    return LineageNode(
        id=f"node:{name}",
        name=name,
        fqn=fqn or name,
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        namespace=namespace,
        database=database,
        schema=schema,
    )


def _make_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType,
) -> LineageEdge:
    return LineageEdge(
        id=f"edge:{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
    )


# ---- Node type mapping tests ----

class TestMapNodeType:
    """Test all NodeType → CanonicalNodeType mappings."""

    @pytest.mark.parametrize("node_type,expected", [
        (NodeType.TABLE, CanonicalNodeType.DATASET),
        (NodeType.VIEW, CanonicalNodeType.DATASET),
        (NodeType.MATERIALIZED_VIEW, CanonicalNodeType.DATASET),
        (NodeType.SOURCE, CanonicalNodeType.DATASET),
        (NodeType.SEED, CanonicalNodeType.DATASET),
        (NodeType.SNAPSHOT, CanonicalNodeType.DATASET),
    ])
    def test_data_assets_map_to_dataset(self, node_type, expected):
        node = _make_node("test", node_type)
        assert map_node_type(node) == expected

    @pytest.mark.parametrize("node_type,expected", [
        (NodeType.TASK, CanonicalNodeType.JOB),
        (NodeType.DAG, CanonicalNodeType.JOB),
        (NodeType.FLOW, CanonicalNodeType.JOB),
        (NodeType.PIPELINE, CanonicalNodeType.JOB),
        (NodeType.WORKFLOW, CanonicalNodeType.JOB),
        (NodeType.NOTEBOOK, CanonicalNodeType.JOB),
        (NodeType.CONNECTOR, CanonicalNodeType.JOB),
        (NodeType.MONITOR, CanonicalNodeType.JOB),
    ])
    def test_executables_map_to_job(self, node_type, expected):
        node = _make_node("test", node_type)
        assert map_node_type(node) == expected

    @pytest.mark.parametrize("node_type,expected", [
        (NodeType.DASHBOARD, CanonicalNodeType.SEMANTIC),
        (NodeType.REPORT, CanonicalNodeType.SEMANTIC),
        (NodeType.WORKBOOK, CanonicalNodeType.SEMANTIC),
        (NodeType.QUESTION, CanonicalNodeType.SEMANTIC),
        (NodeType.EXPLORE, CanonicalNodeType.SEMANTIC),
    ])
    def test_bi_assets_map_to_semantic(self, node_type, expected):
        node = _make_node("test", node_type)
        assert map_node_type(node) == expected

    def test_model_transform_maps_to_dataset(self):
        """dbt model = materialized table → DATASET."""
        node = _make_node("orders", NodeType.MODEL, PlatformDomain.TRANSFORM)
        assert map_node_type(node) == CanonicalNodeType.DATASET

    def test_model_bi_maps_to_semantic(self):
        """Looker model = semantic layer → SEMANTIC."""
        node = _make_node("users_explore", NodeType.MODEL, PlatformDomain.BI)
        assert map_node_type(node) == CanonicalNodeType.SEMANTIC

    def test_model_default_maps_to_dataset(self):
        """Unknown-domain MODEL defaults to DATASET."""
        node = _make_node("thing", NodeType.MODEL, PlatformDomain.OTHER)
        assert map_node_type(node) == CanonicalNodeType.DATASET

    def test_dataset_bi_maps_to_semantic(self):
        """Power BI dataset = semantic model → SEMANTIC."""
        node = _make_node("sales_model", NodeType.DATASET, PlatformDomain.BI)
        assert map_node_type(node) == CanonicalNodeType.SEMANTIC

    def test_dataset_default_maps_to_dataset(self):
        node = _make_node("raw_events", NodeType.DATASET)
        assert map_node_type(node) == CanonicalNodeType.DATASET

    def test_unknown_maps_to_dataset(self):
        node = _make_node("mystery", NodeType.UNKNOWN)
        assert map_node_type(node) == CanonicalNodeType.DATASET


# ---- Edge type mapping tests ----

class TestMapEdgeType:
    """Test EdgeType → CanonicalEdgeType mappings."""

    @pytest.mark.parametrize("edge_type,expected", [
        (EdgeType.DEPENDS_ON, CanonicalEdgeType.DERIVES),
        (EdgeType.DERIVED_FROM, CanonicalEdgeType.DERIVES),
    ])
    def test_derives_mappings(self, edge_type, expected):
        edge = _make_edge("a", "b", edge_type)
        assert map_edge_type(edge) == expected

    @pytest.mark.parametrize("edge_type,expected", [
        (EdgeType.READS_FROM, CanonicalEdgeType.READS),
        (EdgeType.QUERIES, CanonicalEdgeType.READS),
        (EdgeType.JOINS, CanonicalEdgeType.READS),
        (EdgeType.REFERENCES, CanonicalEdgeType.READS),
        (EdgeType.TESTS, CanonicalEdgeType.READS),
        (EdgeType.MONITORS, CanonicalEdgeType.READS),
    ])
    def test_reads_mappings(self, edge_type, expected):
        edge = _make_edge("a", "b", edge_type)
        assert map_edge_type(edge) == expected

    @pytest.mark.parametrize("edge_type,expected", [
        (EdgeType.POPULATES, CanonicalEdgeType.WRITES),
        (EdgeType.REFRESHES, CanonicalEdgeType.WRITES),
        (EdgeType.WRITES_TO, CanonicalEdgeType.WRITES),
        (EdgeType.MATERIALIZES, CanonicalEdgeType.WRITES),
        (EdgeType.SYNCS_TO, CanonicalEdgeType.WRITES),
    ])
    def test_writes_mappings(self, edge_type, expected):
        edge = _make_edge("a", "b", edge_type)
        assert map_edge_type(edge) == expected

    @pytest.mark.parametrize("edge_type,expected", [
        (EdgeType.TRIGGERS, CanonicalEdgeType.RUNS),
        (EdgeType.PRODUCED_BY, CanonicalEdgeType.RUNS),
    ])
    def test_runs_mappings(self, edge_type, expected):
        edge = _make_edge("a", "b", edge_type)
        assert map_edge_type(edge) == expected


# ---- Infer canonical edge type tests ----

class TestInferCanonicalEdgeType:
    """Test semantic overrides based on node type pairs."""

    def test_dataset_to_semantic_becomes_serves(self):
        result = infer_canonical_edge_type(
            CanonicalNodeType.DATASET,
            CanonicalNodeType.SEMANTIC,
            EdgeType.READS_FROM,
        )
        assert result == CanonicalEdgeType.SERVES

    def test_dataset_to_dataset_reads_becomes_derives(self):
        """dataset→dataset with READS_FROM should be DERIVES."""
        result = infer_canonical_edge_type(
            CanonicalNodeType.DATASET,
            CanonicalNodeType.DATASET,
            EdgeType.READS_FROM,
        )
        assert result == CanonicalEdgeType.DERIVES

    def test_system_to_service_becomes_hosts(self):
        result = infer_canonical_edge_type(
            CanonicalNodeType.SYSTEM,
            CanonicalNodeType.SERVICE,
            EdgeType.DEPENDS_ON,
        )
        assert result == CanonicalEdgeType.HOSTS

    def test_service_to_job_becomes_runs(self):
        result = infer_canonical_edge_type(
            CanonicalNodeType.SERVICE,
            CanonicalNodeType.JOB,
            EdgeType.TRIGGERS,
        )
        assert result == CanonicalEdgeType.RUNS


# ---- URN generation tests ----

class TestGenerateUrn:
    def test_basic_urn(self):
        node = _make_node(
            "orders", NodeType.TABLE,
            PlatformDomain.WAREHOUSE, platform="bigquery",
            namespace="production", fqn="analytics.public.orders",
        )
        urn = generate_urn(node)
        assert urn == "urn:pallisade:dataset:bigquery:production:analytics.public.orders"

    def test_urn_deterministic(self):
        """Same input → same URN."""
        node1 = _make_node("tbl", NodeType.TABLE, platform="snowflake", fqn="db.sc.tbl")
        node2 = _make_node("tbl", NodeType.TABLE, platform="snowflake", fqn="db.sc.tbl")
        assert generate_urn(node1) == generate_urn(node2)

    def test_urn_case_insensitive(self):
        """URN uses lowercase regardless of input case."""
        node = _make_node("TBL", NodeType.TABLE, platform="Snowflake", fqn="DB.SC.TBL")
        urn = generate_urn(node)
        assert "snowflake" in urn
        assert "db.sc.tbl" in urn

    def test_urn_with_missing_namespace(self):
        node = _make_node("events", NodeType.TABLE, platform="postgres", fqn="public.events")
        urn = generate_urn(node)
        assert urn == "urn:pallisade:dataset:postgres::public.events"


# ---- get_layer tests ----

class TestGetLayer:
    def test_warehouse_layer(self):
        node = _make_node("t", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        assert get_layer(node) == "WAREHOUSE"

    def test_transform_layer(self):
        node = _make_node("m", NodeType.MODEL, PlatformDomain.TRANSFORM)
        assert get_layer(node) == "TRANSFORMATION"

    def test_bi_layer(self):
        node = _make_node("d", NodeType.DASHBOARD, PlatformDomain.BI)
        assert get_layer(node) == "REPORTING"


# ---- get_layer_order tests ----

class TestGetLayerOrder:
    def test_ingestion_before_warehouse(self):
        assert get_layer_order("INGESTION") < get_layer_order("WAREHOUSE")

    def test_warehouse_before_reporting(self):
        assert get_layer_order("WAREHOUSE") < get_layer_order("REPORTING")

    def test_unknown_layer_gets_high_number(self):
        assert get_layer_order("NONEXISTENT") == 99


# ---- is_needs_mapping tests ----

class TestIsNeedsMapping:
    def test_unknown_type_needs_mapping(self):
        node = _make_node("x", NodeType.UNKNOWN)
        assert is_needs_mapping(node) is True

    def test_table_does_not_need_mapping(self):
        node = _make_node("orders", NodeType.TABLE)
        assert is_needs_mapping(node) is False

    def test_other_domain_with_exotic_type_needs_mapping(self):
        node = _make_node("thing", NodeType.CONNECTOR, PlatformDomain.OTHER)
        assert is_needs_mapping(node) is True

    def test_other_domain_with_table_does_not_need_mapping(self):
        node = _make_node("t", NodeType.TABLE, PlatformDomain.OTHER)
        assert is_needs_mapping(node) is False


# ---- canonicalize_graph_in_place tests ----

class TestCanonicalizeGraphInPlace:
    def test_sets_canonical_type_and_urn(self):
        """canonicalize_graph_in_place should populate canonical_type and urn."""
        node = _make_node("orders", NodeType.TABLE, PlatformDomain.WAREHOUSE, platform="bigquery")
        edge = _make_edge(node.id, "node:other", EdgeType.DEPENDS_ON)
        other = _make_node("other", NodeType.VIEW, PlatformDomain.WAREHOUSE, platform="bigquery")

        nodes = {node.id: node, other.id: other}
        edges = {edge.id: edge}

        result = canonicalize_graph_in_place(nodes, edges)

        assert node.canonical_type == "dataset"
        assert other.canonical_type == "dataset"
        assert node.urn is not None
        assert "urn:pallisade:dataset:bigquery" in node.urn
        assert edge.canonical_edge_type == "derives"
        assert len(result["needs_mapping"]) == 0

    def test_detects_needs_mapping(self):
        node = _make_node("mystery", NodeType.UNKNOWN)
        nodes = {node.id: node}
        edges = {}

        result = canonicalize_graph_in_place(nodes, edges)
        assert node.id in result["needs_mapping"]

    def test_infer_edge_type_dataset_to_semantic(self):
        """dataset → semantic edge should get canonical_edge_type=serves."""
        table = _make_node("raw", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        dash = _make_node("sales_dash", NodeType.DASHBOARD, PlatformDomain.BI)
        edge = _make_edge(table.id, dash.id, EdgeType.READS_FROM)

        nodes = {table.id: table, dash.id: dash}
        edges = {edge.id: edge}

        canonicalize_graph_in_place(nodes, edges)
        assert edge.canonical_edge_type == "serves"

    def test_preserves_inferred_flag(self):
        """inferred flag should not be overwritten by canonicalization."""
        node = _make_node("bridge", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        node.inferred = True
        nodes = {node.id: node}
        edges = {}

        canonicalize_graph_in_place(nodes, edges)
        assert node.inferred is True
        assert node.canonical_type == "dataset"

    def test_preserves_adapter_set_canonical_edge_type(self):
        """When adapter explicitly sets canonical_edge_type, canonicalize must not overwrite."""
        job = _make_node("sync", NodeType.CONNECTOR, PlatformDomain.INGESTION)
        table = _make_node("raw_orders", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        edge = _make_edge(job.id, table.id, EdgeType.POPULATES)
        edge.canonical_edge_type = "writes"  # Explicitly set by bridge/adapter

        nodes = {job.id: job, table.id: table}
        edges = {edge.id: edge}

        canonicalize_graph_in_place(nodes, edges)
        assert edge.canonical_edge_type == "writes"  # Preserved, not re-inferred

    def test_infers_canonical_edge_when_not_set(self):
        """When canonical_edge_type is None, canonicalize fills it in."""
        job = _make_node("sync", NodeType.CONNECTOR, PlatformDomain.INGESTION)
        table = _make_node("raw_orders", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        edge = _make_edge(job.id, table.id, EdgeType.POPULATES)
        assert edge.canonical_edge_type is None

        nodes = {job.id: job, table.id: table}
        edges = {edge.id: edge}

        canonicalize_graph_in_place(nodes, edges)
        assert edge.canonical_edge_type == "writes"

    def test_dataset_to_dataset_reads_becomes_derives(self):
        """READS_FROM between two datasets should be canonicalized to 'derives'."""
        src = _make_node("source_table", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        tgt = _make_node("target_table", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        edge = _make_edge(src.id, tgt.id, EdgeType.READS_FROM)

        nodes = {src.id: src, tgt.id: tgt}
        edges = {edge.id: edge}

        canonicalize_graph_in_place(nodes, edges)
        assert edge.canonical_edge_type == "derives"


# ---- map_edge_type_explicit tests ----

class TestMapEdgeTypeExplicit:
    """Test the single-source-of-truth edge mapping function."""

    def test_job_writes_to_dataset(self):
        from scanner.lineage.engine.canonical import map_edge_type_explicit
        job = _make_node("loader", NodeType.CONNECTOR, PlatformDomain.INGESTION)
        table = _make_node("raw", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        result = map_edge_type_explicit(EdgeType.WRITES_TO, job, table)
        assert result == CanonicalEdgeType.WRITES

    def test_service_triggers_job(self):
        from scanner.lineage.engine.canonical import map_edge_type_explicit
        svc = _make_node("fivetran", NodeType.PIPELINE, PlatformDomain.INGESTION)
        job = _make_node("sync", NodeType.CONNECTOR, PlatformDomain.INGESTION)
        result = map_edge_type_explicit(EdgeType.TRIGGERS, svc, job)
        assert result == CanonicalEdgeType.RUNS

    def test_dataset_to_semantic_serves(self):
        from scanner.lineage.engine.canonical import map_edge_type_explicit
        table = _make_node("metrics", NodeType.TABLE, PlatformDomain.WAREHOUSE)
        dash = _make_node("revenue", NodeType.DASHBOARD, PlatformDomain.BI)
        result = map_edge_type_explicit(EdgeType.READS_FROM, table, dash)
        assert result == CanonicalEdgeType.SERVES
