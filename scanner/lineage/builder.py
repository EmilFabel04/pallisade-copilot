"""
Lineage Builder

Orchestrates multiple parsers to build a comprehensive lineage graph
across an organization's entire data stack.
"""

from typing import Dict, List, Any, Optional, Set
from datetime import datetime
import json
import logging

from .graph import LineageGraph, LineageNode, LineageEdge, NodeType
from .canonical import normalize_to_canonical_fqn
from .parsers import (
    DbtManifestParser,
    SnowflakeQueryParser,
    BigQueryParser,
    SQLServerParser,
    ForeignKeyParser,
    SQLLineageParser,
)


class LineageBuilder:
    """
    Builds a unified lineage graph from multiple sources.
    
    Sources:
    - dbt manifest (if available)
    - Database query history
    - Foreign key relationships
    - BI tool metadata
    - Custom integrations
    """
    
    def __init__(self):
        self.graph = LineageGraph()
        self.sources_used: List[str] = []
        self.errors: List[str] = []
    
    def build(self, integrations: List[Dict[str, Any]], 
              dbt_manifest: Dict[str, Any] = None) -> LineageGraph:
        """
        Build lineage graph from all available sources.
        
        Args:
            integrations: List of integration configs with connections
            dbt_manifest: Optional dbt manifest.json data
            
        Returns:
            Unified LineageGraph
        """
        print("🔗 Building lineage graph...")
        
        # Start with dbt if available (most accurate for transformations)
        if dbt_manifest:
            self._add_from_dbt(dbt_manifest)
        
        # Add from each integration
        for integration in integrations:
            self._add_from_integration(integration)
        
        # Merge duplicate nodes
        self._deduplicate_nodes()
        
        # Compute graph metrics
        self.graph.compute_depths()
        self.graph.built_at = datetime.utcnow()
        
        print(f"✅ Lineage complete: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")
        print(f"   Sources: {', '.join(self.sources_used)}")
        
        return self.graph
    
    def _add_from_dbt(self, manifest: Dict[str, Any]) -> None:
        """Add lineage from dbt manifest."""
        try:
            # Detect target dialect from manifest
            target_type = manifest.get("metadata", {}).get("adapter_type", "snowflake")
            
            parser = DbtManifestParser(
                manifest_data=manifest,
                target_dialect=target_type
            )
            dbt_graph = parser.parse()
            
            # Merge into main graph
            self._merge_graph(dbt_graph, "dbt")
            self.sources_used.append("dbt")
            self.errors.extend(parser.errors)
            
        except Exception as e:
            self.errors.append(f"dbt parsing failed: {e}")
    
    # Integration types that use engine live adapters
    _LIVE_ADAPTER_MAP = {
        "dagster": ("live_dagster", "dagster_config"),
        "prefect": ("live_prefect", "prefect_config"),
        "fivetran": ("live_fivetran", "fivetran_config"),
        "airbyte": ("live_airbyte", "airbyte_config"),
        "looker": ("live_looker", "looker_config"),
    }

    def _add_from_integration(self, integration: Dict[str, Any]) -> None:
        """Add lineage from a data integration."""
        int_type = integration.get("type", "").lower()
        connection = integration.get("connection")

        # Check if this integration type uses a live adapter
        if int_type in self._LIVE_ADAPTER_MAP:
            adapter_type, config_key = self._LIVE_ADAPTER_MAP[int_type]
            self._add_from_live_adapter(adapter_type, int_type, integration, config_key)
            return

        if not connection:
            return

        try:
            if int_type == "snowflake":
                parser = SnowflakeQueryParser(connection)
                graph = parser.parse()
                self._merge_graph(graph, "snowflake")
                self.sources_used.append("snowflake")

            elif int_type in ("sqlserver", "azure_sql", "azure_synapse"):
                parser = SQLServerParser(connection)
                graph = parser.parse()
                self._merge_graph(graph, "sqlserver")
                self.sources_used.append("sqlserver")

            elif int_type == "bigquery":
                config = integration.get("config", {})
                project_id = config.get("project_id") or config.get("project", "")
                # Use 'auto' region to try common regions for job history
                region = config.get("location") or config.get("region") or "auto"
                days_back = config.get("days_back", 30)

                # BigQueryAdapter wraps the raw client - extract it for the parser
                raw_client = getattr(connection, '_client', connection)

                # Extract selected datasets from config (multi-dataset support)
                config = integration.get("config", {})
                selected_datasets = config.get("datasets")  # Array of selected datasets
                if not selected_datasets and config.get("dataset"):
                    # Fallback to single dataset if datasets array not provided
                    selected_datasets = [config.get("dataset")]

                print(f"🔗 Building BigQuery lineage: project={project_id}, region={region}")
                if selected_datasets:
                    print(f"   Selected datasets: {selected_datasets}")

                parser = BigQueryParser(
                    raw_client,
                    project_id,
                    region=region,
                    days_back=days_back,
                    enable_data_catalog=True,
                    selected_datasets=selected_datasets,
                )
                graph = parser.parse()
                self._merge_graph(graph, "bigquery")
                self.sources_used.append("bigquery")
                print(f"   Found {len(graph.nodes)} nodes, {len(graph.edges)} edges")

            elif int_type in ("postgres", "redshift", "mysql"):
                # Use FK parser for basic lineage
                from ..utils.connectors import get_connection
                adapter = get_connection(int_type, integration.get("config", {}))
                parser = ForeignKeyParser(adapter)
                graph = parser.parse()
                self._merge_graph(graph, int_type)
                self.sources_used.append(int_type)

        except Exception as e:
            self.errors.append(f"{int_type} parsing failed: {e}")

    def _add_from_live_adapter(
        self,
        adapter_type: str,
        int_type: str,
        integration: Dict[str, Any],
        config_key: str,
    ) -> None:
        """
        Add lineage using an engine live adapter.

        Creates the adapter instance, runs discover_assets and extract_lineage,
        and merges the results into the main graph.
        """
        from .engine.adapter import create_default_registry

        logger = logging.getLogger(__name__)
        integration_id = integration.get("id")
        int_config = integration.get("config", {})
        namespace = int_config.get("namespace", int_type)

        adapter_config = {
            "namespace": namespace,
            "integration_id": integration_id,
            config_key: int_config,
            "client": integration.get("connection"),
        }

        # Propagate workspace/host config for Airbyte
        if int_type == "airbyte":
            adapter_config["workspace_id"] = int_config.get("workspace_id")

        registry = create_default_registry()
        adapter_id = f"{int_type}_{integration_id or 'default'}"

        try:
            adapter = registry.create(adapter_type, adapter_id)
        except ValueError as e:
            self.errors.append(f"Failed to create {adapter_type} adapter: {e}")
            return

        # Discover assets
        try:
            nodes = adapter.discover_assets(adapter_config)
        except Exception as e:
            self.errors.append(f"{int_type} discover_assets failed: {e}")
            nodes = []

        for node in nodes:
            if node.id not in self.graph.nodes:
                self.graph.add_node(node)
            else:
                self._merge_node_metadata(self.graph.nodes[node.id], node)

        # Extract lineage
        try:
            edges = adapter.extract_lineage(adapter_config)
        except Exception as e:
            self.errors.append(f"{int_type} extract_lineage failed: {e}")
            edges = []

        for edge in edges:
            if edge.id not in self.graph.edges:
                self.graph.add_edge(edge)

        self.sources_used.append(int_type)
        logger.info(
            f"Added {len(nodes)} nodes and {len(edges)} edges from {int_type} adapter"
        )
    
    def _merge_graph(self, source_graph: LineageGraph, source_name: str) -> None:
        """Merge a source graph into the main graph."""
        # Add nodes
        for node_id, node in source_graph.nodes.items():
            if node_id in self.graph.nodes:
                # Merge metadata
                existing = self.graph.nodes[node_id]
                self._merge_node_metadata(existing, node)
            else:
                self.graph.add_node(node)
        
        # Add edges
        for edge_id, edge in source_graph.edges.items():
            if edge_id not in self.graph.edges:
                self.graph.add_edge(edge)
    
    def _merge_node_metadata(self, existing: LineageNode, new: LineageNode) -> None:
        """Merge metadata from new node into existing."""
        # Prefer non-None values
        if new.description and not existing.description:
            existing.description = new.description
        if new.owner and not existing.owner:
            existing.owner = new.owner
        if new.row_count and not existing.row_count:
            existing.row_count = new.row_count
        if new.last_updated:
            if not existing.last_updated or new.last_updated > existing.last_updated:
                existing.last_updated = new.last_updated
        
        # Merge tags
        existing.tags = list(set(existing.tags + new.tags))
        
        # Merge columns (prefer more complete)
        if len(new.columns) > len(existing.columns):
            existing.columns = new.columns
    
    def _deduplicate_nodes(self) -> None:
        """
        Find and merge duplicate nodes (same table, different sources).

        Uses canonical FQN matching to identify the same physical table
        discovered by different tools (e.g., BigQuery table = dbt model target).
        """
        logger = logging.getLogger(__name__)

        # Group by canonical FQN for cross-tool matching
        by_canonical: Dict[str, List[str]] = {}

        for node_id, node in self.graph.nodes.items():
            # Build canonical FQN: warehouse_type:database.schema.table
            canonical = self._get_canonical_fqn(node)
            if canonical not in by_canonical:
                by_canonical[canonical] = []
            by_canonical[canonical].append(node_id)

        # Merge duplicates
        nodes_merged = 0
        for canonical_fqn, node_ids in by_canonical.items():
            if len(node_ids) > 1:
                # Sort by priority: warehouse > dbt > bi tools
                sorted_ids = sorted(node_ids, key=lambda nid: self._node_priority(nid))
                primary_id = sorted_ids[0]
                primary = self.graph.nodes[primary_id]

                for other_id in sorted_ids[1:]:
                    other = self.graph.nodes.get(other_id)
                    if not other:
                        continue

                    self._merge_node_metadata(primary, other)

                    # Track discovery sources
                    discovered_by: Set[str] = set(primary.raw_metadata.get("discovered_by", [primary.platform]))
                    discovered_by.add(other.platform)
                    primary.raw_metadata["discovered_by"] = list(discovered_by)

                    # Redirect edges
                    self._redirect_edges(other_id, primary_id)

                    # Remove duplicate
                    del self.graph.nodes[other_id]
                    nodes_merged += 1

        if nodes_merged > 0:
            logger.info(f"Deduplicated {nodes_merged} nodes using canonical FQN matching")

    def _get_canonical_fqn(self, node: LineageNode) -> str:
        """Get canonical FQN for a node for cross-tool matching."""
        # Determine warehouse type from dialect or platform
        warehouse_type = (node.dialect or node.platform or "unknown").lower()

        # Normalize warehouse type
        if warehouse_type == "dbt":
            # dbt nodes use the target warehouse dialect
            warehouse_type = node.raw_metadata.get("adapter_type", "bigquery").lower()

        # Build canonical FQN
        if node.database and node.schema:
            return normalize_to_canonical_fqn(
                warehouse_type, node.database, node.schema, node.name
            )
        elif node.fqn:
            # Parse FQN
            parts = node.fqn.replace("`", "").replace('"', "").lower().split(".")
            if len(parts) >= 3:
                return normalize_to_canonical_fqn(warehouse_type, parts[-3], parts[-2], parts[-1])
            elif len(parts) == 2:
                return normalize_to_canonical_fqn(warehouse_type, "", parts[0], parts[1])
            else:
                return normalize_to_canonical_fqn(warehouse_type, "", "", parts[0])

        # Fallback to original FQN-based key
        return f"{warehouse_type}:{node.fqn.lower()}"

    def _node_priority(self, node_id: str) -> int:
        """
        Get priority for a node (lower = higher priority).

        Warehouse nodes have highest priority (most accurate metadata),
        followed by dbt, then BI tools.
        """
        node = self.graph.nodes.get(node_id)
        if not node:
            return 99

        platform = (node.platform or "").lower()

        if platform in ("bigquery", "snowflake", "postgres", "redshift"):
            return 1  # Warehouse: highest priority
        elif platform == "dbt":
            return 2  # dbt: good metadata but less accurate row counts
        elif platform in ("looker", "tableau", "powerbi", "metabase"):
            return 3  # BI tools
        else:
            return 4  # Unknown
    
    def _redirect_edges(self, old_id: str, new_id: str) -> None:
        """Redirect edges from old node to new node."""
        edges_to_update = []
        
        for edge_id, edge in self.graph.edges.items():
            if edge.source_id == old_id or edge.target_id == old_id:
                edges_to_update.append((edge_id, edge))
        
        for edge_id, edge in edges_to_update:
            # Create new edge with updated IDs
            new_source = new_id if edge.source_id == old_id else edge.source_id
            new_target = new_id if edge.target_id == old_id else edge.target_id
            
            # Remove old edge
            del self.graph.edges[edge_id]
            
            # Update adjacency
            if old_id in self.graph._upstream:
                self.graph._upstream[new_id].update(self.graph._upstream[old_id])
            if old_id in self.graph._downstream:
                self.graph._downstream[new_id].update(self.graph._downstream[old_id])
    
    def to_json(self) -> str:
        """Export the graph as JSON."""
        return self.graph.to_json()
    
    def save(self, path: str) -> None:
        """Save the graph to a file."""
        with open(path, 'w') as f:
            f.write(self.to_json())
    
    @classmethod
    def load(cls, path: str) -> 'LineageBuilder':
        """Load a graph from a file."""
        builder = cls()
        with open(path, 'r') as f:
            data = json.load(f)
        builder.graph = LineageGraph.from_dict(data)
        return builder
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the lineage graph."""
        return {
            "node_count": len(self.graph.nodes),
            "edge_count": len(self.graph.edges),
            "sources_used": self.sources_used,
            "errors": self.errors,
            "by_type": self._count_by_type(),
            "by_platform": self._count_by_platform(),
            "root_count": len(self.graph.get_roots()),
            "leaf_count": len(self.graph.get_leaves()),
            "max_depth": max((n.depth for n in self.graph.nodes.values()), default=0),
            "built_at": self.graph.built_at.isoformat() if self.graph.built_at else None,
        }
    
    def _count_by_type(self) -> Dict[str, int]:
        """Count nodes by type."""
        counts: Dict[str, int] = {}
        for node in self.graph.nodes.values():
            type_name = node.node_type.value
            counts[type_name] = counts.get(type_name, 0) + 1
        return counts
    
    def _count_by_platform(self) -> Dict[str, int]:
        """Count nodes by platform."""
        counts: Dict[str, int] = {}
        for node in self.graph.nodes.values():
            platform = node.platform or "unknown"
            counts[platform] = counts.get(platform, 0) + 1
        return counts

