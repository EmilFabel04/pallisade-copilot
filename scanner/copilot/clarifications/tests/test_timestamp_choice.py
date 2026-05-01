import pytest
from copilot.clarifications.kinds.timestamp_choice.schemas import (
    validate_payload, validate_answer,
)
from copilot.clarifications.kinds.timestamp_choice.parser import parse_reply


def test_payload_requires_candidates_and_table_fqn():
    with pytest.raises(ValueError):
        validate_payload({})
    with pytest.raises(ValueError):
        validate_payload({"candidates": []})
    validate_payload({
        "table_fqn": "raw.orders",
        "candidates": ["loaded_at", "created_at"],
        "evidence": {},
    })


def test_answer_requires_column():
    with pytest.raises(ValueError):
        validate_answer({})
    validate_answer({"column": "loaded_at"})


def test_parse_reply_picks_named_column():
    candidates = ["loaded_at", "created_at", "updated_at"]
    assert parse_reply("use loaded_at please", candidates) == {"column": "loaded_at"}
    assert parse_reply("definitely created_at", candidates) == {"column": "created_at"}


def test_parse_reply_returns_none_when_unparseable():
    assert parse_reply("idk", ["a", "b"]) is None
