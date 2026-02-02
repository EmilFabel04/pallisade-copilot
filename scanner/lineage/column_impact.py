"""
Column-Level Impact Analysis Engine
Analyzes downstream impact of findings based on specific column dependencies.
"""

from typing import List, Dict, Set, Optional, Any, Tuple
from dataclasses import dataclass, field
from .graph import LineageGraph, LineageNode, LineageEdge


# Finding type to propagation explanation mapping
PROPAGATION_EXPLANATIONS = {
    "null_rate": "NULL values will cause JOIN failures or propagate as NULL/default values. Downstream aggregations will exclude these rows, potentially skewing results.",
    "high_null_rate": "NULL values will cause JOIN failures or propagate as NULL/default values. Downstream aggregations will exclude these rows, potentially skewing results.",
    "outlier": "Outlier values will skew averages, sums, and other aggregations. Downstream metrics and calculations will be unreliable.",
    "anomaly": "Anomalous values will propagate through transformations, potentially causing incorrect calculations and misleading insights.",
    "schema_change": "The schema change may cause type mismatches and transformation failures downstream. Queries expecting the old schema will break.",
    "duplicate": "Duplicate values will cause incorrect JOIN cardinality, potentially multiplying row counts and inflating aggregations.",
    "stale": "Stale data means downstream reports and dashboards are working with outdated information, leading to delayed or incorrect decisions.",
    "freshness": "Data freshness issues mean downstream consumers are working with outdated information.",
    "negative_value": "Unexpected negative values will cause incorrect calculations in downstream aggregations and business logic.",
    "format_violation": "Format violations will cause parsing failures or incorrect data interpretation downstream.",
    "referential_integrity": "Orphan records will cause JOIN failures or missing data in downstream queries.",
    "volume": "Volume anomalies indicate potential data pipeline issues that may affect downstream completeness.",
    "distribution": "Distribution changes may indicate data quality issues that will affect downstream analytics.",
}

# Transformation type detection patterns
TRANSFORMATION_PATTERNS = {
    "JOIN": ["join", "inner join", "left join", "right join", "outer join", "cross join"],
    "AGGREGATE": ["sum(", "avg(", "count(", "min(", "max(", "group by"],
    "FILTER": ["where ", "having ", "filter("],
    "SELECT": ["select "],
    "UNION": ["union ", "union all"],
}


@dataclass
class AffectedColumn:
    """A column affected by an upstream issue."""
    table: str
    column: str
    distance: int  # Hops from the source
    criticality: str
    node_type: str
    owner: Optional[str]
    impact_reason: str  # Specific explanation of what breaks
    transformation: Optional[str]  # SQL snippet showing how column is used
    transformation_type: str  # JOIN, SELECT, AGGREGATE, etc.
    path: List[str]  # Path from source to this column


@dataclass
class ImpactSummary:
    """Summary statistics for impact analysis."""
    total_affected_tables: int = 0
    total_affected_columns: int = 0
    total_affected_dashboards: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    affected_teams: List[str] = field(default_factory=list)
    max_distance: int = 0


@dataclass
class ColumnImpactReport:
    """Complete column-level impact analysis report."""
    source_table: str
    source_column: str
    finding_type: str
    finding_severity: str
    finding_title: Optional[str] = None
    finding_value: Optional[str] = None
    
    # Affected downstream
    affected_columns: List[AffectedColumn] = field(default_factory=list)
    
    # Summary
    summary: ImpactSummary = field(default_factory=ImpactSummary)
    
    # Propagation explanation (finding-type specific)
    propagation_explanation: str = ""
    
    # Whether this column is isolated (no downstream)
    is_isolated: bool = False
    
    # Graph data for visualization
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_table": self.source_table,
            "source_column": self.source_column,
            "finding_type": self.finding_type,
            "finding_severity": self.finding_severity,
            "finding_title": self.finding_title,
            "finding_value": self.finding_value,
            "affected_columns": [
                {
                    "table": ac.table,
                    "column": ac.column,
                    "distance": ac.distance,
                    "criticality": ac.criticality,
                    "node_type": ac.node_type,
                    "owner": ac.owner,
                    "impact_reason": ac.impact_reason,
                    "transformation": ac.transformation,
                    "transformation_type": ac.transformation_type,
                    "path": ac.path,
                }
                for ac in self.affected_columns
            ],
            "summary": {
                "total_affected_tables": self.summary.total_affected_tables,
                "total_affected_columns": self.summary.total_affected_columns,
                "total_affected_dashboards": self.summary.total_affected_dashboards,
                "criticality_breakdown": {
                    "critical": self.summary.critical_count,
                    "high": self.summary.high_count,
                    "medium": self.summary.medium_count,
                    "low": self.summary.low_count,
                },
                "affected_teams": self.summary.affected_teams,
                "max_distance": self.summary.max_distance,
            },
            "propagation_explanation": self.propagation_explanation,
            "is_isolated": self.is_isolated,
            "graph": {
                "nodes": self.nodes,
                "edges": self.edges,
            },
        }


class ColumnImpactAnalyzer:
    """
    Analyzes the impact of findings on downstream assets at the column level.
    
    Unlike table-level impact analysis, this follows specific column dependencies
    through transformations to show exactly what breaks when a specific column
    has a data quality issue.
    """
    
    def __init__(self, graph: LineageGraph):
        self.graph = graph
        # Build edge lookup by source node for efficient traversal
        self._edges_by_source: Dict[str, List[LineageEdge]] = {}
        for edge in graph.edges.values():
            if edge.source_id not in self._edges_by_source:
                self._edges_by_source[edge.source_id] = []
            self._edges_by_source[edge.source_id].append(edge)
    
    def analyze_column_impact(
        self,
        table: str,
        column: str,
        finding_type: str,
        finding_severity: str = "medium",
        finding_title: Optional[str] = None,
        finding_value: Optional[str] = None,
        max_depth: int = 10,
    ) -> ColumnImpactReport:
        """
        Analyze the downstream impact of a finding on a specific column.
        
        Args:
            table: The table containing the finding
            column: The specific column with the issue
            finding_type: Type of finding (null_rate, outlier, schema_change, etc.)
            finding_severity: Severity of the finding (critical, high, medium, low)
            finding_title: Title/description of the finding
            finding_value: Value associated with finding (e.g., "47.3% null rate")
            max_depth: Maximum depth to traverse
            
        Returns:
            ColumnImpactReport with column-specific impact analysis
        """
        report = ColumnImpactReport(
            source_table=table,
            source_column=column,
            finding_type=finding_type,
            finding_severity=finding_severity,
            finding_title=finding_title,
            finding_value=finding_value,
        )
        
        # Get propagation explanation for this finding type
        report.propagation_explanation = self._get_propagation_explanation(
            finding_type, column
        )
        
        # Find the source node
        source_node = self._find_node(table)
        if not source_node:
            report.is_isolated = True
            return report
        
        # Traverse downstream following column dependencies
        affected = self._traverse_column_downstream(
            source_node.id, column, finding_type, max_depth
        )
        
        if not affected:
            report.is_isolated = True
            # Build minimal graph with just the source
            report.nodes = [self._build_source_node(source_node, column, finding_type, finding_severity)]
            return report
        
        # Build affected columns list
        affected_columns = []
        affected_tables = set()
        owners = set()
        dashboard_count = 0
        
        for target_table, target_column, distance, path, transformation, transform_type in affected:
            node = self._find_node(target_table)
            if not node:
                continue
            
            criticality = node.criticality or "medium"
            node_type = node.node_type.value if node.node_type else "table"
            owner = node.owner
            
            # Generate impact reason specific to finding type and transformation
            impact_reason = self._generate_impact_reason(
                finding_type, column, target_column, transform_type, target_table
            )
            
            affected_columns.append(AffectedColumn(
                table=target_table,
                column=target_column,
                distance=distance,
                criticality=criticality,
                node_type=node_type,
                owner=owner,
                impact_reason=impact_reason,
                transformation=transformation,
                transformation_type=transform_type,
                path=path,
            ))
            
            affected_tables.add(target_table)
            if owner:
                owners.add(owner)
            if node_type in ("dashboard", "report"):
                dashboard_count += 1
        
        # Sort by criticality then distance
        criticality_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        affected_columns.sort(
            key=lambda x: (criticality_order.get(x.criticality, 2), x.distance)
        )
        
        report.affected_columns = affected_columns
        
        # Build summary
        report.summary = ImpactSummary(
            total_affected_tables=len(affected_tables),
            total_affected_columns=len(affected_columns),
            total_affected_dashboards=dashboard_count,
            critical_count=sum(1 for ac in affected_columns if ac.criticality == "critical"),
            high_count=sum(1 for ac in affected_columns if ac.criticality == "high"),
            medium_count=sum(1 for ac in affected_columns if ac.criticality == "medium"),
            low_count=sum(1 for ac in affected_columns if ac.criticality == "low"),
            affected_teams=list(owners),
            max_distance=max((ac.distance for ac in affected_columns), default=0),
        )
        
        # Build graph for visualization
        report.nodes, report.edges = self._build_graph_data(
            source_node, column, finding_type, finding_severity, affected_columns
        )
        
        return report
    
    def _find_node(self, table: str) -> Optional[LineageNode]:
        """Find a node by table name (tries various matching strategies)."""
        table_lower = table.lower()
        
        # Direct match
        if table_lower in self.graph.nodes:
            return self.graph.nodes[table_lower]
        
        # Try without schema prefix
        for node_id, node in self.graph.nodes.items():
            if node_id.endswith(f".{table_lower}") or node_id == table_lower:
                return node
            if node.name and node.name.lower() == table_lower:
                return node
            if node.fqn and node.fqn.lower().endswith(table_lower):
                return node
        
        return None
    
    def _traverse_column_downstream(
        self,
        source_id: str,
        column: str,
        finding_type: str,
        max_depth: int,
    ) -> List[Tuple[str, str, int, List[str], Optional[str], str]]:
        """
        Traverse downstream following column dependencies.
        
        Returns list of (target_table, target_column, distance, path, transformation, transform_type)
        """
        results = []
        visited = set()  # (node_id, column) pairs to avoid cycles
        
        # Queue: (node_id, column, distance, path)
        queue = [(source_id, column.lower(), 0, [source_id])]
        
        while queue:
            current_id, current_column, distance, path = queue.pop(0)
            
            visit_key = (current_id, current_column)
            if visit_key in visited:
                continue
            visited.add(visit_key)
            
            # Check depth limit
            if distance >= max_depth:
                continue
            
            # Get edges from this node
            edges = self._edges_by_source.get(current_id, [])
            
            for edge in edges:
                # Find column mappings that involve our column
                target_columns = self._find_column_mappings(edge, current_column)
                
                # If no specific column mapping, check if there's a general dependency
                # (e.g., SELECT * or no column info available)
                if not target_columns and edge.columns:
                    # Check if edge has any column mappings at all
                    # If it has mappings but none match our column, skip this edge
                    continue
                elif not target_columns and not edge.columns:
                    # No column info - assume all columns flow through (conservative)
                    target_columns = [(current_column, edge.transformation, "SELECT")]
                
                for target_col, transformation, transform_type in target_columns:
                    target_node = self.graph.nodes.get(edge.target_id)
                    if not target_node:
                        continue
                    
                    new_path = path + [edge.target_id]
                    
                    # Add to results
                    results.append((
                        target_node.fqn or target_node.name,
                        target_col,
                        distance + 1,
                        new_path,
                        transformation,
                        transform_type,
                    ))
                    
                    # Continue traversal
                    queue.append((edge.target_id, target_col.lower(), distance + 1, new_path))
        
        return results
    
    def _find_column_mappings(
        self, 
        edge: LineageEdge, 
        source_column: str
    ) -> List[Tuple[str, Optional[str], str]]:
        """
        Find column mappings in an edge that involve the source column.
        
        Returns list of (target_column, transformation, transform_type)
        """
        results = []
        source_col_lower = source_column.lower()
        
        for mapping in edge.columns:
            source = mapping.get("source", "").lower()
            target = mapping.get("target", source_column)
            transform = mapping.get("transform") or edge.transformation
            
            if source == source_col_lower or source_col_lower in source:
                transform_type = self._detect_transformation_type(transform)
                results.append((target, transform, transform_type))
        
        # Also check if the column appears in the transformation SQL
        if edge.transformation and source_col_lower in edge.transformation.lower():
            # Column is used but might not have explicit mapping
            if not results:
                transform_type = self._detect_transformation_type(edge.transformation)
                results.append((source_column, edge.transformation, transform_type))
        
        return results
    
    def _detect_transformation_type(self, sql: Optional[str]) -> str:
        """Detect the type of transformation from SQL snippet."""
        if not sql:
            return "SELECT"
        
        sql_lower = sql.lower()
        
        for transform_type, patterns in TRANSFORMATION_PATTERNS.items():
            for pattern in patterns:
                if pattern in sql_lower:
                    return transform_type
        
        return "SELECT"
    
    def _get_propagation_explanation(self, finding_type: str, column: str) -> str:
        """Get finding-type-specific propagation explanation."""
        base_explanation = PROPAGATION_EXPLANATIONS.get(
            finding_type.lower(),
            f"Data quality issues in {column} will propagate to downstream assets, potentially causing incorrect results."
        )
        return base_explanation.replace("{column}", column)
    
    def _generate_impact_reason(
        self,
        finding_type: str,
        source_column: str,
        target_column: str,
        transform_type: str,
        target_table: str,
    ) -> str:
        """Generate specific impact reason for a downstream column."""
        finding_lower = finding_type.lower()
        
        if "null" in finding_lower:
            if transform_type == "JOIN":
                return f"JOIN on {source_column} will fail for NULL values, causing missing rows"
            elif transform_type == "AGGREGATE":
                return f"Aggregations on {target_column} will exclude NULL rows, skewing results"
            else:
                return f"NULL values will propagate to {target_column}"
        
        elif "outlier" in finding_lower or "anomaly" in finding_lower:
            if transform_type == "AGGREGATE":
                return f"AVG/SUM of {target_column} will be skewed by outlier values"
            else:
                return f"Outlier values will propagate through to {target_column}"
        
        elif "duplicate" in finding_lower:
            if transform_type == "JOIN":
                return f"Duplicate values will cause row multiplication in JOIN"
            else:
                return f"Duplicate values will propagate to {target_column}"
        
        elif "schema" in finding_lower:
            return f"Schema mismatch may cause transformation failure"
        
        elif "stale" in finding_lower or "fresh" in finding_lower:
            return f"Stale data will produce outdated {target_column} values"
        
        elif "negative" in finding_lower:
            if transform_type == "AGGREGATE":
                return f"Negative values will affect SUM/AVG calculations"
            else:
                return f"Unexpected negative values will propagate"
        
        else:
            return f"Data quality issue affects {target_column}"
    
    def _build_source_node(
        self,
        node: LineageNode,
        column: str,
        finding_type: str,
        finding_severity: str,
    ) -> Dict[str, Any]:
        """Build the source node data for visualization."""
        return {
            "id": node.id,
            "name": node.name or node.fqn,
            "fqn": node.fqn,
            "type": node.node_type.value if node.node_type else "table",
            "criticality": node.criticality or "medium",
            "owner": node.owner,
            "affected_column": column,
            "is_source": True,
            "finding_type": finding_type,
            "finding_severity": finding_severity,
            "distance": 0,
        }
    
    def _build_graph_data(
        self,
        source_node: LineageNode,
        source_column: str,
        finding_type: str,
        finding_severity: str,
        affected_columns: List[AffectedColumn],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Build nodes and edges data for visualization."""
        nodes = []
        edges = []
        seen_nodes = set()
        
        # Add source node
        nodes.append(self._build_source_node(
            source_node, source_column, finding_type, finding_severity
        ))
        seen_nodes.add(source_node.id)
        
        # Add affected nodes
        for ac in affected_columns:
            node = self._find_node(ac.table)
            if not node or node.id in seen_nodes:
                continue
            
            seen_nodes.add(node.id)
            nodes.append({
                "id": node.id,
                "name": node.name or node.fqn,
                "fqn": node.fqn,
                "type": ac.node_type,
                "criticality": ac.criticality,
                "owner": ac.owner,
                "affected_column": ac.column,
                "is_source": False,
                "impact_reason": ac.impact_reason,
                "distance": ac.distance,
            })
        
        # Build edges from paths
        seen_edges = set()
        for ac in affected_columns:
            for i in range(len(ac.path) - 1):
                source_id = ac.path[i]
                target_id = ac.path[i + 1]
                edge_key = f"{source_id}->{target_id}"
                
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                
                # Find the actual edge to get transformation info
                actual_edge = None
                for edge in self._edges_by_source.get(source_id, []):
                    if edge.target_id == target_id:
                        actual_edge = edge
                        break
                
                edges.append({
                    "id": edge_key,
                    "source": source_id,
                    "target": target_id,
                    "transformation_type": ac.transformation_type if i == len(ac.path) - 2 else "SELECT",
                    "transformation": actual_edge.transformation[:200] if actual_edge and actual_edge.transformation else None,
                    "target_criticality": ac.criticality if i == len(ac.path) - 2 else "medium",
                })
        
        return nodes, edges


def analyze_finding_column_impact(
    graph: LineageGraph,
    finding: Dict[str, Any],
) -> ColumnImpactReport:
    """
    Convenience function to analyze column impact for a finding.
    
    Args:
        graph: The lineage graph
        finding: Finding dict with table, column, finding_type, severity, etc.
        
    Returns:
        ColumnImpactReport with column-specific impact analysis
    """
    analyzer = ColumnImpactAnalyzer(graph)
    
    table = finding.get("table", "")
    column = finding.get("column", "")
    finding_type = finding.get("finding_type") or finding.get("scan_type", "unknown")
    severity = finding.get("severity", "medium")
    title = finding.get("title")
    
    # Extract value from title or description if available
    value = None
    description = finding.get("description", "")
    if "%" in description:
        # Try to extract percentage
        import re
        match = re.search(r'(\d+\.?\d*%)', description)
        if match:
            value = match.group(1)
    
    return analyzer.analyze_column_impact(
        table=table,
        column=column,
        finding_type=finding_type,
        finding_severity=severity,
        finding_title=title,
        finding_value=value,
    )
