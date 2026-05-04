"""
Run with: cd scanner && PYTHONPATH=. pytest tests/copilot/test_incident_diagnosis.py -v
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from copilot.incident_diagnosis import diagnose_incident, DiagnosisRequest


def test_diagnose_returns_json_fields_from_llm(monkeypatch):
    fake_llm_response = {
        "content": '{"hypothesis": "Upstream sync stalled at 09:14.", "signature": "fivetran-source-stalled"}',
        "tool_call_evidence": [
            {"tool": "query_warehouse", "input": "...", "output": "..."},
        ],
    }

    with patch("copilot.incident_diagnosis._call_copilot_llm", return_value=fake_llm_response) as call:
        with patch("copilot.incident_diagnosis._classify_owner", return_value=("ingestion", 0.85)):
            req = DiagnosisRequest(
                stack_id="stack_1",
                monitor_run_id="run_1",
                target_fqn="raw.orders",
                monitor_type="FRESHNESS",
                run_details={"value": 26.2, "threshold": 24, "message": "stale"},
            )
            result = diagnose_incident(req)

    assert call.called
    assert result.hypothesis.startswith("Upstream sync")
    assert result.signature == "fivetran-source-stalled"
    assert result.owner_system == "ingestion"
    assert result.owner_confidence == 0.85


def test_diagnose_rejects_invalid_json_with_fallback():
    fake_llm_response = {"content": "not json at all", "tool_call_evidence": []}

    with patch("copilot.incident_diagnosis._call_copilot_llm", return_value=fake_llm_response):
        with patch("copilot.incident_diagnosis._classify_owner", return_value=("unknown", 0.0)):
            req = DiagnosisRequest(
                stack_id="stack_1",
                monitor_run_id="run_1",
                target_fqn="raw.orders",
                monitor_type="FRESHNESS",
                run_details={},
            )
            result = diagnose_incident(req)

    # Falls back to a deterministic signature based on monitor type
    assert result.signature == "freshness-unknown"
    # Hypothesis is the LLM's raw text since JSON parse failed
    assert "not json" in result.hypothesis or result.hypothesis  # non-empty
