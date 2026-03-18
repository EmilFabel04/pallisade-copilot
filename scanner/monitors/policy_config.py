"""
Shared policy-to-monitor-config mapping module.

Provides:
- sensitivity_to_zscore: Convert a 0-1 sensitivity to a z-score anomaly threshold
- POLICY_TO_MONITOR_CONFIG: Canonical mapping of monitor types to their policy fields
- merge_policy_config: Merge an EffectivePolicy into a monitor config dict
- is_less_strict: Compare two field values by strictness semantics
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Sensitivity → Z-score conversion
# ---------------------------------------------------------------------------

def sensitivity_to_zscore(sensitivity: float) -> float:
    """Convert a 0-1 sensitivity scale to a z-score anomaly threshold.

    Higher sensitivity → lower threshold → more alerts.
    Maps: 0.99→2.0, 0.95→3.0, 0.90→3.5, 0.80→4.0, ≤0.50→5.0
    Uses piecewise linear interpolation between known breakpoints.
    """
    s = max(0.0, min(1.0, sensitivity))
    breakpoints = [
        (0.99, 2.0),
        (0.95, 3.0),
        (0.90, 3.5),
        (0.80, 4.0),
        (0.50, 5.0),
    ]
    if s >= breakpoints[0][0]:
        return breakpoints[0][1]
    if s <= breakpoints[-1][0]:
        return breakpoints[-1][1]
    for i in range(len(breakpoints) - 1):
        s_hi, z_hi = breakpoints[i]
        s_lo, z_lo = breakpoints[i + 1]
        if s_lo <= s <= s_hi:
            ratio = (s - s_lo) / (s_hi - s_lo)
            return z_lo + ratio * (z_hi - z_lo)
    return 3.0  # fallback


# ---------------------------------------------------------------------------
# Strictness / tolerance ordering for is_less_strict
# ---------------------------------------------------------------------------

# Fields where a higher numeric value means less strict (e.g. allowing more hours/lag)
_HIGHER_IS_LESS_STRICT: Set[str] = {
    "max_hours",
    "warning_hours",
    "sync_lag_minutes",
    "anomaly_threshold",      # higher z-score = less sensitive = less strict
    "growth_threshold",
    "max_null_rate",
    "max_duplicate_rate",
    "run_latency_minutes",
    "schedule_lag_minutes",
    "lag_tolerance_minutes",
}

# Fields where a lower numeric value means less strict (e.g. requiring fewer minimum rows)
_LOWER_IS_LESS_STRICT: Set[str] = {
    "min_rows",
    "lookback_days",
}

# Ordered from most strict to least strict
_STRICTNESS_ORDER: Dict[str, int] = {
    "strict": 0,
    "warn": 1,
    "ignore": 2,
}

_TOLERANCE_ORDER: Dict[str, int] = {
    "strict": 0,
    "normal": 1,
    "relaxed": 2,
}


def is_less_strict(field: str, policy_value: Any, override_value: Any) -> bool:
    """Return True if override_value is less strict than policy_value for this field.

    Used to detect when a user override would weaken a policy requirement.

    Args:
        field: The config field name (e.g. "max_hours", "strictness")
        policy_value: The value from the resolved policy
        override_value: The value from the user override

    Returns:
        True if override_value is less strict than policy_value, False otherwise
    """
    if field == "strictness":
        p = _STRICTNESS_ORDER.get(str(policy_value), 99)
        o = _STRICTNESS_ORDER.get(str(override_value), 99)
        return o > p

    if field in ("failure_tolerance", "orch_failure_tolerance", "test_failure_tolerance"):
        p = _TOLERANCE_ORDER.get(str(policy_value), 99)
        o = _TOLERANCE_ORDER.get(str(override_value), 99)
        return o > p

    if field in _HIGHER_IS_LESS_STRICT:
        try:
            return float(override_value) > float(policy_value)
        except (TypeError, ValueError):
            return False

    if field in _LOWER_IS_LESS_STRICT:
        try:
            return float(override_value) < float(policy_value)
        except (TypeError, ValueError):
            return False

    return False


# ---------------------------------------------------------------------------
# Policy → monitor config field mapping
#
# Format per monitor type:
#   policy_field_name -> config_field_name   (str)
# OR
#   policy_field_name -> (config_field_name, converter_func)  (tuple)
#
# policy_field_name: the key as it comes from the policy_config dict passed
#   to merge_policy_config (typically using the monitor's own config key names,
#   e.g. "max_hours", "min_rows", etc.)
# ---------------------------------------------------------------------------

# Converter: treat the policy field as anomaly_sensitivity (0-1) and convert to z-score
_anomaly_conv: Callable[[float], float] = sensitivity_to_zscore

POLICY_TO_MONITOR_CONFIG: Dict[str, Dict[str, Any]] = {
    # ----- Warehouse SQL monitors -----
    "FRESHNESS": {
        "max_hours": "max_hours",
        "warning_hours": "warning_hours",
    },
    "VOLUME": {
        "min_rows": "min_rows",
        "max_rows": "max_rows",
        "growth_threshold": "growth_threshold",
    },
    "OUTLIER_DETECTION": {
        # policy sends sensitivity (0-1); config expects z-score threshold
        "anomaly_threshold": ("anomaly_threshold", _anomaly_conv),
        "lookback_days": "lookback_days",
    },
    "ANOMALY": {
        # Legacy alias for OUTLIER_DETECTION
        "anomaly_threshold": ("anomaly_threshold", _anomaly_conv),
        "lookback_days": "lookback_days",
    },
    "NULL_CHECK": {
        "max_null_rate": "max_null_rate",
    },
    "UNIQUENESS_CHECK": {
        "max_duplicate_rate": "max_duplicate_rate",
    },
    "SCHEMA_CHANGE": {
        "strictness": "strictness",
    },
    # ----- Ingestion monitors -----
    "SYNC_LAG": {
        "sync_lag_minutes": "lag_tolerance_minutes",
    },
    "FAILED_SYNCS": {
        "failure_tolerance": "failure_tolerance",
    },
    "CONNECTOR_SCHEMA_DRIFT": {
        "strictness": "strictness",
    },
    # ----- BI / Reporting monitors -----
    "BI_FRESHNESS_PROXY": {
        "max_hours": "max_hours",
    },
    "BI_UPSTREAM_BREAK_RISK": {
        "strictness": "strictness",
    },
    # ----- Orchestration monitors -----
    "DAG_LAST_RUN": {
        "run_latency_minutes": "run_latency_minutes",
    },
    "DAG_SCHEDULE_LAG": {
        "schedule_lag_minutes": "schedule_lag_minutes",
    },
    "TASK_FAILURE_RATE": {
        "failure_tolerance": "failure_tolerance",
    },
    # ----- Transformation / dbt monitors -----
    "DBT_TEST_FAILURES": {
        "failure_tolerance": "failure_tolerance",
    },
    "DBT_MODEL_FRESHNESS": {
        "max_hours": "max_hours",
    },
    "DBT_SOURCE_FRESHNESS": {
        "max_hours": "max_hours",
    },
}


# ---------------------------------------------------------------------------
# merge_policy_config
# ---------------------------------------------------------------------------

def merge_policy_config(
    monitor_type: str,
    config: Dict[str, Any],
    policy_config: Optional[Dict[str, Any]],
    policy_overrides: List[str],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Merge policy values into a monitor config dict, respecting user overrides.

    Resolution order per config field:
    1. If the config field is listed in policy_overrides → keep config value (provenance="override")
    2. Else if policy_config has a mapped value → use policy value (provenance="policy")
    3. Otherwise → keep config value as-is (provenance="config")

    Args:
        monitor_type: e.g. "FRESHNESS", "VOLUME"
        config: Existing monitor config dict (may contain user-supplied values)
        policy_config: Dict of policy values keyed by policy field names, or None
        policy_overrides: List of config field names the user has explicitly overridden

    Returns:
        (merged_config, provenance) where provenance maps field → "policy"|"override"|"config"
    """
    merged: Dict[str, Any] = dict(config)
    provenance: Dict[str, str] = {k: "config" for k in config}

    if not policy_config:
        return merged, provenance

    field_map = POLICY_TO_MONITOR_CONFIG.get(monitor_type)
    if not field_map:
        # Unknown monitor type — return config unchanged
        return merged, provenance

    for policy_field, mapping in field_map.items():
        # Determine the target config field name and optional converter
        if isinstance(mapping, tuple):
            config_field, converter = mapping
        else:
            config_field = mapping
            converter = None

        # Look up the policy value. Accept both the policy field name and the
        # config field name as keys (Next.js may send already-mapped names).
        policy_value = policy_config.get(policy_field)
        if policy_value is None:
            policy_value = policy_config.get(config_field)
        if policy_value is None:
            continue

        # Apply converter if needed
        if converter is not None:
            policy_value = converter(policy_value)

        if config_field in policy_overrides:
            # User explicitly overrode this field — keep their value
            provenance[config_field] = "override"
            # Ensure it's present in merged (it should already be from config)
            if config_field not in merged and config_field in config:
                merged[config_field] = config[config_field]
        else:
            # Policy wins
            merged[config_field] = policy_value
            provenance[config_field] = "policy"

    return merged, provenance
