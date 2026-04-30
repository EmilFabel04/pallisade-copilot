"""SQL specialist — generates SQL queries from natural language + schema context."""

from typing import Dict, Iterable, Optional, Type
from pydantic import BaseModel

from .base import BaseSpecialist
from ..schemas import SQLResponse


# Prepended to the system prompt only when the orchestrator is repairing
# a query that already failed at execution. The cue tells the model to
# attach its fix to the specific error rather than regenerate from
# scratch — without this, the second attempt often reproduces the same
# broken SQL because the prompt is identical to the first.
REPAIR_MODE_PREFIX = """REPAIR MODE — you are repairing a SQL query that failed at execution.

The PREVIOUS SQL and the warehouse's exact error are appended to the evidence below. Your job:
1. Identify the root cause from the error message.
2. Make the MINIMAL change that fixes that specific error. Do not rewrite the query structure unless the error proves the structure is wrong.
3. Common failure modes to check first:
   - Column not found → use a column that exists in the schema.
   - Type mismatch → add SAFE_CAST / TRY_CAST per dialect.
   - Function not found → use the dialect-correct equivalent.
   - Wrong warehouse syntax → confirm the `warehouse` field matches the dialect.
4. Your repair must differ from the previous attempt in at least one substantive way. Do not return the same SQL.

"""

# Dialect-specific rules injected into the specialist prompt.
# Only the target warehouse's rules are included — keeps prompt small.
DIALECT_RULES: Dict[str, str] = {
    "bigquery": (
        "- Use backticks for fully qualified names: `project.dataset.table`\n"
        "- Time functions: TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL N DAY)\n"
        "- Safe functions: SAFE_CAST(), SAFE_DIVIDE()\n"
        "- Array handling: UNNEST()\n"
        "- Example: SELECT COUNT(*) FROM `myproject.analytics.events` "
        "WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)"
    ),
    "databricks": (
        "- FQN format: catalog.schema.table (no backticks, use as provided in schema)\n"
        "- Time functions: current_timestamp(), date_sub(current_date(), N)\n"
        "- Safe cast: try_cast() if available, else CAST()\n"
        "- Example: SELECT COUNT(*) FROM catalog.schema.events "
        "WHERE created_at > date_sub(current_date(), 7)"
    ),
    "snowflake": (
        "- Preserve exact FQN from schema (DATABASE.SCHEMA.TABLE)\n"
        "- Time functions: DATEADD('DAY', -N, CURRENT_TIMESTAMP())\n"
        "- Use double quotes for case-sensitive identifiers only when needed\n"
        "- Example: SELECT COUNT(*) FROM DATABASE.SCHEMA.EVENTS "
        "WHERE CREATED_AT > DATEADD('DAY', -7, CURRENT_TIMESTAMP())"
    ),
    "postgres": (
        "- FQN format: schema.table (no catalog prefix)\n"
        "- Time functions: NOW() - INTERVAL 'N days'\n"
        "- Use lowercase identifiers\n"
        "- Example: SELECT COUNT(*) FROM public.events "
        "WHERE created_at > NOW() - INTERVAL '7 days'"
    ),
    "redshift": (
        "- FQN format: schema.table (no catalog prefix)\n"
        "- Time functions: GETDATE() - INTERVAL 'N days'\n"
        "- Use lowercase identifiers\n"
        "- Example: SELECT COUNT(*) FROM public.events "
        "WHERE created_at > GETDATE() - INTERVAL '7 days'"
    ),
}


class SQLSpecialist(BaseSpecialist):

    @property
    def name(self) -> str:
        return "sql"

    @property
    def response_model(self) -> Type[BaseModel]:
        return SQLResponse

    def build_messages(self, evidence: str, query: str, **kwargs) -> list:
        warehouse_type = kwargs.get("warehouse_type", "bigquery")
        schema_json = SQLResponse.model_json_schema()
        dialect_rules = DIALECT_RULES.get(
            warehouse_type, "Use correct syntax for this warehouse."
        )

        # Inject the user's actually-connected warehouses so the specialist
        # doesn't generate SQL for one that isn't available. Mirrors the
        # available_tools pattern in LogsSpecialist.
        available_warehouses: Optional[Iterable[str]] = kwargs.get("available_warehouses")
        if available_warehouses:
            wh_list = sorted({w.lower() for w in available_warehouses})
            warehouses_block = (
                "CONNECTED WAREHOUSES (the `warehouse` field MUST be one of these):\n- "
                + "\n- ".join(wh_list)
            )
        else:
            warehouses_block = (
                "CONNECTED WAREHOUSES: not provided — assume target warehouse is "
                f"`{warehouse_type}`."
            )

        system_prompt = f"""You are a SQL specialist for data pipelines. \
Return a single JSON object. No markdown, no code fences, no extra keys, no preamble text.

Your job: Given a user question and database schema, produce a single SQL query.

RULES:
1. Use ONLY column names from the provided schema. Never guess.
2. Always use fully qualified table names as shown in the schema.
3. SELECT only — no INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, CREATE.
4. Add LIMIT 1000 unless the user asks for aggregates (COUNT, SUM, AVG, GROUP BY).
5. Target warehouse: {warehouse_type}.
DIALECT RULES:
{dialect_rules}
6. If the schema does not contain the needed columns, set "sql" to empty string and explain in "explanation".
7. The "warehouse" field is REQUIRED — always set it to "{warehouse_type}".

{warehouses_block}

OUTPUT FORMAT (strict JSON):
{schema_json}"""

        if kwargs.get("repair_mode"):
            system_prompt = REPAIR_MODE_PREFIX + system_prompt

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {query}\n\nEvidence:\n{evidence}"},
        ]
