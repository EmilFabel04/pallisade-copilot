"""
Run with: cd scanner && PYTHONPATH=. pytest tests/copilot/test_incident_diagnosis.py -v
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from copilot.incident_diagnosis import diagnose_incident, DiagnosisRequest


@pytest.mark.asyncio
async def test_diagnose_returns_json_fields_from_llm():
    fake_llm_response = {
        "content": '{"hypothesis": "Upstream sync stalled at 09:14.", "signature": "fivetran-source-stalled"}',
        "tool_call_evidence": [
            {"tool": "query_warehouse", "input": "...", "output": "..."},
        ],
    }

    with patch(
        "copilot.incident_diagnosis._call_copilot_llm",
        new=AsyncMock(return_value=fake_llm_response),
    ) as call:
        with patch("copilot.incident_diagnosis._classify_owner", return_value=("ingestion", 0.85)):
            req = DiagnosisRequest(
                org_id="org_1",
                stack_id="stack_1",
                monitor_run_id="run_1",
                target_fqn="raw.orders",
                monitor_type="FRESHNESS",
                run_details={"value": 26.2, "threshold": 24, "message": "stale"},
            )
            result = await diagnose_incident(req)

    assert call.called
    assert result.hypothesis.startswith("Upstream sync")
    assert result.signature == "fivetran-source-stalled"
    assert result.owner_system == "ingestion"
    assert result.owner_confidence == 0.85


@pytest.mark.asyncio
async def test_diagnose_rejects_invalid_json_with_fallback():
    fake_llm_response = {"content": "not json at all", "tool_call_evidence": []}

    with patch(
        "copilot.incident_diagnosis._call_copilot_llm",
        new=AsyncMock(return_value=fake_llm_response),
    ):
        with patch("copilot.incident_diagnosis._classify_owner", return_value=("unknown", 0.0)):
            req = DiagnosisRequest(
                org_id="org_1",
                stack_id="stack_1",
                monitor_run_id="run_1",
                target_fqn="raw.orders",
                monitor_type="FRESHNESS",
                run_details={},
            )
            result = await diagnose_incident(req)

    # Falls back to a deterministic signature based on monitor type
    assert result.signature == "freshness-unknown"
    # Hypothesis is the LLM's raw text since JSON parse failed
    assert "not json" in result.hypothesis or result.hypothesis  # non-empty


def test_router_accepts_diagnose_request():
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_settings

    # Read the actual shared secret (may be overridden by SCANNER_SHARED_SECRET env var)
    auth_headers = {
        "x-internal-auth": get_settings().shared_secret,
        "x-acting-user": "test_user",
        "x-acting-org": "test_org",
    }

    client = TestClient(app)
    payload = {
        "stackId": "stack_1",
        "monitorRunId": "run_1",
        "targetFqn": "raw.orders",
        "monitorType": "FRESHNESS",
        "runDetails": {"value": 26, "threshold": 24, "message": "stale"},
    }

    with patch("api.routers.copilot.diagnose_incident") as fake:
        from copilot.incident_diagnosis import DiagnosisResult
        fake.return_value = DiagnosisResult(
            hypothesis="Upstream sync stalled.",
            signature="fivetran-source-stalled",
            owner_system="ingestion",
            owner_confidence=0.85,
        )
        # The route awaits diagnose_incident, so the patch needs to be awaitable.
        async def _coro(*args, **kwargs):
            return fake.return_value
        fake.side_effect = _coro
        res = client.post(
            "/api/v1/copilot/incident-diagnose",
            json=payload,
            headers=auth_headers,
        )

    assert res.status_code == 200
    body = res.json()
    assert body["hypothesis"] == "Upstream sync stalled."
    assert body["signature"] == "fivetran-source-stalled"
    assert body["ownerSystem"] == "ingestion"
    assert body["ownerConfidence"] == 0.85
