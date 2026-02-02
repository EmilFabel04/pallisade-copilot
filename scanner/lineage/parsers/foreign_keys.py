"""
Generic Foreign Key Parser

Extracts lineage from foreign key relationships across any database.
Uses the adapter pattern to work with different database types.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from .base import BaseParser
from ..graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType


class ForeignKeyParser(BaseParser):
    """
    Extract lineage from foreign key relationships.
    
    Works with any database that has INFORMATION_SCHEMA or equivalent.
    """
    
    PLATFORM = "foreign_keys"
    
    def __init__(self, adapter, database_name: str = None, **kwargs):
        super().__init__(**kwargs)
        self.adapter = adapter
        self.database_name = database_name
        self.DIALECT = getattr(adapter, 'dialect', 'unknown')
    
    def parse(self) -> LineageGraph:
        """Build lineage from foreign keys."""
        try:
            dialect = self.DIALECT.lower()
            
            if dialect in ('snowflake', 'postgres', 'redshift'):
                self._parse_information_schema_fk()
            elif dialect in ('sqlserver', 'tsql'):
                self._parse_sqlserver_fk()
            elif dialect == 'bigquery':
                # BigQuery doesn't have enforced FKs
                pass
            elif dialect in ('mysql', 'mariadb'):
                self._parse_mysql_fk()
            else:
                self._parse_information_schema_fk()
            
            self.graph.compute_depths()
            self.graph.built_at = datetime.utcnow()
            
            print(f"✅ FK parser: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")
            
        except Exception as e:
            self.add_error(f"Failed to parse foreign keys: {e}")
        
        return self.graph
    
    def _parse_information_schema_fk(self) -> None:
        """Parse using standard INFORMATION_SCHEMA."""
        cursor = self.adapter.connection.cursor()
        
        try:
            # Get all tables first
            cursor.execute("""
                SELECT 
                    table_catalog,
                    table_schema,
                    table_name,
                    table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            """)
            
            for row in cursor.fetchall():
                catalog, schema, table, table_type = row
                fqn = self.normalize_fqn(catalog, schema, table)
                node_type = NodeType.VIEW if 'VIEW' in str(table_type) else NodeType.TABLE
                
                node = self.create_table_node(
                    fqn=fqn,
                    database=catalog,
                    schema=schema,
                    table=table,
                    node_type=node_type,
                )
                self.graph.add_node(node)
            
            # Get foreign keys
            cursor.execute("""
                SELECT 
                    tc.table_catalog AS fk_catalog,
                    tc.table_schema AS fk_schema,
                    tc.table_name AS fk_table,
                    kcu.column_name AS fk_column,
                    ccu.table_catalog AS pk_catalog,
                    ccu.table_schema AS pk_schema,
                    ccu.table_name AS pk_table,
                    ccu.column_name AS pk_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
            """)
            
            for row in cursor.fetchall():
                fk_fqn = self.normalize_fqn(row[0], row[1], row[2])
                pk_fqn = self.normalize_fqn(row[4], row[5], row[6])
                
                fk_id = self.generate_node_id(fk_fqn)
                pk_id = self.generate_node_id(pk_fqn)
                
                if fk_id in self.graph.nodes and pk_id in self.graph.nodes:
                    edge = self.create_edge(
                        source_id=pk_id,
                        target_id=fk_id,
                        edge_type=EdgeType.REFERENCES,
                        columns=[{"source": row[7], "target": row[3]}],
                    )
                    self.graph.add_edge(edge)
        finally:
            cursor.close()
    
    def _parse_sqlserver_fk(self) -> None:
        """Parse SQL Server foreign keys."""
        cursor = self.adapter.connection.cursor()
        
        try:
            # Get tables
            cursor.execute("""
                SELECT 
                    DB_NAME() AS catalog,
                    s.name AS schema_name,
                    t.name AS table_name,
                    t.type_desc
                FROM sys.tables t
                INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
                
                UNION ALL
                
                SELECT 
                    DB_NAME(),
                    s.name,
                    v.name,
                    'VIEW'
                FROM sys.views v
                INNER JOIN sys.schemas s ON v.schema_id = s.schema_id
            """)
            
            for row in cursor.fetchall():
                catalog, schema, table, table_type = row
                fqn = self.normalize_fqn(catalog, schema, table)
                node_type = NodeType.VIEW if 'VIEW' in str(table_type) else NodeType.TABLE
                
                node = self.create_table_node(
                    fqn=fqn,
                    database=catalog,
                    schema=schema,
                    table=table,
                    node_type=node_type,
                )
                self.graph.add_node(node)
            
            # Get foreign keys
            cursor.execute("""
                SELECT 
                    DB_NAME() AS fk_catalog,
                    OBJECT_SCHEMA_NAME(fk.parent_object_id) AS fk_schema,
                    OBJECT_NAME(fk.parent_object_id) AS fk_table,
                    COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS fk_column,
                    DB_NAME() AS pk_catalog,
                    OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS pk_schema,
                    OBJECT_NAME(fk.referenced_object_id) AS pk_table,
                    COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS pk_column
                FROM sys.foreign_keys fk
                INNER JOIN sys.foreign_key_columns fkc 
                    ON fk.object_id = fkc.constraint_object_id
            """)
            
            for row in cursor.fetchall():
                fk_fqn = self.normalize_fqn(row[0], row[1], row[2])
                pk_fqn = self.normalize_fqn(row[4], row[5], row[6])
                
                fk_id = self.generate_node_id(fk_fqn)
                pk_id = self.generate_node_id(pk_fqn)
                
                if fk_id in self.graph.nodes and pk_id in self.graph.nodes:
                    edge = self.create_edge(
                        source_id=pk_id,
                        target_id=fk_id,
                        edge_type=EdgeType.REFERENCES,
                        columns=[{"source": row[7], "target": row[3]}],
                    )
                    self.graph.add_edge(edge)
        finally:
            cursor.close()
    
    def _parse_mysql_fk(self) -> None:
        """Parse MySQL foreign keys."""
        cursor = self.adapter.connection.cursor()
        
        try:
            # Get tables
            cursor.execute(f"""
                SELECT 
                    table_schema,
                    table_name,
                    table_type
                FROM information_schema.tables
                WHERE table_schema = '{self.database_name or "DATABASE()"}'
            """)
            
            for row in cursor.fetchall():
                schema, table, table_type = row
                fqn = self.normalize_fqn(self.database_name, schema, table)
                node_type = NodeType.VIEW if 'VIEW' in str(table_type) else NodeType.TABLE
                
                node = self.create_table_node(
                    fqn=fqn,
                    database=self.database_name,
                    schema=schema,
                    table=table,
                    node_type=node_type,
                )
                self.graph.add_node(node)
            
            # Get foreign keys
            cursor.execute(f"""
                SELECT 
                    kcu.table_schema AS fk_schema,
                    kcu.table_name AS fk_table,
                    kcu.column_name AS fk_column,
                    kcu.referenced_table_schema AS pk_schema,
                    kcu.referenced_table_name AS pk_table,
                    kcu.referenced_column_name AS pk_column
                FROM information_schema.key_column_usage kcu
                WHERE kcu.referenced_table_name IS NOT NULL
                AND kcu.table_schema = '{self.database_name or "DATABASE()"}'
            """)
            
            for row in cursor.fetchall():
                fk_fqn = self.normalize_fqn(self.database_name, row[0], row[1])
                pk_fqn = self.normalize_fqn(self.database_name, row[3], row[4])
                
                fk_id = self.generate_node_id(fk_fqn)
                pk_id = self.generate_node_id(pk_fqn)
                
                if fk_id in self.graph.nodes and pk_id in self.graph.nodes:
                    edge = self.create_edge(
                        source_id=pk_id,
                        target_id=fk_id,
                        edge_type=EdgeType.REFERENCES,
                        columns=[{"source": row[5], "target": row[2]}],
                    )
                    self.graph.add_edge(edge)
        finally:
            cursor.close()

