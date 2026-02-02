"""
Fivetran Integration

Monitor Fivetran connectors and sync health:
- Connector status and sync frequency
- Table sync times
- Data freshness from Fivetran metadata
- Error tracking
- Schema changes from Fivetran

Uses Fivetran REST API v1.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import httpx
import base64

logger = logging.getLogger(__name__)


class ConnectorStatus(Enum):
    """Fivetran connector status."""
    CONNECTED = "connected"
    PAUSED = "paused"
    BROKEN = "broken"
    INCOMPLETE = "incomplete"
    DISCONNECTED = "disconnected"


class SyncStatus(Enum):
    """Fivetran sync status."""
    SCHEDULED = "scheduled"
    SYNCING = "syncing"
    RESCHEDULED = "rescheduled"
    PENDING = "pending"


@dataclass
class FivetranTable:
    """A table synced by Fivetran."""
    name: str
    schema: str
    enabled: bool = True
    sync_state: Optional[str] = None
    rows_synced: Optional[int] = None
    bytes_synced: Optional[int] = None
    
    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass
class FivetranConnector:
    """A Fivetran connector."""
    id: str
    name: str
    service: str  # e.g., 'postgres', 'salesforce', 'google_sheets'
    schema: str  # destination schema
    status: ConnectorStatus
    sync_state: SyncStatus
    
    # Timing
    succeeded_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    last_sync_started: Optional[datetime] = None
    
    # Config
    sync_frequency: int = 360  # minutes
    paused: bool = False
    daily_sync_time: Optional[str] = None
    
    # Metadata
    group_id: Optional[str] = None
    destination_id: Optional[str] = None
    
    # Tables
    tables: List[FivetranTable] = field(default_factory=list)
    
    @property
    def is_healthy(self) -> bool:
        return self.status == ConnectorStatus.CONNECTED and not self.paused
    
    @property
    def hours_since_success(self) -> Optional[float]:
        if not self.succeeded_at:
            return None
        return (datetime.now() - self.succeeded_at).total_seconds() / 3600
    
    @property
    def is_stale(self) -> bool:
        """Check if connector hasn't synced in expected time."""
        if not self.succeeded_at:
            return True
        # Allow 50% buffer on sync frequency
        max_hours = (self.sync_frequency / 60) * 1.5
        hours = self.hours_since_success
        return hours is not None and hours > max_hours


@dataclass
class FivetranGroup:
    """A Fivetran group (collection of connectors)."""
    id: str
    name: str
    created_at: Optional[datetime] = None
    connectors: List[FivetranConnector] = field(default_factory=list)


class FivetranIntegration:
    """
    Fivetran integration for Pallisade.
    
    Capabilities:
    - List connectors and their status
    - Monitor sync health
    - Track data freshness
    - Detect sync failures
    - Get table-level metadata
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Fivetran integration.
        
        Config options:
            api_key: Fivetran API key
            api_secret: Fivetran API secret
            
        Get credentials from:
        https://fivetran.com/account/settings/account
        """
        self.config = config
        self.base_url = "https://api.fivetran.com/v1"
        
        # Setup authentication
        api_key = config.get('api_key', '')
        api_secret = config.get('api_secret', '')
        
        credentials = f"{api_key}:{api_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        
        self._client = httpx.Client(
            timeout=30,
            headers={
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/json',
            }
        )
    
    def _request(self, 
                 method: str, 
                 endpoint: str, 
                 **kwargs) -> Dict[str, Any]:
        """Make an authenticated request to Fivetran API."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self._client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()
    
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """Test connection to Fivetran."""
        try:
            result = self._request('GET', '/users')
            user = result.get('data', {}).get('id', 'unknown')
            return True, f"Fivetran connected as user: {user}"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return False, "Invalid API credentials"
            return False, str(e)
        except Exception as e:
            return False, str(e)
    
    def get_groups(self) -> List[FivetranGroup]:
        """
        Get all Fivetran groups.
        
        Returns:
            List of FivetranGroup objects
        """
        try:
            result = self._request('GET', '/groups')
            
            groups = []
            for group_data in result.get('data', {}).get('items', []):
                groups.append(FivetranGroup(
                    id=group_data.get('id', ''),
                    name=group_data.get('name', ''),
                    created_at=self._parse_datetime(group_data.get('created_at')),
                ))
            
            return groups
            
        except Exception as e:
            logger.error(f"Failed to get groups: {e}")
            return []
    
    def get_connectors(self, group_id: Optional[str] = None) -> List[FivetranConnector]:
        """
        Get connectors, optionally filtered by group.
        
        Args:
            group_id: Optional group ID to filter by
            
        Returns:
            List of FivetranConnector objects
        """
        try:
            if group_id:
                result = self._request('GET', f'/groups/{group_id}/connectors')
                connectors_data = result.get('data', {}).get('items', [])
            else:
                # Get all connectors from all groups
                groups = self.get_groups()
                connectors_data = []
                for group in groups:
                    result = self._request('GET', f'/groups/{group.id}/connectors')
                    items = result.get('data', {}).get('items', [])
                    for item in items:
                        item['group_id'] = group.id
                    connectors_data.extend(items)
            
            connectors = []
            for conn_data in connectors_data:
                connector = self._parse_connector(conn_data)
                connectors.append(connector)
            
            return connectors
            
        except Exception as e:
            logger.error(f"Failed to get connectors: {e}")
            return []
    
    def get_connector(self, connector_id: str) -> Optional[FivetranConnector]:
        """
        Get details for a specific connector.
        
        Args:
            connector_id: The connector ID
            
        Returns:
            FivetranConnector object or None
        """
        try:
            result = self._request('GET', f'/connectors/{connector_id}')
            return self._parse_connector(result.get('data', {}))
        except Exception as e:
            logger.error(f"Failed to get connector {connector_id}: {e}")
            return None
    
    def get_connector_schema(self, connector_id: str) -> Dict[str, Any]:
        """
        Get schema information for a connector.
        
        Args:
            connector_id: The connector ID
            
        Returns:
            Dict with schema and table information
        """
        try:
            result = self._request('GET', f'/connectors/{connector_id}/schemas')
            
            schemas = {}
            for schema_name, schema_data in result.get('data', {}).get('schemas', {}).items():
                tables = []
                for table_name, table_data in schema_data.get('tables', {}).items():
                    tables.append(FivetranTable(
                        name=table_name,
                        schema=schema_name,
                        enabled=table_data.get('enabled', True),
                        sync_state=table_data.get('sync_state'),
                    ))
                schemas[schema_name] = {
                    'enabled': schema_data.get('enabled', True),
                    'tables': tables,
                }
            
            return schemas
            
        except Exception as e:
            logger.error(f"Failed to get schema for {connector_id}: {e}")
            return {}
    
    def get_sync_logs(self, 
                      connector_id: str, 
                      limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent sync logs for a connector.
        
        Args:
            connector_id: The connector ID
            limit: Max logs to return
            
        Returns:
            List of sync log entries
        """
        try:
            result = self._request(
                'GET', 
                f'/connectors/{connector_id}/sync',
                params={'limit': limit}
            )
            
            logs = []
            for log in result.get('data', {}).get('logs', []):
                logs.append({
                    'timestamp': log.get('timestamp'),
                    'message': log.get('message'),
                    'sync_type': log.get('sync_type'),
                })
            
            return logs
            
        except Exception as e:
            logger.warning(f"Failed to get sync logs: {e}")
            return []
    
    def analyze_connector_health(self, connector_id: str) -> Dict[str, Any]:
        """
        Analyze health of a connector.
        
        Args:
            connector_id: The connector ID
            
        Returns:
            Dict with health metrics
        """
        connector = self.get_connector(connector_id)
        if not connector:
            return {
                'connector_id': connector_id,
                'status': 'not_found',
            }
        
        # Determine health status
        if connector.status == ConnectorStatus.BROKEN:
            status = 'critical'
            issues = ['Connector is broken']
        elif connector.paused:
            status = 'warning'
            issues = ['Connector is paused']
        elif connector.is_stale:
            status = 'warning'
            issues = [f'No successful sync in {connector.hours_since_success:.1f} hours']
        else:
            status = 'healthy'
            issues = []
        
        # Get schema info
        schemas = self.get_connector_schema(connector_id)
        total_tables = sum(
            len(s['tables']) for s in schemas.values()
        )
        enabled_tables = sum(
            sum(1 for t in s['tables'] if t.enabled)
            for s in schemas.values()
        )
        
        return {
            'connector_id': connector_id,
            'connector_name': connector.name,
            'service': connector.service,
            'status': status,
            'issues': issues,
            'connector_status': connector.status.value,
            'sync_state': connector.sync_state.value,
            'paused': connector.paused,
            'last_success': connector.succeeded_at.isoformat() if connector.succeeded_at else None,
            'hours_since_success': round(connector.hours_since_success, 1) if connector.hours_since_success else None,
            'sync_frequency_minutes': connector.sync_frequency,
            'total_tables': total_tables,
            'enabled_tables': enabled_tables,
        }
    
    def get_all_connector_freshness(self) -> List[Dict[str, Any]]:
        """
        Get freshness info for all connectors.
        
        Returns:
            List of freshness info dicts
        """
        connectors = self.get_connectors()
        
        results = []
        for connector in connectors:
            results.append({
                'connector_id': connector.id,
                'connector_name': connector.name,
                'service': connector.service,
                'schema': connector.schema,
                'is_healthy': connector.is_healthy,
                'is_stale': connector.is_stale,
                'last_success': connector.succeeded_at.isoformat() if connector.succeeded_at else None,
                'hours_since_success': round(connector.hours_since_success, 1) if connector.hours_since_success else None,
                'expected_frequency_hours': connector.sync_frequency / 60,
            })
        
        # Sort by staleness
        results.sort(
            key=lambda x: x['hours_since_success'] or float('inf'),
            reverse=True
        )
        
        return results
    
    def trigger_sync(self, connector_id: str) -> Tuple[bool, str]:
        """
        Trigger a manual sync for a connector.
        
        Args:
            connector_id: The connector ID
            
        Returns:
            Tuple of (success, message)
        """
        try:
            self._request('POST', f'/connectors/{connector_id}/force')
            return True, "Sync triggered successfully"
        except httpx.HTTPStatusError as e:
            return False, f"Failed to trigger sync: {e.response.text}"
        except Exception as e:
            return False, str(e)
    
    def _parse_connector(self, data: Dict[str, Any]) -> FivetranConnector:
        """Parse connector data from API response."""
        # Parse status
        try:
            status = ConnectorStatus(data.get('status', {}).get('setup_state', 'incomplete'))
        except ValueError:
            status = ConnectorStatus.INCOMPLETE
        
        # Parse sync state
        try:
            sync_state = SyncStatus(data.get('status', {}).get('sync_state', 'scheduled'))
        except ValueError:
            sync_state = SyncStatus.SCHEDULED
        
        return FivetranConnector(
            id=data.get('id', ''),
            name=data.get('schema', ''),  # Fivetran uses schema as connector name
            service=data.get('service', ''),
            schema=data.get('schema', ''),
            status=status,
            sync_state=sync_state,
            succeeded_at=self._parse_datetime(data.get('succeeded_at')),
            failed_at=self._parse_datetime(data.get('failed_at')),
            last_sync_started=self._parse_datetime(
                data.get('status', {}).get('sync_state_timestamp')
            ),
            sync_frequency=data.get('sync_frequency', 360),
            paused=data.get('paused', False),
            daily_sync_time=data.get('daily_sync_time'),
            group_id=data.get('group_id'),
        )
    
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

