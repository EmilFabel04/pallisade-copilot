"""
Base Query History Adapter
Abstract interface for fetching query history from different warehouses.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime, timedelta

from ..parser import UniversalLineageParser, LineageInfo
from ..graph import LineageGraph


class BaseQueryHistoryAdapter(ABC):
    """
    Abstract base class for query history adapters.
    
    Each adapter:
    1. Fetches recent queries from warehouse
    2. Filters to transformation queries (CREATE, INSERT, MERGE)
    3. Parses SQL to extract lineage
    4. Builds a LineageGraph
    """
    
    # SQL statement types that create lineage
    LINEAGE_STATEMENT_TYPES = [
        'CREATE_TABLE_AS_SELECT',
        'CTAS',
        'CREATE_TABLE',
        'CREATE_VIEW',
        'CREATE_MATERIALIZED_VIEW',
        'INSERT',
        'MERGE',
        'UPDATE',
    ]
    
    def __init__(self, connection, dialect: str = 'snowflake'):
        """
        Initialize adapter with database connection.
        
        Args:
            connection: Database connection object
            dialect: SQL dialect for parsing
        """
        self.connection = connection
        self.dialect = dialect
        self.parser = UniversalLineageParser(dialect)
    
    @abstractmethod
    def get_query_history(
        self, 
        days_back: int = 30,
        limit: int = 10000
    ) -> List[str]:
        """
        Fetch transformation queries from warehouse.
        
        Args:
            days_back: How many days of history to fetch
            limit: Maximum number of queries
            
        Returns:
            List of SQL query strings
        """
        pass
    
    @abstractmethod
    def get_table_dependencies(self, table_name: str) -> dict:
        """
        Get direct dependencies for a specific table using warehouse metadata.
        
        Args:
            table_name: Fully qualified table name
            
        Returns:
            Dict with 'upstream' and 'downstream' lists
        """
        pass
    
    def build_lineage_graph(
        self, 
        days_back: int = 30,
        limit: int = 10000
    ) -> LineageGraph:
        """
        Build complete lineage graph from query history.
        
        Args:
            days_back: How many days of history to analyze
            limit: Maximum queries to process
            
        Returns:
            LineageGraph with all discovered dependencies
        """
        graph = LineageGraph()
        graph.source = f"{self.dialect}_query_history"
        
        # Fetch queries
        queries = self.get_query_history(days_back, limit)
        
        # Parse each query and add to graph
        for sql in queries:
            try:
                info = self.parser.parse_query(sql, self.dialect)
                
                # Add edges for each source -> target relationship
                for target in info.targets:
                    for source in info.sources:
                        graph.add_edge(source, target)
                
                # Ensure all tables exist as nodes
                for table in info.sources + info.targets:
                    if table not in graph.nodes:
                        graph.add_node(table)
                        
            except Exception as e:
                # Log but continue on parse errors
                print(f"Warning: Failed to parse query: {str(e)[:100]}")
                continue
        
        return graph
    
    def get_lineage_for_table(
        self, 
        table_name: str,
        direction: str = "both"
    ) -> dict:
        """
        Get lineage for a specific table.
        
        Args:
            table_name: Table to get lineage for
            direction: "upstream", "downstream", or "both"
            
        Returns:
            Dict with upstream and/or downstream tables
        """
        # First try native metadata
        deps = self.get_table_dependencies(table_name)
        
        if deps.get('upstream') or deps.get('downstream'):
            return deps
        
        # Fall back to query history parsing
        graph = self.build_lineage_graph(days_back=30)
        
        result = {}
        if direction in ("upstream", "both"):
            result['upstream'] = list(graph.get_upstream(table_name))
        if direction in ("downstream", "both"):
            result['downstream'] = list(graph.get_downstream(table_name))
        
        return result

