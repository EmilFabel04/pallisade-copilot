"""Trust-boundary authentication for Next.js ↔ FastAPI.

Implements the trusted-subsystem pattern:
- InternalAuthMiddleware: verifies X-Internal-Auth shared secret (constant-time).
- ActingPrincipalMiddleware: parses X-Acting-User/X-Acting-Org into request.state.principal.
- require_principal: FastAPI dependency for routers.
"""

import hmac
import uuid
from dataclasses import dataclass
from typing import Optional

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = structlog.get_logger()

HEADER_INTERNAL_AUTH = "x-internal-auth"
HEADER_ACTING_USER = "x-acting-user"
HEADER_ACTING_ORG = "x-acting-org"
HEADER_REQUEST_ID = "x-request-id"

# Paths exempt from internal-auth check (liveness/readiness probes).
EXEMPT_PATHS = {"/health", "/healthz", "/docs", "/redoc", "/openapi.json"}


@dataclass(frozen=True)
class ActingPrincipal:
    """Identity of the end user on whose behalf Next.js is calling FastAPI."""
    user_id: str
    organization_id: str
    request_id: str


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """Rejects requests that don't carry the shared secret."""

    def __init__(self, app, settings):
        super().__init__(app)
        self._expected = settings.shared_secret.encode()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in EXEMPT_PATHS:
            return await call_next(request)

        provided = request.headers.get(HEADER_INTERNAL_AUTH, "")
        if not provided or not hmac.compare_digest(provided.encode(), self._expected):
            logger.warning(
                "auth.internal.rejected",
                path=path,
                request_id=request.headers.get(HEADER_REQUEST_ID, "unknown"),
            )
            return JSONResponse(status_code=401, content={"error": "unauthorized"})

        return await call_next(request)


class ActingPrincipalMiddleware(BaseHTTPMiddleware):
    """Parses caller identity headers into request.state.principal.

    Runs AFTER InternalAuthMiddleware (added first, Starlette wraps in reverse).
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        user_id = request.headers.get(HEADER_ACTING_USER, "").strip()
        org_id = request.headers.get(HEADER_ACTING_ORG, "").strip()

        if not user_id or not org_id:
            logger.warning(
                "auth.principal.missing",
                path=request.url.path,
                has_user=bool(user_id),
                has_org=bool(org_id),
            )
            return JSONResponse(status_code=400, content={"error": "missing_principal"})

        request_id = request.headers.get(HEADER_REQUEST_ID, "").strip() or f"srv_{uuid.uuid4().hex}"
        request.state.principal = ActingPrincipal(
            user_id=user_id,
            organization_id=org_id,
            request_id=request_id,
        )
        return await call_next(request)


def require_principal(request: Request) -> ActingPrincipal:
    """FastAPI dependency: pull the principal set by ActingPrincipalMiddleware."""
    principal: Optional[ActingPrincipal] = getattr(request.state, "principal", None)
    if principal is None:
        # Should not happen if middleware is registered — fail loudly.
        raise RuntimeError("ActingPrincipalMiddleware is not registered")
    return principal
