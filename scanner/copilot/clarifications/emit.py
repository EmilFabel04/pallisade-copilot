"""Helper for FastAPI-side modules to emit ContextRequests via Next.js."""
import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def emit_via_nextjs(
    *,
    pipeline_stack_id: str,
    organization_id: Optional[str],
    kind: str,
    scope_type: str,
    scope_ref: str,
    payload: Dict[str, Any],
    priority: str = "normal",
) -> Optional[Dict[str, Any]]:
    """POST to Next.js /api/context-requests/create to create a ContextRequest.

    Returns ``{'context_request_id': str, 'suppressed': bool}`` or ``None`` on
    failure / when emission was skipped (missing pipeline, missing org, httpx
    unavailable, or HTTP error). Best-effort: never raises.
    """
    if not pipeline_stack_id:
        return None

    try:
        import httpx
    except ImportError:
        logger.debug("[Clarifications] httpx unavailable; skipping emit")
        return None

    base = (
        os.environ.get("NEXTJS_BASE_URL")
        or os.environ.get("INTERNAL_NEXTJS_URL")
        or "http://localhost:3000"
    )
    secret = os.environ.get("INTERNAL_API_SECRET", "pallisade-internal")

    if not organization_id:
        logger.debug(
            "[Clarifications] no organization_id available for scope_ref=%s; skipping emit",
            scope_ref,
        )
        return None

    body = {
        "pipelineStackId": pipeline_stack_id,
        "kind": kind,
        "scopeType": scope_type,
        "scopeRef": scope_ref,
        "payload": payload,
        "priority": priority,
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{base}/api/context-requests/create",
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Secret": secret,
                    "X-Organization-Id": organization_id,
                },
                json=body,
            )
        if resp.status_code >= 400:
            logger.warning(
                "[Clarifications] create failed (%s): %s",
                resp.status_code,
                resp.text[:200],
            )
            return None
        data = resp.json()
        return {
            "context_request_id": data.get("id"),
            "suppressed": bool(data.get("suppressed")),
        }
    except Exception as exc:
        logger.debug("[Clarifications] create POST raised: %s", exc)
        return None
