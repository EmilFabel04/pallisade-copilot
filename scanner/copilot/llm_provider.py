"""Provider abstraction for the copilot's LLM call path.

Today ``copilot.llm`` has four near-duplicate chat methods — Anthropic
non-streaming, Anthropic streaming, OpenAI non-streaming, OpenAI
streaming — each running the same tool-loop with provider-specific
quirks scattered through the body. Drift between the four is where
provider-specific bugs hide (mid-loop role injection, tool-result
serialization, stop-reason names — see commit ``48ccabb``'s history).

This module collapses the *provider-specific* parts into a small
``LLMProvider`` Protocol with two concrete implementations. The tool
loop itself stays in ``llm.py`` for now and pulls the provider-shaped
bits through this interface; later passes can migrate streaming and
unify the loop body.

Scope:

* **Request shape**: ``request_kwargs`` returns the dict to pass to the
  client's create() method. Hides the system-message-vs-system-param,
  ``max_tokens`` vs ``max_completion_tokens``, ``tool_choice`` shape,
  and reasoning-effort gating.
* **Response normalization**: ``parse_response`` returns a
  ``NormalizedResponse`` with text, tool calls (already parsed),
  canonical stop kind, and token counts.
* **Tool-loop wire format**: ``assistant_turn_for_tool_use`` and
  ``tool_result_message`` produce the messages the loop appends back to
  history when continuing past a tool call.

Out of scope (handled by the loop in ``llm.py``):

* MCP integration and tool execution.
* Adjacent-path steering and root-cause injection.
* Iteration tracking, accumulated text, ``CopilotResponse`` shaping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Protocol


# ---------------------------------------------------------------------------
# Canonical types
# ---------------------------------------------------------------------------


class StopKind(str, Enum):
    """Canonical stop reasons. Each provider's native names map onto these."""
    COMPLETED = "completed"        # final assistant turn — return to user
    TOOL_USE = "tool_use"          # model wants tools executed; loop again
    MAX_TOKENS = "max_tokens"      # truncated output
    OTHER = "other"                # anything else; surface to logs


@dataclass
class NormalizedToolCall:
    """A tool the model invoked, in already-parsed form."""
    id: str                # provider-issued id (toolu_* / call_*)
    name: str
    args: Dict[str, Any]   # parsed JSON; never the raw string
    # Original JSON-string form of args when available (OpenAI emits a
    # string; Anthropic emits a dict). Kept so the loop can round-trip
    # the EXACT bytes the model produced into the next assistant turn,
    # avoiding spurious whitespace/precision drift from re-serializing.
    args_raw: Optional[str] = None


@dataclass
class NormalizedResponse:
    """Provider-agnostic view of one model turn."""
    text: str                                  # concatenated text blocks
    tool_calls: List[NormalizedToolCall] = field(default_factory=list)
    stop_kind: StopKind = StopKind.OTHER
    raw_stop_reason: str = ""                  # provider-native string for logs
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Any = None                            # original SDK response


# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------


@dataclass
class StreamTextDelta:
    """One text chunk emitted during streaming."""
    text: str


@dataclass
class StreamFinal:
    """Terminal event from a streamed turn — carries the same shape as
    a non-streaming response so the loop body can branch on
    ``stop_kind`` exactly the way it does for non-streaming."""
    response: NormalizedResponse


# Union for type hints; runtime checks use isinstance.
StreamingEvent = Any  # StreamTextDelta | StreamFinal


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class LLMProvider(Protocol):
    """Provider-shaped surface used by the copilot tool loop.

    Implementations own anything that differs between providers; the
    loop stays provider-agnostic.
    """

    name: str

    def request_kwargs(
        self,
        *,
        model: str,
        system: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        force_tool_first: bool,
        reasoning_effort: Optional[str],
    ) -> Dict[str, Any]:
        """Build the kwargs dict passed to the SDK's create() method."""
        ...

    def parse_response(self, response: Any) -> NormalizedResponse:
        """Normalize an SDK response into a ``NormalizedResponse``."""
        ...

    def assistant_turn_for_tool_use(
        self, response: NormalizedResponse,
    ) -> Dict[str, Any]:
        """Build the assistant-role message to append to history when a
        tool-use turn is being continued. Provider-specific because the
        wire format differs (Anthropic: content blocks; OpenAI: separate
        ``tool_calls`` field)."""
        ...

    def tool_result_message(
        self,
        tool_use_id: str,
        content: str,
    ) -> Dict[str, Any]:
        """Build a single tool-result message appended after execution.
        For OpenAI this is a top-level ``role: tool`` message; for
        Anthropic this is a ``tool_result`` content block intended to
        live inside a ``role: user`` turn — callers wrap accordingly."""
        ...

    def append_tool_use_round(
        self,
        messages: List[Dict[str, Any]],
        response: NormalizedResponse,
        tool_results: List[Dict[str, Any]],
    ) -> None:
        """Mutate ``messages`` in place: append the assistant tool-use
        turn and the tool result messages produced by ``tool_result_message``.

        This hides the wire-format split (Anthropic wraps all results in
        one ``role: user`` content list; OpenAI emits one top-level
        ``role: tool`` message per result) so the loop can stay
        provider-agnostic."""
        ...

    def iter_stream(self, sdk_stream: Any) -> Iterable[StreamingEvent]:
        """Yield canonical streaming events from an SDK stream object.

        The two SDKs emit very different event shapes (Anthropic:
        message_start / content_block_delta / message_delta;
        OpenAI: chunk-shaped delta with optional partial tool_calls).
        This method collapses them into a stream of ``StreamTextDelta``
        chunks followed by a single terminal ``StreamFinal`` carrying a
        ``NormalizedResponse``. Synchronous iterator because both SDKs'
        streams are sync iterators.
        """
        ...


# ---------------------------------------------------------------------------
# Stop-reason canonicalization
# ---------------------------------------------------------------------------


_ANTHROPIC_STOP_MAP = {
    "end_turn": StopKind.COMPLETED,
    "stop_sequence": StopKind.COMPLETED,
    "tool_use": StopKind.TOOL_USE,
    "max_tokens": StopKind.MAX_TOKENS,
}

_OPENAI_STOP_MAP = {
    "stop": StopKind.COMPLETED,
    "tool_calls": StopKind.TOOL_USE,
    "function_call": StopKind.TOOL_USE,  # legacy, just in case
    "length": StopKind.MAX_TOKENS,
}


def _canonical_stop(raw: str, mapping: Dict[str, StopKind]) -> StopKind:
    return mapping.get(raw or "", StopKind.OTHER)


# ---------------------------------------------------------------------------
# Helpers used by both providers
# ---------------------------------------------------------------------------


def _safe_json_parse(blob: str) -> Dict[str, Any]:
    """Parse tool-call arguments; OpenAI returns them as a string, and
    occasionally the string is malformed. Falling back to ``{}`` matches
    the prior behavior in ``_chat_openai``."""
    try:
        return json.loads(blob) if blob else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class AnthropicProvider:
    """Provider impl for Anthropic Messages API."""

    name = "anthropic"
    # Phrasing preserved verbatim from the pre-refactor code path.
    # OpenAI uses different wording (see OpenAIProvider.root_cause_label);
    # the drift is historical and unifying it would change response tone
    # in ways the eval harness should ratify before we touch.
    root_cause_label = "[System context — root cause analysis]"

    def request_kwargs(
        self,
        *,
        model: str,
        system: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        force_tool_first: bool,
        reasoning_effort: Optional[str],  # noqa: ARG002 — not used by Anthropic
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": model,
            "system": system,            # callers pass the cached-system shape
            "messages": messages,
            "tools": tools if tools else None,
            "max_tokens": 16384,
        }
        if force_tool_first and tools:
            kwargs["tool_choice"] = {"type": "any"}
        return kwargs

    def parse_response(self, response: Any) -> NormalizedResponse:
        text_chunks: List[str] = []
        tool_calls: List[NormalizedToolCall] = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                text_chunks.append(text)
            if getattr(block, "type", None) == "tool_use":
                args = block.input or {}
                tool_calls.append(NormalizedToolCall(
                    id=block.id,
                    name=block.name,
                    args=args,
                    # Anthropic gives us a dict; preserve a deterministic
                    # serialization for round-trip parity with OpenAI.
                    args_raw=json.dumps(args, default=str),
                ))
        usage = getattr(response, "usage", None)
        return NormalizedResponse(
            text="".join(text_chunks),
            tool_calls=tool_calls,
            stop_kind=_canonical_stop(
                getattr(response, "stop_reason", "") or "", _ANTHROPIC_STOP_MAP,
            ),
            raw_stop_reason=getattr(response, "stop_reason", "") or "",
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            raw=response,
        )

    def assistant_turn_for_tool_use(
        self, response: NormalizedResponse,
    ) -> Dict[str, Any]:
        # Build content blocks from the normalized fields. Anthropic
        # accepts dict-shaped content blocks just as it does the SDK's
        # objects, and constructing from normalized fields means this
        # works equally for streaming (where ``raw`` is a stream object
        # we can't round-trip) and non-streaming.
        content_blocks: List[Dict[str, Any]] = []
        if response.text:
            content_blocks.append({"type": "text", "text": response.text})
        for tc in response.tool_calls:
            content_blocks.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.args,
            })
        return {"role": "assistant", "content": content_blocks}

    def iter_stream(self, sdk_stream: Any) -> Iterable[StreamingEvent]:
        # The Anthropic streaming SDK yields events; final state lives
        # on ``stream.get_final_message()``. Caller has already entered
        # the context manager.
        for event in sdk_stream:
            if getattr(event, "type", None) == "content_block_delta":
                delta_text = getattr(getattr(event, "delta", None), "text", None)
                if delta_text:
                    yield StreamTextDelta(text=delta_text)
        final_message = sdk_stream.get_final_message()
        yield StreamFinal(response=self.parse_response(final_message))

    def tool_result_message(
        self, tool_use_id: str, content: str,
    ) -> Dict[str, Any]:
        # Note: Anthropic tool results are content blocks that callers
        # collect into a single ``role: user`` turn. Returning the block
        # alone keeps this method orthogonal — the loop wraps a list of
        # them.
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
        }

    def append_tool_use_round(
        self,
        messages: List[Dict[str, Any]],
        response: NormalizedResponse,
        tool_results: List[Dict[str, Any]],
    ) -> None:
        # Anthropic round-trips its own content blocks; tool results
        # all live inside a single ``role: user`` content list.
        messages.append(self.assistant_turn_for_tool_use(response))
        messages.append({"role": "user", "content": tool_results})


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIProvider:
    """Provider impl for OpenAI / GPT-5.x Chat Completions."""

    name = "openai"
    # Lowercased phrasing intentional: Chat Completions tolerates
    # ``role: "system"`` after the first turn but it's non-standard and
    # the Responses API rejects it, so root-cause is injected as a
    # user-role note. Anthropic keeps its older capitalized phrasing.
    root_cause_label = "[system note — root cause analysis]"

    def __init__(self, *, supports_reasoning_effort: bool = True) -> None:
        # Reasoning models (o1/o3) and GPT-5.x take ``max_completion_tokens``
        # but only some accept ``reasoning_effort``. The flag gates the
        # latter without coupling this module to the model-name parsing
        # helpers in ``llm.py``.
        self._supports_reasoning_effort = supports_reasoning_effort

    def request_kwargs(
        self,
        *,
        model: str,
        system: str,                    # noqa: ARG002 — already in messages for OpenAI
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        force_tool_first: bool,
        reasoning_effort: Optional[str],
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        is_new_model = model.startswith("gpt-5") or model.startswith(
            ("o1", "o3", "o4")
        )
        if is_new_model:
            kwargs["max_completion_tokens"] = 16384
        else:
            kwargs["max_tokens"] = 16384

        will_have_tools = bool(tools)
        if will_have_tools:
            kwargs["tools"] = tools
            if force_tool_first:
                kwargs["tool_choice"] = "required"

        # GPT-5.x rejects ``reasoning_effort`` on Chat Completions when
        # tools are present (returns 400 directing callers to /v1/responses).
        # Drop it on tool-bearing calls — see commit 3700f2b.
        if (
            reasoning_effort
            and self._supports_reasoning_effort
            and not will_have_tools
        ):
            kwargs["reasoning_effort"] = reasoning_effort

        return kwargs

    def parse_response(self, response: Any) -> NormalizedResponse:
        choice = response.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls: List[NormalizedToolCall] = []
        for tc in (getattr(message, "tool_calls", None) or []):
            args_raw = tc.function.arguments
            tool_calls.append(NormalizedToolCall(
                id=tc.id,
                name=tc.function.name,
                args=_safe_json_parse(args_raw),
                # Preserve the EXACT JSON string the model produced —
                # the assistant turn round-trip uses this verbatim to
                # avoid spurious whitespace / number-format drift that
                # re-serialization would introduce.
                args_raw=args_raw,
            ))
        usage = getattr(response, "usage", None)
        return NormalizedResponse(
            text=text,
            tool_calls=tool_calls,
            stop_kind=_canonical_stop(
                getattr(choice, "finish_reason", "") or "", _OPENAI_STOP_MAP,
            ),
            raw_stop_reason=getattr(choice, "finish_reason", "") or "",
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            raw=response,
        )

    def assistant_turn_for_tool_use(
        self, response: NormalizedResponse,
    ) -> Dict[str, Any]:
        # Built from the normalized fields rather than ``response.raw``
        # so this works for streaming (where the SDK's message object
        # doesn't exist post-stream — only the accumulated delta).
        return {
            "role": "assistant",
            "content": response.text or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        # args_raw is the model's exact JSON string when
                        # available; fall back to a deterministic
                        # serialization for synthetic tool calls (e.g.
                        # the pre-execution flow that injects a
                        # confirmed tool result without ever calling
                        # the LLM).
                        "arguments": tc.args_raw or json.dumps(
                            tc.args, default=str,
                        ),
                    },
                }
                for tc in response.tool_calls
            ],
        }

    def iter_stream(self, sdk_stream: Any) -> Iterable[StreamingEvent]:
        # OpenAI streaming chunks each carry a partial delta. Tool calls
        # arrive piecewise, indexed by ``tc_delta.index`` — accumulate
        # them and only synthesize NormalizedToolCall objects on final.
        accumulated_text = ""
        tool_calls_acc: Dict[int, Dict[str, Any]] = {}
        finish_reason: Optional[str] = None
        input_tokens = 0
        output_tokens = 0

        for chunk in sdk_stream:
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            if not choice:
                continue
            delta = getattr(choice, "delta", None)
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            if delta and getattr(delta, "content", None):
                accumulated_text += delta.content
                yield StreamTextDelta(text=delta.content)
            if delta and getattr(delta, "tool_calls", None):
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    bucket = tool_calls_acc.setdefault(idx, {
                        "id": "",
                        "name": "",
                        "arguments": "",
                    })
                    if tc_delta.id:
                        bucket["id"] = tc_delta.id
                    if tc_delta.function and tc_delta.function.name:
                        bucket["name"] = tc_delta.function.name
                    if tc_delta.function and tc_delta.function.arguments:
                        bucket["arguments"] += tc_delta.function.arguments
            usage = getattr(chunk, "usage", None)
            if usage:
                input_tokens += getattr(usage, "prompt_tokens", 0) or 0
                output_tokens += getattr(usage, "completion_tokens", 0) or 0

        tool_calls = [
            NormalizedToolCall(
                id=tc["id"],
                name=tc["name"],
                args=_safe_json_parse(tc["arguments"]),
                args_raw=tc["arguments"] or None,
            )
            for tc in tool_calls_acc.values()
        ]
        yield StreamFinal(response=NormalizedResponse(
            text=accumulated_text,
            tool_calls=tool_calls,
            stop_kind=_canonical_stop(finish_reason or "", _OPENAI_STOP_MAP),
            raw_stop_reason=finish_reason or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # No SDK message object survives streaming; the loop must
            # use the normalized fields, which is now what
            # assistant_turn_for_tool_use does.
            raw=None,
        ))

    def tool_result_message(
        self, tool_use_id: str, content: str,
    ) -> Dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_use_id,
            "content": content,
        }

    def append_tool_use_round(
        self,
        messages: List[Dict[str, Any]],
        response: NormalizedResponse,
        tool_results: List[Dict[str, Any]],
    ) -> None:
        # OpenAI: assistant turn carries the tool_calls field; each tool
        # result is its own top-level ``role: tool`` message.
        messages.append(self.assistant_turn_for_tool_use(response))
        messages.extend(tool_results)
