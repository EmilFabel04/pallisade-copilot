"""
HttpProbeAdapter — probes HTTP-accessible data sources to compute
monitoring metrics. NEVER returns or persists raw rows.

Used by CustomSourceDriver to back the SOURCE-layer integration type.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 30
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB
_MAX_ROWS = 50_000


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


class ProbeError(RuntimeError):
    """Probe failed. `code` is a stable string for the alert layer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class HttpProbeAdapter:
    """Probes an HTTP endpoint and returns a MetricBundle. Never returns rows."""

    def __init__(self, base_url: str, auth: Dict[str, Any]):
        self.base_url = base_url.rstrip("/")
        self.auth = auth or {}

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        kind = self.auth.get("kind")
        secret = self.auth.get("secret", "")
        if kind == "bearer":
            session.headers["Authorization"] = f"Bearer {secret}"
        elif kind == "api_key":
            header_name = self.auth.get("header_name") or "X-API-Key"
            session.headers[header_name] = secret
        elif kind == "basic":
            username = self.auth.get("username", "")
            session.auth = (username, secret)
        else:
            raise ProbeError("invalid_auth", f"unsupported auth kind: {kind!r}")
        return session

    def probe(self, dataset_config: Dict[str, Any]) -> MetricBundle:
        endpoint = dataset_config["endpoint"]
        timestamp_column = dataset_config.get("timestamp_column")

        url = f"{self.base_url}{endpoint}"
        session = self._build_session()

        try:
            resp = session.get(url, timeout=_DEFAULT_TIMEOUT_SEC, stream=True)
        except requests.Timeout:
            raise ProbeError("timeout", f"request timed out after {_DEFAULT_TIMEOUT_SEC}s")
        except requests.RequestException as exc:
            raise ProbeError("network_error", str(exc))

        if resp.status_code == 401 or resp.status_code == 403:
            raise ProbeError("auth_failed", f"HTTP {resp.status_code}")
        if not (200 <= resp.status_code < 300):
            raise ProbeError("http_error", f"HTTP {resp.status_code}")

        # Read with size cap
        content = resp.raw.read(_MAX_RESPONSE_BYTES + 1, decode_content=True)
        if len(content) > _MAX_RESPONSE_BYTES:
            raise ProbeError("response_too_large", f"response exceeded {_MAX_RESPONSE_BYTES} bytes")

        import json as _json
        try:
            payload = _json.loads(content)
        except _json.JSONDecodeError as exc:
            raise ProbeError("malformed_json", str(exc))

        # JSON root navigation
        json_root = dataset_config.get("json_root")
        if json_root:
            for part in json_root.split("."):
                if not isinstance(payload, dict) or part not in payload:
                    raise ProbeError("json_root_not_found", f"path {json_root!r} missing")
                payload = payload[part]

        if not isinstance(payload, list):
            raise ProbeError("not_array", "expected JSON array of objects")

        return self._compute_metrics(payload, timestamp_column)

    def _compute_metrics(
        self, rows: List[Dict[str, Any]], timestamp_column: Optional[str],
    ) -> MetricBundle:
        if len(rows) > _MAX_ROWS:
            raise ProbeError("too_many_rows", f"more than {_MAX_ROWS} rows")

        row_count = len(rows)

        # Determine schema from first non-empty row
        column_schema: List[Dict[str, Any]] = []
        if rows:
            sample = rows[0]
            for col_name, value in sample.items():
                column_schema.append({
                    "name": col_name,
                    "data_type": _infer_type(value),
                    "is_nullable": True,  # JSON has no nullability concept
                })

        null_counts: Dict[str, int] = {col["name"]: 0 for col in column_schema}
        latest_ts: Optional[datetime] = None

        for row in rows:
            for col in column_schema:
                name = col["name"]
                if row.get(name) is None:
                    null_counts[name] += 1
            if timestamp_column:
                ts_val = row.get(timestamp_column)
                if isinstance(ts_val, str):
                    parsed = _parse_iso8601(ts_val)
                    if parsed and (latest_ts is None or parsed > latest_ts):
                        latest_ts = parsed

        return MetricBundle(
            probed_at=datetime.now(timezone.utc),
            row_count=row_count,
            latest_timestamp=latest_ts,
            column_schema=column_schema,
            null_counts=null_counts,
            distinct_counts={},        # filled in Task 9
            value_fingerprints={},     # filled in Task 9
            min_max_numeric={},        # filled in Task 9
        )


def _infer_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _parse_iso8601(value: str) -> Optional[datetime]:
    try:
        # Handle trailing Z
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None
