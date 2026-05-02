"""
Source Discovery Router.

Exposes POST /api/v1/integrations/source/discover — probes an HTTP source
and returns discovered dataset candidates grouped by discovery path
(probe, warehouse, ingestion).

Results are cached in-process for 60 seconds to avoid hammering the
upstream API on repeated wizard refreshes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from scanner.discovery.source_discovery import SourceDiscoveryOrchestrator
from scanner.discovery.probe.source_probe_discoverer import SourceProbeDiscoverer
from scanner.discovery.warehouse.warehouse_discoverer import WarehouseDiscoverer
from scanner.discovery.ingestion.orchestrator import IngestionDiscoverer

from ..auth import require_principal, ActingPrincipal

router = APIRouter(prefix="/api/v1/integrations/source", tags=["source-discovery"])

# Per-worker, in-process cache. cachetools.TTLCache is NOT thread-safe; we rely on
# FastAPI's single-threaded asyncio event loop. Do not switch to a multi-threaded
# WSGI runner without wrapping this with a threading.Lock.
_CACHE: TTLCache = TTLCache(maxsize=512, ttl=60)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class AuthBody(BaseModel):
    kind: str
    header_name: Optional[str] = None
    secret_ref: str


class DiscoverRequest(BaseModel):
    base_url: str
    endpoint: str
    auth: AuthBody
    ingestion_hints: Optional[List[str]] = None
    warehouse_hints: Optional[List[str]] = None
    # Optional pipeline stack ID so WarehouseDiscoverer can look up the right
    # cached adapter config from _engine_tool_configs_map.
    stack_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _orchestrator(org_id: Optional[str] = None, stack_id: Optional[str] = None) -> SourceDiscoveryOrchestrator:
    return SourceDiscoveryOrchestrator(
        probe_discoverer=SourceProbeDiscoverer(),
        warehouse_discoverer=WarehouseDiscoverer(org_id=org_id, stack_id=stack_id),
        ingestion_discoverer=IngestionDiscoverer(org_id=org_id, stack_id=stack_id),
    )


def _serialize_candidate(c) -> Dict[str, Any]:
    return {
        "source": c.source,
        "endpoint": c.endpoint,
        "json_root": c.json_root,
        "timestamp_column": c.timestamp_column,
        "expected_schema": [
            {"name": col.name, "data_type": col.data_type, "is_nullable": col.is_nullable}
            for col in c.expected_schema
        ],
        "lands_in": c.lands_in,
        "confidence": c.confidence,
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/discover")
async def discover(
    body: DiscoverRequest,
    principal: ActingPrincipal = Depends(require_principal),
) -> Dict[str, Any]:
    if not body.base_url.lower().startswith("https://"):
        raise HTTPException(400, "base_url must use https://")

    # auth.secret_ref is intentionally excluded from the cache key — probe-discovery
    # results reflect the public API shape and are safe to share across callers that
    # hit the same (base_url, endpoint, hints, org, stack) tuple regardless of credential.
    # org_id + stack_id are included so warehouse schema results are not shared
    # across tenants or pipeline stacks.
    cache_key = (
        principal.organization_id,
        body.stack_id,
        body.base_url,
        body.endpoint,
        tuple(sorted(body.ingestion_hints or [])),
        tuple(sorted(body.warehouse_hints or [])),
    )
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    # TODO: resolve secret_ref via secret store when helper available.
    # The verify endpoint in Task 6 will wire this up properly.
    # For now we use the secret_ref directly as the runtime secret value.
    runtime_auth = {
        "kind": body.auth.kind,
        "header_name": body.auth.header_name,
        "secret": body.auth.secret_ref,  # TODO: resolve via secret store if helper exists
    }

    result = await _orchestrator(
        org_id=principal.organization_id,
        stack_id=body.stack_id,
    ).discover(
        base_url=body.base_url,
        endpoint=body.endpoint,
        auth=runtime_auth,
        warehouse_hints=body.warehouse_hints or [],
        ingestion_hints=body.ingestion_hints or [],
    )

    serialized: Dict[str, Any] = {
        "candidates_by_path": {
            path: [_serialize_candidate(c) for c in candidates]
            for path, candidates in result.candidates_by_path.items()
        },
        "errors_by_path": {
            path: ({"code": e.code, "message": e.message} if e else None)
            for path, e in result.errors_by_path.items()
        },
    }
    _CACHE[cache_key] = serialized
    return serialized
