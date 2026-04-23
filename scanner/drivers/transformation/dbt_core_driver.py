"""dbt Core IntegrationDriver — scaffold."""

from __future__ import annotations
from typing import Any, Dict, List

from ..base import (
    ConfigValidation, ConnectionResult, DriverCapabilities,
    GraphDomain, IntegrationDriver, IntegrationLayer,
)


class DbtCoreDriver(IntegrationDriver):
    def id(self) -> str: return "dbt_core"
    def integration_type(self) -> str: return "DBT_CORE"
    def layer(self) -> IntegrationLayer: return IntegrationLayer.TRANSFORMATION
    def graph_domain(self) -> GraphDomain: return GraphDomain.DATA_PLANE

    def validate_config(self, config: Dict[str, Any]) -> ConfigValidation:
        errors = []
        if not config.get("project_dir") and not config.get("projectDir") and not config.get("manifest"):
            errors.append("project_dir or manifest is required")
        return ConfigValidation(valid=not errors, errors=errors)

    def test_connection(self, config: Dict[str, Any]) -> ConnectionResult:
        # dbt Core is file-based; "connection" = manifest exists
        manifest = config.get("manifest")
        if manifest and isinstance(manifest, dict) and manifest.get("nodes"):
            return ConnectionResult(ok=True, message="dbt manifest loaded successfully")
        return ConnectionResult(ok=False, message="No valid dbt manifest found")

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            can_extract_metadata=True, can_extract_lineage=True,
            can_health_check=True,
            supported_monitors=["freshness", "schema_change"],
        )

    def events_emitted(self) -> List[str]:
        return ["run.completed", "run.failed", "test.failed", "extraction.completed", "extraction.failed"]

    def recommended_monitors(self) -> List[str]:
        return ["freshness", "schema_change"]
