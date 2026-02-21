"""
Tests for infrastructure lineage adapters:
  - LiveN8nAdapter
  - LiveDatabricksAdapter
  - LiveStorageAdapter
  - LiveElementaryAdapter

All tests use unittest.mock.MagicMock for client injection via config["client"].
No real integration clients are imported.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    Evidence,
    HealthStatus,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.adapter import BaseLineageAdapter, Capability
from scanner.lineage.engine.adapters.live_n8n import LiveN8nAdapter
from scanner.lineage.engine.adapters.live_databricks import LiveDatabricksAdapter
from scanner.lineage.engine.adapters.live_storage import LiveStorageAdapter
from scanner.lineage.engine.adapters.live_elementary import LiveElementaryAdapter


# =========================================================================
# Helpers: mock object factories
# =========================================================================


def _make_n8n_node(name: str, node_type: str, short_type: str, parameters: dict = None):
    """Create a mock n8n workflow node."""
    node = MagicMock()
    node.name = name
    node.type = node_type
    node.short_type = short_type
    node.parameters = parameters or {}
    return node


def _make_n8n_workflow(
    wf_id: str = "100",
    name: str = "My Workflow",
    active: bool = True,
    nodes: list = None,
    tags: list = None,
    created_at: datetime = None,
    updated_at: datetime = None,
):
    """Create a mock n8n workflow object."""
    wf = MagicMock()
    wf.id = wf_id
    wf.name = name
    wf.active = active
    wf.nodes = nodes or []
    wf.node_count = len(wf.nodes)
    wf.tags = tags or []
    wf.created_at = created_at
    wf.updated_at = updated_at
    return wf


def _make_databricks_client(
    catalogs=None,
    schemas_by_catalog=None,
    tables_by_schema=None,
    table_lineage_by_name=None,
    column_lineage_by_key=None,
):
    """
    Create a mock HTTP client that mimics Databricks Unity Catalog REST API.

    catalogs: list of dicts like [{"name": "main", "owner": "admin"}]
    schemas_by_catalog: dict mapping catalog_name -> list of schema dicts
    tables_by_schema: dict mapping "catalog.schema" -> list of table dicts
    table_lineage_by_name: dict mapping three-part name -> lineage response
    column_lineage_by_key: dict mapping "table_name|col_name" -> lineage response
    """
    catalogs = catalogs or []
    schemas_by_catalog = schemas_by_catalog or {}
    tables_by_schema = tables_by_schema or {}
    table_lineage_by_name = table_lineage_by_name or {}
    column_lineage_by_key = column_lineage_by_key or {}

    def _get(url, params=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        params = params or {}

        if url == "/api/2.1/unity-catalog/catalogs":
            resp.json.return_value = {"catalogs": catalogs}

        elif url == "/api/2.1/unity-catalog/schemas":
            cat = params.get("catalog_name", "")
            resp.json.return_value = {"schemas": schemas_by_catalog.get(cat, [])}

        elif url == "/api/2.1/unity-catalog/tables":
            cat = params.get("catalog_name", "")
            sch = params.get("schema_name", "")
            key = f"{cat}.{sch}"
            resp.json.return_value = {"tables": tables_by_schema.get(key, [])}

        elif url == "/api/2.1/unity-catalog/lineage/table-lineage":
            tbl = params.get("table_name", "")
            resp.json.return_value = table_lineage_by_name.get(tbl, {})

        elif url == "/api/2.1/unity-catalog/lineage/column-lineage":
            tbl = params.get("table_name", "")
            col = params.get("column_name", "")
            key = f"{tbl}|{col}"
            resp.json.return_value = column_lineage_by_key.get(key, {})

        else:
            resp.json.return_value = {}

        return resp

    client = MagicMock()
    client.get = MagicMock(side_effect=_get)
    return client


# =========================================================================
# LiveN8nAdapter Tests
# =========================================================================


class TestLiveN8nAdapter:
    """Tests for the n8n lineage adapter."""

    def _make_adapter(self, adapter_id: str = "live_n8n"):
        return LiveN8nAdapter(adapter_id=adapter_id)

    # ---- Identity & capabilities ----

    def test_id_returns_expected(self):
        adapter = self._make_adapter("my_n8n")
        assert adapter.id() == "my_n8n"

    def test_default_id(self):
        adapter = self._make_adapter()
        assert adapter.id() == "live_n8n"

    def test_capabilities(self):
        adapter = self._make_adapter()
        caps = adapter.capabilities()
        assert Capability.DISCOVER_ASSETS in caps
        assert Capability.EXTRACT_TOOL_LINEAGE in caps
        assert Capability.GET_RUNS_LOGS in caps

    def test_is_base_adapter_subclass(self):
        adapter = self._make_adapter()
        assert isinstance(adapter, BaseLineageAdapter)

    def test_case_hint(self):
        adapter = self._make_adapter()
        assert adapter.case_hint == "lower"

    # ---- discover_assets ----

    def test_discover_assets_workflow_and_task_nodes(self):
        """Workflows become WORKFLOW nodes; internal nodes become TASK nodes."""
        http_node = _make_n8n_node("HTTP Request", "n8n-nodes-base.httpRequest", "httpRequest")
        wf = _make_n8n_workflow(
            wf_id="42",
            name="Sync Users",
            active=True,
            nodes=[http_node],
            tags=[{"name": "production"}],
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 6, 15),
        )

        client = MagicMock()
        client.get_workflows.return_value = [wf]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client, "namespace": "acme"})

        assert len(nodes) == 2

        # Workflow node
        wf_node = [n for n in nodes if n.node_type == NodeType.WORKFLOW]
        assert len(wf_node) == 1
        assert wf_node[0].platform == "n8n"
        assert wf_node[0].platform_domain == PlatformDomain.ORCHESTRATION
        assert wf_node[0].asset_kind == AssetKind.WORKFLOW
        assert wf_node[0].name == "Sync Users"
        assert "n8n.acme.workflow.42" == wf_node[0].fqn
        assert wf_node[0].namespace == "acme"
        assert wf_node[0].raw_metadata["active"] is True
        assert wf_node[0].raw_metadata["node_count"] == 1
        assert wf_node[0].raw_metadata["tags"] == ["production"]

        # Task node
        task_nodes = [n for n in nodes if n.node_type == NodeType.TASK]
        assert len(task_nodes) == 1
        assert task_nodes[0].platform == "n8n"
        assert task_nodes[0].asset_kind == AssetKind.TASK
        assert task_nodes[0].name == "HTTP Request"
        assert task_nodes[0].fqn == "n8n.acme.workflow.42.HTTP Request"

    def test_discover_assets_multiple_workflows(self):
        """Multiple workflows with multiple nodes produce correct count."""
        nodes_wf1 = [
            _make_n8n_node("Start", "n8n-nodes-base.start", "start"),
            _make_n8n_node("Postgres", "n8n-nodes-base.postgres", "postgres"),
        ]
        nodes_wf2 = [
            _make_n8n_node("Cron", "n8n-nodes-base.cron", "cron"),
        ]
        wf1 = _make_n8n_workflow(wf_id="1", name="WF1", nodes=nodes_wf1)
        wf2 = _make_n8n_workflow(wf_id="2", name="WF2", nodes=nodes_wf2)

        client = MagicMock()
        client.get_workflows.return_value = [wf1, wf2]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client})

        # 2 workflows + 2 tasks + 1 task = 5
        assert len(nodes) == 5
        wf_nodes = [n for n in nodes if n.node_type == NodeType.WORKFLOW]
        task_nodes = [n for n in nodes if n.node_type == NodeType.TASK]
        assert len(wf_nodes) == 2
        assert len(task_nodes) == 3

    def test_discover_assets_empty_client_returns_empty(self):
        """No client in config → empty list."""
        adapter = self._make_adapter()
        nodes = adapter.discover_assets({})
        assert nodes == []

    def test_discover_assets_client_exception_returns_empty(self):
        """If get_workflows raises, return empty list."""
        client = MagicMock()
        client.get_workflows.side_effect = Exception("API error")

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client})
        assert nodes == []

    def test_discover_assets_no_nodes_in_workflow(self):
        """A workflow with zero internal nodes still produces a WORKFLOW node."""
        wf = _make_n8n_workflow(wf_id="10", name="Empty WF", nodes=[])

        client = MagicMock()
        client.get_workflows.return_value = [wf]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client})
        assert len(nodes) == 1
        assert nodes[0].node_type == NodeType.WORKFLOW

    # ---- extract_lineage ----

    def test_extract_lineage_workflow_task_edges(self):
        """Workflow→Task edges are CONTROL plane, DEPENDS_ON, confidence 1.0."""
        task_node = _make_n8n_node("Start", "n8n-nodes-base.start", "start")
        wf = _make_n8n_workflow(wf_id="5", name="WF", nodes=[task_node])

        client = MagicMock()
        client.get_workflows.return_value = [wf]

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client, "namespace": "ns"})

        # At least 1 edge: workflow → task
        control_edges = [e for e in edges if e.plane == LinePlane.CONTROL]
        assert len(control_edges) >= 1
        edge = control_edges[0]
        assert edge.edge_type == EdgeType.DEPENDS_ON
        assert edge.lineage_level == LineageLevel.TOOL
        assert edge.confidence == 1.0
        assert edge.plane == LinePlane.CONTROL

    def test_extract_lineage_db_node_creates_cross_plane_edges(self):
        """DB nodes with table params produce CROSS plane edges."""
        db_node = _make_n8n_node(
            "Read Users",
            "n8n-nodes-base.postgres",
            "postgres",
            {"table": "users", "schema": "public", "operation": "select"},
        )
        wf = _make_n8n_workflow(wf_id="7", name="DB WF", nodes=[db_node])

        client = MagicMock()
        client.get_workflows.return_value = [wf]

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client, "namespace": "ns"})

        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]
        assert len(cross_edges) >= 1
        # select = read operation, so edge should be READS_FROM
        reads_edges = [e for e in cross_edges if e.edge_type == EdgeType.READS_FROM]
        assert len(reads_edges) == 1
        assert reads_edges[0].confidence == 0.7
        assert reads_edges[0].lineage_level == LineageLevel.TABLE

    def test_extract_lineage_db_node_write_operation(self):
        """DB nodes with insert/update/upsert/delete produce WRITES_TO edges."""
        insert_node = _make_n8n_node(
            "Insert Orders",
            "n8n-nodes-base.postgres",
            "postgres",
            {"table": "orders", "schema": "sales", "operation": "insert"},
        )
        wf = _make_n8n_workflow(wf_id="8", name="Write WF", nodes=[insert_node])

        client = MagicMock()
        client.get_workflows.return_value = [wf]

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client, "namespace": "ns"})

        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]
        writes_edges = [e for e in cross_edges if e.edge_type == EdgeType.WRITES_TO]
        assert len(writes_edges) == 1
        assert writes_edges[0].confidence == 0.7

    def test_extract_lineage_empty_client_returns_empty(self):
        """No client → empty edge list."""
        adapter = self._make_adapter()
        edges = adapter.extract_lineage({})
        assert edges == []

    def test_extract_lineage_client_exception_returns_empty(self):
        """If get_workflows raises during lineage, return empty."""
        client = MagicMock()
        client.get_workflows.side_effect = Exception("n8n down")

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client})
        assert edges == []

    # ---- _extract_db_table_refs ----

    def test_extract_db_table_refs_from_params(self):
        """Table and schema params are combined into a ref."""
        node = _make_n8n_node(
            "PG", "n8n-nodes-base.postgres", "postgres",
            {"table": "users", "schema": "public", "operation": "select"},
        )
        adapter = self._make_adapter()
        refs = adapter._extract_db_table_refs(node)

        assert len(refs) == 1
        table_ref, is_write = refs[0]
        assert table_ref == "public.users"
        assert is_write is False

    def test_extract_db_table_refs_write_operations(self):
        """Insert, update, upsert, delete, create are all writes."""
        for op in ("insert", "update", "upsert", "delete", "create"):
            node = _make_n8n_node(
                "N", "n8n-nodes-base.postgres", "postgres",
                {"table": "t", "operation": op},
            )
            adapter = self._make_adapter()
            refs = adapter._extract_db_table_refs(node)
            assert refs[0][1] is True, f"operation={op} should be a write"

    def test_extract_db_table_refs_no_schema(self):
        """When schema is missing, ref is just the table name."""
        node = _make_n8n_node(
            "PG", "n8n-nodes-base.postgres", "postgres",
            {"table": "events", "operation": "select"},
        )
        adapter = self._make_adapter()
        refs = adapter._extract_db_table_refs(node)

        assert refs[0][0] == "events"

    def test_extract_db_table_refs_from_sql_query(self):
        """When no table param but query is provided, parse FROM/JOIN clauses."""
        node = _make_n8n_node(
            "PG", "n8n-nodes-base.postgres", "postgres",
            {"query": "SELECT * FROM analytics.events JOIN analytics.users ON 1=1"},
        )
        adapter = self._make_adapter()
        refs = adapter._extract_db_table_refs(node)

        table_names = [r[0] for r in refs]
        assert "analytics.events" in table_names
        assert "analytics.users" in table_names

    def test_extract_db_table_refs_sql_insert(self):
        """SQL INSERT INTO should be flagged as write."""
        node = _make_n8n_node(
            "PG", "n8n-nodes-base.postgres", "postgres",
            {"query": "INSERT INTO staging.raw_events SELECT * FROM source.events"},
        )
        adapter = self._make_adapter()
        refs = adapter._extract_db_table_refs(node)

        # All refs from an INSERT query should be writes
        for table_ref, is_write in refs:
            assert is_write is True

    def test_extract_db_table_refs_empty_params(self):
        """No table and no query → empty list."""
        node = _make_n8n_node(
            "PG", "n8n-nodes-base.postgres", "postgres", {},
        )
        adapter = self._make_adapter()
        refs = adapter._extract_db_table_refs(node)
        assert refs == []

    # ---- Evidence structure ----

    def test_edges_have_evidence(self):
        """Every edge should carry at least one Evidence record."""
        task_node = _make_n8n_node("T", "n8n-nodes-base.start", "start")
        wf = _make_n8n_workflow(wf_id="1", name="WF", nodes=[task_node])

        client = MagicMock()
        client.get_workflows.return_value = [wf]

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client})

        for edge in edges:
            assert len(edge.evidence) >= 1
            ev = edge.evidence[0]
            assert ev.adapter_id == "live_n8n"
            assert ev.observed_at is not None


# =========================================================================
# LiveDatabricksAdapter Tests
# =========================================================================


class TestLiveDatabricksAdapter:
    """Tests for the Databricks Unity Catalog lineage adapter."""

    def _make_adapter(self, adapter_id: str = "live_databricks"):
        return LiveDatabricksAdapter(adapter_id=adapter_id)

    # ---- Identity & capabilities ----

    def test_id_returns_expected(self):
        adapter = self._make_adapter("db_prod")
        assert adapter.id() == "db_prod"

    def test_default_id(self):
        adapter = self._make_adapter()
        assert adapter.id() == "live_databricks"

    def test_capabilities(self):
        adapter = self._make_adapter()
        caps = adapter.capabilities()
        assert Capability.DISCOVER_ASSETS in caps
        assert Capability.EXTRACT_TABLE_LINEAGE in caps
        assert Capability.EXTRACT_COLUMN_LINEAGE in caps

    def test_is_base_adapter_subclass(self):
        adapter = self._make_adapter()
        assert isinstance(adapter, BaseLineageAdapter)

    def test_case_hint(self):
        adapter = self._make_adapter()
        assert adapter.case_hint == "lower"

    # ---- discover_assets ----

    def test_discover_assets_produces_table_nodes(self):
        """Catalogs → schemas → tables are discovered as TABLE nodes."""
        client = _make_databricks_client(
            catalogs=[{"name": "main", "owner": "admin"}],
            schemas_by_catalog={"main": [{"name": "default"}]},
            tables_by_schema={
                "main.default": [
                    {
                        "name": "orders",
                        "table_type": "MANAGED",
                        "columns": [
                            {"name": "id", "type_text": "INT"},
                            {"name": "amount", "type_text": "DECIMAL(10,2)"},
                        ],
                        "owner": "admin",
                    }
                ]
            },
        )

        adapter = self._make_adapter()
        config = {"client": client, "namespace": "acme-prod"}
        nodes = adapter.discover_assets(config)

        assert len(nodes) == 1
        node = nodes[0]
        assert node.node_type == NodeType.TABLE
        assert node.platform == "databricks"
        assert node.platform_domain == PlatformDomain.WAREHOUSE
        assert node.asset_kind == AssetKind.TABLE
        assert node.database == "main"
        assert node.schema == "default"
        assert node.name == "orders"
        assert node.fqn == "main.default.orders"
        assert node.namespace == "acme-prod"
        assert node.owner == "admin"
        assert len(node.columns) == 2
        assert node.columns[0]["name"] == "id"
        assert node.columns[0]["type"] == "INT"

    def test_discover_assets_view_type(self):
        """VIEW table_type maps to NodeType.VIEW / AssetKind.VIEW."""
        client = _make_databricks_client(
            catalogs=[{"name": "main"}],
            schemas_by_catalog={"main": [{"name": "analytics"}]},
            tables_by_schema={
                "main.analytics": [
                    {"name": "v_summary", "table_type": "VIEW", "columns": []},
                ]
            },
        )

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client})

        assert len(nodes) == 1
        assert nodes[0].node_type == NodeType.VIEW
        assert nodes[0].asset_kind == AssetKind.VIEW

    def test_discover_assets_skips_information_schema(self):
        """information_schema is skipped."""
        client = _make_databricks_client(
            catalogs=[{"name": "main"}],
            schemas_by_catalog={"main": [
                {"name": "default"},
                {"name": "information_schema"},
            ]},
            tables_by_schema={
                "main.default": [{"name": "t1", "table_type": "MANAGED", "columns": []}],
                "main.information_schema": [{"name": "tables", "table_type": "VIEW", "columns": []}],
            },
        )

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client})

        # Only tables from 'default' schema, not information_schema
        assert len(nodes) == 1
        assert nodes[0].schema == "default"

    def test_discover_assets_multiple_catalogs_and_schemas(self):
        """Multiple catalogs each with multiple schemas."""
        client = _make_databricks_client(
            catalogs=[{"name": "prod"}, {"name": "staging"}],
            schemas_by_catalog={
                "prod": [{"name": "public"}],
                "staging": [{"name": "raw"}],
            },
            tables_by_schema={
                "prod.public": [{"name": "users", "table_type": "MANAGED", "columns": []}],
                "staging.raw": [
                    {"name": "events", "table_type": "MANAGED", "columns": []},
                    {"name": "clicks", "table_type": "EXTERNAL", "columns": []},
                ],
            },
        )

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client})

        assert len(nodes) == 3
        fqns = {n.fqn for n in nodes}
        assert "prod.public.users" in fqns
        assert "staging.raw.events" in fqns
        assert "staging.raw.clicks" in fqns

    def test_discover_assets_empty_client_returns_empty(self):
        """No client → empty list."""
        adapter = self._make_adapter()
        nodes = adapter.discover_assets({})
        assert nodes == []

    def test_discover_assets_no_catalogs_returns_empty(self):
        """API returns empty catalogs → empty list."""
        client = _make_databricks_client(catalogs=[])
        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client})
        assert nodes == []

    def test_discover_assets_api_error_returns_empty(self):
        """If the catalogs endpoint raises, return empty list."""
        client = MagicMock()
        client.get.side_effect = Exception("Connection refused")

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client})
        assert nodes == []

    # ---- extract_lineage ----

    def test_extract_lineage_upstream_edges(self):
        """Upstream dependencies produce DEPENDS_ON edges on DATA plane."""
        client = _make_databricks_client(
            catalogs=[{"name": "main"}],
            schemas_by_catalog={"main": [{"name": "default"}]},
            tables_by_schema={
                "main.default": [
                    {
                        "name": "orders",
                        "table_type": "MANAGED",
                        "columns": [],
                    }
                ]
            },
            table_lineage_by_name={
                "main.default.orders": {
                    "upstreams": [
                        {
                            "table_info": {
                                "name": "raw_orders",
                                "catalog_name": "main",
                                "schema_name": "staging",
                            }
                        }
                    ],
                    "downstreams": [],
                }
            },
        )

        adapter = self._make_adapter()
        config = {"client": client, "namespace": "acme"}
        edges = adapter.extract_lineage(config)

        # Should have at least one DEPENDS_ON edge
        dep_edges = [e for e in edges if e.edge_type == EdgeType.DEPENDS_ON]
        assert len(dep_edges) >= 1

        edge = dep_edges[0]
        assert edge.lineage_level == LineageLevel.TABLE
        assert edge.plane == LinePlane.DATA
        assert edge.confidence == 0.95
        assert len(edge.evidence) >= 1
        assert edge.evidence[0].adapter_id == "live_databricks"

    def test_extract_lineage_downstream_edges(self):
        """Downstream dependents also produce DEPENDS_ON edges."""
        client = _make_databricks_client(
            catalogs=[{"name": "main"}],
            schemas_by_catalog={"main": [{"name": "default"}]},
            tables_by_schema={
                "main.default": [
                    {"name": "raw_orders", "table_type": "MANAGED", "columns": []}
                ]
            },
            table_lineage_by_name={
                "main.default.raw_orders": {
                    "upstreams": [],
                    "downstreams": [
                        {
                            "table_info": {
                                "name": "orders",
                                "catalog_name": "main",
                                "schema_name": "default",
                            }
                        }
                    ],
                }
            },
        )

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client, "namespace": "acme"})

        dep_edges = [e for e in edges if e.edge_type == EdgeType.DEPENDS_ON]
        assert len(dep_edges) >= 1
        # Source should be raw_orders, target should be orders
        edge = dep_edges[0]
        assert edge.plane == LinePlane.DATA

    def test_extract_lineage_column_level(self):
        """Column-level lineage creates COLUMN level edges with mappings."""
        client = _make_databricks_client(
            catalogs=[{"name": "main"}],
            schemas_by_catalog={"main": [{"name": "default"}]},
            tables_by_schema={
                "main.default": [
                    {
                        "name": "orders",
                        "table_type": "MANAGED",
                        "columns": [{"name": "id", "type_text": "INT"}],
                    }
                ]
            },
            table_lineage_by_name={
                "main.default.orders": {"upstreams": [], "downstreams": []},
            },
            column_lineage_by_key={
                "main.default.orders|id": {
                    "upstream_cols": [
                        {
                            "table_name": "main.staging.raw_orders",
                            "name": "order_id",
                        }
                    ]
                }
            },
        )

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client, "namespace": "acme"})

        col_edges = [e for e in edges if e.lineage_level == LineageLevel.COLUMN]
        assert len(col_edges) == 1
        edge = col_edges[0]
        assert edge.edge_type == EdgeType.DEPENDS_ON
        assert edge.plane == LinePlane.DATA
        assert edge.confidence == 0.9
        assert len(edge.column_mappings) == 1
        assert edge.column_mappings[0].from_column == "order_id"
        assert edge.column_mappings[0].to_column == "id"

    def test_extract_lineage_no_lineage_data(self):
        """Tables with no lineage info produce no edges."""
        client = _make_databricks_client(
            catalogs=[{"name": "main"}],
            schemas_by_catalog={"main": [{"name": "default"}]},
            tables_by_schema={
                "main.default": [
                    {"name": "isolated", "table_type": "MANAGED", "columns": []}
                ]
            },
            table_lineage_by_name={
                "main.default.isolated": {"upstreams": [], "downstreams": []},
            },
        )

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client})
        assert edges == []

    def test_extract_lineage_empty_client_returns_empty(self):
        """No client → empty edge list."""
        adapter = self._make_adapter()
        edges = adapter.extract_lineage({})
        assert edges == []

    def test_extract_lineage_deduplicates_edges(self):
        """Same upstream referenced multiple times should not duplicate edges."""
        client = _make_databricks_client(
            catalogs=[{"name": "main"}],
            schemas_by_catalog={"main": [{"name": "default"}]},
            tables_by_schema={
                "main.default": [
                    {"name": "orders", "table_type": "MANAGED", "columns": []},
                    {"name": "raw_orders", "table_type": "MANAGED", "columns": []},
                ]
            },
            table_lineage_by_name={
                # orders depends on raw_orders (upstream direction)
                "main.default.orders": {
                    "upstreams": [
                        {"table_info": {"name": "raw_orders", "catalog_name": "main", "schema_name": "default"}}
                    ],
                    "downstreams": [],
                },
                # raw_orders shows orders as downstream
                "main.default.raw_orders": {
                    "upstreams": [],
                    "downstreams": [
                        {"table_info": {"name": "orders", "catalog_name": "main", "schema_name": "default"}}
                    ],
                },
            },
        )

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"client": client, "namespace": "acme"})

        # raw_orders → orders should appear only once despite bidirectional discovery
        table_edges = [e for e in edges if e.lineage_level == LineageLevel.TABLE]
        edge_pairs = [(e.source_id, e.target_id) for e in table_edges]
        assert len(edge_pairs) == len(set(edge_pairs)), "Duplicate edges found"


# =========================================================================
# LiveStorageAdapter Tests
# =========================================================================


class TestLiveStorageAdapter:
    """Tests for the cloud storage lineage adapter."""

    def _make_adapter(self, adapter_id: str = "live_storage"):
        return LiveStorageAdapter(adapter_id=adapter_id)

    # ---- Identity & capabilities ----

    def test_id_returns_expected(self):
        adapter = self._make_adapter("storage_s3")
        assert adapter.id() == "storage_s3"

    def test_default_id(self):
        adapter = self._make_adapter()
        assert adapter.id() == "live_storage"

    def test_capabilities(self):
        adapter = self._make_adapter()
        caps = adapter.capabilities()
        assert Capability.DISCOVER_ASSETS in caps
        assert Capability.EXTRACT_TABLE_LINEAGE in caps

    def test_is_base_adapter_subclass(self):
        adapter = self._make_adapter()
        assert isinstance(adapter, BaseLineageAdapter)

    def test_case_hint(self):
        adapter = self._make_adapter()
        assert adapter.case_hint == "lower"

    # ---- discover_assets ----

    def test_discover_assets_source_nodes_with_file_kind(self):
        """Buckets become SOURCE nodes with asset_kind=FILE."""
        client = MagicMock()
        client.list_buckets.return_value = ["data-lake", "raw-events"]

        adapter = self._make_adapter()
        config = {
            "client": client,
            "provider": "s3",
            "namespace": "my-account",
        }
        nodes = adapter.discover_assets(config)

        assert len(nodes) == 2
        for node in nodes:
            assert node.node_type == NodeType.SOURCE
            assert node.asset_kind == AssetKind.FILE
            assert node.platform_domain == PlatformDomain.INGESTION

        names = {n.name for n in nodes}
        assert "data-lake" in names
        assert "raw-events" in names

    def test_discover_assets_platform_mapping_s3(self):
        """Provider 's3' maps to platform 'aws_s3'."""
        client = MagicMock()
        client.list_buckets.return_value = ["bucket1"]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client, "provider": "s3"})

        assert nodes[0].platform == "aws_s3"

    def test_discover_assets_platform_mapping_gcs(self):
        """Provider 'gcs' maps to platform 'gcp_gcs'."""
        client = MagicMock()
        client.list_buckets.return_value = ["bucket1"]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client, "provider": "gcs"})

        assert nodes[0].platform == "gcp_gcs"

    def test_discover_assets_platform_mapping_adls(self):
        """Provider 'adls' maps to platform 'azure_adls'."""
        client = MagicMock()
        client.list_buckets.return_value = ["container1"]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client, "provider": "adls"})

        assert nodes[0].platform == "azure_adls"

    def test_discover_assets_platform_mapping_azure_alias(self):
        """Provider 'azure' also maps to platform 'azure_adls'."""
        client = MagicMock()
        client.list_buckets.return_value = ["c1"]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client, "provider": "azure"})

        assert nodes[0].platform == "azure_adls"

    def test_discover_assets_buckets_as_dicts(self):
        """Buckets can also be returned as dicts with 'name' key."""
        client = MagicMock()
        client.list_buckets.return_value = [
            {"name": "dict-bucket-a"},
            {"name": "dict-bucket-b"},
        ]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client, "provider": "s3"})

        assert len(nodes) == 2
        names = {n.name for n in nodes}
        assert "dict-bucket-a" in names
        assert "dict-bucket-b" in names

    def test_discover_assets_fqn_format(self):
        """FQN follows pattern: platform.namespace.bucket_name."""
        client = MagicMock()
        client.list_buckets.return_value = ["my-bucket"]

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({
            "client": client, "provider": "gcs", "namespace": "proj-123"
        })

        assert nodes[0].fqn == "gcp_gcs.proj-123.my-bucket"

    def test_discover_assets_empty_client_returns_empty(self):
        """No client → empty list."""
        adapter = self._make_adapter()
        nodes = adapter.discover_assets({})
        assert nodes == []

    def test_discover_assets_list_buckets_error_returns_empty(self):
        """Exception from list_buckets → empty list (handled gracefully)."""
        client = MagicMock()
        client.list_buckets.side_effect = Exception("Permission denied")

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"client": client, "provider": "s3"})
        assert nodes == []

    # ---- extract_lineage ----

    def test_extract_lineage_with_known_mappings(self):
        """Known mappings produce POPULATES edges on CROSS plane."""
        adapter = self._make_adapter()
        config = {
            "provider": "s3",
            "namespace": "my-account",
            "known_mappings": [
                {
                    "prefix": "raw/events/",
                    "table_fqn": "analytics.public.events",
                    "bucket": "data-lake",
                }
            ],
        }
        edges = adapter.extract_lineage(config)

        assert len(edges) == 1
        edge = edges[0]
        assert edge.edge_type == EdgeType.POPULATES
        assert edge.lineage_level == LineageLevel.TABLE
        assert edge.plane == LinePlane.CROSS
        assert edge.confidence == 0.9
        assert len(edge.evidence) >= 1

    def test_extract_lineage_no_known_mappings_returns_empty(self):
        """Without known_mappings, no edges are produced."""
        adapter = self._make_adapter()
        edges = adapter.extract_lineage({"provider": "s3", "namespace": "ns"})
        assert edges == []

    def test_extract_lineage_empty_known_mappings_returns_empty(self):
        """Empty known_mappings list → no edges."""
        adapter = self._make_adapter()
        edges = adapter.extract_lineage({
            "provider": "s3", "namespace": "ns", "known_mappings": [],
        })
        assert edges == []

    def test_extract_lineage_multiple_mappings(self):
        """Multiple mappings produce multiple POPULATES edges."""
        adapter = self._make_adapter()
        config = {
            "provider": "gcs",
            "namespace": "proj",
            "known_mappings": [
                {"prefix": "raw/users/", "table_fqn": "db.public.users", "bucket": "data"},
                {"prefix": "raw/orders/", "table_fqn": "db.public.orders", "bucket": "data"},
            ],
        }
        edges = adapter.extract_lineage(config)

        assert len(edges) == 2
        for edge in edges:
            assert edge.edge_type == EdgeType.POPULATES
            assert edge.plane == LinePlane.CROSS

    def test_extract_lineage_skips_incomplete_mapping(self):
        """Mappings missing prefix or table_fqn are skipped."""
        adapter = self._make_adapter()
        config = {
            "provider": "s3",
            "namespace": "ns",
            "known_mappings": [
                {"prefix": "raw/", "table_fqn": ""},
                {"prefix": "", "table_fqn": "db.public.t"},
                {"prefix": "good/", "table_fqn": "db.public.good", "bucket": "b"},
            ],
        }
        edges = adapter.extract_lineage(config)

        # Only the last mapping has both prefix and table_fqn
        assert len(edges) == 1

    def test_extract_lineage_evidence_has_adapter_id(self):
        """Evidence on storage edges carries the correct adapter_id."""
        adapter = self._make_adapter("my_s3_adapter")
        config = {
            "provider": "s3",
            "namespace": "ns",
            "known_mappings": [
                {"prefix": "p/", "table_fqn": "db.s.t", "bucket": "b"},
            ],
        }
        edges = adapter.extract_lineage(config)
        assert edges[0].evidence[0].adapter_id == "my_s3_adapter"


# =========================================================================
# LiveElementaryAdapter Tests
# =========================================================================


class TestLiveElementaryAdapter:
    """Tests for the Elementary data quality adapter."""

    def _make_adapter(self, adapter_id: str = "live_elementary"):
        return LiveElementaryAdapter(adapter_id=adapter_id)

    def _make_warehouse_mock(self, test_suites=None, test_results=None, health_rows=None):
        """
        Create a mock warehouse adapter with execute_query that returns
        different results depending on the SQL.
        """
        test_suites = test_suites or []
        test_results = test_results or []
        health_rows = health_rows or []

        def _execute_query(sql):
            sql_lower = sql.strip().lower()
            if "select distinct" in sql_lower and "test_unique_id" in sql_lower:
                # Could be either the suites query or the results query
                if "schema_name" in sql_lower:
                    return test_results
                return test_suites
            if "count(*)" in sql_lower:
                return health_rows
            return []

        mock = MagicMock()
        mock.execute_query = MagicMock(side_effect=_execute_query)
        return mock

    # ---- Identity & capabilities ----

    def test_id_returns_expected(self):
        adapter = self._make_adapter("elem_prod")
        assert adapter.id() == "elem_prod"

    def test_default_id(self):
        adapter = self._make_adapter()
        assert adapter.id() == "live_elementary"

    def test_capabilities(self):
        adapter = self._make_adapter()
        caps = adapter.capabilities()
        assert Capability.DISCOVER_ASSETS in caps
        assert Capability.EXTRACT_TABLE_LINEAGE in caps

    def test_is_base_adapter_subclass(self):
        adapter = self._make_adapter()
        assert isinstance(adapter, BaseLineageAdapter)

    def test_case_hint(self):
        adapter = self._make_adapter()
        assert adapter.case_hint == "lower"

    # ---- discover_assets ----

    def test_discover_assets_monitor_nodes(self):
        """Test suites become MONITOR nodes with platform='elementary'."""
        wh_mock = self._make_warehouse_mock(
            test_suites=[
                {
                    "test_unique_id": "test_not_null_orders_id",
                    "test_name": "not_null",
                    "test_type": "generic",
                    "table_name": "orders",
                },
                {
                    "test_unique_id": "test_unique_users_email",
                    "test_name": "unique",
                    "test_type": "generic",
                    "table_name": "users",
                },
            ]
        )

        adapter = self._make_adapter()
        config = {
            "namespace": "analytics",
            "elementary_config": {
                "warehouse_adapter": wh_mock,
                "schema": "elementary",
            },
        }
        nodes = adapter.discover_assets(config)

        assert len(nodes) == 2
        for node in nodes:
            assert node.node_type == NodeType.MONITOR
            assert node.platform == "elementary"
            assert node.platform_domain == PlatformDomain.CATALOG
            assert node.asset_kind == AssetKind.MONITOR
            assert node.namespace == "analytics"

        names = {n.name for n in nodes}
        assert "test_not_null_orders_id" in names
        assert "test_unique_users_email" in names

    def test_discover_assets_fqn_format(self):
        """FQN follows: elementary.{namespace}.{test_unique_id}."""
        wh_mock = self._make_warehouse_mock(
            test_suites=[
                {"test_unique_id": "t1", "test_name": "t1", "test_type": "generic", "table_name": "x"},
            ]
        )

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({
            "namespace": "prod",
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert nodes[0].fqn == "elementary.prod.t1"

    def test_discover_assets_empty_client_returns_empty(self):
        """No warehouse_adapter → empty list."""
        adapter = self._make_adapter()
        nodes = adapter.discover_assets({})
        assert nodes == []

    def test_discover_assets_no_elementary_config_returns_empty(self):
        """Missing elementary_config → empty list."""
        adapter = self._make_adapter()
        nodes = adapter.discover_assets({"namespace": "ns"})
        assert nodes == []

    def test_discover_assets_query_error_returns_empty(self):
        """If execute_query raises, return empty list."""
        wh_mock = MagicMock()
        wh_mock.execute_query.side_effect = Exception("Table not found")

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })
        assert nodes == []

    def test_discover_assets_raw_metadata(self):
        """Monitor nodes carry test_type and table_name in raw_metadata."""
        wh_mock = self._make_warehouse_mock(
            test_suites=[
                {"test_unique_id": "t1", "test_name": "not_null", "test_type": "generic", "table_name": "orders"},
            ]
        )

        adapter = self._make_adapter()
        nodes = adapter.discover_assets({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        meta = nodes[0].raw_metadata
        assert meta["test_type"] == "generic"
        assert meta["table_name"] == "orders"

    # ---- extract_lineage ----

    def test_extract_lineage_monitors_edges(self):
        """Test results produce MONITORS edges on DATA plane."""
        wh_mock = self._make_warehouse_mock(
            test_results=[
                {
                    "test_unique_id": "test_not_null_orders_id",
                    "test_name": "not_null",
                    "table_name": "orders",
                    "schema_name": "public",
                    "database_name": "analytics",
                },
            ]
        )

        adapter = self._make_adapter()
        config = {
            "namespace": "prod",
            "elementary_config": {
                "warehouse_adapter": wh_mock,
                "schema": "elementary",
            },
        }
        edges = adapter.extract_lineage(config)

        assert len(edges) == 1
        edge = edges[0]
        assert edge.edge_type == EdgeType.MONITORS
        assert edge.lineage_level == LineageLevel.TABLE
        assert edge.plane == LinePlane.DATA
        assert edge.confidence == 1.0
        assert len(edge.evidence) >= 1
        assert edge.evidence[0].adapter_id == "live_elementary"

    def test_extract_lineage_deduplicates_test_table_pairs(self):
        """Same test-table pair appearing multiple times should only produce one edge."""
        wh_mock = self._make_warehouse_mock(
            test_results=[
                {
                    "test_unique_id": "t1",
                    "test_name": "not_null",
                    "table_name": "orders",
                    "schema_name": "public",
                    "database_name": "db",
                },
                {
                    "test_unique_id": "t1",
                    "test_name": "not_null",
                    "table_name": "orders",
                    "schema_name": "public",
                    "database_name": "db",
                },
            ]
        )

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({
            "namespace": "ns",
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert len(edges) == 1

    def test_extract_lineage_empty_client_returns_empty(self):
        """No client → empty list."""
        adapter = self._make_adapter()
        edges = adapter.extract_lineage({})
        assert edges == []

    def test_extract_lineage_query_error_returns_empty(self):
        """If test results query fails, return empty list."""
        wh_mock = MagicMock()
        wh_mock.execute_query.side_effect = Exception("Query failed")

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })
        assert edges == []

    def test_extract_lineage_multiple_tests_multiple_tables(self):
        """Multiple tests on different tables produce one edge each."""
        wh_mock = self._make_warehouse_mock(
            test_results=[
                {
                    "test_unique_id": "test_not_null_orders_id",
                    "test_name": "not_null",
                    "table_name": "orders",
                    "schema_name": "public",
                    "database_name": "db",
                },
                {
                    "test_unique_id": "test_unique_users_email",
                    "test_name": "unique",
                    "table_name": "users",
                    "schema_name": "public",
                    "database_name": "db",
                },
            ]
        )

        adapter = self._make_adapter()
        edges = adapter.extract_lineage({
            "namespace": "ns",
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert len(edges) == 2
        for edge in edges:
            assert edge.edge_type == EdgeType.MONITORS

    # ---- get_health_enrichment ----

    def test_get_health_enrichment_failing(self):
        """Tables with failed_tests > 0 get FAILING status."""
        wh_mock = self._make_warehouse_mock(
            health_rows=[
                {
                    "table_name": "orders",
                    "schema_name": "public",
                    "database_name": "analytics",
                    "total_tests": 5,
                    "failed_tests": 2,
                    "warn_tests": 0,
                },
            ]
        )

        adapter = self._make_adapter()
        result = adapter.get_health_enrichment({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert "analytics.public.orders" in result
        entry = result["analytics.public.orders"]
        assert entry["health_status"] == HealthStatus.FAILING
        assert entry["failed_tests"] == 2
        assert entry["total_tests"] == 5

    def test_get_health_enrichment_degraded(self):
        """Tables with warn_tests > 0 and no failures get DEGRADED."""
        wh_mock = self._make_warehouse_mock(
            health_rows=[
                {
                    "table_name": "users",
                    "schema_name": "public",
                    "database_name": "db",
                    "total_tests": 3,
                    "failed_tests": 0,
                    "warn_tests": 1,
                },
            ]
        )

        adapter = self._make_adapter()
        result = adapter.get_health_enrichment({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert "db.public.users" in result
        assert result["db.public.users"]["health_status"] == HealthStatus.DEGRADED

    def test_get_health_enrichment_healthy(self):
        """Tables with tests and no failures/warnings get HEALTHY."""
        wh_mock = self._make_warehouse_mock(
            health_rows=[
                {
                    "table_name": "products",
                    "schema_name": "public",
                    "database_name": "db",
                    "total_tests": 10,
                    "failed_tests": 0,
                    "warn_tests": 0,
                },
            ]
        )

        adapter = self._make_adapter()
        result = adapter.get_health_enrichment({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert result["db.public.products"]["health_status"] == HealthStatus.HEALTHY

    def test_get_health_enrichment_unknown(self):
        """Tables with total_tests=0 get UNKNOWN status."""
        wh_mock = self._make_warehouse_mock(
            health_rows=[
                {
                    "table_name": "empty",
                    "schema_name": "public",
                    "database_name": "db",
                    "total_tests": 0,
                    "failed_tests": 0,
                    "warn_tests": 0,
                },
            ]
        )

        adapter = self._make_adapter()
        result = adapter.get_health_enrichment({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert result["db.public.empty"]["health_status"] == HealthStatus.UNKNOWN

    def test_get_health_enrichment_priority_fail_over_warn(self):
        """When both failed and warned, FAILING takes priority over DEGRADED."""
        wh_mock = self._make_warehouse_mock(
            health_rows=[
                {
                    "table_name": "mixed",
                    "schema_name": "public",
                    "database_name": "db",
                    "total_tests": 10,
                    "failed_tests": 1,
                    "warn_tests": 3,
                },
            ]
        )

        adapter = self._make_adapter()
        result = adapter.get_health_enrichment({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert result["db.public.mixed"]["health_status"] == HealthStatus.FAILING

    def test_get_health_enrichment_empty_client_returns_empty(self):
        """No client → empty dict."""
        adapter = self._make_adapter()
        result = adapter.get_health_enrichment({})
        assert result == {}

    def test_get_health_enrichment_query_error_returns_empty(self):
        """If health query fails, return empty dict."""
        wh_mock = MagicMock()
        wh_mock.execute_query.side_effect = Exception("Timeout")

        adapter = self._make_adapter()
        result = adapter.get_health_enrichment({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })
        assert result == {}

    def test_get_health_enrichment_multiple_tables(self):
        """Multiple tables each get their own health status."""
        wh_mock = self._make_warehouse_mock(
            health_rows=[
                {
                    "table_name": "orders",
                    "schema_name": "public",
                    "database_name": "db",
                    "total_tests": 5,
                    "failed_tests": 1,
                    "warn_tests": 0,
                },
                {
                    "table_name": "users",
                    "schema_name": "public",
                    "database_name": "db",
                    "total_tests": 3,
                    "failed_tests": 0,
                    "warn_tests": 0,
                },
            ]
        )

        adapter = self._make_adapter()
        result = adapter.get_health_enrichment({
            "elementary_config": {"warehouse_adapter": wh_mock},
        })

        assert len(result) == 2
        assert result["db.public.orders"]["health_status"] == HealthStatus.FAILING
        assert result["db.public.users"]["health_status"] == HealthStatus.HEALTHY

    # ---- client resolution ----

    def test_client_resolution_prefers_warehouse_adapter(self):
        """elementary_config.warehouse_adapter is the primary client source."""
        primary_mock = MagicMock()
        primary_mock.execute_query.return_value = []
        fallback_mock = MagicMock()

        adapter = self._make_adapter()
        config = {
            "client": fallback_mock,
            "elementary_config": {
                "warehouse_adapter": primary_mock,
            },
        }
        adapter.discover_assets(config)

        # The primary mock should have been called, not the fallback
        primary_mock.execute_query.assert_called()
        fallback_mock.execute_query.assert_not_called()

    def test_client_resolution_falls_back_to_config_client(self):
        """If no warehouse_adapter, fall back to config['client']."""
        fallback_mock = MagicMock()
        fallback_mock.execute_query.return_value = []

        adapter = self._make_adapter()
        config = {
            "client": fallback_mock,
            "elementary_config": {},
        }
        adapter.discover_assets(config)

        fallback_mock.execute_query.assert_called()
