"""
Core Lineage Graph Data Structures

Represents the complete data lineage as a directed acyclic graph (DAG).
Supports multiple node types and relationship semantics.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from enum import Enum
from datetime import datetime
import json


class NodeType(Enum):
    """Types of nodes in the lineage graph."""
    # Data sources
    SOURCE = "source"           # External data source (API, file, stream)
    TABLE = "table"             # Database table
    VIEW = "view"               # Database view
    MATERIALIZED_VIEW = "materialized_view"
    
    # Transformation layer
    MODEL = "model"             # dbt model
    SNAPSHOT = "snapshot"       # dbt snapshot
    SEED = "seed"               # dbt seed
    MACRO = "macro"             # dbt macro
    
    # Pipeline/orchestration
    TASK = "task"               # Airflow/Prefect task
    DAG = "dag"                 # Airflow DAG
    FLOW = "flow"               # Prefect flow
    PIPELINE = "pipeline"       # Generic pipeline
    
    # BI/Analytics
    DASHBOARD = "dashboard"     # BI dashboard
    REPORT = "report"           # BI report
    DATASET = "dataset"         # Power BI dataset
    EXPLORE = "explore"         # Looker explore
    
    # ML
    FEATURE = "feature"         # ML feature
    MODEL_ARTIFACT = "model_artifact"  # ML model
    
    # Unknown
    UNKNOWN = "unknown"


class EdgeType(Enum):
    """Types of relationships between nodes."""
    DEPENDS_ON = "depends_on"           # General dependency
    DERIVED_FROM = "derived_from"       # Data lineage (SELECT FROM)
    JOINS = "joins"                     # JOIN relationship
    REFERENCES = "references"           # Foreign key reference
    TRIGGERS = "triggers"               # Pipeline triggers
    POPULATES = "populates"             # ETL populates target
    REFRESHES = "refreshes"             # Refresh dependency
    READS_FROM = "reads_from"           # BI reads from source
    WRITES_TO = "writes_to"             # Pipeline writes to target
    TESTS = "tests"                     # dbt test on model


class HealthStatus(Enum):
    """Health status of a node."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    UNKNOWN = "unknown"
    STALE = "stale"


@dataclass
class LineageNode:
    """A node in the lineage graph representing a data asset."""
    
    # Identity
    id: str                             # Unique ID (usually fqn)
    name: str                           # Display name
    fqn: str                            # Fully qualified name (db.schema.table)
    node_type: NodeType
    
    # Location
    database: Optional[str] = None
    schema: Optional[str] = None
    catalog: Optional[str] = None       # For Unity Catalog, etc.
    
    # Tech stack context
    platform: Optional[str] = None      # snowflake, bigquery, dbt, looker, etc.
    dialect: Optional[str] = None       # SQL dialect
    integration_id: Optional[str] = None  # Link to Pallisade integration
    
    # Metadata
    description: Optional[str] = None
    owner: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    # Business context
    domain: Optional[str] = None        # Business domain (sales, marketing, etc.)
    criticality: str = "medium"         # critical, high, medium, low
    pii_columns: List[str] = field(default_factory=list)
    
    # Schema info
    columns: List[Dict[str, Any]] = field(default_factory=list)
    primary_key: Optional[List[str]] = None
    row_count: Optional[int] = None
    
    # Freshness
    last_updated: Optional[datetime] = None
    expected_freshness_hours: Optional[int] = None
    
    # Health
    health_status: HealthStatus = HealthStatus.UNKNOWN
    active_findings: List[str] = field(default_factory=list)  # Finding IDs
    
    # Graph position (computed)
    depth: int = 0                      # Distance from sources
    upstream_count: int = 0
    downstream_count: int = 0
    
    # Raw data from source
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "fqn": self.fqn,
            "node_type": self.node_type.value,
            "database": self.database,
            "schema": self.schema,
            "platform": self.platform,
            "dialect": self.dialect,
            "description": self.description,
            "owner": self.owner,
            "tags": self.tags,
            "domain": self.domain,
            "criticality": self.criticality,
            "columns": self.columns,
            "row_count": self.row_count,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "health_status": self.health_status.value,
            "active_findings": self.active_findings,
            "depth": self.depth,
            "upstream_count": self.upstream_count,
            "downstream_count": self.downstream_count,
        }


@dataclass
class LineageEdge:
    """An edge representing a relationship between two nodes."""
    
    id: str                             # Unique edge ID
    source_id: str                      # Source node ID (upstream)
    target_id: str                      # Target node ID (downstream)
    edge_type: EdgeType
    
    # Relationship details
    columns: List[Dict[str, str]] = field(default_factory=list)  # Column mappings
    transformation: Optional[str] = None  # SQL snippet or description
    confidence: float = 1.0             # How confident we are (for inferred edges)
    
    # Source of this edge
    discovered_from: Optional[str] = None  # query_history, dbt_manifest, fk, manual
    discovered_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "columns": self.columns,
            "transformation": self.transformation,
            "confidence": self.confidence,
            "discovered_from": self.discovered_from,
        }


class LineageGraph:
    """
    The complete lineage graph for an organization.
    
    Supports:
    - Multiple data sources and platforms
    - Efficient traversal (upstream/downstream)
    - Subgraph extraction
    - Impact analysis
    - Root cause detection
    """
    
    def __init__(self):
        self.nodes: Dict[str, LineageNode] = {}
        self.edges: Dict[str, LineageEdge] = {}
        
        # Adjacency lists for efficient traversal
        self._upstream: Dict[str, Set[str]] = {}    # node_id -> set of upstream node_ids
        self._downstream: Dict[str, Set[str]] = {}  # node_id -> set of downstream node_ids
        
        # Indexes for fast lookup
        self._by_platform: Dict[str, Set[str]] = {}
        self._by_type: Dict[NodeType, Set[str]] = {}
        self._by_database: Dict[str, Set[str]] = {}
        
        # Metadata
        self.built_at: Optional[datetime] = None
        self.source_counts: Dict[str, int] = {}  # How many edges from each source
        
    def add_node(self, node: LineageNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.id] = node
        
        # Initialize adjacency
        if node.id not in self._upstream:
            self._upstream[node.id] = set()
        if node.id not in self._downstream:
            self._downstream[node.id] = set()
        
        # Update indexes
        if node.platform:
            if node.platform not in self._by_platform:
                self._by_platform[node.platform] = set()
            self._by_platform[node.platform].add(node.id)
            
        if node.node_type not in self._by_type:
            self._by_type[node.node_type] = set()
        self._by_type[node.node_type].add(node.id)
        
        if node.database:
            db_key = f"{node.platform or 'unknown'}.{node.database}"
            if db_key not in self._by_database:
                self._by_database[db_key] = set()
            self._by_database[db_key].add(node.id)
    
    def add_edge(self, edge: LineageEdge) -> None:
        """Add an edge to the graph."""
        # Ensure nodes exist
        if edge.source_id not in self.nodes:
            print(f"Warning: Source node {edge.source_id} not found, skipping edge")
            return
        if edge.target_id not in self.nodes:
            print(f"Warning: Target node {edge.target_id} not found, skipping edge")
            return
            
        self.edges[edge.id] = edge
        
        # Update adjacency lists
        self._downstream[edge.source_id].add(edge.target_id)
        self._upstream[edge.target_id].add(edge.source_id)
        
        # Update node counts
        self.nodes[edge.source_id].downstream_count = len(self._downstream[edge.source_id])
        self.nodes[edge.target_id].upstream_count = len(self._upstream[edge.target_id])
        
        # Track source counts
        source = edge.discovered_from or "unknown"
        self.source_counts[source] = self.source_counts.get(source, 0) + 1
    
    def get_upstream(self, node_id: str, depth: int = -1) -> List[LineageNode]:
        """
        Get all upstream nodes (dependencies).
        
        Args:
            node_id: The node to find upstream for
            depth: How many levels deep (-1 for all)
        
        Returns:
            List of upstream nodes
        """
        if node_id not in self.nodes:
            return []
        
        result = []
        visited = set()
        queue = [(node_id, 0)]
        
        while queue:
            current_id, current_depth = queue.pop(0)
            
            if current_id in visited:
                continue
            visited.add(current_id)
            
            if current_id != node_id:
                result.append(self.nodes[current_id])
            
            if depth == -1 or current_depth < depth:
                for upstream_id in self._upstream.get(current_id, set()):
                    if upstream_id not in visited:
                        queue.append((upstream_id, current_depth + 1))
        
        return result
    
    def get_downstream(self, node_id: str, depth: int = -1) -> List[LineageNode]:
        """
        Get all downstream nodes (dependents).
        
        Args:
            node_id: The node to find downstream for
            depth: How many levels deep (-1 for all)
        
        Returns:
            List of downstream nodes
        """
        if node_id not in self.nodes:
            return []
        
        result = []
        visited = set()
        queue = [(node_id, 0)]
        
        while queue:
            current_id, current_depth = queue.pop(0)
            
            if current_id in visited:
                continue
            visited.add(current_id)
            
            if current_id != node_id:
                result.append(self.nodes[current_id])
            
            if depth == -1 or current_depth < depth:
                for downstream_id in self._downstream.get(current_id, set()):
                    if downstream_id not in visited:
                        queue.append((downstream_id, current_depth + 1))
        
        return result
    
    def get_direct_upstream(self, node_id: str) -> List[LineageNode]:
        """Get immediate upstream nodes (one level)."""
        return self.get_upstream(node_id, depth=1)
    
    def get_direct_downstream(self, node_id: str) -> List[LineageNode]:
        """Get immediate downstream nodes (one level)."""
        return self.get_downstream(node_id, depth=1)
    
    def get_roots(self) -> List[LineageNode]:
        """Get all root nodes (no upstream dependencies)."""
        return [
            node for node_id, node in self.nodes.items()
            if len(self._upstream.get(node_id, set())) == 0
        ]
    
    def get_leaves(self) -> List[LineageNode]:
        """Get all leaf nodes (no downstream dependents)."""
        return [
            node for node_id, node in self.nodes.items()
            if len(self._downstream.get(node_id, set())) == 0
        ]
    
    def get_path(self, from_id: str, to_id: str) -> Optional[List[LineageNode]]:
        """Find shortest path between two nodes (if exists)."""
        if from_id not in self.nodes or to_id not in self.nodes:
            return None
        
        visited = set()
        queue = [(from_id, [from_id])]
        
        while queue:
            current_id, path = queue.pop(0)
            
            if current_id == to_id:
                return [self.nodes[nid] for nid in path]
            
            if current_id in visited:
                continue
            visited.add(current_id)
            
            for downstream_id in self._downstream.get(current_id, set()):
                if downstream_id not in visited:
                    queue.append((downstream_id, path + [downstream_id]))
        
        return None
    
    def get_subgraph(self, center_id: str, upstream_depth: int = 2, 
                     downstream_depth: int = 2) -> 'LineageGraph':
        """
        Extract a subgraph centered on a node.
        
        Useful for visualization of a specific asset's lineage.
        """
        subgraph = LineageGraph()
        
        if center_id not in self.nodes:
            return subgraph
        
        # Add center node
        subgraph.add_node(self.nodes[center_id])
        
        # Add upstream
        for node in self.get_upstream(center_id, depth=upstream_depth):
            subgraph.add_node(node)
        
        # Add downstream
        for node in self.get_downstream(center_id, depth=downstream_depth):
            subgraph.add_node(node)
        
        # Add relevant edges
        for edge in self.edges.values():
            if edge.source_id in subgraph.nodes and edge.target_id in subgraph.nodes:
                subgraph.add_edge(edge)
        
        return subgraph
    
    def compute_depths(self) -> None:
        """Compute depth (distance from sources) for all nodes."""
        # Find roots
        roots = self.get_roots()
        
        # BFS from roots
        visited = set()
        queue = [(root.id, 0) for root in roots]
        
        while queue:
            node_id, depth = queue.pop(0)
            
            if node_id in visited:
                # Take the minimum depth
                self.nodes[node_id].depth = min(self.nodes[node_id].depth, depth)
                continue
            
            visited.add(node_id)
            self.nodes[node_id].depth = depth
            
            for downstream_id in self._downstream.get(node_id, set()):
                queue.append((downstream_id, depth + 1))
    
    def get_critical_path(self) -> List[LineageNode]:
        """Get the critical path (longest path through the graph)."""
        if not self.nodes:
            return []
        
        # Find node with max depth
        self.compute_depths()
        max_depth_node = max(self.nodes.values(), key=lambda n: n.depth)
        
        # Trace back to root
        path = [max_depth_node]
        current = max_depth_node
        
        while self._upstream.get(current.id):
            # Find upstream with depth = current.depth - 1
            for upstream_id in self._upstream[current.id]:
                upstream = self.nodes[upstream_id]
                if upstream.depth == current.depth - 1:
                    path.insert(0, upstream)
                    current = upstream
                    break
            else:
                break
        
        return path
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize the graph to a dictionary."""
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges.values()],
            "stats": {
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "root_count": len(self.get_roots()),
                "leaf_count": len(self.get_leaves()),
                "source_counts": self.source_counts,
            },
            "built_at": self.built_at.isoformat() if self.built_at else None,
        }
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LineageGraph':
        """Deserialize from dictionary."""
        graph = cls()
        
        # Add nodes first
        for node_data in data.get("nodes", []):
            node = LineageNode(
                id=node_data["id"],
                name=node_data["name"],
                fqn=node_data["fqn"],
                node_type=NodeType(node_data["node_type"]),
                database=node_data.get("database"),
                schema=node_data.get("schema"),
                platform=node_data.get("platform"),
                dialect=node_data.get("dialect"),
                description=node_data.get("description"),
                owner=node_data.get("owner"),
                tags=node_data.get("tags", []),
                domain=node_data.get("domain"),
                criticality=node_data.get("criticality", "medium"),
                health_status=HealthStatus(node_data.get("health_status", "unknown")),
            )
            graph.add_node(node)
        
        # Add edges
        for edge_data in data.get("edges", []):
            edge = LineageEdge(
                id=edge_data["id"],
                source_id=edge_data["source_id"],
                target_id=edge_data["target_id"],
                edge_type=EdgeType(edge_data["edge_type"]),
                columns=edge_data.get("columns", []),
                transformation=edge_data.get("transformation"),
                confidence=edge_data.get("confidence", 1.0),
                discovered_from=edge_data.get("discovered_from"),
            )
            graph.add_edge(edge)
        
        return graph
