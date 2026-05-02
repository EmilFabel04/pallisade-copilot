"""timestamp_choice clarification kind."""
from pathlib import Path
from copilot.clarifications.registry import register_kind, KindHandler
from copilot.clarifications.kinds.timestamp_choice.schemas import (
    validate_payload, validate_answer,
)
from copilot.clarifications.kinds.timestamp_choice.parser import parse_reply
from copilot.clarifications.kinds.timestamp_choice.conventions import on_resolve

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def _load_prompt(payload):
    template = _PROMPT_PATH.read_text()
    return template.format(
        table_fqn=payload.get("table_fqn", "<unknown>"),
        candidates=", ".join(payload.get("candidates", [])) or "(none)",
        confidence=payload.get("confidence", "unknown"),
        request_id=payload.get("__request_id", "<unknown>"),
    )


register_kind(KindHandler(
    kind="timestamp_choice",
    validate_payload=validate_payload,
    validate_answer=validate_answer,
    load_prompt=_load_prompt,
    on_resolve=on_resolve,
))


__all__ = ["parse_reply"]
