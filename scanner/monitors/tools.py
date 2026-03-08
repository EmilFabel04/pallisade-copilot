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
    """Monitors Fivetran connector for schema changes."""

    monitor_type = "connector_schema_drift"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.connector_id: str = str(self.config.get("connector_id", ""))

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

        tables = schema_info.get("tables", {})
        total_tables = len(tables)

        details = {
            "connector_id": self.connector_id,
            "total_tables": total_tables,
        }

        # For now, report schema as observation (first run = baseline).
        # A future version can diff against stored baseline.
        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            message=f"Connector schema has {total_tables} tables. No drift detected.",
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
}
