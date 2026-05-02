"""
BigQuery Database Adapter - Enterprise Grade

Full-featured adapter for Google BigQuery with support for:
- Deep column statistics using INFORMATION_SCHEMA
- Query history from JOBS_BY_PROJECT
- Partitioning and clustering information
- Cost estimation
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


# BigQuery __TABLES__.type encoding:
#   1 = regular table, 2 = view, 4 = external, 5 = materialized view
_BQ_TABLE_TYPE_LABELS = {1: "TABLE", 2: "VIEW", 4: "EXTERNAL", 5: "MATERIALIZED_VIEW"}


def _bq_table_type_label(type_code: Any) -> str:
    try:
        return _BQ_TABLE_TYPE_LABELS.get(int(type_code), "UNKNOWN")
    except (TypeError, ValueError):
        return "UNKNOWN"


class BigQueryAdapter(DatabaseAdapter):
    """
    Enterprise BigQuery adapter.
    
    Capabilities:
    - Column statistics from INFORMATION_SCHEMA
    - Query history from JOBS_BY_PROJECT
    - Partitioning and clustering info
    - Cost tracking via bytes_billed
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.database_type = DatabaseType.BIGQUERY
        self.dialect = "bigquery"
        
        self._capabilities = AdapterCapabilities(
            supports_sql=True,
            supports_transactions=False,  # BigQuery is append-only
            supports_column_stats=True,
            supports_histograms=False,  # Limited histogram support
            supports_cardinality=True,
            supports_percentiles=True,  # APPROX_QUANTILES
            supports_query_history=True,
            query_history_days=180,  # 6 months in INFORMATION_SCHEMA
            supports_sampling=True,
            supports_tablesample=True,  # TABLESAMPLE SYSTEM
            supports_information_schema=True,
            supports_schema_changes=True,
            supports_explain=True,  # EXPLAIN / dry run
            supports_partitions=True,
            supports_clustering=True,
            supports_table_last_modified=True,
        )
        
        # Parse config - handle both naming conventions
        self.project = config.get('project') or config.get('project_id')
        self.dataset = config.get('dataset')
        # Handle datasets array from pipeline config
        datasets = config.get('datasets', [])
        if datasets and not self.dataset:
            self.dataset = datasets[0] if isinstance(datasets, list) else datasets
        self.location = config.get('location', 'US')
        # Handle both credentials and credentials_json
        self.credentials_json = config.get('credentials_json') or config.get('credentials')
        
        self._client = None
    
    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================
    
    def connect(self) -> bool:
        """Establish connection to BigQuery."""
        try:
            import json
            from google.cloud import bigquery
            from google.oauth2 import service_account
            
            logger.info(f"Connecting to BigQuery project: {self.project}, location: {self.location}")
            
            if self.credentials_json:
                # Parse credentials if it's a string
                creds = self.credentials_json
                if isinstance(creds, str):
                    try:
                        creds = json.loads(creds)
                    except json.JSONDecodeError:
                        logger.warning("Could not parse credentials as JSON, using as-is")
                
                # Use service account
                credentials = service_account.Credentials.from_service_account_info(creds)
                self._client = bigquery.Client(
                    project=self.project,
                    credentials=credentials,
                    location=self.location,
                )
            else:
                # Use default credentials (e.g., from environment)
                logger.info("No credentials provided, using default credentials")
                self._client = bigquery.Client(
                    project=self.project,
                    location=self.location,
                )
            
            self._connection = self._client  # For compatibility
            
            logger.info(f"Connected to BigQuery: {self.project}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to BigQuery: {e}")
            self._client = None
            self._connection = None
            return False
    
    def disconnect(self) -> None:
        """Close BigQuery client."""
        if self._client:
            try:
                self._client.close()
                logger.info("Disconnected from BigQuery")
            except Exception as e:
                logger.warning(f"Error closing BigQuery client: {e}")
            finally:
                self._client = None
                self._connection = None
    
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """Test BigQuery connection."""
        try:
            if not self._client:
                self.connect()
            
            # Simple query to test connection
            result = list(self._client.query("SELECT 1 as test").result())
            
            return True, f"BigQuery ({self.project})"
            
        except Exception as e:
            return False, str(e)
    
    def _execute_query_impl(self, query: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Execute query and return results."""
        if params:
            # BigQuery uses @param syntax for named parameters
            from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter
            
            job_config = QueryJobConfig()
            job_config.query_parameters = [
                ScalarQueryParameter(k, "STRING", str(v)) 
                for k, v in params.items()
            ]
            result = self._client.query(query, job_config=job_config).result()
        else:
            result = self._client.query(query).result()
        
        return [dict(row) for row in result]
    
    # =========================================================================
    # TABLE DISCOVERY
    # =========================================================================
    
    def get_tables(self, 
                   database: Optional[str] = None,
                   schema: Optional[str] = None,
                   include_views: bool = False) -> List[str]:
        """Get list of tables in BigQuery."""
        dataset = schema or self.dataset
        
        type_filter = "table_type = 'BASE TABLE'" if not include_views else "table_type IN ('BASE TABLE', 'VIEW')"
        
        query = f"""
            SELECT 
                table_catalog || '.' || table_schema || '.' || table_name as full_name
            FROM `{self.project}.{dataset}.INFORMATION_SCHEMA.TABLES`
            WHERE {type_filter}
            ORDER BY table_name
        """
        
        result = self.execute_query(query)
        return [row['full_name'] for row in result]
    
    def get_table_metadata(self, table: str) -> TableMetadata:
        """Get comprehensive table metadata from BigQuery."""
        # Parse table name
        parts = table.replace('`', '').split('.')
        if len(parts) == 3:
            project, dataset, tbl = parts
        elif len(parts) == 2:
            project, dataset, tbl = self.project, parts[0], parts[1]
        else:
            project, dataset, tbl = self.project, self.dataset, parts[0]
        
        # Get basic metadata
        query = f"""
            SELECT 
                t.table_catalog as project,
                t.table_schema as dataset,
                t.table_name,
                t.table_type,
                t.creation_time,
                ts.row_count,
                ts.size_bytes,
                ts.last_modified_time,
                ARRAY_TO_STRING(t.ddl_target_table.partition_column_names, ', ') as partition_columns,
                ARRAY_TO_STRING(t.ddl_target_table.clustering_columns, ', ') as clustering_columns
            FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES` t
            LEFT JOIN `{project}.{dataset}.__TABLES__` ts 
                ON ts.table_id = t.table_name
            WHERE t.table_name = '{tbl}'
        """
        
        try:
            result = self.execute_query(query)
        except:
            # Fallback without DDL info
            query = f"""
                SELECT 
                    table_id as table_name,
                    'BASE TABLE' as table_type,
                    creation_time,
                    row_count,
                    size_bytes,
                    last_modified_time
                FROM `{project}.{dataset}.__TABLES__`
                WHERE table_id = '{tbl}'
            """
            result = self.execute_query(query)
        
        if not result:
            raise ValueError(f"Table not found: {table}")
        
        row = result[0]
        
        # Get columns
        columns = self.get_columns(table)
        
        # Parse partition/clustering columns
        partition_cols = []
        clustering_cols = []
        if row.get('partition_columns'):
            partition_cols = [c.strip() for c in row['partition_columns'].split(',')]
        if row.get('clustering_columns'):
            clustering_cols = [c.strip() for c in row['clustering_columns'].split(',')]
        
        return TableMetadata(
            full_name=f"{project}.{dataset}.{tbl}",
            database=project,
            schema=dataset,
            table_name=tbl,
            row_count=row.get('row_count'),
            size_bytes=row.get('size_bytes'),
            created_at=row.get('creation_time'),
            last_modified=row.get('last_modified_time'),
            columns=columns,
            is_partitioned=len(partition_cols) > 0,
            partition_columns=partition_cols,
            clustering_columns=clustering_cols,
            table_type=row.get('table_type', 'BASE TABLE'),
        )
    
    def get_columns(self, table: str) -> List[ColumnMetadata]:
        """Get detailed column information."""
        parts = table.replace('`', '').split('.')
        if len(parts) == 3:
            project, dataset, tbl = parts
        elif len(parts) == 2:
            project, dataset, tbl = self.project, parts[0], parts[1]
        else:
            project, dataset, tbl = self.project, self.dataset, parts[0]
        
        query = f"""
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.ordinal_position,
                cfp.description
            FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS` c
            LEFT JOIN `{project}.{dataset}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` cfp
                ON c.table_name = cfp.table_name
                AND c.column_name = cfp.column_name
                AND cfp.field_path = cfp.column_name
            WHERE c.table_name = '{tbl}'
            ORDER BY c.ordinal_position
        """

        try:
            result = self.execute_query(query)
        except Exception:
            # Fallback: skip descriptions if COLUMN_FIELD_PATHS not available
            query = f"""
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    ordinal_position
                FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
                WHERE table_name = '{tbl}'
                ORDER BY ordinal_position
            """
            result = self.execute_query(query)

        return [
            ColumnMetadata(
                name=row['column_name'],
                data_type=row['data_type'],
                is_nullable=row['is_nullable'] == 'YES',
                ordinal_position=row['ordinal_position'],
                comment=row.get('description'),
            )
            for row in result
        ]
    
    def get_table_schema(self, fqn: str) -> List[Dict[str, Any]]:
        """Return column metadata for *fqn* as a list of plain dicts.

        Each dict contains ``column_name``, ``data_type``, and ``is_nullable``
        (bool). This is the canonical interface used by :class:`WarehouseDiscoverer`.
        """
        cols = self.get_columns(fqn)
        return [
            {"column_name": c.name, "data_type": c.data_type, "is_nullable": c.is_nullable}
            for c in cols
        ]

    # =========================================================================
    # COLUMN STATISTICS
    # =========================================================================

    def get_column_stats(self,
                         table: str,
                         columns: Optional[List[str]] = None,
                         sample_size: Optional[int] = None) -> List[ColumnStats]:
        """Get column statistics from BigQuery."""
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
        col_name = f"`{col.name}`"
        sample_clause = f"TABLESAMPLE SYSTEM ({min(sample_size / 1000, 100)} PERCENT)" if sample_size else ""
        
        # Check data type
        is_numeric = col.data_type.upper() in (
            'INT64', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC', 'INTEGER', 'FLOAT'
        )
        is_timestamp = col.data_type.upper() in ('TIMESTAMP', 'DATE', 'DATETIME', 'TIME')
        is_string = col.data_type.upper() in ('STRING', 'BYTES')
        
        # Base stats
        base_query = f"""
            SELECT 
                COUNT(*) as total_count,
                COUNTIF({col_name} IS NOT NULL) as non_null_count,
                COUNTIF({col_name} IS NULL) as null_count,
                APPROX_COUNT_DISTINCT({col_name}) as distinct_count
            FROM `{table}` {sample_clause}
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
        
        # Numeric stats
        if is_numeric:
            try:
                numeric_query = f"""
                    SELECT 
                        MIN({col_name}) as min_val,
                        MAX({col_name}) as max_val,
                        AVG({col_name}) as avg_val,
                        SUM({col_name}) as sum_val,
                        STDDEV({col_name}) as std_dev,
                        VARIANCE({col_name}) as variance
                    FROM `{table}` {sample_clause}
                """
                numeric_result = self.execute_query(numeric_query)
                if numeric_result:
                    n = numeric_result[0]
                    stats.min_value = n.get('min_val')
                    stats.max_value = n.get('max_val')
                    stats.avg_value = n.get('avg_val')
                    stats.sum_value = n.get('sum_val')
                    stats.std_dev = n.get('std_dev')
                    stats.variance = n.get('variance')
                
                # Percentiles using APPROX_QUANTILES
                pct_query = f"""
                    SELECT 
                        APPROX_QUANTILES({col_name}, 100)[OFFSET(25)] as p25,
                        APPROX_QUANTILES({col_name}, 100)[OFFSET(50)] as p50,
                        APPROX_QUANTILES({col_name}, 100)[OFFSET(75)] as p75,
                        APPROX_QUANTILES({col_name}, 100)[OFFSET(90)] as p90,
                        APPROX_QUANTILES({col_name}, 100)[OFFSET(99)] as p99
                    FROM `{table}` {sample_clause}
                """
                pct_result = self.execute_query(pct_query)
                if pct_result:
                    p = pct_result[0]
                    stats.percentile_25 = p.get('p25')
                    stats.percentile_50 = p.get('p50')
                    stats.percentile_75 = p.get('p75')
                    stats.percentile_90 = p.get('p90')
                    stats.percentile_99 = p.get('p99')
                    
            except Exception as e:
                logger.warning(f"Error getting numeric stats for {col.name}: {e}")
        
        # Timestamp stats
        if is_timestamp:
            try:
                ts_query = f"""
                    SELECT 
                        MIN({col_name}) as min_ts,
                        MAX({col_name}) as max_ts
                    FROM `{table}` {sample_clause}
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
                        COUNTIF({col_name} = '') as empty_count,
                        COUNTIF(TRIM({col_name}) = '' AND {col_name} != '') as whitespace_count
                    FROM `{table}` {sample_clause}
                """
                string_result = self.execute_query(string_query)
                if string_result:
                    s = string_result[0]
                    stats.min_length = s.get('min_len')
                    stats.max_length = s.get('max_len')
                    stats.avg_length = s.get('avg_len')
                    stats.empty_string_count = s.get('empty_count', 0)
                    stats.whitespace_only_count = s.get('whitespace_count', 0)
            except Exception as e:
                logger.warning(f"Error getting string stats for {col.name}: {e}")
        
        # Top values
        try:
            top_query = f"""
                SELECT {col_name} as value, COUNT(*) as cnt
                FROM `{table}` {sample_clause}
                WHERE {col_name} IS NOT NULL
                GROUP BY {col_name}
                ORDER BY cnt DESC
                LIMIT 10
            """
            top_result = self.execute_query(top_query)
            stats.top_values = [
                {'value': str(r['value']), 'count': r['cnt']} 
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
        """Get freshness information for a BigQuery table.

        Uses __TABLES__ metadata for row_count (instant, no scan).
        If a timestamp column exists, queries MAX(ts_col) for freshness.
        """
        parts = table.replace('`', '').split('.')
        if len(parts) == 3:
            project, dataset, tbl = parts
        elif len(parts) == 2:
            project, dataset, tbl = self.project, parts[0], parts[1]
        else:
            project, dataset, tbl = self.project, self.dataset, parts[0]

        # Step 1: Always get row_count + last_modified from __TABLES__ (free, no scan)
        row_count = 0
        meta_hours_ago = None
        meta_last_modified = None
        try:
            meta_query = f"""
                SELECT last_modified_time, row_count,
                       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP_MILLIS(last_modified_time), HOUR) as hours_ago
                FROM `{project}.{dataset}.__TABLES__`
                WHERE table_id = '{tbl}'
            """
            meta_result = self.execute_query(meta_query)
            if meta_result:
                row = meta_result[0]
                row_count = row.get('row_count', 0)
                meta_hours_ago = row.get('hours_ago', 0)
                meta_last_modified = row.get('last_modified_time')
        except Exception:
            pass

        # Step 2: Try to get precise freshness from a timestamp column
        ts_col = timestamp_column or self.detect_timestamp_column(table)

        if ts_col:
            try:
                ts_query = f"""
                    SELECT MAX(`{ts_col}`) as last_update,
                           TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), CAST(MAX(`{ts_col}`) AS TIMESTAMP), HOUR) as hours_ago
                    FROM `{project}.{dataset}.{tbl}`
                """
                ts_result = self.execute_query(ts_query)
                if ts_result and ts_result[0].get('last_update') is not None:
                    row = ts_result[0]
                    return {
                        'last_updated': row.get('last_update'),
                        'hours_since_update': row.get('hours_ago', 0),
                        'row_count': row_count,
                        'timestamp_column': ts_col,
                        'source': 'column'
                    }
            except Exception:
                pass  # Fall through to metadata

        # Step 3: Fall back to __TABLES__ metadata
        if meta_hours_ago is not None:
            return {
                'last_updated': meta_last_modified,
                'hours_since_update': meta_hours_ago,
                'row_count': row_count,
                'timestamp_column': '_METADATA',
                'source': 'table_metadata'
            }

        return {
            'error': 'No freshness data available',
            'timestamp_column': None
        }
        
        return {'error': 'Failed to get freshness', 'timestamp_column': ts_col}

    # =========================================================================
    # FAST STATS (BigQuery-optimized)
    # =========================================================================

    def get_table_stats(self, table: str) -> Dict[str, Any]:
        """BigQuery override: __TABLES__ gives row_count + last_modified in one query.

        The base implementation fires three separate metadata queries (get_table_metadata,
        get_table_freshness, get_row_count). On BigQuery these each do extra work we don't
        need — INFORMATION_SCHEMA scans, DDL lookups, etc. One __TABLES__ query has
        everything except columns, which we fetch once via get_columns.
        """
        try:
            project, dataset, tbl = self._parse_table_parts(table)
        except Exception as e:
            logger.warning(f"get_table_stats({table}) parse failed: {e}")
            return super().get_table_stats(table)

        query = f"""
            SELECT
                table_id,
                type,
                row_count,
                size_bytes,
                TIMESTAMP_MILLIS(last_modified_time) AS last_modified,
                TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP_MILLIS(last_modified_time), HOUR) AS hours_since_update
            FROM `{project}.{dataset}.__TABLES__`
            WHERE table_id = '{tbl}'
        """

        try:
            rows = self.execute_query(query)
        except Exception as e:
            logger.warning(f"get_table_stats({table}) __TABLES__ query failed: {e}")
            return super().get_table_stats(table)

        if not rows:
            return {
                "table_name": table,
                "row_count": None,
                "freshness": None,
                "columns": [],
                "last_modified": None,
            }

        row = rows[0]
        last_modified = row.get("last_modified")
        row_count = row.get("row_count")
        table_type = _bq_table_type_label(row.get("type"))

        # __TABLES__ reports row_count=0 for views and external tables because
        # nothing is materialized. Run a COUNT(*) to get the real number.
        if table_type in ("VIEW", "EXTERNAL"):
            try:
                count_rows = self.execute_query(
                    f"SELECT COUNT(*) AS row_count FROM `{project}.{dataset}.{tbl}`"
                )
                if count_rows:
                    row_count = count_rows[0].get("row_count")
            except Exception as e:
                logger.warning(f"get_table_stats({table}) COUNT(*) for {table_type} failed: {e}")
                row_count = None

        try:
            columns = [
                {"name": c.name, "data_type": c.data_type, "is_nullable": c.is_nullable}
                for c in self.get_columns(table)
            ]
        except Exception as e:
            logger.warning(f"get_table_stats({table}) columns fetch failed: {e}")
            columns = []

        freshness = {
            "last_updated": last_modified,
            "hours_since_update": row.get("hours_since_update"),
            "row_count": row_count,
            "timestamp_column": "_METADATA",
            "source": "table_metadata",
        } if last_modified is not None else None

        return {
            "table_name": table,
            "table_type": table_type,
            "row_count": row_count,
            "size_bytes": row.get("size_bytes"),
            "freshness": freshness,
            "columns": columns,
            "last_modified": last_modified,
        }

    def get_table_stats_batch(self, tables: List[str]) -> List[Dict[str, Any]]:
        """Fetch stats for many tables in a single BigQuery metadata query.

        Groups tables by (project, dataset) and UNIONs the __TABLES__ lookups.
        Columns are omitted to keep the payload small — callers can fetch
        columns per-table with get_table_stats when needed.
        """
        if not tables:
            return []

        # Group by (project, dataset) so we can query each dataset's __TABLES__ once
        by_dataset: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        originals: Dict[Tuple[str, str, str], str] = {}
        for table in tables:
            try:
                project, dataset, tbl = self._parse_table_parts(table)
            except Exception as e:
                logger.warning(f"get_table_stats_batch: skipping unparseable table {table}: {e}")
                continue
            by_dataset.setdefault((project, dataset), []).append((tbl, table))
            originals[(project, dataset, tbl)] = table

        if not by_dataset:
            return []

        subqueries = []
        for (project, dataset), table_pairs in by_dataset.items():
            # Escape single quotes defensively even though table ids don't contain them
            ids = ", ".join("'" + t.replace("'", "\\'") + "'" for t, _ in table_pairs)
            subqueries.append(
                f"""
                SELECT
                    '{project}' AS project,
                    '{dataset}' AS dataset,
                    table_id,
                    type,
                    row_count,
                    size_bytes,
                    TIMESTAMP_MILLIS(last_modified_time) AS last_modified,
                    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP_MILLIS(last_modified_time), HOUR) AS hours_since_update
                FROM `{project}.{dataset}.__TABLES__`
                WHERE table_id IN ({ids})
                """.strip()
            )

        query = "\nUNION ALL\n".join(subqueries)

        try:
            rows = self.execute_query(query)
        except Exception as e:
            logger.warning(f"get_table_stats_batch: __TABLES__ union query failed ({e}); falling back to per-table lookups")
            return [self.get_table_stats(t) for t in tables]

        by_fqn: Dict[str, Dict[str, Any]] = {}
        views_to_count: List[str] = []  # FQNs that need a COUNT(*) because __TABLES__ reports 0
        for row in rows:
            key = (row.get("project"), row.get("dataset"), row.get("table_id"))
            original = originals.get(key)
            if not original:
                continue
            last_modified = row.get("last_modified")
            row_count = row.get("row_count")
            table_type = _bq_table_type_label(row.get("type"))
            if table_type in ("VIEW", "EXTERNAL"):
                views_to_count.append(original)
            by_fqn[original] = {
                "table_name": original,
                "table_type": table_type,
                "row_count": row_count,
                "size_bytes": row.get("size_bytes"),
                "last_modified": last_modified,
                "freshness": {
                    "last_updated": last_modified,
                    "hours_since_update": row.get("hours_since_update"),
                    "row_count": row_count,
                    "timestamp_column": "_METADATA",
                    "source": "table_metadata",
                } if last_modified is not None else None,
                "columns": [],  # Omitted in batch mode; call get_table_stats for columns
            }

        # Views/external tables have row_count=0 in __TABLES__ because nothing
        # is materialized. One UNION ALL of COUNT(*) gets real counts for all
        # of them in a single round-trip.
        if views_to_count:
            count_subqueries = [
                f"SELECT '{fqn}' AS fqn, COUNT(*) AS row_count FROM `{fqn}`"
                for fqn in views_to_count
            ]
            try:
                count_rows = self.execute_query("\nUNION ALL\n".join(count_subqueries))
                counts_by_fqn = {r.get("fqn"): r.get("row_count") for r in count_rows}
                for fqn, actual in counts_by_fqn.items():
                    if fqn in by_fqn:
                        by_fqn[fqn]["row_count"] = actual
                        if by_fqn[fqn].get("freshness"):
                            by_fqn[fqn]["freshness"]["row_count"] = actual
            except Exception as e:
                logger.warning(f"get_table_stats_batch: view COUNT(*) union failed ({e}); leaving view row counts as 0")

        # Preserve input order; include a stub for any tables that weren't found
        results: List[Dict[str, Any]] = []
        for t in tables:
            if t in by_fqn:
                results.append(by_fqn[t])
            else:
                results.append({
                    "table_name": t,
                    "row_count": None,
                    "size_bytes": None,
                    "last_modified": None,
                    "freshness": None,
                    "columns": [],
                    "note": "Table not found in __TABLES__",
                })
        return results

    # =========================================================================
    # DATA SAMPLING
    # =========================================================================
    
    def sample_data(self, 
                    table: str, 
                    n: int = 1000,
                    columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get random sample from BigQuery."""
        cols = ', '.join(f'`{c}`' for c in columns) if columns else '*'
        
        # Use RAND() for random sampling
        query = f"""
            SELECT {cols}
            FROM `{table}`
            WHERE RAND() < {n * 2} / (SELECT COUNT(*) FROM `{table}`)
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
        """Get query history from BigQuery INFORMATION_SCHEMA."""
        where_clauses = [
            f"creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)",
            "job_type = 'QUERY'"
        ]
        
        if user:
            where_clauses.append(f"user_email = '{user}'")
        
        where = " AND ".join(where_clauses)
        
        # Use region-specific view
        query = f"""
            SELECT 
                job_id as query_id,
                query as query_text,
                creation_time as start_time,
                end_time,
                TIMESTAMP_DIFF(end_time, creation_time, MILLISECOND) as duration_ms,
                state as status,
                error_result.message as error_message,
                total_bytes_billed,
                user_email as user_name
            FROM `{self.project}.region-{self.location.lower()}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
            WHERE {where}
            AND query IS NOT NULL
            ORDER BY creation_time DESC
            LIMIT 10000
        """
        
        try:
            results = self.execute_query(query)
            
            return [
                QueryHistoryEntry(
                    query_id=row['query_id'],
                    query_text=row['query_text'],
                    start_time=row['start_time'],
                    end_time=row.get('end_time'),
                    duration_ms=row.get('duration_ms'),
                    status='SUCCESS' if row.get('status') == 'DONE' else row.get('status', 'UNKNOWN'),
                    error_message=row.get('error_message'),
                    bytes_scanned=row.get('total_bytes_billed'),
                    user_name=row.get('user_name'),
                )
                for row in results
            ]
        except Exception as e:
            logger.error(f"Error fetching query history: {e}")
            return []
    
    # =========================================================================
    # HISTORICAL QUERIES
    # =========================================================================

    def _parse_table_parts(self, table: str):
        """Parse a table FQN into (project, dataset, table_name)."""
        parts = table.replace("`", "").split(".")
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            return self.project, parts[0], parts[1]
        return self.project, self.dataset, parts[0]

    def get_freshness_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get modification timestamp history. Tries TABLE_STORAGE_TIMELINE first,
        falls back to TABLE_STORAGE, then TABLES metadata."""
        project, dataset, tbl = self._parse_table_parts(table)

        # Try 1: TABLE_STORAGE_TIMELINE (full history)
        try:
            query = f"""
                SELECT DISTINCT DATE(storage_last_modified_time) as mod_date,
                       MAX(storage_last_modified_time) as timestamp
                FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLE_STORAGE_TIMELINE`
                WHERE table_name = '{tbl}'
                  AND storage_last_modified_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                GROUP BY mod_date
                ORDER BY mod_date
            """
            rows = self.execute_query(query)
            if rows:
                return [{"timestamp": row["timestamp"]} for row in rows]
        except Exception:
            pass

        # Try 2: TABLE_STORAGE (current snapshot — single point)
        try:
            query = f"""
                SELECT last_modified_time as timestamp
                FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLE_STORAGE`
                WHERE table_name = '{tbl}'
            """
            rows = self.execute_query(query)
            if rows:
                return [{"timestamp": row["timestamp"]} for row in rows]
        except Exception:
            pass

        # Try 3: TABLES metadata (last modified)
        try:
            query = f"""
                SELECT TIMESTAMP_MILLIS(last_modified_time) as timestamp
                FROM `{project}.{dataset}.__TABLES__`
                WHERE table_id = '{tbl}'
            """
            rows = self.execute_query(query)
            if rows:
                return [{"timestamp": row["timestamp"]} for row in rows]
        except Exception:
            pass

        return []

    def get_row_count_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get row count history. Tries TABLE_STORAGE_TIMELINE first,
        falls back to TABLE_STORAGE, then __TABLES__, then COUNT(*)."""
        project, dataset, tbl = self._parse_table_parts(table)

        # Try 1: TABLE_STORAGE_TIMELINE (full daily history)
        try:
            query = f"""
                SELECT DATE(storage_last_modified_time) as date,
                       MAX(total_rows) as row_count
                FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLE_STORAGE_TIMELINE`
                WHERE table_name = '{tbl}'
                  AND storage_last_modified_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                GROUP BY date
                ORDER BY date
            """
            rows = self.execute_query(query)
            if rows:
                return [{"date": row["date"], "row_count": int(row["row_count"])} for row in rows]
        except Exception:
            pass

        # Try 2: TABLE_STORAGE (current snapshot)
        try:
            query = f"""
                SELECT CURRENT_DATE() as date, total_rows as row_count
                FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLE_STORAGE`
                WHERE table_name = '{tbl}' AND total_rows IS NOT NULL
            """
            rows = self.execute_query(query)
            if rows and rows[0].get("row_count") is not None:
                return [{"date": row["date"], "row_count": int(row["row_count"])} for row in rows]
        except Exception:
            pass

        # Try 3: __TABLES__ metadata
        try:
            query = f"""
                SELECT CURRENT_DATE() as date, row_count
                FROM `{project}.{dataset}.__TABLES__`
                WHERE table_id = '{tbl}'
            """
            rows = self.execute_query(query)
            if rows and rows[0].get("row_count") is not None:
                return [{"date": row["date"], "row_count": int(row["row_count"])} for row in rows]
        except Exception:
            pass

        # Try 4: Direct COUNT(*)
        try:
            query = f"SELECT CURRENT_DATE() as date, COUNT(*) as row_count FROM `{project}.{dataset}.{tbl}`"
            rows = self.execute_query(query)
            if rows:
                return [{"date": row["date"], "row_count": int(row["row_count"])} for row in rows]
        except Exception:
            pass

        return []

    def get_daily_null_rates(self, table: str, timestamp_column: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily null rates across all columns, partitioned by timestamp_column."""
        parts = table.replace("`", "").split(".")
        if len(parts) == 3:
            project, dataset, tbl = parts
        elif len(parts) == 2:
            project, dataset, tbl = self.project, parts[0], parts[1]
        else:
            project, dataset, tbl = self.project, self.dataset, parts[0]

        cols_query = f"""
            SELECT column_name FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = '{tbl}' AND column_name != '{timestamp_column}'
        """
        col_rows = self.execute_query(cols_query)
        columns = [r["column_name"] for r in col_rows]
        if not columns:
            return []

        null_exprs = " + ".join(f"COUNTIF(`{c}` IS NULL)" for c in columns)
        total_expr = f"COUNT(*) * {len(columns)}"

        query = f"""
            SELECT DATE(`{timestamp_column}`) as date,
                   SAFE_DIVIDE({null_exprs}, {total_expr}) as null_rate
            FROM `{project}.{dataset}.{tbl}`
            WHERE `{timestamp_column}` >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            GROUP BY date
            ORDER BY date
        """
        rows = self.execute_query(query)
        return [{"date": row["date"], "null_rate": float(row["null_rate"] or 0)} for row in rows]

    def get_schema_change_history(self, table: str, days: int = 30) -> List[Dict[str, Any]]:
        """BigQuery INFORMATION_SCHEMA doesn't track column-level change history.
        Return empty — discovery will suggest strict/no-evolution (safe default)."""
        return []

    # =========================================================================
    # SQL GENERATION
    # =========================================================================
    
    def quote_identifier(self, identifier: str) -> str:
        """Quote BigQuery identifier (validated + escaped)."""
        from .sql_safety import quote_identifier as _q
        return _q(identifier, "bigquery")
    
    def get_current_timestamp_sql(self) -> str:
        """BigQuery current timestamp."""
        return "CURRENT_TIMESTAMP()"
    
    def get_interval_sql(self, hours: int) -> str:
        """BigQuery interval subtraction."""
        return f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)"
    
    def get_limit_sql(self, n: int) -> str:
        """BigQuery LIMIT clause."""
        return f"LIMIT {n}"
    
    def get_random_sample_sql(self, table: str, n: int) -> str:
        """BigQuery random sample."""
        return f"SELECT * FROM `{table}` ORDER BY RAND() LIMIT {n}"

