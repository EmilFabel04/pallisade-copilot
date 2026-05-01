"""Per-pipeline isolation for the MAAS specialist response cache.

The module-level ``_response_cache`` in ``copilot.maas.specialists.base`` is
shared across every running specialist call. Two pipeline profiles MUST NOT
see each other's cached responses, even when the same specialist is asked
the same question with the same prompt — the data behind that prompt may
differ entirely between profiles.

These tests pin the isolation behavior so a future refactor can't quietly
collapse the cache key back to a global namespace.
"""

from typing import Type
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from copilot.maas.specialists.base import BaseSpecialist, clear_specialist_cache


class _Echo(BaseModel):
    answer: str


class _StubSpecialist(BaseSpecialist):
    """Minimal concrete specialist for cache-key tests.

    ``build_messages`` is deterministic so the cache hash for a given
    ``(evidence, query)`` pair is identical across calls — that's the whole
    point: only the pipeline_id should distinguish them.
    """

    @property
    def name(self) -> str:
        return "stub"

    @property
    def response_model(self) -> Type[BaseModel]:
        return _Echo

    def build_messages(self, evidence: str, query: str, **kwargs) -> list:
        return [
            {"role": "system", "content": "echo"},
            {"role": "user", "content": f"{evidence}|{query}"},
        ]


def _make_specialist():
    client = AsyncMock()
    client.model_name = "stub-model"
    client.chat_completion = AsyncMock(
        return_value={"content": '{"answer": "ok"}', "latency_ms": 1}
    )
    return _StubSpecialist(client), client


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_specialist_cache()
    yield
    clear_specialist_cache()


@pytest.mark.asyncio
async def test_cache_hit_within_same_pipeline():
    """Same prompt + same pipeline_id → cache hit, no second LLM call."""
    specialist, client = _make_specialist()

    await specialist.call(evidence="ev", query="q", pipeline_id="pipe-A")
    await specialist.call(evidence="ev", query="q", pipeline_id="pipe-A")

    assert client.chat_completion.await_count == 1


@pytest.mark.asyncio
async def test_cache_miss_across_pipelines():
    """Same prompt + different pipeline_id → cache miss, second LLM call fires.

    This is the regression case for cross-pipeline data leak: pipeline A
    must never serve pipeline B a cached response, even when the prompts
    are textually identical.
    """
    specialist, client = _make_specialist()

    await specialist.call(evidence="ev", query="q", pipeline_id="pipe-A")
    await specialist.call(evidence="ev", query="q", pipeline_id="pipe-B")

    assert client.chat_completion.await_count == 2


@pytest.mark.asyncio
async def test_no_pipeline_id_uses_default_bucket():
    """Calls without pipeline_id share a single default bucket.

    Pre-existing callers that haven't been threaded with pipeline_id yet
    should keep working (still cache, just under a default key).
    """
    specialist, client = _make_specialist()

    await specialist.call(evidence="ev", query="q")
    await specialist.call(evidence="ev", query="q")

    assert client.chat_completion.await_count == 1
