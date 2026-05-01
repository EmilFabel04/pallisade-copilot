"""
Persist HttpProbeAdapter results to the CustomSourceProbeRun table.

NEVER persists raw rows — only derived metrics from MetricBundle.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from scanner.adapters.http_probe import MetricBundle

logger = structlog.get_logger()


def _json_safe_fingerprints(fingerprints):
    """HLL bytes → base64 strings (jsonb cannot hold raw bytes)."""
    return {col: base64.b64encode(buf).decode("ascii") for col, buf in fingerprints.items()}


def _json_safe_min_max(min_max_numeric):
    """Tuples → lists (json has no tuple type)."""
    return {col: list(pair) for col, pair in min_max_numeric.items()}


def _new_run_id() -> str:
    """Mimic cuid()-ish 25-char id (Prisma's default for the table)."""
    return uuid.uuid4().hex[:25]


def save_probe_run(
    integration_id: str,
    dataset_id: str,
    bundle: MetricBundle,
    duration_ms: Optional[int] = None,
) -> str:
    """Insert a successful CustomSourceProbeRun. Returns the new row id."""
    from scanner.scheduler.service import _get_connection

    run_id = _new_run_id()

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "CustomSourceProbeRun" (
                    id, "integrationId", "datasetId", status,
                    "rowCount", "latestTimestamp",
                    "columnSchema", "nullCounts", "distinctCounts",
                    "valueFingerprints", "minMaxNumeric",
                    "probedAt", "durationMs"
                )
                VALUES (
                    %s, %s, %s, 'SUCCESS',
                    %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s::jsonb,
                    %s, %s
                )
                """,
                (
                    run_id, integration_id, dataset_id,
                    bundle.row_count, bundle.latest_timestamp,
                    json.dumps(bundle.column_schema),
                    json.dumps(bundle.null_counts),
                    json.dumps(bundle.distinct_counts),
                    json.dumps(_json_safe_fingerprints(bundle.value_fingerprints)),
                    json.dumps(_json_safe_min_max(bundle.min_max_numeric)),
                    bundle.probed_at, duration_ms,
                ),
            )
        conn.commit()
        logger.info(
            "[ProbeRun] saved",
            run_id=run_id,
            integration_id=integration_id,
            dataset_id=dataset_id,
            row_count=bundle.row_count,
            duration_ms=duration_ms,
        )
        return run_id
    finally:
        conn.close()


def save_probe_failure(
    integration_id: str,
    dataset_id: str,
    error_code: str,
    error_message: str,
    duration_ms: Optional[int] = None,
) -> str:
    """Insert a failed CustomSourceProbeRun. Returns the new row id."""
    from scanner.scheduler.service import _get_connection

    run_id = _new_run_id()

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "CustomSourceProbeRun" (
                    id, "integrationId", "datasetId", status,
                    "errorCode", "errorMessage",
                    "probedAt", "durationMs"
                )
                VALUES (%s, %s, %s, 'FAILED', %s, %s, %s, %s)
                """,
                (
                    run_id, integration_id, dataset_id,
                    error_code, error_message,
                    datetime.now(timezone.utc), duration_ms,
                ),
            )
        conn.commit()
        logger.info(
            "[ProbeRun] saved failure",
            run_id=run_id,
            integration_id=integration_id,
            dataset_id=dataset_id,
            error_code=error_code,
            duration_ms=duration_ms,
        )
        return run_id
    finally:
        conn.close()
