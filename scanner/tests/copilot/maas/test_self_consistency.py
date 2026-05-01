"""Self-consistency for high-stakes SQL specialist calls.

For complex investigative queries (multi-table comparisons, joins,
debugging questions), the SQL specialist runs twice in parallel —
once at temperature=0.0 and once at temperature=0.7. The orchestrator
picks the result that passes the verifier with the higher confidence;
disagreements are recorded in the trace.

Easy queries take a single call. The fan-out is gated by a heuristic
so the doubled cost only applies where it actually buys quality.
"""

from typing import Type
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from copilot.maas.orchestrator import _is_high_stakes
from copilot.maas.specialists.base import BaseSpecialist, clear_specialist_cache


class TestHighStakesHeuristic:
    """``_is_high_stakes(query)`` decides whether the fan-out fires."""

    @pytest.mark.parametrize("query", [
        "compare order volume across regions for Q4",
        "join orders with users to find inactive accounts",
        "what's the difference between the staging and prod tables?",
        "why did my pipeline fail last night?",  # investigation
        "investigate the spike in null values yesterday",
        "find users who placed orders versus those who didn't",
    ])
    def test_complex_queries_are_high_stakes(self, query):
        assert _is_high_stakes(query), f"expected high-stakes for: {query!r}"

    @pytest.mark.parametrize("query", [
        "how many orders are there?",
        "show me the top 10 customers",
        "count rows in events",
        "list all tables",
        "what's the latest record?",
    ])
    def test_simple_queries_are_not_high_stakes(self, query):
        assert not _is_high_stakes(query), (
            f"unexpectedly high-stakes: {query!r}"
        )

    def test_empty_query_is_not_high_stakes(self):
        assert not _is_high_stakes("")


class TestTemperatureKwargPropagation:
    """``BaseSpecialist.call`` must accept ``temperature`` and forward it.

    Self-consistency relies on the same prompt going to the LLM at two
    different temperatures, so a hardcoded ``temperature=0.0`` in the
    base class would defeat the whole feature.
    """

    @pytest.mark.asyncio
    async def test_call_propagates_temperature(self):
        class _Echo(BaseModel):
            answer: str

        class _Stub(BaseSpecialist):
            @property
            def name(self) -> str:
                return "stub"

            @property
            def response_model(self) -> Type[BaseModel]:
                return _Echo

            def build_messages(self, evidence, query, **kwargs):
                return [{"role": "user", "content": evidence}]

        clear_specialist_cache()
        client = AsyncMock()
        client.model_name = "gpt-5.4"
        client.chat_completion = AsyncMock(
            return_value={"content": '{"answer": "ok"}', "latency_ms": 1}
        )

        await _Stub(client).call(evidence="ev", query="q", temperature=0.7)
        kwargs = client.chat_completion.await_args.kwargs
        assert kwargs["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_temperature_partitions_cache(self):
        """Different temperatures must not share a cache slot.

        Otherwise the second self-consistency call returns the cached
        first result and the temperature variation is illusory.
        """

        class _Echo(BaseModel):
            answer: str

        class _Stub(BaseSpecialist):
            @property
            def name(self) -> str:
                return "stub"

            @property
            def response_model(self) -> Type[BaseModel]:
                return _Echo

            def build_messages(self, evidence, query, **kwargs):
                return [{"role": "user", "content": evidence}]

        clear_specialist_cache()
        client = AsyncMock()
        client.model_name = "gpt-5.4"
        client.chat_completion = AsyncMock(
            return_value={"content": '{"answer": "ok"}', "latency_ms": 1}
        )

        await _Stub(client).call(evidence="ev", query="q", temperature=0.0)
        await _Stub(client).call(evidence="ev", query="q", temperature=0.7)
        # Two distinct LLM calls — cache must not have collapsed them.
        assert client.chat_completion.await_count == 2


class TestSpecialistInvocationSchema:
    """``self_consistency_used`` and ``self_consistency_picked`` are
    surfaced through the trace so we can measure how often the fan-out
    fires and whether it tends to favor A or B in production."""

    def test_default_invocation_has_no_self_consistency(self):
        from copilot.maas.schemas import SpecialistInvocation

        inv = SpecialistInvocation(specialist="sql", latency_ms=10, success=True)
        assert inv.self_consistency_used is False
        assert inv.self_consistency_picked is None

    def test_invocation_records_picked_branch(self):
        from copilot.maas.schemas import SpecialistInvocation

        inv = SpecialistInvocation(
            specialist="sql",
            latency_ms=42,
            success=True,
            self_consistency_used=True,
            self_consistency_picked="B",
        )
        assert inv.self_consistency_used is True
        assert inv.self_consistency_picked == "B"
