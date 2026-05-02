"""Flow C: borderline z-score → failure_review request → 'expected' answer
writes dampening; 'investigate' records debug handoff."""
import pytest

from scanner.monitors.borderline import classify_severity
from copilot.clarifications.engine import ClarificationEngine
from copilot.clarifications.kinds import failure_review  # registration
from copilot.clarifications.kinds import timestamp_choice  # noqa  (Plan 1 kind)
from copilot.clarifications.registry import KIND_REGISTRY


@pytest.fixture(autouse=True)
def _ensure_failure_review_registered():
    """Other tests in the suite call KIND_REGISTRY.clear(), which wipes the
    self-registration that happens at module import. Force re-registration
    before each test in this file so we don't depend on test ordering."""
    if "failure_review" not in KIND_REGISTRY:
        import importlib

        from copilot.clarifications.kinds import failure_review as _fr
        importlib.reload(_fr)
    yield


class _FakeReq:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "r1")
        self.pipelineStackId = kwargs.get("pipelineStackId", "ps1")
        self.kind = "failure_review"
        self.scopeType = "node"
        self.scopeRef = kwargs.get("scopeRef", "raw.orders")
        self.payload = kwargs.get("payload", {})
        self.status = "open"
        self.priority = "high"
        self.createdAt = None
        self.dismissedUntil = None
        self.resolvedAt = None


class _DB:
    def __init__(self):
        self.requests = []
        self.resolutions = []
        self.conventions = {}
        self.overrides = {}
        self.handed_off_to_debug = []


def test_classifier_distinguishes_clear_borderline_drastic():
    assert classify_severity(z_score=1.0, sensitivity_threshold=3.0) == "clear"
    assert classify_severity(z_score=2.0, sensitivity_threshold=3.0) == "borderline"
    assert classify_severity(z_score=-2.5, sensitivity_threshold=3.0) == "borderline"
    assert classify_severity(z_score=3.5, sensitivity_threshold=3.0) == "drastic"


def test_expected_disposition_writes_dampening_convention():
    db = _DB()
    payload = {
        "node_fqn": "raw.orders",
        "metric": "row_count",
        "observed": 8200,
        "expected_range": [10000, 12000],
        "z_score": -2.1,
        "sample_window": "7d",
    }
    req = _FakeReq(payload=payload)
    db.requests.append(req)

    engine = ClarificationEngine(db=db)
    engine.resolve(
        request=req,
        answer={"disposition": "expected"},
        transcript=[{"role": "user", "content": "expected weekend dip"}],
        answered_by="u1",
    )

    rules = db.conventions["ps1"]["dampening"]["rules"]
    assert any(r["node"] == "raw.orders" and r["metric"] == "row_count" for r in rules)
    assert rules[0]["min_z_to_alert"] >= 2.6


def test_investigate_disposition_records_debug_handoff():
    db = _DB()
    req = _FakeReq(payload={
        "node_fqn": "raw.orders",
        "metric": "row_count",
        "observed": 8200,
        "expected_range": [10000, 12000],
        "z_score": -2.1,
        "sample_window": "7d",
    })
    db.requests.append(req)
    engine = ClarificationEngine(db=db)
    engine.resolve(
        request=req,
        answer={"disposition": "investigate"},
        transcript=[],
        answered_by="u1",
    )
    assert len(db.handed_off_to_debug) == 1
    assert db.handed_off_to_debug[0]["node_fqn"] == "raw.orders"
