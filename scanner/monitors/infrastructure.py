"""
Infrastructure monitors.

Non-SQL monitors that inspect remote servers via SSH for:
- TLS/SSL certificate expiry and missing client certs
- System health (CPU, memory, disk)
- Log file error analysis
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import MonitorResult, MonitorStatus

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

    Config keys:
        log_paths : list[str]
            Log file paths to check.
        error_patterns : list[str]
            Regex patterns to match (default: ["ERROR", "FATAL", "CRITICAL"]).
        max_errors : int
            Max error count before FAIL (default: 10).
        lookback_lines : int
            Number of lines to tail (default: 1000).
    """

    monitor_type = "log_analysis"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.log_paths: List[str] = self.config.get("log_paths", [])
        self.error_patterns: List[str] = self.config.get(
            "error_patterns", ["ERROR", "FATAL", "CRITICAL"]
        )
        self.max_errors: int = int(self.config.get("max_errors", 10))
        self.lookback_lines: int = int(self.config.get("lookback_lines", 1000))

    def execute(self, server_adapter: Any) -> MonitorResult:
        """Scan log files for error patterns."""
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

        pattern = "|".join(self.error_patterns)
        regex = re.compile(pattern, re.IGNORECASE)

        for log_path in self.log_paths:
            try:
                content = server_adapter.tail_log(log_path, self.lookback_lines)
                matches = [
                    line for line in content.split("\n")
                    if line.strip() and regex.search(line)
                ]
                error_count = len(matches)
                total_errors += error_count

                per_file.append({
                    "path": log_path,
                    "error_count": error_count,
                    "lines_checked": len(content.split("\n")),
                })

                # Collect sample error lines
                for match_line in matches[:5]:
                    if len(sample_errors) < 10:
                        sample_errors.append(f"[{log_path}] {match_line.strip()[:200]}")

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
        }

        if total_errors > self.max_errors:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.FAIL,
                value=float(total_errors),
                threshold=float(self.max_errors),
                message=(
                    f"Found {total_errors} errors across {len(self.log_paths)} log file(s) "
                    f"(threshold: {self.max_errors})"
                ),
                details=details,
            )

        if total_errors > self.max_errors // 2:
            return MonitorResult(
                monitor_type=self.monitor_type,
                target_fqn=target,
                status=MonitorStatus.WARN,
                value=float(total_errors),
                threshold=float(self.max_errors),
                message=(
                    f"Found {total_errors} errors across {len(self.log_paths)} log file(s) "
                    f"(approaching threshold of {self.max_errors})"
                ),
                details=details,
            )

        return MonitorResult(
            monitor_type=self.monitor_type,
            target_fqn=target,
            status=MonitorStatus.PASS,
            value=float(total_errors),
            message=(
                f"Log analysis passed — {total_errors} error(s) found "
                f"across {len(self.log_paths)} file(s) (within {self.max_errors} threshold)"
            ),
            details=details,
        )


# Registry mapping monitor type strings to classes
INFRA_MONITOR_REGISTRY = {
    "certificate": CertificateMonitor,
    "server_health": ServerHealthMonitor,
    "log_analysis": LogMonitor,
}
