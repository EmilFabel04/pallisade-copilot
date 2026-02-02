"""
SQL Server / Azure SQL lineage parser.

Extracts lineage from:
- sys.sql_expression_dependencies
- sys.dm_exec_query_stats + sys.dm_exec_sql_text
- sys.foreign_keys
- Azure Synapse Analytics metadata
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from .base import BaseParser
from .sql_parser import SQLLineageParser
from ..graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType


class SQLServerParser(BaseParser):
    """
    Extract lineage from SQL Server / Azure SQL databases.
    
    Supports:
    - SQL Server 2016+
    - Azure SQL Database
    - Azure Synapse Analytics
    """
    
    PLATFORM = "sqlserver"
    DIALECT = "tsql"
    
    def __init__(self, connection, include_query_history: bool = True, **kwargs):
        super().__init__(connection=connection, **kwargs)
        self.include_query_history = include_query_history
        self.sql_parser = SQLLineageParser(dialect="tsql")
        self.database_name = None
    
    def parse(self) -> LineageGraph:
        """Build lineage from SQL Server metadata."""
        try:
            cursor = self.connection.cursor()
            
            # Get current database
            cursor.execute("SELECT DB_NAME()")
            self.database_name = cursor.fetchone()[0]
            cursor.close()
            
            # Discover objects
            self._discover_objects()
            
            # Parse dependencies from sys.sql_expression_dependencies
            self._parse_expression_dependencies()
            
            # Parse foreign keys
            self._parse_foreign_keys()
            
            # Parse query history (if available)
            if self.include_query_history:
                self._parse_query_stats()
            
            self.graph.compute_depths()
            self.graph.built_at = datetime.utcnow()
            
            print(f"✅ SQL Server parser: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")
            
        except Exception as e:
            self.add_error(f"Failed to parse SQL Server lineage: {e}")
        
        return self.graph
    
    def _discover_objects(self) -> None:
        """Discover all tables and views."""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute("""
                SELECT 
                    s.name AS schema_name,
                    t.name AS table_name,
                    t.type_desc,
                    p.rows AS row_count,
                    t.create_date,
                    t.modify_date,
                    ep.value AS description
                FROM sys.tables t
                INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                LEFT JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0,1)
                LEFT JOIN sys.extended_properties ep 
                    ON t.object_id = ep.major_id 
                    AND ep.minor_id = 0 
                    AND ep.name = 'MS_Description'
                
                UNION ALL
                
                SELECT 
                    s.name AS schema_name,
                    v.name AS table_name,
                    'VIEW' AS type_desc,
                    NULL AS row_count,
                    v.create_date,
                    v.modify_date,
                    ep.value AS description
                FROM sys.views v
                INNER JOIN sys.schemas s ON v.schema_id = s.schema_id
                LEFT JOIN sys.extended_properties ep 
                    ON v.object_id = ep.major_id 
                    AND ep.minor_id = 0 
                    AND ep.name = 'MS_Description'
            """)
            
            for row in cursor.fetchall():
                schema, table = row[0], row[1]
                type_desc = row[2]
                
                fqn = self.normalize_fqn(self.database_name, schema, table)
                node_type = NodeType.VIEW if type_desc == 'VIEW' else NodeType.TABLE
                
                node = self.create_table_node(
                    fqn=fqn,
                    database=self.database_name,
                    schema=schema,
                    table=table,
                    node_type=node_type,
                    row_count=row[3],
                    description=str(row[6]) if row[6] else None,
                )
                node.last_updated = row[5]
                
                self.graph.add_node(node)
        finally:
            cursor.close()
    
    def _parse_expression_dependencies(self) -> None:
        """Parse sys.sql_expression_dependencies for view/proc dependencies."""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute("""
                SELECT DISTINCT
                    OBJECT_SCHEMA_NAME(d.referencing_id) AS referencing_schema,
                    OBJECT_NAME(d.referencing_id) AS referencing_name,
                    COALESCE(d.referenced_schema_name, 'dbo') AS referenced_schema,
                    d.referenced_entity_name AS referenced_name,
                    o.type_desc AS referencing_type
                FROM sys.sql_expression_dependencies d
                INNER JOIN sys.objects o ON d.referencing_id = o.object_id
                WHERE d.referenced_entity_name IS NOT NULL
                AND o.type_desc IN ('VIEW', 'SQL_STORED_PROCEDURE', 'SQL_TABLE_VALUED_FUNCTION')
            """)
            
            for row in cursor.fetchall():
                ref_schema, ref_name = row[0], row[1]
                src_schema, src_name = row[2], row[3]
                
                if not ref_schema or not ref_name or not src_name:
                    continue
                
                target_fqn = self.normalize_fqn(self.database_name, ref_schema, ref_name)
                source_fqn = self.normalize_fqn(self.database_name, src_schema, src_name)
                
                target_id = self.generate_node_id(target_fqn)
                source_id = self.generate_node_id(source_fqn)
                
                if source_id in self.graph.nodes and target_id in self.graph.nodes:
                    edge = self.create_edge(
                        source_id=source_id,
                        target_id=target_id,
                        edge_type=EdgeType.DEPENDS_ON,
                        discovered_from="expression_dependencies",
                    )
                    self.graph.add_edge(edge)
        finally:
            cursor.close()
    
    def _parse_foreign_keys(self) -> None:
        """Parse foreign key relationships."""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute("""
                SELECT 
                    OBJECT_SCHEMA_NAME(fk.parent_object_id) AS fk_schema,
                    OBJECT_NAME(fk.parent_object_id) AS fk_table,
                    COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS fk_column,
                    OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS pk_schema,
                    OBJECT_NAME(fk.referenced_object_id) AS pk_table,
                    COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS pk_column
                FROM sys.foreign_keys fk
                INNER JOIN sys.foreign_key_columns fkc 
                    ON fk.object_id = fkc.constraint_object_id
            """)
            
            for row in cursor.fetchall():
                fk_schema, fk_table, fk_col = row[0], row[1], row[2]
                pk_schema, pk_table, pk_col = row[3], row[4], row[5]
                
                fk_fqn = self.normalize_fqn(self.database_name, fk_schema, fk_table)
                pk_fqn = self.normalize_fqn(self.database_name, pk_schema, pk_table)
                
                fk_id = self.generate_node_id(fk_fqn)
                pk_id = self.generate_node_id(pk_fqn)
                
                if fk_id in self.graph.nodes and pk_id in self.graph.nodes:
                    edge = self.create_edge(
                        source_id=pk_id,
                        target_id=fk_id,
                        edge_type=EdgeType.REFERENCES,
                        columns=[{"source": pk_col, "target": fk_col}],
                        discovered_from="foreign_keys",
                    )
                    self.graph.add_edge(edge)
        finally:
            cursor.close()
    
    def _parse_query_stats(self) -> None:
        """Parse recent query statistics for lineage (requires permissions)."""
        cursor = self.connection.cursor()
        
        try:
            # Get recently executed queries
            cursor.execute("""
                SELECT TOP 5000
                    SUBSTRING(qt.text, 1, 8000) AS query_text,
                    qs.last_execution_time,
                    qs.execution_count
                FROM sys.dm_exec_query_stats qs
                CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt
                WHERE qs.last_execution_time >= DATEADD(day, -7, GETUTCDATE())
                AND qt.text LIKE '%INSERT%'
                   OR qt.text LIKE '%CREATE%TABLE%'
                   OR qt.text LIKE '%CREATE%VIEW%'
                   OR qt.text LIKE '%MERGE%'
                ORDER BY qs.last_execution_time DESC
            """)
            
            for row in cursor.fetchall():
                query_text = row[0]
                
                try:
                    sources, target = self.sql_parser.parse_single(query_text)
                    
                    if not sources or not target:
                        continue
                    
                    target_id = self.generate_node_id(target)
                    
                    for source_fqn in sources:
                        source_id = self.generate_node_id(source_fqn)
                        
                        if source_id in self.graph.nodes and target_id in self.graph.nodes:
                            edge = self.create_edge(
                                source_id=source_id,
                                target_id=target_id,
                                edge_type=EdgeType.DERIVED_FROM,
                                discovered_from="query_stats",
                            )
                            self.graph.add_edge(edge)
                except Exception:
                    continue
                    
        except Exception as e:
            # Query stats might not be available
            self.add_error(f"Query stats not available: {e}")
        finally:
            cursor.close()

