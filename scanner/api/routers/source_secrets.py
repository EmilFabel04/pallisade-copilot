"""
Source Secrets Router.

Exposes two endpoints for the Custom Source wizard's credential lifecycle:

POST /api/v1/integrations/source/stash-secret
    Accepts a raw credential, stashes it in the in-process TTLCache, and
    returns an opaque ``secret_ref``.  The wizard calls this after step 2
    (Connection) so that subsequent /discover and /verify calls never carry
    the raw secret over the wire.

POST /api/v1/integrations/source/resolve-secret
    Resolves a ``secret_ref`` back to the raw secret.  Called by the Next.js
    persist route (/api/integrations) immediately before writing the
    Integration row, so the durable config can store the resolved secret
    rather than an ephemeral ref.

Both endpoints are auth-gated via ``require_principal`` and enforce owner
isolation — a ref issued for user A cannot be resolved by user B.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from scanner.secret_stash.stash import stash_secret, resolve_secret_ref
from ..auth import require_principal, ActingPrincipal

router = APIRouter(prefix="/api/v1/integrations/source", tags=["source-secrets"])

_STASH_TTL_SECONDS = 1800  # 30 minutes — must match stash.py


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StashSecretRequest(BaseModel):
    secret: str


class StashSecretResponse(BaseModel):
    secret_ref: str
    expires_at: str  # ISO-8601


class ResolveSecretRequest(BaseModel):
    secret_ref: str


class ResolveSecretResponse(BaseModel):
    secret: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/stash-secret", response_model=StashSecretResponse)
async def stash_secret_endpoint(
    body: StashSecretRequest,
    principal: ActingPrincipal = Depends(require_principal),
) -> StashSecretResponse:
    """Stash a raw credential and return an opaque ``secret_ref``.

    The ref is scoped to the calling user; only the same user can resolve it.
    The ref expires after 30 minutes (one wizard session).
    """
    if not body.secret:
        raise HTTPException(status_code=400, detail="secret must be non-empty")

    ref = stash_secret(body.secret, owner_id=principal.user_id)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=_STASH_TTL_SECONDS)
    ).isoformat()
    return StashSecretResponse(secret_ref=ref, expires_at=expires_at)


@router.post("/resolve-secret", response_model=ResolveSecretResponse)
async def resolve_secret_endpoint(
    body: ResolveSecretRequest,
    principal: ActingPrincipal = Depends(require_principal),
) -> ResolveSecretResponse:
    """Resolve a ``secret_ref`` to the raw credential.

    Returns 400 if the ref is expired, unknown, or owned by a different user.
    This endpoint is called by the Next.js persist route at save-time to
    hand off the resolved secret for durable storage.
    """
    secret = resolve_secret_ref(body.secret_ref, owner_id=principal.user_id)
    if secret is None:
        raise HTTPException(
            status_code=400,
            detail="secret_ref invalid or expired — re-enter credentials",
        )
    return ResolveSecretResponse(secret=secret)
