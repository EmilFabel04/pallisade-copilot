"""
Tests for BI lineage adapters: LiveTableauAdapter, LivePowerBIAdapter, LiveMetabaseAdapter.

Each adapter is tested for:
1. capabilities() returns expected set
2. discover_assets with mock client returns correct node types, count, fqn format, metadata
3. extract_lineage with mock client returns correct edge types, planes, confidence levels
4. Empty/None client returns empty lists gracefully
5. id() returns expected adapter ID
"""

import pytest
from unittest.mock import MagicMock, patch

from scanner.lineage.graph import (
    AssetKind,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.adapter import BaseLineageAdapter, Capability
from scanner.lineage.engine.adapters.live_tableau import LiveTableauAdapter
from scanner.lineage.engine.adapters.live_powerbi import LivePowerBIAdapter
from scanner.lineage.engine.adapters.live_metabase import LiveMetabaseAdapter


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def tableau_mock_client():
    """Create a mock Tableau client with realistic workbook and datasource data."""
    client = MagicMock()

    client.get_all_workbooks.return_value = [
        {
            "id": "wb-001",
            "name": "Revenue Dashboard",
            "project": {"name": "Finance"},
            "viewCount": 42,
            "owner": {"name": "alice@acme.com"},
            "datasource_ids": ["ds-001", "ds-002"],
        },
        {
            "id": "wb-002",
            "name": "Marketing Overview",
            "project": {"name": "Marketing"},
            "viewCount": 17,
            "owner": {"name": "bob@acme.com"},
            "datasource_ids": ["ds-002"],
        },
    ]

    client.get_all_datasources.return_value = [
        {
            "id": "ds-001",
            "name": "Warehouse Revenue",
            "contentType": "bigquery",
            "serverName": "bq-prod.acme.com",
            "databaseName": "analytics.public.revenue",
            "hasExtracts": False,
            "project": {"name": "Finance"},
        },
        {
            "id": "ds-002",
            "name": "Marketing Spend",
            "contentType": "snowflake",
            "serverName": "sf-prod.acme.com",
            "databaseName": "marketing_db.public.spend",
            "hasExtracts": True,
            "project": {"name": "Marketing"},
        },
    ]

    return client


@pytest.fixture
def powerbi_mock_client():
    """Create a mock Power BI client with realistic report and dataset data."""
    client = MagicMock()

    client.get_reports_in_workspace.return_value = [
        {
            "id": "rpt-001",
            "name": "Sales Summary",
            "datasetId": "ds-100",
            "workspaceName": "Sales Workspace",
        },
        {
            "id": "rpt-002",
            "name": "Inventory Report",
            "datasetId": "ds-200",
            "workspaceName": "Ops Workspace",
        },
    ]

    client.get_datasets_in_workspace.return_value = [
        {
            "id": "ds-100",
            "name": "Sales Dataset",
            "targetStorageMode": "Import",
            "configuredBy": "alice@acme.com",
        },
        {
            "id": "ds-200",
            "name": "Inventory Dataset",
            "targetStorageMode": "DirectQuery",
            "configuredBy": "bob@acme.com",
        },
    ]

    # ds-100 has a datasource with a 3-part path
    # ds-200 has a datasource with a 2-part path
    def mock_get_dataset_datasources(workspace_id, dataset_id):
        if dataset_id == "ds-100":
            return [
                {
                    "connectionDetails": {
                        "server": "sql-server.acme.com",
                        "database": "sales_db",
                        "path": "sales_db.dbo.fact_sales",
                    }
                },
            ]
        elif dataset_id == "ds-200":
            return [
                {
                    "connectionDetails": {
                        "server": "pg-prod.acme.com",
                        "database": "inventory_db",
                        "path": "public.dim_products",
                    }
                },
            ]
        return []

    client.get_dataset_datasources.side_effect = mock_get_dataset_datasources
    return client


@pytest.fixture
def metabase_mock_client():
    """Create a mock Metabase client with dashboards, cards, and varied query types."""
    client = MagicMock()

    client.get_dashboards.return_value = [
        {
            "id": 1,
            "name": "KPI Dashboard",
            "collection": {"name": "Analytics"},
            "card_count": 3,
        },
        {
            "id": 2,
            "name": "User Funnel",
            "collection": {"name": "Growth"},
            "card_count": 1,
        },
    ]

    client.get_cards.return_value = [
        {
            "id": 10,
            "name": "Revenue by Month",
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": "SELECT month, sum(amount) FROM analytics.public.orders GROUP BY month",
                },
            },
            "database_id": 1,
            "display": "bar",
        },
        {
            "id": 20,
            "name": "Active Users",
            "dataset_query": {
                "type": "query",
                "query": {
                    "source-table": 42,
                },
            },
            "database_id": 1,
            "display": "scalar",
        },
        {
            "id": 30,
            "name": "Signup Trend",
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": "SELECT date, count(*) FROM signups JOIN users ON signups.user_id = users.id GROUP BY date",
                },
            },
            "database_id": 1,
            "display": "line",
        },
    ]

    def mock_get_dashboard(dash_id):
        if dash_id == 1:
            return {
                "id": 1,
                "name": "KPI Dashboard",
                "ordered_cards": [
                    {"card": {"id": 10}},
                    {"card": {"id": 20}},
                    {"card": {"id": 30}},
                ],
            }
        elif dash_id == 2:
            return {
                "id": 2,
                "name": "User Funnel",
                "ordered_cards": [
                    {"card": {"id": 20}},
                ],
            }
        return {"ordered_cards": []}

    client.get_dashboard.side_effect = mock_get_dashboard
    return client


# ======================================================================
# LiveTableauAdapter Tests
# ======================================================================


class TestLiveTableauAdapter:
    """Tests for the LiveTableauAdapter."""

    def setup_method(self):
        self.adapter = LiveTableauAdapter()

    # ---- Identity ----

    def test_id_default(self):
        assert self.adapter.id() == "live_tableau"

    def test_id_custom(self):
        adapter = LiveTableauAdapter(adapter_id="my_tableau")
        assert adapter.id() == "my_tableau"

    # ---- Capabilities ----

    def test_capabilities(self):
        caps = self.adapter.capabilities()
        assert caps == {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.GET_BI_EXPOSURES,
        }

    def test_is_base_adapter(self):
        assert isinstance(self.adapter, BaseLineageAdapter)

    def test_case_hint(self):
        assert self.adapter.case_hint == "lower"

    # ---- discover_assets ----

    def test_discover_assets_returns_correct_count(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        # 2 workbooks + 2 datasources = 4
        assert len(nodes) == 4

    def test_discover_assets_workbook_nodes(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        workbook_nodes = [n for n in nodes if n.node_type == NodeType.WORKBOOK]

        assert len(workbook_nodes) == 2

        wb1 = workbook_nodes[0]
        assert wb1.name == "Revenue Dashboard"
        assert wb1.platform == "tableau"
        assert wb1.platform_domain == PlatformDomain.BI
        assert wb1.asset_kind == AssetKind.WORKBOOK
        assert wb1.namespace == "acme"
        assert wb1.fqn == "tableau.acme.workbook.wb-001"
        assert wb1.owner == "alice@acme.com"
        assert "live_tableau" in wb1.sources
        assert wb1.raw_metadata["project_name"] == "Finance"
        assert wb1.raw_metadata["view_count"] == 42
        assert wb1.raw_metadata["datasource_ids"] == ["ds-001", "ds-002"]

    def test_discover_assets_datasource_nodes(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        ds_nodes = [n for n in nodes if n.node_type == NodeType.DATASET]

        assert len(ds_nodes) == 2

        ds1 = ds_nodes[0]
        assert ds1.name == "Warehouse Revenue"
        assert ds1.platform == "tableau"
        assert ds1.platform_domain == PlatformDomain.BI
        assert ds1.asset_kind == AssetKind.DATASET
        assert ds1.fqn == "tableau.acme.datasource.ds-001"
        assert ds1.raw_metadata["connection_type"] == "bigquery"
        assert ds1.raw_metadata["server_name"] == "bq-prod.acme.com"
        assert ds1.raw_metadata["database_name"] == "analytics.public.revenue"
        assert ds1.raw_metadata["has_extracts"] is False

    def test_discover_assets_datasource_extracts(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        ds_nodes = [n for n in nodes if n.node_type == NodeType.DATASET]

        ds2 = ds_nodes[1]
        assert ds2.raw_metadata["has_extracts"] is True

    def test_discover_assets_integration_id(self, tableau_mock_client):
        config = {
            "client": tableau_mock_client,
            "namespace": "acme",
            "integration_id": "int-123",
        }
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.integration_id == "int-123"

    def test_discover_assets_default_namespace(self, tableau_mock_client):
        config = {"client": tableau_mock_client}
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.namespace == "tableau"

    def test_discover_assets_observed_at_set(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.observed_at is not None

    # ---- extract_lineage ----

    def test_extract_lineage_returns_edges(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        # wb-001 has 2 datasource_ids => 2 TOOL edges
        # wb-002 has 1 datasource_id => 1 TOOL edge
        # ds-001 has databaseName => 1 CROSS edge
        # ds-002 has databaseName => 1 CROSS edge
        # Total: 3 TOOL + 2 CROSS = 5
        assert len(edges) == 5

    def test_extract_lineage_tool_edges(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]

        assert len(tool_edges) == 3
        for edge in tool_edges:
            assert edge.edge_type == EdgeType.READS_FROM
            assert edge.plane == LinePlane.DATA
            assert edge.confidence == 1.0
            assert len(edge.evidence) == 1
            assert edge.evidence[0].adapter_id == "live_tableau"

    def test_extract_lineage_table_cross_edges(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]

        assert len(cross_edges) == 2
        for edge in cross_edges:
            assert edge.edge_type == EdgeType.READS_FROM
            assert edge.lineage_level == LineageLevel.TABLE
            assert edge.confidence == 0.8

    def test_extract_lineage_source_refs(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]

        source_refs = {e.discovered_from for e in tool_edges}
        assert "tableau:workbook:wb-001:reads_datasource:ds-001" in source_refs
        assert "tableau:workbook:wb-001:reads_datasource:ds-002" in source_refs
        assert "tableau:workbook:wb-002:reads_datasource:ds-002" in source_refs

    def test_extract_lineage_edge_ids_unique(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        edge_ids = [e.id for e in edges]
        assert len(edge_ids) == len(set(edge_ids)), "Edge IDs must be unique"

    def test_extract_lineage_evidence_observed_at(self, tableau_mock_client):
        config = {"client": tableau_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        for edge in edges:
            assert edge.discovered_at is not None
            for ev in edge.evidence:
                assert ev.observed_at is not None

    # ---- Graceful empty/None ----

    def test_discover_assets_none_client(self):
        config = {"client": None}
        nodes = self.adapter.discover_assets(config)
        assert nodes == []

    def test_discover_assets_no_client_key(self):
        config = {}
        nodes = self.adapter.discover_assets(config)
        assert nodes == []

    def test_extract_lineage_none_client(self):
        config = {"client": None}
        edges = self.adapter.extract_lineage(config)
        assert edges == []

    def test_extract_lineage_no_client_key(self):
        config = {}
        edges = self.adapter.extract_lineage(config)
        assert edges == []

    # ---- Exception handling ----

    def test_discover_assets_workbook_api_error(self):
        client = MagicMock()
        client.get_all_workbooks.side_effect = RuntimeError("API timeout")
        client.get_all_datasources.return_value = []
        config = {"client": client, "namespace": "acme"}
        # Should not raise; returns datasources only
        nodes = self.adapter.discover_assets(config)
        assert isinstance(nodes, list)

    def test_discover_assets_datasource_api_error(self):
        client = MagicMock()
        client.get_all_workbooks.return_value = []
        client.get_all_datasources.side_effect = RuntimeError("API timeout")
        config = {"client": client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        assert isinstance(nodes, list)

    def test_extract_lineage_api_error_workbooks(self):
        client = MagicMock()
        client.get_all_workbooks.side_effect = RuntimeError("fail")
        client.get_all_datasources.return_value = []
        config = {"client": client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        assert isinstance(edges, list)

    # ---- Workbook with no datasource_ids falls back to API ----

    def test_extract_lineage_falls_back_to_connections_api(self):
        client = MagicMock()
        # Workbook has no datasource_ids in its data
        client.get_all_workbooks.return_value = [
            {
                "id": "wb-010",
                "name": "Bare Workbook",
                "project": {"name": "Test"},
                "viewCount": 0,
                "owner": {"name": "test@test.com"},
                # No datasource_ids key
            },
        ]
        client.get_workbook_connections.return_value = [
            {"datasource": {"id": "ds-abc"}},
        ]
        client.get_all_datasources.return_value = []
        config = {"client": client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        # Should have one TOOL edge from the connections fallback
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        assert len(tool_edges) == 1


# ======================================================================
# LivePowerBIAdapter Tests
# ======================================================================


class TestLivePowerBIAdapter:
    """Tests for the LivePowerBIAdapter."""

    def setup_method(self):
        self.adapter = LivePowerBIAdapter()

    # ---- Identity ----

    def test_id_default(self):
        assert self.adapter.id() == "live_powerbi"

    def test_id_custom(self):
        adapter = LivePowerBIAdapter(adapter_id="custom_pbi")
        assert adapter.id() == "custom_pbi"

    # ---- Capabilities ----

    def test_capabilities(self):
        caps = self.adapter.capabilities()
        assert caps == {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.GET_BI_EXPOSURES,
        }

    def test_is_base_adapter(self):
        assert isinstance(self.adapter, BaseLineageAdapter)

    def test_case_hint(self):
        assert self.adapter.case_hint == "lower"

    # ---- discover_assets ----

    def test_discover_assets_returns_correct_count(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        # 2 reports + 2 datasets = 4
        assert len(nodes) == 4

    def test_discover_assets_report_nodes(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        report_nodes = [n for n in nodes if n.node_type == NodeType.REPORT]

        assert len(report_nodes) == 2

        rpt1 = report_nodes[0]
        assert rpt1.name == "Sales Summary"
        assert rpt1.platform == "powerbi"
        assert rpt1.platform_domain == PlatformDomain.BI
        assert rpt1.asset_kind == AssetKind.REPORT
        assert rpt1.namespace == "acme"
        assert rpt1.fqn == "powerbi.acme.report.rpt-001"
        assert rpt1.raw_metadata["workspace_name"] == "Sales Workspace"
        assert rpt1.raw_metadata["dataset_id"] == "ds-100"

    def test_discover_assets_dataset_nodes(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        dataset_nodes = [n for n in nodes if n.node_type == NodeType.DATASET]

        assert len(dataset_nodes) == 2

        ds1 = dataset_nodes[0]
        assert ds1.name == "Sales Dataset"
        assert ds1.platform == "powerbi"
        assert ds1.platform_domain == PlatformDomain.BI
        assert ds1.asset_kind == AssetKind.DATASET
        assert ds1.fqn == "powerbi.acme.dataset.ds-100"
        assert ds1.owner == "alice@acme.com"
        assert ds1.raw_metadata["storage_mode"] == "Import"
        assert ds1.raw_metadata["configured_by"] == "alice@acme.com"

    def test_discover_assets_integration_id(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "integration_id": "pbi-int-1",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.integration_id == "pbi-int-1"

    def test_discover_assets_default_namespace(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.namespace == "powerbi"

    def test_discover_assets_observed_at_set(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.observed_at is not None

    def test_discover_assets_sources_list(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert "live_powerbi" in node.sources

    # ---- extract_lineage ----

    def test_extract_lineage_returns_edges(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        edges = self.adapter.extract_lineage(config)
        # 2 report->dataset edges (TOOL)
        # ds-100 has 1 datasource with 3-part path => 1 TABLE edge
        # ds-200 has 1 datasource with 2-part path => 1 TABLE edge
        # Total: 2 + 2 = 4
        assert len(edges) == 4

    def test_extract_lineage_tool_edges(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        edges = self.adapter.extract_lineage(config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]

        assert len(tool_edges) == 2
        for edge in tool_edges:
            assert edge.edge_type == EdgeType.READS_FROM
            assert edge.plane == LinePlane.DATA
            assert edge.confidence == 1.0
            assert len(edge.evidence) == 1
            assert edge.evidence[0].adapter_id == "live_powerbi"

    def test_extract_lineage_table_cross_edges(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        edges = self.adapter.extract_lineage(config)
        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]

        assert len(cross_edges) == 2
        for edge in cross_edges:
            assert edge.edge_type == EdgeType.READS_FROM
            assert edge.lineage_level == LineageLevel.TABLE
            assert edge.confidence == 0.7

    def test_extract_lineage_source_refs(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        edges = self.adapter.extract_lineage(config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        source_refs = {e.discovered_from for e in tool_edges}
        assert "powerbi:report:rpt-001:reads_dataset:ds-100" in source_refs
        assert "powerbi:report:rpt-002:reads_dataset:ds-200" in source_refs

    def test_extract_lineage_edge_ids_unique(self, powerbi_mock_client):
        config = {
            "client": powerbi_mock_client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        edges = self.adapter.extract_lineage(config)
        edge_ids = [e.id for e in edges]
        assert len(edge_ids) == len(set(edge_ids)), "Edge IDs must be unique"

    # ---- _parse_table_ref ----

    def test_parse_table_ref_three_part_path(self):
        result = self.adapter._parse_table_ref("server", "db", "mydb.schema1.table1")
        assert result == {"database": "mydb", "schema": "schema1", "table": "table1"}

    def test_parse_table_ref_two_part_path(self):
        result = self.adapter._parse_table_ref("server", "sales_db", "dbo.fact_sales")
        assert result == {"database": "sales_db", "schema": "dbo", "table": "fact_sales"}

    def test_parse_table_ref_one_part_path(self):
        result = self.adapter._parse_table_ref("server", "mydb", "orders")
        assert result == {"database": "mydb", "schema": "", "table": "orders"}

    def test_parse_table_ref_no_path_only_database(self):
        """When there is no path, just a database, no table reference is possible."""
        result = self.adapter._parse_table_ref("server", "mydb", "")
        assert result is None

    def test_parse_table_ref_empty_all(self):
        result = self.adapter._parse_table_ref("", "", "")
        assert result is None

    def test_parse_table_ref_strips_brackets(self):
        result = self.adapter._parse_table_ref("server", "db", "[dbo].[fact_sales]")
        assert result == {"database": "db", "schema": "dbo", "table": "fact_sales"}

    def test_parse_table_ref_strips_backticks(self):
        result = self.adapter._parse_table_ref("server", "db", "`schema`.`table`")
        assert result == {"database": "db", "schema": "schema", "table": "table"}

    def test_parse_table_ref_strips_double_quotes(self):
        result = self.adapter._parse_table_ref("server", "db", '"public"."users"')
        assert result == {"database": "db", "schema": "public", "table": "users"}

    # ---- Graceful empty/None ----

    def test_discover_assets_none_client(self):
        config = {"client": None}
        nodes = self.adapter.discover_assets(config)
        assert nodes == []

    def test_discover_assets_no_client_key(self):
        config = {}
        nodes = self.adapter.discover_assets(config)
        assert nodes == []

    def test_extract_lineage_none_client(self):
        config = {"client": None}
        edges = self.adapter.extract_lineage(config)
        assert edges == []

    def test_extract_lineage_no_client_key(self):
        config = {}
        edges = self.adapter.extract_lineage(config)
        assert edges == []

    # ---- Exception handling ----

    def test_discover_assets_reports_api_error(self):
        client = MagicMock()
        client.get_reports_in_workspace.side_effect = RuntimeError("API error")
        client.get_datasets_in_workspace.return_value = []
        config = {
            "client": client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        assert isinstance(nodes, list)

    def test_discover_assets_datasets_api_error(self):
        client = MagicMock()
        client.get_reports_in_workspace.return_value = []
        client.get_datasets_in_workspace.side_effect = RuntimeError("API error")
        config = {
            "client": client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        nodes = self.adapter.discover_assets(config)
        assert isinstance(nodes, list)

    def test_extract_lineage_datasource_api_error(self):
        """If get_dataset_datasources fails, adapter should skip that dataset."""
        client = MagicMock()
        client.get_reports_in_workspace.return_value = []
        client.get_datasets_in_workspace.return_value = [
            {"id": "ds-fail", "name": "Broken"},
        ]
        client.get_dataset_datasources.side_effect = RuntimeError("Not found")
        config = {
            "client": client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        edges = self.adapter.extract_lineage(config)
        # Only cross edges would come from ds, and that fails, so 0 cross edges
        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]
        assert len(cross_edges) == 0

    # ---- Report without datasetId ----

    def test_extract_lineage_report_missing_dataset_id(self):
        client = MagicMock()
        client.get_reports_in_workspace.return_value = [
            {"id": "rpt-bad", "name": "No Dataset"},
        ]
        client.get_datasets_in_workspace.return_value = []
        config = {
            "client": client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        edges = self.adapter.extract_lineage(config)
        # No dataset linkage, so no TOOL edge produced
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        assert len(tool_edges) == 0

    # ---- Datasource with no connectionDetails ----

    def test_extract_lineage_empty_connection_details(self):
        client = MagicMock()
        client.get_reports_in_workspace.return_value = []
        client.get_datasets_in_workspace.return_value = [
            {"id": "ds-empty", "name": "Empty DS"},
        ]
        client.get_dataset_datasources.return_value = [
            {"connectionDetails": {}},
        ]
        config = {
            "client": client,
            "namespace": "acme",
            "powerbi_config": {"workspace_id": "ws-001"},
        }
        edges = self.adapter.extract_lineage(config)
        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]
        assert len(cross_edges) == 0


# ======================================================================
# LiveMetabaseAdapter Tests
# ======================================================================


class TestLiveMetabaseAdapter:
    """Tests for the LiveMetabaseAdapter."""

    def setup_method(self):
        self.adapter = LiveMetabaseAdapter()

    # ---- Identity ----

    def test_id_default(self):
        assert self.adapter.id() == "live_metabase"

    def test_id_custom(self):
        adapter = LiveMetabaseAdapter(adapter_id="custom_mb")
        assert adapter.id() == "custom_mb"

    # ---- Capabilities ----

    def test_capabilities(self):
        caps = self.adapter.capabilities()
        assert caps == {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.GET_BI_EXPOSURES,
        }

    def test_is_base_adapter(self):
        assert isinstance(self.adapter, BaseLineageAdapter)

    def test_case_hint(self):
        assert self.adapter.case_hint == "lower"

    # ---- discover_assets ----

    def test_discover_assets_returns_correct_count(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        # 2 dashboards + 3 cards = 5
        assert len(nodes) == 5

    def test_discover_assets_dashboard_nodes(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        dash_nodes = [n for n in nodes if n.node_type == NodeType.DASHBOARD]

        assert len(dash_nodes) == 2

        d1 = dash_nodes[0]
        assert d1.name == "KPI Dashboard"
        assert d1.platform == "metabase"
        assert d1.platform_domain == PlatformDomain.BI
        assert d1.asset_kind == AssetKind.DASHBOARD
        assert d1.namespace == "acme"
        assert d1.fqn == "metabase.acme.dashboard.1"
        assert d1.raw_metadata["collection_name"] == "Analytics"
        assert d1.raw_metadata["card_count"] == 3
        assert d1.raw_metadata["dashboard_id"] == 1

    def test_discover_assets_card_nodes(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        card_nodes = [n for n in nodes if n.node_type == NodeType.QUESTION]

        assert len(card_nodes) == 3

        c1 = card_nodes[0]
        assert c1.name == "Revenue by Month"
        assert c1.platform == "metabase"
        assert c1.platform_domain == PlatformDomain.BI
        assert c1.asset_kind == AssetKind.QUESTION
        assert c1.fqn == "metabase.acme.card.10"
        assert c1.raw_metadata["query_type"] == "native"
        assert c1.raw_metadata["database_id"] == 1
        assert c1.raw_metadata["display"] == "bar"

    def test_discover_assets_gui_query_card(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        card_nodes = [n for n in nodes if n.node_type == NodeType.QUESTION]

        gui_card = [c for c in card_nodes if c.name == "Active Users"][0]
        assert gui_card.raw_metadata["query_type"] == "query"

    def test_discover_assets_integration_id(self, metabase_mock_client):
        config = {
            "client": metabase_mock_client,
            "namespace": "acme",
            "integration_id": "mb-int-1",
        }
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.integration_id == "mb-int-1"

    def test_discover_assets_default_namespace(self, metabase_mock_client):
        config = {"client": metabase_mock_client}
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.namespace == "metabase"

    def test_discover_assets_observed_at_set(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert node.observed_at is not None

    def test_discover_assets_sources_list(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        for node in nodes:
            assert "live_metabase" in node.sources

    # ---- extract_lineage ----

    def test_extract_lineage_dashboard_card_edges(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]

        # Dashboard 1 has cards 10, 20, 30 => 3 edges
        # Dashboard 2 has card 20 => 1 edge
        # Total TOOL edges: 4
        assert len(tool_edges) == 4
        for edge in tool_edges:
            assert edge.edge_type == EdgeType.DEPENDS_ON
            assert edge.plane == LinePlane.DATA
            assert edge.confidence == 1.0

    def test_extract_lineage_dashboard_card_source_refs(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        source_refs = {e.discovered_from for e in tool_edges}

        assert "metabase:dashboard:1:contains_card:10" in source_refs
        assert "metabase:dashboard:1:contains_card:20" in source_refs
        assert "metabase:dashboard:1:contains_card:30" in source_refs
        assert "metabase:dashboard:2:contains_card:20" in source_refs

    def test_extract_lineage_native_sql_edges(self, metabase_mock_client):
        """Native SQL queries should produce CROSS edges to parsed table references."""
        config = {"client": metabase_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]

        # Card 10: native query with "analytics.public.orders" => 1 edge
        # Card 20: GUI query with source-table 42 => 1 edge
        # Card 30: native query with "signups" and "users" => 2 edges
        # Total cross edges >= 3 (native) + 1 (GUI) = 4
        assert len(cross_edges) >= 3

        native_edges = [
            e for e in cross_edges
            if "native_query" in (e.discovered_from or "")
        ]
        assert len(native_edges) >= 1

        for edge in native_edges:
            assert edge.edge_type == EdgeType.READS_FROM
            assert edge.lineage_level == LineageLevel.TABLE
            assert edge.confidence == 0.8

    def test_extract_lineage_native_sql_snippet_in_evidence(self, metabase_mock_client):
        """Native query edges should store the SQL snippet in evidence."""
        config = {"client": metabase_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        native_edges = [
            e for e in edges
            if "native_query" in (e.discovered_from or "")
        ]
        for edge in native_edges:
            assert len(edge.evidence) == 1
            ev = edge.evidence[0]
            assert ev.snippet is not None
            assert len(ev.snippet) <= 200

    def test_extract_lineage_gui_query_edge(self, metabase_mock_client):
        """GUI queries with source-table should produce a synthetic table reference."""
        config = {"client": metabase_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        gui_edges = [
            e for e in edges
            if "gui_query" in (e.discovered_from or "")
        ]

        assert len(gui_edges) == 1
        edge = gui_edges[0]
        assert edge.edge_type == EdgeType.READS_FROM
        assert edge.lineage_level == LineageLevel.TABLE
        assert edge.plane == LinePlane.CROSS
        assert edge.confidence == 0.9
        assert "table_id:42" in edge.discovered_from

    def test_extract_lineage_edge_ids_unique(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        edge_ids = [e.id for e in edges]
        assert len(edge_ids) == len(set(edge_ids)), "Edge IDs must be unique"

    def test_extract_lineage_evidence_adapter_id(self, metabase_mock_client):
        config = {"client": metabase_mock_client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        for edge in edges:
            for ev in edge.evidence:
                assert ev.adapter_id == "live_metabase"

    # ---- Deduplication of cards within a dashboard ----

    def test_extract_lineage_deduplicates_cards_in_dashboard(self):
        """If the same card appears twice in ordered_cards, only one edge is produced."""
        client = MagicMock()
        client.get_dashboards.return_value = [
            {"id": 99, "name": "Dup Dashboard", "collection": {"name": "X"}, "card_count": 2},
        ]
        client.get_cards.return_value = []
        client.get_dashboard.return_value = {
            "ordered_cards": [
                {"card": {"id": 5}},
                {"card": {"id": 5}},  # Duplicate
                {"card": {"id": 6}},
            ],
        }
        config = {"client": client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        # Should be 2, not 3 — the duplicate card 5 is deduplicated
        assert len(tool_edges) == 2

    # ---- Graceful empty/None ----

    def test_discover_assets_none_client(self):
        config = {"client": None}
        nodes = self.adapter.discover_assets(config)
        assert nodes == []

    def test_discover_assets_no_client_key(self):
        config = {}
        nodes = self.adapter.discover_assets(config)
        assert nodes == []

    def test_extract_lineage_none_client(self):
        config = {"client": None}
        edges = self.adapter.extract_lineage(config)
        assert edges == []

    def test_extract_lineage_no_client_key(self):
        config = {}
        edges = self.adapter.extract_lineage(config)
        assert edges == []

    # ---- Exception handling ----

    def test_discover_assets_dashboards_api_error(self):
        client = MagicMock()
        client.get_dashboards.side_effect = RuntimeError("API error")
        client.get_cards.return_value = []
        config = {"client": client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        assert isinstance(nodes, list)

    def test_discover_assets_cards_api_error(self):
        client = MagicMock()
        client.get_dashboards.return_value = []
        client.get_cards.side_effect = RuntimeError("API error")
        config = {"client": client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        assert isinstance(nodes, list)

    def test_extract_lineage_get_dashboard_error(self):
        """If get_dashboard fails for one dashboard, adapter continues with others."""
        client = MagicMock()
        client.get_dashboards.return_value = [
            {"id": 1, "name": "Bad", "collection": {"name": "X"}, "card_count": 0},
            {"id": 2, "name": "Good", "collection": {"name": "Y"}, "card_count": 1},
        ]
        client.get_cards.return_value = []

        def side_effect(dash_id):
            if dash_id == 1:
                raise RuntimeError("fail")
            return {"ordered_cards": [{"card": {"id": 100}}]}

        client.get_dashboard.side_effect = side_effect
        config = {"client": client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        # Dashboard 1 fails, dashboard 2 succeeds with 1 card
        tool_edges = [e for e in edges if e.lineage_level == LineageLevel.TOOL]
        assert len(tool_edges) == 1

    # ---- Card with empty native query ----

    def test_extract_lineage_empty_native_query(self):
        """If native query SQL is empty, no table edges are produced."""
        client = MagicMock()
        client.get_dashboards.return_value = []
        client.get_cards.return_value = [
            {
                "id": 77,
                "name": "Empty Query",
                "dataset_query": {
                    "type": "native",
                    "native": {"query": ""},
                },
            },
        ]
        config = {"client": client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]
        assert len(cross_edges) == 0

    # ---- Card with no source-table in GUI query ----

    def test_extract_lineage_gui_query_missing_source_table(self):
        """If GUI query has no source-table, no cross-plane edge is produced."""
        client = MagicMock()
        client.get_dashboards.return_value = []
        client.get_cards.return_value = [
            {
                "id": 88,
                "name": "Broken GUI",
                "dataset_query": {
                    "type": "query",
                    "query": {},
                },
            },
        ]
        config = {"client": client, "namespace": "acme"}
        edges = self.adapter.extract_lineage(config)
        cross_edges = [e for e in edges if e.plane == LinePlane.CROSS]
        assert len(cross_edges) == 0

    # ---- Card with no dataset_query ----

    def test_discover_assets_card_missing_dataset_query(self):
        """Cards without dataset_query should still be discoverable."""
        client = MagicMock()
        client.get_dashboards.return_value = []
        client.get_cards.return_value = [
            {"id": 99, "name": "Minimal Card"},
        ]
        config = {"client": client, "namespace": "acme"}
        nodes = self.adapter.discover_assets(config)
        assert len(nodes) == 1
        assert nodes[0].node_type == NodeType.QUESTION
        assert nodes[0].raw_metadata["query_type"] == "query"  # default


# ======================================================================
# Cross-adapter consistency tests
# ======================================================================


class TestBIAdapterConsistency:
    """Ensure all three BI adapters follow the same structural contracts."""

    @pytest.fixture(autouse=True)
    def setup_adapters(self):
        self.adapters = [
            LiveTableauAdapter(),
            LivePowerBIAdapter(),
            LiveMetabaseAdapter(),
        ]

    def test_all_are_base_adapter_subclasses(self):
        for adapter in self.adapters:
            assert isinstance(adapter, BaseLineageAdapter)

    def test_all_have_discover_assets_capability(self):
        for adapter in self.adapters:
            assert Capability.DISCOVER_ASSETS in adapter.capabilities()

    def test_all_have_extract_tool_lineage_capability(self):
        for adapter in self.adapters:
            assert Capability.EXTRACT_TOOL_LINEAGE in adapter.capabilities()

    def test_all_have_extract_table_lineage_capability(self):
        for adapter in self.adapters:
            assert Capability.EXTRACT_TABLE_LINEAGE in adapter.capabilities()

    def test_all_have_get_bi_exposures_capability(self):
        for adapter in self.adapters:
            assert Capability.GET_BI_EXPOSURES in adapter.capabilities()

    def test_all_same_capability_count(self):
        """All BI adapters should have exactly the same 4 capabilities."""
        for adapter in self.adapters:
            assert len(adapter.capabilities()) == 4

    def test_all_return_empty_for_no_client(self):
        for adapter in self.adapters:
            assert adapter.discover_assets({}) == []
            assert adapter.extract_lineage({}) == []

    def test_all_return_empty_for_none_client(self):
        for adapter in self.adapters:
            assert adapter.discover_assets({"client": None}) == []
            assert adapter.extract_lineage({"client": None}) == []

    def test_all_have_case_hint(self):
        for adapter in self.adapters:
            assert adapter.case_hint in ("lower", "upper", "preserve")

    def test_all_produce_bi_domain_nodes(
        self, tableau_mock_client, powerbi_mock_client, metabase_mock_client,
    ):
        configs = [
            {"client": tableau_mock_client, "namespace": "test"},
            {
                "client": powerbi_mock_client,
                "namespace": "test",
                "powerbi_config": {"workspace_id": "ws"},
            },
            {"client": metabase_mock_client, "namespace": "test"},
        ]
        for adapter, config in zip(self.adapters, configs):
            nodes = adapter.discover_assets(config)
            for node in nodes:
                assert node.platform_domain == PlatformDomain.BI, (
                    f"{adapter.id()} node {node.fqn} has domain {node.platform_domain}"
                )
