"""
SQL Server / Azure SQL Query History Adapter

Extracts lineage from:
1. Query Store (if enabled) - Best source for Azure SQL
2. sys.dm_exec_query_stats + sys.dm_exec_sql_text
3. View definitions from sys.sql_modules
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import re

from .base import BaseQueryHistoryAdapter
from ..graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType
from ..parser import UniversalLineageParser


class SQLServerQueryHistoryAdapter(BaseQueryHistoryAdapter):
    """
    Adapter to build lineage from SQL Server / Azure SQL query history.
    
    Supports:
    - Azure SQL Database (Query Store)
    - Azure Synapse Analytics
    - SQL Server 2016+ (Query Store)
    - Older SQL Server (DMVs)
    """
    
    def __init__(self, connection):
        super().__init__(connection, dialect='tsql')
        self.parser = UniversalLineageParser('tsql')
        self._query_store_enabled = None
        
    def _check_query_store(self) -> bool:
        """Check if Query Store is enabled."""
        if self._query_store_enabled is not None:
            return self._query_store_enabled
            
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT is_query_store_on 
                FROM sys.databases 
                WHERE name = DB_NAME()
            """)
            row = cursor.fetchone()
            self._query_store_enabled = row[0] if row else False
            cursor.close()
        except Exception:
            self._query_store_enabled = False
            
        return self._query_store_enabled
    
    def get_query_history(self, days_back: int = 30) -> List[Dict[str, Any]]:
        """
        Fetch query history from SQL Server.
        
        Tries Query Store first (better for Azure SQL), 
        falls back to DMVs if not available.
        """
        queries = []
        
        if self._check_query_store():
            queries = self._get_from_query_store(days_back)
        
        if not queries:
            queries = self._get_from_dmvs(days_back)
            
        # Also get view definitions for additional lineage
        view_queries = self._get_view_definitions()
        queries.extend(view_queries)
        
        return queries
    
    def _get_from_query_store(self, days_back: int) -> List[Dict[str, Any]]:
        """Get queries from Query Store (Azure SQL / SQL Server 2016+)."""
        queries = []
        cutoff = datetime.now() - timedelta(days=days_back)
        
        try:
            cursor = self.connection.cursor()
            
            # Query Store stores query text and execution stats
            query = """
                SELECT DISTINCT
                    qt.query_sql_text,
                    OBJECT_NAME(q.object_id) as object_name,
                    rs.last_execution_time,
                    rs.count_executions,
                    q.query_id
                FROM sys.query_store_query_text qt
                JOIN sys.query_store_query q ON qt.query_text_id = q.query_text_id
                JOIN sys.query_store_plan p ON q.query_id = p.query_id
                JOIN sys.query_store_runtime_stats rs ON p.plan_id = rs.plan_id
                WHERE rs.last_execution_time >= ?
                AND qt.query_sql_text NOT LIKE '%sys.%'
                AND qt.query_sql_text NOT LIKE '%INFORMATION_SCHEMA%'
                AND (
                    qt.query_sql_text LIKE '%INSERT%INTO%SELECT%'
                    OR qt.query_sql_text LIKE '%CREATE%TABLE%AS%'
                    OR qt.query_sql_text LIKE '%SELECT%INTO%'
                    OR qt.query_sql_text LIKE '%MERGE%'
                    OR qt.query_sql_text LIKE '%UPDATE%FROM%'
                )
                ORDER BY rs.count_executions DESC
            """
            
            cursor.execute(query, (cutoff,))
            
            for row in cursor.fetchall():
                sql_text = row[0]
                if sql_text and len(sql_text) > 20:
                    queries.append({
                        'query_text': sql_text,
                        'object_name': row[1],
                        'last_execution': row[2],
                        'execution_count': row[3],
                        'source': 'query_store'
                    })
                    
            cursor.close()
            
        except Exception as e:
            print(f"Query Store fetch failed: {e}")
            
        return queries
    
    def _get_from_dmvs(self, days_back: int) -> List[Dict[str, Any]]:
        """Get queries from DMVs (fallback for older SQL Server)."""
        queries = []
        
        try:
            cursor = self.connection.cursor()
            
            # Get cached query plans with their SQL text
            query = """
                SELECT DISTINCT TOP 500
                    SUBSTRING(st.text, (qs.statement_start_offset/2)+1,
                        ((CASE qs.statement_end_offset
                            WHEN -1 THEN DATALENGTH(st.text)
                            ELSE qs.statement_end_offset
                        END - qs.statement_start_offset)/2)+1) as query_text,
                    qs.last_execution_time,
                    qs.execution_count
                FROM sys.dm_exec_query_stats qs
                CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
                WHERE qs.last_execution_time >= DATEADD(day, -?, GETDATE())
                AND st.text NOT LIKE '%sys.%'
                AND st.text NOT LIKE '%INFORMATION_SCHEMA%'
                AND (
                    st.text LIKE '%INSERT%INTO%SELECT%'
                    OR st.text LIKE '%CREATE%TABLE%AS%'
                    OR st.text LIKE '%SELECT%INTO%'
                    OR st.text LIKE '%MERGE%'
                    OR st.text LIKE '%UPDATE%FROM%'
                )
                ORDER BY qs.execution_count DESC
            """
            
            cursor.execute(query, (days_back,))
            
            for row in cursor.fetchall():
                sql_text = row[0]
                if sql_text and len(sql_text) > 20:
                    queries.append({
                        'query_text': sql_text,
                        'last_execution': row[1],
                        'execution_count': row[2],
                        'source': 'dmv'
                    })
                    
            cursor.close()
            
        except Exception as e:
            print(f"DMV fetch failed: {e}")
            
        return queries
    
    def _get_view_definitions(self) -> List[Dict[str, Any]]:
        """Get view definitions to extract view->table lineage."""
        queries = []
        
        try:
            cursor = self.connection.cursor()
            
            query = """
                SELECT 
                    SCHEMA_NAME(v.schema_id) as schema_name,
                    v.name as view_name,
                    m.definition
                FROM sys.views v
                JOIN sys.sql_modules m ON v.object_id = m.object_id
                WHERE m.definition IS NOT NULL
            """
            
            cursor.execute(query)
            
            for row in cursor.fetchall():
                schema_name = row[0]
                view_name = row[1]
                definition = row[2]
                
                if definition:
                    queries.append({
                        'query_text': definition,
                        'object_name': f"{schema_name}.{view_name}",
                        'source': 'view_definition',
                        'is_view': True
                    })
                    
            cursor.close()
            
        except Exception as e:
            print(f"View definition fetch failed: {e}")
            
        return queries
    
    def build_lineage_graph(self, days_back: int = 30) -> LineageGraph:
        """
        Build complete lineage graph from SQL Server query history.
        """
        graph = LineageGraph()
        
        # Get all tables in the database first
        tables = self._discover_tables()
        
        # Add all tables as nodes
        for table in tables:
            fqn = f"{table['database']}.{table['schema']}.{table['name']}"
            node = LineageNode(
                id=fqn.lower(),
                name=table['name'],
                fqn=fqn,
                node_type=NodeType.VIEW if table.get('is_view') else NodeType.TABLE,
                database=table['database'],
                schema=table['schema'],
                platform='sqlserver',
                dialect='tsql',
                criticality='MEDIUM',
            )
            graph.add_node(node)
        
        # Get query history
        queries = self.get_query_history(days_back)
        
        # Parse each query to extract lineage
        edge_id = 0
        for query_info in queries:
            sql = query_info.get('query_text', '')
            if not sql:
                continue
                
            try:
                lineage = self.parser.parse_query(sql)
                
                # Create edges from sources to targets
                for target in lineage.targets:
                    target_fqn = self._normalize_table_name(target)
                    
                    for source in lineage.sources:
                        source_fqn = self._normalize_table_name(source)
                        
                        # Ensure both nodes exist
                        if target_fqn.lower() not in graph.nodes:
                            self._add_node_from_name(graph, target_fqn)
                        if source_fqn.lower() not in graph.nodes:
                            self._add_node_from_name(graph, source_fqn)
                        
                        # Create edge
                        edge_id += 1
                        edge = LineageEdge(
                            id=f"edge_{edge_id}",
                            source_id=source_fqn.lower(),
                            target_id=target_fqn.lower(),
                            edge_type=EdgeType.DERIVED_FROM,
                            discovered_from='query_history',
                        )
                        graph.add_edge(edge)
                        
            except Exception as e:
                # Skip queries that can't be parsed
                continue
        
        graph.compute_depths()
        graph.built_at = datetime.now()
        
        return graph
    
    def _discover_tables(self) -> List[Dict[str, Any]]:
        """Discover all tables and views in the database."""
        tables = []
        
        try:
            cursor = self.connection.cursor()
            
            # Get database name
            cursor.execute("SELECT DB_NAME()")
            db_name = cursor.fetchone()[0]
            
            # Get all tables and views
            query = """
                SELECT 
                    TABLE_SCHEMA,
                    TABLE_NAME,
                    TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """
            
            cursor.execute(query)
            
            for row in cursor.fetchall():
                tables.append({
                    'database': db_name,
                    'schema': row[0],
                    'name': row[1],
                    'is_view': row[2] == 'VIEW'
                })
                
            cursor.close()
            
        except Exception as e:
            print(f"Table discovery failed: {e}")
            
        return tables
    
    def _normalize_table_name(self, name: str) -> str:
        """Normalize table name to fqn format."""
        parts = name.replace('[', '').replace(']', '').split('.')
        
        if len(parts) == 1:
            # Just table name - use default schema
            return f"dbo.{parts[0]}"
        elif len(parts) == 2:
            # schema.table
            return f"{parts[0]}.{parts[1]}"
        else:
            # database.schema.table or more
            return '.'.join(parts[-3:]) if len(parts) >= 3 else name
            
        return name
    
    def _add_node_from_name(self, graph: LineageGraph, fqn: str) -> None:
        """Add a node to the graph from a table name."""
        parts = fqn.split('.')
        
        if len(parts) >= 2:
            schema = parts[-2]
            table = parts[-1]
            database = parts[-3] if len(parts) >= 3 else None
        else:
            schema = 'dbo'
            table = fqn
            database = None
        
        node = LineageNode(
            id=fqn.lower(),
            name=table,
            fqn=fqn,
            node_type=NodeType.TABLE,
            database=database,
            schema=schema,
            platform='sqlserver',
            dialect='tsql',
            criticality='MEDIUM',
        )
        graph.add_node(node)
