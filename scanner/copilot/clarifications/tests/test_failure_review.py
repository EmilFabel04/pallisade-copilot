import pytest
from copilot.clarifications.kinds.failure_review.schemas import (
    validate_payload, validate_answer,
)
from copilot.clarifications.kinds.failure_review.parser import parse_reply


def test_payload_requires_node_metric_z_score_window():
    with pytest.raises(ValueError):
        validate_payload({})
    validate_payload({
        "node_fqn": "raw.orders",
        "metric": "row_count",
        "observed": 8200.0,
        "expected_range": [10000, 12000],
        "z_score": 2.1,
        "sample_window": "7d",
    })


def test_answer_requires_disposition():
    with pytest.raises(ValueError):
        validate_answer({})
    with pytest.raises(ValueError):
        validate_answer({"disposition": "wrong_value"})
    validate_answer({"disposition": "expected"})
    validate_answer({"disposition": "investigate"})


def test_parse_reply_detects_expected():
    assert parse_reply("yeah this is expected, weekend dip") == {"disposition": "expected"}
    assert parse_reply("normal noise, dampen") == {"disposition": "expected"}


def test_parse_reply_detects_investigate():
    assert parse_reply("investigate this please") == {"disposition": "investigate"}
    assert parse_reply("looks weird, look into it") == {"disposition": "investigate"}


def test_parse_reply_returns_none_on_ambiguous():
    assert parse_reply("hmm") is None


from copilot.clarifications.kinds.failure_review.conventions import on_resolve


class _FakeReq:
    def __init__(self):
        self.id = "r1"
        self.pipelineStackId = "ps1"
        self.kind = "failure_review"
        self.scopeType = "node"
        self.scopeRef = "raw.orders"
        self.payload = {
            "node_fqn": "raw.orders",
            "metric": "row_count",
            "observed": 8200,
            "expected_range": [10000, 12000],
            "z_score": -2.1,
            "sample_window": "7d",
        }


class _FakeDB:
    def __init__(self):
        self.conventions = {}
        self.overrides = {}
        self.handed_off_to_debug = []


def test_on_resolve_expected_writes_dampening_convention():
    db = _FakeDB()
    on_resolve(_FakeReq(), {"disposition": "expected"}, db)
    conv = db.conventions["ps1"]
    assert "dampening" in conv
    rules = conv["dampening"]["rules"]
    assert any(r["node"] == "raw.orders" and r["metric"] == "row_count" for r in rules)


def test_on_resolve_investigate_emits_debug_handoff():
    db = _FakeDB()
    on_resolve(_FakeReq(), {"disposition": "investigate"}, db)
    assert len(db.handed_off_to_debug) == 1
    assert db.handed_off_to_debug[0]["node_fqn"] == "raw.orders"
