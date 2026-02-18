"""
Server Infrastructure Endpoints

Test connection, health checks, and certificate inspection for Linux servers.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

import structlog

logger = structlog.get_logger()

router = APIRouter()


class ServerConfig(BaseModel):
    """SSH connection configuration."""
    host: str
    port: int = 22
    username: str = "root"
    auth_method: str = "key"
    private_key: Optional[str] = None
    password: Optional[str] = None
    passphrase: Optional[str] = None


class ServerTestResponse(BaseModel):
    """Response from server test connection."""
    success: bool
    hostname: str = ""
    os: str = ""
    uptime_seconds: int = 0
    message: str = ""


@router.post("/server/test-connection", response_model=ServerTestResponse)
async def test_server_connection(config: ServerConfig):
    """Test SSH connection to a remote server."""
    from scanner.adapters.server import ServerAdapter

    adapter = ServerAdapter()
    try:
        adapter.connect(config.model_dump())
        info = adapter.test_connection()
        return ServerTestResponse(
            success=True,
            hostname=info.get("hostname", ""),
            os=info.get("os", ""),
            uptime_seconds=info.get("uptime_seconds", 0),
            message=info.get("message", "Connected successfully"),
        )
    except Exception as e:
        logger.error("[Server] Test connection failed", error=str(e))
        return ServerTestResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )
    finally:
        adapter.disconnect()


class CertCheckRequest(BaseModel):
    """Request to check certificates on a server."""
    host: str
    port: int = 22
    username: str = "root"
    auth_method: str = "key"
    private_key: Optional[str] = None
    password: Optional[str] = None
    passphrase: Optional[str] = None
    cert_paths: Optional[List[str]] = None


@router.post("/server/check-certificates")
async def check_certificates(req: CertCheckRequest):
    """Check TLS/SSL certificates on a remote server."""
    from scanner.adapters.server import ServerAdapter

    adapter = ServerAdapter()
    try:
        adapter.connect(req.model_dump(exclude={"cert_paths"}))
        certs = adapter.check_certificates(req.cert_paths)
        return {
            "success": True,
            "certificates": [
                {
                    "path": c.path,
                    "subject": c.subject,
                    "issuer": c.issuer,
                    "not_after": c.not_after,
                    "days_until_expiry": c.days_until_expiry,
                    "has_client_cert": c.has_client_cert,
                    "error": c.error,
                }
                for c in certs
            ],
        }
    except Exception as e:
        logger.error("[Server] Certificate check failed", error=str(e))
        return {"success": False, "message": str(e), "certificates": []}
    finally:
        adapter.disconnect()


@router.post("/server/health")
async def server_health(config: ServerConfig):
    """Get system health metrics from a remote server."""
    from scanner.adapters.server import ServerAdapter

    adapter = ServerAdapter()
    try:
        adapter.connect(config.model_dump())
        health = adapter.get_system_health()
        return {
            "success": True,
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
                    "available_gb": d.available_gb,
                }
                for d in health.disk_usage
            ],
        }
    except Exception as e:
        logger.error("[Server] Health check failed", error=str(e))
        return {"success": False, "message": str(e)}
    finally:
        adapter.disconnect()
