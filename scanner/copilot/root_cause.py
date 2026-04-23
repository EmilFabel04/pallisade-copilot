"""
Root Cause Ownership Resolver

Deterministic post-evidence resolver that classifies which system
owns the root cause of a pipeline issue. Called after the LLM's
tool-calling phase gathers evidence, so it can guide the LLM to
create fixes in the correct repo/system.
"""

import re
import json
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


class OwnerSystem(Enum):
    AIRFLOW = "airflow"
    DBT = "dbt"
    INGESTION = "ingestion"
    WAREHOUSE = "warehouse"
    INFRA = "infra"
    REPORTING = "reporting"
    UNKNOWN = "unknown"


@dataclass
class OwnerDecision:
    owner_system: OwnerSystem
    confidence: float  # 0.0 - 1.0
    explanation: str
    related_entities: List[str] = field(default_factory=list)
    evidence_summary: Dict[str, Any] = field(default_factory=dict)
    suggested_tools: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pattern definitions for each owner system
# ---------------------------------------------------------------------------

_AIRFLOW_ERROR_PATTERNS = [
    (r"(?:DAG|dag)\s+(?:import|parse|syntax)\s+error", 0.9),
    (r"ModuleNotFoundError", 0.85),
    (r"ImportError.*(?:dag|airflow|operator)", 0.85),
    (r"(?:DAG|dag)\s+(?:not found|missing)", 0.8),
    (r"scheduler.*(?:error|fail)", 0.7),
    (r"(?:operator|task)\s+(?:misconfig|invalid|missing)", 0.8),
    (r"airflow\.exceptions\.\w+Error", 0.85),
    (r"(?:pool|slot|queue)\s+(?:full|exhausted|unavailable)", 0.7),
    (r"(?:dag_run|DagRun)\s+(?:failed|timeout)", 0.6),
    (r"(?:sensor|trigger)\s+(?:timeout|poke.*fail)", 0.7),
]

_DBT_ERROR_PATTERNS = [
    (r"Compilation Error", 0.95),
    (r"dbt\s+(?:run|test|build)\s+(?:failed|error)", 0.9),
    (r"relation\s+.*does not exist", 0.8),
    (r"(?:model|test|snapshot|seed)\s+.*(?:failed|error)", 0.75),
    (r"Database Error in model", 0.9),
    (r"Runtime Error in model", 0.9),
    (r"(?:ref|source)\s*\(.*\)\s+.*not found", 0.85),
    (r"schema\.yml.*(?:error|invalid)", 0.8),
    (r"dbt_project\.yml.*(?:error|invalid)", 0.8),
    (r"Encountered an error.*running (?:model|test|snapshot)", 0.85),
]

_DBT_IN_AIRFLOW_PATTERNS = [
    # dbt command invocation within Airflow logs
    (r"(?:Running|Executing|running).*dbt\s+(?:run|test|build|seed|snapshot)", 0.4),
]

_INGESTION_ERROR_PATTERNS = [
    (r"(?:connector|connection)\s+(?:status|state).*(?:broken|failed|error|paused)", 0.9),
    (r"sync\s+(?:failed|error|broken)", 0.85),
    (r"(?:fivetran|airbyte).*(?:error|fail|broken)", 0.85),
    (r"authentication\s+failed.*(?:source|connector)", 0.8),
    (r"(?:source|upstream)\s+(?:schema|table)\s+(?:changed|missing|dropped)", 0.7),
    (r"schema\s+(?:change|drift|mismatch)", 0.7),
    (r"(?:replication|sync)\s+(?:lag|delay|behind)", 0.6),
]

_WAREHOUSE_ERROR_PATTERNS = [
    (r"Permission denied", 0.85),
    (r"Access Denied", 0.85),
    (r"quota\s+exceeded", 0.85),
    (r"RESOURCE_EXCEEDED", 0.85),
    (r"(?:table|view|dataset|schema)\s+(?:not found|does not exist)", 0.7),
    (r"(?:insufficient|no)\s+(?:permissions?|privileges?|access)", 0.85),
    (r"billing.*(?:disabled|error)", 0.8),
    (r"(?:timeout|timed out).*(?:query|statement)", 0.6),
    (r"(?:deadlock|lock timeout)", 0.7),
]

_INFRA_ERROR_PATTERNS = [
    (r"(?:401|403)\s+(?:Unauthorized|Forbidden)", 0.75),
    (r"connection\s+(?:refused|reset|timeout)", 0.7),
    (r"(?:DNS|SSL|TLS)\s+(?:error|fail)", 0.8),
    (r"(?:docker|container|k8s|kubernetes)\s+(?:error|fail|crash)", 0.8),
    (r"(?:OOM|out of memory|OutOfMemoryError)", 0.8),
    (r"(?:disk|storage)\s+(?:full|exhausted)", 0.8),
    (r"(?:network|connectivity)\s+(?:error|issue|fail)", 0.7),
]

_REPORTING_ERROR_PATTERNS = [
    (r"(?:dashboard|report|tile|widget)\s+(?:broken|error|fail)", 0.8),
    (r"(?:looker|tableau|power\s*bi)\s+(?:error|fail)", 0.8),
    (r"(?:refresh|extract)\s+(?:failed|error)", 0.7),
    (r"(?:data source|datasource)\s+(?:error|unavailable)", 0.7),
]


def _extract_text_from_tool_results(tool_results: List[Dict]) -> str:
    """Flatten all tool results into a single searchable text blob."""
    parts = []
    for tr in tool_results:
        # Handle various result structures
        result = tr.get("result", tr.get("data", tr))
        if isinstance(result, str):
            parts.append(result)
        elif isinstance(result, dict):
            parts.append(json.dumps(result, default=str))
        elif isinstance(result, list):
            parts.append(json.dumps(result, default=str))
    return "\n".join(parts)


def _extract_tool_names(tool_results: List[Dict]) -> List[str]:
    """Get list of tool names that were called."""
    names = []
    for tr in tool_results:
        name = tr.get("tool") or tr.get("tool_name") or tr.get("name", "")
        if name:
            names.append(name)
    return names


def _check_dbt_in_airflow(text: str) -> bool:
    """Check if Airflow logs contain dbt command invocations."""
    for pattern, _ in _DBT_IN_AIRFLOW_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _check_tool_status(tool_results: List[Dict]) -> Dict[str, Any]:
    """Extract status fields from tool results."""
    statuses = {}
    for tr in tool_results:
        tool_name = tr.get("tool") or tr.get("tool_name") or ""
        result = tr.get("result", tr.get("data", {}))
        if isinstance(result, dict):
            status = result.get("status") or result.get("state")
            success = result.get("success")
            error = result.get("error")
            if status or success is not None or error:
                statuses[tool_name] = {
                    "status": status,
                    "success": success,
                    "error": error,
                }
            # Check nested data
            data = result.get("data", {})
            if isinstance(data, dict):
                nested_status = data.get("status") or data.get("state")
                nested_error = data.get("error")
                if nested_status or nested_error:
                    statuses[f"{tool_name}:data"] = {
                        "status": nested_status,
                        "error": nested_error,
                    }
    return statuses


def _match_patterns(
    text: str, patterns: List[tuple]
) -> tuple[float, List[str]]:
    """Match text against patterns, return (max_score, matched_patterns)."""
    max_score = 0.0
    matched = []
    for pattern, weight in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            if weight > max_score:
                max_score = weight
            matched.append(pattern)
    return max_score, matched


def _extract_entities_from_results(text: str) -> List[str]:
    """Extract model/table/dag names from tool result text."""
    entities = set()
    # dbt model names
    for m in re.finditer(r"model\s+(\w+[\w.]*\w+)", text):
        entities.add(m.group(1))
    # Table FQNs
    for m in re.finditer(r"([a-zA-Z_][\w-]*\.[a-zA-Z_][\w-]*\.[a-zA-Z_][\w-]*)", text):
        entities.add(m.group(1))
    # DAG names
    for m in re.finditer(r"(?:dag_id|DAG)\s*[=:]\s*['\"]?(\w+)", text):
        entities.add(m.group(1))
    return list(entities)


def resolve_fix_owner(
    tool_results: List[Dict],
    intent_result: Any = None,
) -> OwnerDecision:
    """
    Determine which system owns the root cause based on tool evidence.

    Args:
        tool_results: List of tool call results from the LLM conversation.
            Each dict should have 'tool'/'tool_name' and 'result'/'data' keys.
        intent_result: Optional IntentResult for additional context.

    Returns:
        OwnerDecision with the identified owner, confidence, and explanation.
    """
    text = _extract_text_from_tool_results(tool_results)
    tool_names = _extract_tool_names(tool_results)
    statuses = _check_tool_status(tool_results)
    entities = _extract_entities_from_results(text)

    candidates: List[OwnerDecision] = []

    # --- Rule 1: Airflow DAG parse/import/scheduling error ---
    airflow_score, airflow_matches = _match_patterns(text, _AIRFLOW_ERROR_PATTERNS)
    if airflow_score > 0 and not _check_dbt_in_airflow(text):
        # Pure Airflow error (not dbt-within-airflow)
        candidates.append(OwnerDecision(
            owner_system=OwnerSystem.AIRFLOW,
            confidence=airflow_score,
            explanation=f"Airflow error detected: {airflow_matches[0] if airflow_matches else 'unknown pattern'}",
            related_entities=entities,
            evidence_summary={"patterns": airflow_matches},
        ))

    # --- Rule 2: dbt compilation/test failure (direct) ---
    dbt_score, dbt_matches = _match_patterns(text, _DBT_ERROR_PATTERNS)
    if dbt_score > 0:
        candidates.append(OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=dbt_score,
            explanation=f"dbt error detected: {dbt_matches[0] if dbt_matches else 'unknown pattern'}",
            related_entities=entities,
            evidence_summary={"patterns": dbt_matches},
        ))

    # --- Rule 3: dbt command failing INSIDE Airflow ---
    if _check_dbt_in_airflow(text) and dbt_score > 0:
        # dbt is the root cause even though it runs in Airflow
        combined_score = min(dbt_score + 0.05, 0.95)
        candidates.append(OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=combined_score,
            explanation="dbt command failing within Airflow task. Root cause is in dbt, not Airflow orchestration.",
            related_entities=entities,
            evidence_summary={"patterns": dbt_matches, "context": "dbt_in_airflow"},
        ))
    elif _check_dbt_in_airflow(text) and airflow_score > 0:
        # dbt invocation detected but dbt-specific errors didn't match —
        # Airflow is still calling dbt, so dbt is likely the issue
        candidates.append(OwnerDecision(
            owner_system=OwnerSystem.DBT,
            confidence=0.7,
            explanation="Airflow task invokes dbt. The failure likely originates in dbt.",
            related_entities=entities,
            evidence_summary={"patterns": airflow_matches, "context": "dbt_in_airflow_inferred"},
        ))

    # --- Rule 4: Ingestion connector failure ---
    ingestion_score, ingestion_matches = _match_patterns(text, _INGESTION_ERROR_PATTERNS)
    # Also check explicit status fields
    for tool_key, status_info in statuses.items():
        if any(k in tool_key for k in ("fivetran", "airbyte")):
            status_val = str(status_info.get("status", "")).lower()
            if status_val in ("broken", "failed", "error", "paused"):
                ingestion_score = max(ingestion_score, 0.9)
                ingestion_matches.append(f"status={status_val}")
    if ingestion_score > 0:
        candidates.append(OwnerDecision(
            owner_system=OwnerSystem.INGESTION,
            confidence=ingestion_score,
            explanation=f"Ingestion error detected: {ingestion_matches[0] if ingestion_matches else 'connector issue'}",
            related_entities=entities,
            evidence_summary={"patterns": ingestion_matches},
        ))

    # --- Rule 5: Warehouse permission/quota errors ---
    wh_score, wh_matches = _match_patterns(text, _WAREHOUSE_ERROR_PATTERNS)
    if wh_score > 0:
        candidates.append(OwnerDecision(
            owner_system=OwnerSystem.WAREHOUSE,
            confidence=wh_score,
            explanation=f"Warehouse error detected: {wh_matches[0] if wh_matches else 'unknown'}",
            related_entities=entities,
            evidence_summary={"patterns": wh_matches},
        ))

    # --- Rule 6: Infrastructure errors ---
    infra_score, infra_matches = _match_patterns(text, _INFRA_ERROR_PATTERNS)
    if infra_score > 0:
        candidates.append(OwnerDecision(
            owner_system=OwnerSystem.INFRA,
            confidence=infra_score,
            explanation=f"Infrastructure error detected: {infra_matches[0] if infra_matches else 'unknown'}",
            related_entities=entities,
            evidence_summary={"patterns": infra_matches},
        ))

    # --- Rule 7: Reporting errors ---
    report_score, report_matches = _match_patterns(text, _REPORTING_ERROR_PATTERNS)
    if report_score > 0:
        candidates.append(OwnerDecision(
            owner_system=OwnerSystem.REPORTING,
            confidence=report_score,
            explanation=f"Reporting error detected: {report_matches[0] if report_matches else 'unknown'}",
            related_entities=entities,
            evidence_summary={"patterns": report_matches},
        ))

    # --- Select best candidate ---
    if candidates:
        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        best = candidates[0]

        # If low confidence, suggest additional evidence tools
        if best.confidence < 0.6:
            best.suggested_tools = _suggest_evidence_tools(tool_names)

        return best

    # --- Fallback: unknown ---
    return OwnerDecision(
        owner_system=OwnerSystem.UNKNOWN,
        confidence=0.3,
        explanation="Could not determine root cause owner from available evidence.",
        related_entities=entities,
        suggested_tools=_suggest_evidence_tools(tool_names),
    )


def _suggest_evidence_tools(already_called: List[str]) -> List[str]:
    """Suggest tools to call for more evidence, excluding already-called ones."""
    all_evidence_tools = [
        "get_dbt_run_history",
        "get_dbt_test_results",
        "get_fivetran_connector_status",
        "get_fivetran_sync_logs",
        "get_active_incidents",
        "get_upstream",
        "get_downstream",
        "query_warehouse",
        "get_coverage_report",
        "run_coverage_monitor",
    ]
    # Normalize: strip mcp_ prefixes for comparison
    called_normalized = {
        name.replace("mcp_airflow__", "").replace("mcp_", "")
        for name in already_called
    }
    return [t for t in all_evidence_tools if t not in called_normalized][:5]


def format_owner_hint(
    decision: OwnerDecision,
    target_hint: Optional[str] = None,
) -> str:
    """
    Format the ownership decision as a hint message for injection
    into the LLM conversation.

    Args:
        decision: The ownership decision.
        target_hint: The user's originally mentioned system (e.g., "airflow").
    """
    parts = [
        f"Root cause analysis complete. Owner system: {decision.owner_system.value} "
        f"(confidence: {decision.confidence:.0%}). {decision.explanation}"
    ]

    # PR pivot hint: user mentioned one system but root cause is another
    if (
        target_hint
        and decision.owner_system != OwnerSystem.UNKNOWN
        and target_hint.lower() != decision.owner_system.value.lower()
        and decision.confidence >= 0.6
    ):
        parts.append(
            f"Note: The user mentioned {target_hint}, but the root cause is in "
            f"{decision.owner_system.value}. Create the fix in {decision.owner_system.value}, "
            f"not {target_hint}."
        )

    if decision.related_entities:
        parts.append(f"Related entities: {', '.join(decision.related_entities[:10])}")

    if decision.confidence < 0.6 and decision.suggested_tools:
        parts.append(
            f"Confidence is low. Consider calling these tools for more evidence: "
            f"{', '.join(decision.suggested_tools)}. "
            f"If still uncertain, ask the user ONE clarifying question before proposing a fix."
        )

    return " ".join(parts)
