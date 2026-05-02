"""
Amazon Redshift Database Adapter

Supports Redshift and Redshift Serverless

Features:
- SVL_QUERY_SUMMARY for query history
- STL_SCAN for table access patterns
- System tables for column statistics
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


class RedshiftAdapter(DatabaseAdapter):
    """
    Amazon Redshift database adapter.
    
    Supports:
    - Redshift (RA3, DC2, DS2)
    - Redshift Serverless
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Redshift adapter.
        
        Config options:
            host: Cluster endpoint
            port: Port (default 5439)
            user: Username
            password: Password
            database: Database name
            sslmode: SSL mode (default 'require')
        """
        super().__init__(config)
        self.database_type = DatabaseType.REDSHIFT
        self.dialect = "redshift"
        
        self._capabilities = AdapterCapabilities(
            supports_sql=True,
            supports_transactions=True,
            supports_column_stats=True,
            supports_histograms=False,
            supports_cardinality=True,
            supports_percentiles=True,
            supports_query_history=True,
            query_history_days=7,
            supports_sampling=True,
            supports_tablesample=False,
            supports_information_schema=True,
            supports_schema_changes=True,
            supports_explain=True,
            supports_partitions=False,
            supports_clustering=True,  # Sort keys
            supports_table_last_modified=True,
        )
    
    def connect(self) -> bool:
        """Connect to Redshift."""
        try:
            import redshift_connector
            
            self._connection = redshift_connector.connect(
                host=self.config.get('host'),
                port=self.config.get('port', 5439),
                user=self.config.get('user'),
                password=self.config.get('password'),
                database=self.config.get('database'),
                sslmode=self.config.get('sslmode', 'require'),
            )
            
            logger.info(f"Connected to Redshift: {self.config.get('host')}")
            return True
            
        except Exception as e:
            logger.error(f"Redshift connection failed: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from Redshift."""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.info("Disconnected from Redshift")
    
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """Test Redshift connection."""
        try:
            if not self.is_connected:
                self.connect()
            
            cursor = self._connection.cursor()
            cursor.execute("SELECT version(), current_database()")
            version, database = cursor.fetchone()
            cursor.close()
            
            return True, f"Redshift, database: {database}"
            
        except Exception as e:
            return False, str(e)
    
    def _execute_query_impl(self, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Execute query and return results."""
        cursor = self._connection.cursor()
        
        try:
            cursor.execute(query)
            
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                results = []
                for row in cursor.fetchall():
                    results.append(dict(zip(columns, row)))
                return results
            return []
            
        finally:
            cursor.close()
    
    def get_tables(self,
                   database: Optional[str] = None,
                   schema: Optional[str] = None,
                   include_views: bool = False) -> List[str]:
        """Get list of tables."""
        schema_filter = f"AND schemaname = '{schema}'" if schema else "AND schemaname NOT IN ('pg_catalog', 'information_schema')"
        
        query = f"""
            SELECT schemaname, tablename
            FROM pg_tables
            WHERE 1=1
              {schema_filter}
            ORDER BY schemaname, tablename
        """
        
        results = self.execute_query(query)
        tables = [f"{row['schemaname']}.{row['tablename']}" for row in results]
        
        if include_views:
            view_query = f"""
                SELECT schemaname, viewname as tablename
                FROM pg_views
                WHERE 1=1
                  {schema_filter}
            """
            view_results = self.execute_query(view_query)
            tables.extend([f"{row['schemaname']}.{row['tablename']}" for row in view_results])
        
        return tables
    
    def get_table_metadata(self, table: str) -> TableMetadata:
        """Get table metadata."""
        parts = table.split('.')
        schema = parts[0] if len(parts) > 1 else 'public'
        table_name = parts[-1]
        
        query = f"""
            SELECT 
                t.schemaname,
                t.tablename,
                c.reltuples as row_count,
                pg_total_relation_size('"' || t.schemaname || '"."' || t.tablename || '"') as size_bytes,
                obj_description(c.oid) as description
            FROM pg_tables t
            JOIN pg_class c ON c.relname = t.tablename
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.schemaname
            WHERE t.schemaname = '{schema}'
              AND t.tablename = '{table_name}'
        """
        
        results = self.execute_query(query)
        
        if not results:
            raise ValueError(f"Table not found: {table}")
        
        row = results[0]
        columns = self.get_columns(table)
        
        return TableMetadata(
            full_name=table,
            database=self.config.get('database'),
            schema=schema,
            table_name=table_name,
            table_type='BASE TABLE',
            row_count=int(row.get('row_count', 0)),
            size_bytes=row.get('size_bytes'),
            comment=row.get('description'),
            columns=columns,
        )
    
    def get_columns(self, table: str) -> List[ColumnMetadata]:
        """Get column metadata."""
        parts = table.split('.')
        schema = parts[0] if len(parts) > 1 else 'public'
        table_name = parts[-1]
        
        query = f"""
            SELECT 
                c.column_name,
                c.ordinal_position,
                c.data_type,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                c.is_nullable,
                c.column_default,
                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END as is_primary_key,
                d.description
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT kcu.column_name, kcu.table_schema, kcu.table_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu 
                    ON tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
            ) pk ON c.table_schema = pk.table_schema 
                AND c.table_name = pk.table_name 
                AND c.column_name = pk.column_name
            LEFT JOIN pg_catalog.pg_description d
                ON d.objoid = (
                    SELECT oid FROM pg_class WHERE relname = c.table_name
                    AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = c.table_schema)
                )
                AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = '{schema}'
              AND c.table_name = '{table_name}'
            ORDER BY c.ordinal_position
        """
        
        results = self.execute_query(query)
        
        columns = []
        for row in results:
            columns.append(ColumnMetadata(
                name=row['column_name'],
                data_type=row['data_type'],
                is_nullable=row['is_nullable'] == 'YES',
                default_value=row.get('column_default'),
                ordinal_position=row['ordinal_position'],
                character_max_length=row.get('character_maximum_length'),
                numeric_precision=row.get('numeric_precision'),
                numeric_scale=row.get('numeric_scale'),
                is_primary_key=row.get('is_primary_key', False),
                comment=row.get('description'),
            ))
        
        return columns

    def get_table_schema(self, fqn: str) -> List[Dict[str, Any]]:
        """Return column metadata for *fqn* as a list of plain dicts.

        Each dict contains ``column_name``, ``data_type``, and ``is_nullable``
        (bool). This is the canonical interface used by :class:`WarehouseDiscoverer`.

        Redshift FQNs may optionally include a leading ``redshift.`` warehouse
        prefix (e.g. ``"redshift.public.my_table"``). The prefix is stripped
        before passing to :meth:`get_columns`, which handles ``schema.table``
        and plain ``table`` forms.
        """
        parts = fqn.split(".")
        if len(parts) >= 2 and parts[0].lower() == "redshift":
            table_ref = ".".join(parts[1:])
        else:
            table_ref = fqn
        cols = self.get_columns(table_ref)
        return [
            {"column_name": c.name, "data_type": c.data_type, "is_nullable": c.is_nullable}
            for c in cols
        ]

    def get_column_stats(self,
                         table: str,
                         columns: Optional[List[str]] = None,
                         sample_size: Optional[int] = None) -> List[ColumnStats]:
        """Get column statistics."""
        parts = table.split('.')
        schema = parts[0] if len(parts) > 1 else 'public'
        table_name = parts[-1]
        full_table = f'"{schema}"."{table_name}"'
        
        if columns is None:
            col_meta = self.get_columns(table)
            columns = [c.name for c in col_meta]
        
        stats = []
        sample_clause = f"LIMIT {sample_size}" if sample_size else ""
        
        for col in columns:
            try:
                query = f"""
                    SELECT 
                        COUNT(*) as total_count,
                        COUNT("{col}") as non_null_count,
                        COUNT(DISTINCT "{col}") as distinct_count,
                        MIN("{col}") as min_val,
                        MAX("{col}") as max_val,
                        AVG("{col}"::float) as avg_val,
                        STDDEV("{col}"::float) as stddev_val,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY "{col}") as median_val
                    FROM (SELECT "{col}" FROM {full_table} {sample_clause}) t
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
                        median_value=row.get('median_val'),
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
        schema = parts[0] if len(parts) > 1 else 'public'
        table_name = parts[-1]
        full_table = f'"{schema}"."{table_name}"'
        
        if not timestamp_column:
            timestamp_column = self.detect_timestamp_column(table)
        
        if not timestamp_column:
            # Try STL_INSERT for last insert time
            query = f"""
                SELECT MAX(endtime) as last_updated
                FROM stl_insert i
                JOIN pg_class c ON c.oid = i.tbl
                WHERE c.relname = '{table_name}'
            """
            result = self.execute_query(query)
            
            if result and result[0].get('last_updated'):
                last_updated = result[0]['last_updated']
                hours_since = (datetime.now() - last_updated).total_seconds() / 3600
                return {
                    'last_updated': last_updated,
                    'hours_since_update': hours_since,
                    'source': 'stl_insert',
                }
            
            return {'last_updated': None, 'error': 'No timestamp column found'}
        
        query = f"""
            SELECT 
                MAX("{timestamp_column}") as last_updated,
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
        """Sample data."""
        parts = table.split('.')
        schema = parts[0] if len(parts) > 1 else 'public'
        table_name = parts[-1]
        full_table = f'"{schema}"."{table_name}"'
        
        col_list = ', '.join(f'"{c}"' for c in columns) if columns else '*'
        
        # Use random() for sampling
        query = f"""
            SELECT {col_list}
            FROM {full_table}
            ORDER BY RANDOM()
            LIMIT {n}
        """
        
        return self.execute_query(query)
    
    def get_query_history(self,
                          start_time: Optional[datetime] = None,
                          end_time: Optional[datetime] = None,
                          limit: int = 1000) -> List[QueryHistoryEntry]:
        """Get query history from SVL_QUERY_SUMMARY."""
        time_filter = ""
        if start_time:
            time_filter = f"AND starttime >= '{start_time.isoformat()}'"
        
        query = f"""
            SELECT 
                query,
                starttime,
                endtime,
                elapsed / 1000 as execution_time_ms,
                rows as rows_produced,
                bytes_scanned,
                LISTAGG(querytxt, ' ') WITHIN GROUP (ORDER BY sequence) as query_text
            FROM stl_query q
            JOIN stl_querytext qt ON q.query = qt.query
            WHERE userid > 1
              {time_filter}
            GROUP BY query, starttime, endtime, elapsed, rows, bytes_scanned
            ORDER BY starttime DESC
            LIMIT {limit}
        """
        
        try:
            results = self.execute_query(query)
            
            return [
                QueryHistoryEntry(
                    query_id=str(row.get('query')),
                    query_text=row.get('query_text', '')[:10000],
                    start_time=row.get('starttime'),
                    end_time=row.get('endtime'),
                    execution_time_ms=row.get('execution_time_ms'),
                    rows_produced=row.get('rows_produced'),
                    bytes_scanned=row.get('bytes_scanned'),
                    database=self.config.get('database'),
                )
                for row in results
            ]
            
        except Exception as e:
            logger.warning(f"Could not get query history: {e}")
            return []
    
    # SQL dialect helpers (required abstract methods)
    def quote_identifier(self, identifier: str) -> str:
        """Quote Redshift identifier (validated + escaped)."""
        from .sql_safety import quote_identifier as _q
        return _q(identifier, "redshift")
    
    def get_current_timestamp_sql(self) -> str:
        """Get current timestamp SQL."""
        return "GETDATE()"
    
    def get_interval_sql(self, hours: int) -> str:
        """Get interval subtraction SQL."""
        return f"DATEADD(hour, -{hours}, GETDATE())"
    
    def get_limit_sql(self, n: int) -> str:
        """Get LIMIT clause."""
        return f"LIMIT {n}"
    
    def get_random_sample_sql(self, table: str, n: int) -> str:
        """Get random sample SQL."""
        return f"SELECT * FROM {table} ORDER BY RANDOM() LIMIT {n}"
    
    # Additional helpers
    def get_current_timestamp(self) -> str:
        return "GETDATE()"
    
    def get_interval_hours(self, hours: int) -> str:
        return f"DATEADD(hour, -{hours}, GETDATE())"
    
    def get_date_trunc(self, field: str, column: str) -> str:
        return f"DATE_TRUNC('{field}', {column})"

