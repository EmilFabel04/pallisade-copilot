"""
Waitlist Router.

Lets users register interest in coming-soon source connectors
(salesforce, shopify, hubspot).  The endpoint is idempotent:
the first POST for a given (user, connector) pair returns 201;
subsequent calls return 200 with the original record.
"""

from __future__ import annotations

import os
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

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            # Check for an existing record (idempotency).
            cur.execute(
                'SELECT "connectorId", "requestedAt" '
                'FROM "SourceConnectorWaitlist" '
                'WHERE "userId" = %s AND "connectorId" = %s',
                (principal.user_id, body.connector_id),
            )
            row = cur.fetchone()

        if row:
            connector_id, requested_at = row
            logger.info(
                "[Waitlist] already on waitlist",
                user_id=principal.user_id,
                connector_id=connector_id,
            )
            return JSONResponse(
                status_code=200,
                content={
                    "connector_id": connector_id,
                    "requested_at": (
                        requested_at.isoformat()
                        if isinstance(requested_at, datetime)
                        else str(requested_at)
                    ),
                },
            )

        # Insert new record.
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "SourceConnectorWaitlist" '
                '("id", "userId", "connectorId", "requestedAt") '
                "VALUES (gen_random_uuid()::text, %s, %s, NOW()) "
                'RETURNING "connectorId", "requestedAt"',
                (principal.user_id, body.connector_id),
            )
            new_row = cur.fetchone()
        conn.commit()

        connector_id, requested_at = new_row
        logger.info(
            "[Waitlist] joined waitlist",
            user_id=principal.user_id,
            connector_id=connector_id,
        )
        return JSONResponse(
            status_code=201,
            content={
                "connector_id": connector_id,
                "requested_at": (
                    requested_at.isoformat()
                    if isinstance(requested_at, datetime)
                    else str(requested_at)
                ),
            },
        )
    finally:
        conn.close()
