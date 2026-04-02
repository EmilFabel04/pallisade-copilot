"""Tests for policy_resolver — resolution chain precedence, field-by-field merge, branch logic."""

from __future__ import annotations

import pytest

from scanner.monitors.policy_resolver import (
    BUILTIN_PROFILES,
    CRITICALITY_PROFILE_MAP,
    EffectivePolicy,
    _compute_branch_distances,
    _extract_all_fields_from_profile,
    _extract_fields_from_config,
    get_policy_status,
    resolve_policy,
    resolve_policies_bulk,
)


# ---------------------------------------------------------------------------
# Helpers: mock graph for branch tests
# ---------------------------------------------------------------------------

class _MockNode:
    def __init__(self, id: str, fqn: str):
        self.id = id
        self.fqn = fqn


class _MockEdge:
    def __init__(self, source_id: str, target_id: str):
        self.source_id = source_id
        self.target_id = target_id


class _MockGraph:
    """Minimal graph stub for branch distance BFS."""
    def __init__(self, nodes: dict, edges: dict):
        self.nodes = nodes  # id → _MockNode
        self.edges = edges  # id → _MockEdge


def _simple_graph():
    """
    A → B → C → D
    """
    nodes = {
        "a": _MockNode("a", "schema.table_a"),
        "b": _MockNode("b", "schema.table_b"),
        "c": _MockNode("c", "schema.table_c"),
        "d": _MockNode("d", "schema.table_d"),
    }
    edges = {
        "e1": _MockEdge("a", "b"),
        "e2": _MockEdge("b", "c"),
        "e3": _MockEdge("c", "d"),
    }
    return _MockGraph(nodes, edges)


def _diamond_graph():
    """
    A → B → D
    A → C → D
    """
    nodes = {
        "a": _MockNode("a", "schema.table_a"),
        "b": _MockNode("b", "schema.table_b"),
        "c": _MockNode("c", "schema.table_c"),
        "d": _MockNode("d", "schema.table_d"),
    }
    edges = {
        "e1": _MockEdge("a", "b"),
        "e2": _MockEdge("a", "c"),
        "e3": _MockEdge("b", "d"),
        "e4": _MockEdge("c", "d"),
    }
    return _MockGraph(nodes, edges)


# ---------------------------------------------------------------------------
# Profiles dict helper
# ---------------------------------------------------------------------------

def _make_profiles(*profile_tuples):
    """Build profiles dict from (id, name, config_dict) tuples."""
    result = {}
    for pid, name, config in profile_tuples:
        result[pid] = {"name": name, **config}
    return result


# ---------------------------------------------------------------------------
# Tests: config extraction
# ---------------------------------------------------------------------------

class TestConfigExtraction:
    def test_freshness_config_extraction(self):
        config = {"enabled": True, "maxHours": 6, "warningHours": 3}
        fields = _extract_fields_from_config(config, "freshnessConfig")
        assert fields["freshness_enabled"] is True
        assert fields["freshness_max_hours"] == 6
        assert fields["freshness_warning_hours"] == 3

    def test_none_config_returns_empty(self):
        assert _extract_fields_from_config(None, "freshnessConfig") == {}

    def test_unknown_config_key_returns_empty(self):
        assert _extract_fields_from_config({"foo": 1}, "unknownConfig") == {}

    def test_ingestion_config_extraction(self):
        config = {"syncLagToleranceMinutes": 30, "failureTolerance": "strict", "schemaDriftStrictness": "warn"}
        fields = _extract_fields_from_config(config, "ingestionConfig")
        assert fields["sync_lag_tolerance_minutes"] == 30
        assert fields["failure_tolerance"] == "strict"
        assert fields["schema_drift_strictness"] == "warn"

    def test_bi_config_extraction(self):
        config = {"freshnessHours": 4, "contentHealthEnabled": True, "upstreamBreakStrictness": "strict"}
        fields = _extract_fields_from_config(config, "biConfig")
        assert fields["bi_freshness_hours"] == 4
        assert fields["content_health_enabled"] is True
        assert fields["upstream_break_strictness"] == "strict"

    def test_extract_all_fields_from_profile(self):
        profile = BUILTIN_PROFILES["Critical SLA"]
        fields = _extract_all_fields_from_profile(profile)
        assert fields["freshness_max_hours"] == 2
        assert fields["schema_strictness"] == "strict"
        assert fields["anomaly_sensitivity"] == 0.99
        assert fields["quality_max_null_rate"] == 0.01



# ---------------------------------------------------------------------------
# Tests: resolution chain precedence
# ---------------------------------------------------------------------------

class TestResolutionPrecedence:
    def test_builtin_fallback_when_no_assignments(self):
        """Layer 7: builtin fallback based on criticality mapping."""
        policy = resolve_policy(
            node_fqn="db.schema.my_table",
            node_domain="warehouse",
            node_criticality="critical",
            assignments=[],
            profiles={},
        )
        assert policy.source == "builtin"
        assert policy.profile_name == "Critical SLA"
        assert policy.freshness_max_hours == 2
        assert policy.schema_strictness == "strict"

    def test_builtin_fallback_medium_criticality(self):
        policy = resolve_policy(
            node_fqn="db.schema.my_table",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=[],
            profiles={},
        )
        assert policy.profile_name == "Standard"
        assert policy.freshness_max_hours == 12

    def test_builtin_fallback_low_criticality(self):
        policy = resolve_policy(
            node_fqn="db.schema.my_table",
            node_domain="warehouse",
            node_criticality="low",
            assignments=[],
            profiles={},
        )
        assert policy.profile_name == "Relaxed"
        assert policy.freshness_max_hours == 48

    def test_direct_profile_overrides_builtin(self):
        """Layer 3 beats Layer 7."""
        profiles = _make_profiles(
            ("p1", "Custom", {
                "freshnessConfig": {"enabled": True, "maxHours": 4, "warningHours": 2},
            }),
        )
        assignments = [
            {"assignmentType": "direct", "nodeFqn": "db.schema.t1", "profileId": "p1"},
        ]
        policy = resolve_policy(
            node_fqn="db.schema.t1",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
        )
        assert policy.source == "direct_profile"
        assert policy.profile_name == "Custom"
        assert policy.freshness_max_hours == 4
        # Fields not set in custom profile fall through to builtin
        assert policy.schema_strictness == "warn"  # from Standard builtin

    def test_direct_override_beats_direct_profile(self):
        """Layer 2 beats Layer 3."""
        profiles = _make_profiles(
            ("p1", "Standard", {
                "freshnessConfig": {"enabled": True, "maxHours": 12, "warningHours": 6},
            }),
        )
        assignments = [
            {
                "assignmentType": "direct",
                "nodeFqn": "db.schema.t1",
                "profileId": "p1",
                "overrides": {
                    "freshnessConfig": {"maxHours": 3},
                },
            },
        ]
        policy = resolve_policy(
            node_fqn="db.schema.t1",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
        )
        assert policy.source == "direct_override"
        assert policy.freshness_max_hours == 3
        # Non-overridden fields come from the profile
        assert policy.freshness_warning_hours == 6

    def test_domain_default_used_when_no_direct(self):
        """Layer 6: domain default."""
        profiles = _make_profiles(
            ("p1", "BI Custom", {
                "biConfig": {"freshnessHours": 8, "contentHealthEnabled": True},
            }),
        )
        assignments = [
            {"assignmentType": "domain_default", "nodeDomain": "bi", "profileId": "p1"},
        ]
        policy = resolve_policy(
            node_fqn="bi.dashboard.d1",
            node_domain="bi",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
        )
        assert policy.source == "domain_default"
        assert policy.bi_freshness_hours == 8

    def test_criticality_default_beats_domain_default(self):
        """Layer 6 beats Layer 7."""
        profiles = _make_profiles(
            ("p1", "Crit Default", {
                "freshnessConfig": {"maxHours": 3},
            }),
            ("p2", "Domain Default", {
                "freshnessConfig": {"maxHours": 24},
            }),
        )
        assignments = [
            {"assignmentType": "criticality_default", "nodeDomain": "warehouse", "nodeCriticality": "critical", "profileId": "p1"},
            {"assignmentType": "domain_default", "nodeDomain": "warehouse", "profileId": "p2"},
        ]
        policy = resolve_policy(
            node_fqn="db.schema.t1",
            node_domain="warehouse",
            node_criticality="critical",
            assignments=assignments,
            profiles=profiles,
        )
        assert policy.source == "criticality_default"
        assert policy.freshness_max_hours == 3

    def test_auto_discovered_used_when_no_direct_or_branch(self):
        """auto_discovered layer sits between branch and criticality_default."""
        profiles = _make_profiles(
            ("p1", "Auto-discovered: db.schema.t1", {
                "freshnessConfig": {"enabled": True, "maxHours": 6, "warningHours": 3},
            }),
        )
        assignments = [
            {
                "assignmentType": "auto_discovered",
                "nodeFqn": "db.schema.t1",
                "profileId": "p1",
            },
        ]
        policy = resolve_policy(
            node_fqn="db.schema.t1",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
        )
        assert policy.source == "auto_discovered"
        assert policy.freshness_max_hours == 6
        assert policy.freshness_warning_hours == 3

    def test_direct_beats_auto_discovered(self):
        """direct_profile takes precedence over auto_discovered."""
        profiles = _make_profiles(
            ("p1", "User Profile", {
                "freshnessConfig": {"enabled": True, "maxHours": 2, "warningHours": 1},
            }),
            ("p2", "Auto-discovered: db.schema.t1", {
                "freshnessConfig": {"enabled": True, "maxHours": 12, "warningHours": 6},
            }),
        )
        assignments = [
            {"assignmentType": "direct", "nodeFqn": "db.schema.t1", "profileId": "p1"},
            {"assignmentType": "auto_discovered", "nodeFqn": "db.schema.t1", "profileId": "p2"},
        ]
        policy = resolve_policy(
            node_fqn="db.schema.t1",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
        )
        assert policy.source == "direct_profile"
        assert policy.freshness_max_hours == 2


# ---------------------------------------------------------------------------
# Tests: field-by-field merge (null fields fall through)
# ---------------------------------------------------------------------------

class TestFieldByFieldMerge:
    def test_null_fields_fall_through_to_lower_layer(self):
        """Direct profile sets freshness only; schema comes from builtin."""
        profiles = _make_profiles(
            ("p1", "Freshness Only", {
                "freshnessConfig": {"enabled": True, "maxHours": 5},
            }),
        )
        assignments = [
            {"assignmentType": "direct", "nodeFqn": "db.schema.t1", "profileId": "p1"},
        ]
        policy = resolve_policy(
            node_fqn="db.schema.t1",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
        )
        assert policy.freshness_max_hours == 5  # from direct
        assert policy.schema_strictness == "warn"  # from Standard builtin
        assert policy.anomaly_sensitivity == 0.95  # from Standard builtin

    def test_each_field_resolved_independently(self):
        """Override sets one field, profile sets another, builtin fills rest."""
        profiles = _make_profiles(
            ("p1", "Mixed", {
                "freshnessConfig": {"maxHours": 10},
                "schemaConfig": {"strictness": "ignore"},
            }),
        )
        assignments = [
            {
                "assignmentType": "direct",
                "nodeFqn": "db.schema.t1",
                "profileId": "p1",
                "overrides": {
                    "freshnessConfig": {"maxHours": 2},
                    # schema not overridden
                },
            },
        ]
        policy = resolve_policy(
            node_fqn="db.schema.t1",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
        )
        assert policy.freshness_max_hours == 2  # override
        assert policy.schema_strictness == "ignore"  # from profile (not overridden)
        assert policy.anomaly_sensitivity == 0.95  # builtin Standard


# ---------------------------------------------------------------------------
# Tests: branch assignment
# ---------------------------------------------------------------------------

class TestBranchAssignment:
    def test_branch_covers_downstream_node(self):
        """Branch from A covers C (2 hops downstream)."""
        graph = _simple_graph()  # A → B → C → D
        profiles = _make_profiles(
            ("p1", "Branch Profile", {
                "freshnessConfig": {"maxHours": 6},
            }),
        )
        assignments = [
            {"assignmentType": "branch", "branchRootFqn": "schema.table_a", "profileId": "p1"},
        ]
        policy = resolve_policy(
            node_fqn="schema.table_c",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
            graph=graph,
        )
        assert policy.source == "branch"
        assert policy.freshness_max_hours == 6

    def test_branch_does_not_cover_upstream(self):
        """Branch from C does NOT cover A (upstream, not downstream)."""
        graph = _simple_graph()  # A → B → C → D
        profiles = _make_profiles(
            ("p1", "Branch Profile", {
                "freshnessConfig": {"maxHours": 6},
            }),
        )
        assignments = [
            {"assignmentType": "branch", "branchRootFqn": "schema.table_c", "profileId": "p1"},
        ]
        policy = resolve_policy(
            node_fqn="schema.table_a",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
            graph=graph,
        )
        # Not covered by branch — falls back to builtin
        assert policy.source == "builtin"

    def test_nearest_ancestor_wins(self):
        """Two branches: A→...→D and C→D. C is closer, so C's policy wins."""
        graph = _simple_graph()  # A → B → C → D
        profiles = _make_profiles(
            ("p1", "Far Branch", {"freshnessConfig": {"maxHours": 24}}),
            ("p2", "Near Branch", {"freshnessConfig": {"maxHours": 3}}),
        )
        assignments = [
            {"assignmentType": "branch", "branchRootFqn": "schema.table_a", "profileId": "p1"},
            {"assignmentType": "branch", "branchRootFqn": "schema.table_c", "profileId": "p2"},
        ]
        policy = resolve_policy(
            node_fqn="schema.table_d",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
            graph=graph,
        )
        assert policy.freshness_max_hours == 3  # nearest ancestor (C, distance 1)
        assert policy.profile_name == "Near Branch"

    def test_equidistant_branch_tiebreak_alphabetical(self):
        """Diamond: A→B→D, A→C→D. Both B and C are distance 1 from D.
        Alphabetical by branchRootFqn: B < C, so B wins."""
        graph = _diamond_graph()
        profiles = _make_profiles(
            ("p1", "Profile B", {"freshnessConfig": {"maxHours": 5}}),
            ("p2", "Profile C", {"freshnessConfig": {"maxHours": 10}}),
        )
        assignments = [
            {"assignmentType": "branch", "branchRootFqn": "schema.table_b", "profileId": "p1"},
            {"assignmentType": "branch", "branchRootFqn": "schema.table_c", "profileId": "p2"},
        ]
        policy = resolve_policy(
            node_fqn="schema.table_d",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
            graph=graph,
        )
        assert policy.freshness_max_hours == 5  # B wins alphabetically
        assert policy.profile_name == "Profile B"

    def test_branch_without_graph_is_skipped(self):
        """Branch assignments are ignored when no graph is provided."""
        profiles = _make_profiles(
            ("p1", "Branch Only", {"freshnessConfig": {"maxHours": 3}}),
        )
        assignments = [
            {"assignmentType": "branch", "branchRootFqn": "schema.table_a", "profileId": "p1"},
        ]
        policy = resolve_policy(
            node_fqn="schema.table_c",
            node_domain="warehouse",
            node_criticality="medium",
            assignments=assignments,
            profiles=profiles,
            graph=None,
        )
        # Falls to builtin
        assert policy.source == "builtin"


# ---------------------------------------------------------------------------
# Tests: branch distance computation
# ---------------------------------------------------------------------------

class TestBranchDistances:
    def test_simple_distances(self):
        graph = _simple_graph()  # A → B → C → D
        assignments = [
            {"branchRootFqn": "schema.table_a"},
        ]
        result = _compute_branch_distances("schema.table_c", assignments, graph)
        assert len(result) == 1
        assert result[0][1] == 2  # distance from A to C

    def test_unreachable_node_not_included(self):
        graph = _simple_graph()
        assignments = [
            {"branchRootFqn": "schema.table_c"},
        ]
        # A is upstream of C, not downstream
        result = _compute_branch_distances("schema.table_a", assignments, graph)
        assert len(result) == 0

    def test_sort_by_distance_then_alphabetical(self):
        graph = _simple_graph()  # A → B → C → D
        assignments = [
            {"branchRootFqn": "schema.table_a"},  # distance 3 to D
            {"branchRootFqn": "schema.table_c"},  # distance 1 to D
        ]
        result = _compute_branch_distances("schema.table_d", assignments, graph)
        assert len(result) == 2
        assert result[0][1] == 1  # nearest first
        assert result[1][1] == 3


# ---------------------------------------------------------------------------
# Tests: builtin profiles and criticality mapping
# ---------------------------------------------------------------------------

class TestBuiltinProfiles:
    def test_all_expected_profiles_exist(self):
        expected = {"Critical SLA", "Standard", "Relaxed", "BI Shield", "Source Guard"}
        assert set(BUILTIN_PROFILES.keys()) == expected

    def test_criticality_mapping(self):
        assert CRITICALITY_PROFILE_MAP["critical"] == "Critical SLA"
        assert CRITICALITY_PROFILE_MAP["high"] == "Critical SLA"
        assert CRITICALITY_PROFILE_MAP["medium"] == "Standard"
        assert CRITICALITY_PROFILE_MAP["low"] == "Relaxed"

    def test_unknown_criticality_defaults_to_standard(self):
        """When criticality is unknown, builtin fallback uses Standard."""
        policy = resolve_policy(
            node_fqn="db.schema.t1",
            node_domain="warehouse",
            node_criticality="unknown",
            assignments=[],
            profiles={},
        )
        assert policy.profile_name == "Standard"


# ---------------------------------------------------------------------------
# Tests: bulk resolution
# ---------------------------------------------------------------------------

class TestBulkResolution:
    def test_bulk_resolves_multiple_nodes(self):
        nodes = [
            {"fqn": "db.schema.t1", "domain": "warehouse", "criticality": "critical"},
            {"fqn": "db.schema.t2", "domain": "warehouse", "criticality": "low"},
        ]
        results = resolve_policies_bulk(nodes, assignments=[], profiles={})
        assert "db.schema.t1" in results
        assert "db.schema.t2" in results
        assert results["db.schema.t1"].profile_name == "Critical SLA"
        assert results["db.schema.t2"].profile_name == "Relaxed"



# ---------------------------------------------------------------------------
# Tests: policy status (for UI badges)
# ---------------------------------------------------------------------------

class TestPolicyStatus:
    def test_direct_assignment_returns_assigned(self):
        assignments = [
            {"assignmentType": "direct", "nodeFqn": "db.t1", "profileId": "p1"},
        ]
        assert get_policy_status("db.t1", assignments) == "assigned"

    def test_direct_with_overrides_returns_override(self):
        assignments = [
            {"assignmentType": "direct", "nodeFqn": "db.t1", "profileId": "p1", "overrides": {"freshnessConfig": {"maxHours": 1}}},
        ]
        assert get_policy_status("db.t1", assignments) == "override"

    def test_branch_coverage_returns_inherited(self):
        graph = _simple_graph()
        assignments = [
            {"assignmentType": "branch", "branchRootFqn": "schema.table_a", "profileId": "p1"},
        ]
        assert get_policy_status("schema.table_c", assignments, graph=graph) == "inherited"

    def test_no_assignment_returns_none(self):
        assert get_policy_status("db.t1", []) == "none"

    def test_branch_without_graph_returns_none(self):
        assignments = [
            {"assignmentType": "branch", "branchRootFqn": "schema.table_a", "profileId": "p1"},
        ]
        assert get_policy_status("schema.table_c", assignments, graph=None) == "none"
