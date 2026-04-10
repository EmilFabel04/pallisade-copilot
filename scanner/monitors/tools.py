"""
Tool monitors.

Non-SQL monitors that query external tool APIs (Fivetran, Airflow, dbt Cloud)
for pipeline health status. Each monitor class accepts a tool integration
client and returns a MonitorResult.

Follows the same pattern as infrastructure.py:
- Registry mapping type strings to classes
- Each class has __init__(config) and execute(client) -> MonitorResult
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import MonitorResult, MonitorStatus

import structlog

logger = structlog.get_logger()

# Tool monitor types (not SQL-based, not SSH-based)
TOOL_MONITOR_TYPES = {
    "sync_lag", "failed_syncs", "connector_schema_drift",
    "dag_last_run", "dag_schedule_lag", "task_failure_rate",
    "dbt_test_failures", "dbt_model_freshness", "dbt_source_freshness",
    "query_performance", "cost_anomaly", "storage_growth",
}


# =============================================================================
# FIVETRAN MONITORS
# =============================================================================


class SyncLagMonitor:
    """Monitors Fivetran connector sync freshness.

    Config keys:
        connector_id : str (REQUIRED)
            Fivetran connector ID to monitor.
        max_lag_minutes : int | None
            Maximum acceptable minutes since last successful sync.
            If None, auto-derived from connector's sync_frequency.
        warn_multiplier : float
            Multiplier on sync frequency for WARN threshold (default: 1.5).
        fail_multiplier : float
            Multiplier on sync frequency for FAIL threshold (default: 3.0).
    """

    monitor_type = "sync_lag"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.connector_id: str = str(self.config.get("connector_id", ""))
        self.max_lag_minutes: Optional[int] = self.config.get("max_lag_minutes")
        self.warn_multiplier: float = float(self.config.get("warn_multiplier", 1.5))
        self.fail_multiplier: float = float(self.config.get("fail_multiplier", 3.0))

    def execute(self, integration: Any) -> MonitorResult:
        """Check Fivetran connector sync lag."""
        target = f"fivetran:{self.connector_id}"

        if not self.connector_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No connector_id configured.",
            )

        try:
            connector = integration.get_connector(self.connector_id)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch connector: {e}",
            )

        if not connector:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Connector {self.connector_id} not found.",
            )

        target = f"fivetran:{connector.name or self.connector_id}"

        # Check connector health
        from scanner.integrations.fivetran import ConnectorStatus

        if connector.status == ConnectorStatus.BROKEN:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"Connector '{connector.name}' is BROKEN.",
                details={
                    "connector_id": self.connector_id,
                    "connector_status": connector.status.value,
                    "service": connector.service,
                    "failed_at": connector.failed_at.isoformat() if connector.failed_at else None,
                },
            )

        if connector.paused:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"Connector '{connector.name}' is PAUSED.",
                details={
                    "connector_id": self.connector_id,
                    "connector_status": "paused",
                    "service": connector.service,
                },
            )

        # Calculate lag
        hours_since = connector.hours_since_success
        if hours_since is None:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"Connector '{connector.name}' has never successfully synced.",
                details={
                    "connector_id": self.connector_id,
                    "service": connector.service,
                },
            )

        minutes_since = hours_since * 60
        sync_freq_minutes = connector.sync_frequency  # Already in minutes

        # Determine thresholds
        if self.max_lag_minutes:
            warn_threshold = float(self.max_lag_minutes)
            fail_threshold = float(self.max_lag_minutes) * 2
        else:
            warn_threshold = sync_freq_minutes * self.warn_multiplier
            fail_threshold = sync_freq_minutes * self.fail_multiplier

        details = {
            "connector_id": self.connector_id,
            "connector_name": connector.name,
            "service": connector.service,
            "minutes_since_sync": round(minutes_since, 1),
            "sync_frequency_minutes": sync_freq_minutes,
            "warn_threshold_minutes": round(warn_threshold, 1),
            "fail_threshold_minutes": round(fail_threshold, 1),
            "succeeded_at": connector.succeeded_at.isoformat() if connector.succeeded_at else None,
        }

        if minutes_since > fail_threshold:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=round(minutes_since, 1),
                threshold=round(fail_threshold, 1),
                message=(
                    f"Connector '{connector.name}' sync lag: {minutes_since:.0f} min "
                    f"(threshold: {fail_threshold:.0f} min, frequency: {sync_freq_minutes} min)."
                ),
                details=details,
            )

        if minutes_since > warn_threshold:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=round(minutes_since, 1),
                threshold=round(warn_threshold, 1),
                message=(
                    f"Connector '{connector.name}' sync slightly delayed: "
                    f"{minutes_since:.0f} min since last sync (warn at {warn_threshold:.0f} min)."
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=round(minutes_since, 1),
            message=(
                f"Connector '{connector.name}' synced {minutes_since:.0f} min ago "
                f"(frequency: {sync_freq_minutes} min)."
            ),
            details=details,
        )


class FailedSyncsMonitor:
    """Monitors Fivetran connector for recent sync failures."""

    monitor_type = "failed_syncs"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.connector_id: str = str(self.config.get("connector_id", ""))
        self.lookback_hours: int = int(self.config.get("lookback_hours", 24))

    def execute(self, integration: Any) -> MonitorResult:
        target = f"fivetran:{self.connector_id}"

        if not self.connector_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No connector_id configured.",
            )

        try:
            health = integration.analyze_connector_health(self.connector_id)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to analyze connector health: {e}",
            )

        status_str = health.get("status", "unknown")
        issues = health.get("issues", [])

        details = {
            "connector_id": self.connector_id,
            "health_status": status_str,
            "issues": issues,
            "lookback_hours": self.lookback_hours,
        }

        if status_str == "not_found":
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Connector '{self.connector_id}' not found. Check the connector_id in the task config.",
                details=details,
            )

        if status_str == "critical":
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"Connector has critical issues: {'; '.join(issues[:3])}",
                details=details,
            )

        if status_str == "warning":
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                message=f"Connector has warnings: {'; '.join(issues[:3])}",
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            message="No recent sync failures.",
            details=details,
        )


class ConnectorSchemaDriftMonitor:
    """Monitors Fivetran/Airbyte connector schemas for drift over time.

    On the first run, captures a baseline snapshot of tables and columns.
    On subsequent runs, compares the current schema against the baseline
    and reports added/removed tables and columns.

    Config keys:
        connector_id : str (REQUIRED)
            Fivetran/Airbyte connector ID to monitor.
        baseline_schema : dict | None
            Previously captured snapshot in the form
            ``{"tables": {table_name: [column, ...]}}``.  Injected by
            the scheduler from the most recent run's persisted details.
            When absent, this run captures the baseline and returns PASS.
        fail_on_removal : bool
            Treat removed tables or columns as FAIL (default: True).
            Additions alone trigger WARN.
    """

    monitor_type = "connector_schema_drift"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.connector_id: str = str(self.config.get("connector_id", ""))
        self.baseline_schema: Optional[Dict[str, Any]] = self.config.get("baseline_schema")
        self.fail_on_removal: bool = bool(self.config.get("fail_on_removal", True))

    @staticmethod
    def _snapshot_from_schema_info(schema_info: Dict[str, Any]) -> Dict[str, List[str]]:
        """Normalize a connector schema response into {table: [columns]}."""
        tables_raw = schema_info.get("tables") or {}
        snapshot: Dict[str, List[str]] = {}
        for table_name, table_def in tables_raw.items():
            cols: List[str] = []
            if isinstance(table_def, dict):
                columns = table_def.get("columns") or {}
                if isinstance(columns, dict):
                    cols = sorted(columns.keys())
                elif isinstance(columns, list):
                    cols = sorted(
                        str(c.get("name") if isinstance(c, dict) else c)
                        for c in columns
                        if c
                    )
            snapshot[str(table_name)] = cols
        return snapshot

    def execute(self, integration: Any) -> MonitorResult:
        target = f"fivetran:{self.connector_id}"

        if not self.connector_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No connector_id configured.",
            )

        try:
            schema_info = integration.get_connector_schema(self.connector_id)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch connector schema: {e}",
            )

        current_snapshot = self._snapshot_from_schema_info(schema_info)
        current_tables = set(current_snapshot.keys())

        # First run — capture baseline. The scheduler persists details
        # so subsequent runs can load baseline_schema via config injection.
        if not self.baseline_schema or not isinstance(self.baseline_schema, dict):
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                value=float(len(current_snapshot)),
                message=(
                    f"Baseline captured: {len(current_snapshot)} table(s). "
                    f"Future runs will detect drift against this snapshot."
                ),
                details={
                    "connector_id": self.connector_id,
                    "baseline_captured": True,
                    "total_tables": len(current_snapshot),
                    "schema_snapshot": current_snapshot,
                },
            )

        baseline_tables_raw = self.baseline_schema.get("tables") or {}
        baseline_snapshot: Dict[str, List[str]] = {
            str(k): list(v) if isinstance(v, list) else []
            for k, v in baseline_tables_raw.items()
        }
        baseline_tables = set(baseline_snapshot.keys())

        added_tables = sorted(current_tables - baseline_tables)
        removed_tables = sorted(baseline_tables - current_tables)

        added_columns: Dict[str, List[str]] = {}
        removed_columns: Dict[str, List[str]] = {}
        for tbl in current_tables & baseline_tables:
            before = set(baseline_snapshot.get(tbl, []))
            after = set(current_snapshot.get(tbl, []))
            added = sorted(after - before)
            removed = sorted(before - after)
            if added:
                added_columns[tbl] = added
            if removed:
                removed_columns[tbl] = removed

        total_changes = (
            len(added_tables)
            + len(removed_tables)
            + sum(len(v) for v in added_columns.values())
            + sum(len(v) for v in removed_columns.values())
        )

        details: Dict[str, Any] = {
            "connector_id": self.connector_id,
            "total_tables": len(current_snapshot),
            "baseline_table_count": len(baseline_snapshot),
            "added_tables": added_tables,
            "removed_tables": removed_tables,
            "added_columns": added_columns,
            "removed_columns": removed_columns,
            "total_changes": total_changes,
            # Always emit current snapshot so the scheduler can persist it
            # as the new baseline for the next run.
            "schema_snapshot": current_snapshot,
        }

        if total_changes == 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                value=0.0,
                message=(
                    f"No schema drift detected across {len(current_snapshot)} table(s)."
                ),
                details=details,
            )

        has_removals = bool(removed_tables or removed_columns)
        status = (
            MonitorStatus.FAIL
            if has_removals and self.fail_on_removal
            else MonitorStatus.WARN
        )

        summary_parts: List[str] = []
        if added_tables:
            summary_parts.append(f"{len(added_tables)} table(s) added")
        if removed_tables:
            summary_parts.append(f"{len(removed_tables)} table(s) removed")
        if added_columns:
            col_count = sum(len(v) for v in added_columns.values())
            summary_parts.append(f"{col_count} column(s) added in {len(added_columns)} table(s)")
        if removed_columns:
            col_count = sum(len(v) for v in removed_columns.values())
            summary_parts.append(f"{col_count} column(s) removed from {len(removed_columns)} table(s)")

        message = "Schema drift detected: " + ", ".join(summary_parts) + "."

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=status,
            value=float(total_changes),
            message=message,
            details=details,
        )


# =============================================================================
# AIRFLOW MONITORS
# =============================================================================


class DagLastRunMonitor:
    """Monitors Airflow DAG last run status.

    Config keys:
        dag_id : str (REQUIRED)
            Airflow DAG ID to monitor.
        max_stale_hours : float | None
            Maximum hours since last successful run.
            If None, auto-derived from DAG schedule.
    """

    monitor_type = "dag_last_run"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.dag_id: str = str(self.config.get("dag_id", ""))
        self.max_stale_hours: Optional[float] = self.config.get("max_stale_hours")

    def execute(self, integration: Any) -> MonitorResult:
        target = f"airflow:{self.dag_id}"

        if not self.dag_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No dag_id configured.",
            )

        try:
            runs = integration.get_dag_runs(self.dag_id, limit=5)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch DAG runs: {e}",
            )

        if not runs:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                message=f"No runs found for DAG '{self.dag_id}'.",
                details={"dag_id": self.dag_id},
            )

        latest_run = runs[0]

        from scanner.integrations.airflow import DAGState

        details: Dict[str, Any] = {
            "dag_id": self.dag_id,
            "run_id": latest_run.run_id,
            "state": latest_run.state.value if hasattr(latest_run.state, "value") else str(latest_run.state),
            "execution_date": latest_run.execution_date.isoformat() if latest_run.execution_date else None,
        }

        # Check if latest run failed
        if latest_run.state == DAGState.FAILED:
            # Try to get failed task info
            try:
                tasks = integration.get_task_instances(self.dag_id, latest_run.run_id)
                failed_tasks = [t for t in tasks if hasattr(t, "is_failed") and t.is_failed]
                details["failed_tasks"] = [
                    {"task_id": t.task_id, "state": t.state.value if hasattr(t.state, "value") else str(t.state)}
                    for t in failed_tasks[:5]
                ]
            except Exception:
                pass

            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"DAG '{self.dag_id}' last run FAILED (run: {latest_run.run_id}).",
                details=details,
            )

        # Check if still running
        if latest_run.state == DAGState.RUNNING:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                message=f"DAG '{self.dag_id}' is currently running.",
                details=details,
            )

        # Check staleness (if succeeded)
        if latest_run.state == DAGState.SUCCESS:
            run_end = getattr(latest_run, "end_date", None) or getattr(latest_run, "start_date", None)
            if run_end:
                now = datetime.now(timezone.utc)
                if run_end.tzinfo is None:
                    run_end = run_end.replace(tzinfo=timezone.utc)
                hours_since = (now - run_end).total_seconds() / 3600
                details["hours_since_success"] = round(hours_since, 1)

                stale_threshold = self.max_stale_hours
                if stale_threshold and hours_since > stale_threshold:
                    return MonitorResult(
                        monitor_type=self.monitor_type,
                        target_fqn=target,
                        status=MonitorStatus.WARN,
                        value=round(hours_since, 1),
                        threshold=stale_threshold,
                        message=(
                            f"DAG '{self.dag_id}' last succeeded {hours_since:.1f}h ago "
                            f"(threshold: {stale_threshold}h)."
                        ),
                        details=details,
                    )

            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                message=f"DAG '{self.dag_id}' last run succeeded.",
                details=details,
            )

        # Queued or other states
        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            message=f"DAG '{self.dag_id}' is in state: {details['state']}.",
            details=details,
        )


class DagScheduleLagMonitor:
    """Monitors Airflow DAG schedule lag."""

    monitor_type = "dag_schedule_lag"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.dag_id: str = str(self.config.get("dag_id", ""))
        self.max_lag_minutes: int = int(self.config.get("max_lag_minutes", 30))

    def execute(self, integration: Any) -> MonitorResult:
        target = f"airflow:{self.dag_id}"

        if not self.dag_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No dag_id configured.",
            )

        try:
            runs = integration.get_dag_runs(self.dag_id, limit=5)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch DAG runs: {e}",
            )

        if not runs:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                message=f"No runs found for DAG '{self.dag_id}'.",
                details={"dag_id": self.dag_id},
            )

        latest = runs[0]
        execution_date = latest.execution_date
        start_date = getattr(latest, "start_date", None)

        details: Dict[str, Any] = {
            "dag_id": self.dag_id,
            "run_id": latest.run_id,
        }

        if execution_date and start_date:
            if execution_date.tzinfo is None:
                execution_date = execution_date.replace(tzinfo=timezone.utc)
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            lag_minutes = (start_date - execution_date).total_seconds() / 60
            details["lag_minutes"] = round(lag_minutes, 1)

            if lag_minutes > self.max_lag_minutes:
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target,
                    status=MonitorStatus.FAIL,
                    value=round(lag_minutes, 1),
                    threshold=float(self.max_lag_minutes),
                    message=(
                        f"DAG '{self.dag_id}' schedule lag: {lag_minutes:.0f} min "
                        f"(threshold: {self.max_lag_minutes} min)."
                    ),
                    details=details,
                )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            message=f"DAG '{self.dag_id}' is on schedule.",
            details=details,
        )


class TaskFailureRateMonitor:
    """Monitors Airflow task failure rate."""

    monitor_type = "task_failure_rate"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.dag_id: str = str(self.config.get("dag_id", ""))
        self.max_failure_pct: float = float(self.config.get("max_failure_pct", 10))
        self.lookback_hours: int = int(self.config.get("lookback_hours", 24))

    def execute(self, integration: Any) -> MonitorResult:
        target = f"airflow:{self.dag_id}"

        if not self.dag_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No dag_id configured.",
            )

        try:
            runs = integration.get_dag_runs(self.dag_id, limit=20)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch DAG runs: {e}",
            )

        from scanner.integrations.airflow import DAGState

        # Filter to recent runs within lookback window
        cutoff = datetime.now(timezone.utc).timestamp() - (self.lookback_hours * 3600)
        recent = []
        for r in runs:
            run_date = getattr(r, "start_date", None) or r.execution_date
            if run_date:
                if run_date.tzinfo is None:
                    run_date = run_date.replace(tzinfo=timezone.utc)
                if run_date.timestamp() >= cutoff:
                    recent.append(r)

        if not recent:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                message=f"No runs in the last {self.lookback_hours}h for DAG '{self.dag_id}'.",
                details={"dag_id": self.dag_id, "lookback_hours": self.lookback_hours},
            )

        failed = sum(1 for r in recent if r.state == DAGState.FAILED)
        rate = (failed / len(recent)) * 100

        details: Dict[str, Any] = {
            "dag_id": self.dag_id,
            "total_runs": len(recent),
            "failed_runs": failed,
            "failure_rate_pct": round(rate, 1),
            "lookback_hours": self.lookback_hours,
        }

        if rate > self.max_failure_pct:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=round(rate, 1),
                threshold=self.max_failure_pct,
                message=(
                    f"DAG '{self.dag_id}' failure rate: {rate:.1f}% "
                    f"({failed}/{len(recent)} runs failed in {self.lookback_hours}h)."
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=round(rate, 1),
            message=(
                f"DAG '{self.dag_id}' failure rate: {rate:.1f}% "
                f"({failed}/{len(recent)} in {self.lookback_hours}h)."
            ),
            details=details,
        )


# =============================================================================
# DBT MONITORS
# =============================================================================


class DbtTestFailuresMonitor:
    """Monitors dbt Cloud job test results.

    Config keys:
        job_id : int (REQUIRED)
            dbt Cloud job ID to monitor.
        include_warnings : bool
            Whether warnings count as failures (default: False).
    """

    monitor_type = "dbt_test_failures"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.job_id: Optional[int] = self.config.get("job_id")
        if self.job_id is not None:
            self.job_id = int(self.job_id)
        self.include_warnings: bool = self.config.get("include_warnings", False)

    def execute(self, client: Any) -> MonitorResult:
        target = f"dbt:job/{self.job_id}" if self.job_id else "dbt:unknown"

        if not self.job_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No job_id configured.",
            )

        # Get latest run for this job
        try:
            runs = client.get_job_runs(self.job_id, limit=1)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch job runs: {e}",
            )

        if not runs:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                message=f"No runs found for dbt job {self.job_id}.",
                details={"job_id": self.job_id},
            )

        latest_run = runs[0]
        run_id = latest_run.get("id")
        run_status_code = latest_run.get("status")
        run_status_human = latest_run.get("status_humanized", "unknown")

        details: Dict[str, Any] = {
            "job_id": self.job_id,
            "run_id": run_id,
            "run_status": run_status_human,
            "started_at": latest_run.get("started_at"),
            "finished_at": latest_run.get("finished_at"),
        }

        # Status 20 = Error in dbt Cloud
        if run_status_code == 20:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"dbt job {self.job_id} run #{run_id} failed: {run_status_human}.",
                details={
                    **details,
                    "error_message": latest_run.get("status_message"),
                },
            )

        # Status 3 = Running
        if run_status_code == 3:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                message=f"dbt job {self.job_id} is currently running.",
                details=details,
            )

        # Run completed — fetch test results
        try:
            test_results = client.get_test_results(run_id)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch test results for run {run_id}: {e}",
                details=details,
            )

        failed = test_results.get("failed", 0)
        warned = test_results.get("warned", 0)
        skipped = test_results.get("skipped", 0)
        passed = test_results.get("passed", 0)
        total = test_results.get("total_tests", 0)

        details.update({
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "skipped": skipped,
            "failing_tests": [
                t for t in test_results.get("tests", [])
                if t.get("status") == "fail"
            ][:10],
        })

        if failed > 0:
            failing_names = [
                t.get("name", "unknown")
                for t in test_results.get("tests", [])
                if t.get("status") == "fail"
            ][:5]
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=float(failed),
                message=(
                    f"{failed}/{total} dbt tests failed in job {self.job_id}: "
                    f"{', '.join(failing_names)}"
                ),
                details=details,
            )

        if self.include_warnings and warned > 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=float(warned),
                message=f"{warned}/{total} dbt tests have warnings in job {self.job_id}.",
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=0.0,
            message=f"All {total} dbt tests passed in job {self.job_id}.",
            details=details,
        )


class DbtModelFreshnessMonitor:
    """Monitors dbt Cloud job run freshness."""

    monitor_type = "dbt_model_freshness"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.job_id: Optional[int] = self.config.get("job_id")
        if self.job_id is not None:
            self.job_id = int(self.job_id)
        self.max_hours: float = float(self.config.get("max_hours", 24))

    def execute(self, client: Any) -> MonitorResult:
        target = f"dbt:job/{self.job_id}" if self.job_id else "dbt:unknown"

        if not self.job_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No job_id configured.",
            )

        try:
            runs = client.get_job_runs(self.job_id, limit=1)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch job runs: {e}",
            )

        if not runs:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                message=f"No runs found for dbt job {self.job_id}.",
            )

        latest = runs[0]
        finished = latest.get("finished_at")

        details: Dict[str, Any] = {
            "job_id": self.job_id,
            "run_id": latest.get("id"),
            "finished_at": finished,
        }

        if finished:
            try:
                finished_dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                hours_since = (datetime.now(timezone.utc) - finished_dt).total_seconds() / 3600
                details["hours_since_run"] = round(hours_since, 1)

                if hours_since > self.max_hours:
                    return MonitorResult(
                        monitor_type=self.monitor_type,
                        target_fqn=target,
                        status=MonitorStatus.FAIL,
                        value=round(hours_since, 1),
                        threshold=self.max_hours,
                        message=(
                            f"dbt job {self.job_id} last ran {hours_since:.1f}h ago "
                            f"(threshold: {self.max_hours}h)."
                        ),
                        details=details,
                    )
            except (ValueError, TypeError):
                pass

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            message=f"dbt job {self.job_id} is fresh.",
            details=details,
        )


class DbtSourceFreshnessMonitor:
    """Monitors dbt source freshness from latest run."""

    monitor_type = "dbt_source_freshness"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.job_id: Optional[int] = self.config.get("job_id")
        if self.job_id is not None:
            self.job_id = int(self.job_id)

    def execute(self, client: Any) -> MonitorResult:
        target = f"dbt:job/{self.job_id}" if self.job_id else "dbt:unknown"

        if not self.job_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No job_id configured.",
            )

        try:
            runs = client.get_job_runs(self.job_id, limit=1)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch job runs: {e}",
            )

        if not runs:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                message=f"No runs found for dbt job {self.job_id}.",
            )

        latest = runs[0]
        run_id = latest.get("id")

        # Try to fetch source freshness artifact
        try:
            artifact = client.get_run_artifact(run_id, "sources.json")
            sources = artifact.get("results", [])
            stale = [s for s in sources if s.get("status") == "error"]

            details: Dict[str, Any] = {
                "job_id": self.job_id,
                "run_id": run_id,
                "total_sources": len(sources),
                "stale_sources": len(stale),
            }

            if stale:
                names = [s.get("unique_id", "unknown").split(".")[-1] for s in stale[:5]]
                return MonitorResult(
                    monitor_type=self.monitor_type,
                    target_fqn=target,
                    status=MonitorStatus.FAIL,
                    value=float(len(stale)),
                    message=f"{len(stale)} stale source(s): {', '.join(names)}",
                    details=details,
                )

            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                message=f"All {len(sources)} sources are fresh.",
                details=details,
            )

        except Exception:
            # sources.json not available (not all jobs run source freshness)
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                message=f"No source freshness data available for run {run_id}.",
                details={"job_id": self.job_id, "run_id": run_id},
            )


# =============================================================================
# WAREHOUSE OPS MONITORS
# =============================================================================


class QueryPerformanceMonitor:
    """Monitors warehouse query performance and timeouts.

    Queries INFORMATION_SCHEMA or equivalent to detect slow queries,
    timeouts, and queue congestion.

    Config keys:
        query_time_threshold_seconds : int
            Maximum acceptable average query time (default: 300).
        lookback_hours : int
            How far back to analyze queries (default: 24).
    """

    monitor_type = "query_performance"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.threshold_seconds: int = int(self.config.get("query_time_threshold_seconds", 300))
        self.lookback_hours: int = int(self.config.get("lookback_hours", 24))

    def execute(self, adapter: Any) -> MonitorResult:
        target = f"warehouse:{getattr(adapter, 'warehouse_type', 'unknown')}"

        try:
            # Adapter should expose query_performance_stats(lookback_hours)
            # returning {"avg_duration_seconds", "max_duration_seconds",
            #            "total_queries", "failed_queries", "timed_out_queries"}
            stats = adapter.query_performance_stats(self.lookback_hours)
        except AttributeError:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="Warehouse adapter does not support query performance monitoring.",
            )
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch query performance stats: {e}",
            )

        avg_duration = stats.get("avg_duration_seconds", 0)
        timed_out = stats.get("timed_out_queries", 0)
        total = stats.get("total_queries", 0)

        details = {
            "avg_duration_seconds": round(avg_duration, 1),
            "max_duration_seconds": stats.get("max_duration_seconds"),
            "total_queries": total,
            "failed_queries": stats.get("failed_queries", 0),
            "timed_out_queries": timed_out,
            "lookback_hours": self.lookback_hours,
            "threshold_seconds": self.threshold_seconds,
        }

        if timed_out > 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=float(timed_out),
                message=f"{timed_out} queries timed out in the last {self.lookback_hours}h.",
                details=details,
            )

        if avg_duration > self.threshold_seconds:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=round(avg_duration, 1),
                threshold=float(self.threshold_seconds),
                message=(
                    f"Average query time {avg_duration:.0f}s exceeds threshold "
                    f"({self.threshold_seconds}s) over {self.lookback_hours}h."
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=round(avg_duration, 1),
            message=f"Query performance healthy: avg {avg_duration:.0f}s across {total} queries.",
            details=details,
        )


class CostAnomalyMonitor:
    """Monitors warehouse cost for anomalous spikes.

    Compares recent daily cost against a rolling average to detect
    unexpected spend increases.

    Config keys:
        cost_spike_multiplier : float
            WARN if daily cost > multiplier * rolling avg (default: 1.5).
        lookback_days : int
            Rolling average window (default: 7).
    """

    monitor_type = "cost_anomaly"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.spike_multiplier: float = float(self.config.get("cost_spike_multiplier", 1.5))
        self.lookback_days: int = int(self.config.get("lookback_days", 7))

    def execute(self, adapter: Any) -> MonitorResult:
        target = f"warehouse:{getattr(adapter, 'warehouse_type', 'unknown')}"

        try:
            # Adapter should expose cost_stats(lookback_days)
            # returning {"daily_costs": [float], "today_cost": float,
            #            "rolling_avg": float, "currency": str}
            stats = adapter.cost_stats(self.lookback_days)
        except AttributeError:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="Warehouse adapter does not support cost monitoring.",
            )
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch cost stats: {e}",
            )

        today_cost = stats.get("today_cost", 0)
        rolling_avg = stats.get("rolling_avg", 0)
        currency = stats.get("currency", "USD")

        details = {
            "today_cost": round(today_cost, 2),
            "rolling_avg": round(rolling_avg, 2),
            "spike_multiplier": self.spike_multiplier,
            "lookback_days": self.lookback_days,
            "currency": currency,
        }

        if rolling_avg > 0 and today_cost > rolling_avg * 3:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=round(today_cost, 2),
                threshold=round(rolling_avg * 3, 2),
                message=(
                    f"Cost spike: {currency} {today_cost:.2f} today vs "
                    f"{currency} {rolling_avg:.2f} avg (>{3}x)."
                ),
                details=details,
            )

        if rolling_avg > 0 and today_cost > rolling_avg * self.spike_multiplier:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=round(today_cost, 2),
                threshold=round(rolling_avg * self.spike_multiplier, 2),
                message=(
                    f"Cost elevated: {currency} {today_cost:.2f} today vs "
                    f"{currency} {rolling_avg:.2f} avg (>{self.spike_multiplier}x)."
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=round(today_cost, 2),
            message=f"Cost normal: {currency} {today_cost:.2f} today (avg {currency} {rolling_avg:.2f}).",
            details=details,
        )


class StorageGrowthMonitor:
    """Monitors warehouse storage growth rate.

    Detects abnormally fast storage growth that may indicate
    runaway ETL jobs or missing cleanup.

    Config keys:
        growth_rate_multiplier : float
            WARN if growth > multiplier * normal rate (default: 2.0).
        lookback_days : int
            Window for measuring growth trend (default: 30).
    """

    monitor_type = "storage_growth"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.growth_multiplier: float = float(self.config.get("growth_rate_multiplier", 2.0))
        self.lookback_days: int = int(self.config.get("lookback_days", 30))

    def execute(self, adapter: Any) -> MonitorResult:
        target = f"warehouse:{getattr(adapter, 'warehouse_type', 'unknown')}"

        try:
            # Adapter should expose storage_stats(lookback_days)
            # returning {"current_bytes", "previous_bytes", "growth_bytes",
            #            "avg_daily_growth_bytes", "recent_daily_growth_bytes"}
            stats = adapter.storage_stats(self.lookback_days)
        except AttributeError:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="Warehouse adapter does not support storage monitoring.",
            )
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch storage stats: {e}",
            )

        avg_daily = stats.get("avg_daily_growth_bytes", 0)
        recent_daily = stats.get("recent_daily_growth_bytes", 0)
        current_gb = stats.get("current_bytes", 0) / (1024 ** 3)

        details = {
            "current_gb": round(current_gb, 2),
            "avg_daily_growth_mb": round(avg_daily / (1024 ** 2), 2) if avg_daily else 0,
            "recent_daily_growth_mb": round(recent_daily / (1024 ** 2), 2) if recent_daily else 0,
            "growth_multiplier": self.growth_multiplier,
            "lookback_days": self.lookback_days,
        }

        if avg_daily > 0 and recent_daily > avg_daily * self.growth_multiplier:
            ratio = recent_daily / avg_daily
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=round(ratio, 1),
                threshold=self.growth_multiplier,
                message=(
                    f"Storage growing {ratio:.1f}x faster than normal "
                    f"({details['recent_daily_growth_mb']} MB/day vs "
                    f"{details['avg_daily_growth_mb']} MB/day avg)."
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=round(current_gb, 2),
            message=f"Storage growth normal: {current_gb:.1f} GB total.",
            details=details,
        )


# =============================================================================
# Cross-cutting: Consecutive failure, Recovery, SLA breach
# =============================================================================


def enrich_tool_result(
    result: MonitorResult,
    config: Dict[str, Any],
) -> MonitorResult:
    """Post-process a tool monitor result with streak/recovery/SLA logic.

    Config keys consumed:
        recent_statuses : list[str]
            Last N run statuses (newest first), e.g. ["FAIL","FAIL","PASS"].
            Injected by the scheduler from BaselineStore.get_recent_statuses().
        consecutive_fail_escalate : int
            Number of consecutive failures before escalation (default: 3).
        first_failure_at : str | None
            ISO timestamp of the first failure in the current streak.
            Set by the scheduler on first FAIL, cleared on PASS.
    """
    recent_statuses: List[str] = config.get("recent_statuses") or []
    escalate_threshold: int = int(config.get("consecutive_fail_escalate", 3))
    first_failure_at: Optional[str] = config.get("first_failure_at")

    if not recent_statuses:
        return result

    current_status = result.status.value.upper()
    details = dict(result.details) if result.details else {}
    message = result.message

    # Count leading failures in recent history (before this run)
    streak = 0
    for s in recent_statuses:
        if s.upper() in ("FAIL", "ERROR"):
            streak += 1
        else:
            break

    details["failure_streak"] = streak

    # 7A: Consecutive-failure escalation
    if current_status in ("FAIL", "ERROR") and streak >= escalate_threshold:
        total_streak = streak + 1  # including current
        details["escalated"] = True
        details["consecutive_failures"] = total_streak
        message = f"ESCALATED: {total_streak} consecutive failures. {message}"

    # 7B: Recovery detection
    if current_status == "PASS" and streak > 0:
        details["recovery"] = True
        details["recovered_after"] = streak
        message = f"RECOVERED after {streak} failure(s). {message}"

    # 7C: SLA breach duration
    if current_status in ("FAIL", "ERROR") and first_failure_at:
        try:
            first_fail_dt = datetime.fromisoformat(
                first_failure_at.replace("Z", "+00:00")
            )
            breach_hours = (
                datetime.now(timezone.utc) - first_fail_dt
            ).total_seconds() / 3600
            details["breach_hours"] = round(breach_hours, 1)
            details["first_failure_at"] = first_failure_at
            message = f"{message} ({breach_hours:.1f}h in breach)"
        except (ValueError, TypeError):
            pass

    return MonitorResult(
        monitor_type=result.monitor_type,
        target_fqn=result.target_fqn,
        status=result.status,
        value=result.value,
        threshold=result.threshold,
        expected_range=result.expected_range,
        message=message,
        details=details,
        executed_at=result.executed_at,
        duration_ms=result.duration_ms,
        sql_executed=result.sql_executed,
        raw_status=result.raw_status,
    )


# =============================================================================
# Registry
# =============================================================================

TOOL_MONITOR_REGISTRY = {
    "sync_lag": SyncLagMonitor,
    "failed_syncs": FailedSyncsMonitor,
    "connector_schema_drift": ConnectorSchemaDriftMonitor,
    "dag_last_run": DagLastRunMonitor,
    "dag_schedule_lag": DagScheduleLagMonitor,
    "task_failure_rate": TaskFailureRateMonitor,
    "dbt_test_failures": DbtTestFailuresMonitor,
    "dbt_model_freshness": DbtModelFreshnessMonitor,
    "dbt_source_freshness": DbtSourceFreshnessMonitor,
    "query_performance": QueryPerformanceMonitor,
    "cost_anomaly": CostAnomalyMonitor,
    "storage_growth": StorageGrowthMonitor,
}
