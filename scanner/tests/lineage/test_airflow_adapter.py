"""Tests for the LiveAirflowAdapter (static mode)."""

import pytest
from scanner.lineage.engine.adapters.live_airflow import LiveAirflowAdapter
from scanner.lineage.engine.ids import generate_asset_id
from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    LineageLevel,
    LinePlane,
    NodeType,
    PlatformDomain,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_DAG = '''
from airflow import DAG
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
from airflow.operators.python import PythonOperator

with DAG("test_dag", schedule="@daily", default_args={"owner": "test"}) as dag:
    load = BigQueryInsertJobOperator(
        task_id="load_data",
        configuration={
            "query": {
                "query": "INSERT INTO project.analytics.output SELECT * FROM project.raw.input",
                "destinationTable": {
                    "projectId": "project",
                    "datasetId": "analytics",
                    "tableId": "output",
                },
            }
        },
    )

    check = PythonOperator(
        task_id="check_data",
        python_callable=lambda: None,
    )

    load >> check
'''

MULTI_TABLE_DAG = '''
from airflow import DAG
from airflow.providers.google.cloud.operators.bigquery import BigQueryExecuteQueryOperator

with DAG("multi_table_dag") as dag:
    join_task = BigQueryExecuteQueryOperator(
        task_id="join_tables",
        sql="INSERT INTO warehouse.analytics.joined SELECT * FROM warehouse.raw.users JOIN warehouse.raw.events ON users.id = events.user_id",
    )
'''


@pytest.fixture
def adapter():
    return LiveAirflowAdapter(adapter_id="test_airflow")


@pytest.fixture
def simple_config():
    return {
        "mode": "static",
        "namespace": "test",
        "integration_id": "int_123",
        "dag_files": {"test_dag.py": SIMPLE_DAG},
    }


@pytest.fixture
def multi_table_config():
    return {
        "mode": "static",
        "namespace": "test",
        "dag_files": {"multi.py": MULTI_TABLE_DAG},
    }


# ---------------------------------------------------------------------------
# discover_assets
# ---------------------------------------------------------------------------

class TestDiscoverAssets:
    def test_discover_dag_nodes(self, adapter, simple_config):
        nodes = adapter.discover_assets(simple_config)
        dag_nodes = [n for n in nodes if n.node_type == NodeType.DAG]
        assert len(dag_nodes) == 1
        dag = dag_nodes[0]
        assert dag.name == "test_dag"
        assert dag.platform == "airflow"
        assert dag.platform_domain == PlatformDomain.ORCHESTRATION
        assert dag.asset_kind == AssetKind.JOB
        assert dag.namespace == "test"

    def test_discover_task_nodes(self, adapter, simple_config):
        nodes = adapter.discover_assets(simple_config)
        task_nodes = [n for n in nodes if n.node_type == NodeType.TASK]
        assert len(task_nodes) == 2
        task_ids = {n.name for n in task_nodes}
        assert task_ids == {"load_data", "check_data"}
        for tn in task_nodes:
            assert tn.platform_domain == PlatformDomain.ORCHESTRATION
            assert tn.asset_kind == AssetKind.TASK

    def test_discover_table_nodes(self, adapter, simple_config):
        nodes = adapter.discover_assets(simple_config)
        table_nodes = [n for n in nodes if n.node_type == NodeType.TABLE]
        # load_data reads from project.raw.input, writes to project.analytics.output
        # PythonOperator is opaque → no tables
        assert len(table_nodes) >= 2
        table_names = {n.name for n in table_nodes}
        assert "input" in table_names
        assert "output" in table_names

    def test_table_nodes_use_warehouse_domain(self, adapter, simple_config):
        """Table nodes must use WAREHOUSE domain for cross-tool dedup."""
        nodes = adapter.discover_assets(simple_config)
        table_nodes = [n for n in nodes if n.node_type == NodeType.TABLE]
        for tn in table_nodes:
            assert tn.platform_domain == PlatformDomain.WAREHOUSE
            assert tn.asset_kind == AssetKind.TABLE

    def test_opaque_operator_no_tables(self, adapter, simple_config):
        """PythonOperator should not produce any table nodes."""
        nodes = adapter.discover_assets(simple_config)
        task_nodes = [n for n in nodes if n.node_type == NodeType.TASK]
        check_task = next(n for n in task_nodes if n.name == "check_data")
        assert check_task.raw_metadata.get("is_opaque") is True

    def test_empty_dag_files_returns_only_pipeline_node(self, adapter):
        # The adapter always emits a single Airflow pipeline node so the
        # platform shows up in lineage even before any DAGs are discovered.
        # Asset-level nodes (DAGs/tasks/tables) should remain empty.
        nodes = adapter.discover_assets({"namespace": "test", "dag_files": {}})
        non_pipeline = [n for n in nodes if n.node_type != NodeType.PIPELINE]
        assert non_pipeline == []


# ---------------------------------------------------------------------------
# extract_lineage
# ---------------------------------------------------------------------------

class TestExtractLineage:
    def test_dag_to_task_edges(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        dag_to_task = [
            e for e in edges
            if e.edge_type == EdgeType.DEPENDS_ON
            and e.lineage_level == LineageLevel.TOOL
        ]
        # DAG → load_data, DAG → check_data
        dag_asset_id = generate_asset_id("orchestration", "airflow", "test", "", "test_dag")
        dag_edges = [e for e in dag_to_task if e.source_id == dag_asset_id]
        assert len(dag_edges) == 2

    def test_task_to_task_edges(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        # load >> check
        load_id = generate_asset_id("orchestration", "airflow", "test", "test_dag", "load_data")
        check_id = generate_asset_id("orchestration", "airflow", "test", "test_dag", "check_data")
        dep_edges = [
            e for e in edges
            if e.source_id == load_id and e.target_id == check_id
        ]
        assert len(dep_edges) == 1
        assert dep_edges[0].confidence == 1.0

    def test_task_to_table_write_edges(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        write_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]
        assert len(write_edges) >= 1

    def test_table_to_task_read_edges(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        read_edges = [e for e in edges if e.edge_type == EdgeType.READS_FROM]
        assert len(read_edges) >= 1

    def test_evidence_on_edges(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        for edge in edges:
            assert len(edge.evidence) > 0
            ev = edge.evidence[0]
            assert ev.adapter_id == "test_airflow"
            assert ev.source_ref is not None

    def test_confidence_levels(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        # Tool-level edges should be 1.0
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        for e in tool_edges:
            assert e.confidence == 1.0
        # Table-level edges should be 0.8 (SQL-parsed)
        table_edges = [e for e in edges if e.lineage_level == LineageLevel.TABLE]
        for e in table_edges:
            assert 0.0 < e.confidence <= 1.0

    def test_multi_table_join(self, adapter, multi_table_config):
        edges = adapter.extract_lineage(multi_table_config)
        read_edges = [e for e in edges if e.edge_type == EdgeType.READS_FROM]
        write_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]
        # Should read from users and events, write to joined
        assert len(read_edges) >= 2
        assert len(write_edges) >= 1


# ---------------------------------------------------------------------------
# ID generation / cross-tool dedup
# ---------------------------------------------------------------------------

class TestIdDedup:
    def test_table_node_ids_match_warehouse_pattern(self, adapter, simple_config):
        """Table IDs should use warehouse domain so they dedup with BQ nodes."""
        nodes = adapter.discover_assets(simple_config)
        table_nodes = [n for n in nodes if n.node_type == NodeType.TABLE]
        for tn in table_nodes:
            # Verify the ID was generated with "warehouse" domain
            expected_id = generate_asset_id(
                "warehouse", "airflow", "test",
                f"{tn.database or ''}.{tn.schema or ''}",
                tn.name,
            )
            assert tn.id == expected_id

    def test_dag_node_id_uses_orchestration_domain(self, adapter, simple_config):
        nodes = adapter.discover_assets(simple_config)
        dag_nodes = [n for n in nodes if n.node_type == NodeType.DAG]
        for dn in dag_nodes:
            expected_id = generate_asset_id(
                "orchestration", "airflow", "test", "", dn.name,
            )
            assert dn.id == expected_id


# ---------------------------------------------------------------------------
# Edge plane classification
# ---------------------------------------------------------------------------

class TestEdgePlaneClassification:
    def test_dag_to_task_edges_are_control_plane(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        dag_asset_id = generate_asset_id("orchestration", "airflow", "test", "", "test_dag")
        dag_edges = [
            e for e in edges
            if e.source_id == dag_asset_id
            and e.lineage_level == LineageLevel.TOOL
        ]
        assert len(dag_edges) == 2
        for e in dag_edges:
            assert e.plane == LinePlane.CONTROL

    def test_task_to_task_edges_are_control_plane(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        load_id = generate_asset_id("orchestration", "airflow", "test", "test_dag", "load_data")
        check_id = generate_asset_id("orchestration", "airflow", "test", "test_dag", "check_data")
        dep_edges = [
            e for e in edges
            if e.source_id == load_id and e.target_id == check_id
        ]
        assert len(dep_edges) == 1
        assert dep_edges[0].plane == LinePlane.CONTROL

    def test_task_to_table_write_edges_are_cross_plane(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        write_edges = [e for e in edges if e.edge_type == EdgeType.WRITES_TO]
        assert len(write_edges) >= 1
        for e in write_edges:
            assert e.plane == LinePlane.CROSS

    def test_table_to_task_read_edges_are_cross_plane(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        read_edges = [e for e in edges if e.edge_type == EdgeType.READS_FROM]
        assert len(read_edges) >= 1
        for e in read_edges:
            assert e.plane == LinePlane.CROSS

    def test_all_tool_level_edges_are_control(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        for e in tool_edges:
            assert e.plane == LinePlane.CONTROL

    def test_all_table_level_edges_are_cross(self, adapter, simple_config):
        edges = adapter.extract_lineage(simple_config)
        table_edges = [e for e in edges if e.lineage_level == LineageLevel.TABLE]
        for e in table_edges:
            assert e.plane == LinePlane.CROSS
