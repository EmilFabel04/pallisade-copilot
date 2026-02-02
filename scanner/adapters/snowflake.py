"""
Snowflake Database Adapter - Enterprise Grade

Full-featured adapter for Snowflake with support for:
- Deep column statistics
- Query history for lineage
- Materialized views and clustering
- Automatic warehouse management
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from .base import (
    DatabaseAdapter,
    DatabaseType,
    AdapterCapabilities,
    TableMetadata,
    ColumnMetadata,
    ColumnStats,
    QueryHistoryEntry
)

logger = logging.getLogger(__name__)


class SnowflakeAdapter(DatabaseAdapter):
    """
    Enterprise Snowflake adapter with full feature support.
    
    Capabilities:
    - Full column statistics including histograms
    - Query history access (requires ACCOUNTADMIN or SYSADMIN)
    - Table sampling using SAMPLE clause
    - Partition/Clustering information
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.database_type = DatabaseType.SNOWFLAKE
        self.dialect = "snowflake"
        
        # Snowflake-specific capabilities
        self._capabilities = AdapterCapabilities(
            supports_sql=True,
            supports_transactions=True,
            supports_column_stats=True,
            supports_histograms=True,
            supports_cardinality=True,
            supports_percentiles=True,
            supports_query_history=True,
            query_history_days=365,  # Up to 1 year in Enterprise
            supports_sampling=True,
            supports_tablesample=True,
            supports_information_schema=True,
            supports_schema_changes=True,
            supports_explain=True,
            supports_partitions=True,  # Micro-partitions
            supports_clustering=True,
            supports_table_last_modified=True,
        )
        
        # Parse config
        self.account = config.get('account')
        self.user = config.get('user')
        self.password = config.get('password')
        self.warehouse = config.get('warehouse', 'COMPUTE_WH')
        self.database = config.get('database')
        self.schema = config.get('schema', 'PUBLIC')
        self.role = config.get('role', 'PUBLIC')
        
    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================
    
    def connect(self) -> bool:
        """Establish connection to Snowflake."""
        try:
            import snowflake.connector
            
            self._connection = snowflake.connector.connect(
                user=self.user,
                password=self.password,
                account=self.account,
                warehouse=self.warehouse,
                database=self.database,
                schema=self.schema,
                role=self.role,
                # Performance settings
                client_session_keep_alive=True,
                login_timeout=30,
                network_timeout=60,
            )
            
            logger.info(f"Connected to Snowflake: {self.account}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Snowflake: {e}")
            self._connection = None
            return False
    
    def disconnect(self) -> None:
        """Close Snowflake connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.info("Disconnected from Snowflake")
            except Exception as e:
                logger.warning(f"Error closing Snowflake connection: {e}")
            finally:
                self._connection = None
    
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """Test Snowflake connection."""
        try:
            if not self.is_connected:
                self.connect()
            
            result = self.execute_query("SELECT CURRENT_VERSION() as version")
            version = result[0]['VERSION'] if result else 'unknown'
            
            return True, f"Snowflake {version}"
            
        except Exception as e:
            return False, str(e)
    
    def _execute_query_impl(self, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Execute query and return results."""
        cursor = self._connection.cursor()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Get column names
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            
            # Fetch all results as dicts
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
            
        finally:
            cursor.close()
    
    # =========================================================================
    # TABLE DISCOVERY
    # =========================================================================
    
    def get_tables(self, 
                   database: Optional[str] = None,
                   schema: Optional[str] = None,
                   include_views: bool = False) -> List[str]:
        """Get list of tables in Snowflake."""
        db = database or self.database
        sch = schema or self.schema
        
        type_filter = "IN ('BASE TABLE')" if not include_views else "IN ('BASE TABLE', 'VIEW')"
        
        query = f"""
            SELECT TABLE_CATALOG || '.' || TABLE_SCHEMA || '.' || TABLE_NAME as full_name
            FROM {db}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{sch}'
            AND TABLE_TYPE {type_filter}
            ORDER BY TABLE_NAME
        """
        
        result = self.execute_query(query)
        return [row['FULL_NAME'] for row in result]
    
    def get_table_metadata(self, table: str) -> TableMetadata:
        """Get comprehensive table metadata from Snowflake."""
        # Parse table name
        parts = table.split('.')
        if len(parts) == 3:
            db, schema, tbl = parts
        elif len(parts) == 2:
            db, schema, tbl = self.database, parts[0], parts[1]
        else:
            db, schema, tbl = self.database, self.schema, parts[0]
        
        # Get basic metadata
        query = f"""
            SELECT 
                TABLE_CATALOG,
                TABLE_SCHEMA,
                TABLE_NAME,
                TABLE_TYPE,
                ROW_COUNT,
                BYTES,
                CREATED,
                LAST_ALTERED,
                COMMENT,
                TABLE_OWNER,
                CLUSTERING_KEY,
                IS_TRANSIENT
            FROM {db}.INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{schema}'
            AND TABLE_NAME = '{tbl}'
        """
        
        result = self.execute_query(query)
        
        if not result:
            raise ValueError(f"Table not found: {table}")
        
        row = result[0]
        
        # Get columns
        columns = self.get_columns(table)
        
        # Parse clustering key
        clustering_key = row.get('CLUSTERING_KEY') or ''
        clustering_columns = []
        if clustering_key:
            # Format: LINEAR(col1, col2) or (col1, col2)
            import re
            match = re.search(r'\((.*?)\)', clustering_key)
            if match:
                clustering_columns = [c.strip() for c in match.group(1).split(',')]
        
        return TableMetadata(
            full_name=f"{row['TABLE_CATALOG']}.{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}",
            database=row['TABLE_CATALOG'],
            schema=row['TABLE_SCHEMA'],
            table_name=row['TABLE_NAME'],
            row_count=row.get('ROW_COUNT'),
            size_bytes=row.get('BYTES'),
            created_at=row.get('CREATED'),
            last_modified=row.get('LAST_ALTERED'),
            columns=columns,
            primary_key_columns=self._get_primary_keys(db, schema, tbl),
            is_partitioned=True,  # Snowflake always uses micro-partitions
            clustering_columns=clustering_columns,
            table_type=row['TABLE_TYPE'],
            comment=row.get('COMMENT'),
            owner=row.get('TABLE_OWNER'),
        )
    
    def _get_primary_keys(self, database: str, schema: str, table: str) -> List[str]:
        """Get primary key columns for a table."""
        try:
            query = f"""
                SHOW PRIMARY KEYS IN {database}.{schema}.{table}
            """
            result = self.execute_query(query)
            return [row.get('column_name', row.get('COLUMN_NAME', '')) for row in result]
        except:
            return []
    
    def get_columns(self, table: str) -> List[ColumnMetadata]:
        """Get detailed column information."""
        parts = table.split('.')
        if len(parts) == 3:
            db, schema, tbl = parts
        elif len(parts) == 2:
            db, schema, tbl = self.database, parts[0], parts[1]
        else:
            db, schema, tbl = self.database, self.schema, parts[0]
        
        query = f"""
            SELECT 
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_DEFAULT,
                ORDINAL_POSITION,
                CHARACTER_MAXIMUM_LENGTH,
                NUMERIC_PRECISION,
                NUMERIC_SCALE,
                COMMENT
            FROM {db}.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{schema}'
            AND TABLE_NAME = '{tbl}'
            ORDER BY ORDINAL_POSITION
        """
        
        result = self.execute_query(query)
        
        return [
            ColumnMetadata(
                name=row['COLUMN_NAME'],
                data_type=row['DATA_TYPE'],
                is_nullable=row['IS_NULLABLE'] == 'YES',
                default_value=row.get('COLUMN_DEFAULT'),
                ordinal_position=row['ORDINAL_POSITION'],
                character_max_length=row.get('CHARACTER_MAXIMUM_LENGTH'),
                numeric_precision=row.get('NUMERIC_PRECISION'),
                numeric_scale=row.get('NUMERIC_SCALE'),
                comment=row.get('COMMENT'),
            )
            for row in result
        ]
    
    # =========================================================================
    # COLUMN STATISTICS
    # =========================================================================
    
    def get_column_stats(self, 
                         table: str, 
                         columns: Optional[List[str]] = None,
                         sample_size: Optional[int] = None) -> List[ColumnStats]:
        """Get detailed column statistics from Snowflake."""
        all_columns = self.get_columns(table)
        
        if columns:
            all_columns = [c for c in all_columns if c.name in columns]
        
        stats_list = []
        
        for col in all_columns:
            stats = self._get_single_column_stats(table, col, sample_size)
            stats_list.append(stats)
        
        return stats_list
    
    def _get_single_column_stats(self, 
                                  table: str, 
                                  col: ColumnMetadata,
                                  sample_size: Optional[int] = None) -> ColumnStats:
        """Get statistics for a single column."""
        col_name = f'"{col.name}"'
        sample_clause = f"SAMPLE ({sample_size} ROWS)" if sample_size else ""
        
        # Build stats query based on data type
        is_numeric = col.data_type.upper() in (
            'NUMBER', 'DECIMAL', 'INT', 'INTEGER', 'BIGINT', 
            'SMALLINT', 'TINYINT', 'FLOAT', 'FLOAT4', 'FLOAT8', 
            'DOUBLE', 'REAL', 'NUMERIC'
        )
        
        is_timestamp = 'TIMESTAMP' in col.data_type.upper() or col.data_type.upper() in ('DATE', 'DATETIME')
        is_string = col.data_type.upper() in ('VARCHAR', 'STRING', 'TEXT', 'CHAR', 'CHARACTER')
        
        # Base stats query
        base_query = f"""
            SELECT 
                COUNT(*) as total_count,
                COUNT({col_name}) as non_null_count,
                COUNT(*) - COUNT({col_name}) as null_count,
                APPROX_COUNT_DISTINCT({col_name}) as distinct_count
            FROM {table} {sample_clause}
        """
        
        base_result = self.execute_query(base_query)
        base = base_result[0] if base_result else {}
        
        total = base.get('TOTAL_COUNT', 0)
        null_count = base.get('NULL_COUNT', 0)
        distinct = base.get('DISTINCT_COUNT', 0)
        
        stats = ColumnStats(
            column_name=col.name,
            data_type=col.data_type,
            total_count=total,
            null_count=null_count,
            distinct_count=distinct,
            null_rate=null_count / total if total > 0 else 0,
            distinct_rate=distinct / total if total > 0 else 0,
        )
        
        # Numeric stats
        if is_numeric:
            numeric_query = f"""
                SELECT 
                    MIN({col_name}) as min_val,
                    MAX({col_name}) as max_val,
                    AVG({col_name}) as avg_val,
                    SUM({col_name}) as sum_val,
                    STDDEV({col_name}) as std_dev,
                    VARIANCE({col_name}) as variance,
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col_name}) as p25,
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {col_name}) as p50,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col_name}) as p75,
                    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY {col_name}) as p90,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY {col_name}) as p99
                FROM {table} {sample_clause}
            """
            
            try:
                numeric_result = self.execute_query(numeric_query)
                if numeric_result:
                    n = numeric_result[0]
                    stats.min_value = n.get('MIN_VAL')
                    stats.max_value = n.get('MAX_VAL')
                    stats.avg_value = n.get('AVG_VAL')
                    stats.sum_value = n.get('SUM_VAL')
                    stats.std_dev = n.get('STD_DEV')
                    stats.variance = n.get('VARIANCE')
                    stats.percentile_25 = n.get('P25')
                    stats.percentile_50 = n.get('P50')
                    stats.percentile_75 = n.get('P75')
                    stats.percentile_90 = n.get('P90')
                    stats.percentile_99 = n.get('P99')
            except Exception as e:
                logger.warning(f"Error getting numeric stats for {col.name}: {e}")
        
        # Timestamp stats
        if is_timestamp:
            ts_query = f"""
                SELECT 
                    MIN({col_name}) as min_ts,
                    MAX({col_name}) as max_ts
                FROM {table} {sample_clause}
            """
            
            try:
                ts_result = self.execute_query(ts_query)
                if ts_result:
                    t = ts_result[0]
                    stats.min_timestamp = t.get('MIN_TS')
                    stats.max_timestamp = t.get('MAX_TS')
            except Exception as e:
                logger.warning(f"Error getting timestamp stats for {col.name}: {e}")
        
        # String stats
        if is_string:
            string_query = f"""
                SELECT 
                    MIN(LENGTH({col_name})) as min_len,
                    MAX(LENGTH({col_name})) as max_len,
                    AVG(LENGTH({col_name})) as avg_len,
                    SUM(CASE WHEN {col_name} = '' THEN 1 ELSE 0 END) as empty_count,
                    SUM(CASE WHEN TRIM({col_name}) = '' AND {col_name} != '' THEN 1 ELSE 0 END) as whitespace_count
                FROM {table} {sample_clause}
            """
            
            try:
                string_result = self.execute_query(string_query)
                if string_result:
                    s = string_result[0]
                    stats.min_length = s.get('MIN_LEN')
                    stats.max_length = s.get('MAX_LEN')
                    stats.avg_length = s.get('AVG_LEN')
                    stats.empty_string_count = s.get('EMPTY_COUNT', 0)
                    stats.whitespace_only_count = s.get('WHITESPACE_COUNT', 0)
            except Exception as e:
                logger.warning(f"Error getting string stats for {col.name}: {e}")
        
        # Get top values
        try:
            top_query = f"""
                SELECT {col_name} as value, COUNT(*) as cnt
                FROM {table} {sample_clause}
                WHERE {col_name} IS NOT NULL
                GROUP BY {col_name}
                ORDER BY cnt DESC
                LIMIT 10
            """
            top_result = self.execute_query(top_query)
            stats.top_values = [
                {'value': str(r['VALUE']), 'count': r['CNT']} 
                for r in top_result
            ]
        except Exception as e:
            logger.warning(f"Error getting top values for {col.name}: {e}")
        
        return stats
    
    # =========================================================================
    # FRESHNESS
    # =========================================================================
    
    def get_table_freshness(self, 
                            table: str, 
                            timestamp_column: Optional[str] = None) -> Dict[str, Any]:
        """Get freshness information for a Snowflake table."""
        
        ts_col = timestamp_column or self.detect_timestamp_column(table)
        
        if not ts_col:
            # Try to get from table metadata (last_altered)
            metadata = self.get_table_metadata(table)
            if metadata.last_modified:
                hours_ago = (datetime.now() - metadata.last_modified).total_seconds() / 3600
                return {
                    'last_updated': metadata.last_modified,
                    'hours_since_update': hours_ago,
                    'row_count': metadata.row_count,
                    'timestamp_column': '_METADATA',
                    'source': 'table_metadata'
                }
            return {
                'error': 'No timestamp column found',
                'timestamp_column': None
            }
        
        query = f"""
            SELECT 
                MAX("{ts_col}") as last_update,
                COUNT(*) as row_count,
                DATEDIFF(hour, MAX("{ts_col}"), CURRENT_TIMESTAMP()) as hours_ago
            FROM {table}
        """
        
        result = self.execute_query(query)
        
        if result:
            row = result[0]
            return {
                'last_updated': row.get('LAST_UPDATE'),
                'hours_since_update': row.get('HOURS_AGO', 0),
                'row_count': row.get('ROW_COUNT', 0),
                'timestamp_column': ts_col,
                'source': 'column'
            }
        
        return {'error': 'Failed to get freshness', 'timestamp_column': ts_col}
    
    # =========================================================================
    # DATA SAMPLING
    # =========================================================================
    
    def sample_data(self, 
                    table: str, 
                    n: int = 1000,
                    columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get random sample from Snowflake using SAMPLE clause."""
        cols = ', '.join(f'"{c}"' for c in columns) if columns else '*'
        
        # Snowflake's SAMPLE is efficient for large tables
        query = f"""
            SELECT {cols}
            FROM {table}
            SAMPLE ({n} ROWS)
        """
        
        return self.execute_query(query)
    
    # =========================================================================
    # QUERY HISTORY
    # =========================================================================
    
    def _get_query_history_impl(self, 
                                hours: int,
                                user: Optional[str],
                                database: Optional[str]) -> List[QueryHistoryEntry]:
        """Get query history from Snowflake's ACCOUNT_USAGE schema."""
        
        where_clauses = [f"START_TIME >= DATEADD(hour, -{hours}, CURRENT_TIMESTAMP())"]
        
        if user:
            where_clauses.append(f"USER_NAME = '{user}'")
        if database:
            where_clauses.append(f"DATABASE_NAME = '{database}'")
        
        where = " AND ".join(where_clauses)
        
        query = f"""
            SELECT 
                QUERY_ID,
                QUERY_TEXT,
                START_TIME,
                END_TIME,
                TOTAL_ELAPSED_TIME,
                EXECUTION_STATUS,
                ERROR_MESSAGE,
                ROWS_PRODUCED,
                BYTES_SCANNED,
                USER_NAME,
                ROLE_NAME,
                WAREHOUSE_NAME,
                DATABASE_NAME,
                SCHEMA_NAME,
                QUERY_TYPE
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE {where}
            AND QUERY_TYPE IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'CREATE_TABLE_AS_SELECT')
            ORDER BY START_TIME DESC
            LIMIT 10000
        """
        
        try:
            results = self.execute_query(query)
            
            return [
                QueryHistoryEntry(
                    query_id=row['QUERY_ID'],
                    query_text=row['QUERY_TEXT'],
                    start_time=row['START_TIME'],
                    end_time=row.get('END_TIME'),
                    duration_ms=row.get('TOTAL_ELAPSED_TIME'),
                    status=row.get('EXECUTION_STATUS', 'UNKNOWN'),
                    error_message=row.get('ERROR_MESSAGE'),
                    rows_produced=row.get('ROWS_PRODUCED'),
                    bytes_scanned=row.get('BYTES_SCANNED'),
                    user_name=row.get('USER_NAME'),
                    role_name=row.get('ROLE_NAME'),
                    warehouse=row.get('WAREHOUSE_NAME'),
                    database=row.get('DATABASE_NAME'),
                    schema=row.get('SCHEMA_NAME'),
                    query_type=row.get('QUERY_TYPE'),
                )
                for row in results
            ]
        except Exception as e:
            logger.error(f"Error fetching query history: {e}")
            return []
    
    # =========================================================================
    # SQL GENERATION
    # =========================================================================
    
    def quote_identifier(self, identifier: str) -> str:
        """Quote Snowflake identifier."""
        # Already qualified with dots
        if '.' in identifier:
            parts = identifier.split('.')
            return '.'.join(f'"{p}"' for p in parts)
        return f'"{identifier}"'
    
    def get_current_timestamp_sql(self) -> str:
        """Snowflake current timestamp."""
        return "CURRENT_TIMESTAMP()"
    
    def get_interval_sql(self, hours: int) -> str:
        """Snowflake interval subtraction."""
        return f"DATEADD(hour, -{hours}, CURRENT_TIMESTAMP())"
    
    def get_limit_sql(self, n: int) -> str:
        """Snowflake LIMIT clause."""
        return f"LIMIT {n}"
    
    def get_random_sample_sql(self, table: str, n: int) -> str:
        """Snowflake random sample."""
        return f"SELECT * FROM {table} SAMPLE ({n} ROWS)"

