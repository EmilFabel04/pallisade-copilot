"""
SQL Server Database Adapter

Supports SQL Server 2016+ and Azure SQL Database

Features:
- sys.dm_exec_query_stats for query history
- Column statistics from sys.stats
- TABLESAMPLE for efficient sampling
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from .base import (
    DatabaseAdapter,
    DatabaseType,
    AdapterCapabilities,
    TableMetadata,
    ColumnMetadata,
    ColumnStats,
    QueryHistoryEntry,
)

logger = logging.getLogger(__name__)


class SQLServerAdapter(DatabaseAdapter):
    """
    SQL Server / Azure SQL database adapter.
    
    Supports:
    - SQL Server 2016+
    - SQL Server 2019+
    - Azure SQL Database
    - Azure Synapse Analytics
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize SQL Server adapter.
        
        Config options:
            host: Server host
            port: Port (default 1433)
            user: Username
            password: Password
            database: Database name
            driver: ODBC driver name
            encrypt: Use encryption (default True for Azure)
            trust_server_certificate: Trust cert (default False)
        """
        super().__init__(config)
        self.database_type = DatabaseType.SQLSERVER
        self.dialect = "tsql"
        
        self._capabilities = AdapterCapabilities(
            supports_sql=True,
            supports_transactions=True,
            supports_column_stats=True,
            supports_histograms=True,
            supports_cardinality=True,
            supports_percentiles=True,  # PERCENTILE_CONT
            supports_query_history=True,
            query_history_days=7,
            supports_sampling=True,
            supports_tablesample=True,
            supports_information_schema=True,
            supports_schema_changes=True,
            supports_explain=True,
            supports_partitions=True,
            supports_table_last_modified=True,
        )
    
    def connect(self) -> bool:
        """Connect to SQL Server with automatic driver fallback."""
        import pyodbc
        
        # Support both naming conventions (host/server, user/username)
        host = self.config.get('host') or self.config.get('server', 'localhost')
        port = self.config.get('port', 1433)
        database = self.config.get('database')
        user = self.config.get('user') or self.config.get('username')
        password = self.config.get('password')
        encrypt = self.config.get('encrypt', True)
        trust_cert = self.config.get('trust_server_certificate', True)
        
        # Try drivers in order of preference (always try 18 first, regardless of config)
        drivers = [
            '{ODBC Driver 18 for SQL Server}',
            # Only Driver 18 is installed on this system
        ]
        
        last_error = None
        for driver in drivers:
            try:
                conn_str = (
                    f"DRIVER={driver};"
                    f"SERVER={host},{port};"
                    f"DATABASE={database};"
                    f"UID={user};"
                    f"PWD={password};"
                )
                
                if encrypt:
                    conn_str += "Encrypt=yes;"
                if trust_cert:
                    conn_str += "TrustServerCertificate=yes;"
                
                self._connection = pyodbc.connect(conn_str, timeout=30)
                logger.info(f"Connected to SQL Server: {host} (driver: {driver})")
                return True
                
            except pyodbc.Error as e:
                last_error = e
                logger.debug(f"Driver {driver} failed, trying next...")
                continue
        
        logger.error(f"SQL Server connection failed with all drivers: {last_error}")
        return False
    
    def disconnect(self) -> None:
        """Disconnect from SQL Server."""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.info("Disconnected from SQL Server")
    
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """Test SQL Server connection."""
        try:
            if not self.is_connected:
                self.connect()
            
            cursor = self._connection.cursor()
            cursor.execute("SELECT @@VERSION, DB_NAME()")
            row = cursor.fetchone()
            cursor.close()
            
            version = row[0].split('\n')[0] if row else 'Unknown'
            database = row[1] if row else 'Unknown'
            
            return True, f"{version}, database: {database}"
            
        except Exception as e:
            return False, str(e)
    
    def _execute_query_impl(self, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Execute query and return results."""
        cursor = self._connection.cursor()
        
        try:
            if params:
                cursor.execute(query, list(params.values()))
            else:
                cursor.execute(query)
            
            # Get column names
            columns = [column[0] for column in cursor.description] if cursor.description else []
            
            # Fetch all and convert to dicts
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
            
        finally:
            cursor.close()
    
    def get_tables(self,
                   database: Optional[str] = None,
                   schema: Optional[str] = None,
                   include_views: bool = False) -> List[str]:
        """Get list of tables."""
        db = database or self.config.get('database')
        schema_filter = f"AND TABLE_SCHEMA = '{schema}'" if schema else ""
        
        table_types = "'BASE TABLE'"
        if include_views:
            table_types = "'BASE TABLE', 'VIEW'"
        
        query = f"""
            SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_CATALOG = '{db}'
              AND TABLE_TYPE IN ({table_types})
              {schema_filter}
            ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
        
        results = self.execute_query(query)
        return [f"{row['TABLE_CATALOG']}.{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}" for row in results]
    
    def get_table_metadata(self, table: str) -> TableMetadata:
        """Get table metadata."""
        parts = table.split('.')
        if len(parts) == 3:
            db, schema, table_name = parts
        elif len(parts) == 2:
            db = self.config.get('database')
            schema, table_name = parts
        else:
            db = self.config.get('database')
            schema = 'dbo'
            table_name = parts[0]
        
        # Get table info
        query = f"""
            SELECT 
                t.name as table_name,
                s.name as schema_name,
                t.type_desc as table_type,
                p.rows as row_count,
                SUM(a.total_pages) * 8 * 1024 as size_bytes,
                t.create_date,
                t.modify_date,
                ep.value as description
            FROM sys.tables t
            INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
            INNER JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)
            INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
            LEFT JOIN sys.extended_properties ep ON ep.major_id = t.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description'
            WHERE t.name = '{table_name}'
              AND s.name = '{schema}'
            GROUP BY t.name, s.name, t.type_desc, p.rows, t.create_date, t.modify_date, ep.value
        """
        
        results = self.execute_query(query)
        
        if not results:
            raise ValueError(f"Table not found: {table}")
        
        row = results[0]
        columns = self.get_columns(table)
        
        return TableMetadata(
            full_name=table,
            database=db,
            schema=schema,
            table_name=table_name,
            table_type=row.get('table_type', 'USER_TABLE'),
            row_count=row.get('row_count'),
            size_bytes=row.get('size_bytes'),
            created_at=row.get('create_date'),
            last_modified=row.get('modify_date'),
            comment=row.get('description'),
            columns=columns,
        )
    
    def get_columns(self, table: str) -> List[ColumnMetadata]:
        """Get column metadata."""
        parts = table.split('.')
        if len(parts) == 3:
            db, schema, table_name = parts
        elif len(parts) == 2:
            schema, table_name = parts
        else:
            schema = 'dbo'
            table_name = parts[0]
        
        query = f"""
            SELECT 
                c.COLUMN_NAME,
                c.ORDINAL_POSITION,
                c.DATA_TYPE,
                c.CHARACTER_MAXIMUM_LENGTH,
                c.NUMERIC_PRECISION,
                c.NUMERIC_SCALE,
                c.IS_NULLABLE,
                c.COLUMN_DEFAULT,
                CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END as IS_PRIMARY_KEY,
                ep.value as DESCRIPTION
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN (
                SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku 
                    ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            ) pk ON c.TABLE_SCHEMA = pk.TABLE_SCHEMA 
                AND c.TABLE_NAME = pk.TABLE_NAME 
                AND c.COLUMN_NAME = pk.COLUMN_NAME
            LEFT JOIN sys.columns sc ON sc.name = c.COLUMN_NAME
            LEFT JOIN sys.tables st ON st.object_id = sc.object_id AND st.name = c.TABLE_NAME
            LEFT JOIN sys.extended_properties ep 
                ON ep.major_id = st.object_id 
                AND ep.minor_id = sc.column_id 
                AND ep.name = 'MS_Description'
            WHERE c.TABLE_SCHEMA = '{schema}'
              AND c.TABLE_NAME = '{table_name}'
            ORDER BY c.ORDINAL_POSITION
        """
        
        results = self.execute_query(query)
        
        columns = []
        for row in results:
            columns.append(ColumnMetadata(
                name=row['COLUMN_NAME'],
                data_type=row['DATA_TYPE'],
                is_nullable=row['IS_NULLABLE'] == 'YES',
                default_value=row.get('COLUMN_DEFAULT'),
                ordinal_position=row['ORDINAL_POSITION'],
                character_max_length=row.get('CHARACTER_MAXIMUM_LENGTH'),
                numeric_precision=row.get('NUMERIC_PRECISION'),
                numeric_scale=row.get('NUMERIC_SCALE'),
                is_primary_key=bool(row.get('IS_PRIMARY_KEY')),
                comment=row.get('DESCRIPTION'),
            ))
        
        return columns
    
    def get_column_stats(self,
                         table: str,
                         columns: Optional[List[str]] = None,
                         sample_size: Optional[int] = None) -> List[ColumnStats]:
        """Get column statistics."""
        parts = table.split('.')
        if len(parts) == 3:
            full_table = f"[{parts[0]}].[{parts[1]}].[{parts[2]}]"
        elif len(parts) == 2:
            full_table = f"[{parts[0]}].[{parts[1]}]"
        else:
            full_table = f"[dbo].[{parts[0]}]"
        
        if columns is None:
            col_meta = self.get_columns(table)
            columns = [c.name for c in col_meta]
        
        stats = []
        sample_clause = f"TABLESAMPLE ({sample_size} ROWS)" if sample_size else ""
        
        for col in columns:
            try:
                query = f"""
                    SELECT 
                        COUNT(*) as total_count,
                        COUNT([{col}]) as non_null_count,
                        COUNT(DISTINCT [{col}]) as distinct_count,
                        MIN([{col}]) as min_val,
                        MAX([{col}]) as max_val,
                        AVG(CAST([{col}] AS FLOAT)) as avg_val,
                        STDEV(CAST([{col}] AS FLOAT)) as stddev_val
                    FROM {full_table} {sample_clause}
                """
                
                result = self.execute_query(query)
                
                if result:
                    row = result[0]
                    total = row.get('total_count', 0) or 0
                    non_null = row.get('non_null_count', 0) or 0
                    
                    stats.append(ColumnStats(
                        column_name=col,
                        null_count=total - non_null,
                        null_rate=(total - non_null) / total if total > 0 else 0,
                        distinct_count=row.get('distinct_count') or 0,
                        min_value=row.get('min_val'),
                        max_value=row.get('max_val'),
                        avg_value=row.get('avg_val'),
                        stddev_value=row.get('stddev_val'),
                    ))
                    
            except Exception as e:
                logger.warning(f"Error getting stats for {col}: {e}")
                stats.append(ColumnStats(column_name=col, null_rate=0, distinct_count=0))
        
        return stats
    
    def get_table_freshness(self,
                            table: str,
                            timestamp_column: Optional[str] = None) -> Dict[str, Any]:
        """Get table freshness."""
        parts = table.split('.')
        if len(parts) == 3:
            full_table = f"[{parts[0]}].[{parts[1]}].[{parts[2]}]"
            table_name = parts[2]
        elif len(parts) == 2:
            full_table = f"[{parts[0]}].[{parts[1]}]"
            table_name = parts[1]
        else:
            full_table = f"[dbo].[{parts[0]}]"
            table_name = parts[0]
        
        if not timestamp_column:
            timestamp_column = self.detect_timestamp_column(table)
        
        if not timestamp_column:
            # Try sys.dm_db_index_usage_stats for last access
            query = f"""
                SELECT TOP 1 last_user_update
                FROM sys.dm_db_index_usage_stats ius
                JOIN sys.tables t ON t.object_id = ius.object_id
                WHERE t.name = '{table_name}'
                ORDER BY last_user_update DESC
            """
            result = self.execute_query(query)
            
            if result and result[0].get('last_user_update'):
                last_updated = result[0]['last_user_update']
                hours_since = (datetime.now() - last_updated).total_seconds() / 3600
                
                return {
                    'last_updated': last_updated,
                    'hours_since_update': hours_since,
                    'source': 'index_usage_stats',
                }
            
            return {'last_updated': None, 'error': 'No timestamp column found'}
        
        query = f"""
            SELECT 
                MAX([{timestamp_column}]) as last_updated,
                COUNT(*) as row_count
            FROM {full_table}
        """
        
        result = self.execute_query(query)
        
        if result and result[0].get('last_updated'):
            last_updated = result[0]['last_updated']
            hours_since = (datetime.now() - last_updated).total_seconds() / 3600
            
            return {
                'last_updated': last_updated,
                'hours_since_update': hours_since,
                'row_count': result[0].get('row_count'),
                'timestamp_column': timestamp_column,
            }
        
        return {'last_updated': None, 'timestamp_column': timestamp_column}
    
    def sample_data(self,
                    table: str,
                    n: int = 1000,
                    columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Sample data using TABLESAMPLE."""
        parts = table.split('.')
        if len(parts) == 3:
            full_table = f"[{parts[0]}].[{parts[1]}].[{parts[2]}]"
        else:
            full_table = table
        
        col_list = ', '.join(f'[{c}]' for c in columns) if columns else '*'
        
        query = f"""
            SELECT TOP {n} {col_list}
            FROM {full_table}
            TABLESAMPLE ({n * 2} ROWS)
        """
        
        return self.execute_query(query)
    
    def get_query_history(self,
                          start_time: Optional[datetime] = None,
                          end_time: Optional[datetime] = None,
                          limit: int = 1000) -> List[QueryHistoryEntry]:
        """Get query history from DMVs."""
        query = f"""
            SELECT TOP {limit}
                qs.creation_time as start_time,
                qs.last_execution_time as end_time,
                qs.total_elapsed_time / 1000.0 as execution_time_ms,
                qs.total_rows as rows_produced,
                SUBSTRING(st.text, (qs.statement_start_offset/2)+1,
                    ((CASE qs.statement_end_offset
                        WHEN -1 THEN DATALENGTH(st.text)
                        ELSE qs.statement_end_offset
                    END - qs.statement_start_offset)/2) + 1) as query_text
            FROM sys.dm_exec_query_stats qs
            CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
            WHERE st.text NOT LIKE '%sys.%'
            ORDER BY qs.last_execution_time DESC
        """
        
        try:
            results = self.execute_query(query)
            
            entries = []
            for row in results:
                entries.append(QueryHistoryEntry(
                    query_id=None,
                    query_text=row.get('query_text', '')[:10000],
                    start_time=row.get('start_time'),
                    end_time=row.get('end_time'),
                    execution_time_ms=row.get('execution_time_ms'),
                    rows_produced=row.get('rows_produced'),
                    database=self.config.get('database'),
                ))
            
            return entries
            
        except Exception as e:
            logger.warning(f"Could not get query history: {e}")
            return []
    
    # SQL dialect helpers (required abstract methods)
    def quote_identifier(self, identifier: str) -> str:
        """Quote identifier with brackets for SQL Server."""
        return f"[{identifier}]"
    
    def get_current_timestamp_sql(self) -> str:
        """Get current timestamp SQL."""
        return "GETDATE()"
    
    def get_interval_sql(self, hours: int) -> str:
        """Get interval subtraction SQL."""
        return f"DATEADD(HOUR, -{hours}, GETDATE())"
    
    def get_limit_sql(self, n: int) -> str:
        """Get TOP clause (SQL Server style)."""
        return f"TOP {n}"
    
    def get_random_sample_sql(self, table: str, n: int) -> str:
        """Get random sample SQL using TABLESAMPLE."""
        return f"SELECT TOP {n} * FROM {table} TABLESAMPLE ({n * 2} ROWS)"
    
    # Additional helpers
    def get_current_timestamp(self) -> str:
        return "GETDATE()"
    
    def get_interval_hours(self, hours: int) -> str:
        return f"DATEADD(HOUR, -{hours}, GETDATE())"
    
    def get_date_trunc(self, field: str, column: str) -> str:
        if field == 'hour':
            return f"DATEADD(HOUR, DATEDIFF(HOUR, 0, {column}), 0)"
        elif field == 'day':
            return f"CAST({column} AS DATE)"
        elif field == 'month':
            return f"DATEADD(MONTH, DATEDIFF(MONTH, 0, {column}), 0)"
        return column

