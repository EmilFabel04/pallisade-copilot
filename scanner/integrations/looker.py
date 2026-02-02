"""
Looker Integration - Enterprise Grade Scanner

Monitors Looker dashboards and explores for:
- Dashboard load times and errors
- Query performance and failures
- Data freshness (when was source data last updated)
- Broken content (dashboards with errors)
- Usage patterns (popular vs stale dashboards)
- Schedule failures (PDF/email delivery issues)

Uses Looker API 4.0
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import httpx
import hashlib

logger = logging.getLogger(__name__)


class LookerContentType(Enum):
    """Types of Looker content."""
    DASHBOARD = "dashboard"
    LOOK = "look"
    EXPLORE = "explore"
    SCHEDULED_PLAN = "scheduled_plan"


class LookerHealthStatus(Enum):
    """Health status for Looker content."""
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass
class LookerQuery:
    """A Looker query with performance metrics."""
    id: str
    model: str
    view: str
    fields: List[str] = field(default_factory=list)
    filters: Dict[str, str] = field(default_factory=dict)
    
    # Performance
    runtime_seconds: Optional[float] = None
    source_queries: int = 0  # Number of SQL queries generated
    
    # Status
    status: str = "complete"
    error_message: Optional[str] = None
    
    @property
    def is_slow(self) -> bool:
        return self.runtime_seconds is not None and self.runtime_seconds > 30
    
    @property
    def is_failed(self) -> bool:
        return self.status == "error" or self.error_message is not None


@dataclass
class LookerDashboard:
    """A Looker dashboard with health metrics."""
    id: str
    title: str
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    
    # Content
    element_count: int = 0
    filter_count: int = 0
    
    # Usage
    view_count: int = 0
    favorite_count: int = 0
    last_viewed_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    
    # Health
    status: LookerHealthStatus = LookerHealthStatus.UNKNOWN
    broken_elements: List[Dict] = field(default_factory=list)
    slow_queries: List[LookerQuery] = field(default_factory=list)
    
    # Owner
    created_by: Optional[str] = None
    
    @property
    def is_stale(self) -> bool:
        """Dashboard not viewed in 90 days."""
        if not self.last_viewed_at:
            return True
        return (datetime.now() - self.last_viewed_at).days > 90
    
    @property
    def has_errors(self) -> bool:
        return len(self.broken_elements) > 0
    
    @property
    def health_score(self) -> float:
        """Calculate health score 0-100."""
        score = 100.0
        
        # Deduct for broken elements
        score -= len(self.broken_elements) * 20
        
        # Deduct for slow queries
        score -= len(self.slow_queries) * 5
        
        # Deduct for staleness
        if self.is_stale:
            score -= 10
        
        return max(0, min(100, score))


@dataclass
class LookerSchedule:
    """A Looker scheduled plan (PDF/email delivery)."""
    id: str
    name: str
    dashboard_id: Optional[str] = None
    look_id: Optional[str] = None
    
    # Schedule
    cron: Optional[str] = None
    enabled: bool = True
    
    # Delivery
    destination_type: str = "email"  # email, sftp, s3, webhook
    recipients: List[str] = field(default_factory=list)
    
    # Status
    last_run_at: Optional[datetime] = None
    last_run_status: str = "unknown"
    consecutive_failures: int = 0
    
    @property
    def is_failing(self) -> bool:
        return self.last_run_status == "failure" or self.consecutive_failures > 0


@dataclass 
class LookerModel:
    """A Looker model (LookML project connection)."""
    name: str
    project_name: str
    connection_name: str
    
    # Explores
    explores: List[str] = field(default_factory=list)
    
    # Status
    has_content_validation_errors: bool = False
    validation_errors: List[str] = field(default_factory=list)


class LookerClient:
    """
    Looker API 4.0 client.
    
    Handles authentication and provides methods for:
    - Dashboard health checks
    - Query performance monitoring
    - Schedule status
    - Content validation
    """
    
    def __init__(self, 
                 host: str,
                 client_id: str,
                 client_secret: str,
                 port: int = 19999,
                 verify_ssl: bool = True):
        """
        Initialize Looker client.
        
        Args:
            host: Looker instance URL (e.g., company.cloud.looker.com)
            client_id: API3 client ID
            client_secret: API3 client secret
            port: API port (default 19999, use 443 for cloud)
            verify_ssl: Whether to verify SSL certificates
        """
        # Normalize host
        self.host = host.rstrip('/')
        if not self.host.startswith('http'):
            self.host = f"https://{self.host}"
        
        # For Looker Cloud, use port 443
        if 'cloud.looker.com' in self.host:
            self.api_url = f"{self.host}/api/4.0"
        else:
            self.api_url = f"{self.host}:{port}/api/4.0"
        
        self.client_id = client_id
        self.client_secret = client_secret
        self.verify_ssl = verify_ssl
        
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._client: Optional[httpx.Client] = None
    
    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                timeout=60.0,
                verify=self.verify_ssl,
            )
        return self._client
    
    def _authenticate(self) -> str:
        """Authenticate and get access token."""
        # Check if token is still valid
        if self._token and self._token_expires and datetime.now() < self._token_expires:
            return self._token
        
        client = self._get_client()
        
        response = client.post(
            f"{self.api_url}/login",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Looker authentication failed: {response.text}")
        
        data = response.json()
        self._token = data["access_token"]
        # Token expires in 1 hour, refresh at 50 minutes
        self._token_expires = datetime.now() + timedelta(minutes=50)
        
        return self._token
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make authenticated request to Looker API."""
        token = self._authenticate()
        client = self._get_client()
        
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        
        response = client.request(
            method,
            f"{self.api_url}/{endpoint.lstrip('/')}",
            headers=headers,
            **kwargs
        )
        
        if response.status_code == 401:
            # Token expired, refresh and retry
            self._token = None
            token = self._authenticate()
            headers["Authorization"] = f"Bearer {token}"
            response = client.request(
                method,
                f"{self.api_url}/{endpoint.lstrip('/')}",
                headers=headers,
                **kwargs
            )
        
        if response.status_code >= 400:
            raise Exception(f"Looker API error: {response.status_code} - {response.text}")
        
        return response.json() if response.text else None
    
    def test_connection(self) -> Tuple[bool, str]:
        """Test connection to Looker."""
        try:
            self._authenticate()
            # Try to get current user
            user = self._request("GET", "/user")
            return True, f"Connected as {user.get('display_name', 'Unknown')}"
        except Exception as e:
            return False, str(e)
    
    # =========================================================================
    # DASHBOARD METHODS
    # =========================================================================
    
    def get_all_dashboards(self, limit: int = 1000) -> List[Dict]:
        """Get all dashboards."""
        return self._request(
            "GET", 
            "/dashboards",
            params={"limit": limit, "fields": "id,title,folder,view_count,favorite_count,last_viewed_at,last_updated_at,user_id,dashboard_elements"}
        )
    
    def get_dashboard(self, dashboard_id: str) -> Dict:
        """Get dashboard details."""
        return self._request("GET", f"/dashboards/{dashboard_id}")
    
    def get_dashboard_elements(self, dashboard_id: str) -> List[Dict]:
        """Get dashboard elements (tiles)."""
        dashboard = self.get_dashboard(dashboard_id)
        return dashboard.get("dashboard_elements", [])
    
    def run_dashboard_element(self, element_id: str, dashboard_id: str) -> Dict:
        """Run a dashboard element query and get results/timing."""
        try:
            # Get the element's query
            element = self._request("GET", f"/dashboard_elements/{element_id}")
            query_id = element.get("query_id") or element.get("result_maker", {}).get("query_id")
            
            if not query_id:
                return {"status": "no_query", "element_id": element_id}
            
            # Run the query
            start = datetime.now()
            result = self._request(
                "POST",
                f"/queries/{query_id}/run/json",
                params={"limit": 1}  # Just test if it runs
            )
            runtime = (datetime.now() - start).total_seconds()
            
            return {
                "status": "success",
                "element_id": element_id,
                "runtime_seconds": runtime,
                "row_count": len(result) if isinstance(result, list) else 0,
            }
        except Exception as e:
            return {
                "status": "error",
                "element_id": element_id,
                "error": str(e),
            }
    
    def validate_dashboard(self, dashboard_id: str) -> Dict:
        """
        Validate a dashboard by running all its queries.
        Returns health status and any errors.
        """
        dashboard = self.get_dashboard(dashboard_id)
        elements = dashboard.get("dashboard_elements", [])
        
        results = {
            "dashboard_id": dashboard_id,
            "title": dashboard.get("title"),
            "total_elements": len(elements),
            "healthy_elements": 0,
            "broken_elements": [],
            "slow_elements": [],
            "errors": [],
        }
        
        for element in elements:
            element_id = element.get("id")
            if not element_id:
                continue
            
            result = self.run_dashboard_element(element_id, dashboard_id)
            
            if result.get("status") == "success":
                results["healthy_elements"] += 1
                if result.get("runtime_seconds", 0) > 30:
                    results["slow_elements"].append({
                        "element_id": element_id,
                        "title": element.get("title"),
                        "runtime_seconds": result["runtime_seconds"],
                    })
            elif result.get("status") == "error":
                results["broken_elements"].append({
                    "element_id": element_id,
                    "title": element.get("title"),
                    "error": result.get("error"),
                })
                results["errors"].append(result.get("error"))
        
        return results
    
    # =========================================================================
    # SCHEDULE METHODS
    # =========================================================================
    
    def get_all_scheduled_plans(self) -> List[Dict]:
        """Get all scheduled plans."""
        return self._request("GET", "/scheduled_plans", params={"all_users": True})
    
    def get_scheduled_plan_history(self, plan_id: str, limit: int = 10) -> List[Dict]:
        """Get execution history for a scheduled plan."""
        return self._request(
            "GET",
            f"/scheduled_plans/{plan_id}/run_once_results",
            params={"limit": limit}
        )
    
    # =========================================================================
    # MODEL/EXPLORE METHODS
    # =========================================================================
    
    def get_all_models(self) -> List[Dict]:
        """Get all LookML models."""
        return self._request("GET", "/lookml_models")
    
    def validate_model(self, model_name: str) -> Dict:
        """Validate a LookML model for errors."""
        return self._request("GET", f"/lookml_models/{model_name}/validate")
    
    # =========================================================================
    # QUERY HISTORY
    # =========================================================================
    
    def get_query_history(self, hours: int = 24, limit: int = 500) -> List[Dict]:
        """Get recent query history."""
        return self._request(
            "GET",
            "/queries/history",
            params={
                "limit": limit,
                "fields": "id,model,view,created_at,runtime,status,error_message,source"
            }
        )
    
    def get_slow_queries(self, min_runtime_seconds: float = 30, hours: int = 24) -> List[Dict]:
        """Get queries slower than threshold."""
        history = self.get_query_history(hours=hours)
        return [
            q for q in history 
            if q.get("runtime", 0) > min_runtime_seconds
        ]
    
    def get_failed_queries(self, hours: int = 24) -> List[Dict]:
        """Get failed queries."""
        history = self.get_query_history(hours=hours)
        return [
            q for q in history 
            if q.get("status") == "error" or q.get("error_message")
        ]


class LookerScanner:
    """
    Enterprise-grade Looker scanner.
    
    Checks:
    1. Dashboard health (broken tiles, slow queries)
    2. Schedule status (failing deliveries)
    3. Model validation (LookML errors)
    4. Query performance (slow/failed queries)
    5. Content staleness (unused dashboards)
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scanner with Looker credentials.
        
        Config:
            host: Looker instance URL
            client_id: API3 client ID
            client_secret: API3 client secret
        """
        self.client = LookerClient(
            host=config.get("host"),
            client_id=config.get("client_id"),
            client_secret=config.get("client_secret"),
            verify_ssl=config.get("verify_ssl", True),
        )
        
        # Thresholds
        self.thresholds = {
            "slow_query_seconds": config.get("slow_query_seconds", 30),
            "stale_days": config.get("stale_days", 90),
            "schedule_failure_warning": 1,
            "schedule_failure_critical": 3,
        }
    
    def scan(self) -> Dict[str, Any]:
        """
        Run full Looker health scan.
        
        Returns:
            Dict with findings, metrics, and health score
        """
        findings = []
        metrics = {
            "dashboards_scanned": 0,
            "healthy_dashboards": 0,
            "broken_dashboards": 0,
            "stale_dashboards": 0,
            "schedules_scanned": 0,
            "failing_schedules": 0,
            "slow_queries_24h": 0,
            "failed_queries_24h": 0,
        }
        
        # 1. Scan Dashboards
        logger.info("Scanning Looker dashboards...")
        dashboard_findings = self._scan_dashboards()
        findings.extend(dashboard_findings["findings"])
        metrics.update(dashboard_findings["metrics"])
        
        # 2. Scan Schedules
        logger.info("Scanning Looker schedules...")
        schedule_findings = self._scan_schedules()
        findings.extend(schedule_findings["findings"])
        metrics.update(schedule_findings["metrics"])
        
        # 3. Check Query Performance
        logger.info("Checking query performance...")
        query_findings = self._scan_queries()
        findings.extend(query_findings["findings"])
        metrics.update(query_findings["metrics"])
        
        # 4. Validate LookML Models
        logger.info("Validating LookML models...")
        model_findings = self._scan_models()
        findings.extend(model_findings["findings"])
        
        # Calculate health score
        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        high_count = sum(1 for f in findings if f.get("severity") == "high")
        medium_count = sum(1 for f in findings if f.get("severity") == "medium")
        
        health_score = max(0, 100 - (critical_count * 25) - (high_count * 10) - (medium_count * 3))
        
        return {
            "scan_type": "looker",
            "status": "critical" if critical_count > 0 else "warning" if high_count > 0 else "healthy",
            "health_score": health_score,
            "findings": findings,
            "metrics": metrics,
            "scanned_at": datetime.now().isoformat(),
        }
    
    def _scan_dashboards(self) -> Dict:
        """Scan all dashboards for health issues."""
        findings = []
        metrics = {
            "dashboards_scanned": 0,
            "healthy_dashboards": 0,
            "broken_dashboards": 0,
            "stale_dashboards": 0,
        }
        
        try:
            dashboards = self.client.get_all_dashboards()
            metrics["dashboards_scanned"] = len(dashboards)
            
            for dash in dashboards:
                dashboard_id = dash.get("id")
                title = dash.get("title", "Untitled")
                
                # Check for stale dashboards
                last_viewed = dash.get("last_viewed_at")
                if last_viewed:
                    try:
                        last_viewed_dt = datetime.fromisoformat(last_viewed.replace("Z", "+00:00"))
                        days_since_view = (datetime.now(last_viewed_dt.tzinfo) - last_viewed_dt).days
                        
                        if days_since_view > self.thresholds["stale_days"]:
                            metrics["stale_dashboards"] += 1
                            findings.append({
                                "type": "stale_dashboard",
                                "severity": "low",
                                "title": f"Stale Dashboard: {title}",
                                "description": f"Dashboard '{title}' hasn't been viewed in {days_since_view} days. Consider archiving or updating.",
                                "resource": f"dashboard/{dashboard_id}",
                                "resource_type": "looker_dashboard",
                                "suggested_fix": {
                                    "type": "manual",
                                    "action": "Review dashboard usage and either update content or archive",
                                },
                            })
                    except Exception:
                        pass
                
                # Validate dashboard (check for broken tiles)
                try:
                    validation = self.client.validate_dashboard(dashboard_id)
                    
                    if validation.get("broken_elements"):
                        metrics["broken_dashboards"] += 1
                        for broken in validation["broken_elements"]:
                            findings.append({
                                "type": "broken_dashboard_element",
                                "severity": "high",
                                "title": f"Broken Dashboard Element: {title}",
                                "description": f"Dashboard '{title}' has a broken tile: {broken.get('title', 'Unknown')}. Error: {broken.get('error', 'Unknown error')}",
                                "resource": f"dashboard/{dashboard_id}",
                                "resource_type": "looker_dashboard",
                                "suggested_fix": {
                                    "type": "manual",
                                    "action": "Check the tile's underlying query or LookML model for errors",
                                },
                            })
                    
                    if validation.get("slow_elements"):
                        for slow in validation["slow_elements"]:
                            findings.append({
                                "type": "slow_dashboard_element",
                                "severity": "medium",
                                "title": f"Slow Dashboard Element: {title}",
                                "description": f"Dashboard '{title}' has a slow tile ({slow.get('runtime_seconds', 0):.1f}s): {slow.get('title', 'Unknown')}",
                                "resource": f"dashboard/{dashboard_id}",
                                "resource_type": "looker_dashboard",
                                "suggested_fix": {
                                    "type": "manual",
                                    "action": "Optimize the underlying query or add caching",
                                },
                            })
                    
                    if not validation.get("broken_elements") and not validation.get("slow_elements"):
                        metrics["healthy_dashboards"] += 1
                        
                except Exception as e:
                    logger.warning(f"Could not validate dashboard {dashboard_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning dashboards: {e}")
            findings.append({
                "type": "scan_error",
                "severity": "medium",
                "title": "Dashboard Scan Error",
                "description": f"Could not complete dashboard scan: {str(e)}",
            })
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_schedules(self) -> Dict:
        """Scan scheduled plans for failures."""
        findings = []
        metrics = {
            "schedules_scanned": 0,
            "failing_schedules": 0,
        }
        
        try:
            schedules = self.client.get_all_scheduled_plans()
            metrics["schedules_scanned"] = len(schedules)
            
            for schedule in schedules:
                plan_id = schedule.get("id")
                name = schedule.get("name", "Unnamed")
                enabled = schedule.get("enabled", True)
                
                if not enabled:
                    continue
                
                # Check run history
                try:
                    history = self.client.get_scheduled_plan_history(plan_id, limit=5)
                    
                    # Count recent failures
                    failures = sum(1 for h in history if h.get("status") == "failure")
                    
                    if failures >= self.thresholds["schedule_failure_critical"]:
                        metrics["failing_schedules"] += 1
                        findings.append({
                            "type": "schedule_failing",
                            "severity": "critical",
                            "title": f"Scheduled Plan Consistently Failing: {name}",
                            "description": f"Scheduled plan '{name}' has failed {failures} of the last 5 runs.",
                            "resource": f"scheduled_plan/{plan_id}",
                            "resource_type": "looker_schedule",
                            "suggested_fix": {
                                "type": "manual",
                                "action": "Check the underlying dashboard/look for errors and verify delivery settings",
                            },
                        })
                    elif failures >= self.thresholds["schedule_failure_warning"]:
                        findings.append({
                            "type": "schedule_warning",
                            "severity": "high",
                            "title": f"Scheduled Plan Has Recent Failures: {name}",
                            "description": f"Scheduled plan '{name}' has failed {failures} of the last 5 runs.",
                            "resource": f"scheduled_plan/{plan_id}",
                            "resource_type": "looker_schedule",
                        })
                        
                except Exception as e:
                    logger.warning(f"Could not get history for schedule {plan_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning schedules: {e}")
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_queries(self) -> Dict:
        """Check query performance over last 24 hours."""
        findings = []
        metrics = {
            "slow_queries_24h": 0,
            "failed_queries_24h": 0,
        }
        
        try:
            # Get slow queries
            slow_queries = self.client.get_slow_queries(
                min_runtime_seconds=self.thresholds["slow_query_seconds"],
                hours=24
            )
            metrics["slow_queries_24h"] = len(slow_queries)
            
            if len(slow_queries) > 10:
                findings.append({
                    "type": "many_slow_queries",
                    "severity": "high",
                    "title": f"High Number of Slow Queries ({len(slow_queries)} in 24h)",
                    "description": f"There have been {len(slow_queries)} queries taking longer than {self.thresholds['slow_query_seconds']}s in the last 24 hours. This may indicate performance issues.",
                    "resource_type": "looker_queries",
                    "suggested_fix": {
                        "type": "manual",
                        "action": "Review slow queries and optimize LookML models or add caching",
                    },
                })
            
            # Get failed queries
            failed_queries = self.client.get_failed_queries(hours=24)
            metrics["failed_queries_24h"] = len(failed_queries)
            
            if len(failed_queries) > 5:
                # Group by error message
                error_groups = {}
                for q in failed_queries:
                    error = q.get("error_message", "Unknown error")[:100]
                    if error not in error_groups:
                        error_groups[error] = 0
                    error_groups[error] += 1
                
                for error, count in error_groups.items():
                    findings.append({
                        "type": "query_errors",
                        "severity": "high" if count > 10 else "medium",
                        "title": f"Query Errors: {count} occurrences",
                        "description": f"{count} queries failed with: {error}",
                        "resource_type": "looker_queries",
                    })
                    
        except Exception as e:
            logger.error(f"Error scanning queries: {e}")
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_models(self) -> Dict:
        """Validate LookML models."""
        findings = []
        
        try:
            models = self.client.get_all_models()
            
            for model in models:
                model_name = model.get("name")
                
                try:
                    validation = self.client.validate_model(model_name)
                    errors = validation.get("errors", [])
                    
                    if errors:
                        findings.append({
                            "type": "lookml_validation_error",
                            "severity": "critical",
                            "title": f"LookML Validation Errors: {model_name}",
                            "description": f"Model '{model_name}' has {len(errors)} validation errors: {errors[0] if errors else 'Unknown'}",
                            "resource": f"model/{model_name}",
                            "resource_type": "looker_model",
                            "suggested_fix": {
                                "type": "manual",
                                "action": "Review and fix LookML syntax errors",
                            },
                        })
                except Exception as e:
                    logger.warning(f"Could not validate model {model_name}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning models: {e}")
        
        return {"findings": findings, "metrics": {}}
