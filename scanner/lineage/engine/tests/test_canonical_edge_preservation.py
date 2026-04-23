"""
Stress test: canonical edge preservation when bridge rules create inferred
edges and re-canonicalization runs.

Verifies that canonicalize_graph_in_place() respects the preservation guard
(canonical.py line 307: ``if edge.canonical_edge_type: continue``) for
bridge-created edges.

Why this matters:
    Without the guard, re-canonicalization would call infer_canonical_edge_type()
    on bridge edges, potentially overwriting their explicit canonical_edge_type
    with different values from semantic overrides.  In live runs this path was
    never exercised because bridge produced 0 changes, so re-canonicalize was
    skipped.  This test ensures the guard works for non-trivial bridge output.
"""

import pytest

from scanner.lineage.graph import (
    EdgeType,
    LineageEdge,
    LineageGraph,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.bridge import BridgeRuleEngine
from scanner.lineage.engine.canonical import (
    canonicalize_graph_in_place,
)


# ---- Helpers ----


def _make_service_node() -> LineageNode:
    """Fivetran service node (ingestion platform, canonical_type=service)."""
    return LineageNode(
        id="node:fivetran:svc",
        name="Fivetran",
        fqn="fivetran.service",
        node_type=NodeType.CONNECTOR,
        platform="fivetran",
        platform_domain=PlatformDomain.INGESTION,
        canonical_type="service",
        integration_id="ft-default",
    )


def _make_raw_dataset(name: str, schema: str = "raw") -> LineageNode:
    """Raw warehouse dataset node — orphan (no upstream edges)."""
    return LineageNode(
        id=f"node:bigquery:{name}",
        name=name,
        fqn=f"project.{schema}.{name}",
        node_type=NodeType.TABLE,
        platform="bigquery",
        platform_domain=PlatformDomain.WAREHOUSE,
        database="project",
        schema=schema,
        canonical_type="dataset",
        raw_metadata={"zone": "raw"},
    )


# ---- Fixtures ----


@pytest.fixture
def bridge_graph() -> LineageGraph:
    """Minimal graph: Fivetran service + one orphan raw dataset.

    No ingestion *job* nodes exist, so the bridge will create an
    Unknown Loader node plus writes/runs edges.
    """
    graph = LineageGraph()
    graph.add_node(_make_service_node())
    graph.add_node(_make_raw_dataset("raw_orders"))
    return graph


# ---- Tests ----


class TestCanonicalEdgePreservationUnderBridge:
    """Bridge-created edges must survive re-canonicalization unchanged."""

    def test_bridge_then_recanonicalize_preserves_all_edge_properties(
        self, bridge_graph: LineageGraph,
    ):
        """Core round-trip: canonicalize → bridge → re-canonicalize.

        Every bridge edge property (canonical_edge_type, confidence,
        inferred, edge_type, discovered_from, evidence) must be
        identical before and after re-canonicalization.
        """
        graph = bridge_graph

        # 1. Initial canonicalization (sets node URNs, no edges yet)
        canonicalize_graph_in_place(graph.nodes, graph.edges)
        assert len(graph.edges) == 0

        # 2. Apply bridge rules — creates Unknown Loader + edges
        result = BridgeRuleEngine(graph).apply_all()

        assert result.total_changes > 0, "Bridge should produce changes"
        assert len(result.added_nodes) >= 1, "Bridge should create Unknown Loader"
        assert len(result.added_edges) >= 2, "Bridge should create writes + runs edges"

        # Verify bridge set canonical_edge_type on ALL created edges
        for edge in result.added_edges:
            assert edge.canonical_edge_type is not None, (
                f"Bridge edge {edge.id} missing canonical_edge_type"
            )

        # 3. Snapshot bridge edge properties BEFORE re-canonicalization
        snapshots = {}
        for edge in graph.edges.values():
            snapshots[edge.id] = {
                "canonical_edge_type": edge.canonical_edge_type,
                "confidence": edge.confidence,
                "inferred": edge.inferred,
                "edge_type": edge.edge_type,
                "discovered_from": edge.discovered_from,
                "evidence_count": len(edge.evidence),
                "evidence_adapter_ids": [e.adapter_id for e in edge.evidence],
            }

        # 4. Re-canonicalize — the preservation guard must skip bridge edges
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        # 5. Assert every property is unchanged
        for edge in graph.edges.values():
            snap = snapshots[edge.id]
            assert edge.canonical_edge_type == snap["canonical_edge_type"], (
                f"Edge {edge.id}: canonical_edge_type changed from "
                f"'{snap['canonical_edge_type']}' to '{edge.canonical_edge_type}'"
            )
            assert edge.confidence == snap["confidence"], (
                f"Edge {edge.id}: confidence changed from "
                f"{snap['confidence']} to {edge.confidence}"
            )
            assert edge.inferred is snap["inferred"], (
                f"Edge {edge.id}: inferred changed from "
                f"{snap['inferred']} to {edge.inferred}"
            )
            assert edge.edge_type == snap["edge_type"], (
                f"Edge {edge.id}: edge_type changed"
            )
            assert edge.discovered_from == snap["discovered_from"], (
                f"Edge {edge.id}: discovered_from changed"
            )
            assert len(edge.evidence) == snap["evidence_count"], (
                f"Edge {edge.id}: evidence count changed"
            )

        # 6. Semantic checks on the bridge output
        writes_edges = [
            e for e in graph.edges.values()
            if e.canonical_edge_type == "writes"
        ]
        runs_edges = [
            e for e in graph.edges.values()
            if e.canonical_edge_type == "runs"
        ]
        assert len(writes_edges) >= 1, "Expected at least one writes edge"
        assert len(runs_edges) >= 1, "Expected at least one runs edge"

        for e in writes_edges:
            assert e.inferred is True
            assert e.confidence <= 0.5
            assert any(ev.adapter_id == "bridge_rule" for ev in e.evidence)

        for e in runs_edges:
            assert e.inferred is True
            assert e.confidence <= 0.5
            assert any(ev.adapter_id == "bridge_rule" for ev in e.evidence)

        # 7. The raw dataset is no longer an orphan
        raw_node = graph.nodes["node:bigquery:raw_orders"]
        upstream_ids = graph._upstream.get(raw_node.id, set())
        assert len(upstream_ids) >= 1, (
            "raw_orders should have an upstream writer after bridge"
        )

    def test_multiple_recanonicalize_passes_are_idempotent(
        self, bridge_graph: LineageGraph,
    ):
        """Running canonicalize_graph_in_place() N times after bridge must
        produce identical results every time."""
        graph = bridge_graph
        canonicalize_graph_in_place(graph.nodes, graph.edges)
        BridgeRuleEngine(graph).apply_all()

        # Snapshot after bridge
        initial = {
            eid: (e.canonical_edge_type, e.confidence, e.inferred)
            for eid, e in graph.edges.items()
        }

        for pass_num in range(5):
            canonicalize_graph_in_place(graph.nodes, graph.edges)
            for eid, edge in graph.edges.items():
                orig = initial[eid]
                assert edge.canonical_edge_type == orig[0], (
                    f"Pass {pass_num + 1}: edge {eid} canonical_edge_type "
                    f"drifted from '{orig[0]}' to '{edge.canonical_edge_type}'"
                )
                assert edge.confidence == orig[1], (
                    f"Pass {pass_num + 1}: edge {eid} confidence drifted"
                )
                assert edge.inferred is orig[2], (
                    f"Pass {pass_num + 1}: edge {eid} inferred drifted"
                )

    def test_bridge_edges_not_in_unmapped_set(
        self, bridge_graph: LineageGraph,
    ):
        """Re-canonicalize result must not flag bridge edges as unmapped."""
        graph = bridge_graph
        canonicalize_graph_in_place(graph.nodes, graph.edges)
        BridgeRuleEngine(graph).apply_all()

        result = canonicalize_graph_in_place(graph.nodes, graph.edges)

        assert "writes_to" not in result["unmapped_edge_types"]
        assert "triggers" not in result["unmapped_edge_types"]

        # Unknown Loader has canonical_type="job" set by bridge —
        # must NOT appear in needs_mapping
        for node in graph.nodes.values():
            if node.inferred:
                assert node.id not in result["needs_mapping"], (
                    f"Inferred node {node.id} should not need mapping"
                )

    def test_non_bridge_edge_still_gets_inferred(
        self, bridge_graph: LineageGraph,
    ):
        """Edges WITHOUT canonical_edge_type must still be inferred.

        Proves the preservation guard is selective: it only skips edges
        that already have canonical_edge_type, not all edges.
        """
        graph = bridge_graph
        canonicalize_graph_in_place(graph.nodes, graph.edges)
        BridgeRuleEngine(graph).apply_all()

        # Add a manual edge with NO canonical_edge_type
        manual_edge = LineageEdge(
            id="edge:manual_test",
            source_id="node:fivetran:svc",
            target_id="node:bigquery:raw_orders",
            edge_type=EdgeType.READS_FROM,
            # canonical_edge_type deliberately left unset (None)
        )
        graph.add_edge(manual_edge)
        assert manual_edge.canonical_edge_type is None

        canonicalize_graph_in_place(graph.nodes, graph.edges)

        # Manual edge SHOULD have been inferred
        assert manual_edge.canonical_edge_type is not None, (
            "Edge without canonical_edge_type should be inferred"
        )

        # Bridge edges SHOULD still be preserved
        for edge in graph.edges.values():
            if edge.id == "edge:manual_test":
                continue
            assert edge.inferred is True
            assert edge.canonical_edge_type in ("writes", "runs")

    def test_scale_stress_many_orphans(self):
        """50 orphans → 50 writes + 1 runs edge, all preserved after
        re-canonicalize."""
        graph = LineageGraph()
        graph.add_node(_make_service_node())
        for i in range(50):
            graph.add_node(_make_raw_dataset(f"raw_table_{i}"))

        canonicalize_graph_in_place(graph.nodes, graph.edges)

        result = BridgeRuleEngine(graph).apply_all()

        writes_edges = [
            e for e in result.added_edges
            if e.canonical_edge_type == "writes"
        ]
        runs_edges = [
            e for e in result.added_edges
            if e.canonical_edge_type == "runs"
        ]
        assert len(writes_edges) == 50
        # Bridge creates runs edges from service → each same-platform job
        # in the index (which includes the service node itself) AND
        # service → Unknown Loader.
        assert len(runs_edges) >= 1

        # Snapshot all edges
        snapshot = {
            eid: (e.canonical_edge_type, e.confidence, e.inferred)
            for eid, e in graph.edges.items()
        }

        # Re-canonicalize
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        # Every edge must be unchanged
        for eid, edge in graph.edges.items():
            orig = snapshot[eid]
            assert edge.canonical_edge_type == orig[0], (
                f"Edge {eid}: canonical_edge_type changed"
            )
            assert edge.confidence == orig[1], (
                f"Edge {eid}: confidence changed"
            )
            assert edge.inferred is orig[2], (
                f"Edge {eid}: inferred changed"
            )
