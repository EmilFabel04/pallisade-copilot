"""
BI / Reporting monitors.

Non-SQL monitors that query BI platform APIs (Looker, Tableau, Power BI, Metabase)
and optionally combine with lineage-based upstream health signals.

Follows the same pattern as tools.py:
- Registry mapping type strings to classes
- Each class has __init__(config) and execute(bi_client, **kwargs) -> MonitorResult
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from .base import MonitorResult, MonitorStatus

import structlog

logger = structlog.get_logger()

# BI monitor types
BI_MONITOR_TYPES = {
    "bi_freshness_proxy", "bi_upstream_break_risk",
    "bi_content_health", "bi_refresh_failure",
}


# =============================================================================
# BI_FRESHNESS_PROXY — Dashboard Freshness
# =============================================================================

class BIFreshnessProxyMonitor:
    """Checks BI asset last_updated time and upstream table freshness via lineage.

    Config keys:
        asset_id : str (REQUIRED)
            BI asset identifier (e.g. "dashboard/123").
        asset_type : str
            Type of BI asset: dashboard, report, workbook, explore, question.
        max_stale_hours : int
            Maximum acceptable hours since the asset was last updated (default: 24).
        check_upstream : bool
            Also check upstream table freshness via lineage (default: True).
    """

    monitor_type = "bi_freshness_proxy"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.asset_id: str = str(self.config.get("asset_id", ""))
        self.asset_type: str = self.config.get("asset_type", "dashboard")
        self.max_stale_hours: int = int(self.config.get("max_stale_hours", 24))
        self.check_upstream: bool = self.config.get("check_upstream", True)

    def execute(
        self,
        bi_client: Any,
        engine_store: Any = None,
    ) -> MonitorResult:
        """Check BI asset freshness.

        Args:
            bi_client: BI platform adapter with get_asset_metadata(asset_id) method.
            engine_store: Optional lineage engine store for upstream freshness checks.
        """
        target = f"bi:{self.asset_id}"

        if not self.asset_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No asset_id configured.",
            )

        try:
            metadata = bi_client.get_asset_metadata(self.asset_id)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch BI asset metadata: {e}",
            )

        if not metadata:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"BI asset {self.asset_id} not found.",
            )

        # Check asset last_updated
        last_updated = metadata.get("last_updated") or metadata.get("updated_at")
        now = datetime.now(timezone.utc)
        details: Dict[str, Any] = {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "max_stale_hours": self.max_stale_hours,
        }

        if last_updated:
            if isinstance(last_updated, str):
                try:
                    last_updated = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                except ValueError:
                    last_updated = None

            if last_updated:
                hours_since = (now - last_updated).total_seconds() / 3600
                details["hours_since_update"] = round(hours_since, 1)
                details["last_updated"] = last_updated.isoformat()

                if hours_since > self.max_stale_hours:
                    return MonitorResult(
                        monitor_type=self.monitor_type,
                        target_fqn=target,
                        status=MonitorStatus.FAIL,
                        value=round(hours_since, 1),
                        threshold=float(self.max_stale_hours),
                        message=f"BI asset stale: last updated {round(hours_since, 1)}h ago (threshold: {self.max_stale_hours}h).",
                        details=details,
                    )

                if hours_since > self.max_stale_hours * 0.75:
                    return MonitorResult(
                        monitor_type=self.monitor_type,
                        target_fqn=target,
                        status=MonitorStatus.WARN,
                        value=round(hours_since, 1),
                        threshold=float(self.max_stale_hours),
                        message=f"BI asset approaching stale: {round(hours_since, 1)}h since update.",
                        details=details,
                    )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=details.get("hours_since_update"),
            threshold=float(self.max_stale_hours),
            message="BI asset is fresh.",
            details=details,
        )


# =============================================================================
# BI_UPSTREAM_BREAK_RISK — Upstream Break Risk
# =============================================================================

class BIUpstreamBreakRiskMonitor:
    """Counts failing monitors on upstream warehouse tables via lineage.

    Config keys:
        asset_id : str (REQUIRED)
            BI asset identifier.
        lookback_hours : int
            How far back to check monitor runs (default: 24).
    """

    monitor_type = "bi_upstream_break_risk"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.asset_id: str = str(self.config.get("asset_id", ""))
        self.lookback_hours: int = int(self.config.get("lookback_hours", 24))

    def execute(
        self,
        bi_client: Any = None,
        engine_store: Any = None,
        monitor_history_func: Any = None,
    ) -> MonitorResult:
        """Check upstream break risk.

        Args:
            bi_client: BI platform adapter (unused for this monitor).
            engine_store: Lineage engine store for upstream traversal.
            monitor_history_func: Callable(target_fqn, lookback_hours) -> List[dict]
                Returns recent monitor runs for a target FQN.
        """
        target = f"bi:{self.asset_id}"

        if not engine_store or not monitor_history_func:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.SKIPPED,
                message="No lineage store or monitor history available — skipping upstream break risk check.",
            )

        try:
            # Get upstream warehouse nodes from lineage
            upstream_nodes = engine_store.get_upstream(self.asset_id, depth=3)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to traverse upstream lineage: {e}",
            )

        if not upstream_nodes:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.PASS,
                message="No upstream nodes found in lineage.",
                details={"upstream_count": 0},
            )

        # Check monitor history for each upstream node
        failing_upstreams: List[Dict[str, Any]] = []
        total_checked = 0

        for node in upstream_nodes:
            try:
                runs = monitor_history_func(node.fqn, self.lookback_hours)
                if runs:
                    total_checked += 1
                    fail_runs = [r for r in runs if r.get("status") in ("FAIL", "ERROR")]
                    if fail_runs:
                        failing_upstreams.append({
                            "fqn": node.fqn,
                            "name": node.name,
                            "fail_count": len(fail_runs),
                        })
            except Exception:
                continue

        details = {
            "asset_id": self.asset_id,
            "upstream_nodes_total": len(upstream_nodes),
            "upstream_nodes_checked": total_checked,
            "failing_upstreams": failing_upstreams[:5],
            "lookback_hours": self.lookback_hours,
        }

        if len(failing_upstreams) > 2:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=float(len(failing_upstreams)),
                message=f"{len(failing_upstreams)} upstream dependencies have failing monitors.",
                details=details,
            )

        if failing_upstreams:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=float(len(failing_upstreams)),
                message=f"{len(failing_upstreams)} upstream dependency has failing monitors.",
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=0.0,
            message=f"All {total_checked} upstream dependencies healthy.",
            details=details,
        )


# =============================================================================
# BI_CONTENT_HEALTH — Content Health
# =============================================================================

class BIContentHealthMonitor:
    """Verifies BI asset exists, is accessible, and deliveries are not failing.

    Config keys:
        asset_id : str (REQUIRED)
            BI asset identifier.
        check_deliveries : bool
            Check scheduled delivery status (default: True).
    """

    monitor_type = "bi_content_health"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.asset_id: str = str(self.config.get("asset_id", ""))
        self.check_deliveries: bool = self.config.get("check_deliveries", True)

    def execute(self, bi_client: Any) -> MonitorResult:
        """Check BI asset content health.

        Args:
            bi_client: BI platform adapter with get_asset_metadata(asset_id) method
                and optionally get_delivery_status(asset_id) method.
        """
        target = f"bi:{self.asset_id}"

        if not self.asset_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No asset_id configured.",
            )

        # Check asset existence and accessibility
        try:
            metadata = bi_client.get_asset_metadata(self.asset_id)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"BI asset inaccessible: {e}",
            )

        if not metadata:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"BI asset {self.asset_id} not found or has been deleted.",
            )

        details: Dict[str, Any] = {
            "asset_id": self.asset_id,
            "asset_exists": True,
            "title": metadata.get("title") or metadata.get("name", ""),
        }

        # Check deliveries if enabled and supported
        if self.check_deliveries and hasattr(bi_client, "get_delivery_status"):
            try:
                deliveries = bi_client.get_delivery_status(self.asset_id)
                if deliveries:
                    failing = [d for d in deliveries if d.get("status") == "failed"]
                    details["delivery_count"] = len(deliveries)
                    details["failing_deliveries"] = len(failing)

                    if failing:
                        return MonitorResult(
                            monitor_type=self.monitor_type,
                            target_fqn=target,
                            status=MonitorStatus.WARN,
                            message=f"{len(failing)} scheduled delivery(s) failing.",
                            details=details,
                        )
            except Exception as e:
                details["delivery_check_error"] = str(e)

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            message="BI asset is healthy and accessible.",
            details=details,
        )


# =============================================================================
# BI_REFRESH_FAILURE — Refresh Failure
# =============================================================================

class BIRefreshFailureMonitor:
    """Detects BI dataset/extract refresh job failures.

    Config keys:
        asset_id : str (REQUIRED)
            BI dataset or extract identifier.
        workspace_id : str | None
            Power BI workspace ID or Tableau site ID.
        lookback_hours : int
            How far back to check refresh history (default: 24).
    """

    monitor_type = "bi_refresh_failure"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.asset_id: str = str(self.config.get("asset_id", ""))
        self.workspace_id: Optional[str] = self.config.get("workspace_id")
        self.lookback_hours: int = int(self.config.get("lookback_hours", 24))

    def execute(self, bi_client: Any) -> MonitorResult:
        """Check BI dataset refresh status.

        Args:
            bi_client: BI platform adapter with get_refresh_history(asset_id, ...) method.
        """
        target = f"bi:{self.asset_id}"

        if not self.asset_id:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No asset_id configured.",
            )

        if not hasattr(bi_client, "get_refresh_history"):
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.SKIPPED,
                message="BI platform does not support refresh history.",
            )

        try:
            refresh_history = bi_client.get_refresh_history(
                self.asset_id,
                workspace_id=self.workspace_id,
                lookback_hours=self.lookback_hours,
            )
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message=f"Failed to fetch refresh history: {e}",
            )

        if not refresh_history:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                message=f"No refresh runs found in the last {self.lookback_hours}h.",
                details={"asset_id": self.asset_id, "lookback_hours": self.lookback_hours},
            )

        # Check for failures
        failed = [r for r in refresh_history if r.get("status") in ("failed", "Failed", "FAILED")]
        succeeded = [r for r in refresh_history if r.get("status") in ("completed", "Completed", "COMPLETED", "succeeded")]

        details: Dict[str, Any] = {
            "asset_id": self.asset_id,
            "workspace_id": self.workspace_id,
            "lookback_hours": self.lookback_hours,
            "total_refreshes": len(refresh_history),
            "failed_count": len(failed),
            "succeeded_count": len(succeeded),
        }

        if failed and not succeeded:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=float(len(failed)),
                message=f"All {len(failed)} refresh(es) failed in the last {self.lookback_hours}h.",
                details=details,
            )

        if failed:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=float(len(failed)),
                message=f"{len(failed)} of {len(refresh_history)} refresh(es) failed.",
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=0.0,
            message=f"All {len(succeeded)} refresh(es) succeeded.",
            details=details,
        )


# =============================================================================
# Registry
# =============================================================================

BI_MONITOR_REGISTRY: Dict[str, type] = {
    "bi_freshness_proxy": BIFreshnessProxyMonitor,
    "bi_upstream_break_risk": BIUpstreamBreakRiskMonitor,
    "bi_content_health": BIContentHealthMonitor,
    "bi_refresh_failure": BIRefreshFailureMonitor,
}
