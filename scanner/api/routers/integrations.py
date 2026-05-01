"""
Integrations API Router.

Per-integration operational endpoints. Currently exposes a single
operator-facing route to manually force a probe for a CUSTOM_SOURCE
integration so wizards / debugging / smoke tests don't have to wait
for the next scheduler tick.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import structlog

logger = structlog.get_logger()

router = APIRouter(prefix="/integrations")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ProbeNowResponse(BaseModel):
    probes_attempted: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_connection():
    """Indirect import so tests can monkeypatch this module's symbol.

    The real connection factory lives on scanner.scheduler.service; we
    re-export it here so that patching
    `scanner.api.routers.integrations._get_connection` is sufficient.
    """
    from scanner.scheduler.service import _get_connection as _real_get_connection
    return _real_get_connection()


def run_due_probes() -> int:
    """Indirect import so tests can monkeypatch this module's symbol."""
    from scanner.scheduler.probe_runner import run_due_probes as _real_run_due_probes
    return _real_run_due_probes()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{integration_id}/probe-now", response_model=ProbeNowResponse)
async def probe_now(integration_id: str) -> ProbeNowResponse:
    """Manually trigger a probe for a CUSTOM_SOURCE integration.

    Marks ``Integration.nextProbeAt = NOW()`` for the given id (only when
    the row exists AND is a CUSTOM_SOURCE), then synchronously calls
    ``run_due_probes()``. Returns the number of (integration, dataset)
    probes the runner attempted.

    Returns 404 if the integration doesn't exist or isn't a CUSTOM_SOURCE.
    The single ``UPDATE ... WHERE id = X AND type = 'CUSTOM_SOURCE'``
    handles both cases via ``rowcount == 0``.
    """
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Integration" '
                'SET "nextProbeAt" = %s '
                "WHERE id = %s AND type = 'CUSTOM_SOURCE'",
                (datetime.now(timezone.utc), integration_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="integration not found or not CUSTOM_SOURCE",
                )
        conn.commit()
    finally:
        conn.close()

    n = run_due_probes()
    logger.info(
        "[Integrations] probe-now dispatched",
        integration_id=integration_id,
        probes_attempted=n,
    )
    return ProbeNowResponse(probes_attempted=n)
