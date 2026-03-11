"""
Alert engine with deduplication, suppression, and grouping.

Replaces fire-and-forget alert dispatch with intelligent noise reduction:
- Dedup: Suppress repeat alerts for the same status within a time window
- Grouping: Batch multiple failures on the same table into one alert
- Min-history: Suppress alerts during the first N runs of a new monitor
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()


# Default suppression windows per status
_SUPPRESSION_WINDOWS: Dict[str, timedelta] = {
    "FAIL": timedelta(minutes=15),
    "WARN": timedelta(hours=1),
    "ERROR": timedelta(minutes=30),
}

# Minimum runs before alerts are active (during baseline building)
DEFAULT_MIN_HISTORY_RUNS = 3


class AlertDecision:
    """Result of the alert engine's evaluation."""

    def __init__(
        self,
        should_alert: bool,
        reason: str,
        suppressed: bool = False,
        grouped_with: Optional[List[str]] = None,
    ):
        self.should_alert = should_alert
        self.reason = reason
        self.suppressed = suppressed
        self.grouped_with = grouped_with or []

    def __repr__(self) -> str:
        return f"AlertDecision(alert={self.should_alert}, reason='{self.reason}')"


class AlertEngine:
    """Evaluates whether an alert should be sent for a monitor result.

    Stateless — reads context from task/result dicts. The scheduler
    is responsible for persisting alert tracking fields.
    """

    def __init__(
        self,
        min_history_runs: int = DEFAULT_MIN_HISTORY_RUNS,
        suppression_windows: Optional[Dict[str, timedelta]] = None,
    ):
        self.min_history_runs = min_history_runs
        self.suppression_windows = suppression_windows or _SUPPRESSION_WINDOWS

    def evaluate(
        self,
        task: Dict[str, Any],
        result: Dict[str, Any],
        run_count: int = 0,
    ) -> AlertDecision:
        """Decide whether to send an alert for this monitor result.

        Parameters
        ----------
        task : dict
            The monitor/task configuration including alertOnStatus,
            alertChannels, lastAlertStatus, lastAlertAt, etc.
        result : dict
            The monitor execution result with status, message, details.
        run_count : int
            Total number of runs for this monitor (including current).

        Returns
        -------
        AlertDecision
        """
        status = (result.get("status", "ERROR")).upper()
        alert_on = task.get("alertOnStatus") or []
        alert_channels = task.get("alertChannels") or []

        # Check if status matches alert configuration
        if status not in alert_on:
            return AlertDecision(
                should_alert=False,
                reason=f"Status '{status}' not in alertOnStatus {alert_on}",
            )

        if not alert_channels:
            return AlertDecision(
                should_alert=False,
                reason="No alert channels configured",
            )

        # Min-history check: don't alert during baseline building
        if run_count > 0 and run_count <= self.min_history_runs:
            details = result.get("details") or {}
            confidence = details.get("confidence_pct")
            if confidence is not None and confidence < 50:
                return AlertDecision(
                    should_alert=False,
                    suppressed=True,
                    reason=(
                        f"Suppressed: only {run_count} run(s) completed "
                        f"(need {self.min_history_runs}+ for reliable alerts, "
                        f"confidence: {confidence}%)"
                    ),
                )

        # Dedup check: suppress if same status was alerted recently
        last_alert_status = task.get("lastAlertStatus")
        last_alert_at = task.get("lastAlertAt")

        if last_alert_status and last_alert_at and last_alert_status == status:
            window = self.suppression_windows.get(
                status, timedelta(minutes=30)
            )
            if isinstance(last_alert_at, str):
                try:
                    last_alert_at = datetime.fromisoformat(
                        last_alert_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    last_alert_at = None

            if last_alert_at:
                now = datetime.now(timezone.utc)
                if hasattr(last_alert_at, 'tzinfo') and last_alert_at.tzinfo is None:
                    last_alert_at = last_alert_at.replace(tzinfo=timezone.utc)
                elapsed = now - last_alert_at
                if elapsed < window:
                    remaining = window - elapsed
                    return AlertDecision(
                        should_alert=False,
                        suppressed=True,
                        reason=(
                            f"Suppressed: same status '{status}' was alerted "
                            f"{elapsed.total_seconds():.0f}s ago "
                            f"(suppression window: {window.total_seconds():.0f}s, "
                            f"{remaining.total_seconds():.0f}s remaining)"
                        ),
                    )

        return AlertDecision(
            should_alert=True,
            reason=f"Alert triggered: status '{status}' matches alertOnStatus",
        )


class AlertBuffer:
    """Buffers alert dispatches within a scheduler tick for grouping.

    Usage:
        buffer = AlertBuffer()
        buffer.add(task1, result1)
        buffer.add(task2, result2)  # same table as task1
        grouped = buffer.flush()
        # grouped contains batched alerts per table
    """

    def __init__(self):
        self._pending: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    def add(self, task: Dict[str, Any], result: Dict[str, Any]):
        """Add an alert to the buffer."""
        self._pending.append((task, result))

    @property
    def size(self) -> int:
        return len(self._pending)

    def flush(self) -> List[Dict[str, Any]]:
        """Flush the buffer, grouping alerts by target table.

        Returns a list of alert payloads. Multiple failures on the
        same target are combined into a single grouped alert.
        """
        if not self._pending:
            return []

        # Group by targetFqn
        by_target: Dict[str, List[Tuple[Dict, Dict]]] = {}
        ungrouped: List[Tuple[Dict, Dict]] = []

        for task, result in self._pending:
            target = task.get("targetFqn")
            if target:
                by_target.setdefault(target, []).append((task, result))
            else:
                ungrouped.append((task, result))

        alerts: List[Dict[str, Any]] = []

        for target, items in by_target.items():
            if len(items) == 1:
                task, result = items[0]
                alerts.append(_build_alert_payload(task, result))
            else:
                # Group multiple monitors on the same table
                alerts.append(_build_grouped_alert_payload(target, items))

        for task, result in ungrouped:
            alerts.append(_build_alert_payload(task, result))

        self._pending.clear()
        return alerts


def _build_alert_payload(
    task: Dict[str, Any], result: Dict[str, Any]
) -> Dict[str, Any]:
    """Build a single alert payload."""
    return {
        "taskId": task.get("id"),
        "taskName": task.get("name"),
        "targetFqn": task.get("targetFqn"),
        "status": result.get("status", "ERROR"),
        "message": result.get("message", ""),
        "channels": task.get("alertChannels", []),
        "config": task.get("alertConfig"),
        "organizationId": task.get("organizationId"),
        "grouped": False,
    }


def _build_grouped_alert_payload(
    target: str,
    items: List[Tuple[Dict[str, Any], Dict[str, Any]]],
) -> Dict[str, Any]:
    """Build a grouped alert payload for multiple monitors on the same table."""
    statuses = [r.get("status", "ERROR") for _, r in items]
    # Use the worst status
    worst = "FAIL" if "FAIL" in statuses else (
        "ERROR" if "ERROR" in statuses else (
            "WARN" if "WARN" in statuses else statuses[0]
        )
    )

    monitor_summaries = []
    for task, result in items:
        monitor_summaries.append(
            f"- {task.get('name', '?')}: {result.get('status', '?')} — {result.get('message', '')}"
        )

    # Use the first task's alert config as representative
    first_task = items[0][0]

    return {
        "taskId": first_task.get("id"),
        "taskName": f"{len(items)} monitors on {target}",
        "targetFqn": target,
        "status": worst,
        "message": (
            f"{len(items)} monitor(s) triggered on {target}:\n"
            + "\n".join(monitor_summaries)
        ),
        "channels": first_task.get("alertChannels", []),
        "config": first_task.get("alertConfig"),
        "organizationId": first_task.get("organizationId"),
        "grouped": True,
        "grouped_count": len(items),
        "monitor_ids": [t.get("id") for t, _ in items],
    }
