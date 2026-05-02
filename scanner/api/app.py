"""
Pallisade Co-Pilot - FastAPI Application
"""

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

# Ensure the repo root is on sys.path so `from scanner.X import Y` works
# when the server is started from inside the scanner/ directory.
# api/app.py -> api/ -> scanner/ -> repo_root/
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import structlog

from .dependencies import get_settings, setup_logging

# Setup logging on module load
setup_logging()
logger = structlog.get_logger()


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def enforce_loopback_in_production(environment: str, host: str) -> None:
    """Exit loudly if FastAPI is bound to a non-loopback interface in production.

    Called from create_app() when ENVIRONMENT=production. Host is read from
    the HOST env var, which is what uvicorn/gunicorn conventionally set.
    """
    if environment != "production":
        return
    if host not in _LOOPBACK_HOSTS:
        raise RuntimeError(
            f"startup.loopback_violation: FastAPI must bind to loopback in production, got host={host!r}"
        )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    # Refuse to boot on non-loopback in production.
    enforce_loopback_in_production(
        environment=settings.environment,
        host=os.getenv("HOST", "127.0.0.1"),
    )

    app = FastAPI(
        title="Pallisade Co-Pilot API",
        description="AI-powered data pipeline assistant",
        version=settings.version,
        docs_url="/docs",
        redoc_url="/redoc"
    )
    
    # Register auth middlewares FIRST — ordering note:
    # Starlette applies middlewares in reverse registration order, so the
    # add_middleware call made LAST runs FIRST on inbound requests.
    # We want: InternalAuth (outer) → ActingPrincipal (inner) → CORS → app.
    from .auth import InternalAuthMiddleware, ActingPrincipalMiddleware

    # CORS Middleware — explicit origins only in prod (enforced by Settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Internal-Auth",
            "X-Acting-User",
            "X-Acting-Org",
            "X-Request-Id",
        ],
    )
    app.add_middleware(ActingPrincipalMiddleware)
    app.add_middleware(InternalAuthMiddleware, settings=settings)
    
    # Request Logging Middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all requests with timing."""
        start_time = datetime.utcnow()
        response = await call_next(request)
        duration = (datetime.utcnow() - start_time).total_seconds() * 1000
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration, 2)
        )
        return response
    
    # Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler for unhandled errors."""
        logger.error("unhandled_exception", error=str(exc), path=request.url.path)
        # Only echo the exception message back to the client in development —
        # exception messages from drivers can include credentials, file paths,
        # or internal hostnames.
        environment = (os.environ.get("ENVIRONMENT") or "").strip().lower()
        body = {"error": "Internal server error"}
        if environment == "development":
            body["detail"] = str(exc)
        return JSONResponse(status_code=500, content=body)
    
    # Register all integration drivers
    from scanner.drivers.loader import register_all_drivers
    register_all_drivers()

    # Register Routers
    from .routers import health_router, database_router, lineage_router, coverage_router, server_router, reporting_router
    from .routers.copilot import router as copilot_router
    from .routers.dbt import router as dbt_router
    from .routers.schedule import router as schedule_router
    from .routers.drivers import router as drivers_router
    from .routers.presets import router as presets_router
    from .routers.plans import router as plans_router
    from .routers.policies import router as policies_router
    from .routers.discovery import router as discovery_router
    from .routers.drift import router as drift_router
    from .routers.context_requests import router as context_requests_router
    from .routers.integrations import router as integrations_router
    from .routers.waitlist import router as waitlist_router
    from .routers.source_discovery import router as source_discovery_router
    from .routers.source_verify import router as source_verify_router
    from .routers.source_secrets import router as source_secrets_router

    # Health endpoint
    app.include_router(health_router, tags=["Health"])

    # Co-Pilot API
    app.include_router(copilot_router, prefix="/api/v1", tags=["Co-Pilot"])

    # Database discovery API
    app.include_router(database_router, prefix="/api/v1", tags=["Database"])

    # Lineage extraction API
    app.include_router(lineage_router, prefix="/api/v1", tags=["Lineage"])

    # dbt discovery API
    app.include_router(dbt_router, prefix="/api/v1", tags=["dbt"])

    # Coverage analysis API
    app.include_router(coverage_router, prefix="/api/v1", tags=["Coverage"])

    # Schedule/Tasks API
    app.include_router(schedule_router, prefix="/api/v1", tags=["Schedule"])

    # Server/Infrastructure API
    app.include_router(server_router, prefix="/api/v1", tags=["Server"])

    # Integration Drivers API
    app.include_router(drivers_router, prefix="/api/v1", tags=["Drivers"])

    # Reporting/BI Metadata API
    app.include_router(reporting_router, prefix="/api/v1", tags=["Reporting"])

    # Monitor Presets API
    app.include_router(presets_router, prefix="/api/v1", tags=["Presets"])

    # Monitoring Plans API
    app.include_router(plans_router, prefix="/api/v1", tags=["Plans"])

    # Pipeline Monitoring Policies API
    app.include_router(policies_router, prefix="/api/v1", tags=["Policies"])

    # SLA Discovery API
    app.include_router(discovery_router, prefix="/api/v1", tags=["Discovery"])

    # Drift Analysis API
    app.include_router(drift_router, prefix="/api/v1", tags=["Drift Analysis"])

    # Clarification (ContextRequest) API — stateless validation + on_resolve
    # invocation. Persistence stays in Next.js; see
    # scanner/api/routers/context_requests.py for the full contract.
    app.include_router(context_requests_router, prefix="/api/v1", tags=["Clarifications"])

    # Subscribe in-process guesser listeners to the clarification bus so
    # tentative discoveries get a chance to react to context_resolved events.
    # Today the SLA listener is a logged no-op pending a background re-run
    # queue (see scanner/lineage/sla_discovery_listeners.py for the rationale).
    from scanner.lineage.sla_discovery_listeners import register as _register_sla_clarif_listener
    _register_sla_clarif_listener()

    # Integrations operational API (probe-now, etc.)
    app.include_router(integrations_router, prefix="/api/v1", tags=["Integrations"])

    # Source-connector waitlist API
    app.include_router(waitlist_router, prefix="/api/v1", tags=["Waitlist"])

    # Source Discovery API (router already has /api/v1/integrations/source prefix)
    app.include_router(source_discovery_router)

    # Source Verify API (router already has /api/v1/integrations/source prefix)
    app.include_router(source_verify_router)

    # Source Secrets API — stash-secret + resolve-secret
    app.include_router(source_secrets_router)

    logger.info("app_started", version=settings.version, environment=settings.environment)

    return app


# ---------------------------------------------------------------------------
# Scheduler lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Start/stop the background scheduler with the app."""
    from scanner.scheduler.service import SchedulerService

    scheduler = SchedulerService()
    await scheduler.start()
    yield
    await scheduler.stop()


# Create the app instance
app = create_app()
app.router.lifespan_context = lifespan
