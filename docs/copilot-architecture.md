# Pallisade Copilot — Architecture & Reference

## Table of Contents

1. [Overview](#1-overview)
2. [End-to-End Request Flow](#2-end-to-end-request-flow)
3. [LLM Provider Routing](#3-llm-provider-routing)
4. [System Prompt](#4-system-prompt)
5. [Context Building](#5-context-building)
6. [Interaction Modes](#6-interaction-modes)
7. [Tool Registry](#7-tool-registry)
8. [Tool Execution](#8-tool-execution)
9. [Streaming & Confirmation Flow](#9-streaming--confirmation-flow)
10. [Database Persistence](#10-database-persistence)
11. [Key Design Decisions](#11-key-design-decisions)

---

## 1. Overview

The Pallisade Copilot is an AI-powered data pipeline assistant that can query warehouses, trace lineage, debug failures, generate fixes, and more. It uses LLM tool calling to interact with the user's connected integrations in real time.

### Tech Stack

```
Frontend (Next.js 15)
    → Next.js API route (/api/copilot/chat)
        → FastAPI backend (/api/v1/copilot/chat)
            → LLM (Claude or GPT) with tool calling
                → ToolExecutor → Adapters (BigQuery, Snowflake, dbt, Airflow, etc.)
```

### Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `scanner/copilot/llm.py` | ~1,836 | LLM integration, system prompt, streaming, tool loop |
| `scanner/copilot/context_builder.py` | ~1,306 | Context assembly, schema fetching, lineage prompt |
| `scanner/copilot/tool_executor.py` | ~5,000 | Tool routing, adapter management, query execution |
| `scanner/copilot/tools.py` | ~1,461 | Tool definitions, registry, format conversion |
| `scanner/copilot/modes.py` | ~702 | Interaction modes, auto-detection, slash commands |
| `scanner/api/routers/copilot.py` | — | FastAPI endpoints |
| `app/api/copilot/chat/route.ts` | — | Next.js API proxy, auth, session management |
| `app/(dashboard)/dashboard/assistant/page.tsx` | — | Frontend chat UI |
| `hooks/useStreamingChat.ts` | — | SSE streaming hook |

---

## 2. End-to-End Request Flow

### Data Flow Diagram

```
User types message in chat UI
    │
    ▼
Frontend (useStreamingChat hook)
    │  POST /api/copilot/chat  { message, sessionId, model, mode, stream: true }
    ▼
Next.js API Route (app/api/copilot/chat/route.ts)
    │  1. Authenticate user (NextAuth session)
    │  2. Fetch/create CopilotSession in DB
    │  3. Save user message to CopilotMessage table
    │  4. Load conversation history from DB
    │  5. resolveStackIntegrations() → get credentials
    │  6. Fetch lineage nodes/edges from DB
    │  7. POST to FastAPI with full payload
    ▼
FastAPI Router (scanner/api/routers/copilot.py)
    │  1. Parse slash command (/debug, /plan, etc.)
    │  2. Auto-detect mode if not specified
    │  3. Build CopilotContext (integrations, lineage, schema)
    │  4. Initialize CopilotLLM (Anthropic or OpenAI)
    ▼
CopilotLLM.chat_stream() (scanner/copilot/llm.py)
    │  1. Pre-fetch warehouse schema
    │  2. Build system prompt with context
    │  3. Convert tools to provider format
    ▼
┌─────────────────────────────────────┐
│         TOOL CALLING LOOP           │
│  (max 15 iterations)                │
│                                     │
│  1. Call LLM with messages + tools  │
│  2. If stop_reason == end_turn:     │
│     → return response               │
│  3. If stop_reason == tool_use:     │
│     → Execute tool via ToolExecutor │
│     → Inject result into messages   │
│     → Loop back to step 1           │
└─────────────────────────────────────┘
    │
    ▼
SSE Stream → Next.js proxy → Frontend
    │  Events: text_delta, tool_call_start,
    │  tool_call_result, done, error
    ▼
Next.js saves AI response + tokens to DB
```

### Request Payload (Next.js → FastAPI)

```json
{
  "message": "how many orders do I have?",
  "messages": [ /* full conversation history */ ],
  "session_id": "clx...",
  "pipeline_stack_id": "clx...",
  "node_ids": [],
  "referenced_entities": [],
  "model": "gpt-5.2",
  "mode": "ask",
  "integrations": [
    {
      "id": "...", "name": "BigQuery", "type": "BIGQUERY",
      "layer": "warehouse", "status": "active",
      "config": { "project_id": "my-project", "dataset": "analytics", ... }
    }
  ],
  "lineage": {
    "nodes": [ { "id": "...", "name": "analytics.orders", "node_type": "TABLE", ... } ],
    "edges": [ { "source_id": "...", "target_id": "...", "edge_type": "TABLE_TO_TABLE", ... } ]
  }
}
```

### Field Mappings

| Frontend | FastAPI | Notes |
|----------|---------|-------|
| `pipelineStackId` | `pipeline_stack_id` | Both spellings accepted |
| User `username` | Mapped to `user` | In `resolveStackIntegrations()` |
| `toolCalls` (camelCase) | `tool_calls` (snake_case) | Tool confirmation wraps execution |

---

## 3. LLM Provider Routing

### Supported Models

```python
MODELS = {
    # OpenAI (default — higher rate limits)
    "gpt-5.2":      {"provider": "openai",    "model": "gpt-5.2"},
    "gpt-5.2-mini": {"provider": "openai",    "model": "gpt-5.2-mini"},
    "o3-mini":      {"provider": "openai",    "model": "o3-mini"},

    # Anthropic
    "claude-sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
    "claude-opus":   {"provider": "anthropic", "model": "claude-opus-4-20250514"},
    "claude-haiku":  {"provider": "anthropic", "model": "claude-haiku-4-20250514"},
}

DEFAULT_MODEL = "gpt-5.2"
```

### Provider Differences

| Aspect | Anthropic (Claude) | OpenAI (GPT) |
|--------|--------------------|--------------|
| Tool call format | `tools` parameter, `tool_use` content blocks | `tools` parameter, `tool_calls` on assistant message |
| Tool result format | `tool_result` content block in user message | `tool` role message with `tool_call_id` |
| System prompt | First `user` message or `system` parameter | `system` role message |
| Streaming | `messages.stream()` | `chat.completions.create(stream=True)` |
| Stop signal | `stop_reason == "end_turn"` | `finish_reason == "stop"` |

### Core Data Structures

```python
@dataclass
class Message:
    role: str          # "user", "assistant", "system"
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None

@dataclass
class CopilotResponse:
    content: str
    tool_calls: List[Dict[str, Any]]
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str
```

---

## 4. System Prompt

The system prompt is built dynamically in `CopilotLLM.build_system_prompt()` and consists of these sections assembled in order:

### 4.1. Critical Rules

The LLM receives 11 mandatory rules:

1. **EXECUTE READ QUERIES IMMEDIATELY** — Don't ask permission for read-only tools. Just run them.
2. **ALWAYS RUN THE QUERY** — When you know what to query, execute it. Don't preview SQL.
3. **GIVE DIRECT ANSWERS** — State answers clearly with the source table. No "Here's a query you could run..."
4. **USE THE SCHEMA PROVIDED** — Use only exact column names from the schema section.
5. **NEVER HALLUCINATE COLUMNS** — If unsure, check schema. Don't guess.
6. **DO NOT QUERY INFORMATION_SCHEMA** — Schema is pre-loaded. Go straight to data queries.
7. **MATCH DEPTH TO QUESTION COMPLEXITY** — Simple questions: 1 query. Investigations: 5-8 queries.
8. **USE REAL NAMES, NEVER PLACEHOLDERS** — Use actual project/dataset/table names from config.
9. **ANSWERS MUST BE PIPELINE-SPECIFIC** — Base suggestions on actual config, not generic examples.
10. **IMPACT ANALYSIS FOR CHANGES** — Call lineage tools before proposing changes. Report breaking changes.
11. **SYNTHESIZE TOOL RESULTS** — Interpret results. Never dump raw JSON.

### 4.2. Impact Analysis Requirements

For PLAN, FIX, CREATE modes — mandatory before any change:
1. Run `get_downstream` on all objects being changed
2. Report breaking changes in a table format
3. Include fixes for ALL downstream breakages

Exception: Skip for documentation files (.md, .txt, README), config-only files.

### 4.3. Investigation Workflow

For debugging/comparison questions — deep-dive process:
1. Gather evidence with discovery queries
2. Use `run_coverage_monitor` (anomaly type) for anomaly detection — **mandatory, not manual SQL**
3. Check every connected warehouse
4. Drill into specifics after overview
5. Check metadata via INFORMATION_SCHEMA when needed
6. Read logs (Airflow, Fivetran, Airbyte)
7. Chain queries — use results to inform next steps
8. Synthesize findings with root cause and fix

### 4.4. Warehouse-Specific SQL Syntax

Dynamically generated based on connected warehouses:

| Warehouse | Identifier Style | Key Syntax |
|-----------|-----------------|------------|
| BigQuery | Backticks: `` `project.dataset.table` `` | `FORMAT_TIMESTAMP`, `SAFE_DIVIDE` |
| Snowflake | Double quotes or uppercase: `DATABASE.SCHEMA.TABLE` | `TRY_TO_NUMBER`, `TRY_TO_DATE` |
| PostgreSQL / Redshift | Lowercase: `schema.table` | `TO_CHAR`, `COALESCE` |
| SQL Server / Azure SQL | Square brackets: `[schema].[table]` | `TOP N` instead of `LIMIT` |

When multiple warehouses are connected, the prompt includes a warning: "You MUST specify the `warehouse` parameter to target the correct one."

### 4.5. Tool Selection Guide

Embedded in the prompt — maps question types to tools:

- **Simple data questions** → ONE `query_warehouse` call
- **Multi-table questions** → Combine into ONE query (UNION ALL / JOINs)
- **Investigation** → Start with ONE comprehensive diagnostic, then follow-ups
- **Cross-warehouse comparison** → 2 queries max (one per warehouse)
- **Lineage questions** → `get_upstream` / `get_downstream`; fallback to `search_lineage` with wildcards
- **Airflow DAG lineage** → `get_airflow_dag_lineage`; fallback to `search_lineage` with `*airflow*`
- **Orchestration context** → `get_asset_orchestration_context` with table FQN
- **Data health / anomalies** → Coverage tools (`get_coverage_report`, `run_coverage_monitor`)
- **dbt questions** → `get_dbt_model`, `get_dbt_run_history`, `get_dbt_test_results`
- **Pipeline failures** → Orchestration tools → task logs → follow-up SQL
- **Ingestion status** → `get_fivetran_connector_status` / `get_airbyte_connection_status`
- **Knowledge / advice** → `search_knowledge_base`

### 4.6. Anomaly Detection Mandate

Hard rule: When users ask about anomalies/outliers/spikes/drops, the LLM **MUST** use `run_coverage_monitor` with `monitor_type: "anomaly"` instead of writing manual SQL. The prompt includes both the correct and incorrect approaches.

### 4.7. Error Recovery

8-step error recovery guide:
1. Wrong column → re-read schema, retry
2. Wrong table → check schema for correct FQN
3. Syntax error → fix using warehouse-specific syntax
4. No results → broaden query
5. Tool returns success → trust it (don't claim "not connected")
6. Tool not connected → use `search_knowledge_base` instead
7. Auth errors → inspect infra config via GitHub tools, suggest fixes
8. Lineage "not found" → `search_lineage` with wildcards, try full FQN

### 4.8. Response Format

- Lead with the answer (number + source table)
- 3-5 short bullet points over paragraphs
- No walls of text, no nested bullets, no italic emphasis
- Never repeat what the user said
- Never use placeholders — always real names

### 4.9. Additional Prompt Sections

After the base rules, these are appended in order:
1. **Mode-specific prompt** — from `mode_config.system_prompt_section`
2. **Preferred tools** — from `mode_config.preferred_tools`
3. **Warehouse SQL syntax** — built from connected warehouse types
4. **Tool selection guide** — efficiency rules
5. **Few-shot examples** — from `_build_few_shot_examples()`
6. **Stack context** — from `context.to_system_prompt_context()` (integrations, lineage catalog, schema)
7. **Onboarded context** — learned facts from onboarding sessions
8. **Schema discovery fallback** — if warehouse connected but schema empty
9. **Knowledge base hints** — if query matches known topics
10. **Available tools list** — names of tools available for user's integrations

---

## 5. Context Building

### CopilotContext

```python
@dataclass
class CopilotContext:
    org_id: str
    query: str = ""
    integrations: List[IntegrationInfo] = []
    integration_types: Set[str] = set()         # {"BIGQUERY", "DBT_CLOUD", ...}

    graph: Optional[LineageGraph] = None         # Basic lineage graph
    engine_store: Optional[GraphStore] = None    # Engine-powered graph (richer)
    relevant_nodes: List[LineageNode] = []

    available_tools: List[str] = []
    warehouse_schema: Dict[str, List[TableSchema]] = {}

    mode: str = "ask"
    mode_config: Optional[ModeConfig] = None
    pipeline_context: Optional[Dict] = None      # Learned from onboarding
    mcp_enabled: bool = False
```

### Integration Layers

```python
class IntegrationLayer(Enum):
    INGESTION = "ingestion"          # Fivetran, Airbyte, Stitch
    TRANSFORMATION = "transformation" # dbt
    WAREHOUSE = "warehouse"          # BigQuery, Snowflake, Postgres, Redshift
    REPORTING = "reporting"          # Looker, Tableau, PowerBI
    OBSERVABILITY = "observability"  # Monte Carlo, Bigeye, Soda, Elementary
```

### Schema Pre-Fetching

Happens in `ToolExecutor.fetch_warehouse_schema()` **before** the system prompt is built:

1. **Skip non-warehouse queries** — detect if query is about GitHub/VCS
2. **Detect target warehouses** — search query text for "bigquery", "snowflake", etc.
3. **Resolve datasets** — try config keys in order:
   - `datasets`, `dataset`, `schema`, `default_dataset`, `datasetId`
   - Fallback: `adapter.dataset` attribute
   - Auto-discover: query `INFORMATION_SCHEMA.SCHEMATA` or `client.list_datasets()`
4. **Fetch schema per dataset** — query `INFORMATION_SCHEMA.TABLES` and `INFORMATION_SCHEMA.COLUMNS`
5. **Return compound keys** — format: `"WAREHOUSE_TYPE:dataset"` (e.g., `"BIGQUERY:raw"`, `"SNOWFLAKE:PUBLIC"`)

### TableSchema Format

```python
@dataclass
class TableSchema:
    name: str
    dataset: str
    columns: List[Dict[str, str]]     # [{name, type, description}]
    row_count: Optional[int] = None
    project: Optional[str] = None      # BigQuery project ID
    warehouse_type: Optional[str] = None
```

### Query-Relevance Scoring

Tables are scored against the user's query to determine which appear in "Most Relevant" vs "Other Available":
- Exact table name match: +10
- Partial name match: +5
- Column name match: +3
- Dataset mention: +2

### Lineage Prompt Tiering

The lineage catalog in the system prompt adapts to graph size:

| Graph Size | Format |
|-----------|--------|
| ≤ 50 nodes | Full catalog with adjacency lists |
| 51–150 nodes | Roots/leaves + query-relevant with adjacency; rest as compact list |
| 150+ nodes | Top 50 relevant + roots/leaves; summary for rest |

---

## 6. Interaction Modes

### Mode Overview

| Mode | Slash Cmd | Color | Description | Key Preferred Tools |
|------|-----------|-------|-------------|---------------------|
| Ask | `/ask` | blue | General questions | `query_warehouse`, `search_knowledge_base`, `get_coverage_report` |
| Debug | `/debug` | red | Investigate failures, root causes | `run_coverage_monitor`, `get_airflow_task_logs`, `get_dbt_test_results` |
| Plan | `/plan` | purple | Migration & refactoring strategies | `get_downstream`, `get_upstream`, `get_dbt_model` |
| Create | `/create` | green | Generate dbt models, tests, configs | `query_warehouse`, `get_dbt_model` |
| Fix | `/fix` | emerald | Generate validated fixes, open PRs | `create_change_plan`, `validate_change_plan`, `run_coverage_monitor` |
| Explain | `/explain` | cyan | Deep understanding & learning | `search_knowledge_base`, `get_upstream`, `get_dbt_model` |
| Suggest | `/suggest` | yellow | Improvement recommendations | `get_coverage_report`, `get_coverage_gaps`, `get_monitor_recommendations` |
| Bundle | `/bundle` | orange | Package artifacts for download | `query_warehouse`, `get_dbt_model` |
| Onboard | `/onboard` | indigo | Interview to learn user's setup | `get_pending_questions`, `save_onboarding_context` |

### Mode Auto-Detection

Each mode has regex patterns for auto-detection from message content:

- **Debug**: `why did .* fail`, `anomal`, `outlier`, `spike`, `unexpected`, `broken`, `not working`
- **Plan**: `migrate`, `refactor`, `strategy`, `redesign`, `how should i`
- **Create**: `create a`, `generate a`, `write a`, `build a .* model`
- **Fix**: `fix (?:the|this|my)`, `apply (?:a|the) fix`, `patch`, `repair`, `correct`
- **Explain**: `what is`, `how does .* work`, `explain`, `teach me`
- **Suggest**: `suggest`, `recommend`, `optimize`, `best practices`
- **Bundle**: `bundle`, `package`, `export`, `download`
- **Onboard**: `start onboarding`, `teach you about`, `learn about my pipeline`

### Mode-Specific Prompt Sections

Each mode injects a system prompt section that defines:
- Investigation methodology
- Required output structure
- Response format rules
- Mandatory steps (e.g., impact analysis for Plan/Fix/Create)

**Debug Mode** enforces:
- Problem / Cause / Fix format
- Under 150 words when possible
- Use `run_coverage_monitor` for anomalies

**Plan Mode** enforces:
- Impact Analysis (MANDATORY FIRST)
- Current State → Proposed Changes → Implementation Steps
- Risks & Mitigations table
- Rollback Plan + Testing Strategy

**Fix Mode** enforces:
- Impact Analysis (MANDATORY FIRST)
- Root Cause Summary
- Complete Fix (all affected objects)
- Validation Plan + Rollback Steps
- Submit via `create_change_plan` tool

**Create Mode** enforces:
- Check downstream before modifying existing objects
- Full file contents (no placeholders)
- Follow existing codebase patterns

**Onboard Mode** enforces:
- Ask ONE question at a time
- Cover ALL connected integration types
- Use `save_onboarding_context` to persist answers
- Summarize learnings per integration

---

## 7. Tool Registry

### Tool Structure

```python
@dataclass
class Tool:
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter]
    required_integrations: Set[str]     # ALL must be present
    alternative_integrations: Set[str]  # ANY one is sufficient
    requires_confirmation: bool = False # For destructive tools
```

**Availability logic**: A tool is available if:
- All `required_integrations` are in the user's set (AND logic)
- At least one `alternative_integrations` is in the user's set (OR logic)
- If neither field is set → always available

### Tool Categories

```python
class ToolCategory(Enum):
    LINEAGE         # Graph traversal, search, impact analysis
    WAREHOUSE       # SQL queries, table stats
    DBT             # Model info, run history, tests
    ORCHESTRATION   # Airflow, Dagster, Prefect, n8n
    INGESTION       # Fivetran, Airbyte
    REPORTING       # Looker, Tableau, Power BI
    STORAGE         # S3, GCS, ADLS
    KNOWLEDGE       # Knowledge base search
    OBSERVABILITY   # Monte Carlo, Bigeye, Soda, Elementary
    COVERAGE        # Coverage analysis & monitors
    CHANGE_PLAN     # Fix generation, validation, PR creation
    ONBOARDING      # Pipeline learning interview
    INFRASTRUCTURE  # Server health, certs, logs
```

### Complete Tool List

#### Lineage Tools (always available with any data integration)

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_upstream` | Trace data sources upstream | `node_id`, `depth`, `level`, `min_confidence`, `system` |
| `get_downstream` | Find all downstream dependents | `node_id`, `depth`, `level`, `min_confidence`, `system` |
| `get_node_details` | Detailed node info (schema, stats, metadata) | `node_id` |
| `search_lineage` | Search graph by name pattern | `query` (wildcards), `node_type`, `limit` |
| `get_column_lineage` | Column-level lineage tracing | `node_id`, `column_name` |
| `analyze_change_impact` | Full change impact assessment | `objects[]`, `change_type`, `details` |
| `explain_edge` | Edge evidence & provenance | `edge_id` |
| `get_lineage_stats` | Coverage stats (nodes, edges, confidence) | — |
| `get_table_dependencies` | Upstream + downstream tables | `table_name`, `direction` |
| `get_asset_orchestration_context` | DAG/task that produces a table | `asset_name` |

#### Warehouse Tools

| Tool | Description | Requires |
|------|-------------|----------|
| `query_warehouse` | Execute read-only SQL (SELECT only) | Any warehouse |
| `get_table_stats` | Row count, size, last updated, column stats | Any warehouse |
| `get_query_history` | Recent queries on a table | Snowflake, BigQuery, or Databricks |

#### dbt Tools

| Tool | Description | Requires |
|------|-------------|----------|
| `get_dbt_model` | Model SQL, dependencies, tests, docs | DBT_CLOUD or DBT_CORE |
| `get_dbt_run_history` | Recent run history | DBT_CLOUD or DBT_CORE |
| `get_dbt_test_results` | Test results for a model | DBT_CLOUD or DBT_CORE |
| `get_dbt_lineage` | dbt-specific parent/child models | DBT_CLOUD or DBT_CORE |

#### Orchestration Tools

| Tool | Requires |
|------|----------|
| `get_dag_run_history` | AIRFLOW |
| `get_dagster_asset_status` | DAGSTER |
| `get_dagster_run_history` | DAGSTER |
| `get_prefect_flow_status` | PREFECT |
| `get_prefect_flow_runs` | PREFECT |
| `get_n8n_workflows` | N8N |
| `get_n8n_workflow_details` | N8N |
| `get_n8n_executions` | N8N |
| `get_n8n_execution_details` | N8N |
| `get_n8n_recent_failures` | N8N |

#### Ingestion Tools

| Tool | Requires |
|------|----------|
| `get_fivetran_connector_status` | FIVETRAN |
| `get_fivetran_sync_logs` | FIVETRAN |
| `get_fivetran_schema_changes` | FIVETRAN |
| `get_airbyte_connection_status` | AIRBYTE |
| `get_airbyte_sync_history` | AIRBYTE |

#### Reporting Tools

| Tool | Requires |
|------|----------|
| `get_looker_dashboard_status` | LOOKER |
| `get_looker_model_info` | LOOKER |
| `get_tableau_workbook_status` | TABLEAU |
| `get_tableau_datasource_info` | TABLEAU |
| `get_tableau_refresh_history` | TABLEAU |
| `get_powerbi_dataset_status` | POWERBI |
| `get_powerbi_refresh_history` | POWERBI |
| `get_powerbi_gateway_status` | POWERBI |

#### Storage Tools

| Tool | Requires |
|------|----------|
| `list_storage_objects` | S3, GCS, or ADLS |
| `get_storage_object_metadata` | S3, GCS, or ADLS |
| `list_storage_buckets` | S3, GCS, or ADLS |

#### Coverage Tools (always available)

| Tool | Description |
|------|-------------|
| `get_coverage_report` | 7-dimension health score (freshness, volume, schema, quality, lineage, ownership, docs) |
| `get_coverage_gaps` | Prioritized gaps by severity |
| `get_node_coverage` | Per-asset coverage breakdown |
| `get_monitor_recommendations` | Actionable monitor configs with SQL templates |
| `run_coverage_monitor` | Execute freshness/volume/schema_change/anomaly monitor with Z-score analysis |

#### Observability Tools

| Tool | Requires |
|------|----------|
| `get_active_incidents` | Monte Carlo, Bigeye, Soda, or Elementary |
| `get_asset_quality` | Monte Carlo, Bigeye, Soda, or Elementary |
| `trace_incident_root_cause` | Monte Carlo, Bigeye, or Elementary |
| `get_quality_checks` | Monte Carlo, Bigeye, Soda, or Elementary |
| `get_incident_details` | Monte Carlo, Bigeye, Soda, or Elementary |

#### Change Plan Tools

| Tool | Description | Confirmation? |
|------|-------------|---------------|
| `create_change_plan` | Create structured fix with patches | No |
| `validate_change_plan` | Static/CI/sandbox validation | No |
| `get_change_plan` | Retrieve plan by ID | No |
| `apply_change_plan` | Create GitHub PR | **Yes** |
| `list_change_plans` | List all plans in session | No |

#### GitHub Tools

| Tool | Requires |
|------|----------|
| `list_github_repos` | GITHUB |
| `get_github_tree` | GITHUB |
| `get_github_file` | GITHUB |

#### Knowledge Base Tools (always available)

| Tool | Description |
|------|-------------|
| `search_knowledge_base` | Expert guidance on data pipeline tools, troubleshooting, best practices |

#### Onboarding Tools (always available)

| Tool | Description |
|------|-------------|
| `get_pending_questions` | Get unanswered onboarding questions |
| `save_onboarding_context` | Save user's answer with extracted facts |
| `complete_onboarding` | Mark onboarding complete |

#### Infrastructure Tools

| Tool | Requires |
|------|----------|
| `check_server_health` | linux_server |
| `check_certificates` | linux_server |
| `analyze_server_logs` | linux_server |
| `list_server_services` | linux_server |

### Tool Format Conversion

Tools are converted to provider-specific formats:
- `to_anthropic_tool()` → `{ name, description, input_schema: { type: "object", properties, required } }`
- `to_openai_tool()` → `{ type: "function", function: { name, description, parameters: { type: "object", properties, required } } }`

### MCP Tool Merging

MCP-discovered tools use prefixed names (e.g., `mcp_snowflake__execute_query`) and are merged with static registry tools at runtime. No name collisions occur.

---

## 8. Tool Execution

### ToolExecutor

```python
class ToolExecutor:
    def __init__(self, context: CopilotContext):
        self.context = context
        self._adapters: Dict[str, Any] = {}
        self._anomaly_baselines: Dict[str, List[float]] = {}
        self._initialize_adapters()

    async def execute(self, tool_name: str, arguments: Dict) -> ToolResult:
        handler = getattr(self, f"_execute_{tool_name}", None)
        return await handler(arguments)
```

### Supported Adapters

| Integration Type | Adapter |
|-----------------|---------|
| BIGQUERY | BigQueryAdapter |
| SNOWFLAKE | SnowflakeAdapter |
| POSTGRES | PostgresAdapter |
| REDSHIFT | RedshiftAdapter |
| DATABRICKS | DatabricksAdapter |
| DBT_CLOUD / DBT_CORE | DbtIntegration |
| AIRFLOW | MCP-based (no legacy handler) |
| DAGSTER | DagsterIntegration |
| PREFECT | PrefectIntegration |
| N8N | N8nIntegration |
| FIVETRAN | FivetranIntegration |
| AIRBYTE | AirbyteIntegration |
| LOOKER | LookerIntegration |
| TABLEAU | TableauIntegration |
| POWERBI | PowerBIIntegration |
| AMAZON_S3 / GCS / ADLS | Storage clients |

### Query Warehouse Execution

The `_execute_query_warehouse()` handler has several safety mechanisms:

1. **SQL validation** — Only allows `SELECT` or `WITH...SELECT` statements
2. **Warehouse targeting** — Uses `warehouse` parameter or infers from SQL syntax
3. **Auto LIMIT injection** — Adds `LIMIT` if not present (smart about CTEs, UNIONs)
4. **Column validation** — Cross-references columns against pre-fetched schema
5. **Error hints** — Suggests correct column/table names on errors
6. **Result serialization** — Handles datetime, Decimal, bytes types

### Warehouse-Specific Schema Queries

**BigQuery:**
```sql
SELECT table_name, table_type FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES`
SELECT table_name, column_name, data_type FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
```

**Snowflake:**
```sql
SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = '{dataset}'
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COMMENT FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{dataset}'
```

**PostgreSQL / Redshift:**
```sql
SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = '{dataset}'
SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = '{dataset}'
```

---

## 9. Streaming & Confirmation Flow

### SSE Event Types

```python
@dataclass
class StreamEvent:
    event_type: str
    data: Dict[str, Any]

    def to_sse(self) -> str:
        return f"event: {self.event_type}\ndata: {json.dumps(self.data)}\n\n"
```

| Event | Data | When |
|-------|------|------|
| `text_delta` | `{ text: "..." }` | Incremental text from LLM |
| `tool_call_start` | `{ tool_name, tool_use_id, arguments }` | Tool execution begins |
| `tool_call_result` | `{ tool_use_id, tool_name, result }` | Tool execution complete |
| `tool_confirmation_required` | `{ tool_use_id, tool_name, arguments, description }` | Destructive tool needs approval |
| `iteration_start` | `{ iteration: N }` | New LLM iteration |
| `done` | `{ input_tokens, output_tokens, model, stop_reason }` | Stream complete |
| `error` | `{ message, type }` | Error occurred |

### Tool Confirmation Flow

For tools with `requires_confirmation = True` (e.g., `apply_change_plan`):

```
1. LLM calls destructive tool
2. Backend yields: tool_confirmation_required event
3. Frontend shows ToolConfirmation component (name, args, description)
4. User clicks "Approve & Execute" or "Deny"
5. If approved:
   - Frontend resends with confirmed_tool_ids + pending_tool_call
   - Backend pre-executes tool, injects result, continues LLM
6. If denied:
   - Backend skips tool, LLM may try alternate approach
```

### Token Tracking

Tokens are accumulated across all iterations within a single request:

```python
total_input_tokens = 0
total_output_tokens = 0

# Each iteration adds to the total
total_input_tokens += response.usage.input_tokens
total_output_tokens += response.usage.output_tokens
```

Max iterations: 15. If reached, all accumulated text is returned.

---

## 10. Database Persistence

### Tables

**CopilotSession:**
| Column | Type | Description |
|--------|------|-------------|
| id | string | Primary key |
| title | string | Auto-generated from first message |
| userId | string | FK to User |
| organizationId | string | FK to Organization |
| model | string | LLM model used |
| pipelineStackId | string | FK to PipelineStack |
| totalInputTokens | int | Accumulated input tokens |
| totalOutputTokens | int | Accumulated output tokens |
| createdAt | datetime | |
| updatedAt | datetime | |

**CopilotMessage:**
| Column | Type | Description |
|--------|------|-------------|
| id | string | Primary key |
| sessionId | string | FK to CopilotSession |
| role | enum | USER or ASSISTANT |
| content | string | Message text |
| toolCalls | JSON | Array of tool call objects |
| inputTokens | int | Tokens for this message |
| outputTokens | int | Tokens for this message |
| createdAt | datetime | |

### Persistence Points

1. **User message** — saved immediately when received
2. **AI response** — saved on stream completion (accumulated from all events)
3. **Session title** — generated from first message (strips context blocks, code blocks, filler words)
4. **Token counts** — accumulated on session after each interaction

---

## 11. Key Design Decisions

1. **Schema pre-fetch timing**: Happens BEFORE building the system prompt so column info is in the LLM's context. If fetch fails, fallback instructions are injected instead.

2. **Compound schema keys**: `"WAREHOUSE_TYPE:dataset"` format supports multiple warehouses simultaneously. Code iterating the dict must use `_parse_schema_key()` or `table.dataset` for SQL generation, not the raw dict key.

3. **MCP integration**: MCP tools are discovered at runtime and merged with static tools. Prefixed names (`mcp_snowflake__*`) prevent collisions. Airflow uses MCP exclusively (no legacy adapter).

4. **Tool confirmation**: Only applies to tools with `requires_confirmation = True`. The system pauses the stream and waits for user approval before executing.

5. **Anomaly detection mandate**: Hard rule in the prompt forces the LLM to use `run_coverage_monitor` (with Z-score analysis) instead of writing manual anomaly SQL.

6. **Message accumulation**: Text from ALL iterations is collected (not just the final one), ensuring no tool observations or partial responses are lost.

7. **Query validation**: Pre-execution column checking against schema + post-error suggestions for correct names enables self-healing query attempts.

8. **Warehouse inference**: If the `warehouse` parameter isn't specified, the system infers from SQL syntax (backticks → BigQuery, uppercase → Snowflake, etc.) as a fallback.

9. **Pipeline isolation**: All data is scoped per organization and pipeline profile. Schema cache uses `key_prefix + pipelineId`.

10. **Depth matching**: System prompt explicitly tells the LLM to scale investigation depth to question complexity — 1 query for "how many rows?" vs 5-8 queries for "why did this fail?"
