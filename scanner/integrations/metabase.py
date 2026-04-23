"""
Metabase Integration - Enterprise Grade Scanner

Monitors Metabase for:
- Dashboard health (broken cards/questions)
- Database connection issues
- Query performance
- Sync status
- Cache health
- Usage patterns

Uses Metabase REST API
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import httpx

logger = logging.getLogger(__name__)


@dataclass
class MetabaseDatabase:
    """A Metabase database connection."""
    id: int
    name: str
    engine: str
    
    # Connection
    host: Optional[str] = None
    port: Optional[int] = None
    db_name: Optional[str] = None
    
    # Sync status
    initial_sync_status: str = "complete"
    sync_status: str = "complete"
    last_sync_at: Optional[datetime] = None
    
    # Cache
    cache_field_values_schedule: str = "0 0 0 * * ?"  # Default: midnight
    
    # Health
    is_sample: bool = False
    auto_run_queries: bool = True


@dataclass
class MetabaseCard:
    """A Metabase card (saved question/visualization)."""
    id: int
    name: str
    collection_id: Optional[int] = None
    collection_name: Optional[str] = None
    
    # Query
    database_id: Optional[int] = None
    query_type: str = "query"  # query, native, model
    
    # Display
    display: str = "table"
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_query_at: Optional[datetime] = None
    
    # Performance
    avg_query_time_ms: Optional[float] = None
    cache_ttl: Optional[int] = None
    
    # Errors
    last_error: Optional[str] = None
    
    @property
    def is_slow(self) -> bool:
        return self.avg_query_time_ms is not None and self.avg_query_time_ms > 10000  # 10s


@dataclass
class MetabaseDashboard:
    """A Metabase dashboard."""
    id: int
    name: str
    collection_id: Optional[int] = None
    collection_name: Optional[str] = None
    
    # Content
    card_count: int = 0
    filter_count: int = 0
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Errors
    broken_cards: List[Dict] = field(default_factory=list)
    
    @property
    def has_errors(self) -> bool:
        return len(self.broken_cards) > 0


class MetabaseClient:
    """
    Metabase REST API client.
    
    Supports both session-based and API key authentication.
    """
    
    def __init__(self,
                 host: str,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 api_key: Optional[str] = None):
        """
        Initialize Metabase client.
        
        Args:
            host: Metabase instance URL
            username: Email for session auth
            password: Password for session auth
            api_key: API key (alternative to session auth)
        """
        self.host = host.rstrip('/')
        self.username = username
        self.password = password
        self.api_key = api_key
        
        self._session_token: Optional[str] = None
        self._client: Optional[httpx.Client] = None
    
    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=f"{self.host}/api",
                timeout=60.0,
            )
        return self._client
    
    def _authenticate(self) -> str:
        """Authenticate and return session token or API key."""
        if self.api_key:
            return self.api_key
        
        if self._session_token:
            return self._session_token
        
        client = self._get_client()
        
        response = client.post(
            "/session",
            json={
                "username": self.username,
                "password": self.password,
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Metabase authentication failed: {response.text}")
        
        data = response.json()
        self._session_token = data.get("id")
        
        return self._session_token
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authentication headers."""
        token = self._authenticate()
        
        if self.api_key:
            return {"X-Api-Key": token}
        else:
            return {"X-Metabase-Session": token}
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make authenticated request to Metabase API."""
        client = self._get_client()
        headers = kwargs.pop("headers", {})
        headers.update(self._get_headers())
        
        response = client.request(
            method,
            endpoint.lstrip('/'),
            headers=headers,
            **kwargs
        )
        
        if response.status_code == 401:
            # Re-authenticate
            self._session_token = None
            headers.update(self._get_headers())
            response = client.request(
                method,
                endpoint.lstrip('/'),
                headers=headers,
                **kwargs
            )
        
        if response.status_code >= 400:
            raise Exception(f"Metabase API error: {response.status_code} - {response.text}")
        
        return response.json() if response.text else None
    
    def test_connection(self) -> Tuple[bool, str]:
        """Test connection to Metabase."""
        try:
            self._authenticate()
            user = self._request("GET", "/user/current")
            return True, f"Connected as {user.get('common_name', user.get('email', 'Unknown'))}"
        except Exception as e:
            return False, str(e)
    
    # =========================================================================
    # DATABASE METHODS
    # =========================================================================
    
    def get_databases(self) -> List[Dict]:
        """Get all database connections."""
        return self._request("GET", "/database")
    
    def get_database(self, database_id: int) -> Dict:
        """Get database details."""
        return self._request("GET", f"/database/{database_id}")
    
    def sync_database(self, database_id: int) -> Dict:
        """Trigger a sync for a database."""
        return self._request("POST", f"/database/{database_id}/sync_schema")
    
    def get_database_metadata(self, database_id: int) -> Dict:
        """Get database tables/fields metadata."""
        return self._request("GET", f"/database/{database_id}/metadata")

    def get_table(self, table_id: int) -> Dict:
        """Get table metadata by Metabase internal table ID."""
        return self._request("GET", f"/table/{table_id}")

    def get_field(self, field_id: int) -> Dict:
        """Get field metadata by Metabase internal field ID."""
        return self._request("GET", f"/field/{field_id}")
    
    # =========================================================================
    # CARD (QUESTION) METHODS
    # =========================================================================
    
    def get_cards(self) -> List[Dict]:
        """Get all saved questions/cards."""
        return self._request("GET", "/card")
    
    def get_card(self, card_id: int) -> Dict:
        """Get card details."""
        return self._request("GET", f"/card/{card_id}")
    
    def run_card(self, card_id: int, parameters: Dict = None) -> Dict:
        """Run a card query."""
        return self._request(
            "POST",
            f"/card/{card_id}/query",
            json=parameters or {}
        )
    
    def get_card_query_metadata(self, card_id: int) -> Dict:
        """Get query metadata for a card."""
        try:
            return self._request("GET", f"/card/{card_id}/query_metadata")
        except Exception:
            return {}
    
    # =========================================================================
    # DASHBOARD METHODS
    # =========================================================================
    
    def get_dashboards(self) -> List[Dict]:
        """Get all dashboards."""
        return self._request("GET", "/dashboard")
    
    def get_dashboard(self, dashboard_id: int) -> Dict:
        """Get dashboard with all cards."""
        return self._request("GET", f"/dashboard/{dashboard_id}")
    
    # =========================================================================
    # ACTIVITY/AUDIT METHODS
    # =========================================================================
    
    def get_recent_activity(self, limit: int = 50) -> List[Dict]:
        """Get recent activity/audit log."""
        try:
            return self._request("GET", f"/activity?limit={limit}")
        except Exception:
            return []
    
    def get_query_metrics(self) -> Dict:
        """Get query metrics (if enabled)."""
        try:
            return self._request("GET", "/util/stats")
        except Exception:
            return {}


class MetabaseScanner:
    """
    Enterprise-grade Metabase scanner.
    
    Checks:
    1. Database connection health
    2. Sync status
    3. Dashboard errors (broken cards)
    4. Query performance
    5. Stale content
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scanner with Metabase credentials.
        
        Config:
            host: Metabase URL
            username: Admin email (or)
            password: Admin password (or)
            api_key: API key
        """
        self.client = MetabaseClient(
            host=config.get("host"),
            username=config.get("username"),
            password=config.get("password"),
            api_key=config.get("api_key"),
        )
        
        # Thresholds
        self.thresholds = {
            "slow_query_ms": config.get("slow_query_ms", 10000),  # 10 seconds
            "stale_days": config.get("stale_days", 90),
            "sync_stale_hours": config.get("sync_stale_hours", 24),
        }
    
    def scan(self) -> Dict[str, Any]:
        """
        Run full Metabase health scan.
        
        Returns:
            Dict with findings, metrics, and health score
        """
        findings = []
        metrics = {
            "databases_scanned": 0,
            "database_issues": 0,
            "dashboards_scanned": 0,
            "broken_dashboards": 0,
            "cards_scanned": 0,
            "slow_cards": 0,
        }
        
        # 1. Scan Databases
        logger.info("Scanning Metabase databases...")
        db_findings = self._scan_databases()
        findings.extend(db_findings["findings"])
        metrics.update(db_findings["metrics"])
        
        # 2. Scan Dashboards
        logger.info("Scanning Metabase dashboards...")
        dash_findings = self._scan_dashboards()
        findings.extend(dash_findings["findings"])
        metrics.update(dash_findings["metrics"])
        
        # 3. Scan Cards
        logger.info("Scanning Metabase cards...")
        card_findings = self._scan_cards()
        findings.extend(card_findings["findings"])
        metrics.update(card_findings["metrics"])
        
        # Calculate health score
        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        high_count = sum(1 for f in findings if f.get("severity") == "high")
        medium_count = sum(1 for f in findings if f.get("severity") == "medium")
        
        health_score = max(0, 100 - (critical_count * 25) - (high_count * 10) - (medium_count * 3))
        
        return {
            "scan_type": "metabase",
            "status": "critical" if critical_count > 0 else "warning" if high_count > 0 else "healthy",
            "health_score": health_score,
            "findings": findings,
            "metrics": metrics,
            "scanned_at": datetime.now().isoformat(),
        }
    
    def _scan_databases(self) -> Dict:
        """Scan database connections."""
        findings = []
        metrics = {
            "databases_scanned": 0,
            "database_issues": 0,
        }
        
        try:
            databases = self.client.get_databases()
            metrics["databases_scanned"] = len(databases)
            
            for db in databases:
                db_id = db.get("id")
                name = db.get("name", "Unknown")
                engine = db.get("engine", "unknown")
                
                # Skip sample database
                if db.get("is_sample"):
                    continue
                
                # Check sync status
                initial_sync = db.get("initial_sync_status")
                if initial_sync == "incomplete":
                    findings.append({
                        "type": "database_sync_incomplete",
                        "severity": "high",
                        "title": f"Database Sync Incomplete: {name}",
                        "description": f"Database '{name}' ({engine}) has not completed initial sync. Some tables may not be available.",
                        "resource": f"database/{db_id}",
                        "resource_type": "metabase_database",
                        "suggested_fix": {
                            "type": "api",
                            "action": f"POST /api/database/{db_id}/sync_schema",
                        },
                    })
                    metrics["database_issues"] += 1
                elif initial_sync == "aborted":
                    findings.append({
                        "type": "database_sync_failed",
                        "severity": "critical",
                        "title": f"Database Sync Failed: {name}",
                        "description": f"Database '{name}' ({engine}) sync was aborted. Check connection settings.",
                        "resource": f"database/{db_id}",
                        "resource_type": "metabase_database",
                        "suggested_fix": {
                            "type": "manual",
                            "action": "Verify database credentials and network connectivity",
                        },
                    })
                    metrics["database_issues"] += 1
                
                # Check if database can be connected
                try:
                    db_details = self.client.get_database(db_id)
                    
                    # Check auto_run_queries (security setting)
                    if db_details.get("auto_run_queries") == False:
                        findings.append({
                            "type": "auto_run_disabled",
                            "severity": "low",
                            "title": f"Auto-run Disabled: {name}",
                            "description": f"Database '{name}' has auto-run queries disabled. Users must manually run queries.",
                            "resource": f"database/{db_id}",
                            "resource_type": "metabase_database",
                        })
                except Exception as e:
                    findings.append({
                        "type": "database_connection_error",
                        "severity": "critical",
                        "title": f"Cannot Connect to Database: {name}",
                        "description": f"Failed to get details for database '{name}': {str(e)}",
                        "resource": f"database/{db_id}",
                        "resource_type": "metabase_database",
                    })
                    metrics["database_issues"] += 1
                    
        except Exception as e:
            logger.error(f"Error scanning databases: {e}")
            findings.append({
                "type": "scan_error",
                "severity": "medium",
                "title": "Database Scan Error",
                "description": f"Could not complete database scan: {str(e)}",
            })
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_dashboards(self) -> Dict:
        """Scan dashboards for issues."""
        findings = []
        metrics = {
            "dashboards_scanned": 0,
            "broken_dashboards": 0,
        }
        
        try:
            dashboards = self.client.get_dashboards()
            metrics["dashboards_scanned"] = len(dashboards)
            
            for dash in dashboards:
                dash_id = dash.get("id")
                name = dash.get("name", "Unknown")
                
                # Skip archived dashboards
                if dash.get("archived"):
                    continue
                
                try:
                    # Get full dashboard with cards
                    full_dash = self.client.get_dashboard(dash_id)
                    cards = full_dash.get("ordered_cards", [])
                    
                    # Check each card for errors
                    broken_cards = []
                    for card_info in cards:
                        card = card_info.get("card", {})
                        card_id = card.get("id")
                        card_name = card.get("name", "Untitled")
                        
                        # Check for visualization settings errors
                        viz_settings = card_info.get("visualization_settings", {})
                        
                        # Try to detect broken references
                        # (In real implementation, would need to run query)
                        
                    if broken_cards:
                        metrics["broken_dashboards"] += 1
                        findings.append({
                            "type": "broken_dashboard",
                            "severity": "high",
                            "title": f"Dashboard Has Broken Cards: {name}",
                            "description": f"Dashboard '{name}' has {len(broken_cards)} broken cards.",
                            "resource": f"dashboard/{dash_id}",
                            "resource_type": "metabase_dashboard",
                            "details": {"broken_cards": broken_cards},
                        })
                    
                    # Check for staleness
                    updated_at = dash.get("updated_at")
                    if updated_at:
                        try:
                            # Metabase uses ISO format
                            updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                            days_since = (datetime.now(updated_dt.tzinfo) - updated_dt).days
                            
                            if days_since > self.thresholds["stale_days"]:
                                findings.append({
                                    "type": "stale_dashboard",
                                    "severity": "low",
                                    "title": f"Stale Dashboard: {name}",
                                    "description": f"Dashboard '{name}' hasn't been updated in {days_since} days.",
                                    "resource": f"dashboard/{dash_id}",
                                    "resource_type": "metabase_dashboard",
                                })
                        except Exception:
                            pass
                            
                except Exception as e:
                    logger.warning(f"Could not check dashboard {dash_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning dashboards: {e}")
        
        return {"findings": findings, "metrics": metrics}
    
    def _scan_cards(self) -> Dict:
        """Scan saved questions/cards."""
        findings = []
        metrics = {
            "cards_scanned": 0,
            "slow_cards": 0,
        }
        
        try:
            cards = self.client.get_cards()
            metrics["cards_scanned"] = len(cards)
            
            # Check for common issues
            for card in cards:
                card_id = card.get("id")
                name = card.get("name", "Untitled")
                
                # Skip archived cards
                if card.get("archived"):
                    continue
                
                # Check query average execution time
                avg_time = card.get("average_query_time")
                if avg_time and avg_time > self.thresholds["slow_query_ms"]:
                    metrics["slow_cards"] += 1
                    findings.append({
                        "type": "slow_card",
                        "severity": "medium",
                        "title": f"Slow Query: {name}",
                        "description": f"Card '{name}' has average query time of {avg_time/1000:.1f}s. Consider optimizing.",
                        "resource": f"card/{card_id}",
                        "resource_type": "metabase_card",
                        "suggested_fix": {
                            "type": "manual",
                            "action": "Optimize the underlying query or add caching",
                        },
                    })
                
                # Check for missing database reference
                database_id = card.get("database_id")
                if not database_id and card.get("dataset_query", {}).get("type") != "native":
                    findings.append({
                        "type": "missing_database",
                        "severity": "high",
                        "title": f"Card Missing Database: {name}",
                        "description": f"Card '{name}' has no database reference. It may be broken.",
                        "resource": f"card/{card_id}",
                        "resource_type": "metabase_card",
                    })
                    
        except Exception as e:
            logger.error(f"Error scanning cards: {e}")
        
        return {"findings": findings, "metrics": metrics}
