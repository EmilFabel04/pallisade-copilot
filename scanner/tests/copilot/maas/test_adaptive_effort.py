"""Adaptive reasoning-effort escalation for MAAS specialists.

When a specialist's first attempt fails verification, the orchestrator
should retry once at the next reasoning-effort tier before falling back.
The ladder is ``minimal → low → medium → high``; an attempt at the top
tier doesn't escalate further.

Scope: this only applies to specialist clients (SQL, Logs). The narration
LLM uses Chat Completions with tools, where ``reasoning_effort`` is
silently dropped (see commit ``3700f2b``), so escalation there has no
effect until the /v1/responses migration lands.
"""

import pytest

from copilot.maas.orchestrator import EFFORT_LADDER, _next_effort


class TestEffortLadder:
    def test_minimal_escalates_to_low(self):
        assert _next_effort("minimal") == "low"

    def test_low_escalates_to_medium(self):
        assert _next_effort("low") == "medium"

    def test_medium_escalates_to_high(self):
        assert _next_effort("medium") == "high"

    def test_high_does_not_escalate(self):
        assert _next_effort("high") is None

    def test_none_starts_at_medium(self):
        # When no effort was configured, escalation should pick a sensible
        # mid-ladder default rather than guessing the bottom.
        assert _next_effort(None) == "medium"

    def test_unknown_falls_back_to_medium(self):
        assert _next_effort("turbo") == "medium"

    def test_ladder_is_canonical(self):
        assert EFFORT_LADDER == ["minimal", "low", "medium", "high"]


class TestChatCompletionEffortKwarg:
    """``reasoning_effort`` should be overridable per-call.

    Today it's only set on the client at construction. Item 1 requires
    transient overrides for the escalation retry, so the kwarg must reach
    the request payload without mutating the client.
    """

    @pytest.mark.asyncio
    async def test_per_call_effort_overrides_instance(self):
        from copilot.maas.client import RunPodClient
        from unittest.mock import AsyncMock, patch

        client = RunPodClient(
            base_url="https://api.example.com",
            api_key="k",
            model_name="gpt-5.4",
            reasoning_effort="low",
        )

        captured = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {
                    "choices": [
                        {"message": {"content": "{}"}, "finish_reason": "stop"}
                    ],
                    "usage": {},
                }

        async def fake_post(url, json):
            captured["payload"] = json
            return _Resp()

        with patch.object(client, "_get_client") as gc:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=fake_post)
            gc.return_value = mock_http
            await client.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                reasoning_effort="high",
            )

        assert captured["payload"]["reasoning_effort"] == "high"
        # Instance default unchanged
        assert client.reasoning_effort == "low"


class TestSpecialistEscalation:
    """End-to-end: specialist.call passes reasoning_effort to the client."""

    @pytest.mark.asyncio
    async def test_call_propagates_reasoning_effort(self):
        from typing import Type
        from unittest.mock import AsyncMock
        from pydantic import BaseModel

        from copilot.maas.specialists.base import (
            BaseSpecialist,
            clear_specialist_cache,
        )

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

        await _Stub(client).call(
            evidence="ev",
            query="q",
            reasoning_effort="high",
        )
        kwargs = client.chat_completion.await_args.kwargs
        assert kwargs["reasoning_effort"] == "high"
