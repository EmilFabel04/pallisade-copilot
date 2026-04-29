"""CopilotResponse must carry a meaningful `stop_reason` and `iterations_used`
at every return path, so the frontend / observability layer can tell why a
chat turn ended (natural completion vs hit-the-cap vs error vs needs-confirmation)
without guessing from raw provider strings."""
import re

from copilot.llm import CopilotResponse, StopReason, MockCopilotLLM, Message
from copilot.context_builder import CopilotContext


# -- Dataclass shape ----------------------------------------------------------


def test_copilot_response_has_stop_reason_and_iterations_used_fields():
    r = CopilotResponse(content="hi")
    assert hasattr(r, "stop_reason")
    assert hasattr(r, "iterations_used")
    assert r.stop_reason == ""
    assert r.iterations_used == 0


def test_stop_reason_constants_are_distinct_strings():
    values = {
        StopReason.COMPLETED,
        StopReason.MAX_ITERATIONS,
        StopReason.MAX_TOKENS,
        StopReason.CONFIRMATION_REQUIRED,
        StopReason.ERROR,
        StopReason.UNKNOWN,
    }
    assert len(values) == 6
    for v in values:
        assert isinstance(v, str) and v


# -- Mock chat sets stop_reason -----------------------------------------------


async def _run_mock(query: str) -> CopilotResponse:
    llm = MockCopilotLLM.__new__(MockCopilotLLM)
    llm.model = "mock"
    llm.client = None
    ctx = CopilotContext(org_id="org_test")
    return await llm.chat([Message(role="user", content=query)], ctx)


def test_mock_chat_returns_completed_for_upstream_query():
    import asyncio
    r = asyncio.run(_run_mock("show upstream of orders"))
    assert r.stop_reason == StopReason.COMPLETED


def test_mock_chat_returns_completed_for_downstream_query():
    import asyncio
    r = asyncio.run(_run_mock("downstream impact"))
    assert r.stop_reason == StopReason.COMPLETED


def test_mock_chat_returns_completed_for_generic_query():
    import asyncio
    r = asyncio.run(_run_mock("hello"))
    assert r.stop_reason == StopReason.COMPLETED


# -- Source-level: every return path sets a stop_reason -----------------------


def _read_llm_source() -> str:
    import copilot.llm as mod
    return open(mod.__file__).read()


def test_every_return_copilot_response_call_sets_stop_reason():
    """Static check on llm.py: every `return CopilotResponse(...)` block must
    set `stop_reason=`. This is the regression guard that prevents someone
    adding a new return path that emits an empty stop_reason to the frontend."""
    src = _read_llm_source()
    # Strip f-strings so braces inside content=f"...{e}..." don't break our
    # naive call-block matcher.
    src_no_fstrings = re.sub(r'f"[^"]*"', '""', src)
    blocks = re.findall(
        r'return CopilotResponse\((.*?)\n\s*\)', src_no_fstrings, re.DOTALL,
    )
    assert blocks, "no CopilotResponse returns found — test broken"
    bad = [b for b in blocks if "stop_reason" not in b]
    assert not bad, f"{len(bad)} return paths missing stop_reason: {bad[:1]}"


def test_every_stream_done_event_carries_iterations_used():
    """The streaming chat methods MUST emit `iterations_used` in every `done`
    event so the frontend can show 'used N of M iterations' on completion."""
    src = _read_llm_source()
    blocks = re.findall(r'StreamEvent\("done",\s*(\{[^}]+?\})\)', src, re.DOTALL)
    assert blocks, "no done events found — test broken"
    bad = [b for b in blocks if "iterations_used" not in b]
    assert not bad, f"{len(bad)} done events missing iterations_used: {bad[:1]}"


def test_every_stream_done_event_carries_stop_reason():
    src = _read_llm_source()
    blocks = re.findall(r'StreamEvent\("done",\s*(\{[^}]+?\})\)', src, re.DOTALL)
    assert blocks
    bad = [b for b in blocks if "stop_reason" not in b]
    assert not bad, f"{len(bad)} done events missing stop_reason: {bad[:1]}"


# -- Helper response builder uses canonical constants -------------------------


def test_max_iterations_response_sets_canonical_stop_reason_and_count():
    """`_build_max_iterations_response` must report the exact iteration count
    the chat loop hit, so observability can distinguish 'used 15 of 15 iterations'
    from 'errored on iteration 3'."""
    llm = MockCopilotLLM.__new__(MockCopilotLLM)
    llm.model = "mock"
    r = llm._build_max_iterations_response(
        all_tool_calls=[],
        total_input_tokens=100,
        total_output_tokens=50,
        accumulated_text=["partial answer"],
        iterations_used=15,
    )
    assert r.stop_reason == StopReason.MAX_ITERATIONS
    assert r.iterations_used == 15
