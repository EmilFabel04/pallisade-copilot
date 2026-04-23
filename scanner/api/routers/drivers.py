"""
Integration Drivers API — unified query surface for all tool integrations.

Endpoints:
  GET  /drivers              — list all registered drivers with metadata
  GET  /drivers/matrix       — full support matrix (for docs / dashboard)
  GET  /drivers/{type}       — single driver info
  GET  /drivers/{type}/capabilities
  POST /drivers/{type}/validate
  GET  /drivers/{type}/events
  GET  /drivers/{type}/contract-schema
  GET  /drivers/{type}/recommended-monitors
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scanner.drivers.registry import DriverRegistry

router = APIRouter(prefix="/drivers")


# ── Response models ────────────────────────────────────────────────────

class DriverInfo(BaseModel):
    id: str
    integration_type: str
    layer: str
    graph_domain: str
    capabilities: Dict[str, Any]
    events_emitted: List[str]
    recommended_monitors: List[str]


class DriverListResponse(BaseModel):
    drivers: List[DriverInfo]
    total: int
    data_plane_count: int
    control_plane_count: int


class CapabilitiesResponse(BaseModel):
    integration_type: str
    capabilities: Dict[str, Any]


class ValidateRequest(BaseModel):
    config: Dict[str, Any]


class ValidateResponse(BaseModel):
    valid: bool
    errors: List[str]
    warnings: List[str]


class MatrixRow(BaseModel):
    integration_type: str
    id: str
    layer: str
    graph_domain: str
    can_query: bool
    can_extract_metadata: bool
    can_extract_lineage: bool
    can_fetch_logs: bool
    can_write: bool
    can_health_check: bool
    supported_monitors: List[str]
    events_emitted: List[str]
    recommended_monitors: List[str]


# ── Helpers ────────────────────────────────────────────────────────────

def _get_driver_or_404(integration_type: str):
    driver_cls = DriverRegistry.get(integration_type)
    if driver_cls is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown integration type: {integration_type}. "
                   f"Available: {DriverRegistry.list_supported()}",
        )
    return driver_cls()


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("", response_model=DriverListResponse)
async def list_drivers(
    layer: Optional[str] = None,
    graph_domain: Optional[str] = None,
):
    """List all registered integration drivers, optionally filtered."""
    all_types = DriverRegistry.list_supported()
    drivers: List[DriverInfo] = []

    for key in all_types:
        driver_cls = DriverRegistry.get(key)
        if driver_cls is None:
            continue
        driver = driver_cls()

        # Filter by layer
        if layer and driver.layer().value.upper() != layer.upper():
            continue
        # Filter by graph_domain
        if graph_domain and driver.graph_domain().value.upper() != graph_domain.upper():
            continue

        drivers.append(DriverInfo(**driver.to_dict()))

    return DriverListResponse(
        drivers=drivers,
        total=len(drivers),
        data_plane_count=len(DriverRegistry.list_data_plane()),
        control_plane_count=len(DriverRegistry.list_control_plane()),
    )


@router.get("/matrix", response_model=List[MatrixRow])
async def get_support_matrix():
    """Full support matrix for all drivers (for docs and dashboard)."""
    return DriverRegistry.get_support_matrix()


@router.get("/{integration_type}", response_model=DriverInfo)
async def get_driver(integration_type: str):
    """Get metadata for a single integration driver."""
    driver = _get_driver_or_404(integration_type)
    return DriverInfo(**driver.to_dict())


@router.get("/{integration_type}/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(integration_type: str):
    """Get capabilities for a single integration driver."""
    driver = _get_driver_or_404(integration_type)
    return CapabilitiesResponse(
        integration_type=integration_type.upper(),
        capabilities=driver.capabilities().to_dict(),
    )


@router.post("/{integration_type}/validate", response_model=ValidateResponse)
async def validate_config(integration_type: str, body: ValidateRequest):
    """Validate integration config without making a network call."""
    driver = _get_driver_or_404(integration_type)
    result = driver.validate_config(body.config)
    return ValidateResponse(
        valid=result.valid,
        errors=result.errors,
        warnings=result.warnings,
    )


@router.get("/{integration_type}/events")
async def get_events(integration_type: str):
    """List notification event types this integration can emit."""
    driver = _get_driver_or_404(integration_type)
    return {"integration_type": integration_type.upper(), "events": driver.events_emitted()}


@router.get("/{integration_type}/contract-schema")
async def get_contract_schema(integration_type: str):
    """Get tool-specific contract override schema (JSON Schema)."""
    driver = _get_driver_or_404(integration_type)
    schema = driver.contract_schema()
    return {"integration_type": integration_type.upper(), "schema": schema}


@router.get("/{integration_type}/recommended-monitors")
async def get_recommended_monitors(integration_type: str):
    """Get recommended monitor types for this integration."""
    driver = _get_driver_or_404(integration_type)
    return {
        "integration_type": integration_type.upper(),
        "monitors": driver.recommended_monitors(),
    }
