"""
Tests for pipeline enrichment fixes:
- _merge_node_metadata() timestamp and health merging
- _run_health_enrichment() in the extraction pipeline
- Expanded jobCount detection in views.py
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from scanner.lineage.graph import (
    HealthStatus,
    LineageGraph,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.resolver import _merge_node_metadata
from scanner.lineage.engine.investigator import ToolConfig
from scanner.lineage.engine.views import ViewBuilder
from scanner.lineage.engine.canonical import canonicalize_graph_in_place


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    node_id: str,
    name: str = "test",
    fqn: str = "",
    platform: str = "bigquery",
    health_status: HealthStatus = HealthStatus.UNKNOWN,
    observed_at=None,
    last_updated=None,
    raw_metadata=None,
    canonical_type=None,
    node_type=NodeType.TABLE,
    platform_domain=PlatformDomain.WAREHOUSE,
) -> LineageNode:
    return LineageNode(
        id=node_id,
        name=name,
        fqn=fqn or name,
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        health_status=health_status,
        observed_at=observed_at,
        last_updated=last_updated,
        raw_metadata=raw_metadata or {},
        canonical_type=canonical_type,
    )


# ===========================================================================
# TestMergeNodeMetadataTimestamps
# ===========================================================================


class TestMergeNodeMetadataTimestamps:
    """Tests for observed_at, last_updated, and health_status merging."""

    def test_observed_at_keeps_most_recent(self):
        older = datetime(2025, 1, 1, 12, 0, 0)
        newer = datetime(2025, 6, 15, 12, 0, 0)
        primary = _make_node("a", observed_at=older)
        secondary = _make_node("b", observed_at=newer)

        _merge_node_metadata(primary, secondary)

        assert primary.observed_at == newer

    def test_observed_at_fills_none(self):
        ts = datetime(2025, 3, 1, 8, 0, 0)
        primary = _make_node("a", observed_at=None)
        secondary = _make_node("b", observed_at=ts)

        _merge_node_metadata(primary, secondary)

        assert primary.observed_at == ts

    def test_observed_at_keeps_primary_when_newer(self):
        newer = datetime(2025, 6, 15, 12, 0, 0)
        older = datetime(2025, 1, 1, 12, 0, 0)
        primary = _make_node("a", observed_at=newer)
        secondary = _make_node("b", observed_at=older)

        _merge_node_metadata(primary, secondary)

        assert primary.observed_at == newer

    def test_observed_at_unchanged_when_secondary_none(self):
        ts = datetime(2025, 3, 1, 8, 0, 0)
        primary = _make_node("a", observed_at=ts)
        secondary = _make_node("b", observed_at=None)

        _merge_node_metadata(primary, secondary)

        assert primary.observed_at == ts

    def test_last_updated_keeps_most_recent(self):
        older = datetime(2025, 1, 1)
        newer = datetime(2025, 6, 1)
        primary = _make_node("a", last_updated=older)
        secondary = _make_node("b", last_updated=newer)

        _merge_node_metadata(primary, secondary)

        assert primary.last_updated == newer

    def test_last_updated_fills_none(self):
        ts = datetime(2025, 3, 1)
        primary = _make_node("a", last_updated=None)
        secondary = _make_node("b", last_updated=ts)

        _merge_node_metadata(primary, secondary)

        assert primary.last_updated == ts

    def test_health_status_prefers_non_unknown(self):
        primary = _make_node("a", health_status=HealthStatus.UNKNOWN)
        secondary = _make_node("b", health_status=HealthStatus.HEALTHY)

        _merge_node_metadata(primary, secondary)

        assert primary.health_status == HealthStatus.HEALTHY

    def test_health_status_prefers_worse(self):
        primary = _make_node("a", health_status=HealthStatus.HEALTHY)
        secondary = _make_node("b", health_status=HealthStatus.FAILING)

        _merge_node_metadata(primary, secondary)

        assert primary.health_status == HealthStatus.FAILING

    def test_health_status_degraded_beats_healthy(self):
        primary = _make_node("a", health_status=HealthStatus.HEALTHY)
        secondary = _make_node("b", health_status=HealthStatus.DEGRADED)

        _merge_node_metadata(primary, secondary)

        assert primary.health_status == HealthStatus.DEGRADED

    def test_health_status_keeps_unknown_when_both_unknown(self):
        primary = _make_node("a", health_status=HealthStatus.UNKNOWN)
        secondary = _make_node("b", health_status=HealthStatus.UNKNOWN)

        _merge_node_metadata(primary, secondary)

        assert primary.health_status == HealthStatus.UNKNOWN

    def test_health_status_keeps_worse_primary(self):
        """If primary is already FAILING, secondary HEALTHY shouldn't downgrade."""
        primary = _make_node("a", health_status=HealthStatus.FAILING)
        secondary = _make_node("b", health_status=HealthStatus.HEALTHY)

        _merge_node_metadata(primary, secondary)

        assert primary.health_status == HealthStatus.FAILING


# ===========================================================================
# TestHealthEnrichment
# ===========================================================================


class TestHealthEnrichment:
    """Tests for _run_health_enrichment() in pipeline.py."""

    def _run_with_mock_health(self, graph, tool_configs, mock_health):
        """Helper that mocks both get_adapter and LiveElementaryAdapter."""
        import sys
        from scanner.lineage.engine.pipeline import _run_health_enrichment

        mock_elem_cls = MagicMock()
        mock_elem_instance = MagicMock()
        mock_elem_cls.return_value = mock_elem_instance
        mock_elem_instance.get_health_enrichment.return_value = mock_health

        # Create a fake module so the lazy import doesn't trigger
        # the full adapters __init__.py (which needs httpx)
        fake_elem_mod = MagicMock()
        fake_elem_mod.LiveElementaryAdapter = mock_elem_cls

        with patch("scanner.adapters.factory.get_adapter") as mock_get_adapter, \
             patch.dict(sys.modules, {
                 "scanner.lineage.engine.adapters.live_elementary": fake_elem_mod,
             }):
            mock_wh = MagicMock()
            mock_get_adapter.return_value = mock_wh
            result = _run_health_enrichment(graph, tool_configs, "test-run")

        return result

    def test_health_enrichment_applies_to_matching_nodes(self):
        graph = LineageGraph()
        node = _make_node("n1", name="orders", fqn="project.dataset.orders")
        graph.add_node(node)

        mock_health = {
            "project.dataset.orders": {
                "health_status": HealthStatus.HEALTHY,
                "total_tests": 5,
                "failed_tests": 0,
                "warn_tests": 0,
            }
        }

        tool_configs = [
            ToolConfig(tool_type="bigquery", config={"project_id": "test"})
        ]

        result = self._run_with_mock_health(graph, tool_configs, mock_health)

        assert result is not None
        assert result["tables_enriched"] == 1
        assert node.health_status == HealthStatus.HEALTHY
        assert node.raw_metadata["health_total_tests"] == 5

    def test_health_enrichment_matches_case_insensitive(self):
        graph = LineageGraph()
        node = _make_node("n1", fqn="PROJECT.DATASET.ORDERS")
        graph.add_node(node)

        mock_health = {
            "project.dataset.orders": {
                "health_status": HealthStatus.DEGRADED,
                "total_tests": 3,
                "failed_tests": 0,
                "warn_tests": 1,
            }
        }

        tool_configs = [
            ToolConfig(tool_type="bigquery", config={"project_id": "test"})
        ]

        result = self._run_with_mock_health(graph, tool_configs, mock_health)

        assert result["tables_enriched"] == 1
        assert node.health_status == HealthStatus.DEGRADED

    def test_health_enrichment_matches_short_fqn(self):
        graph = LineageGraph()
        node = _make_node("n1", fqn="my_project.raw.users")
        graph.add_node(node)

        mock_health = {
            "raw.users": {
                "health_status": HealthStatus.FAILING,
                "total_tests": 2,
                "failed_tests": 1,
                "warn_tests": 0,
            }
        }

        tool_configs = [
            ToolConfig(tool_type="bigquery", config={"project_id": "test"})
        ]

        result = self._run_with_mock_health(graph, tool_configs, mock_health)

        assert result["tables_enriched"] == 1
        assert node.health_status == HealthStatus.FAILING

    def test_health_enrichment_skips_when_no_warehouse_config(self):
        from scanner.lineage.engine.pipeline import _run_health_enrichment

        graph = LineageGraph()
        tool_configs = [
            ToolConfig(tool_type="dbt_core", config={})
        ]

        result = _run_health_enrichment(graph, tool_configs, "test-run")

        assert result is None

    def test_health_enrichment_nonfatal_on_error(self):
        from scanner.lineage.engine.pipeline import _run_health_enrichment

        graph = LineageGraph()
        tool_configs = [
            ToolConfig(tool_type="bigquery", config={"project_id": "test"})
        ]

        with patch("scanner.adapters.factory.get_adapter", side_effect=Exception("connection failed")):
            result = _run_health_enrichment(graph, tool_configs, "test-run")

        assert result is None


# ===========================================================================
# TestJobCountExpansion
# ===========================================================================


class TestJobCountExpansion:
    """Tests for expanded jobCount detection in views.py."""

    def _build_overview_with_nodes(self, nodes, edges=None):
        """Helper to build a lane pipeline overview from graph nodes."""
        graph = LineageGraph()
        for n in nodes:
            graph.add_node(n)
        if edges:
            for e in edges:
                graph.add_edge(e)

        canonicalize_graph_in_place(graph.nodes, graph.edges)

        tool_nodes = [
            {
                "id": "bq_001",
                "name": "BigQuery",
                "type": "bigquery",
                "platform": "bigquery",
                "integration_id": "int_bq",
                "datasets": ["raw"],
            }
        ]
        builder = ViewBuilder(graph, tool_nodes=tool_nodes)
        return builder.build_lane_pipeline_overview()

    def test_dbt_model_counts_as_job(self):
        node = _make_node(
            "dbt_model_1",
            name="stg_orders",
            fqn="raw.stg_orders",
            platform="bigquery",
            raw_metadata={"dbt_resource_type": "model"},
            node_type=NodeType.TABLE,
        )
        view = self._build_overview_with_nodes([node])

        # Find the BigQuery tool node
        bq_nodes = [vn for vn in view.nodes if "bigquery" in vn.platform]
        assert len(bq_nodes) > 0
        bq_node = bq_nodes[0]
        assert bq_node.metadata["jobCount"] >= 1

    def test_orchestrator_task_counts_as_job(self):
        node = _make_node(
            "airflow_task_1",
            name="load_data",
            fqn="raw.load_data",
            platform="bigquery",
            raw_metadata={"dag_id": "etl_pipeline"},
            node_type=NodeType.TABLE,
        )
        view = self._build_overview_with_nodes([node])

        bq_nodes = [vn for vn in view.nodes if "bigquery" in vn.platform]
        assert len(bq_nodes) > 0
        bq_node = bq_nodes[0]
        assert bq_node.metadata["jobCount"] >= 1

    def test_ingestion_sync_counts_as_job(self):
        node = _make_node(
            "fivetran_sync_1",
            name="sync_users",
            fqn="raw.sync_users",
            platform="bigquery",
            raw_metadata={"connector_id": "fivetran_conn_123"},
            node_type=NodeType.TABLE,
        )
        view = self._build_overview_with_nodes([node])

        bq_nodes = [vn for vn in view.nodes if "bigquery" in vn.platform]
        assert len(bq_nodes) > 0
        bq_node = bq_nodes[0]
        assert bq_node.metadata["jobCount"] >= 1

    def test_no_double_counting(self):
        """A node with canonical_type=job AND dbt_resource_type should count once."""
        node = _make_node(
            "dbt_job_1",
            name="stg_orders",
            fqn="raw.stg_orders",
            platform="bigquery",
            canonical_type="job",
            raw_metadata={"dbt_resource_type": "model"},
            node_type=NodeType.TASK,
        )
        view = self._build_overview_with_nodes([node])

        bq_nodes = [vn for vn in view.nodes if "bigquery" in vn.platform]
        assert len(bq_nodes) > 0
        bq_node = bq_nodes[0]
        # Should count exactly once, not twice
        assert bq_node.metadata["jobCount"] == 1

    def test_plain_table_not_counted_as_job(self):
        """A plain table node without job indicators should not count."""
        node = _make_node(
            "plain_table",
            name="raw_orders",
            fqn="raw.raw_orders",
            platform="bigquery",
            node_type=NodeType.TABLE,
        )
        view = self._build_overview_with_nodes([node])

        bq_nodes = [vn for vn in view.nodes if "bigquery" in vn.platform]
        assert len(bq_nodes) > 0
        bq_node = bq_nodes[0]
        assert bq_node.metadata["jobCount"] == 0
