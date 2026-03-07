"""Tests for MAAS fallback scenarios: disabled flag, missing config, circuit breaker."""

import os
import pytest
from unittest.mock import patch, MagicMock
import time

from copilot.maas.config import MAASConfig, is_maas_enabled, get_maas_config
from copilot.maas.client import CircuitBreakerState, RunPodClient, RunPodUnavailableError


class TestMAASDisabled:
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_maas_enabled() is False

    def test_enabled_via_env(self):
        with patch.dict(os.environ, {"COPILOT_MAAS_ENABLED": "true"}):
            assert is_maas_enabled() is True

    def test_disabled_explicit(self):
        with patch.dict(os.environ, {"COPILOT_MAAS_ENABLED": "false"}):
            assert is_maas_enabled() is False

    def test_case_insensitive(self):
        with patch.dict(os.environ, {"COPILOT_MAAS_ENABLED": "True"}):
            assert is_maas_enabled() is True


class TestMAASConfig:
    def test_from_env_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = MAASConfig.from_env()
            assert config.enabled is False
            assert config.sql_model == "specialist-sql"
            assert config.specialist_timeout == 30.0
            assert config.orchestrator_model == "gpt-5.2"

    def test_from_env_custom(self):
        env = {
            "COPILOT_MAAS_ENABLED": "true",
            "MAAS_SQL_ENDPOINT": "http://sql:8000",
            "MAAS_SQL_API_KEY": "sk-sql",
            "MAAS_SQL_MODEL": "my-sql-model",
            "MAAS_SPECIALIST_TIMEOUT": "60",
            "MAAS_ORCHESTRATOR_MODEL": "gpt-5.3",
        }
        with patch.dict(os.environ, env, clear=True):
            config = MAASConfig.from_env()
            assert config.enabled is True
            assert config.sql_endpoint == "http://sql:8000"
            assert config.sql_api_key == "sk-sql"
            assert config.sql_model == "my-sql-model"
            assert config.specialist_timeout == 60.0
            assert config.orchestrator_model == "gpt-5.3"

    def test_frozen(self):
        config = MAASConfig.from_env()
        with pytest.raises(AttributeError):
            config.enabled = True


class TestCircuitBreakerFallback:
    def test_three_failures_opens_circuit(self):
        cb = CircuitBreakerState()
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open is True
        assert cb.can_attempt() is False

    def test_success_resets_circuit(self):
        cb = CircuitBreakerState()
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failures == 0
        assert cb.is_open is False

    def test_half_open_recovery(self):
        cb = CircuitBreakerState()
        for _ in range(3):
            cb.record_failure()
        # Simulate 61 seconds passing
        cb.last_failure_time = time.time() - 61
        assert cb.can_attempt() is True
        # Circuit should now be closed for half-open attempt
        assert cb.is_open is False

    @pytest.mark.asyncio
    async def test_client_rejects_when_circuit_open(self):
        client = RunPodClient(
            base_url="http://localhost:8000",
            api_key="test",
        )
        # Force circuit open
        for _ in range(3):
            client._circuit.record_failure()

        with pytest.raises(RunPodUnavailableError, match="Circuit breaker open"):
            await client.chat_completion(
                messages=[{"role": "user", "content": "test"}],
            )
