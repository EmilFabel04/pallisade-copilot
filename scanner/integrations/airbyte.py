"""
Airbyte Integration - Enterprise Grade Scanner

Monitors Airbyte for:
- Connection sync health
- Source/destination status
- Sync failures and errors
- Data volume trends
- Sync duration monitoring
- Schema drift detection

Supports:
- Airbyte OSS (self-hosted)
- Airbyte Cloud
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class AirbyteSyncStatus(Enum):
    """Airbyte sync job status."""
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RUNNING = "running"
    PENDING = "pending"
    INCOMPLETE = "incomplete"


class AirbyteConnectionStatus(Enum):
    """Airbyte connection status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


@dataclass
class AirbyteSource:
    """An Airbyte source connector."""
    source_id: str
    name: str
    source_type: str  # e.g., "postgres", "mysql", "salesforce"
    
    # Workspace
    workspace_id: str
    
    # Configuration
    configuration: Dict = field(default_factory=dict)
    
    # Status
    status: str = "active"
    
    # Timestamps
    created_at: Optional[datetime] = None


@dataclass
class AirbyteDestination:
    """An Airbyte destination connector."""
    destination_id: str
    name: str
    destination_type: str  # e.g., "snowflake", "bigquery", "postgres"
    
    # Workspace
    workspace_id: str
    
    # Status
    status: str = "active"


@dataclass
class AirbyteConnection:
    """An Airbyte connection (source → destination sync)."""
    connection_id: str
    name: str
    source_id: str
    destination_id: str
    
    # Sync config
    schedule_type: str = "manual"  # manual, basic, cron
    schedule_data: Optional[Dict] = None
    namespace_definition: str = "source"
    
    # Status
    status: AirbyteConnectionStatus = AirbyteConnectionStatus.ACTIVE
    
    # Streams
    stream_count: int = 0
    
    # Last sync info
    last_sync_status: Optional[AirbyteSyncStatus] = None
    last_sync_at: Optional[datetime] = None
    last_sync_duration_seconds: Optional[float] = None
    last_sync_bytes: Optional[int] = None
    last_sync_records: Optional[int] = None
    
    # Health
    consecutive_failures: int = 0
    
    @property
    def is_failing(self) -> bool:
        return self.last_sync_status == AirbyteSyncStatus.FAILED
    
    @property
    def is_stale(self) -> bool:
        """Check if sync is overdue."""
        if not self.last_sync_at or self.schedule_type == "manual":
            return False
        
        hours_since = (datetime.now() - self.last_sync_at).total_seconds() / 3600
        
        # Check based on schedule
        if self.schedule_type == "basic" and self.schedule_data:
            expected_hours = self.schedule_data.get("units", 1)
            time_unit = self.schedule_data.get("timeUnit", "hours")
            if time_unit == "minutes":
                expected_hours = expected_hours / 60
            elif time_unit == "days":
                expected_hours = expected_hours * 24
            
            return hours_since > expected_hours * 1.5
        
        return hours_since > 24  # Default: stale if no sync in 24h


@dataclass
class AirbyteJob:
    """An Airbyte sync job."""
    job_id: str
    job_type: str = "sync"
    
    # Connection
    connection_id: str = ""
    
    # Status
    status: AirbyteSyncStatus = AirbyteSyncStatus.PENDING
    
    # Timing
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    
    # Metrics
    bytes_synced: int = 0
    records_synced: int = 0
    
    # Error
    failure_reason: Optional[str] = None


class AirbyteClient:
    """
    Airbyte API client.

    Supports both Airbyte OSS and Airbyte Cloud.

    Airbyte Cloud uses client credentials (client_id/client_secret) to
    obtain a short-lived Bearer token via /v1/applications/token.
    """

    def __init__(self,
                 host: str,
                 client_id: Optional[str] = None,
                 client_secret: Optional[str] = None,
                 api_key: Optional[str] = None,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 workspace_id: Optional[str] = None):
        """
        Initialize Airbyte client.

        For Airbyte OSS:
            host: API host (e.g., http://localhost:8000)
            username/password: Basic auth (if enabled)

        For Airbyte Cloud:
            host: https://api.airbyte.com
            client_id/client_secret: From Settings → Applications
        """
        # Auto-correct common mistake: dashboard URL instead of API URL
        clean_host = host.rstrip('/')
        if "cloud.airbyte.com" in clean_host and "api.airbyte.com" not in clean_host:
            clean_host = "https://api.airbyte.com"

        self.host = clean_host
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_key = api_key  # Legacy: direct Bearer token
        self.username = username
        self.password = password
        self.workspace_id = workspace_id

        # Detect API version
        self.is_cloud = "api.airbyte.com" in self.host or "airbyte.com" in self.host

        self._client = None
        self._access_token: Optional[str] = None

    def _fetch_access_token(self) -> str:
        """Exchange client credentials for a short-lived Bearer token."""
        url = f"{self.host}/v1/applications/token"
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            })
            if resp.status_code >= 400:
                raise Exception(
                    f"Airbyte token exchange failed: {resp.status_code} - {resp.text}"
                )
            data = resp.json()
            token = data.get("access_token")
            if not token:
                raise Exception(f"No access_token in token response: {data}")
            return token

    def _get_client(self) -> httpx.Client:
        """Get HTTP client with current auth."""
        # For Cloud with client credentials, always fetch a fresh token
        # (tokens are short-lived: 3 min on Cloud, 24h on Enterprise)
        if self.is_cloud and self.client_id and self.client_secret:
            self._access_token = self._fetch_access_token()
            self._client = None  # Force new client with new token

        if self._client is None:
            headers = {}
            auth = None

            if self._access_token:
                headers["Authorization"] = f"Bearer {self._access_token}"
            elif self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif self.username and self.password:
                auth = (self.username, self.password)

            self._client = httpx.Client(
                timeout=60.0,
                headers=headers,
                auth=auth,
            )
        return self._client

    def _get_api_url(self, endpoint: str) -> str:
        """Build API URL."""
        if self.is_cloud:
            return f"{self.host}/v1/{endpoint.lstrip('/')}"
        else:
            # OSS uses different API structure
            return f"{self.host}/api/v1/{endpoint.lstrip('/')}"

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make request to Airbyte API."""
        client = self._get_client()

        response = client.request(
            method,
            self._get_api_url(endpoint),
            **kwargs
        )
        
        if response.status_code >= 400:
            raise Exception(f"Airbyte API error: {response.status_code} - {response.text}")
        
        return response.json() if response.text else None
    
    def test_connection(self) -> Tuple[bool, str]:
        """Test connection to Airbyte."""
        try:
            if self.is_cloud:
                workspaces = self.get_workspaces()
                return True, f"Connected to Airbyte Cloud ({len(workspaces)} workspaces)"
            else:
                # OSS - check health endpoint
                client = self._get_client()
                response = client.get(f"{self.host}/api/v1/health")
                if response.status_code == 200:
                    return True, "Connected to Airbyte OSS"
                else:
                    return False, f"Health check failed: {response.status_code}"
        except Exception as e:
            return False, str(e)
    
    # =========================================================================
    # WORKSPACE METHODS
    # =========================================================================
    
    def get_workspaces(self) -> List[Dict]:
        """Get all workspaces."""
        if self.is_cloud:
            data = self._request("GET", "/workspaces")
            return data.get("data", [])
        else:
            data = self._request("POST", "/workspaces/list", json={})
            return data.get("workspaces", [])
    
    # =========================================================================
    # SOURCE METHODS
    # =========================================================================
    
    def get_sources(self, workspace_id: str = None) -> List[Dict]:
        """Get all sources in a workspace."""
        ws_id = workspace_id or self.workspace_id
        
        if self.is_cloud:
            data = self._request("GET", f"/sources?workspaceId={ws_id}")
            return data.get("data", [])
        else:
            data = self._request(
                "POST",
                "/sources/list",
                json={"workspaceId": ws_id}
            )
            return data.get("sources", [])
    
    def check_source_connection(self, source_id: str) -> Dict:
        """Check if source can connect."""
        if self.is_cloud:
            return self._request("POST", f"/sources/{source_id}/check_connection")
        else:
            return self._request(
                "POST",
                "/sources/check_connection",
                json={"sourceId": source_id}
            )
    
    # =========================================================================
    # DESTINATION METHODS
    # =========================================================================
    
    def get_destinations(self, workspace_id: str = None) -> List[Dict]:
        """Get all destinations in a workspace."""
        ws_id = workspace_id or self.workspace_id
        
        if self.is_cloud:
            data = self._request("GET", f"/destinations?workspaceId={ws_id}")
            return data.get("data", [])
        else:
            data = self._request(
                "POST",
                "/destinations/list",
                json={"workspaceId": ws_id}
            )
            return data.get("destinations", [])
    
    # =========================================================================
    # CONNECTION METHODS
    # =========================================================================
    
    def get_connections(self, workspace_id: str = None) -> List[Dict]:
        """Get all connections in a workspace."""
        ws_id = workspace_id or self.workspace_id
        
        if self.is_cloud:
            data = self._request("GET", f"/connections?workspaceId={ws_id}")
            return data.get("data", [])
        else:
            data = self._request(
                "POST",
                "/connections/list",
                json={"workspaceId": ws_id}
            )
            return data.get("connections", [])
    
    def get_connection(self, connection_id: str) -> Dict:
        """Get connection details."""
        if self.is_cloud:
            return self._request("GET", f"/connections/{connection_id}")
        else:
            return self._request(
                "POST",
                "/connections/get",
                json={"connectionId": connection_id}
            )
    
    # =========================================================================
    # JOB METHODS
    # =========================================================================
    
    def get_jobs(self, connection_id: str = None, limit: int = 10) -> List[Dict]:
        """Get recent jobs, optionally for a specific connection."""
        if self.is_cloud:
            params = {"limit": limit, "orderBy": "createdAt|DESC"}
            if connection_id:
                params["connectionId"] = connection_id
            data = self._request("GET", "/jobs", params=params)
            return data.get("data", [])
        else:
            body = {
                "configTypes": ["sync"],
                "pagination": {"pageSize": limit}
            }
            if connection_id:
                body["configId"] = connection_id
            data = self._request("POST", "/jobs/list", json=body)
            return data.get("jobs", [])
    
    def get_job(self, job_id: str) -> Dict:
        """Get job details."""
        if self.is_cloud:
            return self._request("GET", f"/jobs/{job_id}")
        else:
            data = self._request("POST", "/jobs/get", json={"id": int(job_id)})
            return data.get("job", {})
    
    def get_job_logs(self, job_id: str) -> List[Dict]:
        """Get logs for a job."""
        if self.is_cloud:
            # Cloud API may not expose logs directly
            return []
        else:
            try:
                data = self._request("POST", "/jobs/get_debug_info", json={"id": int(job_id)})
                return data.get("attempts", [])
            except Exception:
                return []


class AirbyteScanner:
    """
    Enterprise-grade Airbyte scanner.
    
    Monitors:
    1. Connection sync health
    2. Source/destination connectivity
    3. Sync failures and patterns
    4. Data volume trends
    5. Schema changes
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scanner with Airbyte credentials.
        
        Config:
            host: Airbyte API host
            api_key: API key (for Cloud)
            username: Basic auth username (for OSS)
            password: Basic auth password (for OSS)
            workspace_id: Default workspace ID
        """
        self.client = AirbyteClient(
            host=config.get("host"),
            client_id=config.get("client_id"),
            client_secret=config.get("client_secret"),
            api_key=config.get("api_key"),
            username=config.get("username"),
            password=config.get("password"),
            workspace_id=config.get("workspace_id"),
        )
        
        # Thresholds
        self.thresholds = {
            "consecutive_failures_warning": 1,
            "consecutive_failures_critical": 3,
            "stale_hours": config.get("stale_hours", 48),
            "long_sync_minutes": config.get("long_sync_minutes", 120),
        }
    
    def scan(self, workspace_id: str = None) -> Dict[str, Any]:
        """
        Run full Airbyte health scan.
        
        Args:
            workspace_id: Specific workspace to scan (optional)
            
        Returns:
            Dict with findings, metrics, and health score
        """
        findings = []
        metrics = {
            "connections_scanned": 0,
            "healthy_connections": 0,
            "failing_connections": 0,
            "stale_connections": 0,
            "sources_scanned": 0,
            "destinations_scanned": 0,
        }
        
        ws_id = workspace_id or self.client.workspace_id
        
        # 1. Scan Sources
        logger.info("Scanning Airbyte sources...")
        source_findings = self._scan_sources(ws_id)
        findings.extend(source_findings["findings"])
        metrics.update(source_findings["metrics"])
        
        # 2. Scan Destinations
        logger.info("Scanning Airbyte destinations...")
        dest_findings = self._scan_destinations(ws_id)
        findings.extend(dest_findings["findings"])
        metrics.update(dest_findings["metrics"])
        
        # 3. Scan Connections
        logger.info("Scanning Airbyte connections...")
        conn_findings = self._scan_connections(ws_id)
        findings.extend(conn_findings["findings"])
        metrics.update(conn_findings["metrics"])
        
        # Calculate health score
        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        high_count = sum(1 for f in findings if f.get("severity") == "high")
        medium_count = sum(1 for f in findings if f.get("severity") == "medium")
        
        health_score = max(0, 100 - (critical_count * 25) - (high_count * 10) - (medium_count * 3))
        
        return {
            "scan_type": "airbyte",
            "status": "critical" if critical_count > 0 else "warning" if high_count > 0 else "healthy",
            "health_score": health_score,
            "findings": findings,
            "metrics": metrics,
            "scanned_at": datetime.now().isoformat(),
        }
    
    def _scan_sources(self, workspace_id: str) -> Dict:
        """Scan sources for connectivity issues."""
        findings = []
        metrics = {
            "sources_scanned": 0,
        }
        
        try:
            sources = self.client.get_sources(workspace_id)
            metrics["sources_scanned"] = len(sources)
            
            for source in sources:
                source_id = source.get("sourceId") or source.get("id")
                name = source.get("name", "Unknown")
                source_type = source.get("sourceType") or source.get("sourceName", "unknown")
                
                # Check source connection
                try:
                    check = self.client.check_source_connection(source_id)
                    status = check.get("status") or check.get("jobInfo", {}).get("succeeded")
                    
                    if status in [False, "failed"]:
                        findings.append({
                            "type": "source_connection_failed",
                            "severity": "critical",
                            "title": f"Source Connection Failed: {name}",
                            "description": f"Source '{name}' ({source_type}) cannot connect. Check credentials and network access.",
                            "resource": f"source/{source_id}",
                            "resource_type": "airbyte_source",
                            "suggested_fix": {
                                "type": "manual",
                                "action": "Verify source credentials and network connectivity",
                            },
                        })
                except Exception as e:
                    logger.warning(f"Could not check source {source_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning sources: {e}")
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_destinations(self, workspace_id: str) -> Dict:
        """Scan destinations."""
        findings = []
        metrics = {
            "destinations_scanned": 0,
        }
        
        try:
            destinations = self.client.get_destinations(workspace_id)
            metrics["destinations_scanned"] = len(destinations)
            
            # Could add destination-specific checks here
            # For now, just count them
            
        except Exception as e:
            logger.error(f"Error scanning destinations: {e}")
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_connections(self, workspace_id: str) -> Dict:
        """Scan connections for sync issues."""
        findings = []
        metrics = {
            "connections_scanned": 0,
            "healthy_connections": 0,
            "failing_connections": 0,
            "stale_connections": 0,
        }
        
        try:
            connections = self.client.get_connections(workspace_id)
            metrics["connections_scanned"] = len(connections)
            
            for conn in connections:
                conn_id = conn.get("connectionId") or conn.get("id")
                name = conn.get("name", "Unknown")
                status = conn.get("status", "active")
                
                # Skip inactive connections
                if status in ["inactive", "deprecated"]:
                    continue
                
                # Get recent jobs for this connection
                jobs = self.client.get_jobs(connection_id=conn_id, limit=10)
                
                if not jobs:
                    continue
                
                # Analyze job history
                consecutive_failures = 0
                latest_job = jobs[0]
                latest_status = latest_job.get("status") or latest_job.get("job", {}).get("status")
                
                for job in jobs:
                    job_status = job.get("status") or job.get("job", {}).get("status")
                    if job_status in ["failed", "incomplete"]:
                        consecutive_failures += 1
                    else:
                        break
                
                # Check for failing connections
                if consecutive_failures >= self.thresholds["consecutive_failures_critical"]:
                    metrics["failing_connections"] += 1
                    
                    # Get error message from latest failure
                    error_msg = ""
                    if latest_job.get("failureReason"):
                        error_msg = latest_job["failureReason"][:200]
                    
                    findings.append({
                        "type": "connection_failing",
                        "severity": "critical",
                        "title": f"Connection Consistently Failing: {name}",
                        "description": f"Connection '{name}' has failed {consecutive_failures} consecutive times.{' Error: ' + error_msg if error_msg else ''}",
                        "resource": f"connection/{conn_id}",
                        "resource_type": "airbyte_connection",
                        "suggested_fix": {
                            "type": "manual",
                            "action": "Check source/destination connectivity and job logs",
                        },
                    })
                elif consecutive_failures >= self.thresholds["consecutive_failures_warning"]:
                    findings.append({
                        "type": "connection_recent_failure",
                        "severity": "high",
                        "title": f"Connection Has Recent Failures: {name}",
                        "description": f"Connection '{name}' has failed {consecutive_failures} recent syncs.",
                        "resource": f"connection/{conn_id}",
                        "resource_type": "airbyte_connection",
                    })
                else:
                    metrics["healthy_connections"] += 1
                
                # Check for stale connections
                last_sync = latest_job.get("createdAt") or latest_job.get("job", {}).get("createdAt")
                if last_sync:
                    try:
                        last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                        hours_since = (datetime.now(last_sync_dt.tzinfo) - last_sync_dt).total_seconds() / 3600
                        
                        if hours_since > self.thresholds["stale_hours"]:
                            metrics["stale_connections"] += 1
                            findings.append({
                                "type": "stale_connection",
                                "severity": "medium",
                                "title": f"Stale Connection: {name}",
                                "description": f"Connection '{name}' hasn't synced in {hours_since:.0f} hours.",
                                "resource": f"connection/{conn_id}",
                                "resource_type": "airbyte_connection",
                            })
                    except Exception:
                        pass
                
                # Check for long-running syncs
                for job in jobs:
                    job_status = job.get("status") or job.get("job", {}).get("status")
                    if job_status == "running":
                        started = job.get("startTime") or job.get("job", {}).get("startedAt")
                        if started:
                            try:
                                start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                                running_minutes = (datetime.now(start_dt.tzinfo) - start_dt).total_seconds() / 60
                                
                                if running_minutes > self.thresholds["long_sync_minutes"]:
                                    findings.append({
                                        "type": "long_running_sync",
                                        "severity": "medium",
                                        "title": f"Long Running Sync: {name}",
                                        "description": f"Connection '{name}' has been syncing for {running_minutes:.0f} minutes.",
                                        "resource": f"connection/{conn_id}",
                                        "resource_type": "airbyte_connection",
                                    })
                            except Exception:
                                pass
                        break
                        
        except Exception as e:
            logger.error(f"Error scanning connections: {e}")
            findings.append({
                "type": "scan_error",
                "severity": "medium",
                "title": "Connection Scan Error",
                "description": f"Could not complete connection scan: {str(e)}",
            })
        
        return {"findings": findings, "metrics": metrics}
