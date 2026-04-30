"""Payload + answer schemas for failure_review."""
from typing import Any, Dict


_REQUIRED_PAYLOAD = ("node_fqn", "metric", "observed", "expected_range", "z_score", "sample_window")
_VALID_DISPOSITIONS = ("expected", "investigate")


def validate_payload(payload: Dict[str, Any]) -> None:
    for key in _REQUIRED_PAYLOAD:
        if key not in payload:
            raise ValueError(f"payload.{key} is required")
    if not isinstance(payload["expected_range"], list) or len(payload["expected_range"]) != 2:
        raise ValueError("payload.expected_range must be [min, max]")


def validate_answer(answer: Dict[str, Any]) -> None:
    disp = answer.get("disposition")
    if disp not in _VALID_DISPOSITIONS:
        raise ValueError(f"answer.disposition must be one of {_VALID_DISPOSITIONS}")
