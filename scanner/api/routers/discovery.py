"""
On-demand SLA discovery endpoint.

Receives a node engine ID + stack_id, looks up the node from the
in-memory engine graph, creates the appropriate warehouse adapter,
and runs `discover_sla_profile()` to suggest SLA thresholds.
"""

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import require_principal, ActingPrincipal
from . import _lineage_cache

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class NodeDiscoveryRequest(BaseModel):
    """Request body for on-demand SLA discovery."""
    nodeId: str = Field(..., description="Engine stable_id of the node")


class NodeDiscoveryResponse(BaseModel):
    """Response with discovered SLA profile suggestions."""
    node_fqn: str
    warehouse_ancestor_fqn: Optional[str] = None
    freshness: Optional[Dict[str, Any]] = None
    volume: Optional[Dict[str, Any]] = None
    quality: Optional[Dict[str, Any]] = None
    schema_profile: Optional[Dict[str, Any]] = None
    uniqueness: Optional[Dict[str, Any]] = None
    unsupported: bool = False
    skipped_reason: Optional[str] = None


class DirectDiscoveryRequest(BaseModel):
    """Request body for direct SLA discovery (no lineage graph needed)."""
    platform: str = Field(..., description="Warehouse platform: bigquery, snowflake, postgres, redshift")
    tableFqn: str = Field(..., description="Fully qualified table name (e.g. project.dataset.table)")
    credentials: Dict[str, Any] = Field(..., description="Warehouse connection credentials")
    stackId: Optional[str] = Field(None, description="Pipeline stack id; required for clarification emits")
    organizationId: Optional[str] = Field(None, description="Caller's organization id; paired with stackId for clarifications")


class BulkDirectDiscoveryRequest(BaseModel):
    """Request body for bulk direct SLA discovery (no lineage graph needed)."""
    platform: str = Field(..., description="Warehouse platform")
    tableFqns: list[str] = Field(..., description="Table FQNs to discover", max_length=50)
    credentials: Dict[str, Any] = Field(..., description="Warehouse connection credentials")
    stackId: Optional[str] = Field(None, description="Pipeline stack id; required for clarification emits")
    organizationId: Optional[str] = Field(None, description="Caller's organization id; paired with stackId for clarifications")


class BulkDiscoveryRequest(BaseModel):
    """Request body for bulk SLA discovery."""
    nodeIds: list[str] = Field(..., description="Engine stable_ids of the nodes", max_length=50)
    stackId: Optional[str] = None


class BulkDiscoveryResponse(BaseModel):
    """Response with discovery results for multiple nodes."""
    results: list[NodeDiscoveryResponse]


class AnalyzeDiscoveryRequest(BaseModel):
    """Request body for phase 1 (analyze) of two-phase discovery."""
    platform: str = Field(..., description="Warehouse platform")
    tableFqn: str = Field(..., description="Fully qualified table name")
    credentials: Dict[str, Any] = Field(..., description="Warehouse connection credentials")
    stackId: Optional[str] = Field(None, description="Pipeline stack id; required for clarification emits")
    organizationId: Optional[str] = Field(None, description="Caller's organization id")


class AnalyzeDiscoveryResponse(BaseModel):
    """Response from phase 1 — the plan and any pending clarifications."""
    status: str  # "ready" | "awaiting_clarifications"
    table_fqn: str
    plan: Dict[str, Any]
    clarification_ids: list[str]


class ComputeDiscoveryRequest(BaseModel):
    """Request body for phase 2 (compute) of two-phase discovery."""
    platform: str = Field(..., description="Warehouse platform")
    tableFqn: str = Field(..., description="Fully qualified table name; must match plan.table_fqn")
    credentials: Dict[str, Any] = Field(..., description="Warehouse connection credentials")
    plan: Dict[str, Any] = Field(..., description="The AnalysisPlan dict returned by /analyze")
    answers: Dict[str, Any] = Field(default_factory=dict, description="{request_id: answer} from resolved clarifications")
    stackId: Optional[str] = None
    organizationId: Optional[str] = None


class AnalyzeBulkDiscoveryRequest(BaseModel):
    """Request body for phase 1 bulk: analyze multiple tables on the same platform."""
    platform: str = Field(..., description="Warehouse platform")
    tableFqns: list[str] = Field(..., description="Table FQNs to analyze", max_length=50)
    credentials: Dict[str, Any] = Field(..., description="Warehouse connection credentials")
    stackId: Optional[str] = Field(None)
    organizationId: Optional[str] = Field(None)


class AnalyzeBulkDiscoveryResponse(BaseModel):
    """Response from /discovery/analyze-bulk — one entry per table."""
    results: list[AnalyzeDiscoveryResponse]


class ComputeBulkItem(BaseModel):
    """A single (plan, answers) compute item in a bulk compute request."""
    tableFqn: str
    plan: Dict[str, Any]
    answers: Dict[str, Any] = Field(default_factory=dict)


class ComputeBulkDiscoveryRequest(BaseModel):
    """Request body for phase 2 bulk: compute SLAs for multiple prepared plans."""
    platform: str = Field(..., description="Warehouse platform")
    credentials: Dict[str, Any] = Field(..., description="Warehouse connection credentials")
    items: list[ComputeBulkItem] = Field(..., max_length=50)
    stackId: Optional[str] = None
    organizationId: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WAREHOUSE_PLATFORMS = {"bigquery", "snowflake", "postgres", "redshift", "sqlserver"}


def _create_warehouse_adapter(platform: str, config: Dict[str, Any]):
    """Instantiate a warehouse adapter from platform name and config."""
    try:
        from adapters.bigquery import BigQueryAdapter
        from adapters.snowflake import SnowflakeAdapter
        from adapters.postgres import PostgresAdapter
        from adapters.redshift import RedshiftAdapter
    except ImportError:
        from scanner.adapters.bigquery import BigQueryAdapter
        from scanner.adapters.snowflake import SnowflakeAdapter
        from scanner.adapters.postgres import PostgresAdapter
        from scanner.adapters.redshift import RedshiftAdapter

    adapters = {
        "bigquery": BigQueryAdapter,
        "snowflake": SnowflakeAdapter,
        "postgres": PostgresAdapter,
        "redshift": RedshiftAdapter,
    }

    adapter_class = adapters.get(platform.lower())
    if not adapter_class:
        return None

    return adapter_class(config)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/discovery/node", response_model=NodeDiscoveryResponse)
async def discover_node_sla(
    request: NodeDiscoveryRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Run on-demand SLA discovery for a single lineage node.

    Looks up the node from the engine graph (by stable_id), finds the
    nearest warehouse ancestor, queries historical metrics, and returns
    suggested SLA thresholds without persisting anything.
    """
    org_id = principal.organization_id

    # 1. Get the engine graph for this stack
    store = _lineage_cache.get_engine_store(org_id, stack_id)
    if not store.graph or not store.graph.nodes:
        raise HTTPException(
            status_code=404,
            detail="No lineage graph found for this pipeline. Run an investigation first.",
        )

    # 2. Find the node by stable_id
    node = store.graph.nodes.get(request.nodeId)
    if not node:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{request.nodeId}' not found in lineage graph",
        )

    # 3. Determine the warehouse platform for this node (or its ancestor)
    try:
        from lineage.sla_discovery import _find_warehouse_ancestor, discover_sla_profile
        from lineage.graph import PlatformDomain, NodeType
    except ImportError:
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor, discover_sla_profile
        from scanner.lineage.graph import PlatformDomain, NodeType

    _WAREHOUSE_NODE_TYPES = {NodeType.TABLE, NodeType.VIEW, NodeType.MATERIALIZED_VIEW}

    # Find the warehouse ancestor to determine which adapter we need
    logger.info(
        "[SLA Discovery] Node %s: platform_domain=%s, node_type=%s, platform=%s",
        node.fqn,
        getattr(node, 'platform_domain', 'MISSING'),
        getattr(node, 'node_type', 'MISSING'),
        getattr(node, 'platform', 'MISSING'),
    )
    ancestor = _find_warehouse_ancestor(node, store.graph)
    if ancestor is None:
        return NodeDiscoveryResponse(
            node_fqn=node.fqn,
            unsupported=True,
            skipped_reason=f"No warehouse ancestor found in lineage graph (node platform_domain={getattr(node, 'platform_domain', 'MISSING')}, node_type={getattr(node, 'node_type', 'MISSING')})",
        )

    # 4. Create the adapter from cached tool configs
    platform = (ancestor.platform or "").lower()
    if platform not in _WAREHOUSE_PLATFORMS:
        return NodeDiscoveryResponse(
            node_fqn=node.fqn,
            unsupported=True,
            skipped_reason=f"Platform '{platform}' does not support historical metrics",
        )

    tool_configs = _lineage_cache.get_tool_configs(org_id, stack_id)
    config = tool_configs.get(platform)

    if not config:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "no_adapter_config",
                "message": f"No cached connection config for platform '{platform}'. "
                           "Re-run the pipeline investigation to populate the config cache.",
            },
        )

    adapter = _create_warehouse_adapter(platform, config)
    if not adapter:
        return NodeDiscoveryResponse(
            node_fqn=node.fqn,
            unsupported=True,
            skipped_reason=f"Could not create adapter for platform '{platform}'",
        )

    # 5. Connect the adapter and run discovery
    try:
        adapter.connect()
    except Exception as e:
        logger.warning("[SLA Discovery] Failed to connect %s adapter: %s", platform, e)
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to {platform}: {e}",
        )

    try:
        result = await discover_sla_profile(
            node,
            store.graph,
            adapter,
            pipeline_stack_id=stack_id,
            organization_id=org_id,
        )
    except Exception as e:
        logger.error("[SLA Discovery] On-demand discovery failed for %s: %s", node.fqn, e)
        raise HTTPException(status_code=500, detail=f"Discovery failed: {e}")
    finally:
        try:
            adapter.disconnect()
        except Exception:
            pass

    return NodeDiscoveryResponse(
        node_fqn=result.node_fqn,
        warehouse_ancestor_fqn=result.warehouse_ancestor_fqn,
        freshness=result.freshness,
        volume=result.volume,
        quality=result.quality,
        schema_profile=result.schema,
        uniqueness=result.uniqueness,
        unsupported=result.unsupported,
        skipped_reason=result.skipped_reason,
    )


@router.post("/discovery/bulk", response_model=BulkDiscoveryResponse)
async def discover_bulk_sla(
    request: BulkDiscoveryRequest,
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Run on-demand SLA discovery for multiple lineage nodes.

    Groups nodes by platform to reuse adapter connections. Each node is
    discovered independently — results are per-node, not merged.
    """
    org_id = principal.organization_id
    stack_id = request.stackId  # bulk endpoint takes stack_id from body, not query

    store = _lineage_cache.get_engine_store(org_id, stack_id)
    if not store.graph or not store.graph.nodes:
        raise HTTPException(
            status_code=404,
            detail="No lineage graph found for this pipeline. Run an investigation first.",
        )

    try:
        from lineage.sla_discovery import _find_warehouse_ancestor, discover_sla_profile
    except ImportError:
        from scanner.lineage.sla_discovery import _find_warehouse_ancestor, discover_sla_profile

    tool_configs = _lineage_cache.get_tool_configs(org_id, stack_id)

    # Group nodes by platform to reuse adapter connections
    platform_nodes: Dict[str, list] = {}  # platform -> [(node, ancestor)]
    skipped_results: list[NodeDiscoveryResponse] = []

    for node_id in request.nodeIds:
        node = store.graph.nodes.get(node_id)
        if not node:
            skipped_results.append(NodeDiscoveryResponse(
                node_fqn=node_id,
                unsupported=True,
                skipped_reason=f"Node '{node_id}' not found in lineage graph",
            ))
            continue

        ancestor = _find_warehouse_ancestor(node, store.graph)
        if ancestor is None:
            skipped_results.append(NodeDiscoveryResponse(
                node_fqn=node.fqn,
                unsupported=True,
                skipped_reason="No warehouse ancestor found",
            ))
            continue

        platform = (ancestor.platform or "").lower()
        if platform not in _WAREHOUSE_PLATFORMS:
            skipped_results.append(NodeDiscoveryResponse(
                node_fqn=node.fqn,
                unsupported=True,
                skipped_reason=f"Platform '{platform}' not supported",
            ))
            continue

        if platform not in tool_configs:
            skipped_results.append(NodeDiscoveryResponse(
                node_fqn=node.fqn,
                unsupported=True,
                skipped_reason=f"No cached config for '{platform}'. Re-run investigation.",
            ))
            continue

        platform_nodes.setdefault(platform, []).append((node, ancestor))

    # Discover concurrently — each task gets its own adapter to avoid shared state
    # Concurrency capped at 5 to avoid hammering the warehouse
    MAX_CONCURRENT = 5
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _discover_one(node, platform: str) -> NodeDiscoveryResponse:
        async with semaphore:
            adapter = _create_warehouse_adapter(platform, tool_configs[platform])
            if not adapter:
                return NodeDiscoveryResponse(
                    node_fqn=node.fqn,
                    unsupported=True,
                    skipped_reason=f"Could not create adapter for '{platform}'",
                )
            try:
                adapter.connect()
            except Exception as e:
                return NodeDiscoveryResponse(
                    node_fqn=node.fqn,
                    unsupported=True,
                    skipped_reason=f"Failed to connect to {platform}",
                )
            try:
                # discover_sla_profile is async but calls sync adapter methods;
                # run in thread pool to avoid blocking the event loop
                result = await asyncio.to_thread(
                    asyncio.run,
                    discover_sla_profile(
                        node,
                        store.graph,
                        adapter,
                        pipeline_stack_id=stack_id,
                        organization_id=org_id,
                    ),
                )
                return NodeDiscoveryResponse(
                    node_fqn=result.node_fqn,
                    warehouse_ancestor_fqn=result.warehouse_ancestor_fqn,
                    freshness=result.freshness,
                    volume=result.volume,
                    quality=result.quality,
                    schema_profile=result.schema,
                    uniqueness=result.uniqueness,
                    unsupported=result.unsupported,
                    skipped_reason=result.skipped_reason,
                )
            except Exception as e:
                logger.error("[SLA Discovery] Bulk: node %s failed: %s", node.fqn, e)
                return NodeDiscoveryResponse(
                    node_fqn=node.fqn,
                    unsupported=True,
                    skipped_reason=f"Discovery failed: {e}",
                )
            finally:
                try:
                    adapter.disconnect()
                except Exception:
                    pass

    # Flatten all nodes across platforms into concurrent tasks
    tasks = []
    for platform, node_pairs in platform_nodes.items():
        for node, ancestor in node_pairs:
            tasks.append(_discover_one(node, platform))

    discovered_results = list(await asyncio.gather(*tasks))

    return BulkDiscoveryResponse(results=[*skipped_results, *discovered_results])


# ---------------------------------------------------------------------------
# Direct discovery — no lineage graph required
# ---------------------------------------------------------------------------

@router.post("/discovery/direct", response_model=NodeDiscoveryResponse)
async def discover_direct_sla(request: DirectDiscoveryRequest):
    """
    Run SLA discovery directly from a table FQN and warehouse credentials.

    Does NOT require a lineage graph — the caller provides the platform,
    table FQN, and connection credentials directly.
    """
    try:
        from lineage.sla_discovery import discover_sla_direct
    except ImportError:
        from scanner.lineage.sla_discovery import discover_sla_direct

    platform = request.platform.lower()
    if platform not in _WAREHOUSE_PLATFORMS:
        return NodeDiscoveryResponse(
            node_fqn=request.tableFqn,
            unsupported=True,
            skipped_reason=f"Platform '{platform}' is not supported for discovery",
        )

    adapter = _create_warehouse_adapter(platform, request.credentials)
    if not adapter:
        return NodeDiscoveryResponse(
            node_fqn=request.tableFqn,
            unsupported=True,
            skipped_reason=f"Could not create adapter for platform '{platform}'",
        )

    try:
        adapter.connect()
    except Exception as e:
        logger.warning("[SLA Discovery] Direct: failed to connect %s: %s", platform, e)
        raise HTTPException(status_code=503, detail=f"Failed to connect to {platform}: {e}")

    try:
        result = await discover_sla_direct(
            request.tableFqn,
            adapter,
            pipeline_stack_id=request.stackId,
            organization_id=request.organizationId,
        )
    except Exception as e:
        logger.error("[SLA Discovery] Direct discovery failed for %s: %s", request.tableFqn, e)
        raise HTTPException(status_code=500, detail=f"Discovery failed: {e}")
    finally:
        try:
            adapter.disconnect()
        except Exception:
            pass

    return NodeDiscoveryResponse(
        node_fqn=result.node_fqn,
        warehouse_ancestor_fqn=result.warehouse_ancestor_fqn,
        freshness=result.freshness,
        volume=result.volume,
        quality=result.quality,
        schema_profile=result.schema,
        uniqueness=result.uniqueness,
        unsupported=result.unsupported,
        skipped_reason=result.skipped_reason,
    )


@router.post("/discovery/direct-bulk", response_model=BulkDiscoveryResponse)
async def discover_direct_bulk_sla(request: BulkDirectDiscoveryRequest):
    """
    Run SLA discovery for multiple tables directly from credentials.

    Does NOT require a lineage graph — the caller provides the platform,
    table FQNs, and connection credentials directly.
    """
    try:
        from lineage.sla_discovery import discover_sla_direct
    except ImportError:
        from scanner.lineage.sla_discovery import discover_sla_direct

    platform = request.platform.lower()
    if platform not in _WAREHOUSE_PLATFORMS:
        return BulkDiscoveryResponse(results=[
            NodeDiscoveryResponse(
                node_fqn=fqn, unsupported=True,
                skipped_reason=f"Platform '{platform}' is not supported",
            ) for fqn in request.tableFqns
        ])

    MAX_CONCURRENT = 5
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _discover_one(table_fqn: str) -> NodeDiscoveryResponse:
        async with semaphore:
            adapter = _create_warehouse_adapter(platform, request.credentials)
            if not adapter:
                return NodeDiscoveryResponse(
                    node_fqn=table_fqn, unsupported=True,
                    skipped_reason=f"Could not create adapter for '{platform}'",
                )
            try:
                adapter.connect()
            except Exception:
                return NodeDiscoveryResponse(
                    node_fqn=table_fqn, unsupported=True,
                    skipped_reason=f"Failed to connect to {platform}",
                )
            try:
                result = await discover_sla_direct(
                    table_fqn,
                    adapter,
                    pipeline_stack_id=request.stackId,
                    organization_id=request.organizationId,
                )
                return NodeDiscoveryResponse(
                    node_fqn=result.node_fqn,
                    warehouse_ancestor_fqn=result.warehouse_ancestor_fqn,
                    freshness=result.freshness,
                    volume=result.volume,
                    quality=result.quality,
                    schema_profile=result.schema,
                    uniqueness=result.uniqueness,
                    unsupported=result.unsupported,
                    skipped_reason=result.skipped_reason,
                )
            except Exception as e:
                logger.error("[SLA Discovery] Direct bulk: %s failed: %s", table_fqn, e)
                return NodeDiscoveryResponse(
                    node_fqn=table_fqn, unsupported=True,
                    skipped_reason=f"Discovery failed: {e}",
                )
            finally:
                try:
                    adapter.disconnect()
                except Exception:
                    pass

    results = list(await asyncio.gather(*[_discover_one(fqn) for fqn in request.tableFqns]))
    return BulkDiscoveryResponse(results=results)


# ---------------------------------------------------------------------------
# Two-phase discovery — phase 1: analyze
# ---------------------------------------------------------------------------

@router.post("/discovery/analyze", response_model=AnalyzeDiscoveryResponse)
async def analyze_sla_route(request: AnalyzeDiscoveryRequest):
    """Phase 1: pick timestamps, emit clarifications if needed, return the plan."""
    try:
        from lineage.sla_analysis import analyze_sla, plan_to_dict
    except ImportError:
        from scanner.lineage.sla_analysis import analyze_sla, plan_to_dict

    platform = request.platform.lower()
    if platform not in _WAREHOUSE_PLATFORMS:
        # No adapter at all — return an unsupported plan, status=ready, no clarifications.
        plan = {
            "table_fqn": request.tableFqn,
            "warehouse_ancestor_fqn": None,
            "volume_timestamp_pick": None,
            "volume_timestamp_candidates": [],
            "schema_snapshot": {"columns": []},
            "row_count": None,
            "unsupported": True,
            "skipped_reason": f"Platform '{platform}' is not supported for discovery",
        }
        return AnalyzeDiscoveryResponse(
            status="ready",
            table_fqn=request.tableFqn,
            plan=plan,
            clarification_ids=[],
        )

    adapter = _create_warehouse_adapter(platform, request.credentials)
    if not adapter:
        plan = {
            "table_fqn": request.tableFqn,
            "warehouse_ancestor_fqn": None,
            "volume_timestamp_pick": None,
            "volume_timestamp_candidates": [],
            "schema_snapshot": {"columns": []},
            "row_count": None,
            "unsupported": True,
            "skipped_reason": f"Could not create adapter for platform '{platform}'",
        }
        return AnalyzeDiscoveryResponse(
            status="ready",
            table_fqn=request.tableFqn,
            plan=plan,
            clarification_ids=[],
        )

    try:
        adapter.connect()
    except Exception as e:
        logger.warning("[SLA Discovery] Analyze: failed to connect %s: %s", platform, e)
        raise HTTPException(status_code=503, detail=f"Failed to connect to {platform}: {e}")

    try:
        result = analyze_sla(
            table_fqn=request.tableFqn,
            adapter=adapter,
            pipeline_stack_id=request.stackId,
            organization_id=request.organizationId,
        )
    except Exception as e:
        logger.error("[SLA Discovery] Analyze failed for %s: %s", request.tableFqn, e)
        raise HTTPException(status_code=500, detail=f"Analyze failed: {e}")
    finally:
        try:
            adapter.disconnect()
        except Exception:
            pass

    return AnalyzeDiscoveryResponse(
        status=result.status,
        table_fqn=result.table_fqn,
        plan=plan_to_dict(result.plan),
        clarification_ids=list(result.clarification_ids),
    )


# ---------------------------------------------------------------------------
# Two-phase discovery — phase 2: compute
# ---------------------------------------------------------------------------

@router.post("/discovery/compute", response_model=NodeDiscoveryResponse)
async def compute_sla_route(request: ComputeDiscoveryRequest):
    """Phase 2: compute SLAs from plan + user answers."""
    try:
        from lineage.sla_analysis import plan_from_dict
        from lineage.sla_discovery import compute_sla
    except ImportError:
        from scanner.lineage.sla_analysis import plan_from_dict
        from scanner.lineage.sla_discovery import compute_sla

    if request.plan.get("table_fqn") != request.tableFqn:
        raise HTTPException(
            status_code=400,
            detail="plan.table_fqn does not match request tableFqn",
        )

    platform = request.platform.lower()
    if platform not in _WAREHOUSE_PLATFORMS:
        return NodeDiscoveryResponse(
            node_fqn=request.tableFqn,
            unsupported=True,
            skipped_reason=f"Platform '{platform}' is not supported for discovery",
        )

    adapter = _create_warehouse_adapter(platform, request.credentials)
    if not adapter:
        return NodeDiscoveryResponse(
            node_fqn=request.tableFqn,
            unsupported=True,
            skipped_reason=f"Could not create adapter for platform '{platform}'",
        )

    try:
        adapter.connect()
    except Exception as e:
        logger.warning("[SLA Discovery] Compute: failed to connect %s: %s", platform, e)
        raise HTTPException(status_code=503, detail=f"Failed to connect to {platform}: {e}")

    try:
        plan = plan_from_dict(request.plan)
        result = compute_sla(
            plan,
            adapter,
            answers=request.answers,
            pipeline_stack_id=request.stackId,
            organization_id=request.organizationId,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[SLA Discovery] Compute failed for %s: %s", request.tableFqn, e)
        raise HTTPException(status_code=500, detail=f"Compute failed: {e}")
    finally:
        try:
            adapter.disconnect()
        except Exception:
            pass

    return NodeDiscoveryResponse(
        node_fqn=result.node_fqn,
        warehouse_ancestor_fqn=result.warehouse_ancestor_fqn,
        freshness=result.freshness,
        volume=result.volume,
        quality=result.quality,
        schema_profile=result.schema,
        uniqueness=result.uniqueness,
        unsupported=result.unsupported,
        skipped_reason=result.skipped_reason,
    )


# ---------------------------------------------------------------------------
# Two-phase discovery — phase 1 bulk: analyze-bulk
# ---------------------------------------------------------------------------

@router.post("/discovery/analyze-bulk", response_model=AnalyzeBulkDiscoveryResponse)
async def analyze_bulk_sla_route(request: AnalyzeBulkDiscoveryRequest):
    """Phase 1 bulk — analyze multiple tables, returning per-table plans + clarifications."""
    try:
        from lineage.sla_analysis import analyze_sla, plan_to_dict
    except ImportError:
        from scanner.lineage.sla_analysis import analyze_sla, plan_to_dict

    platform = request.platform.lower()
    if platform not in _WAREHOUSE_PLATFORMS:
        results = [
            AnalyzeDiscoveryResponse(
                status="ready",
                table_fqn=fqn,
                plan={
                    "table_fqn": fqn,
                    "warehouse_ancestor_fqn": None,
                    "volume_timestamp_pick": None,
                    "volume_timestamp_candidates": [],
                    "schema_snapshot": {"columns": []},
                    "row_count": None,
                    "unsupported": True,
                    "skipped_reason": f"Platform '{platform}' is not supported for discovery",
                },
                clarification_ids=[],
            )
            for fqn in request.tableFqns
        ]
        return AnalyzeBulkDiscoveryResponse(results=results)

    # Single shared adapter per bulk call (matches /discovery/direct-bulk pattern).
    adapter = _create_warehouse_adapter(platform, request.credentials)
    if not adapter:
        results = [
            AnalyzeDiscoveryResponse(
                status="ready",
                table_fqn=fqn,
                plan={
                    "table_fqn": fqn,
                    "warehouse_ancestor_fqn": None,
                    "volume_timestamp_pick": None,
                    "volume_timestamp_candidates": [],
                    "schema_snapshot": {"columns": []},
                    "row_count": None,
                    "unsupported": True,
                    "skipped_reason": f"Could not create adapter for platform '{platform}'",
                },
                clarification_ids=[],
            )
            for fqn in request.tableFqns
        ]
        return AnalyzeBulkDiscoveryResponse(results=results)

    try:
        adapter.connect()
    except Exception as e:
        logger.warning("[SLA Discovery] AnalyzeBulk: failed to connect %s: %s", platform, e)
        raise HTTPException(status_code=503, detail=f"Failed to connect to {platform}: {e}")

    semaphore = asyncio.Semaphore(5)

    async def _analyze_one(fqn: str) -> AnalyzeDiscoveryResponse:
        async with semaphore:
            try:
                result = analyze_sla(
                    table_fqn=fqn,
                    adapter=adapter,
                    pipeline_stack_id=request.stackId,
                    organization_id=request.organizationId,
                )
                return AnalyzeDiscoveryResponse(
                    status=result.status,
                    table_fqn=result.table_fqn,
                    plan=plan_to_dict(result.plan),
                    clarification_ids=list(result.clarification_ids),
                )
            except Exception as e:
                logger.error("[SLA Discovery] AnalyzeBulk failed for %s: %s", fqn, e)
                return AnalyzeDiscoveryResponse(
                    status="ready",
                    table_fqn=fqn,
                    plan={
                        "table_fqn": fqn,
                        "warehouse_ancestor_fqn": None,
                        "volume_timestamp_pick": None,
                        "volume_timestamp_candidates": [],
                        "schema_snapshot": {"columns": []},
                        "row_count": None,
                        "unsupported": True,
                        "skipped_reason": f"Analyze failed: {e}",
                    },
                    clarification_ids=[],
                )

    try:
        results = list(await asyncio.gather(*[_analyze_one(fqn) for fqn in request.tableFqns]))
    finally:
        try:
            adapter.disconnect()
        except Exception:
            pass

    return AnalyzeBulkDiscoveryResponse(results=results)


# ---------------------------------------------------------------------------
# Two-phase discovery — phase 2 bulk: compute-bulk
# ---------------------------------------------------------------------------

@router.post("/discovery/compute-bulk", response_model=BulkDiscoveryResponse)
async def compute_bulk_sla_route(request: ComputeBulkDiscoveryRequest):
    """Phase 2 bulk — compute SLAs for prepared plans + their resolved answers."""
    try:
        from lineage.sla_analysis import plan_from_dict
        from lineage.sla_discovery import compute_sla
    except ImportError:
        from scanner.lineage.sla_analysis import plan_from_dict
        from scanner.lineage.sla_discovery import compute_sla

    # Plan/FQN consistency check
    for item in request.items:
        if item.plan.get("table_fqn") != item.tableFqn:
            raise HTTPException(
                status_code=400,
                detail=f"plan.table_fqn does not match tableFqn for {item.tableFqn}",
            )

    platform = request.platform.lower()
    if platform not in _WAREHOUSE_PLATFORMS:
        results = [
            NodeDiscoveryResponse(
                node_fqn=item.tableFqn,
                unsupported=True,
                skipped_reason=f"Platform '{platform}' is not supported for discovery",
            )
            for item in request.items
        ]
        return BulkDiscoveryResponse(results=results)

    adapter = _create_warehouse_adapter(platform, request.credentials)
    if not adapter:
        results = [
            NodeDiscoveryResponse(
                node_fqn=item.tableFqn,
                unsupported=True,
                skipped_reason=f"Could not create adapter for platform '{platform}'",
            )
            for item in request.items
        ]
        return BulkDiscoveryResponse(results=results)

    try:
        adapter.connect()
    except Exception as e:
        logger.warning("[SLA Discovery] ComputeBulk: failed to connect %s: %s", platform, e)
        raise HTTPException(status_code=503, detail=f"Failed to connect to {platform}: {e}")

    semaphore = asyncio.Semaphore(5)

    async def _compute_one(item: ComputeBulkItem) -> NodeDiscoveryResponse:
        async with semaphore:
            try:
                plan = plan_from_dict(item.plan)
                result = compute_sla(
                    plan,
                    adapter,
                    answers=item.answers,
                    pipeline_stack_id=request.stackId,
                    organization_id=request.organizationId,
                )
                return NodeDiscoveryResponse(
                    node_fqn=result.node_fqn,
                    warehouse_ancestor_fqn=result.warehouse_ancestor_fqn,
                    freshness=result.freshness,
                    volume=result.volume,
                    quality=result.quality,
                    schema_profile=result.schema,
                    uniqueness=result.uniqueness,
                    unsupported=result.unsupported,
                    skipped_reason=result.skipped_reason,
                )
            except Exception as e:
                logger.error("[SLA Discovery] ComputeBulk failed for %s: %s", item.tableFqn, e)
                return NodeDiscoveryResponse(
                    node_fqn=item.tableFqn,
                    unsupported=True,
                    skipped_reason=f"Compute failed: {e}",
                )

    try:
        results = list(await asyncio.gather(*[_compute_one(it) for it in request.items]))
    finally:
        try:
            adapter.disconnect()
        except Exception:
            pass

    return BulkDiscoveryResponse(results=results)
