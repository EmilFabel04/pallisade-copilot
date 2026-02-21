"""
LLM-Powered Lineage Extraction Agent

Agentic extraction mode where Claude/GPT uses tools to query each connected
integration, reasons about data flow, and incrementally builds the lineage graph.
The LLM-built graph then flows through the existing canonicalize → bridge → views
pipeline.

Key difference from existing `investigate-llm`: That endpoint uses LLM only for
*planning adapter order* and *reconciling the result*. This module uses LLM for
the *actual extraction* — the LLM decides what to query, interprets results,
and builds the graph itself.
"""

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from ..graph import (
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
from .adapter import AdapterRegistry, BaseLineageAdapter, create_default_registry
from .bridge import BridgeRuleEngine
from .canonical import canonicalize_graph_in_place
from .ids import generate_edge_id, normalize_identifier
from .investigator import TOOL_TO_ADAPTER, ToolConfig, _build_adapter_config
from .views import ViewBuilder
from .zones import DatasetZone, classify_dataset_zone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool-type → category mapping for the system prompt
# ---------------------------------------------------------------------------

_TOOL_CATEGORY: Dict[str, str] = {
    "bigquery": "warehouse",
    "snowflake": "warehouse",
    "postgres": "warehouse",
    "redshift": "warehouse",
    "databricks": "warehouse",
    "dbt_cloud": "transformation",
    "dbt_core": "transformation",
    "n8n": "orchestration",
    "airflow": "orchestration",
    "dagster": "orchestration",
    "prefect": "orchestration",
    "fivetran": "ingestion",
    "airbyte": "ingestion",
    "looker": "reporting",
    "tableau": "reporting",
    "powerbi": "reporting",
    "metabase": "reporting",
    "linux_server": "infrastructure",
    "ssh": "infrastructure",
    "github": "version_control",
    "gitlab": "version_control",
    "elementary": "quality",
}

# Category → query tool name
_CATEGORY_TO_TOOL: Dict[str, str] = {
    "warehouse": "discover_warehouse_assets",
    "transformation": "discover_dbt_assets",
    "orchestration": "discover_orchestration_workflows",
    "ingestion": "discover_ingestion_connectors",
    "reporting": "discover_bi_assets",
    "infrastructure": "discover_infrastructure",
    "version_control": "discover_version_control",
    "quality": "discover_quality_data",
}


# ---------------------------------------------------------------------------
# Configuration and events
# ---------------------------------------------------------------------------


@dataclass
class LLMExtractorConfig:
    """Configuration for LLM-powered extraction."""

    provider: str = "anthropic"  # "anthropic" | "openai"
    model: Optional[str] = None  # None = use default per provider
    api_key: Optional[str] = None  # None = read from env
    max_iterations: int = 40  # Safety cap on tool-call rounds
    max_nodes: int = 2000
    max_edges: int = 5000
    max_tokens: int = 4096
    temperature: float = 0.0


@dataclass
class ExtractionEvent:
    """A single event emitted during extraction for SSE streaming."""

    event_type: str  # phase, tool_call, tool_result, node_added, edge_added, error, complete
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        """Format as an SSE data line."""
        payload = {"type": self.event_type, "data": self.data, "ts": self.timestamp}
        return f"data: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a data lineage extraction agent. Your job is to discover all data assets across a data pipeline stack and build an accurate lineage graph showing how data flows between them.

## How Data Pipelines Work
Data flows through these layers (left to right):
1. **Ingestion** — Tools like Fivetran, Airbyte, n8n pull data from sources into the warehouse
2. **Warehouse** — BigQuery, Snowflake, Postgres store raw and processed tables
3. **Transformation** — dbt transforms raw tables into analytics-ready models
4. **Orchestration** — Airflow, n8n, Dagster schedule and coordinate the pipeline
5. **Reporting/BI** — Looker, Tableau, Power BI, Metabase query models for dashboards

## Your Strategy
Follow this 6-phase extraction strategy:

### Phase 1: Discovery
Call `list_integrations` to see what tools are connected. This tells you what's available.

### Phase 2: Warehouse First
Call the appropriate discover tool for each warehouse (BigQuery, Snowflake, etc.). This gives you the foundation — all tables, views, columns, and any SQL-based lineage already available.

For each table/view discovered, call `add_node` with the correct fields. For any SQL lineage edges found, call `add_edge`.

### Phase 3: Transformation Layer
Call `discover_dbt_assets` for dbt integrations. dbt manifests contain explicit depends_on relationships. Models map to warehouse tables.

IMPORTANT: When a dbt model maps to a warehouse table you already added, use THE SAME node_id. Don't create duplicates.

### Phase 4: Ingestion & Orchestration
Call discover tools for n8n, Fivetran, Airbyte, Airflow, etc. These show what loads data into the warehouse.

### Phase 5: BI & Reporting
Call discover tools for Looker, Tableau, etc. These show what reads from the warehouse.

### Phase 6: Review & Complete
Call `get_graph_summary` to review your work. Check for:
- Orphan nodes (no edges) that should be connected
- Missing connections between layers
- Duplicate nodes

When satisfied, call `mark_extraction_complete`.

## Node ID Rules
- For warehouse tables: `{platform}:{database}.{schema}.{table_name}` (lowercase)
  Example: `bigquery:my-project.raw.customers`
- For dbt models that map to warehouse tables: USE THE SAME ID as the warehouse table
- For dbt-only models (no warehouse match): `dbt:{database}.{schema}.{model_name}`
- For orchestration (n8n, airflow): `{platform}:{workflow_name}` or `{platform}:{dag_id}`
- For BI assets: `{platform}:{dashboard_id}` or `{platform}:{report_name}`
- For ingestion connectors: `{platform}:{connector_id}`
- Always lowercase, no spaces

## Edge Direction
- `source_id` = upstream (where data comes FROM)
- `target_id` = downstream (where data goes TO)
- Example: raw table → dbt model means source=raw_table, target=dbt_model

## Confidence Guidelines
- 1.0 — Explicit manifest/config (dbt depends_on, Fivetran destination)
- 0.9 — SQL parsing (SELECT FROM detected)
- 0.8 — Query history / usage logs
- 0.7 — API metadata (connector configs, dashboard sources)
- 0.5 — Naming convention inference (table names match across tools)
- 0.3 — Weak inference (same schema, likely related)

## Namespace & Zone Hints
When calling add_node, always provide these when possible:

### namespace
The project/account/host identifier for the platform:
- BigQuery: GCP project ID (e.g. "my-analytics-project")
- Snowflake: account identifier (e.g. "xy12345")
- Postgres/Redshift: hostname
- dbt: project name or target project

### zone_hint
Where a dataset sits in the data lifecycle:
- "raw" — ingested/landed data, no transformation (tables in schemas like "raw", "landing", "source")
- "staging" — cleaned/renamed (stg_ prefix, "staging" schema)
- "intermediate" — joins/aggregations (int_ prefix)
- "mart" — business entities, facts/dimensions (fct_, dim_ prefix, "marts" schema)
- "analytics" — final reporting/metrics tables ("analytics" schema)

### dbt_path
For dbt models, the file path: e.g. "models/staging/stg_orders.sql"

### dbt_resource_type
For dbt assets: "model", "source", "seed", or "snapshot"

## Important Rules
- NEVER invent edges that aren't supported by evidence
- NEVER guess edge direction — verify from the data
- Use evidence descriptions to explain why each edge exists
- When in doubt, use lower confidence rather than guessing
- Call get_graph_summary periodically to track your progress"""


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic format)
# ---------------------------------------------------------------------------


def _build_tool_definitions() -> List[Dict[str, Any]]:
    """Build Anthropic-format tool definitions for the LLM."""
    return [
        {
            "name": "list_integrations",
            "description": "List all connected integrations with their types and layers. Call this first to understand what tools are available.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "discover_warehouse_assets",
            "description": "Discover tables, views, columns, and SQL-based lineage from a warehouse (BigQuery, Snowflake, Postgres, etc). Returns tables with columns and any known lineage edges.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "string",
                        "description": "The integration ID of the warehouse to query",
                    },
                },
                "required": ["integration_id"],
            },
        },
        {
            "name": "discover_dbt_assets",
            "description": "Discover dbt models, sources, seeds, and depends_on relationships. Returns models with their SQL, upstream dependencies, and materialization targets.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "string",
                        "description": "The integration ID of the dbt project",
                    },
                },
                "required": ["integration_id"],
            },
        },
        {
            "name": "discover_orchestration_workflows",
            "description": "Discover workflows, tasks, and table references from orchestration tools (n8n, Airflow, Dagster, Prefect).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "string",
                        "description": "The integration ID of the orchestration tool",
                    },
                },
                "required": ["integration_id"],
            },
        },
        {
            "name": "discover_ingestion_connectors",
            "description": "Discover connectors, source types, destination tables, and sync status from ingestion tools (Fivetran, Airbyte).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "string",
                        "description": "The integration ID of the ingestion tool",
                    },
                },
                "required": ["integration_id"],
            },
        },
        {
            "name": "discover_bi_assets",
            "description": "Discover dashboards, reports, and data source queries from BI tools (Looker, Tableau, Power BI, Metabase).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "string",
                        "description": "The integration ID of the BI tool",
                    },
                },
                "required": ["integration_id"],
            },
        },
        {
            "name": "discover_infrastructure",
            "description": "Discover servers, services, and resource usage from infrastructure (Linux servers).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "string",
                        "description": "The integration ID of the infrastructure",
                    },
                },
                "required": ["integration_id"],
            },
        },
        {
            "name": "discover_version_control",
            "description": "Discover repositories and files from version control (GitHub, GitLab).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "string",
                        "description": "The integration ID of the VCS tool",
                    },
                },
                "required": ["integration_id"],
            },
        },
        {
            "name": "discover_quality_data",
            "description": "Discover test results and model health from quality tools (Elementary).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "integration_id": {
                        "type": "string",
                        "description": "The integration ID of the quality tool",
                    },
                },
                "required": ["integration_id"],
            },
        },
        {
            "name": "add_node",
            "description": "Add a node to the lineage graph. Use this to register tables, models, dashboards, workflows, connectors, etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "Unique node ID. Format: {platform}:{fqn} — e.g. 'bigquery:project.raw.customers'",
                    },
                    "name": {
                        "type": "string",
                        "description": "Display name (e.g. 'customers', 'stg_orders')",
                    },
                    "node_type": {
                        "type": "string",
                        "enum": [
                            "table", "view", "model", "source", "seed", "snapshot",
                            "dashboard", "report", "explore", "workbook", "question",
                            "workflow", "dag", "task", "pipeline",
                            "connector", "monitor", "notebook", "dataset",
                        ],
                        "description": "Type of data asset",
                    },
                    "platform": {
                        "type": "string",
                        "description": "Tool platform (bigquery, snowflake, dbt, looker, n8n, etc.)",
                    },
                    "platform_domain": {
                        "type": "string",
                        "enum": ["warehouse", "transform", "orchestration", "bi", "ingestion", "other"],
                        "description": "High-level domain of the platform",
                    },
                    "database": {
                        "type": "string",
                        "description": "Database/project name (optional)",
                    },
                    "schema": {
                        "type": "string",
                        "description": "Schema name (optional)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the asset (optional)",
                    },
                    "integration_id": {
                        "type": "string",
                        "description": "Integration ID this node belongs to (optional)",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Project/account/host identifier. BigQuery: project_id, Snowflake: account, Postgres: hostname. Used for deduplication.",
                    },
                    "zone_hint": {
                        "type": "string",
                        "enum": ["raw", "staging", "intermediate", "mart", "analytics"],
                        "description": "Where this dataset sits in the data lifecycle. raw=ingested, staging=cleaned, intermediate=joins, mart=business entities, analytics=final reporting.",
                    },
                    "dbt_path": {
                        "type": "string",
                        "description": "File path within the dbt project (e.g. 'models/staging/stg_customers.sql'). Only for dbt models.",
                    },
                    "dbt_resource_type": {
                        "type": "string",
                        "enum": ["model", "source", "seed", "snapshot"],
                        "description": "dbt resource type. Only for dbt assets.",
                    },
                },
                "required": ["node_id", "name", "node_type", "platform", "platform_domain"],
            },
        },
        {
            "name": "add_edge",
            "description": "Add a lineage edge between two nodes. source_id is upstream, target_id is downstream.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Upstream node ID (where data comes from)",
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Downstream node ID (where data goes to)",
                    },
                    "edge_type": {
                        "type": "string",
                        "enum": [
                            "derived_from", "depends_on", "writes_to", "reads_from",
                            "populates", "triggers", "syncs_to", "queries", "monitors",
                            "produced_by", "materializes",
                        ],
                        "description": "Type of relationship",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence score 0.0-1.0",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Why this edge exists (e.g. 'dbt depends_on in manifest', 'SQL SELECT FROM detected')",
                    },
                },
                "required": ["source_id", "target_id", "edge_type", "confidence", "evidence"],
            },
        },
        {
            "name": "get_graph_summary",
            "description": "Get a summary of the current graph state: node/edge counts, nodes by platform, orphan list.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "mark_extraction_complete",
            "description": "Signal that extraction is done. Call this when you've discovered all assets and built all edges.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of what was discovered",
                    },
                    "unresolved_gaps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of known gaps or unresolved connections (optional)",
                    },
                },
                "required": ["summary"],
            },
        },
    ]


# ---------------------------------------------------------------------------
# OpenAI tool format converter
# ---------------------------------------------------------------------------


def _to_openai_tools(anthropic_tools: List[Dict]) -> List[Dict]:
    """Convert Anthropic tool definitions to OpenAI function-calling format."""
    result = []
    for tool in anthropic_tools:
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        })
    return result


# ---------------------------------------------------------------------------
# Core extractor
# ---------------------------------------------------------------------------


class LLMLineageExtractor:
    """
    Agentic LLM-powered lineage extractor.

    Uses tool calling to query integrations and build a lineage graph.
    Yields ExtractionEvent objects for real-time progress streaming.
    """

    def __init__(self, config: LLMExtractorConfig):
        self.config = config
        self._graph = LineageGraph()
        self._adapters: Dict[str, BaseLineageAdapter] = {}
        self._tool_configs: Dict[str, ToolConfig] = {}  # integration_id → ToolConfig
        self._namespace_lookup: Dict[str, str] = {}  # platform → namespace
        self._registry: Optional[AdapterRegistry] = None
        self._extraction_complete = False
        self._completion_summary = ""
        self._unresolved_gaps: List[str] = []

    async def extract(
        self,
        tool_configs: List[ToolConfig],
        tool_nodes: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[ExtractionEvent, None]:
        """
        Run agentic extraction loop, yielding events for SSE streaming.

        The final event (type="complete") contains the processed graph.
        """
        tool_nodes = tool_nodes or []
        start = time.time()

        yield ExtractionEvent("phase", {"phase": "initializing", "message": "Initializing extraction agent..."})

        # Initialize adapter registry and build adapters for each tool config
        self._registry = create_default_registry()
        for tc in tool_configs:
            adapter_type = TOOL_TO_ADAPTER.get(tc.tool_type.lower())
            if not adapter_type:
                logger.warning("[LLMExtractor] No adapter for tool_type=%s", tc.tool_type)
                continue
            try:
                adapter_config = _build_adapter_config(tc)
                adapter_id = tc.integration_id or f"{tc.tool_type}_{uuid.uuid4().hex[:6]}"
                adapter = self._registry.create(adapter_type, adapter_id, **adapter_config)
                self._adapters[adapter_id] = adapter
                self._tool_configs[adapter_id] = tc
            except Exception as e:
                logger.warning("[LLMExtractor] Failed to create adapter for %s: %s", tc.tool_type, e)

        # Build namespace lookup from tool configs for post-processing
        self._namespace_lookup = self._build_namespace_lookup(tool_configs)

        yield ExtractionEvent("phase", {
            "phase": "starting",
            "message": f"Starting AI extraction with {len(self._adapters)} integrations",
            "integrations": len(self._adapters),
        })

        # Build user message describing the pipeline
        user_message = self._build_user_message(tool_configs)

        # Run the agentic loop
        if self.config.provider == "anthropic":
            async for event in self._run_anthropic_loop(user_message):
                yield event
        elif self.config.provider == "openai":
            async for event in self._run_openai_loop(user_message):
                yield event
        else:
            yield ExtractionEvent("error", {"message": f"Unsupported provider: {self.config.provider}"})
            return

        # Strict accountant: normalize, enrich, dedup, validate
        yield ExtractionEvent("phase", {"phase": "normalizing", "message": "Validating and standardizing graph..."})
        norm_stats = self._normalize_and_validate()

        # Post-processing
        yield ExtractionEvent("phase", {"phase": "post_processing", "message": "Running canonicalization and bridge rules..."})

        canonicalize_graph_in_place(self._graph.nodes, self._graph.edges)
        bridge = BridgeRuleEngine(self._graph)
        bridge_result = bridge.apply_all()
        if bridge_result.total_changes > 0:
            canonicalize_graph_in_place(self._graph.nodes, self._graph.edges)
            logger.info(
                "[LLMExtractor] Bridge: +%d nodes, +%d edges",
                len(bridge_result.added_nodes), len(bridge_result.added_edges),
            )

        # Build views
        yield ExtractionEvent("phase", {"phase": "building_views", "message": "Building pipeline views..."})
        views = self._build_views(tool_nodes)

        duration_ms = int((time.time() - start) * 1000)

        yield ExtractionEvent("complete", {
            "message": "Extraction complete",
            "summary": self._completion_summary,
            "unresolved_gaps": self._unresolved_gaps,
            "stats": {
                "total_nodes": len(self._graph.nodes),
                "total_edges": len(self._graph.edges),
                "views_built": list(views.keys()),
                "duration_ms": duration_ms,
                "bridge_nodes_added": len(bridge_result.added_nodes) if bridge_result else 0,
                "bridge_edges_added": len(bridge_result.added_edges) if bridge_result else 0,
                "normalization": norm_stats,
            },
            "graph": self._graph.to_dict(),
            "views": views,
        })

        logger.info(
            "[LLMExtractor] Complete: %d nodes, %d edges, %dms",
            len(self._graph.nodes), len(self._graph.edges), duration_ms,
        )

    # -------------------------------------------------------------------
    # Anthropic loop
    # -------------------------------------------------------------------

    async def _run_anthropic_loop(self, user_message: str) -> AsyncGenerator[ExtractionEvent, None]:
        """Agentic tool-calling loop using Anthropic."""
        try:
            import anthropic
        except ImportError:
            yield ExtractionEvent("error", {"message": "anthropic package not installed"})
            return

        api_key = self.config.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            yield ExtractionEvent("error", {"message": "ANTHROPIC_API_KEY not set"})
            return

        client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=3)
        tools = _build_tool_definitions()
        model = self.config.model or "claude-sonnet-4-20250514"

        messages = [{"role": "user", "content": user_message}]

        for iteration in range(self.config.max_iterations):
            if self._extraction_complete:
                break

            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools,
                )
            except Exception as e:
                yield ExtractionEvent("error", {"message": f"LLM API error: {str(e)}", "iteration": iteration})
                break

            # Extract text blocks
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    yield ExtractionEvent("thinking", {"text": block.text, "iteration": iteration})

            # Check if done
            if response.stop_reason == "end_turn":
                if not self._extraction_complete:
                    self._extraction_complete = True
                    self._completion_summary = "LLM ended extraction (end_turn)"
                break

            # Handle tool use
            if response.stop_reason == "tool_use":
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input
                        tool_use_id = block.id

                        yield ExtractionEvent("tool_call", {
                            "tool": tool_name,
                            "input": _truncate_for_event(tool_input),
                            "iteration": iteration,
                        })

                        result = await self._execute_tool(tool_name, tool_input)

                        # Yield specific events for graph-building tools
                        async for sub_event in self._yield_tool_events(tool_name, tool_input, result):
                            yield sub_event

                        yield ExtractionEvent("tool_result", {
                            "tool": tool_name,
                            "success": result.get("success", False),
                            "summary": result.get("summary", ""),
                            "iteration": iteration,
                        })

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps(result),
                        })

                # Append assistant message + tool results to conversation
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

        if not self._extraction_complete:
            self._extraction_complete = True
            self._completion_summary = f"Reached max iterations ({self.config.max_iterations})"
            yield ExtractionEvent("phase", {
                "phase": "max_iterations",
                "message": f"Reached maximum {self.config.max_iterations} iterations",
            })

    # -------------------------------------------------------------------
    # OpenAI loop
    # -------------------------------------------------------------------

    async def _run_openai_loop(self, user_message: str) -> AsyncGenerator[ExtractionEvent, None]:
        """Agentic tool-calling loop using OpenAI."""
        try:
            import openai
        except ImportError:
            yield ExtractionEvent("error", {"message": "openai package not installed"})
            return

        api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            yield ExtractionEvent("error", {"message": "OPENAI_API_KEY not set"})
            return

        client = openai.AsyncOpenAI(api_key=api_key, max_retries=3)
        tools = _to_openai_tools(_build_tool_definitions())
        model = self.config.model or "gpt-4o"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        for iteration in range(self.config.max_iterations):
            if self._extraction_complete:
                break

            try:
                response = await client.chat.completions.create(
                    model=model,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    messages=messages,
                    tools=tools,
                )
            except Exception as e:
                yield ExtractionEvent("error", {"message": f"LLM API error: {str(e)}", "iteration": iteration})
                break

            choice = response.choices[0]

            # Extract text
            if choice.message.content:
                yield ExtractionEvent("thinking", {"text": choice.message.content, "iteration": iteration})

            # Check if done
            if choice.finish_reason == "stop":
                if not self._extraction_complete:
                    self._extraction_complete = True
                    self._completion_summary = "LLM ended extraction (stop)"
                break

            # Handle tool calls
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                messages.append(choice.message)

                for tc in choice.message.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_input = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_input = {}

                    yield ExtractionEvent("tool_call", {
                        "tool": tool_name,
                        "input": _truncate_for_event(tool_input),
                        "iteration": iteration,
                    })

                    result = await self._execute_tool(tool_name, tool_input)

                    async for sub_event in self._yield_tool_events(tool_name, tool_input, result):
                        yield sub_event

                    yield ExtractionEvent("tool_result", {
                        "tool": tool_name,
                        "success": result.get("success", False),
                        "summary": result.get("summary", ""),
                        "iteration": iteration,
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    })

        if not self._extraction_complete:
            self._extraction_complete = True
            self._completion_summary = f"Reached max iterations ({self.config.max_iterations})"

    # -------------------------------------------------------------------
    # Tool execution
    # -------------------------------------------------------------------

    async def _execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Route a tool call to the appropriate handler."""
        try:
            if name == "list_integrations":
                return self._tool_list_integrations()
            elif name == "discover_warehouse_assets":
                return await self._tool_discover_assets(args, "warehouse")
            elif name == "discover_dbt_assets":
                return await self._tool_discover_assets(args, "transformation")
            elif name == "discover_orchestration_workflows":
                return await self._tool_discover_assets(args, "orchestration")
            elif name == "discover_ingestion_connectors":
                return await self._tool_discover_assets(args, "ingestion")
            elif name == "discover_bi_assets":
                return await self._tool_discover_assets(args, "reporting")
            elif name == "discover_infrastructure":
                return await self._tool_discover_assets(args, "infrastructure")
            elif name == "discover_version_control":
                return await self._tool_discover_assets(args, "version_control")
            elif name == "discover_quality_data":
                return await self._tool_discover_assets(args, "quality")
            elif name == "add_node":
                return self._tool_add_node(args)
            elif name == "add_edge":
                return self._tool_add_edge(args)
            elif name == "get_graph_summary":
                return self._tool_get_graph_summary()
            elif name == "mark_extraction_complete":
                return self._tool_mark_complete(args)
            else:
                return {"success": False, "error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error("[LLMExtractor] Tool %s failed: %s", name, e, exc_info=True)
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------
    # Query tools (delegate to adapters)
    # -------------------------------------------------------------------

    def _tool_list_integrations(self) -> Dict[str, Any]:
        """List all available integrations."""
        integrations = []
        for adapter_id, tc in self._tool_configs.items():
            category = _TOOL_CATEGORY.get(tc.tool_type.lower(), "other")
            discover_tool = _CATEGORY_TO_TOOL.get(category, "discover_warehouse_assets")
            integrations.append({
                "integration_id": adapter_id,
                "tool_type": tc.tool_type,
                "category": category,
                "discover_tool": discover_tool,
                "layer": tc.layer or category,
            })
        return {
            "success": True,
            "summary": f"Found {len(integrations)} integrations",
            "integrations": integrations,
        }

    async def _tool_discover_assets(
        self, args: Dict[str, Any], expected_category: str,
    ) -> Dict[str, Any]:
        """Discover assets from an adapter. Returns nodes + edges for LLM."""
        integration_id = args.get("integration_id", "")

        # Find the adapter
        adapter = self._adapters.get(integration_id)
        if not adapter:
            # Try matching by tool_type
            for aid, tc in self._tool_configs.items():
                cat = _TOOL_CATEGORY.get(tc.tool_type.lower(), "other")
                if cat == expected_category:
                    adapter = self._adapters.get(aid)
                    integration_id = aid
                    break

        if not adapter:
            return {
                "success": False,
                "error": f"No adapter found for integration_id={integration_id} (category={expected_category})",
                "summary": "Integration not found",
            }

        tc = self._tool_configs.get(integration_id)
        if not tc:
            return {"success": False, "error": "No config found", "summary": "Config not found"}

        adapter_config = _build_adapter_config(tc)

        # Discover assets
        try:
            nodes = adapter.discover_assets(adapter_config)
        except Exception as e:
            logger.warning("[LLMExtractor] discover_assets failed for %s: %s", integration_id, e)
            return {"success": False, "error": str(e), "summary": f"Discovery failed: {e}"}

        # Extract lineage edges
        try:
            edges = adapter.extract_lineage(adapter_config)
        except Exception as e:
            logger.warning("[LLMExtractor] extract_lineage failed for %s: %s", integration_id, e)
            edges = []

        # Format for LLM (truncated for context window)
        formatted_nodes = []
        for n in nodes[:200]:  # Cap at 200
            node_info = {
                "id": n.id,
                "name": n.name,
                "fqn": n.fqn,
                "type": n.node_type.value,
                "platform": n.platform,
                "platform_domain": n.platform_domain.value,
            }
            if n.database:
                node_info["database"] = n.database
            if n.schema:
                node_info["schema"] = n.schema
            if n.columns:
                node_info["columns"] = [
                    {"name": c.get("name"), "type": c.get("type", c.get("data_type", ""))}
                    for c in n.columns[:20]  # Cap columns
                ]
                if len(n.columns) > 20:
                    node_info["columns_truncated"] = len(n.columns)
            if n.row_count is not None:
                node_info["row_count"] = n.row_count
            if n.description:
                node_info["description"] = n.description[:200]
            if n.raw_metadata:
                # Include relevant metadata keys
                for key in ("depends_on", "sql", "schedule", "destination_table",
                            "source_type", "connector_type", "materialized"):
                    if key in n.raw_metadata:
                        val = n.raw_metadata[key]
                        if isinstance(val, str) and len(val) > 500:
                            val = val[:500] + "..."
                        node_info[key] = val
            formatted_nodes.append(node_info)

        formatted_edges = []
        for e in edges[:200]:  # Cap at 200
            formatted_edges.append({
                "source_id": e.source_id,
                "target_id": e.target_id,
                "edge_type": e.edge_type.value,
                "confidence": e.confidence,
            })

        result = {
            "success": True,
            "summary": f"Found {len(nodes)} assets and {len(edges)} edges from {tc.tool_type}",
            "tool_type": tc.tool_type,
            "integration_id": integration_id,
            "nodes": formatted_nodes,
            "edges": formatted_edges,
        }

        if len(nodes) > 200:
            result["nodes_truncated"] = f"Showing 200 of {len(nodes)} total"
        if len(edges) > 200:
            result["edges_truncated"] = f"Showing 200 of {len(edges)} total"

        return result

    # -------------------------------------------------------------------
    # Graph-building tools
    # -------------------------------------------------------------------

    def _tool_add_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Add a node to the graph."""
        node_id = args.get("node_id", "").lower().strip()
        if not node_id:
            return {"success": False, "error": "node_id is required", "summary": "Missing node_id"}

        # Check for duplicate
        if node_id in self._graph.nodes:
            return {
                "success": True,
                "action": "skipped",
                "summary": f"Node {node_id} already exists",
                "node_id": node_id,
            }

        # Check node limit
        if len(self._graph.nodes) >= self.config.max_nodes:
            return {
                "success": False,
                "error": f"Maximum node limit ({self.config.max_nodes}) reached",
                "summary": "Node limit reached",
            }

        # Parse node type
        try:
            node_type = NodeType(args.get("node_type", "unknown"))
        except ValueError:
            node_type = NodeType.UNKNOWN

        # Parse platform domain
        try:
            platform_domain = PlatformDomain(args.get("platform_domain", "other"))
        except ValueError:
            platform_domain = PlatformDomain.OTHER

        name = args.get("name", node_id.split(":")[-1] if ":" in node_id else node_id)
        platform = args.get("platform", "unknown")
        database = args.get("database")
        schema = args.get("schema")
        description = args.get("description")
        integration_id = args.get("integration_id")
        namespace = args.get("namespace")
        zone_hint = args.get("zone_hint")
        dbt_path = args.get("dbt_path")
        dbt_resource_type = args.get("dbt_resource_type")

        # Build FQN
        parts = [p for p in [database, schema, name] if p]
        fqn = ".".join(parts) if parts else name

        # Build raw_metadata with zone/dbt hints for downstream classification
        raw_metadata: Dict[str, Any] = {"case_hint": "lower"}
        if zone_hint:
            raw_metadata["zone"] = zone_hint
        if dbt_path:
            raw_metadata["dbt_path"] = dbt_path
        if dbt_resource_type:
            raw_metadata["dbt_resource_type"] = dbt_resource_type

        node = LineageNode(
            id=node_id,
            name=name,
            fqn=fqn,
            node_type=node_type,
            platform=platform,
            platform_domain=platform_domain,
            database=database,
            schema=schema,
            namespace=namespace,
            description=description,
            integration_id=integration_id,
            raw_metadata=raw_metadata,
            sources=["llm_extractor"],
        )

        self._graph.add_node(node)

        return {
            "success": True,
            "action": "added",
            "summary": f"Added {node_type.value} node: {name}",
            "node_id": node_id,
            "total_nodes": len(self._graph.nodes),
        }

    def _tool_add_edge(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Add an edge to the graph."""
        source_id = args.get("source_id", "").lower().strip()
        target_id = args.get("target_id", "").lower().strip()

        if not source_id or not target_id:
            return {"success": False, "error": "source_id and target_id are required", "summary": "Missing IDs"}

        # Validate endpoints exist
        if source_id not in self._graph.nodes:
            return {
                "success": False,
                "error": f"Source node '{source_id}' not found in graph",
                "summary": f"Source node not found: {source_id}",
            }
        if target_id not in self._graph.nodes:
            return {
                "success": False,
                "error": f"Target node '{target_id}' not found in graph",
                "summary": f"Target node not found: {target_id}",
            }

        # Self-loops
        if source_id == target_id:
            return {"success": False, "error": "Self-loops not allowed", "summary": "Self-loop rejected"}

        # Check edge limit
        if len(self._graph.edges) >= self.config.max_edges:
            return {
                "success": False,
                "error": f"Maximum edge limit ({self.config.max_edges}) reached",
                "summary": "Edge limit reached",
            }

        # Parse edge type
        try:
            edge_type = EdgeType(args.get("edge_type", "derived_from"))
        except ValueError:
            edge_type = EdgeType.DERIVED_FROM

        confidence = min(1.0, max(0.0, float(args.get("confidence", 0.5))))
        evidence_text = args.get("evidence", "LLM-inferred")

        edge_id = generate_edge_id(source_id, target_id, edge_type.value, "table", "llm_extractor")

        # Check for duplicate edge
        if edge_id in self._graph.edges:
            return {
                "success": True,
                "action": "skipped",
                "summary": f"Edge already exists: {source_id} → {target_id}",
                "edge_id": edge_id,
            }

        evidence = Evidence(
            adapter_id="llm_extractor",
            source_ref="llm_reasoning",
            observed_at=datetime.now(timezone.utc),
            snippet=evidence_text[:200],
        )

        # Determine plane
        source_node = self._graph.nodes[source_id]
        target_node = self._graph.nodes[target_id]
        source_domain = source_node.platform_domain
        target_domain = target_node.platform_domain
        if source_domain != target_domain:
            plane = LinePlane.CROSS
        elif source_domain == PlatformDomain.ORCHESTRATION:
            plane = LinePlane.CONTROL
        else:
            plane = LinePlane.DATA

        edge = LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            lineage_level=LineageLevel.TABLE,
            confidence=confidence,
            discovered_from="llm_extractor",
            discovered_at=datetime.now(timezone.utc),
            evidence=[evidence],
            plane=plane,
        )

        self._graph.add_edge(edge)

        return {
            "success": True,
            "action": "added",
            "summary": f"Added edge: {source_id} → {target_id} ({edge_type.value})",
            "edge_id": edge_id,
            "total_edges": len(self._graph.edges),
        }

    def _tool_get_graph_summary(self) -> Dict[str, Any]:
        """Return a summary of the current graph state."""
        nodes_by_platform: Dict[str, int] = {}
        nodes_by_domain: Dict[str, int] = {}
        for node in self._graph.nodes.values():
            p = node.platform or "unknown"
            nodes_by_platform[p] = nodes_by_platform.get(p, 0) + 1
            d = node.platform_domain.value
            nodes_by_domain[d] = nodes_by_domain.get(d, 0) + 1

        # Find orphans (nodes with no edges)
        connected = set()
        for edge in self._graph.edges.values():
            connected.add(edge.source_id)
            connected.add(edge.target_id)
        orphans = [nid for nid in self._graph.nodes if nid not in connected]

        return {
            "success": True,
            "summary": f"Graph has {len(self._graph.nodes)} nodes and {len(self._graph.edges)} edges",
            "total_nodes": len(self._graph.nodes),
            "total_edges": len(self._graph.edges),
            "nodes_by_platform": nodes_by_platform,
            "nodes_by_domain": nodes_by_domain,
            "orphan_count": len(orphans),
            "orphan_nodes": orphans[:30],  # Cap for context window
        }

    def _tool_mark_complete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Mark extraction as complete."""
        self._extraction_complete = True
        self._completion_summary = args.get("summary", "Extraction completed")
        self._unresolved_gaps = args.get("unresolved_gaps", [])

        return {
            "success": True,
            "summary": "Extraction marked complete",
            "final_stats": {
                "total_nodes": len(self._graph.nodes),
                "total_edges": len(self._graph.edges),
            },
        }

    # -------------------------------------------------------------------
    # Strict accountant: normalization & validation
    # -------------------------------------------------------------------

    def _build_namespace_lookup(self, tool_configs: List[ToolConfig]) -> Dict[str, str]:
        """Derive namespace (project/account/host) from each tool config."""
        lookup: Dict[str, str] = {}
        for tc in tool_configs:
            tool_lower = tc.tool_type.lower()
            cfg = tc.config or {}
            ns = None
            if tool_lower == "bigquery":
                ns = cfg.get("project_id") or cfg.get("project")
            elif tool_lower == "snowflake":
                ns = cfg.get("account") or cfg.get("account_identifier")
            elif tool_lower in ("postgres", "redshift"):
                ns = cfg.get("host") or cfg.get("hostname")
            elif tool_lower in ("dbt_cloud", "dbt_core"):
                ns = cfg.get("project_id") or cfg.get("project_name")
            elif tool_lower == "databricks":
                ns = cfg.get("host") or cfg.get("workspace_url")
            elif tool_lower == "looker":
                ns = cfg.get("host") or cfg.get("base_url")
            elif tool_lower in ("n8n", "airflow"):
                ns = cfg.get("host") or cfg.get("base_url") or cfg.get("url")
            elif tool_lower in ("fivetran", "airbyte"):
                ns = cfg.get("account_id")
            if ns:
                lookup[tool_lower] = str(ns).lower().strip()
        return lookup

    def _normalize_and_validate(self) -> Dict[str, Any]:
        """
        Strict accountant phase: normalize, enrich, dedup, and validate
        the LLM-built graph before canonicalization.
        """
        stats: Dict[str, Any] = {}

        stats["identifiers_normalized"] = self._normalize_identifiers()
        stats["namespaces_filled"] = self._fill_missing_namespaces()
        stats["zones_enriched"] = self._enrich_zone_metadata()
        stats["nodes_deduped"] = self._deduplicate_nodes()
        edge_stats = self._validate_edges()
        stats.update(edge_stats)
        stats["confidence_adjusted"] = self._normalize_confidence()

        logger.info(
            "[LLMExtractor] Strict accountant: %s",
            ", ".join(f"{k}={v}" for k, v in stats.items() if v),
        )
        return stats

    def _normalize_identifiers(self) -> int:
        """Lowercase all names, rebuild FQNs consistently."""
        modified = 0
        for node in self._graph.nodes.values():
            hint = node.raw_metadata.get("case_hint", "lower")
            old_name = node.name
            node.name = normalize_identifier(node.name, hint)
            if node.database:
                node.database = normalize_identifier(node.database, hint)
            if node.schema:
                node.schema = normalize_identifier(node.schema, hint)
            # Rebuild FQN from normalized parts
            parts = [p for p in [node.database, node.schema, node.name] if p]
            node.fqn = ".".join(parts) if parts else node.name
            if node.name != old_name:
                modified += 1
        return modified

    def _fill_missing_namespaces(self) -> int:
        """Fill namespace from _namespace_lookup for nodes missing it."""
        filled = 0
        for node in self._graph.nodes.values():
            if node.namespace:
                continue
            platform = (node.platform or "").lower()
            ns = self._namespace_lookup.get(platform)
            if ns:
                node.namespace = ns
                filled += 1
            elif node.database and platform in ("bigquery",):
                # For BigQuery, database IS the project (namespace)
                node.namespace = node.database.lower()
                filled += 1
        return filled

    def _enrich_zone_metadata(self) -> int:
        """Classify dataset zones and persist in raw_metadata."""
        enriched = 0
        for node in self._graph.nodes.values():
            if node.platform_domain not in (PlatformDomain.WAREHOUSE, PlatformDomain.TRANSFORM):
                continue
            if node.raw_metadata.get("zone"):
                continue  # LLM already provided a zone hint
            zone = classify_dataset_zone(node)
            if zone != DatasetZone.UNKNOWN:
                node.raw_metadata["zone"] = zone.value
                enriched += 1
        return enriched

    def _deduplicate_nodes(self) -> int:
        """Merge nodes with same (platform_domain, namespace, schema, name)."""
        by_key: Dict[Tuple[str, str, str, str], List[str]] = defaultdict(list)
        for node_id, node in self._graph.nodes.items():
            if not node.name:
                continue
            key = (
                node.platform_domain.value,
                (node.namespace or "").lower(),
                (node.schema or "").lower(),
                node.name.lower(),
            )
            by_key[key].append(node_id)

        removed = 0
        id_remap: Dict[str, str] = {}

        for key, node_ids in by_key.items():
            if len(node_ids) <= 1:
                continue
            # Sort for deterministic winner
            node_ids.sort()
            primary_id = node_ids[0]
            primary = self._graph.nodes[primary_id]

            for dup_id in node_ids[1:]:
                dup = self._graph.nodes[dup_id]
                # Merge metadata from loser into winner
                if dup.description and not primary.description:
                    primary.description = dup.description
                if dup.columns and len(dup.columns) > len(primary.columns):
                    primary.columns = dup.columns
                if dup.row_count and not primary.row_count:
                    primary.row_count = dup.row_count
                if dup.database and not primary.database:
                    primary.database = dup.database
                if dup.namespace and not primary.namespace:
                    primary.namespace = dup.namespace
                for src in dup.sources:
                    if src not in primary.sources:
                        primary.sources.append(src)
                for mk, mv in dup.raw_metadata.items():
                    if mk not in primary.raw_metadata:
                        primary.raw_metadata[mk] = mv
                # Merge evidence
                primary.evidence.extend(dup.evidence)

                id_remap[dup_id] = primary_id
                del self._graph.nodes[dup_id]
                removed += 1

        # Remap edge references
        if id_remap:
            edges_to_remove = []
            for edge_id, edge in self._graph.edges.items():
                edge.source_id = id_remap.get(edge.source_id, edge.source_id)
                edge.target_id = id_remap.get(edge.target_id, edge.target_id)
                if edge.source_id == edge.target_id:
                    edges_to_remove.append(edge_id)
            for eid in edges_to_remove:
                del self._graph.edges[eid]

        if removed:
            logger.info("[LLMExtractor] Dedup: removed %d duplicate nodes", removed)
        return removed

    def _validate_edges(self) -> Dict[str, int]:
        """Remove dangling edges and flag edges without evidence."""
        stats = {"removed_dangling": 0, "flagged_no_evidence": 0}
        edges_to_remove = []

        for edge_id, edge in self._graph.edges.items():
            if edge.source_id not in self._graph.nodes or edge.target_id not in self._graph.nodes:
                edges_to_remove.append(edge_id)
                stats["removed_dangling"] += 1
                continue

            has_meaningful_evidence = False
            for ev in edge.evidence:
                if ev.snippet and ev.snippet.strip() and ev.snippet.lower() != "llm-inferred":
                    has_meaningful_evidence = True
                    break

            if not has_meaningful_evidence:
                edge.inferred = True
                stats["flagged_no_evidence"] += 1

        for eid in edges_to_remove:
            del self._graph.edges[eid]
        return stats

    def _normalize_confidence(self) -> int:
        """Cap confidence based on evidence quality."""
        adjusted = 0
        for edge in self._graph.edges.values():
            has_manifest = False
            has_sql = False
            has_api = False

            for ev in edge.evidence:
                snippet_lower = (ev.snippet or "").lower()
                if any(kw in snippet_lower for kw in ("manifest", "depends_on", "config", "sync")):
                    has_manifest = True
                elif any(kw in snippet_lower for kw in ("sql", "select", "from", "join", "query", "view_def")):
                    has_sql = True
                elif any(kw in snippet_lower for kw in ("api", "metadata", "connector")):
                    has_api = True

            if has_manifest:
                max_conf = 0.95
            elif has_sql:
                max_conf = 0.9
            elif has_api:
                max_conf = 0.8
            else:
                max_conf = 0.7

            if edge.confidence > max_conf:
                edge.confidence = max_conf
                adjusted += 1
        return adjusted

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _build_user_message(self, tool_configs: List[ToolConfig]) -> str:
        """Build the initial user message describing the pipeline stack."""
        lines = ["Please extract the complete data lineage for this pipeline stack.\n"]
        lines.append("Connected integrations:")
        for tc in tool_configs:
            category = _TOOL_CATEGORY.get(tc.tool_type.lower(), "other")
            lines.append(f"  - {tc.tool_type} (id: {tc.integration_id or 'auto'}, category: {category})")
        lines.append("")
        lines.append("Start by calling list_integrations, then discover assets from each tool, "
                      "build the graph with add_node and add_edge, and call mark_extraction_complete when done.")
        return "\n".join(lines)

    def _build_views(self, tool_nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Build rendered views from the final graph."""
        views: Dict[str, Dict[str, Any]] = {}
        builder = ViewBuilder(self._graph, tool_nodes=tool_nodes)

        for view_name, build_fn in [
            ("pipeline_overview", builder.build_pipeline_overview),
            ("data_plane", builder.build_data_plane),
            ("lane_pipeline_overview", builder.build_lane_pipeline_overview),
        ]:
            try:
                view = build_fn()
                views[view_name] = view.to_dict()
            except Exception as e:
                logger.warning("[LLMExtractor] %s view failed: %s", view_name, e)

        return views

    async def _yield_tool_events(
        self, tool_name: str, tool_input: Dict, result: Dict,
    ) -> AsyncGenerator[ExtractionEvent, None]:
        """Yield specific events for node/edge additions."""
        if tool_name == "add_node" and result.get("action") == "added":
            yield ExtractionEvent("node_added", {
                "node_id": result.get("node_id"),
                "name": tool_input.get("name"),
                "node_type": tool_input.get("node_type"),
                "platform": tool_input.get("platform"),
                "total_nodes": result.get("total_nodes", 0),
            })
        elif tool_name == "add_edge" and result.get("action") == "added":
            yield ExtractionEvent("edge_added", {
                "source_id": tool_input.get("source_id"),
                "target_id": tool_input.get("target_id"),
                "edge_type": tool_input.get("edge_type"),
                "total_edges": result.get("total_edges", 0),
            })

    @property
    def graph(self) -> LineageGraph:
        """Access the built graph after extraction."""
        return self._graph


def _truncate_for_event(data: Any, max_len: int = 200) -> Any:
    """Truncate data for SSE events to keep them small."""
    if isinstance(data, str) and len(data) > max_len:
        return data[:max_len] + "..."
    if isinstance(data, dict):
        return {k: _truncate_for_event(v, max_len) for k, v in list(data.items())[:10]}
    if isinstance(data, list) and len(data) > 5:
        return data[:5] + [f"... and {len(data) - 5} more"]
    return data
