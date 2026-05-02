"""
WarehouseDiscoverer — Path 3: read warehouse table schemas for user-picked landing tables.

Given a list of fully-qualified table names (FQNs) such as "snowflake.raw.water_meters",
this discoverer resolves the appropriate warehouse adapter, fetches column metadata,
and returns one DatasetCandidate per FQN with:
  - source='warehouse'
  - confidence=0.9
  - lands_in=<the FQN>
  - timestamp_column detected via name/type heuristic
  - expected_schema populated from the adapter
"""
from __future__ import annotations
import logging
from typing import List, Optional, Tuple

from scanner.discovery.types import (
    ColumnMetadata,
    DatasetCandidate,
    DiscoveryError,
)

logger = logging.getLogger(__name__)

# Name fragments that suggest a timestamp column (checked via substring match on lowercase name).
_TIMESTAMP_NAME_HINTS = (
    "_at", "_ts", "timestamp", "created", "updated", "modified", "occurred", "event_time",
)
# Data types that are definitively timestamp-flavoured.
_TIMESTAMP_TYPES = ("TIMESTAMP", "DATETIME", "TIMESTAMP_NTZ", "TIMESTAMPTZ", "DATE")


def adapter_for_fqn(fqn: str, org_id: Optional[str] = None, stack_id: Optional[str] = None):
    """Resolve an FQN like 'snowflake.raw.water_meters' to a configured adapter instance."""
    from scanner.adapters.factory import build_adapter_from_fqn
    return build_adapter_from_fqn(fqn, org_id=org_id, stack_id=stack_id)


def _detect_ts_col(schema: List[dict]) -> Optional[str]:
    """Return the first column whose name or type suggests a timestamp; None if none found."""
    for col in schema:
        name = col["column_name"].lower()
        dtype = (col.get("data_type") or "").upper()
        if dtype in _TIMESTAMP_TYPES or any(h in name for h in _TIMESTAMP_NAME_HINTS):
            return col["column_name"]
    return None


class WarehouseDiscoverer:
    """Path 3: read warehouse table schemas for user-picked landing tables."""

    def __init__(self, org_id: Optional[str] = None, stack_id: Optional[str] = None) -> None:
        self._org_id = org_id
        self._stack_id = stack_id

    def discover(self, hints: List[str]) -> Tuple[List[DatasetCandidate], Optional[DiscoveryError]]:
        if not hints:
            return [], DiscoveryError(code='no_warehouse_hint', message='no warehouse hints provided')

        candidates: List[DatasetCandidate] = []
        for fqn in hints:
            try:
                adapter = adapter_for_fqn(fqn, org_id=self._org_id, stack_id=self._stack_id)
                schema_rows = adapter.get_table_schema(fqn)
            except Exception as e:
                logger.warning("[WarehouseDiscoverer] failed for %s: %s", fqn, e)
                continue

            cols = [
                ColumnMetadata(
                    name=row["column_name"],
                    data_type=row.get("data_type") or "UNKNOWN",
                    is_nullable=bool(row.get("is_nullable", True)),
                )
                for row in schema_rows
            ]
            candidates.append(
                DatasetCandidate(
                    source='warehouse',
                    endpoint=None,
                    json_root=None,
                    timestamp_column=_detect_ts_col(schema_rows),
                    expected_schema=cols,
                    lands_in=fqn,
                    confidence=0.9,
                )
            )
        return candidates, None
