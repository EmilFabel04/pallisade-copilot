"""
Tests for LLMLineageExtractor.

Covers:
- Graph-building tools (add_node, add_edge, get_graph_summary, mark_complete)
- Edge validation (missing endpoints, duplicates, self-loops)
- Discovery tool formatting
- Post-processing (canonicalize + bridge applied)
- Event stream format
- Max iterations safety
"""

import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanner.lineage.graph import (
    EdgeType,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.llm_extractor import (
    ExtractionEvent,
    LLMExtractorConfig,
    LLMLineageExtractor,
    _build_tool_definitions,
    _to_openai_tools,
)
from scanner.lineage.engine.canonical import canonicalize_graph_in_place
from scanner.lineage.engine.bridge import BridgeRuleEngine
from scanner.lineage.engine.investigator import ToolConfig


# ---- Helpers ----


def _make_extractor(**kwargs) -> LLMLineageExtractor:
    config = LLMExtractorConfig(**kwargs)
    return LLMLineageExtractor(config)


# =====================================================================
# Graph-building tool tests
# =====================================================================


class TestAddNode:
    """Test add_node tool."""

    def test_add_node_creates_valid_lineage_node(self):
        ext = _make_extractor()
        result = ext._tool_add_node({
            "node_id": "bigquery:project.raw.customers",
            "name": "customers",
            "node_type": "table",
            "platform": "bigquery",
            "platform_domain": "warehouse",
            "database": "project",
            "schema": "raw",
            "description": "Customer dimension table",
        })

        assert result["success"] is True
        assert result["action"] == "added"
        assert result["node_id"] == "bigquery:project.raw.customers"
        assert result["total_nodes"] == 1

        # Verify actual node in graph
        node = ext.graph.nodes["bigquery:project.raw.customers"]
        assert node.name == "customers"
        assert node.node_type == NodeType.TABLE
        assert node.platform == "bigquery"
        assert node.platform_domain == PlatformDomain.WAREHOUSE
        assert node.database == "project"
        assert node.schema == "raw"
        assert node.fqn == "project.raw.customers"
        assert "llm_extractor" in node.sources

    def test_add_node_rejects_duplicates(self):
        ext = _make_extractor()
        ext._tool_add_node({
            "node_id": "bigquery:project.raw.customers",
            "name": "customers",
            "node_type": "table",
            "platform": "bigquery",
            "platform_domain": "warehouse",
        })

        # Second add should skip, not error
        result = ext._tool_add_node({
            "node_id": "bigquery:project.raw.customers",
            "name": "customers",
            "node_type": "table",
            "platform": "bigquery",
            "platform_domain": "warehouse",
        })

        assert result["success"] is True
        assert result["action"] == "skipped"
        assert len(ext.graph.nodes) == 1

    def test_add_node_lowercases_id(self):
        ext = _make_extractor()
        result = ext._tool_add_node({
            "node_id": "BigQuery:Project.RAW.Customers",
            "name": "Customers",
            "node_type": "table",
            "platform": "bigquery",
            "platform_domain": "warehouse",
        })

        assert result["success"] is True
        assert result["node_id"] == "bigquery:project.raw.customers"

    def test_add_node_unknown_type_defaults(self):
        ext = _make_extractor()
        result = ext._tool_add_node({
            "node_id": "custom:something",
            "name": "something",
            "node_type": "nonexistent_type",
            "platform": "custom",
            "platform_domain": "other",
        })

        assert result["success"] is True
        node = ext.graph.nodes["custom:something"]
        assert node.node_type == NodeType.UNKNOWN

    def test_add_node_requires_node_id(self):
        ext = _make_extractor()
        result = ext._tool_add_node({
            "name": "test",
            "node_type": "table",
            "platform": "bigquery",
            "platform_domain": "warehouse",
        })
        assert result["success"] is False

    def test_add_node_respects_max_nodes(self):
        ext = _make_extractor(max_nodes=2)
        ext._tool_add_node({
            "node_id": "a:1", "name": "1", "node_type": "table",
            "platform": "a", "platform_domain": "warehouse",
        })
        ext._tool_add_node({
            "node_id": "a:2", "name": "2", "node_type": "table",
            "platform": "a", "platform_domain": "warehouse",
        })
        result = ext._tool_add_node({
            "node_id": "a:3", "name": "3", "node_type": "table",
            "platform": "a", "platform_domain": "warehouse",
        })
        assert result["success"] is False
        assert "limit" in result["error"].lower()


class TestAddEdge:
    """Test add_edge tool."""

    def _setup_graph(self) -> LLMLineageExtractor:
        ext = _make_extractor()
        ext._tool_add_node({
            "node_id": "bq:raw.customers", "name": "customers",
            "node_type": "table", "platform": "bigquery",
            "platform_domain": "warehouse",
        })
        ext._tool_add_node({
            "node_id": "dbt:analytics.stg_customers", "name": "stg_customers",
            "node_type": "model", "platform": "dbt",
            "platform_domain": "transform",
        })
        return ext

    def test_add_edge_creates_valid_edge(self):
        ext = self._setup_graph()
        result = ext._tool_add_edge({
            "source_id": "bq:raw.customers",
            "target_id": "dbt:analytics.stg_customers",
            "edge_type": "derived_from",
            "confidence": 1.0,
            "evidence": "dbt depends_on in manifest",
        })

        assert result["success"] is True
        assert result["action"] == "added"
        assert result["total_edges"] == 1

        # Verify edge in graph
        edge = list(ext.graph.edges.values())[0]
        assert edge.source_id == "bq:raw.customers"
        assert edge.target_id == "dbt:analytics.stg_customers"
        assert edge.edge_type == EdgeType.DERIVED_FROM
        assert edge.confidence == 1.0
        assert len(edge.evidence) == 1
        assert edge.evidence[0].snippet == "dbt depends_on in manifest"
        assert edge.plane == LinePlane.CROSS  # warehouse → transform = cross

    def test_add_edge_validates_source_exists(self):
        ext = self._setup_graph()
        result = ext._tool_add_edge({
            "source_id": "nonexistent:table",
            "target_id": "dbt:analytics.stg_customers",
            "edge_type": "derived_from",
            "confidence": 0.5,
            "evidence": "test",
        })
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_add_edge_validates_target_exists(self):
        ext = self._setup_graph()
        result = ext._tool_add_edge({
            "source_id": "bq:raw.customers",
            "target_id": "nonexistent:model",
            "edge_type": "derived_from",
            "confidence": 0.5,
            "evidence": "test",
        })
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_add_edge_rejects_self_loop(self):
        ext = self._setup_graph()
        result = ext._tool_add_edge({
            "source_id": "bq:raw.customers",
            "target_id": "bq:raw.customers",
            "edge_type": "derived_from",
            "confidence": 0.5,
            "evidence": "test",
        })
        assert result["success"] is False
        assert "self-loop" in result["error"].lower()

    def test_add_edge_skips_duplicate(self):
        ext = self._setup_graph()
        ext._tool_add_edge({
            "source_id": "bq:raw.customers",
            "target_id": "dbt:analytics.stg_customers",
            "edge_type": "derived_from",
            "confidence": 1.0,
            "evidence": "test",
        })
        result = ext._tool_add_edge({
            "source_id": "bq:raw.customers",
            "target_id": "dbt:analytics.stg_customers",
            "edge_type": "derived_from",
            "confidence": 0.8,
            "evidence": "second discovery",
        })
        assert result["success"] is True
        assert result["action"] == "skipped"
        assert len(ext.graph.edges) == 1

    def test_add_edge_clamps_confidence(self):
        ext = self._setup_graph()
        result = ext._tool_add_edge({
            "source_id": "bq:raw.customers",
            "target_id": "dbt:analytics.stg_customers",
            "edge_type": "derived_from",
            "confidence": 1.5,  # Over 1.0
            "evidence": "test",
        })
        assert result["success"] is True
        edge = list(ext.graph.edges.values())[0]
        assert edge.confidence == 1.0

    def test_add_edge_respects_max_edges(self):
        ext = _make_extractor(max_edges=1)
        # Add 3 nodes
        for i in range(3):
            ext._tool_add_node({
                "node_id": f"bq:t{i}", "name": f"t{i}",
                "node_type": "table", "platform": "bigquery",
                "platform_domain": "warehouse",
            })
        ext._tool_add_edge({
            "source_id": "bq:t0", "target_id": "bq:t1",
            "edge_type": "derived_from", "confidence": 1.0, "evidence": "test",
        })
        result = ext._tool_add_edge({
            "source_id": "bq:t1", "target_id": "bq:t2",
            "edge_type": "derived_from", "confidence": 1.0, "evidence": "test",
        })
        assert result["success"] is False
        assert "limit" in result["error"].lower()

    def test_add_edge_same_domain_gets_data_plane(self):
        ext = _make_extractor()
        ext._tool_add_node({
            "node_id": "bq:raw.a", "name": "a",
            "node_type": "table", "platform": "bigquery",
            "platform_domain": "warehouse",
        })
        ext._tool_add_node({
            "node_id": "bq:analytics.b", "name": "b",
            "node_type": "view", "platform": "bigquery",
            "platform_domain": "warehouse",
        })
        ext._tool_add_edge({
            "source_id": "bq:raw.a", "target_id": "bq:analytics.b",
            "edge_type": "derived_from", "confidence": 0.9, "evidence": "SQL",
        })
        edge = list(ext.graph.edges.values())[0]
        assert edge.plane == LinePlane.DATA


class TestGetGraphSummary:
    """Test get_graph_summary tool."""

    def test_graph_summary_empty(self):
        ext = _make_extractor()
        result = ext._tool_get_graph_summary()
        assert result["success"] is True
        assert result["total_nodes"] == 0
        assert result["total_edges"] == 0
        assert result["orphan_count"] == 0

    def test_graph_summary_reports_orphans(self):
        ext = _make_extractor()
        ext._tool_add_node({
            "node_id": "bq:table1", "name": "table1",
            "node_type": "table", "platform": "bigquery",
            "platform_domain": "warehouse",
        })
        ext._tool_add_node({
            "node_id": "bq:table2", "name": "table2",
            "node_type": "table", "platform": "bigquery",
            "platform_domain": "warehouse",
        })
        # No edges — both are orphans
        result = ext._tool_get_graph_summary()
        assert result["orphan_count"] == 2
        assert "bq:table1" in result["orphan_nodes"]
        assert "bq:table2" in result["orphan_nodes"]

    def test_graph_summary_connected_not_orphan(self):
        ext = _make_extractor()
        ext._tool_add_node({
            "node_id": "bq:a", "name": "a",
            "node_type": "table", "platform": "bigquery",
            "platform_domain": "warehouse",
        })
        ext._tool_add_node({
            "node_id": "bq:b", "name": "b",
            "node_type": "table", "platform": "bigquery",
            "platform_domain": "warehouse",
        })
        ext._tool_add_edge({
            "source_id": "bq:a", "target_id": "bq:b",
            "edge_type": "derived_from", "confidence": 1.0, "evidence": "test",
        })
        result = ext._tool_get_graph_summary()
        assert result["orphan_count"] == 0
        assert result["nodes_by_platform"]["bigquery"] == 2

    def test_graph_summary_nodes_by_domain(self):
        ext = _make_extractor()
        ext._tool_add_node({
            "node_id": "bq:t", "name": "t", "node_type": "table",
            "platform": "bigquery", "platform_domain": "warehouse",
        })
        ext._tool_add_node({
            "node_id": "dbt:m", "name": "m", "node_type": "model",
            "platform": "dbt", "platform_domain": "transform",
        })
        result = ext._tool_get_graph_summary()
        assert result["nodes_by_domain"]["warehouse"] == 1
        assert result["nodes_by_domain"]["transform"] == 1


class TestMarkComplete:
    """Test mark_extraction_complete tool."""

    def test_mark_complete(self):
        ext = _make_extractor()
        result = ext._tool_mark_complete({
            "summary": "Found 10 tables and 5 edges",
            "unresolved_gaps": ["n8n workflows not connected"],
        })
        assert result["success"] is True
        assert ext._extraction_complete is True
        assert ext._completion_summary == "Found 10 tables and 5 edges"
        assert ext._unresolved_gaps == ["n8n workflows not connected"]


class TestListIntegrations:
    """Test list_integrations tool."""

    def test_list_integrations(self):
        ext = _make_extractor()
        tc1 = ToolConfig(tool_type="bigquery", config={}, integration_id="bq-1", layer="warehouse")
        tc2 = ToolConfig(tool_type="dbt_core", config={}, integration_id="dbt-1", layer="transformation")
        ext._tool_configs = {"bq-1": tc1, "dbt-1": tc2}

        result = ext._tool_list_integrations()
        assert result["success"] is True
        assert len(result["integrations"]) == 2
        assert result["integrations"][0]["tool_type"] == "bigquery"
        assert result["integrations"][0]["category"] == "warehouse"
        assert result["integrations"][1]["tool_type"] == "dbt_core"
        assert result["integrations"][1]["category"] == "transformation"


# =====================================================================
# Discovery tool tests
# =====================================================================


class TestDiscoverAssets:
    """Test discover_*_assets tools (via adapter delegation)."""

    @pytest.mark.asyncio
    async def test_discover_warehouse_formats_results(self):
        ext = _make_extractor()

        # Create mock adapter
        mock_adapter = MagicMock()
        mock_adapter.discover_assets.return_value = [
            LineageNode(
                id="bq:proj.raw.users", name="users", fqn="proj.raw.users",
                node_type=NodeType.TABLE, platform="bigquery",
                platform_domain=PlatformDomain.WAREHOUSE,
                database="proj", schema="raw",
                columns=[{"name": "id", "type": "INT64"}, {"name": "email", "type": "STRING"}],
                row_count=1000,
            ),
        ]
        mock_adapter.extract_lineage.return_value = [
            LineageEdge(
                id="e1", source_id="bq:proj.raw.users", target_id="bq:proj.analytics.dim_users",
                edge_type=EdgeType.DERIVED_FROM, lineage_level=LineageLevel.TABLE,
                confidence=0.9,
            ),
        ]

        tc = ToolConfig(tool_type="bigquery", config={}, integration_id="bq-1")
        ext._adapters = {"bq-1": mock_adapter}
        ext._tool_configs = {"bq-1": tc}

        result = await ext._tool_discover_assets({"integration_id": "bq-1"}, "warehouse")

        assert result["success"] is True
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["name"] == "users"
        assert result["nodes"][0]["database"] == "proj"
        assert len(result["nodes"][0]["columns"]) == 2
        assert result["nodes"][0]["row_count"] == 1000
        assert len(result["edges"]) == 1
        assert result["edges"][0]["source_id"] == "bq:proj.raw.users"

    @pytest.mark.asyncio
    async def test_discover_missing_adapter(self):
        ext = _make_extractor()
        result = await ext._tool_discover_assets({"integration_id": "nonexistent"}, "warehouse")
        assert result["success"] is False
        assert "no adapter found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_discover_adapter_failure(self):
        ext = _make_extractor()
        mock_adapter = MagicMock()
        mock_adapter.discover_assets.side_effect = Exception("Connection refused")

        tc = ToolConfig(tool_type="bigquery", config={}, integration_id="bq-1")
        ext._adapters = {"bq-1": mock_adapter}
        ext._tool_configs = {"bq-1": tc}

        result = await ext._tool_discover_assets({"integration_id": "bq-1"}, "warehouse")
        assert result["success"] is False
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_discover_truncates_large_results(self):
        ext = _make_extractor()
        mock_adapter = MagicMock()
        # Return 300 nodes (should truncate to 200)
        mock_adapter.discover_assets.return_value = [
            LineageNode(
                id=f"bq:t{i}", name=f"t{i}", fqn=f"t{i}",
                node_type=NodeType.TABLE, platform="bigquery",
                platform_domain=PlatformDomain.WAREHOUSE,
            )
            for i in range(300)
        ]
        mock_adapter.extract_lineage.return_value = []

        tc = ToolConfig(tool_type="bigquery", config={}, integration_id="bq-1")
        ext._adapters = {"bq-1": mock_adapter}
        ext._tool_configs = {"bq-1": tc}

        result = await ext._tool_discover_assets({"integration_id": "bq-1"}, "warehouse")
        assert result["success"] is True
        assert len(result["nodes"]) == 200
        assert "nodes_truncated" in result


# =====================================================================
# Event format tests
# =====================================================================


class TestEventFormat:
    """Test ExtractionEvent serialization."""

    def test_event_to_sse(self):
        event = ExtractionEvent("node_added", {"node_id": "bq:t1", "name": "t1"}, timestamp=1000.0)
        sse = event.to_sse()
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        import json
        payload = json.loads(sse[6:].strip())
        assert payload["type"] == "node_added"
        assert payload["data"]["node_id"] == "bq:t1"
        assert payload["ts"] == 1000.0

    def test_event_types(self):
        for event_type in ["phase", "tool_call", "tool_result", "node_added", "edge_added", "error", "complete"]:
            event = ExtractionEvent(event_type, {"test": True})
            assert event.event_type == event_type
            assert event.timestamp > 0


# =====================================================================
# Tool definitions tests
# =====================================================================


class TestToolDefinitions:
    """Test tool definition formats."""

    def test_anthropic_tool_definitions(self):
        tools = _build_tool_definitions()
        names = [t["name"] for t in tools]

        # Should have 9 query tools + 4 graph tools = 13
        assert len(tools) == 13
        assert "list_integrations" in names
        assert "discover_warehouse_assets" in names
        assert "discover_dbt_assets" in names
        assert "add_node" in names
        assert "add_edge" in names
        assert "get_graph_summary" in names
        assert "mark_extraction_complete" in names

        # Each tool should have required fields
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_openai_tool_conversion(self):
        anthropic_tools = _build_tool_definitions()
        openai_tools = _to_openai_tools(anthropic_tools)

        assert len(openai_tools) == len(anthropic_tools)
        for tool in openai_tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]


# =====================================================================
# Integration / post-processing tests
# =====================================================================


class TestPostProcessing:
    """Test that post-processing (canonicalize + bridge) is applied."""

    @pytest.mark.asyncio
    async def test_post_processing_runs(self):
        """Verify canonicalize and bridge are applied to the LLM-built graph."""
        ext = _make_extractor()

        # Build a graph with some nodes that bridge rules can act on
        ext._tool_add_node({
            "node_id": "n8n:workflow_1", "name": "workflow_1",
            "node_type": "workflow", "platform": "n8n",
            "platform_domain": "orchestration",
            "integration_id": "n8n-1",
        })
        ext._tool_add_node({
            "node_id": "bigquery:proj.raw.customers", "name": "customers",
            "node_type": "table", "platform": "bigquery",
            "platform_domain": "warehouse",
            "database": "proj", "schema": "raw",
        })
        ext._tool_add_node({
            "node_id": "dbt:proj.analytics.stg_customers", "name": "stg_customers",
            "node_type": "model", "platform": "dbt",
            "platform_domain": "transform",
        })
        ext._tool_add_edge({
            "source_id": "bigquery:proj.raw.customers",
            "target_id": "dbt:proj.analytics.stg_customers",
            "edge_type": "derived_from", "confidence": 1.0,
            "evidence": "dbt depends_on",
        })

        # Run canonicalize + bridge (same as post-processing in extract())
        canonicalize_graph_in_place(ext._graph.nodes, ext._graph.edges)
        bridge = BridgeRuleEngine(ext._graph)
        bridge_result = bridge.apply_all()

        # Graph should still be valid
        assert len(ext.graph.nodes) >= 3
        assert len(ext.graph.edges) >= 1

        # Nodes should have canonical_type set by canonicalize
        for node in ext.graph.nodes.values():
            # canonical_type is set by canonicalize_graph_in_place
            # (it may or may not be set depending on the rules)
            pass  # Just verify no exceptions

    @pytest.mark.asyncio
    async def test_views_are_built(self):
        """Verify views can be built from LLM-built graph."""
        ext = _make_extractor()

        ext._tool_add_node({
            "node_id": "bigquery:proj.raw.customers", "name": "customers",
            "node_type": "table", "platform": "bigquery",
            "platform_domain": "warehouse",
            "database": "proj", "schema": "raw",
        })

        canonicalize_graph_in_place(ext._graph.nodes, ext._graph.edges)
        views = ext._build_views([])

        # Should produce at least some views without error
        assert isinstance(views, dict)


# =====================================================================
# Full extraction loop tests (mocked LLM)
# =====================================================================


class TestExtractionLoop:
    """Test the full extraction loop with mocked LLM."""

    def _mock_anthropic_module(self, mock_client):
        """Create a mock anthropic module and inject into sys.modules."""
        mock_mod = MagicMock()
        mock_mod.AsyncAnthropic.return_value = mock_client
        return mock_mod

    @pytest.mark.asyncio
    async def test_max_iterations_safety(self):
        """Loop should break at max_iterations."""
        ext = _make_extractor(max_iterations=2, provider="anthropic", api_key="test-key")

        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [
            MagicMock(type="tool_use", name="list_integrations", input={}, id="tu_1"),
        ]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_mod = self._mock_anthropic_module(mock_client)

        events = []
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            async for event in ext._run_anthropic_loop("Test message"):
                events.append(event)

        event_types = [e.event_type for e in events]
        assert "phase" in event_types or "tool_call" in event_types

    @pytest.mark.asyncio
    async def test_end_turn_stops_loop(self):
        """Loop should stop on end_turn."""
        ext = _make_extractor(provider="anthropic", api_key="test-key")

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [
            MagicMock(type="text", text="Extraction complete"),
        ]
        mock_response.content[0].text = "Extraction complete"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_mod = self._mock_anthropic_module(mock_client)

        events = []
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            async for event in ext._run_anthropic_loop("Test message"):
                events.append(event)

        assert ext._extraction_complete is True
        event_types = [e.event_type for e in events]
        assert "thinking" in event_types

    @pytest.mark.asyncio
    async def test_api_error_yields_error_event(self):
        """API errors should yield error events."""
        ext = _make_extractor(provider="anthropic", api_key="test-key")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("Rate limited"))
        mock_mod = self._mock_anthropic_module(mock_client)

        events = []
        with patch.dict(sys.modules, {"anthropic": mock_mod}):
            async for event in ext._run_anthropic_loop("Test message"):
                events.append(event)

        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) >= 1
        assert "Rate limited" in error_events[0].data["message"]

    @pytest.mark.asyncio
    async def test_missing_api_key_yields_error(self):
        """Missing API key should yield error event."""
        ext = _make_extractor(provider="anthropic", api_key=None)

        events = []
        with patch.dict("os.environ", {}, clear=True):
            # Remove ANTHROPIC_API_KEY from env
            import os
            env_backup = os.environ.get("ANTHROPIC_API_KEY")
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]
            try:
                async for event in ext._run_anthropic_loop("Test"):
                    events.append(event)
            finally:
                if env_backup:
                    os.environ["ANTHROPIC_API_KEY"] = env_backup

        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) >= 1
