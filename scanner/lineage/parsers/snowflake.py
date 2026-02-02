"""
Snowflake-specific lineage parser.

Extracts lineage from:
- ACCESS_HISTORY (Enterprise+)
- QUERY_HISTORY
- OBJECT_DEPENDENCIES
- Foreign key relationships
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from .base import BaseParser
from .sql_parser import SQLLineageParser
from ..graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType


class SnowflakeQueryParser(BaseParser):
    """
    Extract lineage from Snowflake query history and metadata.
    
    Uses multiple sources:
    1. ACCESS_HISTORY (if Enterprise+) - most accurate
    2. QUERY_HISTORY - fallback, parsed
    3. OBJECT_DEPENDENCIES - for views
    4. INFORMATION_SCHEMA - for foreign keys
    """
    
    PLATFORM = "snowflake"
    DIALECT = "snowflake"
    
    def __init__(self, connection, days_back: int = 30, use_access_history: bool = True, **kwargs):
        super().__init__(connection=connection, **kwargs)
        self.days_back = days_back
        self.use_access_history = use_access_history
        self.sql_parser = SQLLineageParser(dialect="snowflake")
    
    def parse(self) -> LineageGraph:
        """Build lineage from Snowflake metadata."""
        try:
            # First, discover all tables/views
            self._discover_objects()
            
            # Try ACCESS_HISTORY first (most accurate)
            if self.use_access_history:
                try:
                    self._parse_access_history()
                except Exception as e:
                    print(f"ACCESS_HISTORY not available, falling back to QUERY_HISTORY: {e}")
                    self._parse_query_history()
            else:
                self._parse_query_history()
            
            # Add view dependencies
            self._parse_view_dependencies()
            
            # Add foreign key relationships
            self._parse_foreign_keys()
            
            self.graph.compute_depths()
            self.graph.built_at = datetime.utcnow()
            
            print(f"✅ Snowflake parser: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")
            
        except Exception as e:
            self.add_error(f"Failed to parse Snowflake lineage: {e}")
        
        return self.graph
    
    def _discover_objects(self) -> None:
        """Discover all tables and views."""
        cursor = self.connection.cursor()
        
        try:
            # Get tables
            cursor.execute("""
                SELECT 
                    table_catalog,
                    table_schema,
                    table_name,
                    table_type,
                    row_count,
                    created,
                    last_altered,
                    comment
                FROM information_schema.tables
                WHERE table_schema NOT IN ('INFORMATION_SCHEMA')
            """)
            
            for row in cursor.fetchall():
                database, schema, table = row[0], row[1], row[2]
                table_type = row[3]
                
                fqn = self.normalize_fqn(database, schema, table)
                node_type = NodeType.VIEW if 'VIEW' in table_type else NodeType.TABLE
                
                node = self.create_table_node(
                    fqn=fqn,
                    database=database,
                    schema=schema,
                    table=table,
                    node_type=node_type,
                    row_count=row[4],
                    description=row[7],
                )
                node.last_updated = row[6]
                
                self.graph.add_node(node)
        finally:
            cursor.close()
    
    def _parse_access_history(self) -> None:
        """Parse ACCESS_HISTORY for accurate lineage (Enterprise+)."""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute(f"""
                SELECT 
                    query_id,
                    direct_objects_accessed,
                    objects_modified,
                    query_start_time
                FROM snowflake.account_usage.access_history
                WHERE query_start_time >= DATEADD(day, -{self.days_back}, CURRENT_TIMESTAMP())
                AND array_size(objects_modified) > 0
                ORDER BY query_start_time DESC
                LIMIT 50000
            """)
            
            for row in cursor.fetchall():
                sources = row[1] or []  # direct_objects_accessed
                targets = row[2] or []  # objects_modified
                
                for target in targets:
                    if not isinstance(target, dict):
                        continue
                    
                    target_fqn = self._extract_fqn(target)
                    if not target_fqn:
                        continue
                    
                    target_id = self.generate_node_id(target_fqn)
                    
                    for source in sources:
                        if not isinstance(source, dict):
                            continue
                        
                        source_fqn = self._extract_fqn(source)
                        if not source_fqn or source_fqn == target_fqn:
                            continue
                        
                        source_id = self.generate_node_id(source_fqn)
                        
                        # Add edge if both nodes exist
                        if source_id in self.graph.nodes and target_id in self.graph.nodes:
                            edge = self.create_edge(
                                source_id=source_id,
                                target_id=target_id,
                                edge_type=EdgeType.DERIVED_FROM,
                                discovered_from="access_history",
                            )
                            self.graph.add_edge(edge)
        finally:
            cursor.close()
    
    def _parse_query_history(self) -> None:
        """Parse QUERY_HISTORY as fallback."""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute(f"""
                SELECT 
                    query_id,
                    query_text,
                    query_type,
                    database_name,
                    schema_name,
                    start_time
                FROM snowflake.account_usage.query_history
                WHERE start_time >= DATEADD(day, -{self.days_back}, CURRENT_TIMESTAMP())
                AND query_type IN ('CREATE_TABLE_AS_SELECT', 'INSERT', 'MERGE', 
                                   'CREATE_VIEW', 'REPLACE_VIEW')
                AND execution_status = 'SUCCESS'
                ORDER BY start_time DESC
                LIMIT 10000
            """)
            
            for row in cursor.fetchall():
                query_text = row[1]
                
                # Parse the SQL
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
                            discovered_from="query_history",
                        )
                        self.graph.add_edge(edge)
        finally:
            cursor.close()
    
    def _parse_view_dependencies(self) -> None:
        """Parse view dependencies from OBJECT_DEPENDENCIES."""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute("""
                SELECT 
                    referencing_database,
                    referencing_schema,
                    referencing_object_name,
                    referenced_database,
                    referenced_schema,
                    referenced_object_name
                FROM snowflake.account_usage.object_dependencies
                WHERE referencing_object_domain = 'VIEW'
                AND referenced_object_domain = 'TABLE'
            """)
            
            for row in cursor.fetchall():
                target_fqn = self.normalize_fqn(row[0], row[1], row[2])
                source_fqn = self.normalize_fqn(row[3], row[4], row[5])
                
                target_id = self.generate_node_id(target_fqn)
                source_id = self.generate_node_id(source_fqn)
                
                if source_id in self.graph.nodes and target_id in self.graph.nodes:
                    edge = self.create_edge(
                        source_id=source_id,
                        target_id=target_id,
                        edge_type=EdgeType.DEPENDS_ON,
                        discovered_from="object_dependencies",
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
                    fk_table_catalog,
                    fk_table_schema,
                    fk_table_name,
                    pk_table_catalog,
                    pk_table_schema,
                    pk_table_name,
                    fk_column_name,
                    pk_column_name
                FROM information_schema.referential_constraints rc
                JOIN information_schema.key_column_usage kcu
                    ON rc.constraint_name = kcu.constraint_name
            """)
            
            for row in cursor.fetchall():
                fk_fqn = self.normalize_fqn(row[0], row[1], row[2])
                pk_fqn = self.normalize_fqn(row[3], row[4], row[5])
                
                fk_id = self.generate_node_id(fk_fqn)
                pk_id = self.generate_node_id(pk_fqn)
                
                if fk_id in self.graph.nodes and pk_id in self.graph.nodes:
                    edge = self.create_edge(
                        source_id=pk_id,
                        target_id=fk_id,
                        edge_type=EdgeType.REFERENCES,
                        columns=[{"source": row[7], "target": row[6]}],
                        discovered_from="foreign_keys",
                    )
                    self.graph.add_edge(edge)
        except Exception as e:
            # FK query might fail on some Snowflake setups
            self.add_error(f"Failed to parse foreign keys: {e}")
        finally:
            cursor.close()
    
    def _extract_fqn(self, obj: Dict[str, Any]) -> Optional[str]:
        """Extract FQN from ACCESS_HISTORY object."""
        obj_name = obj.get("objectName", "")
        obj_domain = obj.get("objectDomain", "")
        
        if obj_domain not in ("Table", "View", "MaterializedView"):
            return None
        
        # objectName is usually in format: DATABASE.SCHEMA.TABLE
        return obj_name.lower() if obj_name else None

