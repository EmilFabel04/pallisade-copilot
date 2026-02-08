"""
Bigeye Data Observability Integration

Bigeye is a data observability platform that monitors data pipelines
for data quality issues using automated ML-based anomaly detection.

Uses Bigeye's REST API.
API Docs: https://docs.bigeye.com/docs/api-overview
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


class BigeyeClient(ObservabilityClient):
    """
    Bigeye observability client.

    Capabilities:
    - Get active issues/incidents
    - Get metrics for tables
    - Get metric configurations (checks)
    """

    TOOL_NAME = "bigeye"
    BASE_URL = "https://api.bigeye.com/api/v1"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Bigeye client.

        Config options:
            api_token: Bigeye API token
            workspace_id: Bigeye workspace ID (optional)

        Get credentials from:
        https://app.bigeye.com/settings/api
        """
        super().__init__(config)

        self.api_token = config.get("api_token", "")
        self.workspace_id = config.get("workspace_id")

        self._client: Optional[httpx.Client] = None

    def connect(self) -> bool:
        """Establish connection to Bigeye API."""
        try:
            self._client = httpx.Client(
                base_url=self.BASE_URL,
                timeout=30,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
            )
            self._connected = True
            logger.info("Connected to Bigeye API")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Bigeye: {e}")
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
            response = self._client.get("/user")
            if response.status_code == 200:
                user = response.json()
                email = user.get("email", "Unknown")
                return True, f"Connected as {email}"
            else:
                return False, f"API error: {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def _parse_incident(self, issue: Dict[str, Any]) -> DataIncident:
        """Parse Bigeye issue to DataIncident."""
        # Parse affected asset
        table_info = issue.get("table", {})
        affected_assets = []
        if table_info:
            affected_assets.append(
                AffectedAsset(
                    id=str(table_info.get("id", "")),
                    name=table_info.get("name", ""),
                    fqn=f"{table_info.get('schema', '')}.{table_info.get('name', '')}",
                    asset_type="table",
                    platform=table_info.get("warehouse", "unknown"),
                    database=table_info.get("database"),
                    schema=table_info.get("schema"),
                    column_name=issue.get("column_name"),
                )
            )

        # Parse severity
        priority = issue.get("priority", "medium")
        severity = IncidentSeverity.from_bigeye(priority)

        # Parse status
        status_str = issue.get("status", "OPEN")
        status = IncidentStatus.ACTIVE if status_str == "OPEN" else IncidentStatus.RESOLVED

        # Parse check type
        metric_type = issue.get("metric_type", "")
        check_type = CheckType.from_bigeye(metric_type)

        # Parse timestamps
        detected_at = datetime.now(timezone.utc)
        if issue.get("created_at"):
            try:
                detected_at = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return DataIncident(
            id=str(issue.get("id", "")),
            source=self.TOOL_NAME,
            severity=severity,
            status=status,
            incident_type=check_type,
            title=issue.get("title", issue.get("description", "Untitled")),
            description=issue.get("description", ""),
            affected_assets=affected_assets,
            detected_at=detected_at,
            expected_value=str(issue.get("expected_value")) if issue.get("expected_value") else None,
            actual_value=str(issue.get("actual_value")) if issue.get("actual_value") else None,
            deviation_percentage=issue.get("deviation_percentage"),
            external_url=issue.get("url"),
            external_id=str(issue.get("id", "")),
            raw_data=issue,
        )

    def get_active_incidents(
        self,
        severity_filter: Optional[List[IncidentSeverity]] = None,
        asset_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[DataIncident]:
        """Get active issues from Bigeye."""
        if not self._client:
            self.connect()

        try:
            params = {
                "status": "OPEN",
                "limit": limit,
            }

            if self.workspace_id:
                params["workspace_id"] = self.workspace_id

            response = self._client.get("/issues", params=params)
            response.raise_for_status()
            data = response.json()

            incidents = []
            for issue in data.get("issues", []):
                incident = self._parse_incident(issue)

                # Apply severity filter
                if severity_filter and incident.severity not in severity_filter:
                    continue

                # Apply asset filter
                if asset_filter:
                    pattern = asset_filter.replace("%", "").lower()
                    asset_match = any(
                        pattern in asset.fqn.lower()
                        for asset in incident.affected_assets
                    )
                    if not asset_match:
                        continue

                incidents.append(incident)

            logger.info(f"Fetched {len(incidents)} active issues from Bigeye")
            return incidents

        except Exception as e:
            logger.error(f"Error fetching issues from Bigeye: {e}")
            return []

    def get_incidents_for_asset(
        self,
        asset_fqn: str,
        hours_back: int = 168,
        include_resolved: bool = False,
    ) -> List[DataIncident]:
        """Get issues for a specific asset."""
        if not self._client:
            self.connect()

        try:
            # Parse asset FQN to get table name
            parts = asset_fqn.split(".")
            table_name = parts[-1] if parts else asset_fqn

            params = {
                "table_name": table_name,
                "limit": 50,
            }

            if not include_resolved:
                params["status"] = "OPEN"

            response = self._client.get("/issues", params=params)
            response.raise_for_status()
            data = response.json()

            incidents = []
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

            for issue in data.get("issues", []):
                incident = self._parse_incident(issue)

                if incident.detected_at.replace(tzinfo=timezone.utc) < cutoff:
                    continue

                incidents.append(incident)

            return incidents

        except Exception as e:
            logger.error(f"Error fetching issues for {asset_fqn}: {e}")
            return []

    def get_incident_details(self, incident_id: str) -> Optional[DataIncident]:
        """Get detailed information about a specific issue."""
        if not self._client:
            self.connect()

        try:
            response = self._client.get(f"/issues/{incident_id}")
            response.raise_for_status()
            issue = response.json()
            return self._parse_incident(issue)
        except Exception as e:
            logger.error(f"Error fetching issue {incident_id}: {e}")
            return None

    def get_checks_for_asset(self, asset_fqn: str) -> List[DataQualityCheck]:
        """Get metrics configured for an asset."""
        if not self._client:
            self.connect()

        try:
            # Parse asset FQN
            parts = asset_fqn.split(".")
            table_name = parts[-1] if parts else asset_fqn

            response = self._client.get(
                "/metrics",
                params={"table_name": table_name, "limit": 50}
            )
            response.raise_for_status()
            data = response.json()

            checks = []
            for metric in data.get("metrics", []):
                check_type = CheckType.from_bigeye(metric.get("type", ""))

                checks.append(
                    DataQualityCheck(
                        id=str(metric.get("id", "")),
                        source=self.TOOL_NAME,
                        name=metric.get("name", "Unnamed Metric"),
                        check_type=check_type,
                        target_asset=AffectedAsset(
                            id=str(metric.get("table_id", "")),
                            name=table_name,
                            fqn=asset_fqn,
                            asset_type="table",
                            platform="unknown",
                        ),
                        threshold=metric.get("threshold"),
                        is_passing=metric.get("status", "PASSING") == "PASSING",
                        consecutive_failures=metric.get("consecutive_failures", 0),
                        last_run_at=None,
                        external_url=metric.get("url"),
                    )
                )

            return checks

        except Exception as e:
            logger.error(f"Error fetching metrics for {asset_fqn}: {e}")
            return []

    def get_failing_checks(self, limit: int = 50) -> List[DataQualityCheck]:
        """Get currently failing metrics."""
        if not self._client:
            self.connect()

        try:
            response = self._client.get(
                "/metrics",
                params={"status": "FAILING", "limit": limit}
            )
            response.raise_for_status()
            data = response.json()

            checks = []
            for metric in data.get("metrics", []):
                check_type = CheckType.from_bigeye(metric.get("type", ""))
                table_info = metric.get("table", {})

                checks.append(
                    DataQualityCheck(
                        id=str(metric.get("id", "")),
                        source=self.TOOL_NAME,
                        name=metric.get("name", "Unnamed Metric"),
                        check_type=check_type,
                        target_asset=AffectedAsset(
                            id=str(table_info.get("id", "")),
                            name=table_info.get("name", ""),
                            fqn=f"{table_info.get('schema', '')}.{table_info.get('name', '')}",
                            asset_type="table",
                            platform=table_info.get("warehouse", "unknown"),
                        ),
                        threshold=metric.get("threshold"),
                        is_passing=False,
                        consecutive_failures=metric.get("consecutive_failures", 1),
                    )
                )

            return checks

        except Exception as e:
            logger.error(f"Error fetching failing metrics: {e}")
            return []

    def get_asset_quality_metrics(self, asset_fqn: str) -> Optional[DataQualityMetrics]:
        """Get quality metrics for an asset."""
        if not self._client:
            self.connect()

        try:
            # Parse asset FQN
            parts = asset_fqn.split(".")
            table_name = parts[-1] if parts else asset_fqn

            # Get table info
            response = self._client.get(
                "/tables",
                params={"name": table_name, "limit": 1}
            )
            response.raise_for_status()
            tables = response.json().get("tables", [])

            if not tables:
                return None

            table = tables[0]
            table_id = table.get("id")

            # Get metrics for this table
            metrics_response = self._client.get(
                "/metrics",
                params={"table_id": table_id, "limit": 100}
            )
            metrics_response.raise_for_status()
            metrics = metrics_response.json().get("metrics", [])

            # Get issues for this table
            issues_response = self._client.get(
                "/issues",
                params={"table_id": table_id, "status": "OPEN", "limit": 100}
            )
            issues_response.raise_for_status()
            issues = issues_response.json().get("issues", [])

            # Calculate stats
            total_checks = len(metrics)
            passing_checks = sum(1 for m in metrics if m.get("status") == "PASSING")
            active_incidents = len(issues)

            # Calculate health score
            health_score = None
            if total_checks > 0:
                health_score = (passing_checks / total_checks) * 100

            health_status = "healthy"
            if health_score is not None:
                if health_score < 50:
                    health_status = "critical"
                elif health_score < 80:
                    health_status = "warning"

            return DataQualityMetrics(
                asset_fqn=asset_fqn,
                asset_name=table_name,
                active_incidents=active_incidents,
                total_checks=total_checks,
                passing_checks=passing_checks,
                health_score=health_score,
                health_status=health_status,
                freshness_status="unknown",
                volume_status="unknown",
                last_checked_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error(f"Error fetching metrics for {asset_fqn}: {e}")
            return None
