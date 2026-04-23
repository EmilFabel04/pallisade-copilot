"""
Tests for BI tool executor methods in ToolExecutor.

Covers Tableau, Power BI, and Metabase executors:
1. Happy path — client returns valid data, executor returns ToolResult(success=True)
2. Entity not found — name doesn't match, returns helpful error
3. Client exception — graceful ToolResult(success=False)
4. Missing adapter — KB fallback error message
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from scanner.copilot.tool_executor import ToolResult


# ======================================================================
# Helpers
# ======================================================================


def _make_executor_with_adapter(adapter_type: str, mock_client):
    """Create a minimal executor-like object with _adapters dict for testing."""
    # Import the class — we test the individual _execute_* methods directly
    from scanner.copilot.tool_executor import ToolExecutor

    executor = object.__new__(ToolExecutor)
    executor._adapters = {adapter_type: mock_client}
    return executor


def _make_executor_without_adapter(adapter_type: str):
    """Create executor with no adapter for the given type."""
    from scanner.copilot.tool_executor import ToolExecutor

    executor = object.__new__(ToolExecutor)
    executor._adapters = {}
    return executor


# ======================================================================
# Tableau Fixtures
# ======================================================================


@pytest.fixture
def tableau_client():
    client = MagicMock()

    client.get_all_workbooks.return_value = [
        {
            "id": "wb-001",
            "name": "Revenue Dashboard",
            "project": {"name": "Finance"},
            "owner": {"name": "alice@acme.com"},
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-06-01T00:00:00Z",
        },
    ]

    client.get_workbook.return_value = {
        "workbook": {"id": "wb-001", "name": "Revenue Dashboard"},
    }

    client.get_workbook_connections.return_value = [
        {"type": "snowflake", "serverAddress": "acme.snowflakecomputing.com", "serverPort": "443"},
    ]

    client.get_views_for_workbook.return_value = [
        {"id": "v-001", "name": "Overview"},
        {"id": "v-002", "name": "Details"},
    ]

    client.get_all_datasources.return_value = [
        {
            "id": "ds-001",
            "name": "Sales Data",
            "project": {"name": "Finance"},
            "owner": {"name": "alice@acme.com"},
            "type": "snowflake",
            "contentUrl": "SalesData",
            "hasExtracts": True,
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-06-01T00:00:00Z",
        },
    ]

    client.get_datasource.return_value = {
        "datasource": {"id": "ds-001", "name": "Sales Data", "hasExtracts": True},
    }

    client.get_background_jobs.return_value = [
        {
            "id": "job-001",
            "status": "Success",
            "createdAt": "2024-06-01T10:00:00Z",
            "startedAt": "2024-06-01T10:00:05Z",
            "endedAt": "2024-06-01T10:05:00Z",
            "title": "Refresh Sales Data",
            "type": "extractRefresh",
        },
        {
            "id": "job-002",
            "status": "Failed",
            "createdAt": "2024-06-01T08:00:00Z",
            "startedAt": "2024-06-01T08:00:05Z",
            "endedAt": "2024-06-01T08:01:00Z",
            "title": "Refresh Marketing Data",
            "type": "extractRefresh",
        },
    ]

    return client


# ======================================================================
# Power BI Fixtures
# ======================================================================


@pytest.fixture
def powerbi_client():
    client = MagicMock()

    client.get_workspaces.return_value = [
        {"id": "ws-001", "name": "Finance Workspace"},
    ]

    client.get_datasets_in_workspace.return_value = [
        {
            "id": "ds-001",
            "name": "Sales Dataset",
            "isRefreshable": True,
            "configuredBy": "admin@acme.com",
        },
    ]

    client.get_dataset_datasources.return_value = [
        {
            "datasourceType": "Sql",
            "connectionDetails": {"server": "sql.acme.com", "database": "SalesDB"},
        },
    ]

    client.get_dataset_refresh_history.return_value = [
        {
            "status": "Completed",
            "startTime": "2024-06-01T10:00:00Z",
            "endTime": "2024-06-01T10:05:00Z",
            "refreshType": "Scheduled",
            "requestId": "req-001",
        },
    ]

    client.get_dataset_refresh_schedule.return_value = {
        "enabled": True,
        "days": ["Monday", "Wednesday", "Friday"],
        "times": ["06:00", "18:00"],
        "localTimeZoneId": "UTC",
    }

    client.get_gateways.return_value = [
        {"id": "gw-001", "name": "On-Prem Gateway", "type": "Personal", "publicKey": None},
    ]

    client.get_gateway_datasources.return_value = [
        {"id": "gds-001", "datasourceName": "SQL Server", "datasourceType": "Sql", "connectionDetails": {}},
    ]

    return client


# ======================================================================
# Metabase Fixtures
# ======================================================================


@pytest.fixture
def metabase_client():
    client = MagicMock()

    client.get_dashboard.return_value = {
        "id": 1,
        "name": "KPI Dashboard",
        "description": "Key metrics",
        "collection": {"name": "Analytics"},
        "creator": {"common_name": "Alice"},
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-06-01T00:00:00Z",
        "parameters": [{"id": "p1"}],
        "dashcards": [
            {"card": {"id": 10, "name": "Revenue Card", "last_error": None}},
            {"card": {"id": 11, "name": "Broken Card", "last_error": "Query failed"}},
        ],
    }

    client.get_card.return_value = {
        "id": 10,
        "name": "Revenue Card",
        "description": "Monthly revenue",
        "collection": {"name": "Analytics"},
        "database_id": 1,
        "query_type": "query",
        "display": "bar",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-06-01T00:00:00Z",
        "average_query_time": 250,
        "cache_ttl": 3600,
        "last_query_start": "2024-06-01T10:00:00Z",
        "archived": False,
    }

    client.get_database.return_value = {
        "id": 1,
        "name": "Production Postgres",
        "engine": "postgres",
        "details": {"host": "db.acme.com"},
        "initial_sync_status": "complete",
        "auto_run_queries": True,
        "cache_ttl": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-06-01T00:00:00Z",
    }

    client.get_databases.return_value = [
        {
            "id": 1,
            "name": "Production Postgres",
            "engine": "postgres",
            "details": {"host": "db.acme.com"},
            "initial_sync_status": "complete",
            "auto_run_queries": True,
            "cache_ttl": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-06-01T00:00:00Z",
        },
    ]

    return client


# ======================================================================
# Tableau Tests
# ======================================================================


class TestTableauExecutors:

    @pytest.mark.asyncio
    async def test_workbook_status_happy_path(self, tableau_client):
        executor = _make_executor_with_adapter("TABLEAU", tableau_client)
        result = await executor._execute_get_tableau_workbook_status({"workbook_name": "Revenue Dashboard"})
        assert result.success is True
        assert result.data["workbook_id"] == "wb-001"
        assert result.data["view_count"] == 2
        assert len(result.data["connections"]) == 1

    @pytest.mark.asyncio
    async def test_workbook_status_not_found(self, tableau_client):
        executor = _make_executor_with_adapter("TABLEAU", tableau_client)
        result = await executor._execute_get_tableau_workbook_status({"workbook_name": "Nonexistent"})
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_workbook_status_client_error(self, tableau_client):
        tableau_client.get_all_workbooks.side_effect = Exception("Connection timeout")
        executor = _make_executor_with_adapter("TABLEAU", tableau_client)
        result = await executor._execute_get_tableau_workbook_status({"workbook_name": "Revenue Dashboard"})
        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_workbook_status_no_adapter(self):
        executor = _make_executor_without_adapter("TABLEAU")
        result = await executor._execute_get_tableau_workbook_status({"workbook_name": "X"})
        assert result.success is False
        assert "not connected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_datasource_info_happy_path(self, tableau_client):
        executor = _make_executor_with_adapter("TABLEAU", tableau_client)
        result = await executor._execute_get_tableau_datasource_info({"datasource_name": "Sales Data"})
        assert result.success is True
        assert result.data["datasource_id"] == "ds-001"
        assert result.data["has_extracts"] is True

    @pytest.mark.asyncio
    async def test_datasource_info_not_found(self, tableau_client):
        executor = _make_executor_with_adapter("TABLEAU", tableau_client)
        result = await executor._execute_get_tableau_datasource_info({"datasource_name": "Nonexistent"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_refresh_history_happy_path(self, tableau_client):
        executor = _make_executor_with_adapter("TABLEAU", tableau_client)
        result = await executor._execute_get_tableau_refresh_history({"limit": 10})
        assert result.success is True
        assert result.data["total_jobs"] == 2

    @pytest.mark.asyncio
    async def test_refresh_history_filtered(self, tableau_client):
        executor = _make_executor_with_adapter("TABLEAU", tableau_client)
        result = await executor._execute_get_tableau_refresh_history({"datasource_name": "Sales", "limit": 10})
        assert result.success is True
        assert result.data["total_jobs"] == 1  # Only "Refresh Sales Data" matches

    @pytest.mark.asyncio
    async def test_refresh_history_no_adapter(self):
        executor = _make_executor_without_adapter("TABLEAU")
        result = await executor._execute_get_tableau_refresh_history({})
        assert result.success is False
        assert "not connected" in result.error.lower()


# ======================================================================
# Power BI Tests
# ======================================================================


class TestPowerBIExecutors:

    @pytest.mark.asyncio
    async def test_dataset_status_happy_path(self, powerbi_client):
        executor = _make_executor_with_adapter("POWERBI", powerbi_client)
        result = await executor._execute_get_powerbi_dataset_status({"dataset_name": "Sales Dataset"})
        assert result.success is True
        assert result.data["dataset_id"] == "ds-001"
        assert result.data["workspace"] == "Finance Workspace"
        assert result.data["last_refresh"]["status"] == "Completed"
        assert len(result.data["datasources"]) == 1

    @pytest.mark.asyncio
    async def test_dataset_status_not_found(self, powerbi_client):
        executor = _make_executor_with_adapter("POWERBI", powerbi_client)
        result = await executor._execute_get_powerbi_dataset_status({"dataset_name": "Nonexistent"})
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dataset_status_no_adapter(self):
        executor = _make_executor_without_adapter("POWERBI")
        result = await executor._execute_get_powerbi_dataset_status({"dataset_name": "X"})
        assert result.success is False
        assert "not connected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_refresh_history_happy_path(self, powerbi_client):
        executor = _make_executor_with_adapter("POWERBI", powerbi_client)
        result = await executor._execute_get_powerbi_refresh_history({"dataset_name": "Sales Dataset", "limit": 10})
        assert result.success is True
        assert result.data["dataset_name"] == "Sales Dataset"
        assert result.data["schedule"]["enabled"] is True
        assert len(result.data["history"]) == 1

    @pytest.mark.asyncio
    async def test_refresh_history_not_found(self, powerbi_client):
        executor = _make_executor_with_adapter("POWERBI", powerbi_client)
        result = await executor._execute_get_powerbi_refresh_history({"dataset_name": "Nonexistent"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_gateway_status_happy_path(self, powerbi_client):
        executor = _make_executor_with_adapter("POWERBI", powerbi_client)
        result = await executor._execute_get_powerbi_gateway_status({})
        assert result.success is True
        # Single gateway returns unwrapped
        assert result.data["gateway_id"] == "gw-001"
        assert result.data["datasource_count"] == 1

    @pytest.mark.asyncio
    async def test_gateway_status_filtered(self, powerbi_client):
        executor = _make_executor_with_adapter("POWERBI", powerbi_client)
        result = await executor._execute_get_powerbi_gateway_status({"gateway_name": "On-Prem Gateway"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_gateway_status_not_found(self, powerbi_client):
        executor = _make_executor_with_adapter("POWERBI", powerbi_client)
        result = await executor._execute_get_powerbi_gateway_status({"gateway_name": "Nonexistent"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_gateway_status_no_adapter(self):
        executor = _make_executor_without_adapter("POWERBI")
        result = await executor._execute_get_powerbi_gateway_status({})
        assert result.success is False
        assert "not connected" in result.error.lower()


# ======================================================================
# Metabase Tests
# ======================================================================


class TestMetabaseExecutors:

    @pytest.mark.asyncio
    async def test_dashboard_status_happy_path(self, metabase_client):
        executor = _make_executor_with_adapter("METABASE", metabase_client)
        result = await executor._execute_get_metabase_dashboard_status({"dashboard_id": 1})
        assert result.success is True
        assert result.data["name"] == "KPI Dashboard"
        assert result.data["card_count"] == 2
        assert result.data["filter_count"] == 1
        assert len(result.data["broken_cards"]) == 1
        assert result.data["broken_cards"][0]["name"] == "Broken Card"
        assert result.data["is_healthy"] is False

    @pytest.mark.asyncio
    async def test_dashboard_status_client_error(self, metabase_client):
        metabase_client.get_dashboard.side_effect = Exception("Not found")
        executor = _make_executor_with_adapter("METABASE", metabase_client)
        result = await executor._execute_get_metabase_dashboard_status({"dashboard_id": 999})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_dashboard_status_no_adapter(self):
        executor = _make_executor_without_adapter("METABASE")
        result = await executor._execute_get_metabase_dashboard_status({"dashboard_id": 1})
        assert result.success is False
        assert "not connected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_card_info_happy_path(self, metabase_client):
        executor = _make_executor_with_adapter("METABASE", metabase_client)
        result = await executor._execute_get_metabase_card_info({"card_id": 10})
        assert result.success is True
        assert result.data["name"] == "Revenue Card"
        assert result.data["query_type"] == "query"
        assert result.data["display"] == "bar"
        assert result.data["average_query_time"] == 250

    @pytest.mark.asyncio
    async def test_card_info_no_adapter(self):
        executor = _make_executor_without_adapter("METABASE")
        result = await executor._execute_get_metabase_card_info({"card_id": 10})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_database_status_single(self, metabase_client):
        executor = _make_executor_with_adapter("METABASE", metabase_client)
        result = await executor._execute_get_metabase_database_status({"database_id": 1})
        assert result.success is True
        assert len(result.data["databases"]) == 1
        assert result.data["databases"][0]["engine"] == "postgres"

    @pytest.mark.asyncio
    async def test_database_status_all(self, metabase_client):
        executor = _make_executor_with_adapter("METABASE", metabase_client)
        result = await executor._execute_get_metabase_database_status({})
        assert result.success is True
        assert len(result.data["databases"]) == 1

    @pytest.mark.asyncio
    async def test_database_status_no_adapter(self):
        executor = _make_executor_without_adapter("METABASE")
        result = await executor._execute_get_metabase_database_status({})
        assert result.success is False
        assert "not connected" in result.error.lower()


# ======================================================================
# Looker Config Normalization Tests
# ======================================================================


class TestLookerConfigNormalization:
    """Test that _create_adapter handles both host and base_url for Looker."""

    def test_create_adapter_with_host(self):
        """Config with 'host' key should create a LookerClient."""
        from scanner.copilot.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)

        class FakeIntegration:
            type = "LOOKER"
            config = {"host": "company.cloud.looker.com", "client_id": "abc", "client_secret": "xyz"}

        with patch("integrations.looker.LookerClient") as MockClient:
            MockClient.return_value = MagicMock()
            executor._create_adapter(FakeIntegration())
            MockClient.assert_called_once_with(
                host="company.cloud.looker.com",
                client_id="abc",
                client_secret="xyz",
                port=19999,
                verify_ssl=True,
            )

    def test_create_adapter_with_base_url(self):
        """Config with 'base_url' (no 'host') should fall back to base_url."""
        from scanner.copilot.tool_executor import ToolExecutor

        executor = object.__new__(ToolExecutor)

        class FakeIntegration:
            type = "LOOKER"
            config = {"base_url": "https://looker.acme.com", "client_id": "abc", "client_secret": "xyz"}

        with patch("integrations.looker.LookerClient") as MockClient:
            MockClient.return_value = MagicMock()
            executor._create_adapter(FakeIntegration())
            MockClient.assert_called_once_with(
                host="https://looker.acme.com",
                client_id="abc",
                client_secret="xyz",
                port=19999,
                verify_ssl=True,
            )
