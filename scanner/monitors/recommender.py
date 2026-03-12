"""
Node-aware monitor recommendation engine.

Given a lineage node and its upstream context, recommends appropriate monitors
based on node type, platform domain, criticality, and upstream relationships.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set, Any

from ..lineage.graph import LineageNode, PlatformDomain, AssetKind, NodeType


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MonitorRecommendation:
    """A single recommended monitor for a lineage node."""
    monitor_key: str           # e.g. "FRESHNESS", "SYNC_LAG"
    target_fqn: str            # prefilled FQN for the monitor target
    target_node_id: str        # engine node ID
    source: str                # "direct" | "upstream" | "bundle"
    reason: str                # human-readable explanation
    priority: int              # 1=critical, 2=high, 3=medium
    config_hints: Dict[str, Any] = field(default_factory=dict)
    integration_type: str = ""  # "bigquery", "fivetran", etc.
    already_monitored: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MonitorBundle:
    """A named set of monitor recommendations."""
    bundle_key: str            # "asset_stability", "upstream_stability", "reporting_health"
    label: str
    description: str
    recommendations: List[MonitorRecommendation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_key": self.bundle_key,
            "label": self.label,
            "description": self.description,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


# ---------------------------------------------------------------------------
# Constants — monitor keys (match types/monitor-catalog.ts)
# ---------------------------------------------------------------------------

# Warehouse SQL monitors
FRESHNESS = "FRESHNESS"
VOLUME = "VOLUME"
SCHEMA_CHANGE = "SCHEMA_CHANGE"
NULL_RATE = "NULL_RATE"
UNIQUENESS = "UNIQUENESS"
ANOMALY = "ANOMALY"

# Ingestion monitors
SYNC_LAG = "SYNC_LAG"
FAILED_SYNCS = "FAILED_SYNCS"
CONNECTOR_SCHEMA_DRIFT = "CONNECTOR_SCHEMA_DRIFT"

# Orchestration monitors
DAG_LAST_RUN = "DAG_LAST_RUN"
DAG_SCHEDULE_LAG = "DAG_SCHEDULE_LAG"

# Transformation monitors
DBT_TEST_FAILURES = "DBT_TEST_FAILURES"
DBT_MODEL_FRESHNESS = "DBT_MODEL_FRESHNESS"
DBT_SOURCE_FRESHNESS = "DBT_SOURCE_FRESHNESS"

# BI node types
_BI_NODE_TYPES = {
    NodeType.DASHBOARD, NodeType.REPORT, NodeType.WORKBOOK,
    NodeType.QUESTION, NodeType.EXPLORE,
}
_BI_ASSET_KINDS = {
    AssetKind.DASHBOARD, AssetKind.REPORT, AssetKind.WORKBOOK,
    AssetKind.QUESTION, AssetKind.EXPLORE,
}

# Max recommendations per bundle
BUNDLE_CAP = 8


# ---------------------------------------------------------------------------
# Config hint helpers
# ---------------------------------------------------------------------------

def _guess_timestamp_column(node: LineageNode) -> Optional[str]:
    """Pick the best timestamp column from a node's columns list."""
    ts_keywords = {"timestamp", "datetime", "date"}
    name_hints = {"updated_at", "created_at", "loaded_at", "_loaded_at", "ingested_at", "updated", "modified_at"}

    # First pass: column name is a known timestamp field
    for col in node.columns:
        col_name = (col.get("name") or "").lower()
        if col_name in name_hints:
            return col.get("name")

    # Second pass: column type contains timestamp/datetime/date
    for col in node.columns:
        col_type = (col.get("type") or "").lower()
        if any(kw in col_type for kw in ts_keywords):
            return col.get("name")

    return None


def _build_config_hints(node: LineageNode, monitor_key: str) -> Dict[str, Any]:
    """Build prefilled config hints based on node metadata and monitor type."""
    hints: Dict[str, Any] = {}

    if monitor_key in (FRESHNESS, VOLUME, ANOMALY):
        ts_col = _guess_timestamp_column(node)
        if ts_col:
            hints["timestamp_column"] = ts_col

    if monitor_key in (SYNC_LAG, FAILED_SYNCS, CONNECTOR_SCHEMA_DRIFT):
        if node.integration_id:
            hints["connector_id"] = node.integration_id

    if monitor_key in (DAG_LAST_RUN, DAG_SCHEDULE_LAG):
        hints["dag_id"] = node.name

    if monitor_key in (DBT_TEST_FAILURES, DBT_MODEL_FRESHNESS, DBT_SOURCE_FRESHNESS):
        if node.integration_id:
            hints["dbt_job_id"] = node.integration_id

    return hints


def is_bi_node(node: LineageNode) -> bool:
    """Check if a node is a BI/reporting asset."""
    return (
        node.platform_domain == PlatformDomain.BI
        or node.node_type in _BI_NODE_TYPES
        or node.asset_kind in _BI_ASSET_KINDS
    )


def _is_high_criticality(node: LineageNode) -> bool:
    return node.criticality in ("critical", "high")


# ---------------------------------------------------------------------------
# Direct monitor recommendations
# ---------------------------------------------------------------------------

def _recommend_direct(node: LineageNode) -> List[MonitorRecommendation]:
    """Recommend monitors directly applicable to this node."""
    recs: List[MonitorRecommendation] = []

    def _add(key: str, priority: int, reason: str):
        recs.append(MonitorRecommendation(
            monitor_key=key,
            target_fqn=node.fqn,
            target_node_id=node.id,
            source="direct",
            reason=reason,
            priority=priority,
            config_hints=_build_config_hints(node, key),
            integration_type=node.platform or "",
        ))

    # --- Warehouse tables/views ---
    if node.platform_domain == PlatformDomain.WAREHOUSE and node.asset_kind in (
        AssetKind.TABLE, AssetKind.VIEW, AssetKind.MODEL, AssetKind.DATASET,
    ):
        _add(FRESHNESS, 1, "Core data quality — detect stale data in this warehouse asset")
        _add(VOLUME, 2, "Core data quality — detect unexpected row count changes")
        _add(SCHEMA_CHANGE, 2, "Core data quality — detect column additions or removals")

        if _is_high_criticality(node):
            _add(NULL_RATE, 2, "Critical asset — monitor null spikes in key columns")
            _add(UNIQUENESS, 2, "Critical asset — detect key degradation")
            _add(ANOMALY, 3, "Critical asset — statistical anomaly detection on metrics")

    # --- Ingestion connectors ---
    elif node.platform_domain == PlatformDomain.INGESTION or node.asset_kind == AssetKind.CONNECTOR:
        _add(SYNC_LAG, 1, "Track ingestion connector sync lag")
        _add(FAILED_SYNCS, 1, "Detect failed syncs on this connector")

        if node.columns:
            _add(CONNECTOR_SCHEMA_DRIFT, 2, "Detect schema changes at the ingestion source")

    # --- Orchestration DAGs ---
    elif node.platform_domain == PlatformDomain.ORCHESTRATION and node.node_type in (
        NodeType.DAG, NodeType.FLOW, NodeType.PIPELINE, NodeType.WORKFLOW,
    ):
        _add(DAG_LAST_RUN, 1, "Ensure scheduled orchestration runs succeed")
        _add(DAG_SCHEDULE_LAG, 2, "Detect when runs fall behind schedule")

    # --- Transformation models (dbt) ---
    elif node.platform_domain == PlatformDomain.TRANSFORM and node.asset_kind in (
        AssetKind.MODEL, AssetKind.TABLE, AssetKind.VIEW,
    ):
        _add(DBT_TEST_FAILURES, 1, "Watch for dbt test regressions on this model")
        _add(DBT_MODEL_FRESHNESS, 2, "Detect when this model build becomes stale")

    # --- BI nodes get no direct monitors (upstream only) ---
    # (handled by upstream recommendations)

    return recs


# ---------------------------------------------------------------------------
# Upstream monitor recommendations
# ---------------------------------------------------------------------------

def _recommend_upstream(
    target_node: LineageNode,
    upstream_nodes: List[LineageNode],
) -> List[MonitorRecommendation]:
    """Recommend monitors on upstream dependencies of target_node."""
    recs: List[MonitorRecommendation] = []
    seen: Set[str] = set()  # (monitor_key, target_fqn) dedup

    for up in upstream_nodes:
        def _add(key: str, priority: int, reason: str):
            dedup_key = f"{key}:{up.fqn}"
            if dedup_key in seen:
                return
            seen.add(dedup_key)
            recs.append(MonitorRecommendation(
                monitor_key=key,
                target_fqn=up.fqn,
                target_node_id=up.id,
                source="upstream",
                reason=reason,
                priority=priority,
                config_hints=_build_config_hints(up, key),
                integration_type=up.platform or "",
            ))

        # Upstream warehouse tables
        if up.platform_domain == PlatformDomain.WAREHOUSE and up.asset_kind in (
            AssetKind.TABLE, AssetKind.VIEW, AssetKind.MODEL, AssetKind.DATASET,
        ):
            _add(FRESHNESS, 2,
                 f"Upstream dependency — stale data in {up.name} impacts {target_node.name}")
            _add(SCHEMA_CHANGE, 3,
                 f"Upstream schema change in {up.name} could break {target_node.name}")

        # Upstream ingestion connectors
        elif up.platform_domain == PlatformDomain.INGESTION or up.asset_kind == AssetKind.CONNECTOR:
            _add(SYNC_LAG, 2,
                 f"Upstream connector {up.name} — sync lag impacts {target_node.name}")

        # Upstream orchestration DAGs
        elif up.platform_domain == PlatformDomain.ORCHESTRATION and up.node_type in (
            NodeType.DAG, NodeType.FLOW, NodeType.PIPELINE, NodeType.WORKFLOW,
        ):
            _add(DAG_LAST_RUN, 2,
                 f"Upstream DAG {up.name} — run failures impact {target_node.name}")

        # Upstream dbt models
        elif up.platform_domain == PlatformDomain.TRANSFORM and up.asset_kind in (
            AssetKind.MODEL, AssetKind.TABLE, AssetKind.VIEW,
        ):
            _add(DBT_TEST_FAILURES, 2,
                 f"Upstream model {up.name} — test failures impact {target_node.name}")

    return recs


# ---------------------------------------------------------------------------
# Dedup marking
# ---------------------------------------------------------------------------

def _mark_existing(
    recs: List[MonitorRecommendation],
    existing_monitor_fqns: Set[str],
) -> None:
    """Mark recommendations whose target is already monitored."""
    for r in recs:
        # Check if a monitor of the same type already targets this FQN
        # Format: "MONITOR_KEY:target_fqn" or just "target_fqn" for any coverage
        key_fqn = f"{r.monitor_key}:{r.target_fqn}"
        if key_fqn in existing_monitor_fqns or r.target_fqn in existing_monitor_fqns:
            r.already_monitored = True


# ---------------------------------------------------------------------------
# Public API — recommend_for_node
# ---------------------------------------------------------------------------

def recommend_for_node(
    node: LineageNode,
    upstream_nodes: Optional[List[LineageNode]] = None,
    existing_monitor_fqns: Optional[Set[str]] = None,
) -> List[MonitorRecommendation]:
    """Return all monitor recommendations for a node and its upstream context.

    Args:
        node: The lineage node to recommend monitors for.
        upstream_nodes: Upstream dependency nodes (depth 1-3 typically).
        existing_monitor_fqns: Set of "MONITOR_KEY:target_fqn" strings for dedup.

    Returns:
        List of MonitorRecommendation sorted by priority (1=highest).
    """
    upstream_nodes = upstream_nodes or []
    existing_monitor_fqns = existing_monitor_fqns or set()

    # Direct recommendations for this node
    direct = _recommend_direct(node)

    # Upstream recommendations
    upstream = _recommend_upstream(node, upstream_nodes)

    all_recs = direct + upstream

    # Deduplicate: no two recs with same (monitor_key, target_fqn)
    seen: Set[str] = set()
    deduped: List[MonitorRecommendation] = []
    for r in all_recs:
        key = f"{r.monitor_key}:{r.target_fqn}"
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    # Mark existing
    _mark_existing(deduped, existing_monitor_fqns)

    # Sort by priority
    deduped.sort(key=lambda r: r.priority)

    return deduped


# ---------------------------------------------------------------------------
# Public API — get_bundles
# ---------------------------------------------------------------------------

def get_bundles(
    node: LineageNode,
    upstream_nodes: Optional[List[LineageNode]] = None,
    existing_monitor_fqns: Optional[Set[str]] = None,
) -> List[MonitorBundle]:
    """Return applicable monitor bundles for a node.

    Bundles are pre-composed sets of monitors. Each bundle is capped at
    BUNDLE_CAP recommendations.
    """
    upstream_nodes = upstream_nodes or []
    existing_monitor_fqns = existing_monitor_fqns or set()
    bundles: List[MonitorBundle] = []

    # --- Asset Stability: direct monitors for this node ---
    if not is_bi_node(node):
        direct = _recommend_direct(node)
        if direct:
            for r in direct:
                r.source = "bundle"
            _mark_existing(direct, existing_monitor_fqns)
            bundles.append(MonitorBundle(
                bundle_key="asset_stability",
                label="Asset Stability",
                description=f"Core quality monitors for {node.name}",
                recommendations=sorted(direct, key=lambda r: r.priority)[:BUNDLE_CAP],
            ))

    # --- Upstream Stability: monitors on upstream deps ---
    if upstream_nodes:
        upstream = _recommend_upstream(node, upstream_nodes)
        if upstream:
            for r in upstream:
                r.source = "bundle"
            _mark_existing(upstream, existing_monitor_fqns)
            bundles.append(MonitorBundle(
                bundle_key="upstream_stability",
                label="Upstream Stability",
                description=f"Monitor upstream dependencies of {node.name}",
                recommendations=sorted(upstream, key=lambda r: r.priority)[:BUNDLE_CAP],
            ))

    # --- Reporting Health: BI nodes only ---
    if is_bi_node(node) and upstream_nodes:
        reporting_recs: List[MonitorRecommendation] = []
        seen: Set[str] = set()

        for up in upstream_nodes:
            if up.platform_domain == PlatformDomain.WAREHOUSE and up.asset_kind in (
                AssetKind.TABLE, AssetKind.VIEW, AssetKind.MODEL, AssetKind.DATASET,
            ):
                for key, reason_tpl in [
                    (FRESHNESS, f"Reporting dependency — stale {up.name} breaks this dashboard/report"),
                    (SCHEMA_CHANGE, f"Reporting dependency — schema change in {up.name} could break queries"),
                ]:
                    dedup_key = f"{key}:{up.fqn}"
                    if dedup_key not in seen:
                        seen.add(dedup_key)
                        reporting_recs.append(MonitorRecommendation(
                            monitor_key=key,
                            target_fqn=up.fqn,
                            target_node_id=up.id,
                            source="bundle",
                            reason=reason_tpl,
                            priority=1,
                            config_hints=_build_config_hints(up, key),
                            integration_type=up.platform or "",
                        ))

            elif up.platform_domain == PlatformDomain.INGESTION or up.asset_kind == AssetKind.CONNECTOR:
                dedup_key = f"{SYNC_LAG}:{up.fqn}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    reporting_recs.append(MonitorRecommendation(
                        monitor_key=SYNC_LAG,
                        target_fqn=up.fqn,
                        target_node_id=up.id,
                        source="bundle",
                        reason=f"Reporting dependency — ingestion lag in {up.name} delays this dashboard/report",
                        priority=2,
                        config_hints=_build_config_hints(up, SYNC_LAG),
                        integration_type=up.platform or "",
                    ))

            elif up.platform_domain == PlatformDomain.TRANSFORM and up.asset_kind in (
                AssetKind.MODEL, AssetKind.TABLE, AssetKind.VIEW,
            ):
                dedup_key = f"{DBT_MODEL_FRESHNESS}:{up.fqn}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    reporting_recs.append(MonitorRecommendation(
                        monitor_key=DBT_MODEL_FRESHNESS,
                        target_fqn=up.fqn,
                        target_node_id=up.id,
                        source="bundle",
                        reason=f"Reporting dependency — stale transform {up.name} delays this dashboard/report",
                        priority=2,
                        config_hints=_build_config_hints(up, DBT_MODEL_FRESHNESS),
                        integration_type=up.platform or "",
                    ))

        if reporting_recs:
            _mark_existing(reporting_recs, existing_monitor_fqns)
            bundles.append(MonitorBundle(
                bundle_key="reporting_health",
                label="Reporting Health",
                description=f"End-to-end monitoring for {node.name} and its data sources",
                recommendations=sorted(reporting_recs, key=lambda r: r.priority)[:BUNDLE_CAP],
            ))

    return bundles
