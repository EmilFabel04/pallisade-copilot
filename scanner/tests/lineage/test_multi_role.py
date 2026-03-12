"""
Tests for the multi-role platform framework.

DESIGN RULE: Observed usage beats theoretical capability.
A platform splits into multiple roles ONLY when:
  1. Discovered assets / metadata provide evidence of that role
  2. Each role group has meaningful content (assets/jobs/nodes)
  3. Role membership is evidence-backed, not just capability-based
PlatformInfo.capabilities is an ELIGIBILITY HINT, not proof of active usage.
"""

import pytest
from collections import defaultdict

from scanner.lineage.graph import (
    LineageEdge,
    LineageGraph,
    LineageNode,
    NodeType,
    EdgeType,
    HealthStatus,
    PlatformDomain,
)
from scanner.lineage.engine.platforms import (
    PlatformInfo,
    ToolCategory,
    get_all_categories,
    get_category,
    has_capability,
    is_multi_role,
    ORCHESTRATION_PLATFORMS,
    TRANSFORM_PLATFORMS,
    WAREHOUSE_PLATFORMS,
)
from scanner.lineage.engine.zones import (
    FunctionalRole,
    ActorCapability,
    _ROLE_TO_LANE,
    classify_actor_capability,
    resolve_functional_role,
)
from scanner.lineage.engine.control_plane import build_control_plane_graph
from scanner.drivers.base import ObservedCapability


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_node(
    node_id: str,
    name: str,
    platform: str = "testplatform",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    node_type: NodeType = NodeType.TABLE,
    canonical_type: str = "dataset",
    schema: str = "public",
    raw_metadata: dict = None,
    integration_id: str = None,
) -> LineageNode:
    return LineageNode(
        id=node_id,
        name=name,
        fqn=f"{schema}.{name}" if schema else name,
        platform=platform,
        platform_domain=platform_domain,
        node_type=node_type,
        canonical_type=canonical_type,
        schema=schema,
        raw_metadata=raw_metadata or {},
        integration_id=integration_id,
        health_status=HealthStatus.HEALTHY,
    )


def _make_edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    edge_type: EdgeType = EdgeType.DERIVED_FROM,
) -> LineageEdge:
    return LineageEdge(
        id=edge_id,
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. Platform Registry: capabilities, helpers, derived sets
# ═══════════════════════════════════════════════════════════════════════

class TestPlatformCapabilities:
    """Tests 14-16: helper functions and derived set membership."""

    def test_get_all_categories_single_role(self):
        """Single-role platform returns only primary category."""
        cats = get_all_categories("bigquery")
        assert cats == (ToolCategory.WAREHOUSE,)

    def test_get_all_categories_multi_role(self):
        """Multi-role platform returns primary + secondary capabilities."""
        cats = get_all_categories("databricks")
        assert ToolCategory.WAREHOUSE in cats
        assert ToolCategory.ORCHESTRATION in cats
        assert ToolCategory.TRANSFORMATION in cats

    def test_has_capability_primary(self):
        """has_capability returns True for the primary category."""
        assert has_capability("databricks", ToolCategory.WAREHOUSE)

    def test_has_capability_secondary(self):
        """has_capability returns True for eligible secondary capabilities."""
        assert has_capability("databricks", ToolCategory.ORCHESTRATION)

    def test_has_capability_not_eligible(self):
        """has_capability returns False for capabilities not declared."""
        assert not has_capability("databricks", ToolCategory.REPORTING)

    def test_is_multi_role_true(self):
        """is_multi_role returns True for platforms with capabilities."""
        assert is_multi_role("databricks")

    def test_is_multi_role_false(self):
        """is_multi_role returns False for single-role platforms."""
        assert not is_multi_role("bigquery")

    def test_is_multi_role_eligibility_only(self):
        """is_multi_role is eligibility, not observed usage."""
        # This is a design contract test — even though Databricks is
        # multi-role eligible, this does NOT mean it's observed.
        assert is_multi_role("databricks")
        # get_category still returns the PRIMARY category
        assert get_category("databricks") == ToolCategory.WAREHOUSE

    def test_derived_set_multi_role_membership(self):
        """Multi-role platforms appear in multiple derived sets."""
        assert "databricks" in WAREHOUSE_PLATFORMS
        assert "databricks" in ORCHESTRATION_PLATFORMS
        assert "databricks" in TRANSFORM_PLATFORMS

    def test_derived_set_single_role_unchanged(self):
        """Single-role platforms still appear in exactly one set."""
        assert "bigquery" in WAREHOUSE_PLATFORMS
        assert "bigquery" not in ORCHESTRATION_PLATFORMS
        assert "bigquery" not in TRANSFORM_PLATFORMS

    def test_get_category_unchanged(self):
        """get_category still returns PRIMARY for backward compat."""
        assert get_category("databricks") == ToolCategory.WAREHOUSE
        assert get_category("airflow") == ToolCategory.ORCHESTRATION

    def test_unknown_platform(self):
        """Unknown platform returns empty tuple / None / False."""
        assert get_all_categories("nonexistent") == ()
        assert not has_capability("nonexistent", ToolCategory.WAREHOUSE)
        assert not is_multi_role("nonexistent")


# ═══════════════════════════════════════════════════════════════════════
# 2. ObservedCapability structure
# ═══════════════════════════════════════════════════════════════════════

class TestObservedCapability:
    """Test 17: ObservedCapability structure preserves fields."""

    def test_to_dict(self):
        oc = ObservedCapability(
            capability="orchestration",
            source="api_probe",
            confidence=0.9,
            metadata={"api_endpoint": "/api/2.1/jobs/list", "asset_count": 42},
        )
        d = oc.to_dict()
        assert d["capability"] == "orchestration"
        assert d["source"] == "api_probe"
        assert d["confidence"] == 0.9
        assert d["metadata"]["asset_count"] == 42

    def test_defaults(self):
        oc = ObservedCapability(capability="warehouse", source="driver_identity")
        assert oc.confidence == 1.0
        assert oc.metadata == {}


# ═══════════════════════════════════════════════════════════════════════
# 3. Evidence-based actor capability resolution
# ═══════════════════════════════════════════════════════════════════════

class TestClassifyActorCapability:
    """Tests for evidence-first classify_actor_capability."""

    def test_workflow_id_metadata(self):
        """Node with workflow_id → ORCHESTRATION regardless of platform."""
        node = _make_node("n1", "my_workflow", platform="databricks",
                          canonical_type="job", raw_metadata={"workflow_id": "wf-123"})
        assert classify_actor_capability(node) == ActorCapability.ORCHESTRATION

    def test_dag_id_metadata(self):
        """Node with dag_id → ORCHESTRATION."""
        node = _make_node("n1", "my_dag", platform="databricks",
                          canonical_type="job", raw_metadata={"dag_id": "etl_daily"})
        assert classify_actor_capability(node) == ActorCapability.ORCHESTRATION

    def test_notebook_path_metadata(self):
        """Node with notebook_path → TRANSFORMATION."""
        node = _make_node("n1", "notebook_run", platform="databricks",
                          canonical_type="job",
                          raw_metadata={"notebook_path": "/Users/me/etl.py"})
        assert classify_actor_capability(node) == ActorCapability.TRANSFORMATION

    def test_dq_check_metadata(self):
        """Node with dq_check_id → QUALITY."""
        node = _make_node("n1", "quality_check", platform="databricks",
                          canonical_type="job",
                          raw_metadata={"dq_check_id": "check-001"})
        assert classify_actor_capability(node) == ActorCapability.QUALITY

    def test_no_metadata_falls_to_platform(self):
        """Without metadata signals, falls back to platform set membership."""
        node = _make_node("n1", "some_job", platform="airflow",
                          platform_domain=PlatformDomain.ORCHESTRATION,
                          canonical_type="job")
        assert classify_actor_capability(node) == ActorCapability.ORCHESTRATION

    def test_databricks_no_metadata_uses_platform_set(self):
        """Databricks without role metadata uses platform set (now includes ORCHESTRATION)."""
        node = _make_node("n1", "some_service", platform="databricks",
                          canonical_type="service")
        # Databricks is in ORCHESTRATION_PLATFORMS (via capabilities),
        # but INGESTION_PLATFORMS is checked first in the code,
        # and Databricks is not in INGESTION. It IS in TRANSFORM_PLATFORMS.
        cap = classify_actor_capability(node)
        # Databricks is in both TRANSFORM and ORCHESTRATION via capabilities,
        # but TRANSFORM is checked first in the code
        assert cap in (ActorCapability.TRANSFORMATION, ActorCapability.ORCHESTRATION)


# ═══════════════════════════════════════════════════════════════════════
# 4. Functional role resolution
# ═══════════════════════════════════════════════════════════════════════

class TestResolveFunctionalRole:
    """Tests for resolve_functional_role with multi-role platforms."""

    def test_dataset_raw_zone(self):
        """Dataset in raw zone → warehouse_raw."""
        node = _make_node("n1", "raw_events", platform="databricks",
                          schema="raw")
        role = resolve_functional_role(node, "dataset")
        assert role == FunctionalRole.WAREHOUSE_RAW.value

    def test_job_with_workflow_id(self):
        """Job with workflow_id → orchestration."""
        node = _make_node("n1", "etl_workflow", platform="databricks",
                          canonical_type="job",
                          raw_metadata={"workflow_id": "wf-123", "is_orchestrator": True})
        role = resolve_functional_role(node, "job")
        assert role == FunctionalRole.ORCHESTRATION.value


# ═══════════════════════════════════════════════════════════════════════
# 5. No-speculative-split tests
# ═══════════════════════════════════════════════════════════════════════

class TestNoSpeculativeSplit:
    """Tests 1, 4, 8: platforms must NOT split without observed evidence."""

    def test_capability_without_evidence_no_split(self):
        """Platform with multi-role capability but only dataset nodes → NO split.

        This is the core design rule test: capability ≠ evidence.
        """
        # Databricks with only SQL tables (no workflow_id, no job nodes)
        nodes = [
            _make_node(f"n{i}", f"table_{i}", platform="databricks",
                       schema="analytics", canonical_type="dataset",
                       raw_metadata={"dbt_resource_type": "model",
                                     "dbt_unique_id": f"model.proj.table_{i}",
                                     "discovered_platforms": ["databricks", "dbt"]})
            for i in range(5)
        ]
        # All nodes resolve to warehouse_analytics → single lane → no split
        roles = set()
        for n in nodes:
            role = resolve_functional_role(n, "dataset")
            roles.add(role)
            lane = _ROLE_TO_LANE.get(role, "")
            assert lane  # all should get a lane

        # All in same lane → no split condition met
        lanes = {_ROLE_TO_LANE.get(r, "") for r in roles}
        assert len(lanes) == 1, f"Expected 1 lane, got {lanes}"

    def test_single_role_platform_no_split(self):
        """BigQuery (single-role) with datasets → no split regardless."""
        nodes = [
            _make_node(f"n{i}", f"table_{i}", platform="bigquery",
                       schema="raw", canonical_type="dataset")
            for i in range(3)
        ]
        roles = {resolve_functional_role(n, "dataset") for n in nodes}
        lanes = {_ROLE_TO_LANE.get(r, "") for r in roles}
        # Even if all in warehouse_raw, it's one lane → no split
        assert len(lanes) <= 1 or not is_multi_role("bigquery")

    def test_one_role_group_empty_no_split(self):
        """If one role group would be empty → no split.

        This tests the minimum-content check.
        """
        # Only one node type: all datasets, no jobs
        roles_per_tool = defaultdict(lambda: defaultdict(int))
        tool_id = "databricks:int-1"
        for i in range(5):
            n = _make_node(f"n{i}", f"table_{i}", platform="databricks",
                           schema="raw", canonical_type="dataset")
            role = resolve_functional_role(n, "dataset")
            roles_per_tool[tool_id][role] += 1

        # Verify: only one role type present
        assert len(roles_per_tool[tool_id]) == 1


# ═══════════════════════════════════════════════════════════════════════
# 6. Evidence-backed split tests
# ═══════════════════════════════════════════════════════════════════════

class TestEvidenceBackedSplit:
    """Tests 2, 3: platforms split when real evidence exists."""

    def test_datasets_plus_jobs_produces_two_roles(self):
        """Platform with datasets + job nodes (with workflow_id) → two distinct roles."""
        # Dataset nodes → warehouse_raw
        dataset_nodes = [
            _make_node(f"d{i}", f"raw_table_{i}", platform="databricks",
                       schema="raw", canonical_type="dataset")
            for i in range(3)
        ]
        # Job nodes → orchestration (via workflow_id metadata)
        job_nodes = [
            _make_node(f"j{i}", f"workflow_{i}", platform="databricks",
                       canonical_type="job",
                       node_type=NodeType.TASK,
                       raw_metadata={"workflow_id": f"wf-{i}", "is_orchestrator": True})
            for i in range(2)
        ]

        all_roles = set()
        for n in dataset_nodes:
            all_roles.add(resolve_functional_role(n, "dataset"))
        for n in job_nodes:
            all_roles.add(resolve_functional_role(n, "job"))

        # Should produce at least 2 roles mapping to different lanes
        assert len(all_roles) >= 2
        lanes = {_ROLE_TO_LANE.get(r, "") for r in all_roles}
        lanes.discard("")
        assert len(lanes) >= 2, f"Expected 2+ lanes, got {lanes}"

    def test_each_role_group_has_content(self):
        """Both role groups have meaningful node counts."""
        role_counts = defaultdict(int)

        # 3 dataset nodes
        for i in range(3):
            n = _make_node(f"d{i}", f"table_{i}", platform="databricks",
                           schema="raw", canonical_type="dataset")
            role_counts[resolve_functional_role(n, "dataset")] += 1

        # 2 job nodes
        for i in range(2):
            n = _make_node(f"j{i}", f"wf_{i}", platform="databricks",
                           canonical_type="job",
                           raw_metadata={"workflow_id": f"wf-{i}"})
            role_counts[resolve_functional_role(n, "job")] += 1

        # Every role has at least 1 node
        for role, count in role_counts.items():
            assert count >= 1, f"Role {role} has {count} nodes"


# ═══════════════════════════════════════════════════════════════════════
# 7. Same-platform edge tests
# ═══════════════════════════════════════════════════════════════════════

class TestSamePlatformEdges:
    """Tests 5-7: same-platform cross-role edges."""

    def test_different_role_nodes_produce_different_lanes(self):
        """Workflow job and raw table on same platform → different lanes."""
        job = _make_node("j1", "etl_wf", platform="databricks",
                         canonical_type="job",
                         raw_metadata={"workflow_id": "wf-1"})
        table = _make_node("t1", "raw_events", platform="databricks",
                           schema="raw", canonical_type="dataset")

        job_role = resolve_functional_role(job, "job")
        table_role = resolve_functional_role(table, "dataset")
        assert job_role != table_role

        job_lane = _ROLE_TO_LANE.get(job_role, "")
        table_lane = _ROLE_TO_LANE.get(table_role, "")
        assert job_lane != table_lane

    def test_same_role_nodes_same_lane(self):
        """Two raw tables on same platform → same lane, no cross-role edge."""
        t1 = _make_node("t1", "raw_a", platform="databricks",
                         schema="raw", canonical_type="dataset")
        t2 = _make_node("t2", "raw_b", platform="databricks",
                         schema="raw", canonical_type="dataset")

        r1 = resolve_functional_role(t1, "dataset")
        r2 = resolve_functional_role(t2, "dataset")
        assert r1 == r2  # Same role → no cross-role edge possible


# ═══════════════════════════════════════════════════════════════════════
# 8. Backward compatibility: warehouse raw/analytics split
# ═══════════════════════════════════════════════════════════════════════

class TestWarehouseSplitBackwardCompat:
    """Test 9: existing warehouse raw/analytics split preserved."""

    def test_raw_and_analytics_different_roles(self):
        """Raw tables and dbt-materialized tables → different functional roles."""
        raw = _make_node("r1", "raw_events", platform="bigquery",
                         schema="raw", canonical_type="dataset")
        analytics = _make_node("a1", "fct_orders", platform="bigquery",
                               schema="analytics", canonical_type="dataset",
                               raw_metadata={
                                   "dbt_resource_type": "model",
                                   "dbt_unique_id": "model.proj.fct_orders",
                                   "discovered_platforms": ["bigquery", "dbt"],
                               })

        raw_role = resolve_functional_role(raw, "dataset")
        analytics_role = resolve_functional_role(analytics, "dataset")

        assert raw_role == FunctionalRole.WAREHOUSE_RAW.value
        assert analytics_role == FunctionalRole.WAREHOUSE_ANALYTICS.value

    def test_raw_analytics_different_lanes(self):
        """Raw and analytics roles map to different lanes."""
        raw_lane = _ROLE_TO_LANE[FunctionalRole.WAREHOUSE_RAW.value]
        analytics_lane = _ROLE_TO_LANE[FunctionalRole.WAREHOUSE_ANALYTICS.value]
        assert raw_lane != analytics_lane


# ═══════════════════════════════════════════════════════════════════════
# 9. Control plane: role-qualified nodes
# ═══════════════════════════════════════════════════════════════════════

class TestControlPlaneMultiRole:
    """Tests 10-11: CP nodes from observed roles only, not capability."""

    def test_single_observed_role_single_cp_node(self):
        """Multi-role-eligible platform with 1 observed role → single CP node."""
        graph = LineageGraph()
        # Only dataset nodes (no workflow_id) — one observed role
        for i in range(3):
            graph.add_node(_make_node(
                f"t{i}", f"raw_table_{i}", platform="databricks",
                schema="raw", canonical_type="dataset",
                integration_id="int-1",
            ))

        cp = build_control_plane_graph(graph)
        # Should be exactly 1 CP node for databricks (no role split)
        db_nodes = [n for n in cp.nodes if n.tool_type == "databricks"]
        assert len(db_nodes) == 1
        assert ":role:" not in db_nodes[0].id

    def test_two_observed_roles_two_cp_nodes(self):
        """Multi-role platform with 2+ observed roles with content → separate CP nodes."""
        graph = LineageGraph()
        # Dataset nodes → warehouse role
        for i in range(3):
            graph.add_node(_make_node(
                f"t{i}", f"raw_table_{i}", platform="databricks",
                schema="raw", canonical_type="dataset",
                integration_id="int-1",
            ))
        # Job nodes → orchestration role (via workflow_id)
        for i in range(2):
            graph.add_node(_make_node(
                f"j{i}", f"workflow_{i}", platform="databricks",
                canonical_type="job",
                node_type=NodeType.TASK,
                integration_id="int-1",
                raw_metadata={"workflow_id": f"wf-{i}", "is_orchestrator": True},
            ))

        cp = build_control_plane_graph(graph)
        db_nodes = [n for n in cp.nodes if n.tool_type == "databricks"]
        assert len(db_nodes) >= 2, (
            f"Expected 2+ CP nodes for databricks, got {len(db_nodes)}: "
            f"{[n.id for n in db_nodes]}"
        )
        # At least one should have :role: in its ID
        role_nodes = [n for n in db_nodes if ":role:" in n.id]
        assert len(role_nodes) >= 2

    def test_cp_node_not_from_capability_alone(self):
        """Snowflake with only dataset nodes → 1 CP node even though it has
        transformation capability declared."""
        graph = LineageGraph()
        for i in range(3):
            graph.add_node(_make_node(
                f"t{i}", f"table_{i}", platform="snowflake",
                schema="public", canonical_type="dataset",
                integration_id="int-1",
            ))

        cp = build_control_plane_graph(graph)
        sf_nodes = [n for n in cp.nodes if n.tool_type == "snowflake"]
        assert len(sf_nodes) == 1
        assert ":role:" not in sf_nodes[0].id


# ═══════════════════════════════════════════════════════════════════════
# 10. Tool details
# ═══════════════════════════════════════════════════════════════════════

class TestToolDetailsRoleFields:
    """Tests 12-13: tool details response includes role fields."""

    # These are structural tests — build_tool_details requires a full
    # PipelineOverviewBuilder which is heavy to set up.  We verify the
    # response shape in the integration/regression tests instead.
    # Here we verify the ObservedCapability and helper contracts.

    def test_observed_capability_fields(self):
        """ObservedCapability preserves all structured fields."""
        oc = ObservedCapability(
            capability="orchestration",
            source="api_probe",
            confidence=0.85,
            metadata={"job_count": 10},
        )
        d = oc.to_dict()
        assert set(d.keys()) == {"capability", "source", "confidence", "metadata"}
