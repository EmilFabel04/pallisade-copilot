"""
PostgreSQL Database Adapter - Enterprise Grade

Full-featured adapter for PostgreSQL with support for:
- Deep column statistics using pg_stats
- Query history via pg_stat_statements
- Table size and bloat analysis
- Partition support
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

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


class PostgresAdapter(DatabaseAdapter):
    """
    Enterprise PostgreSQL adapter.
    
    Capabilities:
    - Column statistics from pg_stats
    - Query history from pg_stat_statements (if installed)
    - Table size analysis including indexes
    - TOAST and bloat detection
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.database_type = DatabaseType.POSTGRES
        self.dialect = "postgres"
        
        self._capabilities = AdapterCapabilities(
            supports_sql=True,
            supports_transactions=True,
            supports_column_stats=True,
            supports_histograms=True,  # Via pg_stats
            supports_cardinality=True,
            supports_percentiles=True,
            supports_query_history=True,  # Via pg_stat_statements
            query_history_days=7,
            supports_sampling=True,
            supports_tablesample=True,  # PostgreSQL 9.5+
            supports_information_schema=True,
            supports_schema_changes=True,
            supports_explain=True,
            supports_partitions=True,  # PostgreSQL 10+
            supports_clustering=False,
            supports_table_last_modified=False,  # Not directly available
        )
        
        # Parse config
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 5432)
        self.database = config.get('database')
        self.user = config.get('user')
        self.password = config.get('password')
        self.schema = config.get('schema', 'public')
        self.sslmode = config.get('sslmode', 'prefer')
        
        self._has_pg_stat_statements = False
    
    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================
    
    def connect(self) -> bool:
        """Establish connection to PostgreSQL."""
        try:
            import psycopg2
            import psycopg2.extras
            
            self._connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                sslmode=self.sslmode,
                connect_timeout=30,
            )
            
            # Enable dict cursor
            self._connection.autocommit = True
            
            # Check for pg_stat_statements
            self._check_pg_stat_statements()
            
            logger.info(f"Connected to PostgreSQL: {self.host}:{self.port}/{self.database}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            self._connection = None
            return False
    
    def _check_pg_stat_statements(self):
        """Check if pg_stat_statements extension is available."""
        try:
            result = self.execute_query("""
                SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
            """)
            self._has_pg_stat_statements = len(result) > 0
            if self._has_pg_stat_statements:
                logger.info("pg_stat_statements extension found")
        except:
            self._has_pg_stat_statements = False
    
    def disconnect(self) -> None:
        """Close PostgreSQL connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.info("Disconnected from PostgreSQL")
            except Exception as e:
                logger.warning(f"Error closing PostgreSQL connection: {e}")
            finally:
                self._connection = None
    
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """Test PostgreSQL connection."""
        try:
            if not self.is_connected:
                self.connect()
            
            result = self.execute_query("SELECT version()")
            version = result[0]['version'] if result else 'unknown'
            
            return True, version.split(' ')[0:2]  # e.g., "PostgreSQL 14.5"
            
        except Exception as e:
            return False, str(e)
    
    def _execute_query_impl(self, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Execute query and return results."""
        import psycopg2.extras
        
        cursor = self._connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Check if query returns results
            if cursor.description:
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            return []
            
        finally:
            cursor.close()
    
    # =========================================================================
    # TABLE DISCOVERY
    # =========================================================================
    
    def get_tables(self, 
                   database: Optional[str] = None,
                   schema: Optional[str] = None,
                   include_views: bool = False) -> List[str]:
        """Get list of tables in PostgreSQL."""
        sch = schema or self.schema
        
        type_filter = "IN ('BASE TABLE')" if not include_views else "IN ('BASE TABLE', 'VIEW')"
        
        query = f"""
            SELECT table_schema || '.' || table_name as full_name
            FROM information_schema.tables
            WHERE table_schema = '{sch}'
            AND table_type {type_filter}
            ORDER BY table_name
        """
        
        result = self.execute_query(query)
        return [row['full_name'] for row in result]
    
    def get_table_metadata(self, table: str) -> TableMetadata:
        """Get comprehensive table metadata from PostgreSQL."""
        # Parse table name
        parts = table.split('.')
        if len(parts) == 2:
            schema, tbl = parts
        else:
            schema, tbl = self.schema, parts[0]
        
        # Get basic metadata
        query = f"""
            SELECT 
                t.table_schema,
                t.table_name,
                t.table_type,
                c.reltuples::bigint as estimated_rows,
                pg_total_relation_size(c.oid) as total_bytes,
                pg_size_pretty(pg_total_relation_size(c.oid)) as size_pretty,
                obj_description(c.oid) as comment,
                pg_get_userbyid(c.relowner) as owner
            FROM information_schema.tables t
            JOIN pg_class c ON c.relname = t.table_name
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.table_schema
            WHERE t.table_schema = '{schema}'
            AND t.table_name = '{tbl}'
        """
        
        result = self.execute_query(query)
        
        if not result:
            raise ValueError(f"Table not found: {table}")
        
        row = result[0]
        
        # Get columns
        columns = self.get_columns(table)
        
        # Get primary keys
        pk_columns = self._get_primary_keys(schema, tbl)
        
        # Check if partitioned
        partition_info = self._get_partition_info(schema, tbl)
        
        return TableMetadata(
            full_name=f"{schema}.{tbl}",
            database=self.database,
            schema=schema,
            table_name=tbl,
            row_count=row.get('estimated_rows'),
            size_bytes=row.get('total_bytes'),
            columns=columns,
            primary_key_columns=pk_columns,
            is_partitioned=partition_info.get('is_partitioned', False),
            partition_columns=partition_info.get('columns', []),
            table_type=row['table_type'],
            comment=row.get('comment'),
            owner=row.get('owner'),
        )
    
    def _get_primary_keys(self, schema: str, table: str) -> List[str]:
        """Get primary key columns."""
        query = f"""
            SELECT a.attname as column_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE i.indisprimary
            AND n.nspname = '{schema}'
            AND c.relname = '{table}'
        """
        result = self.execute_query(query)
        return [row['column_name'] for row in result]
    
    def _get_partition_info(self, schema: str, table: str) -> Dict[str, Any]:
        """Get partition information (PostgreSQL 10+)."""
        try:
            query = f"""
                SELECT 
                    pt.relkind = 'p' as is_partitioned,
                    pg_get_partkeydef(pt.oid) as partition_key
                FROM pg_class pt
                JOIN pg_namespace n ON n.oid = pt.relnamespace
                WHERE n.nspname = '{schema}'
                AND pt.relname = '{table}'
            """
            result = self.execute_query(query)
            if result:
                row = result[0]
                columns = []
                if row.get('partition_key'):
                    # Parse partition key like "RANGE (date)"
                    import re
                    match = re.search(r'\((.*?)\)', row['partition_key'])
                    if match:
                        columns = [c.strip() for c in match.group(1).split(',')]
                return {
                    'is_partitioned': row.get('is_partitioned', False),
                    'columns': columns
                }
        except:
            pass
        return {'is_partitioned': False, 'columns': []}
    
    def get_columns(self, table: str) -> List[ColumnMetadata]:
        """Get detailed column information."""
        parts = table.split('.')
        if len(parts) == 2:
            schema, tbl = parts
        else:
            schema, tbl = self.schema, parts[0]
        
        query = f"""
            SELECT 
                column_name,
                data_type,
                is_nullable,
                column_default,
                ordinal_position,
                character_maximum_length,
                numeric_precision,
                numeric_scale,
                col_description('{schema}.{tbl}'::regclass, ordinal_position) as comment
            FROM information_schema.columns
            WHERE table_schema = '{schema}'
            AND table_name = '{tbl}'
            ORDER BY ordinal_position
        """
        
        result = self.execute_query(query)
        
        return [
            ColumnMetadata(
                name=row['column_name'],
                data_type=row['data_type'],
                is_nullable=row['is_nullable'] == 'YES',
                default_value=row.get('column_default'),
                ordinal_position=row['ordinal_position'],
                character_max_length=row.get('character_maximum_length'),
                numeric_precision=row.get('numeric_precision'),
                numeric_scale=row.get('numeric_scale'),
                comment=row.get('comment'),
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
        """Get column statistics using pg_stats and queries."""
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
        parts = table.split('.')
        if len(parts) == 2:
            schema, tbl = parts
        else:
            schema, tbl = self.schema, parts[0]
        
        col_name = f'"{col.name}"'
        
        # Use TABLESAMPLE for large tables
        sample_clause = ""
        if sample_size:
            # Estimate percentage
            total_rows = self._get_estimated_rows(schema, tbl)
            if total_rows and total_rows > sample_size:
                pct = min((sample_size / total_rows) * 100, 100)
                sample_clause = f"TABLESAMPLE SYSTEM ({pct})"
        
        # Check data type
        is_numeric = col.data_type in (
            'integer', 'bigint', 'smallint', 'decimal', 'numeric',
            'real', 'double precision', 'float', 'money'
        )
        is_timestamp = col.data_type in (
            'timestamp', 'timestamp with time zone', 'timestamp without time zone',
            'date', 'time', 'time with time zone'
        )
        is_string = col.data_type in (
            'character varying', 'varchar', 'character', 'char', 'text'
        )
        
        # Base stats
        base_query = f"""
            SELECT 
                COUNT(*) as total_count,
                COUNT({col_name}) as non_null_count,
                COUNT(*) - COUNT({col_name}) as null_count,
                COUNT(DISTINCT {col_name}) as distinct_count
            FROM {table} {sample_clause}
        """
        
        base_result = self.execute_query(base_query)
        base = base_result[0] if base_result else {}
        
        total = base.get('total_count', 0)
        null_count = base.get('null_count', 0)
        distinct = base.get('distinct_count', 0)
        
        stats = ColumnStats(
            column_name=col.name,
            data_type=col.data_type,
            total_count=total,
            null_count=null_count,
            distinct_count=distinct,
            null_rate=null_count / total if total > 0 else 0,
            distinct_rate=distinct / total if total > 0 else 0,
        )
        
        # Try to get from pg_stats first (much faster)
        pg_stats = self._get_pg_stats(schema, tbl, col.name)
        if pg_stats:
            stats.null_rate = pg_stats.get('null_frac', stats.null_rate)
            stats.distinct_count = abs(int(pg_stats.get('n_distinct', 0) * total)) if pg_stats.get('n_distinct', 0) < 0 else pg_stats.get('n_distinct', 0)
            # pg_stats has histogram bounds
            if pg_stats.get('histogram_bounds'):
                stats.histogram = [{'bound': b} for b in pg_stats['histogram_bounds']]
            if pg_stats.get('most_common_vals'):
                mcv = pg_stats['most_common_vals']
                mcf = pg_stats.get('most_common_freqs', [])
                stats.top_values = [
                    {'value': str(v), 'frequency': f} 
                    for v, f in zip(mcv, mcf)
                ]
        
        # Numeric stats
        if is_numeric:
            try:
                numeric_query = f"""
                    SELECT 
                        MIN({col_name}) as min_val,
                        MAX({col_name}) as max_val,
                        AVG({col_name}::numeric) as avg_val,
                        SUM({col_name}::numeric) as sum_val,
                        STDDEV({col_name}::numeric) as std_dev,
                        VARIANCE({col_name}::numeric) as variance,
                        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col_name}) as p25,
                        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {col_name}) as p50,
                        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col_name}) as p75,
                        PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY {col_name}) as p90,
                        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY {col_name}) as p99
                    FROM {table} {sample_clause}
                """
                numeric_result = self.execute_query(numeric_query)
                if numeric_result:
                    n = numeric_result[0]
                    stats.min_value = n.get('min_val')
                    stats.max_value = n.get('max_val')
                    stats.avg_value = float(n['avg_val']) if n.get('avg_val') else None
                    stats.sum_value = float(n['sum_val']) if n.get('sum_val') else None
                    stats.std_dev = float(n['std_dev']) if n.get('std_dev') else None
                    stats.variance = float(n['variance']) if n.get('variance') else None
                    stats.percentile_25 = float(n['p25']) if n.get('p25') else None
                    stats.percentile_50 = float(n['p50']) if n.get('p50') else None
                    stats.percentile_75 = float(n['p75']) if n.get('p75') else None
                    stats.percentile_90 = float(n['p90']) if n.get('p90') else None
                    stats.percentile_99 = float(n['p99']) if n.get('p99') else None
            except Exception as e:
                logger.warning(f"Error getting numeric stats for {col.name}: {e}")
        
        # Timestamp stats
        if is_timestamp:
            try:
                ts_query = f"""
                    SELECT 
                        MIN({col_name}) as min_ts,
                        MAX({col_name}) as max_ts
                    FROM {table} {sample_clause}
                """
                ts_result = self.execute_query(ts_query)
                if ts_result:
                    t = ts_result[0]
                    stats.min_timestamp = t.get('min_ts')
                    stats.max_timestamp = t.get('max_ts')
            except Exception as e:
                logger.warning(f"Error getting timestamp stats for {col.name}: {e}")
        
        # String stats
        if is_string:
            try:
                string_query = f"""
                    SELECT 
                        MIN(LENGTH({col_name})) as min_len,
                        MAX(LENGTH({col_name})) as max_len,
                        AVG(LENGTH({col_name})) as avg_len,
                        SUM(CASE WHEN {col_name} = '' THEN 1 ELSE 0 END) as empty_count,
                        SUM(CASE WHEN TRIM({col_name}) = '' AND {col_name} != '' THEN 1 ELSE 0 END) as whitespace_count
                    FROM {table} {sample_clause}
                """
                string_result = self.execute_query(string_query)
                if string_result:
                    s = string_result[0]
                    stats.min_length = s.get('min_len')
                    stats.max_length = s.get('max_len')
                    stats.avg_length = float(s['avg_len']) if s.get('avg_len') else None
                    stats.empty_string_count = s.get('empty_count', 0)
                    stats.whitespace_only_count = s.get('whitespace_count', 0)
            except Exception as e:
                logger.warning(f"Error getting string stats for {col.name}: {e}")
        
        return stats
    
    def _get_pg_stats(self, schema: str, table: str, column: str) -> Optional[Dict[str, Any]]:
        """Get statistics from pg_stats catalog."""
        try:
            query = f"""
                SELECT 
                    null_frac,
                    n_distinct,
                    most_common_vals::text as most_common_vals,
                    most_common_freqs,
                    histogram_bounds::text as histogram_bounds
                FROM pg_stats
                WHERE schemaname = '{schema}'
                AND tablename = '{table}'
                AND attname = '{column}'
            """
            result = self.execute_query(query)
            if result:
                row = result[0]
                # Parse array strings
                if row.get('most_common_vals'):
                    # Format: {val1,val2,val3}
                    vals = row['most_common_vals'].strip('{}').split(',')
                    row['most_common_vals'] = [v.strip('"') for v in vals]
                if row.get('histogram_bounds'):
                    bounds = row['histogram_bounds'].strip('{}').split(',')
                    row['histogram_bounds'] = [b.strip('"') for b in bounds]
                return row
        except:
            pass
        return None
    
    def _get_estimated_rows(self, schema: str, table: str) -> Optional[int]:
        """Get estimated row count from pg_class."""
        try:
            query = f"""
                SELECT reltuples::bigint as estimate
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = '{schema}' AND c.relname = '{table}'
            """
            result = self.execute_query(query)
            return result[0]['estimate'] if result else None
        except:
            return None
    
    # =========================================================================
    # FRESHNESS
    # =========================================================================
    
    def get_table_freshness(self, 
                            table: str, 
                            timestamp_column: Optional[str] = None) -> Dict[str, Any]:
        """Get freshness information for a PostgreSQL table."""
        ts_col = timestamp_column or self.detect_timestamp_column(table)
        
        if not ts_col:
            return {
                'error': 'No timestamp column found',
                'timestamp_column': None
            }
        
        query = f"""
            SELECT 
                MAX("{ts_col}") as last_update,
                COUNT(*) as row_count,
                EXTRACT(EPOCH FROM (NOW() - MAX("{ts_col}"))) / 3600 as hours_ago
            FROM {table}
        """
        
        result = self.execute_query(query)
        
        if result:
            row = result[0]
            return {
                'last_updated': row.get('last_update'),
                'hours_since_update': row.get('hours_ago', 0),
                'row_count': row.get('row_count', 0),
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
        """Get random sample using TABLESAMPLE (PostgreSQL 9.5+)."""
        cols = ', '.join(f'"{c}"' for c in columns) if columns else '*'
        
        # Estimate percentage for TABLESAMPLE
        parts = table.split('.')
        if len(parts) == 2:
            schema, tbl = parts
        else:
            schema, tbl = self.schema, parts[0]
        
        total_rows = self._get_estimated_rows(schema, tbl)
        
        if total_rows and total_rows > n:
            # Use TABLESAMPLE with percentage
            pct = min((n / total_rows) * 100 * 1.5, 100)  # Add buffer
            query = f"""
                SELECT {cols}
                FROM {table} TABLESAMPLE BERNOULLI ({pct})
                LIMIT {n}
            """
        else:
            # Table is small, just limit
            query = f"""
                SELECT {cols}
                FROM {table}
                ORDER BY RANDOM()
                LIMIT {n}
            """
        
        return self.execute_query(query)
    
    # =========================================================================
    # QUERY HISTORY
    # =========================================================================
    
    def _get_query_history_impl(self, 
                                hours: int,
                                user: Optional[str],
                                database: Optional[str]) -> List[QueryHistoryEntry]:
        """Get query history from pg_stat_statements."""
        if not self._has_pg_stat_statements:
            logger.warning("pg_stat_statements extension not available")
            return []
        
        where_clauses = []
        if user:
            where_clauses.append(f"u.usename = '{user}'")
        if database:
            where_clauses.append(f"d.datname = '{database}'")
        
        where = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        query = f"""
            SELECT 
                s.queryid::text as query_id,
                s.query as query_text,
                NOW() as start_time,  -- pg_stat_statements doesn't have timestamps
                s.total_exec_time as duration_ms,
                s.rows as rows_produced,
                u.usename as user_name,
                d.datname as database_name
            FROM pg_stat_statements s
            JOIN pg_user u ON s.userid = u.usesysid
            JOIN pg_database d ON s.dbid = d.oid
            WHERE {where}
            AND s.query NOT LIKE 'COPY%'
            AND s.query NOT LIKE 'COMMIT%'
            ORDER BY s.total_exec_time DESC
            LIMIT 1000
        """
        
        try:
            results = self.execute_query(query)
            
            return [
                QueryHistoryEntry(
                    query_id=row['query_id'],
                    query_text=row['query_text'],
                    start_time=row['start_time'],
                    duration_ms=int(row.get('duration_ms', 0)),
                    rows_produced=row.get('rows_produced'),
                    user_name=row.get('user_name'),
                    database=row.get('database_name'),
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
        """Quote PostgreSQL identifier (validated + escaped)."""
        from .sql_safety import quote_identifier as _q
        return _q(identifier, "postgres")
    
    def get_current_timestamp_sql(self) -> str:
        """PostgreSQL current timestamp."""
        return "NOW()"
    
    def get_interval_sql(self, hours: int) -> str:
        """PostgreSQL interval subtraction."""
        return f"NOW() - INTERVAL '{hours} hours'"
    
    def get_limit_sql(self, n: int) -> str:
        """PostgreSQL LIMIT clause."""
        return f"LIMIT {n}"
    
    def get_random_sample_sql(self, table: str, n: int) -> str:
        """PostgreSQL random sample."""
        return f"SELECT * FROM {table} ORDER BY RANDOM() LIMIT {n}"

