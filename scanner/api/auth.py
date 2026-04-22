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
