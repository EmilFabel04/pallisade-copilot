"""
Apache Airflow Integration

Monitor Airflow DAGs and tasks:
- DAG status and health
- Task execution metrics
- SLA tracking
- Failure analysis
- Data pipeline freshness

Supports:
- Airflow REST API (2.0+)
- Airflow CLI
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class DAGState(Enum):
    """DAG run states."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class TaskState(Enum):
    """Task instance states."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    UPSTREAM_FAILED = "upstream_failed"
    SKIPPED = "skipped"
    UP_FOR_RETRY = "up_for_retry"
    UP_FOR_RESCHEDULE = "up_for_reschedule"
    SENSING = "sensing"
    DEFERRED = "deferred"


@dataclass
class AirflowTask:
    """An Airflow task instance."""
    task_id: str
    dag_id: str
    state: TaskState
    execution_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    duration: Optional[float] = None  # seconds
    try_number: int = 1
    max_tries: int = 1
    operator: Optional[str] = None
    pool: Optional[str] = None
    queue: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        return self.state == TaskState.SUCCESS
    
    @property
    def is_failed(self) -> bool:
        return self.state in (TaskState.FAILED, TaskState.UPSTREAM_FAILED)
    
    @property
    def is_running(self) -> bool:
        return self.state == TaskState.RUNNING
    
    @property
    def duration_minutes(self) -> Optional[float]:
        return self.duration / 60 if self.duration else None


@dataclass
class AirflowDAGRun:
    """An Airflow DAG run."""
    dag_id: str
    run_id: str
    state: DAGState
    execution_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    external_trigger: bool = False
    conf: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration(self) -> Optional[timedelta]:
        if self.start_date and self.end_date:
            return self.end_date - self.start_date
        return None
    
    @property
    def duration_minutes(self) -> Optional[float]:
        d = self.duration
        return d.total_seconds() / 60 if d else None


@dataclass
class AirflowDAG:
    """An Airflow DAG."""
    dag_id: str
    description: Optional[str] = None
    schedule_interval: Optional[str] = None
    is_paused: bool = False
    is_active: bool = True
    tags: List[str] = field(default_factory=list)
    owners: List[str] = field(default_factory=list)
    default_args: Dict[str, Any] = field(default_factory=dict)
    
    # Computed from runs
    last_run_state: Optional[DAGState] = None
    last_run_date: Optional[datetime] = None
    success_rate: Optional[float] = None
    avg_duration_minutes: Optional[float] = None
    
    @property
    def has_sla(self) -> bool:
        return 'sla' in self.default_args or any('sla' in str(t) for t in self.tags)


@dataclass
class SLAMiss:
    """An SLA miss event."""
    dag_id: str
    task_id: str
    execution_date: datetime
    expected_time: datetime
    actual_time: Optional[datetime] = None
    description: Optional[str] = None


class AirflowIntegration:
    """
    Apache Airflow integration for Pallisade.
    
    Capabilities:
    - List and monitor DAGs
    - Track DAG run status
    - Analyze task performance
    - Detect SLA misses
    - Calculate pipeline health metrics
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Airflow integration.
        
        Config options:
            base_url: Airflow webserver URL (e.g., http://localhost:8080)
            username: Airflow username
            password: Airflow password
            
        Or:
            api_key: API key for authentication
        """
        self.config = config
        self.base_url = config.get('base_url', 'http://localhost:8080').rstrip('/')
        self.api_url = f"{self.base_url}/api/v1"
        
        # Setup auth
        self._client = httpx.Client(timeout=30)
        
        if config.get('api_key'):
            self._client.headers['Authorization'] = f"Bearer {config['api_key']}"
        elif config.get('username') and config.get('password'):
            self._auth = (config['username'], config['password'])
        else:
            self._auth = None
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated request to Airflow API."""
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        
        if hasattr(self, '_auth') and self._auth:
            kwargs['auth'] = self._auth
        
        response = self._client.request(method, url, **kwargs)
        response.raise_for_status()
        
        return response.json()
    
    def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test connection to Airflow."""
        try:
            result = self._request('GET', '/health')
            status = result.get('metadatabase', {}).get('status', 'unknown')
            return True, f"Airflow connected, DB status: {status}"
        except Exception as e:
            return False, str(e)
    
    def get_dags(self, 
                 only_active: bool = True,
                 tags: Optional[List[str]] = None) -> List[AirflowDAG]:
        """
        Get list of DAGs.
        
        Args:
            only_active: Only return active DAGs
            tags: Filter by tags
            
        Returns:
            List of AirflowDAG objects
        """
        params = {'limit': 100}
        if only_active:
            params['only_active'] = 'true'
        if tags:
            params['tags'] = tags
        
        try:
            result = self._request('GET', '/dags', params=params)
            
            dags = []
            for dag_data in result.get('dags', []):
                dags.append(AirflowDAG(
                    dag_id=dag_data.get('dag_id', ''),
                    description=dag_data.get('description'),
                    schedule_interval=dag_data.get('schedule_interval', {}).get('value'),
                    is_paused=dag_data.get('is_paused', False),
                    is_active=dag_data.get('is_active', True),
                    tags=[t.get('name', '') for t in dag_data.get('tags', [])],
                    owners=dag_data.get('owners', []),
                ))
            
            return dags
            
        except Exception as e:
            logger.error(f"Failed to get DAGs: {e}")
            return []
    
    def get_dag_runs(self,
                     dag_id: str,
                     limit: int = 25,
                     state: Optional[str] = None,
                     start_date: Optional[datetime] = None) -> List[AirflowDAGRun]:
        """
        Get DAG runs for a specific DAG.
        
        Args:
            dag_id: The DAG ID
            limit: Max runs to return
            state: Filter by state
            start_date: Filter runs after this date
            
        Returns:
            List of AirflowDAGRun objects
        """
        params = {'limit': limit, 'order_by': '-execution_date'}
        if state:
            params['state'] = state
        if start_date:
            params['start_date_gte'] = start_date.isoformat()
        
        try:
            result = self._request('GET', f'/dags/{dag_id}/dagRuns', params=params)
            
            runs = []
            for run_data in result.get('dag_runs', []):
                try:
                    state = DAGState(run_data.get('state', 'queued'))
                except ValueError:
                    state = DAGState.QUEUED
                
                runs.append(AirflowDAGRun(
                    dag_id=dag_id,
                    run_id=run_data.get('dag_run_id', ''),
                    state=state,
                    execution_date=self._parse_datetime(run_data.get('execution_date')),
                    start_date=self._parse_datetime(run_data.get('start_date')),
                    end_date=self._parse_datetime(run_data.get('end_date')),
                    external_trigger=run_data.get('external_trigger', False),
                    conf=run_data.get('conf', {}),
                ))
            
            return runs
            
        except Exception as e:
            logger.error(f"Failed to get DAG runs for {dag_id}: {e}")
            return []
    
    def get_task_instances(self,
                           dag_id: str,
                           dag_run_id: str) -> List[AirflowTask]:
        """
        Get task instances for a DAG run.
        
        Args:
            dag_id: The DAG ID
            dag_run_id: The DAG run ID
            
        Returns:
            List of AirflowTask objects
        """
        try:
            result = self._request(
                'GET', 
                f'/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances'
            )
            
            tasks = []
            for task_data in result.get('task_instances', []):
                try:
                    state = TaskState(task_data.get('state', 'queued'))
                except ValueError:
                    state = TaskState.QUEUED
                
                tasks.append(AirflowTask(
                    task_id=task_data.get('task_id', ''),
                    dag_id=dag_id,
                    state=state,
                    execution_date=self._parse_datetime(task_data.get('execution_date')),
                    start_date=self._parse_datetime(task_data.get('start_date')),
                    end_date=self._parse_datetime(task_data.get('end_date')),
                    duration=task_data.get('duration'),
                    try_number=task_data.get('try_number', 1),
                    max_tries=task_data.get('max_tries', 1),
                    operator=task_data.get('operator'),
                    pool=task_data.get('pool'),
                    queue=task_data.get('queue'),
                ))
            
            return tasks
            
        except Exception as e:
            logger.error(f"Failed to get task instances: {e}")
            return []
    
    def get_sla_misses(self, 
                       dag_id: Optional[str] = None,
                       limit: int = 100) -> List[SLAMiss]:
        """
        Get SLA miss events.
        
        Args:
            dag_id: Filter by DAG ID (optional)
            limit: Max events to return
            
        Returns:
            List of SLAMiss objects
        """
        # Note: SLA misses endpoint varies by Airflow version
        # This is for Airflow 2.x
        try:
            endpoint = '/sla_misses' if not dag_id else f'/dags/{dag_id}/sla_misses'
            result = self._request('GET', endpoint, params={'limit': limit})
            
            misses = []
            for miss_data in result.get('sla_misses', []):
                misses.append(SLAMiss(
                    dag_id=miss_data.get('dag_id', ''),
                    task_id=miss_data.get('task_id', ''),
                    execution_date=self._parse_datetime(miss_data.get('execution_date')),
                    expected_time=self._parse_datetime(miss_data.get('timestamp')),
                    description=miss_data.get('description'),
                ))
            
            return misses
            
        except Exception as e:
            logger.warning(f"Failed to get SLA misses: {e}")
            return []
    
    def analyze_dag_health(self, dag_id: str, days: int = 7) -> Dict[str, Any]:
        """
        Analyze health metrics for a DAG.
        
        Args:
            dag_id: The DAG ID
            days: Number of days to analyze
            
        Returns:
            Dict with health metrics
        """
        start_date = datetime.now() - timedelta(days=days)
        runs = self.get_dag_runs(dag_id, limit=100, start_date=start_date)
        
        if not runs:
            return {
                'dag_id': dag_id,
                'total_runs': 0,
                'status': 'no_runs',
            }
        
        # Calculate metrics
        successful = [r for r in runs if r.state == DAGState.SUCCESS]
        failed = [r for r in runs if r.state == DAGState.FAILED]
        
        success_rate = len(successful) / len(runs) if runs else 0
        
        # Calculate average duration
        durations = [r.duration_minutes for r in successful if r.duration_minutes]
        avg_duration = sum(durations) / len(durations) if durations else None
        
        # Find longest running
        max_duration = max(durations) if durations else None
        
        # Recent failures
        recent_failures = [
            {
                'run_id': r.run_id,
                'execution_date': r.execution_date.isoformat() if r.execution_date else None,
            }
            for r in failed[:5]
        ]
        
        # Determine health status
        if success_rate >= 0.95:
            status = 'healthy'
        elif success_rate >= 0.8:
            status = 'degraded'
        else:
            status = 'unhealthy'
        
        return {
            'dag_id': dag_id,
            'analysis_period_days': days,
            'total_runs': len(runs),
            'successful_runs': len(successful),
            'failed_runs': len(failed),
            'success_rate_pct': round(success_rate * 100, 1),
            'avg_duration_minutes': round(avg_duration, 2) if avg_duration else None,
            'max_duration_minutes': round(max_duration, 2) if max_duration else None,
            'recent_failures': recent_failures,
            'status': status,
        }
    
    def get_pipeline_freshness(self, dag_id: str) -> Dict[str, Any]:
        """
        Get freshness info for a data pipeline DAG.
        
        Args:
            dag_id: The DAG ID
            
        Returns:
            Dict with freshness info
        """
        runs = self.get_dag_runs(dag_id, limit=1, state='success')
        
        if not runs:
            return {
                'dag_id': dag_id,
                'last_success': None,
                'hours_since_success': None,
                'status': 'never_succeeded',
            }
        
        last_run = runs[0]
        last_success = last_run.end_date or last_run.start_date
        
        if last_success:
            hours_since = (datetime.now() - last_success).total_seconds() / 3600
        else:
            hours_since = None
        
        return {
            'dag_id': dag_id,
            'last_success': last_success.isoformat() if last_success else None,
            'hours_since_success': round(hours_since, 1) if hours_since else None,
            'last_run_duration_minutes': last_run.duration_minutes,
        }
    
    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse datetime string."""
        if not value:
            return None
        try:
            # Handle various formats
            if 'T' in value:
                return datetime.fromisoformat(value.replace('Z', '+00:00'))
            return datetime.fromisoformat(value)
        except Exception:
            return None
    
    def close(self):
        """Close the HTTP client."""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()

