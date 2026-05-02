"""Read the most recent successful probe run for a CUSTOM_SOURCE dataset."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


def latest_probe_run_for(integration_id: str, dataset_id: str) -> Optional[Dict[str, Any]]:
    """Return the most recent SUCCESS probe run, or None."""
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT "rowCount", "latestTimestamp", "columnSchema",
                       "nullCounts", "distinctCounts", "minMaxNumeric",
                       "probedAt"
                FROM "CustomSourceProbeRun"
                WHERE "integrationId" = %s AND "datasetId" = %s AND status = 'SUCCESS'
                ORDER BY "probedAt" DESC
                LIMIT 1
                """,
                (integration_id, dataset_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "row_count": row[0],
                "latest_timestamp": row[1],
                "column_schema": row[2] if isinstance(row[2], (dict, list)) else (json.loads(row[2]) if row[2] else None),
                "null_counts": row[3] if isinstance(row[3], dict) else (json.loads(row[3]) if row[3] else {}),
                "distinct_counts": row[4] if isinstance(row[4], dict) else (json.loads(row[4]) if row[4] else {}),
                "min_max_numeric": row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {}),
                "probed_at": row[6],
            }
    finally:
        conn.close()


def previous_probe_run_for(integration_id: str, dataset_id: str) -> Optional[Dict[str, Any]]:
    """Return the second-most-recent SUCCESS probe run, or None.

    Used by the schema-drift monitor to compare the latest probe's column
    schema against the previous one.
    """
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT "rowCount", "latestTimestamp", "columnSchema",
                       "nullCounts", "distinctCounts", "minMaxNumeric",
                       "probedAt"
                FROM "CustomSourceProbeRun"
                WHERE "integrationId" = %s AND "datasetId" = %s AND status = 'SUCCESS'
                ORDER BY "probedAt" DESC
                OFFSET 1 LIMIT 1
                """,
                (integration_id, dataset_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "row_count": row[0],
                "latest_timestamp": row[1],
                "column_schema": row[2] if isinstance(row[2], (dict, list)) else (json.loads(row[2]) if row[2] else None),
                "null_counts": row[3] if isinstance(row[3], dict) else (json.loads(row[3]) if row[3] else {}),
                "distinct_counts": row[4] if isinstance(row[4], dict) else (json.loads(row[4]) if row[4] else {}),
                "min_max_numeric": row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else {}),
                "probed_at": row[6],
            }
    finally:
        conn.close()
