"""
Tests for schema-agnostic landing zone resolution.

All tests use generic schema names (e.g., "ingest_zone_alpha", "container_beta")
— never hardcoded names like "raw" or "public".

Tests:
1. Landing zone inference from tool config destination_config
2. Landing zone inference from adapter-emitted edges
3. Container mismatch — no fabricated cross-tool edges
4. Name-only fallback — ambiguous case skipped
5. Bridge container validation — mismatch diagnostic
6. Zone classification with landing zone profile
"""

import pytest
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from scanner.lineage.graph import (
    EdgeType,
    Evidence,
    LineageEdge,
    LineageGraph,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.canonical import canonicalize_graph_in_place
from scanner.lineage.engine.landing_zone import (
    LandingContainer,
    LandingZoneProfile,
    IntegrationLandingZone,
    infer_landing_zones,
)
from scanner.lineage.engine.zones import (
    DatasetZone,
    classify_dataset_zone,
)
from scanner.lineage.engine.bridge import BridgeRuleEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeToolConfig:
    """Minimal ToolConfig stand-in for tests."""
    tool_type: str
    config: Dict[str, Any]
    integration_id: Optional[str] = None
    layer: Optional[str] = None
    adapter_type: Optional[str] = None


def _make_node(
    name: str,
    node_type: NodeType,
    platform: str,
    platform_domain: PlatformDomain,
    database: str = "",
    schema: str = "",
    fqn: str = "",
    integration_id: str = None,
    inferred: bool = False,
    raw_metadata: dict = None,
    canonical_type: str = None,
    environment_scope: str = "",
) -> LineageNode:
    node = LineageNode(
        id=f"node:{platform}:{schema}:{name}" if schema else f"node:{platform}:{name}",
        name=name,
        fqn=fqn or f"{database}.{schema}.{name}".strip("."),
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        database=database,
        schema=schema,
        integration_id=integration_id,
        inferred=inferred,
        canonical_type=canonical_type,
        environment_scope=environment_scope,
    )
    if raw_metadata:
        node.raw_metadata = raw_metadata
    return node


def _make_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType = EdgeType.WRITES_TO,
    confidence: float = 0.9,
    inferred: bool = False,
    discovered_from: str = "test",
) -> LineageEdge:
    return LineageEdge(
        id=f"edge:{source_id}→{target_id}",
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        lineage_level=LineageLevel.TABLE,
        confidence=confidence,
        plane=LinePlane.CROSS,
        inferred=inferred,
        discovered_from=discovered_from,
    )


# ---------------------------------------------------------------------------
# Test 1: Landing zone inference from tool config
# ---------------------------------------------------------------------------

class TestLandingZoneInferenceFromToolConfig:
    """Tool config with destination_config should produce high-confidence landing containers."""

    def test_destination_config_produces_landing_container(self):
        """destination_config.dataset in tool config → landing container at 0.95 confidence."""
        graph = LineageGraph()

        # Fivetran job node
        job = _make_node(
            "fivetran_connector_abc", NodeType.WORKFLOW, "fivetran",
            PlatformDomain.INGESTION,
            integration_id="ft_abc",
            canonical_type="job",
        )
        graph.add_node(job)

        # Warehouse table in the declared destination
        table = _make_node(
            "customers", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="my_project", schema="ingest_zone_alpha",
            canonical_type="dataset",
        )
        graph.add_node(table)

        tool_configs = [
            FakeToolConfig(
                tool_type="fivetran",
                integration_id="ft_abc",
                config={
                    "destination_config": {
                        "platform": "bigquery",
                        "project_id": "my_project",
                        "dataset": "ingest_zone_alpha",
                    },
                },
            ),
        ]

        profile = infer_landing_zones(graph, tool_configs)

        assert "ft_abc" in profile.zones
        containers = profile.get_landing_containers_for("ft_abc")
        assert len(containers) >= 1

        lc = containers[0]
        assert lc.schema == "ingest_zone_alpha"
        assert lc.database == "my_project"
        assert lc.confidence == 0.95
        assert lc.evidence_type == "tool_config"

    def test_no_destination_config_produces_no_tool_config_container(self):
        """Without destination_config, no tool_config containers should be inferred."""
        graph = LineageGraph()
        tool_configs = [
            FakeToolConfig(
                tool_type="fivetran",
                integration_id="ft_xyz",
                config={},
            ),
        ]

        profile = infer_landing_zones(graph, tool_configs)
        containers = profile.get_landing_containers_for("ft_xyz")
        # May be empty or populated from other phases, but no tool_config evidence
        tool_config_containers = [
            c for c in containers if c.evidence_type == "tool_config"
        ]
        assert len(tool_config_containers) == 0


# ---------------------------------------------------------------------------
# Test 2: Landing zone inference from adapter edges
# ---------------------------------------------------------------------------

class TestLandingZoneInferenceFromAdapterEdges:
    """Adapter-emitted ingestion→warehouse edges should produce landing containers."""

    def test_adapter_edge_produces_landing_container(self):
        """Non-inferred ingestion→warehouse edge → landing container at 0.9 confidence."""
        graph = LineageGraph()

        job = _make_node(
            "fivetran_job", NodeType.WORKFLOW, "fivetran",
            PlatformDomain.INGESTION,
            integration_id="ft_001",
            canonical_type="job",
        )
        graph.add_node(job)

        table = _make_node(
            "orders", NodeType.TABLE, "snowflake",
            PlatformDomain.WAREHOUSE,
            database="warehouse_db", schema="zone_beta",
            canonical_type="dataset",
        )
        graph.add_node(table)

        edge = _make_edge(job.id, table.id, EdgeType.WRITES_TO, inferred=False)
        graph.add_edge(edge)

        profile = infer_landing_zones(graph, [])

        is_landing, confidence = profile.is_landing_container("warehouse_db", "zone_beta")
        assert is_landing
        assert confidence == 0.9

    def test_inferred_edges_are_skipped(self):
        """Inferred edges should not be used for landing zone inference."""
        graph = LineageGraph()

        job = _make_node(
            "fivetran_job", NodeType.WORKFLOW, "fivetran",
            PlatformDomain.INGESTION,
            integration_id="ft_002",
            canonical_type="job",
        )
        graph.add_node(job)

        table = _make_node(
            "events", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema="some_schema",
            canonical_type="dataset",
        )
        graph.add_node(table)

        edge = _make_edge(job.id, table.id, EdgeType.WRITES_TO, inferred=True)
        graph.add_edge(edge)

        profile = infer_landing_zones(graph, [])
        is_landing, _ = profile.is_landing_container("proj", "some_schema")
        assert not is_landing


# ---------------------------------------------------------------------------
# Test 3: Container mismatch — no fabricated edges
# ---------------------------------------------------------------------------

class TestContainerMismatch:
    """Ingestion declares destination container_a; warehouse has tables in container_b.
    No edges should be fabricated to container_b."""

    def test_no_cross_container_edges(self):
        """Bridge should not create edges for datasets outside the landing zone."""
        graph = LineageGraph()

        # Fivetran job writes to container_a
        job = _make_node(
            "fivetran_loader", NodeType.WORKFLOW, "fivetran",
            PlatformDomain.INGESTION,
            integration_id="ft_mismatch",
            canonical_type="job",
            raw_metadata={"synced_tables": ["users", "orders"]},
        )
        graph.add_node(job)

        dest_table = _make_node(
            "users", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema="container_a",
            canonical_type="dataset",
        )
        graph.add_node(dest_table)
        graph.add_edge(_make_edge(job.id, dest_table.id, EdgeType.WRITES_TO))

        # Orphan dataset in container_b (different from landing zone)
        orphan = _make_node(
            "orders", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema="container_b",
            canonical_type="dataset",
        )
        graph.add_node(orphan)

        # Build landing zone profile
        profile = infer_landing_zones(graph, [])
        assert profile.is_landing_container("proj", "container_a")[0]
        assert not profile.is_landing_container("proj", "container_b")[0]

        # Canonicalize + bridge
        canonicalize_graph_in_place(graph.nodes, graph.edges)
        bridge = BridgeRuleEngine(graph, landing_zone_profile=profile)
        result = bridge.apply_all()

        # The orphan "orders" in container_b should NOT get a bridge edge
        orphan_edges = [
            e for e in result.added_edges if e.target_id == orphan.id
        ]
        assert len(orphan_edges) == 0

        # Should have a landing_zone_mismatch diagnostic
        mismatch_diags = [
            d for d in result.diagnostics
            if d.match_strategy == "landing_zone_mismatch"
        ]
        assert len(mismatch_diags) >= 1
        assert "container_b" in mismatch_diags[0].reason


# ---------------------------------------------------------------------------
# Test 4: Name-only fallback — ambiguous case
# ---------------------------------------------------------------------------

class TestNameOnlyAmbiguity:
    """Two tables with same name in different containers.
    Name-only matching should not be used or should have very low confidence."""

    def test_ambiguous_name_skipped_in_cross_tool(self):
        """When the same table name exists in multiple schemas,
        synced_table matching without container info should not create edges."""
        from scanner.lineage.cross_tool import CrossToolEdgeSynthesizer

        graph = LineageGraph()

        # Ingestion connector with synced_tables but no destination schema
        connector = _make_node(
            "postgres_connector", NodeType.SOURCE, "fivetran",
            PlatformDomain.INGESTION,
            raw_metadata={
                "synced_tables": ["orders"],
                "connector_name": "postgres_connector",
            },
        )
        graph.add_node(connector)

        # Same table name in two different schemas
        table_a = _make_node(
            "orders", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema="container_x",
        )
        graph.add_node(table_a)

        table_b = _make_node(
            "orders", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema="container_y",
        )
        graph.add_node(table_b)

        synthesizer = CrossToolEdgeSynthesizer(graph=graph)
        initial_edge_count = len(graph.edges)
        synthesizer.synthesize_ingestion_edges()

        # Strategy 5 should NOT match because "orders" is ambiguous
        # (exists in both container_x and container_y)
        new_edges = [
            e for e in graph.edges.values()
            if e.source_id == connector.id
            and e.target_id in (table_a.id, table_b.id)
        ]
        assert len(new_edges) == 0, (
            f"Expected no edges for ambiguous name match, got {len(new_edges)}"
        )


# ---------------------------------------------------------------------------
# Test 5: Bridge container validation
# ---------------------------------------------------------------------------

class TestBridgeContainerValidation:
    """Orphan in known landing container → bridge edge.
    Orphan outside landing container → no bridge, diagnostic emitted."""

    def _build_graph_with_orphan(self, orphan_schema: str):
        """Helper: graph with fivetran job + orphan dataset."""
        graph = LineageGraph()

        # Fivetran service (uses CONNECTOR node type, canonical_type="service")
        service = _make_node(
            "Fivetran", NodeType.CONNECTOR, "fivetran",
            PlatformDomain.INGESTION,
            integration_id="ft_bridge",
            canonical_type="service",
        )
        graph.add_node(service)

        # Fivetran job
        job = _make_node(
            "pg_loader", NodeType.WORKFLOW, "fivetran",
            PlatformDomain.INGESTION,
            integration_id="ft_bridge",
            canonical_type="job",
            raw_metadata={"synced_tables": ["events"]},
        )
        graph.add_node(job)

        # Orphan dataset
        orphan = _make_node(
            "events", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema=orphan_schema,
            canonical_type="dataset",
        )
        orphan.sources = ["bigquery"]
        graph.add_node(orphan)

        return graph, orphan

    def test_orphan_in_landing_zone_gets_bridge_edge(self):
        """Orphan in known landing container → bridge edge created."""
        graph, orphan = self._build_graph_with_orphan("landing_alpha")

        # Create profile with landing_alpha as known container
        profile = LandingZoneProfile(
            zones={
                "ft_bridge": IntegrationLandingZone(
                    integration_id="ft_bridge",
                    platform="fivetran",
                    environment_scope="",
                    landing_containers=[
                        LandingContainer(
                            database="proj",
                            schema="landing_alpha",
                            confidence=0.95,
                            evidence_type="tool_config",
                            source_ref="test",
                        ),
                    ],
                ),
            },
        )
        profile._rebuild_cache()

        canonicalize_graph_in_place(graph.nodes, graph.edges)
        bridge = BridgeRuleEngine(graph, landing_zone_profile=profile)
        result = bridge.apply_all()

        # Orphan should get a bridge edge (matched via synced_table_name)
        orphan_edges = [
            e for e in result.added_edges if e.target_id == orphan.id
        ]
        assert len(orphan_edges) >= 1, "Expected bridge edge for orphan in landing zone"

    def test_orphan_outside_landing_zone_gets_mismatch_diagnostic(self):
        """Orphan outside landing container → no bridge edge, diagnostic emitted."""
        graph, orphan = self._build_graph_with_orphan("unrelated_schema")

        # Create profile with a DIFFERENT container as landing zone
        profile = LandingZoneProfile(
            zones={
                "ft_bridge": IntegrationLandingZone(
                    integration_id="ft_bridge",
                    platform="fivetran",
                    environment_scope="",
                    landing_containers=[
                        LandingContainer(
                            database="proj",
                            schema="landing_alpha",
                            confidence=0.95,
                            evidence_type="tool_config",
                            source_ref="test",
                        ),
                    ],
                ),
            },
        )
        profile._rebuild_cache()

        canonicalize_graph_in_place(graph.nodes, graph.edges)
        bridge = BridgeRuleEngine(graph, landing_zone_profile=profile)
        result = bridge.apply_all()

        # Orphan should NOT get a bridge edge
        orphan_edges = [
            e for e in result.added_edges if e.target_id == orphan.id
        ]
        assert len(orphan_edges) == 0, "Expected no bridge edge for orphan outside landing zone"

        # Should have a mismatch diagnostic
        mismatch_diags = [
            d for d in result.diagnostics
            if d.match_strategy == "landing_zone_mismatch"
        ]
        assert len(mismatch_diags) >= 1
        assert "unrelated_schema" in mismatch_diags[0].reason


# ---------------------------------------------------------------------------
# Test 6: Zone classification with landing zone profile
# ---------------------------------------------------------------------------

class TestZoneClassificationWithProfile:
    """Landing zone profile should influence zone classification."""

    def test_table_in_landing_zone_classified_as_raw(self):
        """Table in a known landing container → classified as RAW."""
        profile = LandingZoneProfile(
            zones={
                "ft_test": IntegrationLandingZone(
                    integration_id="ft_test",
                    platform="fivetran",
                    environment_scope="",
                    landing_containers=[
                        LandingContainer(
                            database="proj",
                            schema="custom_landing_schema",
                            confidence=0.9,
                            evidence_type="adapter_edge",
                            source_ref="test",
                        ),
                    ],
                ),
            },
        )
        profile._rebuild_cache()

        # Node with a non-standard schema name (no regex would match)
        node = _make_node(
            "transactions", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema="custom_landing_schema",
        )

        zone = classify_dataset_zone(node, landing_zone_profile=profile)
        assert zone == DatasetZone.RAW

    def test_table_outside_landing_zone_uses_fallback(self):
        """Table in an unrelated container → falls through to other heuristics."""
        profile = LandingZoneProfile(
            zones={
                "ft_test": IntegrationLandingZone(
                    integration_id="ft_test",
                    platform="fivetran",
                    environment_scope="",
                    landing_containers=[
                        LandingContainer(
                            database="proj",
                            schema="ingest_zone",
                            confidence=0.9,
                            evidence_type="adapter_edge",
                            source_ref="test",
                        ),
                    ],
                ),
            },
        )
        profile._rebuild_cache()

        # Node in an unrelated schema with a mart-like name
        node = _make_node(
            "dim_customers", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema="some_other_schema",
        )

        zone = classify_dataset_zone(node, landing_zone_profile=profile)
        # "dim_customers" matches _MART_PATTERNS, so should be MART
        assert zone == DatasetZone.MART

    def test_no_profile_preserves_existing_behavior(self):
        """Without a profile, classification should work as before."""
        node = _make_node(
            "events", NodeType.TABLE, "bigquery",
            PlatformDomain.WAREHOUSE,
            database="proj", schema="completely_unknown",
        )
        node.sources = ["bigquery"]

        zone = classify_dataset_zone(node, landing_zone_profile=None)
        # Warehouse-only node with no transform sources → RAW (existing fallback)
        assert zone == DatasetZone.RAW
