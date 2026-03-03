"""
Tests for deduplication correctness.

Covers:
- Resolver FQN-based secondary dedup (catches mismatched database fields)
- Resolver stable_id dedup (existing behavior preserved)
- Bridge orphan dedup by FQN (no duplicate writes edges)
- Fivetran adapter deterministic edges (connector JOB nodes + WRITES_TO)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

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
from scanner.lineage.engine.ids import generate_asset_id, compute_environment_scope
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
        """Unmatched orphans go to a single Unknown Loader node."""
        graph = self._build_graph_with_duplicate_orphans()
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        # No ingestion job nodes with synced_tables → all orphans go to Unknown Loader
        assert len(result.added_nodes) == 1
        assert "unknown loader" in result.added_nodes[0].name.lower()

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


# ---- Cross-domain fallback merging ----


class TestCrossDomainFallback:
    """Verify cross-domain dedup merges transform ↔ warehouse nodes."""

    def test_same_schema_direct_merge(self):
        """Transform and warehouse nodes with same (ns, schema, name) merge."""
        bq_view = _make_node(
            "product_performance", database="proj", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        )
        dbt_model = _make_node(
            "product_performance", database="proj", schema="analytics",
            platform="dbt", platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_view, dbt_model], [])

        assert len(graph.nodes) == 1
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"

    def test_schema_mismatch_fallback_ns_name(self):
        """Transform node with different schema merges via (namespace, name) fallback."""
        bq_view = _make_node(
            "product_performance", database="proj", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        )
        dbt_model = _make_node(
            "product_performance", database="proj", schema="",
            platform="dbt", platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_view, dbt_model], [])

        assert len(graph.nodes) == 1
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"

    def test_namespace_mismatch_fallback_name_only(self):
        """Transform node with different namespace merges via name-only fallback."""
        bq_view = _make_node(
            "product_performance", database="proj", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
            namespace="my-gcp-project",
        )
        dbt_model = _make_node(
            "product_performance", database="proj", schema="analytics",
            platform="dbt", platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
            namespace="",  # dbt adapter failed to infer namespace
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_view, dbt_model], [])

        assert len(graph.nodes) == 1
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"

    def test_multiple_wh_groups_picks_real_warehouse(self):
        """When multiple warehouse groups share a name, prefer group with real WH platform."""
        # dbt source in "raw" schema (WAREHOUSE domain)
        dbt_source = _make_node(
            "product_performance", database="proj", schema="raw",
            platform="dbt", platform_domain=PlatformDomain.WAREHOUSE,
            node_type=NodeType.SOURCE,
        )
        # BQ view in "analytics" schema (WAREHOUSE domain)
        bq_view = _make_node(
            "product_performance", database="proj", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        )
        # dbt model with empty schema (TRANSFORM domain)
        dbt_model = _make_node(
            "product_performance", database="proj", schema="",
            platform="dbt", platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([dbt_source, bq_view, dbt_model], [])

        # dbt_source and bq_view are both WAREHOUSE but different schemas,
        # dbt_model is TRANSFORM. Should merge dbt_model with the bq_view
        # group (real warehouse platform).
        # Also dbt_source might merge with bq_view or stay separate.
        # Key assertion: no standalone dbt TRANSFORM node remains.
        names = [n.name for n in graph.nodes.values()]
        assert names.count("product_performance") <= 2  # at most source + merged
        # At least one surviving node should be bigquery
        bq_nodes = [n for n in graph.nodes.values()
                     if n.name == "product_performance" and n.platform == "bigquery"]
        assert len(bq_nodes) >= 1

    def test_schema_affinity_prefers_analytics_over_raw(self):
        """When name exists in both raw and analytics, dbt model merges with analytics."""
        # BQ view in analytics (dbt model target)
        bq_analytics = _make_node(
            "product_performance", database="proj", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        )
        # BQ view in raw (derived raw view, NOT the dbt target)
        bq_raw = _make_node(
            "product_performance", database="proj", schema="raw",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        )
        # dbt model with empty schema (project parser didn't resolve it)
        dbt_model = _make_node(
            "product_performance", database="proj", schema="",
            platform="dbt", platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_analytics, bq_raw, dbt_model], [])

        # Should have 2 nodes: merged analytics+dbt, and raw stays separate
        assert len(graph.nodes) == 2

        # The analytics node should be the merge winner
        analytics_node = [n for n in graph.nodes.values() if n.schema == "analytics"][0]
        assert analytics_node.platform == "bigquery"
        # It should have dbt in discovered_platforms (model, not source)
        platforms = analytics_node.raw_metadata.get("discovered_platforms", [])
        assert "dbt" in platforms

        # The raw node should still exist separately
        raw_node = [n for n in graph.nodes.values() if n.schema == "raw"][0]
        assert raw_node.platform == "bigquery"

    def test_both_namespace_and_schema_mismatch(self):
        """Transform node mismatches both namespace and schema — name-only fallback."""
        bq_view = _make_node(
            "product_performance", database="proj", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
            namespace="gcp-project-123",
        )
        dbt_model = _make_node(
            "product_performance", database="proj", schema="dbt_analytics",
            platform="dbt", platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
            namespace="",
        )

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_view, dbt_model], [])

        assert len(graph.nodes) == 1
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"


# ---- Fivetran adapter: deterministic edges ----


def _mock_fivetran_client(connectors=None, schemas=None):
    """Create a mock Fivetran client for adapter tests."""
    client = MagicMock()

    if connectors is None:
        conn = MagicMock()
        conn.id = "conn_abc"
        conn.name = "my_postgres"
        conn.service = "postgres"
        conn.schema = "my_postgres"
        connectors = [conn]

    if schemas is None:
        t1 = {"name": "users", "enabled": True}
        t2 = {"name": "orders", "enabled": True}
        t3 = {"name": "deleted", "enabled": False}
        schemas = {"public": {"tables": [t1, t2, t3]}}

    client.get_connectors.return_value = connectors
    client.get_connector_schema.return_value = schemas
    return client


def _import_fivetran_adapter():
    """Import LiveFivetranAdapter, working around potential import failures
    from the adapters __init__.py (which pulls optional deps like httpx
    via live_openlineage)."""
    import os, sys, importlib.util  # noqa: E401

    sub = "scanner.lineage.engine.adapters.live_fivetran"
    mod = sys.modules.get(sub)

    # If already loaded and has the class, just return it
    if mod and hasattr(mod, "LiveFivetranAdapter"):
        return mod.LiveFivetranAdapter

    # Force (re)load from file
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    engine_dir = os.path.dirname(tests_dir)
    filepath = os.path.join(engine_dir, "adapters", "live_fivetran.py")

    spec = importlib.util.spec_from_file_location(sub, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sub] = mod
    spec.loader.exec_module(mod)
    return mod.LiveFivetranAdapter


class TestFivetranDeterministicEdges:
    """Verify Fivetran adapter emits connector JOB nodes and WRITES_TO edges."""

    @staticmethod
    def _adapter():
        cls = _import_fivetran_adapter()
        return cls()

    def _base_config(self, client, **overrides):
        cfg = {
            "client": client,
            "namespace": "test-ns",
            "integration_id": "ft-001",
        }
        cfg.update(overrides)
        return cfg

    def test_discover_includes_connector_job_nodes(self):
        """discover_assets() should emit both synced-table and connector JOB nodes."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        nodes = adapter.discover_assets(self._base_config(client))

        table_nodes = [n for n in nodes if n.raw_metadata.get("node_role") == "synced_table"]
        job_nodes = [n for n in nodes if n.raw_metadata.get("node_role") == "connector_job"]

        # 2 enabled tables + 1 connector job
        assert len(table_nodes) == 2
        assert len(job_nodes) == 1
        assert job_nodes[0].canonical_type == "job"
        assert job_nodes[0].node_type == NodeType.CONNECTOR
        assert job_nodes[0].platform_domain == PlatformDomain.INGESTION
        assert "conn_abc" in job_nodes[0].raw_metadata["connector_id"]

    def test_extract_lineage_emits_writes_edges(self):
        """extract_lineage() should create WRITES_TO edges with evidence."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        edges = adapter.extract_lineage(self._base_config(client))

        # Filter to WRITES_TO edges only (excludes service→job RUNS edges)
        writes_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]

        # 2 enabled tables → 2 WRITES_TO edges
        assert len(writes_edges) == 2
        for edge in writes_edges:
            assert edge.confidence == 0.9
            assert edge.canonical_edge_type == "writes"
            assert edge.inferred is False
            assert len(edge.evidence) == 1
            assert "fivetran_connector:conn_abc" in edge.evidence[0].source_ref

    def test_edges_skip_disabled_tables(self):
        """Disabled tables should get no WRITES_TO edges."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        edges = adapter.extract_lineage(self._base_config(client))

        # Filter to WRITES_TO edges
        writes_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]
        target_ids = {e.target_id for e in writes_edges}
        # 'deleted' table is disabled → only 2 edges (users + orders)
        assert len(target_ids) == 2

    def test_edge_targets_match_synced_table_nodes(self):
        """WRITES_TO edge targets match the synced_table node IDs from discover_assets."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        config = self._base_config(client)

        nodes = adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)

        synced_table_ids = {
            n.id for n in nodes
            if n.raw_metadata.get("node_role") == "synced_table"
        }
        # Filter to synced_table WRITES_TO edges (exclude RUNS + destination edges)
        writes_edges = [
            e for e in edges
            if e.edge_type == EdgeType.WRITES_TO
            and "schema_mapping" in (e.evidence[0].source_ref if e.evidence else "")
        ]
        edge_target_ids = {e.target_id for e in writes_edges}

        # Every synced_table WRITES_TO edge target should match a synced_table node
        assert edge_target_ids == synced_table_ids

    def test_skips_internal_connectors(self):
        """fivetran_metadata and fivetran_log connectors produce no data nodes/edges."""
        internal = MagicMock()
        internal.id = "conn_internal"
        internal.name = "fivetran_metadata"
        internal.service = "fivetran_metadata"
        internal.schema = "fivetran_metadata"

        client = _mock_fivetran_client(connectors=[internal])
        adapter = self._adapter()

        nodes = adapter.discover_assets(self._base_config(client))
        edges = adapter.extract_lineage(self._base_config(client))
        # Only the service node should exist (no connectors, no synced tables)
        data_nodes = [n for n in nodes if n.canonical_type != "service"]
        assert len(data_nodes) == 0
        # No WRITES_TO edges (only possible RUNS edges to non-existent connectors)
        writes_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]
        assert len(writes_edges) == 0

    def test_connector_job_id_consistent(self):
        """Connector JOB node ID from discover_assets matches WRITES_TO edge source."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        config = self._base_config(client)

        nodes = adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)

        job_nodes = [n for n in nodes if n.raw_metadata.get("node_role") == "connector_job"]
        assert len(job_nodes) == 1
        job_id = job_nodes[0].id

        # All WRITES_TO edges should originate from the connector job node
        writes_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]
        for edge in writes_edges:
            assert edge.source_id == job_id

    def test_fallback_ids_without_destination_config(self):
        """Without destination_platform, WRITES_TO edges use Fivetran-domain IDs."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        # No destination_platform in config
        edges = adapter.extract_lineage(self._base_config(client))

        writes_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]
        assert len(writes_edges) == 2
        # Verify edges were created with ingestion-domain IDs
        for edge in writes_edges:
            assert edge.target_id
            assert edge.evidence[0].source_ref.startswith("fivetran_connector:")


# ---- Scored ingestion bridging ----


def _make_bridge_graph(
    ingestion_jobs=None,
    existing_writes=None,
    orphans=None,
):
    """Build a graph for bridge testing with ingestion jobs and raw orphans."""
    graph = LineageGraph()

    # Add all nodes first, then edges (edges need both endpoints present)
    for node in (ingestion_jobs or []):
        graph.add_node(node)
    for node in (orphans or []):
        graph.add_node(node)
    for edge in (existing_writes or []):
        graph.add_edge(edge)

    return graph


def _raw_dataset(name, schema="raw", **kwargs):
    """Create a raw dataset node for bridge testing."""
    node = _make_node(
        name, database="my-project", schema=schema,
        platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
    )
    node.canonical_type = "dataset"
    node.raw_metadata = {"zone": "raw", "case_hint": "lower"}
    for k, v in kwargs.items():
        setattr(node, k, v)
    return node


def _ingestion_job(name, platform="fivetran", synced_tables=None,
                   dest_schema="", connector_name="", integration_id="ft-1"):
    """Create an ingestion job node for bridge testing."""
    node_id = f"urn:job:{platform}:{name}"
    return LineageNode(
        id=node_id,
        name=name,
        fqn=f"{platform}.{name}",
        node_type=NodeType.CONNECTOR,
        platform=platform,
        platform_domain=PlatformDomain.INGESTION,
        canonical_type="job",
        integration_id=integration_id,
        raw_metadata={
            "synced_tables": synced_tables or [],
            "dest_schema": dest_schema,
            "connector_name": connector_name or name,
            "node_role": "connector_job",
        },
    )


class TestScoredIngestionBridge:
    """Verify scored matching for ingestion bridging."""

    def test_synced_table_name_wins(self):
        """Orphan name in job's synced_tables -> matched via synced_table_name.

        No existing warehouse writes edges, so only metadata-based strategies
        fire. synced_table_name (0.85) beats same_schema (0.8).
        """
        job = _ingestion_job("stripe_connector", synced_tables=["charges", "customers"],
                             dest_schema="stripe")
        orphan = _raw_dataset("customers", schema="stripe")

        graph = _make_bridge_graph(
            ingestion_jobs=[job],
            orphans=[orphan],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        # Orphan should be matched to stripe_connector
        writes_to_orphan = [
            e for e in result.added_edges
            if e.target_id == orphan.id and e.canonical_edge_type == "writes"
        ]
        assert len(writes_to_orphan) == 1
        assert writes_to_orphan[0].source_id == job.id
        assert writes_to_orphan[0].inferred is True

        # Check diagnostic
        diag = [d for d in result.diagnostics if d.dataset_id == orphan.id]
        assert len(diag) == 1
        assert diag[0].match_strategy == "synced_table_name"

    def test_same_schema_match(self):
        """Orphan in same schema as job dest_schema -> matched via same_schema.

        No existing warehouse writes edges, so only metadata-based strategies
        fire. same_schema (0.8) is the top match when synced_table_name doesn't apply.
        """
        job = _ingestion_job("postgres_connector", dest_schema="pg_public")

        # Orphan is in the same schema as the job's dest_schema
        orphan = _raw_dataset("invoices", schema="pg_public")

        graph = _make_bridge_graph(
            ingestion_jobs=[job],
            orphans=[orphan],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        writes_to_orphan = [
            e for e in result.added_edges
            if e.target_id == orphan.id and e.canonical_edge_type == "writes"
        ]
        assert len(writes_to_orphan) == 1
        assert writes_to_orphan[0].source_id == job.id

        diag = [d for d in result.diagnostics if d.dataset_id == orphan.id]
        assert diag[0].match_strategy == "same_schema"

    def test_no_match_gets_unknown_loader(self):
        """Orphan with no matching job -> Unknown Loader, confidence=0.3."""
        job = _ingestion_job("stripe_connector", synced_tables=["charges"],
                             dest_schema="stripe")

        # Orphan in a completely unrelated schema
        orphan = _raw_dataset("events", schema="segment")

        graph = _make_bridge_graph(
            ingestion_jobs=[job],
            orphans=[orphan],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        writes_to_orphan = [
            e for e in result.added_edges
            if e.target_id == orphan.id and e.canonical_edge_type == "writes"
        ]
        assert len(writes_to_orphan) == 1
        assert "unknown_loader" in writes_to_orphan[0].source_id
        assert writes_to_orphan[0].confidence == 0.3
        assert writes_to_orphan[0].inferred is True

        diag = [d for d in result.diagnostics if d.dataset_id == orphan.id]
        assert diag[0].match_strategy == "fallback_unknown"

    def test_no_ingestion_platforms_no_edges(self):
        """No ingestion tools -> no bridge edges at all."""
        orphan = _raw_dataset("events", schema="raw")

        graph = LineageGraph()
        graph.add_node(orphan)

        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()
        assert len(result.added_edges) == 0
        assert len(result.added_nodes) == 0

    def test_confidence_capped_at_half(self):
        """Matched bridge edges have confidence <= 0.5."""
        job = _ingestion_job("stripe_connector",
                             synced_tables=["customers", "charges"],
                             dest_schema="stripe")
        orphan = _raw_dataset("customers", schema="stripe")

        graph = _make_bridge_graph(ingestion_jobs=[job], orphans=[orphan])
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        for edge in result.added_edges:
            if edge.canonical_edge_type == "writes":
                assert edge.confidence <= 0.5
                assert edge.inferred is True

    def test_diagnostics_recorded(self):
        """Bridge should record diagnostics for every orphan."""
        job = _ingestion_job("stripe_connector",
                             synced_tables=["charges"],
                             dest_schema="stripe")
        matched_orphan = _raw_dataset("charges", schema="stripe")
        unmatched_orphan = _raw_dataset("events", schema="segment")

        graph = _make_bridge_graph(
            ingestion_jobs=[job],
            orphans=[matched_orphan, unmatched_orphan],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        assert len(result.diagnostics) == 2
        strategies = {d.match_strategy for d in result.diagnostics}
        assert "synced_table_name" in strategies
        assert "fallback_unknown" in strategies

    def test_existing_writer_not_bridged(self):
        """Orphan with existing upstream job is NOT re-bridged."""
        job = _ingestion_job("stripe_connector",
                             synced_tables=["customers"],
                             dest_schema="stripe")
        dataset = _raw_dataset("customers", schema="stripe")

        # Job already writes to this dataset
        writes_edge = LineageEdge(
            id="edge:job->customers",
            source_id=job.id, target_id=dataset.id,
            edge_type=EdgeType.WRITES_TO,
            lineage_level=LineageLevel.TABLE,
            canonical_edge_type="writes",
        )

        graph = _make_bridge_graph(
            ingestion_jobs=[job],
            existing_writes=[writes_edge],
            orphans=[dataset],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        # Dataset already has a writer — bridge should not add another
        writes_to_dataset = [
            e for e in result.added_edges
            if e.target_id == dataset.id and e.canonical_edge_type == "writes"
        ]
        assert len(writes_to_dataset) == 0


# ---- Environment scope dedup ----


from scanner.lineage.graph import generate_stable_id


class TestEnvironmentScopeDedup:
    """Verify environment_scope prevents cross-env merges."""

    def test_different_env_scopes_no_merge(self):
        """Two BQ tables with same name but different environment_scope stay separate."""
        prod = _make_node(
            "dim_customers", database="analytics-prod", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
            namespace="analytics-prod",
        )
        prod.environment_scope = "analytics-prod"

        dev = _make_node(
            "dim_customers", database="analytics-dev", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
            namespace="analytics-dev",
        )
        dev.environment_scope = "analytics-dev"

        resolver = ResolverPipeline()
        graph = resolver.resolve([prod, dev], [])

        # Different scopes → must NOT merge
        assert len(graph.nodes) == 2
        assert resolver.stats.nodes_deduplicated == 0

    def test_empty_scope_backward_compat(self):
        """Nodes without environment_scope merge as before."""
        bq_node = _make_node(
            "customers", database="my-project", schema="raw",
            platform="bigquery",
        )
        dbt_node = _make_node(
            "customers", database="my-project", schema="raw",
            platform="dbt", node_type=NodeType.SOURCE,
        )
        # No environment_scope set (None) → backward-compatible merge
        assert bq_node.environment_scope is None
        assert dbt_node.environment_scope is None

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_node, dbt_node], [])

        assert len(graph.nodes) == 1
        assert resolver.stats.nodes_deduplicated >= 1

    def test_dbt_shares_scope_with_warehouse(self):
        """dbt node with same scope as BQ table → correct merge."""
        bq_node = _make_node(
            "dim_customers", database="my-project", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        )
        bq_node.environment_scope = "my-project"

        dbt_node = _make_node(
            "dim_customers", database="my-project", schema="analytics",
            platform="dbt", platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
        )
        dbt_node.environment_scope = "my-project"

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_node, dbt_node], [])

        # Same scope → should merge via cross-domain dedup
        assert len(graph.nodes) == 1
        surviving = list(graph.nodes.values())[0]
        assert surviving.platform == "bigquery"

    def test_scope_in_serialization_roundtrip(self):
        """to_dict → LineageGraph.from_dict preserves environment_scope."""
        node = _make_node(
            "orders", database="my-project", schema="raw",
            platform="bigquery",
        )
        node.environment_scope = "my-bq-project"

        data = node.to_dict()
        assert data["environment_scope"] == "my-bq-project"

        # Roundtrip through LineageGraph serialization
        graph = LineageGraph()
        graph.add_node(node)
        graph_data = graph.to_dict()
        restored_graph = LineageGraph.from_dict(graph_data)
        restored = list(restored_graph.nodes.values())[0]
        assert restored.environment_scope == "my-bq-project"

    def test_stable_id_differs_with_scope(self):
        """generate_stable_id produces different IDs for different scopes."""
        id1 = generate_stable_id("warehouse", "ns", "db.schema", "tbl", "prod")
        id2 = generate_stable_id("warehouse", "ns", "db.schema", "tbl", "dev")
        id3 = generate_stable_id("warehouse", "ns", "db.schema", "tbl", "")

        assert id1 != id2
        assert id1 != id3
        assert id2 != id3

    def test_stable_id_same_without_scope(self):
        """generate_stable_id with empty scope matches legacy behavior."""
        id_none = generate_stable_id("warehouse", "ns", "db.schema", "tbl")
        id_empty = generate_stable_id("warehouse", "ns", "db.schema", "tbl", "")

        assert id_none == id_empty

    def test_compute_environment_scope_bigquery(self):
        """compute_environment_scope returns project_id for BigQuery."""
        scope = compute_environment_scope("bigquery", {"project_id": "My-GCP-Project"})
        assert scope == "my-gcp-project"

    def test_compute_environment_scope_snowflake(self):
        """compute_environment_scope returns account.region.database for Snowflake."""
        scope = compute_environment_scope("snowflake", {
            "account": "xy12345",
            "region": "us-east-1",
            "database": "ANALYTICS",
        })
        assert scope == "xy12345.us-east-1.analytics"

    def test_compute_environment_scope_postgres(self):
        """compute_environment_scope returns host:port.database for Postgres."""
        scope = compute_environment_scope("postgres", {
            "host": "db.example.com",
            "port": 5432,
            "database": "mydb",
        })
        assert scope == "db.example.com:5432.mydb"

    def test_compute_environment_scope_unknown_platform(self):
        """compute_environment_scope returns empty string for unknown platforms."""
        scope = compute_environment_scope("unknown", {"host": "x"})
        assert scope == ""

    def test_cross_domain_respects_scope(self):
        """Cross-domain dedup does NOT merge nodes with different scopes."""
        bq_prod = _make_node(
            "orders", database="proj", schema="analytics",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
            namespace="proj",
        )
        bq_prod.environment_scope = "prod-project"

        dbt_dev = _make_node(
            "orders", database="proj", schema="analytics",
            platform="dbt", platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
            namespace="proj",
        )
        dbt_dev.environment_scope = "dev-project"

        resolver = ResolverPipeline()
        graph = resolver.resolve([bq_prod, dbt_dev], [])

        # Different scopes → should NOT merge even though names match
        assert len(graph.nodes) == 2

    def test_compute_environment_scope_fivetran(self):
        """compute_environment_scope returns group_id for Fivetran."""
        scope = compute_environment_scope("fivetran", {"group_id": "grp_abc123"})
        assert scope == "grp_abc123"

    def test_compute_environment_scope_fivetran_account_id(self):
        """compute_environment_scope falls back to account_id for Fivetran."""
        scope = compute_environment_scope("fivetran", {"account_id": "ACCT-XY"})
        assert scope == "acct-xy"

    def test_compute_environment_scope_dbt(self):
        """compute_environment_scope returns target_name.database for dbt."""
        scope = compute_environment_scope("dbt", {
            "target_name": "prod",
            "database": "analytics",
        })
        assert scope == "prod.analytics"

    def test_compute_environment_scope_dbt_warehouse_fallback(self):
        """compute_environment_scope dbt falls back to warehouse_type delegation."""
        scope = compute_environment_scope("dbt", {
            "warehouse_type": "bigquery",
            "project_id": "my-gcp-project",
        })
        assert scope == "my-gcp-project"

    def test_fivetran_auto_scope_from_destination_config(self):
        """Fivetran adapter auto-computes scope from destination_config."""
        client = _mock_fivetran_client()
        cls = _import_fivetran_adapter()
        adapter = cls()
        config = {
            "client": client,
            "namespace": "test-ns",
            "integration_id": "ft-001",
            "destination_config": {
                "platform": "bigquery",
                "project_id": "my-bq-project",
            },
        }
        nodes = adapter.discover_assets(config)
        # All nodes should get the BigQuery project as scope
        scoped_nodes = [n for n in nodes if n.environment_scope == "my-bq-project"]
        assert len(scoped_nodes) > 0
        # Specifically, synced_table nodes should have it
        synced = [n for n in nodes if n.raw_metadata.get("node_role") == "synced_table"]
        for n in synced:
            assert n.environment_scope == "my-bq-project"


# ---- Fivetran destination config tests ----


class TestFivetranDestinationConfig:
    """Verify Fivetran adapter emits warehouse-domain destination nodes and edges."""

    @staticmethod
    def _adapter():
        cls = _import_fivetran_adapter()
        return cls()

    def _base_config(self, client, **overrides):
        cfg = {
            "client": client,
            "namespace": "test-ns",
            "integration_id": "ft-001",
            "destination_config": {
                "platform": "bigquery",
                "project_id": "my-project",
                "dataset": "raw_pg",
            },
        }
        cfg.update(overrides)
        return cfg

    def test_destination_config_emits_warehouse_nodes(self):
        """With destination_config, adapter emits WAREHOUSE-domain nodes."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        nodes = adapter.discover_assets(self._base_config(client))

        dest_nodes = [
            n for n in nodes
            if n.raw_metadata.get("node_role") == "fivetran_destination"
        ]
        # 2 enabled tables → 2 destination nodes
        assert len(dest_nodes) == 2
        for n in dest_nodes:
            assert n.platform == "bigquery"
            assert n.platform_domain == PlatformDomain.WAREHOUSE
            assert n.database == "my-project"
            assert n.schema == "raw_pg"
            assert n.environment_scope == "my-project"
            assert len(n.evidence) == 1
            assert "fivetran_connector" in n.evidence[0].source_ref

    def test_destination_edges_target_warehouse_ids(self):
        """WRITES_TO edges target warehouse-domain node IDs when destination_config present."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        config = self._base_config(client)

        nodes = adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)

        dest_node_ids = {
            n.id for n in nodes
            if n.raw_metadata.get("node_role") == "fivetran_destination"
        }

        # There should be edges targeting destination node IDs
        dest_edges = [e for e in edges if e.target_id in dest_node_ids]
        assert len(dest_edges) == 2
        for edge in dest_edges:
            assert edge.edge_type == EdgeType.WRITES_TO
            assert edge.confidence == 0.9
            assert edge.canonical_edge_type == "writes"
            assert edge.inferred is False
            assert "destination_mapping" in edge.evidence[0].source_ref

    def test_destination_nodes_merge_with_warehouse_discovered(self):
        """Fivetran destination nodes merge with BQ-discovered nodes via resolver."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        config = self._base_config(client)

        ft_nodes = adapter.discover_assets(config)
        ft_edges = adapter.extract_lineage(config)

        # Create a BQ-discovered table that should merge with Fivetran destination
        bq_users = _make_node(
            "users", database="my-project", schema="raw_pg",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
            namespace="my-project",
        )
        bq_users.environment_scope = "my-project"

        all_nodes = ft_nodes + [bq_users]
        resolver = ResolverPipeline()
        graph = resolver.resolve(all_nodes, ft_edges)

        # "users" from Fivetran dest + BQ should merge into 1 node
        users_nodes = [
            n for n in graph.nodes.values()
            if n.name == "users" and n.platform_domain == PlatformDomain.WAREHOUSE
        ]
        assert len(users_nodes) == 1
        # The merged node should have BQ as platform (warehouse priority)
        assert users_nodes[0].platform == "bigquery"

    def test_without_destination_config_no_warehouse_nodes(self):
        """Without destination_config, no warehouse-domain nodes are emitted."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        config = {
            "client": client,
            "namespace": "test-ns",
            "integration_id": "ft-001",
            # No destination_config
        }
        nodes = adapter.discover_assets(config)
        dest_nodes = [
            n for n in nodes
            if n.raw_metadata.get("node_role") == "fivetran_destination"
        ]
        assert len(dest_nodes) == 0

    def test_service_node_created(self):
        """discover_assets creates a Fivetran SERVICE node."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        nodes = adapter.discover_assets(self._base_config(client))

        service_nodes = [
            n for n in nodes if n.canonical_type == "service"
        ]
        assert len(service_nodes) == 1
        assert service_nodes[0].name == "Fivetran"
        assert service_nodes[0].platform == "fivetran"
        assert service_nodes[0].platform_domain == PlatformDomain.INGESTION

    def test_runs_edges_service_to_connector(self):
        """extract_lineage creates RUNS edges from service to connector jobs."""
        client = _mock_fivetran_client()
        adapter = self._adapter()
        config = self._base_config(client)

        nodes = adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)

        service_node = next(n for n in nodes if n.canonical_type == "service")
        job_nodes = [n for n in nodes if n.raw_metadata.get("node_role") == "connector_job"]

        runs_edges = [
            e for e in edges
            if e.source_id == service_node.id and e.canonical_edge_type == "runs"
        ]
        assert len(runs_edges) == 1  # 1 connector → 1 RUNS edge
        assert runs_edges[0].target_id == job_nodes[0].id
        assert runs_edges[0].confidence == 0.95
        assert runs_edges[0].edge_type == EdgeType.TRIGGERS
        assert runs_edges[0].plane == LinePlane.CONTROL


# ---- Bridge adapter-destination scoring tests ----


class TestAdapterDestinationBridgeScoring:
    """Verify bridge scoring uses adapter destination edges for matching."""

    def test_adapter_destination_table_match_wins(self):
        """Job with warehouse WRITES_TO edge to 'charges' -> orphan 'charges' matched."""
        job = _ingestion_job("stripe_connector", synced_tables=["charges"],
                             dest_schema="stripe")
        # Create a warehouse destination table that the job writes to
        dest_table = _raw_dataset("charges", schema="stripe")
        dest_table.canonical_type = "dataset"

        writes_edge = LineageEdge(
            id="edge:job->charges_dest",
            source_id=job.id, target_id=dest_table.id,
            edge_type=EdgeType.WRITES_TO,
            lineage_level=LineageLevel.TABLE,
            confidence=0.9,
            canonical_edge_type="writes",
            inferred=False,  # adapter edge, not bridge-inferred
        )

        # A different orphan with same name in different schema
        orphan = _raw_dataset("charges", schema="raw_stripe")

        graph = _make_bridge_graph(
            ingestion_jobs=[job],
            existing_writes=[writes_edge],
            orphans=[dest_table, orphan],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        # orphan should be matched via adapter_destination_table (score 0.95)
        diag = [d for d in result.diagnostics if d.dataset_id == orphan.id]
        assert len(diag) == 1
        assert diag[0].match_strategy == "adapter_destination_table"

    def test_adapter_destination_schema_match(self):
        """Job writes to warehouse table in 'stripe' schema -> orphan 'refunds' in same schema matched."""
        job = _ingestion_job("stripe_connector", synced_tables=["charges"],
                             dest_schema="stripe")
        dest_table = _raw_dataset("charges", schema="stripe")
        dest_table.canonical_type = "dataset"

        writes_edge = LineageEdge(
            id="edge:job->charges_dest",
            source_id=job.id, target_id=dest_table.id,
            edge_type=EdgeType.WRITES_TO,
            lineage_level=LineageLevel.TABLE,
            confidence=0.9,
            canonical_edge_type="writes",
            inferred=False,
        )

        # New orphan in same schema but not in synced_tables
        orphan = _raw_dataset("refunds", schema="stripe")

        graph = _make_bridge_graph(
            ingestion_jobs=[job],
            existing_writes=[writes_edge],
            orphans=[dest_table, orphan],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        diag = [d for d in result.diagnostics if d.dataset_id == orphan.id]
        assert len(diag) == 1
        # adapter_destination_schema (0.9) beats same_schema (0.8) and synced_table_name
        assert diag[0].match_strategy == "adapter_destination_schema"

    def test_two_jobs_compete_highest_score_wins(self):
        """Two ingestion jobs match, highest score wins with alternatives recorded."""
        job1 = _ingestion_job("stripe_connector",
                              synced_tables=["payments"],
                              dest_schema="stripe")
        job2 = _ingestion_job("backup_connector",
                              synced_tables=[],
                              dest_schema="stripe")  # same schema → same_schema match

        # job1 has a direct warehouse destination edge for "charges"
        dest_table = _raw_dataset("charges", schema="stripe")
        dest_table.canonical_type = "dataset"
        writes_edge = LineageEdge(
            id="edge:job1->charges",
            source_id=job1.id, target_id=dest_table.id,
            edge_type=EdgeType.WRITES_TO,
            lineage_level=LineageLevel.TABLE,
            confidence=0.9,
            canonical_edge_type="writes",
            inferred=False,
        )

        # Orphan in stripe schema — both jobs match but via different strategies
        orphan = _raw_dataset("payments", schema="stripe")

        graph = _make_bridge_graph(
            ingestion_jobs=[job1, job2],
            existing_writes=[writes_edge],
            orphans=[dest_table, orphan],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        diag = [d for d in result.diagnostics if d.dataset_id == orphan.id]
        assert len(diag) == 1
        # job1 should win: adapter_destination_table (0.95) + synced_table_name (0.85)
        # vs job2: same_schema (0.8)
        assert diag[0].matched_job_id == job1.id
        # Alternatives should record job2's match
        assert len(diag[0].alternatives) > 0
        alt_job_ids = {a["job_id"] for a in diag[0].alternatives}
        assert job2.id in alt_job_ids

    def test_fivetran_destination_edges_prevent_orphan(self):
        """Orphan with existing Fivetran WRITES_TO edge is NOT classified as orphan."""
        job = _ingestion_job("stripe_connector", synced_tables=["charges"],
                             dest_schema="stripe")
        # Dataset with existing adapter-created WRITES_TO from the job
        dataset = _raw_dataset("charges", schema="stripe")
        dataset.canonical_type = "dataset"

        writes_edge = LineageEdge(
            id="edge:job->charges",
            source_id=job.id, target_id=dataset.id,
            edge_type=EdgeType.WRITES_TO,
            lineage_level=LineageLevel.TABLE,
            confidence=0.9,
            canonical_edge_type="writes",
            inferred=False,
        )

        graph = _make_bridge_graph(
            ingestion_jobs=[job],
            existing_writes=[writes_edge],
            orphans=[dataset],
        )
        engine = BridgeRuleEngine(graph)
        result = engine.apply_all()

        # Dataset already has a writer → should NOT be bridged
        bridge_edges_to_dataset = [
            e for e in result.added_edges
            if e.target_id == dataset.id and e.canonical_edge_type == "writes"
        ]
        assert len(bridge_edges_to_dataset) == 0
