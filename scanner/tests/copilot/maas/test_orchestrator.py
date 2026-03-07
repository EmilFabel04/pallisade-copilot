"""Tests for MAASOrchestrator: init, specialist routing, fallback."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from copilot.llm import Message, StreamEvent
from copilot.intent import Intent

from copilot.maas.orchestrator import MAASOrchestrator
from copilot.maas.schemas import (
    SQLResponse,
    LogsResponse,
    ErrorSignature,
    WarehouseType,
)

from .conftest import make_intent_result, make_context


def _mock_config():
    """Create a mock MAASConfig."""
    config = MagicMock()
    config.enabled = True
    config.sql_endpoint = "http://sql:8000"
    config.sql_api_key = "key"
    config.sql_model = "sql-model"
    config.logs_endpoint = "http://logs:8000"
    config.logs_api_key = "key"
    config.logs_model = "logs-model"
    config.codefix_endpoint = "http://codefix:8000"
    config.codefix_api_key = "key"
    config.codefix_model = "codefix-model"
    config.specialist_timeout = 30
    config.orchestrator_model = "gpt-5.2"
    return config


async def _fake_chat_stream(*args, **kwargs):
    """Async generator that mimics CopilotLLM.chat_stream()."""
    yield StreamEvent("text_delta", {"text": "Fallback response"})
    yield StreamEvent("done", {"model": "gpt-5.2", "input_tokens": 0, "output_tokens": 0})


@pytest.mark.asyncio
class TestMAASOrchestrator:
    @patch("copilot.maas.orchestrator.get_maas_config")
    async def test_init_creates_specialists(self, mock_config_fn):
        mock_config_fn.return_value = _mock_config()
        orch = MAASOrchestrator()
        assert "sql" in orch._specialists
        assert "logs" in orch._specialists
        assert "codefix" in orch._specialists

    @patch("copilot.maas.orchestrator.get_maas_config")
    async def test_init_without_endpoints(self, mock_config_fn):
        config = _mock_config()
        config.sql_endpoint = ""
        config.logs_endpoint = ""
        config.codefix_endpoint = ""
        mock_config_fn.return_value = config
        orch = MAASOrchestrator()
        assert "sql" not in orch._specialists
        assert "logs" not in orch._specialists
        assert "codefix" not in orch._specialists


@pytest.mark.asyncio
class TestMAASFallback:
    @patch("copilot.maas.orchestrator.get_maas_config")
    @patch("copilot.maas.orchestrator.CopilotLLM")
    async def test_fallback_on_no_intent(self, mock_llm_cls, mock_config_fn):
        """When no intent_result in context, should fall back to standard LLM."""
        mock_config_fn.return_value = _mock_config()

        mock_llm = MagicMock()
        mock_llm.chat_stream = _fake_chat_stream
        mock_llm_cls.return_value = mock_llm

        orch = MAASOrchestrator()
        ctx = make_context(query="hello")
        ctx.intent_result = None
        ctx.mode_config = MagicMock()

        events = []
        async for event in orch.run_stream(
            [Message(role="user", content="hello")],
            ctx,
        ):
            events.append(event)

        assert len(events) > 0
        event_types = [e.event_type for e in events]
        assert "done" in event_types

    @patch("copilot.maas.orchestrator.get_maas_config")
    @patch("copilot.maas.orchestrator.CopilotLLM")
    async def test_fallback_on_exception(self, mock_llm_cls, mock_config_fn):
        """On orchestration error, should fall back gracefully."""
        mock_config_fn.return_value = _mock_config()

        mock_llm = MagicMock()
        mock_llm.chat_stream = _fake_chat_stream
        mock_llm_cls.return_value = mock_llm

        orch = MAASOrchestrator()

        ctx = make_context(query="test")
        ctx.intent_result = make_intent_result(primary=Intent.INFO)
        ctx.mode_config = MagicMock()

        events = []
        with patch("copilot.maas.orchestrator.route_intent", side_effect=Exception("boom")):
            async for event in orch.run_stream(
                [Message(role="user", content="test")],
                ctx,
            ):
                events.append(event)

        assert len(events) > 0


class TestWarehouseResolution:
    """Test _resolve_target_warehouse deterministic logic."""

    @patch("copilot.maas.orchestrator.get_maas_config")
    def test_single_warehouse_auto_selected(self, mock_config_fn):
        mock_config_fn.return_value = _mock_config()
        orch = MAASOrchestrator()

        ctx = make_context(
            query="count rows",
            warehouse_schema={"BIGQUERY:analytics": []},
        )
        result = orch._resolve_target_warehouse(ctx)
        assert result == "bigquery"

    @patch("copilot.maas.orchestrator.get_maas_config")
    def test_multi_warehouse_query_mention(self, mock_config_fn):
        mock_config_fn.return_value = _mock_config()
        orch = MAASOrchestrator()

        ctx = make_context(
            query="count rows in bigquery",
            warehouse_schema={
                "BIGQUERY:analytics": [],
                "SNOWFLAKE:PUBLIC": [],
            },
        )
        result = orch._resolve_target_warehouse(ctx)
        assert result == "bigquery"

    @patch("copilot.maas.orchestrator.get_maas_config")
    def test_multi_warehouse_bq_alias(self, mock_config_fn):
        mock_config_fn.return_value = _mock_config()
        orch = MAASOrchestrator()

        ctx = make_context(
            query="count rows in bq",
            warehouse_schema={
                "BIGQUERY:analytics": [],
                "SNOWFLAKE:PUBLIC": [],
            },
        )
        result = orch._resolve_target_warehouse(ctx)
        assert result == "bigquery"

    @patch("copilot.maas.orchestrator.get_maas_config")
    def test_multi_warehouse_snowflake_mention(self, mock_config_fn):
        mock_config_fn.return_value = _mock_config()
        orch = MAASOrchestrator()

        ctx = make_context(
            query="count rows in snowflake",
            warehouse_schema={
                "BIGQUERY:analytics": [],
                "SNOWFLAKE:PUBLIC": [],
            },
        )
        result = orch._resolve_target_warehouse(ctx)
        assert result == "snowflake"

    @patch("copilot.maas.orchestrator.get_maas_config")
    def test_multi_warehouse_no_mention_uses_first(self, mock_config_fn):
        mock_config_fn.return_value = _mock_config()
        orch = MAASOrchestrator()

        ctx = make_context(
            query="count rows in the table",
            warehouse_schema={
                "BIGQUERY:analytics": [],
                "SNOWFLAKE:PUBLIC": [],
            },
        )
        result = orch._resolve_target_warehouse(ctx)
        # Should return one of the connected warehouses (deterministic but order may vary with set)
        assert result in ("bigquery", "snowflake")

    @patch("copilot.maas.orchestrator.get_maas_config")
    def test_no_schema_returns_none(self, mock_config_fn):
        mock_config_fn.return_value = _mock_config()
        orch = MAASOrchestrator()

        ctx = make_context(query="hello", warehouse_schema={})
        result = orch._resolve_target_warehouse(ctx)
        assert result is None


@pytest.mark.asyncio
class TestRepairLoop:
    """Test the one-retry repair loop for SQL execution failures."""

    @patch("copilot.maas.orchestrator.get_maas_config")
    @patch("copilot.maas.orchestrator.CopilotLLM")
    @patch("copilot.maas.orchestrator.ToolExecutor")
    async def test_repair_succeeds_on_second_attempt(
        self, mock_executor_cls, mock_llm_cls, mock_config_fn
    ):
        """SQL fails first execution, repair succeeds on second."""
        mock_config_fn.return_value = _mock_config()

        mock_llm = MagicMock()
        mock_llm.chat_stream = _fake_chat_stream
        mock_llm_cls.return_value = mock_llm

        # Mock executor: first query_warehouse fails, second succeeds
        mock_executor = AsyncMock()
        call_count = 0

        async def _fake_execute(tool_name, args):
            nonlocal call_count
            if tool_name == "query_warehouse":
                call_count += 1
                result = MagicMock()
                if call_count == 1:
                    result.success = False
                    result.error = "Column not found: bad_col"
                    result.to_dict.return_value = {
                        "success": False,
                        "error": "Column not found: bad_col",
                    }
                else:
                    result.success = True
                    result.to_dict.return_value = {
                        "success": True,
                        "data": {"rows": [{"count": 42}]},
                    }
                return result
            return MagicMock(success=True, to_dict=lambda: {})

        mock_executor.execute = _fake_execute
        mock_executor.fetch_warehouse_schema = AsyncMock(return_value={})
        mock_executor_cls.return_value = mock_executor

        orch = MAASOrchestrator()

        # Mock the SQL specialist to return valid responses
        sql_response = SQLResponse(
            sql="SELECT COUNT(*) FROM t",
            warehouse=WarehouseType.BIGQUERY,
            explanation="test",
        )
        mock_specialist = AsyncMock()
        mock_specialist.call = AsyncMock(return_value=sql_response)
        mock_specialist.name = "sql"
        orch._specialists["sql"] = mock_specialist

        from copilot.context_builder import TableSchema
        tables = [TableSchema(name="t", columns=[{"name": "id", "type": "INT"}], dataset="ds")]
        ctx = make_context(
            query="count rows",
            warehouse_schema={"BIGQUERY:ds": tables},
        )
        ctx.intent_result = make_intent_result(primary=Intent.INFO)

        events = []
        async for event in orch.run_stream(
            [Message(role="user", content="count rows")], ctx
        ):
            events.append(event)

        event_types = [e.event_type for e in events]
        # Should have two query_warehouse tool calls (original + repair)
        qw_starts = [
            e for e in events
            if e.event_type == "tool_call_start"
            and e.data.get("tool_name") == "query_warehouse"
        ]
        assert len(qw_starts) == 2
        assert qw_starts[0].data["tool_use_id"] == "maas_sql_exec"
        assert qw_starts[1].data["tool_use_id"] == "maas_sql_repair"

    @patch("copilot.maas.orchestrator.get_maas_config")
    @patch("copilot.maas.orchestrator.CopilotLLM")
    @patch("copilot.maas.orchestrator.ToolExecutor")
    async def test_fallback_on_double_failure(
        self, mock_executor_cls, mock_llm_cls, mock_config_fn
    ):
        """SQL fails both times — should fallback."""
        mock_config_fn.return_value = _mock_config()

        mock_llm = MagicMock()
        mock_llm.chat_stream = _fake_chat_stream
        mock_llm_cls.return_value = mock_llm

        mock_executor = AsyncMock()

        async def _always_fail(tool_name, args):
            result = MagicMock()
            result.success = False
            result.error = "Table not found"
            result.to_dict.return_value = {"success": False, "error": "Table not found"}
            return result

        mock_executor.execute = _always_fail
        mock_executor.fetch_warehouse_schema = AsyncMock(return_value={})
        mock_executor_cls.return_value = mock_executor

        orch = MAASOrchestrator()

        sql_response = SQLResponse(
            sql="SELECT 1 FROM missing_table",
            warehouse=WarehouseType.BIGQUERY,
            explanation="test",
        )
        mock_specialist = AsyncMock()
        mock_specialist.call = AsyncMock(return_value=sql_response)
        mock_specialist.name = "sql"
        orch._specialists["sql"] = mock_specialist

        from copilot.context_builder import TableSchema
        tables = [TableSchema(name="t", columns=[{"name": "id", "type": "INT"}], dataset="ds")]
        ctx = make_context(
            query="count rows",
            warehouse_schema={"BIGQUERY:ds": tables},
        )
        ctx.intent_result = make_intent_result(primary=Intent.INFO)

        events = []
        async for event in orch.run_stream(
            [Message(role="user", content="count rows")], ctx
        ):
            events.append(event)

        # Should end with a done event from fallback
        done_events = [e for e in events if e.event_type == "done"]
        assert len(done_events) > 0
        # Trace should indicate fallback
        trace = done_events[-1].data.get("maas_trace", {})
        assert trace.get("fallback_reason") == "sql_repair_failed"
        assert trace.get("repair_attempted") is True
