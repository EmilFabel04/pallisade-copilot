"""
Per-request evidence store that scopes data for specialist prompts.

Prevents context burnout by:
- Truncating individual results to MAX_TOOL_RESULT_CHARS
- Limiting total evidence per specialist call to MAX_TOTAL_EVIDENCE_CHARS
- Scoring schema tables by relevance (reuses context_builder logic)
- Bounding log excerpts to MAX_LOG_LINES
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set

from copilot.context_builder import CopilotContext, TableSchema, tokenize_query, score_table_relevance

logger = logging.getLogger(__name__)

# Maximum sizes to prevent context burnout
MAX_TOOL_RESULT_CHARS = 4_000
MAX_LOG_LINES = 50
MAX_SCHEMA_TABLES = 8
MAX_LINEAGE_NODES = 30
MAX_TOTAL_EVIDENCE_CHARS = 20_000


@dataclass
class EvidenceItem:
    """A single piece of evidence collected during orchestration."""
    source: str           # tool name or "schema" or "lineage"
    category: str         # "schema", "query_result", "log", "lineage", "error", "metric"
    warehouse: Optional[str] = None
    data: Any = None
    summary: Optional[str] = None
    char_count: int = 0


@dataclass
class EvidenceStore:
    """
    Per-request evidence store that scopes data for specialist prompts.

    Created once per MAAS request. Tools add results to it, and specialists
    receive scoped slices via for_specialist().
    """
    context: CopilotContext
    items: List[EvidenceItem] = field(default_factory=list)
    _lineage_upstream: List[Dict[str, Any]] = field(default_factory=list)
    _lineage_downstream: List[Dict[str, Any]] = field(default_factory=list)
    _tool_result_cache: Dict[str, Any] = field(default_factory=dict)

    def add_tool_result(
        self,
        tool_name: str,
        result: Dict[str, Any],
        warehouse: Optional[str] = None,
    ):
        """Add a tool execution result, truncated to bounds."""
        text = json.dumps(result, default=str)
        truncated = text[:MAX_TOOL_RESULT_CHARS]
        if len(text) > MAX_TOOL_RESULT_CHARS:
            truncated += f"... [truncated, {len(text)} total chars]"

        category = _categorize_result(tool_name, result)
        self.items.append(EvidenceItem(
            source=tool_name,
            category=category,
            warehouse=warehouse,
            data=truncated,
            summary=_summarize_result(tool_name, result),
            char_count=len(truncated),
        ))

    def add_log_excerpt(self, source: str, log_text: str):
        """Add bounded log excerpt."""
        lines = log_text.split("\n")
        bounded = "\n".join(lines[:MAX_LOG_LINES])
        if len(lines) > MAX_LOG_LINES:
            bounded += f"\n... [{len(lines) - MAX_LOG_LINES} more lines truncated]"

        self.items.append(EvidenceItem(
            source=source,
            category="log",
            data=bounded,
            char_count=len(bounded),
        ))

    def add_lineage(self, direction: str, nodes: List[Dict[str, Any]]):
        """Add lineage neighborhood, bounded to MAX_LINEAGE_NODES."""
        bounded = nodes[:MAX_LINEAGE_NODES]
        if direction == "upstream":
            self._lineage_upstream = bounded
        else:
            self._lineage_downstream = bounded

    def slice_schema(self, query: str) -> str:
        """
        Build a schema slice relevant to the query.

        Reuses the scoring logic from context_builder.score_table_relevance.
        Returns formatted prompt text with top-scored tables.
        """
        query_lower = query.lower()
        query_tokens = set(tokenize_query(query_lower))

        scored = []
        for schema_key, tables in self.context.warehouse_schema.items():
            _, dataset_name = _parse_schema_key(schema_key)
            for table in tables:
                score = score_table_relevance(
                    table, dataset_name, query_lower, query_tokens
                )
                scored.append((score, schema_key, table))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_tables = scored[:MAX_SCHEMA_TABLES]

        if not top_tables:
            return "## Schema\nNo schema available."

        lines = ["## Schema"]
        for score, schema_key, table in top_tables:
            wh_type, dataset = _parse_schema_key(schema_key)
            prefix = f"{wh_type}:" if wh_type else ""
            cols = ", ".join(
                f"{c.get('name', '?')} ({c.get('type', '?')})"
                for c in table.columns[:10]
            )
            extra = f" + {len(table.columns) - 10} more" if len(table.columns) > 10 else ""
            lines.append(f"- {prefix}{dataset}.{table.name}: {cols}{extra}")

        return "\n".join(lines)

    def for_specialist(
        self,
        specialist: str,
        query: str,
        warehouse_filter: Optional[str] = None,
    ) -> str:
        """
        Build a scoped evidence blob for a specialist prompt.

        Returns a string under MAX_TOTAL_EVIDENCE_CHARS.
        """
        parts = []

        # Schema slice for SQL specialist and orchestrator
        if specialist in ("sql", "orchestrator"):
            parts.append(self.slice_schema(query))

        # Lineage for Logs specialist and orchestrator
        if specialist in ("logs", "orchestrator"):
            if self._lineage_upstream or self._lineage_downstream:
                parts.append(_format_lineage(
                    self._lineage_upstream, self._lineage_downstream
                ))

        # Relevant evidence items
        for item in self.items:
            if warehouse_filter and item.warehouse and item.warehouse != warehouse_filter:
                continue
            if item.summary:
                parts.append(f"[{item.source}] {item.summary}")
            if item.data:
                parts.append(f"[{item.source}]\n{item.data}")

        blob = "\n\n".join(parts)
        if len(blob) > MAX_TOTAL_EVIDENCE_CHARS:
            blob = blob[:MAX_TOTAL_EVIDENCE_CHARS] + "\n... [evidence truncated]"
        return blob

    def get_cached_result(self, args_hash: str) -> Optional[Dict[str, Any]]:
        """Get a previously cached tool result by args_hash."""
        return self._tool_result_cache.get(args_hash)

    def cache_result(self, args_hash: str, result: Dict[str, Any]):
        """Cache a tool result for deduplication."""
        self._tool_result_cache[args_hash] = result


def _parse_schema_key(key: str) -> tuple:
    """Parse 'WAREHOUSE_TYPE:dataset' key format."""
    if ":" in key:
        wh_type, dataset = key.split(":", 1)
        return wh_type, dataset
    return None, key


def _categorize_result(tool_name: str, result: Dict) -> str:
    """Categorize a tool result for evidence organization."""
    name_lower = tool_name.lower()
    if "query" in name_lower or "warehouse" in name_lower:
        return "query_result"
    if "log" in name_lower:
        return "log"
    if any(k in name_lower for k in ("lineage", "upstream", "downstream")):
        return "lineage"
    if any(k in name_lower for k in ("coverage", "monitor", "anomaly")):
        return "metric"
    return "other"


def _summarize_result(tool_name: str, result: Dict) -> Optional[str]:
    """Generate a short summary of a tool result."""
    if result.get("success") is False:
        return f"FAILED: {result.get('error', 'unknown error')}"
    data = result.get("data")
    if isinstance(data, list):
        return f"Returned {len(data)} items"
    if isinstance(data, dict) and "rows" in data:
        return f"Returned {len(data['rows'])} rows"
    return None


def _format_lineage(upstream: List[Dict], downstream: List[Dict]) -> str:
    """Format lineage neighborhood for specialist prompts."""
    lines = ["## Lineage Neighborhood"]
    if upstream:
        lines.append(f"Upstream ({len(upstream)} nodes):")
        for node in upstream[:10]:
            lines.append(f"  - {node.get('name', node.get('id', '?'))}")
        if len(upstream) > 10:
            lines.append(f"  ... +{len(upstream) - 10} more")
    if downstream:
        lines.append(f"Downstream ({len(downstream)} nodes):")
        for node in downstream[:10]:
            lines.append(f"  - {node.get('name', node.get('id', '?'))}")
        if len(downstream) > 10:
            lines.append(f"  ... +{len(downstream) - 10} more")
    return "\n".join(lines)
