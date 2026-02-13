"""
Co-Pilot LLM Integration

Integrates with Anthropic Claude and OpenAI GPT for AI-powered assistance.
Supports tool calling for executing actions against integrations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
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

logger = logging.getLogger(__name__)


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

1. **NEVER ASK FOR PERMISSION** - Just run queries and give answers. Don't say "Do you want me to run this?" or "Should I execute this?" - JUST DO IT.

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

10. **MANDATORY IMPACT ANALYSIS FOR CHANGES** - Before creating ANY code change, plan, or fix:
   - ✅ Call `get_downstream` on every table/model being modified
   - ✅ Call `get_upstream` to understand data sources
   - ✅ Identify ALL breaking changes (column renames, table moves, schema changes)
   - ✅ Report an Impact Analysis table showing what will break
   - ✅ Include fixes for EVERYTHING that breaks, not just the original request
   - **If you skip impact analysis for a change request, your response is INCOMPLETE and potentially dangerous.**

11. **SYNTHESIZE TOOL RESULTS - NEVER DUMP RAW DATA** - After calling a tool:
   - ✅ Interpret the results and explain what they mean
   - ✅ For action tools (create_change_plan, apply_change_plan): State the outcome clearly ("I've created PR #123 at [URL]")
   - ✅ For query results: Summarize the key findings, don't just show the raw table
   - ❌ NEVER paste raw JSON or tool output without interpretation
   - ❌ NEVER say "Here's what I found:" followed by a raw data dump
   - **If the user asks you to "go ahead" with an action, EXECUTE the action and report the result - don't show previous query results.**

## Impact Analysis Requirements (For PLAN, FIX, CREATE Modes)

When the user asks you to make changes (modify code, change datasets, rename models, etc.), you MUST:

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

## How to Answer Simple Data Questions

1. Look at the schema below to find the right table and columns
2. Write and EXECUTE the query immediately — ONE tool call, not multiple
3. Read the results and give a clear, direct answer
4. Include WHERE the data came from (which table)

## How to Investigate (Debugging, Comparisons, Root Cause Analysis)

When the user asks "why?", "what's wrong?", "compare", "are they the same?", "what happened?", or any question that requires investigation — DO NOT give a shallow answer. Follow this deep-dive workflow:

1. **Gather evidence first**: Run discovery queries to understand the current state. List tables, check row counts, check freshness timestamps, look at recent data.
2. **Check every warehouse**: If multiple warehouses are connected, query ALL of them. Don't stop at one. Compare tables, schemas, row counts, and data across all connected warehouses.
3. **Drill into specifics**: After an overview query, run follow-up queries to drill into anomalies. If counts don't match, check which rows differ. If a table is missing, check if it exists under a different name or schema.
4. **Check metadata**: Query INFORMATION_SCHEMA for table lists, column details, and table creation/modification times when the pre-loaded schema doesn't answer the question.
5. **Read logs**: Use orchestration tools (`get_airflow_task_logs`, `get_airflow_dag_status`) and ingestion tools (`get_fivetran_sync_logs`, `get_airbyte_sync_history`) to read actual failure logs.
6. **Chain queries**: Use the results of one query to inform the next. If you find a suspicious table, query its contents. If you find a failed job, get its logs.
7. **Synthesize findings**: After gathering all evidence, provide a comprehensive answer with: what happened, why it happened, the root cause, and what to do about it.

**EFFICIENCY IS KEY: Combine multiple questions into single queries using UNION ALL, multiple aggregations, or JOINs. Aim for 1-3 well-designed queries max. The schema is pre-loaded below — use it to write precise queries without exploration.**

"""
        # Add mode-specific prompt section
        if context.mode_config and context.mode != "ask":
            prompt += f"\n{context.mode_config.system_prompt_section}\n"

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
  - `run_coverage_monitor`: Execute a freshness/volume/schema_change/anomaly monitor against the warehouse. **Use this instead of manual diagnostic SQL** — it has built-in thresholds, Z-score anomaly detection, and time-series analysis.
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
5. **Tool not connected / adapter error**: If a tool returns "not connected" or "not implemented", use `search_knowledge_base` to find expert guidance on the topic. Do NOT tell the user about "technical limitations" — instead provide helpful advice from the knowledge base.
6. **Authentication / 401 errors from Airflow or other tools**: This is a CONFIGURATION issue you can help debug. Do NOT give up or ask the user to run CLI commands. Instead:
   a. Use `search_knowledge_base` with "airflow api auth" to find the fix
   b. Use `list_github_repos` → `get_github_tree` → `get_github_file` to inspect the user's infrastructure config files (docker-compose.yml, airflow.cfg, .env, etc.)
   c. Look for missing auth configuration (e.g. `AIRFLOW__API__AUTH_BACKENDS` for Airflow 2.x)
   d. Tell the user exactly what to change in their config, with the specific file path and setting
7. **Lineage "not found" errors**: When `get_airflow_dag_lineage`, `get_upstream`, `get_downstream`, or `get_asset_orchestration_context` say a node is not found, DO NOT give up. Instead:
   a. Use `search_lineage` with wildcards (e.g., `*dag_name*`, `*table_name*`) to find what nodes actually exist
   b. Use `get_lineage_stats` to check if any lineage was extracted at all
   c. Try the node's full FQN instead of just its name (check the lineage catalog in the prompt for FQNs)
   d. For Airflow DAGs: also use `get_dag_run_history` and Airflow API tools to get info from Airflow directly — don't assume lineage is the only path to understanding the pipeline
   e. For tables: use `get_asset_orchestration_context` with the full table FQN to find the producing DAG
   f. Cross-reference: if you can see the DAG runs but not the lineage, tell the user lineage extraction may need to be re-run, and use the tools you DO have to answer their question
Do NOT give up after one failed query - fix the issue and retry.

## Response Format

- **Data answers**: "**[Direct answer with numbers]** (from `dataset.table`)"
- **Lineage answers**: List the nodes with their types and relationships clearly.
- **Status answers**: State the current status, last run time, and any issues.
- **Debugging answers**: Identify the root cause and suggest the fix.
- **Code/config answers**: Provide copy-paste ready code using the user's REAL project names, file paths, dataset names, and current config. Call tools first to get current state.

Keep responses concise. Don't over-explain. Just answer the question.
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
            examples += """### Example 4: Debugging a Pipeline Failure (read logs, check data, find root cause)
User: "Why did my pipeline fail last night?"
This requires a full investigation. DO NOT give a surface-level answer.
Step 1: `get_airflow_dag_status(dag_id="daily_etl")` — find which run failed and when
Step 2: `get_airflow_task_logs(dag_id="daily_etl", task_id="<failing_task>")` — read the actual error message
Step 3: If the error mentions data issues, run SQL queries to investigate (e.g., check for NULLs, duplicates, missing rows)
Step 4: If the error mentions upstream issues, check ingestion status with `get_fivetran_connector_status` or `get_airbyte_connection_status`
Step 5: Synthesize all findings into a root cause analysis.
Response: "**Your daily_etl DAG failed at 2:15 AM on the `load_orders` task.** The error was: `Duplicate key violation on orders.order_id`. Investigation shows 847 duplicate order_ids were inserted by Fivetran sync at 1:30 AM (connector `orders_source` ran twice due to a retry). **Root cause**: Fivetran double-synced, and the load task doesn't handle duplicates. **Fix**: Add a MERGE/upsert strategy to the load task, or deduplicate in staging."

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

        # Error recovery example
        examples += """### Example 6: Recovering From a Query Error
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
                        max_tokens=4096,
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
                                    "content": json.dumps(result.data if result.success else {"error": result.error}),
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
                        api_params["max_completion_tokens"] = 4096
                    else:
                        api_params["max_tokens"] = 4096

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
                                "content": json.dumps(result.data if result.success else {"error": result.error}),
                            })

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
