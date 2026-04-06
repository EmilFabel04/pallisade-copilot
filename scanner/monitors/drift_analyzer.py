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
