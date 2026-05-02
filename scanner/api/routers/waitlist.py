"""
Waitlist Router.

Lets users register interest in coming-soon source connectors
(salesforce, shopify, hubspot).  The endpoint is idempotent:
the first POST for a given (user, connector) pair returns 201;
subsequent calls return 200 with the original record.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..auth import require_principal, ActingPrincipal

logger = structlog.get_logger()

router = APIRouter(prefix="/waitlist", tags=["waitlist"])

ALLOWED_CONNECTORS = {"salesforce", "shopify", "hubspot"}


# ---------------------------------------------------------------------------
# Database helper (same pattern as scheduler/service.py)
# ---------------------------------------------------------------------------


def _get_connection():
    """Get a psycopg2 connection using DATABASE_URL.

    Indirect import so tests can monkeypatch this module's symbol.
    """
    import psycopg2
    from urllib.parse import urlparse, parse_qs

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")

    parsed = urlparse(url)
    params = {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/").split("?")[0],
    }
    qs = parse_qs(parsed.query)
    if "sslmode" in qs:
        params["sslmode"] = qs["sslmode"][0]

    return psycopg2.connect(**params)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class WaitlistRequest(BaseModel):
    connector_id: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/source-connector")
async def join_waitlist(
    body: WaitlistRequest,
    principal: ActingPrincipal = Depends(require_principal),
):
    """Join the waitlist for a coming-soon source connector.

    Returns 201 on first registration, 200 if already on the waitlist.
    Returns 400 for unknown connector_id values.
    """
    if body.connector_id not in ALLOWED_CONNECTORS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown connector_id: {body.connector_id!r}",
        )

    conn = None
    conn = _get_connection()
    try:
        new_id = str(uuid.uuid4())
        with conn.cursor() as cur:
            # Single atomic upsert — eliminates the SELECT-then-INSERT race condition.
            # (xmax = 0) is True only when this row was just inserted (not a conflict).
            # Python-side UUID avoids a pgcrypto dependency on gen_random_uuid().
            cur.execute(
                'INSERT INTO "SourceConnectorWaitlist" '
                '("id", "userId", "connectorId", "requestedAt") '
                'VALUES (%s, %s, %s, NOW()) '
                'ON CONFLICT ("userId", "connectorId") DO UPDATE '
                'SET "connectorId" = EXCLUDED."connectorId" '
                'RETURNING "connectorId", "requestedAt", (xmax = 0) AS inserted',
                (new_id, principal.user_id, body.connector_id),
            )
            row = cur.fetchone()
        conn.commit()

        connector_id, requested_at, inserted = row
        status_code = 201 if inserted else 200
        logger.info(
            "[Waitlist] %s waitlist",
            "joined" if inserted else "already on",
            user_id=principal.user_id,
            connector_id=connector_id,
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "connector_id": connector_id,
                "requested_at": (
                    requested_at.isoformat()
                    if hasattr(requested_at, "isoformat")
                    else str(requested_at)
                ),
            },
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
