"""
HttpProbeAdapter — probes HTTP-accessible data sources to compute
monitoring metrics. NEVER returns or persists raw rows.

Used by CustomSourceDriver to back the SOURCE-layer integration type.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class MetricBundle:
    """Derived monitoring metrics from a single probe run.

    Contains aggregates and column-level metadata only — never raw rows.
    """
    probed_at: datetime
    row_count: int
    latest_timestamp: Optional[datetime]
    column_schema: List[Dict[str, Any]]  # [{name, data_type, is_nullable}, ...]
    null_counts: Dict[str, int]
    distinct_counts: Dict[str, int]
    value_fingerprints: Dict[str, bytes]  # column -> HLL serialized
    min_max_numeric: Dict[str, Tuple[float, float]]
