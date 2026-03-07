"""CodeFix specialist — proposes unified diff patches with validation and rollback."""

from typing import Type
from pydantic import BaseModel

from .base import BaseSpecialist
from ..schemas import CodeFixResponse


class CodeFixSpecialist(BaseSpecialist):

    @property
    def name(self) -> str:
        return "codefix"

    @property
    def response_model(self) -> Type[BaseModel]:
        return CodeFixResponse

    def build_messages(self, evidence: str, query: str, **kwargs) -> list:
        schema_json = CodeFixResponse.model_json_schema()

        system_prompt = f"""You are a data pipeline code fix specialist. \
Return a single JSON object. No markdown, no code fences, no extra keys, no preamble text.

Your job: Given a root cause analysis and schema/lineage context, produce:
1. Unified diff patches for all files that need changes
2. Validation steps (static + CI)
3. Rollback steps
4. Impact summary on downstream objects

RULES:
1. Patches must be complete — full file content in new_content, not just the changed lines.
2. patch_type must be one of: sql_model, yaml_config, python_script, orchestration, text_file.
3. Always include rollback steps for every patch.
4. Include fixes for ALL downstream breakages, not just the original issue.
5. Use real table/column/project names from the evidence — never placeholders.
6. file_path must be a valid relative path (e.g. models/staging/stg_orders.sql).

OUTPUT FORMAT (strict JSON):
{schema_json}"""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Fix request: {query}\n\nEvidence:\n{evidence}"},
        ]
