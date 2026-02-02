"""
Prefect Integration

Monitor Prefect flows and tasks:
- Flow run status and health
- Task run metrics
- Deployment health
- Work pool monitoring
- Block status

Supports:
- Prefect Cloud API
- Prefect Server (self-hosted)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class FlowRunState(Enum):
    """Prefect flow run states."""
    SCHEDULED = "SCHEDULED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CANCELLING = "CANCELLING"
    CRASHED = "CRASHED"
    PAUSED = "PAUSED"


class DeploymentStatus(Enum):
    """Deployment statuses."""
    READY = "READY"
    NOT_READY = "NOT_READY"


@dataclass
class PrefectFlow:
    """A Prefect flow."""
    id: str
    name: str
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    
    # Computed from deployments/runs
    deployment_count: int = 0
    last_run_state: Optional[FlowRunState] = None
    last_run_time: Optional[datetime] = None


@dataclass
class PrefectFlowRun:
    """A Prefect flow run."""
    id: str
    flow_id: str
    flow_name: str
    name: str  # run name
    state: FlowRunState
    state_message: Optional[str] = None
    created: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_run_time: Optional[float] = None  # seconds
    deployment_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    @property
    def duration_minutes(self) -> Optional[float]:
        if self.total_run_time:
            return self.total_run_time / 60
        return None
    
    @property
    def is_success(self) -> bool:
        return self.state == FlowRunState.COMPLETED
    
    @property
    def is_failed(self) -> bool:
        return self.state in (FlowRunState.FAILED, FlowRunState.CRASHED)


@dataclass
class PrefectDeployment:
    """A Prefect deployment."""
    id: str
    name: str
    flow_id: str
    flow_name: str
    is_schedule_active: bool = True
    schedule: Optional[Dict[str, Any]] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    work_pool_name: Optional[str] = None
    work_queue_name: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    # Health metrics
    last_polled: Optional[datetime] = None
    status: DeploymentStatus = DeploymentStatus.READY


@dataclass
class PrefectWorkPool:
    """A Prefect work pool."""
    id: str
    name: str
    type: str  # e.g., "process", "docker", "kubernetes"
    is_paused: bool = False
    concurrency_limit: Optional[int] = None
    
    # Health
    status: str = "READY"  # READY, NOT_READY, PAUSED


class PrefectIntegration:
    """
    Prefect integration for Pallisade.
    
    Capabilities:
    - List and monitor flows
    - Track flow run status
    - Monitor deployments
    - Analyze work pool health
    - Calculate pipeline health metrics
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Prefect integration.
        
        Config options:
            api_url: Prefect API URL (e.g., https://api.prefect.cloud/api)
            api_key: Prefect API key
            
        For Prefect Cloud:
            account_id: Account ID
            workspace_id: Workspace ID
            
        For self-hosted:
            api_url: http://localhost:4200/api
        """
        self.config = config
        
        if config.get('account_id') and config.get('workspace_id'):
            # Prefect Cloud
            account_id = config['account_id']
            workspace_id = config['workspace_id']
            self.api_url = f"https://api.prefect.cloud/api/accounts/{account_id}/workspaces/{workspace_id}"
        else:
            # Self-hosted
            self.api_url = config.get('api_url', 'http://localhost:4200/api').rstrip('/')
        
        headers = {'Content-Type': 'application/json'}
        if config.get('api_key'):
            headers['Authorization'] = f"Bearer {config['api_key']}"
        
        self._client = httpx.Client(timeout=30, headers=headers)
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make API request."""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        response = self._client.request(method, url, **kwargs)
        response.raise_for_status()
        
        if response.content:
            return response.json()
        return None
    
    def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test connection to Prefect."""
        try:
            result = self._request('GET', '/health')
            return True, "Prefect connected"
        except Exception as e:
            return False, str(e)
    
    def get_flows(self, limit: int = 100) -> List[PrefectFlow]:
        """Get all flows."""
        try:
            result = self._request('POST', '/flows/filter', json={
                'limit': limit,
                'sort': 'UPDATED_DESC'
            })
            
            flows = []
            for flow_data in result or []:
                flows.append(PrefectFlow(
                    id=flow_data.get('id', ''),
                    name=flow_data.get('name', ''),
                    created=self._parse_datetime(flow_data.get('created')),
                    updated=self._parse_datetime(flow_data.get('updated')),
                    tags=flow_data.get('tags', []),
                ))
            
            return flows
            
        except Exception as e:
            logger.error(f"Failed to get flows: {e}")
            return []
    
    def get_flow_runs(self,
                      flow_id: Optional[str] = None,
                      flow_name: Optional[str] = None,
                      deployment_id: Optional[str] = None,
                      state: Optional[FlowRunState] = None,
                      limit: int = 25) -> List[PrefectFlowRun]:
        """Get flow runs with optional filters."""
        try:
            filters = {}
            
            if flow_id:
                filters['flow_id'] = {'any_': [flow_id]}
            if flow_name:
                filters['flow_name'] = {'any_': [flow_name]}
            if deployment_id:
                filters['deployment_id'] = {'any_': [deployment_id]}
            if state:
                filters['state'] = {'type': {'any_': [state.value]}}
            
            result = self._request('POST', '/flow_runs/filter', json={
                'limit': limit,
                'sort': 'START_TIME_DESC',
                'flow_runs': filters if filters else None,
            })
            
            runs = []
            for run_data in result or []:
                try:
                    state_type = run_data.get('state', {}).get('type', 'PENDING')
                    run_state = FlowRunState(state_type)
                except ValueError:
                    run_state = FlowRunState.PENDING
                
                runs.append(PrefectFlowRun(
                    id=run_data.get('id', ''),
                    flow_id=run_data.get('flow_id', ''),
                    flow_name=run_data.get('flow_name', '') or run_data.get('name', ''),
                    name=run_data.get('name', ''),
                    state=run_state,
                    state_message=run_data.get('state', {}).get('message'),
                    created=self._parse_datetime(run_data.get('created')),
                    start_time=self._parse_datetime(run_data.get('start_time')),
                    end_time=self._parse_datetime(run_data.get('end_time')),
                    total_run_time=run_data.get('total_run_time'),
                    deployment_id=run_data.get('deployment_id'),
                    tags=run_data.get('tags', []),
                ))
            
            return runs
            
        except Exception as e:
            logger.error(f"Failed to get flow runs: {e}")
            return []
    
    def get_deployments(self, limit: int = 100) -> List[PrefectDeployment]:
        """Get all deployments."""
        try:
            result = self._request('POST', '/deployments/filter', json={
                'limit': limit,
                'sort': 'UPDATED_DESC'
            })
            
            deployments = []
            for dep_data in result or []:
                schedule = dep_data.get('schedule')
                
                deployments.append(PrefectDeployment(
                    id=dep_data.get('id', ''),
                    name=dep_data.get('name', ''),
                    flow_id=dep_data.get('flow_id', ''),
                    flow_name=dep_data.get('flow_name', ''),
                    is_schedule_active=dep_data.get('is_schedule_active', True),
                    schedule=schedule,
                    created=self._parse_datetime(dep_data.get('created')),
                    updated=self._parse_datetime(dep_data.get('updated')),
                    work_pool_name=dep_data.get('work_pool_name'),
                    work_queue_name=dep_data.get('work_queue_name'),
                    tags=dep_data.get('tags', []),
                    status=DeploymentStatus.READY if dep_data.get('status') == 'READY' else DeploymentStatus.NOT_READY,
                ))
            
            return deployments
            
        except Exception as e:
            logger.error(f"Failed to get deployments: {e}")
            return []
    
    def get_work_pools(self) -> List[PrefectWorkPool]:
        """Get all work pools."""
        try:
            result = self._request('POST', '/work_pools/filter', json={
                'limit': 100
            })
            
            pools = []
            for pool_data in result or []:
                pools.append(PrefectWorkPool(
                    id=pool_data.get('id', ''),
                    name=pool_data.get('name', ''),
                    type=pool_data.get('type', 'process'),
                    is_paused=pool_data.get('is_paused', False),
                    concurrency_limit=pool_data.get('concurrency_limit'),
                    status=pool_data.get('status', 'READY'),
                ))
            
            return pools
            
        except Exception as e:
            logger.error(f"Failed to get work pools: {e}")
            return []
    
    def analyze_flow_health(self, flow_id: str, days: int = 7) -> Dict[str, Any]:
        """Analyze health of a flow."""
        runs = self.get_flow_runs(flow_id=flow_id, limit=100)
        
        # Filter to recent period
        cutoff = datetime.now() - timedelta(days=days)
        recent_runs = [r for r in runs if r.start_time and r.start_time > cutoff]
        
        if not recent_runs:
            return {
                'flow_id': flow_id,
                'total_runs': 0,
                'status': 'no_runs',
            }
        
        successful = [r for r in recent_runs if r.is_success]
        failed = [r for r in recent_runs if r.is_failed]
        
        success_rate = len(successful) / len(recent_runs)
        
        # Duration analysis
        durations = [r.duration_minutes for r in successful if r.duration_minutes]
        avg_duration = sum(durations) / len(durations) if durations else None
        
        # Health status
        if success_rate >= 0.95:
            status = 'healthy'
        elif success_rate >= 0.8:
            status = 'degraded'
        else:
            status = 'unhealthy'
        
        return {
            'flow_id': flow_id,
            'flow_name': recent_runs[0].flow_name if recent_runs else None,
            'analysis_period_days': days,
            'total_runs': len(recent_runs),
            'successful_runs': len(successful),
            'failed_runs': len(failed),
            'success_rate_pct': round(success_rate * 100, 1),
            'avg_duration_minutes': round(avg_duration, 2) if avg_duration else None,
            'status': status,
            'recent_failures': [
                {
                    'run_id': r.id,
                    'name': r.name,
                    'start_time': r.start_time.isoformat() if r.start_time else None,
                    'message': r.state_message,
                }
                for r in failed[:5]
            ],
        }
    
    def analyze_deployment_health(self, deployment_id: str, days: int = 7) -> Dict[str, Any]:
        """Analyze health of a deployment."""
        runs = self.get_flow_runs(deployment_id=deployment_id, limit=100)
        
        # Filter to recent period
        cutoff = datetime.now() - timedelta(days=days)
        recent_runs = [r for r in runs if r.start_time and r.start_time > cutoff]
        
        if not recent_runs:
            return {
                'deployment_id': deployment_id,
                'total_runs': 0,
                'status': 'no_runs',
            }
        
        successful = [r for r in recent_runs if r.is_success]
        failed = [r for r in recent_runs if r.is_failed]
        
        success_rate = len(successful) / len(recent_runs)
        
        # Last run info
        last_run = recent_runs[0] if recent_runs else None
        hours_since_last = None
        if last_run and last_run.start_time:
            hours_since_last = (datetime.now() - last_run.start_time).total_seconds() / 3600
        
        # Health status
        if success_rate >= 0.95:
            status = 'healthy'
        elif success_rate >= 0.8:
            status = 'degraded'
        else:
            status = 'unhealthy'
        
        return {
            'deployment_id': deployment_id,
            'analysis_period_days': days,
            'total_runs': len(recent_runs),
            'successful_runs': len(successful),
            'failed_runs': len(failed),
            'success_rate_pct': round(success_rate * 100, 1),
            'last_run_state': last_run.state.value if last_run else None,
            'hours_since_last_run': round(hours_since_last, 1) if hours_since_last else None,
            'status': status,
        }
    
    def get_work_pool_health(self) -> List[Dict[str, Any]]:
        """Get health status of all work pools."""
        pools = self.get_work_pools()
        
        health_report = []
        for pool in pools:
            status = 'healthy'
            if pool.is_paused:
                status = 'paused'
            elif pool.status != 'READY':
                status = 'unhealthy'
            
            health_report.append({
                'name': pool.name,
                'type': pool.type,
                'status': status,
                'is_paused': pool.is_paused,
                'concurrency_limit': pool.concurrency_limit,
            })
        
        return health_report
    
    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse datetime string."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except Exception:
            return None
    
    def close(self):
        """Close the HTTP client."""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
