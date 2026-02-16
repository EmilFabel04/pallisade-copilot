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
