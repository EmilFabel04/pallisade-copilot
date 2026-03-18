"""
Pipeline Monitoring Policies API Router.

CRUD for PolicyProfiles and PolicyAssignments, plus policy resolution endpoints.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .lineage import _get_engine_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/policies")


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class PolicyProfileCreate(BaseModel):
    """Create a new policy profile."""
    name: str
    description: Optional[str] = None
    targetDomain: Optional[str] = None
    criticality: Optional[str] = None
    freshnessConfig: Optional[Dict[str, Any]] = None
    schemaConfig: Optional[Dict[str, Any]] = None
    volumeConfig: Optional[Dict[str, Any]] = None
    anomalyConfig: Optional[Dict[str, Any]] = None
    qualityConfig: Optional[Dict[str, Any]] = None
    ingestionConfig: Optional[Dict[str, Any]] = None
    biConfig: Optional[Dict[str, Any]] = None
    orchestrationConfig: Optional[Dict[str, Any]] = None
    transformConfig: Optional[Dict[str, Any]] = None


class PolicyProfileUpdate(BaseModel):
    """Update an existing policy profile."""
    name: Optional[str] = None
    description: Optional[str] = None
    targetDomain: Optional[str] = None
    criticality: Optional[str] = None
    freshnessConfig: Optional[Dict[str, Any]] = None
    schemaConfig: Optional[Dict[str, Any]] = None
    volumeConfig: Optional[Dict[str, Any]] = None
    anomalyConfig: Optional[Dict[str, Any]] = None
    qualityConfig: Optional[Dict[str, Any]] = None
    ingestionConfig: Optional[Dict[str, Any]] = None
    biConfig: Optional[Dict[str, Any]] = None
    orchestrationConfig: Optional[Dict[str, Any]] = None
    transformConfig: Optional[Dict[str, Any]] = None


class PolicyAssignRequest(BaseModel):
    """Assign a policy profile to one or more nodes."""
    profileId: str
    assignmentType: str = Field(..., description="direct | branch | domain_default | criticality_default")
    # For direct assignments
    nodeFqns: Optional[List[str]] = None
    # For branch assignment
    branchRootFqn: Optional[str] = None
    # For domain/criticality defaults
    nodeDomain: Optional[str] = None
    nodeCriticality: Optional[str] = None
    # Per-asset overrides
    overrides: Optional[Dict[str, Any]] = None


class PolicyResolveRequest(BaseModel):
    """Request to resolve effective policies for nodes."""
    model_config = {"populate_by_name": True}

    nodes: List[Dict[str, Any]] = Field(
        ...,
        description="List of {fqn, domain, criticality} dicts",
    )
    stackId: Optional[str] = None
    # DB data passed from Next.js proxy (avoids FastAPI needing DB access)
    db_assignments: Optional[List[Dict[str, Any]]] = Field(None, alias="_assignments")
    db_profiles: Optional[Dict[str, Any]] = Field(None, alias="_profiles")


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------

@router.get("/profiles")
async def list_profiles(
    organization_id: str = Query(..., alias="organizationId"),
):
    """List all policy profiles (built-in + custom) for an organization."""
    try:
        from scanner.monitors.policy_resolver import BUILTIN_PROFILES
    except ImportError:
        from monitors.policy_resolver import BUILTIN_PROFILES

    # Return built-in profiles with synthetic IDs
    profiles = []
    for name, config in BUILTIN_PROFILES.items():
        profiles.append({
            "id": f"builtin_{name.lower().replace(' ', '_')}",
            "name": name,
            "description": config.get("description", ""),
            "isBuiltIn": True,
            "targetDomain": config.get("targetDomain"),
            "criticality": config.get("criticality"),
            "freshnessConfig": config.get("freshnessConfig"),
            "schemaConfig": config.get("schemaConfig"),
            "volumeConfig": config.get("volumeConfig"),
            "anomalyConfig": config.get("anomalyConfig"),
            "qualityConfig": config.get("qualityConfig"),
            "ingestionConfig": config.get("ingestionConfig"),
            "biConfig": config.get("biConfig"),
            "orchestrationConfig": config.get("orchestrationConfig"),
            "transformConfig": config.get("transformConfig"),
        })

    # TODO: Query DB for custom profiles when Prisma is accessible from Python
    # For now, built-in profiles are sufficient for MVP

    return {"profiles": profiles}


@router.get("/profiles/builtins")
async def list_builtin_profiles():
    """List built-in profile definitions."""
    try:
        from scanner.monitors.policy_resolver import BUILTIN_PROFILES
    except ImportError:
        from monitors.policy_resolver import BUILTIN_PROFILES

    return {"profiles": BUILTIN_PROFILES}


# ---------------------------------------------------------------------------
# Assignment endpoints
# ---------------------------------------------------------------------------

@router.post("/assign")
async def assign_policy(
    request: PolicyAssignRequest,
    organization_id: str = Query(..., alias="organizationId"),
):
    """
    Assign a policy profile to nodes.

    Supports:
    - direct: assigns to specific nodes by FQN
    - branch: assigns to all downstream of a root node
    - domain_default: sets default for an entire domain
    - criticality_default: sets default for a domain + criticality pair
    """
    if request.assignmentType == "direct":
        if not request.nodeFqns:
            raise HTTPException(400, "nodeFqns required for direct assignments")

        assignments = []
        for fqn in request.nodeFqns:
            assignments.append({
                "profileId": request.profileId,
                "assignmentType": "direct",
                "nodeFqn": fqn,
                "overrides": request.overrides,
                "organizationId": organization_id,
            })
        # TODO: Upsert via Prisma — for now, return the planned assignments
        return {
            "created": len(assignments),
            "assignments": assignments,
            "message": f"Assigned policy to {len(assignments)} node(s)",
        }

    elif request.assignmentType == "branch":
        if not request.branchRootFqn:
            raise HTTPException(400, "branchRootFqn required for branch assignments")
        assignment = {
            "profileId": request.profileId,
            "assignmentType": "branch",
            "branchRootFqn": request.branchRootFqn,
            "overrides": request.overrides,
            "organizationId": organization_id,
        }
        return {
            "created": 1,
            "assignments": [assignment],
            "message": f"Branch policy assigned from {request.branchRootFqn}",
        }

    elif request.assignmentType == "domain_default":
        if not request.nodeDomain:
            raise HTTPException(400, "nodeDomain required for domain_default assignments")
        assignment = {
            "profileId": request.profileId,
            "assignmentType": "domain_default",
            "nodeDomain": request.nodeDomain,
            "organizationId": organization_id,
        }
        return {
            "created": 1,
            "assignments": [assignment],
            "message": f"Domain default set for {request.nodeDomain}",
        }

    elif request.assignmentType == "criticality_default":
        if not request.nodeDomain or not request.nodeCriticality:
            raise HTTPException(400, "nodeDomain and nodeCriticality required for criticality_default")
        assignment = {
            "profileId": request.profileId,
            "assignmentType": "criticality_default",
            "nodeDomain": request.nodeDomain,
            "nodeCriticality": request.nodeCriticality,
            "organizationId": organization_id,
        }
        return {
            "created": 1,
            "assignments": [assignment],
            "message": f"Criticality default set for {request.nodeDomain}/{request.nodeCriticality}",
        }

    else:
        raise HTTPException(400, f"Unknown assignmentType: {request.assignmentType}")


@router.delete("/assignments/{assignment_id}")
async def delete_assignment(
    assignment_id: str,
    organization_id: str = Query(..., alias="organizationId"),
):
    """Delete a policy assignment."""
    # TODO: Delete via Prisma
    return {"deleted": assignment_id}


# ---------------------------------------------------------------------------
# Resolution endpoints
# ---------------------------------------------------------------------------

@router.post("/resolve")
async def resolve_policies(request: PolicyResolveRequest):
    """
    Resolve effective policies for multiple nodes.

    Returns the effective policy + source for each node FQN.
    """
    try:
        from scanner.monitors.policy_resolver import (
            resolve_policies_bulk,
            get_policy_status,
            BUILTIN_PROFILES,
            _extract_all_fields_from_profile,
        )
    except ImportError:
        from monitors.policy_resolver import (
            resolve_policies_bulk,
            get_policy_status,
            BUILTIN_PROFILES,
            _extract_all_fields_from_profile,
        )

    # Get graph for branch resolution
    graph = None
    if request.stackId:
        store = _get_engine_store(request.stackId)
        graph = store.graph

    # Use DB data if passed from Next.js proxy, otherwise fall back to builtins
    assignments: List[Dict[str, Any]] = request.db_assignments or []
    profiles: Dict[str, Dict[str, Any]] = request.db_profiles or {}

    # Always include built-in profiles as fallback
    for name, config in BUILTIN_PROFILES.items():
        pid = f"builtin_{name.lower().replace(' ', '_')}"
        if pid not in profiles:
            profiles[pid] = {"name": name, **config}

    # Resolve
    resolved = resolve_policies_bulk(
        nodes=request.nodes,
        assignments=assignments,
        profiles=profiles,
        graph=graph,
    )

    # Format response
    result = {}
    for fqn, policy in resolved.items():
        status = get_policy_status(fqn, assignments, graph)
        result[fqn] = {
            "source": policy.source,
            "profileId": policy.profile_id,
            "profileName": policy.profile_name,
            "status": status,
            "freshness": {
                "enabled": policy.freshness_enabled,
                "maxHours": policy.freshness_max_hours,
                "warningHours": policy.freshness_warning_hours,
            },
            "schema": {
                "enabled": policy.schema_enabled,
                "strictness": policy.schema_strictness,
                "allowEvolution": policy.schema_allow_evolution,
            },
            "volume": {
                "enabled": policy.volume_enabled,
                "minRows": policy.volume_min_rows,
                "maxRows": policy.volume_max_rows,
                "growthThreshold": policy.volume_growth_threshold,
            },
            "anomaly": {
                "enabled": policy.anomaly_enabled,
                "sensitivity": policy.anomaly_sensitivity,
                "lookbackDays": policy.anomaly_lookback_days,
            },
            "quality": {
                "enabled": policy.quality_enabled,
                "maxNullRate": policy.quality_max_null_rate,
                "maxDuplicateRate": policy.quality_max_duplicate_rate,
            },
            "ingestion": {
                "syncLagToleranceMinutes": policy.sync_lag_tolerance_minutes,
                "failureTolerance": policy.failure_tolerance,
                "schemaDriftStrictness": policy.schema_drift_strictness,
            },
            "bi": {
                "freshnessHours": policy.bi_freshness_hours,
                "contentHealthEnabled": policy.content_health_enabled,
                "upstreamBreakStrictness": policy.upstream_break_strictness,
            },
            "orchestration": {
                "runLatencyMinutes": policy.run_latency_minutes,
                "scheduleLagMinutes": policy.schedule_lag_minutes,
                "failureTolerance": policy.orch_failure_tolerance,
            },
            "transform": {
                "testFailureTolerance": policy.test_failure_tolerance,
                "modelFreshnessHours": policy.model_freshness_hours,
            },
        }

    return {"policies": result}


@router.get("/coverage")
async def policy_coverage(
    stack_id: str = Query(..., alias="stackId"),
    organization_id: str = Query(..., alias="organizationId"),
):
    """Get policy coverage stats: how many nodes have explicit policies vs defaults."""
    store = _get_engine_store(stack_id)
    if not store.graph:
        return {"totalNodes": 0, "withPolicy": 0, "withoutPolicy": 0, "coveragePct": 0}

    total = len(store.graph.nodes)
    # TODO: Query assignments from DB to compute real coverage
    return {
        "totalNodes": total,
        "withPolicy": 0,
        "withoutPolicy": total,
        "coveragePct": 0.0,
    }
