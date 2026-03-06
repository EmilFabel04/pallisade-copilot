"""
Lineage Extraction Pipeline — correct end-to-end ordering.

Steps:
0. Start run_id via RunRegistry
1. (optional) LLM planner → adapter execution order
2. Investigator executes adapters → raw nodes/edges; resolver → graph
2.5. Cross-tool edge synthesis (ingestion→warehouse, dbt↔warehouse, BI↔warehouse)
2.6. Health enrichment (Elementary test results → node health_status)
3. Canonicalize types (first pass)
4. Deterministic bridge rules (uses canonical types to identify orphans)
5. Re-canonicalize (bridge-added nodes)
6. (optional) LLM reconciliation → GraphPatch → validate + apply safe subset
7. Build rendered views (PipelineOverview, DataPlane, LanePipelineOverview)
8. Persist artifacts under run_id, atomically publish current_run_id
9. Update store.graph for backward compatibility
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..cross_tool import CrossToolEdgeSynthesizer
from .bridge import BridgeRuleEngine
from .canonical import canonicalize_graph_in_place
from .indexes import build_producer_index
from .investigator import InvestigationResult, LineageInvestigator, ToolConfig
from .run_registry import RunArtifacts, RunRegistry
from .views import ViewBuilder

logger = logging.getLogger(__name__)


@dataclass
class ExtractionPipelineConfig:
    """Configuration for a pipeline run."""

    use_llm_planner: bool = False
    use_llm_reconciler: bool = False
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    tool_nodes: List[Dict[str, Any]] = field(default_factory=list)


async def run_extraction_pipeline(
    tool_configs: List[ToolConfig],
    registry: RunRegistry,
    store: Any,  # GraphStore — avoid circular import
    config: Optional[ExtractionPipelineConfig] = None,
) -> str:
    """
    Execute the full extraction pipeline with correct step ordering.

    Returns run_id. On success, registry.current_run_id is atomically
    updated and store.graph is set for backward compatibility.
    On failure, current_run_id stays pointing to the previous run.
    """
    config = config or ExtractionPipelineConfig()

    # Step 0: Start run
    tool_names = [tc.tool_type for tc in tool_configs]
    run_id = registry.start_run(tool_names)

    try:
        start = time.time()

        # Steps 1–2: Investigation (planner + adapters + resolver)
        result = await _run_investigation(tool_configs, config)

        if not result.graph:
            registry.fail_run(run_id, result.errors or ["No graph produced"])
            return run_id

        graph = result.graph

        # Step 2.5: Cross-tool edge synthesis
        # Creates edges across tool boundaries (ingestion→warehouse,
        # dbt↔warehouse, BI↔warehouse, orchestrator↔tables).
        # Must run AFTER resolver dedup but BEFORE canonicalize and bridge.
        synthesis_dict = _run_cross_tool_synthesis(graph, run_id)

        # Step 2.6: Health enrichment (Elementary test results → node health)
        health_dict = _run_health_enrichment(graph, tool_configs, run_id)

        # Step 2.7: Infer ingestion landing zones (schema-agnostic)
        # Must run AFTER cross-tool synthesis (which adds adapter edges)
        # and BEFORE bridge rules (which need container awareness).
        from .landing_zone import infer_landing_zones
        landing_profile = infer_landing_zones(graph, tool_configs)
        landing_zone_dict = landing_profile.to_dict() if landing_profile.zones else None

        # Step 3: Canonicalize (first pass)
        canonicalize_graph_in_place(graph.nodes, graph.edges)

        # Step 4: Bridge rules (with landing zone awareness)
        bridge_engine = BridgeRuleEngine(graph, landing_zone_profile=landing_profile)
        bridge_result = bridge_engine.apply_all()
        bridge_dict = bridge_result.to_dict() if bridge_result.total_changes > 0 else None
        if bridge_result.total_changes > 0:
            logger.info(
                "[Pipeline:%s] Bridge: +%d nodes, +%d edges",
                run_id,
                len(bridge_result.added_nodes),
                len(bridge_result.added_edges),
            )

        # Step 5: Re-canonicalize (bridge-added nodes)
        if bridge_result.total_changes > 0:
            canonicalize_graph_in_place(graph.nodes, graph.edges)

        # Step 5.5: Build producer index (needs canonical types from step 5)
        producer_index_dict = None
        try:
            producer_index = build_producer_index(graph)
            producer_index_dict = producer_index.to_dict()
            logger.info(
                "[Pipeline:%s] Producer index: %d datasets, %d producers",
                run_id, producer_index.total_datasets,
                producer_index.total_producers,
            )
        except Exception as e:
            logger.warning(
                "[Pipeline:%s] Producer index failed (non-fatal): %s",
                run_id, e,
            )

        # Step 6: LLM Reconciliation (optional)
        reconciliation_dict = None
        if config.use_llm_reconciler and config.llm_api_key:
            reconciliation_dict = await _run_reconciliation(
                graph, config, run_id
            )

        # Step 7: Build rendered views
        views = _build_views(graph, config.tool_nodes, run_id)

        # Step 8: Persist artifacts and atomically publish
        artifacts = RunArtifacts(
            graph_dict=graph.to_dict(),
            views=views,
            diagnostics=(
                reconciliation_dict.get("diagnostics")
                if reconciliation_dict
                else None
            ),
            reconciliation=reconciliation_dict,
            stats={
                **result.stats,
                "cross_tool_synthesis": synthesis_dict,
                "health_enrichment": health_dict,
                "landing_zones": landing_zone_dict,
                "bridge": bridge_dict,
                "views_built": list(views.keys()),
                "run_id": run_id,
            },
            bridge_result=bridge_dict,
            producer_index=producer_index_dict,
        )

        registry.complete_run(run_id, artifacts)

        # Step 9: Update store.graph for backward compatibility
        # (existing query endpoints like /engine/upstream still read from store)
        store.graph = graph

        duration = int((time.time() - start) * 1000)
        logger.info(
            "[Pipeline:%s] Complete: %d nodes, %d edges, %d views, %dms",
            run_id,
            len(graph.nodes),
            len(graph.edges),
            len(views),
            duration,
        )

        return run_id

    except Exception as e:
        import traceback

        traceback.print_exc()
        registry.fail_run(run_id, [str(e)])
        return run_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _run_investigation(
    tool_configs: List[ToolConfig],
    config: ExtractionPipelineConfig,
) -> InvestigationResult:
    """Run the investigator — sync run() wrapped in a thread."""
    investigator = LineageInvestigator()

    if config.use_llm_planner and config.llm_api_key:
        # Use LLM planner for extraction order, but NOT the reconciler
        # (we handle reconciliation separately in the pipeline)
        result = await investigator.run_with_llm(
            tool_configs,
            use_llm_planner=True,
            use_llm_reconciler=False,
            llm_provider=config.llm_provider,
            llm_model=config.llm_model,
            llm_api_key=config.llm_api_key,
        )
    else:
        result = await asyncio.to_thread(investigator.run, tool_configs)

    return result


def _run_cross_tool_synthesis(
    graph: Any,
    run_id: str,
) -> Optional[Dict[str, int]]:
    """Run cross-tool edge synthesis (non-fatal on failure).

    Creates edges across tool boundaries:
    - Ingestion connector → warehouse table (POPULATES)
    - dbt source ↔ warehouse table
    - dbt model → materialization target
    - BI dashboard ← warehouse table
    - Orchestrator task ↔ tables
    """
    try:
        synthesizer = CrossToolEdgeSynthesizer(graph=graph)
        stats = synthesizer.synthesize_all()
        if stats.total_edges_created > 0 or stats.nodes_merged > 0:
            logger.info(
                "[Pipeline:%s] Cross-tool synthesis: %d edges created, %d nodes merged",
                run_id,
                stats.total_edges_created,
                stats.nodes_merged,
            )
        return stats.to_dict()
    except Exception as e:
        logger.warning(
            "[Pipeline:%s] Cross-tool synthesis failed (non-fatal): %s",
            run_id,
            e,
        )
        return None


def _run_health_enrichment(
    graph: Any,
    tool_configs: List[ToolConfig],
    run_id: str,
) -> Optional[Dict[str, int]]:
    """Enrich graph nodes with health data from Elementary (non-fatal).

    Finds a warehouse ToolConfig, creates a warehouse adapter client,
    queries Elementary test-result tables, and sets health_status on
    matching graph nodes.
    """
    try:
        from .adapters.live_elementary import LiveElementaryAdapter
        from scanner.adapters.factory import get_adapter

        # Find a warehouse tool config
        _WAREHOUSE_TOOLS = {"bigquery", "snowflake", "postgres", "redshift"}
        warehouse_tc = None
        for tc in tool_configs:
            if tc.tool_type.lower() in _WAREHOUSE_TOOLS:
                warehouse_tc = tc
                break
        if not warehouse_tc:
            return None

        # Create old-style warehouse adapter (has execute_query())
        wh_adapter = get_adapter(
            warehouse_tc.tool_type.lower(),
            warehouse_tc.config,
            auto_connect=True,
        )

        elem_adapter = LiveElementaryAdapter()
        elem_config = {
            "elementary_config": {
                "warehouse_adapter": wh_adapter,
                "schema": "elementary",
            }
        }

        health_data = elem_adapter.get_health_enrichment(elem_config)

        # Disconnect warehouse client
        try:
            wh_adapter.disconnect()
        except Exception:
            pass

        if not health_data:
            return {"tables_enriched": 0}

        # Build case-insensitive + short-FQN lookup for flexible matching
        health_lookup: Dict[str, Dict[str, Any]] = {}
        for fqn, data in health_data.items():
            health_lookup[fqn.lower()] = data
            parts = fqn.split(".")
            if len(parts) >= 2:
                health_lookup[".".join(parts[-2:]).lower()] = data

        # Apply health data to matching graph nodes
        enriched = 0
        for node in graph.nodes.values():
            if not node.fqn:
                continue
            fqn_lower = node.fqn.lower()
            match = health_lookup.get(fqn_lower)
            if not match:
                parts = fqn_lower.split(".")
                if len(parts) >= 2:
                    match = health_lookup.get(".".join(parts[-2:]))
            if match:
                node.health_status = match["health_status"]
                node.raw_metadata["health_total_tests"] = match.get("total_tests", 0)
                node.raw_metadata["health_failed_tests"] = match.get("failed_tests", 0)
                node.raw_metadata["health_warn_tests"] = match.get("warn_tests", 0)
                enriched += 1

        logger.info(
            "[Pipeline:%s] Health enrichment: %d/%d tables enriched",
            run_id, enriched, len(health_data),
        )
        return {"tables_enriched": enriched, "tables_with_tests": len(health_data)}

    except Exception as e:
        logger.warning(
            "[Pipeline:%s] Health enrichment failed (non-fatal): %s",
            run_id, e,
        )
        return None


async def _run_reconciliation(
    graph: Any,
    config: ExtractionPipelineConfig,
    run_id: str,
) -> Optional[Dict[str, Any]]:
    """Run LLM reconciliation. Returns result dict or None."""
    try:
        from .reconciler import ReconcilerConfig, ReconciliationEngine

        _default_model = (
            "gpt-4o" if config.llm_provider == "openai"
            else "claude-sonnet-4-20250514"
        )
        recon_config = ReconcilerConfig(
            provider=config.llm_provider,
            model=config.llm_model or _default_model,
            api_key=config.llm_api_key,
        )
        recon_engine = ReconciliationEngine(recon_config)
        recon_result = await recon_engine.reconcile(graph)

        if recon_result.success:
            logger.info(
                "[Pipeline:%s] Reconciliation applied: %s",
                run_id, recon_result.applied,
            )
        else:
            logger.warning(
                "[Pipeline:%s] Reconciliation issues: %s",
                run_id, recon_result.validation_errors,
            )
        return recon_result.to_dict()
    except Exception as e:
        logger.warning(
            "[Pipeline:%s] LLM reconciler failed (non-fatal): %s", run_id, e,
        )
        return None


def _build_views(
    graph: Any,
    tool_nodes: List[Dict[str, Any]],
    run_id: str,
) -> Dict[str, Dict[str, Any]]:
    """Build all rendered views from the final canonical graph."""
    views: Dict[str, Dict[str, Any]] = {}

    builder = ViewBuilder(graph, tool_nodes=tool_nodes)

    for view_name, build_fn in [
        ("pipeline_overview", builder.build_pipeline_overview),
        ("data_plane", builder.build_data_plane),
        ("lane_pipeline_overview", builder.build_lane_pipeline_overview),
    ]:
        try:
            view = build_fn()
            views[view_name] = view.to_dict()
        except Exception as e:
            logger.warning(
                "[Pipeline:%s] %s view failed: %s", run_id, view_name, e,
            )

    return views
