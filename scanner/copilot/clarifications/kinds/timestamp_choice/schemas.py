"""Payload + answer schemas for timestamp_choice."""
from typing import Any, Dict


def validate_payload(payload: Dict[str, Any]) -> None:
    if "table_fqn" not in payload or not isinstance(payload["table_fqn"], str):
        raise ValueError("payload.table_fqn (str) is required")
    if "candidates" not in payload or not isinstance(payload["candidates"], list):
        raise ValueError("payload.candidates (list) is required")


def validate_answer(answer: Dict[str, Any]) -> None:
    if "column" not in answer or not isinstance(answer["column"], str):
        raise ValueError("answer.column (str) is required")
