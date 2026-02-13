"""
Lineage Engine MCP Server — exposes GraphStore via MCP protocol.

This is the only custom MCP server we build. It wraps the Pallisade
lineage engine (GraphStore, LineageGraph) and exposes traversal,
blast radius, evidence explanation, and filtering as MCP tools.

Launched as a subprocess by MCPClientManager; receives the serialized
lineage graph via the PALLISADE_LINEAGE_GRAPH environment variable.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, TextContent, Tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graph reconstruction from serialized JSON
# ---------------------------------------------------------------------------

def _load_graph():
    """Load LineageGraph from environment variable."""
    # Import here to avoid import issues when running as subprocess
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    from lineage.graph import LineageGraph
    from lineage.engine.store import GraphStore

    graph_json = os.environ.get("PALLISADE_LINEAGE_GRAPH", "")
    if not graph_json:
        logger.warning("No lineage graph data provided")
        return LineageGraph(), GraphStore()

    try:
        graph_data = json.loads(graph_json)
        graph = LineageGraph.from_dict(graph_data)
        store = GraphStore()
        store.graph = graph
        logger.info(
            f"Loaded lineage graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges"
        )
        return graph, store
    except Exception as e:
        logger.error(f"Failed to load lineage graph: {e}")
        return LineageGraph(), GraphStore()


def _build_filters(arguments: Dict[str, Any]):
    """Build a Filters object from tool arguments."""
    from lineage.engine.store import Filters
    from lineage.graph import AssetKind, LineageLevel, LinePlane, PlatformDomain

    filters = Filters()

    if "min_confidence" in arguments:
        filters.min_confidence = float(arguments["min_confidence"])

    if "lineage_levels" in arguments:
        filters.lineage_levels = {
            LineageLevel(level) for level in arguments["lineage_levels"]
            if level in [e.value for e in LineageLevel]
        }

    if "systems" in arguments:
        filters.systems = set(arguments["systems"])

    if "platform_domains" in arguments:
        filters.platform_domains = {
            PlatformDomain(d) for d in arguments["platform_domains"]
            if d in [e.value for e in PlatformDomain]
        }

    if "asset_kinds" in arguments:
        filters.asset_kinds = {
            AssetKind(k) for k in arguments["asset_kinds"]
            if k in [e.value for e in AssetKind]
        }

    if "planes" in arguments:
        filters.planes = {
            LinePlane(p) for p in arguments["planes"]
            if p in [e.value for e in LinePlane]
        }

    return filters


def _node_to_dict(node) -> Dict[str, Any]:
    """Convert a LineageNode to a serializable dictionary."""
    return {
        "id": node.id,
        "name": node.name,
        "fqn": node.fqn,
        "node_type": node.node_type.value,
        "platform": node.platform,
        "database": node.database,
        "schema": node.schema,
        "platform_domain": node.platform_domain.value if hasattr(node, "platform_domain") else None,
        "asset_kind": node.asset_kind.value if hasattr(node, "asset_kind") else None,
        "description": node.description,
        "owner": node.owner,
        "tags": node.tags,
        "domain": node.domain,
        "criticality": node.criticality,
        "columns": node.columns[:20] if node.columns else [],  # Limit for token budget
        "row_count": node.row_count,
        "health_status": node.health_status.value if hasattr(node.health_status, "value") else str(node.health_status),
        "depth": node.depth,
        "upstream_count": node.upstream_count,
        "downstream_count": node.downstream_count,
    }


def _edge_to_dict(edge) -> Dict[str, Any]:
    """Convert a LineageEdge to a serializable dictionary."""
    result = {
        "id": edge.id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "edge_type": edge.edge_type.value,
        "confidence": edge.confidence,
        "discovered_from": edge.discovered_from,
    }
    if hasattr(edge, "lineage_level") and edge.lineage_level:
        result["lineage_level"] = edge.lineage_level.value
    if hasattr(edge, "plane") and edge.plane:
        result["plane"] = edge.plane.value
    if hasattr(edge, "evidence") and edge.evidence:
        result["evidence"] = [e.to_dict() for e in edge.evidence[:5]]
    if hasattr(edge, "column_mappings") and edge.column_mappings:
        result["column_mappings"] = [m.to_dict() for m in edge.column_mappings[:10]]
    return result


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="get_upstream",
        description="Get all upstream dependencies of a data asset. Supports depth control and filtering by confidence, lineage level, system, platform domain, and asset kind.",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "description": "The ID or FQN of the asset to trace upstream"},
                "depth": {"type": "integer", "description": "Max traversal depth (-1 for unlimited)", "default": -1},
                "min_confidence": {"type": "number", "description": "Minimum edge confidence (0.0-1.0)", "default": 0.0},
                "lineage_levels": {"type": "array", "items": {"type": "string", "enum": ["tool", "table", "column"]}, "description": "Filter by lineage level"},
                "systems": {"type": "array", "items": {"type": "string"}, "description": "Filter by system (snowflake, bigquery, dbt, airflow, etc.)"},
                "platform_domains": {"type": "array", "items": {"type": "string", "enum": ["warehouse", "transform", "orchestration", "bi", "ingestion", "catalog", "app", "other"]}, "description": "Filter by platform domain"},
            },
            "required": ["asset_id"],
        },
    ),
    Tool(
        name="get_downstream",
        description="Get all downstream dependents of a data asset. Supports the same filtering as get_upstream.",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "description": "The ID or FQN of the asset to trace downstream"},
                "depth": {"type": "integer", "description": "Max traversal depth (-1 for unlimited)", "default": -1},
                "min_confidence": {"type": "number", "description": "Minimum edge confidence (0.0-1.0)", "default": 0.0},
                "lineage_levels": {"type": "array", "items": {"type": "string", "enum": ["tool", "table", "column"]}, "description": "Filter by lineage level"},
                "systems": {"type": "array", "items": {"type": "string"}, "description": "Filter by system"},
                "platform_domains": {"type": "array", "items": {"type": "string", "enum": ["warehouse", "transform", "orchestration", "bi", "ingestion", "catalog", "app", "other"]}, "description": "Filter by platform domain"},
            },
            "required": ["asset_id"],
        },
    ),
    Tool(
        name="blast_radius",
        description="Compute the downstream blast radius of changing an asset. Returns total affected count and breakdown by asset kind and platform domain.",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "description": "The ID or FQN of the asset to analyze"},
                "min_confidence": {"type": "number", "description": "Minimum edge confidence", "default": 0.0},
            },
            "required": ["asset_id"],
        },
    ),
    Tool(
        name="explain_edge",
        description="Explain WHY a lineage edge exists — returns evidence, confidence score, provenance, and column mappings.",
        inputSchema={
            "type": "object",
            "properties": {
                "edge_id": {"type": "string", "description": "The ID of the edge to explain"},
            },
            "required": ["edge_id"],
        },
    ),
    Tool(
        name="get_subgraph",
        description="Extract a subgraph around one or more seed nodes, including both upstream and downstream neighbors.",
        inputSchema={
            "type": "object",
            "properties": {
                "seed_ids": {"type": "array", "items": {"type": "string"}, "description": "IDs of center nodes"},
                "depth": {"type": "integer", "description": "Traversal depth in each direction", "default": 2},
                "min_confidence": {"type": "number", "description": "Minimum edge confidence", "default": 0.0},
            },
            "required": ["seed_ids"],
        },
    ),
    Tool(
        name="get_stats",
        description="Get lineage coverage statistics: total nodes/edges, distribution by level/plane/system/domain/kind, confidence breakdown, and coverage percentages.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="search_nodes",
        description="Search for nodes by name pattern, asset kind, or platform domain.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name pattern to search for (case-insensitive substring match)"},
                "asset_kind": {"type": "string", "enum": ["table", "view", "model", "dataset", "dashboard", "job", "task", "file", "topic", "stream", "api", "unknown"], "description": "Filter by asset kind"},
                "platform_domain": {"type": "string", "enum": ["warehouse", "transform", "orchestration", "bi", "ingestion", "catalog", "app", "other"], "description": "Filter by platform domain"},
                "limit": {"type": "integer", "description": "Maximum results to return", "default": 20},
            },
        },
    ),
    Tool(
        name="get_node_details",
        description="Get full details for a specific node including columns, health status, metadata, and connection counts.",
        inputSchema={
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "The ID or FQN of the node"},
            },
            "required": ["node_id"],
        },
    ),
    Tool(
        name="trace_column_lineage",
        description="Trace column-level lineage for a specific table or model. Returns column mappings with confidence scores.",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "description": "The ID or FQN of the asset"},
                "column_name": {"type": "string", "description": "Optional: specific column to trace"},
                "direction": {"type": "string", "enum": ["upstream", "downstream", "both"], "default": "both", "description": "Direction to trace"},
            },
            "required": ["asset_id"],
        },
    ),
    Tool(
        name="get_path",
        description="Find the shortest path between two nodes in the lineage graph.",
        inputSchema={
            "type": "object",
            "properties": {
                "from_id": {"type": "string", "description": "Source node ID or FQN"},
                "to_id": {"type": "string", "description": "Target node ID or FQN"},
            },
            "required": ["from_id", "to_id"],
        },
    ),
]


async def run_server():
    """Main entry point for the lineage MCP server."""
    graph, store = _load_graph()
    server = Server("pallisade-lineage")

    def _resolve_node_id(id_or_fqn: str) -> Optional[str]:
        """Resolve a node ID or FQN to an actual node ID in the graph."""
        if id_or_fqn in graph.nodes:
            return id_or_fqn
        # Try FQN match
        for nid, node in graph.nodes.items():
            if node.fqn and node.fqn.lower() == id_or_fqn.lower():
                return nid
        # Try name suffix match
        for nid, node in graph.nodes.items():
            if node.name and node.name.lower() == id_or_fqn.lower():
                return nid
        # Try partial FQN match
        for nid, node in graph.nodes.items():
            if node.fqn and id_or_fqn.lower() in node.fqn.lower():
                return nid
        return None

    @server.list_tools()
    async def list_tools() -> list:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        try:
            if name == "get_upstream":
                asset_id = _resolve_node_id(arguments["asset_id"])
                if not asset_id:
                    return [TextContent(type="text", text=json.dumps({"error": f"Node not found: {arguments['asset_id']}"}))]
                depth = arguments.get("depth", -1)
                filters = _build_filters(arguments)
                nodes = store.get_upstream(asset_id, depth=depth, filters=filters)
                result = {
                    "asset_id": asset_id,
                    "upstream_count": len(nodes),
                    "upstream_nodes": [_node_to_dict(n) for n in nodes[:50]],
                }
                return [TextContent(type="text", text=json.dumps(result))]

            elif name == "get_downstream":
                asset_id = _resolve_node_id(arguments["asset_id"])
                if not asset_id:
                    return [TextContent(type="text", text=json.dumps({"error": f"Node not found: {arguments['asset_id']}"}))]
                depth = arguments.get("depth", -1)
                filters = _build_filters(arguments)
                nodes = store.get_downstream(asset_id, depth=depth, filters=filters)
                result = {
                    "asset_id": asset_id,
                    "downstream_count": len(nodes),
                    "downstream_nodes": [_node_to_dict(n) for n in nodes[:50]],
                }
                return [TextContent(type="text", text=json.dumps(result))]

            elif name == "blast_radius":
                asset_id = _resolve_node_id(arguments["asset_id"])
                if not asset_id:
                    return [TextContent(type="text", text=json.dumps({"error": f"Node not found: {arguments['asset_id']}"}))]
                filters = _build_filters(arguments)
                result = store.blast_radius(asset_id, filters=filters)
                return [TextContent(type="text", text=json.dumps(result))]

            elif name == "explain_edge":
                edge_id = arguments["edge_id"]
                result = store.explain_edge(edge_id)
                return [TextContent(type="text", text=json.dumps(result))]

            elif name == "get_subgraph":
                seed_ids = []
                for sid in arguments["seed_ids"]:
                    resolved = _resolve_node_id(sid)
                    if resolved:
                        seed_ids.append(resolved)
                if not seed_ids:
                    return [TextContent(type="text", text=json.dumps({"error": "No valid seed nodes found"}))]
                depth = arguments.get("depth", 2)
                filters = _build_filters(arguments)
                sub = store.subgraph(seed_ids, depth=depth, filters=filters)
                result = {
                    "nodes": [_node_to_dict(n) for n in sub.nodes.values()],
                    "edges": [_edge_to_dict(e) for e in sub.edges.values()],
                    "node_count": len(sub.nodes),
                    "edge_count": len(sub.edges),
                }
                return [TextContent(type="text", text=json.dumps(result))]

            elif name == "get_stats":
                stats = store.get_stats()
                return [TextContent(type="text", text=json.dumps(stats.to_dict()))]

            elif name == "search_nodes":
                query = arguments.get("query", "").lower()
                limit = arguments.get("limit", 20)
                results = []
                for node in graph.nodes.values():
                    if len(results) >= limit:
                        break
                    # Name/FQN match
                    if query and query not in (node.name or "").lower() and query not in (node.fqn or "").lower():
                        continue
                    # Asset kind filter
                    if "asset_kind" in arguments:
                        from lineage.graph import AssetKind
                        try:
                            if node.asset_kind != AssetKind(arguments["asset_kind"]):
                                continue
                        except ValueError:
                            pass
                    # Platform domain filter
                    if "platform_domain" in arguments:
                        from lineage.graph import PlatformDomain
                        try:
                            if node.platform_domain != PlatformDomain(arguments["platform_domain"]):
                                continue
                        except ValueError:
                            pass
                    results.append(_node_to_dict(node))

                return [TextContent(type="text", text=json.dumps({
                    "count": len(results),
                    "nodes": results,
                }))]

            elif name == "get_node_details":
                node_id = _resolve_node_id(arguments["node_id"])
                if not node_id:
                    return [TextContent(type="text", text=json.dumps({"error": f"Node not found: {arguments['node_id']}"}))]
                node = graph.nodes[node_id]
                details = _node_to_dict(node)
                # Include full columns for detail view
                details["columns"] = node.columns
                # Add connection info
                details["direct_upstream"] = [
                    {"id": n.id, "name": n.name, "fqn": n.fqn}
                    for n in graph.get_upstream(node_id, depth=1)
                ]
                details["direct_downstream"] = [
                    {"id": n.id, "name": n.name, "fqn": n.fqn}
                    for n in graph.get_downstream(node_id, depth=1)
                ]
                return [TextContent(type="text", text=json.dumps(details))]

            elif name == "trace_column_lineage":
                asset_id = _resolve_node_id(arguments["asset_id"])
                if not asset_id:
                    return [TextContent(type="text", text=json.dumps({"error": f"Node not found: {arguments['asset_id']}"}))]
                column_name = arguments.get("column_name")
                direction = arguments.get("direction", "both")

                column_edges = []
                for edge in graph.edges.values():
                    if not hasattr(edge, "lineage_level"):
                        continue
                    from lineage.graph import LineageLevel
                    if edge.lineage_level != LineageLevel.COLUMN:
                        continue

                    matches = False
                    if direction in ("upstream", "both") and edge.target_id == asset_id:
                        matches = True
                    if direction in ("downstream", "both") and edge.source_id == asset_id:
                        matches = True
                    if not matches:
                        continue

                    # Filter by specific column if requested
                    if column_name and hasattr(edge, "column_mappings"):
                        col_match = any(
                            column_name.lower() in (
                                (getattr(m, "source_column", "") or "").lower() +
                                (getattr(m, "target_column", "") or "").lower()
                            )
                            for m in edge.column_mappings
                        )
                        if not col_match:
                            continue

                    column_edges.append(_edge_to_dict(edge))

                return [TextContent(type="text", text=json.dumps({
                    "asset_id": asset_id,
                    "column_name": column_name,
                    "direction": direction,
                    "column_lineage_edges": column_edges,
                    "total": len(column_edges),
                }))]

            elif name == "get_path":
                from_id = _resolve_node_id(arguments["from_id"])
                to_id = _resolve_node_id(arguments["to_id"])
                if not from_id:
                    return [TextContent(type="text", text=json.dumps({"error": f"Source node not found: {arguments['from_id']}"}))]
                if not to_id:
                    return [TextContent(type="text", text=json.dumps({"error": f"Target node not found: {arguments['to_id']}"}))]

                path = graph.get_path(from_id, to_id)
                if path is None:
                    return [TextContent(type="text", text=json.dumps({
                        "from": from_id, "to": to_id,
                        "path": None, "message": "No path found between these nodes"
                    }))]

                return [TextContent(type="text", text=json.dumps({
                    "from": from_id,
                    "to": to_id,
                    "path_length": len(path),
                    "path": [_node_to_dict(n) for n in path],
                }))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        except Exception as e:
            logger.exception(f"Error in tool {name}")
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    @server.list_resources()
    async def list_resources() -> list:
        resources = [
            Resource(uri="lineage://stats", name="Lineage Statistics", description="Coverage and distribution statistics"),
            Resource(uri="lineage://roots", name="Root Nodes", description="All source/root nodes with no upstream"),
            Resource(uri="lineage://leaves", name="Leaf Nodes", description="All output/leaf nodes with no downstream"),
        ]
        # Add platform-specific resources
        for platform in graph._by_platform:
            count = len(graph._by_platform[platform])
            resources.append(Resource(
                uri=f"lineage://platforms/{platform}",
                name=f"{platform.title()} Nodes",
                description=f"{count} nodes from {platform}",
            ))
        return resources

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        uri_str = str(uri)
        if uri_str == "lineage://stats":
            stats = store.get_stats()
            return json.dumps(stats.to_dict(), indent=2)

        elif uri_str == "lineage://roots":
            roots = graph.get_roots()
            return json.dumps([_node_to_dict(n) for n in roots], indent=2)

        elif uri_str == "lineage://leaves":
            leaves = graph.get_leaves()
            return json.dumps([_node_to_dict(n) for n in leaves], indent=2)

        elif uri_str.startswith("lineage://platforms/"):
            platform = uri_str.split("/")[-1]
            node_ids = graph._by_platform.get(platform, set())
            nodes = [graph.nodes[nid] for nid in node_ids if nid in graph.nodes]
            return json.dumps([_node_to_dict(n) for n in nodes[:100]], indent=2)

        elif uri_str.startswith("lineage://nodes/"):
            node_id = uri_str.split("lineage://nodes/")[1]
            resolved = _resolve_node_id(node_id)
            if resolved and resolved in graph.nodes:
                return json.dumps(_node_to_dict(graph.nodes[resolved]), indent=2)
            return json.dumps({"error": f"Node not found: {node_id}"})

        return json.dumps({"error": f"Unknown resource: {uri_str}"})

    # Run the server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Entry point when run as python -m scanner.mcp.servers.lineage_server."""
    import asyncio
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
