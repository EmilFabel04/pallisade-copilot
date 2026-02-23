"""
Tests for the LLM extractor's "strict accountant" normalization phase.

Covers:
- Identifier normalization (lowercase, FQN rebuild)
- Namespace filling from tool_configs
- Zone metadata enrichment
- Lightweight deduplication
- Edge validation (dangling, no-evidence)
- Confidence normalization
- Full pipeline: normalize → canonicalize → bridge
"""

import pytest

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
from scanner.lineage.engine.llm_extractor import (
    LLMExtractorConfig,
    LLMLineageExtractor,
)
from scanner.lineage.engine.investigator import ToolConfig
from scanner.lineage.engine.canonical import canonicalize_graph_in_place
from scanner.lineage.engine.bridge import BridgeRuleEngine
from scanner.lineage.engine.zones import DatasetZone, classify_dataset_zone
from scanner.lineage.engine.ids import generate_edge_id
from datetime import datetime, timezone


# ---- Helpers ----


def _make_extractor(**kwargs) -> LLMLineageExtractor:
    config = LLMExtractorConfig(**kwargs)
    return LLMLineageExtractor(config)


def _add_node(ext, node_id, name, node_type="table", platform="bigquery",
              platform_domain="warehouse", schema=None, database=None,
              namespace=None, zone_hint=None, dbt_path=None,
              dbt_resource_type=None, description=None):
    """Helper to add a node via the tool handler."""
    args = {
        "node_id": node_id,
        "name": name,
        "node_type": node_type,
        "platform": platform,
        "platform_domain": platform_domain,
    }
    if schema:
        args["schema"] = schema
    if database:
        args["database"] = database
    if namespace:
        args["namespace"] = namespace
    if zone_hint:
        args["zone_hint"] = zone_hint
    if dbt_path:
        args["dbt_path"] = dbt_path
    if dbt_resource_type:
        args["dbt_resource_type"] = dbt_resource_type
    if description:
        args["description"] = description
    return ext._tool_add_node(args)


def _add_edge(ext, source_id, target_id, edge_type="derived_from",
              confidence=0.8, evidence="test evidence"):
    """Helper to add an edge via the tool handler."""
    return ext._tool_add_edge({
        "source_id": source_id,
        "target_id": target_id,
        "edge_type": edge_type,
        "confidence": confidence,
        "evidence": evidence,
    })


# =====================================================================
# Normalize identifiers
# =====================================================================


class TestNormalizeIdentifiers:
    """Test _normalize_identifiers lowercases and rebuilds FQNs."""

    def test_lowercases_name_and_rebuilds_fqn(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.customers", "Customers",
                  schema="RAW", database="PROJ")
        ext._normalize_identifiers()

        node = ext._graph.nodes["bigquery:proj.raw.customers"]
        assert node.name == "customers"
        assert node.schema == "raw"
        assert node.database == "proj"
        assert node.fqn == "proj.raw.customers"

    def test_preserves_already_lowercase(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.orders", "orders",
                  schema="raw", database="proj")
        count = ext._normalize_identifiers()
        assert count == 0  # nothing changed

    def test_handles_missing_database_schema(self):
        ext = _make_extractor()
        _add_node(ext, "n8n:my_workflow", "My_Workflow",
                  node_type="workflow", platform="n8n",
                  platform_domain="orchestration")
        ext._normalize_identifiers()

        node = ext._graph.nodes["n8n:my_workflow"]
        assert node.name == "my_workflow"
        assert node.fqn == "my_workflow"


# =====================================================================
# Fill missing namespaces
# =====================================================================


class TestFillMissingNamespaces:
    """Test _fill_missing_namespaces from lookup and database fallback."""

    def test_fills_from_lookup(self):
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "my-project"}
        _add_node(ext, "bigquery:my-project.raw.customers", "customers",
                  schema="raw", database="my-project")

        filled = ext._fill_missing_namespaces()
        assert filled == 1
        node = ext._graph.nodes["bigquery:my-project.raw.customers"]
        assert node.namespace == "my-project"

    def test_fills_bigquery_from_database_fallback(self):
        ext = _make_extractor()
        ext._namespace_lookup = {}  # no lookup available
        _add_node(ext, "bigquery:proj.raw.orders", "orders",
                  schema="raw", database="proj")

        filled = ext._fill_missing_namespaces()
        assert filled == 1
        node = ext._graph.nodes["bigquery:proj.raw.orders"]
        assert node.namespace == "proj"

    def test_skips_nodes_with_existing_namespace(self):
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "other-project"}
        _add_node(ext, "bigquery:proj.raw.orders", "orders",
                  schema="raw", database="proj", namespace="proj")

        filled = ext._fill_missing_namespaces()
        assert filled == 0
        node = ext._graph.nodes["bigquery:proj.raw.orders"]
        assert node.namespace == "proj"  # unchanged

    def test_handles_unknown_platform(self):
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "proj"}
        _add_node(ext, "custom:thing", "thing", platform="custom_tool",
                  platform_domain="other")

        filled = ext._fill_missing_namespaces()
        assert filled == 0

    def test_fills_snowflake_from_lookup(self):
        ext = _make_extractor()
        ext._namespace_lookup = {"snowflake": "xy12345"}
        _add_node(ext, "snowflake:db.public.users", "users",
                  platform="snowflake", schema="public", database="db")

        filled = ext._fill_missing_namespaces()
        assert filled == 1
        assert ext._graph.nodes["snowflake:db.public.users"].namespace == "xy12345"


# =====================================================================
# Enrich zone metadata
# =====================================================================


class TestEnrichZoneMetadata:
    """Test _enrich_zone_metadata classifies and persists zones."""

    def test_raw_schema_gets_raw_zone(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.events", "events", schema="raw")

        enriched = ext._enrich_zone_metadata()
        assert enriched == 1
        node = ext._graph.nodes["bigquery:proj.raw.events"]
        assert node.raw_metadata["zone"] == "raw"

    def test_staging_prefix_gets_staging_zone(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.staging.stg_orders", "stg_orders",
                  schema="staging")

        enriched = ext._enrich_zone_metadata()
        assert enriched == 1
        assert ext._graph.nodes["bigquery:proj.staging.stg_orders"].raw_metadata["zone"] == "staging"

    def test_mart_prefix_gets_mart_zone(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.marts.dim_customers", "dim_customers",
                  schema="marts")

        enriched = ext._enrich_zone_metadata()
        assert enriched == 1
        assert ext._graph.nodes["bigquery:proj.marts.dim_customers"].raw_metadata["zone"] == "mart"

    def test_respects_existing_zone_hint(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.special", "special",
                  schema="raw", zone_hint="analytics")

        enriched = ext._enrich_zone_metadata()
        assert enriched == 0  # already has zone
        assert ext._graph.nodes["bigquery:proj.raw.special"].raw_metadata["zone"] == "analytics"

    def test_skips_non_dataset_nodes(self):
        ext = _make_extractor()
        _add_node(ext, "n8n:workflow1", "workflow1", node_type="workflow",
                  platform="n8n", platform_domain="orchestration")

        enriched = ext._enrich_zone_metadata()
        assert enriched == 0


# =====================================================================
# Deduplicate nodes
# =====================================================================


class TestDeduplicateNodes:
    """Test _deduplicate_nodes merges by (domain, namespace, schema, name)."""

    def test_merges_nodes_with_same_key(self):
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "proj"}
        _add_node(ext, "bigquery:proj.raw.customers", "customers",
                  schema="raw", namespace="proj")
        _add_node(ext, "dbt:raw.customers", "customers",
                  platform="dbt", schema="raw", namespace="proj",
                  platform_domain="warehouse", node_type="source")

        removed = ext._deduplicate_nodes()
        assert removed == 1
        assert len(ext._graph.nodes) == 1

    def test_remaps_edges_after_dedup(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.customers", "customers",
                  schema="raw", namespace="proj")
        _add_node(ext, "dbt:raw.customers", "customers",
                  platform="dbt", schema="raw", namespace="proj",
                  platform_domain="warehouse", node_type="source")
        _add_node(ext, "bigquery:proj.analytics.dim_customers", "dim_customers",
                  schema="analytics", namespace="proj")

        # Edge from dbt node (will be deduped) to downstream
        _add_edge(ext, "dbt:raw.customers", "bigquery:proj.analytics.dim_customers")

        removed = ext._deduplicate_nodes()
        assert removed == 1

        # Edge should be remapped to the surviving node
        edges = list(ext._graph.edges.values())
        assert len(edges) == 1
        surviving = [n for n in ext._graph.nodes.values() if n.name == "customers"][0]
        assert edges[0].source_id == surviving.id

    def test_removes_self_loops_after_dedup(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.customers", "customers",
                  schema="raw", namespace="proj")
        _add_node(ext, "dbt:raw.customers", "customers",
                  platform="dbt", schema="raw", namespace="proj",
                  platform_domain="warehouse", node_type="source")

        # Edge between the two nodes that will merge → self-loop
        _add_edge(ext, "bigquery:proj.raw.customers", "dbt:raw.customers")

        removed = ext._deduplicate_nodes()
        assert removed == 1
        # Self-loop should be removed
        assert len(ext._graph.edges) == 0

    def test_merges_metadata_from_richer_node(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.customers", "customers",
                  schema="raw", namespace="proj")
        _add_node(ext, "dbt:raw.customers", "customers",
                  platform="dbt", schema="raw", namespace="proj",
                  platform_domain="warehouse", node_type="source",
                  description="Customer master data")

        ext._deduplicate_nodes()
        surviving = list(ext._graph.nodes.values())[0]
        assert surviving.description == "Customer master data"

    def test_no_dedup_for_unique_nodes(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.customers", "customers",
                  schema="raw", namespace="proj")
        _add_node(ext, "bigquery:proj.raw.orders", "orders",
                  schema="raw", namespace="proj")

        removed = ext._deduplicate_nodes()
        assert removed == 0
        assert len(ext._graph.nodes) == 2

    def test_different_domains_no_merge(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.customers", "customers",
                  schema="raw", namespace="proj", platform_domain="warehouse")
        _add_node(ext, "looker:customers_dash", "customers",
                  schema="raw", namespace="proj", platform="looker",
                  platform_domain="bi", node_type="dashboard")

        removed = ext._deduplicate_nodes()
        assert removed == 0
        assert len(ext._graph.nodes) == 2


# =====================================================================
# Validate edges
# =====================================================================


class TestValidateEdges:
    """Test _validate_edges removes dangling and flags no-evidence."""

    def test_removes_dangling_edges(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.customers", "customers", schema="raw")
        _add_node(ext, "bigquery:proj.raw.orders", "orders", schema="raw")
        _add_edge(ext, "bigquery:proj.raw.customers", "bigquery:proj.raw.orders")

        # Manually delete a node to create a dangling edge
        del ext._graph.nodes["bigquery:proj.raw.orders"]

        stats = ext._validate_edges()
        assert stats["removed_dangling"] == 1
        assert len(ext._graph.edges) == 0

    def test_flags_no_evidence_edges_as_inferred(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.a", "a", schema="raw")
        _add_node(ext, "bigquery:proj.raw.b", "b", schema="raw")
        _add_edge(ext, "bigquery:proj.raw.a", "bigquery:proj.raw.b",
                  evidence="LLM-inferred")

        stats = ext._validate_edges()
        assert stats["flagged_no_evidence"] == 1
        edge = list(ext._graph.edges.values())[0]
        assert edge.inferred is True

    def test_keeps_edges_with_evidence(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.a", "a", schema="raw")
        _add_node(ext, "bigquery:proj.raw.b", "b", schema="raw")
        _add_edge(ext, "bigquery:proj.raw.a", "bigquery:proj.raw.b",
                  evidence="SQL: SELECT * FROM a used in view b definition")

        stats = ext._validate_edges()
        assert stats["flagged_no_evidence"] == 0


# =====================================================================
# Normalize confidence
# =====================================================================


class TestNormalizeConfidence:
    """Test _normalize_confidence caps based on evidence type."""

    def test_caps_llm_inferred_at_0_7(self):
        ext = _make_extractor()
        _add_node(ext, "a", "a", schema="raw")
        _add_node(ext, "b", "b", schema="raw")
        _add_edge(ext, "a", "b", confidence=1.0, evidence="I think these are related")

        adjusted = ext._normalize_confidence()
        assert adjusted == 1
        edge = list(ext._graph.edges.values())[0]
        assert edge.confidence == 0.7

    def test_allows_manifest_evidence_up_to_0_95(self):
        ext = _make_extractor()
        _add_node(ext, "a", "a", schema="raw")
        _add_node(ext, "b", "b", schema="raw")
        _add_edge(ext, "a", "b", confidence=1.0,
                  evidence="dbt manifest depends_on relationship")

        adjusted = ext._normalize_confidence()
        assert adjusted == 1
        edge = list(ext._graph.edges.values())[0]
        assert edge.confidence == 0.95

    def test_allows_sql_evidence_up_to_0_9(self):
        ext = _make_extractor()
        _add_node(ext, "a", "a", schema="raw")
        _add_node(ext, "b", "b", schema="raw")
        _add_edge(ext, "a", "b", confidence=1.0,
                  evidence="SQL SELECT FROM a detected in view definition")

        adjusted = ext._normalize_confidence()
        assert adjusted == 1
        edge = list(ext._graph.edges.values())[0]
        assert edge.confidence == 0.9

    def test_doesnt_lower_already_below_cap(self):
        ext = _make_extractor()
        _add_node(ext, "a", "a", schema="raw")
        _add_node(ext, "b", "b", schema="raw")
        _add_edge(ext, "a", "b", confidence=0.5,
                  evidence="Some general reasoning")

        adjusted = ext._normalize_confidence()
        assert adjusted == 0  # 0.5 < 0.7 cap, no adjustment needed
        edge = list(ext._graph.edges.values())[0]
        assert edge.confidence == 0.5


# =====================================================================
# Build namespace lookup
# =====================================================================


class TestBuildNamespaceLookup:
    """Test _build_namespace_lookup extracts platform → namespace."""

    def test_bigquery_project_id(self):
        ext = _make_extractor()
        configs = [ToolConfig(
            tool_type="bigquery",
            config={"project_id": "my-analytics-project"},
            integration_id="bq-1",
        )]
        lookup = ext._build_namespace_lookup(configs)
        assert lookup["bigquery"] == "my-analytics-project"

    def test_snowflake_account(self):
        ext = _make_extractor()
        configs = [ToolConfig(
            tool_type="snowflake",
            config={"account": "XY12345"},
            integration_id="sf-1",
        )]
        lookup = ext._build_namespace_lookup(configs)
        assert lookup["snowflake"] == "xy12345"  # lowercased

    def test_multiple_platforms(self):
        ext = _make_extractor()
        configs = [
            ToolConfig(tool_type="bigquery", config={"project_id": "proj"}, integration_id="bq"),
            ToolConfig(tool_type="dbt_core", config={"project_name": "my_dbt"}, integration_id="dbt"),
        ]
        lookup = ext._build_namespace_lookup(configs)
        assert lookup["bigquery"] == "proj"
        assert lookup["dbt_core"] == "my_dbt"

    def test_missing_config_skipped(self):
        ext = _make_extractor()
        configs = [ToolConfig(
            tool_type="bigquery",
            config={},  # no project_id
            integration_id="bq-1",
        )]
        lookup = ext._build_namespace_lookup(configs)
        assert "bigquery" not in lookup


# =====================================================================
# Full normalization pipeline
# =====================================================================


class TestFullNormalizationPipeline:
    """Test _normalize_and_validate end-to-end."""

    def test_end_to_end(self):
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "proj"}

        # Add nodes with inconsistent casing, missing namespace, no zone
        _add_node(ext, "bigquery:proj.raw.customers", "Customers",
                  schema="RAW", database="PROJ")
        _add_node(ext, "bigquery:proj.analytics.dim_customers", "dim_customers",
                  schema="analytics", database="proj")
        _add_edge(ext, "bigquery:proj.raw.customers",
                  "bigquery:proj.analytics.dim_customers",
                  evidence="SQL: model selects from raw.customers")

        stats = ext._normalize_and_validate()

        # Identifiers normalized
        node = ext._graph.nodes["bigquery:proj.raw.customers"]
        assert node.name == "customers"
        assert node.schema == "raw"

        # Namespace filled
        assert node.namespace == "proj"

        # Zone enriched
        assert node.raw_metadata.get("zone") == "raw"

        # Confidence for SQL evidence capped at 0.9
        edge = list(ext._graph.edges.values())[0]
        assert edge.confidence <= 0.9

    def test_normalization_enables_correct_zone_classification(self):
        """After normalization, classify_dataset_zone() returns correct zones."""
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "proj"}

        _add_node(ext, "bigquery:proj.raw.events", "events", schema="raw")
        _add_node(ext, "bigquery:proj.analytics.metrics", "metrics",
                  schema="analytics")
        _add_node(ext, "dbt:proj.staging.stg_events", "stg_events",
                  platform="dbt", platform_domain="transform", schema="staging",
                  dbt_resource_type="model", dbt_path="models/staging/stg_events.sql")

        ext._normalize_and_validate()

        # Check zones via classify_dataset_zone (which now reads raw_metadata["zone"])
        raw_node = ext._graph.nodes["bigquery:proj.raw.events"]
        assert classify_dataset_zone(raw_node) == DatasetZone.RAW

        analytics_node = ext._graph.nodes["bigquery:proj.analytics.metrics"]
        assert classify_dataset_zone(analytics_node) == DatasetZone.ANALYTICS

        staging_node = ext._graph.nodes["dbt:proj.staging.stg_events"]
        assert classify_dataset_zone(staging_node) == DatasetZone.STAGING

    def test_normalization_produces_valid_urns(self):
        """After normalization + canonicalize, URNs have namespace populated."""
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "my-project"}

        _add_node(ext, "bigquery:my-project.raw.orders", "orders",
                  schema="raw", database="my-project")

        ext._normalize_and_validate()
        canonicalize_graph_in_place(ext._graph.nodes, ext._graph.edges)

        node = ext._graph.nodes["bigquery:my-project.raw.orders"]
        assert node.urn is not None
        assert "my-project" in node.urn
        assert "::" not in node.urn  # no empty namespace segment

    def test_dedup_then_bridge_no_duplicates(self):
        """After dedup + bridge, no duplicate writes edges for same FQN."""
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "proj"}

        # Two nodes for same table (BQ + dbt source)
        _add_node(ext, "bigquery:proj.raw.customers", "customers",
                  schema="raw", namespace="proj")
        _add_node(ext, "dbt:raw.customers", "customers",
                  platform="dbt", schema="raw", namespace="proj",
                  platform_domain="warehouse", node_type="source")
        # Unique table
        _add_node(ext, "bigquery:proj.raw.orders", "orders",
                  schema="raw", namespace="proj")
        # Ingestion service
        _add_node(ext, "n8n:main", "n8n", node_type="workflow",
                  platform="n8n", platform_domain="ingestion")

        ext._normalize_and_validate()
        canonicalize_graph_in_place(ext._graph.nodes, ext._graph.edges)

        bridge = BridgeRuleEngine(ext._graph)
        bridge_result = bridge.apply_all()

        # Bridge should create writes edges to unique FQNs only
        writes_fqns = set()
        for e in bridge_result.added_edges:
            if e.canonical_edge_type == "writes":
                target = ext._graph.nodes.get(e.target_id)
                if target:
                    writes_fqns.add(target.fqn.lower())

        # Should be 2 unique FQNs (customers + orders), not 3
        assert len(writes_fqns) <= 2


# =====================================================================
# Zone hint in zones.py
# =====================================================================


class TestZoneHintClassification:
    """Test that raw_metadata['zone'] is respected by classify_dataset_zone."""

    def test_explicit_zone_overrides_schema_pattern(self):
        """A node in 'raw' schema but with zone_hint='analytics' should be analytics."""
        node = LineageNode(
            id="test:raw.special",
            name="special",
            fqn="raw.special",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            schema="raw",
            raw_metadata={"zone": "analytics"},
        )
        assert classify_dataset_zone(node) == DatasetZone.ANALYTICS

    def test_no_zone_hint_falls_through(self):
        """Without zone hint, schema pattern matching still works."""
        node = LineageNode(
            id="test:raw.events",
            name="events",
            fqn="raw.events",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            schema="raw",
            raw_metadata={},
        )
        assert classify_dataset_zone(node) == DatasetZone.RAW

    def test_invalid_zone_hint_ignored(self):
        """An invalid zone value should fall through to pattern matching."""
        node = LineageNode(
            id="test:raw.events",
            name="events",
            fqn="raw.events",
            node_type=NodeType.TABLE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            schema="raw",
            raw_metadata={"zone": "not_a_real_zone"},
        )
        assert classify_dataset_zone(node) == DatasetZone.RAW


# =====================================================================
# add_node tool enrichment
# =====================================================================


class TestAddNodeEnrichment:
    """Test that add_node handler populates raw_metadata with new fields."""

    def test_zone_hint_stored_in_raw_metadata(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.events", "events",
                  schema="raw", zone_hint="raw")

        node = ext._graph.nodes["bigquery:proj.raw.events"]
        assert node.raw_metadata["zone"] == "raw"

    def test_dbt_path_stored(self):
        ext = _make_extractor()
        _add_node(ext, "dbt:proj.staging.stg_orders", "stg_orders",
                  platform="dbt", platform_domain="transform",
                  dbt_path="models/staging/stg_orders.sql")

        node = ext._graph.nodes["dbt:proj.staging.stg_orders"]
        assert node.raw_metadata["dbt_path"] == "models/staging/stg_orders.sql"

    def test_dbt_resource_type_stored(self):
        ext = _make_extractor()
        _add_node(ext, "dbt:proj.raw.src_events", "src_events",
                  platform="dbt", platform_domain="warehouse",
                  node_type="source", dbt_resource_type="source")

        node = ext._graph.nodes["dbt:proj.raw.src_events"]
        assert node.raw_metadata["dbt_resource_type"] == "source"

    def test_namespace_set_on_node(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.events", "events",
                  namespace="my-project")

        node = ext._graph.nodes["bigquery:proj.raw.events"]
        assert node.namespace == "my-project"

    def test_case_hint_always_set(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.events", "events")

        node = ext._graph.nodes["bigquery:proj.raw.events"]
        assert node.raw_metadata["case_hint"] == "lower"

    def test_enriches_existing_node_instead_of_skipping(self):
        """When add_node is called with an existing node_id, it enriches."""
        ext = _make_extractor()
        # First add as warehouse table
        result1 = _add_node(ext, "bigquery:proj.raw.customers", "customers",
                           schema="raw", database="proj")
        assert result1["action"] == "added"

        # Now add same ID with dbt metadata
        result2 = _add_node(ext, "bigquery:proj.raw.customers", "customers",
                           schema="raw", database="proj",
                           dbt_resource_type="model",
                           dbt_path="models/staging/stg_customers.sql",
                           zone_hint="staging",
                           description="Staged customers")
        assert result2["action"] == "enriched"

        node = ext._graph.nodes["bigquery:proj.raw.customers"]
        assert node.raw_metadata["dbt_resource_type"] == "model"
        assert node.raw_metadata["dbt_path"] == "models/staging/stg_customers.sql"
        assert node.raw_metadata["zone"] == "staging"
        assert node.description == "Staged customers"

    def test_enrichment_does_not_overwrite_existing_zone(self):
        """Enrichment preserves existing zone if already set."""
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.events", "events",
                  schema="raw", zone_hint="raw")

        # Try to enrich with different zone — should keep "raw"
        _add_node(ext, "bigquery:proj.raw.events", "events",
                  zone_hint="staging")

        node = ext._graph.nodes["bigquery:proj.raw.events"]
        assert node.raw_metadata["zone"] == "raw"


# =====================================================================
# Normalize node types
# =====================================================================


class TestNormalizeNodeTypes:
    """Test _normalize_node_types fixes source→table for non-dbt nodes."""

    def test_warehouse_source_becomes_table(self):
        """A warehouse node with type 'source' (not dbt) → 'table'."""
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.events", "events",
                  node_type="source", platform_domain="warehouse")

        # The auto-fix in add_node should already fix this
        node = ext._graph.nodes["bigquery:proj.raw.events"]
        assert node.node_type == NodeType.TABLE

    def test_normalize_catches_remaining_source_nodes(self):
        """_normalize_node_types fixes any source nodes without dbt_resource_type."""
        ext = _make_extractor()
        # Manually create a SOURCE node that bypassed the add_node auto-fix
        node = LineageNode(
            id="bigquery:proj.raw.orders",
            name="orders",
            fqn="proj.raw.orders",
            node_type=NodeType.SOURCE,
            platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            schema="raw",
            raw_metadata={},
        )
        ext._graph.add_node(node)

        fixed = ext._normalize_node_types()
        assert fixed == 1
        assert ext._graph.nodes["bigquery:proj.raw.orders"].node_type == NodeType.TABLE

    def test_preserves_dbt_source(self):
        """A node with dbt_resource_type='source' keeps SOURCE type."""
        ext = _make_extractor()
        _add_node(ext, "dbt:proj.raw.src_events", "src_events",
                  node_type="source", platform="dbt",
                  platform_domain="warehouse",
                  dbt_resource_type="source")

        node = ext._graph.nodes["dbt:proj.raw.src_events"]
        assert node.node_type == NodeType.SOURCE

        # Normalization should also preserve it
        fixed = ext._normalize_node_types()
        assert fixed == 0
        assert ext._graph.nodes["dbt:proj.raw.src_events"].node_type == NodeType.SOURCE

    def test_non_warehouse_source_kept(self):
        """SOURCE type on non-warehouse nodes is not touched by auto-fix."""
        ext = _make_extractor()
        # A dbt source with transform domain stays as-is through normalize
        node = LineageNode(
            id="dbt:proj.raw.external",
            name="external",
            fqn="proj.raw.external",
            node_type=NodeType.SOURCE,
            platform="dbt",
            platform_domain=PlatformDomain.TRANSFORM,
            schema="raw",
            raw_metadata={"dbt_resource_type": "source"},
        )
        ext._graph.add_node(node)
        fixed = ext._normalize_node_types()
        assert fixed == 0


# =====================================================================
# Cross-domain dedup (transform ↔ warehouse)
# =====================================================================


class TestCrossDomainDedup:
    """Test cross-domain dedup merges transform + warehouse nodes."""

    def test_merges_dbt_model_with_warehouse_table(self):
        """A dbt model (transform) and a BQ table (warehouse) with same
        namespace+schema+name should merge, keeping the warehouse node."""
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "proj", "dbt": "proj"}

        _add_node(ext, "bigquery:proj.staging.stg_orders", "stg_orders",
                  schema="staging", database="proj", namespace="proj")
        _add_node(ext, "dbt:proj.staging.stg_orders", "stg_orders",
                  platform="dbt", platform_domain="transform",
                  schema="staging", namespace="proj",
                  dbt_resource_type="model",
                  dbt_path="models/staging/stg_orders.sql",
                  description="Staged orders from raw")

        # Add an edge FROM raw TO the dbt node
        _add_node(ext, "bigquery:proj.raw.orders", "orders",
                  schema="raw", namespace="proj")
        _add_edge(ext, "bigquery:proj.raw.orders", "dbt:proj.staging.stg_orders",
                  evidence="dbt depends_on")

        ext._normalize_identifiers()
        ext._fill_missing_namespaces()
        removed = ext._deduplicate_nodes()

        assert removed == 1
        # dbt node removed, warehouse node kept
        assert "dbt:proj.staging.stg_orders" not in ext._graph.nodes
        assert "bigquery:proj.staging.stg_orders" in ext._graph.nodes

        # dbt metadata merged into warehouse node
        winner = ext._graph.nodes["bigquery:proj.staging.stg_orders"]
        assert winner.raw_metadata.get("dbt_resource_type") == "model"
        assert winner.raw_metadata.get("dbt_path") == "models/staging/stg_orders.sql"
        assert winner.description == "Staged orders from raw"

        # Edge remapped to warehouse node
        edge = list(ext._graph.edges.values())[0]
        assert edge.target_id == "bigquery:proj.staging.stg_orders"

    def test_same_domain_not_affected_by_cross_domain(self):
        """Two warehouse nodes with same name in same-domain pass should
        dedup, not in cross-domain pass."""
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.events", "events",
                  schema="raw", namespace="proj")
        _add_node(ext, "bigquery:proj2.raw.events", "events",
                  schema="raw", namespace="proj")

        removed = ext._deduplicate_nodes()
        assert removed == 1  # Same domain dedup catches it

    def test_no_merge_when_namespace_differs(self):
        """Transform and warehouse nodes with different namespaces
        should NOT merge."""
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.events", "events",
                  schema="raw", namespace="proj-a")
        _add_node(ext, "dbt:other.raw.events", "events",
                  platform="dbt", platform_domain="transform",
                  schema="raw", namespace="proj-b")

        removed = ext._deduplicate_nodes()
        assert removed == 0
        assert len(ext._graph.nodes) == 2

    def test_cross_domain_removes_self_loops(self):
        """After cross-domain merge, self-loop edges are removed."""
        ext = _make_extractor()
        ext._namespace_lookup = {"bigquery": "proj"}

        _add_node(ext, "bigquery:proj.staging.stg_orders", "stg_orders",
                  schema="staging", namespace="proj")
        _add_node(ext, "dbt:proj.staging.stg_orders", "stg_orders",
                  platform="dbt", platform_domain="transform",
                  schema="staging", namespace="proj")

        # Edge between the two (will become self-loop after merge)
        _add_edge(ext, "bigquery:proj.staging.stg_orders",
                  "dbt:proj.staging.stg_orders",
                  evidence="same table")

        removed = ext._deduplicate_nodes()
        assert removed == 1
        # Self-loop edge should be removed
        assert len(ext._graph.edges) == 0


# =====================================================================
# Discovery cache & auto-enrichment
# =====================================================================


class TestDiscoveryCacheEnrichment:
    """Test auto-enrichment from discovery cache."""

    def test_add_node_auto_enriches_from_cache(self):
        """add_node should pull columns/row_count/owner from discovery cache."""
        ext = _make_extractor()
        # Pre-populate cache (as if discover ran first)
        ext._discovery_cache["bigquery:proj.raw.users"] = {
            "columns": [{"name": "id", "type": "INT64"}, {"name": "email", "type": "STRING"}],
            "row_count": 5000,
            "owner": "data-team",
            "tags": ["pii"],
            "sql": "SELECT * FROM raw.users",
            "_adapter_id": "bq-1",
            "_platform": "bigquery",
        }

        _add_node(ext, "bigquery:proj.raw.users", "users",
                  database="proj", schema="raw")

        node = ext._graph.nodes["bigquery:proj.raw.users"]
        assert len(node.columns) == 2
        assert node.columns[0]["name"] == "id"
        assert node.row_count == 5000
        assert node.owner == "data-team"
        assert "pii" in node.tags
        assert node.raw_metadata.get("sql") == "SELECT * FROM raw.users"

    def test_enrichment_does_not_overwrite_existing(self):
        """If node already has columns, cache should not overwrite."""
        ext = _make_extractor()
        ext._discovery_cache["bigquery:proj.raw.users"] = {
            "columns": [{"name": "id", "type": "INT64"}],
            "owner": "cache-owner",
            "_platform": "bigquery",
            "_adapter_id": "bq-1",
        }

        # Manually add node with existing data
        node = LineageNode(
            id="bigquery:proj.raw.users", name="users", fqn="proj.raw.users",
            node_type=NodeType.TABLE, platform="bigquery",
            platform_domain=PlatformDomain.WAREHOUSE,
            columns=[{"name": "id", "type": "INT64"}, {"name": "name", "type": "STRING"}],
            owner="explicit-owner",
            raw_metadata={},
        )
        ext._graph.add_node(node)
        ext._enrich_from_discovery("bigquery:proj.raw.users", node)

        # Should keep existing (more complete) columns and owner
        assert len(node.columns) == 2
        assert node.owner == "explicit-owner"

    def test_enrichment_via_normalized_key(self):
        """Discovery cache lookup should work via normalized key."""
        ext = _make_extractor()
        # Cache under adapter's ID format
        ext._discovery_cache["bq:proj.raw.users"] = {
            "columns": [{"name": "id", "type": "INT64"}],
            "row_count": 100,
            "_platform": "bigquery",
            "_adapter_id": "bq-1",
        }
        # Also under normalized key (as _tool_discover_assets would do)
        ext._discovery_cache["bigquery:proj.raw.users"] = ext._discovery_cache["bq:proj.raw.users"]

        _add_node(ext, "bigquery:proj.raw.users", "users",
                  database="proj", schema="raw")

        node = ext._graph.nodes["bigquery:proj.raw.users"]
        assert len(node.columns) == 1
        assert node.row_count == 100

    def test_sweep_catches_unmatched_nodes(self):
        """Post-discovery sweep should enrich nodes not matched during add_node."""
        ext = _make_extractor()
        # Add node first without cache
        _add_node(ext, "bigquery:proj.raw.orders", "orders",
                  database="proj", schema="raw")

        # Now populate cache (simulating late discovery)
        ext._discovery_cache["bigquery:proj.raw.orders"] = {
            "columns": [{"name": "order_id", "type": "INT64"}],
            "row_count": 9999,
            "_platform": "bigquery",
            "_adapter_id": "bq-1",
        }

        enriched = ext._sweep_discovery_enrichment()
        assert enriched == 1

        node = ext._graph.nodes["bigquery:proj.raw.orders"]
        assert len(node.columns) == 1
        assert node.row_count == 9999

    def test_sweep_skips_already_enriched(self):
        """Sweep should skip nodes that already have columns."""
        ext = _make_extractor()
        ext._discovery_cache["bigquery:proj.raw.users"] = {
            "columns": [{"name": "id", "type": "INT64"}],
            "_platform": "bigquery",
            "_adapter_id": "bq-1",
        }
        _add_node(ext, "bigquery:proj.raw.users", "users",
                  database="proj", schema="raw")

        # Node already enriched during add_node
        assert len(ext._graph.nodes["bigquery:proj.raw.users"].columns) == 1

        # Sweep should find 0 additional nodes to enrich
        enriched = ext._sweep_discovery_enrichment()
        assert enriched == 0

    def test_metadata_keys_cached(self):
        """SQL, materialized, depends_on from raw_metadata should be cached."""
        ext = _make_extractor()
        ext._discovery_cache["bigquery:proj.analytics.dim_users"] = {
            "sql": "SELECT id, name FROM staging.stg_users",
            "materialized": "table",
            "depends_on": ["staging.stg_users"],
            "_platform": "bigquery",
            "_adapter_id": "bq-1",
        }

        _add_node(ext, "bigquery:proj.analytics.dim_users", "dim_users",
                  database="proj", schema="analytics")

        node = ext._graph.nodes["bigquery:proj.analytics.dim_users"]
        assert node.raw_metadata["sql"] == "SELECT id, name FROM staging.stg_users"
        assert node.raw_metadata["materialized"] == "table"
        assert node.raw_metadata["depends_on"] == ["staging.stg_users"]


# =====================================================================
# Multi-platform provenance
# =====================================================================


class TestMultiPlatformProvenance:
    """Test discovered_platforms tracking."""

    def test_new_node_has_platform(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.users", "users")
        node = ext._graph.nodes["bigquery:proj.raw.users"]
        assert "bigquery" in node.raw_metadata.get("discovered_platforms", [])

    def test_enrichment_merges_platforms(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.users", "users")
        # Enrich with dbt (same node_id, different platform)
        ext._tool_add_node({
            "node_id": "bigquery:proj.raw.users",
            "name": "users",
            "node_type": "table",
            "platform": "dbt",
            "platform_domain": "transform",
        })
        node = ext._graph.nodes["bigquery:proj.raw.users"]
        platforms = node.raw_metadata.get("discovered_platforms", [])
        assert "bigquery" in platforms
        assert "dbt" in platforms

    def test_dedup_merges_platforms_same_domain(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.raw.users_1", "users",
                  schema="raw", namespace="proj")
        _add_node(ext, "bigquery:proj.raw.users_2", "users",
                  schema="raw", namespace="proj")

        ext._deduplicate_nodes()
        remaining = list(ext._graph.nodes.values())
        assert len(remaining) == 1
        platforms = remaining[0].raw_metadata.get("discovered_platforms", [])
        assert "bigquery" in platforms

    def test_cross_domain_dedup_merges_platforms(self):
        ext = _make_extractor()
        _add_node(ext, "bigquery:proj.staging.stg_orders", "stg_orders",
                  schema="staging", namespace="proj")
        _add_node(ext, "dbt:proj.staging.stg_orders", "stg_orders",
                  platform="dbt", platform_domain="transform",
                  schema="staging", namespace="proj")

        ext._deduplicate_nodes()
        remaining = list(ext._graph.nodes.values())
        assert len(remaining) == 1
        platforms = remaining[0].raw_metadata.get("discovered_platforms", [])
        assert "bigquery" in platforms
        assert "dbt" in platforms

    def test_discovery_cache_adds_platform(self):
        """Auto-enrichment from cache should add the discovering platform."""
        ext = _make_extractor()
        ext._discovery_cache["bigquery:proj.raw.users"] = {
            "columns": [{"name": "id", "type": "INT64"}],
            "_platform": "bigquery",
            "_adapter_id": "bq-1",
        }
        _add_node(ext, "bigquery:proj.raw.users", "users",
                  database="proj", schema="raw")

        node = ext._graph.nodes["bigquery:proj.raw.users"]
        platforms = node.raw_metadata.get("discovered_platforms", [])
        assert "bigquery" in platforms


# =====================================================================
# Column mappings on edges
# =====================================================================


class TestColumnMappingsOnEdge:
    """Test column_mappings parameter on add_edge."""

    def test_add_edge_with_column_mappings(self):
        ext = _make_extractor()
        _add_node(ext, "bq:raw.users", "users")
        _add_node(ext, "dbt:stg.stg_users", "stg_users",
                  platform="dbt", platform_domain="transform")

        result = ext._tool_add_edge({
            "source_id": "bq:raw.users",
            "target_id": "dbt:stg.stg_users",
            "edge_type": "derived_from",
            "confidence": 0.9,
            "evidence": "SQL SELECT FROM",
            "column_mappings": [
                {"from_column": "user_id", "to_column": "id"},
                {"from_column": "email_address", "to_column": "email"},
            ],
            "transformation": "SELECT user_id AS id, email_address AS email FROM raw.users",
        })

        assert result["success"] is True
        edge = list(ext._graph.edges.values())[0]
        assert len(edge.column_mappings) == 2
        assert edge.column_mappings[0].from_column == "user_id"
        assert edge.column_mappings[0].to_column == "id"
        assert edge.column_mappings[1].from_column == "email_address"
        assert edge.transformation is not None
        assert edge.lineage_level == LineageLevel.COLUMN

    def test_add_edge_without_column_mappings_stays_table_level(self):
        ext = _make_extractor()
        _add_node(ext, "bq:a", "a")
        _add_node(ext, "bq:b", "b")
        _add_edge(ext, "bq:a", "bq:b")

        edge = list(ext._graph.edges.values())[0]
        assert edge.lineage_level == LineageLevel.TABLE
        assert len(edge.column_mappings) == 0

    def test_add_edge_ignores_malformed_column_mappings(self):
        ext = _make_extractor()
        _add_node(ext, "bq:a", "a")
        _add_node(ext, "bq:b", "b")

        result = ext._tool_add_edge({
            "source_id": "bq:a",
            "target_id": "bq:b",
            "edge_type": "derived_from",
            "confidence": 0.8,
            "evidence": "test",
            "column_mappings": [
                {"from_column": "x"},  # missing to_column
                "invalid_string",       # not a dict
                {"from_column": "a", "to_column": "b"},  # valid
            ],
        })

        assert result["success"] is True
        edge = list(ext._graph.edges.values())[0]
        assert len(edge.column_mappings) == 1
        assert edge.column_mappings[0].from_column == "a"
