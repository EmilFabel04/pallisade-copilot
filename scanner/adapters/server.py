"""
Server adapter for SSH-based remote server inspection.

Connects via SSH using paramiko and provides methods for:
- System health checks (CPU, memory, disk, load)
- TLS/SSL certificate inspection and expiry detection
- Log file tailing and analysis
- systemd service status listing
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

try:
    import paramiko
except ImportError:
    paramiko = None  # type: ignore[assignment]


@dataclass
class CommandResult:
    """Result of executing a remote SSH command."""
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int = 0


@dataclass
class CertInfo:
    """Information about a TLS/SSL certificate."""
    path: str
    subject: str = ""
    issuer: str = ""
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    days_until_expiry: Optional[int] = None
    has_client_cert: bool = False
    chain_valid: bool = True
    error: Optional[str] = None


@dataclass
class DiskUsage:
    """Disk usage for a single mount point."""
    mount: str
    total_gb: float
    used_gb: float
    available_gb: float
    percent: float


@dataclass
class SystemHealth:
    """System health metrics."""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_total_gb: float = 0.0
    memory_used_gb: float = 0.0
    disk_usage: List[DiskUsage] = field(default_factory=list)
    load_avg: List[float] = field(default_factory=list)
    uptime_seconds: int = 0
    hostname: str = ""
    os_info: str = ""


@dataclass
class ServiceInfo:
    """systemd service status."""
    name: str
    status: str  # running, stopped, failed, inactive
    enabled: bool = False
    pid: Optional[int] = None


class ServerAdapter:
    """SSH-based adapter for remote server inspection."""

    def __init__(self) -> None:
        self._client: Optional["paramiko.SSHClient"] = None
        self._config: Dict[str, Any] = {}

    def connect(self, config: Dict[str, Any]) -> None:
        """Establish SSH connection to the server."""
        if paramiko is None:
            raise ImportError(
                "paramiko is required for server connections. "
                "Install it with: pip install paramiko"
            )

        self._config = config
        host = config["host"]
        port = int(config.get("port", 22))
        username = config.get("username", "root")
        auth_method = config.get("auth_method", "key")

        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: Dict[str, Any] = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": 15,
        }

        if auth_method == "key" and config.get("private_key"):
            # Load private key from string
            import io
            key_str = config["private_key"]
            passphrase = config.get("passphrase") or None
            try:
                pkey = paramiko.RSAKey.from_private_key(
                    io.StringIO(key_str), password=passphrase
                )
            except paramiko.SSHException:
                try:
                    pkey = paramiko.Ed25519Key.from_private_key(
                        io.StringIO(key_str), password=passphrase
                    )
                except paramiko.SSHException:
                    pkey = paramiko.ECDSAKey.from_private_key(
                        io.StringIO(key_str), password=passphrase
                    )
            connect_kwargs["pkey"] = pkey
        elif config.get("password"):
            connect_kwargs["password"] = config["password"]

        logger.info(
            "[ServerAdapter] Connecting",
            host=host,
            port=port,
            username=username,
            auth_method=auth_method,
        )
        self._client.connect(**connect_kwargs)

    def disconnect(self) -> None:
        """Close the SSH connection."""
        if self._client:
            self._client.close()
            self._client = None

    def test_connection(self) -> Dict[str, Any]:
        """Test the connection and return basic server info."""
        hostname_result = self.execute_command("hostname")
        os_result = self.execute_command(
            "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"' "
            "|| uname -s"
        )
        uptime_result = self.execute_command("cat /proc/uptime 2>/dev/null | cut -d' ' -f1 || uptime")

        hostname = hostname_result.stdout.strip()
        os_info = os_result.stdout.strip() or "Unknown"

        uptime_str = uptime_result.stdout.strip()
        try:
            uptime_seconds = int(float(uptime_str))
        except (ValueError, TypeError):
            uptime_seconds = 0

        return {
            "success": True,
            "hostname": hostname,
            "os": os_info,
            "uptime_seconds": uptime_seconds,
            "message": f"Connected to {hostname} ({os_info})",
        }

    def execute_command(self, command: str, timeout: int = 30) -> CommandResult:
        """Execute a command on the remote server."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        import time
        start = time.monotonic()

        _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")

        duration_ms = int((time.monotonic() - start) * 1000)

        return CommandResult(
            stdout=out,
            stderr=err,
            exit_code=exit_code,
            duration_ms=duration_ms,
        )

    def check_certificates(
        self, paths: Optional[List[str]] = None
    ) -> List[CertInfo]:
        """Check TLS/SSL certificates on the server.

        If paths are not provided, scans common certificate locations.
        For each cert, checks expiry and whether a client cert exists alongside it.
        """
        if not paths:
            # Discover certificate files
            discover_cmd = (
                "find /etc/ssl/certs /etc/pki/tls/certs /etc/letsencrypt/live "
                "/etc/ssl/private 2>/dev/null "
                "-name '*.pem' -o -name '*.crt' -o -name '*.cert' "
                "| head -50"
            )
            result = self.execute_command(discover_cmd)
            paths = [
                p.strip() for p in result.stdout.strip().split("\n") if p.strip()
            ]

        if not paths:
            return []

        certs: List[CertInfo] = []
        for cert_path in paths:
            cert_info = self._inspect_certificate(cert_path)
            if cert_info:
                certs.append(cert_info)

        return certs

    def _inspect_certificate(self, cert_path: str) -> Optional[CertInfo]:
        """Inspect a single certificate file."""
        cmd = (
            f"openssl x509 -in {cert_path} -noout "
            f"-subject -issuer -dates -purpose 2>/dev/null"
        )
        result = self.execute_command(cmd, timeout=10)

        if result.exit_code != 0:
            return CertInfo(path=cert_path, error=f"Cannot read certificate: {result.stderr.strip()}")

        output = result.stdout
        info = CertInfo(path=cert_path)

        # Parse subject
        subject_match = re.search(r"subject\s*=\s*(.+)", output)
        if subject_match:
            info.subject = subject_match.group(1).strip()

        # Parse issuer
        issuer_match = re.search(r"issuer\s*=\s*(.+)", output)
        if issuer_match:
            info.issuer = issuer_match.group(1).strip()

        # Parse dates
        not_before_match = re.search(r"notBefore\s*=\s*(.+)", output)
        if not_before_match:
            info.not_before = not_before_match.group(1).strip()

        not_after_match = re.search(r"notAfter\s*=\s*(.+)", output)
        if not_after_match:
            date_str = not_after_match.group(1).strip()
            info.not_after = date_str
            try:
                # Parse OpenSSL date format: "Mon DD HH:MM:SS YYYY GMT"
                expiry = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
                expiry = expiry.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                info.days_until_expiry = (expiry - now).days
            except (ValueError, TypeError):
                pass

        # Check if this is a server cert and look for a matching client cert
        is_server = "SSL server" in output or "TLS Web Server" in output
        is_client = "SSL client" in output or "TLS Web Client" in output

        if is_server and not is_client:
            # Look for a client cert in the same directory
            import os
            cert_dir = os.path.dirname(cert_path)
            cert_name = os.path.basename(cert_path)

            # Common client cert naming patterns
            client_patterns = [
                cert_name.replace("server", "client"),
                cert_name.replace(".crt", "-client.crt"),
                cert_name.replace(".pem", "-client.pem"),
                "client.crt",
                "client.pem",
                "client-cert.pem",
            ]

            for pattern in client_patterns:
                check_cmd = f"test -f {cert_dir}/{pattern} && echo 'exists'"
                check_result = self.execute_command(check_cmd, timeout=5)
                if "exists" in check_result.stdout:
                    info.has_client_cert = True
                    break

        if is_client:
            info.has_client_cert = True

        return info

    def get_system_health(self) -> SystemHealth:
        """Get system health metrics (CPU, memory, disk, load)."""
        health = SystemHealth()

        # Hostname
        result = self.execute_command("hostname")
        health.hostname = result.stdout.strip()

        # OS info
        result = self.execute_command(
            "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"' "
            "|| uname -s"
        )
        health.os_info = result.stdout.strip()

        # CPU usage (1-second sample)
        result = self.execute_command(
            "top -bn1 2>/dev/null | grep 'Cpu(s)' | awk '{print $2}' "
            "|| mpstat 1 1 2>/dev/null | tail -1 | awk '{print 100-$NF}'"
        )
        try:
            health.cpu_percent = float(result.stdout.strip().replace(",", "."))
        except (ValueError, TypeError):
            pass

        # Memory
        result = self.execute_command("free -b | grep Mem")
        if result.stdout.strip():
            parts = result.stdout.strip().split()
            if len(parts) >= 3:
                try:
                    total = int(parts[1])
                    used = int(parts[2])
                    health.memory_total_gb = round(total / (1024**3), 2)
                    health.memory_used_gb = round(used / (1024**3), 2)
                    health.memory_percent = round(
                        (used / total) * 100, 1
                    ) if total > 0 else 0
                except (ValueError, IndexError):
                    pass

        # Disk usage
        result = self.execute_command("df -B1 --output=target,size,used,avail,pcent 2>/dev/null | tail -n +2 || df -k | tail -n +2")
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 5:
                try:
                    mount = parts[0]
                    # Skip pseudo-filesystems
                    if mount.startswith(("/dev", "/run", "/sys", "/proc", "/snap")):
                        if not mount.startswith("/dev/"):
                            continue
                    total_b = int(parts[1])
                    used_b = int(parts[2])
                    avail_b = int(parts[3])
                    pct_str = parts[4].rstrip("%")
                    health.disk_usage.append(DiskUsage(
                        mount=mount,
                        total_gb=round(total_b / (1024**3), 2),
                        used_gb=round(used_b / (1024**3), 2),
                        available_gb=round(avail_b / (1024**3), 2),
                        percent=float(pct_str),
                    ))
                except (ValueError, IndexError):
                    continue

        # Load average
        result = self.execute_command("cat /proc/loadavg 2>/dev/null || uptime | awk -F'load average:' '{print $2}'")
        load_str = result.stdout.strip()
        if load_str:
            try:
                parts = load_str.replace(",", " ").split()
                health.load_avg = [float(parts[i]) for i in range(min(3, len(parts)))]
            except (ValueError, IndexError):
                pass

        # Uptime
        result = self.execute_command("cat /proc/uptime 2>/dev/null | cut -d' ' -f1")
        try:
            health.uptime_seconds = int(float(result.stdout.strip()))
        except (ValueError, TypeError):
            pass

        return health

    def tail_log(self, path: str, lines: int = 100) -> str:
        """Read the last N lines of a log file."""
        result = self.execute_command(f"tail -n {lines} {path} 2>&1")
        return result.stdout

    def list_services(self) -> List[ServiceInfo]:
        """List systemd service status."""
        result = self.execute_command(
            "systemctl list-units --type=service --all --no-pager --no-legend 2>/dev/null "
            "| head -100"
        )

        services: List[ServiceInfo] = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 4:
                name = parts[0].replace(".service", "")
                # systemctl output: UNIT LOAD ACTIVE SUB DESCRIPTION...
                active = parts[2] if len(parts) > 2 else "unknown"
                sub = parts[3] if len(parts) > 3 else "unknown"

                status = "running" if sub == "running" else (
                    "failed" if active == "failed" or sub == "failed" else (
                        "stopped" if sub in ("dead", "exited") else "inactive"
                    )
                )

                services.append(ServiceInfo(
                    name=name,
                    status=status,
                    enabled=True,  # listed units are typically enabled
                ))

        return services
