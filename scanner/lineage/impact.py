"""
Impact Analysis Engine
Analyzes the downstream impact of data quality issues.
"""

from typing import List, Dict, Set, Optional, Any
from dataclasses import dataclass, field
from .graph import LineageGraph, LineageNode


@dataclass
class AffectedTable:
    """A table affected by an upstream issue"""
    name: str
    distance: int  # Hops from the root cause
    criticality: str
    node_type: str
    path: List[str]  # Path from root cause to this table


@dataclass
class ImpactReport:
    """Complete impact analysis report"""
    root_cause: str  # The table with the issue
    root_cause_issue: Optional[str] = None  # Description of the issue
    
    # Affected tables
    affected_tables: List[AffectedTable] = field(default_factory=list)
    affected_count: int = 0
    
    # By criticality
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    
    # By distance
    direct_impact: List[str] = field(default_factory=list)  # Distance 1
    indirect_impact: List[str] = field(default_factory=list)  # Distance 2+
    
    # Critical paths (most important downstream paths)
    critical_paths: List[List[str]] = field(default_factory=list)
    
    # Business impact
    business_domains_affected: List[str] = field(default_factory=list)
    owners_to_notify: List[str] = field(default_factory=list)
    
    # Priority
    priority_score: float = 0.0
    priority_level: str = "medium"  # P0, P1, P2, P3
    priority_reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "root_cause_issue": self.root_cause_issue,
            "affected_count": self.affected_count,
            "affected_tables": [
                {
                    "name": t.name,
                    "distance": t.distance,
                    "criticality": t.criticality,
                    "path": t.path,
                }
                for t in self.affected_tables
            ],
            "by_criticality": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
            },
            "direct_impact": self.direct_impact,
            "indirect_impact": self.indirect_impact,
            "critical_paths": self.critical_paths,
            "business_domains_affected": self.business_domains_affected,
            "owners_to_notify": self.owners_to_notify,
            "priority": {
                "score": self.priority_score,
                "level": self.priority_level,
                "reason": self.priority_reason,
            }
        }


class ImpactAnalyzer:
    """
    Analyzes the impact of issues on downstream tables.
    
    Features:
    - Calculates all affected downstream tables
    - Identifies critical paths (high-value downstream)
    - Scores priority based on impact
    - Groups by business domain and owner
    """
    
    # Criticality weights for priority scoring
    CRITICALITY_WEIGHTS = {
        "critical": 10,
        "high": 5,
        "medium": 2,
        "low": 1,
    }
    
    # Distance decay - closer tables matter more
    DISTANCE_DECAY = 0.8
    
    def __init__(self, graph: LineageGraph):
        self.graph = graph
    
    def analyze_impact(
        self, 
        table_name: str, 
        issue_description: Optional[str] = None,
        max_depth: int = -1
    ) -> ImpactReport:
        """
        Analyze the downstream impact of an issue on a table.
        
        Args:
            table_name: The table with the issue
            issue_description: What's wrong with the table
            max_depth: Maximum depth to traverse (-1 for unlimited)
            
        Returns:
            ImpactReport with full analysis
        """
        report = ImpactReport(
            root_cause=table_name,
            root_cause_issue=issue_description
        )
        
        # Get all downstream tables with distances
        affected = self._get_affected_with_distances(table_name, max_depth)
        
        if not affected:
            report.priority_level = "P3"
            report.priority_reason = "No downstream dependencies"
            return report
        
        # Build affected tables list
        affected_tables = []
        for name, (distance, path) in affected.items():
            node = self.graph.get_node(name)
            criticality = node.criticality if node else "medium"
            node_type = node.node_type if node else "table"
            
            affected_tables.append(AffectedTable(
                name=name,
                distance=distance,
                criticality=criticality,
                node_type=node_type,
                path=path
            ))
        
        # Sort by criticality then distance
        criticality_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        affected_tables.sort(key=lambda x: (criticality_order.get(x.criticality, 2), x.distance))
        
        report.affected_tables = affected_tables
        report.affected_count = len(affected_tables)
        
        # Count by criticality
        for table in affected_tables:
            if table.criticality == "critical":
                report.critical_count += 1
            elif table.criticality == "high":
                report.high_count += 1
            elif table.criticality == "medium":
                report.medium_count += 1
            else:
                report.low_count += 1
        
        # Split direct vs indirect
        report.direct_impact = [t.name for t in affected_tables if t.distance == 1]
        report.indirect_impact = [t.name for t in affected_tables if t.distance > 1]
        
        # Find critical paths (paths to critical/high tables)
        report.critical_paths = self._find_critical_paths(table_name, affected_tables)
        
        # Collect business domains and owners
        domains = set()
        owners = set()
        for table in affected_tables:
            node = self.graph.get_node(table.name)
            if node:
                if node.business_domain:
                    domains.add(node.business_domain)
                if node.owner:
                    owners.add(node.owner)
        
        report.business_domains_affected = list(domains)
        report.owners_to_notify = list(owners)
        
        # Calculate priority
        self._calculate_priority(report)
        
        return report
    
    def _get_affected_with_distances(
        self, 
        start: str, 
        max_depth: int = -1
    ) -> Dict[str, tuple]:
        """
        Get all downstream tables with their distances and paths.
        
        Returns:
            Dict[table_name -> (distance, path)]
        """
        start_norm = start.lower()
        result = {}
        visited = set()
        queue = [(start_norm, 0, [start_norm])]
        
        while queue:
            current, distance, path = queue.pop(0)
            
            if current in visited:
                continue
            visited.add(current)
            
            # Skip the starting node itself
            if current != start_norm:
                result[current] = (distance, path)
            
            # Check depth limit
            if max_depth != -1 and distance >= max_depth:
                continue
            
            # Add children to queue
            for child in self.graph.get_direct_downstream(current):
                if child not in visited:
                    queue.append((child, distance + 1, path + [child]))
        
        return result
    
    def _find_critical_paths(
        self, 
        root: str, 
        affected_tables: List[AffectedTable]
    ) -> List[List[str]]:
        """Find paths to critical and high priority tables"""
        critical_paths = []
        
        for table in affected_tables:
            if table.criticality in ("critical", "high"):
                critical_paths.append(table.path)
        
        # Limit to top 5 critical paths
        return critical_paths[:5]
    
    def _calculate_priority(self, report: ImpactReport) -> None:
        """Calculate priority score and level"""
        score = 0.0
        
        # Score based on affected count
        score += min(report.affected_count * 2, 20)  # Cap at 20
        
        # Score based on criticality
        score += report.critical_count * self.CRITICALITY_WEIGHTS["critical"]
        score += report.high_count * self.CRITICALITY_WEIGHTS["high"]
        score += report.medium_count * self.CRITICALITY_WEIGHTS["medium"]
        score += report.low_count * self.CRITICALITY_WEIGHTS["low"]
        
        # Bonus for direct impact on critical tables
        for table in report.affected_tables:
            if table.distance == 1 and table.criticality == "critical":
                score += 10
        
        report.priority_score = score
        
        # Determine level
        if score >= 50 or report.critical_count >= 2:
            report.priority_level = "P0"
            report.priority_reason = f"Critical impact: {report.critical_count} critical tables affected, {report.affected_count} total downstream"
        elif score >= 30 or report.critical_count >= 1:
            report.priority_level = "P1"
            report.priority_reason = f"High impact: {report.critical_count} critical, {report.high_count} high priority tables affected"
        elif score >= 15 or report.high_count >= 2:
            report.priority_level = "P2"
            report.priority_reason = f"Medium impact: {report.affected_count} tables affected"
        else:
            report.priority_level = "P3"
            report.priority_reason = f"Low impact: {report.affected_count} tables affected, no critical dependencies"
    
    def compare_impacts(self, tables: List[str]) -> List[ImpactReport]:
        """
        Compare impact of multiple tables to help prioritize fixes.
        
        Returns:
            List of ImpactReports sorted by priority (highest first)
        """
        reports = []
        for table in tables:
            report = self.analyze_impact(table)
            reports.append(report)
        
        # Sort by priority score descending
        reports.sort(key=lambda r: r.priority_score, reverse=True)
        
        return reports
    
    def get_root_causes(self, affected_table: str) -> List[str]:
        """
        Find potential root causes for an affected table.
        Traces upstream to find source tables with no dependencies.
        """
        upstream = self.graph.get_upstream(affected_table)
        roots = []
        
        for table in upstream:
            if not self.graph.get_upstream(table):
                roots.append(table)
        
        return roots
    
    def deduplicate_findings(
        self, 
        findings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Deduplicate findings by identifying root causes.
        Instead of showing 50 symptoms, show the 3 root causes.
        
        Args:
            findings: List of findings with 'table' field
            
        Returns:
            Deduplicated findings with root causes prioritized
        """
        if not findings:
            return findings
        
        # Group findings by table
        table_findings = {}
        for finding in findings:
            table = finding.get('table', '')
            if table:
                table_findings[table.lower()] = finding
        
        # Find which findings are actually root causes
        root_causes = set()
        symptoms = set()
        
        for table in table_findings.keys():
            upstream_with_issues = set()
            for upstream in self.graph.get_upstream(table):
                if upstream in table_findings:
                    upstream_with_issues.add(upstream)
            
            if upstream_with_issues:
                # This table's issue is caused by upstream - it's a symptom
                symptoms.add(table)
            else:
                # No upstream issues - this is a root cause
                root_causes.add(table)
        
        # Enrich root cause findings with impact data
        result = []
        for table in root_causes:
            finding = table_findings[table].copy()
            impact = self.analyze_impact(table, finding.get('title'))
            
            finding['is_root_cause'] = True
            finding['impact'] = impact.to_dict()
            finding['downstream_affected'] = impact.affected_count
            finding['priority_level'] = impact.priority_level
            finding['priority_score'] = impact.priority_score
            
            result.append(finding)
        
        # Sort by priority
        result.sort(key=lambda f: f.get('priority_score', 0), reverse=True)
        
        # Add symptom count to each root cause
        for finding in result:
            table = finding.get('table', '').lower()
            downstream = self.graph.get_downstream(table)
            symptom_count = len([s for s in symptoms if s in downstream])
            finding['symptoms_caused'] = symptom_count
        
        return result


def analyze_finding_impact(
    graph: LineageGraph, 
    finding: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Convenience function to add impact analysis to a single finding.
    """
    table = finding.get('table', '')
    if not table:
        return finding
    
    analyzer = ImpactAnalyzer(graph)
    impact = analyzer.analyze_impact(table, finding.get('title'))
    
    finding_with_impact = finding.copy()
    finding_with_impact['impact'] = impact.to_dict()
    finding_with_impact['downstream_count'] = impact.affected_count
    finding_with_impact['priority_level'] = impact.priority_level
    
    return finding_with_impact

