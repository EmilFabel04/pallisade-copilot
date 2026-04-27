"""
Abstract base monitor and shared result types.

Every monitor produces dialect-agnostic SQL via sqlglot, which is then
transpiled to the target warehouse's dialect before execution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import sqlglot


class MonitorStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class MonitorResult:
    """Result of executing a single monitor."""

    monitor_type: str
    target_fqn: str
    status: MonitorStatus
    value: Optional[float] = None
    threshold: Optional[float] = None
    expected_range: Optional[Dict[str, float]] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    executed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    sql_executed: Optional[str] = None
    raw_status: Optional["MonitorStatus"] = None

    @property
    def is_passing(self) -> bool:
        return self.status in (MonitorStatus.PASS, MonitorStatus.SKIPPED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "monitor_type": self.monitor_type,
            "target_fqn": self.target_fqn,
            "status": self.status.value,
            "value": self.value,
            "threshold": self.threshold,
            "expected_range": self.expected_range,
            "message": self.message,
            "details": self.details,
            "executed_at": (
                self.executed_at.isoformat() if self.executed_at else None
            ),
            "duration_ms": self.duration_ms,
            "raw_status": self.raw_status.value if self.raw_status else None,
        }


class BaseMonitor(ABC):
    """
    Abstract base for all tech-agnostic monitors.

    Subclasses implement `build_query()` to produce a dialect-neutral SQL
    query string (using sqlglot's generic SQL), and `evaluate()` to
    interpret the query results into a MonitorResult.

    The executor handles dialect transpilation and actual execution.
    """

    monitor_type: str = "base"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        """
        Build the monitoring SQL query.

        Parameters
        ----------
        database : str
            Target database name.
        schema : str
            Target schema name.
        table : str
            Target table name.
        dialect : str
            Target warehouse dialect for sqlglot transpilation.

        Returns
        -------
        str
            SQL query string ready for execution against the target warehouse.
        """
        ...

    @abstractmethod
    def evaluate(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        """
        Evaluate query results and produce a MonitorResult.

        Parameters
        ----------
        query_results : list of dict
            Rows returned by the monitoring query.
        target_fqn : str
            Fully qualified name of the monitored asset.

        Returns
        -------
        MonitorResult
        """
        ...

    def transpile_sql(self, sql: str, target_dialect: str) -> str:
        """Transpile generic SQL to a specific warehouse dialect."""
        try:
            transpiled = sqlglot.transpile(
                sql, read="postgres", write=target_dialect
            )
            return transpiled[0] if transpiled else sql
        except Exception:
            # Fall back to the original SQL if transpilation fails.
            return sql

    def _fqn(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        """Build a quoted, fully qualified table reference for *dialect*.

        Each part is validated against a strict identifier character set;
        anything else raises ValueError. The dialect controls the quote
        character (backticks for BigQuery / Databricks, brackets for
        SQL Server, double-quotes elsewhere).
        """
        from scanner.adapters.sql_safety import join_quoted_identifiers
        parts = [p for p in (database, schema, table) if p]
        return join_quoted_identifiers(parts, dialect)

    def _qident(self, name: str, dialect: str = "postgres") -> str:
        """Validate + quote a single column or alias identifier."""
        from scanner.adapters.sql_safety import quote_identifier
        return quote_identifier(name, dialect)

    def _validate_column(self, name: str) -> str:
        """Reject column names with SQL metacharacters; return unchanged.

        Use at the top of `build_query` for any user-supplied column name
        that will be interpolated unquoted into SQL (e.g. `COUNT(DISTINCT
        {col})` or `AS null_rate_{col}`). Validation is strict — columns
        with dashes or other special characters must instead flow through
        `_qident()` and be used in identifier-quoted positions only.
        """
        import re
        if not isinstance(name, str) or not name:
            raise ValueError("column name is required")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_$]*$", name):
            raise ValueError("column name contains disallowed characters")
        return name
