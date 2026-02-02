"""
Snowflake Query History Adapter
Fetches lineage from Snowflake's ACCOUNT_USAGE and OBJECT_DEPENDENCIES views.
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .base import BaseQueryHistoryAdapter


class SnowflakeQueryHistoryAdapter(BaseQueryHistoryAdapter):
    """
    Adapter for Snowflake lineage extraction.
    
    Uses:
    - SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY for SQL queries
    - SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES for native lineage (if available)
    - SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY for access patterns
    """
    
    def __init__(self, connection):
        super().__init__(connection, dialect='snowflake')
    
    def get_query_history(
        self, 
        days_back: int = 30,
        limit: int = 10000
    ) -> List[str]:
        """
        Fetch transformation queries from Snowflake query history.
        
        Note: Requires SNOWFLAKE.ACCOUNT_USAGE access (ACCOUNTADMIN or granted)
        """
        queries = []
        cursor = self.connection.cursor()
        
        try:
            # Query for transformation statements
            sql = f"""
                SELECT QUERY_TEXT
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE QUERY_TYPE IN (
                    'CREATE_TABLE_AS_SELECT',
                    'CREATE_TABLE',
                    'CREATE_VIEW',
                    'INSERT',
                    'MERGE',
                    'UPDATE'
                )
                AND EXECUTION_STATUS = 'SUCCESS'
                AND START_TIME >= DATEADD(day, -{days_back}, CURRENT_TIMESTAMP())
                AND QUERY_TEXT IS NOT NULL
                AND LENGTH(QUERY_TEXT) > 10
                ORDER BY START_TIME DESC
                LIMIT {limit}
            """
            
            cursor.execute(sql)
            rows = cursor.fetchall()
            queries = [row[0] for row in rows if row[0]]
            
        except Exception as e:
            # If ACCOUNT_USAGE fails, try INFORMATION_SCHEMA (limited history)
            print(f"ACCOUNT_USAGE query failed: {e}. Trying INFORMATION_SCHEMA...")
            try:
                sql = f"""
                    SELECT QUERY_TEXT
                    FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                        RESULT_LIMIT => {min(limit, 1000)},
                        END_TIME_RANGE_START => DATEADD(day, -{min(days_back, 7)}, CURRENT_TIMESTAMP())
                    ))
                    WHERE QUERY_TYPE IN (
                        'CREATE_TABLE_AS_SELECT',
                        'CREATE_TABLE', 
                        'CREATE_VIEW',
                        'INSERT',
                        'MERGE'
                    )
                    AND EXECUTION_STATUS = 'SUCCESS'
                """
                cursor.execute(sql)
                rows = cursor.fetchall()
                queries = [row[0] for row in rows if row[0]]
            except Exception as e2:
                print(f"INFORMATION_SCHEMA query also failed: {e2}")
        
        finally:
            cursor.close()
        
        return queries
    
    def get_table_dependencies(self, table_name: str) -> Dict[str, List[str]]:
        """
        Get dependencies using Snowflake's native OBJECT_DEPENDENCIES view.
        
        Note: This is the most accurate source but requires ACCOUNTADMIN
        """
        result = {'upstream': [], 'downstream': []}
        cursor = self.connection.cursor()
        
        # Parse table name
        parts = table_name.upper().split('.')
        if len(parts) == 3:
            database, schema, table = parts
        elif len(parts) == 2:
            database = None
            schema, table = parts
        else:
            table = parts[0]
            database = schema = None
        
        try:
            # Get upstream dependencies (what this table depends on)
            upstream_sql = """
                SELECT 
                    REFERENCED_DATABASE || '.' || REFERENCED_SCHEMA || '.' || REFERENCED_OBJECT_NAME as FULL_NAME
                FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
                WHERE REFERENCING_OBJECT_NAME = %s
            """
            params = [table]
            
            if schema:
                upstream_sql += " AND REFERENCING_SCHEMA = %s"
                params.append(schema)
            if database:
                upstream_sql += " AND REFERENCING_DATABASE = %s"
                params.append(database)
            
            cursor.execute(upstream_sql, params)
            result['upstream'] = [row[0] for row in cursor.fetchall()]
            
            # Get downstream dependencies (what depends on this table)
            downstream_sql = """
                SELECT 
                    REFERENCING_DATABASE || '.' || REFERENCING_SCHEMA || '.' || REFERENCING_OBJECT_NAME as FULL_NAME
                FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
                WHERE REFERENCED_OBJECT_NAME = %s
            """
            params = [table]
            
            if schema:
                downstream_sql += " AND REFERENCED_SCHEMA = %s"
                params.append(schema)
            if database:
                downstream_sql += " AND REFERENCED_DATABASE = %s"
                params.append(database)
            
            cursor.execute(downstream_sql, params)
            result['downstream'] = [row[0] for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Object dependencies query failed: {e}")
        
        finally:
            cursor.close()
        
        return result
    
    def get_access_history(
        self, 
        table_name: str,
        days_back: int = 7
    ) -> List[Dict]:
        """
        Get recent access history for a table.
        Shows who/what has been reading from this table.
        """
        cursor = self.connection.cursor()
        accesses = []
        
        try:
            sql = """
                SELECT 
                    QUERY_START_TIME,
                    USER_NAME,
                    QUERY_TYPE,
                    QUERY_ID
                FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY,
                     LATERAL FLATTEN(BASE_OBJECTS_ACCESSED) f
                WHERE f.value:objectName::STRING ILIKE %s
                AND QUERY_START_TIME >= DATEADD(day, -%s, CURRENT_TIMESTAMP())
                ORDER BY QUERY_START_TIME DESC
                LIMIT 100
            """
            
            cursor.execute(sql, [f'%{table_name}%', days_back])
            rows = cursor.fetchall()
            
            for row in rows:
                accesses.append({
                    'timestamp': row[0],
                    'user': row[1],
                    'query_type': row[2],
                    'query_id': row[3],
                })
                
        except Exception as e:
            print(f"Access history query failed: {e}")
        
        finally:
            cursor.close()
        
        return accesses
    
    def get_all_tables(self, database: str = None, schema: str = None) -> List[str]:
        """Get list of all tables in the warehouse"""
        cursor = self.connection.cursor()
        tables = []
        
        try:
            if database and schema:
                sql = f"""
                    SELECT TABLE_CATALOG || '.' || TABLE_SCHEMA || '.' || TABLE_NAME
                    FROM {database}.INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = '{schema}'
                    AND TABLE_TYPE = 'BASE TABLE'
                """
            else:
                sql = """
                    SELECT TABLE_CATALOG || '.' || TABLE_SCHEMA || '.' || TABLE_NAME
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'BASE TABLE'
                """
            
            cursor.execute(sql)
            tables = [row[0] for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Get tables failed: {e}")
        
        finally:
            cursor.close()
        
        return tables

