"""
Base parser class for lineage extraction.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
from ..graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType
import hashlib


class BaseParser(ABC):
    """
    Base class for all lineage parsers.
    
    Subclasses implement platform-specific parsing logic.
    """
    
    # Override in subclasses
    PLATFORM = "unknown"
    DIALECT = "unknown"
    
    def __init__(self, connection: Any = None, config: Dict[str, Any] = None):
        self.connection = connection
        self.config = config or {}
        self.graph = LineageGraph()
        self.errors: List[str] = []
        
    @abstractmethod
    def parse(self) -> LineageGraph:
        """Parse and build the lineage graph."""
        pass
    
    def generate_node_id(self, fqn: str) -> str:
        """Generate a unique node ID from FQN (includes platform prefix for backward compat)."""
        return hashlib.md5(f"{self.PLATFORM}:{fqn}".encode()).hexdigest()[:16]

    def generate_canonical_node_id(self, fqn: str, warehouse_type: str = None) -> str:
        """
        Generate a platform-agnostic node ID for cross-tool matching.

        The canonical ID is based on warehouse_type:database.schema.table
        which allows the same physical table to be identified across tools.

        Args:
            fqn: Fully qualified name (database.schema.table)
            warehouse_type: The underlying warehouse type (bigquery, snowflake, etc.)
                           If not provided, uses DIALECT or PLATFORM

        Returns:
            16-character canonical node ID
        """
        wh_type = warehouse_type or self.DIALECT or self.PLATFORM
        canonical_fqn = f"{wh_type.lower()}:{fqn.lower()}"
        return hashlib.md5(canonical_fqn.encode()).hexdigest()[:16]

    def get_canonical_fqn(self, database: str, schema: str, table: str, warehouse_type: str = None) -> str:
        """
        Build a canonical FQN for cross-tool matching.

        Format: {warehouse_type}:{database}.{schema}.{table}
        """
        wh_type = warehouse_type or self.DIALECT or self.PLATFORM
        parts = [p.lower() for p in [database, schema, table] if p]
        return f"{wh_type.lower()}:{'.'.join(parts)}"

    def generate_edge_id(self, source_id: str, target_id: str, edge_type: str) -> str:
        """Generate a unique edge ID."""
        return hashlib.md5(f"{source_id}:{target_id}:{edge_type}".encode()).hexdigest()[:16]
    
    def normalize_fqn(self, *parts: str) -> str:
        """Normalize a fully qualified name."""
        return ".".join(p.lower().strip() for p in parts if p)
    
    def parse_fqn(self, fqn: str) -> Tuple[Optional[str], Optional[str], str]:
        """
        Parse a fully qualified name into (database, schema, table).
        
        Handles various formats:
        - table
        - schema.table
        - database.schema.table
        - catalog.database.schema.table
        """
        parts = fqn.replace('"', '').replace('`', '').replace('[', '').replace(']', '').split('.')
        
        if len(parts) >= 3:
            return parts[-3], parts[-2], parts[-1]
        elif len(parts) == 2:
            return None, parts[0], parts[1]
        else:
            return None, None, parts[0]
    
    def create_table_node(self, fqn: str, database: str = None, schema: str = None,
                         table: str = None, node_type: NodeType = NodeType.TABLE,
                         **kwargs) -> LineageNode:
        """Helper to create a table node."""
        if not table:
            database, schema, table = self.parse_fqn(fqn)
        
        node_id = self.generate_node_id(fqn)
        
        return LineageNode(
            id=node_id,
            name=table,
            fqn=fqn,
            node_type=node_type,
            database=database,
            schema=schema,
            platform=self.PLATFORM,
            dialect=self.DIALECT,
            **kwargs
        )
    
    def create_edge(self, source_id: str, target_id: str, 
                   edge_type: EdgeType = EdgeType.DEPENDS_ON,
                   **kwargs) -> LineageEdge:
        """Helper to create an edge."""
        edge_id = self.generate_edge_id(source_id, target_id, edge_type.value)
        
        # Only add discovered_from if not already provided in kwargs
        if 'discovered_from' not in kwargs:
            kwargs['discovered_from'] = self.PLATFORM
        
        return LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            **kwargs
        )
    
    def add_error(self, message: str) -> None:
        """Record a parsing error."""
        self.errors.append(f"[{self.PLATFORM}] {message}")
        print(f"⚠️ {self.PLATFORM} parser error: {message}")

