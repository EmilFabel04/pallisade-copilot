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
from typing import Any, Dict, List, Optional, Protocol


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
                tool_calls.append(NormalizedToolCall(
                    id=block.id,
                    name=block.name,
                    args=block.input or {},
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
        # Anthropic accepts the raw content-blocks list as-is — the SDK
        # round-trips its own response objects.
        return {
            "role": "assistant",
            "content": response.raw.content if response.raw else [],
        }

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


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIProvider:
    """Provider impl for OpenAI / GPT-5.x Chat Completions."""

    name = "openai"

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
            tool_calls.append(NormalizedToolCall(
                id=tc.id,
                name=tc.function.name,
                args=_safe_json_parse(tc.function.arguments),
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
        message = response.raw.choices[0].message
        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in (message.tool_calls or [])
            ],
        }

    def tool_result_message(
        self, tool_use_id: str, content: str,
    ) -> Dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_use_id,
            "content": content,
        }
