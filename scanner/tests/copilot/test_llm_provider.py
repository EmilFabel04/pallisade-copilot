"""Tests for the LLM provider abstraction.

Pin the provider-shaped behavior that ``copilot.llm`` will eventually
delegate to. Each provider's parse_response, request_kwargs, and
tool-loop wire format are exercised against canned response objects
that match what the real SDKs hand back.
"""

import json
from types import SimpleNamespace

from copilot.llm_provider import (
    AnthropicProvider,
    NormalizedResponse,
    NormalizedToolCall,
    OpenAIProvider,
    StopKind,
    StreamFinal,
    StreamTextDelta,
)


# ---------------------------------------------------------------------------
# Canned responses
# ---------------------------------------------------------------------------


def _anthropic_text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _anthropic_tool_use_block(*, id: str, name: str, input: dict):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def _anthropic_response(*, content, stop_reason, input_tokens=10, output_tokens=20):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )


def _openai_response(
    *,
    content,
    finish_reason,
    tool_calls=None,
    prompt_tokens=10,
    completion_tokens=20,
):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def _openai_tool_call(*, id: str, name: str, args_json: str):
    function = SimpleNamespace(name=name, arguments=args_json)
    return SimpleNamespace(id=id, type="function", function=function)


# ---------------------------------------------------------------------------
# Anthropic — parse_response
# ---------------------------------------------------------------------------


class TestAnthropicParseResponse:
    def test_completed_text_only(self):
        resp = _anthropic_response(
            content=[_anthropic_text_block("hello")],
            stop_reason="end_turn",
        )
        norm = AnthropicProvider().parse_response(resp)
        assert norm.text == "hello"
        assert norm.tool_calls == []
        assert norm.stop_kind is StopKind.COMPLETED
        assert norm.input_tokens == 10
        assert norm.output_tokens == 20
        assert norm.raw is resp

    def test_tool_use_extracts_id_name_args(self):
        resp = _anthropic_response(
            content=[
                _anthropic_text_block("I'll check that."),
                _anthropic_tool_use_block(
                    id="toolu_001",
                    name="query_warehouse",
                    input={"sql": "SELECT 1"},
                ),
            ],
            stop_reason="tool_use",
        )
        norm = AnthropicProvider().parse_response(resp)
        assert norm.text == "I'll check that."
        assert len(norm.tool_calls) == 1
        tc = norm.tool_calls[0]
        assert tc.id == "toolu_001"
        assert tc.name == "query_warehouse"
        assert tc.args == {"sql": "SELECT 1"}
        # args_raw is a deterministic JSON serialization of the dict
        # (Anthropic gives us a dict; we synthesize the string for
        # parity with OpenAI's exact-string preservation).
        assert tc.args_raw is not None
        assert json.loads(tc.args_raw) == {"sql": "SELECT 1"}
        assert norm.stop_kind is StopKind.TOOL_USE

    def test_max_tokens_canonicalized(self):
        resp = _anthropic_response(content=[], stop_reason="max_tokens")
        norm = AnthropicProvider().parse_response(resp)
        assert norm.stop_kind is StopKind.MAX_TOKENS

    def test_unknown_stop_reason_falls_to_other(self):
        resp = _anthropic_response(content=[], stop_reason="something_new")
        norm = AnthropicProvider().parse_response(resp)
        assert norm.stop_kind is StopKind.OTHER
        # Provider-native string is preserved for log readability.
        assert norm.raw_stop_reason == "something_new"


# ---------------------------------------------------------------------------
# Anthropic — request_kwargs
# ---------------------------------------------------------------------------


class TestAnthropicRequestKwargs:
    def test_basic_shape(self):
        kwargs = AnthropicProvider().request_kwargs(
            model="claude-sonnet-4-6",
            system="be helpful",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "query_warehouse"}],
            force_tool_first=False,
            reasoning_effort=None,
        )
        assert kwargs["model"] == "claude-sonnet-4-6"
        assert kwargs["system"] == "be helpful"
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
        assert kwargs["tools"] == [{"name": "query_warehouse"}]
        assert kwargs["max_tokens"] == 16384
        assert "tool_choice" not in kwargs

    def test_force_tool_first_sets_tool_choice(self):
        kwargs = AnthropicProvider().request_kwargs(
            model="claude-sonnet-4-6",
            system="x",
            messages=[],
            tools=[{"name": "t"}],
            force_tool_first=True,
            reasoning_effort=None,
        )
        assert kwargs["tool_choice"] == {"type": "any"}

    def test_force_tool_first_without_tools_is_noop(self):
        kwargs = AnthropicProvider().request_kwargs(
            model="claude-sonnet-4-6",
            system="x",
            messages=[],
            tools=None,
            force_tool_first=True,
            reasoning_effort=None,
        )
        assert "tool_choice" not in kwargs


# ---------------------------------------------------------------------------
# Anthropic — wire format
# ---------------------------------------------------------------------------


class TestAnthropicWireFormat:
    def test_assistant_turn_round_trips_content(self):
        raw = _anthropic_response(
            content=[_anthropic_text_block("ok"), _anthropic_tool_use_block(
                id="toolu_1", name="t", input={"k": 1},
            )],
            stop_reason="tool_use",
        )
        norm = AnthropicProvider().parse_response(raw)
        turn = AnthropicProvider().assistant_turn_for_tool_use(norm)
        assert turn["role"] == "assistant"
        # Built from normalized fields (works for both streaming and
        # non-streaming) — text + tool_use blocks reconstructed.
        assert turn["content"] == [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "toolu_1", "name": "t", "input": {"k": 1}},
        ]

    def test_assistant_turn_omits_text_when_empty(self):
        raw = _anthropic_response(
            content=[_anthropic_tool_use_block(id="toolu_1", name="t", input={})],
            stop_reason="tool_use",
        )
        norm = AnthropicProvider().parse_response(raw)
        turn = AnthropicProvider().assistant_turn_for_tool_use(norm)
        # No text block when the model produced none.
        assert turn["content"] == [
            {"type": "tool_use", "id": "toolu_1", "name": "t", "input": {}},
        ]

    def test_tool_result_message_shape(self):
        msg = AnthropicProvider().tool_result_message(
            "toolu_1", '{"status": "ok"}',
        )
        assert msg == {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": '{"status": "ok"}',
        }


# ---------------------------------------------------------------------------
# OpenAI — parse_response
# ---------------------------------------------------------------------------


class TestOpenAIParseResponse:
    def test_completed_text_only(self):
        resp = _openai_response(content="hello", finish_reason="stop")
        norm = OpenAIProvider().parse_response(resp)
        assert norm.text == "hello"
        assert norm.tool_calls == []
        assert norm.stop_kind is StopKind.COMPLETED
        assert norm.input_tokens == 10
        assert norm.output_tokens == 20

    def test_tool_calls_finish_reason(self):
        raw_args = json.dumps({"sql": "SELECT 1"})
        resp = _openai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[
                _openai_tool_call(
                    id="call_001",
                    name="query_warehouse",
                    args_json=raw_args,
                )
            ],
        )
        norm = OpenAIProvider().parse_response(resp)
        assert norm.text == ""
        assert len(norm.tool_calls) == 1
        tc = norm.tool_calls[0]
        assert tc.id == "call_001"
        assert tc.name == "query_warehouse"
        assert tc.args == {"sql": "SELECT 1"}
        # args_raw preserves the EXACT bytes the model produced, not a
        # re-serialization.
        assert tc.args_raw == raw_args
        assert norm.stop_kind is StopKind.TOOL_USE

    def test_malformed_arguments_fall_back_to_empty_dict(self):
        # Mirrors the long-standing fallback in _chat_openai. Malformed
        # arguments must NOT crash the parser; the loop will reject
        # downstream if needed.
        resp = _openai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[_openai_tool_call(
                id="call_x", name="t", args_json="{not-json",
            )],
        )
        norm = OpenAIProvider().parse_response(resp)
        assert norm.tool_calls[0].args == {}

    def test_length_canonicalized_to_max_tokens(self):
        resp = _openai_response(content="...", finish_reason="length")
        norm = OpenAIProvider().parse_response(resp)
        assert norm.stop_kind is StopKind.MAX_TOKENS


# ---------------------------------------------------------------------------
# OpenAI — request_kwargs
# ---------------------------------------------------------------------------


class TestOpenAIRequestKwargs:
    def test_legacy_model_uses_max_tokens(self):
        kwargs = OpenAIProvider().request_kwargs(
            model="gpt-4-turbo",
            system="ignored",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            force_tool_first=False,
            reasoning_effort=None,
        )
        assert kwargs["max_tokens"] == 16384
        assert "max_completion_tokens" not in kwargs

    def test_gpt5_uses_max_completion_tokens(self):
        kwargs = OpenAIProvider().request_kwargs(
            model="gpt-5.4",
            system="ignored",
            messages=[],
            tools=None,
            force_tool_first=False,
            reasoning_effort=None,
        )
        assert kwargs["max_completion_tokens"] == 16384
        assert "max_tokens" not in kwargs

    def test_force_tool_first_sets_required(self):
        kwargs = OpenAIProvider().request_kwargs(
            model="gpt-5.4",
            system="x",
            messages=[],
            tools=[{"type": "function"}],
            force_tool_first=True,
            reasoning_effort=None,
        )
        assert kwargs["tool_choice"] == "required"

    def test_reasoning_effort_dropped_when_tools_present(self):
        # The whole reason commit 3700f2b exists. Pin it.
        kwargs = OpenAIProvider().request_kwargs(
            model="gpt-5.4",
            system="x",
            messages=[],
            tools=[{"type": "function"}],
            force_tool_first=False,
            reasoning_effort="medium",
        )
        assert "reasoning_effort" not in kwargs

    def test_reasoning_effort_set_when_no_tools(self):
        kwargs = OpenAIProvider().request_kwargs(
            model="gpt-5.4",
            system="x",
            messages=[],
            tools=None,
            force_tool_first=False,
            reasoning_effort="medium",
        )
        assert kwargs["reasoning_effort"] == "medium"

    def test_reasoning_effort_off_when_unsupported(self):
        # Some legacy models reject the param even with no tools.
        kwargs = OpenAIProvider(supports_reasoning_effort=False).request_kwargs(
            model="gpt-4-turbo",
            system="x",
            messages=[],
            tools=None,
            force_tool_first=False,
            reasoning_effort="medium",
        )
        assert "reasoning_effort" not in kwargs


# ---------------------------------------------------------------------------
# OpenAI — wire format
# ---------------------------------------------------------------------------


class TestOpenAIWireFormat:
    def test_assistant_turn_serializes_tool_calls(self):
        raw = _openai_response(
            content="thinking",
            finish_reason="tool_calls",
            tool_calls=[
                _openai_tool_call(id="call_1", name="t", args_json='{"k":1}'),
                _openai_tool_call(id="call_2", name="u", args_json='{}'),
            ],
        )
        norm = OpenAIProvider().parse_response(raw)
        turn = OpenAIProvider().assistant_turn_for_tool_use(norm)
        assert turn["role"] == "assistant"
        assert turn["content"] == "thinking"
        # Tool-call args round-trip the EXACT JSON string the model
        # produced (args_raw), not a re-serialization. Pinning this
        # because re-serializing whitespace/precision is the kind of
        # subtle drift that confuses some tool consumers.
        assert turn["tool_calls"] == [
            {"id": "call_1", "type": "function",
             "function": {"name": "t", "arguments": '{"k":1}'}},
            {"id": "call_2", "type": "function",
             "function": {"name": "u", "arguments": '{}'}},
        ]

    def test_assistant_turn_collapses_empty_text_to_none(self):
        raw = _openai_response(
            content="",
            finish_reason="tool_calls",
            tool_calls=[_openai_tool_call(id="c1", name="t", args_json='{}')],
        )
        norm = OpenAIProvider().parse_response(raw)
        turn = OpenAIProvider().assistant_turn_for_tool_use(norm)
        # OpenAI prefers None over "" for content when only tool_calls
        # are present — the streaming path always returned "" or None
        # depending on accumulator state, leading to inconsistent
        # message shapes. Pin the unified behavior.
        assert turn["content"] is None

    def test_tool_result_message_shape(self):
        msg = OpenAIProvider().tool_result_message(
            "call_1", '{"status": "ok"}',
        )
        assert msg == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"status": "ok"}',
        }


# ---------------------------------------------------------------------------
# Cross-provider invariants
# ---------------------------------------------------------------------------


class TestAnthropicStream:
    """``iter_stream`` collapses Anthropic SDK events into canonical
    StreamTextDelta / StreamFinal events."""

    def _stub_stream(self, *, deltas, final_message):
        """Build a stream stand-in that's iterable and exposes
        ``get_final_message``. Mirrors the real SDK's context shape."""
        events = [
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text=t),
            )
            for t in deltas
        ]

        class _Stream:
            def __iter__(self_):
                return iter(events)

            def get_final_message(self_):
                return final_message

        return _Stream()

    def test_text_deltas_yield_in_order(self):
        stream = self._stub_stream(
            deltas=["Hel", "lo, ", "world"],
            final_message=_anthropic_response(
                content=[_anthropic_text_block("Hello, world")],
                stop_reason="end_turn",
            ),
        )
        events = list(AnthropicProvider().iter_stream(stream))
        assert len(events) == 4
        assert isinstance(events[0], StreamTextDelta)
        assert events[0].text == "Hel"
        assert isinstance(events[3], StreamFinal)
        assert events[3].response.text == "Hello, world"
        assert events[3].response.stop_kind is StopKind.COMPLETED

    def test_tool_use_finalization_carries_tool_calls(self):
        stream = self._stub_stream(
            deltas=["thinking..."],
            final_message=_anthropic_response(
                content=[
                    _anthropic_text_block("thinking..."),
                    _anthropic_tool_use_block(
                        id="toolu_1",
                        name="query_warehouse",
                        input={"sql": "SELECT 1"},
                    ),
                ],
                stop_reason="tool_use",
            ),
        )
        events = list(AnthropicProvider().iter_stream(stream))
        final = events[-1]
        assert isinstance(final, StreamFinal)
        assert final.response.stop_kind is StopKind.TOOL_USE
        assert len(final.response.tool_calls) == 1
        assert final.response.tool_calls[0].name == "query_warehouse"
        assert final.response.tool_calls[0].args == {"sql": "SELECT 1"}

    def test_non_text_deltas_are_dropped(self):
        # Only content_block_delta events with text contribute. Other
        # SDK events (message_start, content_block_stop) flow past the
        # filter without becoming StreamTextDelta.
        events_with_noise = [
            SimpleNamespace(type="message_start"),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(text="x"),
            ),
            SimpleNamespace(type="content_block_stop"),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(),  # delta with no .text attr
            ),
        ]

        class _Stream:
            def __iter__(self_):
                return iter(events_with_noise)

            def get_final_message(self_):
                return _anthropic_response(
                    content=[_anthropic_text_block("x")],
                    stop_reason="end_turn",
                )

        events = list(AnthropicProvider().iter_stream(_Stream()))
        text_events = [e for e in events if isinstance(e, StreamTextDelta)]
        assert len(text_events) == 1
        assert text_events[0].text == "x"


class TestOpenAIStream:
    """``iter_stream`` accumulates partial chunks into a final response.

    OpenAI emits tool-call args as multiple chunks indexed by
    ``tc_delta.index``; the provider must reassemble them.
    """

    def _chunk(self, *, delta_content=None, tool_call_deltas=None,
               finish_reason=None, usage=None):
        delta = SimpleNamespace(
            content=delta_content,
            tool_calls=tool_call_deltas,
        )
        choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
        chunk = SimpleNamespace(choices=[choice])
        if usage is not None:
            chunk.usage = usage
        return chunk

    def _tc_delta(self, *, index, id=None, name=None, args_chunk=None):
        function = SimpleNamespace(
            name=name,
            arguments=args_chunk,
        ) if (name or args_chunk) else None
        return SimpleNamespace(index=index, id=id, function=function)

    def test_text_only_completion(self):
        stream = iter([
            self._chunk(delta_content="Hel"),
            self._chunk(delta_content="lo"),
            self._chunk(finish_reason="stop"),
        ])
        events = list(OpenAIProvider().iter_stream(stream))
        text_events = [e for e in events if isinstance(e, StreamTextDelta)]
        finals = [e for e in events if isinstance(e, StreamFinal)]
        assert "".join(e.text for e in text_events) == "Hello"
        assert len(finals) == 1
        assert finals[0].response.text == "Hello"
        assert finals[0].response.stop_kind is StopKind.COMPLETED

    def test_tool_call_args_assembled_across_chunks(self):
        # Realistic OpenAI streaming: tool call comes in as id+name in
        # chunk 1, then args fragments across chunks 2-4.
        stream = iter([
            self._chunk(tool_call_deltas=[
                self._tc_delta(index=0, id="call_1", name="query_warehouse"),
            ]),
            self._chunk(tool_call_deltas=[
                self._tc_delta(index=0, args_chunk='{"sq'),
            ]),
            self._chunk(tool_call_deltas=[
                self._tc_delta(index=0, args_chunk='l": "SELE'),
            ]),
            self._chunk(tool_call_deltas=[
                self._tc_delta(index=0, args_chunk='CT 1"}'),
            ]),
            self._chunk(finish_reason="tool_calls"),
        ])
        events = list(OpenAIProvider().iter_stream(stream))
        final = events[-1]
        assert isinstance(final, StreamFinal)
        assert final.response.stop_kind is StopKind.TOOL_USE
        tcs = final.response.tool_calls
        assert len(tcs) == 1
        assert tcs[0].id == "call_1"
        assert tcs[0].name == "query_warehouse"
        assert tcs[0].args == {"sql": "SELECT 1"}
        # ``args_raw`` preserves the exact assembled JSON string for
        # round-trip into the next assistant turn.
        assert tcs[0].args_raw == '{"sql": "SELECT 1"}'

    def test_usage_accumulates_across_chunks(self):
        stream = iter([
            self._chunk(delta_content="x"),
            self._chunk(
                finish_reason="stop",
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            ),
        ])
        events = list(OpenAIProvider().iter_stream(stream))
        final = events[-1]
        assert final.response.input_tokens == 10
        assert final.response.output_tokens == 5

    def test_multiple_tool_calls_indexed(self):
        # Two parallel tool calls — ``index`` distinguishes them. The
        # provider must keep their accumulators separate.
        stream = iter([
            self._chunk(tool_call_deltas=[
                self._tc_delta(index=0, id="c1", name="a"),
                self._tc_delta(index=1, id="c2", name="b"),
            ]),
            self._chunk(tool_call_deltas=[
                self._tc_delta(index=0, args_chunk='{"x":1}'),
                self._tc_delta(index=1, args_chunk='{"y":2}'),
            ]),
            self._chunk(finish_reason="tool_calls"),
        ])
        events = list(OpenAIProvider().iter_stream(stream))
        final = events[-1]
        assert len(final.response.tool_calls) == 2
        assert {tc.name for tc in final.response.tool_calls} == {"a", "b"}
        names_to_args = {tc.name: tc.args for tc in final.response.tool_calls}
        assert names_to_args == {"a": {"x": 1}, "b": {"y": 2}}


class TestCrossProviderInvariants:
    def test_completed_stop_kind_consistent_across_providers(self):
        a_norm = AnthropicProvider().parse_response(
            _anthropic_response(content=[], stop_reason="end_turn"),
        )
        o_norm = OpenAIProvider().parse_response(
            _openai_response(content="", finish_reason="stop"),
        )
        assert a_norm.stop_kind is o_norm.stop_kind is StopKind.COMPLETED

    def test_tool_use_stop_kind_consistent_across_providers(self):
        a_norm = AnthropicProvider().parse_response(
            _anthropic_response(content=[], stop_reason="tool_use"),
        )
        o_norm = OpenAIProvider().parse_response(
            _openai_response(content="", finish_reason="tool_calls"),
        )
        assert a_norm.stop_kind is o_norm.stop_kind is StopKind.TOOL_USE

    def test_append_tool_use_round_anthropic_wraps_results_in_one_user_turn(self):
        raw = _anthropic_response(
            content=[_anthropic_tool_use_block(id="toolu_1", name="t", input={})],
            stop_reason="tool_use",
        )
        norm = AnthropicProvider().parse_response(raw)
        result_block = AnthropicProvider().tool_result_message(
            "toolu_1", '{"ok":true}',
        )
        msgs: list = []
        AnthropicProvider().append_tool_use_round(msgs, norm, [result_block])
        # Two turns: assistant (content blocks), then a single user turn
        # whose content is the list of result blocks. Anthropic rejects
        # tool results split across multiple user messages, so the
        # wrapping is load-bearing.
        assert len(msgs) == 2
        assert msgs[0]["role"] == "assistant"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == [result_block]

    def test_append_tool_use_round_openai_emits_tool_messages(self):
        raw = _openai_response(
            content="thinking",
            finish_reason="tool_calls",
            tool_calls=[_openai_tool_call(
                id="call_1", name="t", args_json="{}",
            )],
        )
        norm = OpenAIProvider().parse_response(raw)
        result = OpenAIProvider().tool_result_message("call_1", '{"ok":true}')
        msgs: list = []
        OpenAIProvider().append_tool_use_round(msgs, norm, [result])
        # OpenAI: assistant turn (with tool_calls field), then one
        # top-level ``role: tool`` message per result. Multiple results
        # become multiple top-level messages — no wrapping.
        assert len(msgs) == 2
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["tool_calls"][0]["id"] == "call_1"
        assert msgs[1] == result

    def test_normalized_tool_call_args_are_already_dicts(self):
        """A loop using NormalizedToolCall.args directly must not need
        to know whether the source was Anthropic (already dict) or
        OpenAI (was a JSON string). Pin the dict invariant."""
        a_norm = AnthropicProvider().parse_response(
            _anthropic_response(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_x",
                        name="t",
                        input={"k": 1},
                    ),
                ],
                stop_reason="tool_use",
            ),
        )
        o_norm = OpenAIProvider().parse_response(
            _openai_response(
                content=None,
                finish_reason="tool_calls",
                tool_calls=[_openai_tool_call(
                    id="call_x", name="t", args_json='{"k": 1}',
                )],
            ),
        )
        assert a_norm.tool_calls[0].args == {"k": 1}
        assert o_norm.tool_calls[0].args == {"k": 1}
        assert isinstance(a_norm.tool_calls[0].args, dict)
        assert isinstance(o_norm.tool_calls[0].args, dict)
