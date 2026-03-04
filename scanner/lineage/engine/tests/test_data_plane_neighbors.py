"""
Tests for compute_neighbors_from_view() — the data-plane adjacency lookup
that ensures the detail panel matches the Data Plane graph topology.

Covers:
- Basic upstream/downstream BFS
- Fan-in / fan-out (node with multiple upstreams and downstreams)
- Cycle avoidance
- Depth limiting
- Limit parameter
- Missing node graceful handling
- Response structure validation
- Bypass edge regression: dataset→job→dataset collapsed to dataset→dataset
"""

import pytest

from scanner.lineage.engine.views import compute_neighbors_from_view


# ---------------------------------------------------------------------------
# Helpers — build minimal view dicts
# ---------------------------------------------------------------------------

def _vn(node_id: str, name: str = "", **extra) -> dict:
    """Create a minimal ViewNode dict."""
    return {
        "id": node_id,
        "name": name or node_id,
        "canonicalType": extra.get("canonicalType", "dataset"),
        "originalType": extra.get("originalType", "table"),
        "platform": extra.get("platform", "bigquery"),
        "platformDomain": extra.get("platformDomain", "warehouse"),
        "layer": extra.get("layer", "WAREHOUSE"),
        "clusterId": None,
        "x": 0,
        "y": 0,
        "inferred": extra.get("inferred", False),
        "needsMapping": False,
        "metadata": extra.get("metadata", {}),
    }


def _ve(source_id: str, target_id: str, **extra) -> dict:
    """Create a minimal ViewEdge dict."""
    return {
        "id": extra.get("id", f"edge:{source_id}->{target_id}"),
        "sourceId": source_id,
        "targetId": target_id,
        "canonicalType": extra.get("canonicalType", "derives"),
        "originalType": extra.get("originalType", "derived_from"),
        "confidence": extra.get("confidence", 0.9),
        "inferred": extra.get("inferred", False),
        "evidenceCount": extra.get("evidenceCount", 1),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasicUpstreamDownstream:
    """Chain: A → B → C"""

    @pytest.fixture
    def chain_view(self):
        return {
            "nodes": [_vn("A"), _vn("B"), _vn("C")],
            "edges": [_ve("A", "B"), _ve("B", "C")],
        }

    def test_upstream_of_c(self, chain_view):
        result = compute_neighbors_from_view(chain_view, "C", "upstream", depth=3)
        assert result["totalCount"] == 2
        assert result["nodeId"] == "C"
        assert result["direction"] == "upstream"
        assert result["source"] == "data_plane"
        # Hop 1: B, Hop 2: A
        assert len(result["neighbors"]) == 2
        hop1 = result["neighbors"][0]
        assert hop1["hop"] == 1
        assert len(hop1["items"]) == 1
        assert hop1["items"][0]["node"]["id"] == "B"
        hop2 = result["neighbors"][1]
        assert hop2["hop"] == 2
        assert len(hop2["items"]) == 1
        assert hop2["items"][0]["node"]["id"] == "A"

    def test_downstream_of_a(self, chain_view):
        result = compute_neighbors_from_view(chain_view, "A", "downstream", depth=3)
        assert result["totalCount"] == 2
        hop1 = result["neighbors"][0]
        assert hop1["items"][0]["node"]["id"] == "B"
        hop2 = result["neighbors"][1]
        assert hop2["items"][0]["node"]["id"] == "C"

    def test_upstream_of_a_is_empty(self, chain_view):
        result = compute_neighbors_from_view(chain_view, "A", "upstream", depth=3)
        assert result["totalCount"] == 0
        assert result["neighbors"] == []

    def test_downstream_of_c_is_empty(self, chain_view):
        result = compute_neighbors_from_view(chain_view, "C", "downstream", depth=3)
        assert result["totalCount"] == 0
        assert result["neighbors"] == []


class TestFanInFanOut:
    """
    Fan-in:  X, Y, Z → M
    Fan-out: M → P, Q
    """

    @pytest.fixture
    def fan_view(self):
        return {
            "nodes": [_vn("X"), _vn("Y"), _vn("Z"), _vn("M"), _vn("P"), _vn("Q")],
            "edges": [
                _ve("X", "M"), _ve("Y", "M"), _ve("Z", "M"),
                _ve("M", "P"), _ve("M", "Q"),
            ],
        }

    def test_upstream_of_m(self, fan_view):
        result = compute_neighbors_from_view(fan_view, "M", "upstream", depth=1)
        assert result["totalCount"] == 3
        hop1_ids = {item["node"]["id"] for item in result["neighbors"][0]["items"]}
        assert hop1_ids == {"X", "Y", "Z"}

    def test_downstream_of_m(self, fan_view):
        result = compute_neighbors_from_view(fan_view, "M", "downstream", depth=1)
        assert result["totalCount"] == 2
        hop1_ids = {item["node"]["id"] for item in result["neighbors"][0]["items"]}
        assert hop1_ids == {"P", "Q"}


class TestCycleAvoidance:
    """A → B → C → A: BFS must terminate."""

    @pytest.fixture
    def cycle_view(self):
        return {
            "nodes": [_vn("A"), _vn("B"), _vn("C")],
            "edges": [_ve("A", "B"), _ve("B", "C"), _ve("C", "A")],
        }

    def test_upstream_terminates(self, cycle_view):
        result = compute_neighbors_from_view(cycle_view, "A", "upstream", depth=5)
        # Should find C at hop 1 (C→A), B at hop 2 (B→C)
        assert result["totalCount"] == 2
        all_ids = set()
        for hop in result["neighbors"]:
            for item in hop["items"]:
                all_ids.add(item["node"]["id"])
        assert all_ids == {"B", "C"}

    def test_downstream_terminates(self, cycle_view):
        result = compute_neighbors_from_view(cycle_view, "A", "downstream", depth=5)
        assert result["totalCount"] == 2


class TestDepthLimiting:
    """A → B → C → D: depth=1 from D should only show C."""

    @pytest.fixture
    def long_chain_view(self):
        return {
            "nodes": [_vn("A"), _vn("B"), _vn("C"), _vn("D")],
            "edges": [_ve("A", "B"), _ve("B", "C"), _ve("C", "D")],
        }

    def test_depth_1(self, long_chain_view):
        result = compute_neighbors_from_view(long_chain_view, "D", "upstream", depth=1)
        assert result["totalCount"] == 1
        assert result["neighbors"][0]["items"][0]["node"]["id"] == "C"

    def test_depth_2(self, long_chain_view):
        result = compute_neighbors_from_view(long_chain_view, "D", "upstream", depth=2)
        assert result["totalCount"] == 2
        hop1_ids = {i["node"]["id"] for i in result["neighbors"][0]["items"]}
        hop2_ids = {i["node"]["id"] for i in result["neighbors"][1]["items"]}
        assert hop1_ids == {"C"}
        assert hop2_ids == {"B"}

    def test_depth_3_gets_all(self, long_chain_view):
        result = compute_neighbors_from_view(long_chain_view, "D", "upstream", depth=3)
        assert result["totalCount"] == 3


class TestLimitParameter:
    """Fan-out node with many downstream: limit should truncate."""

    @pytest.fixture
    def fan_out_view(self):
        nodes = [_vn("root")] + [_vn(f"child_{i}") for i in range(20)]
        edges = [_ve("root", f"child_{i}") for i in range(20)]
        return {"nodes": nodes, "edges": edges}

    def test_limit_5(self, fan_out_view):
        result = compute_neighbors_from_view(fan_out_view, "root", "downstream", depth=1, limit=5)
        assert result["totalCount"] == 5
        assert len(result["neighbors"][0]["items"]) == 5

    def test_limit_larger_than_count(self, fan_out_view):
        result = compute_neighbors_from_view(fan_out_view, "root", "downstream", depth=1, limit=100)
        assert result["totalCount"] == 20


class TestMissingNode:
    """Unknown node_id returns empty neighbors."""

    def test_missing_node(self):
        view_dict = {
            "nodes": [_vn("A")],
            "edges": [],
        }
        result = compute_neighbors_from_view(view_dict, "nonexistent", "upstream")
        assert result["totalCount"] == 0
        assert result["neighbors"] == []
        assert result["source"] == "data_plane"

    def test_empty_view(self):
        result = compute_neighbors_from_view({"nodes": [], "edges": []}, "X", "upstream")
        assert result["totalCount"] == 0


class TestResponseStructure:
    """Verify all expected fields are present in the response."""

    def test_structure(self):
        view_dict = {
            "nodes": [_vn("A"), _vn("B")],
            "edges": [_ve("A", "B", confidence=0.75, inferred=True)],
        }
        result = compute_neighbors_from_view(view_dict, "B", "upstream", depth=2, limit=10)
        assert "nodeId" in result
        assert "direction" in result
        assert "depth" in result
        assert "neighbors" in result
        assert "totalCount" in result
        assert "source" in result
        assert result["nodeId"] == "B"
        assert result["direction"] == "upstream"
        assert result["depth"] == 2

        # Check hop structure
        hop = result["neighbors"][0]
        assert "hop" in hop
        assert "items" in hop
        item = hop["items"][0]
        assert "node" in item
        assert "edge" in item
        # Edge carries confidence and inferred
        assert item["edge"]["confidence"] == 0.75
        assert item["edge"]["inferred"] is True


class TestBypassEdgeRegression:
    """
    Regression: dataset→job→dataset bypass edge.

    The raw engine graph has:  src_table → dbt_job → mart_table
    The data_plane view collapses this to: src_table → mart_table (bypass edge)

    The neighbors endpoint must show mart_table's upstream as src_table
    (not the job node, which is excluded from the data_plane view).
    """

    @pytest.fixture
    def bypass_view(self):
        """
        Simulates the output of build_data_plane() after bypass edge creation.
        The job node is NOT in the view — only the dataset nodes remain.
        """
        return {
            "nodes": [
                _vn("src_table", "raw.salesforce.accounts"),
                _vn("mart_table", "analytics.marts.fct_revenue"),
                _vn("dashboard", "Revenue Dashboard",
                     canonicalType="semantic", originalType="dashboard",
                     platform="looker", platformDomain="bi"),
            ],
            "edges": [
                _ve("src_table", "mart_table",
                     originalType="job_bypass", confidence=0.8, inferred=True),
                _ve("mart_table", "dashboard",
                     canonicalType="serves", confidence=0.9),
            ],
        }

    def test_upstream_of_mart_shows_src(self, bypass_view):
        """mart_table's upstream should be src_table, not a job node."""
        result = compute_neighbors_from_view(bypass_view, "mart_table", "upstream", depth=1)
        assert result["totalCount"] == 1
        item = result["neighbors"][0]["items"][0]
        assert item["node"]["id"] == "src_table"
        assert item["edge"]["inferred"] is True
        assert item["edge"]["confidence"] == 0.8

    def test_downstream_of_mart_shows_dashboard(self, bypass_view):
        result = compute_neighbors_from_view(bypass_view, "mart_table", "downstream", depth=1)
        assert result["totalCount"] == 1
        assert result["neighbors"][0]["items"][0]["node"]["id"] == "dashboard"

    def test_full_upstream_chain_of_dashboard(self, bypass_view):
        """Dashboard's full upstream: mart_table at hop 1, src_table at hop 2."""
        result = compute_neighbors_from_view(bypass_view, "dashboard", "upstream", depth=3)
        assert result["totalCount"] == 2
        hop1_ids = {i["node"]["id"] for i in result["neighbors"][0]["items"]}
        hop2_ids = {i["node"]["id"] for i in result["neighbors"][1]["items"]}
        assert hop1_ids == {"mart_table"}
        assert hop2_ids == {"src_table"}


class TestBypassEdgeWithRealViewBuilder:
    """
    Integration test: build a real LineageGraph with dataset→job→dataset,
    run ViewBuilder.build_data_plane(), then verify compute_neighbors_from_view
    on the resulting view dict returns the correct bypass neighbors.
    """

    def test_bypass_via_view_builder(self):
        from scanner.lineage.graph import (
            EdgeType, Evidence, LineageEdge, LineageGraph,
            LineageNode, NodeType, PlatformDomain,
        )
        from scanner.lineage.engine.canonical import canonicalize_graph_in_place
        from scanner.lineage.engine.views import ViewBuilder

        graph = LineageGraph()

        # Source table
        src = LineageNode(
            id="node:bq:raw_accounts",
            name="raw_accounts",
            fqn="raw.salesforce.raw_accounts",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            database="raw",
            schema="salesforce",
        )
        # Job node (should be bypassed in data_plane)
        # NodeType.TASK canonicalizes to "job" which triggers bypass edge creation
        job = LineageNode(
            id="node:dbt:transform_job",
            name="transform_job",
            fqn="transform_job",
            node_type=NodeType.TASK,
            platform="dbt",
            platform_domain=PlatformDomain.TRANSFORM,
        )
        # Mart table
        mart = LineageNode(
            id="node:bq:fct_revenue",
            name="fct_revenue",
            fqn="analytics.marts.fct_revenue",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            database="analytics",
            schema="marts",
        )

        graph.add_node(src)
        graph.add_node(job)
        graph.add_node(mart)

        graph.add_edge(LineageEdge(
            id="edge:src->job",
            source_id=src.id,
            target_id=job.id,
            edge_type=EdgeType.READS_FROM,
            confidence=0.9,
            evidence=[Evidence(adapter_id="test", source_ref="fixture")],
        ))
        graph.add_edge(LineageEdge(
            id="edge:job->mart",
            source_id=job.id,
            target_id=mart.id,
            edge_type=EdgeType.POPULATES,
            confidence=0.85,
            evidence=[Evidence(adapter_id="test", source_ref="fixture")],
        ))

        canonicalize_graph_in_place(graph.nodes, graph.edges)
        builder = ViewBuilder(graph, tool_nodes=set())
        view = builder.build_data_plane()
        view_dict = view.to_dict()

        # The job node should be excluded from the data_plane view
        view_node_ids = {n["id"] for n in view_dict["nodes"]}
        assert job.id not in view_node_ids, "Job node should not be in data_plane view"
        assert src.id in view_node_ids
        assert mart.id in view_node_ids

        # Neighbors of mart should show src via bypass edge
        result = compute_neighbors_from_view(view_dict, mart.id, "upstream", depth=3)
        assert result["totalCount"] >= 1
        upstream_ids = set()
        for hop in result["neighbors"]:
            for item in hop["items"]:
                upstream_ids.add(item["node"]["id"])
        assert src.id in upstream_ids, (
            f"Expected {src.id} in upstream of {mart.id}, got {upstream_ids}"
        )
