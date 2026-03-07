"""Tests for MAAS Pydantic v2 schemas."""

import pytest
from pydantic import ValidationError

from copilot.maas.schemas import (
    SQLResponse,
    SQLAssumption,
    SQLValidationStep,
    LogsResponse,
    ErrorSignature,
    EvidenceRequest,
    CodeFixResponse,
    UnifiedDiffPatch,
    CodeFixValidation,
    SpecialistInvocation,
    ToolCallRecord,
    MAASTrace,
    WarehouseType,
)


class TestSQLResponse:
    def test_valid_sql_response(self):
        resp = SQLResponse(
            sql="SELECT COUNT(*) FROM `project.dataset.table`",
            warehouse=WarehouseType.BIGQUERY,
            assumptions=[SQLAssumption(assumption="table exists", confidence=0.9)],
            explanation="Counts all rows.",
        )
        assert resp.sql.startswith("SELECT")
        assert resp.warehouse == WarehouseType.BIGQUERY
        assert len(resp.assumptions) == 1

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            SQLResponse()  # missing sql, warehouse

    def test_invalid_warehouse_type(self):
        with pytest.raises(ValidationError):
            SQLResponse(sql="SELECT 1", warehouse="mysql")

    def test_from_json(self):
        raw = '{"sql": "SELECT 1", "warehouse": "snowflake", "explanation": "test"}'
        resp = SQLResponse.model_validate_json(raw)
        assert resp.warehouse == WarehouseType.SNOWFLAKE

    def test_assumption_confidence_bounds(self):
        with pytest.raises(ValidationError):
            SQLAssumption(assumption="test", confidence=1.5)

        with pytest.raises(ValidationError):
            SQLAssumption(assumption="test", confidence=-0.1)


class TestLogsResponse:
    def test_valid_logs_response(self):
        resp = LogsResponse(
            error_signature=ErrorSignature(
                failure_layer="SQL Compilation",
                error_message="Column not found: revenue",
                system="bigquery",
            ),
            owner="warehouse",
            owner_confidence=0.85,
            summary="BigQuery compilation error due to missing column.",
        )
        assert resp.owner == "warehouse"
        assert resp.owner_confidence == 0.85
        assert resp.error_signature.failure_layer == "SQL Compilation"

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            LogsResponse(
                error_signature=ErrorSignature(
                    failure_layer="Runtime/Data",
                    error_message="err",
                    system="dbt",
                ),
                owner="dbt",
                owner_confidence=2.0,  # out of range
                summary="test",
            )

    def test_evidence_request_defaults(self):
        req = EvidenceRequest(tool_name="get_dag_run_history", reason="need history")
        assert req.tool_arguments == {}

    def test_from_json(self):
        raw = """{
            "error_signature": {
                "failure_layer": "Connection/Auth",
                "error_message": "403 Forbidden",
                "system": "fivetran"
            },
            "owner": "infra",
            "owner_confidence": 0.7,
            "next_evidence": [],
            "summary": "Auth failure."
        }"""
        resp = LogsResponse.model_validate_json(raw)
        assert resp.owner == "infra"


class TestCodeFixResponse:
    def test_valid_codefix_response(self):
        resp = CodeFixResponse(
            patches=[
                UnifiedDiffPatch(
                    file_path="models/orders.sql",
                    patch_type="sql_model",
                    new_content="SELECT * FROM orders",
                    rationale="Fixed column reference.",
                )
            ],
            validation=CodeFixValidation(
                rollback_steps=["Revert to previous version"],
            ),
            impact_summary="Downstream dashboard affected.",
            root_cause_summary="Wrong column name.",
        )
        assert len(resp.patches) == 1
        assert resp.patches[0].patch_type == "sql_model"

    def test_empty_patches(self):
        # patches is required but can be empty list
        resp = CodeFixResponse(
            patches=[],
            validation=CodeFixValidation(),
            impact_summary="none",
            root_cause_summary="none",
        )
        assert resp.patches == []

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            CodeFixResponse()


class TestObservability:
    def test_specialist_invocation(self):
        inv = SpecialistInvocation(
            specialist="sql",
            latency_ms=450,
            success=True,
        )
        assert inv.retry_count == 0
        assert inv.error is None

    def test_tool_call_record(self):
        rec = ToolCallRecord(
            tool_name="query_warehouse",
            args_hash="abc123",
            latency_ms=200,
            success=True,
        )
        assert rec.tool_name == "query_warehouse"

    def test_maas_trace(self):
        trace = MAASTrace(
            route="INFO/sql",
            total_latency_ms=1200,
        )
        assert trace.specialists == []
        assert trace.fallback_reason is None
        assert trace.skipped_specialists == []

    def test_maas_trace_full(self):
        trace = MAASTrace(
            route="DEBUG/logs+codefix",
            specialists=[
                SpecialistInvocation(specialist="logs", latency_ms=300, success=True),
                SpecialistInvocation(specialist="codefix", latency_ms=500, success=False, error="timeout"),
            ],
            verifier_results={"logs": {"passed": True}},
            tool_calls=[
                ToolCallRecord(tool_name="get_dag_run_history", args_hash="x", latency_ms=100, success=True),
            ],
            fallback_reason=None,
            skipped_specialists=[],
            total_latency_ms=1500,
        )
        assert len(trace.specialists) == 2
        assert trace.specialists[1].error == "timeout"
