"""
Central MAAS configuration.

All values loaded from environment variables.
Enable with COPILOT_MAAS_ENABLED=true.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MAASConfig:
    """Central configuration for the MAAS system."""

    # Feature flag
    enabled: bool

    # Specialist endpoints. Originally RunPod-hosted vLLM; the client speaks
    # plain OpenAI-compatible /v1/chat/completions, so these can also point
    # at api.openai.com directly with a project-scoped key per specialist
    # for cost visibility. No code changes needed when swapping providers.
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

    # Default reasoning_effort for GPT-5 / o-series specialists. None = let
    # the model use its default. For narrow JSON-emitting tasks (SQL gen,
    # log triage) "minimal" or "low" is usually right and keeps cost down.
    specialist_reasoning_effort: Optional[str]

    # Per-specialist overrides. When set, take precedence over the default.
    # Useful when (e.g.) the SQL specialist is fine on "minimal" but the
    # Logs specialist needs "medium" to triage subtle failures.
    sql_reasoning_effort: Optional[str]
    logs_reasoning_effort: Optional[str]

    # Soft deadline (seconds) for the specialist phase. When set and
    # exceeded, the orchestrator abandons specialists and falls back to
    # narrating from Phase-1 evidence alone. ``None`` (default) keeps
    # today's no-deadline behavior. The conservative form of Tier-4
    # item 5 — full speculative narration is gated on the eval harness.
    specialist_soft_deadline_sec: Optional[float]

    @staticmethod
    def _parse_effort(value: str) -> Optional[str]:
        v = (value or "").strip().lower()
        return v if v in ("minimal", "low", "medium", "high") else None

    @staticmethod
    def _parse_positive_float(value: str) -> Optional[float]:
        """Parse a strictly-positive float; non-positive or invalid → None.

        Treating zero as "off" (rather than "fail immediately") avoids
        the operator-surprise case of an accidental ``=0`` causing every
        request to time out instantly. The unset and invalid cases all
        collapse to None for the same reason.
        """
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @classmethod
    def from_env(cls) -> "MAASConfig":
        """Load configuration from environment variables."""
        default_effort = cls._parse_effort(
            os.environ.get("MAAS_SPECIALIST_REASONING_EFFORT", "")
        )
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
            specialist_reasoning_effort=default_effort,
            sql_reasoning_effort=(
                cls._parse_effort(os.environ.get("MAAS_SQL_REASONING_EFFORT", ""))
                or default_effort
            ),
            logs_reasoning_effort=(
                cls._parse_effort(os.environ.get("MAAS_LOGS_REASONING_EFFORT", ""))
                or default_effort
            ),
            specialist_soft_deadline_sec=cls._parse_positive_float(
                os.environ.get("MAAS_SPECIALIST_SOFT_DEADLINE_SEC", "")
            ),
        )


def get_maas_config() -> MAASConfig:
    """Load MAAS configuration from environment."""
    return MAASConfig.from_env()


def is_maas_enabled() -> bool:
    """Quick check for the MAAS feature flag."""
    return os.environ.get("COPILOT_MAAS_ENABLED", "false").lower() == "true"
