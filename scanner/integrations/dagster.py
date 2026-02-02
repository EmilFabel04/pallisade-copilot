"""
Dagster Integration

Monitor Dagster assets and jobs:
- Asset materialization health
- Job run status
- Op execution metrics
- Sensor and schedule health
- Asset lineage

Supports:
- Dagster GraphQL API (dagit/dagster-webserver)
- Dagster Cloud API
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class RunStatus(Enum):
    """Dagster run statuses."""
    QUEUED = "QUEUED"
    NOT_STARTED = "NOT_STARTED"
    STARTING = "STARTING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELING = "CANCELING"
    CANCELED = "CANCELED"


class AssetCheckSeverity(Enum):
    """Asset check severity levels."""
    ERROR = "ERROR"
    WARN = "WARN"


@dataclass
class DagsterAsset:
    """A Dagster asset."""
    key: str  # e.g., "my_asset" or "group/my_asset"
    group_name: Optional[str] = None
    description: Optional[str] = None
    compute_kind: Optional[str] = None  # e.g., "dbt", "python", "sql"
    owners: List[str] = field(default_factory=list)
    tags: Dict[str, str] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # upstream asset keys
    
    # Materialization info
    last_materialization: Optional[datetime] = None
    last_materialization_run_id: Optional[str] = None
    is_partitioned: bool = False
    
    # Health
    has_checks: bool = False
    last_check_passed: Optional[bool] = None


@dataclass
class DagsterRun:
    """A Dagster job/pipeline run."""
    run_id: str
    job_name: str
    status: RunStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    tags: Dict[str, str] = field(default_factory=dict)
    
    # Asset info
    asset_keys: List[str] = field(default_factory=list)
    
    @property
    def duration(self) -> Optional[timedelta]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None
    
    @property
    def duration_minutes(self) -> Optional[float]:
        d = self.duration
        return d.total_seconds() / 60 if d else None
    
    @property
    def is_success(self) -> bool:
        return self.status == RunStatus.SUCCESS
    
    @property
    def is_failed(self) -> bool:
        return self.status == RunStatus.FAILURE


@dataclass
class DagsterSchedule:
    """A Dagster schedule."""
    name: str
    cron_schedule: str
    job_name: str
    status: str  # RUNNING, STOPPED
    next_tick: Optional[datetime] = None
    
    @property
    def is_running(self) -> bool:
        return self.status == "RUNNING"


@dataclass
class DagsterSensor:
    """A Dagster sensor."""
    name: str
    job_name: Optional[str] = None
    status: str = "STOPPED"  # RUNNING, STOPPED
    min_interval_seconds: int = 30
    
    @property
    def is_running(self) -> bool:
        return self.status == "RUNNING"


class DagsterIntegration:
    """
    Dagster integration for Pallisade.
    
    Capabilities:
    - List and monitor assets
    - Track job/pipeline runs
    - Monitor asset materializations
    - Analyze asset health and freshness
    - Track schedules and sensors
    """
    
    # GraphQL queries
    ASSETS_QUERY = """
    query AssetsQuery {
        assetsOrError {
            ... on AssetConnection {
                nodes {
                    key {
                        path
                    }
                    definition {
                        groupName
                        description
                        computeKind
                        owners {
                            ... on TeamAssetOwner { team }
                            ... on UserAssetOwner { email }
                        }
                        assetKey {
                            path
                        }
                        dependencyKeys {
                            path
                        }
                        isPartitioned
                    }
                }
            }
        }
    }
    """
    
    RUNS_QUERY = """
    query RunsQuery($limit: Int!, $filter: RunsFilter) {
        runsOrError(limit: $limit, filter: $filter) {
            ... on Runs {
                results {
                    runId
                    pipelineName
                    status
                    startTime
                    endTime
                    tags {
                        key
                        value
                    }
                    assetSelection {
                        path
                    }
                }
            }
        }
    }
    """
    
    ASSET_MATERIALIZATION_QUERY = """
    query AssetMaterializationQuery($assetKey: AssetKeyInput!) {
        assetOrError(assetKey: $assetKey) {
            ... on Asset {
                assetMaterializations(limit: 1) {
                    runId
                    timestamp
                }
            }
        }
    }
    """
    
    SCHEDULES_QUERY = """
    query SchedulesQuery {
        schedulesOrError {
            ... on Schedules {
                results {
                    name
                    cronSchedule
                    pipelineName
                    scheduleState {
                        status
                    }
                    futureTicks(limit: 1) {
                        results {
                            timestamp
                        }
                    }
                }
            }
        }
    }
    """
    
    SENSORS_QUERY = """
    query SensorsQuery {
        sensorsOrError {
            ... on Sensors {
                results {
                    name
                    targets {
                        pipelineName
                    }
                    sensorState {
                        status
                    }
                    minIntervalSeconds
                }
            }
        }
    }
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Dagster integration.
        
        Config options:
            base_url: Dagster webserver URL (e.g., http://localhost:3000)
            
        For Dagster Cloud:
            deployment_name: Dagster Cloud deployment name
            api_token: Dagster Cloud API token
        """
        self.config = config
        
        if config.get('deployment_name'):
            # Dagster Cloud
            deployment = config['deployment_name']
            self.graphql_url = f"https://{deployment}.dagster.cloud/graphql"
            self._client = httpx.Client(
                timeout=30,
                headers={'Dagster-Cloud-Api-Token': config.get('api_token', '')}
            )
        else:
            # Self-hosted Dagster
            base_url = config.get('base_url', 'http://localhost:3000').rstrip('/')
            self.graphql_url = f"{base_url}/graphql"
            self._client = httpx.Client(timeout=30)
    
    def _query(self, query: str, variables: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute GraphQL query."""
        response = self._client.post(
            self.graphql_url,
            json={'query': query, 'variables': variables or {}}
        )
        response.raise_for_status()
        result = response.json()
        
        if 'errors' in result:
            raise Exception(f"GraphQL errors: {result['errors']}")
        
        return result.get('data', {})
    
    def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test connection to Dagster."""
        try:
            # Simple query to test connection
            query = "query { version }"
            result = self._query(query)
            version = result.get('version', 'unknown')
            return True, f"Dagster connected, version: {version}"
        except Exception as e:
            return False, str(e)
    
    def get_assets(self) -> List[DagsterAsset]:
        """Get all assets."""
        try:
            result = self._query(self.ASSETS_QUERY)
            assets_data = result.get('assetsOrError', {}).get('nodes', [])
            
            assets = []
            for asset_data in assets_data:
                key_path = asset_data.get('key', {}).get('path', [])
                key = '/'.join(key_path)
                
                definition = asset_data.get('definition', {}) or {}
                
                # Parse owners
                owners = []
                for owner in definition.get('owners', []):
                    if owner.get('team'):
                        owners.append(f"team:{owner['team']}")
                    elif owner.get('email'):
                        owners.append(owner['email'])
                
                # Parse dependencies
                deps = []
                for dep in definition.get('dependencyKeys', []):
                    deps.append('/'.join(dep.get('path', [])))
                
                assets.append(DagsterAsset(
                    key=key,
                    group_name=definition.get('groupName'),
                    description=definition.get('description'),
                    compute_kind=definition.get('computeKind'),
                    owners=owners,
                    dependencies=deps,
                    is_partitioned=definition.get('isPartitioned', False),
                ))
            
            return assets
            
        except Exception as e:
            logger.error(f"Failed to get assets: {e}")
            return []
    
    def get_runs(self, 
                 limit: int = 25,
                 job_name: Optional[str] = None,
                 status: Optional[RunStatus] = None) -> List[DagsterRun]:
        """Get recent runs."""
        try:
            filter_dict = {}
            if job_name:
                filter_dict['pipelineName'] = job_name
            if status:
                filter_dict['statuses'] = [status.value]
            
            variables = {
                'limit': limit,
                'filter': filter_dict if filter_dict else None
            }
            
            result = self._query(self.RUNS_QUERY, variables)
            runs_data = result.get('runsOrError', {}).get('results', [])
            
            runs = []
            for run_data in runs_data:
                try:
                    status = RunStatus(run_data.get('status', 'NOT_STARTED'))
                except ValueError:
                    status = RunStatus.NOT_STARTED
                
                # Parse tags
                tags = {}
                for tag in run_data.get('tags', []):
                    tags[tag['key']] = tag['value']
                
                # Parse asset keys
                asset_keys = []
                for asset in run_data.get('assetSelection', []) or []:
                    asset_keys.append('/'.join(asset.get('path', [])))
                
                runs.append(DagsterRun(
                    run_id=run_data.get('runId', ''),
                    job_name=run_data.get('pipelineName', ''),
                    status=status,
                    start_time=self._parse_timestamp(run_data.get('startTime')),
                    end_time=self._parse_timestamp(run_data.get('endTime')),
                    tags=tags,
                    asset_keys=asset_keys,
                ))
            
            return runs
            
        except Exception as e:
            logger.error(f"Failed to get runs: {e}")
            return []
    
    def get_asset_materialization(self, asset_key: str) -> Optional[Dict[str, Any]]:
        """Get last materialization for an asset."""
        try:
            variables = {'assetKey': {'path': asset_key.split('/')}}
            result = self._query(self.ASSET_MATERIALIZATION_QUERY, variables)
            
            asset_data = result.get('assetOrError', {})
            materializations = asset_data.get('assetMaterializations', [])
            
            if not materializations:
                return None
            
            mat = materializations[0]
            return {
                'run_id': mat.get('runId'),
                'timestamp': self._parse_timestamp(mat.get('timestamp')),
            }
            
        except Exception as e:
            logger.warning(f"Failed to get materialization for {asset_key}: {e}")
            return None
    
    def get_schedules(self) -> List[DagsterSchedule]:
        """Get all schedules."""
        try:
            result = self._query(self.SCHEDULES_QUERY)
            schedules_data = result.get('schedulesOrError', {}).get('results', [])
            
            schedules = []
            for sched_data in schedules_data:
                next_tick = None
                ticks = sched_data.get('futureTicks', {}).get('results', [])
                if ticks:
                    next_tick = self._parse_timestamp(ticks[0].get('timestamp'))
                
                schedules.append(DagsterSchedule(
                    name=sched_data.get('name', ''),
                    cron_schedule=sched_data.get('cronSchedule', ''),
                    job_name=sched_data.get('pipelineName', ''),
                    status=sched_data.get('scheduleState', {}).get('status', 'STOPPED'),
                    next_tick=next_tick,
                ))
            
            return schedules
            
        except Exception as e:
            logger.error(f"Failed to get schedules: {e}")
            return []
    
    def get_sensors(self) -> List[DagsterSensor]:
        """Get all sensors."""
        try:
            result = self._query(self.SENSORS_QUERY)
            sensors_data = result.get('sensorsOrError', {}).get('results', [])
            
            sensors = []
            for sensor_data in sensors_data:
                targets = sensor_data.get('targets', [])
                job_name = targets[0].get('pipelineName') if targets else None
                
                sensors.append(DagsterSensor(
                    name=sensor_data.get('name', ''),
                    job_name=job_name,
                    status=sensor_data.get('sensorState', {}).get('status', 'STOPPED'),
                    min_interval_seconds=sensor_data.get('minIntervalSeconds', 30),
                ))
            
            return sensors
            
        except Exception as e:
            logger.error(f"Failed to get sensors: {e}")
            return []
    
    def analyze_asset_health(self, asset_key: str, days: int = 7) -> Dict[str, Any]:
        """Analyze health of an asset."""
        # Get materialization info
        materialization = self.get_asset_materialization(asset_key)
        
        # Get recent runs that touched this asset
        all_runs = self.get_runs(limit=100)
        asset_runs = [r for r in all_runs if asset_key in r.asset_keys]
        
        # Filter to recent period
        cutoff = datetime.now() - timedelta(days=days)
        recent_runs = [r for r in asset_runs if r.start_time and r.start_time > cutoff]
        
        # Calculate metrics
        successful = [r for r in recent_runs if r.is_success]
        failed = [r for r in recent_runs if r.is_failed]
        
        success_rate = len(successful) / len(recent_runs) if recent_runs else None
        
        # Freshness
        hours_since_materialization = None
        if materialization and materialization.get('timestamp'):
            delta = datetime.now() - materialization['timestamp']
            hours_since_materialization = delta.total_seconds() / 3600
        
        # Health status
        if success_rate is None:
            status = 'unknown'
        elif success_rate >= 0.95:
            status = 'healthy'
        elif success_rate >= 0.8:
            status = 'degraded'
        else:
            status = 'unhealthy'
        
        return {
            'asset_key': asset_key,
            'analysis_period_days': days,
            'total_runs': len(recent_runs),
            'successful_runs': len(successful),
            'failed_runs': len(failed),
            'success_rate_pct': round(success_rate * 100, 1) if success_rate else None,
            'last_materialization': materialization.get('timestamp').isoformat() if materialization and materialization.get('timestamp') else None,
            'hours_since_materialization': round(hours_since_materialization, 1) if hours_since_materialization else None,
            'status': status,
        }
    
    def analyze_job_health(self, job_name: str, days: int = 7) -> Dict[str, Any]:
        """Analyze health of a job."""
        runs = self.get_runs(limit=100, job_name=job_name)
        
        # Filter to recent period
        cutoff = datetime.now() - timedelta(days=days)
        recent_runs = [r for r in runs if r.start_time and r.start_time > cutoff]
        
        if not recent_runs:
            return {
                'job_name': job_name,
                'total_runs': 0,
                'status': 'no_runs',
            }
        
        successful = [r for r in recent_runs if r.is_success]
        failed = [r for r in recent_runs if r.is_failed]
        
        success_rate = len(successful) / len(recent_runs)
        
        # Calculate durations
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
            'job_name': job_name,
            'analysis_period_days': days,
            'total_runs': len(recent_runs),
            'successful_runs': len(successful),
            'failed_runs': len(failed),
            'success_rate_pct': round(success_rate * 100, 1),
            'avg_duration_minutes': round(avg_duration, 2) if avg_duration else None,
            'status': status,
            'recent_failures': [
                {'run_id': r.run_id, 'start_time': r.start_time.isoformat() if r.start_time else None}
                for r in failed[:5]
            ],
        }
    
    def _parse_timestamp(self, value) -> Optional[datetime]:
        """Parse timestamp (float or string)."""
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value)
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
