"""
Probe runner — finds CUSTOM_SOURCE integrations with due nextProbeAt
and runs HttpProbeAdapter for each configured dataset.

Sync (called from the async scheduler tick). Persists derived metrics
only — never raw rows — via scanner.drivers.source.probe_persistence.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from scanner.adapters.http_probe import HttpProbeAdapter, ProbeError
from scanner.drivers.source.probe_persistence import save_probe_failure, save_probe_run

logger = structlog.get_logger()

_SCHEDULE_TO_TIMEDELTA = {
    "hourly": timedelta(hours=1),
    "every_6h": timedelta(hours=6),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


def _fetch_due_integrations() -> List[Dict[str, Any]]:
    """Return CUSTOM_SOURCE integrations with nextProbeAt <= now.

    Also returns the encrypted credentials envelope so _resolve_secret can
    decrypt without a second round-trip to the DB per dataset.
    """
    from scanner.scheduler.service import _get_connection
    now = datetime.now(timezone.utc)
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, config, credentials, "probeSchedule"
                FROM "Integration"
                WHERE type = 'CUSTOM_SOURCE'
                  AND status = 'ACTIVE'
                  AND "nextProbeAt" IS NOT NULL
                  AND "nextProbeAt" <= %s
                FOR UPDATE SKIP LOCKED
                """,
                (now,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.commit()
        return rows
    finally:
        conn.close()


def _mark_next_probe_at(integration_id: str, schedule: str) -> None:
    """Advance Integration.nextProbeAt by the configured cadence."""
    delta = _SCHEDULE_TO_TIMEDELTA.get(schedule, timedelta(days=1))
    next_at = datetime.now(timezone.utc) + delta
    from scanner.scheduler.service import _get_connection
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Integration" SET "nextProbeAt" = %s WHERE id = %s',
                (next_at, integration_id),
            )
        conn.commit()
    finally:
        conn.close()


def _resolve_secret(credentials: Any) -> str:
    """Pull the auth secret out of an Integration.credentials JSON value.

    Mirrors the pattern used in scanner.scheduler.executor: credentials
    may be either a plaintext dict, or a {"encrypted": <hex>} envelope
    produced by lib/crypto.ts encrypt(). For CUSTOM_SOURCE the decrypted
    payload is expected to be a JSON object containing a `secret` key
    (the bearer token / api key / basic password).
    """
    from scanner.scheduler.executor import _decrypt

    creds = credentials
    # psycopg2 returns jsonb as already-parsed dicts, but tolerate strings too.
    if isinstance(creds, str):
        try:
            creds = json.loads(creds)
        except json.JSONDecodeError:
            raise RuntimeError("integration credentials is not valid JSON")

    if not isinstance(creds, dict):
        raise RuntimeError("integration has no credentials")

    if "encrypted" in creds:
        try:
            decrypted = _decrypt(creds["encrypted"])
            creds = json.loads(decrypted)
        except Exception as exc:
            raise RuntimeError(f"failed to decrypt credentials: {exc}") from exc

    secret = creds.get("secret")
    if not secret:
        raise RuntimeError("integration credentials missing 'secret'")
    return secret


def run_due_probes() -> int:
    """Run all due CUSTOM_SOURCE probes.

    Returns the number of (integration, dataset) probes attempted. Always
    advances nextProbeAt — even on failure — so a broken integration
    cannot indefinitely lock its row.
    """
    # Feature-flag kill-switch: if SOURCES_CATEGORY is disabled, don't even
    # touch the DB. Mirrors the gate in scanner/drivers/loader.py.
    if os.environ.get("FEATURE_SOURCES_CATEGORY", "").lower() not in ("1", "true", "yes"):
        return 0

    integrations = _fetch_due_integrations()
    attempted = 0

    for integration in integrations:
        config = integration.get("config") or {}
        datasets = config.get("datasets") or []
        auth = dict(config.get("auth") or {})

        # Resolve the secret. In V1, the auth stanza in config carries
        # `kind` (bearer/api_key/basic) and optionally `username` /
        # `header_name`; the actual secret material lives in
        # Integration.credentials. If config.auth.secret is already
        # populated (legacy / dev path) we pass it through.
        if not auth.get("secret"):
            try:
                auth["secret"] = _resolve_secret(integration.get("credentials"))
            except Exception as exc:
                logger.error(
                    "[ProbeRunner] secret resolution failed",
                    integration_id=integration["id"],
                    error=str(exc),
                )
                _mark_next_probe_at(
                    integration["id"],
                    integration.get("probeSchedule") or "daily",
                )
                continue

        adapter = HttpProbeAdapter(
            base_url=config.get("base_url", ""),
            auth=auth,
        )

        for ds in datasets:
            attempted += 1
            start = time.time()
            try:
                bundle = adapter.probe({
                    "endpoint": ds["endpoint"],
                    "timestamp_column": ds.get("timestamp_column"),
                    "json_root": ds.get("json_root"),
                    "cursor_param": ds.get("cursor_param"),
                })
                duration = int((time.time() - start) * 1000)
                save_probe_run(
                    integration["id"], ds["id"], bundle,
                    duration_ms=duration,
                )
            except ProbeError as exc:
                duration = int((time.time() - start) * 1000)
                save_probe_failure(
                    integration["id"], ds["id"],
                    error_code=exc.code, error_message=exc.message,
                    duration_ms=duration,
                )
                logger.warning(
                    "[ProbeRunner] probe failed",
                    integration_id=integration["id"],
                    dataset_id=ds.get("id"),
                    error_code=exc.code,
                )
            except Exception as exc:
                duration = int((time.time() - start) * 1000)
                save_probe_failure(
                    integration["id"], ds["id"],
                    error_code="unknown_error", error_message=str(exc),
                    duration_ms=duration,
                )
                logger.error(
                    "[ProbeRunner] probe unexpected error",
                    integration_id=integration["id"],
                    dataset_id=ds.get("id"),
                    error=str(exc),
                )

        _mark_next_probe_at(
            integration["id"],
            integration.get("probeSchedule") or "daily",
        )

    return attempted
