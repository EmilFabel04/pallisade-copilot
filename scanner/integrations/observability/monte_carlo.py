"""
Monte Carlo Data Observability Integration

Monte Carlo is a data observability platform that monitors data pipelines
for freshness, volume, schema changes, and field-level anomalies.

Uses Monte Carlo's GraphQL API.
API Docs: https://docs.getmontecarlo.com/docs/using-the-api
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
import httpx

from .base import ObservabilityClient
from .models import (
    DataIncident,
    DataQualityCheck,
    DataQualityMetrics,
    AffectedAsset,
    IncidentSeverity,
    IncidentStatus,
    CheckType,
)

logger = logging.getLogger(__name__)


# GraphQL Queries
GET_INCIDENTS_QUERY = """
query getIncidents($first: Int, $statuses: [IncidentFeedbackStatus!], $incidentTypes: [String!]) {
    getIncidents(first: $first, statuses: $statuses, incidentTypes: $incidentTypes) {
        edges {
            node {
                id
                uuid
                incidentType
                incidentSubTypes
                severity
                feedbackStatus
                title
                description
                createdTime
                startTime
                endTime
                affectedTableUrns
                table {
                    id
                    fullTableId
                    friendlyName
                    database
                    schema
                }
                expectedValue
                actualValue
                deviationPercent
                url
            }
        }
    }
}
"""

GET_TABLE_INCIDENTS_QUERY = """
query getTableIncidents($tableId: String!, $first: Int) {
    getIncidents(first: $first, tableIds: [$tableId]) {
        edges {
            node {
                id
                uuid
                incidentType
                severity
                feedbackStatus
                title
                description
                createdTime
                startTime
                expectedValue
                actualValue
                deviationPercent
                url
            }
        }
    }
}
"""

GET_TABLE_MONITORS_QUERY = """
query getTableMonitors($fullTableId: String!) {
    getTable(fullTableId: $fullTableId) {
        id
        monitors {
            id
            name
            monitorType
            scheduleConfig {
                scheduleType
                intervalMinutes
            }
            monitorStatus
            consecutiveAnomalies
            lastRun
        }
    }
}
"""

GET_TABLE_HEALTH_QUERY = """
query getTableHealth($fullTableId: String!) {
    getTable(fullTableId: $fullTableId) {
        id
        fullTableId
        friendlyName
        tableHealth {
            overallStatus
            healthScore
            freshnessStatus
            volumeStatus
            schemaChangeCount
            freshnessHours
            expectedFreshnessHours
            volumeDeviation
            currentRowCount
            expectedRowCount
        }
        activeIncidentCount
        totalMonitorCount
        passingMonitorCount
    }
}
"""

SEARCH_TABLES_QUERY = """
query searchTables($searchString: String!, $first: Int) {
    searchTables(searchString: $searchString, first: $first) {
        edges {
            node {
                id
                fullTableId
            }
        }
    }
}
"""


class MonteCarloClient(ObservabilityClient):
    """
    Monte Carlo observability client.

    Capabilities:
    - Get active incidents (freshness, volume, schema, field quality)
    - Get monitors/checks for tables
    - Get table health scores and metrics
    - Trace upstream incidents through lineage
    """

    TOOL_NAME = "monte_carlo"
    BASE_URL = "https://api.getmontecarlo.com/graphql"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Monte Carlo client.

        Config options:
            api_key_id: Monte Carlo API Key ID
            api_key_secret: Monte Carlo API Key Token

        Get credentials from:
        https://getmontecarlo.com/settings/api
        """
        super().__init__(config)

        self.api_key_id = config.get("api_key_id", "")
        self.api_key_secret = config.get("api_key_secret", "")

        self._client: Optional[httpx.Client] = None

    def connect(self) -> bool:
        """Establish connection to Monte Carlo API."""
        try:
            self._client = httpx.Client(
                timeout=30,
                headers={
                    "x-mcd-id": self.api_key_id,
                    "x-mcd-token": self.api_key_secret,
                    "Content-Type": "application/json",
                },
            )
            self._connected = True
            logger.info("Connected to Monte Carlo API")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Monte Carlo: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Close the connection."""
        if self._client:
            self._client.close()
            self._client = None
        self._connected = False

    def test_connection(self) -> Tuple[bool, str]:
        """Test if the connection is valid."""
        if not self._client:
            self.connect()

        try:
            # Simple query to verify credentials
            query = "query { getUser { email } }"
            response = self._execute_query(query)

            if "errors" in response:
                return False, f"API error: {response['errors'][0].get('message', 'Unknown error')}"

            email = response.get("data", {}).get("getUser", {}).get("email")
            if email:
                return True, f"Connected as {email}"

            return False, "Could not verify connection"

        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def _execute_query(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a GraphQL query."""
        if not self._client:
            raise ConnectionError("Not connected to Monte Carlo")

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self._client.post(self.BASE_URL, json=payload)
        response.raise_for_status()
        return response.json()

    def _parse_incident(self, node: Dict[str, Any]) -> DataIncident:
        """Parse Monte Carlo incident node to DataIncident."""
        # Parse affected assets
        affected_assets = []
        table = node.get("table", {})
        if table:
            affected_assets.append(
                AffectedAsset(
                    id=table.get("id", ""),
                    name=table.get("friendlyName", ""),
                    fqn=table.get("fullTableId", ""),
                    asset_type="table",
                    platform="unknown",  # MC doesn't always provide this
                    database=table.get("database"),
                    schema=table.get("schema"),
                )
            )

        # Parse timestamps
        created_time = node.get("createdTime")
        detected_at = datetime.now(timezone.utc)
        if created_time:
            try:
                detected_at = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        start_time = node.get("startTime")
        started_at = None
        if start_time:
            try:
                started_at = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Parse values
        expected_value = node.get("expectedValue")
        actual_value = node.get("actualValue")
        deviation = node.get("deviationPercent")

        return DataIncident(
            id=node.get("uuid", node.get("id", "")),
            source=self.TOOL_NAME,
            severity=IncidentSeverity.from_monte_carlo(node.get("severity", "SEV-2")),
            status=IncidentStatus.from_monte_carlo(node.get("feedbackStatus", "INVESTIGATING")),
            incident_type=CheckType.from_monte_carlo(node.get("incidentType", "ANOMALY")),
            title=node.get("title", "Untitled incident"),
            description=node.get("description", ""),
            affected_assets=affected_assets,
            detected_at=detected_at,
            started_at=started_at,
            expected_value=str(expected_value) if expected_value else None,
            actual_value=str(actual_value) if actual_value else None,
            deviation_percentage=float(deviation) if deviation else None,
            external_url=node.get("url"),
            external_id=node.get("id"),
            raw_data=node,
        )

    def get_active_incidents(
        self,
        severity_filter: Optional[List[IncidentSeverity]] = None,
        asset_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[DataIncident]:
        """Get active incidents from Monte Carlo."""
        if not self._client:
            self.connect()

        variables = {
            "first": limit,
            "statuses": ["INVESTIGATING", "ACKNOWLEDGED"],
        }

        try:
            response = self._execute_query(GET_INCIDENTS_QUERY, variables)

            if "errors" in response:
                logger.error(f"Monte Carlo API error: {response['errors']}")
                return []

            edges = response.get("data", {}).get("getIncidents", {}).get("edges", [])
            incidents = []

            for edge in edges:
                node = edge.get("node", {})
                incident = self._parse_incident(node)

                # Apply severity filter
                if severity_filter and incident.severity not in severity_filter:
                    continue

                # Apply asset filter (simple pattern match)
                if asset_filter:
                    asset_match = False
                    pattern = asset_filter.replace("%", "").lower()
                    for asset in incident.affected_assets:
                        if pattern in asset.fqn.lower():
                            asset_match = True
                            break
                    if not asset_match:
                        continue

                incidents.append(incident)

            logger.info(f"Fetched {len(incidents)} active incidents from Monte Carlo")
            return incidents

        except Exception as e:
            logger.error(f"Error fetching incidents from Monte Carlo: {e}")
            return []

    def get_incidents_for_asset(
        self,
        asset_fqn: str,
        hours_back: int = 168,
        include_resolved: bool = False,
    ) -> List[DataIncident]:
        """Get incidents for a specific asset."""
        if not self._client:
            self.connect()

        try:
            # First, find the table ID
            search_response = self._execute_query(
                SEARCH_TABLES_QUERY,
                {"searchString": asset_fqn, "first": 1},
            )

            tables = search_response.get("data", {}).get("searchTables", {}).get("edges", [])
            if not tables:
                logger.warning(f"Table not found in Monte Carlo: {asset_fqn}")
                return []

            table_id = tables[0].get("node", {}).get("id")
            if not table_id:
                return []

            # Now get incidents for this table
            response = self._execute_query(
                GET_TABLE_INCIDENTS_QUERY,
                {"tableId": table_id, "first": 50},
            )

            edges = response.get("data", {}).get("getIncidents", {}).get("edges", [])
            incidents = []

            for edge in edges:
                node = edge.get("node", {})
                incident = self._parse_incident(node)

                # Filter by time
                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
                if incident.detected_at.replace(tzinfo=timezone.utc) < cutoff:
                    continue

                # Filter resolved if requested
                if not include_resolved and not incident.is_active:
                    continue

                incidents.append(incident)

            return incidents

        except Exception as e:
            logger.error(f"Error fetching incidents for {asset_fqn}: {e}")
            return []

    def get_incident_details(self, incident_id: str) -> Optional[DataIncident]:
        """Get detailed information about a specific incident."""
        # Monte Carlo doesn't have a single-incident query, so we search in active incidents
        incidents = self.get_active_incidents(limit=200)
        for incident in incidents:
            if incident.id == incident_id or incident.external_id == incident_id:
                return incident
        return None

    def get_checks_for_asset(self, asset_fqn: str) -> List[DataQualityCheck]:
        """Get monitors configured for an asset."""
        if not self._client:
            self.connect()

        try:
            response = self._execute_query(
                GET_TABLE_MONITORS_QUERY,
                {"fullTableId": asset_fqn},
            )

            table_data = response.get("data", {}).get("getTable", {})
            if not table_data:
                return []

            monitors = table_data.get("monitors", [])
            checks = []

            for monitor in monitors:
                check_type = CheckType.from_monte_carlo(monitor.get("monitorType", "CUSTOM"))

                # Parse schedule
                schedule_config = monitor.get("scheduleConfig", {})
                schedule = None
                if schedule_config:
                    schedule_type = schedule_config.get("scheduleType", "")
                    interval = schedule_config.get("intervalMinutes", 0)
                    if schedule_type == "FIXED":
                        schedule = f"Every {interval} minutes"
                    elif schedule_type == "DYNAMIC":
                        schedule = "Dynamic (based on data updates)"

                # Parse last run
                last_run_str = monitor.get("lastRun")
                last_run = None
                if last_run_str:
                    try:
                        last_run = datetime.fromisoformat(last_run_str.replace("Z", "+00:00"))
                    except (ValueError, AttributeError):
                        pass

                checks.append(
                    DataQualityCheck(
                        id=monitor.get("id", ""),
                        source=self.TOOL_NAME,
                        name=monitor.get("name", "Unnamed Monitor"),
                        check_type=check_type,
                        target_asset=AffectedAsset(
                            id=table_data.get("id", ""),
                            name=asset_fqn.split(".")[-1],
                            fqn=asset_fqn,
                            asset_type="table",
                            platform="unknown",
                        ),
                        schedule=schedule,
                        is_passing=monitor.get("monitorStatus", "HEALTHY") == "HEALTHY",
                        consecutive_failures=monitor.get("consecutiveAnomalies", 0),
                        last_run_at=last_run,
                    )
                )

            return checks

        except Exception as e:
            logger.error(f"Error fetching monitors for {asset_fqn}: {e}")
            return []

    def get_failing_checks(self, limit: int = 50) -> List[DataQualityCheck]:
        """Get currently failing monitors."""
        # Monte Carlo doesn't have a direct API for this
        # We'd need to iterate through tables which is expensive
        logger.debug("get_failing_checks not efficiently supported by Monte Carlo API")
        return []

    def get_asset_quality_metrics(self, asset_fqn: str) -> Optional[DataQualityMetrics]:
        """Get quality metrics for an asset."""
        if not self._client:
            self.connect()

        try:
            response = self._execute_query(
                GET_TABLE_HEALTH_QUERY,
                {"fullTableId": asset_fqn},
            )

            table_data = response.get("data", {}).get("getTable", {})
            if not table_data:
                return None

            health = table_data.get("tableHealth", {})
            if not health:
                return None

            # Map health status
            overall_status = health.get("overallStatus", "UNKNOWN")
            status_map = {
                "HEALTHY": "healthy",
                "WARNING": "warning",
                "CRITICAL": "critical",
                "UNKNOWN": "unknown",
            }

            # Map freshness status
            freshness_status = health.get("freshnessStatus", "UNKNOWN")
            freshness_map = {
                "FRESH": "fresh",
                "STALE": "stale",
                "UNKNOWN": "unknown",
            }

            # Map volume status
            volume_status = health.get("volumeStatus", "NORMAL")
            volume_map = {
                "NORMAL": "normal",
                "HIGH": "high",
                "LOW": "low",
                "UNKNOWN": "unknown",
            }

            return DataQualityMetrics(
                asset_fqn=asset_fqn,
                asset_name=table_data.get("friendlyName", asset_fqn.split(".")[-1]),
                active_incidents=table_data.get("activeIncidentCount", 0),
                total_checks=table_data.get("totalMonitorCount", 0),
                passing_checks=table_data.get("passingMonitorCount", 0),
                health_score=health.get("healthScore"),
                health_status=status_map.get(overall_status, "unknown"),
                freshness_status=freshness_map.get(freshness_status, "unknown"),
                hours_since_update=health.get("freshnessHours"),
                expected_freshness_hours=health.get("expectedFreshnessHours"),
                volume_status=volume_map.get(volume_status, "unknown"),
                volume_deviation_pct=health.get("volumeDeviation"),
                current_row_count=health.get("currentRowCount"),
                expected_row_count=health.get("expectedRowCount"),
                schema_changes_7d=health.get("schemaChangeCount", 0),
                last_checked_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error(f"Error fetching metrics for {asset_fqn}: {e}")
            return None

    def get_upstream_incidents(
        self,
        asset_fqn: str,
        depth: int = 3,
    ) -> List[DataIncident]:
        """
        Get incidents from upstream assets using Monte Carlo lineage.

        Monte Carlo has native lineage support, so we can trace upstream.
        """
        # Note: This requires Monte Carlo's lineage API which we'd implement
        # in a production version. For now, return empty list.
        logger.debug("Upstream incident lookup via MC lineage not yet implemented")
        return []
