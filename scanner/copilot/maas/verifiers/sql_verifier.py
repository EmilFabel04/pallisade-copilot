"""
Deterministic SQL verifier.

Safety checks only — LIMIT injection, dialect quirks, and dry-run stay in ToolExecutor.
"""

import re
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

from ..schemas import SQLResponse

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    passed: bool
    errors: List[str]
    warnings: List[str]


# Forbidden keywords — any DML/DDL besides SELECT
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|MERGE|CALL|EXEC)\b",
    re.IGNORECASE,
)

# Warehouse syntax patterns
_BIGQUERY_BACKTICK = re.compile(r"`[^`]+`")
_SNOWFLAKE_FUNCS = re.compile(
    r"\b(TRY_TO_NUMBER|TRY_TO_DATE|FLATTEN|LATERAL|QUALIFY|IFF)\b",
    re.IGNORECASE,
)


class SQLVerifier:
    """
    Deterministic SQL verifier for MAAS.

    Checks:
    1. SELECT-only (no DML/DDL)
    2. Balanced parentheses
    3. Column names exist in schema (heuristic)
    4. Warehouse targeting matches syntax
    5. Multi-warehouse: warehouse field is required
    """

    def verify(
        self,
        response: SQLResponse,
        schema_columns: Dict[str, Set[str]],
        connected_warehouses: Optional[List[str]] = None,
    ) -> VerificationResult:
        errors: List[str] = []
        warnings: List[str] = []
        sql = response.sql.strip()

        if not sql:
            return VerificationResult(
                passed=True,
                errors=[],
                warnings=["Empty SQL — specialist declined to generate a query"],
            )

        # 1. SELECT-only check
        match = _FORBIDDEN.search(sql)
        if match:
            errors.append(f"Forbidden keyword: {match.group()}")

        # 2. Balanced parentheses
        open_count = sql.count("(")
        close_count = sql.count(")")
        if open_count != close_count:
            errors.append(
                f"Unbalanced parentheses: {open_count} open, {close_count} close"
            )

        # 3. Column validation against schema (heuristic, warnings only)
        col_warnings = self._check_columns(sql, schema_columns)
        warnings.extend(col_warnings)

        # 4. Warehouse targeting — syntax should match declared warehouse
        syntax_warnings = self._check_warehouse_syntax(sql, response.warehouse.value)
        warnings.extend(syntax_warnings)

        # 5. Multi-warehouse: warehouse field required
        if connected_warehouses and len(connected_warehouses) > 1:
            if not response.warehouse:
                errors.append(
                    "Multiple warehouses connected — warehouse field is required. "
                    f"Available: {connected_warehouses}"
                )
            elif response.warehouse.value.upper() not in [
                w.upper() for w in connected_warehouses
            ]:
                errors.append(
                    f"Warehouse '{response.warehouse.value}' not in connected "
                    f"warehouses: {connected_warehouses}"
                )

        return VerificationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _check_columns(
        self,
        sql: str,
        schema_columns: Dict[str, Set[str]],
    ) -> List[str]:
        """Heuristic column check — returns warnings for unknown identifiers."""
        warnings = []
        all_known_columns: Set[str] = set()
        table_names: Set[str] = set()

        for fqn, cols in schema_columns.items():
            all_known_columns.update(c.lower() for c in cols)
            for part in fqn.lower().split("."):
                table_names.add(part)

        if not all_known_columns:
            return warnings

        sql_keywords = {
            "select", "from", "where", "and", "or", "not", "in", "is",
            "null", "as", "on", "join", "left", "right", "inner", "outer",
            "cross", "full", "group", "by", "order", "asc", "desc", "limit",
            "offset", "count", "sum", "avg", "min", "max", "distinct",
            "case", "when", "then", "else", "end", "true", "false",
            "between", "like", "having", "union", "all", "except",
            "intersect", "exists", "cast", "coalesce", "if", "ifnull",
            "nullif", "with", "recursive", "over", "partition", "row_number",
            "rank", "dense_rank", "lag", "lead", "first_value", "last_value",
            "extract", "date", "timestamp", "interval", "format_timestamp",
            "safe_divide", "try_to_number", "try_to_date", "to_char",
            "string_agg", "array_agg", "unnest", "flatten", "lateral",
        }

        tokens = set(re.findall(r"\b([a-zA-Z_]\w*)\b", sql.lower()))
        unknown = tokens - sql_keywords - all_known_columns - table_names

        if unknown and len(unknown) <= 5:
            warnings.append(
                f"Possibly unknown identifiers: {sorted(unknown)[:5]}. "
                "Verify against schema."
            )

        return warnings

    def _check_warehouse_syntax(self, sql: str, warehouse: str) -> List[str]:
        """Check that SQL syntax matches declared warehouse type."""
        warnings = []
        wh = warehouse.lower()

        if wh == "bigquery":
            # BigQuery uses backticks — warn if we see Snowflake patterns
            if _SNOWFLAKE_FUNCS.search(sql):
                warnings.append(
                    "SQL uses Snowflake-specific functions but targets BigQuery"
                )
        elif wh == "snowflake":
            # Snowflake shouldn't use backticks
            if _BIGQUERY_BACKTICK.search(sql):
                warnings.append(
                    "SQL uses backtick identifiers (BigQuery style) but targets Snowflake"
                )

        return warnings
