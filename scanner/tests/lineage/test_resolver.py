"""
Tests for the normalization and resolution pipeline.
"""

import pytest
from datetime import datetime

from scanner.lineage.engine.resolver import (
    ResolverConfig,
    ResolverPipeline,
    _merge_node_metadata,
)
from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.ids import generate_asset_id


def _make_node(name, platform="postgres", domain="warehouse", db="warehouse", schema="public", namespace="prod"):
    container = f"{db}.{schema}"
    return LineageNode(
        id=generate_asset_id(domain, platform, namespace, container, name),
        name=name,
        fqn=f"{db}.{schema}.{name}",
        node_type=NodeType.TABLE,
        database=db,
        schema=schema,
        platform=platform,
        platform_domain=PlatformDomain(domain),
        asset_kind=AssetKind.TABLE,
        namespace=namespace,
        sources=[f"{platform}_adapter"],
    )


def _make_edge(source_id, target_id, level="table", confidence=1.0, adapter_id="test"):
    return LineageEdge(
        id=f"{source_id}_{target_id}_{level}",
        source_id=source_id,
        target_id=target_id,
        edge_type=EdgeType.DEPENDS_ON,
        confidence=confidence,
        lineage_level=LineageLevel(level),
        evidence=[Evidence(adapter_id=adapter_id, source_ref=f"test:{source_id}->{target_id}")],
    )


class TestNormalization:
    def test_normalizes_database_schema_name(self):
        node = LineageNode(
            id="n1", name='"MyTable"', fqn="DB.SCHEMA.MyTable",
            node_type=NodeType.TABLE,
            database="DB", schema="SCHEMA",
            platform="postgres",
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE,
        )
        pipeline = ResolverPipeline()
        [normalized] = pipeline._normalize_nodes([node])
        assert normalized.database == "db"
        assert normalized.schema == "schema"
        assert normalized.name == "mytable"
        assert normalized.fqn == "db.schema.mytable"

    @pytest.mark.parametrize("raw_name,expected", [
        ('"Users"', "users"),
        ('`my_table`', "my_table"),
        ("[dbo]", "dbo"),
        ("ORDERS", "orders"),
    ])
    def test_various_quoting(self, raw_name, expected):
        node = LineageNode(
            id="n1", name=raw_name, fqn=raw_name,
            node_type=NodeType.TABLE,
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE,
        )
        pipeline = ResolverPipeline()
        [normalized] = pipeline._normalize_nodes([node])
        assert normalized.name == expected


class TestDeduplication:
    def test_identical_stable_id_merges(self):
        """Two nodes from different adapters with same identity get merged."""
        n1 = _make_node("users", platform="postgres", domain="warehouse")
        n2 = _make_node("users", platform="postgres", domain="warehouse")
        n2.id = n2.id + "_dup"  # different original ID
        n2.sources = ["other_adapter"]

        pipeline = ResolverPipeline()
        merged, remap = pipeline._deduplicate_nodes([n1, n2])
        assert len(merged) == 1
        assert set(merged[0].sources) == {"postgres_adapter", "other_adapter"}
        assert remap[n2.id] == n1.id

    def test_different_tables_not_merged(self):
        n1 = _make_node("users")
        n2 = _make_node("orders")

        pipeline = ResolverPipeline()
        merged, remap = pipeline._deduplicate_nodes([n1, n2])
        assert len(merged) == 2

    def test_warehouse_wins_over_transform(self):
        """When two adapters emit a node for the same physical warehouse
        table, they get the same stable_id and are merged. The node from
        the warehouse adapter is kept as primary (row_count, etc.)."""
        n_wh = _make_node("users", platform="postgres", domain="warehouse")
        n_wh.row_count = 50000
        # Transform adapter also emits this as a warehouse source
        n_tr = _make_node("users", platform="dbt", domain="warehouse")
        n_tr.id = n_tr.id + "_tr"
        n_tr.description = "Users from dbt"
        n_tr.sources = ["dbt_adapter"]
        # stable_ids match: same (domain, namespace, db, schema, name)
        assert n_wh.stable_id == n_tr.stable_id

        pipeline = ResolverPipeline()
        merged, _ = pipeline._deduplicate_nodes([n_wh, n_tr])
        assert len(merged) == 1
        primary = merged[0]
        assert primary.platform_domain == PlatformDomain.WAREHOUSE
        assert primary.row_count == 50000
        assert primary.description == "Users from dbt"
        assert set(primary.sources) == {"postgres_adapter", "dbt_adapter"}

    def test_fuzzy_match_disabled_by_default(self):
        """With fuzzy_resolution=False, near-matches are NOT merged."""
        n1 = _make_node("users")
        n2 = _make_node("user")  # different name, different stable_id

        pipeline = ResolverPipeline(ResolverConfig(fuzzy_resolution=False))
        merged, _ = pipeline._deduplicate_nodes([n1, n2])
        assert len(merged) == 2


class TestEdgeMerge:
    def test_same_relationship_different_evidence_merges(self):
        """Same from/to/type/level from different adapters gets merged."""
        e1 = _make_edge("a", "b", adapter_id="adapter1")
        e2 = LineageEdge(
            id="a_b_table_2",
            source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON,
            confidence=0.7,
            lineage_level=LineageLevel.TABLE,
            evidence=[Evidence(adapter_id="adapter2", source_ref="sql:a->b")],
        )

        pipeline = ResolverPipeline()
        merged = pipeline._merge_edges([e1, e2])
        assert len(merged) == 1
        assert len(merged[0].evidence) == 2
        # Max confidence selected
        assert merged[0].confidence >= 0.7

    def test_different_levels_not_merged(self):
        """Table and column edges between same nodes stay separate."""
        e1 = _make_edge("a", "b", level="table")
        e2 = _make_edge("a", "b", level="column")

        pipeline = ResolverPipeline()
        merged = pipeline._merge_edges([e1, e2])
        assert len(merged) == 2


class TestFullPipeline:
    def test_resolve_produces_valid_graph(self):
        n1 = _make_node("customers")
        n2 = _make_node("orders")
        e = _make_edge(n1.id, n2.id)

        pipeline = ResolverPipeline()
        graph = pipeline.resolve([n1, n2], [e])

        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert pipeline.stats.unresolved_refs == 0

    def test_unresolved_edges_counted(self):
        """Edges referencing non-existent nodes are counted but not added."""
        n1 = _make_node("customers")
        e = _make_edge(n1.id, "nonexistent_node")

        pipeline = ResolverPipeline()
        graph = pipeline.resolve([n1], [e])

        assert len(graph.nodes) == 1
        assert len(graph.edges) == 0
        assert pipeline.stats.unresolved_refs == 1


class TestEvidenceWeighting:
    def test_manifest_evidence_gets_highest_weight(self):
        pipeline = ResolverPipeline()
        ev = Evidence(adapter_id="dbt", source_ref="manifest:model:depends_on:source")
        assert pipeline._classify_evidence(ev) == "declarative"

    def test_sql_evidence_classified(self):
        pipeline = ResolverPipeline()
        ev = Evidence(adapter_id="wh", source_ref="view_def:my_view:table")
        assert pipeline._classify_evidence(ev) == "compiled_sql"

    def test_query_history_classified(self):
        pipeline = ResolverPipeline()
        ev = Evidence(adapter_id="wh", source_ref="query_history:job123")
        assert pipeline._classify_evidence(ev) == "query_history"
