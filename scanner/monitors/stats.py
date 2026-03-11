"""
Statistical engine for monitor anomaly detection.

Centralizes z-score, MAD, confidence scoring, adaptive thresholds,
and minimum-effect-size logic used across all monitors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AnomalyScore:
    """Result of statistical anomaly scoring."""

    z_score: float
    mad_score: float
    pct_change: Optional[float]
    absolute_change: float
    is_anomaly: bool
    method_used: str  # "zscore", "mad", "pct_change", "constant_baseline"
    confidence_pct: int
    direction: str  # "above", "below", "normal"
    explanation: str
    baseline_mean: float
    baseline_median: float
    baseline_stddev: float
    baseline_mad: float
    baseline_count: int
    threshold_used: float


def baseline_confidence(count: int) -> int:
    """Confidence percentage based on baseline size.

    Fewer data points mean the baseline is less representative.
    Returns 0 for <3 points (unusable), scales up to 100 at 60+.
    """
    if count >= 60:
        return 100
    if count >= 30:
        return 90
    if count >= 20:
        return 80
    if count >= 14:
        return 65
    if count >= 7:
        return 50
    if count >= 3:
        return 30
    return 0


def adaptive_threshold(
    baseline: List[float], base_threshold: float = 3.0
) -> float:
    """Adjust anomaly threshold based on baseline variability.

    Highly variable data gets a wider threshold to reduce noise.
    Very stable data gets a tighter threshold to catch subtle shifts.
    """
    if len(baseline) < 3:
        return base_threshold

    mean = sum(baseline) / len(baseline)
    if mean == 0:
        return base_threshold

    stddev = _stddev(baseline, mean)
    cv = stddev / abs(mean)  # coefficient of variation

    if cv > 0.5:
        # Highly variable — widen threshold to reduce false alarms
        return base_threshold * 1.5
    elif cv < 0.05:
        # Very stable — tighten threshold to catch subtle shifts
        return base_threshold * 0.7
    return base_threshold


def score_anomaly(
    current: float,
    baseline: List[float],
    threshold: float = 3.0,
    min_effect_size: float = 0.0,
    method: str = "auto",
    use_adaptive_threshold: bool = True,
) -> AnomalyScore:
    """Score a current value against a historical baseline.

    Parameters
    ----------
    current : float
        The current observed value.
    baseline : list of float
        Historical values forming the baseline.
    threshold : float
        Z-score threshold for anomaly detection (default 3.0).
    min_effect_size : float
        Minimum absolute change required to trigger (default 0.0).
        For rate metrics, use 0.01. For counts, use 0.
    method : str
        Detection method: "zscore", "mad", "pct_change", or "auto".
        "auto" selects the best method based on baseline properties.
    use_adaptive_threshold : bool
        Whether to adjust threshold based on baseline variability.

    Returns
    -------
    AnomalyScore
    """
    count = len(baseline)
    confidence = baseline_confidence(count)

    # Compute all baseline statistics
    mean = sum(baseline) / count if count > 0 else 0.0
    median = _median(baseline) if count > 0 else 0.0
    stddev = _stddev(baseline, mean) if count > 0 else 0.0
    mad = _mad(baseline, median) if count > 0 else 0.0

    absolute_change = current - mean
    pct_change = _pct_change(current, baseline)

    # Compute z-scores
    z_score = (current - mean) / stddev if stddev > 0 else (
        float("inf") if current != mean else 0.0
    )
    mad_score = _mad_zscore(current, median, mad)

    # Select effective threshold
    effective_threshold = threshold
    if use_adaptive_threshold and count >= 7:
        effective_threshold = adaptive_threshold(baseline, threshold)

    # Select method
    resolved_method = _resolve_method(method, baseline, count)

    # Determine anomaly based on resolved method
    is_anomaly, direction, explanation = _evaluate_anomaly(
        current=current,
        mean=mean,
        median=median,
        stddev=stddev,
        mad=mad,
        z_score=z_score,
        mad_score=mad_score,
        pct_change=pct_change,
        absolute_change=absolute_change,
        threshold=effective_threshold,
        min_effect_size=min_effect_size,
        method=resolved_method,
        count=count,
        confidence=confidence,
    )

    return AnomalyScore(
        z_score=round(z_score, 4),
        mad_score=round(mad_score, 4),
        pct_change=round(pct_change, 4) if pct_change is not None else None,
        absolute_change=round(absolute_change, 4),
        is_anomaly=is_anomaly,
        method_used=resolved_method,
        confidence_pct=confidence,
        direction=direction,
        explanation=explanation,
        baseline_mean=round(mean, 4),
        baseline_median=round(median, 4),
        baseline_stddev=round(stddev, 4),
        baseline_mad=round(mad, 4),
        baseline_count=count,
        threshold_used=round(effective_threshold, 4),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _median(values: List[float]) -> float:
    """Compute median of a list."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_v[mid - 1] + sorted_v[mid]) / 2.0
    return sorted_v[mid]


def _stddev(values: List[float], mean: float) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance) if variance > 0 else 0.0


def _mad(values: List[float], median: float) -> float:
    """Median Absolute Deviation."""
    if not values:
        return 0.0
    deviations = [abs(x - median) for x in values]
    return _median(deviations)


def _mad_zscore(current: float, median: float, mad: float) -> float:
    """Modified z-score using MAD.

    Uses the consistency constant 0.6745 so that MAD-based scores
    are comparable to standard z-scores for normal distributions.
    """
    if mad == 0:
        return float("inf") if current != median else 0.0
    return 0.6745 * (current - median) / mad


def _pct_change(current: float, baseline: List[float]) -> Optional[float]:
    """Percentage change vs the most recent baseline value."""
    if not baseline:
        return None
    previous = baseline[-1]
    if previous == 0:
        return None if current == 0 else float("inf")
    return (current - previous) / abs(previous)


def _resolve_method(method: str, baseline: List[float], count: int) -> str:
    """Pick the best detection method automatically."""
    if method != "auto":
        return method

    if count < 7:
        return "pct_change"

    # Check if baseline has outliers (max z-score > 4 in baseline itself)
    if count >= 7:
        mean = sum(baseline) / count
        stddev = _stddev(baseline, mean)
        if stddev > 0:
            max_baseline_z = max(abs(x - mean) / stddev for x in baseline)
            if max_baseline_z > 4.0:
                return "mad"

    return "zscore"


def _evaluate_anomaly(
    *,
    current: float,
    mean: float,
    median: float,
    stddev: float,
    mad: float,
    z_score: float,
    mad_score: float,
    pct_change: Optional[float],
    absolute_change: float,
    threshold: float,
    min_effect_size: float,
    method: str,
    count: int,
    confidence: int,
) -> tuple[bool, str, str]:
    """Evaluate whether the value is anomalous and explain why.

    Returns (is_anomaly, direction, explanation).
    """
    # Effect size gate: anomaly requires both statistical significance
    # AND practical significance (absolute change above floor)
    effect_size_met = abs(absolute_change) >= min_effect_size

    if method == "pct_change":
        is_anomaly = False
        score_val = pct_change
        if pct_change is not None and abs(pct_change) > 0.5:
            is_anomaly = effect_size_met
            direction = "above" if pct_change > 0 else "below"
            explanation = (
                f"Value {current:.4f} changed {pct_change:+.1%} vs previous "
                f"({mean:.4f} baseline mean, {count} points). "
                f"Using percentage change (baseline too short for z-score)."
            )
            if not effect_size_met:
                is_anomaly = False
                explanation += (
                    f" Change below min effect size ({min_effect_size})."
                )
            return is_anomaly, direction, explanation
        direction = "normal"
        explanation = (
            f"Value {current:.4f} within normal range "
            f"({pct_change:+.1%} change vs previous, {count} points). "
            f"Baseline too short for z-score."
        ) if pct_change is not None else (
            f"Value {current:.4f}, cannot compute percentage change. "
            f"Baseline has {count} points."
        )
        return False, direction, explanation

    if method == "mad":
        score_val = mad_score
        exceeds_threshold = abs(mad_score) > threshold
    elif method == "constant_baseline":
        # All baseline values identical — any change is notable
        is_anomaly = current != mean and effect_size_met
        direction = "above" if current > mean else "below" if current < mean else "normal"
        explanation = (
            f"Value {current:.4f} vs constant baseline of {mean:.4f}. "
            f"Absolute change: {abs(absolute_change):.4f}."
        )
        if not effect_size_met and current != mean:
            explanation += (
                f" Change below min effect size ({min_effect_size})."
            )
        return is_anomaly, direction, explanation
    else:
        # zscore
        score_val = z_score
        exceeds_threshold = abs(z_score) > threshold

    is_anomaly = exceeds_threshold and effect_size_met

    # Confidence-based auto-downgrade: if confidence < 50%, suppress anomaly
    # (caller should use WARN instead of FAIL)
    if is_anomaly and confidence < 50:
        is_anomaly = False  # Will be reported as low-confidence observation

    direction = "above" if current > mean else "below" if current < mean else "normal"

    score_label = "MAD score" if method == "mad" else "z-score"
    score_display = mad_score if method == "mad" else z_score

    if is_anomaly:
        explanation = (
            f"Value {current:.4f} is {direction} expected range "
            f"({score_label}: {score_display:.2f}, threshold: {threshold:.1f}, "
            f"baseline: {mean:.4f} mean / {median:.4f} median, "
            f"{count} points, {confidence}% confidence)."
        )
    else:
        reasons = []
        if exceeds_threshold and not effect_size_met:
            reasons.append(
                f"statistically anomalous ({score_label}: {score_display:.2f}) "
                f"but absolute change {abs(absolute_change):.4f} "
                f"below min effect size {min_effect_size}"
            )
        if exceeds_threshold and confidence < 50:
            reasons.append(
                f"suppressed due to low confidence ({confidence}%, "
                f"need 50%+ for anomaly detection, have {count} points)"
            )
        reason_text = "; ".join(reasons) if reasons else "within expected range"
        explanation = (
            f"Value {current:.4f} {reason_text} "
            f"({score_label}: {score_display:.2f}, threshold: {threshold:.1f}, "
            f"baseline: {mean:.4f} mean, {count} points)."
        )

    return is_anomaly, direction, explanation


def detrend_linear(values: List[float]) -> List[float]:
    """Remove linear trend from a time series.

    Useful for growing tables where the baseline drifts upward.
    Returns residuals (deviations from the linear trend).
    """
    n = len(values)
    if n < 3:
        return values

    # Simple linear regression: y = a + b*x
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n

    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return values

    slope = numerator / denominator
    intercept = y_mean - slope * x_mean

    return [v - (intercept + slope * i) for i, v in enumerate(values)]


def format_number(value: float) -> str:
    """Format a number for human-readable display in explanations."""
    abs_val = abs(value)
    if abs_val == 0:
        return "0"
    if abs_val >= 1_000_000:
        return f"{value:,.0f}"
    if abs_val >= 100:
        return f"{value:,.1f}"
    if abs_val >= 1:
        return f"{value:.2f}"
    if abs_val >= 0.01:
        return f"{value:.4f}"
    return f"{value:.6f}"
