"""Tests for classify_data_plane_role — capability-based role classification."""

import pytest

from scanner.lineage.graph import (
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.zones import (
    DataPlaneRole,
    classify_data_plane_role,
)


def _node(
    name: str = "n",
    node_type: NodeType = NodeType.TABLE,
    platform: str = "bigquery",
    platform_domain: PlatformDomain = PlatformDomain.WAREHOUSE,
    schema: str = "",
    fqn: str = "",
    raw_metadata: dict = None,
) -> LineageNode:
    return LineageNode(
        id=f"node:{platform}:{name}",
        name=name,
        fqn=fqn or f"db.{schema}.{name}",
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        schema=schema,
        raw_metadata=raw_metadata or {},
    )


def test_external_source_no_upstream_not_warehouse_returns_source():
    n = _node(platform="postgres_app", platform_domain=PlatformDomain.APP)
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=False, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.SOURCE.value


def test_dbt_source_in_warehouse_returns_source():
    n = _node(
        platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        raw_metadata={"dbt_resource_type": "source"},
    )
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=False, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.SOURCE.value


def test_fivetran_connector_returns_ingest():
    n = _node(platform="fivetran", platform_domain=PlatformDomain.INGESTION,
              node_type=NodeType.CONNECTOR)
    role = classify_data_plane_role(
        n, canonical_type="job",
        has_upstream_data_edges=False, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.INGEST.value


def test_raw_warehouse_table_returns_store_raw():
    n = _node(schema="raw", name="users")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.STORE_RAW.value


def test_dbt_staging_model_returns_transform():
    n = _node(schema="analytics_staging", name="stg_users")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.TRANSFORM.value


def test_mart_table_returns_store_serve():
    n = _node(schema="marts", name="dim_users")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.STORE_SERVE.value


def test_looker_dashboard_returns_serve():
    n = _node(platform="looker", platform_domain=PlatformDomain.BI,
              node_type=NodeType.DASHBOARD)
    role = classify_data_plane_role(
        n, canonical_type="semantic",
        has_upstream_data_edges=True, has_downstream_data_edges=False,
    )
    assert role == DataPlaneRole.SERVE.value


def test_hightouch_destination_returns_activate():
    n = _node(platform="hightouch", platform_domain=PlatformDomain.OTHER)
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=False,
    )
    assert role == DataPlaneRole.ACTIVATE.value


def test_explicit_activation_metadata_returns_activate():
    n = _node(platform="custom", raw_metadata={"activation_target": True})
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=False,
    )
    assert role == DataPlaneRole.ACTIVATE.value


def test_unknown_zone_leaf_returns_store_serve():
    n = _node(schema="custom", name="thing_table")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=False,
    )
    assert role == DataPlaneRole.STORE_SERVE.value


def test_unknown_zone_root_returns_store_raw():
    n = _node(schema="custom", name="thing_table")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=False, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.STORE_RAW.value


def test_unknown_zone_middle_returns_transform():
    n = _node(schema="custom", name="thing_table")
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.TRANSFORM.value


def test_dbt_source_with_generic_schema_and_upstream_returns_store_raw():
    """A dbt source node should land in STORE_RAW even with generic schema name,
    and even when has_upstream_data_edges=True (which triggers the inline
    RAW-vs-UNKNOWN heuristic for non-source nodes)."""
    n = _node(
        platform="bigquery", platform_domain=PlatformDomain.WAREHOUSE,
        schema="", name="n",
        raw_metadata={"dbt_resource_type": "source"},
    )
    role = classify_data_plane_role(
        n, canonical_type="dataset",
        has_upstream_data_edges=True, has_downstream_data_edges=True,
    )
    assert role == DataPlaneRole.STORE_RAW.value
