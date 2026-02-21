"""
Capabilities-based adapter framework for lineage extraction.

Core engine never branches on tool names. Adapters declare what they can do
via capabilities, and the engine orchestrates them generically.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Set, Any, Optional, Type

from ..graph import LineageNode, LineageEdge


class Capability(Enum):
    """What a lineage adapter can do."""
    DISCOVER_ASSETS = "discover_assets"
    EXTRACT_TOOL_LINEAGE = "extract_tool_lineage"
    EXTRACT_TABLE_LINEAGE = "extract_table_lineage"
    EXTRACT_COLUMN_LINEAGE = "extract_column_lineage"
    GET_RUNS_LOGS = "get_runs_logs"
    GET_QUERY_HISTORY = "get_query_history"
    GET_OWNERSHIP = "get_ownership"
    GET_CONTRACTS = "get_contracts"
    GET_BI_EXPOSURES = "get_bi_exposures"


class BaseLineageAdapter(ABC):
    """
    Abstract base class for all lineage adapters.

    Adapters MUST output canonical AssetKeys via the standard fields
    on LineageNode (platform_domain, platform, namespace, database, schema, name).
    No adapter may emit vendor-specific IDs as the only identifier.
    """

    @abstractmethod
    def id(self) -> str:
        """Unique identifier for this adapter instance."""
        ...

    @abstractmethod
    def capabilities(self) -> Set[Capability]:
        """Declare which capabilities this adapter supports."""
        ...

    @abstractmethod
    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover data assets and return canonical nodes."""
        ...

    @abstractmethod
    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract lineage edges between assets."""
        ...

    def fetch_context(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Optionally fetch additional context (runs, logs, queries).

        Override in subclasses that support GET_RUNS_LOGS or GET_QUERY_HISTORY.
        """
        return {}

    @property
    def case_hint(self) -> str:
        """
        Casing convention for this adapter's identifiers.

        Returns one of: "lower", "upper", "preserve".
        Override in subclasses.
        """
        return "lower"


class AdapterRegistry:
    """Registry for lineage adapter types and instances."""

    def __init__(self):
        self._types: Dict[str, Type[BaseLineageAdapter]] = {}
        self._instances: Dict[str, BaseLineageAdapter] = {}

    def register_type(self, type_name: str, adapter_cls: Type[BaseLineageAdapter]) -> None:
        """Register an adapter class by type name."""
        self._types[type_name] = adapter_cls

    def create(self, type_name: str, adapter_id: str, **kwargs) -> BaseLineageAdapter:
        """Create and register an adapter instance."""
        if type_name not in self._types:
            raise ValueError(f"Unknown adapter type: {type_name}. Available: {list(self._types.keys())}")
        instance = self._types[type_name](adapter_id=adapter_id, **kwargs)
        self._instances[adapter_id] = instance
        return instance

    def get(self, adapter_id: str) -> Optional[BaseLineageAdapter]:
        """Get an adapter instance by ID."""
        return self._instances.get(adapter_id)

    def list_types(self) -> List[str]:
        """List all registered adapter type names."""
        return list(self._types.keys())

    def list_instances(self) -> List[BaseLineageAdapter]:
        """List all active adapter instances."""
        return list(self._instances.values())

    def filter_by_capability(self, capability: Capability) -> List[BaseLineageAdapter]:
        """Get all adapter instances that have a given capability."""
        return [a for a in self._instances.values() if capability in a.capabilities()]


def create_default_registry() -> AdapterRegistry:
    """Create a registry pre-loaded with the built-in reference adapters."""
    from .adapters.transform_artifact import TransformArtifactAdapter
    from .adapters.warehouse_catalog import WarehouseCatalogAdapter
    from .adapters.bi_query import BIQueryAdapter
    from .adapters.live_warehouse import LiveWarehouseAdapter
    from .adapters.live_dbt import LiveDbtAdapter
    from .adapters.live_airflow import LiveAirflowAdapter
    from .adapters.live_dagster import LiveDagsterAdapter
    from .adapters.live_prefect import LivePrefectAdapter
    from .adapters.live_fivetran import LiveFivetranAdapter
    from .adapters.live_airbyte import LiveAirbyteAdapter
    from .adapters.live_looker import LiveLookerAdapter
    from .adapters.live_tableau import LiveTableauAdapter
    from .adapters.live_databricks import LiveDatabricksAdapter
    from .adapters.live_n8n import LiveN8nAdapter
    from .adapters.live_powerbi import LivePowerBIAdapter
    from .adapters.live_metabase import LiveMetabaseAdapter
    from .adapters.live_storage import LiveStorageAdapter
    from .adapters.live_elementary import LiveElementaryAdapter
    from .adapters.live_openlineage import LiveOpenLineageAdapter
    from .adapters.live_linux import LiveLinuxAdapter
    from .adapters.live_github import LiveGithubAdapter

    registry = AdapterRegistry()
    # Reference adapters (JSON fixture-based)
    registry.register_type("transform_artifact", TransformArtifactAdapter)
    registry.register_type("warehouse_catalog", WarehouseCatalogAdapter)
    registry.register_type("bi_query", BIQueryAdapter)
    # Live adapters (connect to real infrastructure)
    registry.register_type("live_warehouse", LiveWarehouseAdapter)
    registry.register_type("live_dbt", LiveDbtAdapter)
    registry.register_type("live_airflow", LiveAirflowAdapter)
    # Orchestration adapters
    registry.register_type("live_dagster", LiveDagsterAdapter)
    registry.register_type("live_prefect", LivePrefectAdapter)
    registry.register_type("live_n8n", LiveN8nAdapter)
    # Ingestion adapters
    registry.register_type("live_fivetran", LiveFivetranAdapter)
    registry.register_type("live_airbyte", LiveAirbyteAdapter)
    registry.register_type("live_storage", LiveStorageAdapter)
    # BI adapters
    registry.register_type("live_looker", LiveLookerAdapter)
    registry.register_type("live_tableau", LiveTableauAdapter)
    registry.register_type("live_powerbi", LivePowerBIAdapter)
    registry.register_type("live_metabase", LiveMetabaseAdapter)
    # Warehouse adapters (Unity Catalog)
    registry.register_type("live_databricks", LiveDatabricksAdapter)
    # Quality enrichment
    registry.register_type("live_elementary", LiveElementaryAdapter)
    # OpenLineage (standard event ingestion)
    registry.register_type("live_openlineage", LiveOpenLineageAdapter)
    # Infrastructure & VCS stubs
    registry.register_type("live_linux", LiveLinuxAdapter)
    registry.register_type("live_github", LiveGithubAdapter)
    return registry
