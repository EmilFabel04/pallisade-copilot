"""
Impact Analyzer and Root Cause Analyzer

These are the core intelligence components that:
1. Calculate blast radius when an issue is found
2. Identify root causes to deduplicate cascading issues
3. Prioritize findings based on downstream impact
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any, Tuple
from datetime import datetime
from .graph import LineageGraph, LineageNode, HealthStatus


@dataclass
class ImpactAssessment:
    """Assessment of an issue's impact across the data pipeline."""
    
    # The node with the issue
    source_node_id: str
    source_node_name: str
    
    # Direct downstream impact
    direct_downstream: List[str] = field(default_factory=list)
    
    # Total downstream impact (all levels)
    total_downstream: List[str] = field(default_factory=list)
    
    # Critical downstream nodes
    critical_downstream: List[str] = field(default_factory=list)
    
    # BI/reporting impact
    dashboards_affected: List[str] = field(default_factory=list)
    reports_affected: List[str] = field(default_factory=list)
    
    # ML/feature impact
    features_affected: List[str] = field(default_factory=list)
    models_affected: List[str] = field(default_factory=list)
    
    # Blast radius metrics
    blast_radius: int = 0  # Total nodes affected
    critical_blast_radius: int = 0  # Critical nodes affected
    max_depth: int = 0  # Furthest downstream depth
    
    # Business impact
    domains_affected: List[str] = field(default_factory=list)
    estimated_users_affected: int = 0
    
    # Risk score (0-100)
    impact_score: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_node_id": self.source_node_id,
            "source_node_name": self.source_node_name,
            "blast_radius": self.blast_radius,
            "critical_blast_radius": self.critical_blast_radius,
            "max_depth": self.max_depth,
            "direct_downstream_count": len(self.direct_downstream),
            "total_downstream_count": len(self.total_downstream),
            "dashboards_affected": self.dashboards_affected,
            "reports_affected": self.reports_affected,
            "domains_affected": self.domains_affected,
            "impact_score": self.impact_score,
        }


@dataclass
class RootCauseResult:
    """Result of root cause analysis."""
    
    # Is this finding a root cause or a symptom?
    is_root_cause: bool
    
    # If symptom, what's the root cause?
    root_cause_node_id: Optional[str] = None
    root_cause_finding_id: Optional[str] = None
    root_cause_description: Optional[str] = None
    
    # Path from root cause to this node
    cascade_path: List[str] = field(default_factory=list)
    cascade_depth: int = 0
    
    # Related findings that are also symptoms
    related_symptoms: List[str] = field(default_factory=list)
    
    # Confidence in this analysis
    confidence: float = 1.0
    
    # Explanation
    explanation: str = ""


class ImpactAnalyzer:
    """
    Analyzes the downstream impact of data issues.
    
    When a finding is detected, this calculates:
    - How many downstream tables are affected
    - Which critical assets are impacted
    - Which dashboards/reports will show bad data
    - Overall blast radius and risk score
    """
    
    def __init__(self, graph: LineageGraph):
        self.graph = graph
    
    def analyze(self, node_id: str) -> ImpactAssessment:
        """
        Analyze the downstream impact of an issue at the given node.
        
        Args:
            node_id: The node with the issue
            
        Returns:
            ImpactAssessment with full downstream analysis
        """
        if node_id not in self.graph.nodes:
            return ImpactAssessment(
                source_node_id=node_id,
                source_node_name="unknown"
            )
        
        node = self.graph.nodes[node_id]
        
        # Get all downstream nodes
        downstream = self.graph.get_downstream(node_id)
        direct_downstream = self.graph.get_direct_downstream(node_id)
        
        # Categorize downstream nodes
        critical_nodes = []
        dashboards = []
        reports = []
        features = []
        models = []
        domains = set()
        
        max_depth = 0
        
        for dn in downstream:
            # Track depth
            max_depth = max(max_depth, dn.depth - node.depth)
            
            # Categorize by criticality
            if dn.criticality in ("critical", "high"):
                critical_nodes.append(dn.id)
            
            # Categorize by type
            if dn.node_type.value == "dashboard":
                dashboards.append(dn.name)
            elif dn.node_type.value == "report":
                reports.append(dn.name)
            elif dn.node_type.value == "feature":
                features.append(dn.name)
            elif dn.node_type.value == "model_artifact":
                models.append(dn.name)
            
            # Track domains
            if dn.domain:
                domains.add(dn.domain)
        
        # Calculate impact score
        impact_score = self._calculate_impact_score(
            blast_radius=len(downstream),
            critical_count=len(critical_nodes),
            dashboard_count=len(dashboards),
            node_criticality=node.criticality
        )
        
        return ImpactAssessment(
            source_node_id=node_id,
            source_node_name=node.name,
            direct_downstream=[n.id for n in direct_downstream],
            total_downstream=[n.id for n in downstream],
            critical_downstream=critical_nodes,
            dashboards_affected=dashboards,
            reports_affected=reports,
            features_affected=features,
            models_affected=models,
            blast_radius=len(downstream),
            critical_blast_radius=len(critical_nodes),
            max_depth=max_depth,
            domains_affected=list(domains),
            impact_score=impact_score,
        )
    
    def _calculate_impact_score(self, blast_radius: int, critical_count: int,
                                dashboard_count: int, node_criticality: str) -> int:
        """Calculate a 0-100 impact score."""
        score = 0
        
        # Blast radius contribution (max 40 points)
        if blast_radius > 100:
            score += 40
        elif blast_radius > 50:
            score += 30
        elif blast_radius > 20:
            score += 20
        elif blast_radius > 5:
            score += 10
        elif blast_radius > 0:
            score += 5
        
        # Critical nodes contribution (max 30 points)
        score += min(critical_count * 5, 30)
        
        # Dashboard impact (max 20 points)
        score += min(dashboard_count * 5, 20)
        
        # Source criticality (max 10 points)
        criticality_scores = {"critical": 10, "high": 7, "medium": 4, "low": 1}
        score += criticality_scores.get(node_criticality, 4)
        
        return min(score, 100)
    
    def get_top_impacted_nodes(self, node_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get the most important downstream nodes affected by an issue.
        
        Prioritizes by criticality and type.
        """
        downstream = self.graph.get_downstream(node_id)
        
        # Score each downstream node
        scored = []
        for node in downstream:
            score = 0
            
            # Criticality
            if node.criticality == "critical":
                score += 100
            elif node.criticality == "high":
                score += 50
            elif node.criticality == "medium":
                score += 20
            
            # Type priority
            type_scores = {
                "dashboard": 80,
                "report": 60,
                "model_artifact": 70,
                "feature": 50,
                "table": 20,
                "view": 15,
                "model": 30,
            }
            score += type_scores.get(node.node_type.value, 10)
            
            # Depth penalty (closer = more important)
            score -= (node.depth * 2)
            
            scored.append((node, score))
        
        # Sort by score and return top N
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return [
            {
                "id": node.id,
                "name": node.name,
                "type": node.node_type.value,
                "criticality": node.criticality,
                "domain": node.domain,
                "impact_score": score,
            }
            for node, score in scored[:limit]
        ]


class RootCauseAnalyzer:
    """
    Identifies root causes of data issues to deduplicate cascading findings.
    
    When multiple findings are detected across the pipeline, this:
    1. Identifies which issues are root causes vs symptoms
    2. Groups related findings together
    3. Surfaces only the root cause to the user
    4. Tracks the cascade for context
    """
    
    def __init__(self, graph: LineageGraph):
        self.graph = graph
        self.findings_by_node: Dict[str, List[Dict]] = {}
    
    def register_finding(self, node_id: str, finding: Dict[str, Any]) -> None:
        """Register a finding for root cause analysis."""
        if node_id not in self.findings_by_node:
            self.findings_by_node[node_id] = []
        self.findings_by_node[node_id].append(finding)
    
    def analyze(self, finding: Dict[str, Any]) -> RootCauseResult:
        """
        Analyze whether a finding is a root cause or symptom.
        
        Args:
            finding: The finding to analyze
            
        Returns:
            RootCauseResult indicating if this is root cause or symptom
        """
        node_id = finding.get("node_id") or self._get_node_id(finding.get("table", ""))
        finding_type = finding.get("findingType") or finding.get("type", "")
        
        if node_id not in self.graph.nodes:
            # Can't analyze without lineage
            return RootCauseResult(
                is_root_cause=True,
                explanation="Node not in lineage graph, assuming root cause"
            )
        
        # Look for upstream issues of the same type
        upstream_nodes = self.graph.get_upstream(node_id)
        
        for upstream in upstream_nodes:
            # Check if upstream has the same type of issue
            upstream_findings = self.findings_by_node.get(upstream.id, [])
            
            for uf in upstream_findings:
                uf_type = uf.get("findingType") or uf.get("type", "")
                
                if self._are_related_findings(finding_type, uf_type):
                    # This finding might be caused by upstream
                    path = self.graph.get_path(upstream.id, node_id)
                    
                    return RootCauseResult(
                        is_root_cause=False,
                        root_cause_node_id=upstream.id,
                        root_cause_finding_id=uf.get("id"),
                        root_cause_description=f"Issue in {upstream.name}: {uf.get('title', 'Unknown issue')}",
                        cascade_path=[n.id for n in (path or [])],
                        cascade_depth=len(path or []) - 1,
                        confidence=self._calculate_confidence(finding_type, uf_type, path),
                        explanation=f"This issue appears to be caused by {uf_type} in upstream table {upstream.name}"
                    )
        
        # No upstream issues found - this is a root cause
        return RootCauseResult(
            is_root_cause=True,
            explanation="No related upstream issues found"
        )
    
    def analyze_all(self, findings: List[Dict[str, Any]]) -> Dict[str, RootCauseResult]:
        """
        Analyze all findings and identify root causes.
        
        Returns a mapping of finding_id -> RootCauseResult
        """
        # First, register all findings
        for finding in findings:
            node_id = finding.get("node_id") or self._get_node_id(finding.get("table", ""))
            self.register_finding(node_id, finding)
        
        # Then analyze each
        results = {}
        for finding in findings:
            finding_id = finding.get("id", str(hash(str(finding))))
            results[finding_id] = self.analyze(finding)
        
        # Update related symptoms
        self._link_related_symptoms(findings, results)
        
        return results
    
    def deduplicate_findings(self, findings: List[Dict[str, Any]]) -> Tuple[List[Dict], List[Dict]]:
        """
        Deduplicate findings by root cause.
        
        Returns:
            (root_cause_findings, symptom_findings)
        """
        analysis = self.analyze_all(findings)
        
        root_causes = []
        symptoms = []
        
        for finding in findings:
            finding_id = finding.get("id", str(hash(str(finding))))
            result = analysis.get(finding_id)
            
            if result and result.is_root_cause:
                # Add cascade info to root cause
                finding_with_cascade = finding.copy()
                finding_with_cascade["cascade_count"] = len(result.related_symptoms)
                finding_with_cascade["is_root_cause"] = True
                root_causes.append(finding_with_cascade)
            else:
                # Mark as symptom
                symptom = finding.copy()
                symptom["is_root_cause"] = False
                symptom["root_cause_id"] = result.root_cause_finding_id if result else None
                symptom["cascade_info"] = result.to_dict() if result else None
                symptoms.append(symptom)
        
        return root_causes, symptoms
    
    def _get_node_id(self, table_fqn: str) -> str:
        """Get node ID from table FQN."""
        import hashlib
        return hashlib.md5(f"unknown:{table_fqn}".encode()).hexdigest()[:16]
    
    def _are_related_findings(self, type1: str, type2: str) -> bool:
        """Check if two finding types are related (could cascade)."""
        # Same type always related
        if type1 == type2:
            return True
        
        # Define cascading relationships
        cascades = {
            "stale": ["stale", "freshness", "missing_data"],
            "freshness": ["stale", "freshness", "missing_data"],
            "missing_data": ["stale", "null_rate", "missing_data"],
            "null_rate": ["missing_data", "null_rate"],
            "schema_change": ["schema_change", "type_mismatch"],
            "pipeline_failure": ["stale", "freshness", "missing_data", "pipeline_failure"],
        }
        
        # Check if type1's issues can cause type2
        return type2 in cascades.get(type1, [])
    
    def _calculate_confidence(self, finding_type: str, upstream_type: str, 
                             path: Optional[List[LineageNode]]) -> float:
        """Calculate confidence that upstream issue caused this finding."""
        confidence = 0.5  # Base confidence
        
        # Same type = high confidence
        if finding_type == upstream_type:
            confidence += 0.4
        else:
            confidence += 0.2
        
        # Shorter path = higher confidence
        if path:
            path_length = len(path) - 1
            if path_length <= 1:
                confidence += 0.1
            elif path_length <= 3:
                confidence += 0.05
        
        return min(confidence, 1.0)
    
    def _link_related_symptoms(self, findings: List[Dict], 
                               results: Dict[str, RootCauseResult]) -> None:
        """Link symptoms to their root cause."""
        # Group by root cause
        by_root_cause: Dict[str, List[str]] = {}
        
        for finding in findings:
            finding_id = finding.get("id", str(hash(str(finding))))
            result = results.get(finding_id)
            
            if result and not result.is_root_cause and result.root_cause_finding_id:
                root_id = result.root_cause_finding_id
                if root_id not in by_root_cause:
                    by_root_cause[root_id] = []
                by_root_cause[root_id].append(finding_id)
        
        # Update root causes with their symptoms
        for root_id, symptom_ids in by_root_cause.items():
            if root_id in results:
                results[root_id].related_symptoms = symptom_ids

