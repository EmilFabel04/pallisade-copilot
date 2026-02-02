"""
PostgreSQL Query History Adapter
Fetches lineage from pg_stat_statements and parses SQL.
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .base import BaseQueryHistoryAdapter


class PostgresQueryHistoryAdapter(BaseQueryHistoryAdapter):
    """
    Adapter for PostgreSQL lineage extraction.
    
    Uses:
    - pg_stat_statements for query history (requires extension)
    - information_schema for table metadata
    - pg_depend for view dependencies
    """
    
    def __init__(self, connection):
        super().__init__(connection, dialect='postgres')
    
    def get_query_history(
        self, 
        days_back: int = 30,
        limit: int = 10000
    ) -> List[str]:
        """
        Fetch transformation queries from pg_stat_statements.
        
        Note: Requires pg_stat_statements extension to be enabled
        """
        queries = []
        cursor = self.connection.cursor()
        
        try:
            # Check if pg_stat_statements exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
                )
            """)
            has_extension = cursor.fetchone()[0]
            
            if has_extension:
                # Query pg_stat_statements for transformation queries
                sql = f"""
                    SELECT query
                    FROM pg_stat_statements
                    WHERE query ~* '(CREATE|INSERT|UPDATE|MERGE|DELETE).*'
                    AND query !~* '^(SELECT|EXPLAIN|SHOW|SET|BEGIN|COMMIT|ROLLBACK)'
                    AND calls > 0
                    ORDER BY calls DESC
                    LIMIT {limit}
                """
                cursor.execute(sql)
                rows = cursor.fetchall()
                queries = [row[0] for row in rows if row[0]]
            else:
                print("pg_stat_statements extension not enabled. Using view definitions instead.")
                # Fall back to extracting view definitions
                queries = self._get_view_definitions(cursor)
                
        except Exception as e:
            print(f"PostgreSQL query history failed: {e}")
            # Try view definitions as fallback
            try:
                queries = self._get_view_definitions(cursor)
            except Exception as e2:
                print(f"View definitions also failed: {e2}")
        
        finally:
            cursor.close()
        
        return queries
    
    def _get_view_definitions(self, cursor) -> List[str]:
        """Get SQL definitions of all views"""
        queries = []
        
        try:
            cursor.execute("""
                SELECT 
                    'CREATE OR REPLACE VIEW ' || schemaname || '.' || viewname || ' AS ' || definition
                FROM pg_views
                WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            """)
            rows = cursor.fetchall()
            queries = [row[0] for row in rows if row[0]]
        except Exception as e:
            print(f"Get view definitions failed: {e}")
        
        return queries
    
    def get_table_dependencies(self, table_name: str) -> Dict[str, List[str]]:
        """
        Get dependencies using PostgreSQL system catalogs.
        """
        result = {'upstream': [], 'downstream': []}
        cursor = self.connection.cursor()
        
        # Parse table name
        parts = table_name.split('.')
        if len(parts) == 2:
            schema, table = parts
        else:
            schema = 'public'
            table = parts[0]
        
        try:
            # Get views that depend on this table (downstream)
            cursor.execute("""
                SELECT DISTINCT 
                    n.nspname || '.' || c.relname as view_name
                FROM pg_depend d
                JOIN pg_rewrite r ON d.objid = r.oid
                JOIN pg_class c ON r.ev_class = c.oid
                JOIN pg_namespace n ON c.relnamespace = n.oid
                JOIN pg_class source ON d.refobjid = source.oid
                JOIN pg_namespace source_ns ON source.relnamespace = source_ns.oid
                WHERE source.relname = %s
                AND source_ns.nspname = %s
                AND c.relname != source.relname
            """, [table, schema])
            
            result['downstream'] = [row[0] for row in cursor.fetchall()]
            
            # Get tables/views this depends on (upstream) - for views only
            cursor.execute("""
                SELECT DISTINCT 
                    source_ns.nspname || '.' || source.relname as source_name
                FROM pg_depend d
                JOIN pg_rewrite r ON d.objid = r.oid
                JOIN pg_class c ON r.ev_class = c.oid
                JOIN pg_namespace n ON c.relnamespace = n.oid
                JOIN pg_class source ON d.refobjid = source.oid
                JOIN pg_namespace source_ns ON source.relnamespace = source_ns.oid
                WHERE c.relname = %s
                AND n.nspname = %s
                AND source.relname != c.relname
                AND source.relkind IN ('r', 'v', 'm')
            """, [table, schema])
            
            result['upstream'] = [row[0] for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"PostgreSQL dependencies query failed: {e}")
        
        finally:
            cursor.close()
        
        return result
    
    def get_all_tables(self, schema: str = 'public') -> List[str]:
        """Get list of all tables in PostgreSQL"""
        cursor = self.connection.cursor()
        tables = []
        
        try:
            cursor.execute("""
                SELECT table_schema || '.' || table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """, [schema])
            
            tables = [row[0] for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Get tables failed: {e}")
        
        finally:
            cursor.close()
        
        return tables
    
    def get_foreign_key_lineage(self) -> Dict[str, List[str]]:
        """
        Get implicit lineage from foreign key relationships.
        Returns dict mapping table -> tables it references via FK
        """
        cursor = self.connection.cursor()
        fk_deps = {}
        
        try:
            cursor.execute("""
                SELECT 
                    tc.table_schema || '.' || tc.table_name as child_table,
                    ccu.table_schema || '.' || ccu.table_name as parent_table
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
            """)
            
            for row in cursor.fetchall():
                child, parent = row
                if child not in fk_deps:
                    fk_deps[child] = []
                fk_deps[child].append(parent)
                
        except Exception as e:
            print(f"Get FK lineage failed: {e}")
        
        finally:
            cursor.close()
        
        return fk_deps

