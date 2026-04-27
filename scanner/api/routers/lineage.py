"""
Lineage extraction API router.

Extracts lineage from connected warehouses and returns a graph.
"""

from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from ..auth import require_principal, ActingPrincipal
from . import _lineage_cache

router = APIRouter()


# ==========================================
# LINEAGE ENGINE API (vendor-agnostic)
# ==========================================

class EngineEvidenceResponse(BaseModel):
    """Evidence for a lineage edge."""
    adapter_id: str
    source_ref: str
    observed_at: Optional[str] = None
    snippet: Optional[str] = None


class EngineColumnMappingResponse(BaseModel):
    """Column-level mapping."""
    from_column: str
    to_column: str
    transform_expr: Optional[str] = None
    confidence: float = 1.0


class EngineNodeResponse(BaseModel):
    """Extended node response with engine fields."""
    id: str
    name: str
    fqn: str
    node_type: str
    database: Optional[str] = None
    schema_name: Optional[str] = Field(None, alias="schema")
    platform: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    platform_domain: str = "other"
    asset_kind: str = "unknown"
    namespace: Optional[str] = None
    sources: List[str] = []
    integration_id: Optional[str] = None
    dbt_resource_type: Optional[str] = None
    upstream_count: int = 0
    downstream_count: int = 0
    # Rich metadata for detail panel
    columns: List[Dict[str, Any]] = []
    row_count: Optional[int] = None
    tags: List[str] = []
    criticality: str = "medium"
    canonical_type: Optional[str] = None
    raw_metadata: Dict[str, Any] = {}
    last_updated: Optional[str] = None
    observed_at: Optional[str] = None

    class Config:
        populate_by_name = True


class EngineEdgeResponse(BaseModel):
    """Extended edge response with engine fields."""
    id: str
    source_id: str
    target_id: str
    edge_type: str
    lineage_level: str = "table"
    confidence: float = 1.0
    plane: str = "data"
    discovered_from: Optional[str] = None
    evidence: List[EngineEvidenceResponse] = []
    column_mappings: List[EngineColumnMappingResponse] = []


class EngineGraphResponse(BaseModel):
    """Full engine graph response."""
    success: bool
    nodes: List[EngineNodeResponse] = []
    edges: List[EngineEdgeResponse] = []
    stats: Dict[str, Any] = {}
    errors: List[str] = []


class EngineBuildRequest(BaseModel):
    """Request to build a lineage graph from config."""
    config: Dict[str, Any] = Field(..., description="Engine config with adapters, resolver, sql_parser sections")


class CoverageStatsResponse(BaseModel):
    """Coverage statistics."""
    total_nodes: int = 0
    total_edges: int = 0
    edges_by_level: Dict[str, int] = {}
    edges_by_plane: Dict[str, int] = {}
    edges_by_system: Dict[str, int] = {}
    nodes_by_domain: Dict[str, int] = {}
    nodes_by_kind: Dict[str, int] = {}
    high_confidence_pct: float = 0.0
    medium_confidence_pct: float = 0.0
    low_confidence_pct: float = 0.0
    coverage_table: float = 0.0
    coverage_column: float = 0.0
    coverage_tool: float = 0.0


def _node_to_engine_response(node) -> EngineNodeResponse:
    return EngineNodeResponse(
        id=node.id,
        name=node.name,
        fqn=node.fqn,
        node_type=node.node_type.value,
        database=node.database,
        schema=node.schema,
        platform=node.platform,
        description=node.description,
        owner=node.owner,
        platform_domain=node.platform_domain.value,
        asset_kind=node.asset_kind.value,
        namespace=node.namespace,
        sources=node.sources,
        integration_id=node.integration_id,
        dbt_resource_type=node.raw_metadata.get("dbt_resource_type"),
        upstream_count=node.upstream_count,
        downstream_count=node.downstream_count,
        columns=node.columns or [],
        row_count=node.row_count,
        tags=node.tags or [],
        criticality=getattr(node, "criticality", "medium") or "medium",
        canonical_type=node.canonical_type,
        raw_metadata=node.raw_metadata or {},
        last_updated=(node.last_updated.isoformat() + 'Z') if node.last_updated else None,
        observed_at=(node.observed_at.isoformat() + 'Z') if node.observed_at else None,
    )


def _edge_to_engine_response(edge) -> EngineEdgeResponse:
    return EngineEdgeResponse(
        id=edge.id,
        source_id=edge.source_id,
        target_id=edge.target_id,
        edge_type=edge.edge_type.value,
        lineage_level=edge.lineage_level.value,
        confidence=edge.confidence,
        plane=edge.plane.value,
        discovered_from=edge.discovered_from,
        evidence=[
            EngineEvidenceResponse(
                adapter_id=e.adapter_id,
                source_ref=e.source_ref,
                observed_at=(e.observed_at.isoformat() + 'Z') if e.observed_at else None,
                snippet=e.snippet,
            )
            for e in edge.evidence
        ],
        column_mappings=[
            EngineColumnMappingResponse(
                from_column=m.from_column,
                to_column=m.to_column,
                transform_expr=m.transform_expr,
                confidence=m.confidence,
            )
            for m in edge.column_mappings
        ],
    )


# All cache state lives in _lineage_cache. The wrappers below take the
# explicit (org_id, stack_id) form. They exist as a transition layer
# while individual writer/reader endpoints are migrated to pass
# principal.organization_id directly. Removed in a subsequent task once
# every endpoint passes through _lineage_cache directly.

# Temporary shim — removed once every writer endpoint passes org_id
# explicitly. Reading or writing this value is a bug; if you find
# yourself touching it, fix the call site instead.
_current_stack_id: str = "default"

# Sentinel org_id used when a writer/reader has not yet been migrated
# to pass principal.organization_id explicitly. The compound cache key
# becomes f"__legacy_default_org__:{stack_id}". Removed in a later
# commit once every call site is migrated.
_LEGACY_ORG: str = "__legacy_default_org__"


def _get_engine_store(*args):
    """Transition wrapper. Accepts either (stack_id) [legacy] or
    (org_id, stack_id) [new — preferred]. Removed in a later commit
    once every call site passes (org_id, stack_id)."""
    if len(args) == 1:
        return _lineage_cache.get_engine_store(_LEGACY_ORG, args[0])
    if len(args) == 2:
        return _lineage_cache.get_engine_store(args[0], args[1])
    raise TypeError(
        f"_get_engine_store expected 1 or 2 args, got {len(args)}"
    )


def _get_run_registry(*args):
    """Transition wrapper. Accepts either (stack_id) [legacy] or
    (org_id, stack_id) [new — preferred]. Removed in a later commit
    once every call site passes (org_id, stack_id)."""
    if len(args) == 1:
        return _lineage_cache.get_run_registry(_LEGACY_ORG, args[0])
    if len(args) == 2:
        return _lineage_cache.get_run_registry(args[0], args[1])
    raise TypeError(
        f"_get_run_registry expected 1 or 2 args, got {len(args)}"
    )


def _get_collected_results(*args):
    """Transition wrapper. Accepts either (stack_id) [legacy] or
    (org_id, stack_id) [new — preferred]. Removed in a later commit
    once every call site passes (org_id, stack_id)."""
    if len(args) == 1:
        return _lineage_cache.get_collected_results(_LEGACY_ORG, args[0])
    if len(args) == 2:
        return _lineage_cache.get_collected_results(args[0], args[1])
    raise TypeError(
        f"_get_collected_results expected 1 or 2 args, got {len(args)}"
    )


def _clear_engine_cache(*args):
    """Transition wrapper. Accepts either (stack_id) [legacy] or
    (org_id, stack_id) [new — preferred]. Removed in a later commit
    once every call site passes (org_id, stack_id)."""
    if len(args) == 1:
        _lineage_cache.clear_engine_cache(_LEGACY_ORG, args[0])
    elif len(args) == 2:
        _lineage_cache.clear_engine_cache(args[0], args[1])
    else:
        raise TypeError(
            f"_clear_engine_cache expected 1 or 2 args, got {len(args)}"
        )


class _CollectedResultsProxy:
    """TRANSITION-ONLY proxy. Delegates to the (default-org, current-stack)
    bucket via the legacy _current_stack_id global. Removed in a later
    task once every writer passes (org_id, stack_id) directly."""

    def __getitem__(self, key):
        return _lineage_cache.get_collected_results(_LEGACY_ORG, _current_stack_id)[key]

    def __setitem__(self, key, value):
        _lineage_cache.get_collected_results(_LEGACY_ORG, _current_stack_id)[key] = value

    def get(self, key, default=None):
        return _lineage_cache.get_collected_results(_LEGACY_ORG, _current_stack_id).get(key, default)


_engine_collected_results = _CollectedResultsProxy()


def _rebuild_engine_from_cache(org_id: str, stack_id: Optional[str]) -> None:
    """
    Run the resolver pipeline on cached adapter results (no re-parsing).

    Instead of re-running adapters (which re-run parsers and make network calls),
    this takes the already-converted engine nodes/edges and runs only the resolver
    (normalize, deduplicate, merge evidence, weight confidence).
    """
    import logging
    from datetime import datetime
    _logger = logging.getLogger(__name__)
    try:
        try:
            from lineage.engine.resolver import ResolverPipeline, ResolverConfig
        except ImportError:
            from scanner.lineage.engine.resolver import ResolverPipeline, ResolverConfig

        store = _get_engine_store(org_id, stack_id)
        collected = _get_collected_results(org_id, stack_id)
        pipeline = ResolverPipeline(ResolverConfig())
        store.graph = pipeline.resolve(
            list(collected["nodes"]),
            list(collected["edges"]),
        )
        store.resolution_stats = pipeline.stats
        store.graph.built_at = datetime.utcnow()

        _logger.info(
            f"[Engine] Built graph: {len(store.graph.nodes)} nodes, "
            f"{len(store.graph.edges)} edges"
        )
        if store.resolution_stats:
            _logger.info(
                f"[Engine] Resolver: {store.resolution_stats.nodes_before} → "
                f"{store.resolution_stats.nodes_after} nodes, "
                f"{store.resolution_stats.edges_before} → "
                f"{store.resolution_stats.edges_after} edges, "
                f"{store.resolution_stats.nodes_deduplicated} deduplicated, "
                f"{store.resolution_stats.edges_merged} merged"
            )

        # --- Cross-tool edge synthesis ---
        # Runs for ALL pipelines (not just when dbt is present) so that
        # ingestion→warehouse POPULATES edges are always synthesized.
        if store.graph:
            try:
                try:
                    from lineage.canonical import CanonicalResolver
                    from lineage.cross_tool import CrossToolEdgeSynthesizer
                except ImportError:
                    from scanner.lineage.canonical import CanonicalResolver
                    from scanner.lineage.cross_tool import CrossToolEdgeSynthesizer

                dbt_manifest = collected.get("dbt_manifest")
                dbt_cfg = collected.get("dbt_config") or {}
                resolver = CanonicalResolver(
                    default_warehouse=dbt_cfg.get("warehouse_type", "bigquery"),
                    project_id=dbt_cfg.get("namespace", ""),
                )
                if dbt_manifest:
                    resolver.register_dbt_sources(dbt_manifest.get("sources", {}))
                    resolver.register_dbt_model_targets(dbt_manifest.get("nodes", {}))

                # Patch dbt node schemas if GitHub-derived schema mapping is available
                schema_mapping = collected.get("schema_mapping")
                if schema_mapping:
                    for node in store.graph.nodes.values():
                        if node.platform == "dbt" and node.name in schema_mapping:
                            corrected = schema_mapping[node.name]
                            if corrected and corrected != node.schema:
                                _logger.debug(f"[Engine] Schema fix: {node.name} {node.schema} → {corrected}")
                                node.schema = corrected

                synthesizer = CrossToolEdgeSynthesizer(
                    graph=store.graph,
                    resolver=resolver,
                    dbt_manifest=dbt_manifest,
                )
                synthesis_stats = synthesizer.synthesize_all()
                _logger.info(
                    f"[Engine] Cross-tool synthesis: {synthesis_stats.total_edges_created} edges, "
                    f"{synthesis_stats.nodes_merged} nodes merged"
                )
            except Exception as synth_err:
                _logger.warning(f"[Engine] Cross-tool synthesis failed (non-fatal): {synth_err}")

        # Apply canonical type mapping after all synthesis is done
        store.canonicalize()

        # --- Bridge rules: fill structural gaps (e.g. missing ingestion → raw writes) ---
        try:
            try:
                from lineage.engine.bridge import BridgeRuleEngine
            except ImportError:
                from scanner.lineage.engine.bridge import BridgeRuleEngine

            bridge_engine = BridgeRuleEngine(store.graph)
            bridge_result = bridge_engine.apply_all()
            if bridge_result.total_changes > 0:
                _logger.info(
                    f"[Engine] Bridge rules: +{len(bridge_result.added_nodes)} nodes, "
                    f"+{len(bridge_result.added_edges)} edges"
                )
                # Re-canonicalize so bridge-added nodes get canonical types
                store.canonicalize()
        except Exception as bridge_err:
            _logger.warning(f"[Engine] Bridge rules failed (non-fatal): {bridge_err}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        _logger.warning(f"[Engine] Failed to build engine graph: {e}")


def _parse_filters(
    level: Optional[str] = None,
    system: Optional[str] = None,
    domain: Optional[str] = None,
    kind: Optional[str] = None,
    min_confidence: float = 0.0,
    plane: Optional[str] = None,
):
    """Parse query params into a Filters object."""
    try:
        from lineage.engine.store import Filters
        from lineage.graph import LineageLevel, LinePlane, PlatformDomain, AssetKind
    except ImportError:
        from scanner.lineage.engine.store import Filters
        from scanner.lineage.graph import LineageLevel, LinePlane, PlatformDomain, AssetKind

    filters = Filters(min_confidence=min_confidence)
    if level:
        filters.lineage_levels = {LineageLevel(l.strip()) for l in level.split(",")}
    if system:
        filters.systems = set(system.split(","))
    if domain:
        filters.platform_domains = {PlatformDomain(d.strip()) for d in domain.split(",")}
    if kind:
        filters.asset_kinds = {AssetKind(k.strip()) for k in kind.split(",")}
    if plane:
        filters.planes = {LinePlane(p.strip()) for p in plane.split(",")}
    return filters


@router.post("/lineage/engine/clear-cache")
async def engine_clear_cache(
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Reset engine cache before a fresh extraction batch.

    Clears only the buckets owned by the caller's organization. The
    frontend calls this before looping over pipeline nodes so that
    stale data from a previous extraction run doesn't accumulate.
    """
    import logging

    org_id = principal.organization_id
    _clear_engine_cache(org_id, stack_id)

    # Clear in-memory graph for this principal's bucket
    store = _get_engine_store(org_id, stack_id)
    store.graph = None
    store.tool_nodes = []

    # Clear run registry so stale pre-computed views are not served
    registry = _get_run_registry(org_id, stack_id)
    registry._runs.clear()
    registry._current_run_id = None

    logging.getLogger(__name__).info(
        f"[Engine] clear-cache: org={org_id} stack_id={stack_id or 'default'}"
    )
    return {"success": True, "message": "Engine cache cleared"}


@router.post("/lineage/engine/build", response_model=EngineGraphResponse)
async def engine_build(
    request: EngineBuildRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Build a lineage graph from engine config."""
    import asyncio

    store = _get_engine_store(principal.organization_id, stack_id)
    try:
        graph = await asyncio.to_thread(store.build_graph, request.config)
        coverage = store.get_stats()

        return EngineGraphResponse(
            success=True,
            nodes=[_node_to_engine_response(n) for n in graph.nodes.values()],
            edges=[_edge_to_engine_response(e) for e in graph.edges.values()],
            stats=coverage.to_dict(),
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return EngineGraphResponse(success=False, errors=[str(e)])


@router.get("/lineage/engine/upstream/{asset_id}")
async def engine_upstream(
    asset_id: str,
    depth: int = Query(3, ge=1, le=50),
    level: Optional[str] = Query(None, description="Filter: tool,table,column"),
    system: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    plane: Optional[str] = Query(None, description="Edge plane filter: data,control,cross"),
    stack_id: Optional[str] = Query(None),
):
    """Get upstream lineage for an asset with filtering."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built. Call /lineage/engine/build first.")

    filters = _parse_filters(level, system, domain, kind, min_confidence, plane=plane)
    nodes = store.get_upstream(asset_id, depth=depth, filters=filters)
    return {"asset_id": asset_id, "upstream": [_node_to_engine_response(n).dict() for n in nodes]}


@router.get("/lineage/engine/downstream/{asset_id}")
async def engine_downstream(
    asset_id: str,
    depth: int = Query(3, ge=1, le=50),
    level: Optional[str] = Query(None),
    system: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    stack_id: Optional[str] = Query(None),
):
    """Get downstream lineage for an asset with filtering."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built. Call /lineage/engine/build first.")

    filters = _parse_filters(level, system, domain, kind, min_confidence)
    nodes = store.get_downstream(asset_id, depth=depth, filters=filters)
    return {"asset_id": asset_id, "downstream": [_node_to_engine_response(n).dict() for n in nodes]}


@router.get("/lineage/engine/blast-radius/{asset_id}")
async def engine_blast_radius(
    asset_id: str,
    level: Optional[str] = Query(None),
    system: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    stack_id: Optional[str] = Query(None),
):
    """Compute the downstream blast radius of an asset."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built. Call /lineage/engine/build first.")

    filters = _parse_filters(level, system, domain, kind, min_confidence)
    return store.blast_radius(asset_id, filters=filters)


@router.get("/lineage/engine/recommend-monitors/{asset_id}")
async def engine_recommend_monitors(
    asset_id: str,
    depth: int = Query(3, ge=1, le=10),
    existing_fqns: Optional[str] = Query(None, description="Comma-separated MONITOR_KEY:fqn strings for dedup"),
    stack_id: Optional[str] = Query(None),
):
    """Recommend monitors for a lineage node based on its type and upstream context."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built. Call /lineage/engine/build first.")

    node = store.graph.nodes.get(asset_id)
    if not node:
        # Return empty recommendations instead of 404 to prevent frontend retry spam.
        # The node may exist in Prisma but not in the engine graph (ID mismatch
        # between unified lineage IDs and engine graph IDs).
        return {
            "asset_id": asset_id,
            "asset_name": "",
            "asset_type": "unknown",
            "platform_domain": "unknown",
            "is_bi_node": False,
            "recommendations": [],
            "bundles": [],
        }

    # Get upstream nodes scoped to the visual data-lineage surface.
    # The unified route maps plane=data to "data,cross" at the engine layer
    # (unified/route.ts:371), so both DATA and CROSS edges are visible.
    # BI→table edges use CROSS plane, so we must include it.
    # The canonical type whitelist (dataset + semantic) prevents orchestration
    # nodes (reached via CROSS edges) from leaking into bundle candidates.
    try:
        from lineage.engine.store import Filters
        from lineage.graph import LinePlane
        from lineage.engine.canonical import map_node_type, CanonicalNodeType
    except ImportError:
        from scanner.lineage.engine.store import Filters
        from scanner.lineage.graph import LinePlane
        from scanner.lineage.engine.canonical import map_node_type, CanonicalNodeType

    # Only include physical data assets (DATASET, SEMANTIC) — exclude JOB nodes
    # (connectors, DAGs) to match the visual data-plane lineage.
    # Use DATA plane only (no CROSS) so Fivetran synced tables and other
    # cross-tool replicas don't appear — matches data-plane-neighbors behavior.
    _RECOMMEND_NODE_TYPES = {
        CanonicalNodeType.DATASET.value,
        CanonicalNodeType.SEMANTIC.value,
    }
    data_filters = Filters(planes={LinePlane.DATA})
    raw_upstream = store.get_upstream(asset_id, depth=depth, filters=data_filters)
    upstream_nodes = [
        n for n in raw_upstream
        if (n.canonical_type or map_node_type(n).value) in _RECOMMEND_NODE_TYPES
    ]

    # Parse existing monitor FQNs for dedup
    existing_set = set()
    if existing_fqns:
        existing_set = {fqn.strip() for fqn in existing_fqns.split(",") if fqn.strip()}

    try:
        from scanner.monitors.recommender import recommend_for_node, get_bundles, is_bi_node
    except ImportError:
        from monitors.recommender import recommend_for_node, get_bundles, is_bi_node

    recommendations = recommend_for_node(node, upstream_nodes=upstream_nodes, existing_monitor_fqns=existing_set)
    bundles = get_bundles(node, upstream_nodes=upstream_nodes, existing_monitor_fqns=existing_set)

    return {
        "asset_id": asset_id,
        "asset_name": node.name,
        "asset_type": node.node_type.value,
        "platform_domain": node.platform_domain.value,
        "is_bi_node": is_bi_node(node),
        "recommendations": [r.to_dict() for r in recommendations],
        "bundles": [b.to_dict() for b in bundles],
        "upstream_count": len(upstream_nodes),
    }


@router.get("/lineage/engine/explain-edge/{edge_id}")
async def engine_explain_edge(edge_id: str, stack_id: Optional[str] = Query(None)):
    """Show evidence and reasoning for a specific edge."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    result = store.explain_edge(edge_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/lineage/engine/search")
async def engine_search(
    q: str = Query(..., min_length=1, description="Search query (substring match on name/fqn)"),
    limit: int = Query(10, ge=1, le=100),
    stack_id: Optional[str] = Query(None),
):
    """Search lineage nodes by name or FQN substring match."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        return {"results": []}

    query_lower = q.lower()
    results = []
    for node in store.graph.nodes.values():
        name_match = query_lower in (node.name or "").lower()
        fqn_match = query_lower in (node.fqn or "").lower()
        if name_match or fqn_match:
            results.append({
                "id": node.id,
                "name": node.name,
                "fqn": node.fqn or node.name,
                "node_type": node.node_type.value if node.node_type else None,
                "platform_domain": node.platform_domain.value if node.platform_domain else None,
            })
            if len(results) >= limit:
                break

    return {"results": results}


@router.get("/lineage/engine/auto-anchor")
async def engine_auto_anchor(stack_id: Optional[str] = Query(None)):
    """Pick the best anchor node for full-pipeline protection.

    Strategy: find the leaf node with the most upstream ancestors.
    Falls back to any leaf, then any node.
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"anchor": None}

    leaves = store.graph.get_leaves()
    if not leaves:
        # No leaves — pick the node with the most upstream
        leaves = list(store.graph.nodes.values())

    # Score each candidate by upstream count
    best = None
    best_score = -1
    for node in leaves:
        upstream = store.graph.get_upstream(node.id, depth=10)
        score = len(upstream)
        if score > best_score:
            best_score = score
            best = node

    if not best:
        return {"anchor": None}

    return {
        "anchor": {
            "id": best.id,
            "name": best.name,
            "fqn": best.fqn or best.name,
            "platformDomain": best.platform_domain.value if best.platform_domain else None,
            "nodeType": best.node_type.value if best.node_type else None,
        },
        "totalNodes": len(store.graph.nodes),
    }


@router.get("/lineage/engine/graph")
async def engine_full_graph(
    plane: Optional[str] = Query(None, description="Filter edges by plane: data,control,cross"),
    stack_id: Optional[str] = Query(None),
):
    """Return the full engine graph (nodes + edges with confidence/evidence)."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        return {"nodes": [], "edges": []}

    edges = store.graph.edges.values()
    if plane:
        try:
            from lineage.graph import LinePlane
        except ImportError:
            from scanner.lineage.graph import LinePlane
        allowed = {LinePlane(p.strip()) for p in plane.split(",")}
        edges = [e for e in edges if e.plane in allowed]

    return {
        "nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in store.graph.nodes.values()],
        "edges": [_edge_to_engine_response(e).dict() for e in edges],
    }


@router.get("/lineage/engine/snapshot")
async def engine_snapshot(stack_id: Optional[str] = Query(None)):
    """Return the engine graph serialized for persistence (to store in DB).

    The response includes the full graph dict (nodes + edges with all metadata
    including raw_metadata / dbt_resource_type) so the frontend can save it
    to LineageSnapshot.graphData and restore on server restart.
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"has_graph": False, "graph_data": None}
    graph_data = store.graph.to_dict()
    graph_data["tool_nodes"] = store.tool_nodes or []
    return {"has_graph": True, "graph_data": graph_data}


class EngineRestoreRequest(BaseModel):
    """Request to restore the engine graph from a persisted snapshot."""
    graph_data: Dict[str, Any] = Field(..., description="Serialized graph dict from LineageGraph.to_dict()")


@router.post("/lineage/engine/restore")
async def engine_restore(
    request: EngineRestoreRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Restore the engine graph from a previously persisted snapshot.

    Called by the frontend when the in-memory engine graph is empty (after
    server restart) but a snapshot exists in the database.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        try:
            from lineage.graph import LineageGraph
        except ImportError:
            from scanner.lineage.graph import LineageGraph

        graph = LineageGraph.from_dict(request.graph_data)
        store = _get_engine_store(principal.organization_id, stack_id)
        store.graph = graph
        store.tool_nodes = request.graph_data.get("tool_nodes", [])
        _logger.info(
            f"[Engine] Restored graph from snapshot: {len(graph.nodes)} nodes, "
            f"{len(graph.edges)} edges, {len(store.tool_nodes)} tool_nodes"
        )
        return {
            "success": True,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        _logger.error(f"[Engine] Failed to restore graph: {e}")
        return {"success": False, "error": str(e)}


@router.get("/lineage/engine/control-plane/{dag_id}")
async def engine_control_plane(dag_id: str, stack_id: Optional[str] = Query(None)):
    """Return the control-plane subgraph for a specific DAG.

    Returns the DAG node, its tasks, internal dependency edges, and
    cross-link edges to data-plane assets.
    """
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    sub = store.get_control_plane_subgraph(dag_id)
    if not sub.nodes:
        raise HTTPException(status_code=404, detail=f"DAG '{dag_id}' not found in graph.")

    return {
        "dag_id": dag_id,
        "nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in sub.nodes.values()],
        "edges": [_edge_to_engine_response(e).dict() for e in sub.edges.values()],
        "stats": {
            "total_nodes": len(sub.nodes),
            "total_edges": len(sub.edges),
            "task_count": sum(1 for n in sub.nodes.values() if n.node_type.value == "task"),
            "cross_link_count": sum(1 for e in sub.edges.values() if e.plane.value == "cross"),
        },
    }


@router.get("/lineage/engine/control-plane")
async def engine_control_plane_all(stack_id: Optional[str] = Query(None)):
    """Return the full control-plane subgraph (all DAGs and tasks)."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        return {"nodes": [], "edges": [], "stats": {}}

    sub = store.get_control_plane_subgraph()
    return {
        "nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in sub.nodes.values()],
        "edges": [_edge_to_engine_response(e).dict() for e in sub.edges.values()],
        "stats": {
            "total_nodes": len(sub.nodes),
            "total_edges": len(sub.edges),
        },
    }


@router.get("/lineage/engine/cross-links/{asset_id}")
async def engine_cross_links(asset_id: str, stack_id: Optional[str] = Query(None)):
    """Return cross-plane edges for a data asset (links to orchestration)."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    cross_edges = store.get_cross_links(asset_id)
    # Also return the connected orchestration nodes
    connected_nodes = {}
    for edge in cross_edges:
        other_id = edge.target_id if edge.source_id == asset_id else edge.source_id
        if other_id in store.graph.nodes:
            connected_nodes[other_id] = store.graph.nodes[other_id]

    return {
        "asset_id": asset_id,
        "cross_links": [_edge_to_engine_response(e).dict() for e in cross_edges],
        "connected_nodes": [_node_to_engine_response(n).dict(by_alias=True) for n in connected_nodes.values()],
    }


@router.get("/lineage/engine/run-history/{dag_id}")
async def engine_run_history(
    dag_id: str,
    limit: int = Query(10, ge=1, le=100),
    stack_id: Optional[str] = Query(None),
):
    """Get recent run history for an Airflow DAG.

    Delegates to AirflowIntegration if an adapter is available. Otherwise
    returns whatever run_summary data is stored on the DAG node.
    """
    store = _get_engine_store(stack_id)

    # Try to find run_summary from the DAG node's raw_metadata
    dag_node = None
    if store.graph:
        for node in store.graph.nodes.values():
            if node.node_type.value == "dag" and node.name == dag_id:
                dag_node = node
                break

    run_summary = dag_node.raw_metadata.get("run_summary") if dag_node else None

    return {
        "dag_id": dag_id,
        "run_summary": run_summary,
        "dag_found": dag_node is not None,
    }


@router.get("/lineage/engine/stats", response_model=CoverageStatsResponse)
async def engine_stats(stack_id: Optional[str] = Query(None)):
    """Get coverage statistics for the built lineage graph."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        return CoverageStatsResponse()

    coverage = store.get_stats()
    return CoverageStatsResponse(**coverage.to_dict())


@router.get("/lineage/engine/export")
async def engine_export(
    fmt: str = Query("json", description="Format: json, graphml, dot"),
    level: Optional[str] = Query(None),
    system: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    stack_id: Optional[str] = Query(None),
):
    """Export the lineage graph in various formats."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        raise HTTPException(status_code=404, detail="No graph built.")

    try:
        from lineage.engine.export import export_json, export_graphml, export_dot
    except ImportError:
        from scanner.lineage.engine.export import export_json, export_graphml, export_dot

    filters = _parse_filters(level, system, min_confidence=min_confidence)

    if fmt == "graphml":
        content = export_graphml(store.graph, filters)
        return {"format": "graphml", "content": content}
    elif fmt == "dot":
        content = export_dot(store.graph, filters)
        return {"format": "dot", "content": content}
    else:
        content = export_json(store.graph, filters)
        return {"format": "json", "content": content}


# ==========================================
# CONTROL PLANE OVERVIEW (tool-sequence graph)
# ==========================================


@router.get("/lineage/engine/control-plane-overview")
async def engine_control_plane_overview(stack_id: Optional[str] = Query(None)):
    """
    Return the derived control plane graph showing tool/integration sequence.

    This is different from the per-DAG control plane — it shows the entire
    pipeline architecture: which tools feed into which, in what order.

    Example: Fivetran → Snowflake → dbt → Snowflake → Looker
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"nodes": [], "edges": [], "stats": {"tool_count": 0, "flow_count": 0}}

    try:
        try:
            from lineage.engine.control_plane import build_control_plane_graph
        except ImportError:
            from scanner.lineage.engine.control_plane import build_control_plane_graph

        cp_graph = build_control_plane_graph(store.graph)
        return cp_graph.to_dict()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Control plane overview failed: {e}")
        return {"nodes": [], "edges": [], "stats": {"tool_count": 0, "flow_count": 0}, "error": str(e)}


# ==========================================
# RENDERED VIEWS (v2 — canonical + deterministic layout)
# ==========================================


class ViewNodeResponse(BaseModel):
    """A node in a rendered view."""
    id: str
    name: str
    canonicalType: str
    originalType: str
    platform: Optional[str] = None
    platformDomain: str = "other"
    layer: str = "WAREHOUSE"
    clusterId: Optional[str] = None
    x: float = 0
    y: float = 0
    inferred: bool = False
    needsMapping: bool = False
    metadata: Dict[str, Any] = {}


class ViewEdgeResponse(BaseModel):
    """An edge in a rendered view."""
    id: str
    sourceId: str
    targetId: str
    canonicalType: str
    originalType: str
    confidence: float = 1.0
    inferred: bool = False
    evidenceCount: int = 0


class ViewClusterResponse(BaseModel):
    """A visual cluster in a rendered view."""
    id: str
    label: str
    platform: Optional[str] = None
    layer: str = "WAREHOUSE"
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    nodeCount: int = 0


class RenderedViewResponse(BaseModel):
    """Full rendered view response."""
    viewType: str
    nodes: List[ViewNodeResponse] = []
    edges: List[ViewEdgeResponse] = []
    clusters: List[ViewClusterResponse] = []
    unmappedNodes: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {}


@router.get("/lineage/engine/views/pipeline-overview")
async def view_pipeline_overview(stack_id: Optional[str] = Query(None)):
    """
    Return the pre-rendered Pipeline Overview view.

    Shows tool/integration instances as service nodes with inter-tool
    data flow edges. Deterministic layout with canonical types.

    Serves from pre-computed run artifacts when available,
    falls back to on-demand computation.
    """
    # Try pre-computed view from run registry
    registry = _get_run_registry(stack_id)
    if registry.current_run_id:
        record = registry.get_run(registry.current_run_id)
        if record and "pipeline_overview" in record.artifacts.views:
            return record.artifacts.views["pipeline_overview"]

    # Fallback: compute on-demand
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return RenderedViewResponse(
            viewType="pipeline_overview",
            stats={"serviceCount": 0, "flowCount": 0, "totalAssets": 0},
        ).dict()

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        view = builder.build_pipeline_overview()
        return view.to_dict()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Pipeline overview view failed: {e}")
        return RenderedViewResponse(
            viewType="pipeline_overview",
            stats={"error": str(e)},
        ).dict()


@router.get("/lineage/engine/views/lane-pipeline-overview")
async def view_lane_pipeline_overview(stack_id: Optional[str] = Query(None)):
    """
    Return the lane-based Pipeline Overview view.

    Renders nodes in fixed lanes:
      ingestion → warehouse_raw → transformation → warehouse_analytics → reporting

    Serves from pre-computed run artifacts when available,
    falls back to on-demand computation.
    """
    # Always compute on-demand to pick up latest code changes and tool_nodes.
    # Pre-computed views from run registry can become stale when tool_nodes
    # are enriched or edge aggregation logic changes.
    import logging as _logging
    _log = _logging.getLogger(__name__)
    _log.info("[Engine] lane-pipeline-overview: computing on-demand (v2 — evidence-based edges)")
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        _log.info("[Engine] lane-pipeline-overview: empty graph, returning empty response")
        return RenderedViewResponse(
            viewType="lane_pipeline_overview",
            stats={"totalNodes": 0, "totalEdges": 0},
        ).dict()

    _log.info(
        "[Engine] lane-pipeline-overview: graph has %d nodes, %d edges, %d tool_nodes",
        len(store.graph.nodes), len(store.graph.edges), len(store.tool_nodes or []),
    )

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        view = builder.build_lane_pipeline_overview()
        _log.info(
            "[Engine] lane-pipeline-overview: result has %d nodes, %d edges",
            len(view.nodes), len(view.edges),
        )
        return view.to_dict()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Lane pipeline overview failed: {e}")
        import traceback
        traceback.print_exc()
        return RenderedViewResponse(
            viewType="lane_pipeline_overview",
            stats={"error": str(e)},
        ).dict()


@router.get("/lineage/engine/views/tool-details/{tool_view_id:path}")
async def view_tool_details(
    tool_view_id: str,
    stack_id: Optional[str] = Query(None),
):
    """
    Return detailed inspection data for a single tool in the Pipeline Overview.

    The tool_view_id is the ViewNode.id from the lane-pipeline-overview response
    (e.g. "tool:bigquery" or "tool:fivetran:abc123").
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"error": "No graph loaded", "toolId": tool_view_id}

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        return builder.build_tool_details(tool_view_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Tool details failed: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "toolId": tool_view_id}


@router.get("/lineage/engine/views/data-plane")
async def view_data_plane(stack_id: Optional[str] = Query(None)):
    """
    Return the pre-rendered Data Plane view.

    Shows dataset-to-dataset derivation chains with deterministic
    layered layout, canonical types, and cluster grouping.

    Serves from pre-computed run artifacts when available,
    falls back to on-demand computation.
    """
    # Try pre-computed view from run registry
    registry = _get_run_registry(stack_id)
    if registry.current_run_id:
        record = registry.get_run(registry.current_run_id)
        if record and "data_plane" in record.artifacts.views:
            return record.artifacts.views["data_plane"]

    # Fallback: compute on-demand
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return RenderedViewResponse(
            viewType="data_plane",
            stats={"datasetCount": 0, "edgeCount": 0},
        ).dict()

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        view = builder.build_data_plane()
        return view.to_dict()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[Engine] Data plane view failed: {e}")
        return RenderedViewResponse(
            viewType="data_plane",
            stats={"error": str(e)},
        ).dict()


# ==========================================
# DATA-PLANE NEIGHBOR LOOKUP
# ==========================================


@router.get("/lineage/engine/data-plane/neighbors/{node_id}")
async def data_plane_neighbors(
    node_id: str,
    direction: str = Query("upstream", pattern="^(upstream|downstream)$"),
    depth: int = Query(3, ge=1, le=5),
    limit: int = Query(50, ge=1, le=200),
    stack_id: Optional[str] = Query(None),
):
    """
    Get neighbors of a node in the pre-computed data_plane view.

    Uses the current run's data_plane view edges for adjacency,
    ensuring the detail panel shows the same topology as the
    rendered visualization.

    Falls back to on-demand view build if no pre-computed view exists.
    """
    try:
        from scanner.lineage.engine.views import compute_neighbors_from_view
    except ImportError:
        from lineage.engine.views import compute_neighbors_from_view

    # 1) Try pre-computed data_plane view from current run
    registry = _get_run_registry(stack_id)
    if registry.current_run_id:
        record = registry.get_run(registry.current_run_id)
        if record and "data_plane" in record.artifacts.views:
            view_dict = record.artifacts.views["data_plane"]
            return compute_neighbors_from_view(
                view_dict, node_id, direction, depth, limit,
            )

    # 2) Fallback: compute data_plane view on-demand from engine graph
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {
            "nodeId": node_id,
            "direction": direction,
            "depth": depth,
            "neighbors": [],
            "totalCount": 0,
            "source": "none",
        }

    try:
        try:
            from lineage.engine.views import ViewBuilder
        except ImportError:
            from scanner.lineage.engine.views import ViewBuilder

        builder = ViewBuilder(store.graph, tool_nodes=store.tool_nodes, pipeline_edges=getattr(store, 'pipeline_edges', []))
        view = builder.build_data_plane()
        view_dict = view.to_dict()
        result = compute_neighbors_from_view(
            view_dict, node_id, direction, depth, limit,
        )
        result["source"] = "engine_fallback"
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f"[Engine] Data-plane neighbors fallback failed: {e}"
        )
        return {
            "nodeId": node_id,
            "direction": direction,
            "depth": depth,
            "neighbors": [],
            "totalCount": 0,
            "source": "error",
        }


# ==========================================
# RUN VERSIONING
# ==========================================


@router.get("/lineage/runs/current")
async def get_current_run(stack_id: Optional[str] = Query(None)):
    """Return the current (published) run_id and its status."""
    registry = _get_run_registry(stack_id)
    if not registry.current_run_id:
        return {"current_run_id": None, "status": None}
    record = registry.get_run(registry.current_run_id)
    if not record:
        return {"current_run_id": None, "status": None}
    return record.to_dict()


@router.get("/lineage/runs/{run_id}/status")
async def get_run_status(run_id: str, stack_id: Optional[str] = Query(None)):
    """Lightweight status for polling a specific run."""
    registry = _get_run_registry(stack_id)
    status = registry.get_run_status(run_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return status


@router.get("/lineage/runs/{run_id}/views/{view_type}")
async def get_run_view(run_id: str, view_type: str, stack_id: Optional[str] = Query(None)):
    """Return a pre-computed view from a specific run."""
    registry = _get_run_registry(stack_id)
    record = registry.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    view = record.artifacts.views.get(view_type)
    if not view:
        raise HTTPException(
            status_code=404,
            detail=f"View '{view_type}' not found for run {run_id}. "
                   f"Available: {list(record.artifacts.views.keys())}",
        )
    return view


@router.get("/lineage/runs")
async def list_runs(limit: int = Query(5, ge=1, le=20), stack_id: Optional[str] = Query(None)):
    """Return recent extraction runs."""
    registry = _get_run_registry(stack_id)
    return {
        "runs": registry.list_runs(limit),
        "current_run_id": registry.current_run_id,
    }


# ==========================================
# RECONCILIATION (LLM-powered graph patching)
# ==========================================


class ReconcileRequest(BaseModel):
    """Request to run LLM reconciliation on the engine graph."""
    provider: str = Field("anthropic", description="LLM provider: anthropic or openai")
    model: Optional[str] = Field(None, description="Model override")
    dry_run: bool = Field(True, description="If true, return patch without applying")


class ReconcilePatchResponse(BaseModel):
    """The reconciliation patch for review."""
    patch_version: str = "1.0"
    merge_suggestions: List[Dict[str, Any]] = []
    add_nodes: List[Dict[str, Any]] = []
    add_edges: List[Dict[str, Any]] = []
    layer_assignments: List[Dict[str, Any]] = []
    unknowns: List[Dict[str, Any]] = []


class ReconcileResponse(BaseModel):
    """Full reconciliation response."""
    success: bool
    patch: ReconcilePatchResponse
    diagnostics: Dict[str, Any] = {}
    applied: Dict[str, int] = {}
    unknowns: List[Dict[str, Any]] = []
    validation_errors: List[str] = []
    duration_ms: int = 0
    run_id: str = ""


@router.get("/lineage/engine/reconcile/diagnostics")
async def engine_reconcile_diagnostics(stack_id: Optional[str] = Query(None)):
    """Return graph diagnostics without calling the LLM.

    Useful for showing the user what issues exist before they
    decide to run the (potentially expensive) LLM reconciliation.
    """
    store = _get_engine_store(stack_id)
    if not store.graph or not store.graph.nodes:
        return {"diagnostics": {"dataset_roots": [], "disconnected_components": [],
                                "suspected_duplicates": [], "missing_links_hints": []}}

    try:
        try:
            from lineage.engine.reconciler import DiagnosticsBuilder
        except ImportError:
            from scanner.lineage.engine.reconciler import DiagnosticsBuilder

        builder = DiagnosticsBuilder(store.graph)
        diagnostics = builder.build()
        return {"diagnostics": diagnostics.to_dict()}
    except Exception as e:
        return {"diagnostics": {}, "error": str(e)}


@router.post("/lineage/engine/reconcile", response_model=ReconcileResponse)
async def engine_reconcile(
    request: ReconcileRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Run LLM reconciliation on the current engine graph.

    If dry_run=True (default), returns the patch for UI review without applying.
    If dry_run=False, applies the patch immediately.

    Requires a built engine graph (call /lineage/investigate or
    /lineage/engine/build first).
    """
    import logging
    _logger = logging.getLogger(__name__)

    store = _get_engine_store(principal.organization_id, stack_id)
    if not store.graph or not store.graph.nodes:
        raise HTTPException(404, "No graph built. Extract lineage first.")

    try:
        try:
            from lineage.engine.reconciler import ReconcilerConfig
        except ImportError:
            from scanner.lineage.engine.reconciler import ReconcilerConfig

        config = ReconcilerConfig(
            provider=request.provider,
            model=request.model or (
                "claude-sonnet-4-20250514" if request.provider == "anthropic"
                else "gpt-5.2"
            ),
            dry_run=request.dry_run,
        )

        result = await store.reconcile(config)

        _logger.info(
            f"[Reconciler] {result.run_id}: success={result.success}, "
            f"applied={result.applied}, duration={result.duration_ms}ms"
        )

        return ReconcileResponse(
            success=result.success,
            patch=ReconcilePatchResponse(**result.patch.to_dict()),
            diagnostics=result.diagnostics.to_dict(),
            applied=result.applied,
            unknowns=[
                {"entity_ref": u.entity_ref, "issue": u.issue,
                 "suggested_action": u.suggested_action,
                 "questions": u.questions}
                for u in result.unknowns
            ],
            validation_errors=result.validation_errors,
            duration_ms=result.duration_ms,
            run_id=result.run_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Reconciliation failed: {e}")


class ReconcileApplyRequest(BaseModel):
    """Request to apply a previously-generated reconciliation patch."""
    run_id: str = Field(..., description="Run ID from a previous dry-run")
    patch: Dict[str, Any] = Field(..., description="The patch dict to apply")


@router.post("/lineage/engine/reconcile/apply")
async def engine_reconcile_apply(
    request: ReconcileApplyRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """Apply a reconciliation patch that was previously generated with dry_run=True.

    This enables the 'review & confirm' flow:
    1. User triggers reconcile with dry_run=True
    2. UI shows the patch (merges, new nodes, unknowns)
    3. User reviews and clicks 'Apply'
    4. This endpoint applies the approved patch
    """
    import logging
    _logger = logging.getLogger(__name__)

    store = _get_engine_store(principal.organization_id, stack_id)
    if not store.graph or not store.graph.nodes:
        raise HTTPException(404, "No graph built.")

    try:
        try:
            from lineage.engine.reconciler import (
                ReconciliationPatch, PatchValidator, PatchApplier,
            )
            from lineage.engine.canonical import canonicalize_graph_in_place
        except ImportError:
            from scanner.lineage.engine.reconciler import (
                ReconciliationPatch, PatchValidator, PatchApplier,
            )
            from scanner.lineage.engine.canonical import canonicalize_graph_in_place

        patch = ReconciliationPatch.from_dict(request.patch)

        # Validate
        validator = PatchValidator(store.graph)
        if not validator.validate(patch):
            return {
                "success": False,
                "errors": validator.errors,
                "message": "Patch validation failed",
            }

        # Apply
        applier = PatchApplier(store.graph, request.run_id)
        applied = applier.apply(patch)

        # Re-canonicalize
        canonicalize_graph_in_place(store.graph.nodes, store.graph.edges)

        _logger.info(
            f"[Reconciler] Applied patch {request.run_id}: {applied}"
        )

        return {
            "success": True,
            "applied": applied,
            "total_nodes": len(store.graph.nodes),
            "total_edges": len(store.graph.edges),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ==========================================
# OPENLINEAGE EVENT INGESTION
# ==========================================


class OpenLineageEventRequest(BaseModel):
    """A single OpenLineage RunEvent."""
    eventType: str
    eventTime: str
    run: Dict[str, Any]
    job: Dict[str, Any]
    inputs: List[Dict[str, Any]] = []
    outputs: List[Dict[str, Any]] = []
    producer: Optional[str] = None


class OpenLineageBatchRequest(BaseModel):
    """Batch of OpenLineage RunEvents."""
    events: List[Dict[str, Any]]


@router.post("/lineage/openlineage/event")
async def ingest_openlineage_event(
    request: OpenLineageEventRequest,
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Ingest a single OpenLineage RunEvent.

    Maps the event to internal LineageNode/LineageEdge format and adds
    to the engine cache, triggering an incremental graph rebuild.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        try:
            from lineage.engine.openlineage import OpenLineageMapper
        except ImportError:
            from scanner.lineage.engine.openlineage import OpenLineageMapper

        mapper = OpenLineageMapper()
        event_dict = request.dict()
        nodes, edges = mapper.map_event(event_dict)

        collected = _lineage_cache.get_collected_results(principal.organization_id, None)
        collected["nodes"].extend(nodes)
        collected["edges"].extend(edges)
        _rebuild_engine_from_cache(principal.organization_id, None)

        _logger.info(
            f"[OpenLineage] Ingested event: {request.job.get('name', '?')} "
            f"({request.eventType}) → {len(nodes)} nodes, {len(edges)} edges"
        )

        return {
            "success": True,
            "nodes_added": len(nodes),
            "edges_added": len(edges),
        }
    except Exception as e:
        _logger.error(f"[OpenLineage] Event ingestion failed: {e}")
        return {"success": False, "error": str(e)}


@router.post("/lineage/openlineage/events")
async def ingest_openlineage_events_batch(
    request: OpenLineageBatchRequest,
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Ingest a batch of OpenLineage RunEvents.

    Processes all events, accumulates nodes/edges, then rebuilds once.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        try:
            from lineage.engine.openlineage import OpenLineageMapper
        except ImportError:
            from scanner.lineage.engine.openlineage import OpenLineageMapper

        mapper = OpenLineageMapper()
        total_nodes = 0
        total_edges = 0
        errors = []
        collected = _lineage_cache.get_collected_results(principal.organization_id, None)

        for i, event in enumerate(request.events):
            try:
                nodes, edges = mapper.map_event(event)
                collected["nodes"].extend(nodes)
                collected["edges"].extend(edges)
                total_nodes += len(nodes)
                total_edges += len(edges)
            except Exception as e:
                errors.append(f"Event {i}: {str(e)}")

        _rebuild_engine_from_cache(principal.organization_id, None)

        _logger.info(
            f"[OpenLineage] Batch ingested {len(request.events)} events "
            f"→ {total_nodes} nodes, {total_edges} edges, {len(errors)} errors"
        )

        return {
            "success": len(errors) == 0,
            "events_processed": len(request.events),
            "nodes_added": total_nodes,
            "edges_added": total_edges,
            "errors": errors,
        }
    except Exception as e:
        _logger.error(f"[OpenLineage] Batch ingestion failed: {e}")
        return {"success": False, "error": str(e)}


# ==========================================
# LINEAGE INVESTIGATOR (context-accumulating)
# ==========================================


class InvestigateToolConfig(BaseModel):
    """Configuration for a single tool in the investigation."""
    tool_type: str = Field(..., description="Tool type: bigquery, dbt_cloud, n8n, etc.")
    config: Dict[str, Any] = Field(..., description="Decrypted integration config")
    integration_id: Optional[str] = Field(default=None)
    layer: Optional[str] = Field(default=None)
    adapter_type: Optional[str] = Field(default=None)


class InvestigateResponse(BaseModel):
    """Response from lineage investigation."""
    success: bool
    nodes: List[EngineNodeResponse] = []
    edges: List[EngineEdgeResponse] = []
    investigation: Dict[str, Any] = {}
    stats: Dict[str, Any] = {}
    errors: List[str] = []


def _resolve_github_token_from_tool_configs(tool_configs) -> str:
    """Resolve GitHub access token from sibling GitHub connector in the same scan batch.

    dbt/airflow nodes no longer carry their own github_token — they reference
    the shared GitHub connector's PAT.
    """
    for _tc in tool_configs:
        if (hasattr(_tc, "tool_type") and _tc.tool_type.lower() == "github"):
            _cfg = _tc.config if hasattr(_tc, "config") else {}
            _tok = _cfg.get("access_token") or _cfg.get("token") or _cfg.get("github_token") or ""
            if _tok:
                return _tok
    return ""


async def _preprocess_dbt_configs(tool_configs, logger_instance=None) -> None:
    """Resolve dbt_core tool configs in-place: parse project files or fetch manifest.

    Shared helper used by all investigate/extract endpoints to avoid
    code duplication. Handles project-upload and GitHub source modes,
    with a manifest.json fallback when project files are empty.
    """
    import logging
    _log = logger_instance or logging.getLogger(__name__)

    try:
        from lineage.dbt_project_parser import parse_dbt_project
    except ImportError:
        from scanner.lineage.dbt_project_parser import parse_dbt_project

    try:
        from lineage.github_reader import fetch_dbt_project_files_with_fallback
    except ImportError:
        from scanner.lineage.github_reader import fetch_dbt_project_files_with_fallback

    # Extract warehouse database/project_id from sibling tool configs
    # so dbt models get the correct namespace for cross-domain dedup
    warehouse_database = ""
    for tc in tool_configs:
        tl = tc.tool_type.lower() if hasattr(tc, "tool_type") else ""
        cfg = tc.config if hasattr(tc, "config") else {}
        if tl in ("bigquery", "snowflake", "postgres", "redshift"):
            warehouse_database = cfg.get("project_id") or cfg.get("database") or ""
            if warehouse_database:
                _log.info("[dbt-preprocess] Found warehouse database=%r from %s config", warehouse_database, tl)
                break
    if not warehouse_database:
        _log.warning("[dbt-preprocess] No warehouse project_id/database found in sibling tool configs")

    for tc in tool_configs:
        if tc.tool_type.lower() != "dbt_core":
            continue

        source_mode = tc.config.get("source_mode", "")

        # Skip if manifest exists AND source_mode is upload/unset
        if tc.config.get("manifest") and source_mode in ("upload", ""):
            continue

        # Project folder upload: parse files dict
        if source_mode == "project" and tc.config.get("project_files"):
            try:
                project_files = tc.config["project_files"]
                if isinstance(project_files, dict):
                    manifest = parse_dbt_project(
                        files=project_files,
                        project_name=tc.config.get("project_name", ""),
                        default_database=warehouse_database,
                        warehouse_type=tc.config.get("warehouse_type", "bigquery"),
                    )
                    if manifest and (manifest.get("nodes") or manifest.get("sources")):
                        tc.config["manifest"] = manifest
                        _log.info(f"[dbt-preprocess] Parsed project files: {len(manifest.get('nodes', {}))} models")
            except Exception as parse_err:
                _log.warning(f"[dbt-preprocess] Project files parsing failed: {parse_err}")

        # GitHub mode: fetch project files with manifest.json fallback
        elif source_mode == "github":
            github_token = tc.config.get("github", {}).get("token") or tc.config.get("github_token") or _resolve_github_token_from_tool_configs(tool_configs)
            github_repo = tc.config.get("github_repo")
            if github_token and github_repo:
                try:
                    project_files, fallback_manifest = await fetch_dbt_project_files_with_fallback(
                        repo=github_repo,
                        token=github_token,
                        branch=tc.config.get("github_branch", "main"),
                        dbt_root=tc.config.get("dbt_project_path", ""),
                    )
                    if project_files:
                        manifest = parse_dbt_project(
                            files=project_files,
                            project_name=tc.config.get("project_name", ""),
                            default_database=warehouse_database,
                            warehouse_type=tc.config.get("warehouse_type", "bigquery"),
                        )
                        if manifest and (manifest.get("nodes") or manifest.get("sources")):
                            tc.config["manifest"] = manifest
                            _log.info(f"[dbt-preprocess] Parsed from GitHub: {github_repo} ({len(manifest.get('nodes', {}))} models)")
                    elif fallback_manifest:
                        tc.config["manifest"] = fallback_manifest
                        _log.info(f"[dbt-preprocess] Using manifest.json fallback from GitHub: {github_repo}")
                except Exception as gh_err:
                    _log.warning(f"[dbt-preprocess] GitHub fetch failed: {gh_err}")


async def _fetch_dag_files_from_github(
    repo: str, token: str, branch: str, dag_directory: str
) -> Dict[str, str]:
    """Fetch .py DAG files from a GitHub repo directory."""
    import aiohttp
    import base64

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_base = "https://api.github.com"

    dag_files: Dict[str, str] = {}

    async with aiohttp.ClientSession() as session:
        # List files in the DAG directory
        list_url = f"{api_base}/repos/{repo}/contents/{dag_directory}?ref={branch}"
        async with session.get(list_url, headers=headers) as resp:
            if resp.status == 404:
                # Directory doesn't exist — no DAGs in this repo
                return {}
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"GitHub API error listing {dag_directory}: {resp.status} {error_text}")
            items = await resp.json()

        # Filter to .py files
        py_files = [item for item in items if item.get("name", "").endswith(".py") and item.get("type") == "file"]

        # Fetch each file's content
        for item in py_files:
            file_url = f"{api_base}/repos/{repo}/contents/{item['path']}?ref={branch}"
            async with session.get(file_url, headers=headers) as resp:
                if resp.status != 200:
                    continue
                file_data = await resp.json()
                content_b64 = file_data.get("content", "")
                content = base64.b64decode(content_b64).decode("utf-8")
                dag_files[item["name"]] = content

    return dag_files


async def _preprocess_airflow_configs(tool_configs, logger_instance=None) -> None:
    """Fetch DAG files from GitHub for Airflow configs in-place.

    When Airflow is connected via GitHub (static mode), the config contains
    github.repo / github.token but NOT the actual dag_files.  This function
    fetches the .py DAG files from the repo and injects them into the config
    so LiveAirflowAdapter receives them.
    """
    import logging
    _log = logger_instance or logging.getLogger(__name__)

    for tc in tool_configs:
        tool_type = (tc.tool_type if hasattr(tc, "tool_type") else "").lower()
        if tool_type != "airflow":
            continue

        cfg = tc.config if hasattr(tc, "config") else {}
        _log.info("[airflow-preprocess] Airflow config keys: %s", list(cfg.keys()))

        # Skip if dag_files already populated
        if cfg.get("dag_files"):
            _log.info("[airflow-preprocess] dag_files already present, skipping")
            continue

        # Determine mode: source_mode takes priority over host detection.
        # Config may have BOTH host (API) and github_repo (GitHub) keys —
        # source_mode tells us which the user actually chose.
        source_mode = (cfg.get("source_mode") or "").lower()
        base_url = cfg.get("base_url") or cfg.get("host") or cfg.get("url")

        if source_mode == "api" or (base_url and source_mode not in ("github", "static")):
            _log.info("[airflow-preprocess] API mode (source_mode=%s, base_url=%s), skipping", source_mode, base_url)
            continue  # API mode — no preprocessing needed

        # Fetch from GitHub — check multiple config shapes
        github_config = cfg.get("github") or {}
        github_repo = (
            github_config.get("repo")
            or cfg.get("github_repo")
            or cfg.get("repo")
        )
        github_token = (
            github_config.get("token")
            or cfg.get("github_token")
            or cfg.get("token")
            or _resolve_github_token_from_tool_configs(tool_configs)
        )

        if not github_repo or not github_token:
            _log.warning(
                "[airflow-preprocess] No GitHub credentials found. "
                "Config has github=%s, github_repo=%s, repo=%s. "
                "Airflow needs either github.repo+token, github_repo+github_token, or API mode.",
                bool(github_config), bool(cfg.get("github_repo")), bool(cfg.get("repo")),
            )
            continue

        if github_repo and github_token:
            dag_directory = (
                cfg.get("dag_directory")
                or github_config.get("dag_directory", "dags")
            )
            branch = github_config.get("branch") or cfg.get("github_branch", "main")
            try:
                dag_files = await _fetch_dag_files_from_github(
                    repo=github_repo,
                    token=github_token,
                    branch=branch,
                    dag_directory=dag_directory,
                )
                if dag_files:
                    cfg["dag_files"] = dag_files
                    _log.info(
                        "[airflow-preprocess] Fetched %d DAG files from GitHub %s/%s",
                        len(dag_files), github_repo, dag_directory,
                    )
                else:
                    _log.warning(
                        "[airflow-preprocess] No .py files found in %s/%s",
                        github_repo, dag_directory,
                    )
            except Exception as gh_err:
                _log.warning("[airflow-preprocess] GitHub DAG fetch failed: %s", gh_err)


def _derive_cp_metadata(tc_layer: str, tc_config: dict, all_tool_configs: list) -> dict:
    """Derive control-plane relationship metadata from a tool's config.

    This is a thin passthrough for config-specified values. The primary CP
    metadata is emitted by drivers directly on graph nodes. This function
    handles the remaining relational cases:
      - VCS managed_tools (injected by frontend)
      - Infrastructure host-matching (cross-tool hostname comparison)
    """
    import logging
    _enrich_log = logging.getLogger(__name__)

    raw_meta: dict = {}
    layer = (tc_layer or "").upper()

    if layer == "VERSION_CONTROL" and tc_config:
        # Frontend injects managed_tools based on which tools have GitHub
        # attachments — pass through to the driver config.
        managed = tc_config.get("managed_tools")
        if isinstance(managed, list) and managed:
            raw_meta["managed_repos"] = [t.lower() for t in managed]

    if layer == "INFRASTRUCTURE" and tc_config:
        # Pass through explicit hosted_tools from config (Linux driver also
        # reads these, but this path covers non-driver code paths).
        for key in ("hosted_tools", "hosted_platforms", "managed_services", "hosted_services"):
            vals = tc_config.get(key)
            if isinstance(vals, list) and vals:
                raw_meta["hosted_platforms"] = vals
                break
        # Fallback: cross-tool host matching
        if "hosted_platforms" not in raw_meta:
            infra_host = (tc_config.get("hostname") or tc_config.get("host") or "").lower()
            if infra_host:
                hosted = []
                for other_tc in all_tool_configs:
                    if other_tc.tool_type.lower() == tc_config.get("_self_tool_type", ""):
                        continue
                    other_cfg = other_tc.config or {}
                    other_host = (
                        other_cfg.get("host") or other_cfg.get("hostname")
                        or other_cfg.get("server") or ""
                    ).lower()
                    if other_host and (other_host == infra_host or infra_host in other_host or other_host in infra_host):
                        hosted.append(other_tc.tool_type.lower())
                if hosted:
                    raw_meta["hosted_platforms"] = hosted

    if raw_meta:
        _enrich_log.info("[CP-Enrich] layer=%s → metadata=%s", layer, raw_meta)

    return raw_meta



class InvestigateLLMRequest(BaseModel):
    """Request to run LLM-enhanced investigation."""
    tool_configs: List[InvestigateToolConfig]
    use_llm_planner: bool = True
    use_llm_reconciler: bool = True
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    pipeline_edges: Optional[List[Dict[str, Any]]] = None


@router.post("/lineage/investigate-llm", response_model=InvestigateResponse)
async def investigate_lineage_llm(
    request: InvestigateLLMRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    Run LLM-enhanced lineage investigation.

    Extends the standard investigation with:
    1. LLM planner determines optimal adapter execution order
    2. Deterministic bridge rules fix structural gaps (raw tables as sources)
    3. LLM reconciler reviews and patches the graph

    Falls back to heuristic ordering and deterministic bridge rules
    if LLM calls fail.
    """
    import logging
    _logger = logging.getLogger(__name__)
    org_id = principal.organization_id

    try:
        try:
            from lineage.engine.investigator import ToolConfig
        except ImportError:
            from scanner.lineage.engine.investigator import ToolConfig

        # Pre-process tool configs that need GitHub/remote file fetching
        await _preprocess_dbt_configs(request.tool_configs, _logger)
        await _preprocess_airflow_configs(request.tool_configs, _logger)

        tool_configs = [
            ToolConfig(
                tool_type=tc.tool_type,
                config=tc.config,
                integration_id=tc.integration_id,
                layer=tc.layer,
                adapter_type=tc.adapter_type,
            )
            for tc in request.tool_configs
        ]

        # Run the full extraction pipeline with LLM planner + reconciler
        try:
            from lineage.engine.pipeline import run_extraction_pipeline, ExtractionPipelineConfig
        except ImportError:
            from scanner.lineage.engine.pipeline import run_extraction_pipeline, ExtractionPipelineConfig

        registry = _get_run_registry(org_id, stack_id)
        store = _get_engine_store(org_id, stack_id)

        # Build tool_nodes list so Pipeline Overview shows ALL integrated tools
        _VCS_TOOL_TYPES_LLM = {"github", "gitlab", "bitbucket"}
        _tool_nodes = []
        for tc in request.tool_configs:
            tn: dict = {
                "tool_type": tc.tool_type,
                "integration_id": tc.integration_id or "",
                "name": tc.tool_type.replace("_", " ").title(),
                "layer": tc.layer or "",
            }
            # Include safe metadata for VCS/control-plane tools (no secrets)
            if tc.tool_type.lower() in _VCS_TOOL_TYPES_LLM and tc.config:
                tn["config"] = {
                    "owner": tc.config.get("owner") or tc.config.get("org", ""),
                    "repo": tc.config.get("repo", ""),
                    "repos": tc.config.get("repos") or tc.config.get("repositories", []),
                    "org": tc.config.get("owner") or tc.config.get("org", ""),
                }

            # Derive relationship metadata from config (evidence for CP edges)
            cfg_for_meta = dict(tc.config or {})
            cfg_for_meta["_self_tool_type"] = tc.tool_type.lower()
            raw_meta = _derive_cp_metadata(tc.layer or "", cfg_for_meta, request.tool_configs)
            if raw_meta:
                tn["raw_metadata"] = raw_meta

            _tool_nodes.append(tn)

        # Resolve LLM API key from environment based on provider
        import os
        _llm_key = os.environ.get(
            "OPENAI_API_KEY" if request.llm_provider == "openai" else "ANTHROPIC_API_KEY"
        )
        _pipeline_edges = request.pipeline_edges or []
        pipeline_config = ExtractionPipelineConfig(
            use_llm_planner=request.use_llm_planner,
            use_llm_reconciler=request.use_llm_reconciler,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
            llm_api_key=_llm_key,
            tool_nodes=_tool_nodes,
            pipeline_edges=_pipeline_edges,
        )

        run_id = await run_extraction_pipeline(tool_configs, registry, store, pipeline_config)
        store.tool_nodes = _tool_nodes
        store.pipeline_edges = _pipeline_edges

        # Cache tool configs for on-demand SLA discovery
        _lineage_cache.set_tool_configs(
            org_id,
            stack_id,
            {tc.tool_type: tc.config for tc in request.tool_configs if tc.config},
        )

        # Build response from run record
        record = registry.get_run(run_id)
        if not record or record.status.value == "failed":
            return InvestigateResponse(
                success=False,
                errors=record.errors if record else ["Pipeline failed"],
            )

        nodes_resp = []
        edges_resp = []
        if store.graph:
            nodes_resp = [_node_to_engine_response(n) for n in store.graph.nodes.values()]
            edges_resp = [_edge_to_engine_response(e) for e in store.graph.edges.values()]

        stats = {**record.artifacts.stats}
        stats["run_id"] = run_id

        _logger.info(
            f"[Investigator-LLM] Complete: run_id={run_id}, "
            f"{len(nodes_resp)} nodes, {len(edges_resp)} edges, "
            f"{record.duration_ms}ms"
        )

        return InvestigateResponse(
            success=True,
            nodes=nodes_resp,
            edges=edges_resp,
            investigation=stats,
            stats=stats,
            errors=record.errors,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return InvestigateResponse(
            success=False,
            errors=[str(e)],
        )


# ---------------------------------------------------------------------------
# LLM-Powered Extraction (SSE streaming)
# ---------------------------------------------------------------------------


class LLMExtractRequest(BaseModel):
    """Request for LLM-powered lineage extraction."""
    tool_configs: List[InvestigateToolConfig]
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    tool_nodes: Optional[List[Dict[str, Any]]] = None
    pipeline_edges: Optional[List[Dict[str, Any]]] = None


@router.post("/lineage/extract-llm")
async def extract_lineage_with_llm(
    request: LLMExtractRequest,
    stack_id: Optional[str] = Query(None),
    principal: ActingPrincipal = Depends(require_principal),
):
    """
    LLM-powered lineage extraction with SSE streaming progress.

    The LLM acts as an agent that queries each integration via tools,
    reasons about data flow, and builds the lineage graph itself.
    Returns a stream of SSE events showing real-time progress.
    """
    import logging
    _logger = logging.getLogger(__name__)
    org_id = principal.organization_id

    async def event_stream():
        try:
            try:
                from lineage.engine.investigator import ToolConfig
                from lineage.engine.llm_extractor import LLMExtractorConfig, LLMLineageExtractor
            except ImportError:
                from scanner.lineage.engine.investigator import ToolConfig
                from scanner.lineage.engine.llm_extractor import LLMExtractorConfig, LLMLineageExtractor

            # Pre-process tool configs that need GitHub/remote file fetching
            await _preprocess_dbt_configs(request.tool_configs, _logger)
            await _preprocess_airflow_configs(request.tool_configs, _logger)

            # Build ToolConfig list
            tool_configs = [
                ToolConfig(
                    tool_type=tc.tool_type,
                    config=tc.config,
                    integration_id=tc.integration_id,
                    layer=tc.layer,
                    adapter_type=tc.adapter_type,
                )
                for tc in request.tool_configs
            ]

            # Create extractor
            extractor_config = LLMExtractorConfig(
                provider=request.llm_provider,
                model=request.llm_model,
            )
            extractor = LLMLineageExtractor(extractor_config)

            # Stream extraction events
            graph = None
            views = None
            async for event in extractor.extract(tool_configs, request.tool_nodes or []):
                yield event.to_sse()

                # Capture final graph/views from complete event
                if event.event_type == "complete":
                    graph = event.data.get("graph")
                    views = event.data.get("views")

            # After extraction, persist to registry + store
            if graph:
                try:
                    from scanner.lineage.engine.run_registry import RunArtifacts
                except ImportError:
                    from lineage.engine.run_registry import RunArtifacts

                registry = _get_run_registry(org_id, stack_id)
                store = _get_engine_store(org_id, stack_id)

                run_id = registry.start_run(
                    [tc.tool_type for tc in request.tool_configs]
                )
                artifacts = RunArtifacts(
                    graph_dict=graph,
                    views=views or {},
                    stats={
                        "total_nodes": graph.get("stats", {}).get("node_count", 0),
                        "total_edges": graph.get("stats", {}).get("edge_count", 0),
                        "extraction_mode": "llm",
                        "run_id": run_id,
                        "views_built": list((views or {}).keys()),
                    },
                )
                registry.complete_run(run_id, artifacts)

                # Update store for backward compat
                try:
                    from scanner.lineage.graph import LineageGraph
                except ImportError:
                    from lineage.graph import LineageGraph
                store.graph = LineageGraph.from_dict(graph)
                store.tool_nodes = request.tool_nodes or []
                store.pipeline_edges = request.pipeline_edges or []

                import json
                yield f"data: {json.dumps({'type': 'persisted', 'data': {'run_id': run_id}})}\n\n"

                _logger.info(f"[LLM-Extract] Persisted run_id={run_id}")

        except Exception as e:
            import json
            import traceback
            traceback.print_exc()
            _logger.error(f"[LLM-Extract] Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
