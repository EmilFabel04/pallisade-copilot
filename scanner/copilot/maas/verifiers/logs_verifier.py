"""
Deterministic verifier for Logs specialist output.

Checks structural validity, bounded evidence requests, and valid enum values.
"""

from typing import List, Optional, Set
from dataclasses import dataclass

from ..schemas import LogsResponse

VALID_FAILURE_LAYERS = {
    "Connection/Auth",
    "SQL Compilation",
    "Runtime/Data",
    "Orchestration",
}

VALID_OWNERS = {
    "airflow", "dbt", "ingestion", "warehouse", "infra", "reporting", "unknown",
}

MAX_EVIDENCE_REQUESTS = 3


@dataclass
class LogsVerificationResult:
    passed: bool
    errors: List[str]
    warnings: List[str]


class LogsVerifier:
    """
    Deterministic verifier for Logs specialist output.

    Checks:
    1. error_signature has a valid failure_layer
    2. owner is one of the known systems
    3. owner_confidence is 0.0-1.0
    4. next_evidence has <= MAX_EVIDENCE_REQUESTS entries
    5. Each evidence request has a non-empty tool_name
    6. summary is non-empty
    """

    def verify(
        self,
        response: LogsResponse,
        available_tools: Optional[Set[str]] = None,
    ) -> LogsVerificationResult:
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Valid failure layer
        if response.error_signature.failure_layer not in VALID_FAILURE_LAYERS:
            errors.append(
                f"Invalid failure_layer: '{response.error_signature.failure_layer}'. "
                f"Must be one of: {sorted(VALID_FAILURE_LAYERS)}"
            )

        # 2. Valid owner
        if response.owner.lower() not in VALID_OWNERS:
            errors.append(
                f"Invalid owner: '{response.owner}'. "
                f"Must be one of: {sorted(VALID_OWNERS)}"
            )

        # 3. Confidence range (Pydantic validates, but belt-and-suspenders)
        if not 0.0 <= response.owner_confidence <= 1.0:
            errors.append(
                f"owner_confidence out of range: {response.owner_confidence}"
            )

        # 4. Bounded evidence requests
        if len(response.next_evidence) > MAX_EVIDENCE_REQUESTS:
            warnings.append(
                f"next_evidence has {len(response.next_evidence)} entries, "
                f"will be truncated to {MAX_EVIDENCE_REQUESTS}"
            )

        # 5. Each evidence request has valid tool_name
        for i, req in enumerate(response.next_evidence[:MAX_EVIDENCE_REQUESTS]):
            if not req.tool_name:
                errors.append(f"next_evidence[{i}] has empty tool_name")
            elif available_tools and req.tool_name not in available_tools:
                warnings.append(
                    f"next_evidence[{i}] tool '{req.tool_name}' not in "
                    f"available tools — will be filtered"
                )

        # 6. Non-empty summary
        if not response.summary.strip():
            errors.append("summary is empty")

        return LogsVerificationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
