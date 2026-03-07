"""Tests for RunPod HTTP client + circuit breaker + JSON extraction."""

import pytest
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

from copilot.maas.client import (
    RunPodClient,
    RunPodUnavailableError,
    CircuitBreakerState,
    _extract_json,
)


class TestExtractJson:
    """Test hardened JSON extraction from vLLM output."""

    def test_clean_json(self):
        raw = '{"sql": "SELECT 1", "warehouse": "bigquery"}'
        assert _extract_json(raw) == raw

    def test_json_with_whitespace(self):
        raw = '  \n {"sql": "SELECT 1"}  \n'
        result = _extract_json(raw)
        assert result.startswith("{")

    def test_code_fence_json(self):
        raw = '```json\n{"sql": "SELECT 1", "warehouse": "bigquery"}\n```'
        result = _extract_json(raw)
        assert '"sql"' in result
        assert "```" not in result

    def test_code_fence_without_language(self):
        raw = '```\n{"sql": "SELECT 1"}\n```'
        result = _extract_json(raw)
        assert result.startswith("{")

    def test_preamble_text_before_json(self):
        raw = 'Here is the SQL query:\n{"sql": "SELECT COUNT(*) FROM orders", "warehouse": "bigquery"}'
        result = _extract_json(raw)
        assert result.startswith("{")
        parsed = json.loads(result)
        assert parsed["sql"] == "SELECT COUNT(*) FROM orders"

    def test_nested_braces(self):
        raw = '{"outer": {"inner": "value"}, "list": [1, 2]}'
        result = _extract_json(raw)
        parsed = json.loads(result)
        assert parsed["outer"]["inner"] == "value"

    def test_braces_in_strings(self):
        raw = '{"sql": "SELECT * WHERE name = \'{test}\'", "warehouse": "bigquery"}'
        result = _extract_json(raw)
        assert result.startswith("{")

    def test_no_json_at_all(self):
        raw = "No JSON here, just text."
        result = _extract_json(raw)
        # Should return as-is for Pydantic to reject
        assert result == raw

    def test_vlm_fenced_integration(self):
        """Integration test: simulate vLLM returning fenced JSON → parse with Pydantic."""
        from copilot.maas.schemas import SQLResponse

        fenced = '```json\n{"sql": "SELECT COUNT(*) FROM `proj.ds.orders`", "warehouse": "bigquery", "explanation": "Count rows"}\n```'
        extracted = _extract_json(fenced)
        resp = SQLResponse.model_validate_json(extracted)
        assert resp.warehouse.value == "bigquery"
        assert "COUNT" in resp.sql


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreakerState()
        assert cb.can_attempt() is True
        assert cb.is_open is False

    def test_opens_after_threshold(self):
        cb = CircuitBreakerState()
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open is True
        assert cb.can_attempt() is False

    def test_resets_on_success(self):
        cb = CircuitBreakerState()
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failures == 0
        assert cb.is_open is False

    def test_half_open_after_recovery(self):
        cb = CircuitBreakerState()
        for _ in range(3):
            cb.record_failure()
        assert cb.can_attempt() is False

        # Simulate recovery timeout elapsed
        cb.last_failure_time = time.time() - 61
        assert cb.can_attempt() is True


@pytest.mark.asyncio
class TestRunPodClient:
    async def test_successful_completion(self):
        client = RunPodClient(
            base_url="http://localhost:8000",
            api_key="test-key",
            model_name="test-model",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"sql": "SELECT 1"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        client._client = mock_http

        result = await client.chat_completion(
            messages=[{"role": "user", "content": "test"}],
        )
        assert result["content"] == '{"sql": "SELECT 1"}'
        assert "latency_ms" in result

    async def test_circuit_breaker_blocks_request(self):
        client = RunPodClient(
            base_url="http://localhost:8000",
            api_key="test-key",
        )
        # Force circuit open
        client._circuit.is_open = True
        client._circuit.last_failure_time = time.time()

        with pytest.raises(RunPodUnavailableError, match="Circuit breaker open"):
            await client.chat_completion(
                messages=[{"role": "user", "content": "test"}],
            )

    async def test_retries_on_http_error(self):
        client = RunPodClient(
            base_url="http://localhost:8000",
            api_key="test-key",
            max_retries=1,
        )

        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=error_resp)
        mock_http.is_closed = False
        client._client = mock_http

        with pytest.raises(RunPodUnavailableError, match="All retries exhausted"):
            await client.chat_completion(
                messages=[{"role": "user", "content": "test"}],
            )
        # Should have been called max_retries + 1 times
        assert mock_http.post.call_count == 2

    async def test_extracts_json_from_fenced_response(self):
        client = RunPodClient(
            base_url="http://localhost:8000",
            api_key="test-key",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {"content": '```json\n{"sql": "SELECT 1"}\n```'},
                "finish_reason": "stop",
            }],
            "usage": {},
        }

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        client._client = mock_http

        result = await client.chat_completion(
            messages=[{"role": "user", "content": "test"}],
        )
        assert result["content"] == '{"sql": "SELECT 1"}'

    async def test_close(self):
        client = RunPodClient(
            base_url="http://localhost:8000",
            api_key="test-key",
        )
        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._client = mock_http

        await client.close()
        mock_http.aclose.assert_called_once()

    async def test_is_available(self):
        client = RunPodClient(
            base_url="http://localhost:8000",
            api_key="test-key",
        )
        assert client.is_available is True

        client._circuit.is_open = True
        client._circuit.last_failure_time = time.time()
        assert client.is_available is False
