"""
Adapter Factory - Creates the right adapter for each database type.

SUPPORTED DATABASES:
- Snowflake (primary)
- BigQuery
- PostgreSQL
- Redshift
- SQL Server / Azure SQL
- Databricks

Usage:
    from adapters import get_adapter
    
    adapter = get_adapter('snowflake', {
        'account': 'xxx',
        'user': 'xxx',
        'password': 'xxx',
        'database': 'xxx',
        'schema': 'xxx',
        'warehouse': 'xxx'
    })
    
    with adapter:
        tables = adapter.get_tables()
        stats = adapter.get_column_stats(tables[0])
"""

import logging
from typing import Dict, Any, Type, Optional

from .base import DatabaseAdapter, DatabaseType

logger = logging.getLogger(__name__)


class AdapterFactory:
    """
    Factory for creating database adapters.
    
    Supports lazy loading of adapters to avoid import errors
    when dependencies are not installed.
    """
    
    # Registry mapping type strings to adapter classes
    _adapters: Dict[str, Type[DatabaseAdapter]] = {}
    _loaded: bool = False
    
    @classmethod
    def _load_adapters(cls) -> None:
        """Lazily load adapter classes."""
        if cls._loaded:
            return
        
        # ===========================================
        # CORE ADAPTERS (6 supported databases)
        # ===========================================
        
        # Snowflake - Primary data warehouse
        try:
            from .snowflake import SnowflakeAdapter
            cls._adapters['snowflake'] = SnowflakeAdapter
            logger.debug("Snowflake adapter loaded")
        except ImportError as e:
            logger.warning(f"Snowflake adapter not available: {e}")
        
        # BigQuery - Google Cloud data warehouse
        try:
            from .bigquery import BigQueryAdapter
            cls._adapters['bigquery'] = BigQueryAdapter
            logger.debug("BigQuery adapter loaded")
        except ImportError as e:
            logger.warning(f"BigQuery adapter not available: {e}")
        
        # PostgreSQL - Open source database (also covers Supabase, RDS, etc.)
        try:
            from .postgres import PostgresAdapter
            cls._adapters['postgres'] = PostgresAdapter
            cls._adapters['postgresql'] = PostgresAdapter
            logger.debug("PostgreSQL adapter loaded")
        except ImportError as e:
            logger.warning(f"PostgreSQL adapter not available: {e}")
        
        # Redshift - AWS data warehouse (extends PostgreSQL)
        try:
            from .redshift import RedshiftAdapter
            cls._adapters['redshift'] = RedshiftAdapter
            logger.debug("Redshift adapter loaded")
        except ImportError as e:
            logger.debug(f"Redshift adapter not available: {e}")
        
        # SQL Server / Azure SQL - Microsoft data platforms
        try:
            from .sqlserver import SQLServerAdapter
            cls._adapters['sqlserver'] = SQLServerAdapter
            cls._adapters['mssql'] = SQLServerAdapter
            cls._adapters['azure_sql'] = SQLServerAdapter
            cls._adapters['azure_synapse'] = SQLServerAdapter
            logger.debug("SQL Server adapter loaded")
        except ImportError as e:
            logger.debug(f"SQL Server adapter not available: {e}")

        # Databricks - Lakehouse Platform (Unity Catalog)
        try:
            from .databricks import DatabricksAdapter
            cls._adapters['databricks'] = DatabricksAdapter
            logger.debug("Databricks adapter loaded")
        except ImportError as e:
            logger.debug(f"Databricks adapter not available: {e}")

        cls._loaded = True
    
    @classmethod
    def get_adapter(cls, 
                    adapter_type: str, 
                    config: Dict[str, Any],
                    auto_connect: bool = True) -> DatabaseAdapter:
        """
        Get a database adapter instance.
        
        Args:
            adapter_type: Type of database ('snowflake', 'postgres', 'bigquery', etc.)
            config: Connection configuration dictionary
            auto_connect: Whether to automatically connect
            
        Returns:
            DatabaseAdapter instance
            
        Raises:
            ValueError: If adapter type is not supported
            ConnectionError: If auto_connect is True and connection fails
        """
        cls._load_adapters()
        
        adapter_type = adapter_type.lower().strip()
        
        if adapter_type not in cls._adapters:
            available = list(cls._adapters.keys())
            raise ValueError(
                f"Unsupported adapter type: '{adapter_type}'. "
                f"Available types: {available}"
            )
        
        adapter_class = cls._adapters[adapter_type]
        adapter = adapter_class(config)
        
        if auto_connect:
            success = adapter.connect()
            if not success:
                raise ConnectionError(f"Failed to connect to {adapter_type}")
        
        return adapter
    
    @classmethod
    def list_available_adapters(cls) -> list:
        """List all available adapter types."""
        cls._load_adapters()
        return list(cls._adapters.keys())
    
    @classmethod
    def is_adapter_available(cls, adapter_type: str) -> bool:
        """Check if an adapter type is available."""
        cls._load_adapters()
        return adapter_type.lower() in cls._adapters
    
    @classmethod
    def register_adapter(cls, 
                         name: str, 
                         adapter_class: Type[DatabaseAdapter]) -> None:
        """
        Register a custom adapter.
        
        Args:
            name: Adapter type name
            adapter_class: Adapter class (must extend DatabaseAdapter)
        """
        if not issubclass(adapter_class, DatabaseAdapter):
            raise ValueError(f"{adapter_class} must extend DatabaseAdapter")
        
        cls._adapters[name.lower()] = adapter_class
        logger.info(f"Registered custom adapter: {name}")


# Convenience function
def get_adapter(adapter_type: str, 
                config: Dict[str, Any],
                auto_connect: bool = True) -> DatabaseAdapter:
    """
    Get a database adapter instance.
    
    This is a convenience function that wraps AdapterFactory.get_adapter().
    
    Args:
        adapter_type: Type of database ('snowflake', 'postgres', 'bigquery', etc.)
        config: Connection configuration dictionary
        auto_connect: Whether to automatically connect
        
    Returns:
        DatabaseAdapter instance
        
    Example:
        >>> adapter = get_adapter('snowflake', {
        ...     'account': 'xyz123.us-east-1',
        ...     'user': 'myuser',
        ...     'password': 'mypassword',
        ...     'database': 'MYDB',
        ...     'schema': 'PUBLIC',
        ...     'warehouse': 'COMPUTE_WH'
        ... })
        >>> 
        >>> tables = adapter.get_tables()
        >>> for table in tables:
        ...     stats = adapter.get_column_stats(table)
        ...     print(f"{table}: {len(stats)} columns")
    """
    return AdapterFactory.get_adapter(adapter_type, config, auto_connect)


# Type mapping from integration types to adapter types
# Only includes supported databases
INTEGRATION_TYPE_MAP = {
    # Snowflake
    'SNOWFLAKE': 'snowflake',
    
    # BigQuery
    'BIGQUERY': 'bigquery',
    
    # PostgreSQL family
    'POSTGRES': 'postgres',
    'POSTGRESQL': 'postgres',
    
    # Redshift
    'REDSHIFT': 'redshift',
    
    # SQL Server family
    'SQLSERVER': 'sqlserver',
    'MSSQL': 'sqlserver',
    'AZURE_SQL': 'sqlserver',
    'AZURE_SYNAPSE': 'sqlserver',

    # Databricks
    'DATABRICKS': 'databricks',
}


def get_adapter_type_from_integration(integration_type: str) -> Optional[str]:
    """
    Map integration type to adapter type.

    Args:
        integration_type: Integration type string (e.g., 'SNOWFLAKE')

    Returns:
        Adapter type string or None if not found
    """
    return INTEGRATION_TYPE_MAP.get(integration_type.upper())


def build_adapter_from_fqn(
    fqn: str,
    org_id: Optional[str] = None,
    stack_id: Optional[str] = None,
) -> "DatabaseAdapter":
    """Resolve an FQN like 'snowflake.raw.water_meters' to a configured adapter instance.

    Uses the pipeline-profile-scoped integration cache populated by the lineage
    investigation pipeline (``_engine_tool_configs_map`` in
    ``scanner/api/routers/_lineage_cache.py``).

    Args:
        fqn: Fully-qualified table name, first segment is the warehouse type
             (e.g. ``"snowflake.raw.water_meters"``).
        org_id: Organisation ID from the acting principal. When provided together
                with ``stack_id``, the cache lookup is scoped to that specific
                tenant. When omitted, all cached configs are searched (test / fallback).
        stack_id: Pipeline stack ID (optional, defaults to ``"default"`` in the cache).

    Returns:
        A connected ``DatabaseAdapter`` instance.

    Raises:
        ValueError: If the FQN is malformed, no matching adapter config is found,
                    or the warehouse type is unsupported.
    """
    parts = fqn.split(".")
    if len(parts) < 2:
        raise ValueError(f"invalid fqn (expected at least 2 dot-separated segments): {fqn!r}")
    warehouse_type = parts[0].lower()

    from scanner.api.routers import _lineage_cache

    # --- Resolve config ---
    cfg: Optional[Dict[str, Any]] = None

    if org_id is not None:
        # Scoped lookup — preferred path in production request context.
        tool_configs = _lineage_cache.get_tool_configs(org_id, stack_id)
        cfg = tool_configs.get(warehouse_type)
    else:
        # org_id=None path: tests/CLI only. Production HTTP middleware enforces a
        # non-empty x-acting-org header before any handler runs, so the FastAPI route
        # always passes a real org_id. This branch exists so unit tests and ad-hoc
        # scripts can resolve adapters without spinning up the full auth stack.
        for entry in _lineage_cache._engine_tool_configs_map.values():
            candidate = entry.get(warehouse_type)
            if candidate:
                cfg = candidate
                break

    if cfg is None:
        raise ValueError(
            f"no configured adapter for warehouse type '{warehouse_type}'. "
            "Re-run the pipeline investigation to populate the connection config cache."
        )

    # --- Instantiate adapter ---
    # All adapters take a single config dict and expect field 'user' (not 'username').
    # The frontend stores 'username'; the mapping is done at the Next.js proxy layer,
    # so by the time configs reach _lineage_cache they should already use 'user'.
    adapter = AdapterFactory.get_adapter(warehouse_type, cfg, auto_connect=True)
    return adapter
