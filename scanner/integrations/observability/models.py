"""
Unified Data Models for Observability Integrations

These models provide a common interface for data quality incidents, checks,
and metrics across different observability tools (Monte Carlo, Bigeye, Soda, Elementary).

The goal is to abstract away tool-specific differences so the copilot can
reason about data quality issues uniformly.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional


class IncidentSeverity(Enum):
    """Standardized severity levels across all observability tools."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @classmethod
    def from_monte_carlo(cls, mc_severity: str) -> "IncidentSeverity":
        """Map Monte Carlo severity to unified model."""
        mapping = {
            "SEV-0": cls.CRITICAL,
            "SEV-1": cls.HIGH,
            "SEV-2": cls.MEDIUM,
            "SEV-3": cls.LOW,
            "SEV-4": cls.INFO,
        }
        return mapping.get(mc_severity.upper(), cls.MEDIUM)

    @classmethod
    def from_bigeye(cls, bigeye_priority: str) -> "IncidentSeverity":
        """Map Bigeye priority to unified model."""
        mapping = {
            "critical": cls.CRITICAL,
            "high": cls.HIGH,
            "medium": cls.MEDIUM,
            "low": cls.LOW,
        }
        return mapping.get(bigeye_priority.lower(), cls.MEDIUM)

    @classmethod
    def from_soda(cls, soda_level: str) -> "IncidentSeverity":
        """Map Soda check level to unified model."""
        mapping = {
            "critical": cls.CRITICAL,
            "warn": cls.HIGH,
            "info": cls.INFO,
        }
        return mapping.get(soda_level.lower(), cls.MEDIUM)


class IncidentStatus(Enum):
    """Status of a data quality incident."""
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"
    EXPECTED = "expected"
    MUTED = "muted"

    @classmethod
    def from_monte_carlo(cls, mc_status: str) -> "IncidentStatus":
        """Map Monte Carlo status to unified model."""
        mapping = {
            "INVESTIGATING": cls.ACTIVE,
            "ACKNOWLEDGED": cls.ACKNOWLEDGED,
            "EXPECTED": cls.EXPECTED,
            "FALSE_POSITIVE": cls.FALSE_POSITIVE,
            "FIXED": cls.RESOLVED,
            "NO_ACTION_NEEDED": cls.RESOLVED,
            "MUTED": cls.MUTED,
        }
        return mapping.get(mc_status.upper(), cls.ACTIVE)


class CheckType(Enum):
    """Types of data quality checks."""
    FRESHNESS = "freshness"
    VOLUME = "volume"
    SCHEMA = "schema"
    DISTRIBUTION = "distribution"
    NULLS = "nulls"
    UNIQUENESS = "uniqueness"
    REFERENTIAL = "referential"
    CUSTOM_SQL = "custom_sql"
    ANOMALY = "anomaly"

    @classmethod
    def from_monte_carlo(cls, mc_type: str) -> "CheckType":
        """Map Monte Carlo incident type to unified model."""
        mapping = {
            "FRESHNESS": cls.FRESHNESS,
            "VOLUME": cls.VOLUME,
            "SCHEMA_CHANGE": cls.SCHEMA,
            "FIELD_QUALITY": cls.DISTRIBUTION,
            "FIELD_HEALTH": cls.DISTRIBUTION,
            "DIMENSION_TRACKING": cls.DISTRIBUTION,
            "CUSTOM_SQL": cls.CUSTOM_SQL,
            "JSON_SCHEMA": cls.SCHEMA,
        }
        return mapping.get(mc_type.upper(), cls.ANOMALY)

    @classmethod
    def from_bigeye(cls, bigeye_type: str) -> "CheckType":
        """Map Bigeye metric type to unified model."""
        mapping = {
            "freshness": cls.FRESHNESS,
            "volume": cls.VOLUME,
            "null_percentage": cls.NULLS,
            "distinct_count": cls.UNIQUENESS,
            "distribution": cls.DISTRIBUTION,
            "custom_sql": cls.CUSTOM_SQL,
        }
        return mapping.get(bigeye_type.lower(), cls.ANOMALY)


@dataclass
class AffectedAsset:
    """An asset (table, column, model) affected by an incident."""
    id: str
    name: str
    fqn: str  # Fully qualified name: database.schema.table
    asset_type: str  # table, view, model, column
    platform: str  # bigquery, snowflake, etc.
    column_name: Optional[str] = None
    database: Optional[str] = None
    schema: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Human-readable name for the asset."""
        if self.column_name:
            return f"{self.name}.{self.column_name}"
        return self.name


@dataclass
class DataIncident:
    """
    A data quality incident detected by an observability tool.

    This is the core model for tracking data issues across tools.
    Incidents can be freshness violations, volume anomalies, schema changes,
    distribution shifts, or custom SQL check failures.
    """
    id: str
    source: str  # monte_carlo, bigeye, soda, elementary
    severity: IncidentSeverity
    status: IncidentStatus
    incident_type: CheckType
    title: str
    description: str

    # Affected assets
    affected_assets: List[AffectedAsset] = field(default_factory=list)

    # Timing
    detected_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    # Values for comparison
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    deviation_percentage: Optional[float] = None
    threshold: Optional[str] = None

    # External reference
    external_url: Optional[str] = None
    external_id: Optional[str] = None

    # Raw data from source tool
    raw_data: Dict[str, Any] = field(default_factory=dict)

    # Tags/labels
    tags: List[str] = field(default_factory=list)

    @property
    def primary_asset(self) -> Optional[AffectedAsset]:
        """Get the primary affected asset."""
        return self.affected_assets[0] if self.affected_assets else None

    @property
    def is_active(self) -> bool:
        """Check if incident is still active."""
        return self.status in (IncidentStatus.ACTIVE, IncidentStatus.ACKNOWLEDGED)

    @property
    def age_hours(self) -> float:
        """Hours since incident was detected."""
        return (datetime.now() - self.detected_at).total_seconds() / 3600

    def to_summary(self) -> str:
        """Generate a summary string for the LLM."""
        asset_name = self.primary_asset.display_name if self.primary_asset else "Unknown"
        summary = f"[{self.severity.value.upper()}] {self.incident_type.value}: {self.title}"
        summary += f"\n  Asset: {asset_name}"
        if self.expected_value and self.actual_value:
            summary += f"\n  Expected: {self.expected_value}, Actual: {self.actual_value}"
        if self.deviation_percentage:
            summary += f" ({self.deviation_percentage:+.1f}% deviation)"
        summary += f"\n  Detected: {self.detected_at.strftime('%Y-%m-%d %H:%M')} ({self.age_hours:.1f}h ago)"
        return summary


@dataclass
class DataQualityCheck:
    """
    A configured data quality check/rule/monitor.

    Represents both active and historical checks. Can be used to understand
    what monitoring is in place for an asset.
    """
    id: str
    source: str  # monte_carlo, bigeye, soda, elementary
    name: str
    check_type: CheckType
    target_asset: AffectedAsset

    # Configuration
    threshold: Optional[str] = None
    sql_expression: Optional[str] = None
    schedule: Optional[str] = None  # cron expression or description

    # Current state
    is_passing: bool = True
    consecutive_failures: int = 0
    last_run_at: Optional[datetime] = None
    last_result: Optional[str] = None

    # Metadata
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    description: Optional[str] = None

    # External reference
    external_url: Optional[str] = None

    def to_summary(self) -> str:
        """Generate a summary string for the LLM."""
        status = "PASSING" if self.is_passing else f"FAILING ({self.consecutive_failures} consecutive)"
        summary = f"{self.name} ({self.check_type.value}): {status}"
        summary += f"\n  Target: {self.target_asset.display_name}"
        if self.threshold:
            summary += f"\n  Threshold: {self.threshold}"
        if self.last_run_at:
            summary += f"\n  Last run: {self.last_run_at.strftime('%Y-%m-%d %H:%M')}"
        return summary


@dataclass
class DataQualityMetrics:
    """
    Aggregated quality metrics for an asset.

    Provides a high-level health score and key metrics for quick assessment.
    """
    asset_fqn: str
    asset_name: str

    # Counts
    active_incidents: int = 0
    resolved_incidents_24h: int = 0
    total_checks: int = 0
    passing_checks: int = 0

    # Health
    health_score: Optional[float] = None  # 0-100
    health_status: str = "unknown"  # healthy, warning, critical, unknown

    # Freshness
    freshness_status: str = "unknown"  # fresh, stale, unknown
    hours_since_update: Optional[float] = None
    expected_freshness_hours: Optional[float] = None

    # Volume
    volume_status: str = "normal"  # normal, high, low, unknown
    volume_deviation_pct: Optional[float] = None
    current_row_count: Optional[int] = None
    expected_row_count: Optional[int] = None

    # Schema
    schema_changes_7d: int = 0

    # Timestamps
    last_checked_at: Optional[datetime] = None

    @property
    def check_pass_rate(self) -> Optional[float]:
        """Percentage of checks passing."""
        if self.total_checks == 0:
            return None
        return (self.passing_checks / self.total_checks) * 100

    def to_summary(self) -> str:
        """Generate a summary string for the LLM."""
        lines = [f"Quality Metrics for {self.asset_name}:"]

        if self.health_score is not None:
            lines.append(f"  Health Score: {self.health_score:.0f}/100 ({self.health_status})")

        if self.active_incidents > 0:
            lines.append(f"  Active Incidents: {self.active_incidents}")

        if self.total_checks > 0:
            lines.append(f"  Checks: {self.passing_checks}/{self.total_checks} passing ({self.check_pass_rate:.0f}%)")

        lines.append(f"  Freshness: {self.freshness_status}")
        if self.hours_since_update is not None:
            lines.append(f"    Last updated {self.hours_since_update:.1f}h ago")

        lines.append(f"  Volume: {self.volume_status}")
        if self.volume_deviation_pct is not None:
            lines.append(f"    {self.volume_deviation_pct:+.1f}% from expected")

        if self.schema_changes_7d > 0:
            lines.append(f"  Schema Changes (7d): {self.schema_changes_7d}")

        return "\n".join(lines)


@dataclass
class ObservabilityContext:
    """
    Complete observability context for the copilot.

    This is pre-fetched when the user is debugging or asking about data quality,
    and injected into the LLM system prompt for context.
    """
    # Active issues
    active_incidents: List[DataIncident] = field(default_factory=list)

    # Asset-level quality
    asset_quality: Dict[str, DataQualityMetrics] = field(default_factory=dict)

    # What tools are connected
    connected_tools: List[str] = field(default_factory=list)

    # Summary stats
    total_active_incidents: int = 0
    critical_incidents: int = 0
    high_incidents: int = 0

    # Timestamps
    fetched_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """Calculate summary stats."""
        self.total_active_incidents = len(self.active_incidents)
        self.critical_incidents = sum(
            1 for i in self.active_incidents if i.severity == IncidentSeverity.CRITICAL
        )
        self.high_incidents = sum(
            1 for i in self.active_incidents if i.severity == IncidentSeverity.HIGH
        )

    def get_incidents_for_asset(self, asset_fqn: str) -> List[DataIncident]:
        """Get incidents affecting a specific asset."""
        return [
            i for i in self.active_incidents
            if any(a.fqn.lower() == asset_fqn.lower() for a in i.affected_assets)
        ]

    def to_system_prompt_context(self) -> str:
        """Generate context string for the LLM system prompt."""
        lines = ["\n## Data Observability Context"]
        lines.append(f"Connected tools: {', '.join(self.connected_tools) or 'None'}")

        if not self.active_incidents:
            lines.append("No active data quality incidents detected.")
            return "\n".join(lines)

        lines.append(f"\n### Active Incidents ({self.total_active_incidents} total)")
        if self.critical_incidents > 0:
            lines.append(f"- CRITICAL: {self.critical_incidents}")
        if self.high_incidents > 0:
            lines.append(f"- HIGH: {self.high_incidents}")

        # Show top 10 incidents
        sorted_incidents = sorted(
            self.active_incidents,
            key=lambda i: (
                0 if i.severity == IncidentSeverity.CRITICAL else
                1 if i.severity == IncidentSeverity.HIGH else
                2 if i.severity == IncidentSeverity.MEDIUM else 3
            )
        )

        for incident in sorted_incidents[:10]:
            lines.append(f"\n{incident.to_summary()}")

        if len(self.active_incidents) > 10:
            lines.append(f"\n... and {len(self.active_incidents) - 10} more incidents")

        # Asset quality summaries
        if self.asset_quality:
            lines.append("\n### Asset Quality Summaries")
            for fqn, metrics in list(self.asset_quality.items())[:5]:
                if metrics.health_status in ("warning", "critical") or metrics.active_incidents > 0:
                    lines.append(f"\n{metrics.to_summary()}")

        return "\n".join(lines)
