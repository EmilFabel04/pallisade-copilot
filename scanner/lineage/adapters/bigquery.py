"""
BigQuery Query History Adapter
Fetches lineage from BigQuery's INFORMATION_SCHEMA.JOBS view.
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .base import BaseQueryHistoryAdapter


class BigQueryQueryHistoryAdapter(BaseQueryHistoryAdapter):
    """
    Adapter for BigQuery lineage extraction.
    
    Uses:
    - INFORMATION_SCHEMA.JOBS for query history
    - BigQuery Data Lineage API (if enabled)
    """
    
    def __init__(self, connection):
        super().__init__(connection, dialect='bigquery')
    
    def get_query_history(
        self, 
        days_back: int = 30,
        limit: int = 10000
    ) -> List[str]:
        """
        Fetch transformation queries from BigQuery job history.
        
        Note: Requires access to INFORMATION_SCHEMA.JOBS
        """
        queries = []
        
        try:
            # Query for transformation statements
            sql = f"""
                SELECT query
                FROM `region-us`.INFORMATION_SCHEMA.JOBS
                WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days_back} DAY)
                AND job_type = 'QUERY'
                AND statement_type IN (
                    'CREATE_TABLE_AS_SELECT',
                    'CREATE_TABLE',
                    'CREATE_VIEW',
                    'CREATE_MATERIALIZED_VIEW',
                    'INSERT',
                    'MERGE',
                    'UPDATE'
                )
                AND state = 'DONE'
                AND error_result IS NULL
                ORDER BY creation_time DESC
                LIMIT {limit}
            """
            
            # Execute query using the connection
            # BigQuery client has different API than standard cursor
            if hasattr(self.connection, 'query'):
                # google.cloud.bigquery.Client
                result = self.connection.query(sql)
                queries = [row.query for row in result if row.query]
            else:
                # Standard DB-API cursor
                cursor = self.connection.cursor()
                cursor.execute(sql)
                rows = cursor.fetchall()
                queries = [row[0] for row in rows if row[0]]
                cursor.close()
            
        except Exception as e:
            print(f"BigQuery query history failed: {e}")
            # Try alternative region
            try:
                sql = sql.replace('`region-us`', '`region-EU`')
                if hasattr(self.connection, 'query'):
                    result = self.connection.query(sql)
                    queries = [row.query for row in result if row.query]
            except Exception as e2:
                print(f"BigQuery EU region also failed: {e2}")
        
        return queries
    
    def get_table_dependencies(self, table_name: str) -> Dict[str, List[str]]:
        """
        Get dependencies using BigQuery's Data Lineage API.
        
        Note: Requires Data Catalog and Lineage API to be enabled
        """
        result = {'upstream': [], 'downstream': []}
        
        # Parse table name (project.dataset.table)
        parts = table_name.split('.')
        if len(parts) == 3:
            project, dataset, table = parts
        elif len(parts) == 2:
            project = None
            dataset, table = parts
        else:
            return result
        
        try:
            # BigQuery doesn't have a direct dependencies view like Snowflake
            # We need to use the Data Lineage API or parse query history
            
            # Try to find queries that reference this table
            sql = f"""
                SELECT DISTINCT query
                FROM `region-us`.INFORMATION_SCHEMA.JOBS
                WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
                AND state = 'DONE'
                AND (
                    referenced_tables IS NOT NULL
                    OR destination_table IS NOT NULL
                )
                AND query LIKE '%{table}%'
                LIMIT 100
            """
            
            if hasattr(self.connection, 'query'):
                query_result = self.connection.query(sql)
                for row in query_result:
                    # Parse each query to extract dependencies
                    info = self.parser.parse_query(row.query, 'bigquery')
                    table_lower = table_name.lower()
                    
                    # If this table is a target, sources are upstream
                    if any(table_lower in t.lower() for t in info.targets):
                        result['upstream'].extend(info.sources)
                    
                    # If this table is a source, targets are downstream  
                    if any(table_lower in t.lower() for t in info.sources):
                        result['downstream'].extend(info.targets)
            
            # Deduplicate
            result['upstream'] = list(set(result['upstream']))
            result['downstream'] = list(set(result['downstream']))
            
        except Exception as e:
            print(f"BigQuery dependencies query failed: {e}")
        
        return result
    
    def get_all_tables(self, project: str = None, dataset: str = None) -> List[str]:
        """Get list of all tables in BigQuery"""
        tables = []
        
        try:
            if project and dataset:
                sql = f"""
                    SELECT table_catalog || '.' || table_schema || '.' || table_name
                    FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES`
                    WHERE table_type = 'BASE TABLE'
                """
            else:
                # List tables in current default dataset
                sql = """
                    SELECT table_catalog || '.' || table_schema || '.' || table_name
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE table_type = 'BASE TABLE'
                """
            
            if hasattr(self.connection, 'query'):
                result = self.connection.query(sql)
                tables = [f"{row[0]}" for row in result]
            else:
                cursor = self.connection.cursor()
                cursor.execute(sql)
                tables = [row[0] for row in cursor.fetchall()]
                cursor.close()
                
        except Exception as e:
            print(f"Get tables failed: {e}")
        
        return tables

