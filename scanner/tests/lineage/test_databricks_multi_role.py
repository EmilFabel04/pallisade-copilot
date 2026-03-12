"""
Tests for Databricks multi-role adapter — PR 2 proof-point.

Verifies that the LiveDatabricksAdapter discovers workflow jobs alongside
Unity Catalog tables, emits correct metadata for evidence-based role
classification, and that the multi-role framework from PR 1 splits
Databricks into separate pipeline nodes when both roles have content.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    HealthStatus,
    LineageEdge,
    LineageGraph,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.adapters.live_databricks import LiveDatabricksAdapter
from scanner.lineage.engine.control_plane import build_control_plane_graph
from scanner.lineage.engine.zones import classify_actor_capability, ActorCapability
from scanner.drivers.warehouse.databricks_driver import DatabricksDriver
from scanner.drivers.base import ObservedCapability


# ── Mock HTTP helpers ────────────────────────────────────────────────────

def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        from httpx import HTTPStatusError
        resp.raise_for_status.side_effect = HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp,
        )
    return resp


def _make_mock_client(responses: dict):
    """Create a mock httpx client that returns canned responses by URL path."""
    client = MagicMock()

    def _get(url, **kwargs):
        for path, resp in responses.items():
            if path in url:
                return resp
        return _mock_response(404, {})

    client.get = MagicMock(side_effect=_get)
    return client


# ── Fixture data ─────────────────────────────────────────────────────────

MOCK_CATALOGS = {"catalogs": [{"name": "main", "owner": "admin"}]}
MOCK_SCHEMAS = {"schemas": [{"name": "raw"}, {"name": "analytics"}]}
MOCK_TABLES = {"tables": [
    {"name": "orders", "table_type": "MANAGED", "columns": []},
    {"name": "customers", "table_type": "MANAGED", "columns": []},
]}

MOCK_JOBS = {"jobs": [
    {
        "job_id": 101,
        "creator_user_name": "data-eng@acme.com",
        "created_time": 1700000000000,
        "settings": {
            "name": "etl_daily",
            "format": "MULTI_TASK",
            "schedule": {"quartz_cron_expression": "0 0 6 * * ?"},
            "tasks": [
                {
                    "task_key": "extract_orders",
                    "notebook_task": {"notebook_path": "/etl/extract_orders"},
                    "depends_on": [],
                },
                {
                    "task_key": "transform_orders",
                    "sql_task": {"query": {"value": "SELECT * FROM raw.orders"}},
                    "depends_on": [{"task_key": "extract_orders"}],
                },
            ],
        },
    },
    {
        "job_id": 102,
        "creator_user_name": "data-eng@acme.com",
        "settings": {
            "name": "ml_training",
            "format": "SINGLE_TASK",
            "tasks": [
                {
                    "task_key": "train_model",
                    "spark_python_task": {"python_file": "/ml/train.py"},
                },
            ],
        },
    },
], "has_more": False}

MOCK_EMPTY_JOBS = {"jobs": [], "has_more": False}

BASE_CONFIG = {
    "namespace": "acme-prod",
    "integration_id": "int_123",
}


def _config_with_client(client):
    return {**BASE_CONFIG, "client": client}


def _build_client_with_tables_and_jobs():
    """Client that returns both catalogs/tables and jobs."""
    return _make_mock_client({
        "/api/2.1/unity-catalog/catalogs": _mock_response(200, MOCK_CATALOGS),
        "/api/2.1/unity-catalog/schemas": _mock_response(200, MOCK_SCHEMAS),
        "/api/2.1/unity-catalog/tables": _mock_response(200, MOCK_TABLES),
        "/api/2.1/unity-catalog/lineage/table-lineage": _mock_response(200, {}),
        "/api/2.1/unity-catalog/lineage/column-lineage": _mock_response(200, {}),
        "/api/2.1/jobs/list": _mock_response(200, MOCK_JOBS),
    })


def _build_client_tables_only():
    """Client that returns tables but Jobs API is 403."""
    return _make_mock_client({
        "/api/2.1/unity-catalog/catalogs": _mock_response(200, MOCK_CATALOGS),
        "/api/2.1/unity-catalog/schemas": _mock_response(200, MOCK_SCHEMAS),
        "/api/2.1/unity-catalog/tables": _mock_response(200, MOCK_TABLES),
        "/api/2.1/unity-catalog/lineage/table-lineage": _mock_response(200, {}),
        "/api/2.1/unity-catalog/lineage/column-lineage": _mock_response(200, {}),
        "/api/2.1/jobs/list": _mock_response(403, {}),
    })


# ═════════════════════════════════════════════════════════════════════════
# 1. Job Discovery Tests
# ═════════════════════════════════════════════════════════════════════════

class TestJobDiscovery:
    """Tests that LiveDatabricksAdapter discovers workflow jobs."""

    def test_discover_jobs_basic(self):
        """Jobs API returns 2 jobs → adapter emits JOB nodes with correct metadata."""
        adapter = LiveDatabricksAdapter()
        client = _build_client_with_tables_and_jobs()
        config = _config_with_client(client)

        nodes = adapter.discover_assets(config)

        job_nodes = [n for n in nodes if n.asset_kind == AssetKind.JOB]
        assert len(job_nodes) == 2

        etl_job = next(n for n in job_nodes if "etl_daily" in n.name)
        assert etl_job.platform == "databricks"
        assert etl_job.platform_domain == PlatformDomain.ORCHESTRATION
        assert etl_job.node_type == NodeType.PIPELINE
        assert etl_job.raw_metadata["workflow_id"] == "101"
        assert etl_job.raw_metadata["is_orchestrator"] is True
        assert etl_job.raw_metadata["task_count"] == 2

    def test_discover_tasks_within_jobs(self):
        """Jobs with tasks → adapter emits TASK nodes."""
        adapter = LiveDatabricksAdapter()
        client = _build_client_with_tables_and_jobs()
        config = _config_with_client(client)

        nodes = adapter.discover_assets(config)

        task_nodes = [n for n in nodes if n.asset_kind == AssetKind.TASK]
        # etl_daily has 2 tasks, ml_training has 1 task
        assert len(task_nodes) == 3

        extract_task = next(n for n in task_nodes if "extract_orders" in n.name)
        assert extract_task.node_type == NodeType.TASK
        assert extract_task.platform_domain == PlatformDomain.ORCHESTRATION
        assert extract_task.raw_metadata["workflow_id"] == "101"
        assert extract_task.raw_metadata["task_type"] == "notebook"
        assert extract_task.raw_metadata["notebook_path"] == "/etl/extract_orders"

        transform_task = next(n for n in task_nodes if "transform_orders" in n.name)
        assert transform_task.raw_metadata["task_type"] == "sql"
        assert "extract_orders" in transform_task.raw_metadata["depends_on"]

    def test_jobs_api_403_graceful(self):
        """Jobs API returns 403 → adapter returns only table nodes, no error."""
        adapter = LiveDatabricksAdapter()
        client = _build_client_tables_only()
        config = _config_with_client(client)

        nodes = adapter.discover_assets(config)

        # Should have table nodes but no job/task nodes
        table_nodes = [n for n in nodes if n.platform_domain == PlatformDomain.WAREHOUSE]
        job_nodes = [n for n in nodes if n.asset_kind == AssetKind.JOB]
        task_nodes = [n for n in nodes if n.asset_kind == AssetKind.TASK]

        assert len(table_nodes) > 0
        assert len(job_nodes) == 0
        assert len(task_nodes) == 0

    def test_jobs_api_connection_error(self):
        """httpx connection error → adapter returns only table nodes."""
        adapter = LiveDatabricksAdapter()

        client = _make_mock_client({
            "/api/2.1/unity-catalog/catalogs": _mock_response(200, MOCK_CATALOGS),
            "/api/2.1/unity-catalog/schemas": _mock_response(200, MOCK_SCHEMAS),
            "/api/2.1/unity-catalog/tables": _mock_response(200, MOCK_TABLES),
        })
        # Make jobs/list raise an exception
        original_get = client.get.side_effect

        def _get_with_error(url, **kwargs):
            if "jobs/list" in url:
                raise ConnectionError("Connection refused")
            return original_get(url, **kwargs)

        client.get.side_effect = _get_with_error
        config = _config_with_client(client)

        nodes = adapter.discover_assets(config)

        job_nodes = [n for n in nodes if n.asset_kind == AssetKind.JOB]
        assert len(job_nodes) == 0
        assert len([n for n in nodes if n.platform_domain == PlatformDomain.WAREHOUSE]) > 0

    def test_task_type_classification(self):
        """_classify_task_type correctly identifies task types."""
        adapter = LiveDatabricksAdapter()

        assert adapter._classify_task_type({"notebook_task": {}}) == "notebook"
        assert adapter._classify_task_type({"sql_task": {}}) == "sql"
        assert adapter._classify_task_type({"spark_python_task": {}}) == "spark_python"
        assert adapter._classify_task_type({"spark_jar_task": {}}) == "spark_jar"
        assert adapter._classify_task_type({"python_wheel_task": {}}) == "python_wheel"
        assert adapter._classify_task_type({"pipeline_task": {}}) == "dlt_pipeline"
        assert adapter._classify_task_type({"dbt_task": {}}) == "dbt"
        assert adapter._classify_task_type({}) == "unknown"


# ═════════════════════════════════════════════════════════════════════════
# 2. Edge Tests
# ═════════════════════════════════════════════════════════════════════════

class TestJobEdges:
    """Tests for control-plane and cross-plane edges."""

    def test_job_to_task_control_edges(self):
        """Job→Task edges use LinePlane.CONTROL and EdgeType.DEPENDS_ON."""
        adapter = LiveDatabricksAdapter()
        client = _build_client_with_tables_and_jobs()
        config = _config_with_client(client)

        edges = adapter.extract_lineage(config)

        control_edges = [e for e in edges if e.plane == LinePlane.CONTROL]
        # etl_daily → 2 tasks, ml_training → 1 task = 3 job→task edges
        # plus 1 task→task dependency (transform_orders depends on extract_orders)
        job_to_task = [
            e for e in control_edges
            if e.edge_type == EdgeType.DEPENDS_ON
        ]
        assert len(job_to_task) >= 3  # At least 3 job→task edges

    def test_task_dependency_edges(self):
        """Task→Task deps from depends_on create CONTROL edges."""
        adapter = LiveDatabricksAdapter()
        client = _build_client_with_tables_and_jobs()
        config = _config_with_client(client)

        edges = adapter.extract_lineage(config)

        control_edges = [e for e in edges if e.plane == LinePlane.CONTROL]
        # Find the extract_orders >> transform_orders dependency
        dep_edges = [
            e for e in control_edges
            if e.discovered_from and "extract_orders>>transform_orders" in e.discovered_from
        ]
        assert len(dep_edges) == 1
        assert dep_edges[0].confidence == 1.0


# ═════════════════════════════════════════════════════════════════════════
# 3. Driver Tests
# ═════════════════════════════════════════════════════════════════════════

class TestDatabricksDriverCapabilities:
    """Tests for DatabricksDriver.observed_capabilities()."""

    def test_observed_capabilities_with_jobs(self):
        """Jobs API success → returns both warehouse and orchestration."""
        import httpx as real_httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jobs": [{"job_id": 1}], "has_more": True}

        with patch.object(real_httpx, "get", return_value=mock_resp):
            driver = DatabricksDriver()
            caps = driver.observed_capabilities({
                "host": "adb-123.azuredatabricks.net",
                "token": "dapi_test_token",
            })

        cap_names = [c.capability for c in caps]
        assert "warehouse" in cap_names
        assert "orchestration" in cap_names

        orch_cap = next(c for c in caps if c.capability == "orchestration")
        assert orch_cap.source == "api_probe"
        assert orch_cap.confidence == 0.9
        assert orch_cap.metadata["api_endpoint"] == "/api/2.1/jobs/list"

    def test_observed_capabilities_no_jobs(self):
        """Jobs API 403 → returns only warehouse."""
        import httpx as real_httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch.object(real_httpx, "get", return_value=mock_resp):
            driver = DatabricksDriver()
            caps = driver.observed_capabilities({
                "host": "adb-123.azuredatabricks.net",
                "token": "dapi_test_token",
            })

        cap_names = [c.capability for c in caps]
        assert "warehouse" in cap_names
        assert "orchestration" not in cap_names

    def test_observed_capabilities_no_credentials(self):
        """No host/token → returns only driver_identity warehouse."""
        driver = DatabricksDriver()
        caps = driver.observed_capabilities({})

        assert len(caps) == 1
        assert caps[0].capability == "warehouse"
        assert caps[0].source == "driver_identity"


# ═════════════════════════════════════════════════════════════════════════
# 4. Evidence-Based Classification Tests
# ═════════════════════════════════════════════════════════════════════════

class TestRoleMetadataClassification:
    """Tests that job nodes with workflow_id metadata trigger correct classification."""

    def test_workflow_id_triggers_orchestration(self):
        """Node with workflow_id → classify_actor_capability returns ORCHESTRATION."""
        node = LineageNode(
            id="test-job",
            name="etl_daily",
            fqn="databricks.jobs.etl_daily",
            node_type=NodeType.PIPELINE,
            platform="databricks",
            platform_domain=PlatformDomain.ORCHESTRATION,
            raw_metadata={"workflow_id": "101", "is_orchestrator": True},
        )
        result = classify_actor_capability(node)
        assert result == ActorCapability.ORCHESTRATION

    def test_table_node_no_orchestration(self):
        """Table node without workflow_id → does NOT get ORCHESTRATION."""
        node = LineageNode(
            id="test-table",
            name="orders",
            fqn="main.raw.orders",
            node_type=NodeType.TABLE,
            platform="databricks",
            platform_domain=PlatformDomain.WAREHOUSE,
            raw_metadata={"unity_catalog": {"table_type": "MANAGED"}},
        )
        result = classify_actor_capability(node)
        # Should NOT be ORCHESTRATION — should fall through to platform set
        assert result != ActorCapability.ORCHESTRATION


# ═════════════════════════════════════════════════════════════════════════
# 5. End-to-End Integration Tests (Control Plane)
# ═════════════════════════════════════════════════════════════════════════

def _make_cp_node(
    node_id: str,
    name: str,
    platform: str = "databricks",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    node_type: NodeType = NodeType.TABLE,
    canonical_type: str = "dataset",
    raw_metadata: dict = None,
    integration_id: str = "int_123",
) -> LineageNode:
    """Helper to create nodes for control-plane graph tests."""
    return LineageNode(
        id=node_id,
        name=name,
        fqn=f"databricks.{name}",
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        canonical_type=canonical_type,
        raw_metadata=raw_metadata or {},
        integration_id=integration_id,
        health_status=HealthStatus.HEALTHY,
    )


class TestControlPlaneIntegration:
    """Tests that Databricks multi-role output triggers correct CP graph."""

    def test_databricks_splits_in_control_plane(self):
        """Tables + jobs → separate CP nodes for warehouse and orchestration."""
        graph = LineageGraph()

        # Add table nodes (warehouse role)
        for i in range(3):
            graph.add_node(_make_cp_node(
                f"tbl_{i}", f"table_{i}",
                platform_domain=PlatformDomain.WAREHOUSE,
                node_type=NodeType.TABLE,
                canonical_type="dataset",
            ))

        # Add job nodes (orchestration role)
        for i in range(2):
            graph.add_node(_make_cp_node(
                f"job_{i}", f"job_{i}",
                platform_domain=PlatformDomain.ORCHESTRATION,
                node_type=NodeType.PIPELINE,
                canonical_type="job",
                raw_metadata={"workflow_id": str(i), "is_orchestrator": True},
            ))

        # Add a cross-plane edge (job → table)
        graph.add_edge(LineageEdge(
            id="job_0→tbl_0",
            source_id="job_0",
            target_id="tbl_0",
            edge_type=EdgeType.WRITES_TO,
            plane=LinePlane.CROSS,
        ))

        cp = build_control_plane_graph(graph)

        # Should have 2 CP nodes for Databricks (role-split)
        db_nodes = [n for n in cp.nodes if n.tool_type == "databricks"]
        assert len(db_nodes) >= 2, (
            f"Expected 2+ CP nodes for Databricks (role-split), "
            f"got {len(db_nodes)}: {[n.name for n in db_nodes]}"
        )

        domains = {n.platform_domain for n in db_nodes}
        assert PlatformDomain.WAREHOUSE.value in domains or "warehouse" in domains
        assert PlatformDomain.ORCHESTRATION.value in domains or "orchestration" in domains

    def test_databricks_no_split_tables_only(self):
        """Tables only (no jobs) → single CP node (no speculative split)."""
        graph = LineageGraph()

        # Only table nodes — no job evidence
        for i in range(5):
            graph.add_node(_make_cp_node(
                f"tbl_{i}", f"table_{i}",
                platform_domain=PlatformDomain.WAREHOUSE,
                node_type=NodeType.TABLE,
                canonical_type="dataset",
            ))

        cp = build_control_plane_graph(graph)

        db_nodes = [n for n in cp.nodes if n.tool_type == "databricks"]
        assert len(db_nodes) == 1, (
            f"Expected 1 CP node for Databricks (no split), "
            f"got {len(db_nodes)}: {[n.name for n in db_nodes]}"
        )

    def test_databricks_no_split_single_job(self):
        """One job + zero tables → single CP node (need 2+ roles for split)."""
        graph = LineageGraph()

        graph.add_node(_make_cp_node(
            "job_0", "my_job",
            platform_domain=PlatformDomain.ORCHESTRATION,
            node_type=NodeType.PIPELINE,
            canonical_type="job",
            raw_metadata={"workflow_id": "1", "is_orchestrator": True},
        ))

        cp = build_control_plane_graph(graph)

        db_nodes = [n for n in cp.nodes if n.tool_type == "databricks"]
        assert len(db_nodes) == 1
