"""
Elementary Data Observability Integration

Elementary is a dbt-native data observability tool that stores test results
and anomaly detection data directly in your data warehouse.

Unlike other observability tools, Elementary doesn't have an external API.
We query the Elementary tables directly using the existing warehouse adapter.

Elementary tables:
- elementary.elementary_test_results: Test results from dbt tests
- elementary.data_monitoring_metrics: Time-series metrics
- elementary.anomaly_detection_results: ML-based anomaly detection
- elementary.schema_changes: Schema change tracking
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

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


class ElementaryClient(ObservabilityClient):
    """
    Elementary observability client.

    Queries Elementary tables directly in the warehouse to get:
    - Test results (dbt tests + Elementary tests)
    - Anomaly detection alerts
    - Schema changes
    - Data freshness/volume metrics
    """

    TOOL_NAME = "elementary"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Elementary client.

        Config options:
            schema: Schema where Elementary tables are stored (default: "elementary")
            warehouse_adapter: The warehouse adapter to use for queries

        Elementary uses your existing warehouse connection, so you need to
        pass the warehouse adapter that can execute SQL queries.
        """
        super().__init__(config)

        self.schema = config.get("schema", "elementary")
        self._warehouse_adapter = config.get("warehouse_adapter")
        self._warehouse_type = config.get("warehouse_type", "unknown").upper()

    def connect(self) -> bool:
        """Verify Elementary tables exist in the warehouse."""
        if not self._warehouse_adapter:
            logger.warning("No warehouse adapter provided for Elementary")
            self._connected = False
            return False

        try:
            # Test that we can query the Elementary schema
            if not self._warehouse_adapter.is_connected:
                self._warehouse_adapter.connect()

            # Simple test query
            test_query = self._build_test_query()
            self._warehouse_adapter.execute_query(test_query)

            self._connected = True
            logger.info(f"Connected to Elementary in {self.schema} schema")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Elementary: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """No-op since we use the warehouse adapter."""
        self._connected = False

    def test_connection(self) -> Tuple[bool, str]:
        """Test if Elementary tables are accessible."""
        if not self._warehouse_adapter:
            return False, "No warehouse adapter configured"

        try:
            test_query = self._build_test_query()
            result = self._warehouse_adapter.execute_query(test_query)

            if result is not None:
                return True, f"Elementary tables found in {self.schema} schema"

            return False, "Elementary tables not found"

        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def _build_test_query(self) -> str:
        """Build a test query to verify Elementary tables exist."""
        if self._warehouse_type == "BIGQUERY":
            return f"SELECT 1 FROM `{self.schema}.elementary_test_results` LIMIT 1"
        else:
            return f"SELECT 1 FROM {self.schema}.elementary_test_results LIMIT 1"

    def _quote_schema(self, table: str) -> str:
        """Quote schema.table appropriately for the warehouse."""
        if self._warehouse_type == "BIGQUERY":
            return f"`{self.schema}.{table}`"
        elif self._warehouse_type == "SNOWFLAKE":
            return f"{self.schema.upper()}.{table.upper()}"
        else:
            return f"{self.schema}.{table}"

    def _parse_test_result_to_incident(self, row: Dict[str, Any]) -> DataIncident:
        """Parse an Elementary test result row to DataIncident."""
        # Determine severity based on test status and type
        status = row.get("status", "fail").lower()
        test_type = row.get("test_type", "").lower()

        if status == "fail":
            if test_type in ("anomaly_detection", "schema_change"):
                severity = IncidentSeverity.HIGH
            else:
                severity = IncidentSeverity.MEDIUM
        elif status == "warn":
            severity = IncidentSeverity.LOW
        else:
            severity = IncidentSeverity.INFO

        # Determine incident status
        incident_status = IncidentStatus.ACTIVE if status == "fail" else IncidentStatus.RESOLVED

        # Determine check type
        if "freshness" in test_type:
            check_type = CheckType.FRESHNESS
        elif "volume" in test_type or "row_count" in test_type:
            check_type = CheckType.VOLUME
        elif "schema" in test_type:
            check_type = CheckType.SCHEMA
        elif "null" in test_type:
            check_type = CheckType.NULLS
        elif "unique" in test_type:
            check_type = CheckType.UNIQUENESS
        elif "anomaly" in test_type:
            check_type = CheckType.ANOMALY
        else:
            check_type = CheckType.CUSTOM_SQL

        # Build affected asset
        model_name = row.get("model_name") or row.get("table_name") or "unknown"
        schema_name = row.get("schema_name", "")
        fqn = f"{schema_name}.{model_name}" if schema_name else model_name

        affected_assets = [
            AffectedAsset(
                id=row.get("model_id", model_name),
                name=model_name,
                fqn=fqn,
                asset_type="model",
                platform=self._warehouse_type.lower(),
                schema=schema_name,
                column_name=row.get("column_name"),
            )
        ]

        # Parse timestamp
        detected_at = datetime.now(timezone.utc)
        if row.get("detected_at") or row.get("created_at"):
            ts = row.get("detected_at") or row.get("created_at")
            if isinstance(ts, datetime):
                detected_at = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
            elif isinstance(ts, str):
                try:
                    detected_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    pass

        return DataIncident(
            id=row.get("test_unique_id", row.get("id", "")),
            source=self.TOOL_NAME,
            severity=severity,
            status=incident_status,
            incident_type=check_type,
            title=row.get("test_name", "Test Failure"),
            description=row.get("error_message", row.get("test_results_description", "")),
            affected_assets=affected_assets,
            detected_at=detected_at,
            expected_value=row.get("expected_value"),
            actual_value=row.get("actual_value"),
            deviation_percentage=row.get("deviation_from_average"),
            raw_data=row,
        )

    def get_active_incidents(
        self,
        severity_filter: Optional[List[IncidentSeverity]] = None,
        asset_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[DataIncident]:
        """Get failing tests and anomalies from Elementary."""
        if not self._warehouse_adapter:
            return []

        try:
            # Query recent failed tests
            query = f"""
                SELECT
                    test_unique_id,
                    test_name,
                    test_type,
                    status,
                    model_name,
                    schema_name,
                    column_name,
                    error_message,
                    test_results_description,
                    detected_at,
                    severity
                FROM {self._quote_schema('elementary_test_results')}
                WHERE status = 'fail'
                AND detected_at >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY detected_at DESC
                LIMIT {limit}
            """

            # Adjust for BigQuery syntax
            if self._warehouse_type == "BIGQUERY":
                query = query.replace("CURRENT_DATE - INTERVAL '7 days'",
                                      "DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)")

            results = self._warehouse_adapter.execute_query(query)

            incidents = []
            for row in results:
                incident = self._parse_test_result_to_incident(row)

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

            logger.info(f"Fetched {len(incidents)} failing tests from Elementary")
            return incidents

        except Exception as e:
            logger.error(f"Error fetching test results from Elementary: {e}")
            return []

    def get_incidents_for_asset(
        self,
        asset_fqn: str,
        hours_back: int = 168,
        include_resolved: bool = False,
    ) -> List[DataIncident]:
        """Get test results for a specific model/table."""
        if not self._warehouse_adapter:
            return []

        try:
            # Parse asset name
            parts = asset_fqn.split(".")
            model_name = parts[-1] if parts else asset_fqn

            status_filter = "" if include_resolved else "AND status = 'fail'"

            query = f"""
                SELECT
                    test_unique_id,
                    test_name,
                    test_type,
                    status,
                    model_name,
                    schema_name,
                    column_name,
                    error_message,
                    test_results_description,
                    detected_at
                FROM {self._quote_schema('elementary_test_results')}
                WHERE LOWER(model_name) = LOWER('{model_name}')
                {status_filter}
                ORDER BY detected_at DESC
                LIMIT 50
            """

            results = self._warehouse_adapter.execute_query(query)

            incidents = []
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

            for row in results:
                incident = self._parse_test_result_to_incident(row)

                if incident.detected_at.replace(tzinfo=timezone.utc) < cutoff:
                    continue

                incidents.append(incident)

            return incidents

        except Exception as e:
            logger.error(f"Error fetching tests for {asset_fqn}: {e}")
            return []

    def get_incident_details(self, incident_id: str) -> Optional[DataIncident]:
        """Get details for a specific test result."""
        if not self._warehouse_adapter:
            return None

        try:
            query = f"""
                SELECT *
                FROM {self._quote_schema('elementary_test_results')}
                WHERE test_unique_id = '{incident_id}'
                LIMIT 1
            """

            results = self._warehouse_adapter.execute_query(query)

            if results:
                return self._parse_test_result_to_incident(results[0])

            return None

        except Exception as e:
            logger.error(f"Error fetching test {incident_id}: {e}")
            return None

    def get_checks_for_asset(self, asset_fqn: str) -> List[DataQualityCheck]:
        """Get configured tests for a model."""
        if not self._warehouse_adapter:
            return []

        try:
            parts = asset_fqn.split(".")
            model_name = parts[-1] if parts else asset_fqn

            # Get distinct tests for this model
            query = f"""
                SELECT
                    test_unique_id,
                    test_name,
                    test_type,
                    status,
                    model_name,
                    column_name,
                    detected_at
                FROM {self._quote_schema('elementary_test_results')}
                WHERE LOWER(model_name) = LOWER('{model_name}')
                ORDER BY test_name, detected_at DESC
            """

            results = self._warehouse_adapter.execute_query(query)

            # Deduplicate by test_name, keeping most recent
            seen_tests = {}
            for row in results:
                test_name = row.get("test_name", "")
                if test_name not in seen_tests:
                    seen_tests[test_name] = row

            checks = []
            for test_name, row in seen_tests.items():
                test_type = row.get("test_type", "").lower()

                if "freshness" in test_type:
                    check_type = CheckType.FRESHNESS
                elif "volume" in test_type:
                    check_type = CheckType.VOLUME
                elif "schema" in test_type:
                    check_type = CheckType.SCHEMA
                elif "null" in test_type:
                    check_type = CheckType.NULLS
                elif "unique" in test_type:
                    check_type = CheckType.UNIQUENESS
                else:
                    check_type = CheckType.CUSTOM_SQL

                status = row.get("status", "pass").lower()
                is_passing = status != "fail"

                # Parse last run time
                last_run = None
                if row.get("detected_at"):
                    ts = row.get("detected_at")
                    if isinstance(ts, datetime):
                        last_run = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts

                checks.append(
                    DataQualityCheck(
                        id=row.get("test_unique_id", ""),
                        source=self.TOOL_NAME,
                        name=test_name,
                        check_type=check_type,
                        target_asset=AffectedAsset(
                            id=model_name,
                            name=model_name,
                            fqn=asset_fqn,
                            asset_type="model",
                            platform=self._warehouse_type.lower(),
                            column_name=row.get("column_name"),
                        ),
                        is_passing=is_passing,
                        last_run_at=last_run,
                    )
                )

            return checks

        except Exception as e:
            logger.error(f"Error fetching tests for {asset_fqn}: {e}")
            return []

    def get_failing_checks(self, limit: int = 50) -> List[DataQualityCheck]:
        """Get currently failing tests across all models."""
        if not self._warehouse_adapter:
            return []

        try:
            query = f"""
                SELECT
                    test_unique_id,
                    test_name,
                    test_type,
                    model_name,
                    schema_name,
                    column_name,
                    detected_at
                FROM {self._quote_schema('elementary_test_results')}
                WHERE status = 'fail'
                AND detected_at >= CURRENT_DATE - INTERVAL '24 hours'
                ORDER BY detected_at DESC
                LIMIT {limit}
            """

            # Adjust for BigQuery
            if self._warehouse_type == "BIGQUERY":
                query = query.replace("CURRENT_DATE - INTERVAL '24 hours'",
                                      "TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)")

            results = self._warehouse_adapter.execute_query(query)

            checks = []
            for row in results:
                test_type = row.get("test_type", "").lower()

                if "freshness" in test_type:
                    check_type = CheckType.FRESHNESS
                elif "volume" in test_type:
                    check_type = CheckType.VOLUME
                else:
                    check_type = CheckType.CUSTOM_SQL

                model_name = row.get("model_name", "")
                schema_name = row.get("schema_name", "")
                fqn = f"{schema_name}.{model_name}" if schema_name else model_name

                checks.append(
                    DataQualityCheck(
                        id=row.get("test_unique_id", ""),
                        source=self.TOOL_NAME,
                        name=row.get("test_name", ""),
                        check_type=check_type,
                        target_asset=AffectedAsset(
                            id=model_name,
                            name=model_name,
                            fqn=fqn,
                            asset_type="model",
                            platform=self._warehouse_type.lower(),
                        ),
                        is_passing=False,
                    )
                )

            return checks

        except Exception as e:
            logger.error(f"Error fetching failing tests: {e}")
            return []

    def get_asset_quality_metrics(self, asset_fqn: str) -> Optional[DataQualityMetrics]:
        """Get quality metrics for a model from Elementary."""
        if not self._warehouse_adapter:
            return None

        try:
            parts = asset_fqn.split(".")
            model_name = parts[-1] if parts else asset_fqn

            # Count tests and failures
            query = f"""
                SELECT
                    COUNT(*) as total_tests,
                    SUM(CASE WHEN status = 'pass' THEN 1 ELSE 0 END) as passing_tests,
                    SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) as failing_tests
                FROM (
                    SELECT test_name, status,
                           ROW_NUMBER() OVER (PARTITION BY test_name ORDER BY detected_at DESC) as rn
                    FROM {self._quote_schema('elementary_test_results')}
                    WHERE LOWER(model_name) = LOWER('{model_name}')
                ) t
                WHERE rn = 1
            """

            results = self._warehouse_adapter.execute_query(query)

            if not results:
                return None

            row = results[0]
            total = int(row.get("total_tests", 0) or 0)
            passing = int(row.get("passing_tests", 0) or 0)
            failing = int(row.get("failing_tests", 0) or 0)

            # Calculate health score
            health_score = None
            if total > 0:
                health_score = (passing / total) * 100

            health_status = "healthy"
            if failing > 0:
                if health_score and health_score < 50:
                    health_status = "critical"
                else:
                    health_status = "warning"

            return DataQualityMetrics(
                asset_fqn=asset_fqn,
                asset_name=model_name,
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

    def get_upstream_incidents(
        self,
        asset_fqn: str,
        depth: int = 3,
    ) -> List[DataIncident]:
        """
        Elementary doesn't have built-in lineage, but we can use dbt's
        ref() dependencies if available in the metadata.
        """
        # Elementary stores model dependencies in dbt_artifacts table
        # For now, return empty - full implementation would query dependencies
        logger.debug("Upstream incident lookup requires dbt lineage metadata")
        return []
