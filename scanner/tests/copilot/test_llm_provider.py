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
        assert norm.tool_calls == [NormalizedToolCall(
            id="toolu_001",
            name="query_warehouse",
            args={"sql": "SELECT 1"},
        )]
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
                id="toolu_1", name="t", input={},
            )],
            stop_reason="tool_use",
        )
        norm = AnthropicProvider().parse_response(raw)
        turn = AnthropicProvider().assistant_turn_for_tool_use(norm)
        assert turn["role"] == "assistant"
        # Anthropic re-accepts its own content-blocks list verbatim.
        assert turn["content"] is raw.content

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
        resp = _openai_response(
            content=None,
            finish_reason="tool_calls",
            tool_calls=[
                _openai_tool_call(
                    id="call_001",
                    name="query_warehouse",
                    args_json=json.dumps({"sql": "SELECT 1"}),
                )
            ],
        )
        norm = OpenAIProvider().parse_response(resp)
        assert norm.text == ""
        assert norm.tool_calls == [NormalizedToolCall(
            id="call_001",
            name="query_warehouse",
            args={"sql": "SELECT 1"},
        )]
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
        assert turn["tool_calls"] == [
            {"id": "call_1", "type": "function",
             "function": {"name": "t", "arguments": '{"k":1}'}},
            {"id": "call_2", "type": "function",
             "function": {"name": "u", "arguments": '{}'}},
        ]

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
