"""
Co-Pilot LLM Integration

Integrates with Anthropic Claude and OpenAI GPT for AI-powered assistance.
Supports tool calling for executing actions against integrations.
"""

from dataclasses import dataclass, field, asdict
from typing import AsyncGenerator, Dict, List, Optional, Any, Set, Union
from datetime import datetime, date
from enum import Enum
import logging
import json
import os

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from .context_builder import CopilotContext
from .tools import get_tool_registry, ToolResult
from .tool_executor import ToolExecutor
from .artifacts import ToolArtifactResult, WRITE_TOOLS

logger = logging.getLogger(__name__)


def _safe_json_default(obj: Any) -> Any:
    """Fallback serializer for json.dumps — prevents stream crashes."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    if hasattr(obj, '__dict__'):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
    return str(obj)


@dataclass
class Message:
    """A chat message."""
    role: str  # "user", "assistant", "system"
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None


@dataclass
class CopilotResponse:
    """Response from the co-pilot."""
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stop_reason: str = ""


@dataclass
class StreamEvent:
    """A single SSE event from the streaming chat.

    Event types:
        text_delta              — Incremental text from the LLM
        tool_call_start         — LLM wants to call a tool
        tool_call_result        — Tool execution finished
        tool_confirmation_required — Destructive tool needs user approval
        ui_artifact             — Write tool proposing an action (rendered as interactive card)
        iteration_start         — New LLM iteration beginning
        done                    — Stream complete
        error                   — Error occurred
    """
    event_type: str
    data: Dict[str, Any]

    def to_sse(self) -> str:
        """Format as Server-Sent Events wire format."""
        try:
            return f"event: {self.event_type}\ndata: {json.dumps(self.data, default=_safe_json_default)}\n\n"
        except Exception as e:
            # Last resort: send error event instead of crashing the stream
            logger.error(f"SSE serialization error for {self.event_type}: {e}")
            safe_data = {"error": f"Serialization error: {str(e)}", "event_type": self.event_type}
            return f"event: error\ndata: {json.dumps(safe_data)}\n\n"


class CopilotLLM:
    """
    LLM integration for the co-pilot.
    
    Uses Anthropic Claude or OpenAI GPT with tool calling to provide
    intelligent assistance for data pipeline questions.
    """
    
    # Available models by provider
    MODELS = {
        # OpenAI (higher rate limits)
        "gpt-5.2": {"provider": "openai", "model": "gpt-5.2"},
        "gpt-5.2-mini": {"provider": "openai", "model": "gpt-5.2-mini"},
        "o3-mini": {"provider": "openai", "model": "o3-mini"},
        # Anthropic
        "claude-sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
        "claude-opus": {"provider": "anthropic", "model": "claude-opus-4-20250514"},
        "claude-haiku": {"provider": "anthropic", "model": "claude-haiku-4-20250514"},
    }

    DEFAULT_MODEL = "gpt-5.2"  # OpenAI as default for higher rate limits
    
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the LLM.
        
        Args:
            model: Model to use (claude-sonnet, claude-opus, gpt-4o, gpt-4o-mini, etc.)
            api_key: API key (defaults to ANTHROPIC_API_KEY or OPENAI_API_KEY env var)
        """
        self.model_name = model
        model_config = self.MODELS.get(model, self.MODELS[self.DEFAULT_MODEL])
        self.provider = model_config["provider"]
        self.model = model_config["model"]
        
        self.anthropic_client = None
        self.openai_client = None
        
        if self.provider == "anthropic":
            if ANTHROPIC_AVAILABLE:
                self.anthropic_client = anthropic.Anthropic(
                    api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
                    max_retries=3,
                )
            else:
                logger.warning("Anthropic SDK not available")
        elif self.provider == "openai":
            if OPENAI_AVAILABLE:
                self.openai_client = openai.OpenAI(
                    api_key=api_key or os.environ.get("OPENAI_API_KEY"),
                    max_retries=3,
                )
            else:
                logger.warning("OpenAI SDK not available")
    
    def build_system_prompt(self, context: CopilotContext) -> str:
        """
        Build the system prompt with context about the user's stack.

        The prompt only includes information about what the user
        has actually connected. Syntax guidance is warehouse-specific.
        """
        prompt = """You are an expert data pipeline assistant for Pallisade, a data reliability platform.

## CRITICAL RULES - FOLLOW THESE EXACTLY

1. **EXECUTE READ QUERIES IMMEDIATELY** - For read-only operations (query_warehouse, get_upstream, get_dbt_model, etc.), just run them and give answers. Don't say "Do you want me to run this?" - JUST DO IT. Note: Some tools that modify external systems (like apply_change_plan) will automatically pause for user confirmation. You don't need to ask for permission yourself — the system handles it.

2. **ALWAYS RUN THE QUERY** - When you know what query to run, execute it immediately using `query_warehouse`. Don't show the SQL and ask if they want you to run it.

3. **GIVE DIRECT ANSWERS** - After running a query, state the answer clearly:
   - GOOD: "The most sold product is StockCode 85123A with 97,894 units sold (from test.transactions)"
   - BAD: "Here's the query you could run..." or "Do you want me to execute this?"

4. **USE THE SCHEMA PROVIDED** - The exact column names for all tables are listed below. Use ONLY these column names - never guess or assume column names.

5. **NEVER HALLUCINATE COLUMNS** - If you're unsure whether a column exists, check the schema section. If it's not listed, do NOT use it.

6. **DO NOT QUERY INFORMATION_SCHEMA** - When the "Database Schema" section below lists tables and columns, that IS your schema. Go straight to writing your data query. Do NOT waste a tool call querying INFORMATION_SCHEMA.

7. **MATCH DEPTH TO QUESTION COMPLEXITY**:
   - **Simple data questions** ("how many orders?", "top product?"): ONE tool call with `query_warehouse`, return the answer.
   - **Investigation / debugging / comparison questions** ("why did this fail?", "are tables the same?", "what's wrong with my data?"): Use AS MANY tool calls as needed. Run multiple queries, check metadata, compare across warehouses, drill into anomalies. Do NOT stop at a surface-level answer.

8. **USE REAL NAMES, NEVER PLACEHOLDERS** - You have the user's actual integration config, project names, dataset names, model names, and lineage below. ALWAYS use their real names in your answers. NEVER use placeholders like `your_project`, `<project_name>`, `your_dataset`, etc. If the user's BigQuery project is `acme-484520`, write `acme-484520`. If their dbt project is `jaffle_shop`, write `jaffle_shop`. If you need a name you don't have, call the appropriate tool to get it first.

9. **ANSWERS MUST BE PIPELINE-SPECIFIC** - When giving code suggestions, config changes, or architecture advice, base it on the user's ACTUAL connected integrations and current configuration. Call `get_dbt_model` or other tools to get the real state before suggesting changes. Your answer should be copy-paste ready with the user's real project names, file paths, table names, and schema names — not generic examples.

10. **IMPACT ANALYSIS FOR DATA PIPELINE CHANGES** - Before creating changes to SQL models, dbt models, DAGs, orchestration configs, or schema definitions:
   - ✅ Call `get_downstream` on every table/model being modified
   - ✅ Call `get_upstream` to understand data sources
   - ✅ Identify ALL breaking changes (column renames, table moves, schema changes)
   - ✅ Report an Impact Analysis table showing what will break
   - ✅ Include fixes for EVERYTHING that breaks, not just the original request
   - **Skip impact analysis for documentation files (.md, .txt, .gitignore, README), config-only changes, and non-pipeline code.**

11. **SYNTHESIZE TOOL RESULTS - NEVER DUMP RAW DATA** - After calling a tool:
   - ✅ Interpret the results and explain what they mean
   - ✅ For action tools (create_change_plan, apply_change_plan): State the outcome clearly ("I've created PR #123 at [URL]")
   - ✅ For query results: Summarize the key findings, don't just show the raw table
   - ❌ NEVER paste raw JSON or tool output without interpretation
   - ❌ NEVER say "Here's what I found:" followed by a raw data dump
   - ❌ NEVER output the full file content in the chat when you are also creating a change plan — the plan already contains the patches. Instead, briefly describe what the plan does and let the ChangePlanCard UI show the details.
   - **If the user asks you to "go ahead" with an action, EXECUTE the action and report the result - don't show previous query results.**

## Impact Analysis Requirements (For PLAN, FIX, CREATE Modes)

When the user asks you to make changes to **data pipeline objects** (SQL models, dbt models, DAGs, orchestration configs, warehouse tables, schema definitions), you MUST:

1. **Check Lineage First** - Run `get_downstream` on all objects being changed
2. **Report Breaking Changes** - Include an Impact Analysis section:

   ### Impact Analysis
   **Downstream Dependencies:**
   | Object | Type | Will Break? | Required Fix |
   |--------|------|-------------|--------------|
   | model_x | dbt | YES | Update ref() |
   | dashboard | Looker | YES | Update source |

   **Breaking Changes:** X items need attention

3. **Include All Fixes** - Your implementation must address ALL breaking changes, not just the original request

**Exception:** Skip impact analysis entirely when creating documentation files (.md, .txt, README), config-only files (.gitignore, requirements.txt), or other non-pipeline artifacts. These have no downstream data dependencies.

## How to Answer Simple Data Questions

1. Look at the schema below to find the right table and columns
2. Write and EXECUTE the query immediately — ONE tool call, not multiple
3. Read the results and give a clear, direct answer
4. Include WHERE the data came from (which table)

## How to Investigate (Debugging, Comparisons, Root Cause Analysis)

When the user asks "why?", "what's wrong?", "compare", "are they the same?", "what happened?", or any question that requires investigation — DO NOT give a shallow answer. Follow this deep-dive workflow:

1. **Gather evidence first**: Run discovery queries to understand the current state. List tables, check row counts, check freshness timestamps, look at recent data.
2. **Use coverage monitors for anomaly detection**: When investigating anomalies, outliers, or unexpected data patterns, use `run_coverage_monitor` with `monitor_type: "anomaly"` instead of writing manual statistical SQL. The monitor has built-in Z-score analysis, lookback windows, and seasonality support.
3. **Check every warehouse**: If multiple warehouses are connected, query ALL of them. Don't stop at one. Compare tables, schemas, row counts, and data across all connected warehouses.
4. **For pipeline failures**: Get the actual error message first (task logs, job history, sync logs). Classify the failure layer: Connection/Auth vs SQL Compilation vs Runtime/Data vs Orchestration. If the error contains SQL or a warehouse error code, it is NOT Connection/Auth. If BigQuery is involved, query `INFORMATION_SCHEMA.JOBS_BY_PROJECT` via `query_warehouse` for the server-side error.
5. **Drill into specifics**: After an overview query, run follow-up queries to drill into anomalies. If counts don't match, check which rows differ. If a table is missing, check if it exists under a different name or schema.
6. **Check metadata**: Query INFORMATION_SCHEMA for table lists, column details, and table creation/modification times when the pre-loaded schema doesn't answer the question.
7. **Read logs**: Use orchestration tools (`get_dag_run_history` for run/task status, Airflow MCP tools like `mcp_airflow__get_task_logs` for full logs) and ingestion tools (`get_fivetran_sync_logs`, `get_airbyte_sync_history`) to read actual failure logs.
8. **Verify schema compatibility**: Before proposing any fix that moves data between tables, compare column names AND data types between source and target. Type mismatches (STRING vs INT64, TIMESTAMP vs DATE) cause runtime failures. Use the pre-loaded schema or query INFORMATION_SCHEMA.COLUMNS.
9. **Verify downstream impact**: After finding the root cause, check freshness and quality of downstream tables using `run_coverage_monitor(monitor_type="freshness")` and `get_downstream`.
10. **Chain queries**: Use the results of one query to inform the next. If you find a suspicious table, query its contents. If you find a failed job, get its logs.
11. **Synthesize findings**: After gathering all evidence, provide a comprehensive answer with: what happened, why it happened, the root cause, and what to do about it.

**EFFICIENCY IS KEY: Combine multiple questions into single queries using UNION ALL, multiple aggregations, or JOINs. Aim for 1-3 well-designed queries max. The schema is pre-loaded below — use it to write precise queries without exploration.**

"""
        # Add mode-specific prompt section
        if context.mode_config and context.mode != "ask":
            prompt += f"\n{context.mode_config.system_prompt_section}\n"

        # Inject Answer Contract based on intent classification
        if context.intent_result:
            try:
                from .response_builder import build_answer_contract
                contract = build_answer_contract(context.intent_result)
                prompt += f"\n{contract}\n"
            except Exception:
                pass  # Answer contract is optional, don't fail if unavailable

        # Inject tool-calling policy based on intent
        if context.intent_result:
            policy = self._build_tool_policy(context.intent_result)
            if policy:
                prompt += f"\n{policy}\n"

        # Inject write action policy (always present — write tools are always available)
        prompt += """
## Write Actions

You can create and modify resources in Pallisade. Write actions emit interactive
cards that the user reviews before execution.

RULES:
- ALWAYS gather information first (read-only tools) before proposing write actions
- For a SINGLE write action: emit the artifact directly by calling the write tool
- For MULTIPLE write actions (2+): call each write tool separately — each will emit
  its own artifact card for user review
- NEVER assume user confirmation. Wait for explicit __action:confirm before proceeding.
- When you receive __action:confirm, acknowledge the creation and summarize what was done.
- If a user cancels (__action:cancel), acknowledge gracefully and ask what they'd like instead.
- After completing all actions, summarize what was done and ask if anything else is needed.

AVAILABLE WRITE TOOLS:
- create_watch: Create a watch (monitor group) with bundled monitors and schedule
- run_watch: Run all monitors in an existing watch immediately (no confirmation needed)
"""

        # Inject preferred tools for the active mode so the LLM knows
        # which tools to reach for first in this context
        if context.mode_config and context.mode_config.preferred_tools:
            tools_list = ", ".join(
                f"`{t}`" for t in context.mode_config.preferred_tools
            )
            prompt += (
                f"\n**Preferred tools for this mode**: {tools_list}. "
                "Use these tools first when they match the user's question.\n"
            )

        # Add warehouse-specific SQL syntax guidance
        prompt += self._build_warehouse_syntax_section(context)

        prompt += """
## Tool Selection Guide (Be Efficient!)

- **Simple data questions** ("how many orders?", "top customers"): ONE `query_warehouse` call. Schema is below — go straight to the query.
- **Multi-table questions**: Combine into ONE query using UNION ALL or subqueries. Example: To check null counts across 4 tables, use UNION ALL to get all results in one call.
- **Investigation / debugging**: Start with ONE comprehensive diagnostic query that checks multiple things (row counts, null counts, recent timestamps) together. Only make follow-up queries if the first reveals something that needs deeper investigation.
- **Cross-warehouse comparison**: If comparing two warehouses, that's 2 queries max (one per warehouse). Combine all checks for each warehouse into a single query.
- **Lineage questions** ("what feeds into X?", "what depends on Y?"): Use `get_upstream` or `get_downstream`. If the node isn't found, use `search_lineage` with wildcards to find the correct ID first.
- **Airflow DAG lineage** ("what tables does my DAG produce?", "show the data flow"): Use `get_airflow_dag_lineage` for the DAG→task→table subgraph. If it returns "not found", use `search_lineage` with `*airflow*` or `*dag*` to find what Airflow nodes exist, then check `get_lineage_stats` for coverage info.
- **Orchestration context** ("what produces this table?", "why is it stale?"): Use `get_asset_orchestration_context` with the table FQN. This finds the DAG/task that produces a table via cross-plane edges.
- **Finding tables** ("do I have a users table?"): Check the schema section below first. Only use `search_lineage` or INFORMATION_SCHEMA if the table isn't listed.
- **Table health** ("is my data fresh?", "how big is X?"): Use `get_table_stats`.
- **Impact analysis** ("what breaks if I change X?"): Use `get_downstream` to find all dependents.
- **Lineage coverage / completeness** ("is my lineage complete?"): Use `get_lineage_stats` to see node/edge counts, coverage percentages, and confidence distribution.
- **Data health / anomalies / freshness / monitoring** ("is my data healthy?", "any anomalies?", "check freshness", "how's my coverage?", "what needs monitoring?"): **ALWAYS use coverage tools instead of writing raw SQL.** These tools run purpose-built monitors with statistical analysis:
  - `get_coverage_report`: Overall health score across 7 dimensions (freshness, volume, schema, quality, lineage, ownership, documentation). Start here for any health/monitoring question.
  - `get_coverage_gaps`: Prioritized gaps sorted by severity — use for "what's missing?" or "where should I add monitoring?"
  - `get_node_coverage`: Per-asset breakdown — use for "how well covered is orders?"
  - `get_monitor_recommendations`: Actionable monitor configs with SQL templates — use for "what monitors should I add?"
  - `run_coverage_monitor`: Execute a freshness/volume/schema_change/anomaly monitor against the warehouse. **Use this instead of manual diagnostic SQL** — it has built-in thresholds, Z-score anomaly detection, and time-series analysis. For **anomaly** monitors you MUST pass `config` with at least `column` and `metric` (e.g. `{"column": "revenue", "metric": "null_rate", "timestamp_column": "created_at"}`). Available metrics: null_rate, distinct_count, distinct_rate, min, max, avg, sum, stddev, zero_rate.

### ⚠️ MANDATORY: Anomaly Detection via Coverage Monitor

When the user asks about **anomalies, outliers, unusual patterns, spikes, drops, deviations, or unexpected values** in their data, you **MUST** use `run_coverage_monitor` with `monitor_type: "anomaly"` instead of writing your own SQL. This is a hard rule — not a suggestion.

**Why:** `run_coverage_monitor` uses statistically rigorous Z-score analysis with configurable lookback windows, seasonality support, and proper baseline calculation. Hand-written SQL for anomaly detection is fragile, misses edge cases, and duplicates logic that already exists.

**How to handle anomaly questions:**
1. **Identify the table and column(s)** the user is asking about from the schema or their question.
2. **Pick the right metric** for each column: `null_rate` (null spikes), `avg`/`sum`/`min`/`max` (value anomalies), `distinct_count`/`distinct_rate` (cardinality shifts), `zero_rate` (zero influx), `stddev` (volatility changes).
3. **Call `run_coverage_monitor`** with `monitor_type: "anomaly"`, the table FQN, and `config: {"column": "<col>", "metric": "<metric>", "timestamp_column": "<ts_col>"}`. If the user mentions seasonality (e.g., weekday patterns), add `"seasonality": "day_of_week"`.
4. **Run multiple monitors** if the user asks about general anomalies — check the most important columns (e.g., primary metrics, key dimensions) with separate `run_coverage_monitor` calls.
5. **Supplement with `get_coverage_report`** or `get_node_coverage`** for broader context on what monitoring already exists.

**WRONG approach (DO NOT DO THIS):**
```sql
-- DO NOT write manual anomaly SQL like this:
SELECT date, revenue,
  AVG(revenue) OVER (ORDER BY date ROWS 30 PRECEDING) as avg_30d,
  STDDEV(revenue) OVER (ORDER BY date ROWS 30 PRECEDING) as std_30d
FROM my_table
WHERE revenue > avg_30d + 3 * std_30d
```
This duplicates what `run_coverage_monitor(monitor_type="anomaly")` already does with better statistics. **Use the tool.**

**RIGHT approach:**
```
run_coverage_monitor(monitor_type="anomaly", table_fqn="project.dataset.my_table", config={"column": "revenue", "metric": "avg", "timestamp_column": "date", "lookback_days": 30})
```
- **Verifying lineage edges** ("why does X connect to Y?"): Use `explain_edge` with the edge ID from upstream/downstream results.
- **dbt questions** ("show me the model SQL", "did my run pass?"): Use `get_dbt_model`, `get_dbt_run_history`, or `get_dbt_test_results`.
- **Pipeline failures** ("why did my DAG fail?", "what happened last night?"): Use orchestration tools to get the DAG status, then get task logs for the failing task. Read the actual error message. If it's a data issue, run follow-up SQL queries to investigate. If you encounter errors accessing Airflow, use GitHub tools to inspect the infrastructure config.
- **Ingestion status** ("is Fivetran syncing?", "last sync time?"): Use `get_fivetran_connector_status` or `get_airbyte_connection_status`. For failures, also get sync logs.
- **Code/config suggestions**: FIRST call `get_dbt_model` for relevant models to get their current SQL, schema, database, path, and dependencies. Then give copy-paste ready code using REAL names.
- **Knowledge/advice questions** ("how does Snowflake differ from BigQuery?", "Kafka best practices"): Use `search_knowledge_base` for curated expert guidance.

## Error Recovery

If a query fails:
1. **Wrong column name**: Re-read the schema section below. Use ONLY the exact column names listed. Re-run with corrected columns.
2. **Wrong table name**: Check the schema section for the correct fully qualified table name. Re-run with the corrected name.
3. **Syntax error**: Check the SQL syntax reminders for this warehouse type. Fix and re-run.
4. **No results**: Try broadening the query (remove filters, check for NULL values).
5. **Tool results are ground truth**: When a tool executes and returns `"success": true`, that tool IS connected and working — NEVER claim otherwise. If data comes back from a tool, the adapter IS connected. Only report "not connected" if the tool result explicitly contains `"success": false` with a connection error message.
6. **Tool not connected / adapter error**: If a tool returns `"success": false` with "not connected" or "not implemented", use `search_knowledge_base` to find expert guidance on the topic. Do NOT tell the user about "technical limitations" — instead provide helpful advice from the knowledge base.
7. **Authentication / 401 errors from Airflow or other tools**: This is a CONFIGURATION issue you can help debug. Do NOT give up or ask the user to run CLI commands. Instead:
   a. Use `search_knowledge_base` with "airflow api auth" to find the fix
   b. Use `list_github_repos` → `get_github_tree` → `get_github_file` to inspect the user's infrastructure config files (docker-compose.yml, airflow.cfg, .env, etc.)
   c. Look for missing auth configuration (e.g. `AIRFLOW__API__AUTH_BACKENDS` for Airflow 2.x)
   d. Tell the user exactly what to change in their config, with the specific file path and setting
8. **Lineage "not found" errors**: When `get_airflow_dag_lineage`, `get_upstream`, `get_downstream`, or `get_asset_orchestration_context` say a node is not found, DO NOT give up. Instead:
   a. Use `search_lineage` with wildcards (e.g., `*dag_name*`, `*table_name*`) to find what nodes actually exist
   b. Use `get_lineage_stats` to check if any lineage was extracted at all
   c. Try the node's full FQN instead of just its name (check the lineage catalog in the prompt for FQNs)
   d. For Airflow DAGs: also use `get_dag_run_history` and Airflow API tools to get info from Airflow directly — don't assume lineage is the only path to understanding the pipeline
   e. For tables: use `get_asset_orchestration_context` with the full table FQN to find the producing DAG
   f. Cross-reference: if you can see the DAG runs but not the lineage, tell the user lineage extraction may need to be re-run, and use the tools you DO have to answer their question
Do NOT give up after one failed query - fix the issue and retry.

## Response Format

Keep responses SHORT and SCANNABLE. The user should get the answer in the first sentence.

- **Data answers**: Lead with the number and source — e.g. "42,581 rows (from `raw.orders`)"
- **Lineage answers**: List nodes with types, no extra prose
- **Debugging answers**: State the problem, cause, and fix. No preamble, no "let me investigate"
- **Code/config answers**: Copy-paste ready code with REAL names. Call tools first to get current state

Formatting rules:
- Use plain text. Minimal bold — only for the key answer or section label
- No walls of text. Prefer 3-5 short bullet points over paragraphs
- No nested bullets, no italic emphasis blocks, no confidence labels
- Don't repeat information the user already provided back to them
- Don't dump raw JSON or tool output — synthesize into a human sentence
NEVER use placeholders like `your_project`, `<your_dataset>`, `your_table`. Use the actual names from the user's integrations and tool results.

"""
        # Add few-shot examples
        prompt += self._build_few_shot_examples(context)

        # Add context about user's stack
        prompt += context.to_system_prompt_context(query=context.query)

        # Add learned context from onboarding (if available)
        prompt += self._build_onboarded_context(context)

        # If warehouse is connected but schema is empty, add discovery instructions
        if context.has_warehouse() and not context.warehouse_schema:
            prompt += self._build_schema_discovery_fallback(context)

        # Add knowledge base hints if query matches known topics
        try:
            from .knowledge import get_knowledge_base
            kb = get_knowledge_base()
            kb_hint = kb.get_context_hints(context.query, context.integration_types)
            if kb_hint:
                prompt += kb_hint
        except Exception:
            pass  # Knowledge base is optional, don't fail if unavailable

        # Add complementary integration hints
        prompt += self._build_complementary_integration_hints(context)

        # Add available tools info
        available_tools = context.available_tools
        if available_tools:
            prompt += "\n## Available Tools\n\n"
            prompt += f"You have access to these tools based on the user's connected integrations: {', '.join(available_tools)}\n"
        else:
            prompt += "\n## Note\n\nNo integrations are currently connected. Guide the user to connect their data tools first.\n"

        return prompt

    def _build_warehouse_syntax_section(self, context: CopilotContext) -> str:
        """Build warehouse-specific SQL syntax guidance for ALL connected warehouses."""
        sections = []

        if context.has_integration("BIGQUERY"):
            sections.append("""## SQL Syntax (BigQuery)
- Use backticks for table names: `project.dataset.table`
- Use fully qualified names: `project.dataset.table`
- String comparisons are case-sensitive by default
- Use FORMAT_TIMESTAMP for date formatting
- Use SAFE_DIVIDE to avoid division by zero
- LIMIT goes at the end of the query
- When using query_warehouse, pass `warehouse: "bigquery"`
""")

        if context.has_integration("SNOWFLAKE"):
            sections.append("""## SQL Syntax (Snowflake)
- Use double quotes for case-sensitive identifiers: "database"."schema"."table"
- Or use unquoted uppercase: DATABASE.SCHEMA.TABLE
- String comparisons are case-insensitive by default
- Use TO_CHAR / TO_TIMESTAMP for date formatting
- Use TRY_TO_NUMBER, TRY_TO_DATE for safe casts
- LIMIT goes at the end of the query
- When using query_warehouse, pass `warehouse: "snowflake"`
""")

        if context.has_integration("POSTGRES") or context.has_integration("REDSHIFT"):
            wh_name = "Redshift" if context.has_integration("REDSHIFT") else "PostgreSQL"
            wh_param = "redshift" if context.has_integration("REDSHIFT") else "postgres"
            sections.append(f"""## SQL Syntax ({wh_name})
- Use double quotes for case-sensitive identifiers: "schema"."table"
- Or use unquoted lowercase: schema.table
- String comparisons are case-sensitive by default
- Use TO_CHAR for date formatting
- Use COALESCE for null handling
- LIMIT goes at the end of the query
- When using query_warehouse, pass `warehouse: "{wh_param}"`
""")

        if context.has_integration("SQLSERVER") or context.has_integration("AZURE_SQL"):
            sections.append("""## SQL Syntax (SQL Server)
- Use square brackets for identifiers: [schema].[table]
- Or use unquoted names: schema.table
- Use TOP N instead of LIMIT (e.g., SELECT TOP 10 ...)
- Use CONVERT or FORMAT for date formatting
- Use ISNULL for null handling
""")

        if len(sections) > 1:
            # Multiple warehouses: add a note about targeting
            header = """## IMPORTANT: Multiple Warehouses Connected
You have multiple data warehouses connected. When calling `query_warehouse`, you MUST specify the `warehouse` parameter to target the correct one. Use the correct SQL syntax for each warehouse.

"""
            return header + "\n".join(sections)
        elif sections:
            return sections[0] + "\n"

        return ""

    def _build_tool_policy(self, intent_result) -> str:
        """Build intent-specific tool-calling policy for injection into the system prompt."""
        from .intent import Intent

        primary = intent_result.primary.intent

        if primary == Intent.INFO:
            return """## Tool-Calling Policy (INFO)
- Minimum: 1 tool call (query_warehouse, search_lineage, or get_table_stats).
- Maximum: 3 tool calls unless the question is genuinely complex.
- After getting the answer, STOP. Do not run follow-up queries unless asked.
"""
        elif primary == Intent.DEBUG:
            return """## Tool-Calling Policy (DEBUG)
- Minimum: 3 tool calls. Follow this sequence:
  1. **Identify failure**: `get_dag_run_history` or `get_dbt_run_history` to find what failed
  2. **Get error details**: MCP Airflow task logs, or `query_warehouse` against `INFORMATION_SCHEMA.JOBS_BY_PROJECT` for BigQuery errors
  3. **Verify impact**: `get_downstream` + `run_coverage_monitor(monitor_type="freshness")` on affected tables
- If the error is unclear after step 2, escalate: check additional systems (ingestion logs, warehouse metadata, lineage).
- Before generating any fix code: compare column names AND data types between source and target tables using the schema provided or INFORMATION_SCHEMA.COLUMNS.
- Aim for 3-5 tool calls total. Go to 8+ only for genuinely complex cross-system issues.
- Do NOT stop after getting the error message. Always verify downstream impact before responding.
"""
        elif primary in (Intent.FIX, Intent.PR):
            has_debug = (
                intent_result.secondary
                and intent_result.secondary.intent == Intent.DEBUG
            )
            extra = ""
            if has_debug:
                extra = "- BEFORE proposing a fix: run diagnostic tools first (you are also debugging).\n"
            return f"""## Tool-Calling Policy (FIX/PR)
{extra}- CRITICAL SEQUENCE — you MUST follow this exact order WITHOUT stopping between steps:
  1. Gather evidence (1-2 diagnostic tool calls)
  2. Call create_change_plan to build the plan
  3. Call validate_change_plan on the plan_id returned by step 2
  4. Call apply_change_plan with that same plan_id — this pauses for user confirmation
- DO NOT stop after create_change_plan or validate_change_plan to ask the user what to do next. Proceed through ALL 4 steps automatically. The user wants the PR, not a conversation about the plan.
- NEVER call apply_change_plan without calling create_change_plan first. apply_change_plan looks up the plan by ID — if you skip create_change_plan, the plan won't exist and it will fail.
- NEVER invent or guess a plan_id. Only use the plan_id returned by create_change_plan.
"""
        elif primary == Intent.PLAN:
            return """## Tool-Calling Policy (PLAN)
- MANDATORY: Call get_downstream and get_upstream on all objects being changed.
- Include impact analysis before proposing any steps.
- Use 3-6 tool calls to understand the current state before planning.
"""
        return ""

    def _build_onboarded_context(self, context: CopilotContext) -> str:
        """
        Inject learned context from onboarding into system prompt.

        This includes information the user provided during onboarding about:
        - How they run dbt (dbt Cloud, GitHub Actions, etc.)
        - Where credentials are stored (profiles.yml, env vars)
        - Team workflows, naming conventions, etc.
        """
        # Check if context has pipeline_context attribute with onboarding data
        pipeline_context = getattr(context, 'pipeline_context', None)
        if not pipeline_context:
            return ""

        # Extract context fields (assuming dict format from API)
        environment_ctx = pipeline_context.get('environmentContext') if isinstance(pipeline_context, dict) else getattr(pipeline_context, 'environment_context', None)
        integration_ctx = pipeline_context.get('integrationContexts') if isinstance(pipeline_context, dict) else getattr(pipeline_context, 'integration_contexts', None)
        conventions_ctx = pipeline_context.get('conventionsContext') if isinstance(pipeline_context, dict) else getattr(pipeline_context, 'conventions_context', None)

        if not any([environment_ctx, integration_ctx, conventions_ctx]):
            return ""

        lines = ["\n## Your Environment (from Onboarding)\n"]
        lines.append("I already know the following about your setup:\n")

        # Add environment context
        if environment_ctx and isinstance(environment_ctx, dict):
            for key, value in environment_ctx.items():
                # Convert snake_case keys to readable format
                readable_key = key.replace('_', ' ').title()
                lines.append(f"- **{readable_key}:** {value}")

        # Add integration-specific context
        if integration_ctx and isinstance(integration_ctx, dict):
            for int_id, int_ctx in integration_ctx.items():
                lines.append(f"\n**{int_id}:**")
                if isinstance(int_ctx, dict):
                    for key, value in int_ctx.items():
                        readable_key = key.replace('_', ' ').title()
                        lines.append(f"- {readable_key}: {value}")

        # Add conventions context
        if conventions_ctx and isinstance(conventions_ctx, dict):
            lines.append("\n**Conventions:**")
            for key, value in conventions_ctx.items():
                readable_key = key.replace('_', ' ').title()
                lines.append(f"- {readable_key}: {value}")

        lines.append("\n**Use this context - do NOT ask clarifying questions about topics covered above.**\n")

        return "\n".join(lines)

    def _build_complementary_integration_hints(self, context: CopilotContext) -> str:
        """Add hints when complementary integrations are both connected."""
        hints = ""
        orchestration_types = {"AIRFLOW", "DAGSTER", "PREFECT", "N8N"}
        transformation_types = {"DBT_CLOUD", "DBT_CORE"}
        has_orchestration = bool(context.integration_types & orchestration_types)
        has_transformation = bool(context.integration_types & transformation_types)
        has_github = "GITHUB" in context.integration_types

        if (has_orchestration or has_transformation) and has_github:
            hints += """
## PR Creation Available

You have both pipeline tools AND GitHub connected. When fixing pipeline issues:
1. Diagnose with orchestration/transformation tools (DAG status, task logs, dbt run history)
2. Create a fix with `create_change_plan`
3. Push directly via `apply_change_plan` — this creates a GitHub PR
Don't just describe fixes — create the change plan and offer to push it.
"""
        return hints

    def _build_few_shot_examples(self, context: CopilotContext) -> str:
        """Build few-shot examples relevant to the user's connected integrations."""
        examples = "## Examples of Good Interactions\n\n"

        # Extract real names from integrations for examples
        bq_project = ""
        bq_dataset = ""
        sf_db = ""
        sf_schema = ""
        for integration in context.integrations:
            cfg = integration.config
            if integration.type.upper() == "BIGQUERY":
                bq_project = cfg.get('project_id') or cfg.get('project', '')
                ds = cfg.get('datasets', cfg.get('dataset', ''))
                bq_dataset = ds[0] if isinstance(ds, list) and ds else (ds if isinstance(ds, str) else '')
            elif integration.type.upper() == "SNOWFLAKE":
                sf_db = cfg.get('database', '')
                sf_schema = cfg.get('schema', '') or 'PUBLIC'

        has_bq = context.has_integration("BIGQUERY")
        has_sf = context.has_integration("SNOWFLAKE")
        multi_warehouse = has_bq and has_sf

        # Always include a data query example if warehouse is connected
        if context.has_warehouse():
            if multi_warehouse:
                bq_p = bq_project or "my-project"
                bq_d = bq_dataset or "analytics"
                sf_d = sf_db or "MY_DB"
                sf_s = sf_schema or "PUBLIC"
                examples += f"""### Example 1: Data Question with Multiple Warehouses
User: "Are the same tables in my Snowflake and BigQuery?"
Assistant thinking: I have schemas for both warehouses listed below. I should query BOTH to compare tables.
Action 1: Call `query_warehouse` with `warehouse: "bigquery"` and BigQuery SQL using backticks like `{bq_p}.{bq_d}.<table>`
Action 2: Call `query_warehouse` with `warehouse: "snowflake"` and Snowflake SQL like {sf_d}.{sf_s}.<TABLE>
CRITICAL: Always specify the `warehouse` parameter when multiple warehouses are connected.

"""
            elif has_bq:
                bq_p = bq_project or "my-project"
                bq_d = bq_dataset or "analytics"
                examples += f"""### Example 1: Data Question (ONE tool call only)
User: "What are my top 5 customers by revenue?"
Assistant thinking: Schema section below shows the tables and columns in `{bq_d}`. I already have the schema — go straight to query using the EXACT column names listed.
Action: Call `query_warehouse` with a query using fully qualified names like `{bq_p}.{bq_d}.<table>` and ONLY columns from the schema section.
WRONG approach: Calling search_lineage or querying INFORMATION_SCHEMA first — that wastes tool calls when schema is already provided.
Response: Use the REAL table and column names from the schema, never placeholders.

"""
            elif has_sf:
                sf_d = sf_db or "MY_DB"
                sf_s = sf_schema or "PUBLIC"
                examples += f"""### Example 1: Data Question (ONE tool call only)
User: "What are my top 5 customers by revenue?"
Assistant thinking: Schema section below shows tables in {sf_d}.{sf_s}. I already have the schema — go straight to query using EXACT column names.
Action: Call `query_warehouse` using fully qualified names like {sf_d}.{sf_s}.<TABLE> and ONLY columns from the schema section.
WRONG approach: Calling search_lineage or querying INFORMATION_SCHEMA first.

"""
            else:
                examples += """### Example 1: Data Question (ONE tool call only)
User: "What are my top 5 customers by revenue?"
Assistant thinking: Schema section below shows the available tables and columns. Go straight to query.
Action: Call `query_warehouse` with the appropriate SQL using ONLY exact column names from the schema section.
WRONG approach: Calling search_lineage or querying INFORMATION_SCHEMA first.

"""

        # Lineage example
        examples += """### Example 2: Lineage Question
User: "What tables feed into my fct_orders model?"
Action: Call `get_upstream` with node_id for fct_orders.
Response: "**fct_orders has 3 upstream dependencies:**
- `raw.orders` (source table) - the raw order events
- `raw.customers` (source table) - customer dimension data
- `stg_orders` (dbt model) - staging transformation"

"""

        # Investigation / deep-dive example
        examples += """### Example 3: Investigation / Deep-Dive (MULTIPLE tool calls expected)
User: "Are my Snowflake tables the same as my BigQuery tables?"
This requires a thorough investigation. DO NOT just list schema names. Drill into the actual tables.
Step 1: Query BigQuery for table list — `query_warehouse(sql="SELECT table_name FROM ...", warehouse="bigquery")`
Step 2: Query Snowflake for table list — `query_warehouse(sql="SELECT TABLE_NAME FROM ...", warehouse="snowflake")`
Step 3: Compare the results. For each matching table, check row counts in BOTH warehouses.
Step 4: If counts differ, sample rows to identify the difference.
Response: "**Yes, both warehouses have the same 8 tables**: customers, orders, transactions, ... BigQuery `raw` has 15,432 rows in `transactions`, Snowflake `PUBLIC` has 15,432 rows — they match exactly."
WRONG approach: Only querying one warehouse, or only listing schema names like "INFORMATION_SCHEMA and PUBLIC" without looking inside them.

"""

        # Debugging example if orchestrator is connected
        if context.has_orchestrator():
            examples += """### Example 4: Debugging a Pipeline Failure (structured investigation)
User: "Why did my pipeline fail last night?"
This requires a structured investigation. DO NOT guess the failure type — investigate first.
Step 1: `get_dag_run_history(dag_id="daily_etl")` — find the failed run, identify the failing task and timestamp.
Step 2: Use MCP Airflow tools if available (`mcp_airflow__get_task_logs`) to get the full error. If MCP unavailable, proceed with what `get_dag_run_history` returned.
Step 3: Classify the failure. Example: error says "Column order_date not found in table raw.orders" → this is **SQL Compilation**, NOT Connection/Auth (the task reached the warehouse).
Step 4: If BigQuery is involved, run `query_warehouse(sql="SELECT job_id, error_result, query FROM \\`region-us.INFORMATION_SCHEMA.JOBS_BY_PROJECT\\` WHERE state = 'DONE' AND error_result IS NOT NULL AND creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) ORDER BY creation_time DESC LIMIT 5", warehouse="bigquery")` — get server-side error details.
Step 5: Before proposing a fix, compare source and target schemas: check the pre-loaded schema for column names AND data types. If source has `order_date (DATE)` but target expects `order_date (TIMESTAMP)`, the fix must include a CAST.
Step 6: `get_downstream(node_id="raw.orders")` + `run_coverage_monitor(monitor_type="freshness", table_fqn="project.dataset.fct_orders")` — check downstream impact.
Response: "**Problem:** The `load_orders` task in `daily_etl` failed at 2:15 AM — SQL Compilation error. **Cause:** Column `order_date` was renamed to `ordered_at` in the upstream Fivetran sync (schema change at 1:30 AM). The MERGE references the old name. **Fix:** Update the MERGE to use `ordered_at`. Also CAST to TIMESTAMP since source is DATE but target is TIMESTAMP. Enumerate all columns explicitly — do not use SELECT *. **Impact:** `fct_orders` and 3 downstream dashboards are stale (last refresh: 12h ago)."

"""

        # dbt config suggestion example
        if context.has_integration("DBT_CLOUD") or context.has_integration("DBT_CORE"):
            examples += """### Example 5: dbt Code/Config Suggestion (ALWAYS use real names)
User: "How do I change my staging models to write to the analytics dataset instead of dbt_dev_staging?"
Step 1: Call `get_dbt_model` for a staging model (e.g., `stg_orders`) to get its ACTUAL current config.
Step 2: Use the REAL values from the tool result — real project name, real schema, real file path, real SQL.
WRONG: "In your `dbt_project.yml`, under `your_project`..." — NEVER use `your_project` as a placeholder.
RIGHT: "In your `dbt_project.yml`, under `jaffle_shop`..." — use the ACTUAL project name from the model data.
The response must include copy-paste ready code with the user's real project name, real paths, and real current SQL.

"""

        # Anomaly detection example (always include — coverage tools are always available)
        examples += """### Example 6: Anomaly Detection (USE COVERAGE MONITOR, NOT RAW SQL)
User: "Are there any anomalies in my orders table?" / "Has anything unusual happened with revenue?"
MANDATORY: Use `run_coverage_monitor` with `monitor_type: "anomaly"`. Do NOT write manual Z-score SQL.
Step 1: `run_coverage_monitor(monitor_type="anomaly", table_fqn="<real_table_fqn>", config={"column": "revenue", "metric": "avg", "timestamp_column": "created_at"})` — check the key metric column
Step 2: `run_coverage_monitor(monitor_type="anomaly", table_fqn="<real_table_fqn>", config={"column": "order_id", "metric": "distinct_count", "timestamp_column": "created_at"})` — check volume/cardinality
Step 3: Optionally call `get_node_coverage` for broader health context on the asset.
Step 4: Synthesize findings: "**Revenue anomaly detected on Jan 15**: average daily revenue dropped to $12,340 (Z-score: -3.2, baseline: $45,600 ± $8,200). Order volume was normal, suggesting a pricing or discount issue rather than traffic drop."
WRONG: Writing `SELECT date, AVG(revenue) OVER(...), STDDEV(revenue) OVER(...)` — the monitor already does this with better statistics.

"""

        # Error recovery example
        examples += """### Example 7: Recovering From a Query Error
User: "How many active users do I have?"
First attempt: query_warehouse with SELECT COUNT(*) FROM users WHERE status = 'active'
Error: "Column 'status' not found"
Recovery: Re-check schema - the column is actually called `is_active` (BOOLEAN). Re-run: SELECT COUNT(*) FROM users WHERE is_active = true
Response: "**You have 12,847 active users** (from `analytics.users`)"

"""
        return examples

    def _build_schema_discovery_fallback(self, context: CopilotContext) -> str:
        """
        When schema pre-fetch fails, instruct the LLM to discover
        tables and columns via INFORMATION_SCHEMA before querying data.
        """
        fallback = """
## IMPORTANT: Schema Not Pre-loaded

The database schema could not be pre-loaded. You MUST discover table and column names before writing queries.

**Before answering ANY data question, ALWAYS do these two steps first:**

"""
        if context.has_integration("BIGQUERY"):
            # Find project from integrations
            project = ""
            dataset_hint = ""
            for integration in context.integrations:
                if integration.type.upper() == "BIGQUERY":
                    project = integration.config.get('project') or integration.config.get('project_id', '')
                    ds = integration.config.get('datasets', [])
                    if ds:
                        dataset_hint = ds[0] if isinstance(ds, list) else ds
                    elif integration.config.get('dataset'):
                        dataset_hint = integration.config['dataset']
                    break

            if dataset_hint:
                fallback += f"""1. **Discover tables**: `SELECT table_name, table_type FROM \\`{project}.{dataset_hint}.INFORMATION_SCHEMA.TABLES\\` WHERE table_type IN ('BASE TABLE', 'VIEW')`
2. **Discover columns for the relevant table**: `SELECT column_name, data_type FROM \\`{project}.{dataset_hint}.INFORMATION_SCHEMA.COLUMNS\\` WHERE table_name = '<table_name>' ORDER BY ordinal_position`
"""
            else:
                fallback += f"""1. **Discover datasets**: `SELECT schema_name FROM \\`{project}.INFORMATION_SCHEMA.SCHEMATA\\` WHERE schema_name NOT LIKE '%INFORMATION_SCHEMA%'`
2. **Then discover tables**: `SELECT table_name FROM \\`{project}.<dataset>.INFORMATION_SCHEMA.TABLES\\``
3. **Then discover columns**: `SELECT column_name, data_type FROM \\`{project}.<dataset>.INFORMATION_SCHEMA.COLUMNS\\` WHERE table_name = '<table>'`
"""
        elif context.has_integration("SNOWFLAKE"):
            fallback += """1. **Discover tables**: `SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA NOT IN ('INFORMATION_SCHEMA') LIMIT 50`
2. **Discover columns for the relevant table**: `SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '<TABLE_NAME>' ORDER BY ORDINAL_POSITION`
"""
        else:
            fallback += """1. **Discover tables**: `SELECT table_name, table_type FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema') LIMIT 50`
2. **Discover columns for the relevant table**: `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '<table_name>' ORDER BY ordinal_position`
"""

        fallback += """
**NEVER guess table or column names.** Always run the discovery queries first, read the results, then write your actual data query using only the exact names returned.

"""
        return fallback

    async def chat(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int = 15,
    ) -> CopilotResponse:
        """
        Send a message and get a response.
        
        Handles tool calling automatically, executing tools
        and continuing the conversation until the AI is done.
        
        Args:
            messages: Conversation history
            context: User's co-pilot context
            max_tool_iterations: Maximum tool call iterations to prevent infinite loops
            
        Returns:
            CopilotResponse with the final answer
        """
        if self.provider == "anthropic":
            return await self._chat_anthropic(messages, context, max_tool_iterations)
        elif self.provider == "openai":
            return await self._chat_openai(messages, context, max_tool_iterations)
        else:
            return CopilotResponse(
                content=f"Unknown provider: {self.provider}",
                model=self.model,
            )

    async def chat_stream(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int = 15,
        confirmed_tool_ids: Optional[Set[str]] = None,
        pending_tool_call: Optional[Dict[str, Any]] = None,
        system_prompt_override: Optional[str] = None,
        confirmed_artifacts: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Stream a chat response as SSE events.

        Yields StreamEvent objects as the LLM generates text and executes tools.
        Tools marked with requires_confirmation=True will pause the stream
        and yield a tool_confirmation_required event.

        Args:
            messages: Conversation history
            context: User's co-pilot context
            max_tool_iterations: Maximum tool call iterations
            confirmed_tool_ids: Tool use IDs or names the user has already approved
            pending_tool_call: Tool call to execute directly (from confirmation flow)
            system_prompt_override: If provided, use this instead of build_system_prompt()
            confirmed_artifacts: Artifacts the user has confirmed for execution
        """
        if self.provider == "anthropic":
            async for event in self._chat_anthropic_stream(
                messages, context, max_tool_iterations, confirmed_tool_ids,
                pending_tool_call=pending_tool_call,
                system_prompt_override=system_prompt_override,
                confirmed_artifacts=confirmed_artifacts,
            ):
                yield event
        elif self.provider == "openai":
            async for event in self._chat_openai_stream(
                messages, context, max_tool_iterations, confirmed_tool_ids,
                pending_tool_call=pending_tool_call,
                system_prompt_override=system_prompt_override,
                confirmed_artifacts=confirmed_artifacts,
            ):
                yield event
        else:
            yield StreamEvent("error", {"message": f"Unknown provider: {self.provider}"})

    async def _chat_anthropic_stream(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int,
        confirmed_tool_ids: Optional[Set[str]] = None,
        pending_tool_call: Optional[Dict[str, Any]] = None,
        system_prompt_override: Optional[str] = None,
        confirmed_artifacts: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream chat with Anthropic Claude via SSE events."""
        if not self.anthropic_client:
            yield StreamEvent("error", {"message": "Anthropic not available. Configure ANTHROPIC_API_KEY."})
            return

        confirmed_tool_ids = confirmed_tool_ids or set()

        # Create tool executor (same setup as _chat_anthropic)
        executor = ToolExecutor(context)

        # Pre-fetch warehouse schema
        if not context.warehouse_schema and context.has_warehouse():
            try:
                logger.info("[Stream/Anthropic] Pre-fetching warehouse schema...")
                context.warehouse_schema = await executor.fetch_warehouse_schema()
                if context.warehouse_schema:
                    total_tables = sum(len(t) for t in context.warehouse_schema.values())
                    logger.info(f"[Stream/Anthropic] Schema loaded: {len(context.warehouse_schema)} datasets, {total_tables} tables")
            except Exception as e:
                logger.error(f"[Stream/Anthropic] Schema pre-fetch failed: {e}", exc_info=True)

        system = system_prompt_override if system_prompt_override else self.build_system_prompt(context)
        registry = get_tool_registry()
        tools = registry.to_anthropic_tools(context.integration_types)

        # Start MCP servers
        mcp_manager = None
        try:
            from scanner.mcp_bridge.client import MCPClientManager
            mcp_manager = MCPClientManager(
                integrations=context.integrations,
                engine_store=getattr(context, "engine_store", None),
                lineage_graph=getattr(context, "graph", None),
            )
            await mcp_manager.start_servers()
            if mcp_manager.has_servers:
                mcp_tools = await mcp_manager.discover_tools(format="anthropic")
                tools = tools + mcp_tools
                logger.info(f"[Stream/Anthropic] MCP: {len(mcp_tools)} tools from {mcp_manager.active_servers}")
                context.mcp_enabled = True
        except Exception as e:
            logger.warning(f"[Stream/Anthropic] MCP init failed: {e}")
            mcp_manager = None

        try:
            anthropic_messages = self._convert_messages(messages)
            total_input_tokens = 0
            total_output_tokens = 0
            all_tool_calls: List[Dict[str, Any]] = []

            # If we have a pending tool call from confirmation flow,
            # execute it directly and inject result into messages
            if pending_tool_call:
                ptc_name = pending_tool_call["tool_name"]
                ptc_args = pending_tool_call.get("arguments", {})
                ptc_id = pending_tool_call.get("tool_use_id", f"toolu_confirmed_{ptc_name}")

                logger.info(f"[Stream/Anthropic] Pre-executing confirmed tool: {ptc_name}")
                yield StreamEvent("tool_call_start", {
                    "tool_use_id": ptc_id,
                    "tool_name": ptc_name,
                    "arguments": ptc_args,
                })

                try:
                    if ptc_name.startswith("mcp_") and mcp_manager:
                        mcp_result = await mcp_manager.call_tool(ptc_name, ptc_args)
                        result = ToolResult(
                            success=mcp_result.get("success", False),
                            data=mcp_result.get("data"),
                            error=mcp_result.get("error"),
                        )
                    else:
                        result = await executor.execute(ptc_name, ptc_args)
                except Exception as e:
                    result = ToolResult(success=False, error=str(e))

                yield StreamEvent("tool_call_result", {
                    "tool_use_id": ptc_id,
                    "tool_name": ptc_name,
                    "result": result.to_dict(),
                })

                all_tool_calls.append({
                    "tool": ptc_name,
                    "input": ptc_args,
                    "result": result.to_dict(),
                })

                # Inject tool call + result into Anthropic messages
                anthropic_messages.append({
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": ptc_id,
                        "name": ptc_name,
                        "input": ptc_args,
                    }],
                })
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": ptc_id,
                        "content": json.dumps(result.to_dict(), default=_safe_json_default),
                    }],
                })

            for iteration in range(max_tool_iterations):
                yield StreamEvent("iteration_start", {
                    "iteration": iteration + 1,
                    "reason": "tool_use" if iteration > 0 else ("confirmed_tool" if pending_tool_call else "initial"),
                })

                try:
                    # Use the streaming API
                    with self.anthropic_client.messages.stream(
                        model=self.model,
                        system=system,
                        messages=anthropic_messages,
                        tools=tools if tools else anthropic.NOT_GIVEN,
                        max_tokens=16384,
                    ) as stream:
                        for event in stream:
                            if event.type == "content_block_delta":
                                if hasattr(event.delta, "text"):
                                    yield StreamEvent("text_delta", {"content": event.delta.text})

                        # Get final message after stream completes
                        final_message = stream.get_final_message()

                    total_input_tokens += final_message.usage.input_tokens
                    total_output_tokens += final_message.usage.output_tokens

                except Exception as e:
                    logger.exception("[Stream/Anthropic] Error in streaming call")
                    yield StreamEvent("error", {"message": f"Error communicating with AI: {str(e)}"})
                    return

                # Check stop reason
                if final_message.stop_reason == "end_turn":
                    yield StreamEvent("done", {
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "model": self.model,
                        "stop_reason": "end_turn",
                        "tool_calls": all_tool_calls,
                    })
                    return

                if final_message.stop_reason == "tool_use":
                    tool_results = []

                    for block in final_message.content:
                        if block.type != "tool_use":
                            continue

                        tool_name = block.name
                        tool_input = block.input
                        tool_use_id = block.id

                        yield StreamEvent("tool_call_start", {
                            "tool_use_id": tool_use_id,
                            "tool_name": tool_name,
                            "arguments": tool_input,
                        })

                        # Check if this tool needs user confirmation
                        # confirmed_tool_ids may contain tool use IDs or tool names
                        tool_def = registry.get_tool(tool_name)
                        needs_confirmation = (
                            tool_def
                            and tool_def.requires_confirmation
                            and tool_use_id not in confirmed_tool_ids
                            and tool_name not in confirmed_tool_ids
                        )

                        # For apply_change_plan: verify the plan exists before pausing for confirmation.
                        # If the LLM hallucinated a plan_id (skipped create_change_plan), execute normally
                        # so the error propagates back and the LLM can self-correct.
                        if needs_confirmation and tool_name == "apply_change_plan":
                            plan_id = tool_input.get("plan_id")
                            if plan_id:
                                try:
                                    from .change_plan import get_change_plan_store
                                    if not get_change_plan_store().get(plan_id):
                                        logger.warning(f"[Stream/Anthropic] apply_change_plan: plan '{plan_id}' not found, skipping confirmation")
                                        needs_confirmation = False
                                except Exception:
                                    pass

                        if needs_confirmation:
                            logger.info(f"[Stream/Anthropic] Tool '{tool_name}' requires confirmation")
                            yield StreamEvent("tool_confirmation_required", {
                                "tool_use_id": tool_use_id,
                                "tool_name": tool_name,
                                "arguments": tool_input,
                                "description": f"The AI wants to execute '{tool_name}' which may modify external systems.",
                            })
                            yield StreamEvent("done", {
                                "input_tokens": total_input_tokens,
                                "output_tokens": total_output_tokens,
                                "model": self.model,
                                "stop_reason": "confirmation_required",
                                "tool_calls": all_tool_calls,
                            })
                            return

                        # Check if this is a confirmed artifact being executed
                        if tool_name in WRITE_TOOLS and confirmed_artifacts:
                            matched_art = False
                            for art_id, art_data in list(confirmed_artifacts.items()):
                                if art_data.get("tool_name") == tool_name:
                                    logger.info(f"[Stream/Anthropic] Executing confirmed artifact '{art_id}' for tool '{tool_name}'")
                                    result = await executor.execute_confirmed(tool_name, art_data)
                                    yield StreamEvent("tool_call_result", {
                                        "tool_use_id": tool_use_id,
                                        "tool_name": tool_name,
                                        "result": result.to_dict(),
                                    })
                                    all_tool_calls.append({
                                        "tool": tool_name,
                                        "input": tool_input,
                                        "result": result.to_dict(),
                                    })
                                    tool_results.append({
                                        "type": "tool_result",
                                        "tool_use_id": tool_use_id,
                                        "content": json.dumps(result.to_dict(), default=_safe_json_default),
                                    })
                                    confirmed_artifacts.pop(art_id, None)
                                    matched_art = True
                                    break
                            if matched_art:
                                continue

                        # Auto-execute safe tool
                        logger.info(f"[Stream/Anthropic] Executing tool: {tool_name}")
                        try:
                            if tool_name.startswith("mcp_") and mcp_manager:
                                mcp_result = await mcp_manager.call_tool(tool_name, tool_input)
                                from scanner.copilot.tools import ToolResult
                                result = ToolResult(
                                    success=mcp_result.get("success", False),
                                    data=mcp_result.get("data"),
                                    error=mcp_result.get("error"),
                                )
                            else:
                                result = await executor.execute(tool_name, tool_input)
                        except Exception as tool_err:
                            logger.exception(f"[Stream/Anthropic] Unhandled error executing tool '{tool_name}'")
                            from scanner.copilot.tools import ToolResult
                            result = ToolResult(success=False, error=f"Tool execution failed: {tool_err}")

                        # Check if the result is an artifact proposal (write tool returning ToolArtifactResult)
                        if isinstance(result, ToolArtifactResult):
                            artifact_data = result.to_dict()
                            yield StreamEvent("ui_artifact", artifact_data)

                            synthetic_text = result.to_synthetic_tool_result()
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": synthetic_text,
                            })
                            all_tool_calls.append({
                                "tool_use_id": tool_use_id,
                                "tool_name": tool_name,
                                "arguments": tool_input,
                                "result": {"artifact": artifact_data},
                            })
                        else:
                            all_tool_calls.append({
                                "tool": tool_name,
                                "input": tool_input,
                                "result": result.to_dict(),
                            })

                            yield StreamEvent("tool_call_result", {
                                "tool_use_id": tool_use_id,
                                "tool_name": tool_name,
                                "result": result.to_dict(),
                            })

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps(result.to_dict(), default=_safe_json_default),
                            })

                    # Append to conversation and continue loop
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": final_message.content,
                    })
                    anthropic_messages.append({
                        "role": "user",
                        "content": tool_results,
                    })

                    # --- Root cause injection (once, after first evidence round) ---
                    if (
                        context.intent_result
                        and iteration >= 1
                        and not getattr(context, '_root_cause_resolved', False)
                    ):
                        try:
                            from .intent import Intent
                            from .root_cause import resolve_fix_owner, format_owner_hint

                            primary_intent = context.intent_result.primary.intent
                            if primary_intent in (Intent.DEBUG, Intent.FIX, Intent.PR):
                                owner_decision = resolve_fix_owner(
                                    all_tool_calls, context.intent_result
                                )
                                context._root_cause_resolved = True
                                hint = format_owner_hint(
                                    owner_decision,
                                    target_hint=context.intent_result.target_hint,
                                )
                                logger.info(
                                    f"[Stream/Anthropic] Root cause: {owner_decision.owner_system.value} "
                                    f"(confidence={owner_decision.confidence:.0%})"
                                )
                                # Inject as a user message with system context
                                anthropic_messages.append({
                                    "role": "user",
                                    "content": f"[System context — root cause analysis]: {hint}",
                                })
                        except Exception as e:
                            logger.debug(f"[Stream/Anthropic] Root cause injection skipped: {e}")

                    continue

                # Unexpected stop reason
                logger.warning(f"[Stream/Anthropic] Unexpected stop reason: {final_message.stop_reason}")
                yield StreamEvent("done", {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "model": self.model,
                    "stop_reason": final_message.stop_reason or "unknown",
                    "tool_calls": all_tool_calls,
                })
                return

            # Max iterations reached
            yield StreamEvent("done", {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "model": self.model,
                "stop_reason": "max_iterations",
                "tool_calls": all_tool_calls,
            })
        finally:
            if mcp_manager:
                try:
                    await mcp_manager.shutdown()
                except Exception as e:
                    logger.warning(f"[Stream/Anthropic] MCP shutdown error (ignored): {e}")

    async def _chat_openai_stream(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int,
        confirmed_tool_ids: Optional[Set[str]] = None,
        pending_tool_call: Optional[Dict[str, Any]] = None,
        system_prompt_override: Optional[str] = None,
        confirmed_artifacts: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream chat with OpenAI GPT via SSE events."""
        if not self.openai_client:
            yield StreamEvent("error", {"message": "OpenAI not available. Configure OPENAI_API_KEY."})
            return

        confirmed_tool_ids = confirmed_tool_ids or set()

        # Create tool executor (same setup as _chat_openai)
        executor = ToolExecutor(context)

        # Pre-fetch warehouse schema
        if not context.warehouse_schema and context.has_warehouse():
            try:
                logger.info("[Stream/OpenAI] Pre-fetching warehouse schema...")
                context.warehouse_schema = await executor.fetch_warehouse_schema()
                if context.warehouse_schema:
                    total_tables = sum(len(t) for t in context.warehouse_schema.values())
                    logger.info(f"[Stream/OpenAI] Schema loaded: {len(context.warehouse_schema)} datasets, {total_tables} tables")
            except Exception as e:
                logger.error(f"[Stream/OpenAI] Schema pre-fetch failed: {e}", exc_info=True)

        system = system_prompt_override if system_prompt_override else self.build_system_prompt(context)
        registry = get_tool_registry()
        tools = registry.to_openai_tools(context.integration_types)

        # Start MCP servers
        mcp_manager = None
        try:
            from scanner.mcp_bridge.client import MCPClientManager
            mcp_manager = MCPClientManager(
                integrations=context.integrations,
                engine_store=getattr(context, "engine_store", None),
                lineage_graph=getattr(context, "graph", None),
            )
            await mcp_manager.start_servers()
            if mcp_manager.has_servers:
                mcp_tools = await mcp_manager.discover_tools(format="openai")
                tools = tools + mcp_tools
                logger.info(f"[Stream/OpenAI] MCP: {len(mcp_tools)} tools from {mcp_manager.active_servers}")
                context.mcp_enabled = True
        except Exception as e:
            logger.warning(f"[Stream/OpenAI] MCP init failed: {e}")
            mcp_manager = None

        try:
            openai_messages = self._convert_messages_openai(messages, system)
            total_input_tokens = 0
            total_output_tokens = 0
            all_tool_calls: List[Dict[str, Any]] = []
            is_reasoning_model = self.model.startswith('o1') or self.model.startswith('o3')

            # If we have a pending tool call from confirmation flow,
            # execute it directly and inject result into messages
            if pending_tool_call:
                ptc_name = pending_tool_call["tool_name"]
                ptc_args = pending_tool_call.get("arguments", {})
                ptc_id = pending_tool_call.get("tool_use_id", f"call_confirmed_{ptc_name}")

                logger.info(f"[Stream/OpenAI] Pre-executing confirmed tool: {ptc_name}")
                yield StreamEvent("tool_call_start", {
                    "tool_use_id": ptc_id,
                    "tool_name": ptc_name,
                    "arguments": ptc_args,
                })

                try:
                    if ptc_name.startswith("mcp_") and mcp_manager:
                        mcp_result = await mcp_manager.call_tool(ptc_name, ptc_args)
                        result = ToolResult(
                            success=mcp_result.get("success", False),
                            data=mcp_result.get("data"),
                            error=mcp_result.get("error"),
                        )
                    else:
                        result = await executor.execute(ptc_name, ptc_args)
                except Exception as e:
                    result = ToolResult(success=False, error=str(e))

                yield StreamEvent("tool_call_result", {
                    "tool_use_id": ptc_id,
                    "tool_name": ptc_name,
                    "result": result.to_dict(),
                })

                all_tool_calls.append({
                    "tool": ptc_name,
                    "input": ptc_args,
                    "result": result.to_dict(),
                })

                # Inject the tool call + result into OpenAI messages
                # so the LLM sees it was already executed
                openai_messages.append({
                    "role": "assistant",
                    "tool_calls": [{
                        "id": ptc_id,
                        "type": "function",
                        "function": {
                            "name": ptc_name,
                            "arguments": json.dumps(ptc_args, default=_safe_json_default),
                        },
                    }],
                })
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": ptc_id,
                    "content": json.dumps(result.to_dict(), default=_safe_json_default),
                })

            for iteration in range(max_tool_iterations):
                yield StreamEvent("iteration_start", {
                    "iteration": iteration + 1,
                    "reason": "tool_use" if iteration > 0 else "initial",
                })

                try:
                    api_params: Dict[str, Any] = {
                        "model": self.model,
                        "messages": openai_messages,
                        "stream": True,
                    }

                    is_new_model = self.model.startswith('gpt-5') or is_reasoning_model
                    if is_new_model:
                        api_params["max_completion_tokens"] = 16384
                    else:
                        api_params["max_tokens"] = 16384

                    if tools and not is_reasoning_model:
                        api_params["tools"] = tools

                    response_stream = self.openai_client.chat.completions.create(**api_params)

                    # Accumulate chunks
                    accumulated_text = ""
                    tool_calls_acc: Dict[int, Dict[str, Any]] = {}
                    finish_reason = None

                    for chunk in response_stream:
                        choice = chunk.choices[0] if chunk.choices else None
                        if not choice:
                            continue

                        delta = choice.delta
                        finish_reason = choice.finish_reason or finish_reason

                        # Stream text deltas
                        if delta and delta.content:
                            accumulated_text += delta.content
                            yield StreamEvent("text_delta", {"content": delta.content})

                        # Accumulate tool call deltas
                        if delta and delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {
                                        "id": tc_delta.id or "",
                                        "name": (tc_delta.function.name if tc_delta.function else "") or "",
                                        "arguments": "",
                                    }
                                else:
                                    if tc_delta.id:
                                        tool_calls_acc[idx]["id"] = tc_delta.id
                                    if tc_delta.function and tc_delta.function.name:
                                        tool_calls_acc[idx]["name"] = tc_delta.function.name
                                if tc_delta.function and tc_delta.function.arguments:
                                    tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

                        # Track usage from stream
                        if hasattr(chunk, "usage") and chunk.usage:
                            total_input_tokens += chunk.usage.prompt_tokens or 0
                            total_output_tokens += chunk.usage.completion_tokens or 0

                except Exception as e:
                    logger.exception("[Stream/OpenAI] Error in streaming call")
                    yield StreamEvent("error", {"message": f"Error communicating with AI: {str(e)}"})
                    return

                # Process finish reason
                if finish_reason == "stop":
                    yield StreamEvent("done", {
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "model": self.model,
                        "stop_reason": "end_turn",
                        "tool_calls": all_tool_calls,
                    })
                    return

                # Token limit hit — send whatever text was accumulated
                if finish_reason == "length":
                    if not accumulated_text:
                        # LLM spent all tokens on tool calls, never generated text
                        fallback = "\n\n*[Response truncated — the analysis required too many steps. Please ask a follow-up question for the summary.]*"
                        yield StreamEvent("text_delta", {"content": fallback})
                    yield StreamEvent("done", {
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "model": self.model,
                        "stop_reason": "length",
                        "tool_calls": all_tool_calls,
                    })
                    return

                if finish_reason == "tool_calls" and tool_calls_acc:
                    # Build assistant message with tool calls for context
                    assistant_tool_calls = [
                        {
                            "id": tc_data["id"],
                            "type": "function",
                            "function": {
                                "name": tc_data["name"],
                                "arguments": tc_data["arguments"],
                            }
                        }
                        for tc_data in tool_calls_acc.values()
                    ]
                    openai_messages.append({
                        "role": "assistant",
                        "content": accumulated_text or None,
                        "tool_calls": assistant_tool_calls,
                    })

                    # Execute each tool call
                    for tc_data in tool_calls_acc.values():
                        tool_name = tc_data["name"]
                        tool_use_id = tc_data["id"]
                        try:
                            tool_input = json.loads(tc_data["arguments"])
                        except json.JSONDecodeError:
                            tool_input = {}

                        yield StreamEvent("tool_call_start", {
                            "tool_use_id": tool_use_id,
                            "tool_name": tool_name,
                            "arguments": tool_input,
                        })

                        # Check confirmation
                        # confirmed_tool_ids may contain tool use IDs or tool names
                        tool_def = registry.get_tool(tool_name)
                        needs_confirmation = (
                            tool_def
                            and tool_def.requires_confirmation
                            and tool_use_id not in confirmed_tool_ids
                            and tool_name not in confirmed_tool_ids
                        )

                        # For apply_change_plan: verify the plan exists before pausing for confirmation.
                        # If the LLM hallucinated a plan_id (skipped create_change_plan), execute normally
                        # so the error propagates back and the LLM can self-correct.
                        if needs_confirmation and tool_name == "apply_change_plan":
                            plan_id = tool_input.get("plan_id")
                            if plan_id:
                                try:
                                    from .change_plan import get_change_plan_store
                                    if not get_change_plan_store().get(plan_id):
                                        logger.warning(f"[Stream/OpenAI] apply_change_plan: plan '{plan_id}' not found, skipping confirmation")
                                        needs_confirmation = False
                                except Exception:
                                    pass

                        if needs_confirmation:
                            logger.info(f"[Stream/OpenAI] Tool '{tool_name}' requires confirmation")
                            yield StreamEvent("tool_confirmation_required", {
                                "tool_use_id": tool_use_id,
                                "tool_name": tool_name,
                                "arguments": tool_input,
                                "description": f"The AI wants to execute '{tool_name}' which may modify external systems.",
                            })
                            yield StreamEvent("done", {
                                "input_tokens": total_input_tokens,
                                "output_tokens": total_output_tokens,
                                "model": self.model,
                                "stop_reason": "confirmation_required",
                                "tool_calls": all_tool_calls,
                            })
                            return

                        # Check if this is a confirmed artifact being executed
                        if tool_name in WRITE_TOOLS and confirmed_artifacts:
                            matched_art = False
                            for art_id, art_data in list(confirmed_artifacts.items()):
                                if art_data.get("tool_name") == tool_name:
                                    logger.info(f"[Stream/OpenAI] Executing confirmed artifact '{art_id}' for tool '{tool_name}'")
                                    result = await executor.execute_confirmed(tool_name, art_data)
                                    yield StreamEvent("tool_call_result", {
                                        "tool_use_id": tool_use_id,
                                        "tool_name": tool_name,
                                        "result": result.to_dict(),
                                    })
                                    all_tool_calls.append({
                                        "tool": tool_name,
                                        "input": tool_input,
                                        "result": result.to_dict(),
                                    })
                                    openai_messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_use_id,
                                        "content": json.dumps(result.to_dict(), default=_safe_json_default),
                                    })
                                    confirmed_artifacts.pop(art_id, None)
                                    matched_art = True
                                    break
                            if matched_art:
                                continue

                        logger.info(f"[Stream/OpenAI] Executing tool: {tool_name}")
                        try:
                            if tool_name.startswith("mcp_") and mcp_manager:
                                mcp_result = await mcp_manager.call_tool(tool_name, tool_input)
                                from scanner.copilot.tools import ToolResult
                                result = ToolResult(
                                    success=mcp_result.get("success", False),
                                    data=mcp_result.get("data"),
                                    error=mcp_result.get("error"),
                                )
                            else:
                                result = await executor.execute(tool_name, tool_input)
                        except Exception as tool_err:
                            logger.exception(f"[Stream/OpenAI] Unhandled error executing tool '{tool_name}'")
                            from scanner.copilot.tools import ToolResult
                            result = ToolResult(success=False, error=f"Tool execution failed: {tool_err}")

                        # Check if the result is an artifact proposal (write tool returning ToolArtifactResult)
                        if isinstance(result, ToolArtifactResult):
                            artifact_data = result.to_dict()
                            yield StreamEvent("ui_artifact", artifact_data)

                            synthetic_text = result.to_synthetic_tool_result()
                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": tool_use_id,
                                "content": synthetic_text,
                            })
                            all_tool_calls.append({
                                "tool_use_id": tool_use_id,
                                "tool_name": tool_name,
                                "arguments": tool_input,
                                "result": {"artifact": artifact_data},
                            })
                        else:
                            all_tool_calls.append({
                                "tool": tool_name,
                                "input": tool_input,
                                "result": result.to_dict(),
                            })

                            yield StreamEvent("tool_call_result", {
                                "tool_use_id": tool_use_id,
                                "tool_name": tool_name,
                                "result": result.to_dict(),
                            })

                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": tool_use_id,
                                "content": json.dumps(result.data if result.success else {"error": result.error}, default=_safe_json_default),
                            })

                    # --- Root cause injection (once, after first evidence round) ---
                    if (
                        context.intent_result
                        and iteration >= 1
                        and not getattr(context, '_root_cause_resolved', False)
                    ):
                        try:
                            from .intent import Intent
                            from .root_cause import resolve_fix_owner, format_owner_hint

                            primary_intent = context.intent_result.primary.intent
                            if primary_intent in (Intent.DEBUG, Intent.FIX, Intent.PR):
                                owner_decision = resolve_fix_owner(
                                    all_tool_calls, context.intent_result
                                )
                                context._root_cause_resolved = True
                                hint = format_owner_hint(
                                    owner_decision,
                                    target_hint=context.intent_result.target_hint,
                                )
                                logger.info(
                                    f"[Stream/OpenAI] Root cause: {owner_decision.owner_system.value} "
                                    f"(confidence={owner_decision.confidence:.0%})"
                                )
                                openai_messages.append({
                                    "role": "system",
                                    "content": f"[Root cause analysis]: {hint}",
                                })
                        except Exception as e:
                            logger.debug(f"[Stream/OpenAI] Root cause injection skipped: {e}")

                    continue

                # Unexpected finish reason
                logger.warning(f"[Stream/OpenAI] Unexpected finish reason: {finish_reason}")
                yield StreamEvent("done", {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "model": self.model,
                    "stop_reason": finish_reason or "unknown",
                    "tool_calls": all_tool_calls,
                })
                return

            # Max iterations reached
            yield StreamEvent("done", {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "model": self.model,
                "stop_reason": "max_iterations",
                "tool_calls": all_tool_calls,
            })
        finally:
            if mcp_manager:
                try:
                    await mcp_manager.shutdown()
                except Exception as e:
                    logger.warning(f"[Stream/OpenAI] MCP shutdown error (ignored): {e}")

    async def _chat_anthropic(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int,
    ) -> CopilotResponse:
        """Handle chat with Anthropic Claude."""
        if not self.anthropic_client:
            return CopilotResponse(
                content="Anthropic not available. Please configure ANTHROPIC_API_KEY or switch to OpenAI.",
                model=self.model,
            )

        # Create tool executor first (needs adapters for schema fetch)
        executor = ToolExecutor(context)

        # Pre-fetch warehouse schema if not already populated
        if not context.warehouse_schema and context.has_warehouse():
            try:
                logger.info("[Anthropic] Pre-fetching warehouse schema...")
                context.warehouse_schema = await executor.fetch_warehouse_schema()
                if context.warehouse_schema:
                    total_tables = sum(len(t) for t in context.warehouse_schema.values())
                    logger.info(f"[Anthropic] Schema loaded: {len(context.warehouse_schema)} datasets, {total_tables} tables")
                else:
                    logger.warning("[Anthropic] Schema pre-fetch returned empty — LLM will have no column info")
            except Exception as e:
                logger.error(f"[Anthropic] Schema pre-fetch failed: {e}", exc_info=True)

        # Build system prompt (now includes schema info)
        system = self.build_system_prompt(context)

        # Get available tools (legacy)
        registry = get_tool_registry()
        tools = registry.to_anthropic_tools(context.integration_types)

        # Start MCP servers and merge their tools
        mcp_manager = None
        try:
            from scanner.mcp_bridge.client import MCPClientManager
            mcp_manager = MCPClientManager(
                integrations=context.integrations,
                engine_store=getattr(context, "engine_store", None),
                lineage_graph=getattr(context, "graph", None),
            )
            await mcp_manager.start_servers()
            if mcp_manager.has_servers:
                mcp_tools = await mcp_manager.discover_tools(format="anthropic")
                tools = tools + mcp_tools
                logger.info(f"[Anthropic] MCP: {len(mcp_tools)} tools from {mcp_manager.active_servers}")
                context.mcp_enabled = True
        except Exception as e:
            logger.warning(f"[Anthropic] MCP initialization failed (continuing without MCP): {e}")
            mcp_manager = None

        try:
            # Convert messages to Anthropic format
            anthropic_messages = self._convert_messages(messages)

            # Track total tokens
            total_input_tokens = 0
            total_output_tokens = 0
            all_tool_calls = []
            accumulated_text = []  # Accumulate text from ALL iterations, not just final

            # Iterate until we get a final response
            for iteration in range(max_tool_iterations):
                try:
                    # Call Claude
                    response = self.anthropic_client.messages.create(
                        model=self.model,
                        system=system,
                        messages=anthropic_messages,
                        tools=tools if tools else None,
                        max_tokens=16384,
                    )

                    # Track tokens
                    total_input_tokens += response.usage.input_tokens
                    total_output_tokens += response.usage.output_tokens

                    # Extract text from EVERY response (not just end_turn)
                    # This captures intermediate text like "I will create this now"
                    for block in response.content:
                        if hasattr(block, "text") and block.text:
                            accumulated_text.append(block.text)

                    # Check if we're done
                    if response.stop_reason == "end_turn":
                        # Return all accumulated text from all iterations
                        final_content = "\n\n".join(accumulated_text) if accumulated_text else ""

                        return CopilotResponse(
                            content=final_content,
                            tool_calls=all_tool_calls,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            model=self.model,
                            stop_reason=response.stop_reason,
                        )

                    # Handle tool use
                    if response.stop_reason == "tool_use":
                        # Process tool calls
                        tool_results = []

                        for block in response.content:
                            if block.type == "tool_use":
                                tool_name = block.name
                                tool_input = block.input
                                tool_use_id = block.id

                                logger.info(f"Executing tool: {tool_name}")

                                # Route MCP-prefixed tools to MCP, others to legacy executor
                                if tool_name.startswith("mcp_") and mcp_manager:
                                    mcp_result = await mcp_manager.call_tool(tool_name, tool_input)
                                    # Convert MCP result to ToolResult-compatible format
                                    from scanner.copilot.tools import ToolResult
                                    result = ToolResult(
                                        success=mcp_result.get("success", False),
                                        data=mcp_result.get("data"),
                                        error=mcp_result.get("error"),
                                    )
                                else:
                                    result = await executor.execute(tool_name, tool_input)

                                # Handle artifact proposals from write tools
                                if isinstance(result, ToolArtifactResult):
                                    synthetic_text = result.to_synthetic_tool_result()
                                    all_tool_calls.append({
                                        "tool": tool_name,
                                        "input": tool_input,
                                        "result": {"artifact": result.to_dict()},
                                    })
                                    tool_results.append({
                                        "type": "tool_result",
                                        "tool_use_id": tool_use_id,
                                        "content": synthetic_text,
                                    })
                                else:
                                    # Track tool call
                                    all_tool_calls.append({
                                        "tool": tool_name,
                                        "input": tool_input,
                                        "result": result.to_dict(),
                                    })

                                    # Format result for Claude
                                    tool_results.append({
                                        "type": "tool_result",
                                        "tool_use_id": tool_use_id,
                                        "content": json.dumps(result.data if result.success else {"error": result.error}, default=_safe_json_default),
                                    })

                        # Add assistant message with tool use
                        anthropic_messages.append({
                            "role": "assistant",
                            "content": response.content,
                        })

                        # Add tool results
                        anthropic_messages.append({
                            "role": "user",
                            "content": tool_results,
                        })

                        # --- Root cause injection (once, after first evidence round) ---
                        if (
                            context.intent_result
                            and iteration >= 1
                            and not getattr(context, '_root_cause_resolved', False)
                        ):
                            try:
                                from .intent import Intent
                                from .root_cause import resolve_fix_owner, format_owner_hint

                                primary_intent = context.intent_result.primary.intent
                                if primary_intent in (Intent.DEBUG, Intent.FIX, Intent.PR):
                                    owner_decision = resolve_fix_owner(
                                        all_tool_calls, context.intent_result
                                    )
                                    context._root_cause_resolved = True
                                    hint = format_owner_hint(
                                        owner_decision,
                                        target_hint=context.intent_result.target_hint,
                                    )
                                    logger.info(
                                        f"[Anthropic] Root cause: {owner_decision.owner_system.value} "
                                        f"(confidence={owner_decision.confidence:.0%})"
                                    )
                                    anthropic_messages.append({
                                        "role": "user",
                                        "content": f"[System context — root cause analysis]: {hint}",
                                    })
                            except Exception as e:
                                logger.debug(f"[Anthropic] Root cause injection skipped: {e}")

                        # Continue loop
                        continue

                    # Unexpected stop reason
                    logger.warning(f"Unexpected stop reason: {response.stop_reason}")
                    final_content = "\n\n".join(accumulated_text) if accumulated_text else "Unexpected response from AI."
                    return CopilotResponse(
                        content=final_content,
                        model=self.model,
                        stop_reason=response.stop_reason,
                    )

                except Exception as e:
                    logger.exception("Error in Anthropic chat")
                    return CopilotResponse(
                        content=f"Error communicating with AI: {str(e)}",
                        model=self.model,
                    )

            return self._build_max_iterations_response(all_tool_calls, total_input_tokens, total_output_tokens, accumulated_text)
        finally:
            # Always shut down MCP servers
            if mcp_manager:
                await mcp_manager.shutdown()

    async def _chat_openai(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int,
    ) -> CopilotResponse:
        """Handle chat with OpenAI GPT."""
        if not self.openai_client:
            return CopilotResponse(
                content="OpenAI not available. Please configure OPENAI_API_KEY or switch to Anthropic.",
                model=self.model,
            )
        
        # Create tool executor first (needs adapters for schema fetch)
        executor = ToolExecutor(context)

        # Pre-fetch warehouse schema if not already populated
        if not context.warehouse_schema and context.has_warehouse():
            try:
                logger.info("[OpenAI] Pre-fetching warehouse schema...")
                context.warehouse_schema = await executor.fetch_warehouse_schema()
                if context.warehouse_schema:
                    total_tables = sum(len(t) for t in context.warehouse_schema.values())
                    logger.info(f"[OpenAI] Schema loaded: {len(context.warehouse_schema)} datasets, {total_tables} tables")
                else:
                    logger.warning("[OpenAI] Schema pre-fetch returned empty — LLM will have no column info")
            except Exception as e:
                logger.error(f"[OpenAI] Schema pre-fetch failed: {e}", exc_info=True)

        # Build system prompt (now includes schema info)
        system = self.build_system_prompt(context)

        # Get available tools in OpenAI format (legacy)
        registry = get_tool_registry()
        tools = registry.to_openai_tools(context.integration_types)

        # Start MCP servers and merge their tools
        mcp_manager = None
        try:
            from scanner.mcp_bridge.client import MCPClientManager
            mcp_manager = MCPClientManager(
                integrations=context.integrations,
                engine_store=getattr(context, "engine_store", None),
                lineage_graph=getattr(context, "graph", None),
            )
            await mcp_manager.start_servers()
            if mcp_manager.has_servers:
                mcp_tools = await mcp_manager.discover_tools(format="openai")
                tools = tools + mcp_tools
                logger.info(f"[OpenAI] MCP: {len(mcp_tools)} tools from {mcp_manager.active_servers}")
                context.mcp_enabled = True
        except Exception as e:
            logger.warning(f"[OpenAI] MCP initialization failed (continuing without MCP): {e}")
            mcp_manager = None

        try:
            # Convert messages to OpenAI format
            openai_messages = self._convert_messages_openai(messages, system)

            # Track total tokens
            total_input_tokens = 0
            total_output_tokens = 0
            all_tool_calls = []
            accumulated_text = []  # Accumulate text from ALL iterations, not just final

            # Check if this is a reasoning model (o1, o3) that uses different params
            is_reasoning_model = self.model.startswith('o1') or self.model.startswith('o3')

            # Iterate until we get a final response
            for iteration in range(max_tool_iterations):
                try:
                    # Build API call params - reasoning models use max_completion_tokens
                    api_params = {
                        "model": self.model,
                        "messages": openai_messages,
                    }

                    # GPT-5.x and reasoning models use max_completion_tokens
                    is_new_model = self.model.startswith('gpt-5') or is_reasoning_model
                    if is_new_model:
                        api_params["max_completion_tokens"] = 16384
                    else:
                        api_params["max_tokens"] = 16384

                    # Add tools (reasoning models don't support tools yet)
                    if tools and not is_reasoning_model:
                        api_params["tools"] = tools

                    # Call OpenAI
                    response = self.openai_client.chat.completions.create(**api_params)

                    # Track tokens
                    if response.usage:
                        total_input_tokens += response.usage.prompt_tokens
                        total_output_tokens += response.usage.completion_tokens

                    message = response.choices[0].message
                    finish_reason = response.choices[0].finish_reason

                    # Extract text from EVERY response (not just stop)
                    # This captures intermediate text like "I will create this now"
                    if message.content:
                        accumulated_text.append(message.content)

                    # Check if we're done
                    if finish_reason == "stop":
                        # Return all accumulated text from all iterations
                        final_content = "\n\n".join(accumulated_text) if accumulated_text else ""
                        return CopilotResponse(
                            content=final_content,
                            tool_calls=all_tool_calls,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            model=self.model,
                            stop_reason=finish_reason,
                        )

                    # Handle tool calls
                    if finish_reason == "tool_calls" and message.tool_calls:
                        # Add assistant message with tool calls
                        openai_messages.append({
                            "role": "assistant",
                            "content": message.content,
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    }
                                }
                                for tc in message.tool_calls
                            ]
                        })

                        # Execute each tool
                        for tool_call in message.tool_calls:
                            tool_name = tool_call.function.name
                            try:
                                tool_input = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                tool_input = {}

                            logger.info(f"Executing tool: {tool_name}")

                            # Route MCP-prefixed tools to MCP, others to legacy executor
                            if tool_name.startswith("mcp_") and mcp_manager:
                                mcp_result = await mcp_manager.call_tool(tool_name, tool_input)
                                from scanner.copilot.tools import ToolResult
                                result = ToolResult(
                                    success=mcp_result.get("success", False),
                                    data=mcp_result.get("data"),
                                    error=mcp_result.get("error"),
                                )
                            else:
                                result = await executor.execute(tool_name, tool_input)

                            # Handle artifact proposals from write tools
                            if isinstance(result, ToolArtifactResult):
                                synthetic_text = result.to_synthetic_tool_result()
                                all_tool_calls.append({
                                    "tool": tool_name,
                                    "input": tool_input,
                                    "result": {"artifact": result.to_dict()},
                                })
                                openai_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": synthetic_text,
                                })
                            else:
                                # Track tool call
                                all_tool_calls.append({
                                    "tool": tool_name,
                                    "input": tool_input,
                                    "result": result.to_dict(),
                                })

                                # Add tool result
                                openai_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps(result.data if result.success else {"error": result.error}, default=_safe_json_default),
                                })

                        # --- Root cause injection (once, after first evidence round) ---
                        if (
                            context.intent_result
                            and iteration >= 1
                            and not getattr(context, '_root_cause_resolved', False)
                        ):
                            try:
                                from .intent import Intent
                                from .root_cause import resolve_fix_owner, format_owner_hint

                                primary_intent = context.intent_result.primary.intent
                                if primary_intent in (Intent.DEBUG, Intent.FIX, Intent.PR):
                                    owner_decision = resolve_fix_owner(
                                        all_tool_calls, context.intent_result
                                    )
                                    context._root_cause_resolved = True
                                    hint = format_owner_hint(
                                        owner_decision,
                                        target_hint=context.intent_result.target_hint,
                                    )
                                    logger.info(
                                        f"[OpenAI] Root cause: {owner_decision.owner_system.value} "
                                        f"(confidence={owner_decision.confidence:.0%})"
                                    )
                                    openai_messages.append({
                                        "role": "system",
                                        "content": f"[Root cause analysis]: {hint}",
                                    })
                            except Exception as e:
                                logger.debug(f"[OpenAI] Root cause injection skipped: {e}")

                        # Continue loop
                        continue

                    # Unexpected finish reason
                    logger.warning(f"Unexpected finish reason: {finish_reason}")
                    final_content = "\n\n".join(accumulated_text) if accumulated_text else "Unexpected response from AI."
                    return CopilotResponse(
                        content=final_content,
                        model=self.model,
                        stop_reason=finish_reason or "unknown",
                    )

                except Exception as e:
                    logger.exception("Error in OpenAI chat")
                    return CopilotResponse(
                        content=f"Error communicating with AI: {str(e)}",
                        model=self.model,
                    )

            return self._build_max_iterations_response(all_tool_calls, total_input_tokens, total_output_tokens, accumulated_text)
        finally:
            # Always shut down MCP servers
            if mcp_manager:
                await mcp_manager.shutdown()
    
    def _build_max_iterations_response(
        self,
        all_tool_calls: List[Dict],
        total_input_tokens: int,
        total_output_tokens: int,
        accumulated_text: List[str] = None,
    ) -> CopilotResponse:
        """Build response when max iterations reached."""
        logger.warning(f"Max tool iterations reached")

        # If we have accumulated text from the LLM, use that first
        if accumulated_text:
            content = "\n\n".join(accumulated_text)
            if content.strip():
                return CopilotResponse(
                    content=content,
                    tool_calls=all_tool_calls,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    model=self.model,
                    stop_reason="max_iterations",
                )

        # Fall back to summarizing tool results
        summary_parts = ["Here's what I found from the tool calls:\n"]
        for tc in all_tool_calls:
            result = tc.get("result", {})
            if result.get("success") and result.get("data"):
                data = result["data"]
                if tc["tool"] == "query_warehouse" and "rows" in data:
                    row_count = data.get("row_count", len(data.get("rows", [])))
                    sql_preview = data.get('sql', 'SQL')[:80]
                    summary_parts.append(f"\n**Query**: `{sql_preview}...`")
                    summary_parts.append(f"**Results** ({row_count} rows):\n")
                    
                    # Include actual row data (up to 10 rows for readability)
                    rows = data.get("rows", [])
                    if rows:
                        # Format as a readable table or list
                        for i, row in enumerate(rows[:10]):
                            if isinstance(row, dict):
                                row_str = ", ".join(f"{k}: {v}" for k, v in row.items())
                                summary_parts.append(f"  {i+1}. {row_str}")
                            else:
                                summary_parts.append(f"  {i+1}. {row}")
                        if row_count > 10:
                            summary_parts.append(f"  ... and {row_count - 10} more rows")
                    else:
                        summary_parts.append("  (no rows returned)")
                elif tc["tool"] == "get_table_stats" and data:
                    summary_parts.append(f"- Table stats: {data}")
                elif tc["tool"] == "search_lineage" and data:
                    nodes = data.get("nodes", [])
                    summary_parts.append(f"- Found {len(nodes)} matching nodes in lineage")
                    for node in nodes[:5]:
                        summary_parts.append(f"  - {node.get('name', 'Unknown')} ({node.get('type', 'unknown')})")
        
        summary = "\n".join(summary_parts) if len(summary_parts) > 1 else "I gathered some information but ran out of iterations. Please try asking a more specific question."
        
        return CopilotResponse(
            content=summary,
            tool_calls=all_tool_calls,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            model=self.model,
            stop_reason="max_iterations",
        )
    
    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert our Message format to Anthropic format."""
        anthropic_messages = []
        
        for msg in messages:
            if msg.role == "system":
                # System messages are handled separately
                continue
            
            anthropic_msg = {
                "role": msg.role,
                "content": msg.content,
            }
            
            anthropic_messages.append(anthropic_msg)
        
        return anthropic_messages
    
    def _convert_messages_openai(self, messages: List[Message], system: str) -> List[Dict[str, Any]]:
        """Convert our Message format to OpenAI format."""
        openai_messages = [{"role": "system", "content": system}]
        
        for msg in messages:
            if msg.role == "system":
                continue
            
            openai_messages.append({
                "role": msg.role,
                "content": msg.content,
            })
        
        return openai_messages
    
    async def quick_answer(
        self,
        question: str,
        context: CopilotContext,
    ) -> str:
        """
        Get a quick answer to a simple question.
        
        For questions that don't need tool calling.
        """
        messages = [Message(role="user", content=question)]
        response = await self.chat(messages, context, max_tool_iterations=1)
        return response.content


class MockCopilotLLM(CopilotLLM):
    """
    Mock LLM for testing without API calls.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = None  # Disable real client
    
    async def chat(
        self,
        messages: List[Message],
        context: CopilotContext,
        max_tool_iterations: int = 5,
    ) -> CopilotResponse:
        """Return a mock response."""
        last_message = messages[-1].content if messages else ""
        
        # Simple mock responses
        if "upstream" in last_message.lower():
            return CopilotResponse(
                content="Based on your lineage graph, I can see the upstream dependencies. Would you like me to trace them?",
                model="mock",
            )
        elif "downstream" in last_message.lower():
            return CopilotResponse(
                content="I can check the downstream impact for you. Which table or model would you like to analyze?",
                model="mock",
            )
        else:
            return CopilotResponse(
                content=f"I understand you're asking about: {last_message[:100]}... I can help you explore your data pipeline. What would you like to know?",
                model="mock",
            )
