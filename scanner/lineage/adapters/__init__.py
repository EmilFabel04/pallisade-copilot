"""
Query History Adapters for Different Warehouses
Each adapter fetches query history and extracts lineage.
"""

from .base import BaseQueryHistoryAdapter
from .snowflake import SnowflakeQueryHistoryAdapter
from .bigquery import BigQueryQueryHistoryAdapter
from .postgres import PostgresQueryHistoryAdapter
from .sqlserver import SQLServerQueryHistoryAdapter


ADAPTER_MAP = {
    'snowflake': SnowflakeQueryHistoryAdapter,
    'bigquery': BigQueryQueryHistoryAdapter,
    'postgres': PostgresQueryHistoryAdapter,
    'postgresql': PostgresQueryHistoryAdapter,
    'sqlserver': SQLServerQueryHistoryAdapter,
    'tsql': SQLServerQueryHistoryAdapter,
    'azure_sql': SQLServerQueryHistoryAdapter,
    'azure_synapse': SQLServerQueryHistoryAdapter,
}


def get_query_history_adapter(
    connection_type: str,
    connection
) -> BaseQueryHistoryAdapter:
    """
    Factory function to get the appropriate adapter.
    
    Args:
        connection_type: snowflake, bigquery, postgres, etc.
        connection: Database connection object
        
    Returns:
        Appropriate adapter instance
    """
    adapter_class = ADAPTER_MAP.get(connection_type.lower())
    
    if not adapter_class:
        raise ValueError(f"No adapter available for {connection_type}. Supported: {list(ADAPTER_MAP.keys())}")
    
    return adapter_class(connection)


__all__ = [
    'BaseQueryHistoryAdapter',
    'SnowflakeQueryHistoryAdapter',
    'BigQueryQueryHistoryAdapter', 
    'PostgresQueryHistoryAdapter',
    'SQLServerQueryHistoryAdapter',
    'get_query_history_adapter',
]

