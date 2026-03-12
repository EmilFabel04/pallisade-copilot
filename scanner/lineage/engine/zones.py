"""
Zone & Lane Classification for Pipeline Overview

Computes view-layer attributes for the lane-based Pipeline Overview:
  - dataset_zone: raw | staging | intermediate | mart | analytics | unknown
  - capability:   ingestion | transformation | orchestration | reporting | infra

These are COMPUTED attributes for view positioning — they do NOT replace
canonical node types (system/service/job/dataset/semantic).

Lane ordering (left → right):
  ingestion → warehouse_raw → transformation → warehouse_analytics → reporting
"""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING, Dict, Optional

from ..graph import LineageNode, PlatformDomain, NodeType

if TYPE_CHECKING:
    from .landing_zone import LandingZoneProfile
from .platforms import (
    INGESTION_PLATFORMS,
    TRANSFORM_PLATFORMS,
    ORCHESTRATION_PLATFORMS,
    REPORTING_PLATFORMS,
    WAREHOUSE_PLATFORMS,
    INFRA_PLATFORMS,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DatasetZone(Enum):
    """Classification of a dataset's position in the data lifecycle."""
    RAW = "raw"
    STAGING = "staging"
    INTERMEDIATE = "intermediate"
    MART = "mart"
    ANALYTICS = "analytics"
    UNKNOWN = "unknown"


class ActorCapability(Enum):
    """What role an actor (service/job) plays in the pipeline."""
    INGESTION = "ingestion"
    TRANSFORMATION = "transformation"
    ORCHESTRATION = "orchestration"
    REPORTING = "reporting"
    INFRA = "infra"
    QUALITY = "quality"


class FunctionalRole(Enum):
    """Node-level functional role combining canonical type, zone, and capability.

    More specific than platform category — captures what a node actually does
    in the pipeline regardless of which platform hosts it.
    """
    WAREHOUSE_RAW = "warehouse_raw"
    WAREHOUSE_ANALYTICS = "warehouse_analytics"
    TRANSFORMATION = "transformation"
    ORCHESTRATION = "orchestration"
    INGESTION = "ingestion"
    REPORTING = "reporting"
    QUALITY = "quality"
    VERSION_CONTROL = "version_control"
    INFRASTRUCTURE = "infrastructure"
    SEMANTIC = "semantic"
    JOB_RUNTIME = "job_runtime"


_FUNCTIONAL_ROLE_VALUES = frozenset(r.value for r in FunctionalRole)


class PipelineLane(Enum):
    """Fixed lanes for the Pipeline Overview view (left → right)."""
    INGESTION = "ingestion"
    WAREHOUSE_RAW = "warehouse_raw"
    TRANSFORMATION = "transformation"
    WAREHOUSE_ANALYTICS = "warehouse_analytics"
    REPORTING = "reporting"


LANE_ORDER: Dict[str, int] = {
    PipelineLane.INGESTION.value: 0,
    PipelineLane.WAREHOUSE_RAW.value: 1,
    PipelineLane.TRANSFORMATION.value: 2,
    PipelineLane.WAREHOUSE_ANALYTICS.value: 3,
    PipelineLane.REPORTING.value: 4,
}


# Platform sets are re-exported from platforms.py (single source of truth).
# Import above: INGESTION_PLATFORMS, TRANSFORM_PLATFORMS, etc.


# ---------------------------------------------------------------------------
# Dataset zone classification
# ---------------------------------------------------------------------------

# Patterns for classifying datasets by schema/name conventions
_RAW_PATTERNS = [
    r"\braw\b", r"\blanding\b", r"\bstage_raw\b", r"\bsource\b",
    r"\bextract\b", r"\bload\b", r"\bingested\b",
    # Medallion architecture (Databricks / Delta Lake)
    r"\bbronze\b",
]

_STAGING_PATTERNS = [
    r"\bstg\b", r"\bstaging\b", r"\bstg_\w+",
    r"_staging\b",  # compound: analytics_staging
    # Medallion architecture
    r"\bsilver\b",
    # Alternative naming
    r"\bclean\b", r"\bcleansed\b",
]

_INTERMEDIATE_PATTERNS = [
    r"\bint\b", r"\bintermediate\b", r"\bint_\w+",
    r"_intermediate\b",  # compound: analytics_intermediate
    # Alternative naming
    r"\brefined\b", r"\bcurated\b",
]

_MART_PATTERNS = [
    r"\bmart\b", r"\bmarts\b", r"\bfct_\w+", r"\bdim_\w+",
    r"\bfact_\w+", r"\bdimension_\w+",
    r"_marts?\b",  # compound: analytics_mart, analytics_marts
    # Medallion architecture
    r"\bgold\b",
    # Alternative naming
    r"\bpresentation\b", r"\bconsumption\b", r"\bdwh\b",
    r"\bdata_warehouse\b", r"\bserving\b",
]

_ANALYTICS_PATTERNS = [
    r"\banalytics\b", r"\breporting\b", r"\bagg_\w+",
    r"\bmetrics\b", r"\bkpi\b",
]


def classify_dataset_zone(
    node: LineageNode,
    landing_zone_profile: Optional[LandingZoneProfile] = None,
) -> DatasetZone:
    """
    Classify a dataset node into a zone based on naming conventions,
    schema name, and metadata.

    Priority order:
    0. Explicit zone hint
    1. dbt resource type (source/seed → RAW)
    1.5. Landing zone profile (ingestion landing container → RAW)
    2. dbt model path patterns
    3. Schema/name regex patterns
    4. Default based on platform domain
    """
    # 0. Explicit zone hint (from LLM or enrichment)
    zone_hint = node.raw_metadata.get("zone", "")
    if zone_hint and zone_hint in {z.value for z in DatasetZone}:
        return DatasetZone(zone_hint)

    # 1. Check dbt resource type metadata
    dbt_type = node.raw_metadata.get("dbt_resource_type", "")
    if dbt_type == "source":
        return DatasetZone.RAW
    if dbt_type == "seed":
        return DatasetZone.RAW

    # 1.5. Landing zone profile: if this node's container is a known
    # ingestion landing zone, classify as RAW regardless of schema name.
    if landing_zone_profile and node.schema:
        is_landing, confidence = landing_zone_profile.is_landing_container(
            node.database or "", node.schema,
        )
        if is_landing and confidence >= 0.7:
            return DatasetZone.RAW

    # Check dbt model path for stg/int/mart patterns
    dbt_path = node.raw_metadata.get("dbt_path", "") or node.raw_metadata.get("path", "")
    if dbt_path:
        path_lower = dbt_path.lower()
        if "/staging/" in path_lower or "/stg/" in path_lower:
            return DatasetZone.STAGING
        if "/intermediate/" in path_lower or "/int/" in path_lower:
            return DatasetZone.INTERMEDIATE
        if "/mart" in path_lower or "/fct/" in path_lower or "/dim/" in path_lower:
            return DatasetZone.MART

    # 2. Schema name patterns
    schema_lower = (node.schema or "").lower()
    name_lower = node.name.lower()
    fqn_lower = (node.fqn or "").lower()
    # Combine for pattern matching
    search_text = f"{schema_lower} {name_lower} {fqn_lower}"

    for pattern in _RAW_PATTERNS:
        if re.search(pattern, search_text):
            return DatasetZone.RAW
    for pattern in _STAGING_PATTERNS:
        if re.search(pattern, search_text):
            return DatasetZone.STAGING
    for pattern in _INTERMEDIATE_PATTERNS:
        if re.search(pattern, search_text):
            return DatasetZone.INTERMEDIATE
    for pattern in _MART_PATTERNS:
        if re.search(pattern, search_text):
            return DatasetZone.MART
    for pattern in _ANALYTICS_PATTERNS:
        if re.search(pattern, search_text):
            return DatasetZone.ANALYTICS

    # 3. Default: if discovered only by warehouse (no dbt), assume raw
    if node.platform_domain == PlatformDomain.WAREHOUSE:
        sources = set(node.sources) if hasattr(node, "sources") else set()
        has_transform_source = bool(sources & TRANSFORM_PLATFORMS)
        if not has_transform_source and dbt_type not in ("model",):
            return DatasetZone.RAW

    # 4. If produced by dbt but no clear naming convention, default analytics
    if dbt_type == "model":
        return DatasetZone.ANALYTICS

    return DatasetZone.UNKNOWN


# ---------------------------------------------------------------------------
# Data-plane layer classification (for semantic layout)
# ---------------------------------------------------------------------------

class DataPlaneLayer(Enum):
    """Semantic layers for the data-plane view (left → right)."""
    INGESTION = 0       # n8n, Fivetran, Airbyte connectors
    RAW = 1             # Raw/landing tables
    STAGING = 2         # dbt staging models, stg_ schemas
    INTERMEDIATE = 3    # dbt intermediate models
    MART = 4            # dbt marts, dim_/fct_ tables, analytics
    SERVING = 5         # Leaf dataset nodes (no downstream data edges)
    REPORTING = 6       # Dashboards, reports, BI objects


_ZONE_TO_LAYER = {
    DatasetZone.RAW: DataPlaneLayer.RAW.value,
    DatasetZone.STAGING: DataPlaneLayer.STAGING.value,
    DatasetZone.INTERMEDIATE: DataPlaneLayer.INTERMEDIATE.value,
    DatasetZone.MART: DataPlaneLayer.MART.value,
    DatasetZone.ANALYTICS: DataPlaneLayer.MART.value,
}


def classify_data_plane_layer(
    node: LineageNode,
    canonical_type: str,
    has_downstream_data_edges: bool = True,
) -> int:
    """
    Classify a node into a semantic data-plane layer for layout.

    Uses metadata signals in priority order:
    1. Canonical type (semantic → REPORTING)
    2. Platform domain (ingestion → INGESTION, BI → REPORTING)
    3. Existing classify_dataset_zone() for datasets
    4. Graph position (leaf nodes → SERVING)

    Returns an integer layer index (0-6).
    """
    # Semantic nodes (dashboards, reports) → REPORTING
    if canonical_type == "semantic":
        return DataPlaneLayer.REPORTING.value

    # Ingestion platforms → INGESTION (but NOT destination tables in warehouses)
    platform = (node.platform or "").lower()
    if (platform in INGESTION_PLATFORMS and node.platform_domain != PlatformDomain.WAREHOUSE) or node.platform_domain == PlatformDomain.INGESTION:
        return DataPlaneLayer.INGESTION.value

    # BI platforms → REPORTING
    if node.platform_domain == PlatformDomain.BI:
        return DataPlaneLayer.REPORTING.value

    # Dataset nodes: classify by zone
    if canonical_type == "dataset":
        zone = classify_dataset_zone(node)
        layer = _ZONE_TO_LAYER.get(zone)
        if layer is not None:
            return layer

        # UNKNOWN zone — additional heuristics
        dbt_type = node.raw_metadata.get("dbt_resource_type", "")
        if dbt_type == "model":
            return DataPlaneLayer.MART.value

        if not has_downstream_data_edges:
            return DataPlaneLayer.SERVING.value

        return DataPlaneLayer.RAW.value

    # Fallback
    return DataPlaneLayer.RAW.value


def classify_actor_capability(node: LineageNode) -> Optional[ActorCapability]:
    """
    Classify an actor node (service/job) by its pipeline capability.

    Returns None for non-actor nodes (datasets, semantics).

    Resolution order:
      1. Evidence-based: check node raw_metadata for generic metadata keys
      2. Platform set membership: check derived platform sets
      3. Fallback: use platform_domain
    """
    rm = node.raw_metadata or {}
    platform = (node.platform or "").lower()

    # Evidence-based resolution FIRST (generic metadata keys)
    if rm.get("workflow_id") or rm.get("dag_id") or rm.get("is_orchestrator"):
        return ActorCapability.ORCHESTRATION
    if rm.get("notebook_path") or rm.get("job_id") or rm.get("spark_job_id"):
        return ActorCapability.TRANSFORMATION
    if rm.get("dq_check_id") or rm.get("test_results"):
        return ActorCapability.QUALITY
    if rm.get("semantic_asset_id"):
        return ActorCapability.REPORTING

    # Then platform set membership
    if platform in INGESTION_PLATFORMS:
        return ActorCapability.INGESTION
    if platform in TRANSFORM_PLATFORMS:
        return ActorCapability.TRANSFORMATION
    if platform in ORCHESTRATION_PLATFORMS:
        return ActorCapability.ORCHESTRATION
    if platform in REPORTING_PLATFORMS:
        return ActorCapability.REPORTING
    if platform in INFRA_PLATFORMS:
        return ActorCapability.INFRA

    # Fallback: use platform_domain
    domain = node.platform_domain
    if domain == PlatformDomain.INGESTION:
        return ActorCapability.INGESTION
    if domain == PlatformDomain.TRANSFORM:
        return ActorCapability.TRANSFORMATION
    if domain == PlatformDomain.ORCHESTRATION:
        return ActorCapability.ORCHESTRATION
    if domain == PlatformDomain.BI:
        return ActorCapability.REPORTING

    return None


def resolve_functional_role(
    node: LineageNode,
    canonical_type: str,
    dataset_zone: Optional[DatasetZone] = None,
    actor_capability: Optional[ActorCapability] = None,
) -> str:
    """Resolve the functional role of a node.

    More specific than platform category — uses node metadata, canonical type,
    zone, and capability to determine what a node actually does in the pipeline.

    Priority:
      1. Explicit override in raw_metadata["functional_role"]
      2. Metadata-driven heuristics (e.g. orchestration metadata on warehouse)
      3. Canonical type + zone/capability classification
      4. Platform category fallback

    Returns a FunctionalRole value string.
    """
    # 1. Explicit override
    override = (node.raw_metadata or {}).get("functional_role", "")
    if override and override in _FUNCTIONAL_ROLE_VALUES:
        return override

    rm = node.raw_metadata or {}
    platform = (node.platform or "").lower()

    # 2. Metadata heuristics — orchestration signals on any node
    if rm.get("dag_id") or rm.get("is_orchestrator"):
        return FunctionalRole.ORCHESTRATION.value

    # 3. Canonical type routing
    if canonical_type == "semantic":
        return FunctionalRole.SEMANTIC.value

    if canonical_type == "dataset":
        # Resolver-merged dbt models materialised in the warehouse are
        # transformation outputs → warehouse_analytics, regardless of
        # naming-based zone (stg_*, int_*).  dbt sources are excluded
        # because they lack dbt_resource_type="model".
        _is_dbt_model = rm.get("dbt_resource_type") == "model" or (
            any(
                dp.lower() in ("dbt", "dbt_core")
                for dp in rm.get("discovered_platforms", [])
            )
            and rm.get("dbt_unique_id", "").startswith("model.")
        )
        if _is_dbt_model and platform in WAREHOUSE_PLATFORMS:
            return FunctionalRole.WAREHOUSE_ANALYTICS.value

        zone = dataset_zone or classify_dataset_zone(node)
        if zone in (DatasetZone.RAW, DatasetZone.UNKNOWN):
            return FunctionalRole.WAREHOUSE_RAW.value
        if zone in (DatasetZone.STAGING, DatasetZone.INTERMEDIATE):
            if platform in WAREHOUSE_PLATFORMS:
                return FunctionalRole.WAREHOUSE_RAW.value
            return FunctionalRole.TRANSFORMATION.value
        if zone in (DatasetZone.MART, DatasetZone.ANALYTICS):
            return FunctionalRole.WAREHOUSE_ANALYTICS.value

    if canonical_type == "system":
        return FunctionalRole.INFRASTRUCTURE.value

    if canonical_type in ("service", "job"):
        cap = actor_capability or classify_actor_capability(node)
        if cap == ActorCapability.INGESTION:
            return FunctionalRole.INGESTION.value
        if cap == ActorCapability.TRANSFORMATION:
            return FunctionalRole.TRANSFORMATION.value
        if cap == ActorCapability.ORCHESTRATION:
            return FunctionalRole.ORCHESTRATION.value
        if cap == ActorCapability.REPORTING:
            return FunctionalRole.REPORTING.value
        if cap == ActorCapability.QUALITY:
            return FunctionalRole.QUALITY.value
        if cap == ActorCapability.INFRA:
            return FunctionalRole.INFRASTRUCTURE.value
        return FunctionalRole.JOB_RUNTIME.value

    # 4. Platform category fallback
    from .platforms import get_category, ToolCategory
    cat = get_category(platform)
    if cat:
        _CAT_TO_ROLE = {
            ToolCategory.WAREHOUSE: FunctionalRole.WAREHOUSE_RAW.value,
            ToolCategory.INGESTION: FunctionalRole.INGESTION.value,
            ToolCategory.TRANSFORMATION: FunctionalRole.TRANSFORMATION.value,
            ToolCategory.ORCHESTRATION: FunctionalRole.ORCHESTRATION.value,
            ToolCategory.REPORTING: FunctionalRole.REPORTING.value,
            ToolCategory.QUALITY: FunctionalRole.QUALITY.value,
            ToolCategory.INFRASTRUCTURE: FunctionalRole.INFRASTRUCTURE.value,
            ToolCategory.VERSION_CONTROL: FunctionalRole.VERSION_CONTROL.value,
        }
        return _CAT_TO_ROLE.get(cat, FunctionalRole.WAREHOUSE_RAW.value)

    return FunctionalRole.WAREHOUSE_RAW.value


# Mapping from functional role → pipeline lane (for role-aware lane assignment)
_ROLE_TO_LANE: Dict[str, str] = {
    FunctionalRole.WAREHOUSE_RAW.value: PipelineLane.WAREHOUSE_RAW.value,
    FunctionalRole.WAREHOUSE_ANALYTICS.value: PipelineLane.WAREHOUSE_ANALYTICS.value,
    FunctionalRole.TRANSFORMATION.value: PipelineLane.TRANSFORMATION.value,
    FunctionalRole.ORCHESTRATION.value: PipelineLane.TRANSFORMATION.value,
    FunctionalRole.INGESTION.value: PipelineLane.INGESTION.value,
    FunctionalRole.REPORTING.value: PipelineLane.REPORTING.value,
    FunctionalRole.QUALITY.value: PipelineLane.TRANSFORMATION.value,
    FunctionalRole.VERSION_CONTROL.value: PipelineLane.INGESTION.value,
    FunctionalRole.INFRASTRUCTURE.value: PipelineLane.INGESTION.value,
    FunctionalRole.SEMANTIC.value: PipelineLane.REPORTING.value,
    FunctionalRole.JOB_RUNTIME.value: PipelineLane.TRANSFORMATION.value,
}


def assign_lane(
    node: LineageNode,
    canonical_type: str,
    dataset_zone: Optional[DatasetZone] = None,
    actor_capability: Optional[ActorCapability] = None,
    functional_role: Optional[str] = None,
) -> str:
    """Assign a node to a pipeline lane for the overview view.

    Precedence:
      1. Explicit lane_override in raw_metadata
      2. Functional role mapping
      3. Zone/capability classification (original logic)

    Returns the lane name as a string.
    """
    # 1. Explicit lane override
    lane_override = (node.raw_metadata or {}).get("lane_override", "")
    if lane_override and lane_override in {l.value for l in PipelineLane}:
        return lane_override

    # 2. Functional role mapping
    if functional_role:
        lane = _ROLE_TO_LANE.get(functional_role)
        if lane:
            return lane

    # 3. Original zone/capability logic (fallback)

    # Datasets → zone-based lane
    if canonical_type == "dataset":
        zone = dataset_zone or classify_dataset_zone(node)
        platform = (node.platform or "").lower()
        is_warehouse = platform in WAREHOUSE_PLATFORMS

        if zone in (DatasetZone.RAW, DatasetZone.UNKNOWN):
            return PipelineLane.WAREHOUSE_RAW.value
        if zone == DatasetZone.STAGING:
            return PipelineLane.WAREHOUSE_RAW.value if is_warehouse else PipelineLane.TRANSFORMATION.value
        if zone == DatasetZone.INTERMEDIATE:
            return PipelineLane.WAREHOUSE_RAW.value if is_warehouse else PipelineLane.TRANSFORMATION.value
        if zone in (DatasetZone.MART, DatasetZone.ANALYTICS):
            return PipelineLane.WAREHOUSE_ANALYTICS.value

    # Semantic → reporting
    if canonical_type == "semantic":
        return PipelineLane.REPORTING.value

    # Actors → capability-based lane
    cap = actor_capability or classify_actor_capability(node)
    if cap == ActorCapability.INGESTION:
        return PipelineLane.INGESTION.value
    if cap == ActorCapability.TRANSFORMATION:
        return PipelineLane.TRANSFORMATION.value
    if cap == ActorCapability.REPORTING:
        return PipelineLane.REPORTING.value

    if cap == ActorCapability.ORCHESTRATION:
        return PipelineLane.TRANSFORMATION.value
    if cap == ActorCapability.INFRA:
        return PipelineLane.INGESTION.value

    # Default
    return PipelineLane.WAREHOUSE_RAW.value
