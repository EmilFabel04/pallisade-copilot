"""
Tests for the canonical data model extensions in graph.py and ids.py.
"""

import pytest
from datetime import datetime

from scanner.lineage.graph import (
    AssetKind,
    ColumnMapping,
    Evidence,
    HealthStatus,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    NodeType,
    EdgeType,
    PlatformDomain,
    TimeWindow,
    generate_stable_id,
)
from scanner.lineage.engine.ids import (
    generate_asset_id,
    generate_edge_id,
    normalize_identifier,
    normalize_fqn,
)


# ---- Stable ID tests ----

class TestStableId:
    def test_deterministic(self):
        """Same inputs always produce the same ID."""
        id1 = generate_stable_id("warehouse", "acme", "public", "users")
        id2 = generate_stable_id("warehouse", "acme", "public", "users")
        assert id1 == id2

    def test_case_insensitive(self):
        """IDs are case-insensitive."""
        id1 = generate_stable_id("WAREHOUSE", "ACME", "PUBLIC", "USERS")
        id2 = generate_stable_id("warehouse", "acme", "public", "users")
        assert id1 == id2

    def test_different_inputs_different_ids(self):
        """Different inputs produce different IDs."""
        id1 = generate_stable_id("warehouse", "acme", "public", "users")
        id2 = generate_stable_id("warehouse", "acme", "public", "orders")
        assert id1 != id2

    def test_id_length(self):
        """IDs are 16 hex characters."""
        id_ = generate_stable_id("warehouse", "ns", "c", "t")
        assert len(id_) == 16
        assert all(c in "0123456789abcdef" for c in id_)

    def test_platform_independent(self):
        """Same physical asset from different systems gets same stable_id."""
        id1 = generate_stable_id("warehouse", "acme", "public", "users")
        id2 = generate_stable_id("warehouse", "acme", "public", "users")
        assert id1 == id2


class TestGenerateAssetId:
    def test_deterministic(self):
        id1 = generate_asset_id("warehouse", "postgres", "acme", "public", "users")
        id2 = generate_asset_id("warehouse", "postgres", "acme", "public", "users")
        assert id1 == id2

    def test_different_containers(self):
        id1 = generate_asset_id("warehouse", "pg", "ns", "schema_a", "t")
        id2 = generate_asset_id("warehouse", "pg", "ns", "schema_b", "t")
        assert id1 != id2


class TestGenerateEdgeId:
    def test_deterministic(self):
        id1 = generate_edge_id("a", "b", "depends_on", "table", "ref1")
        id2 = generate_edge_id("a", "b", "depends_on", "table", "ref1")
        assert id1 == id2

    def test_different_evidence_ref(self):
        """Same relationship from different adapters gets different edge IDs."""
        id1 = generate_edge_id("a", "b", "depends_on", "table", "adapter1")
        id2 = generate_edge_id("a", "b", "depends_on", "table", "adapter2")
        assert id1 != id2


# ---- Identifier normalization tests ----

class TestNormalizeIdentifier:
    @pytest.mark.parametrize("input_,hint,expected", [
        ('`my_table`', "lower", "my_table"),
        ('"MY_TABLE"', "lower", "my_table"),
        ("[dbo]", "lower", "dbo"),
        ("MyTable", "upper", "MYTABLE"),
        ('"MyTable"', "preserve", "MyTable"),
        ('`project.dataset.table`', "lower", "project.dataset.table"),
    ])
    def test_normalization(self, input_, hint, expected):
        assert normalize_identifier(input_, hint) == expected

    def test_default_lowercase(self):
        assert normalize_identifier("FOO") == "foo"


class TestNormalizeFqn:
    def test_full_fqn(self):
        assert normalize_fqn("DB", "SCHEMA", "TABLE", "lower") == "db.schema.table"

    def test_skips_empty_parts(self):
        assert normalize_fqn("", "public", "users", "lower") == "public.users"

    def test_upper_hint(self):
        assert normalize_fqn("db", "public", "users", "upper") == "DB.PUBLIC.USERS"


# ---- Evidence / ColumnMapping / TimeWindow tests ----

class TestEvidence:
    def test_serialization(self):
        now = datetime(2025, 1, 15, 12, 0, 0)
        ev = Evidence(
            adapter_id="wh1",
            source_ref="view_def:my_view",
            observed_at=now,
            snippet="SELECT * FROM t",
            payload={"key": "val"},
        )
        d = ev.to_dict()
        assert d["adapter_id"] == "wh1"
        assert d["observed_at"] == "2025-01-15T12:00:00"

        ev2 = Evidence.from_dict(d)
        assert ev2.adapter_id == ev.adapter_id
        assert ev2.observed_at == ev.observed_at
        assert ev2.payload == {"key": "val"}

    def test_snippet_max_length(self):
        """Snippets should be <=200 chars by convention."""
        ev = Evidence(adapter_id="a", source_ref="r", snippet="x" * 200)
        assert len(ev.snippet) == 200


class TestColumnMapping:
    def test_serialization(self):
        m = ColumnMapping(from_column="id", to_column="customer_id", confidence=0.95)
        d = m.to_dict()
        assert d["from_column"] == "id"
        assert d["confidence"] == 0.95

        m2 = ColumnMapping.from_dict(d)
        assert m2.from_column == m.from_column


class TestTimeWindow:
    def test_serialization(self):
        tw = TimeWindow(
            start=datetime(2025, 1, 1),
            end=datetime(2025, 1, 31),
        )
        d = tw.to_dict()
        tw2 = TimeWindow.from_dict(d)
        assert tw2.start == tw.start
        assert tw2.end == tw.end


# ---- Extended LineageNode tests ----

class TestLineageNodeExtensions:
    def test_default_values(self):
        """New fields have backward-compatible defaults."""
        node = LineageNode(id="n1", name="t", fqn="t", node_type=NodeType.TABLE)
        assert node.platform_domain == PlatformDomain.OTHER
        assert node.asset_kind == AssetKind.UNKNOWN
        assert node.namespace is None
        assert node.sources == []

    def test_stable_id_property(self):
        node = LineageNode(
            id="n1", name="users", fqn="public.users",
            node_type=NodeType.TABLE, platform="postgres",
            database="warehouse", schema="public",
            platform_domain=PlatformDomain.WAREHOUSE,
        )
        sid = node.stable_id
        assert len(sid) == 16
        # Stable across accesses
        assert node.stable_id == sid

    def test_to_dict_includes_new_fields(self):
        node = LineageNode(
            id="n1", name="t", fqn="t", node_type=NodeType.TABLE,
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE,
            sources=["wh1"],
        )
        d = node.to_dict()
        assert d["platform_domain"] == "warehouse"
        assert d["asset_kind"] == "table"
        assert d["sources"] == ["wh1"]


# ---- Extended LineageEdge tests ----

class TestLineageEdgeExtensions:
    def test_default_values(self):
        edge = LineageEdge(
            id="e1", source_id="s", target_id="t",
            edge_type=EdgeType.DEPENDS_ON,
        )
        assert edge.lineage_level == LineageLevel.TABLE
        assert edge.evidence == []
        assert edge.column_mappings == []
        assert edge.time_window is None

    def test_to_dict_includes_new_fields(self):
        edge = LineageEdge(
            id="e1", source_id="s", target_id="t",
            edge_type=EdgeType.DEPENDS_ON,
            lineage_level=LineageLevel.COLUMN,
            evidence=[Evidence(adapter_id="a", source_ref="r")],
            column_mappings=[ColumnMapping(from_column="id", to_column="uid")],
        )
        d = edge.to_dict()
        assert d["lineage_level"] == "column"
        assert len(d["evidence"]) == 1
        assert len(d["column_mappings"]) == 1


# ---- Graph index tests ----

class TestGraphEngineIndexes:
    def test_by_asset_kind_index(self):
        g = LineageGraph()
        g.add_node(LineageNode(
            id="n1", name="t", fqn="t", node_type=NodeType.TABLE,
            asset_kind=AssetKind.TABLE,
        ))
        g.add_node(LineageNode(
            id="n2", name="d", fqn="d", node_type=NodeType.DASHBOARD,
            asset_kind=AssetKind.DASHBOARD,
        ))
        assert "n1" in g._by_asset_kind[AssetKind.TABLE]
        assert "n2" in g._by_asset_kind[AssetKind.DASHBOARD]

    def test_by_lineage_level_index(self):
        g = LineageGraph()
        g.add_node(LineageNode(id="a", name="a", fqn="a", node_type=NodeType.TABLE))
        g.add_node(LineageNode(id="b", name="b", fqn="b", node_type=NodeType.TABLE))
        g.add_edge(LineageEdge(
            id="e1", source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON,
            lineage_level=LineageLevel.TABLE,
        ))
        g.add_edge(LineageEdge(
            id="e2", source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON,
            lineage_level=LineageLevel.COLUMN,
        ))
        assert "e1" in g._by_lineage_level[LineageLevel.TABLE]
        assert "e2" in g._by_lineage_level[LineageLevel.COLUMN]

    def test_confidence_bucket_index(self):
        g = LineageGraph()
        g.add_node(LineageNode(id="a", name="a", fqn="a", node_type=NodeType.TABLE))
        g.add_node(LineageNode(id="b", name="b", fqn="b", node_type=NodeType.TABLE))
        g.add_edge(LineageEdge(
            id="e_low", source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON, confidence=0.3,
        ))
        g.add_edge(LineageEdge(
            id="e_high", source_id="a", target_id="b",
            edge_type=EdgeType.DEPENDS_ON, confidence=0.95,
        ))
        assert "e_low" in g._by_confidence_bucket["low"]
        assert "e_high" in g._by_confidence_bucket["high"]


class TestGraphDeserialization:
    def test_roundtrip_with_new_fields(self):
        g = LineageGraph()
        g.add_node(LineageNode(
            id="n1", name="t", fqn="s.t", node_type=NodeType.TABLE,
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.TABLE,
            namespace="prod",
            sources=["wh1"],
        ))
        g.add_node(LineageNode(
            id="n2", name="v", fqn="s.v", node_type=NodeType.VIEW,
            platform_domain=PlatformDomain.WAREHOUSE,
            asset_kind=AssetKind.VIEW,
        ))
        g.add_edge(LineageEdge(
            id="e1", source_id="n1", target_id="n2",
            edge_type=EdgeType.DEPENDS_ON,
            lineage_level=LineageLevel.TABLE,
            evidence=[Evidence(adapter_id="wh", source_ref="test")],
            column_mappings=[ColumnMapping(from_column="a", to_column="b")],
        ))

        data = g.to_dict()
        g2 = LineageGraph.from_dict(data)

        assert g2.nodes["n1"].platform_domain == PlatformDomain.WAREHOUSE
        assert g2.nodes["n1"].sources == ["wh1"]
        assert g2.edges["e1"].lineage_level == LineageLevel.TABLE
        assert len(g2.edges["e1"].evidence) == 1
        assert len(g2.edges["e1"].column_mappings) == 1
