"""
Ingestion Landing Zone Resolver

Infers which (database, schema) containers are landing zones for ingestion
tools — without assuming any specific schema name like "raw" or "public".

Evidence priority:
1. Tool-declared destination container (destination_config dataset/schema)
2. Adapter-emitted WRITES_TO edges from ingestion → warehouse nodes
3. Warehouse inventory match (synced_tables metadata vs warehouse tables)
4. No match → unknown landing zone (no assumptions)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from ..graph import LineageGraph, LineageNode, PlatformDomain
from .canonical import CanonicalNodeType
from .platforms import INGESTION_PLATFORMS, ToolCategory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LandingContainer:
    """A (database, schema) pair identified as an ingestion landing zone."""

    database: str       # project_id / database name (may be "")
    schema: str         # dataset / schema name
    confidence: float   # 0.0–1.0
    evidence_type: str  # "tool_config" | "adapter_edge" | "warehouse_match"
    source_ref: str     # provenance string


@dataclass
class IntegrationLandingZone:
    """Landing zone info for a single ingestion integration."""

    integration_id: str
    platform: str
    environment_scope: str
    landing_containers: List[LandingContainer] = field(default_factory=list)


@dataclass
class LandingZoneProfile:
    """Aggregated landing zone info across all ingestion integrations."""

    zones: Dict[str, IntegrationLandingZone] = field(default_factory=dict)

    # Precomputed set for fast lookup: {(database_lower, schema_lower)}
    _container_set: Set[Tuple[str, str]] = field(
        default_factory=set, repr=False,
    )
    # Best confidence per container
    _container_confidence: Dict[Tuple[str, str], float] = field(
        default_factory=dict, repr=False,
    )

    def _rebuild_cache(self) -> None:
        self._container_set.clear()
        self._container_confidence.clear()
        for zone in self.zones.values():
            for lc in zone.landing_containers:
                key = (lc.database.lower(), lc.schema.lower())
                self._container_set.add(key)
                if lc.confidence > self._container_confidence.get(key, 0.0):
                    self._container_confidence[key] = lc.confidence

    def is_landing_container(
        self, database: str, schema: str,
    ) -> Tuple[bool, float]:
        """Check if (database, schema) is a known landing container.

        Returns (is_landing, best_confidence).  Schema comparison is
        case-insensitive; an empty database matches any database.
        """
        if not schema:
            return False, 0.0

        schema_lower = schema.lower()
        db_lower = database.lower() if database else ""

        # Exact match (both db and schema)
        key = (db_lower, schema_lower)
        if key in self._container_set:
            return True, self._container_confidence.get(key, 0.0)

        # Match with empty database on either side
        if db_lower:
            key_no_db = ("", schema_lower)
            if key_no_db in self._container_set:
                return True, self._container_confidence.get(key_no_db, 0.0)
        else:
            # Caller has no database — match any database with this schema
            for (stored_db, stored_schema), conf in self._container_confidence.items():
                if stored_schema == schema_lower:
                    return True, conf

        return False, 0.0

    def get_landing_containers_for(
        self, integration_id: str,
    ) -> List[LandingContainer]:
        zone = self.zones.get(integration_id)
        return zone.landing_containers if zone else []

    @property
    def all_containers(self) -> Set[Tuple[str, str]]:
        """All known landing containers as (database, schema) pairs."""
        return set(self._container_set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            integration_id: {
                "platform": zone.platform,
                "environment_scope": zone.environment_scope,
                "landing_containers": [
                    {
                        "database": lc.database,
                        "schema": lc.schema,
                        "confidence": lc.confidence,
                        "evidence_type": lc.evidence_type,
                        "source_ref": lc.source_ref,
                    }
                    for lc in zone.landing_containers
                ],
            }
            for integration_id, zone in self.zones.items()
        }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def infer_landing_zones(
    graph: LineageGraph,
    tool_configs: List[Any],
) -> LandingZoneProfile:
    """Infer landing zones from graph structure and tool configurations.

    Args:
        graph: The lineage graph (after adapter discovery + resolver dedup).
        tool_configs: List of ToolConfig objects from the pipeline.

    Returns:
        LandingZoneProfile with per-integration landing containers.
    """
    profile = LandingZoneProfile()

    # Phase 1: Extract from tool_configs destination_config
    _infer_from_tool_configs(profile, tool_configs)

    # Phase 2: Extract from adapter-emitted edges (ingestion → warehouse)
    _infer_from_adapter_edges(profile, graph)

    # Phase 3: Match synced_tables metadata against warehouse inventory
    _infer_from_warehouse_inventory(profile, graph)

    profile._rebuild_cache()

    logger.info(
        "[LandingZone] Inferred %d integration zones with %d total containers",
        len(profile.zones),
        sum(len(z.landing_containers) for z in profile.zones.values()),
    )
    for int_id, zone in profile.zones.items():
        for lc in zone.landing_containers:
            logger.info(
                "[LandingZone]   %s (%s): %s.%s [%.2f, %s]",
                int_id, zone.platform, lc.database, lc.schema,
                lc.confidence, lc.evidence_type,
            )

    return profile


def _infer_from_tool_configs(
    profile: LandingZoneProfile,
    tool_configs: List[Any],
) -> None:
    """Phase 1: Extract landing containers from tool config destination settings."""
    for tc in tool_configs:
        tool_type = getattr(tc, "tool_type", "")
        if tool_type.lower() not in INGESTION_PLATFORMS:
            continue

        integration_id = getattr(tc, "integration_id", None) or "default"
        config = getattr(tc, "config", {}) or {}
        dest_cfg = config.get("destination_config", {}) or {}
        env_scope = config.get("environment_scope", "")

        # Extract dataset/schema from destination_config
        dest_schema = (
            dest_cfg.get("dataset")
            or dest_cfg.get("schema")
            or ""
        )
        dest_database = (
            dest_cfg.get("project_id")
            or dest_cfg.get("database")
            or ""
        )

        if not dest_schema:
            continue

        zone = profile.zones.setdefault(
            integration_id,
            IntegrationLandingZone(
                integration_id=integration_id,
                platform=tool_type.lower(),
                environment_scope=env_scope,
            ),
        )
        zone.landing_containers.append(LandingContainer(
            database=dest_database,
            schema=dest_schema,
            confidence=0.95,
            evidence_type="tool_config",
            source_ref=f"{tool_type}:{integration_id}:destination_config",
        ))


def _infer_from_adapter_edges(
    profile: LandingZoneProfile,
    graph: LineageGraph,
) -> None:
    """Phase 2: Extract landing containers from adapter-emitted ingestion → warehouse edges."""
    # Find all ingestion job/service nodes
    ingestion_nodes: Dict[str, LineageNode] = {}
    for node in graph.nodes.values():
        platform = (node.platform or "").lower()
        if platform not in INGESTION_PLATFORMS:
            continue
        canonical = node.canonical_type or ""
        if canonical in ("service", "job"):
            ingestion_nodes[node.id] = node

    # For each ingestion node, look at downstream warehouse datasets
    for ing_id, ing_node in ingestion_nodes.items():
        integration_id = ing_node.integration_id or "default"
        platform = (ing_node.platform or "").lower()
        env_scope = ing_node.environment_scope or ""

        downstream_ids = graph._downstream.get(ing_id, set())
        seen_containers: Set[Tuple[str, str]] = set()

        # Build set of inferred edge targets for this ingestion node
        inferred_targets: Set[str] = set()
        for edge in graph.edges.values():
            if edge.source_id == ing_id and edge.inferred:
                inferred_targets.add(edge.target_id)

        for down_id in downstream_ids:
            down_node = graph.nodes.get(down_id)
            if not down_node:
                continue
            if down_node.platform_domain != PlatformDomain.WAREHOUSE:
                continue
            # Skip nodes/edges that were inferred (bridge-created)
            if down_node.inferred or down_id in inferred_targets:
                continue
            if not down_node.schema:
                continue

            container = (
                (down_node.database or "").lower(),
                down_node.schema.lower(),
            )
            if container in seen_containers:
                continue
            seen_containers.add(container)

            # Check that the zone doesn't already have this container from tool_config
            zone = profile.zones.get(integration_id)
            if zone:
                already_known = any(
                    lc.schema.lower() == container[1]
                    and (not lc.database or lc.database.lower() == container[0])
                    for lc in zone.landing_containers
                )
                if already_known:
                    continue

            zone = profile.zones.setdefault(
                integration_id,
                IntegrationLandingZone(
                    integration_id=integration_id,
                    platform=platform,
                    environment_scope=env_scope,
                ),
            )
            zone.landing_containers.append(LandingContainer(
                database=down_node.database or "",
                schema=down_node.schema,
                confidence=0.9,
                evidence_type="adapter_edge",
                source_ref=f"{platform}:{integration_id}:edge_to:{down_node.fqn or down_node.name}",
            ))


def _infer_from_warehouse_inventory(
    profile: LandingZoneProfile,
    graph: LineageGraph,
) -> None:
    """Phase 3: Match ingestion synced_tables metadata against warehouse table inventory."""
    # Build warehouse inventory: {table_name_lower: {(db, schema)}}
    wh_inventory: Dict[str, Set[Tuple[str, str]]] = {}
    for node in graph.nodes.values():
        if node.canonical_type != CanonicalNodeType.DATASET.value:
            continue
        if node.platform_domain != PlatformDomain.WAREHOUSE:
            continue
        if not node.name or not node.schema:
            continue
        name_lower = node.name.lower()
        container = ((node.database or "").lower(), node.schema.lower())
        wh_inventory.setdefault(name_lower, set()).add(container)

    # Find ingestion nodes with synced_tables that don't yet have containers
    for node in graph.nodes.values():
        platform = (node.platform or "").lower()
        if platform not in INGESTION_PLATFORMS:
            continue
        canonical = node.canonical_type or ""
        if canonical not in ("service", "job"):
            continue

        integration_id = node.integration_id or "default"
        zone = profile.zones.get(integration_id)
        if zone and zone.landing_containers:
            # Already resolved — skip
            continue

        synced_tables = (
            node.raw_metadata.get("synced_tables", [])
            or node.raw_metadata.get("synced_streams", [])
        )
        if not synced_tables:
            continue

        # Count how many synced tables appear in each container
        container_hits: Dict[Tuple[str, str], int] = {}
        for table_name in synced_tables:
            containers = wh_inventory.get(table_name.lower(), set())
            for container in containers:
                container_hits[container] = container_hits.get(container, 0) + 1

        if not container_hits:
            continue

        # Pick containers with significant overlap (>= 50% of synced tables)
        threshold = max(1, len(synced_tables) // 2)
        env_scope = node.environment_scope or ""

        for container, hit_count in container_hits.items():
            if hit_count < threshold:
                continue

            zone = profile.zones.setdefault(
                integration_id,
                IntegrationLandingZone(
                    integration_id=integration_id,
                    platform=platform,
                    environment_scope=env_scope,
                ),
            )
            zone.landing_containers.append(LandingContainer(
                database=container[0],
                schema=container[1],
                confidence=0.7,
                evidence_type="warehouse_match",
                source_ref=(
                    f"{platform}:{integration_id}:warehouse_match:"
                    f"{container[0]}.{container[1]}:{hit_count}/{len(synced_tables)}"
                ),
            ))
