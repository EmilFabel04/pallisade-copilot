"""
Databricks Lakehouse / Unity Catalog Database Adapter

Supports Databricks SQL Warehouses and Unity Catalog 3-level namespace.

Features:
- Unity Catalog 3-level namespace: catalog.schema.table
- INFORMATION_SCHEMA for table and column metadata
- DESCRIBE HISTORY for Delta table freshness
- system.access.audit for query history
- TABLESAMPLE for efficient data sampling
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


class DatabricksAdapter(DatabaseAdapter):
    """
    Databricks Lakehouse / Unity Catalog database adapter.

    Supports:
    - Databricks SQL Warehouses (Classic and Serverless)
    - Unity Catalog with 3-level namespace (catalog.schema.table)
    - Delta Lake tables
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Databricks adapter.

        Config options:
            host: Databricks workspace hostname (e.g., adb-xxxx.azuredatabricks.net)
            token: Personal access token or OAuth token
            http_path: SQL warehouse HTTP path (e.g., /sql/1.0/warehouses/xxxx)
            catalog: Unity Catalog name (default 'hive_metastore')
            schema: Default schema name (default 'default')
        """
        super().__init__(config)
        self.database_type = DatabaseType.DATABRICKS
        self.dialect = "databricks"

        self._catalog = self.config.get('catalog', 'hive_metastore')
        self._schema = self.config.get('schema', 'default')

        self._capabilities = AdapterCapabilities(
            supports_sql=True,
            supports_transactions=True,
            supports_column_stats=True,
            supports_histograms=False,
            supports_cardinality=True,
            supports_percentiles=True,
            supports_query_history=True,
            query_history_days=90,
            supports_sampling=True,
            supports_tablesample=True,
            supports_information_schema=True,
            supports_schema_changes=True,
            supports_explain=True,
            supports_partitions=True,
            supports_clustering=True,
            supports_table_last_modified=True,
        )

    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================

    def connect(self) -> bool:
        """Connect to Databricks SQL Warehouse."""
        try:
            from databricks import sql

            self._connection = sql.connect(
                server_hostname=self.config.get('host'),
                http_path=self.config.get('http_path'),
                access_token=self.config.get('token'),
                catalog=self._catalog,
                schema=self._schema,
            )

            logger.info(
                f"Connected to Databricks: {self.config.get('host')} "
                f"(catalog={self._catalog}, schema={self._schema})"
            )
            return True

        except ImportError:
            logger.error(
                "databricks-sql-connector is not installed. "
                "Install it with: pip install databricks-sql-connector"
            )
            return False
        except Exception as e:
            logger.error(f"Databricks connection failed: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from Databricks."""
        if self._connection:
            try:
                self._connection.close()
            except Exception as e:
                logger.warning(f"Error closing Databricks connection: {e}")
            finally:
                self._connection = None
                logger.info("Disconnected from Databricks")

    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """Test Databricks connection."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute("SELECT current_catalog(), current_schema()")
            catalog, schema = cursor.fetchone()
            cursor.close()

            return True, f"Databricks, catalog: {catalog}, schema: {schema}"

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

    # =========================================================================
    # TABLE DISCOVERY
    # =========================================================================

    def _parse_table_name(self, table: str) -> Tuple[str, str, str]:
        """
        Parse a table name into catalog, schema, and table parts.

        Supports:
            - catalog.schema.table  -> (catalog, schema, table)
            - schema.table          -> (self._catalog, schema, table)
            - table                 -> (self._catalog, self._schema, table)

        Args:
            table: Table name (fully qualified or partial)

        Returns:
            Tuple of (catalog, schema, table_name)
        """
        parts = table.split('.')
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            return self._catalog, parts[0], parts[1]
        else:
            return self._catalog, self._schema, parts[0]

    def _fully_qualified_name(self, catalog: str, schema: str, table: str) -> str:
        """Build a fully qualified backtick-quoted table name."""
        return f"`{catalog}`.`{schema}`.`{table}`"

    def get_tables(self,
                   database: Optional[str] = None,
                   schema: Optional[str] = None,
                   include_views: bool = False) -> List[str]:
        """Get list of tables from INFORMATION_SCHEMA."""
        catalog = database or self._catalog
        schema_filter = f"AND table_schema = '{schema}'" if schema else ""

        table_types = "('BASE TABLE', 'MANAGED', 'EXTERNAL')"
        if include_views:
            table_types = "('BASE TABLE', 'MANAGED', 'EXTERNAL', 'VIEW')"

        query = f"""
            SELECT table_catalog, table_schema, table_name
            FROM `{catalog}`.INFORMATION_SCHEMA.TABLES
            WHERE table_type IN {table_types}
              {schema_filter}
            ORDER BY table_schema, table_name
        """

        try:
            results = self.execute_query(query)
            return [
                f"{row['table_catalog']}.{row['table_schema']}.{row['table_name']}"
                for row in results
            ]
        except Exception as e:
            logger.error(f"Failed to list tables from INFORMATION_SCHEMA: {e}")
            # Fallback: SHOW TABLES
            return self._get_tables_fallback(catalog, schema, include_views)

    def _get_tables_fallback(self,
                             catalog: str,
                             schema: Optional[str],
                             include_views: bool) -> List[str]:
        """Fallback table listing using SHOW TABLES."""
        tables = []
        try:
            schemas_to_scan = []
            if schema:
                schemas_to_scan = [schema]
            else:
                schema_results = self.execute_query(
                    f"SHOW SCHEMAS IN `{catalog}`"
                )
                schemas_to_scan = [
                    row.get('databaseName', row.get('namespace', ''))
                    for row in schema_results
                ]

            for s in schemas_to_scan:
                if s in ('information_schema',):
                    continue
                try:
                    results = self.execute_query(
                        f"SHOW TABLES IN `{catalog}`.`{s}`"
                    )
                    for row in results:
                        table_name = row.get('tableName', row.get('table_name', ''))
                        is_temporary = row.get('isTemporary', False)
                        if not is_temporary and table_name:
                            tables.append(f"{catalog}.{s}.{table_name}")
                except Exception as inner_e:
                    logger.warning(f"Failed to list tables in {catalog}.{s}: {inner_e}")

        except Exception as e:
            logger.error(f"Fallback table listing failed: {e}")

        return tables

    # =========================================================================
    # TABLE METADATA
    # =========================================================================

    def get_table_metadata(self, table: str) -> TableMetadata:
        """Get table metadata from INFORMATION_SCHEMA and DESCRIBE DETAIL."""
        catalog, schema, table_name = self._parse_table_name(table)
        fqn = self._fully_qualified_name(catalog, schema, table_name)

        # Get basic metadata from INFORMATION_SCHEMA
        query = f"""
            SELECT
                table_catalog,
                table_schema,
                table_name,
                table_type,
                comment
            FROM `{catalog}`.INFORMATION_SCHEMA.TABLES
            WHERE table_schema = '{schema}'
              AND table_name = '{table_name}'
        """

        results = self.execute_query(query)

        if not results:
            raise ValueError(f"Table not found: {table}")

        row = results[0]
        columns = self.get_columns(table)

        # Try to get detailed Delta metadata via DESCRIBE DETAIL
        detail = self._get_table_detail(fqn)

        # Try to get partition and clustering info
        partition_columns = self._get_partition_columns(fqn)
        clustering_columns = self._get_clustering_columns(fqn)

        return TableMetadata(
            full_name=f"{catalog}.{schema}.{table_name}",
            database=catalog,
            schema=schema,
            table_name=table_name,
            table_type=row.get('table_type', 'BASE TABLE'),
            row_count=detail.get('num_rows') if detail else None,
            size_bytes=detail.get('size_bytes') if detail else None,
            created_at=detail.get('created_at') if detail else None,
            last_modified=detail.get('last_modified') if detail else None,
            comment=row.get('comment'),
            columns=columns,
            is_partitioned=len(partition_columns) > 0,
            partition_columns=partition_columns,
            clustering_columns=clustering_columns,
            owner=detail.get('owner') if detail else None,
        )

    def _get_table_detail(self, fqn: str) -> Optional[Dict[str, Any]]:
        """Get Delta table detail via DESCRIBE DETAIL."""
        try:
            results = self.execute_query(f"DESCRIBE DETAIL {fqn}")
            if results:
                row = results[0]
                return {
                    'num_rows': row.get('numFiles'),
                    'size_bytes': row.get('sizeInBytes'),
                    'created_at': row.get('createdAt'),
                    'last_modified': row.get('lastModified'),
                    'owner': row.get('owner'),
                    'format': row.get('format'),
                    'location': row.get('location'),
                }
        except Exception as e:
            logger.debug(f"DESCRIBE DETAIL not available for {fqn}: {e}")
        return None

    def _get_partition_columns(self, fqn: str) -> List[str]:
        """Get partition columns for a table."""
        try:
            results = self.execute_query(f"DESCRIBE DETAIL {fqn}")
            if results and results[0].get('partitionColumns'):
                partition_cols = results[0]['partitionColumns']
                if isinstance(partition_cols, list):
                    return partition_cols
                elif isinstance(partition_cols, str) and partition_cols:
                    return [c.strip() for c in partition_cols.split(',') if c.strip()]
        except Exception as e:
            logger.debug(f"Could not get partition columns for {fqn}: {e}")
        return []

    def _get_clustering_columns(self, fqn: str) -> List[str]:
        """Get clustering (Z-ORDER) columns for a table."""
        try:
            results = self.execute_query(f"DESCRIBE DETAIL {fqn}")
            if results and results[0].get('clusteringColumns'):
                cluster_cols = results[0]['clusteringColumns']
                if isinstance(cluster_cols, list):
                    return cluster_cols
                elif isinstance(cluster_cols, str) and cluster_cols:
                    return [c.strip() for c in cluster_cols.split(',') if c.strip()]
        except Exception as e:
            logger.debug(f"Could not get clustering columns for {fqn}: {e}")
        return []

    # =========================================================================
    # COLUMN METADATA
    # =========================================================================

    def get_columns(self, table: str) -> List[ColumnMetadata]:
        """Get column metadata from INFORMATION_SCHEMA.COLUMNS."""
        catalog, schema, table_name = self._parse_table_name(table)

        query = f"""
            SELECT
                column_name,
                ordinal_position,
                data_type,
                full_data_type,
                character_maximum_length,
                numeric_precision,
                numeric_scale,
                is_nullable,
                column_default,
                comment
            FROM `{catalog}`.INFORMATION_SCHEMA.COLUMNS
            WHERE table_schema = '{schema}'
              AND table_name = '{table_name}'
            ORDER BY ordinal_position
        """

        try:
            results = self.execute_query(query)
        except Exception as e:
            logger.warning(
                f"INFORMATION_SCHEMA.COLUMNS query failed for {table}: {e}. "
                "Falling back to DESCRIBE."
            )
            return self._get_columns_fallback(catalog, schema, table_name)

        columns = []
        for row in results:
            columns.append(ColumnMetadata(
                name=row['column_name'],
                data_type=row.get('full_data_type', row.get('data_type', 'STRING')),
                is_nullable=row.get('is_nullable', 'YES') == 'YES',
                default_value=row.get('column_default'),
                ordinal_position=row.get('ordinal_position', 0),
                character_max_length=row.get('character_maximum_length'),
                numeric_precision=row.get('numeric_precision'),
                numeric_scale=row.get('numeric_scale'),
                comment=row.get('comment'),
            ))

        return columns

    def _get_columns_fallback(self, catalog: str, schema: str, table_name: str) -> List[ColumnMetadata]:
        """Fallback column listing using DESCRIBE TABLE."""
        fqn = self._fully_qualified_name(catalog, schema, table_name)
        columns = []
        try:
            results = self.execute_query(f"DESCRIBE TABLE {fqn}")
            for idx, row in enumerate(results):
                col_name = row.get('col_name', '')
                # DESCRIBE TABLE output may include partition info after a blank separator
                if not col_name or col_name.startswith('#'):
                    break
                columns.append(ColumnMetadata(
                    name=col_name,
                    data_type=row.get('data_type', 'STRING'),
                    is_nullable=True,
                    ordinal_position=idx + 1,
                    comment=row.get('comment'),
                ))
        except Exception as e:
            logger.error(f"Fallback DESCRIBE TABLE also failed: {e}")

        return columns

    # =========================================================================
    # COLUMN STATISTICS
    # =========================================================================

    def get_column_stats(self,
                         table: str,
                         columns: Optional[List[str]] = None,
                         sample_size: Optional[int] = None) -> List[ColumnStats]:
        """Get column statistics using standard SQL aggregations."""
        catalog, schema, table_name = self._parse_table_name(table)
        fqn = self._fully_qualified_name(catalog, schema, table_name)

        if columns is None:
            col_meta = self.get_columns(table)
            columns = [c.name for c in col_meta]

        stats = []
        source_clause = fqn
        if sample_size:
            source_clause = f"(SELECT * FROM {fqn} LIMIT {sample_size}) __sample"

        for col in columns:
            try:
                quoted_col = f"`{col}`"
                query = f"""
                    SELECT
                        COUNT(*) AS total_count,
                        COUNT({quoted_col}) AS non_null_count,
                        COUNT(DISTINCT {quoted_col}) AS distinct_count,
                        MIN({quoted_col}) AS min_val,
                        MAX({quoted_col}) AS max_val,
                        AVG(CAST({quoted_col} AS DOUBLE)) AS avg_val,
                        STDDEV(CAST({quoted_col} AS DOUBLE)) AS stddev_val
                    FROM {source_clause}
                """

                result = self.execute_query(query)

                if result:
                    row = result[0]
                    total = row.get('total_count', 0) or 0
                    non_null = row.get('non_null_count', 0) or 0

                    stats.append(ColumnStats(
                        column_name=col,
                        data_type='',
                        total_count=total,
                        null_count=total - non_null,
                        null_rate=(total - non_null) / total if total > 0 else 0.0,
                        distinct_count=row.get('distinct_count') or 0,
                        distinct_rate=(row.get('distinct_count') or 0) / total if total > 0 else 0.0,
                        min_value=row.get('min_val'),
                        max_value=row.get('max_val'),
                        avg_value=row.get('avg_val'),
                        std_dev=row.get('stddev_val'),
                    ))

            except Exception as e:
                logger.warning(f"Error getting stats for column {col} in {table}: {e}")
                stats.append(ColumnStats(
                    column_name=col,
                    data_type='',
                    total_count=0,
                    null_count=0,
                    null_rate=0.0,
                    distinct_count=0,
                ))

        return stats

    # =========================================================================
    # FRESHNESS
    # =========================================================================

    def get_table_freshness(self,
                            table: str,
                            timestamp_column: Optional[str] = None) -> Dict[str, Any]:
        """
        Get table freshness information.

        First attempts DESCRIBE HISTORY for Delta tables (metadata-level freshness).
        Falls back to scanning a timestamp column if available.
        """
        catalog, schema, table_name = self._parse_table_name(table)
        fqn = self._fully_qualified_name(catalog, schema, table_name)

        # Strategy 1: DESCRIBE HISTORY (Delta Lake metadata)
        if not timestamp_column:
            try:
                history_query = f"DESCRIBE HISTORY {fqn} LIMIT 1"
                history_result = self.execute_query(history_query)

                if history_result:
                    last_op = history_result[0]
                    last_updated = last_op.get('timestamp')
                    if last_updated:
                        if isinstance(last_updated, str):
                            last_updated = datetime.fromisoformat(last_updated)
                        hours_since = (datetime.now() - last_updated).total_seconds() / 3600
                        return {
                            'last_updated': last_updated,
                            'hours_since_update': hours_since,
                            'source': 'describe_history',
                            'operation': last_op.get('operation'),
                            'operation_parameters': last_op.get('operationParameters'),
                        }

            except Exception as e:
                logger.debug(f"DESCRIBE HISTORY not available for {fqn}: {e}")

        # Strategy 2: Detect or use provided timestamp column
        if not timestamp_column:
            timestamp_column = self.detect_timestamp_column(table)

        if not timestamp_column:
            return {'last_updated': None, 'error': 'No timestamp column found'}

        query = f"""
            SELECT
                MAX(`{timestamp_column}`) AS last_updated,
                COUNT(*) AS row_count
            FROM {fqn}
        """

        result = self.execute_query(query)

        if result and result[0].get('last_updated'):
            last_updated = result[0]['last_updated']
            if isinstance(last_updated, str):
                last_updated = datetime.fromisoformat(last_updated)
            hours_since = (datetime.now() - last_updated).total_seconds() / 3600

            return {
                'last_updated': last_updated,
                'hours_since_update': hours_since,
                'row_count': result[0].get('row_count'),
                'timestamp_column': timestamp_column,
            }

        return {'last_updated': None, 'timestamp_column': timestamp_column}

    # =========================================================================
    # DATA SAMPLING
    # =========================================================================

    def sample_data(self,
                    table: str,
                    n: int = 1000,
                    columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Sample data using TABLESAMPLE with ORDER BY RAND() fallback.

        Databricks supports TABLESAMPLE for efficient sampling on Delta tables.
        """
        catalog, schema, table_name = self._parse_table_name(table)
        fqn = self._fully_qualified_name(catalog, schema, table_name)

        col_list = ', '.join(f'`{c}`' for c in columns) if columns else '*'

        # Try TABLESAMPLE first (efficient, block-level sampling)
        try:
            query = f"""
                SELECT {col_list}
                FROM {fqn} TABLESAMPLE ({n} ROWS)
            """
            return self.execute_query(query)

        except Exception as e:
            logger.debug(
                f"TABLESAMPLE not supported for {fqn}, falling back to "
                f"ORDER BY RAND(): {e}"
            )

        # Fallback: ORDER BY RAND() LIMIT n
        query = f"""
            SELECT {col_list}
            FROM {fqn}
            ORDER BY RAND()
            LIMIT {n}
        """
        return self.execute_query(query)

    # =========================================================================
    # QUERY HISTORY
    # =========================================================================

    def get_query_history(self,
                          hours: int = 24,
                          user: Optional[str] = None,
                          database: Optional[str] = None) -> List[QueryHistoryEntry]:
        """
        Get query history from system.access.audit (Unity Catalog).

        Falls back to DESCRIBE HISTORY on specific tables if system tables
        are not accessible.
        """
        if not self._capabilities.supports_query_history:
            logger.warning("Databricks query history not enabled")
            return []

        return self._get_query_history_impl(hours, user, database)

    def _get_query_history_impl(self,
                                hours: int,
                                user: Optional[str],
                                database: Optional[str]) -> List[QueryHistoryEntry]:
        """Retrieve query history from system.access.audit."""
        user_filter = f"AND user_name = '{user}'" if user else ""
        database_filter = ""
        if database:
            database_filter = f"AND request_params.catalog = '{database}'"

        query = f"""
            SELECT
                event_id AS query_id,
                action_name AS query_type,
                user_identity.email AS user_name,
                request_params.commandText AS query_text,
                event_time AS start_time,
                response.statusCode AS status_code,
                response.errorMessage AS error_message,
                request_params.catalog AS catalog_name,
                request_params.schema AS schema_name
            FROM system.access.audit
            WHERE action_name IN ('commandSubmit', 'runCommand')
              AND event_time >= CURRENT_TIMESTAMP() - INTERVAL {hours} HOUR
              AND request_params.commandText IS NOT NULL
              {user_filter}
              {database_filter}
            ORDER BY event_time DESC
            LIMIT 1000
        """

        try:
            results = self.execute_query(query)

            entries = []
            for row in results:
                start_time = row.get('start_time')
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time)

                status = 'SUCCESS'
                if row.get('status_code') and str(row['status_code']) != '200':
                    status = 'FAILED'

                entries.append(QueryHistoryEntry(
                    query_id=str(row.get('query_id', '')),
                    query_text=str(row.get('query_text', ''))[:10000],
                    start_time=start_time,
                    status=status,
                    error_message=row.get('error_message'),
                    user_name=row.get('user_name'),
                    database=row.get('catalog_name'),
                    schema=row.get('schema_name'),
                    query_type=row.get('query_type'),
                ))

            return entries

        except Exception as e:
            logger.warning(
                f"Could not retrieve query history from system.access.audit: {e}. "
                "Ensure Unity Catalog system tables are enabled."
            )
            return []

    # =========================================================================
    # SQL GENERATION HELPERS
    # =========================================================================

    def quote_identifier(self, identifier: str) -> str:
        """Quote Databricks identifier (validated + escaped)."""
        from .sql_safety import quote_identifier as _q
        return _q(identifier, "databricks")

    def get_current_timestamp_sql(self) -> str:
        """Get current timestamp SQL."""
        return "CURRENT_TIMESTAMP()"

    def get_interval_sql(self, hours: int) -> str:
        """Get interval subtraction SQL."""
        return f"CURRENT_TIMESTAMP() - INTERVAL {hours} HOUR"

    def get_limit_sql(self, n: int) -> str:
        """Get LIMIT clause."""
        return f"LIMIT {n}"

    def get_random_sample_sql(self, table: str, n: int) -> str:
        """Get random sample SQL using TABLESAMPLE."""
        quoted = self.quote_identifier(table)
        return f"SELECT * FROM {quoted} TABLESAMPLE ({n} ROWS)"

    # =========================================================================
    # ADDITIONAL HELPERS
    # =========================================================================

    def get_current_timestamp(self) -> str:
        """Get current timestamp expression."""
        return "CURRENT_TIMESTAMP()"

    def get_interval_hours(self, hours: int) -> str:
        """Get interval subtraction expression."""
        return f"CURRENT_TIMESTAMP() - INTERVAL {hours} HOUR"

    def get_date_trunc(self, field: str, column: str) -> str:
        """Get DATE_TRUNC expression."""
        return f"DATE_TRUNC('{field}', {column})"
