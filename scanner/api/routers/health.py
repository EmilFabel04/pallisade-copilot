"""
Health & Info Endpoints
"""

from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    service: str
    timestamp: str


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        service="pallisade-copilot",
        timestamp=datetime.utcnow().isoformat()
    )


@router.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Pallisade Co-Pilot API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }
