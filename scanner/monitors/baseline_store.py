"""
Baseline time-series store.

Provides read/write access to the MonitorBaseline table for persisting
per-run metric values and querying historical patterns (cadence gaps,
seasonal baselines, trend detection).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


class BaselineStore:
    """Read/write interface to the MonitorBaseline table."""

    def __init__(self, conn):
        """conn: a psycopg2 connection (caller owns lifecycle)."""
        self._conn = conn

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        monitor_id: str,
        metric_name: str,
        value: float,
        target_fqn: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        measured_at: Optional[datetime] = None,
    ) -> None:
        """Record a single metric observation."""
        now = measured_at or datetime.now(timezone.utc)
        # Python weekday(): 0=Mon..6=Sun → convert to 0=Sun convention
        dow_sunday = (now.weekday() + 1) % 7
        hour = now.hour

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "MonitorBaseline"
                    (id, "metricName", "metricValue", "measuredAt",
                     "dayOfWeek", "hourOfDay", "targetFqn", details, "monitorId")
                VALUES (gen_random_uuid()::text, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    metric_name,
                    value,
                    now,
                    dow_sunday,
                    hour,
                    target_fqn,
                    json.dumps(details) if details else None,
                    monitor_id,
                ),
            )

    def record_batch(
        self,
        monitor_id: str,
        metrics: List[Dict[str, Any]],
        target_fqn: Optional[str] = None,
    ) -> None:
        """Record multiple metric observations in one call.

        Each item in metrics should have: {"metric_name": str, "value": float}
        and optionally "details": dict.
        """
        for m in metrics:
            self.record(
                monitor_id=monitor_id,
                metric_name=m["metric_name"],
                value=m["value"],
                target_fqn=target_fqn,
                details=m.get("details"),
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history(
        self,
        monitor_id: str,
        metric_name: str,
        days: int = 90,
        day_of_week: Optional[int] = None,
        hour_of_day: Optional[int] = None,
    ) -> List[float]:
        """Retrieve historical values for a monitor+metric.

        Returns values ordered chronologically (oldest first).
        Optional filters: day_of_week (0=Sun..6=Sat), hour_of_day (0-23).
        """
        conditions = [
            '"monitorId" = %s',
            '"metricName" = %s',
            "\"measuredAt\" >= NOW() - INTERVAL '%s days'",
        ]
        params: list = [monitor_id, metric_name, days]

        if day_of_week is not None:
            conditions.append('"dayOfWeek" = %s')
            params.append(day_of_week)
        if hour_of_day is not None:
            conditions.append('"hourOfDay" = %s')
            params.append(hour_of_day)

        where = " AND ".join(conditions)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT "metricValue"
                FROM "MonitorBaseline"
                WHERE {where}
                ORDER BY "measuredAt" ASC
                """,
                tuple(params),
            )
            return [row[0] for row in cur.fetchall()]

    def get_history_with_timestamps(
        self,
        monitor_id: str,
        metric_name: str,
        days: int = 90,
    ) -> List[tuple]:
        """Retrieve (value, timestamp) pairs ordered chronologically.

        Useful for trend analysis where the caller needs time ordering.
        Returns List[Tuple[float, datetime]].
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT "metricValue", "measuredAt"
                FROM "MonitorBaseline"
                WHERE "monitorId" = %s
                  AND "metricName" = %s
                  AND "measuredAt" >= NOW() - INTERVAL '%s days'
                ORDER BY "measuredAt" ASC
                """,
                (monitor_id, metric_name, days),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

    def get_recent_statuses(
        self,
        monitor_id: str,
        limit: int = 10,
    ) -> List[str]:
        """Return the last N run statuses for a monitor (newest first).

        Queries MonitorRun table, not MonitorBaseline.
        Used for consecutive-failure detection and recovery events.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT status
                FROM "MonitorRun"
                WHERE "monitorId" = %s
                ORDER BY "startedAt" DESC
                LIMIT %s
                """,
                (monitor_id, limit),
            )
            return [row[0] for row in cur.fetchall()]

    def get_cadence_gaps(
        self,
        monitor_id: str,
        metric_name: str = "hours_since_update",
        days: int = 90,
    ) -> List[float]:
        """Return gaps (in hours) between consecutive measurements.

        Used by cadence-aware freshness to learn expected update frequency.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT "measuredAt"
                FROM "MonitorBaseline"
                WHERE "monitorId" = %s
                  AND "metricName" = %s
                  AND "measuredAt" >= NOW() - INTERVAL '%s days'
                ORDER BY "measuredAt" ASC
                """,
                (monitor_id, metric_name, days),
            )
            timestamps = [row[0] for row in cur.fetchall()]

        if len(timestamps) < 2:
            return []

        gaps: List[float] = []
        for i in range(1, len(timestamps)):
            delta = (timestamps[i] - timestamps[i - 1]).total_seconds() / 3600.0
            gaps.append(round(delta, 2))
        return gaps

    def get_latest(
        self,
        monitor_id: str,
        metric_name: str,
    ) -> Optional[float]:
        """Get the most recent value for a metric."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT "metricValue"
                FROM "MonitorBaseline"
                WHERE "monitorId" = %s
                  AND "metricName" = %s
                ORDER BY "measuredAt" DESC
                LIMIT 1
                """,
                (monitor_id, metric_name),
            )
            row = cur.fetchone()
            return row[0] if row else None

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune(self, monitor_id: str, keep_days: int = 180) -> int:
        """Delete baseline entries older than keep_days. Returns count deleted."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM "MonitorBaseline"
                WHERE "monitorId" = %s
                  AND "measuredAt" < NOW() - INTERVAL '%s days'
                """,
                (monitor_id, keep_days),
            )
            return cur.rowcount

    def prune_all(self, keep_days: int = 180) -> int:
        """Delete all baseline entries older than keep_days across all monitors."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM "MonitorBaseline"
                WHERE "measuredAt" < NOW() - INTERVAL '%s days'
                """,
                (keep_days,),
            )
            return cur.rowcount
