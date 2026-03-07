"""Logs specialist — extracts error signatures and triages root cause from logs/tool results."""

from typing import Type
from pydantic import BaseModel

from .base import BaseSpecialist
from ..schemas import LogsResponse


class LogsSpecialist(BaseSpecialist):

    @property
    def name(self) -> str:
        return "logs"

    @property
    def response_model(self) -> Type[BaseModel]:
        return LogsResponse

    def build_messages(self, evidence: str, query: str, **kwargs) -> list:
        schema_json = LogsResponse.model_json_schema()

        system_prompt = f"""You are a data pipeline logs analyst. \
Return a single JSON object. No markdown, no code fences, no extra keys, no preamble text.

Your job: Given error logs, tool results, and schema context, extract:
1. The error signature (failure layer, message, system)
2. The root cause owner system
3. Up to 3 additional tool calls needed for evidence (if applicable)
4. A one-paragraph summary

FAILURE LAYERS (use one of these exact strings):
- Connection/Auth: credentials expired, permission denied, connection refused
- SQL Compilation: syntax error, column/table not found, type mismatch
- Runtime/Data: query ran but hit bad data, duplicates, NULLs, schema drift
- Orchestration: DAG parse error, import error, sensor timeout, scheduler issue

OWNER SYSTEMS (use one of these exact strings):
airflow, dbt, ingestion, warehouse, infra, reporting, unknown

RULES:
1. If the error contains SQL or a warehouse error code, it is NOT Connection/Auth.
2. next_evidence must have at most 3 entries. Each must have a valid tool_name.
3. summary must be non-empty.
4. owner_confidence must be between 0.0 and 1.0.

OUTPUT FORMAT (strict JSON):
{schema_json}"""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Investigation: {query}\n\nEvidence:\n{evidence}"},
        ]
