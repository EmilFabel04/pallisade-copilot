"""
Pallisade Co-Pilot - FastAPI Application
"""

import os
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import structlog

from .dependencies import get_settings, setup_logging

# Setup logging on module load
setup_logging()
logger = structlog.get_logger()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="Pallisade Co-Pilot API",
        description="AI-powered data pipeline assistant",
        version=settings.version,
        docs_url="/docs",
        redoc_url="/redoc"
    )
    
    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
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
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc)}
        )
    
    # Register Routers
    from .routers import health_router, database_router, lineage_router
    from .routers.copilot import router as copilot_router
    
    # Health endpoint
    app.include_router(health_router, tags=["Health"])
    
    # Co-Pilot API
    app.include_router(copilot_router, prefix="/api/v1", tags=["Co-Pilot"])
    
    # Database discovery API
    app.include_router(database_router, prefix="/api/v1", tags=["Database"])
    
    # Lineage extraction API
    app.include_router(lineage_router, prefix="/api/v1", tags=["Lineage"])
    
    logger.info("app_started", version=settings.version, environment=settings.environment)
    
    return app


# Create the app instance
app = create_app()
