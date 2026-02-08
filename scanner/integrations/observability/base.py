"""
Abstract Base Class for Observability Integrations

Defines the universal interface that all observability clients must implement.
Supports Monte Carlo, Bigeye, Soda, and Elementary.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import logging

from .models import (
    DataIncident,
    DataQualityCheck,
    DataQualityMetrics,
    ObservabilityContext,
    IncidentSeverity,
    IncidentStatus,
)

logger = logging.getLogger(__name__)


class ObservabilityClient(ABC):
    """
    Abstract base class for observability tool integrations.

    Every observability client must implement core methods for:
    - Connection management
    - Incident retrieval
    - Check/monitor management
    - Asset quality metrics

    Optional methods for:
    - Lineage-based root cause analysis
    - Historical trends
    """

    # Tool identifier (override in subclasses)
    TOOL_NAME: str = "unknown"

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize client with configuration.

        Args:
            config: Tool-specific configuration (credentials, endpoints, etc.)
        """
        self.config = config
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if client has an active connection."""
        return self._connected

    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to the observability tool.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection."""
        pass

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        """
        Test if the connection is valid.

        Returns:
            Tuple of (success: bool, message: str)
        """
        pass

    # =========================================================================
    # INCIDENTS
    # =========================================================================

    @abstractmethod
    def get_active_incidents(
        self,
        severity_filter: Optional[List[IncidentSeverity]] = None,
        asset_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[DataIncident]:
        """
        Get active (open) data quality incidents.

        Args:
            severity_filter: Optional list of severities to include
            asset_filter: Optional FQN pattern to filter by (e.g., "mydb.myschema.%")
            limit: Maximum number of incidents to return

        Returns:
            List of DataIncident objects
        """
        pass

    @abstractmethod
    def get_incidents_for_asset(
        self,
        asset_fqn: str,
        hours_back: int = 168,  # 7 days
        include_resolved: bool = False,
    ) -> List[DataIncident]:
        """
        Get incidents affecting a specific asset.

        Args:
            asset_fqn: Fully qualified name of the asset (database.schema.table)
            hours_back: How far back to look for incidents
            include_resolved: Whether to include resolved incidents

        Returns:
            List of DataIncident objects
        """
        pass

    @abstractmethod
    def get_incident_details(self, incident_id: str) -> Optional[DataIncident]:
        """
        Get detailed information about a specific incident.

        Args:
            incident_id: The incident ID

        Returns:
            DataIncident or None if not found
        """
        pass

    # =========================================================================
    # CHECKS / MONITORS
    # =========================================================================

    @abstractmethod
    def get_checks_for_asset(self, asset_fqn: str) -> List[DataQualityCheck]:
        """
        Get all data quality checks configured for an asset.

        Args:
            asset_fqn: Fully qualified name of the asset

        Returns:
            List of DataQualityCheck objects
        """
        pass

    @abstractmethod
    def get_failing_checks(self, limit: int = 50) -> List[DataQualityCheck]:
        """
        Get currently failing checks across all assets.

        Args:
            limit: Maximum number of checks to return

        Returns:
            List of DataQualityCheck objects
        """
        pass

    # =========================================================================
    # METRICS
    # =========================================================================

    @abstractmethod
    def get_asset_quality_metrics(self, asset_fqn: str) -> Optional[DataQualityMetrics]:
        """
        Get aggregated quality metrics for an asset.

        Args:
            asset_fqn: Fully qualified name of the asset

        Returns:
            DataQualityMetrics or None if asset not found
        """
        pass

    # =========================================================================
    # LINEAGE & ROOT CAUSE (Optional - implement if supported)
    # =========================================================================

    def get_upstream_incidents(
        self,
        asset_fqn: str,
        depth: int = 3,
    ) -> List[DataIncident]:
        """
        Get incidents from upstream assets in the lineage.

        This helps identify root causes - if a downstream table is stale,
        it might be because an upstream source failed.

        Args:
            asset_fqn: Fully qualified name of the asset
            depth: How many levels upstream to search

        Returns:
            List of DataIncident objects from upstream assets
        """
        # Default implementation returns empty list
        # Override in subclasses that support lineage (Monte Carlo, Elementary)
        logger.debug(f"{self.TOOL_NAME} does not support upstream incident lookup")
        return []

    def get_downstream_impact(
        self,
        asset_fqn: str,
        depth: int = 3,
    ) -> List[str]:
        """
        Get list of downstream assets that would be impacted by an issue.

        Args:
            asset_fqn: Fully qualified name of the asset
            depth: How many levels downstream to search

        Returns:
            List of downstream asset FQNs
        """
        logger.debug(f"{self.TOOL_NAME} does not support downstream impact lookup")
        return []

    # =========================================================================
    # BULK OPERATIONS
    # =========================================================================

    def build_context(
        self,
        asset_filter: Optional[str] = None,
        include_metrics: bool = True,
    ) -> ObservabilityContext:
        """
        Build a complete observability context for the copilot.

        This is called during context building to pre-fetch relevant
        observability data for debugging queries.

        Args:
            asset_filter: Optional FQN pattern to filter by
            include_metrics: Whether to include per-asset metrics

        Returns:
            ObservabilityContext with incidents and metrics
        """
        context = ObservabilityContext(
            connected_tools=[self.TOOL_NAME],
            fetched_at=datetime.now(),
        )

        try:
            # Fetch active incidents
            context.active_incidents = self.get_active_incidents(
                asset_filter=asset_filter,
                limit=100,
            )

            # Fetch metrics for affected assets
            if include_metrics:
                affected_assets = set()
                for incident in context.active_incidents:
                    for asset in incident.affected_assets:
                        affected_assets.add(asset.fqn)

                for fqn in list(affected_assets)[:20]:  # Limit to 20 assets
                    metrics = self.get_asset_quality_metrics(fqn)
                    if metrics:
                        context.asset_quality[fqn] = metrics

        except Exception as e:
            logger.error(f"Error building observability context from {self.TOOL_NAME}: {e}")

        return context

    # =========================================================================
    # CONTEXT MANAGER
    # =========================================================================

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
