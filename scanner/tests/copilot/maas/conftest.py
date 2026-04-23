"""Shared fixtures for MAAS tests."""

from unittest.mock import MagicMock
from typing import Dict, List, Optional, Set

from copilot.intent import Intent, IntentResult, ScoredIntent
from copilot.context_builder import CopilotContext, TableSchema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_intent_result(
    primary: Intent = Intent.INFO,
    primary_score: float = 0.9,
    secondary: Optional[Intent] = None,
    secondary_score: float = 0.5,
    target_hint: Optional[str] = None,
    target_entities: Optional[List[str]] = None,
) -> IntentResult:
    """Create an IntentResult for testing."""
    result = IntentResult(
        primary=ScoredIntent(intent=primary, score=primary_score),
        secondary=ScoredIntent(intent=secondary, score=secondary_score) if secondary else None,
        target_hint=target_hint,
        target_entities=target_entities or [],
    )
    return result


def make_context(
    query: str = "show me row counts",
    warehouse_schema: Optional[Dict] = None,
    integration_types: Optional[Set[str]] = None,
    available_tools: Optional[Set[str]] = None,
) -> MagicMock:
    """Create a mock CopilotContext for testing."""
    ctx = MagicMock(spec=CopilotContext)
    ctx.query = query
    ctx.warehouse_schema = warehouse_schema or {}
    ctx.integration_types = integration_types or {"bigquery"}
    ctx.available_tools = available_tools or set()

    def _has_warehouse():
        return bool(ctx.warehouse_schema)
    ctx.has_warehouse = _has_warehouse
    return ctx


def make_table_schema(name: str, columns: List[Dict[str, str]], dataset: str = "analytics") -> TableSchema:
    """Create a TableSchema for testing."""
    return TableSchema(name=name, columns=columns, dataset=dataset)
