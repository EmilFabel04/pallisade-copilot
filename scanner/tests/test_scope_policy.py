"""Tests for scope policy integration — priority scoring with policy bonus."""

from __future__ import annotations

import pytest

from scanner.lineage.graph import (
    AssetKind,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.monitors.scope import _node_priority_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(
    id: str = "n1",
    name: str = "my_table",
    fqn: str = "db.schema.my_table",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    node_type: NodeType = NodeType.TABLE,
    asset_kind: AssetKind = AssetKind.TABLE,
    platform: str = "bigquery",
    criticality: str = "medium",
    downstream_count: int = 0,
) -> LineageNode:
    return LineageNode(
        id=id,
        name=name,
        fqn=fqn,
        node_type=node_type,
        platform_domain=platform_domain,
        asset_kind=asset_kind,
        platform=platform,
        criticality=criticality,
        downstream_count=downstream_count,
        columns=[],
    )


# ---------------------------------------------------------------------------
# Tests: policy-aware priority scoring
# ---------------------------------------------------------------------------

class TestPolicyPriorityBonus:
    def test_no_policy_status_no_bonus(self):
        node = _make_node()
        base_score = _node_priority_score(node, depth_from_anchor=1)
        none_score = _node_priority_score(node, depth_from_anchor=1, policy_status=None)
        assert base_score == none_score

    def test_assigned_gets_plus_10(self):
        node = _make_node()
        base_score = _node_priority_score(node, depth_from_anchor=1, policy_status=None)
        assigned_score = _node_priority_score(node, depth_from_anchor=1, policy_status="assigned")
        assert assigned_score == base_score + 10

    def test_override_gets_plus_10(self):
        node = _make_node()
        base_score = _node_priority_score(node, depth_from_anchor=1, policy_status=None)
        override_score = _node_priority_score(node, depth_from_anchor=1, policy_status="override")
        assert override_score == base_score + 10

    def test_inherited_gets_plus_5(self):
        node = _make_node()
        base_score = _node_priority_score(node, depth_from_anchor=1, policy_status=None)
        inherited_score = _node_priority_score(node, depth_from_anchor=1, policy_status="inherited")
        assert inherited_score == base_score + 5

    def test_none_status_no_bonus(self):
        node = _make_node()
        base_score = _node_priority_score(node, depth_from_anchor=1, policy_status=None)
        none_score = _node_priority_score(node, depth_from_anchor=1, policy_status="none")
        assert none_score == base_score

    def test_assigned_node_ranks_higher_than_unassigned(self):
        """A medium-criticality node with direct policy should rank above one without."""
        assigned_node = _make_node(id="a", criticality="medium", downstream_count=5)
        unassigned_node = _make_node(id="b", criticality="medium", downstream_count=5)

        assigned_score = _node_priority_score(assigned_node, depth_from_anchor=2, policy_status="assigned")
        unassigned_score = _node_priority_score(unassigned_node, depth_from_anchor=2, policy_status=None)
        assert assigned_score > unassigned_score

    def test_policy_bonus_stacks_with_criticality(self):
        """Policy bonus is additive with criticality scoring."""
        critical_node = _make_node(criticality="critical")
        low_node = _make_node(criticality="low")

        critical_score = _node_priority_score(critical_node, depth_from_anchor=1, policy_status="assigned")
        low_score = _node_priority_score(low_node, depth_from_anchor=1, policy_status="assigned")

        # Both get +10 from policy, but critical has higher base from criticality
        assert critical_score > low_score
