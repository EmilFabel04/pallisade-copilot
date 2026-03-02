"""
Tests for RunRegistry and ExtractionPipeline.

Covers:
- RunRegistry lifecycle (start, complete, fail, eviction)
- Atomic publish semantics (current_run_id only on success)
- Pipeline step ordering (bridge-added nodes appear in views)
- Pre-computed views in artifacts
- Store backward compatibility
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
from scanner.lineage.engine.run_registry import (
    RunArtifacts,
    RunRecord,
    RunRegistry,
    RunStatus,
)


# ---- Helpers ----


def _make_node(
    name: str,
    node_type: NodeType,
    platform: str,
    platform_domain: PlatformDomain,
    database: str = None,
    schema: str = None,
    fqn: str = None,
    integration_id: str = None,
) -> LineageNode:
    return LineageNode(
        id=f"node:{platform}:{name}",
        name=name,
        fqn=fqn or f"{database or ''}.{schema or ''}.{name}".strip("."),
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        database=database,
        schema=schema,
        integration_id=integration_id,
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


def _build_test_graph() -> LineageGraph:
    """Build a small graph with n8n service + raw tables + dbt models."""
    graph = LineageGraph()

    # n8n service node
    n8n = _make_node(
        "n8n",
        NodeType.WORKFLOW,
        "n8n",
        PlatformDomain.INGESTION,
        integration_id="n8n-1",
    )
    n8n.canonical_type = "service"
    graph.add_node(n8n)

    # Raw tables (orphaned — no upstream writer)
    for name in ["customers", "orders", "events"]:
        node = _make_node(
            name, NodeType.TABLE, "bigquery", PlatformDomain.WAREHOUSE,
            database="project", schema="raw",
        )
        graph.add_node(node)

    # dbt staging model
    stg = _make_node(
        "stg_customers", NodeType.MODEL, "dbt", PlatformDomain.TRANSFORM,
        fqn="project.analytics.stg_customers",
    )
    graph.add_node(stg)

    # dbt model depends on raw table
    graph.add_edge(_make_edge(
        "node:bigquery:customers", "node:dbt:stg_customers",
    ))

    return graph


# =====================================================================
# RunRegistry Tests
# =====================================================================


class TestRunRegistryLifecycle:
    """Test run lifecycle: start → complete → current_run_id updates."""

    def test_start_run(self):
        registry = RunRegistry()
        run_id = registry.start_run(["bigquery", "n8n"])
        assert run_id is not None
        assert len(run_id) == 12
        record = registry.get_run(run_id)
        assert record is not None
        assert record.status == RunStatus.RUNNING
        assert record.tool_configs_summary == ["bigquery", "n8n"]
        # Not yet published
        assert registry.current_run_id is None

    def test_complete_run_publishes(self):
        registry = RunRegistry()
        run_id = registry.start_run(["bigquery"])
        artifacts = RunArtifacts(stats={"total_nodes": 10})
        registry.complete_run(run_id, artifacts)

        record = registry.get_run(run_id)
        assert record.status == RunStatus.COMPLETED
        assert record.artifacts.stats["total_nodes"] == 10
        assert record.duration_ms > 0 or record.duration_ms == 0  # could be instant
        # Atomically published
        assert registry.current_run_id == run_id
        assert registry.current_run is record

    def test_complete_run_updates_current(self):
        registry = RunRegistry()
        run1 = registry.start_run(["bigquery"])
        registry.complete_run(run1, RunArtifacts())
        assert registry.current_run_id == run1

        run2 = registry.start_run(["n8n"])
        registry.complete_run(run2, RunArtifacts())
        assert registry.current_run_id == run2


class TestRunRegistryFailure:
    """Test that failed runs do NOT update current_run_id."""

    def test_failed_run_preserves_current(self):
        registry = RunRegistry()
        # First run succeeds
        run1 = registry.start_run(["bigquery"])
        registry.complete_run(run1, RunArtifacts())
        assert registry.current_run_id == run1

        # Second run fails
        run2 = registry.start_run(["n8n"])
        registry.fail_run(run2, ["Connection refused"])

        # Current still points to first
        assert registry.current_run_id == run1
        record2 = registry.get_run(run2)
        assert record2.status == RunStatus.FAILED
        assert record2.errors == ["Connection refused"]

    def test_failed_run_with_no_previous(self):
        registry = RunRegistry()
        run = registry.start_run(["bigquery"])
        registry.fail_run(run, ["Error"])
        assert registry.current_run_id is None


class TestRunRegistryPolling:
    """Test lightweight status for polling."""

    def test_get_run_status(self):
        registry = RunRegistry()
        run_id = registry.start_run(["bigquery"])
        status = registry.get_run_status(run_id)
        assert status is not None
        assert status["run_id"] == run_id
        assert status["status"] == "running"
        assert status["is_current"] is False

        registry.complete_run(run_id, RunArtifacts())
        status = registry.get_run_status(run_id)
        assert status["status"] == "completed"
        assert status["is_current"] is True

    def test_get_run_status_unknown(self):
        registry = RunRegistry()
        assert registry.get_run_status("nonexistent") is None


class TestRunRegistryEviction:
    """Test old run eviction."""

    def test_evict_old_runs(self):
        registry = RunRegistry(max_history=3)
        runs = []
        for i in range(5):
            run_id = registry.start_run([f"tool_{i}"])
            registry.complete_run(run_id, RunArtifacts())
            runs.append(run_id)

        # Should keep at most 3 runs
        assert len(registry._runs) <= 3
        # Current run must survive
        assert registry.current_run_id == runs[-1]
        assert registry.get_run(runs[-1]) is not None

    def test_current_run_never_evicted(self):
        registry = RunRegistry(max_history=2)
        run1 = registry.start_run(["a"])
        registry.complete_run(run1, RunArtifacts())

        # Create many more
        for i in range(5):
            r = registry.start_run([f"tool_{i}"])
            registry.fail_run(r, ["err"])

        # run1 is current — must survive
        assert registry.get_run(run1) is not None


class TestRunRegistryList:
    """Test listing runs."""

    def test_list_runs(self):
        registry = RunRegistry()
        run1 = registry.start_run(["bigquery"])
        registry.complete_run(run1, RunArtifacts())
        run2 = registry.start_run(["n8n"])
        registry.complete_run(run2, RunArtifacts())

        runs = registry.list_runs(limit=5)
        assert len(runs) == 2
        assert runs[0]["run_id"] == run2  # most recent first
        assert runs[1]["run_id"] == run1


class TestRunRecordSerialization:
    """Test RunRecord.to_dict()."""

    def test_to_dict(self):
        registry = RunRegistry()
        run_id = registry.start_run(["bigquery", "dbt"])
        views = {"data_plane": {"viewType": "data_plane", "nodes": []}}
        registry.complete_run(run_id, RunArtifacts(
            views=views,
            stats={"total_nodes": 42},
        ))
        d = registry.get_run(run_id).to_dict()
        assert d["run_id"] == run_id
        assert d["status"] == "completed"
        assert d["has_views"] is True
        assert d["tool_configs"] == ["bigquery", "dbt"]
        assert d["stats"]["total_nodes"] == 42


# =====================================================================
# Pipeline Tests (using mocked investigator)
# =====================================================================


class TestPipelineStepOrdering:
    """Verify bridge-added nodes appear in pre-computed views."""

    @pytest.mark.asyncio
    async def test_bridge_nodes_in_views(self):
        """Bridge-added nodes should appear in lane_pipeline_overview views."""
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        graph = _build_test_graph()
        mock_result = InvestigationResult(
            success=True,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=graph,
            stats={"total_nodes": len(graph.nodes)},
            errors=[],
            duration_ms=100,
        )

        registry = RunRegistry()
        store = MagicMock()
        config = ExtractionPipelineConfig()

        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            run_id = await run_extraction_pipeline(
                [], registry, store, config,
            )

        record = registry.get_run(run_id)
        assert record is not None
        assert record.status == RunStatus.COMPLETED
        assert registry.current_run_id == run_id

        # Views should be pre-computed
        assert "lane_pipeline_overview" in record.artifacts.views
        assert "data_plane" in record.artifacts.views
        assert "pipeline_overview" in record.artifacts.views

        # The lane view should contain tool-level nodes (including n8n from bridge)
        lane_view = record.artifacts.views["lane_pipeline_overview"]
        n8n_tools = [
            n for n in lane_view["nodes"] if n.get("platform") == "n8n"
        ]
        # n8n should appear as a tool in the overview (bridge adds inferred loader)
        assert len(n8n_tools) >= 1, (
            f"Expected n8n tool in lane view, got platforms: "
            f"{[n.get('platform') for n in lane_view['nodes']]}"
        )

    @pytest.mark.asyncio
    async def test_store_updated_for_backward_compat(self):
        """Pipeline should update store.graph for existing query endpoints."""
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        graph = _build_test_graph()
        mock_result = InvestigationResult(
            success=True,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=graph,
            stats={},
            errors=[],
            duration_ms=50,
        )

        registry = RunRegistry()
        store = MagicMock()
        config = ExtractionPipelineConfig()

        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            await run_extraction_pipeline([], registry, store, config)

        # store.graph should be set
        assert store.graph is not None
        assert store.graph == graph


class TestPipelineWithoutLLM:
    """Pipeline works cleanly when LLM reconciler is disabled."""

    @pytest.mark.asyncio
    async def test_no_llm_reconciler(self):
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        graph = _build_test_graph()
        mock_result = InvestigationResult(
            success=True,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=graph,
            stats={},
            errors=[],
            duration_ms=50,
        )

        registry = RunRegistry()
        store = MagicMock()
        config = ExtractionPipelineConfig(
            use_llm_reconciler=False,
            use_llm_planner=False,
        )

        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            run_id = await run_extraction_pipeline(
                [], registry, store, config,
            )

        record = registry.get_run(run_id)
        assert record.status == RunStatus.COMPLETED
        # Reconciliation should be None
        assert record.artifacts.reconciliation is None
        # Views should still be built
        assert len(record.artifacts.views) == 3


class TestPipelineErrorHandling:
    """Pipeline failure should mark run as failed."""

    @pytest.mark.asyncio
    async def test_investigation_failure(self):
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        # No graph produced
        mock_result = InvestigationResult(
            success=False,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=None,
            stats={},
            errors=["BigQuery connection failed"],
            duration_ms=100,
        )

        registry = RunRegistry()
        store = MagicMock()
        config = ExtractionPipelineConfig()

        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            run_id = await run_extraction_pipeline(
                [], registry, store, config,
            )

        record = registry.get_run(run_id)
        assert record.status == RunStatus.FAILED
        assert "BigQuery connection failed" in record.errors
        # current_run_id should NOT be set
        assert registry.current_run_id is None

    @pytest.mark.asyncio
    async def test_failure_preserves_previous_run(self):
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        graph = _build_test_graph()

        registry = RunRegistry()
        store = MagicMock()
        config = ExtractionPipelineConfig()

        # First run succeeds
        good_result = InvestigationResult(
            success=True,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=graph,
            stats={},
            errors=[],
            duration_ms=50,
        )
        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=good_result,
        ):
            run1 = await run_extraction_pipeline(
                [], registry, store, config,
            )
        assert registry.current_run_id == run1

        # Second run fails
        bad_result = InvestigationResult(
            success=False,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=None,
            stats={},
            errors=["Connection timeout"],
            duration_ms=50,
        )
        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=bad_result,
        ):
            run2 = await run_extraction_pipeline(
                [], registry, store, config,
            )

        # Current run should still be the first (successful) one
        assert registry.current_run_id == run1
        assert registry.get_run(run2).status == RunStatus.FAILED


class TestPipelineRunId:
    """Verify run_id propagation through stats."""

    @pytest.mark.asyncio
    async def test_run_id_in_stats(self):
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        graph = _build_test_graph()
        mock_result = InvestigationResult(
            success=True,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=graph,
            stats={},
            errors=[],
            duration_ms=50,
        )

        registry = RunRegistry()
        store = MagicMock()

        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            run_id = await run_extraction_pipeline(
                [], registry, store, ExtractionPipelineConfig(),
            )

        record = registry.get_run(run_id)
        assert record.artifacts.stats["run_id"] == run_id
        assert "views_built" in record.artifacts.stats


# =====================================================================
# Cross-Tool Synthesis Tests
# =====================================================================


class TestPipelineCrossToolSynthesis:
    """Cross-tool synthesis creates edges between ingestion and warehouse nodes."""

    @pytest.mark.asyncio
    async def test_fivetran_to_bigquery_edges_synthesized(self):
        """Fivetran connector should get POPULATES edges to matching BQ tables."""
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        graph = LineageGraph()

        # Fivetran source service node
        ft_source = _make_node(
            "Postgres", NodeType.SOURCE, "fivetran", PlatformDomain.INGESTION,
        )
        ft_source.raw_metadata = {
            "source_service": "postgres",
            "node_role": "external_source",
        }
        graph.add_node(ft_source)

        # Fivetran connector with synced_tables metadata
        ft_connector = _make_node(
            "my_connector", NodeType.SOURCE, "fivetran", PlatformDomain.INGESTION,
        )
        ft_connector.raw_metadata = {
            "service": "postgres",
            "schema": "raw",
            "connector_name": "my_connector",
            "synced_tables": ["customers", "orders"],
        }
        graph.add_node(ft_connector)

        # Source -> connector edge
        graph.add_edge(_make_edge(ft_source.id, ft_connector.id, EdgeType.DERIVED_FROM))

        # BigQuery raw tables (matching synced_tables names)
        for name in ["customers", "orders"]:
            node = _make_node(
                name, NodeType.TABLE, "bigquery", PlatformDomain.WAREHOUSE,
                database="my-project", schema="raw",
            )
            graph.add_node(node)

        mock_result = InvestigationResult(
            success=True,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=graph,
            stats={},
            errors=[],
            duration_ms=50,
        )

        registry = RunRegistry()
        store = MagicMock()
        config = ExtractionPipelineConfig()

        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            run_id = await run_extraction_pipeline([], registry, store, config)

        record = registry.get_run(run_id)
        assert record.status == RunStatus.COMPLETED

        # Check that POPULATES edges were created by cross-tool synthesis
        final_graph = store.graph
        populates_edges = [
            e for e in final_graph.edges.values()
            if e.edge_type == EdgeType.POPULATES
        ]
        assert len(populates_edges) >= 2, (
            f"Expected at least 2 POPULATES edges (connector→customers, connector→orders), "
            f"got {len(populates_edges)}"
        )

        # Verify synthesis stats in artifacts
        stats = record.artifacts.stats
        assert "cross_tool_synthesis" in stats
        assert stats["cross_tool_synthesis"]["ingestion_edges"] >= 2

    @pytest.mark.asyncio
    async def test_fivetran_to_dbt_source_nodes_synthesized(self):
        """Fivetran connector should get POPULATES edges to dbt SOURCE nodes.

        When raw BigQuery tables are only discovered via dbt (as NodeType.SOURCE
        with PlatformDomain.WAREHOUSE), they must still be matched as ingestion
        destinations.
        """
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        graph = LineageGraph()

        # Fivetran connector with synced_tables metadata
        ft_connector = _make_node(
            "my_connector", NodeType.SOURCE, "fivetran", PlatformDomain.INGESTION,
        )
        ft_connector.raw_metadata = {
            "service": "postgres",
            "schema": "raw",
            "connector_name": "my_connector",
            "synced_tables": ["customers", "orders"],
        }
        graph.add_node(ft_connector)

        # dbt SOURCE nodes representing raw BigQuery tables
        # These have NodeType.SOURCE + PlatformDomain.WAREHOUSE
        for name in ["customers", "orders"]:
            node = _make_node(
                name, NodeType.SOURCE, "dbt", PlatformDomain.WAREHOUSE,
                database="my-project", schema="raw",
            )
            graph.add_node(node)

        mock_result = InvestigationResult(
            success=True,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=graph,
            stats={},
            errors=[],
            duration_ms=50,
        )

        registry = RunRegistry()
        store = MagicMock()
        config = ExtractionPipelineConfig()

        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            run_id = await run_extraction_pipeline([], registry, store, config)

        record = registry.get_run(run_id)
        assert record.status == RunStatus.COMPLETED

        # Check that POPULATES edges were created from connector to dbt sources
        final_graph = store.graph
        populates_edges = [
            e for e in final_graph.edges.values()
            if e.edge_type == EdgeType.POPULATES
        ]
        assert len(populates_edges) >= 2, (
            f"Expected at least 2 POPULATES edges (connector→dbt source customers, "
            f"connector→dbt source orders), got {len(populates_edges)}"
        )

        # Verify synthesis stats
        stats = record.artifacts.stats
        assert stats["cross_tool_synthesis"]["ingestion_edges"] >= 2

    @pytest.mark.asyncio
    async def test_synthesis_stats_in_artifacts(self):
        """Cross-tool synthesis stats should appear in run artifacts even with 0 edges."""
        from scanner.lineage.engine.pipeline import (
            ExtractionPipelineConfig,
            run_extraction_pipeline,
        )
        from scanner.lineage.engine.investigator import InvestigationResult

        # Graph with only warehouse tables (no ingestion nodes)
        graph = LineageGraph()
        for name in ["customers", "orders"]:
            node = _make_node(
                name, NodeType.TABLE, "bigquery", PlatformDomain.WAREHOUSE,
                database="my-project", schema="analytics",
            )
            graph.add_node(node)

        mock_result = InvestigationResult(
            success=True,
            context=MagicMock(to_dict=MagicMock(return_value={})),
            graph=graph,
            stats={},
            errors=[],
            duration_ms=50,
        )

        registry = RunRegistry()
        store = MagicMock()

        with patch(
            "scanner.lineage.engine.pipeline._run_investigation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            run_id = await run_extraction_pipeline(
                [], registry, store, ExtractionPipelineConfig(),
            )

        record = registry.get_run(run_id)
        assert "cross_tool_synthesis" in record.artifacts.stats
