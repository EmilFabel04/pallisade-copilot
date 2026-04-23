"""
Tests for scanner.lineage.engine.reconciler

Covers:
- DiagnosticsBuilder: dataset roots, disconnected components, duplicates, missing links
- PatchValidator: merge validation, edge validation, layer validation
- PatchApplier: merge application, node/edge addition, layer assignment
- ReconciliationEngine: full pipeline with mocked LLM
"""

import pytest
from unittest.mock import AsyncMock, patch

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
from scanner.lineage.engine.canonical import canonicalize_graph_in_place
from scanner.lineage.engine.reconciler import (
    AddEdgePatch,
    AddNodePatch,
    DiagnosticsBuilder,
    GraphDiagnostics,
    LayerAssignment,
    LLMReconciler,
    MergeSuggestion,
    PatchApplier,
    PatchValidator,
    ReconcilerConfig,
    ReconciliationEngine,
    ReconciliationPatch,
    UnknownItem,
)


# ---- Helpers ----


def _make_node(
    name: str,
    node_type: NodeType = NodeType.TABLE,
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    platform: str = "bigquery",
    namespace: str = "project1",
    fqn: str = "",
    database: str = None,
    schema: str = None,
    canonical_type: str = "dataset",
    integration_id: str = None,
    inferred: bool = False,
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
        canonical_type=canonical_type,
        integration_id=integration_id,
        inferred=inferred,
    )


def _make_edge(
    source: str,
    target: str,
    edge_type: EdgeType = EdgeType.DERIVED_FROM,
    confidence: float = 1.0,
    canonical_edge_type: str = "derives",
) -> LineageEdge:
    return LineageEdge(
        id=f"edge:{source}->{target}",
        source_id=f"node:{source}",
        target_id=f"node:{target}",
        edge_type=edge_type,
        confidence=confidence,
        canonical_edge_type=canonical_edge_type,
        evidence=[Evidence(adapter_id="test", source_ref="test")],
    )


def _build_simple_graph() -> LineageGraph:
    """Build a simple graph: raw_orders -> stg_orders -> orders."""
    graph = LineageGraph()
    graph.add_node(_make_node("raw_orders"))
    graph.add_node(_make_node("stg_orders", platform="dbt",
                              platform_domain=PlatformDomain.TRANSFORM))
    graph.add_node(_make_node("orders", platform="dbt",
                              platform_domain=PlatformDomain.TRANSFORM))
    graph.add_edge(_make_edge("raw_orders", "stg_orders"))
    graph.add_edge(_make_edge("stg_orders", "orders"))
    return graph


def _build_graph_with_roots() -> LineageGraph:
    """Build a graph with dataset roots (no upstream) and an n8n node."""
    graph = LineageGraph()
    # Warehouse tables with no upstream (roots)
    graph.add_node(_make_node("raw_orders"))
    graph.add_node(_make_node("raw_customers"))
    # Transform output
    graph.add_node(_make_node("stg_orders", platform="dbt",
                              platform_domain=PlatformDomain.TRANSFORM))
    # n8n workflow (ingestion)
    graph.add_node(_make_node("sync_workflow", node_type=NodeType.WORKFLOW,
                              platform="n8n", platform_domain=PlatformDomain.INGESTION,
                              canonical_type="job"))
    # Only stg_orders has upstream
    graph.add_edge(_make_edge("raw_orders", "stg_orders"))
    return graph


def _build_graph_with_duplicates() -> LineageGraph:
    """Build a graph with suspected duplicates (same name, different platforms)."""
    graph = LineageGraph()
    graph.add_node(_make_node("orders", platform="bigquery",
                              platform_domain=PlatformDomain.WAREHOUSE))
    graph.add_node(_make_node("orders_dbt", platform="dbt",
                              platform_domain=PlatformDomain.TRANSFORM))
    # Rename the dbt node to have the same name for duplicate detection
    graph.nodes["node:orders_dbt"].name = "orders"
    graph.add_node(_make_node("customers", platform="bigquery"))
    graph.add_edge(_make_edge("customers", "orders"))
    return graph


def _build_disconnected_graph() -> LineageGraph:
    """Build a graph with disconnected components."""
    graph = LineageGraph()
    # Component 1
    graph.add_node(_make_node("raw_a"))
    graph.add_node(_make_node("stg_a"))
    graph.add_edge(_make_edge("raw_a", "stg_a"))
    # Component 2 (disconnected)
    graph.add_node(_make_node("raw_b"))
    graph.add_node(_make_node("stg_b"))
    graph.add_edge(_make_edge("raw_b", "stg_b"))
    return graph


# ==========================================
# DiagnosticsBuilder tests
# ==========================================


class TestDiagnosticsBuilder:
    def test_finds_dataset_roots(self):
        graph = _build_graph_with_roots()
        builder = DiagnosticsBuilder(graph)
        diag = builder.build()

        root_ids = {r["node_id"] for r in diag.dataset_roots}
        assert "node:raw_orders" in root_ids or "node:raw_customers" in root_ids
        # raw_customers has no upstream at all
        assert "node:raw_customers" in root_ids

    def test_no_roots_in_connected_graph(self):
        graph = _build_simple_graph()
        builder = DiagnosticsBuilder(graph)
        diag = builder.build()

        # raw_orders is a root (no upstream)
        root_ids = {r["node_id"] for r in diag.dataset_roots}
        assert "node:raw_orders" in root_ids
        # stg_orders and orders have upstream, not roots
        assert "node:stg_orders" not in root_ids
        assert "node:orders" not in root_ids

    def test_finds_disconnected_components(self):
        graph = _build_disconnected_graph()
        builder = DiagnosticsBuilder(graph)
        diag = builder.build()

        # Two equal components → the smaller one is reported
        assert len(diag.disconnected_components) >= 1

    def test_no_disconnected_in_connected_graph(self):
        graph = _build_simple_graph()
        builder = DiagnosticsBuilder(graph)
        diag = builder.build()

        assert len(diag.disconnected_components) == 0

    def test_finds_suspected_duplicates(self):
        graph = _build_graph_with_duplicates()
        builder = DiagnosticsBuilder(graph)
        diag = builder.build()

        # Should find "orders" as a suspected duplicate
        dup_names = {d["name"] for d in diag.suspected_duplicates}
        assert "orders" in dup_names

    def test_no_false_positive_duplicates(self):
        graph = _build_simple_graph()
        builder = DiagnosticsBuilder(graph)
        diag = builder.build()

        # All nodes have unique names
        assert len(diag.suspected_duplicates) == 0

    def test_finds_missing_links_hints(self):
        graph = _build_graph_with_roots()
        builder = DiagnosticsBuilder(graph)
        diag = builder.build()

        # n8n is present + warehouse roots exist → hint expected
        assert len(diag.missing_links_hints) >= 1
        hint_text = diag.missing_links_hints[0]["description"]
        assert "n8n" in hint_text.lower() or "ingestion" in hint_text.lower()

    def test_empty_graph_produces_empty_diagnostics(self):
        graph = LineageGraph()
        builder = DiagnosticsBuilder(graph)
        diag = builder.build()

        assert diag.dataset_roots == []
        assert diag.disconnected_components == []
        assert diag.suspected_duplicates == []
        assert diag.missing_links_hints == []

    def test_build_llm_input_structure(self):
        graph = _build_graph_with_roots()
        builder = DiagnosticsBuilder(graph)
        config = ReconcilerConfig(max_nodes_for_llm=100, max_edges_for_llm=100)
        llm_input = builder.build_llm_input(config)

        assert "integrations_present" in llm_input
        assert "canonical_nodes" in llm_input
        assert "canonical_edges" in llm_input
        assert "evidence_summary" in llm_input
        assert "graph_diagnostics" in llm_input
        assert isinstance(llm_input["integrations_present"], list)
        assert isinstance(llm_input["canonical_nodes"], list)

    def test_build_llm_input_truncation(self):
        graph = _build_graph_with_roots()
        builder = DiagnosticsBuilder(graph)
        config = ReconcilerConfig(max_nodes_for_llm=2, max_edges_for_llm=1)
        llm_input = builder.build_llm_input(config)

        assert len(llm_input["canonical_nodes"]) <= 2
        assert len(llm_input["canonical_edges"]) <= 1

    def test_build_llm_input_prioritizes_diagnostic_nodes(self):
        graph = _build_graph_with_roots()
        builder = DiagnosticsBuilder(graph)
        config = ReconcilerConfig(max_nodes_for_llm=2, max_edges_for_llm=100)
        llm_input = builder.build_llm_input(config)

        # Diagnostic nodes (roots) should be included even with truncation
        node_ids = {n["canonical_id"] for n in llm_input["canonical_nodes"]}
        # raw_customers is a root with no upstream — should be prioritized
        assert "node:raw_customers" in node_ids


# ==========================================
# PatchValidator tests
# ==========================================


class TestPatchValidator:
    def test_valid_patch_passes(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[],
            add_edges=[],
            layer_assignments=[],
            unknowns=[],
        )
        validator = PatchValidator(graph)
        assert validator.validate(patch) is True
        assert len(validator.errors) == 0

    def test_merge_with_missing_node_fails(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[
                MergeSuggestion(
                    keep_id="node:nonexistent",
                    merge_ids=["node:raw_orders"],
                    reason="test",
                    confidence=0.9,
                ),
            ],
            add_nodes=[], add_edges=[], layer_assignments=[], unknowns=[],
        )
        validator = PatchValidator(graph)
        assert validator.validate(patch) is False
        assert any("nonexistent" in e for e in validator.errors)

    def test_edge_to_nonexistent_node_fails(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[],
            add_edges=[
                AddEdgePatch(
                    from_id="node:raw_orders",
                    to_id="node:nonexistent",
                    edge_type="derives",
                    inferred=True,
                    confidence=0.5,
                    reason="test",
                    evidence_refs=[],
                ),
            ],
            layer_assignments=[], unknowns=[],
        )
        validator = PatchValidator(graph)
        assert validator.validate(patch) is False

    def test_edge_to_pending_node_passes(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[
                AddNodePatch(
                    canonical_id="node:new_loader",
                    node_type="job",
                    platform="n8n",
                    namespace="",
                    display_name="Loader",
                    integration_id="",
                    aliases=[],
                    inferred=True,
                    confidence=0.5,
                    reason="test",
                ),
            ],
            add_edges=[
                AddEdgePatch(
                    from_id="node:new_loader",
                    to_id="node:raw_orders",
                    edge_type="writes",
                    inferred=True,
                    confidence=0.5,
                    reason="test",
                    evidence_refs=[],
                ),
            ],
            layer_assignments=[], unknowns=[],
        )
        validator = PatchValidator(graph)
        assert validator.validate(patch) is True

    def test_circular_merge_fails(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[
                MergeSuggestion(keep_id="node:raw_orders",
                                merge_ids=["node:stg_orders"],
                                reason="test", confidence=0.9),
                MergeSuggestion(keep_id="node:stg_orders",
                                merge_ids=["node:raw_orders"],
                                reason="test", confidence=0.9),
            ],
            add_nodes=[], add_edges=[], layer_assignments=[], unknowns=[],
        )
        validator = PatchValidator(graph)
        assert validator.validate(patch) is False

    def test_invalid_canonical_type_fails(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[
                AddNodePatch(
                    canonical_id="node:bad",
                    node_type="invalid_type",
                    platform="test", namespace="", display_name="Bad",
                    integration_id="", aliases=[], inferred=True,
                    confidence=0.5, reason="test",
                ),
            ],
            add_edges=[], layer_assignments=[], unknowns=[],
        )
        validator = PatchValidator(graph)
        assert validator.validate(patch) is False

    def test_confidence_out_of_range_fails(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[
                MergeSuggestion(keep_id="node:raw_orders",
                                merge_ids=["node:stg_orders"],
                                reason="test", confidence=1.5),
            ],
            add_nodes=[], add_edges=[], layer_assignments=[], unknowns=[],
        )
        validator = PatchValidator(graph)
        assert validator.validate(patch) is False

    def test_duplicate_add_node_id_fails(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[
                AddNodePatch(canonical_id="node:dup", node_type="job",
                             platform="test", namespace="", display_name="A",
                             integration_id="", aliases=[], inferred=True,
                             confidence=0.5, reason="test"),
                AddNodePatch(canonical_id="node:dup", node_type="job",
                             platform="test", namespace="", display_name="B",
                             integration_id="", aliases=[], inferred=True,
                             confidence=0.5, reason="test"),
            ],
            add_edges=[], layer_assignments=[], unknowns=[],
        )
        validator = PatchValidator(graph)
        assert validator.validate(patch) is False


# ==========================================
# PatchApplier tests
# ==========================================


class TestPatchApplier:
    def test_merge_remaps_edges(self):
        graph = _build_graph_with_duplicates()
        # Merge orders_dbt into orders
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[
                MergeSuggestion(
                    keep_id="node:orders",
                    merge_ids=["node:orders_dbt"],
                    reason="Same table",
                    confidence=0.95,
                ),
            ],
            add_nodes=[], add_edges=[], layer_assignments=[], unknowns=[],
        )
        applier = PatchApplier(graph, "test_run")
        counts = applier.apply(patch)

        assert counts["merges"] == 1
        assert "node:orders_dbt" not in graph.nodes
        assert "node:orders" in graph.nodes

    def test_merge_copies_metadata(self):
        graph = LineageGraph()
        keep = _make_node("primary")
        keep.description = None
        remove = _make_node("secondary", platform="dbt",
                            platform_domain=PlatformDomain.TRANSFORM)
        remove.name = "primary"  # same name
        remove.description = "Important table"
        remove.tags = ["finance"]
        graph.add_node(keep)
        graph.add_node(remove)

        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[
                MergeSuggestion(keep_id="node:primary",
                                merge_ids=["node:secondary"],
                                reason="Same asset", confidence=0.9),
            ],
            add_nodes=[], add_edges=[], layer_assignments=[], unknowns=[],
        )
        applier = PatchApplier(graph, "test_run")
        applier.apply(patch)

        merged = graph.nodes["node:primary"]
        assert merged.description == "Important table"
        assert "finance" in merged.tags

    def test_add_node_creates_with_inferred_flag(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[
                AddNodePatch(
                    canonical_id="node:loader",
                    node_type="job",
                    platform="n8n",
                    namespace="",
                    display_name="N8n Loader",
                    integration_id="",
                    aliases=[],
                    inferred=True,
                    confidence=0.4,
                    reason="Ingestion tool likely writes to raw tables",
                ),
            ],
            add_edges=[], layer_assignments=[], unknowns=[],
        )
        applier = PatchApplier(graph, "test_run")
        counts = applier.apply(patch)

        assert counts["nodes_added"] == 1
        node = graph.nodes["node:loader"]
        assert node.inferred is True
        assert node.canonical_type == "job"
        assert node.platform == "n8n"
        assert node.raw_metadata["reconciler_added"] is True

    def test_add_edge_creates_with_evidence(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[],
            add_edges=[
                AddEdgePatch(
                    from_id="node:raw_orders",
                    to_id="node:orders",
                    edge_type="derives",
                    inferred=True,
                    confidence=0.6,
                    reason="Direct derivation",
                    evidence_refs=[],
                ),
            ],
            layer_assignments=[], unknowns=[],
        )
        applier = PatchApplier(graph, "test_run")
        counts = applier.apply(patch)

        assert counts["edges_added"] == 1
        # Find the new edge
        new_edges = [e for e in graph.edges.values()
                     if e.source_id == "node:raw_orders"
                     and e.target_id == "node:orders"]
        assert len(new_edges) >= 1
        edge = new_edges[-1]
        assert edge.inferred is True
        assert edge.evidence[0].adapter_id == "reconciler"

    def test_layer_assignment_updates_platform_domain(self):
        graph = _build_simple_graph()
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[],
            add_edges=[],
            layer_assignments=[
                LayerAssignment(
                    canonical_id="node:raw_orders",
                    layer="warehouse_raw",
                    reason="Raw landing table",
                    confidence=0.9,
                ),
            ],
            unknowns=[],
        )
        applier = PatchApplier(graph, "test_run")
        counts = applier.apply(patch)

        assert counts["layers_assigned"] == 1
        node = graph.nodes["node:raw_orders"]
        assert node.platform_domain == PlatformDomain.WAREHOUSE
        assert node.raw_metadata["reconciler_layer"] == "warehouse_raw"

    def test_empty_patch_is_noop(self):
        graph = _build_simple_graph()
        original_nodes = len(graph.nodes)
        original_edges = len(graph.edges)

        patch = ReconciliationPatch.empty()
        applier = PatchApplier(graph, "test_run")
        counts = applier.apply(patch)

        assert counts == {"merges": 0, "nodes_added": 0,
                          "edges_added": 0, "layers_assigned": 0}
        assert len(graph.nodes) == original_nodes
        assert len(graph.edges) == original_edges

    def test_idempotent_add_node(self):
        graph = _build_simple_graph()
        node_patch = AddNodePatch(
            canonical_id="node:loader", node_type="job",
            platform="n8n", namespace="", display_name="Loader",
            integration_id="", aliases=[], inferred=True,
            confidence=0.4, reason="test",
        )
        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[],
            add_nodes=[node_patch],
            add_edges=[], layer_assignments=[], unknowns=[],
        )

        # Apply twice
        applier1 = PatchApplier(graph, "run1")
        counts1 = applier1.apply(patch)
        assert counts1["nodes_added"] == 1

        applier2 = PatchApplier(graph, "run2")
        counts2 = applier2.apply(patch)
        assert counts2["nodes_added"] == 0  # skipped because already exists

    def test_merge_deduplicates_edges(self):
        """If merge creates duplicate edge (same src/tgt/type), keep one."""
        graph = LineageGraph()
        graph.add_node(_make_node("a"))
        graph.add_node(_make_node("b"))
        graph.add_node(_make_node("c"))
        # Both a->c and b->c exist. Merging b into a should not create
        # a duplicate a->c edge.
        graph.add_edge(_make_edge("a", "c"))
        graph.add_edge(_make_edge("b", "c"))

        patch = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[
                MergeSuggestion(keep_id="node:a", merge_ids=["node:b"],
                                reason="test", confidence=0.9),
            ],
            add_nodes=[], add_edges=[], layer_assignments=[], unknowns=[],
        )
        applier = PatchApplier(graph, "test_run")
        applier.apply(patch)

        # Should only have one edge from a->c
        edges_a_to_c = [e for e in graph.edges.values()
                        if e.source_id == "node:a" and e.target_id == "node:c"]
        assert len(edges_a_to_c) == 1


# ==========================================
# ReconciliationPatch serialization tests
# ==========================================


class TestPatchSerialization:
    def test_from_dict_roundtrip(self):
        original = ReconciliationPatch(
            patch_version="1.0",
            merge_suggestions=[
                MergeSuggestion(keep_id="a", merge_ids=["b"], reason="dup", confidence=0.9),
            ],
            add_nodes=[
                AddNodePatch(canonical_id="c", node_type="job", platform="n8n",
                             namespace="", display_name="Loader", integration_id="",
                             aliases=[], inferred=True, confidence=0.5, reason="bridge"),
            ],
            add_edges=[
                AddEdgePatch(from_id="c", to_id="a", edge_type="writes",
                             inferred=True, confidence=0.5, reason="inferred",
                             evidence_refs=[]),
            ],
            layer_assignments=[
                LayerAssignment(canonical_id="a", layer="warehouse_raw",
                                reason="raw table", confidence=0.8),
            ],
            unknowns=[
                UnknownItem(entity_ref="x", issue="unclear", suggested_action="ask",
                            questions=["What is x?"]),
            ],
        )
        serialized = original.to_dict()
        restored = ReconciliationPatch.from_dict(serialized)

        assert restored.patch_version == "1.0"
        assert len(restored.merge_suggestions) == 1
        assert restored.merge_suggestions[0].keep_id == "a"
        assert len(restored.add_nodes) == 1
        assert restored.add_nodes[0].canonical_id == "c"
        assert len(restored.add_edges) == 1
        assert len(restored.layer_assignments) == 1
        assert len(restored.unknowns) == 1

    def test_empty_patch(self):
        patch = ReconciliationPatch.empty()
        assert patch.patch_version == "1.0"
        assert len(patch.merge_suggestions) == 0
        assert len(patch.add_nodes) == 0


# ==========================================
# ReconciliationEngine integration tests
# ==========================================


class TestReconciliationEngine:
    @pytest.fixture
    def mock_patch_response(self):
        return {
            "patch_version": "1.0",
            "merge_suggestions": [],
            "add_nodes": [
                {
                    "canonical_id": "urn:job:n8n:loader",
                    "type": "job",
                    "platform": "n8n",
                    "namespace": "",
                    "display_name": "N8n Loader",
                    "integration_id": "",
                    "aliases": [],
                    "inferred": True,
                    "confidence": 0.4,
                    "reason": "n8n likely writes to raw tables",
                },
            ],
            "add_edges": [
                {
                    "from_id": "urn:job:n8n:loader",
                    "to_id": "node:raw_orders",
                    "type": "writes",
                    "inferred": True,
                    "confidence": 0.4,
                    "reason": "n8n is present and raw_orders has no upstream",
                    "evidence_refs": [],
                },
            ],
            "layer_assignments": [
                {
                    "canonical_id": "node:raw_orders",
                    "layer": "warehouse_raw",
                    "reason": "Raw landing table",
                    "confidence": 0.9,
                },
            ],
            "unknowns": [],
        }

    @pytest.mark.asyncio
    async def test_full_reconciliation_dry_run(self, mock_patch_response):
        graph = _build_graph_with_roots()

        with patch.object(
            LLMReconciler, "reconcile",
            new_callable=AsyncMock,
            return_value=(
                ReconciliationPatch.from_dict(mock_patch_response),
                1000, 500,
            ),
        ):
            engine = ReconciliationEngine(ReconcilerConfig(dry_run=True))
            result = await engine.reconcile(graph)

        assert result.success is True
        assert result.graph is None  # dry_run doesn't modify
        assert len(result.patch.add_nodes) == 1
        assert len(result.patch.add_edges) == 1
        assert result.run_id != ""

    @pytest.mark.asyncio
    async def test_full_reconciliation_apply(self, mock_patch_response):
        graph = _build_graph_with_roots()
        original_count = len(graph.nodes)

        with patch.object(
            LLMReconciler, "reconcile",
            new_callable=AsyncMock,
            return_value=(
                ReconciliationPatch.from_dict(mock_patch_response),
                1000, 500,
            ),
        ):
            engine = ReconciliationEngine(ReconcilerConfig(dry_run=False))
            result = await engine.reconcile(graph)

        assert result.success is True
        assert result.graph is not None
        assert len(result.graph.nodes) == original_count + 1  # added loader
        assert result.applied["nodes_added"] == 1
        assert result.applied["edges_added"] == 1
        assert result.applied["layers_assigned"] == 1

    @pytest.mark.asyncio
    async def test_skips_llm_when_no_issues(self):
        """Graph with no diagnostic issues should skip the LLM call."""
        graph = LineageGraph()
        # Single connected chain with no roots that are datasets
        node1 = _make_node("task1", node_type=NodeType.TASK,
                           canonical_type="job",
                           platform_domain=PlatformDomain.ORCHESTRATION)
        node2 = _make_node("table1")
        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_edge(_make_edge("task1", "table1",
                                  edge_type=EdgeType.WRITES_TO,
                                  canonical_edge_type="writes"))

        engine = ReconciliationEngine(ReconcilerConfig())
        result = await engine.reconcile(graph)

        assert result.success is True
        assert len(result.patch.add_nodes) == 0
        # No LLM call needed
        assert result.llm_input_tokens == 0

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        graph = _build_graph_with_roots()

        with patch.object(
            LLMReconciler, "reconcile",
            new_callable=AsyncMock,
            side_effect=Exception("API timeout"),
        ):
            engine = ReconciliationEngine(ReconcilerConfig())
            result = await engine.reconcile(graph)

        assert result.success is False
        assert any("API timeout" in e for e in result.validation_errors)


# ==========================================
# LLMReconciler JSON parsing tests
# ==========================================


class TestLLMReconcilerParsing:
    def test_parse_raw_json(self):
        reconciler = LLMReconciler(ReconcilerConfig())
        result = reconciler._parse_json_response('{"patch_version": "1.0"}')
        assert result["patch_version"] == "1.0"

    def test_parse_fenced_json(self):
        reconciler = LLMReconciler(ReconcilerConfig())
        text = '```json\n{"patch_version": "1.0"}\n```'
        result = reconciler._parse_json_response(text)
        assert result["patch_version"] == "1.0"

    def test_parse_embedded_json(self):
        reconciler = LLMReconciler(ReconcilerConfig())
        text = 'Here is the result: {"patch_version": "1.0"} end'
        result = reconciler._parse_json_response(text)
        assert result["patch_version"] == "1.0"

    def test_parse_invalid_returns_empty(self):
        reconciler = LLMReconciler(ReconcilerConfig())
        result = reconciler._parse_json_response("this is not json")
        assert result == {}
