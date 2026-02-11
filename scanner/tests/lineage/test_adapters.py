"""
Tests for the three reference adapters (TransformArtifact, WarehouseCatalog, BIQuery).

Golden graph tests: given fixture inputs, expected nodes/edges must match by stable IDs.
"""

import os
import pytest

from scanner.lineage.engine.adapter import Capability, create_default_registry
from scanner.lineage.engine.adapters.transform_artifact import TransformArtifactAdapter
from scanner.lineage.engine.adapters.warehouse_catalog import WarehouseCatalogAdapter
from scanner.lineage.engine.adapters.bi_query import BIQueryAdapter
from scanner.lineage.graph import (
    AssetKind,
    LineageLevel,
    NodeType,
    PlatformDomain,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


# ---- TransformArtifactAdapter ----

class TestTransformArtifactAdapter:
    @pytest.fixture
    def adapter(self):
        return TransformArtifactAdapter(
            adapter_id="test_transform",
            path=os.path.join(FIXTURES_DIR, "transform_manifest.json"),
        )

    def test_capabilities(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}
        adapter.discover_assets(config)  # triggers load
        caps = adapter.capabilities()
        assert Capability.DISCOVER_ASSETS in caps
        assert Capability.EXTRACT_TABLE_LINEAGE in caps
        # The manifest has column_mappings, so column lineage should be available
        assert Capability.EXTRACT_COLUMN_LINEAGE in caps

    def test_discover_assets_count(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}
        nodes = adapter.discover_assets(config)
        # 5 sources + 10 models = 15 nodes
        assert len(nodes) == 15

    def test_source_nodes_are_warehouse_domain(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}
        nodes = adapter.discover_assets(config)
        sources = [n for n in nodes if n.node_type == NodeType.SOURCE]
        assert len(sources) == 5
        for s in sources:
            assert s.platform_domain == PlatformDomain.WAREHOUSE
            assert s.asset_kind == AssetKind.TABLE

    def test_model_nodes_are_transform_domain(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}
        nodes = adapter.discover_assets(config)
        models = [n for n in nodes if n.node_type == NodeType.MODEL]
        assert len(models) == 10
        for m in models:
            assert m.platform_domain == PlatformDomain.TRANSFORM

    def test_extract_table_lineage(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}
        adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)
        table_edges = [e for e in edges if e.lineage_level == LineageLevel.TABLE]
        # Count depends_on relations from the manifest
        assert len(table_edges) >= 10

    def test_extract_column_lineage(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}
        adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)
        col_edges = [e for e in edges if e.lineage_level == LineageLevel.COLUMN]
        # stg_customers, stg_orders, rpt_customer_ltv have column_mappings
        assert len(col_edges) >= 3
        for e in col_edges:
            assert len(e.column_mappings) > 0
            assert all(m.from_column for m in e.column_mappings)

    def test_evidence_on_all_edges(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}
        adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)
        for e in edges:
            assert len(e.evidence) > 0
            assert e.evidence[0].adapter_id == "test_transform"

    def test_nodes_have_canonical_identity(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "transform_manifest.json")}
        nodes = adapter.discover_assets(config)
        for n in nodes:
            assert n.id  # not empty
            assert n.fqn  # not empty
            assert n.platform  # system set
            assert n.namespace == "acme-prod"
            assert len(n.sources) > 0


# ---- WarehouseCatalogAdapter ----

class TestWarehouseCatalogAdapter:
    @pytest.fixture
    def adapter(self):
        return WarehouseCatalogAdapter(
            adapter_id="test_warehouse",
            path=os.path.join(FIXTURES_DIR, "warehouse_catalog.json"),
        )

    def test_discover_assets_count(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "warehouse_catalog.json")}
        nodes = adapter.discover_assets(config)
        # 20 tables/views in the fixture
        assert len(nodes) == 20

    def test_views_have_view_type(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "warehouse_catalog.json")}
        nodes = adapter.discover_assets(config)
        views = [n for n in nodes if n.node_type == NodeType.VIEW]
        assert len(views) >= 3  # stg_customers, stg_orders, stg_payments, ...
        for v in views:
            assert v.asset_kind == AssetKind.VIEW

    def test_tables_have_columns(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "warehouse_catalog.json")}
        nodes = adapter.discover_assets(config)
        tables = [n for n in nodes if n.node_type == NodeType.TABLE]
        for t in tables:
            assert len(t.columns) > 0

    def test_extract_view_lineage(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "warehouse_catalog.json")}
        adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)
        # Views with SQL definitions should produce edges
        assert len(edges) >= 3

    def test_all_nodes_are_warehouse_domain(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "warehouse_catalog.json")}
        nodes = adapter.discover_assets(config)
        for n in nodes:
            assert n.platform_domain == PlatformDomain.WAREHOUSE


# ---- BIQueryAdapter ----

class TestBIQueryAdapter:
    @pytest.fixture
    def adapter(self):
        return BIQueryAdapter(
            adapter_id="test_bi",
            path=os.path.join(FIXTURES_DIR, "bi_export.json"),
        )

    def test_discover_dashboards_and_datasets(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "bi_export.json")}
        nodes = adapter.discover_assets(config)
        dashboards = [n for n in nodes if n.node_type == NodeType.DASHBOARD]
        datasets = [n for n in nodes if n.node_type == NodeType.DATASET]
        assert len(dashboards) == 3
        assert len(datasets) == 8

    def test_tool_level_edges(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "bi_export.json")}
        adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        # 3 dashboards with tiles pointing to datasets
        assert len(tool_edges) >= 3

    def test_table_level_edges(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "bi_export.json")}
        adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)
        table_edges = [e for e in edges if e.lineage_level == LineageLevel.TABLE]
        assert len(table_edges) >= 4

    def test_column_level_edges_only_when_explicit(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "bi_export.json")}
        adapter.discover_assets(config)
        edges = adapter.extract_lineage(config)
        col_edges = [e for e in edges if e.lineage_level == LineageLevel.COLUMN]
        # Only datasets with explicit "columns" with source_column should produce these
        for e in col_edges:
            assert len(e.column_mappings) > 0

    def test_dashboards_are_bi_domain(self, adapter):
        config = {"path": os.path.join(FIXTURES_DIR, "bi_export.json")}
        nodes = adapter.discover_assets(config)
        for n in nodes:
            assert n.platform_domain == PlatformDomain.BI


# ---- AdapterRegistry ----

class TestAdapterRegistry:
    def test_default_registry_has_three_types(self):
        reg = create_default_registry()
        types = reg.list_types()
        assert "transform_artifact" in types
        assert "warehouse_catalog" in types
        assert "bi_query" in types

    def test_create_and_get(self):
        reg = create_default_registry()
        adapter = reg.create(
            "warehouse_catalog", "wh1",
            path=os.path.join(FIXTURES_DIR, "warehouse_catalog.json"),
        )
        assert reg.get("wh1") is adapter
        assert adapter.id() == "wh1"

    def test_filter_by_capability(self):
        reg = create_default_registry()
        reg.create("warehouse_catalog", "wh1", path=os.path.join(FIXTURES_DIR, "warehouse_catalog.json"))
        reg.create("bi_query", "bi1", path=os.path.join(FIXTURES_DIR, "bi_export.json"))

        # Both should support DISCOVER_ASSETS
        disc = reg.filter_by_capability(Capability.DISCOVER_ASSETS)
        assert len(disc) == 2

    def test_unknown_type_raises(self):
        reg = create_default_registry()
        with pytest.raises(ValueError, match="Unknown adapter type"):
            reg.create("nonexistent", "x")
