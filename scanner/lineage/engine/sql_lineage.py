"""
SQL Lineage Extractor

Wraps UniversalLineageParser to produce LineageEdge and ColumnMapping
objects with proper evidence, confidence, and safety constraints.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..graph import (
    ColumnMapping,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
)
from ..parser import UniversalLineageParser
from .ids import generate_edge_id, normalize_identifier

logger = logging.getLogger(__name__)


class SQLLineageExtractor:
    """
    Extracts table-level and (safe) column-level lineage from SQL strings.

    Column lineage is produced ONLY when:
    - The SELECT list is explicit (no SELECT *)
    - The AST can map columns deterministically
    Otherwise only table-level edges are emitted.
    """

    def __init__(self, default_dialect: str = "postgres"):
        self._parser = UniversalLineageParser(default_dialect=default_dialect)
        self._dialect = default_dialect

    def extract(
        self,
        sql: str,
        dialect: Optional[str] = None,
        case_hint: str = "lower",
        adapter_id: str = "sql_parser",
        source_ref: str = "",
        source_node_ids: Optional[Dict[str, str]] = None,
        target_node_id: Optional[str] = None,
    ) -> Tuple[List[LineageEdge], List[ColumnMapping]]:
        """
        Extract lineage from a single SQL statement.

        Args:
            sql: SQL query string
            dialect: SQL dialect override
            case_hint: Identifier casing convention
            adapter_id: Adapter that provided this SQL
            source_ref: Evidence source reference
            source_node_ids: Map of table_ref -> node_id for resolved tables
            target_node_id: Node ID of the output/target table (if known)

        Returns:
            Tuple of (edges, column_mappings)
        """
        dialect = dialect or self._dialect
        source_node_ids = source_node_ids or {}
        edges: List[LineageEdge] = []
        all_col_mappings: List[ColumnMapping] = []
        now = datetime.utcnow()

        # Parse table-level lineage
        info = self._parser.parse_query(sql, dialect)
        snippet = sql[:200] if sql else ""

        # Determine confidence based on parse method
        if info.statement_type == "regex_fallback":
            confidence = 0.3
        elif info.statement_type == "parse_error":
            return [], []
        else:
            confidence = 0.8

        # Table-level edges: each source -> target
        for src_ref in info.sources:
            src_norm = normalize_identifier(src_ref, case_hint)
            src_id = source_node_ids.get(src_norm) or source_node_ids.get(src_ref)

            if not src_id or not target_node_id:
                continue

            ev_ref = source_ref or f"sql:{src_norm}"
            edge_id = generate_edge_id(src_id, target_node_id, "depends_on", "table", ev_ref)

            edges.append(LineageEdge(
                id=edge_id,
                source_id=src_id,
                target_id=target_node_id,
                edge_type=EdgeType.DEPENDS_ON,
                confidence=confidence,
                discovered_from=adapter_id,
                discovered_at=now,
                lineage_level=LineageLevel.TABLE,
                evidence=[Evidence(
                    adapter_id=adapter_id,
                    source_ref=ev_ref,
                    observed_at=now,
                    snippet=snippet,
                )],
            ))

        # Column-level lineage (only when safe)
        col_mappings_raw = self._parser.extract_column_lineage(sql, dialect)
        if col_mappings_raw and target_node_id:
            for m in col_mappings_raw:
                from_table = normalize_identifier(m.get("from_table", ""), case_hint)
                src_id = source_node_ids.get(from_table)
                if not src_id:
                    continue

                col_map = ColumnMapping(
                    from_column=normalize_identifier(m["from_column"], case_hint),
                    to_column=normalize_identifier(m["to_column"], case_hint),
                    confidence=float(m.get("confidence", 0.9)),
                )
                all_col_mappings.append(col_map)

            # Group column mappings by source table and create column-level edges
            if all_col_mappings:
                by_source: Dict[str, List[ColumnMapping]] = {}
                for m in col_mappings_raw:
                    from_table = normalize_identifier(m.get("from_table", ""), case_hint)
                    src_id = source_node_ids.get(from_table)
                    if not src_id:
                        continue
                    by_source.setdefault(src_id, []).append(
                        ColumnMapping(
                            from_column=normalize_identifier(m["from_column"], case_hint),
                            to_column=normalize_identifier(m["to_column"], case_hint),
                            confidence=float(m.get("confidence", 0.9)),
                        )
                    )

                for src_id, mappings in by_source.items():
                    ev_ref = source_ref or f"sql_col:{src_id}"
                    edge_id = generate_edge_id(
                        src_id, target_node_id, "depends_on", "column", ev_ref
                    )
                    edges.append(LineageEdge(
                        id=edge_id,
                        source_id=src_id,
                        target_id=target_node_id,
                        edge_type=EdgeType.DEPENDS_ON,
                        confidence=0.9,
                        discovered_from=adapter_id,
                        discovered_at=now,
                        lineage_level=LineageLevel.COLUMN,
                        evidence=[Evidence(
                            adapter_id=adapter_id,
                            source_ref=ev_ref,
                            observed_at=now,
                            snippet=snippet,
                        )],
                        column_mappings=mappings,
                    ))

        return edges, all_col_mappings
