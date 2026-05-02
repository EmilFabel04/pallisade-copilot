"""Tests for endpoint classification."""

from scanner.lineage.graph import LineageNode, NodeType, PlatformDomain
from scanner.lineage.engine.endpoints import (
    EndpointKind,
    EndpointClassification,
    classify_endpoint,
)


def _node(
    name: str = "n",
    platform: str = "bigquery",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    raw_metadata: dict = None,
) -> LineageNode:
    return LineageNode(
        id=f"node:{platform}:{name}",
        name=name,
        fqn=f"db.s.{name}",
        node_type=NodeType.TABLE,
        platform=platform,
        platform_domain=platform_domain,
        raw_metadata=raw_metadata or {},
    )


def test_no_edges_returns_orphan():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=False, has_downstream=False)
    assert result.kind == EndpointKind.ORPHAN
    assert "no edges" in result.reason.lower()


def test_no_upstream_with_downstream_returns_source():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=False, has_downstream=True)
    assert result.kind == EndpointKind.SOURCE


def test_has_upstream_no_downstream_returns_sink():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=True, has_downstream=False)
    assert result.kind == EndpointKind.SINK


def test_both_edges_returns_internal():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=True, has_downstream=True)
    assert result.kind == EndpointKind.INTERNAL


def test_dbt_source_with_no_upstream_explicit_reason():
    n = _node(raw_metadata={"dbt_resource_type": "source"})
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=False, has_downstream=True)
    assert result.kind == EndpointKind.SOURCE
    assert "dbt source" in result.reason.lower()


def test_bi_node_with_no_downstream_high_confidence_sink():
    n = _node(platform="looker", platform_domain=PlatformDomain.BI)
    result = classify_endpoint(n, canonical_type="semantic",
                               has_upstream=True, has_downstream=False)
    assert result.kind == EndpointKind.SINK
    assert result.confidence >= 0.9


def test_warehouse_leaf_lower_confidence_sink():
    """A leaf table without a known terminal role: maybe unused, not a real sink."""
    n = _node(name="forgotten_table")
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=True, has_downstream=False)
    assert result.kind == EndpointKind.SINK
    assert result.confidence < 0.7  # lower confidence: could be unused, not terminal


def test_classification_serializable():
    n = _node()
    result = classify_endpoint(n, canonical_type="dataset",
                               has_upstream=True, has_downstream=True)
    d = result.to_dict()
    assert d["kind"] == "internal"
    assert "reason" in d
    assert "confidence" in d
