"""
dbt Manifest Parser

Extracts lineage from dbt's manifest.json, including:
- Models and their dependencies
- Sources
- Tests
- Exposures (dashboards, reports)
- Seeds and snapshots
"""

import json
from typing import Dict, Any, Optional
from datetime import datetime
from .base import BaseParser
from ..graph import LineageGraph, LineageNode, LineageEdge, NodeType, EdgeType


class DbtManifestParser(BaseParser):
    """
    Parse dbt manifest.json to extract lineage.
    
    dbt provides the most accurate lineage for transformation layer.
    """
    
    PLATFORM = "dbt"
    DIALECT = "sql"  # Actual dialect depends on target
    
    def __init__(self, manifest_path: str = None, manifest_data: Dict = None,
                 target_dialect: str = "snowflake", **kwargs):
        super().__init__(**kwargs)
        self.manifest_path = manifest_path
        self.manifest_data = manifest_data
        self.target_dialect = target_dialect
        self.DIALECT = target_dialect
        
    def parse(self) -> LineageGraph:
        """Parse dbt manifest and build lineage graph."""
        try:
            # Load manifest
            if self.manifest_data:
                manifest = self.manifest_data
            elif self.manifest_path:
                with open(self.manifest_path, 'r') as f:
                    manifest = json.load(f)
            else:
                self.add_error("No manifest path or data provided")
                return self.graph
            
            # Parse sources first (they are the roots)
            self._parse_sources(manifest.get("sources", {}))
            
            # Parse seeds
            self._parse_seeds(manifest.get("nodes", {}))
            
            # Parse models
            self._parse_models(manifest.get("nodes", {}))
            
            # Parse snapshots
            self._parse_snapshots(manifest.get("nodes", {}))
            
            # Parse exposures (BI dashboards, etc.)
            self._parse_exposures(manifest.get("exposures", {}))
            
            # Parse tests (for test dependencies)
            self._parse_tests(manifest.get("nodes", {}))
            
            # Build edges from depends_on
            self._build_edges(manifest.get("nodes", {}), manifest.get("exposures", {}))
            
            # Compute depths
            self.graph.compute_depths()
            self.graph.built_at = datetime.utcnow()
            
            print(f"✅ dbt parser: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")
            
        except Exception as e:
            self.add_error(f"Failed to parse manifest: {e}")
        
        return self.graph
    
    def _parse_sources(self, sources: Dict[str, Any]) -> None:
        """Parse dbt sources (external data)."""
        for source_id, source in sources.items():
            fqn = self._get_source_fqn(source)
            
            node = self.create_table_node(
                fqn=fqn,
                database=source.get("database"),
                schema=source.get("schema"),
                table=source.get("identifier") or source.get("name"),
                node_type=NodeType.SOURCE,
                description=source.get("description"),
                owner=source.get("meta", {}).get("owner"),
                tags=source.get("tags", []),
                raw_metadata=source,
            )
            
            # Mark freshness expectations
            if source.get("freshness"):
                freshness = source["freshness"]
                if freshness.get("warn_after"):
                    hours = self._parse_freshness(freshness["warn_after"])
                    node.expected_freshness_hours = hours
            
            self.graph.add_node(node)
    
    def _parse_seeds(self, nodes: Dict[str, Any]) -> None:
        """Parse dbt seeds (CSV files)."""
        for node_id, node_data in nodes.items():
            if node_data.get("resource_type") != "seed":
                continue
            
            fqn = self._get_node_fqn(node_data)
            
            node = self.create_table_node(
                fqn=fqn,
                database=node_data.get("database"),
                schema=node_data.get("schema"),
                table=node_data.get("alias") or node_data.get("name"),
                node_type=NodeType.SEED,
                description=node_data.get("description"),
                owner=node_data.get("meta", {}).get("owner"),
                tags=node_data.get("tags", []),
                raw_metadata=node_data,
            )
            
            self.graph.add_node(node)
    
    def _parse_models(self, nodes: Dict[str, Any]) -> None:
        """Parse dbt models."""
        for node_id, node_data in nodes.items():
            if node_data.get("resource_type") != "model":
                continue
            
            fqn = self._get_node_fqn(node_data)
            
            # Determine node type based on materialization
            materialization = node_data.get("config", {}).get("materialized", "view")
            if materialization == "view":
                node_type = NodeType.VIEW
            elif materialization == "materialized_view":
                node_type = NodeType.MATERIALIZED_VIEW
            else:
                node_type = NodeType.MODEL
            
            # Extract columns if available
            columns = []
            for col_name, col_data in node_data.get("columns", {}).items():
                columns.append({
                    "name": col_name,
                    "description": col_data.get("description"),
                    "data_type": col_data.get("data_type"),
                    "tests": col_data.get("tests", []),
                })
            
            node = self.create_table_node(
                fqn=fqn,
                database=node_data.get("database"),
                schema=node_data.get("schema"),
                table=node_data.get("alias") or node_data.get("name"),
                node_type=node_type,
                description=node_data.get("description"),
                owner=node_data.get("meta", {}).get("owner"),
                tags=node_data.get("tags", []),
                columns=columns,
                raw_metadata=node_data,
            )
            
            # Check for criticality in meta
            meta = node_data.get("meta", {})
            if meta.get("criticality"):
                node.criticality = meta["criticality"]
            if meta.get("domain"):
                node.domain = meta["domain"]
            
            self.graph.add_node(node)
    
    def _parse_snapshots(self, nodes: Dict[str, Any]) -> None:
        """Parse dbt snapshots."""
        for node_id, node_data in nodes.items():
            if node_data.get("resource_type") != "snapshot":
                continue
            
            fqn = self._get_node_fqn(node_data)
            
            node = self.create_table_node(
                fqn=fqn,
                database=node_data.get("database"),
                schema=node_data.get("schema"),
                table=node_data.get("alias") or node_data.get("name"),
                node_type=NodeType.SNAPSHOT,
                description=node_data.get("description"),
                owner=node_data.get("meta", {}).get("owner"),
                tags=node_data.get("tags", []),
                raw_metadata=node_data,
            )
            
            self.graph.add_node(node)
    
    def _parse_exposures(self, exposures: Dict[str, Any]) -> None:
        """Parse dbt exposures (BI dashboards, ML models, etc.)."""
        for exposure_id, exposure_data in exposures.items():
            exposure_type = exposure_data.get("type", "dashboard")
            
            # Map exposure type to node type
            type_map = {
                "dashboard": NodeType.DASHBOARD,
                "notebook": NodeType.REPORT,
                "analysis": NodeType.REPORT,
                "ml": NodeType.MODEL_ARTIFACT,
                "application": NodeType.REPORT,
            }
            node_type = type_map.get(exposure_type, NodeType.REPORT)
            
            fqn = f"exposure.{exposure_data.get('name', exposure_id)}"
            node_id = self.generate_node_id(fqn)
            
            node = LineageNode(
                id=node_id,
                name=exposure_data.get("name", exposure_id),
                fqn=fqn,
                node_type=node_type,
                platform="dbt",
                description=exposure_data.get("description"),
                owner=exposure_data.get("owner", {}).get("name"),
                tags=exposure_data.get("tags", []),
                raw_metadata=exposure_data,
            )
            
            # Store depends_on for later edge creation
            node.raw_metadata["depends_on"] = exposure_data.get("depends_on", {})
            
            self.graph.add_node(node)
    
    def _parse_tests(self, nodes: Dict[str, Any]) -> None:
        """Parse dbt tests for dependency information."""
        # Tests don't become nodes, but we track their dependencies
        pass
    
    def _build_edges(self, nodes: Dict[str, Any], exposures: Dict[str, Any]) -> None:
        """Build edges from depends_on relationships."""
        
        # Process model dependencies
        for node_id, node_data in nodes.items():
            if node_data.get("resource_type") not in ("model", "snapshot", "seed"):
                continue
            
            target_fqn = self._get_node_fqn(node_data)
            target_id = self.generate_node_id(target_fqn)
            
            if target_id not in self.graph.nodes:
                continue
            
            depends_on = node_data.get("depends_on", {})
            
            # Process node dependencies
            for dep in depends_on.get("nodes", []):
                source_fqn = self._get_dependency_fqn(dep, nodes)
                if source_fqn:
                    source_id = self.generate_node_id(source_fqn)
                    if source_id in self.graph.nodes:
                        edge = self.create_edge(
                            source_id=source_id,
                            target_id=target_id,
                            edge_type=EdgeType.DERIVED_FROM,
                        )
                        self.graph.add_edge(edge)
        
        # Process exposure dependencies
        for exposure_id, exposure_data in exposures.items():
            fqn = f"exposure.{exposure_data.get('name', exposure_id)}"
            target_id = self.generate_node_id(fqn)
            
            if target_id not in self.graph.nodes:
                continue
            
            depends_on = exposure_data.get("depends_on", {})
            
            for dep in depends_on.get("nodes", []):
                source_fqn = self._get_dependency_fqn(dep, nodes)
                if source_fqn:
                    source_id = self.generate_node_id(source_fqn)
                    if source_id in self.graph.nodes:
                        edge = self.create_edge(
                            source_id=source_id,
                            target_id=target_id,
                            edge_type=EdgeType.READS_FROM,
                        )
                        self.graph.add_edge(edge)
    
    def _get_source_fqn(self, source: Dict[str, Any]) -> str:
        """Get FQN for a source."""
        database = source.get("database", "")
        schema = source.get("schema", "")
        table = source.get("identifier") or source.get("name", "")
        return self.normalize_fqn(database, schema, table)
    
    def _get_node_fqn(self, node: Dict[str, Any]) -> str:
        """Get FQN for a model/seed/snapshot."""
        database = node.get("database", "")
        schema = node.get("schema", "")
        table = node.get("alias") or node.get("name", "")
        return self.normalize_fqn(database, schema, table)
    
    def _get_dependency_fqn(self, dep_id: str, nodes: Dict[str, Any]) -> Optional[str]:
        """Get FQN for a dependency reference."""
        # dep_id format: model.project.name, source.project.name.table, etc.
        parts = dep_id.split(".")
        
        if parts[0] == "source":
            # source.project.source_name.table_name
            return None  # Sources are handled separately
        
        # Look up in nodes
        for node_id, node_data in nodes.items():
            if node_id == dep_id or node_data.get("unique_id") == dep_id:
                return self._get_node_fqn(node_data)
        
        return None
    
    def _parse_freshness(self, freshness: Dict[str, Any]) -> int:
        """Parse freshness config to hours."""
        count = freshness.get("count", 24)
        period = freshness.get("period", "hour")
        
        if period == "minute":
            return count / 60
        elif period == "hour":
            return count
        elif period == "day":
            return count * 24
        else:
            return count

