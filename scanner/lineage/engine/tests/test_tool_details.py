"""
Tests for tool-details Inspector Panel responses.

Verifies:
1. Airflow DAG deduplication (real DAG + tasks → no synthetic duplicates)
2. dbt merged nodes matched via discovered_platforms and metadata fallback
3. Category-specific tab keys for each domain
"""

import pytest

from scanner.lineage.graph import (
    LineageGraph,
    LineageNode,
    NodeType,
    PlatformDomain,
)
from scanner.lineage.engine.canonical import canonicalize_graph_in_place
from scanner.lineage.engine.views import ViewBuilder


# ---- Helpers (same pattern as test_lane_overview.py) ----

def _make_node(
    name: str,
    node_type: NodeType,
    platform: str,
    platform_domain: PlatformDomain,
    database: str = None,
    schema: str = None,
    fqn: str = None,
    integration_id: str = None,
    raw_metadata: dict = None,
) -> LineageNode:
    node = LineageNode(
        id=f"node:{platform}:{name}",
        name=name,
        fqn=fqn or f"{database or ''}.{schema or ''}.{name}".strip("."),
        node_type=node_type,
        platform=platform,
        platform_domain=platform_domain,
        database=database,
        schema=schema,
        integration_id=integration_id,
    )
    if raw_metadata:
        node.raw_metadata = raw_metadata
    return node


# ---- Test 1: Airflow DAG deduplication ----

def test_airflow_dag_no_duplicates():
    """DAG nodes with dag_id in raw_metadata should not produce synthetic duplicates."""
    graph = LineageGraph()

    # Real DAG node (as produced by _make_dag_node after fix)
    dag_node = _make_node(
        "etl_pipeline", NodeType.DAG, "airflow",
        PlatformDomain.ORCHESTRATION,
        raw_metadata={
            "dag_id": "etl_pipeline",
            "schedule": "0 * * * *",
            "task_count": 3,
        },
    )

    # Task nodes referencing same dag_id
    task1 = _make_node(
        "extract", NodeType.TASK, "airflow",
        PlatformDomain.ORCHESTRATION,
        raw_metadata={"dag_id": "etl_pipeline", "operator": "PythonOperator"},
    )
    task2 = _make_node(
        "transform", NodeType.TASK, "airflow",
        PlatformDomain.ORCHESTRATION,
        raw_metadata={"dag_id": "etl_pipeline", "operator": "PythonOperator"},
    )
    task3 = _make_node(
        "load", NodeType.TASK, "airflow",
        PlatformDomain.ORCHESTRATION,
        raw_metadata={"dag_id": "etl_pipeline", "operator": "BigQueryOperator"},
    )

    for n in [dag_node, task1, task2, task3]:
        graph.add_node(n)

    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])
    result = builder.build_tool_details("tool:airflow")

    dags = result["groups"]["dags"]
    tasks = result["groups"]["tasks"]

    # Only 1 DAG, not 2 (no synthetic duplicate)
    assert len(dags) == 1, f"Expected 1 DAG, got {len(dags)}: {[d['name'] for d in dags]}"
    assert dags[0]["name"] == "etl_pipeline"

    # All 3 tasks present
    assert len(tasks) == 3

    # DAG has correct task count from itemCount
    assert dags[0].get("itemCount") == 3

    # DAG metadata enriched with schedule
    assert dags[0]["metadata"].get("schedule") == "0 * * * *"


# ---- Test 2: DAG name fallback via node.name ----

def test_orchestration_dag_name_fallback():
    """DAG nodes without dag_id in metadata should still prevent synthetic duplicates via node.name."""
    graph = LineageGraph()

    # DAG node WITHOUT dag_id in raw_metadata (pre-fix adapter scenario)
    dag_node = _make_node(
        "my_dag", NodeType.DAG, "airflow",
        PlatformDomain.ORCHESTRATION,
        raw_metadata={"schedule": "daily"},
    )

    task_node = _make_node(
        "my_task", NodeType.TASK, "airflow",
        PlatformDomain.ORCHESTRATION,
        raw_metadata={"dag_id": "my_dag", "operator": "BashOperator"},
    )

    for n in [dag_node, task_node]:
        graph.add_node(n)

    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])
    result = builder.build_tool_details("tool:airflow")

    dags = result["groups"]["dags"]
    # Should be 1 DAG (real), not 2 (real + synthetic)
    assert len(dags) == 1, f"Expected 1 DAG, got {len(dags)}: {[d['name'] for d in dags]}"
    assert dags[0]["name"] == "my_dag"


# ---- Test 3: dbt merged nodes matched via discovered_platforms ----

def test_dbt_merged_nodes_matched():
    """Nodes with platform=bigquery but dbt in discovered_platforms should appear in dbt tool details."""
    graph = LineageGraph()

    # Simulates a post-resolver merged node:
    # platform=bigquery wins, but dbt metadata preserved
    merged_node = _make_node(
        "stg_orders", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="staging",
        raw_metadata={
            "discovered_platforms": ["bigquery", "dbt"],
            "dbt_resource_type": "model",
            "dbt_unique_id": "model.my_project.stg_orders",
            "materialized": "view",
        },
    )
    graph.add_node(merged_node)

    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])

    # Should match when requesting dbt tool details
    result = builder.build_tool_details("tool:dbt")
    assert result["category"] == "transformation"
    assert result["summary"]["totalAssets"] == 1
    assert len(result["groups"]["models"]) == 1
    assert result["groups"]["models"][0]["name"] == "stg_orders"


# ---- Test 4: dbt metadata fallback (no discovered_platforms) ----

def test_dbt_metadata_fallback_matching():
    """Nodes with dbt_resource_type but missing discovered_platforms should still match dbt tool."""
    graph = LineageGraph()

    # Edge case: discovered_platforms is missing or empty
    node = _make_node(
        "fct_revenue", NodeType.VIEW, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="marts",
        raw_metadata={
            "dbt_resource_type": "model",
            "dbt_unique_id": "model.my_project.fct_revenue",
        },
    )
    graph.add_node(node)

    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])

    result = builder.build_tool_details("tool:dbt")
    assert result["summary"]["totalAssets"] == 1
    assert len(result["groups"]["models"]) == 1
    assert result["groups"]["models"][0]["name"] == "fct_revenue"


# ---- Test 5: Category tab keys ----

# ---- Test 5: dbt with integration_id — THE PRODUCTION BUG ----

def test_dbt_integration_id_cross_tool_match():
    """Merged nodes must match dbt tool details even when tool has an integration_id
    and the merged node carries BigQuery's integration_id (not dbt's).

    This is the exact production scenario:
    - Pipeline has dbt configured with integration_id "dbt_int_001"
    - After resolver merge, dbt models have platform=bigquery, integration_id="bq_int_002"
    - Lane overview creates tool:dbt:dbt_int_001
    - build_tool_details("tool:dbt:dbt_int_001") must find these merged nodes
    """
    graph = LineageGraph()

    # Merged node: platform=bigquery (BQ wins), integration_id=BQ's
    merged1 = _make_node(
        "stg_customers", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="staging",
        integration_id="bq_int_002",
        raw_metadata={
            "discovered_platforms": ["bigquery", "dbt"],
            "dbt_resource_type": "model",
            "materialized": "view",
        },
    )
    merged2 = _make_node(
        "fct_orders", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="marts",
        integration_id="bq_int_002",
        raw_metadata={
            "discovered_platforms": ["bigquery", "dbt"],
            "dbt_resource_type": "model",
            "materialized": "table",
        },
    )
    # Pure BQ node (should NOT appear in dbt tool details)
    bq_only = _make_node(
        "raw_events", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="raw",
        integration_id="bq_int_002",
    )

    for n in [merged1, merged2, bq_only]:
        graph.add_node(n)

    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])

    # Request with dbt's integration_id (as lane overview would send)
    result = builder.build_tool_details("tool:dbt:dbt_int_001")

    # Must find 2 merged dbt models, NOT 0
    assert result["summary"]["totalAssets"] == 2, (
        f"Expected 2 dbt models, got {result['summary']['totalAssets']}. "
        f"Integration_id filter must not block cross-tool matches."
    )
    assert len(result["groups"]["models"]) == 2
    model_names = {m["name"] for m in result["groups"]["models"]}
    assert model_names == {"stg_customers", "fct_orders"}


def test_dbt_metadata_fallback_with_integration_id():
    """Same as above but using dbt_resource_type fallback (no discovered_platforms)."""
    graph = LineageGraph()

    node = _make_node(
        "dim_users", NodeType.VIEW, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="marts",
        integration_id="bq_int_002",
        raw_metadata={
            "dbt_resource_type": "model",
            "dbt_unique_id": "model.my_project.dim_users",
        },
    )
    graph.add_node(node)

    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])

    result = builder.build_tool_details("tool:dbt:dbt_int_001")
    assert result["summary"]["totalAssets"] == 1
    assert result["groups"]["models"][0]["name"] == "dim_users"


# ---- Test 7: Category tab keys ----

@pytest.mark.parametrize("platform,expected_category,expected_tab_keys", [
    ("fivetran", "ingestion", ["connectors", "destinations"]),
    ("dbt", "transformation", ["models", "tests", "exposures"]),
    ("airflow", "orchestration", ["dags", "tasks"]),
    ("bigquery", "warehouse", ["datasets", "tables"]),
    ("looker", "reporting", ["dashboards", "explores"]),
    ("linux", "infrastructure", ["services", "hosts"]),
    ("elementary", "quality", ["monitors", "status"]),
])
def test_category_tab_keys(platform, expected_category, expected_tab_keys):
    """Each category should produce the correct tab keys."""
    graph = LineageGraph()
    builder = ViewBuilder(graph, tool_nodes=[])
    result = builder.build_tool_details(f"tool:{platform}")

    tab_keys = [t["key"] for t in result["tabs"]]
    assert tab_keys == expected_tab_keys, f"For {platform}: expected {expected_tab_keys}, got {tab_keys}"
    assert result["category"] == expected_category


# ---- Test 8: Lane-prefixed tool_view_id parsing ----

def test_lane_prefixed_tool_view_id():
    """build_tool_details must handle lane-prefixed IDs from build_lane_pipeline_overview.

    Lane overview returns IDs like "tool:transformation:dbt_core:int_001"
    but build_tool_details must strip the lane segment to get platform+integration_id.
    """
    graph = LineageGraph()

    # A dbt model node
    node = _make_node(
        "stg_orders", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="staging",
        raw_metadata={
            "discovered_platforms": ["bigquery", "dbt"],
            "dbt_resource_type": "model",
        },
    )
    graph.add_node(node)
    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])

    # Lane-prefixed format (what the UI actually sends)
    result = builder.build_tool_details("tool:transformation:dbt")
    assert result["category"] == "transformation"
    assert result["summary"]["totalAssets"] == 1

    # With integration_id
    result2 = builder.build_tool_details("tool:transformation:dbt:some_int_id")
    assert result2["category"] == "transformation"

    # Non-lane format (backward compat)
    result3 = builder.build_tool_details("tool:dbt")
    assert result3["category"] == "transformation"
    assert result3["summary"]["totalAssets"] == 1


def test_lane_prefixed_warehouse():
    """Warehouse tools with lane prefix should parse correctly."""
    graph = LineageGraph()

    node = _make_node(
        "raw_events", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="raw",
        integration_id="bq_int_001",
    )
    graph.add_node(node)
    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])

    # Lane-prefixed with integration_id
    result = builder.build_tool_details("tool:warehouse_raw:bigquery:bq_int_001")
    assert result["category"] == "warehouse"
    assert result["summary"]["totalAssets"] == 1
    assert result["platform"] == "bigquery"

    # Without lane (backward compat)
    result2 = builder.build_tool_details("tool:bigquery:bq_int_001")
    assert result2["category"] == "warehouse"
    assert result2["summary"]["totalAssets"] == 1


# ---- Test 9: Lane overview cross-tool asset counting ----

def test_lane_overview_dbt_asset_count_after_merge():
    """Lane overview must count merged dbt models under the dbt tool card,
    not just under BigQuery. This is the root cause of 'dbt shows nothing'."""
    graph = LineageGraph()

    # Merged node: platform=bigquery, but discovered_platforms includes dbt
    merged = _make_node(
        "stg_orders", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="staging",
        integration_id="bq_int_001",
        raw_metadata={
            "discovered_platforms": ["bigquery", "dbt"],
            "dbt_resource_type": "model",
        },
    )
    # Pure BQ node
    raw_table = _make_node(
        "raw_events", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="raw",
        integration_id="bq_int_001",
    )

    for n in [merged, raw_table]:
        graph.add_node(n)

    canonicalize_graph_in_place(graph.nodes, graph.edges)

    # dbt tool from pipeline stack (not in graph)
    tool_nodes = [
        {"toolType": "dbt_core", "integrationId": "dbt_int_001", "name": "dbt"},
    ]
    builder = ViewBuilder(graph, tool_nodes=tool_nodes)
    view = builder.build_lane_pipeline_overview()

    # Find the dbt tool ViewNode
    dbt_nodes = [n for n in view.nodes if "dbt" in (n.platform or "").lower()]
    assert len(dbt_nodes) >= 1, (
        f"dbt tool not found in lane overview. Nodes: {[(n.name, n.platform) for n in view.nodes]}"
    )
    dbt_node = dbt_nodes[0]
    dbt_asset_count = dbt_node.metadata.get("assetCount", 0)

    # Must show at least 1 asset (the merged model), NOT 0
    assert dbt_asset_count >= 1, (
        f"dbt tool shows {dbt_asset_count} assets, expected >=1. "
        f"Merged nodes must be counted under dbt too."
    )


def test_lane_overview_dbt_metadata_fallback_counting():
    """Nodes with dbt_resource_type but no discovered_platforms should still
    be counted under the dbt tool in the lane overview."""
    graph = LineageGraph()

    node = _make_node(
        "fct_revenue", NodeType.VIEW, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="marts",
        integration_id="bq_int_001",
        raw_metadata={
            "dbt_resource_type": "model",
        },
    )
    graph.add_node(node)

    canonicalize_graph_in_place(graph.nodes, graph.edges)

    tool_nodes = [
        {"toolType": "dbt_core", "integrationId": "dbt_int_001", "name": "dbt"},
    ]
    builder = ViewBuilder(graph, tool_nodes=tool_nodes)
    view = builder.build_lane_pipeline_overview()

    dbt_nodes = [n for n in view.nodes if "dbt" in (n.platform or "").lower()]
    assert len(dbt_nodes) >= 1
    dbt_asset_count = dbt_nodes[0].metadata.get("assetCount", 0)
    assert dbt_asset_count >= 1, (
        f"dbt fallback counting failed: {dbt_asset_count} assets"
    )


# ---- Test 10: dbt sources should NOT appear as models ----

def test_dbt_sources_excluded_from_models():
    """After resolver merge, dbt sources (raw table refs) should NOT be matched
    as dbt models in tool details. They're metadata pointers, not models."""
    graph = LineageGraph()

    # A dbt model (should appear)
    model = _make_node(
        "stg_orders", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="staging",
        integration_id="bq_int_001",
        raw_metadata={
            "discovered_platforms": ["bigquery", "dbt"],
            "dbt_resource_type": "model",
            "dbt_unique_id": "model.my_project.stg_orders",
        },
    )
    # A raw table that was a dbt source (should NOT appear as dbt model)
    # After resolver merge: no dbt in discovered_platforms, no dbt_resource_type,
    # no dbt_unique_id (all blocked for sources)
    raw_table = _make_node(
        "customers", NodeType.TABLE, "bigquery",
        PlatformDomain.WAREHOUSE,
        database="analytics", schema="raw",
        integration_id="bq_int_001",
        raw_metadata={},  # source metadata stripped during merge
    )

    for n in [model, raw_table]:
        graph.add_node(n)

    canonicalize_graph_in_place(graph.nodes, graph.edges)
    builder = ViewBuilder(graph, tool_nodes=[])
    result = builder.build_tool_details("tool:dbt")

    # Only the model should appear, not the raw table
    assert result["summary"]["totalAssets"] == 1
    assert len(result["groups"]["models"]) == 1
    assert result["groups"]["models"][0]["name"] == "stg_orders"
