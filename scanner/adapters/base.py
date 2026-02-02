"""
Base Database Adapter - Enterprise Grade

Defines the universal interface that all database adapters must implement.
Supports SQL databases, NoSQL, data warehouses, and streaming platforms.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DatabaseType(Enum):
    """Supported database types."""
    # Data Warehouses
    SNOWFLAKE = "snowflake"
    BIGQUERY = "bigquery"
    REDSHIFT = "redshift"
    DATABRICKS = "databricks"
    SYNAPSE = "synapse"
    
    # SQL Databases
    POSTGRES = "postgres"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    ORACLE = "oracle"
    
    # NoSQL
    MONGODB = "mongodb"
    DYNAMODB = "dynamodb"
    CASSANDRA = "cassandra"
    ELASTICSEARCH = "elasticsearch"
    
    # Streaming
    KAFKA = "kafka"
    KINESIS = "kinesis"


@dataclass
class AdapterCapabilities:
    """
    Describes what capabilities an adapter supports.
    Used to conditionally enable features.
    """
    # Core capabilities
    supports_sql: bool = True
    supports_transactions: bool = True
    
    # Statistics capabilities
    supports_column_stats: bool = True
    supports_histograms: bool = False
    supports_cardinality: bool = True
    supports_percentiles: bool = True
    
    # Query history
    supports_query_history: bool = False
    query_history_days: int = 0
    
    # Sampling
    supports_sampling: bool = True
    supports_tablesample: bool = False
    
    # Schema
    supports_information_schema: bool = True
    supports_schema_changes: bool = True
    
    # Advanced
    supports_explain: bool = True
    supports_partitions: bool = False
    supports_clustering: bool = False
    
    # Freshness
    supports_table_last_modified: bool = False
    

@dataclass
class ColumnMetadata:
    """Metadata about a table column."""
    name: str
    data_type: str
    is_nullable: bool = True
    default_value: Optional[str] = None
    ordinal_position: int = 0
    character_max_length: Optional[int] = None
    numeric_precision: Optional[int] = None
    numeric_scale: Optional[int] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_key_table: Optional[str] = None
    foreign_key_column: Optional[str] = None
    comment: Optional[str] = None


@dataclass  
class TableMetadata:
    """Comprehensive metadata about a database table."""
    full_name: str  # database.schema.table
    database: Optional[str] = None
    schema: Optional[str] = None
    table_name: str = ""
    
    # Basic stats
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    last_modified: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    
    # Structure
    columns: List[ColumnMetadata] = field(default_factory=list)
    primary_key_columns: List[str] = field(default_factory=list)
    
    # Partitioning/Clustering
    is_partitioned: bool = False
    partition_columns: List[str] = field(default_factory=list)
    clustering_columns: List[str] = field(default_factory=list)
    
    # Additional metadata
    table_type: str = "BASE TABLE"  # BASE TABLE, VIEW, MATERIALIZED VIEW
    comment: Optional[str] = None
    owner: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class ColumnStats:
    """Deep statistics for a column."""
    column_name: str
    data_type: str
    
    # Counts
    total_count: int = 0
    null_count: int = 0
    distinct_count: int = 0
    
    # Rates (0.0 - 1.0)
    null_rate: float = 0.0
    distinct_rate: float = 0.0
    
    # Numeric stats (for numeric columns)
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    avg_value: Optional[float] = None
    sum_value: Optional[float] = None
    std_dev: Optional[float] = None
    variance: Optional[float] = None
    
    # Percentiles
    percentile_25: Optional[float] = None
    percentile_50: Optional[float] = None  # median
    percentile_75: Optional[float] = None
    percentile_90: Optional[float] = None
    percentile_99: Optional[float] = None
    
    # String stats (for text columns)
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    avg_length: Optional[float] = None
    
    # Distribution
    histogram: Optional[List[Dict[str, Any]]] = None  # [{bucket, count}, ...]
    top_values: Optional[List[Dict[str, Any]]] = None  # [{value, count}, ...]
    
    # Freshness (for timestamp columns)
    min_timestamp: Optional[datetime] = None
    max_timestamp: Optional[datetime] = None
    
    # Quality indicators
    empty_string_count: int = 0
    whitespace_only_count: int = 0


@dataclass
class QueryHistoryEntry:
    """A single entry from query history."""
    query_id: str
    query_text: str
    
    # Timing
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    
    # Execution
    status: str = "SUCCESS"  # SUCCESS, FAILED, CANCELLED
    error_message: Optional[str] = None
    
    # Resources
    rows_produced: Optional[int] = None
    bytes_scanned: Optional[int] = None
    
    # User info
    user_name: Optional[str] = None
    role_name: Optional[str] = None
    
    # Context
    warehouse: Optional[str] = None
    database: Optional[str] = None
    schema: Optional[str] = None
    
    # Parsed info (from SQL)
    tables_accessed: List[str] = field(default_factory=list)
    query_type: Optional[str] = None  # SELECT, INSERT, UPDATE, DELETE, DDL


class DatabaseAdapter(ABC):
    """
    Abstract base class for all database adapters.
    
    Every adapter must implement core methods for:
    - Connection management
    - Table discovery and metadata
    - Column statistics
    - Data freshness checks
    - Data sampling
    
    Optional methods for:
    - Query history (for lineage)
    - Explain plans
    - Advanced statistics
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize adapter with configuration.
        
        Args:
            config: Connection configuration (credentials, host, etc.)
        """
        self.config = config
        self._connection = None
        self._capabilities = AdapterCapabilities()
        self.database_type: DatabaseType = DatabaseType.POSTGRES
        self.dialect: str = "standard"
        
    @property
    def capabilities(self) -> AdapterCapabilities:
        """Get adapter capabilities."""
        return self._capabilities
    
    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to the database.
        
        Returns:
            True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Close the database connection."""
        pass
    
    @abstractmethod
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """
        Test if the connection is valid.
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        pass
    
    @property
    def is_connected(self) -> bool:
        """Check if adapter has an active connection."""
        return self._connection is not None
    
    def execute_query(self, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Execute a query and return results as list of dicts.
        
        Args:
            query: SQL query to execute
            params: Optional query parameters
            
        Returns:
            List of row dictionaries
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to database")
        
        return self._execute_query_impl(query, params)
    
    @abstractmethod
    def _execute_query_impl(self, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Internal query execution - implement in subclass."""
        pass
    
    # =========================================================================
    # TABLE DISCOVERY
    # =========================================================================
    
    @abstractmethod
    def get_tables(self, 
                   database: Optional[str] = None,
                   schema: Optional[str] = None,
                   include_views: bool = False) -> List[str]:
        """
        Get list of tables in the database.
        
        Args:
            database: Optional database name filter
            schema: Optional schema name filter
            include_views: Whether to include views
            
        Returns:
            List of fully qualified table names
        """
        pass
    
    @abstractmethod
    def get_table_metadata(self, table: str) -> TableMetadata:
        """
        Get comprehensive metadata for a table.
        
        Args:
            table: Fully qualified table name
            
        Returns:
            TableMetadata object
        """
        pass
    
    @abstractmethod
    def get_columns(self, table: str) -> List[ColumnMetadata]:
        """
        Get column information for a table.
        
        Args:
            table: Fully qualified table name
            
        Returns:
            List of ColumnMetadata objects
        """
        pass
    
    # =========================================================================
    # COLUMN STATISTICS
    # =========================================================================
    
    @abstractmethod
    def get_column_stats(self, 
                         table: str, 
                         columns: Optional[List[str]] = None,
                         sample_size: Optional[int] = None) -> List[ColumnStats]:
        """
        Get detailed statistics for columns.
        
        Args:
            table: Fully qualified table name
            columns: Optional list of specific columns (default: all)
            sample_size: Optional sample size for large tables
            
        Returns:
            List of ColumnStats objects
        """
        pass
    
    def get_null_rates(self, table: str) -> Dict[str, float]:
        """
        Get null rate for all columns in a table.
        
        Args:
            table: Fully qualified table name
            
        Returns:
            Dict mapping column name to null rate (0.0 - 1.0)
        """
        stats = self.get_column_stats(table)
        return {s.column_name: s.null_rate for s in stats}
    
    def get_distinct_counts(self, table: str) -> Dict[str, int]:
        """
        Get distinct count for all columns.
        
        Args:
            table: Fully qualified table name
            
        Returns:
            Dict mapping column name to distinct count
        """
        stats = self.get_column_stats(table)
        return {s.column_name: s.distinct_count for s in stats}
    
    # =========================================================================
    # FRESHNESS
    # =========================================================================
    
    @abstractmethod
    def get_table_freshness(self, 
                            table: str, 
                            timestamp_column: Optional[str] = None) -> Dict[str, Any]:
        """
        Get freshness information for a table.
        
        Args:
            table: Fully qualified table name
            timestamp_column: Column to use for freshness (auto-detect if None)
            
        Returns:
            Dict with:
                - last_updated: datetime of most recent row
                - hours_since_update: float
                - row_count: int
                - timestamp_column: str (the column used)
        """
        pass
    
    def detect_timestamp_column(self, table: str) -> Optional[str]:
        """
        Auto-detect the best timestamp column for freshness checks.
        
        Looks for columns with names like:
        - updated_at, modified_at, last_updated
        - created_at, inserted_at
        - timestamp, ts, datetime
        - _fivetran_synced, _dbt_updated_at (ETL columns)
        
        Args:
            table: Fully qualified table name
            
        Returns:
            Best timestamp column name or None
        """
        columns = self.get_columns(table)
        
        # Priority order of timestamp column patterns
        patterns = [
            # High priority - explicit update timestamps
            ['updated_at', 'modified_at', 'last_updated', 'last_modified',
             'update_time', 'modification_time', 'modified_date'],
            # ETL tool columns
            ['_fivetran_synced', '_dbt_updated_at', '_etl_updated_at',
             '_loaded_at', '_airbyte_extracted_at'],
            # Created timestamps
            ['created_at', 'created_date', 'creation_time', 'inserted_at',
             'insert_time', 'created'],
            # Generic timestamps
            ['timestamp', 'ts', 'datetime', 'date', 'time', 'event_time'],
        ]
        
        # Get timestamp-type columns
        timestamp_types = {'timestamp', 'datetime', 'date', 'timestamptz', 
                          'timestamp_ntz', 'timestamp_ltz', 'timestamp_tz',
                          'timestamp with time zone', 'timestamp without time zone'}
        
        timestamp_columns = [
            c.name.lower() for c in columns 
            if c.data_type.lower() in timestamp_types or 'timestamp' in c.data_type.lower()
        ]
        
        # Search by priority
        for pattern_group in patterns:
            for pattern in pattern_group:
                for col in timestamp_columns:
                    if pattern in col:
                        return col
        
        # Fall back to any timestamp column
        return timestamp_columns[0] if timestamp_columns else None
    
    # =========================================================================
    # DATA SAMPLING
    # =========================================================================
    
    @abstractmethod
    def sample_data(self, 
                    table: str, 
                    n: int = 1000,
                    columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Get a random sample of rows from a table.
        
        Args:
            table: Fully qualified table name
            n: Number of rows to sample
            columns: Optional list of columns (default: all)
            
        Returns:
            List of row dictionaries
        """
        pass
    
    # =========================================================================
    # QUERY HISTORY (Optional - for lineage)
    # =========================================================================
    
    def get_query_history(self, 
                          hours: int = 24,
                          user: Optional[str] = None,
                          database: Optional[str] = None) -> List[QueryHistoryEntry]:
        """
        Get recent query history from the database.
        
        Only available if capabilities.supports_query_history is True.
        
        Args:
            hours: How many hours of history to retrieve
            user: Optional filter by user
            database: Optional filter by database
            
        Returns:
            List of QueryHistoryEntry objects
        """
        if not self._capabilities.supports_query_history:
            logger.warning(f"{self.database_type.value} does not support query history")
            return []
        
        return self._get_query_history_impl(hours, user, database)
    
    def _get_query_history_impl(self, 
                                hours: int,
                                user: Optional[str],
                                database: Optional[str]) -> List[QueryHistoryEntry]:
        """Override in subclasses that support query history."""
        return []
    
    # =========================================================================
    # SQL GENERATION HELPERS
    # =========================================================================
    
    @abstractmethod
    def quote_identifier(self, identifier: str) -> str:
        """
        Quote an identifier (table/column name) for this database.
        
        Args:
            identifier: The identifier to quote
            
        Returns:
            Properly quoted identifier
        """
        pass
    
    @abstractmethod
    def get_current_timestamp_sql(self) -> str:
        """Get SQL expression for current timestamp."""
        pass
    
    @abstractmethod
    def get_interval_sql(self, hours: int) -> str:
        """Get SQL expression for timestamp minus hours."""
        pass
    
    @abstractmethod
    def get_limit_sql(self, n: int) -> str:
        """Get SQL for limiting results."""
        pass
    
    @abstractmethod
    def get_random_sample_sql(self, table: str, n: int) -> str:
        """Get SQL for random sampling."""
        pass
    
    # =========================================================================
    # ROW COUNT
    # =========================================================================
    
    def get_row_count(self, table: str) -> int:
        """
        Get row count for a table.
        
        Args:
            table: Fully qualified table name
            
        Returns:
            Number of rows
        """
        query = f"SELECT COUNT(*) as cnt FROM {self.quote_identifier(table)}"
        result = self.execute_query(query)
        return result[0]['cnt'] if result else 0
    
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

