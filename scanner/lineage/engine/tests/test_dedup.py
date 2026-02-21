"""
Tests for deduplication correctness.

Covers:
- Resolver FQN-based secondary dedup (catches mismatched database fields)
- Resolver stable_id dedup (existing behavior preserved)
- Bridge orphan dedup by FQN (no duplicate writes edges)
"""

import pytest
from datetime import datetime, timezone

from scanner.lineage.graph import (
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
from scanner.lineage.engine.ids import generate_asset_id
from scanner.lineage.engine.resolver import ResolverPipeline
from scanner.lineage.engine.bridge import BridgeRuleEngine
from scanner.lineage.engine.canonical import canonicalize_graph_in_place


# ---- Helpers ----


def _make_node(
    name: str,
    node_type: NodeType = NodeType.TABLE,
    platform: str = "bigquery",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    database: str = "",
    schema: str = "",
    fqn: str = "",
    namespace: str = "my-project",
    integration_id: str = None,
    raw_metadata: dict = None,
) -> LineageNode:
    fqn = fqn or ".".join(p for p in [database, schema, name] if p)
    asset_id = generate_asset_id(
        platform_domain.value, platform, namespace,
        f"{database}.{schema}", name,
    )
    return LineageNode(
        id=asset_id,
        name=name,
        fqn=fqn,
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        database=database,
        schema=schema,
        namespace=namespace,
        integration_id=integration_id,
        raw_metadata=raw_metadata or {"case_hint": "lower"},
    )


def _make_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType = EdgeType.DERIVED_FROM,
) -> LineageEdge:
    return LineageEdge(
        id=f"edge:{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        lineage_level=LineageLevel.TABLE,
        plane=LinePlane.DATA,
    )


# ---- Resolver: stable_id dedup (existing behavior) ----


class TestStableIdDedup:
    """Verify that stable_id dedup still works correctly."""

    def test_same_stable_id_merges(self):
        """Two nodes with same physical identity but different platforms merge."""
        bq_node = _make_node(
            "customers", database="my-project", schema="raw",
            platform="bigquery",
        )
        dbt_node = _make_node(
            "customers", database="my-project", schema="raw",
            platform="dbt", node_type=NodeType.SOURCE,
        )
        # Same namespace, database, schema, name → same stable_id
        assert bq_node.stable_id == dbt_node.stable_id

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_node, dbt_node], [])

        # Should produce exactly 1 node
        assert len(graph.nodes) == 1
        assert resolver.stats.nodes_deduplicated == 1

        # Winner should be bigquery (real warehouse > dbt)
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"

    def test_different_names_no_merge(self):
        """Two nodes with different names should NOT merge."""
        n1 = _make_node("customers", database="my-project", schema="raw")
        n2 = _make_node("orders", database="my-project", schema="raw")

        resolver = ResolverPipeline()
        graph = resolver.resolve([n1, n2], [])

        assert len(graph.nodes) == 2
        assert resolver.stats.nodes_deduplicated == 0


# ---- Resolver: FQN-based secondary dedup ----


class TestFqnDedup:
    """Verify FQN-based dedup catches cases where stable_id diverges."""

    def test_schema_name_dedup_catches_missing_database(self):
        """
        dbt node with empty database + BQ node with database set.
        Different stable_ids AND different FQNs, but same (schema, name).
        Schema+name dedup should merge them.
        """
        # BigQuery: database="my-project", schema="raw" → FQN="my-project.raw.customers"
        bq_node = _make_node(
            "customers", database="my-project", schema="raw",
            platform="bigquery",
        )
        # dbt: database="" (omitted), schema="raw" → FQN="raw.customers"
        dbt_node = _make_node(
            "customers", database="", schema="raw",
            platform="dbt", node_type=NodeType.SOURCE,
        )

        # Confirm stable_ids differ (the bug scenario)
        assert bq_node.stable_id != dbt_node.stable_id

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_node, dbt_node], [])

        # Schema+name dedup should merge: same (domain, namespace, schema, name)
        assert len(graph.nodes) == 1
        assert resolver.stats.nodes_deduplicated == 1

        # Winner should be bigquery
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"

    def test_schema_name_dedup_different_containers(self):
        """
        Two warehouse-domain nodes with same (schema, name) but different
        container calculations. Schema+name dedup should catch this.
        """
        # Node 1: platform=bigquery, database in different field
        n1 = _make_node(
            "customers", database="my-project", schema="raw",
            platform="bigquery",
        )
        # Node 2: platform=dbt, database empty, same schema+name
        n2 = _make_node(
            "customers", database="", schema="raw",
            platform="dbt", node_type=NodeType.SOURCE,
        )

        # These will have different stable_ids because container differs
        assert n1.stable_id != n2.stable_id

        resolver = ResolverPipeline()
        graph = resolver.resolve([n1, n2], [])

        # Schema+name dedup should merge them
        assert len(graph.nodes) == 1
        assert resolver.stats.nodes_deduplicated == 1

        # Winner should be bigquery
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"

    def test_different_domains_no_merge(self):
        """Nodes in different platform_domains with same name should NOT merge."""
        warehouse_node = _make_node(
            "customers", schema="raw", platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
        )
        bi_node = _make_node(
            "customers", schema="raw", platform="looker",
            platform_domain=PlatformDomain.BI,
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([warehouse_node, bi_node], [])

        # Different domains → should NOT merge
        assert len(graph.nodes) == 2

    def test_schema_name_dedup_preserves_edges(self):
        """Edges pointing to a schema+name-deduped node are remapped correctly."""
        n1 = _make_node(
            "customers", database="my-project", schema="raw",
            platform="bigquery",
        )
        n2 = _make_node(
            "customers", database="", schema="raw",
            platform="dbt", node_type=NodeType.SOURCE,
        )
        upstream = _make_node(
            "ext_customers", schema="staging", platform="bigquery",
        )

        # Edge from upstream to the dbt node (which will be merged away)
        edge = _make_edge(upstream.id, n2.id)

        resolver = ResolverPipeline()
        graph = resolver.resolve([n1, n2, upstream], [edge])

        assert len(graph.nodes) == 2  # customers (merged) + ext_customers
        assert len(graph.edges) == 1

        # The edge should now point to the surviving bigquery node
        surviving_edge = list(graph.edges.values())[0]
        surviving_customers = [n for n in graph.nodes.values() if n.name == "customers"][0]
        assert surviving_edge.target_id == surviving_customers.id

    def test_nodes_without_name_preserved(self):
        """Nodes without a name should pass through without errors."""
        n1 = _make_node("service1", platform="n8n",
                        platform_domain=PlatformDomain.ORCHESTRATION,
                        node_type=NodeType.WORKFLOW)
        n2 = _make_node("customers", schema="raw",
                        platform="bigquery")

        resolver = ResolverPipeline()
        graph = resolver.resolve([n1, n2], [])

        assert len(graph.nodes) == 2


# ---- Bridge: orphan dedup by FQN ----


class TestBridgeOrphanDedup:
    """Verify bridge deduplicates raw_orphans by FQN."""

    def _build_graph_with_duplicate_orphans(self):
        """Build a graph with duplicate raw datasets + an ingestion node."""
        graph = LineageGraph()

        # Ingestion service
        svc = LineageNode(
            id="urn:service:n8n:default",
            name="n8n",
            fqn="n8n",
            node_type=NodeType.WORKFLOW,
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            canonical_type="service",
            integration_id="n8n-1",
        )
        graph.add_node(svc)

        # Two nodes for the same physical table (resolver missed them)
        bq_customers = LineageNode(
            id="node:bq:customers",
            name="customers",
            fqn="raw.customers",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            database="my-project",
            schema="raw",
            canonical_type="dataset",
            raw_metadata={"zone": "raw"},
        )
        dbt_customers = LineageNode(
            id="node:dbt:customers",
            name="customers",
            fqn="raw.customers",
            node_type=NodeType.SOURCE,
            platform="dbt",
            platform_domain=PlatformDomain.WAREHOUSE,
            database="",
            schema="raw",
            canonical_type="dataset",
            raw_metadata={"zone": "raw"},
        )
        graph.add_node(bq_customers)
        graph.add_node(dbt_customers)

        # One unique orphan
        orders = LineageNode(
            id="node:bq:orders",
            name="orders",
            fqn="raw.orders",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            database="my-project",
            schema="raw",
            canonical_type="dataset",
            raw_metadata={"zone": "raw"},
        )
        graph.add_node(orders)

        return graph

    def test_bridge_no_duplicate_orphans(self):
        """Bridge should create only 1 writes edge per unique dataset FQN."""
        graph = self._build_graph_with_duplicate_orphans()
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        # Should find 2 unique orphans (customers + orders), not 3
        writes_edges = [
            e for e in result.added_edges
            if e.canonical_edge_type == "writes"
        ]

        # Count unique target FQNs
        target_fqns = set()
        for e in writes_edges:
            target = graph.nodes.get(e.target_id)
            if target:
                target_fqns.add(target.fqn.lower())

        assert "raw.customers" in target_fqns
        assert "raw.orders" in target_fqns
        # Only 2 unique datasets, so at most 2 writes edges
        assert len(writes_edges) == 2

    def test_bridge_unique_edges_per_platform(self):
        """Each ingestion platform creates exactly 1 writes edge per unique dataset."""
        graph = self._build_graph_with_duplicate_orphans()
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        # Only 1 ingestion platform (n8n), so exactly 1 loader node
        assert len(result.added_nodes) == 1
        assert "n8n" in result.added_nodes[0].name.lower()

    def test_bridge_result_counts_match(self):
        """Bridge result stats should reflect deduped counts."""
        graph = self._build_graph_with_duplicate_orphans()
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        rule_info = result.rules_applied[0]
        # Orphaned raw datasets should be 2 (after dedup), not 3
        assert rule_info["orphaned_raw_datasets"] == 2


# ---- End-to-end: resolver + canonicalize + bridge ----


class TestEndToEndDedup:
    """Full pipeline: resolver dedup → canonicalize → bridge."""

    def test_no_duplicate_nodes_in_final_graph(self):
        """
        BQ and dbt adapters produce overlapping tables with mismatched
        database fields. After resolver + canonicalize + bridge, no
        duplicate node names should exist for the same FQN.
        """
        # Simulate BQ adapter output
        bq_customers = _make_node(
            "customers", database="my-project", schema="raw",
            platform="bigquery", fqn="raw.customers",
        )
        bq_orders = _make_node(
            "orders", database="my-project", schema="raw",
            platform="bigquery", fqn="raw.orders",
        )

        # Simulate dbt adapter output (overlapping sources + new models)
        dbt_customers = _make_node(
            "customers", database="", schema="raw",
            platform="dbt", node_type=NodeType.SOURCE,
            fqn="raw.customers",
        )
        dbt_orders = _make_node(
            "orders", database="", schema="raw",
            platform="dbt", node_type=NodeType.SOURCE,
            fqn="raw.orders",
        )
        dbt_model = _make_node(
            "dim_customers", database="my-project", schema="analytics",
            platform="dbt", node_type=NodeType.MODEL,
            fqn="analytics.dim_customers",
        )

        # dbt edges: sources → model
        edges = [
            _make_edge(dbt_customers.id, dbt_model.id),
            _make_edge(dbt_orders.id, dbt_model.id),
        ]

        all_nodes = [bq_customers, bq_orders, dbt_customers, dbt_orders, dbt_model]

        # Step 1: Resolve
        resolver = ResolverPipeline()
        graph = resolver.resolve(all_nodes, edges)

        # Should have 3 unique nodes: customers, orders, dim_customers
        assert len(graph.nodes) == 3

        # Check no duplicate FQNs in same domain
        seen_fqns = set()
        for node in graph.nodes.values():
            key = (node.platform_domain.value, node.fqn.lower())
            assert key not in seen_fqns, f"Duplicate FQN: {key}"
            seen_fqns.add(key)

        # Step 2: Canonicalize
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        # Step 3: Bridge (should find no duplicates)
        # Add an ingestion node so bridge has something to connect
        ingestion = LineageNode(
            id="urn:service:n8n:default",
            name="n8n",
            fqn="n8n",
            node_type=NodeType.WORKFLOW,
            platform="n8n",
            platform_domain=PlatformDomain.INGESTION,
            canonical_type="service",
            integration_id="n8n-1",
        )
        graph.add_node(ingestion)

        bridge = BridgeRuleEngine(graph)
        bridge_result = bridge.apply_all()

        # If bridge creates writes edges, they should target unique FQNs only
        target_fqns = set()
        for e in bridge_result.added_edges:
            if e.canonical_edge_type == "writes":
                target = graph.nodes.get(e.target_id)
                if target:
                    fqn_lower = target.fqn.lower()
                    assert fqn_lower not in target_fqns, \
                        f"Bridge created duplicate writes edge to {fqn_lower}"
                    target_fqns.add(fqn_lower)
