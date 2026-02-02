"""
Finding Deduplicator

This is the key component that prevents showing 400 findings when
one upstream table has an issue.

It uses lineage to:
1. Identify root causes
2. Group related findings
3. Create smart summaries
4. Track cascade impact
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any, Tuple
from datetime import datetime
from .graph import LineageGraph, LineageNode, NodeType
from .analyzer import ImpactAnalyzer, RootCauseAnalyzer


@dataclass
class DeduplicatedFinding:
    """A finding that may represent multiple cascading issues."""
    
    # Core finding info
    id: str
    finding_type: str
    severity: str
    title: str
    description: str
    
    # Source info
    table: str
    column: Optional[str] = None
    node_id: Optional[str] = None
    
    # Root cause info
    is_root_cause: bool = True
    root_cause_id: Optional[str] = None
    
    # Cascade info (if this is a root cause)
    cascade_count: int = 0
    affected_tables: List[str] = field(default_factory=list)
    affected_dashboards: List[str] = field(default_factory=list)
    
    # Impact
    blast_radius: int = 0
    impact_score: int = 0
    
    # Original finding data
    original_finding: Dict[str, Any] = field(default_factory=dict)
    
    # Related findings (if root cause)
    related_findings: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "findingType": self.finding_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "table": self.table,
            "column": self.column,
            "isRootCause": self.is_root_cause,
            "rootCauseId": self.root_cause_id,
            "cascadeCount": self.cascade_count,
            "affectedTables": self.affected_tables,
            "affectedDashboards": self.affected_dashboards,
            "blastRadius": self.blast_radius,
            "impactScore": self.impact_score,
            "relatedFindingsCount": len(self.related_findings),
        }


class FindingDeduplicator:
    """
    Deduplicates findings using lineage-aware root cause analysis.
    
    Example:
        If table A is stale and tables B, C, D depend on A,
        instead of showing 4 "stale" findings, we show:
        
        "Table A is stale (impacts 3 downstream tables)"
        
        With expandable details showing B, C, D.
    """
    
    def __init__(self, graph: LineageGraph):
        self.graph = graph
        self.impact_analyzer = ImpactAnalyzer(graph)
        self.root_cause_analyzer = RootCauseAnalyzer(graph)
    
    def deduplicate(self, findings: List[Dict[str, Any]], 
                   show_symptoms: bool = False) -> List[DeduplicatedFinding]:
        """
        Deduplicate findings by root cause.
        
        Args:
            findings: List of raw findings
            show_symptoms: If True, include symptom findings (collapsed)
            
        Returns:
            List of DeduplicatedFinding objects
        """
        if not findings:
            return []
        
        # First, map findings to nodes
        for finding in findings:
            node_id = self._get_node_id(finding)
            finding["node_id"] = node_id
        
        # Run root cause analysis
        root_causes, symptoms = self.root_cause_analyzer.deduplicate_findings(findings)
        
        # Build deduplicated findings
        result = []
        
        for finding in root_causes:
            deduped = self._create_deduplicated_finding(finding, symptoms)
            result.append(deduped)
        
        if show_symptoms:
            for finding in symptoms:
                deduped = self._create_symptom_finding(finding)
                result.append(deduped)
        
        # Sort by impact score (most impactful first)
        result.sort(key=lambda f: f.impact_score, reverse=True)
        
        return result
    
    def summarize(self, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create a summary of findings with deduplication.
        
        Returns a summary showing:
        - Total raw findings
        - Deduplicated count (root causes only)
        - Breakdown by type
        - Top impacted assets
        """
        deduped = self.deduplicate(findings)
        
        # Count by type
        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        
        for f in deduped:
            by_type[f.finding_type] = by_type.get(f.finding_type, 0) + 1
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        
        # Total cascade
        total_cascade = sum(f.cascade_count for f in deduped)
        
        # Top impacted
        top_impacted = sorted(deduped, key=lambda f: f.blast_radius, reverse=True)[:5]
        
        return {
            "raw_count": len(findings),
            "deduplicated_count": len(deduped),
            "reduction_percent": round((1 - len(deduped) / len(findings)) * 100, 1) if findings else 0,
            "total_cascade": total_cascade,
            "by_type": by_type,
            "by_severity": by_severity,
            "top_impacted": [f.to_dict() for f in top_impacted],
            "message": self._generate_summary_message(len(findings), len(deduped), total_cascade),
        }
    
    def get_cascade_details(self, root_cause_id: str, 
                           all_findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get detailed information about a cascade.
        
        Returns full info about all findings caused by a root cause.
        """
        # Find the root cause
        root_finding = next((f for f in all_findings if f.get("id") == root_cause_id), None)
        if not root_finding:
            return {"error": "Root cause not found"}
        
        node_id = root_finding.get("node_id") or self._get_node_id(root_finding)
        
        # Get impact assessment
        impact = self.impact_analyzer.analyze(node_id)
        
        # Get all downstream nodes with findings
        affected_findings = []
        for finding in all_findings:
            fn_node_id = finding.get("node_id") or self._get_node_id(finding)
            if fn_node_id in impact.total_downstream:
                affected_findings.append(finding)
        
        # Get cascade path for visualization
        downstream_nodes = self.graph.get_downstream(node_id, depth=3)
        cascade_tree = self._build_cascade_tree(node_id, downstream_nodes)
        
        return {
            "root_cause": root_finding,
            "impact": impact.to_dict(),
            "affected_findings": affected_findings,
            "cascade_tree": cascade_tree,
            "total_affected": len(impact.total_downstream),
            "dashboards_at_risk": impact.dashboards_affected,
            "domains_affected": impact.domains_affected,
        }
    
    def _get_node_id(self, finding: Dict[str, Any]) -> Optional[str]:
        """Get or generate node ID for a finding."""
        if finding.get("node_id"):
            return finding["node_id"]
        
        table = finding.get("table", "")
        if not table:
            return None
        
        # Try to find in graph
        for node_id, node in self.graph.nodes.items():
            if node.fqn.lower() == table.lower() or node.name.lower() == table.lower():
                return node_id
        
        # Generate ID
        import hashlib
        return hashlib.md5(f"unknown:{table}".encode()).hexdigest()[:16]
    
    def _create_deduplicated_finding(self, finding: Dict[str, Any],
                                    all_symptoms: List[Dict[str, Any]]) -> DeduplicatedFinding:
        """Create a deduplicated finding with cascade info."""
        node_id = finding.get("node_id")
        
        # Get related symptoms
        related = [s for s in all_symptoms 
                   if s.get("root_cause_id") == finding.get("id")]
        
        # Get impact assessment
        impact = None
        if node_id and node_id in self.graph.nodes:
            impact = self.impact_analyzer.analyze(node_id)
        
        # Enhance title if there's a cascade
        title = finding.get("title", "Unknown issue")
        if len(related) > 0:
            title = f"{title} (impacts {len(related)} downstream tables)"
        
        return DeduplicatedFinding(
            id=finding.get("id", ""),
            finding_type=finding.get("findingType") or finding.get("type", "unknown"),
            severity=finding.get("severity", "medium"),
            title=title,
            description=finding.get("description", ""),
            table=finding.get("table", ""),
            column=finding.get("column"),
            node_id=node_id,
            is_root_cause=True,
            cascade_count=len(related),
            affected_tables=[s.get("table", "") for s in related],
            affected_dashboards=impact.dashboards_affected if impact else [],
            blast_radius=impact.blast_radius if impact else 0,
            impact_score=impact.impact_score if impact else 0,
            original_finding=finding,
            related_findings=related,
        )
    
    def _create_symptom_finding(self, finding: Dict[str, Any]) -> DeduplicatedFinding:
        """Create a finding marked as symptom."""
        cascade_info = finding.get("cascade_info", {})
        
        return DeduplicatedFinding(
            id=finding.get("id", ""),
            finding_type=finding.get("findingType") or finding.get("type", "unknown"),
            severity=finding.get("severity", "medium"),
            title=finding.get("title", "Unknown issue"),
            description=finding.get("description", ""),
            table=finding.get("table", ""),
            column=finding.get("column"),
            node_id=finding.get("node_id"),
            is_root_cause=False,
            root_cause_id=finding.get("root_cause_id"),
            cascade_count=0,
            blast_radius=0,
            impact_score=0,
            original_finding=finding,
        )
    
    def _build_cascade_tree(self, root_id: str, 
                           downstream: List[LineageNode]) -> Dict[str, Any]:
        """Build a tree structure for cascade visualization."""
        if root_id not in self.graph.nodes:
            return {}
        
        root = self.graph.nodes[root_id]
        
        def build_node(node: LineageNode, depth: int = 0) -> Dict[str, Any]:
            children = []
            if depth < 3:  # Limit depth
                direct_downstream = self.graph.get_direct_downstream(node.id)
                for child in direct_downstream:
                    if child.id in [n.id for n in downstream]:
                        children.append(build_node(child, depth + 1))
            
            return {
                "id": node.id,
                "name": node.name,
                "type": node.node_type.value,
                "health": node.health_status.value,
                "children": children,
            }
        
        return build_node(root)
    
    def _generate_summary_message(self, raw_count: int, deduped_count: int,
                                  cascade_count: int) -> str:
        """Generate a human-readable summary message."""
        if raw_count == deduped_count:
            return f"Found {raw_count} independent issues"
        
        reduction = raw_count - deduped_count
        return (
            f"Found {raw_count} total issues, consolidated to {deduped_count} root causes "
            f"({reduction} are cascade effects from upstream issues)"
        )


class SmartFindingProcessor:
    """
    High-level processor that combines deduplication with prioritization.
    
    This is what should be called after each scan to:
    1. Deduplicate cascading issues
    2. Prioritize by impact
    3. Enrich with lineage context
    4. Generate actionable insights
    """
    
    def __init__(self, graph: LineageGraph):
        self.graph = graph
        self.deduplicator = FindingDeduplicator(graph)
        self.impact_analyzer = ImpactAnalyzer(graph)
    
    def process(self, raw_findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process raw findings into smart, deduplicated results.
        
        Returns:
            {
                "findings": [...],  # Deduplicated findings
                "summary": {...},   # Overall summary
                "insights": [...],  # AI-generated insights
                "actions": [...],   # Recommended actions
            }
        """
        # Deduplicate
        deduped = self.deduplicator.deduplicate(raw_findings)
        summary = self.deduplicator.summarize(raw_findings)
        
        # Generate insights
        insights = self._generate_insights(deduped, summary)
        
        # Generate recommended actions
        actions = self._generate_actions(deduped)
        
        return {
            "findings": [f.to_dict() for f in deduped],
            "summary": summary,
            "insights": insights,
            "actions": actions,
            "raw_count": len(raw_findings),
            "processed_count": len(deduped),
        }
    
    def _generate_insights(self, findings: List[DeduplicatedFinding],
                          summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate insights about the findings."""
        insights = []
        
        # Cascade insight
        if summary.get("total_cascade", 0) > 0:
            insights.append({
                "type": "cascade",
                "title": "Cascading Issues Detected",
                "description": (
                    f"{summary['total_cascade']} issues are symptoms of upstream problems. "
                    f"Focus on fixing the {summary['deduplicated_count']} root causes."
                ),
                "priority": "high",
            })
        
        # High impact insight
        high_impact = [f for f in findings if f.impact_score > 70]
        if high_impact:
            insights.append({
                "type": "impact",
                "title": f"{len(high_impact)} High-Impact Issues",
                "description": (
                    f"These issues affect critical downstream assets. "
                    f"Priority tables: {', '.join(f.table for f in high_impact[:3])}"
                ),
                "priority": "critical",
            })
        
        # Dashboard impact
        total_dashboards = set()
        for f in findings:
            total_dashboards.update(f.affected_dashboards)
        
        if total_dashboards:
            insights.append({
                "type": "bi_impact",
                "title": f"{len(total_dashboards)} Dashboards at Risk",
                "description": (
                    f"These dashboards may show incorrect data: "
                    f"{', '.join(list(total_dashboards)[:5])}"
                ),
                "priority": "high",
            })
        
        return insights
    
    def _generate_actions(self, findings: List[DeduplicatedFinding]) -> List[Dict[str, Any]]:
        """Generate recommended actions."""
        actions = []
        
        # Sort by impact
        sorted_findings = sorted(findings, key=lambda f: f.impact_score, reverse=True)
        
        for i, finding in enumerate(sorted_findings[:5]):
            actions.append({
                "priority": i + 1,
                "finding_id": finding.id,
                "table": finding.table,
                "action": f"Fix {finding.finding_type} in {finding.table}",
                "reason": f"Impacts {finding.blast_radius} downstream assets",
                "severity": finding.severity,
            })
        
        return actions

