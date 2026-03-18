"""
Schema change monitor.

Detects column additions, deletions, type changes, and ordering changes
by comparing the current INFORMATION_SCHEMA against a stored baseline.
Works across any SQL warehouse.

Each schema change is classified by severity:
- CRITICAL: PK/FK column removed or type changed
- HIGH: Non-nullable column removed, narrowing type change
- MEDIUM: Column added with NOT NULL, type widening
- LOW: Nullable column added, nullable change
- INFO: Ordering change only
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseMonitor, MonitorResult, MonitorStatus
from .stats import column_name_similarity


# Severity levels (ordered from highest to lowest)
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_INFO = "info"

_SEVERITY_ORDER = {
    SEVERITY_CRITICAL: 5,
    SEVERITY_HIGH: 4,
    SEVERITY_MEDIUM: 3,
    SEVERITY_LOW: 2,
    SEVERITY_INFO: 1,
}

# Types that are "wider" than others (widening is safer than narrowing)
_TYPE_WIDTH: Dict[str, int] = {
    "smallint": 1,
    "integer": 2,
    "bigint": 3,
    "real": 4,
    "double": 5,
    "numeric": 6,
    "text": 10,
    "varchar": 9,
}


class SchemaMonitor(BaseMonitor):
    """
    Monitors schema changes by querying INFORMATION_SCHEMA.COLUMNS
    and comparing against a known baseline.

    Each change is classified by severity based on column importance
    (PK/FK status, nullability) and change type.

    Config keys:
        baseline_columns : list[dict] | None
            Expected column definitions. Each dict should have
            "column_name", "data_type", and optionally "is_nullable",
            "is_primary_key", "is_foreign_key".
            If None, the monitor only reports the current schema
            (first-run mode).
        fail_on_column_added : bool
            Fail if new columns are detected (default: False).
        fail_on_column_removed : bool
            Fail if columns are missing (default: True).
        fail_on_type_change : bool
            Fail if a column's data type changed (default: True).
        min_severity : str
            Minimum severity to trigger a failure.
            One of: "critical", "high", "medium", "low", "info".
            Default: None (use the boolean flags above).
    """

    monitor_type = "schema_change"

    # Cross-dialect type alias mapping → canonical form.
    _TYPE_ALIASES: Dict[str, str] = {
        # BigQuery → canonical
        "int64": "integer",
        "float64": "double",
        "bool": "boolean",
        "string": "text",
        "bytes": "bytea",
        "bignumeric": "numeric",
        # Snowflake → canonical
        "number": "numeric",
        "variant": "json",
        "timestamp_ltz": "timestamptz",
        "timestamp_ntz": "timestamp",
        "timestamp_tz": "timestamptz",
        # Postgres aliases → canonical
        "character varying": "varchar",
        "double precision": "double",
        "int": "integer",
        "int4": "integer",
        "int8": "bigint",
        "int2": "smallint",
        "float4": "real",
        "float8": "double",
        "serial": "integer",
        "bigserial": "bigint",
        "timestamp with time zone": "timestamptz",
        "timestamp without time zone": "timestamp",
    }

    @staticmethod
    def _normalize_type(raw_type: str) -> str:
        """Normalize a data type string for cross-dialect comparison.

        Strips length/precision (e.g. ``varchar(255)`` → ``varchar``)
        and maps dialect-specific names to a canonical form so that
        ``INT64`` (BigQuery) matches ``integer`` (Postgres).
        """
        t = raw_type.lower().strip()
        # Strip length/precision: varchar(255) → varchar, numeric(10,2) → numeric
        paren_idx = t.find("(")
        if paren_idx > 0:
            t = t[:paren_idx].strip()
        return SchemaMonitor._TYPE_ALIASES.get(t, t)

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.mode: str = self.config.get("mode", "change_detection")
        self.baseline_columns: Optional[List[Dict[str, str]]] = self.config.get(
            "baseline_columns"
        )
        self.expected_types: Optional[Dict[str, str]] = self.config.get(
            "expected_types"
        )
        self.fail_on_added = self.config.get("fail_on_column_added", False)
        self.fail_on_removed = self.config.get("fail_on_column_removed", True)
        self.fail_on_type_change = self.config.get("fail_on_type_change", True)
        self.min_severity: Optional[str] = self.config.get("min_severity")
        self.rename_similarity_threshold: float = float(
            self.config.get("rename_similarity_threshold", 0.6)
        )

    def build_query(
        self,
        database: str,
        schema: str,
        table: str,
        dialect: str = "postgres",
    ) -> str:
        if dialect == "bigquery":
            sql = (
                f"SELECT "
                f"column_name, data_type, is_nullable, ordinal_position "
                f"FROM `{database}.{schema}.INFORMATION_SCHEMA.COLUMNS` "
                f"WHERE table_name = '{table}' "
                f"ORDER BY ordinal_position"
            )
        else:
            sql = (
                f"SELECT "
                f"column_name, data_type, is_nullable, ordinal_position "
                f"FROM information_schema.columns "
                f"WHERE table_catalog = '{database}' "
                f"AND table_schema = '{schema}' "
                f"AND table_name = '{table}' "
                f"ORDER BY ordinal_position"
            )

        return sql

    def evaluate(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        if self.mode == "type_validation":
            return self._evaluate_type_validation(query_results, target_fqn)

        if not query_results:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message="No columns found — table may not exist.",
            )

        current_columns = {
            row["column_name"].lower(): {
                "data_type": self._normalize_type(row.get("data_type", "")),
                "is_nullable": row.get("is_nullable", "YES"),
                "ordinal_position": row.get("ordinal_position"),
            }
            for row in query_results
        }

        # First-run mode: no baseline yet, just report current schema.
        if not self.baseline_columns:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message=(
                    f"Schema baseline established with "
                    f"{len(current_columns)} columns."
                ),
                details={
                    "column_count": len(current_columns),
                    "columns": list(current_columns.keys()),
                    "is_baseline_run": True,
                },
            )

        # Build baseline lookup.
        # Preserve None for is_nullable when not explicitly set in the
        # baseline — this avoids false nullable-change detections when
        # the baseline was established without nullable info.
        baseline = {
            col["column_name"].lower(): {
                "data_type": self._normalize_type(col.get("data_type", "")),
                "is_nullable": col.get("is_nullable"),  # None if not set
                "is_primary_key": col.get("is_primary_key", False),
                "is_foreign_key": col.get("is_foreign_key", False),
            }
            for col in self.baseline_columns
        }

        changes: List[Dict[str, Any]] = []
        baseline_names = set(baseline.keys())
        current_names = set(current_columns.keys())

        # Detect added columns.
        for added in sorted(current_names - baseline_names):
            is_not_null = current_columns[added].get("is_nullable", "YES").upper() == "NO"
            severity = SEVERITY_MEDIUM if is_not_null else SEVERITY_LOW
            changes.append({
                "change_type": "column_added",
                "column": added,
                "new_type": current_columns[added]["data_type"],
                "is_nullable": current_columns[added].get("is_nullable", "YES"),
                "severity": severity,
            })

        # Detect removed columns.
        for removed in sorted(baseline_names - current_names):
            col_info = baseline[removed]
            is_pk = col_info.get("is_primary_key", False)
            is_fk = col_info.get("is_foreign_key", False)
            nullable_val = col_info.get("is_nullable")
            is_not_null = nullable_val.upper() == "NO" if nullable_val else False

            if is_pk or is_fk:
                severity = SEVERITY_CRITICAL
            elif is_not_null:
                severity = SEVERITY_HIGH
            else:
                severity = SEVERITY_MEDIUM

            changes.append({
                "change_type": "column_removed",
                "column": removed,
                "old_type": col_info["data_type"],
                "is_primary_key": is_pk,
                "is_foreign_key": is_fk,
                "severity": severity,
            })

        # Detect suspected renames: one-to-one best-match between
        # added and removed columns with compatible types.
        added_names = sorted(current_names - baseline_names)
        removed_names = sorted(baseline_names - current_names)
        if added_names and removed_names:
            # Build candidate pairs (removed, added) with compatible types
            candidates = []
            for rm in removed_names:
                rm_type = baseline[rm]["data_type"]
                for ad in added_names:
                    ad_type = current_columns[ad]["data_type"]
                    if rm_type != ad_type:
                        continue
                    sim = column_name_similarity(rm, ad)
                    if sim >= self.rename_similarity_threshold:
                        candidates.append((sim, rm, ad))

            # Greedy one-to-one matching: highest similarity first
            candidates.sort(reverse=True, key=lambda x: x[0])
            used_removed: set = set()
            used_added: set = set()
            for sim, rm, ad in candidates:
                if rm in used_removed or ad in used_added:
                    continue
                used_removed.add(rm)
                used_added.add(ad)
                changes.append({
                    "change_type": "suspected_rename",
                    "old_column": rm,
                    "new_column": ad,
                    "data_type": baseline[rm]["data_type"],
                    "similarity": round(sim, 3),
                    "severity": SEVERITY_LOW,
                })

        # Detect type changes on existing columns.
        for col in sorted(baseline_names & current_names):
            old_type = baseline[col]["data_type"]
            new_type = current_columns[col]["data_type"]
            if old_type != new_type:
                is_pk = baseline[col].get("is_primary_key", False)
                is_fk = baseline[col].get("is_foreign_key", False)

                if is_pk or is_fk:
                    severity = SEVERITY_CRITICAL
                else:
                    severity = _classify_type_change_severity(old_type, new_type)

                changes.append({
                    "change_type": "type_changed",
                    "column": col,
                    "old_type": old_type,
                    "new_type": new_type,
                    "is_primary_key": is_pk,
                    "is_foreign_key": is_fk,
                    "severity": severity,
                })

            # Detect nullable changes (only if baseline explicitly has is_nullable)
            old_nullable_raw = baseline[col].get("is_nullable")
            new_nullable_raw = current_columns[col].get("is_nullable")
            if old_nullable_raw and new_nullable_raw:
                old_nullable = old_nullable_raw.upper()
                new_nullable = new_nullable_raw.upper()
            else:
                old_nullable = None
                new_nullable = None
            if old_nullable and new_nullable and old_nullable != new_nullable:
                if new_nullable == "YES":
                    # Column became nullable — could affect NOT NULL constraints
                    severity = SEVERITY_MEDIUM
                else:
                    # Column became NOT NULL — stricter, usually intentional
                    severity = SEVERITY_LOW
                changes.append({
                    "change_type": "nullable_changed",
                    "column": col,
                    "old_nullable": old_nullable,
                    "new_nullable": new_nullable,
                    "severity": severity,
                })

        if not changes:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message="Schema matches baseline. No changes detected.",
                details={
                    "column_count": len(current_columns),
                    "explanation": "No schema changes detected vs baseline.",
                },
            )

        # Determine overall severity (highest among all changes)
        max_severity = max(
            changes, key=lambda c: _SEVERITY_ORDER.get(c.get("severity", SEVERITY_INFO), 0)
        ).get("severity", SEVERITY_INFO)

        # Determine status based on severity or legacy boolean flags
        if self.min_severity:
            # New severity-based evaluation
            should_fail = (
                _SEVERITY_ORDER.get(max_severity, 0)
                >= _SEVERITY_ORDER.get(self.min_severity, 0)
            )
        else:
            # Legacy boolean flag evaluation
            has_removed = any(c["change_type"] == "column_removed" for c in changes)
            has_type_change = any(c["change_type"] == "type_changed" for c in changes)
            has_added = any(c["change_type"] == "column_added" for c in changes)

            should_fail = (
                (has_removed and self.fail_on_removed)
                or (has_type_change and self.fail_on_type_change)
                or (has_added and self.fail_on_added)
            )

        status = MonitorStatus.FAIL if should_fail else MonitorStatus.WARN

        # Build summary
        summary_parts = []
        by_type: Dict[str, int] = {}
        for c in changes:
            ct = c["change_type"]
            by_type[ct] = by_type.get(ct, 0) + 1
        if by_type.get("column_removed"):
            summary_parts.append(f"{by_type['column_removed']} column(s) removed")
        if by_type.get("column_added"):
            summary_parts.append(f"{by_type['column_added']} column(s) added")
        if by_type.get("type_changed"):
            summary_parts.append(f"{by_type['type_changed']} type change(s)")
        if by_type.get("nullable_changed"):
            summary_parts.append(f"{by_type['nullable_changed']} nullable change(s)")
        if by_type.get("suspected_rename"):
            summary_parts.append(f"{by_type['suspected_rename']} suspected rename(s)")

        # Count by severity for explanation
        severity_counts: Dict[str, int] = {}
        for c in changes:
            sev = c.get("severity", SEVERITY_INFO)
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target_fqn,
            status=status,
            message=f"Schema changes detected: {', '.join(summary_parts)}. Max severity: {max_severity}.",
            details={
                "changes": changes,
                "change_count": len(changes),
                "max_severity": max_severity,
                "severity_counts": severity_counts,
                "baseline_column_count": len(baseline),
                "current_column_count": len(current_columns),
                "explanation": (
                    f"{len(changes)} schema change(s) detected. "
                    f"Highest severity: {max_severity}. "
                    f"Breakdown: {', '.join(f'{v} {k}' for k, v in severity_counts.items())}."
                ),
            },
        )

    def _evaluate_type_validation(
        self,
        query_results: List[Dict[str, Any]],
        target_fqn: str,
    ) -> MonitorResult:
        """Validate column data types against expected_types mapping.

        Used when mode="type_validation" (Data Type Validation monitor).
        """
        monitor_type_label = "data_type_validation"

        if not query_results:
            return MonitorResult(
                monitor_type=monitor_type_label,
                target_fqn=target_fqn,
                status=MonitorStatus.ERROR,
                message="No columns found — table may not exist.",
            )

        current_columns = {
            row["column_name"].lower(): self._normalize_type(
                row.get("data_type", "")
            )
            for row in query_results
        }

        # First-run / no expected types: snapshot current types as baseline
        if not self.expected_types:
            return MonitorResult(
                monitor_type=monitor_type_label,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message=(
                    f"Data type baseline established with "
                    f"{len(current_columns)} columns."
                ),
                details={
                    "column_count": len(current_columns),
                    "current_types": current_columns,
                    "is_baseline_run": True,
                },
            )

        # Compare current types against expected
        mismatches: List[Dict[str, Any]] = []
        missing_columns: List[str] = []

        for col_name, expected_type in self.expected_types.items():
            col_lower = col_name.lower()
            normalized_expected = self._normalize_type(expected_type)
            actual_type = current_columns.get(col_lower)

            if actual_type is None:
                missing_columns.append(col_name)
                continue

            if actual_type != normalized_expected:
                mismatches.append({
                    "column": col_name,
                    "expected_type": normalized_expected,
                    "actual_type": actual_type,
                })

        details: Dict[str, Any] = {
            "mismatches": mismatches,
            "missing_columns": missing_columns,
            "checked_columns": len(self.expected_types),
            "current_column_count": len(current_columns),
        }

        if not mismatches and not missing_columns:
            return MonitorResult(
                monitor_type=monitor_type_label,
                target_fqn=target_fqn,
                status=MonitorStatus.PASS,
                message=(
                    f"Data type validation passed: all "
                    f"{len(self.expected_types)} column types match."
                ),
                details=details,
            )

        issues = []
        if mismatches:
            cols = ", ".join(
                f"{m['column']} (expected {m['expected_type']}, "
                f"got {m['actual_type']})"
                for m in mismatches
            )
            issues.append(f"{len(mismatches)} type mismatch(es): {cols}")
        if missing_columns:
            issues.append(
                f"{len(missing_columns)} expected column(s) missing: "
                f"{', '.join(missing_columns)}"
            )

        return MonitorResult(
            monitor_type=monitor_type_label,
            target_fqn=target_fqn,
            status=MonitorStatus.FAIL,
            message=f"Data type validation failed: {'; '.join(issues)}.",
            details=details,
        )


def _classify_type_change_severity(old_type: str, new_type: str) -> str:
    """Classify the severity of a type change.

    Type widening (int → bigint) is lower severity than
    type narrowing (bigint → int) which risks data loss.
    """
    old_width = _TYPE_WIDTH.get(old_type)
    new_width = _TYPE_WIDTH.get(new_type)

    if old_width is not None and new_width is not None:
        if new_width >= old_width:
            return SEVERITY_LOW  # Widening — safe
        else:
            return SEVERITY_HIGH  # Narrowing — data loss risk

    # Unknown type mapping — default to medium
    return SEVERITY_MEDIUM
