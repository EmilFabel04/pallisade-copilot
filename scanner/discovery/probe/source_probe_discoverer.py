from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

from scanner.discovery.types import (
    ColumnMetadata,
    DatasetCandidate,
    DiscoveryError,
)
from scanner.adapters.http_probe import _infer_type, _parse_iso8601

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 30
_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB

_TIMESTAMP_NAME_HINTS = (
    "_at", "_ts", "timestamp", "created", "updated", "modified", "occurred", "event_time",
)


def _apply_auth(session: requests.Session, auth: Dict[str, Any]) -> None:
    kind = auth.get("kind")
    if kind == "api_key":
        session.headers[auth.get("header_name") or "X-API-Key"] = auth["secret"]
    elif kind == "bearer":
        session.headers["Authorization"] = f"Bearer {auth['secret']}"
    elif kind == "basic":
        session.auth = (auth["username"], auth["secret"])


def _find_arrays(obj: Any, path: str = "", max_depth: int = 3) -> List[Tuple[str, list]]:
    """Walk JSON up to max_depth and return [(dotted_path, list)] for every array of objects."""
    out: List[Tuple[str, list]] = []
    if max_depth < 0:
        return out
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        out.append((path, obj))
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            out.extend(_find_arrays(v, child_path, max_depth - 1))
    return out


def _detect_timestamp_column(rows: list) -> Optional[str]:
    if not rows:
        return None
    first = rows[0]
    for col, val in first.items():
        col_l = col.lower()
        if any(h in col_l for h in _TIMESTAMP_NAME_HINTS):
            if isinstance(val, str) and _parse_iso8601(val) is not None:
                return col
            if isinstance(val, (int, float)):
                return col
    return None


def _infer_columns(rows: list) -> List[ColumnMetadata]:
    if not rows:
        return []
    first = rows[0]
    return [
        ColumnMetadata(
            name=col,
            data_type=_infer_type(val),
            is_nullable=any(r.get(col) is None for r in rows),
        )
        for col, val in first.items()
    ]


class SourceProbeDiscoverer:
    """Path 1: probe a single endpoint, find array roots, infer schema."""

    def discover(
        self,
        base_url: str,
        endpoint: str,
        auth: Dict[str, Any],
    ) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        url = base_url.rstrip("/") + endpoint
        session = requests.Session()
        try:
            _apply_auth(session, auth)
        except KeyError as e:
            return [], DiscoveryError(code="auth_failed", message=f"missing auth field: {e}")

        try:
            resp = session.get(url, timeout=_TIMEOUT_SEC, stream=True)
        except requests.exceptions.RequestException as e:
            return [], DiscoveryError(code="host_unreachable", message=str(e))

        if resp.status_code in (401, 403):
            return [], DiscoveryError(code="auth_failed", message=f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            return [], DiscoveryError(code="host_unreachable", message=f"HTTP {resp.status_code}")

        body = b""
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                body += chunk
                if len(body) > _MAX_BYTES:
                    return [], DiscoveryError(code="response_too_large", message=f">{_MAX_BYTES} bytes")

        try:
            import json as _json
            parsed = _json.loads(body)
        except ValueError as e:
            return [], DiscoveryError(code="malformed_json", message=str(e))

        arrays = _find_arrays(parsed)
        candidates: List[DatasetCandidate] = []
        for path, rows in arrays:
            candidates.append(
                DatasetCandidate(
                    source='probe',
                    endpoint=endpoint,
                    json_root=path or None,
                    timestamp_column=_detect_timestamp_column(rows),
                    expected_schema=_infer_columns(rows),
                    lands_in=None,
                    confidence=0.7,
                )
            )
        return candidates, None
