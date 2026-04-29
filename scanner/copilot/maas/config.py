"""
Central MAAS configuration.

All values loaded from environment variables.
Enable with COPILOT_MAAS_ENABLED=true.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MAASConfig:
    """Central configuration for the MAAS system."""

    # Feature flag
    enabled: bool

    # RunPod specialist endpoints (OpenAI-compatible vLLM)
    sql_endpoint: str
    sql_api_key: str
    sql_model: str

    logs_endpoint: str
    logs_api_key: str
    logs_model: str

    # Timeouts (seconds)
    specialist_timeout: float

    # GPT-5 model name for the orchestrator/narrator
    orchestrator_model: str

    @classmethod
    def from_env(cls) -> "MAASConfig":
        """Load configuration from environment variables."""
        return cls(
            enabled=os.environ.get("COPILOT_MAAS_ENABLED", "false").lower() == "true",

            sql_endpoint=os.environ.get("MAAS_SQL_ENDPOINT", ""),
            sql_api_key=os.environ.get("MAAS_SQL_API_KEY", ""),
            sql_model=os.environ.get("MAAS_SQL_MODEL", "specialist-sql"),

            logs_endpoint=os.environ.get("MAAS_LOGS_ENDPOINT", ""),
            logs_api_key=os.environ.get("MAAS_LOGS_API_KEY", ""),
            logs_model=os.environ.get("MAAS_LOGS_MODEL", "specialist-logs"),

            specialist_timeout=float(os.environ.get("MAAS_SPECIALIST_TIMEOUT", "90")),
            orchestrator_model=os.environ.get("MAAS_ORCHESTRATOR_MODEL", "gpt-5.4"),
        )


def get_maas_config() -> MAASConfig:
    """Load MAAS configuration from environment."""
    return MAASConfig.from_env()


def is_maas_enabled() -> bool:
    """Quick check for the MAAS feature flag."""
    return os.environ.get("COPILOT_MAAS_ENABLED", "false").lower() == "true"
