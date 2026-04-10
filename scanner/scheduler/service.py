"""
Scheduler Service.

In-process asyncio background loop that checks for due tasks
every 60 seconds and dispatches execution.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


def _parse_database_url(url: str) -> Dict[str, Any]:
    """Parse a postgres:// or postgresql:// URL into connection params."""
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(url)
    params: Dict[str, Any] = {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/").split("?")[0],
    }
    # Handle sslmode from query params
    qs = parse_qs(parsed.query)
    if "sslmode" in qs:
        params["sslmode"] = qs["sslmode"][0]
    return params


def _get_connection():
    """Get a psycopg2 connection using DATABASE_URL."""
    import psycopg2

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set — scheduler cannot query tasks")

    params = _parse_database_url(url)
    return psycopg2.connect(**params)


def _compute_next_run(cron_expr: str, tz_name: str = "UTC") -> Optional[datetime]:
    """Compute next run time from a cron expression."""
    try:
        from croniter import croniter
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
        now = datetime.now(tz)
        cron = croniter(cron_expr, now)
        return cron.get_next(datetime).astimezone(timezone.utc)
    except ImportError:
        logger.warning("[Scheduler] croniter not installed — cannot compute next run")
        return None
    except Exception as e:
        logger.warning(f"[Scheduler] Failed to parse cron '{cron_expr}': {e}")
        return None


class SchedulerService:
    """Background scheduler that executes due monitor tasks."""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._interval = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "60"))

    async def start(self):
        """Start the scheduler loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "[Scheduler] Started",
            interval_seconds=self._interval,
        )

    async def stop(self):
        """Stop the scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Scheduler] Stopped")

    async def _loop(self):
        # Small initial delay to let the app fully boot
        await asyncio.sleep(5)

        while self._running:
            try:
                await self._check_due_tasks()
                await self._check_drift_analysis()
            except Exception as e:
                logger.error(f"[Scheduler] Error in loop: {e}")
            await asyncio.sleep(self._interval)

    async def _check_drift_analysis(self):
        """Check if weekly drift analysis is due for any organization."""
        from datetime import timedelta

        try:
            marker_file = "/tmp/pallisade_drift_last_run"
            last_run = None
            try:
                with open(marker_file) as f:
                    last_run = datetime.fromisoformat(f.read().strip())
            except (FileNotFoundError, ValueError):
                pass

            now = datetime.now(timezone.utc)
            if last_run and (now - last_run) < timedelta(days=7):
                return

            logger.info("[Scheduler] Weekly drift analysis is due")

            with open(marker_file, "w") as f:
                f.write(now.isoformat())

            logger.info("[Scheduler] Drift analysis marker updated, will be triggered on next UI access or manual run")

        except Exception as e:
            logger.error(f"[Scheduler] Drift analysis check failed: {e}")

    async def _check_due_tasks(self):
        """Find and execute tasks that are due."""
        now = datetime.now(timezone.utc)

        try:
            conn = _get_connection()
        except Exception as e:
            logger.warning(f"[Scheduler] DB connection failed: {e}")
            return

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT m.id, m.name, m."taskMode", m.prompt, m."monitorType",
                           m."targetFqn", m.config, m.schedule, m."alertChannels",
                           m."alertConfig", m."alertOnStatus", m.timezone,
                           m."integrationId", m."organizationId",
                           m."baselineMean", m."baselineStddev", m."baselineCount",
                           m."monitorGroupId", m."lastRunAt",
                           mg.name AS "groupName",
                           mg."monitoringPlanId",
                           mp.name AS "planName"
                    FROM "Monitor" m
                    LEFT JOIN "MonitorGroup" mg ON m."monitorGroupId" = mg.id
                    LEFT JOIN "MonitoringPlan" mp ON mg."monitoringPlanId" = mp.id
                    WHERE m.enabled = true
                      AND m."nextRunAt" IS NOT NULL
                      AND m."nextRunAt" <= %s
                    ORDER BY m."nextRunAt" ASC
                    LIMIT 50
                    FOR UPDATE OF m SKIP LOCKED
                    """,
                    (now,),
                )
                rows = cur.fetchall()
                col_names = [desc[0] for desc in cur.description]

                # Immediately advance nextRunAt for all claimed tasks so no other
                # scheduler instance (or the next tick) can re-pick them.
                if rows:
                    task_ids = [row[0] for row in rows]  # id is first column
                    task_dicts = [dict(zip(col_names, r)) for r in rows]
                    for td in task_dicts:
                        next_run = _compute_next_run(
                            td.get("schedule", "0 * * * *"),
                            td.get("timezone", "UTC"),
                        )
                        cur.execute(
                            """UPDATE "Monitor" SET "nextRunAt" = %s WHERE id = %s""",
                            (next_run, td["id"]),
                        )
                    conn.commit()

            if not rows:
                return

            logger.info(f"[Scheduler] Found {len(rows)} due tasks")

            # Execute all tasks and collect results for group-level summary alerts
            group_results: Dict[str, List[Dict[str, Any]]] = {}  # groupId -> [{task, result, status}]

            for row in rows:
                task = dict(zip(col_names, row))

                # Dedup: skip if this monitor was already run in the last 2 minutes
                # (e.g. by a watch-level run or manual trigger that completed first)
                last_run = task.get("lastRunAt")
                if last_run:
                    # Ensure timezone-aware comparison (psycopg2 may return naive datetimes)
                    if last_run.tzinfo is None:
                        last_run = last_run.replace(tzinfo=timezone.utc)
                    if (now - last_run).total_seconds() < 120:
                        logger.info(
                            f"[Scheduler] Skipping recently-run task: {task.get('name')}",
                            last_run_seconds_ago=int((now - last_run).total_seconds()),
                        )
                        continue

                result = await self._execute_task(task, conn)
                # Buffer results for monitors that belong to a group/plan
                group_id = task.get("monitorGroupId")
                if group_id and result:
                    if group_id not in group_results:
                        group_results[group_id] = []
                    group_results[group_id].append({
                        "task": task,
                        "result": result,
                        "status": (result.get("status", "ERROR")).upper(),
                    })

            # Send summary alerts per group (instead of per-monitor)
            for group_id, items in group_results.items():
                await self._dispatch_group_summary_alert(group_id, items)

        except Exception as e:
            logger.error(f"[Scheduler] Failed to check due tasks: {e}")
        finally:
            conn.close()

    async def _execute_task(self, task: Dict[str, Any], conn) -> Optional[Dict[str, Any]]:
        """Execute a single task and save the result. Returns the result dict."""
        from .executor import TaskExecutor

        task_id = task["id"]
        task_name = task["name"]
        logger.info(f"[Scheduler] Executing task: {task_name} ({task_id})")

        # Inject stored baseline into config (mirrors run/route.ts behavior)
        # so monitors can fall back to previous baselines when warehouse
        # history is insufficient for z-score computation.
        baseline_mean = task.get("baselineMean")
        if baseline_mean is not None:
            config = task.get("config") or {}
            if isinstance(config, str):
                config = json.loads(config)
            else:
                config = dict(config)  # shallow copy to avoid mutating cached dict
            config["stored_baseline"] = {
                "mean": baseline_mean,
                "stddev": task.get("baselineStddev") or 0,
                "count": task.get("baselineCount") or 0,
            }
            task["config"] = config
            logger.info(
                "[Scheduler] Injected stored baseline",
                task=task_name,
                mean=baseline_mean,
                stddev=task.get("baselineStddev"),
                count=task.get("baselineCount"),
            )

        # Pre-resolve integration config so the executor doesn't have to.
        # This mirrors what tasks/[taskId]/run/route.ts does: resolve config
        # BEFORE calling the executor, then pass it as integrationConfig.
        if not task.get("integrationConfig"):
            executor = TaskExecutor()
            task_config = task.get("config") or {}
            if isinstance(task_config, str):
                task_config = json.loads(task_config)
            node_id = task_config.get("nodeId") if isinstance(task_config, dict) else None
            tool_node_id = task_config.get("toolNodeId") if isinstance(task_config, dict) else None

            try:
                resolved = await executor._get_integration_config(
                    task.get("integrationId"),
                    task.get("organizationId"),
                    node_id=node_id,
                )
                if resolved:
                    task["integrationConfig"] = resolved
                    logger.info(
                        "[Scheduler] Pre-resolved integration config",
                        task=task_name,
                        node=resolved.get("name"),
                        type=resolved.get("type"),
                    )
            except Exception as e:
                logger.warning(f"[Scheduler] Failed to pre-resolve integration config: {e}")

        start_time = datetime.now(timezone.utc)
        executor = TaskExecutor()

        try:
            result = await executor.execute(task)

            # Normalize status to uppercase (Python monitors return lowercase, DB enum is uppercase)
            status = (result.get("status", "ERROR")).upper()

            # Save the run result
            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            with conn.cursor() as cur:
                # Insert MonitorRun
                cur.execute(
                    """
                    INSERT INTO "MonitorRun" (id, status, value, threshold, message,
                                              details, "sqlExecuted", "startedAt",
                                              "completedAt", "durationMs", "monitorId")
                    VALUES (
                        gen_random_uuid()::text, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        status,
                        result.get("value"),
                        result.get("threshold"),
                        result.get("message", ""),
                        json.dumps(result.get("details")) if result.get("details") else None,
                        result.get("sql_executed"),
                        start_time,
                        end_time,
                        duration_ms,
                        task_id,
                    ),
                )

                # Update Monitor: lastRunAt, lastStatus, nextRunAt + baseline
                next_run = _compute_next_run(
                    task.get("schedule", "0 * * * *"),
                    task.get("timezone", "UTC"),
                )

                # Extract baseline stats from result details if available
                details = result.get("details") or {}
                baseline_mean = details.get("baseline_mean")
                baseline_stddev = details.get("baseline_stddev")
                baseline_count = details.get("baseline_count") or details.get("data_points")

                if baseline_mean is not None:
                    cur.execute(
                        """
                        UPDATE "Monitor"
                        SET "lastRunAt" = %s,
                            "lastStatus" = %s,
                            "nextRunAt" = %s,
                            "updatedAt" = %s,
                            "baselineMean" = %s,
                            "baselineStddev" = %s,
                            "baselineCount" = %s,
                            "baselineUpdatedAt" = %s
                        WHERE id = %s
                        """,
                        (
                            end_time,
                            status,
                            next_run,
                            end_time,
                            baseline_mean,
                            baseline_stddev,
                            baseline_count,
                            end_time,
                            task_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE "Monitor"
                        SET "lastRunAt" = %s,
                            "lastStatus" = %s,
                            "nextRunAt" = %s,
                            "updatedAt" = %s
                        WHERE id = %s
                        """,
                        (
                            end_time,
                            status,
                            next_run,
                            end_time,
                            task_id,
                        ),
                    )

                conn.commit()

            # Record metric observations in the time-series baseline table
            try:
                from scanner.monitors.baseline_store import BaselineStore

                store = BaselineStore(conn)
                monitor_type = (task.get("monitorType") or "").lower()
                metrics = self._extract_baseline_metrics(monitor_type, task, result)
                if metrics:
                    store.record_batch(
                        monitor_id=task_id,
                        metrics=metrics,
                        target_fqn=task.get("targetFqn"),
                    )
                    conn.commit()
                    logger.debug(
                        "[Scheduler] Recorded baseline observations",
                        task=task_name,
                        count=len(metrics),
                    )
            except Exception as baseline_err:
                logger.debug(f"[Scheduler] Baseline record skipped: {baseline_err}")

            # For standalone monitors (no group), dispatch alert immediately.
            # For group monitors, the caller buffers results and sends a summary.
            if not task.get("monitorGroupId"):
                from .alert_engine import AlertEngine
                alert_engine = AlertEngine()
                decision = alert_engine.evaluate(task, result)

                if decision.should_alert:
                    await self._dispatch_alert(task, result)
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE "Monitor"
                                SET "lastAlertStatus" = %s,
                                    "lastAlertAt" = %s
                                WHERE id = %s
                                """,
                                (status, end_time, task_id),
                            )
                            conn.commit()
                    except Exception:
                        pass
                elif decision.suppressed:
                    logger.info(
                        f"[Scheduler] Alert suppressed: {task_name}",
                        reason=decision.reason,
                    )

            logger.info(
                f"[Scheduler] Task completed: {task_name}",
                status=status,
                duration_ms=duration_ms,
            )

            return result

        except Exception as e:
            logger.error(f"[Scheduler] Task execution failed: {task_name}: {e}")

            # Save error run
            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO "MonitorRun" (id, status, message, "startedAt",
                                                  "completedAt", "durationMs", "monitorId")
                        VALUES (gen_random_uuid()::text, 'ERROR', %s, %s, %s, %s, %s)
                        """,
                        (str(e), start_time, end_time, duration_ms, task_id),
                    )

                    next_run = _compute_next_run(
                        task.get("schedule", "0 * * * *"),
                        task.get("timezone", "UTC"),
                    )

                    cur.execute(
                        """
                        UPDATE "Monitor"
                        SET "lastRunAt" = %s, "lastStatus" = 'ERROR',
                            "nextRunAt" = %s, "updatedAt" = %s
                        WHERE id = %s
                        """,
                        (end_time, next_run, end_time, task_id),
                    )
                    conn.commit()
            except Exception as save_err:
                logger.error(f"[Scheduler] Failed to save error result: {save_err}")
            return None

    async def _dispatch_group_summary_alert(
        self,
        group_id: str,
        items: List[Dict[str, Any]],
    ):
        """Send a single summary alert for all monitors in a group/plan.

        Instead of N individual alerts, sends one summary like:
        "Full Lineage: 10 passed, 5 failed, 2 warned (17 monitors)"
        """
        if not items:
            return

        # Use the first task for alert config (group-level settings propagate)
        first_task = items[0]["task"]
        alert_channels = first_task.get("alertChannels") or []
        alert_on = first_task.get("alertOnStatus") or []

        if not alert_channels:
            return

        # Count statuses
        pass_count = sum(1 for i in items if i["status"] == "PASS")
        fail_count = sum(1 for i in items if i["status"] == "FAIL")
        warn_count = sum(1 for i in items if i["status"] == "WARN")
        error_count = sum(1 for i in items if i["status"] == "ERROR")
        total = len(items)

        # Only alert if there are statuses matching alertOnStatus
        triggered_statuses = set(i["status"] for i in items) & set(alert_on)
        if not triggered_statuses:
            return

        # Determine worst status for severity
        worst = "PASS"
        for s in ("FAIL", "ERROR", "WARN"):
            if any(i["status"] == s for i in items):
                worst = s
                break

        # Build summary
        plan_name = first_task.get("planName") or first_task.get("groupName") or "Monitoring Plan"

        parts = []
        if pass_count > 0:
            parts.append(f"{pass_count} passed")
        if fail_count > 0:
            parts.append(f"{fail_count} failed")
        if error_count > 0:
            parts.append(f"{error_count} errored")
        if warn_count > 0:
            parts.append(f"{warn_count} warned")

        summary_line = ", ".join(parts)
        message = f"{plan_name}: {summary_line} ({total} monitors)"

        # Add details for failed/warned monitors
        problem_monitors = [
            i for i in items if i["status"] in ("FAIL", "ERROR", "WARN")
        ]
        if problem_monitors:
            details_lines = []
            for i in problem_monitors[:10]:  # Cap at 10 to avoid huge messages
                t = i["task"]
                r = i["result"]
                details_lines.append(
                    f"- {t.get('name', '?')}: {i['status']} — {r.get('message', '')}"
                )
            if len(problem_monitors) > 10:
                details_lines.append(f"  ... and {len(problem_monitors) - 10} more")
            message += "\n\n" + "\n".join(details_lines)

        try:
            import httpx

            nextjs_url = os.environ.get("NEXTAUTH_URL", "http://localhost:3000")
            alert_url = f"{nextjs_url}/api/schedule/alert"

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    alert_url,
                    json={
                        "taskId": group_id,
                        "taskName": plan_name,
                        "status": worst,
                        "message": message,
                        "channels": alert_channels,
                        "config": first_task.get("alertConfig"),
                        "organizationId": first_task.get("organizationId"),
                        "grouped": True,
                        "grouped_count": total,
                        "summary": {
                            "total": total,
                            "pass": pass_count,
                            "fail": fail_count,
                            "warn": warn_count,
                            "error": error_count,
                        },
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"[Scheduler] Group alert dispatch failed: {resp.status_code}"
                    )
                else:
                    logger.info(
                        f"[Scheduler] Group summary alert sent: {plan_name}",
                        total=total,
                        pass_count=pass_count,
                        fail_count=fail_count,
                    )
        except Exception as e:
            logger.warning(f"[Scheduler] Group alert dispatch error: {e}")

    @staticmethod
    def _baseline_metric_name(monitor_type: str, task: Dict[str, Any]) -> str:
        """Derive a metric name for the baseline table from monitor type."""
        if monitor_type == "freshness":
            return "hours_since_update"
        if monitor_type == "volume":
            return "row_count"
        if monitor_type == "anomaly":
            config = task.get("config") or {}
            col = config.get("column", "")
            metric = config.get("metric", "value")
            return f"{col}.{metric}" if col else metric
        if monitor_type == "schema":
            return "schema_change_count"
        return "value"

    @staticmethod
    def _extract_baseline_metrics(
        monitor_type: str, task: Dict[str, Any], result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract multiple metric observations from a monitor result.

        Returns a list of dicts with ``metric_name``, ``value``, and
        optionally ``details``.  This replaces the old single-metric
        recording so that we capture richer time-series data (e.g.
        both row_count and row_count_delta for volume, or multiple
        anomaly sub-metrics).
        """
        metrics: List[Dict[str, Any]] = []
        details = result.get("details") or {}
        primary_value = result.get("value")
        status = result.get("status", "")

        base_details = {
            "status": status,
            "monitor_type": monitor_type,
        }

        # Always record the primary metric if present
        if primary_value is not None:
            config = task.get("config") or {}
            if isinstance(config, str):
                import json as _json
                config = _json.loads(config)

            if monitor_type == "freshness":
                metrics.append({"metric_name": "hours_since_update", "value": float(primary_value), "details": base_details})
            elif monitor_type == "volume":
                metrics.append({"metric_name": "row_count", "value": float(primary_value), "details": base_details})
                # Also record delta if available
                delta = details.get("row_count_delta") or details.get("delta")
                if delta is not None:
                    metrics.append({"metric_name": "row_count_delta", "value": float(delta), "details": base_details})
            elif monitor_type == "anomaly":
                col = config.get("column", "")
                metric = config.get("metric", "value")
                name = f"{col}.{metric}" if col else metric
                metrics.append({"metric_name": name, "value": float(primary_value), "details": base_details})
            elif monitor_type == "schema_change":
                metrics.append({"metric_name": "schema_change_count", "value": float(primary_value), "details": base_details})
            elif monitor_type == "referential":
                metrics.append({"metric_name": "orphan_count", "value": float(primary_value), "details": base_details})
                orphan_pct = details.get("orphan_pct")
                if orphan_pct is not None:
                    metrics.append({"metric_name": "orphan_pct", "value": float(orphan_pct), "details": base_details})
            else:
                metrics.append({"metric_name": "value", "value": float(primary_value), "details": base_details})

        # Persist the current connector schema snapshot so the next run can
        # diff against it. This runs regardless of primary_value because
        # we want to record the snapshot even when there are zero changes.
        if monitor_type == "connector_schema_drift":
            snapshot = details.get("schema_snapshot")
            if isinstance(snapshot, dict):
                snapshot_details = {
                    **base_details,
                    "schema_snapshot": snapshot,
                    "total_tables": len(snapshot),
                }
                metrics.append({
                    "metric_name": "connector_schema",
                    "value": float(len(snapshot)),
                    "details": snapshot_details,
                })

        return metrics

    async def _dispatch_alert(self, task: Dict[str, Any], result: Dict[str, Any]):
        """Send alert to configured channels via the Next.js alert API."""
        try:
            import httpx

            nextjs_url = os.environ.get("NEXTAUTH_URL", "http://localhost:3000")
            alert_url = f"{nextjs_url}/api/schedule/alert"

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    alert_url,
                    json={
                        "taskId": task["id"],
                        "taskName": task["name"],
                        "status": result.get("status", "ERROR"),
                        "message": result.get("message", ""),
                        "channels": task.get("alertChannels", []),
                        "config": task.get("alertConfig"),
                        "organizationId": task.get("organizationId"),
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"[Scheduler] Alert dispatch failed: {resp.status_code} {resp.text}"
                    )
        except Exception as e:
            logger.warning(f"[Scheduler] Alert dispatch error: {e}")
