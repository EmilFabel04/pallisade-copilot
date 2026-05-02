"""
Source Verify Router.

Exposes POST /api/v1/integrations/source/verify — streams per-dataset dry-probe
results via Server-Sent Events (SSE). Runs HttpProbeAdapter.probe() for every
dataset in the wizard's accumulated config and emits one `dataset_result` event
per dataset, followed by a final `complete` event.

NEVER persists any Integration row. The endpoint is a verification gate only.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from scanner.adapters.http_probe import HttpProbeAdapter, ProbeError
from scanner.secret_stash.stash import resolve_secret_ref
from scanner.api.security.verify_token import (
    issue_verify_token,
    compute_config_hash,
)
from ..auth import require_principal, ActingPrincipal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrations/source", tags=["source-verify"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AuthBody(BaseModel):
    """Authentication config sent by the wizard.

    ``secret_ref`` is an opaque stash reference created by
    POST /api/v1/integrations/source/stash-secret — NOT the raw credential.
    The endpoint resolves it via :func:`~scanner.secret_stash.stash.resolve_secret_ref`
    before passing the real secret to the probe adapter.
    """

    kind: str
    header_name: Optional[str] = None
    username: Optional[str] = None
    secret_ref: str


class DatasetBody(BaseModel):
    id: str
    endpoint: str
    json_root: Optional[str] = None
    timestamp_column: str
    lands_in: Optional[str] = None
    cursor_param: Optional[str] = None


class VerifyRequest(BaseModel):
    name: str
    platform_label: str
    base_url: str
    auth: AuthBody
    schedule: str
    stack_id: Optional[str] = None
    datasets: List[DatasetBody]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_secret(auth: AuthBody, principal: ActingPrincipal) -> str:
    """Resolve secret_ref to runtime secret value via the stash.

    Raises HTTPException(400) if the ref is expired, unknown, or owned by a
    different user.
    """
    secret = resolve_secret_ref(auth.secret_ref, owner_id=principal.user_id)
    if secret is None:
        raise HTTPException(
            status_code=400,
            detail="secret_ref invalid or expired — re-enter credentials",
        )
    return secret


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/verify")
async def verify(
    body: VerifyRequest,
    principal: ActingPrincipal = Depends(require_principal),
) -> Any:
    """Stream per-dataset dry-probe results via SSE.

    Emits:
    - One ``dataset_result`` event per dataset with status=ok|error.
    - A final ``complete`` event with all_pass and failed_count.

    Never persists Integration rows.
    """
    if not body.datasets:
        raise HTTPException(status_code=422, detail="datasets must be non-empty")

    secret_value = _resolve_secret(body.auth, principal)
    adapter = HttpProbeAdapter(
        base_url=body.base_url,
        auth={
            "kind": body.auth.kind,
            "header_name": body.auth.header_name,
            "username": body.auth.username,
            "secret": secret_value,
        },
    )

    # Pre-compute the config hash from the config-equivalent subset of the verify
    # body.  We hash only the fields that the wizard will send in body.config when
    # calling POST /api/integrations — name, stack_id, and verify_token are excluded
    # because they don't affect probe semantics and may differ at persist-time.
    # The Next.js side hashes body.config over the same keys (computeConfigHash in
    # lib/server/verify-token.ts), so both sides must produce the same digest.
    config_equiv: dict = {
        "platform_label": body.platform_label,
        "base_url": body.base_url,
        "auth": body.auth.model_dump(),
        "datasets": [ds.model_dump() for ds in body.datasets],
        "schedule": body.schedule,
    }
    config_hash = compute_config_hash(config_equiv)

    async def event_stream():
        all_pass = True
        failed = 0

        for ds in body.datasets:
            try:
                # cursor_value not threaded through verify — full-table probe is
                # intentional for one-shot verification.
                bundle = adapter.probe(
                    {
                        "endpoint": ds.endpoint,
                        "json_root": ds.json_root,
                        "timestamp_column": ds.timestamp_column,
                        "cursor_param": ds.cursor_param,
                    }
                )
                payload: dict = {
                    "dataset_id": ds.id,
                    "status": "ok",
                    "row_count": bundle.row_count,
                    "latest_timestamp": (
                        bundle.latest_timestamp.isoformat()
                        if bundle.latest_timestamp
                        else None
                    ),
                    # schema_match is reserved for future warehouse-vs-source schema
                    # comparison; always true in V1 (we compare against expected_schema
                    # only when it's set, which Path 1 candidates don't have).
                    "schema_match": True,
                }
            except ProbeError as e:
                all_pass = False
                failed += 1
                payload = {
                    "dataset_id": ds.id,
                    "status": "error",
                    "code": e.code,
                    "message": e.message,
                }
            except Exception as e:  # noqa: BLE001 — never crash the SSE stream mid-flight
                logger.exception("verify probe raised non-ProbeError for dataset %s", ds.id)
                all_pass = False
                failed += 1
                payload = {
                    "dataset_id": ds.id,
                    "status": "error",
                    "code": "unknown",
                    "message": str(e),
                }

            yield {"event": "dataset_result", "data": json.dumps(payload)}

        complete_payload: dict = {"all_pass": all_pass, "failed_count": failed}
        if all_pass:
            # Issue a short-lived HMAC-signed token so the Next.js persist route
            # can verify that this exact config was successfully probed.
            verify_token = issue_verify_token({
                "org_id": principal.organization_id,
                "config_hash": config_hash,
            })
            complete_payload["verify_token"] = verify_token

        yield {
            "event": "complete",
            "data": json.dumps(complete_payload),
        }

    return EventSourceResponse(event_stream())
