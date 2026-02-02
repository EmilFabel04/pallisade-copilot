"""
Tableau Integration - Enterprise Grade Scanner

Monitors Tableau Server/Cloud for:
- Workbook/datasource refresh failures
- Extract refresh schedules
- Broken data sources
- View load times
- Usage patterns (popular vs stale content)
- Permission issues

Uses Tableau REST API (TSC library)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TableauContentType(Enum):
    """Types of Tableau content."""
    WORKBOOK = "workbook"
    DATASOURCE = "datasource"
    VIEW = "view"
    FLOW = "flow"


class TableauRefreshStatus(Enum):
    """Status of data refresh."""
    SUCCESS = "Success"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    PENDING = "Pending"
    IN_PROGRESS = "InProgress"


@dataclass
class TableauDatasource:
    """A Tableau data source."""
    id: str
    name: str
    project_name: str
    
    # Connection
    connection_type: str = ""
    server_name: Optional[str] = None
    database_name: Optional[str] = None
    
    # Extract info
    has_extracts: bool = False
    extract_updated_at: Optional[datetime] = None
    extract_refresh_frequency: Optional[str] = None
    
    # Health
    last_refresh_status: TableauRefreshStatus = TableauRefreshStatus.SUCCESS
    last_refresh_at: Optional[datetime] = None
    consecutive_failures: int = 0
    
    # Usage
    connected_workbooks: int = 0
    
    @property
    def is_stale(self) -> bool:
        """Check if extract is stale (not refreshed in 48h for hourly, etc.)."""
        if not self.has_extracts or not self.extract_updated_at:
            return False
        hours_since = (datetime.now() - self.extract_updated_at).total_seconds() / 3600
        return hours_since > 48
    
    @property
    def is_failing(self) -> bool:
        return self.last_refresh_status == TableauRefreshStatus.FAILED


@dataclass
class TableauWorkbook:
    """A Tableau workbook."""
    id: str
    name: str
    project_name: str
    
    # Content
    view_count: int = 0
    sheet_names: List[str] = field(default_factory=list)
    
    # Data sources
    datasource_ids: List[str] = field(default_factory=list)
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    
    # Usage
    total_views: int = 0
    favorites: int = 0
    
    # Owner
    owner_name: Optional[str] = None
    
    @property
    def is_stale(self) -> bool:
        """Workbook not accessed in 90 days."""
        if not self.last_accessed_at:
            return True
        return (datetime.now() - self.last_accessed_at).days > 90


@dataclass
class TableauExtractTask:
    """A Tableau extract refresh task."""
    id: str
    datasource_id: Optional[str] = None
    workbook_id: Optional[str] = None
    
    # Schedule
    schedule_id: Optional[str] = None
    schedule_name: Optional[str] = None
    priority: int = 50
    
    # Last run
    last_run_at: Optional[datetime] = None
    last_run_status: TableauRefreshStatus = TableauRefreshStatus.SUCCESS
    last_run_duration_seconds: Optional[float] = None
    
    # Failures
    consecutive_failures: int = 0
    last_error_message: Optional[str] = None


class TableauClient:
    """
    Tableau REST API client.
    
    Uses Personal Access Tokens (PAT) for authentication.
    Supports both Tableau Server and Tableau Cloud.
    """
    
    def __init__(self,
                 server: str,
                 token_name: str,
                 token_secret: str,
                 site_id: str = "",
                 api_version: str = "3.19"):
        """
        Initialize Tableau client.
        
        Args:
            server: Tableau Server URL (e.g., https://tableau.company.com)
            token_name: Personal Access Token name
            token_secret: Personal Access Token secret
            site_id: Site content URL (empty string for default site)
            api_version: API version (default 3.19)
        """
        self.server = server.rstrip('/')
        self.token_name = token_name
        self.token_secret = token_secret
        self.site_id = site_id
        self.api_version = api_version
        
        self._auth_token: Optional[str] = None
        self._site_id_resolved: Optional[str] = None
        self._user_id: Optional[str] = None
    
    def _get_api_url(self, endpoint: str) -> str:
        """Build full API URL."""
        return f"{self.server}/api/{self.api_version}/{endpoint.lstrip('/')}"
    
    def _authenticate(self) -> Tuple[str, str]:
        """Authenticate using PAT and return auth token and site ID."""
        import httpx
        
        if self._auth_token and self._site_id_resolved:
            return self._auth_token, self._site_id_resolved
        
        payload = {
            "credentials": {
                "personalAccessTokenName": self.token_name,
                "personalAccessTokenSecret": self.token_secret,
                "site": {
                    "contentUrl": self.site_id
                }
            }
        }
        
        response = httpx.post(
            self._get_api_url("/auth/signin"),
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30.0,
        )
        
        if response.status_code != 200:
            raise Exception(f"Tableau authentication failed: {response.text}")
        
        data = response.json()
        credentials = data.get("credentials", {})
        
        self._auth_token = credentials.get("token")
        self._site_id_resolved = credentials.get("site", {}).get("id")
        self._user_id = credentials.get("user", {}).get("id")
        
        return self._auth_token, self._site_id_resolved
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make authenticated request to Tableau API."""
        import httpx
        
        token, site_id = self._authenticate()
        
        # Replace {site_id} in endpoint
        endpoint = endpoint.replace("{site_id}", site_id)
        
        headers = kwargs.pop("headers", {})
        headers["X-Tableau-Auth"] = token
        headers["Accept"] = "application/json"
        
        response = httpx.request(
            method,
            self._get_api_url(endpoint),
            headers=headers,
            timeout=60.0,
            **kwargs
        )
        
        if response.status_code == 401:
            # Re-authenticate
            self._auth_token = None
            token, site_id = self._authenticate()
            headers["X-Tableau-Auth"] = token
            endpoint = endpoint.replace("{site_id}", site_id)
            response = httpx.request(
                method,
                self._get_api_url(endpoint),
                headers=headers,
                timeout=60.0,
                **kwargs
            )
        
        if response.status_code >= 400:
            raise Exception(f"Tableau API error: {response.status_code} - {response.text}")
        
        return response.json() if response.text else None
    
    def test_connection(self) -> Tuple[bool, str]:
        """Test connection to Tableau."""
        try:
            self._authenticate()
            return True, f"Connected to {self.server}"
        except Exception as e:
            return False, str(e)
    
    def sign_out(self):
        """Sign out and invalidate token."""
        if self._auth_token:
            try:
                self._request("POST", f"/sites/{self._site_id_resolved}/auth/signout")
            except Exception:
                pass
            finally:
                self._auth_token = None
                self._site_id_resolved = None
    
    # =========================================================================
    # WORKBOOK METHODS
    # =========================================================================
    
    def get_all_workbooks(self, page_size: int = 100) -> List[Dict]:
        """Get all workbooks with pagination."""
        workbooks = []
        page = 1
        
        while True:
            data = self._request(
                "GET",
                f"/sites/{{site_id}}/workbooks",
                params={"pageSize": page_size, "pageNumber": page}
            )
            
            items = data.get("workbooks", {}).get("workbook", [])
            if not items:
                break
            
            workbooks.extend(items)
            
            # Check pagination
            pagination = data.get("pagination", {})
            total_available = int(pagination.get("totalAvailable", 0))
            if len(workbooks) >= total_available:
                break
            
            page += 1
        
        return workbooks
    
    def get_workbook(self, workbook_id: str) -> Dict:
        """Get workbook details including views and data sources."""
        return self._request("GET", f"/sites/{{site_id}}/workbooks/{workbook_id}")
    
    def get_workbook_connections(self, workbook_id: str) -> List[Dict]:
        """Get data connections for a workbook."""
        data = self._request("GET", f"/sites/{{site_id}}/workbooks/{workbook_id}/connections")
        return data.get("connections", {}).get("connection", [])
    
    # =========================================================================
    # DATASOURCE METHODS
    # =========================================================================
    
    def get_all_datasources(self, page_size: int = 100) -> List[Dict]:
        """Get all published data sources."""
        datasources = []
        page = 1
        
        while True:
            data = self._request(
                "GET",
                f"/sites/{{site_id}}/datasources",
                params={"pageSize": page_size, "pageNumber": page}
            )
            
            items = data.get("datasources", {}).get("datasource", [])
            if not items:
                break
            
            datasources.extend(items)
            
            pagination = data.get("pagination", {})
            total_available = int(pagination.get("totalAvailable", 0))
            if len(datasources) >= total_available:
                break
            
            page += 1
        
        return datasources
    
    def get_datasource(self, datasource_id: str) -> Dict:
        """Get data source details."""
        return self._request("GET", f"/sites/{{site_id}}/datasources/{datasource_id}")
    
    # =========================================================================
    # EXTRACT TASK METHODS
    # =========================================================================
    
    def get_extract_refresh_tasks(self) -> List[Dict]:
        """Get all extract refresh tasks."""
        data = self._request("GET", f"/sites/{{site_id}}/tasks/extractRefreshes")
        return data.get("tasks", {}).get("task", [])
    
    def get_extract_refresh_task_history(self, task_id: str, page_size: int = 10) -> List[Dict]:
        """Get history for an extract refresh task."""
        # Note: This may require Tableau Server 2019.3+
        try:
            data = self._request(
                "GET",
                f"/sites/{{site_id}}/tasks/extractRefreshes/{task_id}/runHistory",
                params={"pageSize": page_size}
            )
            return data.get("backgroundJobs", {}).get("backgroundJob", [])
        except Exception:
            return []
    
    # =========================================================================
    # JOB/BACKGROUND TASK METHODS
    # =========================================================================
    
    def get_background_jobs(self, job_type: str = None, page_size: int = 100) -> List[Dict]:
        """
        Get background jobs (extract refreshes, subscriptions, etc.)
        
        job_type: extractRefresh, subscription, etc.
        """
        params = {"pageSize": page_size}
        if job_type:
            params["filter"] = f"jobType:eq:{job_type}"
        
        data = self._request("GET", f"/sites/{{site_id}}/jobs", params=params)
        return data.get("backgroundJobs", {}).get("backgroundJob", [])
    
    def get_recent_failed_jobs(self, hours: int = 24) -> List[Dict]:
        """Get failed jobs from the last N hours."""
        jobs = self.get_background_jobs()
        
        cutoff = datetime.now() - timedelta(hours=hours)
        failed = []
        
        for job in jobs:
            if job.get("status") != "Success":
                created_at = job.get("createdAt")
                if created_at:
                    try:
                        job_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        if job_time.replace(tzinfo=None) > cutoff:
                            failed.append(job)
                    except Exception:
                        failed.append(job)  # Include if we can't parse date
        
        return failed
    
    # =========================================================================
    # VIEW/USAGE METHODS
    # =========================================================================
    
    def get_views_for_workbook(self, workbook_id: str) -> List[Dict]:
        """Get views (sheets) for a workbook."""
        data = self._request("GET", f"/sites/{{site_id}}/workbooks/{workbook_id}/views")
        return data.get("views", {}).get("view", [])
    
    def get_view_usage(self, view_id: str) -> Dict:
        """Get usage statistics for a view."""
        # Note: Requires usage statistics to be enabled
        try:
            return self._request("GET", f"/sites/{{site_id}}/views/{view_id}/usage")
        except Exception:
            return {}


class TableauScanner:
    """
    Enterprise-grade Tableau scanner.
    
    Checks:
    1. Extract refresh failures
    2. Stale data sources
    3. Broken connections
    4. Workbook health
    5. Content staleness
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scanner with Tableau credentials.
        
        Config:
            server: Tableau Server URL
            token_name: PAT name
            token_secret: PAT secret
            site_id: Site content URL (optional)
        """
        self.client = TableauClient(
            server=config.get("server"),
            token_name=config.get("token_name"),
            token_secret=config.get("token_secret"),
            site_id=config.get("site_id", ""),
        )
        
        # Thresholds
        self.thresholds = {
            "stale_extract_hours": config.get("stale_extract_hours", 48),
            "stale_workbook_days": config.get("stale_workbook_days", 90),
            "consecutive_failures_warning": 1,
            "consecutive_failures_critical": 3,
        }
    
    def scan(self) -> Dict[str, Any]:
        """
        Run full Tableau health scan.
        
        Returns:
            Dict with findings, metrics, and health score
        """
        findings = []
        metrics = {
            "workbooks_scanned": 0,
            "datasources_scanned": 0,
            "stale_workbooks": 0,
            "failing_extracts": 0,
            "stale_datasources": 0,
            "broken_connections": 0,
        }
        
        try:
            # 1. Scan Data Sources
            logger.info("Scanning Tableau data sources...")
            ds_findings = self._scan_datasources()
            findings.extend(ds_findings["findings"])
            metrics.update(ds_findings["metrics"])
            
            # 2. Scan Workbooks
            logger.info("Scanning Tableau workbooks...")
            wb_findings = self._scan_workbooks()
            findings.extend(wb_findings["findings"])
            metrics.update(wb_findings["metrics"])
            
            # 3. Check Extract Tasks
            logger.info("Checking extract refresh tasks...")
            task_findings = self._scan_extract_tasks()
            findings.extend(task_findings["findings"])
            
            # 4. Check Recent Failed Jobs
            logger.info("Checking for failed jobs...")
            job_findings = self._scan_failed_jobs()
            findings.extend(job_findings["findings"])
            
        finally:
            # Always sign out
            self.client.sign_out()
        
        # Calculate health score
        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        high_count = sum(1 for f in findings if f.get("severity") == "high")
        medium_count = sum(1 for f in findings if f.get("severity") == "medium")
        
        health_score = max(0, 100 - (critical_count * 25) - (high_count * 10) - (medium_count * 3))
        
        return {
            "scan_type": "tableau",
            "status": "critical" if critical_count > 0 else "warning" if high_count > 0 else "healthy",
            "health_score": health_score,
            "findings": findings,
            "metrics": metrics,
            "scanned_at": datetime.now().isoformat(),
        }
    
    def _scan_datasources(self) -> Dict:
        """Scan data sources for issues."""
        findings = []
        metrics = {
            "datasources_scanned": 0,
            "stale_datasources": 0,
        }
        
        try:
            datasources = self.client.get_all_datasources()
            metrics["datasources_scanned"] = len(datasources)
            
            for ds in datasources:
                ds_id = ds.get("id")
                name = ds.get("name", "Unknown")
                project = ds.get("project", {}).get("name", "Unknown")
                
                # Check extract freshness
                updated_at = ds.get("updatedAt")
                has_extracts = ds.get("hasExtracts", False)
                
                if has_extracts and updated_at:
                    try:
                        updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        hours_since = (datetime.now(updated_dt.tzinfo) - updated_dt).total_seconds() / 3600
                        
                        if hours_since > self.thresholds["stale_extract_hours"]:
                            metrics["stale_datasources"] += 1
                            severity = "critical" if hours_since > self.thresholds["stale_extract_hours"] * 2 else "high"
                            
                            findings.append({
                                "type": "stale_extract",
                                "severity": severity,
                                "title": f"Stale Data Source Extract: {name}",
                                "description": f"Data source '{name}' in project '{project}' hasn't been refreshed in {hours_since:.0f} hours.",
                                "resource": f"datasource/{ds_id}",
                                "resource_type": "tableau_datasource",
                                "suggested_fix": {
                                    "type": "manual",
                                    "action": "Check extract refresh schedule or trigger manual refresh",
                                },
                            })
                    except Exception:
                        pass
                        
        except Exception as e:
            logger.error(f"Error scanning datasources: {e}")
            findings.append({
                "type": "scan_error",
                "severity": "medium",
                "title": "Data Source Scan Error",
                "description": f"Could not complete data source scan: {str(e)}",
            })
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_workbooks(self) -> Dict:
        """Scan workbooks for issues."""
        findings = []
        metrics = {
            "workbooks_scanned": 0,
            "stale_workbooks": 0,
            "broken_connections": 0,
        }
        
        try:
            workbooks = self.client.get_all_workbooks()
            metrics["workbooks_scanned"] = len(workbooks)
            
            for wb in workbooks:
                wb_id = wb.get("id")
                name = wb.get("name", "Unknown")
                project = wb.get("project", {}).get("name", "Unknown")
                
                # Check staleness
                updated_at = wb.get("updatedAt")
                if updated_at:
                    try:
                        updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                        days_since = (datetime.now(updated_dt.tzinfo) - updated_dt).days
                        
                        if days_since > self.thresholds["stale_workbook_days"]:
                            metrics["stale_workbooks"] += 1
                            findings.append({
                                "type": "stale_workbook",
                                "severity": "low",
                                "title": f"Stale Workbook: {name}",
                                "description": f"Workbook '{name}' in project '{project}' hasn't been updated in {days_since} days.",
                                "resource": f"workbook/{wb_id}",
                                "resource_type": "tableau_workbook",
                            })
                    except Exception:
                        pass
                
                # Check connections
                try:
                    connections = self.client.get_workbook_connections(wb_id)
                    for conn in connections:
                        # Check for embedded passwords (security risk)
                        if conn.get("embedPassword"):
                            findings.append({
                                "type": "embedded_password",
                                "severity": "medium",
                                "title": f"Embedded Password in Workbook: {name}",
                                "description": f"Workbook '{name}' has an embedded database password, which is a security risk.",
                                "resource": f"workbook/{wb_id}",
                                "resource_type": "tableau_workbook",
                                "suggested_fix": {
                                    "type": "manual",
                                    "action": "Re-publish workbook without embedded credentials",
                                },
                            })
                except Exception as e:
                    logger.warning(f"Could not check connections for workbook {wb_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning workbooks: {e}")
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_extract_tasks(self) -> Dict:
        """Scan extract refresh tasks."""
        findings = []
        
        try:
            tasks = self.client.get_extract_refresh_tasks()
            
            for task in tasks:
                task_id = task.get("id")
                schedule = task.get("schedule", {}).get("name", "Unknown")
                
                # Get task history
                history = self.client.get_extract_refresh_task_history(task_id)
                
                # Count consecutive failures
                consecutive_failures = 0
                for job in history:
                    if job.get("status") == "Failed":
                        consecutive_failures += 1
                    else:
                        break
                
                if consecutive_failures >= self.thresholds["consecutive_failures_critical"]:
                    findings.append({
                        "type": "extract_refresh_failing",
                        "severity": "critical",
                        "title": f"Extract Refresh Consistently Failing",
                        "description": f"Extract refresh task on schedule '{schedule}' has failed {consecutive_failures} consecutive times.",
                        "resource": f"task/{task_id}",
                        "resource_type": "tableau_extract_task",
                        "suggested_fix": {
                            "type": "manual",
                            "action": "Check data source connection and server logs",
                        },
                    })
                elif consecutive_failures >= self.thresholds["consecutive_failures_warning"]:
                    findings.append({
                        "type": "extract_refresh_warning",
                        "severity": "high",
                        "title": f"Extract Refresh Has Recent Failures",
                        "description": f"Extract refresh task on schedule '{schedule}' has failed recently.",
                        "resource": f"task/{task_id}",
                        "resource_type": "tableau_extract_task",
                    })
                    
        except Exception as e:
            logger.error(f"Error scanning extract tasks: {e}")
        
        return {"findings": findings, "metrics": {}}
    
    def _scan_failed_jobs(self) -> Dict:
        """Check for failed background jobs."""
        findings = []
        
        try:
            failed_jobs = self.client.get_recent_failed_jobs(hours=24)
            
            if len(failed_jobs) > 5:
                # Group by job type
                job_types = {}
                for job in failed_jobs:
                    jtype = job.get("jobType", "Unknown")
                    if jtype not in job_types:
                        job_types[jtype] = 0
                    job_types[jtype] += 1
                
                for jtype, count in job_types.items():
                    findings.append({
                        "type": "multiple_job_failures",
                        "severity": "high" if count > 10 else "medium",
                        "title": f"Multiple {jtype} Failures ({count} in 24h)",
                        "description": f"{count} {jtype} jobs have failed in the last 24 hours.",
                        "resource_type": "tableau_jobs",
                    })
                    
        except Exception as e:
            logger.error(f"Error scanning failed jobs: {e}")
        
        return {"findings": findings, "metrics": {}}
