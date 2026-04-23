"""
Graph export in multiple formats.

Supports JSON, GraphML, and DOT (Graphviz) output with optional filtering.
"""

import json
from typing import Any, Dict, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from ..graph import LineageGraph
from .store import Filters


def _apply_filters(graph: LineageGraph, filters: Optional[Filters]) -> LineageGraph:
    """Return a filtered copy of the graph if filters are provided."""
    if not filters:
        return graph

    from .store import GraphStore
    store = GraphStore()
    store.graph = graph
    return store.subgraph(list(graph.nodes.keys()), depth=9999, filters=filters)


def export_json(graph: LineageGraph, filters: Optional[Filters] = None) -> str:
    """Export graph as JSON string."""
    g = _apply_filters(graph, filters)
    return g.to_json()


def export_graphml(graph: LineageGraph, filters: Optional[Filters] = None) -> str:
    """Export graph as GraphML XML string."""
    g = _apply_filters(graph, filters)

    root = Element("graphml")
    root.set("xmlns", "http://graphml.graphstruct.org/xmlns")

    # Declare attribute keys
    _add_key(root, "d_name", "node", "name", "string")
    _add_key(root, "d_fqn", "node", "fqn", "string")
    _add_key(root, "d_type", "node", "node_type", "string")
    _add_key(root, "d_platform", "node", "platform", "string")
    _add_key(root, "d_domain", "node", "platform_domain", "string")
    _add_key(root, "d_kind", "node", "asset_kind", "string")
    _add_key(root, "d_edge_type", "edge", "edge_type", "string")
    _add_key(root, "d_level", "edge", "lineage_level", "string")
    _add_key(root, "d_confidence", "edge", "confidence", "double")

    graph_el = SubElement(root, "graph")
    graph_el.set("id", "lineage")
    graph_el.set("edgedefault", "directed")

    for node_id, node in g.nodes.items():
        n = SubElement(graph_el, "node")
        n.set("id", node_id)
        _add_data(n, "d_name", node.name)
        _add_data(n, "d_fqn", node.fqn)
        _add_data(n, "d_type", node.node_type.value)
        _add_data(n, "d_platform", node.platform or "")
        _add_data(n, "d_domain", node.platform_domain.value)
        _add_data(n, "d_kind", node.asset_kind.value)

    for edge_id, edge in g.edges.items():
        e = SubElement(graph_el, "edge")
        e.set("id", edge_id)
        e.set("source", edge.source_id)
        e.set("target", edge.target_id)
        _add_data(e, "d_edge_type", edge.edge_type.value)
        _add_data(e, "d_level", edge.lineage_level.value)
        _add_data(e, "d_confidence", str(edge.confidence))

    return tostring(root, encoding="unicode")


def export_dot(graph: LineageGraph, filters: Optional[Filters] = None) -> str:
    """Export graph as Graphviz DOT string."""
    g = _apply_filters(graph, filters)

    lines = ["digraph lineage {", '  rankdir=LR;', '  node [shape=box];']

    # Color by domain
    domain_colors = {
        "warehouse": "#4A90D9",
        "transform": "#7B68EE",
        "bi": "#FF8C00",
        "orchestration": "#2E8B57",
        "other": "#808080",
    }

    for node_id, node in g.nodes.items():
        label = node.name
        color = domain_colors.get(node.platform_domain.value, "#808080")
        safe_id = node_id.replace("-", "_")
        lines.append(
            f'  {safe_id} [label="{label}" '
            f'style=filled fillcolor="{color}" fontcolor=white '
            f'tooltip="{node.fqn}"];'
        )

    for edge_id, edge in g.edges.items():
        src = edge.source_id.replace("-", "_")
        tgt = edge.target_id.replace("-", "_")
        style = "solid" if edge.confidence >= 0.5 else "dashed"
        color = "black" if edge.lineage_level.value == "table" else "gray"
        if edge.lineage_level.value == "tool":
            color = "orange"
        lines.append(
            f'  {src} -> {tgt} [style={style} color="{color}" '
            f'label="{edge.edge_type.value}"];'
        )

    lines.append("}")
    return "\n".join(lines)


# ---- XML helpers ----

def _add_key(root: Element, id_: str, for_: str, name: str, type_: str) -> None:
    key = SubElement(root, "key")
    key.set("id", id_)
    key.set("for", for_)
    key.set("attr.name", name)
    key.set("attr.type", type_)


def _add_data(parent: Element, key: str, value: str) -> None:
    d = SubElement(parent, "data")
    d.set("key", key)
    d.text = value
