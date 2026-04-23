"""
Infrastructure monitors.

Non-SQL monitors that inspect remote servers via SSH for:
- TLS/SSL certificate expiry and missing client certs
- System health (CPU, memory, disk)
- Log file error analysis
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import MonitorResult, MonitorStatus
from .stats import score_anomaly, build_confidence_info

import structlog

logger = structlog.get_logger()

# Infrastructure monitor types (not SQL-based)
INFRA_MONITOR_TYPES = {"certificate", "server_health", "log_analysis"}


class CertificateMonitor:
    """Monitors TLS/SSL certificate expiry and client cert presence.

    Config keys:
        cert_paths : list[str] | None
            Specific cert paths to check (auto-discovers if empty).
        warn_days : int
            Days before expiry to trigger WARN (default: 30).
        fail_days : int
            Days before expiry to trigger FAIL (default: 7).
    """

    monitor_type = "certificate"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.warn_days: int = int(self.config.get("warn_days", 30))
        self.fail_days: int = int(self.config.get("fail_days", 7))
        self.cert_paths: Optional[List[str]] = self.config.get("cert_paths")

    def execute(self, server_adapter: Any) -> MonitorResult:
        """Check certificates on the remote server."""
        try:
            certs = server_adapter.check_certificates(self.cert_paths)
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=server_adapter._config.get("host", "unknown"),
                status=MonitorStatus.ERROR,
                message=f"Certificate check failed: {e}",
            )

        if not certs:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=server_adapter._config.get("host", "unknown"),
                status=MonitorStatus.WARN,
                message="No certificates found on the server.",
                details={"certs_checked": 0},
            )

        target = server_adapter._config.get("host", "unknown")
        issues: List[str] = []
        warnings: List[str] = []
        cert_details: List[Dict[str, Any]] = []

        for cert in certs:
            detail: Dict[str, Any] = {
                "path": cert.path,
                "subject": cert.subject,
                "issuer": cert.issuer,
                "not_after": cert.not_after,
                "days_until_expiry": cert.days_until_expiry,
                "has_client_cert": cert.has_client_cert,
            }

            if cert.error:
                detail["error"] = cert.error
                warnings.append(f"{cert.path}: {cert.error}")
                cert_details.append(detail)
                continue

            # Check for missing client cert (the exact issue that inspired this feature)
            if not cert.has_client_cert and cert.subject:
                # Only flag if this looks like a server cert (has subject)
                issues.append(
                    f"{cert.path}: Server cert found but no matching client cert. "
                    f"Pipelines requiring mutual TLS will fail."
                )
                detail["missing_client_cert"] = True

            # Check expiry
            if cert.days_until_expiry is not None:
                if cert.days_until_expiry <= 0:
                    issues.append(
                        f"{cert.path}: Certificate EXPIRED "
                        f"({abs(cert.days_until_expiry)} days ago)"
                    )
                elif cert.days_until_expiry <= self.fail_days:
                    issues.append(
                        f"{cert.path}: Certificate expires in "
                        f"{cert.days_until_expiry} days (< {self.fail_days}d threshold)"
                    )
                elif cert.days_until_expiry <= self.warn_days:
                    warnings.append(
                        f"{cert.path}: Certificate expires in "
                        f"{cert.days_until_expiry} days (< {self.warn_days}d threshold)"
                    )

            cert_details.append(detail)

        # Determine overall status
        if issues:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                message=f"{len(issues)} certificate issue(s): {'; '.join(issues[:3])}",
                details={
                    "issues": issues,
                    "warnings": warnings,
                    "certs_checked": len(certs),
                    "certificates": cert_details,
                },
            )

        if warnings:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                message=f"{len(warnings)} certificate warning(s): {'; '.join(warnings[:3])}",
                details={
                    "warnings": warnings,
                    "certs_checked": len(certs),
                    "certificates": cert_details,
                },
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            message=f"All {len(certs)} certificates are valid.",
            details={
                "certs_checked": len(certs),
                "certificates": cert_details,
            },
        )


class ServerHealthMonitor:
    """Monitors server CPU, memory, and disk usage.

    Config keys:
        max_cpu : float
            CPU usage percentage threshold for FAIL (default: 90).
        max_memory : float
            Memory usage percentage threshold for FAIL (default: 90).
        max_disk : float
            Disk usage percentage threshold for FAIL (default: 85).
    """

    monitor_type = "server_health"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.max_cpu: float = float(self.config.get("max_cpu", 90))
        self.max_memory: float = float(self.config.get("max_memory", 90))
        self.max_disk: float = float(self.config.get("max_disk", 85))
        self.historical_cpu: Optional[List[float]] = self.config.get("historical_cpu")
        self.historical_memory: Optional[List[float]] = self.config.get("historical_memory")

    def execute(self, server_adapter: Any) -> MonitorResult:
        """Check system health on the remote server."""
        try:
            health = server_adapter.get_system_health()
        except Exception as e:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=server_adapter._config.get("host", "unknown"),
                status=MonitorStatus.ERROR,
                message=f"Health check failed: {e}",
            )

        target = server_adapter._config.get("host", "unknown")
        issues: List[str] = []
        warnings: List[str] = []

        # CPU check
        warn_cpu = self.max_cpu * 0.8
        if health.cpu_percent > self.max_cpu:
            issues.append(f"CPU at {health.cpu_percent:.1f}% (threshold: {self.max_cpu}%)")
        elif health.cpu_percent > warn_cpu:
            warnings.append(f"CPU at {health.cpu_percent:.1f}% (approaching {self.max_cpu}% limit)")

        # Memory check
        warn_memory = self.max_memory * 0.8
        if health.memory_percent > self.max_memory:
            issues.append(f"Memory at {health.memory_percent:.1f}% (threshold: {self.max_memory}%)")
        elif health.memory_percent > warn_memory:
            warnings.append(f"Memory at {health.memory_percent:.1f}% (approaching {self.max_memory}% limit)")

        # Disk check (any mount exceeding threshold)
        for disk in health.disk_usage:
            warn_disk = self.max_disk * 0.8
            if disk.percent > self.max_disk:
                issues.append(
                    f"Disk {disk.mount} at {disk.percent:.1f}% "
                    f"({disk.available_gb:.1f}GB free, threshold: {self.max_disk}%)"
                )
            elif disk.percent > warn_disk:
                warnings.append(
                    f"Disk {disk.mount} at {disk.percent:.1f}% "
                    f"({disk.available_gb:.1f}GB free)"
                )

        # Baseline-aware anomaly detection (complements hard thresholds)
        anomaly_notes: List[str] = []
        anomaly_details: Dict[str, Any] = {}
        if self.historical_cpu and len(self.historical_cpu) >= 3:
            cpu_score = score_anomaly(
                current=health.cpu_percent,
                baseline=self.historical_cpu,
                threshold=3.0,
                min_effect_size=5.0,
            )
            anomaly_details["cpu_anomaly"] = {
                "z_score": cpu_score.z_score,
                "baseline_mean": cpu_score.baseline_mean,
                "is_anomaly": cpu_score.is_anomaly,
                "confidence_pct": cpu_score.confidence_pct,
            }
            if cpu_score.is_anomaly and cpu_score.direction == "above":
                anomaly_notes.append(
                    f"CPU {health.cpu_percent:.1f}% is anomalously high "
                    f"(baseline mean: {cpu_score.baseline_mean:.1f}%, "
                    f"z-score: {cpu_score.z_score:.2f})"
                )

        if self.historical_memory and len(self.historical_memory) >= 3:
            mem_score = score_anomaly(
                current=health.memory_percent,
                baseline=self.historical_memory,
                threshold=3.0,
                min_effect_size=5.0,
            )
            anomaly_details["memory_anomaly"] = {
                "z_score": mem_score.z_score,
                "baseline_mean": mem_score.baseline_mean,
                "is_anomaly": mem_score.is_anomaly,
                "confidence_pct": mem_score.confidence_pct,
            }
            if mem_score.is_anomaly and mem_score.direction == "above":
                anomaly_notes.append(
                    f"Memory {health.memory_percent:.1f}% is anomalously high "
                    f"(baseline mean: {mem_score.baseline_mean:.1f}%, "
                    f"z-score: {mem_score.z_score:.2f})"
                )

        # Anomaly notes become warnings (hard thresholds always win)
        warnings.extend(anomaly_notes)

        details: Dict[str, Any] = {
            "hostname": health.hostname,
            "os": health.os_info,
            "cpu_percent": health.cpu_percent,
            "memory_percent": health.memory_percent,
            "memory_total_gb": health.memory_total_gb,
            "memory_used_gb": health.memory_used_gb,
            "load_avg": health.load_avg,
            "uptime_seconds": health.uptime_seconds,
            "disk_usage": [
                {
                    "mount": d.mount,
                    "percent": d.percent,
                    "total_gb": d.total_gb,
                    "used_gb": d.used_gb,
                    "available_gb": d.available_gb,
                }
                for d in health.disk_usage
            ],
            **anomaly_details,
        }

        if issues:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=max(health.cpu_percent, health.memory_percent),
                message=f"{len(issues)} health issue(s) on {health.hostname}: {'; '.join(issues[:3])}",
                details=details,
            )

        if warnings:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=max(health.cpu_percent, health.memory_percent),
                message=f"{len(warnings)} health warning(s) on {health.hostname}: {'; '.join(warnings[:3])}",
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=max(health.cpu_percent, health.memory_percent),
            message=(
                f"Server {health.hostname} is healthy — "
                f"CPU: {health.cpu_percent:.1f}%, "
                f"Memory: {health.memory_percent:.1f}%, "
                f"Load: {', '.join(f'{l:.2f}' for l in health.load_avg)}"
            ),
            details=details,
        )


class LogMonitor:
    """Monitors server logs for error patterns.

    Scans all log entries from the configured files, using grep on the
    server for efficient pattern matching.  Reports any errors found.

    Config keys:
        log_paths : list[str]
            Log file paths to check.
        error_patterns : list[str]
            Regex patterns to match (default: ["ERROR", "FATAL", "CRITICAL"]).
        lookback_days : int
            Only scan files modified within this many days (default: 20).
    """

    monitor_type = "log_analysis"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.log_paths: List[str] = self.config.get("log_paths", [])
        self.error_patterns: List[str] = self.config.get(
            "error_patterns", ["ERROR", "FATAL", "CRITICAL"]
        )
        self.lookback_days: int = int(self.config.get("lookback_days", 20))

    def execute(self, server_adapter: Any) -> MonitorResult:
        """Scan log files for error patterns using remote grep."""
        target = server_adapter._config.get("host", "unknown")

        if not self.log_paths:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.ERROR,
                message="No log_paths configured. Specify at least one log file path.",
            )

        total_errors = 0
        per_file: List[Dict[str, Any]] = []
        sample_errors: List[str] = []

        # Build grep pattern: "ERROR|FATAL|CRITICAL"
        grep_pattern = "|".join(self.error_patterns)

        for log_path in self.log_paths:
            try:
                # Check if file was modified within lookback window
                check_cmd = (
                    f"find {log_path} -mtime -{self.lookback_days} "
                    f"-type f 2>/dev/null | head -1"
                )
                check_result = server_adapter.execute_command(check_cmd, timeout=5)
                if not check_result.stdout.strip():
                    per_file.append({
                        "path": log_path,
                        "error_count": 0,
                        "skipped": True,
                        "reason": f"Not modified in last {self.lookback_days} days",
                    })
                    continue

                # Use grep -c for count, grep for samples — single pass
                count_cmd = (
                    f"grep -ciE '{grep_pattern}' {log_path} 2>/dev/null || echo 0"
                )
                count_result = server_adapter.execute_command(count_cmd, timeout=30)
                try:
                    error_count = int(count_result.stdout.strip())
                except ValueError:
                    error_count = 0
                total_errors += error_count

                # Get sample error lines (first 5 matches)
                if error_count > 0:
                    sample_cmd = (
                        f"grep -iE '{grep_pattern}' {log_path} 2>/dev/null | head -5"
                    )
                    sample_result = server_adapter.execute_command(sample_cmd, timeout=10)
                    for line in sample_result.stdout.strip().split("\n"):
                        if line.strip() and len(sample_errors) < 10:
                            sample_errors.append(
                                f"[{log_path}] {line.strip()[:200]}"
                            )

                per_file.append({
                    "path": log_path,
                    "error_count": error_count,
                })

            except Exception as e:
                per_file.append({
                    "path": log_path,
                    "error": str(e),
                })

        details: Dict[str, Any] = {
            "total_errors": total_errors,
            "files_checked": len(self.log_paths),
            "per_file": per_file,
            "sample_errors": sample_errors[:10],
            "patterns": self.error_patterns,
            "lookback_days": self.lookback_days,
        }

        if total_errors > 0:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=float(total_errors),
                message=(
                    f"Found {total_errors} error(s) across {len(self.log_paths)} log file(s) "
                    f"in the last {self.lookback_days} days"
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=0.0,
            message=(
                f"No errors found across {len(self.log_paths)} log file(s) "
                f"in the last {self.lookback_days} days"
            ),
            details=details,
        )


# Registry mapping monitor type strings to classes
INFRA_MONITOR_REGISTRY = {
    "certificate": CertificateMonitor,
    "server_health": ServerHealthMonitor,
    "log_analysis": LogMonitor,
}
