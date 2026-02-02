"""
Power BI Integration - Enterprise Grade Scanner

Monitors Power BI for:
- Dataset refresh failures
- Gateway health issues
- Report errors
- Data source connection issues
- Workspace health
- Usage patterns

Uses Power BI REST API with Service Principal authentication
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class PowerBIRefreshStatus(Enum):
    """Dataset refresh status."""
    COMPLETED = "Completed"
    FAILED = "Failed"
    IN_PROGRESS = "InProgress"
    DISABLED = "Disabled"
    UNKNOWN = "Unknown"


class PowerBIGatewayStatus(Enum):
    """Gateway status."""
    LIVE = "Live"
    WARNING = "Warning"
    ERROR = "Error"
    OFFLINE = "Offline"
    UNKNOWN = "Unknown"


@dataclass
class PowerBIDataset:
    """A Power BI dataset."""
    id: str
    name: str
    workspace_id: str
    workspace_name: str = ""
    
    # Configuration
    is_refreshable: bool = True
    is_on_prem_gateway_required: bool = False
    target_storage_mode: str = "Import"  # Import, DirectQuery, Dual
    
    # Refresh info
    refresh_schedule_enabled: bool = False
    refresh_schedule_days: List[str] = field(default_factory=list)
    refresh_schedule_times: List[str] = field(default_factory=list)
    
    # Last refresh
    last_refresh_status: PowerBIRefreshStatus = PowerBIRefreshStatus.UNKNOWN
    last_refresh_at: Optional[datetime] = None
    last_refresh_duration_seconds: Optional[float] = None
    last_refresh_error: Optional[str] = None
    
    # Usage
    configured_by: Optional[str] = None
    
    @property
    def is_failing(self) -> bool:
        return self.last_refresh_status == PowerBIRefreshStatus.FAILED


@dataclass
class PowerBIReport:
    """A Power BI report."""
    id: str
    name: str
    workspace_id: str
    workspace_name: str = ""
    
    # Dataset
    dataset_id: Optional[str] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    
    # Web URL
    web_url: Optional[str] = None


@dataclass
class PowerBIGateway:
    """A Power BI gateway."""
    id: str
    name: str
    gateway_type: str = "Resource"  # Resource, Personal
    
    # Status
    status: PowerBIGatewayStatus = PowerBIGatewayStatus.UNKNOWN
    version: Optional[str] = None
    
    # Cluster
    cluster_count: int = 0
    
    # Data sources
    datasource_count: int = 0


@dataclass
class PowerBIWorkspace:
    """A Power BI workspace (formerly App Workspace)."""
    id: str
    name: str
    workspace_type: str = "Workspace"  # Workspace, Group, Personal
    
    # State
    is_on_dedicated_capacity: bool = False
    capacity_id: Optional[str] = None
    
    # Content counts
    dataset_count: int = 0
    report_count: int = 0
    dashboard_count: int = 0
    dataflow_count: int = 0
    
    # Health
    failing_datasets: int = 0


class PowerBIClient:
    """
    Power BI REST API client.
    
    Uses Service Principal authentication (App registration with secret).
    For tenant-wide scanning, the app needs Admin API permissions.
    """
    
    AUTHORITY_URL = "https://login.microsoftonline.com"
    RESOURCE_URL = "https://analysis.windows.net/powerbi/api"
    API_URL = "https://api.powerbi.com/v1.0/myorg"
    
    def __init__(self,
                 tenant_id: str,
                 client_id: str,
                 client_secret: str,
                 use_admin_api: bool = True):
        """
        Initialize Power BI client.
        
        Args:
            tenant_id: Azure AD tenant ID
            client_id: App registration client ID
            client_secret: App registration client secret
            use_admin_api: Use admin API for tenant-wide scanning
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.use_admin_api = use_admin_api
        
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
    
    def _authenticate(self) -> str:
        """Get access token using Service Principal."""
        if self._token and self._token_expires and datetime.now() < self._token_expires:
            return self._token
        
        token_url = f"{self.AUTHORITY_URL}/{self.tenant_id}/oauth2/v2.0/token"
        
        response = httpx.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": f"{self.RESOURCE_URL}/.default",
            },
            timeout=30.0,
        )
        
        if response.status_code != 200:
            raise Exception(f"Power BI authentication failed: {response.text}")
        
        data = response.json()
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expires = datetime.now() + timedelta(seconds=expires_in - 60)
        
        return self._token
    
    def _get_api_url(self, endpoint: str, admin: bool = None) -> str:
        """Build API URL."""
        admin = admin if admin is not None else self.use_admin_api
        
        if admin:
            return f"https://api.powerbi.com/v1.0/myorg/admin/{endpoint.lstrip('/')}"
        else:
            return f"{self.API_URL}/{endpoint.lstrip('/')}"
    
    def _request(self, method: str, endpoint: str, admin: bool = None, **kwargs) -> Any:
        """Make authenticated request to Power BI API."""
        token = self._authenticate()
        
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        
        url = self._get_api_url(endpoint, admin)
        
        response = httpx.request(
            method,
            url,
            headers=headers,
            timeout=60.0,
            **kwargs
        )
        
        if response.status_code >= 400:
            raise Exception(f"Power BI API error: {response.status_code} - {response.text}")
        
        return response.json() if response.text else None
    
    def test_connection(self) -> Tuple[bool, str]:
        """Test connection to Power BI."""
        try:
            self._authenticate()
            # Try to get workspaces
            self.get_workspaces(top=1)
            return True, "Connected to Power BI"
        except Exception as e:
            return False, str(e)
    
    # =========================================================================
    # WORKSPACE METHODS (Admin API)
    # =========================================================================
    
    def get_workspaces(self, top: int = 100, skip: int = 0) -> List[Dict]:
        """Get all workspaces (Admin API)."""
        if self.use_admin_api:
            # Admin API - get all workspaces in tenant
            data = self._request(
                "GET",
                f"/groups?$top={top}&$skip={skip}",
                admin=True
            )
            return data.get("value", [])
        else:
            # Regular API - only workspaces user has access to
            data = self._request("GET", "/groups")
            return data.get("value", [])
    
    def get_workspace(self, workspace_id: str) -> Dict:
        """Get workspace details."""
        return self._request("GET", f"/groups/{workspace_id}", admin=self.use_admin_api)
    
    # =========================================================================
    # DATASET METHODS
    # =========================================================================
    
    def get_datasets_in_workspace(self, workspace_id: str) -> List[Dict]:
        """Get all datasets in a workspace."""
        if self.use_admin_api:
            data = self._request("GET", f"/groups/{workspace_id}/datasets", admin=True)
        else:
            data = self._request("GET", f"/groups/{workspace_id}/datasets", admin=False)
        return data.get("value", [])
    
    def get_dataset_refresh_history(self, workspace_id: str, dataset_id: str, top: int = 10) -> List[Dict]:
        """Get refresh history for a dataset."""
        try:
            if self.use_admin_api:
                data = self._request(
                    "GET",
                    f"/groups/{workspace_id}/datasets/{dataset_id}/refreshes?$top={top}",
                    admin=True
                )
            else:
                data = self._request(
                    "GET",
                    f"/groups/{workspace_id}/datasets/{dataset_id}/refreshes?$top={top}",
                    admin=False
                )
            return data.get("value", [])
        except Exception:
            return []
    
    def get_dataset_refresh_schedule(self, workspace_id: str, dataset_id: str) -> Dict:
        """Get refresh schedule for a dataset."""
        try:
            return self._request(
                "GET",
                f"/groups/{workspace_id}/datasets/{dataset_id}/refreshSchedule",
                admin=False  # Admin API doesn't support this
            )
        except Exception:
            return {}
    
    def get_dataset_datasources(self, workspace_id: str, dataset_id: str) -> List[Dict]:
        """Get data sources for a dataset."""
        try:
            if self.use_admin_api:
                data = self._request(
                    "GET",
                    f"/groups/{workspace_id}/datasets/{dataset_id}/datasources",
                    admin=True
                )
            else:
                data = self._request(
                    "GET",
                    f"/groups/{workspace_id}/datasets/{dataset_id}/datasources",
                    admin=False
                )
            return data.get("value", [])
        except Exception:
            return []
    
    # =========================================================================
    # REPORT METHODS
    # =========================================================================
    
    def get_reports_in_workspace(self, workspace_id: str) -> List[Dict]:
        """Get all reports in a workspace."""
        if self.use_admin_api:
            data = self._request("GET", f"/groups/{workspace_id}/reports", admin=True)
        else:
            data = self._request("GET", f"/groups/{workspace_id}/reports", admin=False)
        return data.get("value", [])
    
    # =========================================================================
    # GATEWAY METHODS (Admin API only)
    # =========================================================================
    
    def get_gateways(self) -> List[Dict]:
        """Get all gateways (Admin API)."""
        data = self._request("GET", "/gateways", admin=True)
        return data.get("value", [])
    
    def get_gateway_datasources(self, gateway_id: str) -> List[Dict]:
        """Get data sources for a gateway."""
        try:
            data = self._request("GET", f"/gateways/{gateway_id}/datasources", admin=True)
            return data.get("value", [])
        except Exception:
            return []


class PowerBIScanner:
    """
    Enterprise-grade Power BI scanner.
    
    Checks:
    1. Dataset refresh failures
    2. Gateway health
    3. Data source connectivity
    4. Workspace health metrics
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scanner with Power BI credentials.
        
        Config:
            tenant_id: Azure AD tenant ID
            client_id: App registration client ID
            client_secret: App registration client secret
            use_admin_api: Use admin API (default True)
        """
        self.client = PowerBIClient(
            tenant_id=config.get("tenant_id"),
            client_id=config.get("client_id"),
            client_secret=config.get("client_secret"),
            use_admin_api=config.get("use_admin_api", True),
        )
        
        # Thresholds
        self.thresholds = {
            "stale_refresh_hours": config.get("stale_refresh_hours", 48),
            "consecutive_failures_warning": 1,
            "consecutive_failures_critical": 3,
        }
    
    def scan(self) -> Dict[str, Any]:
        """
        Run full Power BI health scan.
        
        Returns:
            Dict with findings, metrics, and health score
        """
        findings = []
        metrics = {
            "workspaces_scanned": 0,
            "datasets_scanned": 0,
            "reports_scanned": 0,
            "failing_datasets": 0,
            "stale_datasets": 0,
            "gateways_scanned": 0,
            "gateway_issues": 0,
        }
        
        # 1. Scan Workspaces and their content
        logger.info("Scanning Power BI workspaces...")
        workspace_findings = self._scan_workspaces()
        findings.extend(workspace_findings["findings"])
        metrics.update(workspace_findings["metrics"])
        
        # 2. Scan Gateways (Admin API only)
        if self.client.use_admin_api:
            logger.info("Scanning Power BI gateways...")
            gateway_findings = self._scan_gateways()
            findings.extend(gateway_findings["findings"])
            metrics.update(gateway_findings["metrics"])
        
        # Calculate health score
        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        high_count = sum(1 for f in findings if f.get("severity") == "high")
        medium_count = sum(1 for f in findings if f.get("severity") == "medium")
        
        health_score = max(0, 100 - (critical_count * 25) - (high_count * 10) - (medium_count * 3))
        
        return {
            "scan_type": "powerbi",
            "status": "critical" if critical_count > 0 else "warning" if high_count > 0 else "healthy",
            "health_score": health_score,
            "findings": findings,
            "metrics": metrics,
            "scanned_at": datetime.now().isoformat(),
        }
    
    def _scan_workspaces(self) -> Dict:
        """Scan all workspaces and their content."""
        findings = []
        metrics = {
            "workspaces_scanned": 0,
            "datasets_scanned": 0,
            "reports_scanned": 0,
            "failing_datasets": 0,
            "stale_datasets": 0,
        }
        
        try:
            workspaces = self.client.get_workspaces(top=500)
            metrics["workspaces_scanned"] = len(workspaces)
            
            for ws in workspaces:
                ws_id = ws.get("id")
                ws_name = ws.get("name", "Unknown")
                
                # Skip personal workspaces if not needed
                if ws.get("type") == "PersonalGroup":
                    continue
                
                # Scan datasets
                try:
                    datasets = self.client.get_datasets_in_workspace(ws_id)
                    metrics["datasets_scanned"] += len(datasets)
                    
                    for ds in datasets:
                        ds_findings = self._check_dataset(ws_id, ws_name, ds)
                        findings.extend(ds_findings["findings"])
                        metrics["failing_datasets"] += ds_findings.get("is_failing", 0)
                        metrics["stale_datasets"] += ds_findings.get("is_stale", 0)
                        
                except Exception as e:
                    logger.warning(f"Could not scan datasets in workspace {ws_id}: {e}")
                
                # Scan reports
                try:
                    reports = self.client.get_reports_in_workspace(ws_id)
                    metrics["reports_scanned"] += len(reports)
                except Exception:
                    pass
                    
        except Exception as e:
            logger.error(f"Error scanning workspaces: {e}")
            findings.append({
                "type": "scan_error",
                "severity": "medium",
                "title": "Workspace Scan Error",
                "description": f"Could not complete workspace scan: {str(e)}",
            })
        
        return {"findings": findings, "metrics": metrics}
    
    def _check_dataset(self, workspace_id: str, workspace_name: str, dataset: Dict) -> Dict:
        """Check a dataset for issues."""
        findings = []
        ds_id = dataset.get("id")
        ds_name = dataset.get("name", "Unknown")
        is_refreshable = dataset.get("isRefreshable", True)
        is_failing = 0
        is_stale = 0
        
        if not is_refreshable:
            return {"findings": findings, "is_failing": 0, "is_stale": 0}
        
        # Get refresh history
        history = self.client.get_dataset_refresh_history(workspace_id, ds_id, top=5)
        
        if history:
            latest = history[0]
            status = latest.get("status", "Unknown")
            end_time = latest.get("endTime")
            
            # Check for failures
            if status == "Failed":
                is_failing = 1
                error_code = latest.get("serviceExceptionJson", "Unknown error")
                
                # Count consecutive failures
                consecutive = 0
                for h in history:
                    if h.get("status") == "Failed":
                        consecutive += 1
                    else:
                        break
                
                severity = "critical" if consecutive >= self.thresholds["consecutive_failures_critical"] else "high"
                
                findings.append({
                    "type": "dataset_refresh_failed",
                    "severity": severity,
                    "title": f"Dataset Refresh Failed: {ds_name}",
                    "description": f"Dataset '{ds_name}' in workspace '{workspace_name}' failed to refresh. Error: {error_code}. Consecutive failures: {consecutive}",
                    "resource": f"workspace/{workspace_id}/dataset/{ds_id}",
                    "resource_type": "powerbi_dataset",
                    "suggested_fix": {
                        "type": "manual",
                        "action": "Check data source credentials and gateway status",
                    },
                })
            
            # Check for staleness
            if end_time:
                try:
                    end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                    hours_since = (datetime.now(end_dt.tzinfo) - end_dt).total_seconds() / 3600
                    
                    if hours_since > self.thresholds["stale_refresh_hours"]:
                        is_stale = 1
                        findings.append({
                            "type": "stale_dataset",
                            "severity": "high" if hours_since > self.thresholds["stale_refresh_hours"] * 2 else "medium",
                            "title": f"Stale Dataset: {ds_name}",
                            "description": f"Dataset '{ds_name}' in workspace '{workspace_name}' hasn't been refreshed in {hours_since:.0f} hours.",
                            "resource": f"workspace/{workspace_id}/dataset/{ds_id}",
                            "resource_type": "powerbi_dataset",
                        })
                except Exception:
                    pass
        
        # Check data sources
        try:
            datasources = self.client.get_dataset_datasources(workspace_id, ds_id)
            for ds_source in datasources:
                conn_details = ds_source.get("connectionDetails", {})
                gateway_id = ds_source.get("gatewayId")
                
                # Check if gateway is required but not configured
                if gateway_id is None and ds_source.get("datasourceType") in ["Sql", "Oracle", "PostgreSql", "MySql"]:
                    findings.append({
                        "type": "missing_gateway",
                        "severity": "high",
                        "title": f"Missing Gateway for Dataset: {ds_name}",
                        "description": f"Dataset '{ds_name}' requires a gateway for its on-premises data source but none is configured.",
                        "resource": f"workspace/{workspace_id}/dataset/{ds_id}",
                        "resource_type": "powerbi_dataset",
                    })
        except Exception:
            pass
        
        return {"findings": findings, "is_failing": is_failing, "is_stale": is_stale}
    
    def _scan_gateways(self) -> Dict:
        """Scan gateways for issues."""
        findings = []
        metrics = {
            "gateways_scanned": 0,
            "gateway_issues": 0,
        }
        
        try:
            gateways = self.client.get_gateways()
            metrics["gateways_scanned"] = len(gateways)
            
            for gw in gateways:
                gw_id = gw.get("id")
                gw_name = gw.get("name", "Unknown")
                gw_status = gw.get("status", "Unknown")
                
                # Check gateway status
                if gw_status not in ["Live", "Unknown"]:
                    metrics["gateway_issues"] += 1
                    severity = "critical" if gw_status == "Offline" else "high"
                    
                    findings.append({
                        "type": "gateway_issue",
                        "severity": severity,
                        "title": f"Gateway Issue: {gw_name}",
                        "description": f"Gateway '{gw_name}' has status: {gw_status}. This may affect data refreshes for connected datasets.",
                        "resource": f"gateway/{gw_id}",
                        "resource_type": "powerbi_gateway",
                        "suggested_fix": {
                            "type": "manual",
                            "action": "Check gateway server connectivity and service status",
                        },
                    })
                
                # Check gateway version (if available)
                version = gw.get("version")
                if version:
                    # Could add version checks here for outdated gateways
                    pass
                
                # Check data sources on this gateway
                try:
                    datasources = self.client.get_gateway_datasources(gw_id)
                    for ds in datasources:
                        cred_state = ds.get("credentialState")
                        if cred_state == "Invalid":
                            findings.append({
                                "type": "invalid_gateway_credentials",
                                "severity": "critical",
                                "title": f"Invalid Credentials on Gateway: {gw_name}",
                                "description": f"Data source '{ds.get('datasourceName', 'Unknown')}' on gateway '{gw_name}' has invalid credentials.",
                                "resource": f"gateway/{gw_id}/datasource/{ds.get('id')}",
                                "resource_type": "powerbi_gateway_datasource",
                                "suggested_fix": {
                                    "type": "manual",
                                    "action": "Update credentials for this data source in Power BI settings",
                                },
                            })
                except Exception as e:
                    logger.warning(f"Could not check datasources for gateway {gw_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning gateways: {e}")
        
        return {"findings": findings, "metrics": metrics}
