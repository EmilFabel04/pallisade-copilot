"""
Drift Analysis Engine

Analyzes monitor run history to detect sustained trends and recommend
SLA adjustments. Runs as a weekly scheduled job.
"""
from __future__ import annotations

import json
import logging
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def compute_freshness_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute freshness statistics from monitor runs (value = hours since update)."""
    values = [r["value"] for r in runs if r.get("value") is not None]
    if not values:
        return {"count": 0, "mean": None, "p95": None, "trend_slope": None}

    sorted_vals = sorted(values)
    p95_idx = int(len(sorted_vals) * 0.95)
    p95 = sorted_vals[min(p95_idx, len(sorted_vals) - 1)]

    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "p95": p95,
        "min": min(values),
        "max": max(values),
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "trend_slope": _compute_trend_slope(runs),
    }


def compute_volume_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute volume statistics from monitor runs (value = row count)."""
    values = [r["value"] for r in runs if r.get("value") is not None]
    if not values:
        return {"count": 0, "mean": None, "trend_slope": None, "growth_rate": None}

    mean_val = statistics.mean(values)
    first_half = values[: len(values) // 2] if len(values) >= 4 else values
    second_half = values[len(values) // 2 :] if len(values) >= 4 else values
    first_mean = statistics.mean(first_half) if first_half else 0
    second_mean = statistics.mean(second_half) if second_half else 0
    growth_rate = (second_mean - first_mean) / first_mean if first_mean > 0 else 0.0

    return {
        "count": len(values),
        "mean": mean_val,
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "trend_slope": _compute_trend_slope(runs),
        "growth_rate": growth_rate,
    }


def compute_quality_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute quality stats (null rate trends, shift detection)."""
    null_rates = []
    for r in runs:
        nr = (r.get("details") or {}).get("null_rate")
        if nr is None:
            nr = r.get("value")
        if nr is not None:
            null_rates.append(float(nr))

    if not null_rates:
        return {"count": 0, "mean_null_rate": None, "shift_detected": False}

    mean_nr = statistics.mean(null_rates)
    stddev_nr = statistics.stdev(null_rates) if len(null_rates) > 1 else 0.0

    shift_detected = False
    if len(null_rates) >= 5 and stddev_nr > 0:
        threshold = mean_nr + 2 * stddev_nr
        recent = null_rates[-2:]
        if all(v > threshold for v in recent):
            shift_detected = True

    return {
        "count": len(null_rates),
        "mean_null_rate": mean_nr,
        "stddev": stddev_nr,
        "shift_detected": shift_detected,
        "trend_slope": _compute_trend_slope(
            [{"value": v, "completedAt": r.get("completedAt")} for r, v in zip(runs, null_rates)]
        ),
    }


def compute_uniqueness_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute uniqueness stats (duplicate rate trends)."""
    dup_rates = []
    for r in runs:
        dr = (r.get("details") or {}).get("duplicate_rate")
        if dr is None:
            dr = r.get("value")
        if dr is not None:
            dup_rates.append(float(dr))

    if not dup_rates:
        return {"count": 0, "mean_duplicate_rate": None}

    return {
        "count": len(dup_rates),
        "mean_duplicate_rate": statistics.mean(dup_rates),
        "stddev": statistics.stdev(dup_rates) if len(dup_rates) > 1 else 0.0,
        "trend_slope": _compute_trend_slope(
            [{"value": v, "completedAt": r.get("completedAt")} for r, v in zip(runs, dup_rates)]
        ),
    }


def compute_schema_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute schema change frequency and patterns."""
    change_runs = [r for r in runs if r.get("status") in ("FAIL", "WARN")]
    additions = 0
    removals = 0
    for r in change_runs:
        details = r.get("details") or {}
        additions += len(details.get("columns_added", []))
        removals += len(details.get("columns_removed", []))

    return {
        "count": len(runs),
        "change_count": len(change_runs),
        "additions": additions,
        "removals": removals,
    }


def compute_anomaly_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute false positive rate from LLM validation history."""
    validated = []
    for r in runs:
        details = r.get("details") or {}
        raw = details.get("raw_status")
        adjusted = details.get("adjusted_status")
        if raw and adjusted:
            validated.append({"raw": raw, "adjusted": adjusted})

    if not validated:
        return {"count": 0, "false_positive_rate": None}

    false_positives = sum(
        1 for v in validated if v["raw"] in ("FAIL", "WARN") and v["adjusted"] == "PASS"
    )

    return {
        "count": len(validated),
        "false_positive_rate": false_positives / len(validated) if validated else 0.0,
        "total_alerts": sum(1 for v in validated if v["raw"] in ("FAIL", "WARN")),
        "downgraded": false_positives,
    }


def _compute_trend_slope(runs: List[Dict[str, Any]]) -> Optional[float]:
    """Simple linear regression slope over time-ordered values."""
    points = []
    for r in runs:
        v = r.get("value")
        t = r.get("completedAt")
        if v is not None and t is not None:
            points.append((t, float(v)))

    if len(points) < 3:
        return None

    points.sort(key=lambda p: p[0])
    n = len(points)
    xs = list(range(n))
    ys = [p[1] for p in points]
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return numerator / denominator


# ---------------------------------------------------------------------------
# LLM prompt construction
# ---------------------------------------------------------------------------

DRIFT_SYSTEM_PROMPT = """You are a data quality analyst reviewing monitor performance trends.

For each monitor below, I've provided:
- Current SLA/config values and their source (direct_profile, auto_discovered, imported_dbt, etc.)
- Statistical summary of all historical results
- Trend direction and significance

Recommend SLA adjustments where the data shows consistent drift.

Rules:
- Only recommend changes where confidence > 0.7 and the trend is sustained
- Do NOT recommend changes for monitors with insufficient history
- For tightening recommendations, ensure the new threshold still has buffer above actual performance
- For loosening recommendations, explain why the current threshold causes false alerts
- For auto_discovered SLAs, weight recommendations higher — these were derived from historical data and the drift analyzer has newer data to refine them
- For imported_dbt SLAs, note in reasoning that the threshold originated from dbt config

Return ONLY a JSON array (no markdown fencing) where each element has:
{
  "monitorId": "...",
  "driftCategory": "freshness|volume|quality|schema|anomaly|uniqueness",
  "currentField": "section.field",
  "currentValue": "...",
  "recommendedValue": "...",
  "reasoning": "1-2 sentence explanation",
  "confidence": 0.0-1.0,
  "severity": "low|medium|high"
}

If no recommendations are warranted, return an empty array: []"""


MONITOR_TYPE_TO_CATEGORY: Dict[str, str] = {
    "FRESHNESS": "freshness",
    "VOLUME": "volume",
    "NULL_CHECK": "quality",
    "SCHEMA_CHANGE": "schema",
    "OUTLIER_DETECTION": "anomaly",
    "ANOMALY": "anomaly",
    "UNIQUENESS_CHECK": "uniqueness",
    "RANGE_VALIDATION": "anomaly",
    "ACCEPTED_VALUES": "quality",
    "DATE_CONSISTENCY": "quality",
    "DATA_TYPE_VALIDATION": "schema",
}

CATEGORY_STAT_FN = {
    "freshness": compute_freshness_stats,
    "volume": compute_volume_stats,
    "quality": compute_quality_stats,
    "schema": compute_schema_stats,
    "anomaly": compute_anomaly_stats,
    "uniqueness": compute_uniqueness_stats,
}

CATEGORY_SLA_FIELDS: Dict[str, List[tuple]] = {
    "freshness": [("freshness", "maxHours"), ("freshness", "warningHours")],
    "volume": [("volume", "growthRateThreshold"), ("volume", "minRows")],
    "quality": [("quality", "maxNullRate"), ("quality", "maxDuplicateRate")],
    "schema": [("schema", "strictness"), ("schema", "allowEvolution")],
    "anomaly": [("anomaly", "sensitivity"), ("anomaly", "lookbackDays")],
    "uniqueness": [("quality", "maxDuplicateRate")],
}


def _build_monitor_context(
    monitor: Dict[str, Any],
    runs: List[Dict[str, Any]],
    stats: Dict[str, Any],
    sla_policy: Optional[Dict[str, Any]],
    category: str,
) -> Dict[str, Any]:
    """Build context dict for a single monitor to include in the LLM prompt."""
    current_sla = {}
    if sla_policy:
        for section, field in CATEGORY_SLA_FIELDS.get(category, []):
            val = (sla_policy.get(section) or {}).get(field)
            if val is not None:
                current_sla[f"{section}.{field}"] = val

    return {
        "monitorId": monitor["id"],
        "monitorName": monitor["name"],
        "monitorType": monitor.get("monitorType", ""),
        "targetFqn": monitor.get("targetFqn", ""),
        "driftCategory": category,
        "slaSource": sla_policy.get("source", "none") if sla_policy else "none",
        "currentSLA": current_sla,
        "stats": stats,
        "runCount": len(runs),
        "config": monitor.get("config") or {},
    }


async def _call_llm(monitors_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Call the LLM with drift analysis context and parse recommendations."""
    import httpx
    import os

    user_prompt = json.dumps(monitors_context, indent=2, default=str)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("DRIFT_LLM_MODEL", "gpt-4o")

    if not api_key:
        logger.warning("[DriftAnalyzer] No OPENAI_API_KEY set, skipping LLM analysis")
        return []

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": DRIFT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        recommendations = json.loads(content)
        if not isinstance(recommendations, list):
            logger.error("[DriftAnalyzer] LLM returned non-list: %s", type(recommendations))
            return []
        return recommendations
    except json.JSONDecodeError as e:
        logger.error("[DriftAnalyzer] Failed to parse LLM response: %s", e)
        return []


async def run_drift_analysis(
    org_id: str,
    monitors: List[Dict[str, Any]],
    runs_by_monitor: Dict[str, List[Dict[str, Any]]],
    policies: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Run drift analysis for an organization's monitors.

    Args:
        org_id: Organization ID
        monitors: List of monitor dicts (from DB)
        runs_by_monitor: Map of monitor_id -> list of MonitorRun dicts
        policies: Map of targetFqn -> resolved SLA policy dict

    Returns:
        Dict with runId and list of recommendation dicts ready for DB insertion.
    """
    run_id = str(uuid.uuid4())
    all_contexts: Dict[str, List[Dict[str, Any]]] = {}

    for monitor in monitors:
        if not monitor.get("enabled"):
            continue

        monitor_id = monitor["id"]
        monitor_type = (monitor.get("monitorType") or "").upper()
        category = MONITOR_TYPE_TO_CATEGORY.get(monitor_type)
        if not category:
            continue

        runs = runs_by_monitor.get(monitor_id, [])
        if len(runs) < 5:
            fqn = monitor.get("targetFqn", "")
            policy = policies.get(fqn)
            if not policy or policy.get("source") != "auto_discovered":
                continue

        stat_fn = CATEGORY_STAT_FN.get(category)
        if not stat_fn:
            continue

        stats = stat_fn(runs)
        fqn = monitor.get("targetFqn", "")
        policy = policies.get(fqn)

        ctx = _build_monitor_context(monitor, runs, stats, policy, category)

        if category not in all_contexts:
            all_contexts[category] = []
        all_contexts[category].append(ctx)

    all_recommendations = []
    for category, contexts in all_contexts.items():
        if not contexts:
            continue
        try:
            recs = await _call_llm(contexts)
            all_recommendations.extend(recs)
        except Exception as e:
            logger.error("[DriftAnalyzer] LLM call failed for %s: %s", category, e)

    monitor_map = {m["id"]: m for m in monitors}
    results = []
    for rec in all_recommendations:
        mid = rec.get("monitorId", "")
        mon = monitor_map.get(mid)
        if not mon:
            continue

        results.append({
            "organizationId": org_id,
            "monitorId": mid,
            "monitorName": mon.get("name", ""),
            "monitorType": mon.get("monitorType", ""),
            "targetFqn": mon.get("targetFqn", ""),
            "driftCategory": rec.get("driftCategory", ""),
            "severity": rec.get("severity", "medium"),
            "currentField": rec.get("currentField", ""),
            "currentValue": str(rec.get("currentValue", "")),
            "recommendedValue": str(rec.get("recommendedValue", "")),
            "reasoning": rec.get("reasoning", ""),
            "confidence": float(rec.get("confidence", 0.0)),
            "evidence": rec,
            "status": "pending",
            "runId": run_id,
        })

    logger.info(
        "[DriftAnalyzer] Analysis complete org_id=%s run_id=%s monitors_analyzed=%d recommendations=%d",
        org_id, run_id, sum(len(c) for c in all_contexts.values()), len(results),
    )

    return {"runId": run_id, "recommendations": results}
