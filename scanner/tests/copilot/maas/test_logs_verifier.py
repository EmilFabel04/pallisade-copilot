"""Tests for Logs verifier: valid layers, owners, bounded evidence."""

import pytest

from copilot.maas.schemas import LogsResponse, ErrorSignature, EvidenceRequest
from copilot.maas.verifiers.logs_verifier import (
    LogsVerifier,
    VALID_FAILURE_LAYERS,
    VALID_OWNERS,
    MAX_EVIDENCE_REQUESTS,
)


def _make_logs_response(
    failure_layer: str = "SQL Compilation",
    owner: str = "warehouse",
    confidence: float = 0.85,
    summary: str = "Test summary.",
    next_evidence: list = None,
) -> LogsResponse:
    return LogsResponse(
        error_signature=ErrorSignature(
            failure_layer=failure_layer,
            error_message="Column not found",
            system="bigquery",
        ),
        owner=owner,
        owner_confidence=confidence,
        next_evidence=next_evidence or [],
        summary=summary,
    )


class TestLogsVerifierValidLayers:
    def test_all_valid_layers_pass(self):
        v = LogsVerifier()
        for layer in VALID_FAILURE_LAYERS:
            resp = _make_logs_response(failure_layer=layer)
            result = v.verify(resp)
            assert result.passed is True, f"Layer '{layer}' should pass"

    def test_invalid_layer_fails(self):
        v = LogsVerifier()
        resp = _make_logs_response(failure_layer="InvalidLayer")
        result = v.verify(resp)
        assert result.passed is False
        assert any("failure_layer" in e.lower() for e in result.errors)


class TestLogsVerifierOwners:
    def test_all_valid_owners_pass(self):
        v = LogsVerifier()
        for owner in VALID_OWNERS:
            resp = _make_logs_response(owner=owner)
            result = v.verify(resp)
            assert result.passed is True, f"Owner '{owner}' should pass"

    def test_invalid_owner_fails(self):
        v = LogsVerifier()
        resp = _make_logs_response(owner="nonexistent_system")
        result = v.verify(resp)
        assert result.passed is False
        assert any("owner" in e.lower() for e in result.errors)


class TestLogsVerifierConfidence:
    def test_valid_confidence(self):
        v = LogsVerifier()
        resp = _make_logs_response(confidence=0.5)
        result = v.verify(resp)
        assert result.passed is True

    def test_boundary_confidence(self):
        v = LogsVerifier()
        for val in [0.0, 1.0]:
            resp = _make_logs_response(confidence=val)
            result = v.verify(resp)
            assert result.passed is True


class TestLogsVerifierEvidence:
    def test_bounded_evidence(self):
        v = LogsVerifier()
        evidence = [
            EvidenceRequest(tool_name=f"tool_{i}", reason=f"reason_{i}")
            for i in range(MAX_EVIDENCE_REQUESTS)
        ]
        resp = _make_logs_response(next_evidence=evidence)
        result = v.verify(resp)
        assert result.passed is True

    def test_too_many_evidence_requests_warns(self):
        v = LogsVerifier()
        evidence = [
            EvidenceRequest(tool_name=f"tool_{i}", reason=f"reason_{i}")
            for i in range(MAX_EVIDENCE_REQUESTS + 2)
        ]
        resp = _make_logs_response(next_evidence=evidence)
        result = v.verify(resp)
        # Too many evidence is a warning (truncated), not a hard failure
        assert any("truncated" in w.lower() or "evidence" in w.lower() for w in result.warnings)

    def test_empty_tool_name_fails(self):
        v = LogsVerifier()
        evidence = [EvidenceRequest(tool_name="", reason="need it")]
        resp = _make_logs_response(next_evidence=evidence)
        result = v.verify(resp)
        assert result.passed is False


class TestLogsVerifierSummary:
    def test_empty_summary_fails(self):
        v = LogsVerifier()
        resp = _make_logs_response(summary="")
        result = v.verify(resp)
        assert result.passed is False

    def test_valid_summary_passes(self):
        v = LogsVerifier()
        resp = _make_logs_response(summary="The dbt model failed due to a schema change.")
        result = v.verify(resp)
        assert result.passed is True
