"""
Soda Data Observability Integration

Soda is a data quality platform that runs checks defined in YAML
and reports results to Soda Cloud.

Uses Soda Cloud REST API.
API Docs: https://docs.soda.io/soda-cloud/api-docs
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


class SodaClient(ObservabilityClient):
    """
    Soda Cloud observability client.

    Capabilities:
    - Get check results (passing/failing)
    - Get incidents from failed checks
    - Get dataset health metrics
    """

    TOOL_NAME = "soda"
    BASE_URL = "https://cloud.soda.io/api/v1"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Soda client.

        Config options:
            api_key: Soda Cloud API key
            api_secret: Soda Cloud API secret (for auth)
            organization_id: Soda organization ID (optional)

        Get credentials from:
        https://cloud.soda.io/profile
        """
        super().__init__(config)

        self.api_key = config.get("api_key", "")
        self.api_secret = config.get("api_secret", "")
        self.organization_id = config.get("organization_id")

        self._client: Optional[httpx.Client] = None
        self._access_token: Optional[str] = None

    def connect(self) -> bool:
        """Establish connection to Soda Cloud API."""
        try:
            self._client = httpx.Client(
                base_url=self.BASE_URL,
                timeout=30,
                headers={"Content-Type": "application/json"},
            )

            # Authenticate and get access token
            auth_response = self._client.post(
                "/auth/token",
                json={
                    "apiKey": self.api_key,
                    "apiSecret": self.api_secret,
                }
            )

            if auth_response.status_code == 200:
                self._access_token = auth_response.json().get("token")
                self._client.headers["Authorization"] = f"Bearer {self._access_token}"
                self._connected = True
                logger.info("Connected to Soda Cloud API")
                return True
            else:
                logger.error(f"Soda auth failed: {auth_response.status_code}")
                self._connected = False
                return False

        except Exception as e:
            logger.error(f"Failed to connect to Soda: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Close the connection."""
        if self._client:
            self._client.close()
            self._client = None
        self._access_token = None
        self._connected = False

    def test_connection(self) -> Tuple[bool, str]:
        """Test if the connection is valid."""
        if not self._client or not self._access_token:
            connected = self.connect()
            if not connected:
                return False, "Authentication failed"

        try:
            response = self._client.get("/organizations/me")
            if response.status_code == 200:
                org = response.json()
                name = org.get("name", "Unknown")
                return True, f"Connected to organization: {name}"
            else:
                return False, f"API error: {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def _parse_check_result_to_incident(self, check: Dict[str, Any]) -> DataIncident:
        """Parse a Soda check result to DataIncident."""
        # Determine severity
        check_level = check.get("level", "warn")
        severity = IncidentSeverity.from_soda(check_level)

        # Status based on outcome
        outcome = check.get("outcome", "").lower()
        status = IncidentStatus.ACTIVE if outcome == "fail" else IncidentStatus.RESOLVED

        # Determine check type from check name/type
        check_name = check.get("name", "").lower()
        check_type_str = check.get("type", "").lower()

        if "fresh" in check_name or "fresh" in check_type_str:
            check_type = CheckType.FRESHNESS
        elif "row_count" in check_name or "volume" in check_type_str:
            check_type = CheckType.VOLUME
        elif "null" in check_name or "missing" in check_name:
            check_type = CheckType.NULLS
        elif "unique" in check_name or "duplicate" in check_name:
            check_type = CheckType.UNIQUENESS
        elif "schema" in check_name:
            check_type = CheckType.SCHEMA
        elif "anomaly" in check_name:
            check_type = CheckType.ANOMALY
        else:
            check_type = CheckType.CUSTOM_SQL

        # Build affected asset
        dataset = check.get("dataset", {})
        dataset_name = dataset.get("name", "unknown")
        schema_name = dataset.get("schema", "")
        fqn = f"{schema_name}.{dataset_name}" if schema_name else dataset_name

        affected_assets = [
            AffectedAsset(
                id=dataset.get("id", ""),
                name=dataset_name,
                fqn=fqn,
                asset_type="table",
                platform=dataset.get("datasource", "unknown"),
                schema=schema_name,
                column_name=check.get("column"),
            )
        ]

        # Parse timestamp
        detected_at = datetime.now(timezone.utc)
        if check.get("evaluatedAt"):
            try:
                detected_at = datetime.fromisoformat(check["evaluatedAt"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Build description
        description = check.get("definition", "")
        if check.get("diagnostics"):
            description += f"\nDiagnostics: {check['diagnostics']}"

        return DataIncident(
            id=check.get("id", ""),
            source=self.TOOL_NAME,
            severity=severity,
            status=status,
            incident_type=check_type,
            title=check.get("name", "Check Failed"),
            description=description,
            affected_assets=affected_assets,
            detected_at=detected_at,
            expected_value=check.get("expectedValue"),
            actual_value=check.get("value"),
            threshold=check.get("threshold"),
            raw_data=check,
        )

    def get_active_incidents(
        self,
        severity_filter: Optional[List[IncidentSeverity]] = None,
        asset_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[DataIncident]:
        """Get failing checks from Soda Cloud."""
        if not self._client or not self._access_token:
            self.connect()

        try:
            # Get recent failed checks
            response = self._client.get(
                "/checks",
                params={
                    "outcome": "fail",
                    "limit": limit,
                    "orderBy": "-evaluatedAt",
                }
            )
            response.raise_for_status()
            data = response.json()

            incidents = []
            for check in data.get("checks", []):
                incident = self._parse_check_result_to_incident(check)

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

            logger.info(f"Fetched {len(incidents)} failing checks from Soda")
            return incidents

        except Exception as e:
            logger.error(f"Error fetching checks from Soda: {e}")
            return []

    def get_incidents_for_asset(
        self,
        asset_fqn: str,
        hours_back: int = 168,
        include_resolved: bool = False,
    ) -> List[DataIncident]:
        """Get check results for a specific dataset."""
        if not self._client or not self._access_token:
            self.connect()

        try:
            # Parse asset name
            parts = asset_fqn.split(".")
            dataset_name = parts[-1] if parts else asset_fqn

            params = {
                "dataset": dataset_name,
                "limit": 50,
                "orderBy": "-evaluatedAt",
            }

            if not include_resolved:
                params["outcome"] = "fail"

            response = self._client.get("/checks", params=params)
            response.raise_for_status()
            data = response.json()

            incidents = []
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

            for check in data.get("checks", []):
                incident = self._parse_check_result_to_incident(check)

                if incident.detected_at.replace(tzinfo=timezone.utc) < cutoff:
                    continue

                incidents.append(incident)

            return incidents

        except Exception as e:
            logger.error(f"Error fetching checks for {asset_fqn}: {e}")
            return []

    def get_incident_details(self, incident_id: str) -> Optional[DataIncident]:
        """Get details for a specific check result."""
        if not self._client or not self._access_token:
            self.connect()

        try:
            response = self._client.get(f"/checks/{incident_id}")
            response.raise_for_status()
            check = response.json()
            return self._parse_check_result_to_incident(check)
        except Exception as e:
            logger.error(f"Error fetching check {incident_id}: {e}")
            return None

    def get_checks_for_asset(self, asset_fqn: str) -> List[DataQualityCheck]:
        """Get checks configured for a dataset."""
        if not self._client or not self._access_token:
            self.connect()

        try:
            parts = asset_fqn.split(".")
            dataset_name = parts[-1] if parts else asset_fqn

            # Get check definitions for this dataset
            response = self._client.get(
                "/check-definitions",
                params={"dataset": dataset_name, "limit": 50}
            )
            response.raise_for_status()
            data = response.json()

            checks = []
            for check_def in data.get("checkDefinitions", []):
                check_name = check_def.get("name", "").lower()

                # Determine check type
                if "fresh" in check_name:
                    check_type = CheckType.FRESHNESS
                elif "row_count" in check_name or "volume" in check_name:
                    check_type = CheckType.VOLUME
                elif "null" in check_name or "missing" in check_name:
                    check_type = CheckType.NULLS
                elif "unique" in check_name:
                    check_type = CheckType.UNIQUENESS
                else:
                    check_type = CheckType.CUSTOM_SQL

                # Get latest result
                latest_result = check_def.get("latestResult", {})
                is_passing = latest_result.get("outcome", "pass") == "pass"

                checks.append(
                    DataQualityCheck(
                        id=check_def.get("id", ""),
                        source=self.TOOL_NAME,
                        name=check_def.get("name", ""),
                        check_type=check_type,
                        target_asset=AffectedAsset(
                            id=check_def.get("datasetId", ""),
                            name=dataset_name,
                            fqn=asset_fqn,
                            asset_type="table",
                            platform="unknown",
                            column_name=check_def.get("column"),
                        ),
                        threshold=check_def.get("threshold"),
                        sql_expression=check_def.get("definition"),
                        is_passing=is_passing,
                        description=check_def.get("description"),
                    )
                )

            return checks

        except Exception as e:
            logger.error(f"Error fetching checks for {asset_fqn}: {e}")
            return []

    def get_failing_checks(self, limit: int = 50) -> List[DataQualityCheck]:
        """Get currently failing checks."""
        if not self._client or not self._access_token:
            self.connect()

        try:
            response = self._client.get(
                "/checks",
                params={"outcome": "fail", "limit": limit}
            )
            response.raise_for_status()
            data = response.json()

            checks = []
            for check in data.get("checks", []):
                check_name = check.get("name", "").lower()

                if "fresh" in check_name:
                    check_type = CheckType.FRESHNESS
                elif "row_count" in check_name:
                    check_type = CheckType.VOLUME
                else:
                    check_type = CheckType.CUSTOM_SQL

                dataset = check.get("dataset", {})
                fqn = f"{dataset.get('schema', '')}.{dataset.get('name', '')}"

                checks.append(
                    DataQualityCheck(
                        id=check.get("id", ""),
                        source=self.TOOL_NAME,
                        name=check.get("name", ""),
                        check_type=check_type,
                        target_asset=AffectedAsset(
                            id=dataset.get("id", ""),
                            name=dataset.get("name", ""),
                            fqn=fqn,
                            asset_type="table",
                            platform=dataset.get("datasource", "unknown"),
                        ),
                        is_passing=False,
                    )
                )

            return checks

        except Exception as e:
            logger.error(f"Error fetching failing checks: {e}")
            return []

    def get_asset_quality_metrics(self, asset_fqn: str) -> Optional[DataQualityMetrics]:
        """Get quality metrics for a dataset."""
        if not self._client or not self._access_token:
            self.connect()

        try:
            parts = asset_fqn.split(".")
            dataset_name = parts[-1] if parts else asset_fqn

            # Get dataset health summary
            response = self._client.get(
                "/datasets",
                params={"name": dataset_name, "limit": 1}
            )
            response.raise_for_status()
            datasets = response.json().get("datasets", [])

            if not datasets:
                return None

            dataset = datasets[0]
            dataset_id = dataset.get("id")

            # Get check stats
            checks_response = self._client.get(
                "/checks",
                params={"datasetId": dataset_id, "limit": 100}
            )
            checks_response.raise_for_status()
            checks = checks_response.json().get("checks", [])

            # Calculate metrics
            total = len(checks)
            passing = sum(1 for c in checks if c.get("outcome") == "pass")
            failing = total - passing

            health_score = None
            if total > 0:
                health_score = (passing / total) * 100

            health_status = "healthy"
            if health_score is not None:
                if health_score < 50:
                    health_status = "critical"
                elif health_score < 80:
                    health_status = "warning"

            return DataQualityMetrics(
                asset_fqn=asset_fqn,
                asset_name=dataset_name,
                active_incidents=failing,
                total_checks=total,
                passing_checks=passing,
                health_score=health_score,
                health_status=health_status,
                freshness_status="unknown",
                volume_status="unknown",
                last_checked_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error(f"Error fetching metrics for {asset_fqn}: {e}")
            return None
