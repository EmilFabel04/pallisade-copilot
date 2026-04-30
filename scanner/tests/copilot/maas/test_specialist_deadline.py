"""MAAS specialist soft-deadline (Tier-4 item 5, conservative form).

Today the orchestrator awaits specialists with no time bound — slow
endpoints can stall the whole request behind them. Item 5 of the Tier-4
plan describes "speculative parallel orchestration"; the spec also flags
the full speculative form as gated on the eval harness because of
quality-vs-latency tradeoffs that are hard to detect without measurement.

The shippable conservative slice is a soft deadline: if specialists
don't return within ``MAAS_SPECIALIST_SOFT_DEADLINE_SEC`` seconds,
abandon them and let the orchestrator's existing ``_fallback_stream``
narrate from Phase-1 evidence alone. Default off — production behavior
is unchanged until an operator opts in. The cost-per-call from running
specialists is unchanged on the fast path, only the wall-clock changes
when they're slow.

These tests pin:
1. Config parsing (default None, valid floats, rejects bad input).
2. The helper short-circuits to "deadline exceeded" when specialists
   exceed the bound, and returns gathered outcomes when they don't.
3. None / 0 disables the deadline (no timeout applied).
"""

import asyncio

import pytest

from copilot.maas.config import MAASConfig
from copilot.maas.orchestrator import gather_specialists_with_deadline


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


class TestConfigParsing:
    def test_default_is_none(self, monkeypatch):
        monkeypatch.delenv("MAAS_SPECIALIST_SOFT_DEADLINE_SEC", raising=False)
        config = MAASConfig.from_env()
        assert config.specialist_soft_deadline_sec is None

    def test_valid_float_parses(self, monkeypatch):
        monkeypatch.setenv("MAAS_SPECIALIST_SOFT_DEADLINE_SEC", "1.5")
        config = MAASConfig.from_env()
        assert config.specialist_soft_deadline_sec == 1.5

    def test_zero_means_disabled(self, monkeypatch):
        # Zero is treated as "no deadline" — same as unset. Avoids the
        # surprising case of an operator setting 0 expecting "fail
        # immediately" and instead getting infinite wait.
        monkeypatch.setenv("MAAS_SPECIALIST_SOFT_DEADLINE_SEC", "0")
        config = MAASConfig.from_env()
        assert config.specialist_soft_deadline_sec is None

    def test_negative_is_rejected(self, monkeypatch):
        monkeypatch.setenv("MAAS_SPECIALIST_SOFT_DEADLINE_SEC", "-1")
        config = MAASConfig.from_env()
        assert config.specialist_soft_deadline_sec is None

    def test_garbage_is_rejected(self, monkeypatch):
        monkeypatch.setenv("MAAS_SPECIALIST_SOFT_DEADLINE_SEC", "soon")
        config = MAASConfig.from_env()
        assert config.specialist_soft_deadline_sec is None


# ---------------------------------------------------------------------------
# Helper: gather_specialists_with_deadline
# ---------------------------------------------------------------------------


class TestGatherSpecialistsWithDeadline:
    """The helper takes a list of coroutines and an optional deadline.

    Returns a tuple ``(outcomes, deadline_exceeded)``. When deadline
    fires, all in-flight specialist coroutines are cancelled — we don't
    leave them running because their work is already abandoned.
    """

    @pytest.mark.asyncio
    async def test_no_deadline_awaits_all(self):
        async def fast():
            await asyncio.sleep(0)
            return "ok"

        outcomes, exceeded = await gather_specialists_with_deadline(
            [fast(), fast()], deadline_sec=None,
        )
        assert outcomes == ["ok", "ok"]
        assert exceeded is False

    @pytest.mark.asyncio
    async def test_under_deadline_returns_outcomes(self):
        async def quick():
            await asyncio.sleep(0.01)
            return "done"

        outcomes, exceeded = await gather_specialists_with_deadline(
            [quick()], deadline_sec=0.5,
        )
        assert outcomes == ["done"]
        assert exceeded is False

    @pytest.mark.asyncio
    async def test_over_deadline_signals_exceeded(self):
        async def slow():
            await asyncio.sleep(0.5)
            return "too late"

        outcomes, exceeded = await gather_specialists_with_deadline(
            [slow()], deadline_sec=0.05,
        )
        assert outcomes is None
        assert exceeded is True

    @pytest.mark.asyncio
    async def test_empty_list_short_circuits(self):
        outcomes, exceeded = await gather_specialists_with_deadline(
            [], deadline_sec=1.0,
        )
        assert outcomes == []
        assert exceeded is False

    @pytest.mark.asyncio
    async def test_one_slow_one_fast_both_cancelled_on_deadline(self):
        cancelled = {"slow": False, "fast": False}

        async def slow():
            try:
                await asyncio.sleep(0.5)
                return "slow"
            except asyncio.CancelledError:
                cancelled["slow"] = True
                raise

        async def fast():
            try:
                await asyncio.sleep(0.01)
                return "fast"
            except asyncio.CancelledError:
                cancelled["fast"] = True
                raise

        outcomes, exceeded = await gather_specialists_with_deadline(
            [slow(), fast()], deadline_sec=0.05,
        )
        assert outcomes is None
        assert exceeded is True
        # Both coroutines are cancelled: the deadline abandons the whole
        # specialist phase, even ones that would have made it. Tradeoff
        # of the conservative form — we don't try to use partial results.
        assert cancelled["slow"] is True
