"""
SQL Lineage Extractor

Uses sqlglot directly to extract table-level and column-level lineage
from SQL strings. Produces LineageEdge and ColumnMapping objects with
proper evidence, confidence, and safety constraints.

This is the standard utility for any adapter that needs SQL parsing.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp

from ..graph import (
    ColumnMapping,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
)
from .ids import generate_edge_id, normalize_identifier

logger = logging.getLogger(__name__)

# Mapping of common dialect names to sqlglot dialect names
DIALECT_MAP = {
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "databricks": "databricks",
    "spark": "spark",
    "redshift": "redshift",
    "postgres": "postgres",
    "postgresql": "postgres",
    "mysql": "mysql",
    "duckdb": "duckdb",
    "trino": "trino",
    "presto": "presto",
    "sqlite": "sqlite",
    "oracle": "oracle",
    "mssql": "tsql",
    "sqlserver": "tsql",
    "azuresql": "tsql",
}


def _norm_dialect(dialect: str) -> str:
    return DIALECT_MAP.get(dialect.lower().strip(), dialect.lower().strip())


class SQLLineageExtractor:
    """
    Extracts table-level and column-level lineage from SQL strings.

    Uses sqlglot for robust multi-dialect parsing with regex fallback.
    Column lineage is produced ONLY when the SELECT list is explicit
    (no SELECT *) and the AST can map columns deterministically.
    """

    def __init__(self, default_dialect: str = "postgres"):
        self._dialect = _norm_dialect(default_dialect)

    # ------------------------------------------------------------------
    # Quick table extraction (replaces regex in adapters)
    # ------------------------------------------------------------------

    def extract_table_refs(
        self,
        sql: str,
        dialect: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """
        Extract source and target table references from SQL.

        Returns:
            {"sources": ["schema.table", ...], "targets": ["schema.table", ...]}
        """
        dialect = _norm_dialect(dialect or self._dialect)
        sources: Set[str] = set()
        targets: Set[str] = set()

        try:
            parsed = sqlglot.parse(sql, dialect=dialect)
            if not parsed:
                return {"sources": [], "targets": []}

            for statement in parsed:
                if statement is None:
                    continue

                s, t = self._extract_sources_targets(statement)
                sources.update(s)
                targets.update(t)

        except Exception as e:
            logger.debug(f"[SQLLineage] sqlglot parse failed, trying regex: {e}")
            sources, targets = self._regex_fallback(sql)

        return {"sources": sorted(sources), "targets": sorted(targets)}

    def extract_source_tables(
        self,
        sql: str,
        dialect: Optional[str] = None,
    ) -> List[str]:
        """Convenience: return just the source tables from SQL."""
        return self.extract_table_refs(sql, dialect)["sources"]

    # ------------------------------------------------------------------
    # Full lineage extraction (table + column level edges)
    # ------------------------------------------------------------------

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
        dialect = _norm_dialect(dialect or self._dialect)
        source_node_ids = source_node_ids or {}
        edges: List[LineageEdge] = []
        all_col_mappings: List[ColumnMapping] = []
        now = datetime.utcnow()
        snippet = sql[:200] if sql else ""

        # Parse with sqlglot
        confidence = 0.8
        sources: Set[str] = set()
        is_regex = False

        try:
            parsed = sqlglot.parse(sql, dialect=dialect)
            if not parsed:
                return [], []

            for statement in parsed:
                if statement is None:
                    continue
                s, _ = self._extract_sources_targets(statement)
                sources.update(s)

        except Exception:
            # Regex fallback
            fb_sources, _ = self._regex_fallback(sql)
            sources = fb_sources
            confidence = 0.3
            is_regex = True

        # Table-level edges: each source -> target
        for src_ref in sources:
            src_norm = normalize_identifier(src_ref, case_hint)
            src_id = source_node_ids.get(src_norm) or source_node_ids.get(src_ref)

            if not src_id or not target_node_id:
                continue

            ev_ref = source_ref or f"sql:{src_norm}"
            edge_id = generate_edge_id(
                src_id, target_node_id, "depends_on", "table", ev_ref
            )

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

        # Column-level lineage (skip if regex fallback)
        if not is_regex and target_node_id:
            col_mappings = self._extract_column_lineage(sql, dialect)
            if col_mappings:
                by_source: Dict[str, List[ColumnMapping]] = {}
                for m in col_mappings:
                    from_table = normalize_identifier(m.get("from_table", ""), case_hint)
                    src_id = source_node_ids.get(from_table)
                    if not src_id:
                        continue

                    cm = ColumnMapping(
                        from_column=normalize_identifier(m["from_column"], case_hint),
                        to_column=normalize_identifier(m["to_column"], case_hint),
                        transform_expr=m.get("transform_expr"),
                        confidence=float(m.get("confidence", 0.9)),
                    )
                    all_col_mappings.append(cm)
                    by_source.setdefault(src_id, []).append(cm)

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

    # ------------------------------------------------------------------
    # Internal: AST-based source/target extraction
    # ------------------------------------------------------------------

    def _extract_sources_targets(
        self, statement: exp.Expression
    ) -> Tuple[Set[str], Set[str]]:
        """Extract source and target tables from a parsed statement."""
        sources: Set[str] = set()
        targets: Set[str] = set()

        # Find target tables (CREATE, INSERT, MERGE, UPDATE)
        if isinstance(statement, exp.Create):
            target = statement.this
            if isinstance(target, exp.Table):
                targets.add(self._table_name(target))
            elif isinstance(target, exp.Schema):
                table = target.this
                if isinstance(table, exp.Table):
                    targets.add(self._table_name(table))

        elif isinstance(statement, exp.Insert):
            target = statement.this
            if isinstance(target, exp.Table):
                targets.add(self._table_name(target))

        elif isinstance(statement, exp.Merge):
            target = statement.this
            if isinstance(target, exp.Table):
                targets.add(self._table_name(target))

        elif isinstance(statement, exp.Update):
            target = statement.this
            if isinstance(target, exp.Table):
                targets.add(self._table_name(target))

        # Find all source tables (FROM, JOIN, subqueries)
        cte_names: Set[str] = set()
        for cte in statement.find_all(exp.CTE):
            alias = cte.alias
            if alias:
                cte_names.add(str(alias))

        for table in statement.find_all(exp.Table):
            name = self._table_name(table)
            if name and name not in targets and name not in cte_names:
                if not self._is_temp(name):
                    sources.add(name)

        return sources, targets

    def _table_name(self, table: exp.Table) -> str:
        """Extract fully qualified table name from AST node."""
        parts = []
        if table.catalog:
            parts.append(str(table.catalog))
        if table.db:
            parts.append(str(table.db))
        if table.name:
            parts.append(str(table.name))
        return ".".join(parts) if parts else str(table)

    @staticmethod
    def _is_temp(name: str) -> bool:
        lower = name.lower()
        return (
            lower.startswith("_")
            or lower.startswith("temp_")
            or lower.startswith("tmp_")
            or "#" in lower
        )

    # ------------------------------------------------------------------
    # Internal: column-level lineage via sqlglot
    # ------------------------------------------------------------------

    def _extract_column_lineage(
        self, sql: str, dialect: str
    ) -> List[Dict[str, str]]:
        """
        Extract column-level lineage using sqlglot AST walking.

        Only produces mappings when the SELECT list is explicit (no SELECT *).
        """
        mappings: List[Dict[str, str]] = []

        try:
            parsed = sqlglot.parse(sql, dialect=dialect)
            if not parsed:
                return []

            for statement in parsed:
                if statement is None:
                    continue

                # Collect CTE definitions for tracing
                cte_defs: Dict[str, exp.Expression] = {}
                for cte in statement.find_all(exp.CTE):
                    cte_name = cte.alias
                    if cte_name:
                        cte_defs[str(cte_name)] = cte.this

                select = statement.find(exp.Select)
                if not select:
                    continue

                # Bail out on SELECT * — can't safely map columns
                for expr in select.expressions:
                    if isinstance(expr, exp.Star):
                        return []
                    if isinstance(expr, exp.Column) and isinstance(
                        expr.this, exp.Star
                    ):
                        return []

                # Map each output column to its source(s)
                for expr in select.expressions:
                    out_col = self._get_output_alias(expr)
                    if not out_col:
                        continue

                    source_cols = self._trace_column_sources(expr, cte_defs)
                    for src_table, src_col, transform in source_cols:
                        if self._is_temp(src_table):
                            continue
                        mapping: Dict[str, str] = {
                            "from_table": src_table,
                            "from_column": src_col,
                            "to_column": out_col,
                            "confidence": "0.9",
                        }
                        if transform:
                            mapping["transform_expr"] = transform
                        mappings.append(mapping)

        except Exception:
            return []

        return mappings

    @staticmethod
    def _get_output_alias(expr: exp.Expression) -> Optional[str]:
        if isinstance(expr, exp.Alias):
            return str(expr.alias)
        if isinstance(expr, exp.Column):
            return str(expr.name)
        return None

    def _trace_column_sources(
        self,
        expr: exp.Expression,
        cte_defs: Dict[str, exp.Expression],
    ) -> List[Tuple[str, str, Optional[str]]]:
        """Trace a SELECT expression back to source (table, column, transform_expr) tuples."""
        results: List[Tuple[str, str, Optional[str]]] = []

        # Detect if this is a transformed expression (not a simple column ref)
        is_transform = isinstance(expr, exp.Alias) and not isinstance(
            expr.this, exp.Column
        )
        transform_expr = expr.sql() if is_transform else None

        for col in expr.find_all(exp.Column):
            col_name = str(col.name)
            table_ref = str(col.table) if col.table else ""

            if table_ref and table_ref in cte_defs:
                # Trace through CTE
                cte_select = cte_defs[table_ref].find(exp.Select)
                if cte_select:
                    for cte_expr in cte_select.expressions:
                        alias = self._get_output_alias(cte_expr)
                        if alias and alias == col_name:
                            deeper = self._trace_column_sources(
                                cte_expr, cte_defs
                            )
                            results.extend(deeper)
                            break
                    else:
                        results.append((table_ref, col_name, transform_expr))
            elif table_ref:
                results.append((table_ref, col_name, transform_expr))
            else:
                results.append(("", col_name, transform_expr))

        return results

    # ------------------------------------------------------------------
    # Regex fallback for malformed SQL
    # ------------------------------------------------------------------

    @staticmethod
    def _regex_fallback(sql: str) -> Tuple[Set[str], Set[str]]:
        import re

        sources: Set[str] = set()
        targets: Set[str] = set()

        sql_clean = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
        sql_clean = " ".join(sql_clean.split())

        create_match = re.search(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW)"
            r"\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
            sql_clean,
            re.IGNORECASE,
        )
        if create_match:
            targets.add(create_match.group(1))

        insert_match = re.search(
            r"INSERT\s+(?:INTO\s+)?([^\s(]+)", sql_clean, re.IGNORECASE
        )
        if insert_match:
            targets.add(insert_match.group(1))

        merge_match = re.search(
            r"MERGE\s+INTO\s+([^\s]+)", sql_clean, re.IGNORECASE
        )
        if merge_match:
            targets.add(merge_match.group(1))

        from_matches = re.findall(
            r"FROM\s+([^\s,()]+)", sql_clean, re.IGNORECASE
        )
        join_matches = re.findall(
            r"JOIN\s+([^\s,()]+)", sql_clean, re.IGNORECASE
        )

        skip = {"SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "AS", "SET"}
        for table in from_matches + join_matches:
            table = table.strip('`"[]')
            if table.upper() not in skip and table not in targets:
                sources.add(table)

        return sources, targets
