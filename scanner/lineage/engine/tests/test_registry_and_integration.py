"""
Tests for the adapter registry and cross-adapter integration scenarios.

Covers:
- Default registry type loading (all 19 built-in adapters)
- Instance creation, retrieval, and listing
- Capability-based filtering
- Custom registry usage
- Cross-adapter graph integration (multi-platform LineageGraph)
- Control plane derivation from multi-adapter data
- Stable ID deduplication across adapters
- OpenLineage adapter with pre-loaded events (no network calls)
"""

import pytest
from typing import Set

from scanner.lineage.engine.adapter import (
    AdapterRegistry,
    BaseLineageAdapter,
    Capability,
    create_default_registry,
)
from scanner.lineage.engine.adapters.live_openlineage import LiveOpenLineageAdapter
from scanner.lineage.engine.control_plane import build_control_plane_graph
from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    HealthStatus,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)


# ======================================================================
# Registry tests
# ======================================================================


class TestDefaultRegistry:
    """Tests for create_default_registry() and its contents."""

    def test_default_registry_has_all_19_types(self):
        """Default registry should contain exactly 19 adapter types."""
        registry = create_default_registry()
        types = registry.list_types()
        assert len(types) == 19

    def test_default_registry_type_names(self):
        """Verify all expected adapter type names are present."""
        registry = create_default_registry()
        types = set(registry.list_types())

        expected_names = {
            "transform_artifact",
            "warehouse_catalog",
            "bi_query",
            "live_warehouse",
            "live_dbt",
            "live_airflow",
            "live_dagster",
            "live_prefect",
            "live_n8n",
            "live_fivetran",
            "live_airbyte",
            "live_storage",
            "live_looker",
            "live_tableau",
            "live_powerbi",
            "live_metabase",
            "live_databricks",
            "live_elementary",
            "live_openlineage",
        }
        assert types == expected_names


class TestRegistryInstanceLifecycle:
    """Tests for creating, retrieving, and listing adapter instances."""

    def test_create_instance_and_get(self):
        """Creating an instance via registry.create should be retrievable via get."""
        registry = create_default_registry()
        instance = registry.create("live_tableau", "my-tableau-1")

        retrieved = registry.get("my-tableau-1")
        assert retrieved is instance
        assert instance.id() == "my-tableau-1"

    def test_create_instance_returns_adapter(self):
        """Created instance should be a BaseLineageAdapter subclass."""
        registry = create_default_registry()
        instance = registry.create("live_powerbi", "pbi-prod")
        assert isinstance(instance, BaseLineageAdapter)

    def test_get_nonexistent_returns_none(self):
        """Getting an adapter ID that was never created should return None."""
        registry = create_default_registry()
        assert registry.get("does-not-exist") is None

    def test_unknown_type_raises_value_error(self):
        """Attempting to create an adapter of an unknown type should raise ValueError."""
        registry = create_default_registry()
        with pytest.raises(ValueError, match="Unknown adapter type"):
            registry.create("nonexistent", "x")

    def test_list_instances_multiple(self):
        """list_instances should return all created adapter instances."""
        registry = create_default_registry()
        a1 = registry.create("live_tableau", "tab-1")
        a2 = registry.create("live_looker", "looker-1")
        a3 = registry.create("live_n8n", "n8n-prod")

        instances = registry.list_instances()
        assert len(instances) == 3
        instance_ids = {inst.id() for inst in instances}
        assert instance_ids == {"tab-1", "looker-1", "n8n-prod"}

    def test_list_instances_empty_initially(self):
        """A fresh registry should have no instances."""
        registry = create_default_registry()
        assert registry.list_instances() == []


class TestCapabilityFiltering:
    """Tests for filter_by_capability on registry instances."""

    def test_filter_by_get_bi_exposures(self):
        """
        GET_BI_EXPOSURES should match Tableau, PowerBI, Metabase, Looker
        but NOT n8n or Databricks.
        """
        registry = create_default_registry()
        registry.create("live_tableau", "tab-1")
        registry.create("live_powerbi", "pbi-1")
        registry.create("live_metabase", "mb-1")
        registry.create("live_looker", "looker-1")
        registry.create("live_n8n", "n8n-1")
        registry.create("live_databricks", "dbx-1")

        bi_adapters = registry.filter_by_capability(Capability.GET_BI_EXPOSURES)
        bi_ids = {a.id() for a in bi_adapters}

        assert "tab-1" in bi_ids
        assert "pbi-1" in bi_ids
        assert "mb-1" in bi_ids
        assert "looker-1" in bi_ids
        assert "n8n-1" not in bi_ids
        assert "dbx-1" not in bi_ids

    def test_filter_by_extract_column_lineage(self):
        """
        EXTRACT_COLUMN_LINEAGE should match Databricks and OpenLineage
        but not BI adapters or n8n.
        """
        registry = create_default_registry()
        registry.create("live_databricks", "dbx-1")
        registry.create("live_openlineage", "ol-1")
        registry.create("live_tableau", "tab-1")
        registry.create("live_n8n", "n8n-1")

        col_adapters = registry.filter_by_capability(Capability.EXTRACT_COLUMN_LINEAGE)
        col_ids = {a.id() for a in col_adapters}

        assert "dbx-1" in col_ids
        assert "ol-1" in col_ids
        assert "tab-1" not in col_ids
        assert "n8n-1" not in col_ids

    def test_filter_by_discover_assets_all_live(self):
        """All live adapters should support DISCOVER_ASSETS."""
        registry = create_default_registry()
        registry.create("live_tableau", "tab-1")
        registry.create("live_n8n", "n8n-1")
        registry.create("live_openlineage", "ol-1")

        discover_adapters = registry.filter_by_capability(Capability.DISCOVER_ASSETS)
        discover_ids = {a.id() for a in discover_adapters}

        assert "tab-1" in discover_ids
        assert "n8n-1" in discover_ids
        assert "ol-1" in discover_ids

    def test_filter_returns_empty_when_no_match(self):
        """If no instances have a capability, filter should return empty list."""
        registry = create_default_registry()
        # n8n does not have GET_BI_EXPOSURES
        registry.create("live_n8n", "n8n-1")

        result = registry.filter_by_capability(Capability.GET_BI_EXPOSURES)
        assert result == []


class TestCustomRegistry:
    """Tests for building a custom registry from scratch."""

    def test_custom_registry_register_and_create(self):
        """An empty AdapterRegistry should support registering a custom type."""

        class StubAdapter(BaseLineageAdapter):
            def __init__(self, adapter_id: str = "stub", **kwargs):
                self._id = adapter_id

            def id(self) -> str:
                return self._id

            def capabilities(self) -> Set[Capability]:
                return {Capability.DISCOVER_ASSETS}

            def discover_assets(self, config):
                return []

            def extract_lineage(self, config):
                return []

        registry = AdapterRegistry()
        assert registry.list_types() == []
        assert registry.list_instances() == []

        registry.register_type("my_stub", StubAdapter)
        assert "my_stub" in registry.list_types()

        instance = registry.create("my_stub", "stub-1")
        assert instance.id() == "stub-1"
        assert isinstance(instance, StubAdapter)
        assert registry.get("stub-1") is instance

    def test_custom_registry_unknown_type(self):
        """An empty registry should raise ValueError for any type."""
        registry = AdapterRegistry()
        with pytest.raises(ValueError, match="Unknown adapter type"):
            registry.create("anything", "x")


# ======================================================================
# Cross-adapter integration tests
# ======================================================================


def _make_node(
    node_id: str,
    name: str,
    platform: str,
    platform_domain: PlatformDomain,
    node_type: NodeType = NodeType.TABLE,
    asset_kind: AssetKind = AssetKind.TABLE,
    namespace: str = "prod",
    database: str = "",
    schema: str = "",
) -> LineageNode:
    """Helper to create a LineageNode with minimal boilerplate."""
    return LineageNode(
        id=node_id,
        name=name,
        fqn=f"{platform}.{namespace}.{name}",
        node_type=node_type,
        database=database or None,
        schema=schema or None,
        platform=platform,
        platform_domain=platform_domain,
        asset_kind=asset_kind,
        namespace=namespace,
    )


def _make_edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    edge_type: EdgeType = EdgeType.DERIVED_FROM,
    plane: LinePlane = LinePlane.DATA,
    confidence: float = 1.0,
) -> LineageEdge:
    """Helper to create a LineageEdge with minimal boilerplate."""
    return LineageEdge(
        id=edge_id,
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        plane=plane,
        confidence=confidence,
    )


class TestMultiAdapterPipeline:
    """
    Test that nodes from multiple platforms coexist in a LineageGraph
    and that build_control_plane_graph correctly derives the tool sequence.

    Simulated pipeline:
        Fivetran (ingestion) -> Snowflake (warehouse) -> dbt (transform) -> Tableau (BI)
    """

    @pytest.fixture
    def multi_platform_graph(self) -> LineageGraph:
        """Build a LineageGraph with nodes/edges spanning 4 platforms."""
        graph = LineageGraph()

        # -- Fivetran nodes (ingestion) --
        ft_connector = _make_node(
            "ft-conn-1", "stripe_connector",
            platform="fivetran",
            platform_domain=PlatformDomain.INGESTION,
            node_type=NodeType.CONNECTOR,
            asset_kind=AssetKind.CONNECTOR,
        )
        graph.add_node(ft_connector)

        # -- Snowflake nodes (warehouse) --
        sf_raw = _make_node(
            "sf-raw-orders", "raw_orders",
            platform="snowflake",
            platform_domain=PlatformDomain.WAREHOUSE,
            node_type=NodeType.TABLE,
            asset_kind=AssetKind.TABLE,
            database="ANALYTICS", schema="RAW",
        )
        sf_staging = _make_node(
            "sf-stg-orders", "stg_orders",
            platform="snowflake",
            platform_domain=PlatformDomain.WAREHOUSE,
            node_type=NodeType.TABLE,
            asset_kind=AssetKind.TABLE,
            database="ANALYTICS", schema="STAGING",
        )
        graph.add_node(sf_raw)
        graph.add_node(sf_staging)

        # -- dbt nodes (transform) --
        dbt_model = _make_node(
            "dbt-stg-orders", "stg_orders",
            platform="dbt",
            platform_domain=PlatformDomain.TRANSFORM,
            node_type=NodeType.MODEL,
            asset_kind=AssetKind.MODEL,
        )
        graph.add_node(dbt_model)

        # -- Tableau nodes (BI) --
        tab_ds = _make_node(
            "tab-ds-orders", "Orders Datasource",
            platform="tableau",
            platform_domain=PlatformDomain.BI,
            node_type=NodeType.DATASET,
            asset_kind=AssetKind.DATASET,
        )
        tab_wb = _make_node(
            "tab-wb-sales", "Sales Dashboard",
            platform="tableau",
            platform_domain=PlatformDomain.BI,
            node_type=NodeType.WORKBOOK,
            asset_kind=AssetKind.WORKBOOK,
        )
        graph.add_node(tab_ds)
        graph.add_node(tab_wb)

        # -- Edges --
        # Fivetran -> Snowflake raw (CROSS plane, ingestion to warehouse)
        graph.add_edge(_make_edge(
            "e-ft-sf", "ft-conn-1", "sf-raw-orders",
            edge_type=EdgeType.SYNCS_TO,
            plane=LinePlane.CROSS,
        ))
        # Snowflake raw -> dbt model (DATA plane, warehouse to transform)
        graph.add_edge(_make_edge(
            "e-sf-dbt", "sf-raw-orders", "dbt-stg-orders",
            edge_type=EdgeType.DERIVED_FROM,
            plane=LinePlane.DATA,
        ))
        # dbt model -> Snowflake staging (DATA plane, transform materializes to warehouse)
        graph.add_edge(_make_edge(
            "e-dbt-sf", "dbt-stg-orders", "sf-stg-orders",
            edge_type=EdgeType.WRITES_TO,
            plane=LinePlane.DATA,
        ))
        # Snowflake staging -> Tableau datasource (CROSS plane, warehouse to BI)
        graph.add_edge(_make_edge(
            "e-sf-tab-ds", "sf-stg-orders", "tab-ds-orders",
            edge_type=EdgeType.READS_FROM,
            plane=LinePlane.CROSS,
        ))
        # Tableau datasource -> Tableau workbook (DATA plane, within BI)
        graph.add_edge(_make_edge(
            "e-tab-ds-wb", "tab-ds-orders", "tab-wb-sales",
            edge_type=EdgeType.READS_FROM,
            plane=LinePlane.DATA,
        ))

        return graph

    def test_graph_has_nodes_from_all_platforms(self, multi_platform_graph):
        """The graph should contain nodes from all 4 platforms."""
        platforms = {n.platform for n in multi_platform_graph.nodes.values()}
        assert platforms == {"fivetran", "snowflake", "dbt", "tableau"}

    def test_graph_has_cross_plane_edges(self, multi_platform_graph):
        """There should be CROSS plane edges spanning different platforms."""
        cross_edges = [
            e for e in multi_platform_graph.edges.values()
            if e.plane == LinePlane.CROSS
        ]
        assert len(cross_edges) >= 2  # fivetran->snowflake, snowflake->tableau

    def test_graph_edge_count(self, multi_platform_graph):
        """The graph should have exactly 5 edges."""
        assert len(multi_platform_graph.edges) == 5

    def test_graph_node_count(self, multi_platform_graph):
        """The graph should have exactly 6 nodes."""
        assert len(multi_platform_graph.nodes) == 6

    def test_control_plane_derivation(self, multi_platform_graph):
        """
        build_control_plane_graph should produce a control plane with
        one node per platform and edges reflecting tool-to-tool data flow.
        """
        cp = build_control_plane_graph(multi_platform_graph)

        # Should have exactly 4 tool nodes (fivetran, snowflake, dbt, tableau)
        cp_tool_types = {n.tool_type for n in cp.nodes}
        assert cp_tool_types == {"fivetran", "snowflake", "dbt", "tableau"}

    def test_control_plane_has_cross_tool_edges(self, multi_platform_graph):
        """
        Control plane should have edges between distinct tools.
        Expected: fivetran->snowflake, snowflake->dbt, dbt->snowflake, snowflake->tableau
        """
        cp = build_control_plane_graph(multi_platform_graph)
        assert len(cp.edges) >= 3  # at least fivetran->sf, sf->dbt, dbt->sf/sf->tab

        edge_pairs = {(e.source, e.target) for e in cp.edges}
        # Fivetran -> Snowflake should exist
        assert any(
            "fivetran" in src and "snowflake" in tgt
            for src, tgt in edge_pairs
        )

    def test_control_plane_node_positions(self, multi_platform_graph):
        """
        Control plane nodes should be ordered by pipeline sequence:
        ingestion < warehouse < transform < BI.
        """
        cp = build_control_plane_graph(multi_platform_graph)
        position_by_type = {n.tool_type: n.position for n in cp.nodes}

        assert position_by_type["fivetran"] < position_by_type["dbt"]
        assert position_by_type["fivetran"] < position_by_type["tableau"]

    def test_control_plane_asset_counts(self, multi_platform_graph):
        """Each control plane node should reflect the correct asset count."""
        cp = build_control_plane_graph(multi_platform_graph)
        count_by_type = {n.tool_type: n.asset_count for n in cp.nodes}

        assert count_by_type["fivetran"] == 1
        assert count_by_type["snowflake"] == 2  # raw + staging
        assert count_by_type["dbt"] == 1
        assert count_by_type["tableau"] == 2  # datasource + workbook

    def test_control_plane_to_dict(self, multi_platform_graph):
        """Serialized control plane should have expected structure."""
        cp = build_control_plane_graph(multi_platform_graph)
        data = cp.to_dict()

        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data
        assert data["stats"]["tool_count"] == 4


class TestStableIdCrossAdapterDedup:
    """
    Test that the same physical asset discovered by different adapters
    gets the same stable_id for deduplication.
    """

    def test_same_table_different_platforms_same_stable_id(self):
        """
        A warehouse TABLE node and a dbt MODEL node for the same
        physical table should share the same stable_id.
        """
        node_warehouse = LineageNode(
            id="id1",
            name="orders",
            fqn="db.public.orders",
            node_type=NodeType.TABLE,
            database="db",
            schema="public",
            platform="snowflake",
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE,
            namespace="prod",
        )
        node_dbt = LineageNode(
            id="id2",
            name="orders",
            fqn="db.public.orders",
            node_type=NodeType.MODEL,
            database="db",
            schema="public",
            platform="dbt",
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.MODEL,
            namespace="prod",
        )
        assert node_warehouse.stable_id == node_dbt.stable_id

    def test_stable_id_differs_for_different_names(self):
        """Different table names should produce different stable_ids."""
        node_a = LineageNode(
            id="a", name="orders", fqn="db.public.orders",
            node_type=NodeType.TABLE, database="db", schema="public",
            platform="snowflake", platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE, namespace="prod",
        )
        node_b = LineageNode(
            id="b", name="customers", fqn="db.public.customers",
            node_type=NodeType.TABLE, database="db", schema="public",
            platform="snowflake", platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE, namespace="prod",
        )
        assert node_a.stable_id != node_b.stable_id

    def test_stable_id_differs_for_different_schemas(self):
        """Same table name in different schemas should produce different stable_ids."""
        node_raw = LineageNode(
            id="r", name="orders", fqn="db.raw.orders",
            node_type=NodeType.TABLE, database="db", schema="raw",
            platform="snowflake", platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE, namespace="prod",
        )
        node_staging = LineageNode(
            id="s", name="orders", fqn="db.staging.orders",
            node_type=NodeType.TABLE, database="db", schema="staging",
            platform="snowflake", platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE, namespace="prod",
        )
        assert node_raw.stable_id != node_staging.stable_id

    def test_stable_id_excludes_platform(self):
        """
        stable_id should not include platform — same physical identity
        from bigquery and postgres should match.
        """
        node_bq = LineageNode(
            id="bq1", name="events", fqn="analytics.raw.events",
            node_type=NodeType.TABLE, database="analytics", schema="raw",
            platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE, namespace="prod",
        )
        node_pg = LineageNode(
            id="pg1", name="events", fqn="analytics.raw.events",
            node_type=NodeType.TABLE, database="analytics", schema="raw",
            platform="postgres", platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE, namespace="prod",
        )
        assert node_bq.stable_id == node_pg.stable_id

    def test_stable_id_is_deterministic(self):
        """Creating the same node twice should produce the same stable_id."""
        def make():
            return LineageNode(
                id="x", name="orders", fqn="db.public.orders",
                node_type=NodeType.TABLE, database="db", schema="public",
                platform="snowflake", platform_domain=PlatformDomain.WAREHOUSE,
                asset_kind=AssetKind.TABLE, namespace="prod",
            )

        assert make().stable_id == make().stable_id


# ======================================================================
# OpenLineage adapter integration tests
# ======================================================================


class TestOpenLineageAdapterPreloaded:
    """
    Test LiveOpenLineageAdapter using pre-loaded events via the config
    'events' key, ensuring no network calls are made.
    """

    @pytest.fixture
    def sample_events(self):
        """Minimal set of OpenLineage RunEvents for testing."""
        return [
            {
                "eventType": "COMPLETE",
                "eventTime": "2024-06-01T12:00:00Z",
                "run": {"runId": "run-001"},
                "job": {
                    "namespace": "airflow://prod-airflow",
                    "name": "etl_dag.load_orders",
                },
                "inputs": [
                    {
                        "namespace": "bigquery",
                        "name": "raw.stripe_charges",
                        "facets": {
                            "schema": {
                                "fields": [
                                    {"name": "id", "type": "STRING"},
                                    {"name": "amount", "type": "INT64"},
                                ]
                            }
                        },
                    }
                ],
                "outputs": [
                    {
                        "namespace": "bigquery",
                        "name": "staging.orders",
                        "facets": {},
                    }
                ],
            },
            {
                "eventType": "COMPLETE",
                "eventTime": "2024-06-01T12:05:00Z",
                "run": {"runId": "run-002"},
                "job": {
                    "namespace": "airflow://prod-airflow",
                    "name": "etl_dag.transform_metrics",
                },
                "inputs": [
                    {
                        "namespace": "bigquery",
                        "name": "staging.orders",
                        "facets": {},
                    }
                ],
                "outputs": [
                    {
                        "namespace": "bigquery",
                        "name": "analytics.order_metrics",
                        "facets": {},
                    }
                ],
            },
        ]

    @pytest.fixture
    def adapter(self):
        return LiveOpenLineageAdapter(adapter_id="ol-test")

    def test_adapter_id(self, adapter):
        """Adapter should return the ID it was created with."""
        assert adapter.id() == "ol-test"

    def test_adapter_capabilities(self, adapter):
        """OpenLineage adapter should declare expected capabilities."""
        caps = adapter.capabilities()
        assert Capability.DISCOVER_ASSETS in caps
        assert Capability.EXTRACT_TABLE_LINEAGE in caps
        assert Capability.EXTRACT_COLUMN_LINEAGE in caps
        assert Capability.GET_RUNS_LOGS in caps
        # Should NOT have BI capabilities
        assert Capability.GET_BI_EXPOSURES not in caps

    def test_discover_assets_from_preloaded_events(self, adapter, sample_events):
        """
        discover_assets with pre-loaded events should produce nodes
        for jobs and datasets without any network calls.
        """
        config = {"events": sample_events}
        nodes = adapter.discover_assets(config)

        assert len(nodes) > 0

        node_names = {n.name for n in nodes}
        # Jobs
        assert "etl_dag.load_orders" in node_names
        assert "etl_dag.transform_metrics" in node_names
        # Datasets
        assert "stripe_charges" in node_names
        assert "orders" in node_names
        assert "order_metrics" in node_names

    def test_extract_lineage_from_preloaded_events(self, adapter, sample_events):
        """
        extract_lineage with pre-loaded events should produce edges
        between jobs and datasets.
        """
        config = {"events": sample_events}
        edges = adapter.extract_lineage(config)

        assert len(edges) > 0

        # Check edge types — should have READS_FROM and WRITES_TO
        edge_types = {e.edge_type for e in edges}
        assert EdgeType.READS_FROM in edge_types
        assert EdgeType.WRITES_TO in edge_types

    def test_extract_lineage_cross_plane_edges(self, adapter, sample_events):
        """
        Edges from OpenLineage should be CROSS plane (job <-> dataset).
        """
        config = {"events": sample_events}
        edges = adapter.extract_lineage(config)

        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]
        assert len(cross_edges) > 0

    def test_discover_assets_empty_events(self, adapter):
        """Empty event list should produce no nodes."""
        config = {"events": []}
        nodes = adapter.discover_assets(config)
        assert nodes == []

    def test_extract_lineage_empty_events(self, adapter):
        """Empty event list should produce no edges."""
        config = {"events": []}
        edges = adapter.extract_lineage(config)
        assert edges == []

    def test_nodes_have_platform_info(self, adapter, sample_events):
        """Nodes should have platform and platform_domain set."""
        config = {"events": sample_events}
        nodes = adapter.discover_assets(config)

        for node in nodes:
            assert node.platform is not None
            assert node.platform_domain is not None

        # Job nodes should have airflow platform
        job_nodes = [n for n in nodes if n.name.startswith("etl_dag.")]
        for jn in job_nodes:
            assert jn.platform == "airflow"
            assert jn.platform_domain == PlatformDomain.ORCHESTRATION

        # Dataset nodes should have bigquery platform
        ds_nodes = [n for n in nodes if n.platform == "bigquery"]
        for dn in ds_nodes:
            assert dn.platform_domain == PlatformDomain.WAREHOUSE

    def test_edges_have_evidence(self, adapter, sample_events):
        """Each edge should carry evidence with the adapter ID."""
        config = {"events": sample_events}
        edges = adapter.extract_lineage(config)

        for edge in edges:
            # At minimum table-level edges should have evidence
            if edge.lineage_level == LineageLevel.TABLE:
                assert len(edge.evidence) > 0
                assert edge.evidence[0].adapter_id == "ol-test"

    def test_openlineage_with_column_lineage_facet(self, adapter):
        """
        Events with columnLineage facets should produce column-level edges.
        """
        events = [
            {
                "eventType": "COMPLETE",
                "eventTime": "2024-06-01T12:00:00Z",
                "run": {"runId": "run-col-1"},
                "job": {
                    "namespace": "airflow://prod",
                    "name": "col_test_job",
                },
                "inputs": [],
                "outputs": [
                    {
                        "namespace": "bigquery",
                        "name": "analytics.summary",
                        "facets": {
                            "columnLineage": {
                                "fields": {
                                    "total_amount": {
                                        "inputFields": [
                                            {
                                                "namespace": "bigquery",
                                                "name": "raw.orders",
                                                "field": "amount",
                                            }
                                        ],
                                        "transformationDescription": "SUM(amount)",
                                    }
                                }
                            }
                        },
                    }
                ],
            }
        ]

        config = {"events": events}
        edges = adapter.extract_lineage(config)

        column_edges = [e for e in edges if e.lineage_level == LineageLevel.COLUMN]
        assert len(column_edges) > 0

        # Check that column mappings are present
        col_edge = column_edges[0]
        assert len(col_edge.column_mappings) > 0
        assert col_edge.column_mappings[0].from_column == "amount"
        assert col_edge.column_mappings[0].to_column == "total_amount"

    def test_full_graph_with_openlineage_nodes(self, adapter, sample_events):
        """
        Nodes and edges from OpenLineage should successfully load
        into a LineageGraph for further analysis.
        """
        config = {"events": sample_events}
        nodes = adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)

        graph = LineageGraph()
        for node in nodes:
            graph.add_node(node)
        for edge in edges:
            graph.add_edge(edge)

        assert len(graph.nodes) > 0
        assert len(graph.edges) > 0

        # Build control plane — should have airflow and bigquery tool nodes
        cp = build_control_plane_graph(graph)
        cp_types = {n.tool_type for n in cp.nodes}
        assert "airflow" in cp_types
        assert "bigquery" in cp_types
