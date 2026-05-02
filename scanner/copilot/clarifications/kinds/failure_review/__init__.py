"""failure_review clarification kind."""
from pathlib import Path
from copilot.clarifications.registry import register_kind, KindHandler
from copilot.clarifications.kinds.failure_review.schemas import (
    validate_payload, validate_answer,
)
from copilot.clarifications.kinds.failure_review.parser import parse_reply
from copilot.clarifications.kinds.failure_review.conventions import on_resolve

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def _load_prompt(payload):
    template = _PROMPT_PATH.read_text()
    return template.format(
        node_fqn=payload.get("node_fqn", "<unknown>"),
        metric=payload.get("metric", "<unknown>"),
        observed=payload.get("observed", "<unknown>"),
        expected_range=payload.get("expected_range", "<unknown>"),
        z_score=payload.get("z_score", "<unknown>"),
        sample_window=payload.get("sample_window", "<unknown>"),
    )


register_kind(KindHandler(
    kind="failure_review",
    validate_payload=validate_payload,
    validate_answer=validate_answer,
    load_prompt=_load_prompt,
    on_resolve=on_resolve,
))


__all__ = ["parse_reply"]
