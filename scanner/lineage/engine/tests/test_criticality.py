"""
Tests for criticality derivation and merge escalation.

Covers:
- Merge escalation: dbt critical + warehouse medium → critical survives
- Topology derivation: downstream count and BI dependents
- Explicit criticality not overwritten by topology
"""

import pytest

from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.ids import generate_asset_id
from scanner.lineage.engine.resolver import ResolverPipeline
from scanner.lineage.engine.criticality import enrich_criticality


# ---- Helpers ----


def _make_node(
    name: str,
    node_type: NodeType = NodeType.TABLE,
    platform: str = "bigquery",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    database: str = "my-project",
    schema: str = "raw",
    namespace: str = "my-project",
    criticality: str = "medium",
    raw_metadata: dict = None,
) -> LineageNode:
    fqn = ".".join(p for p in [database, schema, name] if p)
    asset_id = generate_asset_id(
        platform_domain.value, platform, namespace,
        f"{database}.{schema}", name,
    )
    node = LineageNode(
        id=asset_id,
        name=name,
        fqn=fqn,
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        database=database,
        schema=schema,
        namespace=namespace,
        raw_metadata=raw_metadata or {"case_hint": "lower"},
    )
    node.criticality = criticality
    return node


def _make_edge(source_id: str, target_id: str) -> LineageEdge:
    return LineageEdge(
        id=f"edge:{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=EdgeType.DERIVED_FROM,
        lineage_level=LineageLevel.TABLE,
        plane=LinePlane.DATA,
    )


# ---- Merge escalation tests ----


class TestMergeCriticalityEscalation:
    """Verify that merge takes the higher criticality."""

    def test_dbt_critical_warehouse_medium(self):
        """dbt model is critical, warehouse table is default medium → critical wins."""
        bq_node = _make_node("customers", criticality="medium")
        dbt_node = _make_node(
            "customers",
            platform="dbt",
            node_type=NodeType.SOURCE,
            criticality="critical",
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_node, dbt_node], [])

        assert len(graph.nodes) == 1
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"
        assert surviving.criticality == "critical"

    def test_dbt_high_warehouse_medium(self):
        """dbt high + warehouse medium → high wins."""
        bq_node = _make_node("orders", criticality="medium")
        dbt_node = _make_node(
            "orders",
            platform="dbt",
            node_type=NodeType.SOURCE,
            criticality="high",
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_node, dbt_node], [])

        surviving = list(graph.nodes.values())[0]
        assert surviving.criticality == "high"

    def test_both_medium_stays_medium(self):
        """Both medium → medium."""
        bq_node = _make_node("events", criticality="medium")
        dbt_node = _make_node(
            "events",
            platform="dbt",
            node_type=NodeType.SOURCE,
            criticality="medium",
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_node, dbt_node], [])

        surviving = list(graph.nodes.values())[0]
        assert surviving.criticality == "medium"

    def test_warehouse_high_dbt_low_keeps_high(self):
        """warehouse high + dbt low → high wins (never downgrade)."""
        bq_node = _make_node("important_table", criticality="high")
        dbt_node = _make_node(
            "important_table",
            platform="dbt",
            node_type=NodeType.SOURCE,
            criticality="low",
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_node, dbt_node], [])

        surviving = list(graph.nodes.values())[0]
        assert surviving.criticality == "high"


# ---- Topology derivation tests ----


class TestTopologyCriticalityDerivation:
    """Verify enrich_criticality upgrades nodes based on downstream impact."""

    def _build_graph(self, nodes, edges):
        graph = LineageGraph()
        for n in nodes:
            graph.add_node(n)
        for e in edges:
            graph.add_edge(e)
        return graph

    def test_many_downstream_becomes_critical(self):
        """Node with ≥10 downstream nodes → critical."""
        source = _make_node("hub_table", schema="analytics")
        downstreams = [
            _make_node(f"consumer_{i}", schema="analytics")
            for i in range(10)
        ]
        edges = [_make_edge(source.id, d.id) for d in downstreams]
        graph = self._build_graph([source] + downstreams, edges)

        upgraded = enrich_criticality(graph)

        assert upgraded >= 1
        assert graph.nodes[source.id].criticality == "critical"

    def test_some_downstream_becomes_high(self):
        """Node with 5-9 downstream nodes → high."""
        source = _make_node("mid_table", schema="staging")
        downstreams = [
            _make_node(f"dep_{i}", schema="staging")
            for i in range(5)
        ]
        edges = [_make_edge(source.id, d.id) for d in downstreams]
        graph = self._build_graph([source] + downstreams, edges)

        enrich_criticality(graph)

        assert graph.nodes[source.id].criticality == "high"

    def test_few_downstream_stays_medium(self):
        """Node with <5 downstream non-BI nodes → stays medium."""
        source = _make_node("small_table", schema="raw")
        downstreams = [
            _make_node(f"dep_{i}", schema="raw")
            for i in range(3)
        ]
        edges = [_make_edge(source.id, d.id) for d in downstreams]
        graph = self._build_graph([source] + downstreams, edges)

        enrich_criticality(graph)

        assert graph.nodes[source.id].criticality == "medium"

    def test_dashboard_dependent_becomes_critical(self):
        """Node feeding ≥3 dashboards → critical."""
        source = _make_node("reporting_table", schema="analytics")
        dashboards = []
        for i in range(3):
            d = _make_node(
                f"dashboard_{i}",
                node_type=NodeType.DASHBOARD,
                platform="tableau",
                platform_domain=PlatformDomain.BI,
                schema="",
                database="",
            )
            dashboards.append(d)
        edges = [_make_edge(source.id, d.id) for d in dashboards]
        graph = self._build_graph([source] + dashboards, edges)

        enrich_criticality(graph)

        assert graph.nodes[source.id].criticality == "critical"

    def test_one_dashboard_dependent_becomes_high(self):
        """Node feeding 1 dashboard → high."""
        source = _make_node("table_with_dashboard", schema="analytics")
        dashboard = _make_node(
            "exec_dashboard",
            node_type=NodeType.DASHBOARD,
            platform="looker",
            platform_domain=PlatformDomain.BI,
            schema="",
            database="",
        )
        edges = [_make_edge(source.id, dashboard.id)]
        graph = self._build_graph([source, dashboard], edges)

        enrich_criticality(graph)

        assert graph.nodes[source.id].criticality == "high"

    def test_explicit_criticality_not_overwritten(self):
        """Node already set to 'low' explicitly → topology does NOT upgrade it."""
        source = _make_node("intentionally_low", schema="sandbox", criticality="low")
        downstreams = [
            _make_node(f"dep_{i}", schema="sandbox")
            for i in range(15)
        ]
        edges = [_make_edge(source.id, d.id) for d in downstreams]
        graph = self._build_graph([source] + downstreams, edges)

        enrich_criticality(graph)

        # Should stay low because it was explicitly set (not the default "medium")
        assert graph.nodes[source.id].criticality == "low"

    def test_explicit_high_not_downgraded(self):
        """Node already 'high' with 0 downstream → stays high."""
        node = _make_node("already_high", schema="core", criticality="high")
        graph = self._build_graph([node], [])

        enrich_criticality(graph)

        assert graph.nodes[node.id].criticality == "high"

    def test_indirect_bi_dependents_counted(self):
        """Dashboard 2 hops away still counts toward BI dependent count."""
        source = _make_node("deep_source", schema="raw")
        mid = _make_node("mid_transform", schema="staging")
        dashboards = [
            _make_node(
                f"indirect_dash_{i}",
                node_type=NodeType.DASHBOARD,
                platform="tableau",
                platform_domain=PlatformDomain.BI,
                schema="",
                database="",
            )
            for i in range(3)
        ]
        edges = [_make_edge(source.id, mid.id)] + [
            _make_edge(mid.id, d.id) for d in dashboards
        ]
        graph = self._build_graph([source, mid] + dashboards, edges)

        enrich_criticality(graph)

        assert graph.nodes[source.id].criticality == "critical"

    def test_zero_nodes_no_error(self):
        """Empty graph doesn't crash."""
        graph = LineageGraph()
        assert enrich_criticality(graph) == 0
