"""
Result explainer for monitor outputs.

Generates structured, human-readable explanations for every MonitorResult.
Each explanation describes: what was measured, what baseline/threshold was
used, what changed, and why the status was assigned.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import MonitorResult, MonitorStatus
from .stats import format_number


def explain_result(result: MonitorResult) -> Dict[str, str]:
    """Generate a structured explanation for a MonitorResult.

    Returns a dict with keys: metric, baseline, current, change,
    status_reason, and optionally suggestion.
    """
    details = result.details or {}
    monitor_type = result.monitor_type

    # Dispatch to type-specific explainers
    if monitor_type == "freshness":
        return _explain_freshness(result, details)
    elif monitor_type == "volume":
        return _explain_volume(result, details)
    elif monitor_type == "schema_change":
        return _explain_schema(result, details)
    elif monitor_type == "anomaly":
        return _explain_anomaly(result, details)
    elif monitor_type in ("certificate", "server_health", "log_analysis"):
        return _explain_infrastructure(result, details)
    elif monitor_type == "referential":
        return _explain_referential(result, details)
    else:
        return _explain_generic(result, details)


def enrich_result(result: MonitorResult) -> MonitorResult:
    """Add structured explanation to a MonitorResult's details.

    Modifies the result in-place and returns it. If an explanation
    already exists in details, it is preserved.
    """
    if result.details.get("explanation") and isinstance(
        result.details["explanation"], dict
    ):
        return result

    explanation = explain_result(result)
    # Preserve any existing string explanation as the raw explanation
    existing = result.details.get("explanation")
    if existing and isinstance(existing, str):
        explanation["raw"] = existing

    result.details["explanation"] = explanation
    return result


def _explain_freshness(
    result: MonitorResult, details: Dict[str, Any]
) -> Dict[str, str]:
    hours = details.get("hours_since_update")
    max_hours = details.get("max_hours") or result.threshold
    ts_col = details.get("timestamp_column", "unknown")
    freshness_mode = details.get("freshness_mode", "auto")

    mode_label = {
        "ingestion": "ingestion freshness",
        "business_event": "business-event freshness",
    }.get(freshness_mode, "freshness")

    explanation: Dict[str, str] = {
        "metric": f"Table {mode_label} via column '{ts_col}'",
        "baseline": f"Expected update within {max_hours}h" if max_hours else "No threshold configured",
        "current": f"Last update was {hours:.1f}h ago" if hours else "Unknown",
    }

    if result.status == MonitorStatus.FAIL:
        explanation["change"] = f"Exceeded {max_hours}h SLA by {hours - max_hours:.1f}h" if hours and max_hours else "SLA breached"
        explanation["status_reason"] = "FAIL: data is stale beyond the configured threshold"
        explanation["suggestion"] = "Check if upstream ingestion or transformation pipeline ran successfully"
    elif result.status == MonitorStatus.WARN:
        warn_hours = details.get("warn_hours")
        explanation["change"] = f"Approaching SLA ({hours:.1f}h of {max_hours}h)" if hours else "Approaching SLA"
        explanation["status_reason"] = f"WARN: within warning zone ({warn_hours}h-{max_hours}h)" if warn_hours else "WARN: approaching threshold"
    elif result.status == MonitorStatus.PASS:
        explanation["change"] = "Within expected freshness window"
        explanation["status_reason"] = "PASS: data is fresh"
    else:
        explanation["change"] = "Could not determine freshness"
        explanation["status_reason"] = f"{result.status.value.upper()}: {result.message}"

    return explanation


def _explain_volume(
    result: MonitorResult, details: Dict[str, Any]
) -> Dict[str, str]:
    baseline_mean = details.get("baseline_mean") or details.get("historical_mean")
    baseline_stddev = details.get("baseline_stddev") or details.get("historical_stddev")
    z_score = details.get("z_score")
    data_points = details.get("data_points")
    confidence = details.get("confidence_pct")
    method = details.get("method_used", "z-score")
    detrended = details.get("detrended", False)

    explanation: Dict[str, str] = {
        "metric": "Row count" + (" (daily bucket)" if data_points else " (total)"),
    }

    if baseline_mean is not None:
        baseline_desc = f"{format_number(baseline_mean)} mean"
        if baseline_stddev:
            baseline_desc += f" (stddev: {format_number(baseline_stddev)})"
        if data_points:
            baseline_desc += f", {data_points} data points"
        if detrended:
            baseline_desc += ", detrended"
        explanation["baseline"] = baseline_desc
    else:
        explanation["baseline"] = "No baseline available"

    if result.value is not None:
        explanation["current"] = f"{format_number(result.value)} rows"
    else:
        explanation["current"] = "Unknown"

    if z_score is not None and baseline_mean is not None:
        pct_diff = ((result.value - baseline_mean) / baseline_mean * 100) if baseline_mean and result.value else 0
        explanation["change"] = (
            f"{pct_diff:+.1f}% vs baseline ({method}: {z_score:.2f})"
        )
    else:
        explanation["change"] = "No comparison available"

    if result.status == MonitorStatus.FAIL:
        conf_note = f", {confidence}% confidence" if confidence else ""
        explanation["status_reason"] = f"FAIL: volume anomaly detected ({method}: {z_score:.2f}{conf_note})"
        explanation["suggestion"] = "Check if data pipeline ran and completed successfully"
    elif result.status == MonitorStatus.WARN:
        explanation["status_reason"] = f"WARN: potential volume anomaly (low confidence: {confidence}%)" if confidence else "WARN: volume change detected"
    elif result.status == MonitorStatus.PASS:
        explanation["status_reason"] = "PASS: volume within expected range"
    else:
        explanation["status_reason"] = f"{result.status.value.upper()}: {result.message}"

    return explanation


def _explain_schema(
    result: MonitorResult, details: Dict[str, Any]
) -> Dict[str, str]:
    changes = details.get("changes", [])
    change_count = details.get("change_count", len(changes))
    severity = details.get("severity", "unknown")

    explanation: Dict[str, str] = {
        "metric": "Table schema (columns and types)",
        "baseline": f"Previous schema snapshot ({details.get('baseline_column_count', '?')} columns)",
        "current": f"{change_count} change(s) detected" if change_count else "No changes",
    }

    if changes:
        change_summaries = []
        for c in changes[:5]:
            if isinstance(c, dict):
                change_summaries.append(
                    f"{c.get('type', 'change')}: {c.get('column', '?')}"
                    + (f" [{c.get('severity', '')}]" if c.get("severity") else "")
                )
            else:
                change_summaries.append(str(c))
        explanation["change"] = "; ".join(change_summaries)
        if len(changes) > 5:
            explanation["change"] += f" (+{len(changes) - 5} more)"
    else:
        explanation["change"] = "No schema changes"

    if result.status == MonitorStatus.FAIL:
        explanation["status_reason"] = f"FAIL: {severity} schema changes detected"
        explanation["suggestion"] = "Review schema changes and update downstream dependencies"
    elif result.status == MonitorStatus.WARN:
        explanation["status_reason"] = f"WARN: minor schema changes detected ({severity})"
    elif result.status == MonitorStatus.PASS:
        explanation["status_reason"] = "PASS: schema unchanged" if not change_count else "PASS: changes below severity threshold"
    else:
        explanation["status_reason"] = f"{result.status.value.upper()}: {result.message}"

    return explanation


def _explain_anomaly(
    result: MonitorResult, details: Dict[str, Any]
) -> Dict[str, str]:
    column = details.get("column", "")
    metric = details.get("metric", "unknown")
    z_score = details.get("z_score")
    mad_score = details.get("mad_score")
    baseline_mean = details.get("baseline_mean")
    baseline_count = details.get("baseline_count")
    confidence = details.get("confidence_pct")
    method = details.get("method_used", "z-score")
    min_effect = details.get("min_effect_size", 0)
    direction = details.get("direction", "")

    label = f"{column}.{metric}" if column else metric

    explanation: Dict[str, str] = {
        "metric": f"{metric} on column '{column}'" if column else metric,
    }

    if baseline_mean is not None:
        explanation["baseline"] = (
            f"{format_number(baseline_mean)} mean, "
            f"{baseline_count or '?'} points"
        )
    else:
        explanation["baseline"] = "No baseline"

    if result.value is not None:
        explanation["current"] = format_number(result.value)
    else:
        explanation["current"] = "Unknown"

    score_val = mad_score if method == "mad" else z_score
    score_label = "MAD score" if method == "mad" else "z-score"
    if score_val is not None:
        explanation["change"] = f"{score_label}: {score_val:.2f} ({direction})"
    else:
        explanation["change"] = "Insufficient data for scoring"

    if result.status == MonitorStatus.FAIL:
        explanation["status_reason"] = (
            f"FAIL: {label} anomaly ({score_label}: {score_val:.2f}, "
            f"{confidence}% confidence)"
        ) if score_val else f"FAIL: anomaly on {label}"
    elif result.status == MonitorStatus.WARN:
        explanation["status_reason"] = (
            f"WARN: potential anomaly on {label} "
            f"(low confidence: {confidence}%)"
        ) if confidence else f"WARN: {label}"
    elif result.status == MonitorStatus.PASS:
        explanation["status_reason"] = f"PASS: {label} within expected range"
    else:
        explanation["status_reason"] = f"{result.status.value.upper()}: {result.message}"

    return explanation


def _explain_infrastructure(
    result: MonitorResult, details: Dict[str, Any]
) -> Dict[str, str]:
    return {
        "metric": result.monitor_type.replace("_", " ").title(),
        "baseline": "Configured thresholds",
        "current": result.message or "See details",
        "change": "Threshold check",
        "status_reason": f"{result.status.value.upper()}: {result.message}",
    }


def _explain_referential(
    result: MonitorResult, details: Dict[str, Any]
) -> Dict[str, str]:
    orphan_count = details.get("orphan_count", 0)
    parent = details.get("parent_fqn", "?")
    child_col = details.get("child_column", "?")
    parent_col = details.get("parent_column", "?")

    return {
        "metric": f"Referential integrity: {child_col} -> {parent}.{parent_col}",
        "baseline": "All foreign key values must exist in parent table",
        "current": f"{orphan_count:,} orphaned records" if orphan_count else "No orphans",
        "change": f"{orphan_count:,} records reference non-existent parent values" if orphan_count else "All references valid",
        "status_reason": f"FAIL: {orphan_count:,} FK violations" if orphan_count else "PASS: referential integrity intact",
    }


def _explain_generic(
    result: MonitorResult, details: Dict[str, Any]
) -> Dict[str, str]:
    return {
        "metric": result.monitor_type,
        "baseline": str(result.threshold) if result.threshold else "N/A",
        "current": format_number(result.value) if result.value is not None else "N/A",
        "change": result.message or "N/A",
        "status_reason": f"{result.status.value.upper()}: {result.message}",
    }
