"""
Lineage Engine CLI

Power-user command-line interface for building, querying, and debugging
the lineage graph.

Usage:
    python -m scanner.lineage.engine.cli build --config config.yml --out graph.json
    python -m scanner.lineage.engine.cli show <asset_id> --depth 3
    python -m scanner.lineage.engine.cli impact <asset_id> --downstream
    python -m scanner.lineage.engine.cli explain-edge <edge_id>
    python -m scanner.lineage.engine.cli stats
"""

import json
import sys
from pathlib import Path
from typing import Optional

try:
    import typer
except ImportError:
    # Fallback for environments without typer
    import argparse
    typer = None  # type: ignore

from ..graph import LineageGraph, LineageLevel
from .store import GraphStore, Filters
from .export import export_json, export_graphml, export_dot

if typer:
    app = typer.Typer(name="lineage", help="Lineage engine CLI")
else:
    app = None


def _build_store(config_path: str) -> GraphStore:
    """Build a GraphStore from a YAML config."""
    store = GraphStore()
    store.build_graph_from_yaml(config_path)
    return store


def _load_graph(graph_path: str) -> GraphStore:
    """Load a pre-built graph from JSON."""
    with open(graph_path) as f:
        data = json.load(f)
    store = GraphStore()
    store.graph = LineageGraph.from_dict(data)
    return store


if typer:

    @app.command()
    def build(
        config: str = typer.Option(..., "--config", "-c", help="Path to config YAML"),
        out: str = typer.Option("graph.json", "--out", "-o", help="Output file path"),
        fmt: str = typer.Option("json", "--format", "-f", help="Output format: json, graphml, dot"),
    ):
        """Build a lineage graph from adapter config."""
        store = _build_store(config)
        graph = store.graph

        if fmt == "graphml":
            content = export_graphml(graph)
        elif fmt == "dot":
            content = export_dot(graph)
        else:
            content = export_json(graph)

        Path(out).write_text(content)
        stats = store.get_stats()
        typer.echo(f"Built graph: {stats.total_nodes} nodes, {stats.total_edges} edges")
        typer.echo(f"Written to {out} ({fmt})")

    @app.command()
    def show(
        asset: str = typer.Argument(..., help="Asset ID or FQN"),
        depth: int = typer.Option(3, "--depth", "-d"),
        level: Optional[str] = typer.Option(None, "--level", "-l", help="Filter: tool, table, column"),
        min_confidence: float = typer.Option(0.0, "--min-confidence"),
        config: Optional[str] = typer.Option(None, "--config", "-c"),
        graph_file: Optional[str] = typer.Option(None, "--graph", "-g"),
    ):
        """Show upstream and downstream lineage for an asset."""
        store = _build_store(config) if config else _load_graph(graph_file or "graph.json")

        filters = Filters(min_confidence=min_confidence)
        if level:
            filters.lineage_levels = {LineageLevel(level)}

        # Try to find by ID or by name
        node_id = _resolve_asset(store, asset)
        if not node_id:
            typer.echo(f"Asset not found: {asset}", err=True)
            raise typer.Exit(1)

        node = store.graph.nodes[node_id]
        typer.echo(f"\n{node.name} ({node.fqn})")
        typer.echo(f"  type: {node.node_type.value}  domain: {node.platform_domain.value}  kind: {node.asset_kind.value}")
        typer.echo(f"  platform: {node.platform}  namespace: {node.namespace}")

        upstream = store.get_upstream(node_id, depth=depth, filters=filters)
        downstream = store.get_downstream(node_id, depth=depth, filters=filters)

        typer.echo(f"\nUpstream ({len(upstream)}):")
        for n in upstream:
            typer.echo(f"  <- {n.fqn} [{n.platform_domain.value}/{n.asset_kind.value}]")

        typer.echo(f"\nDownstream ({len(downstream)}):")
        for n in downstream:
            typer.echo(f"  -> {n.fqn} [{n.platform_domain.value}/{n.asset_kind.value}]")

    @app.command()
    def impact(
        asset: str = typer.Argument(..., help="Asset ID or FQN"),
        downstream: bool = typer.Option(True, "--downstream/--upstream"),
        level: Optional[str] = typer.Option(None, "--level", "-l"),
        fmt: str = typer.Option("tree", "--format", "-f", help="Output: tree or json"),
        config: Optional[str] = typer.Option(None, "--config", "-c"),
        graph_file: Optional[str] = typer.Option(None, "--graph", "-g"),
    ):
        """Compute blast radius / impact analysis for an asset."""
        store = _build_store(config) if config else _load_graph(graph_file or "graph.json")

        filters = Filters()
        if level:
            filters.lineage_levels = {LineageLevel(level)}

        node_id = _resolve_asset(store, asset)
        if not node_id:
            typer.echo(f"Asset not found: {asset}", err=True)
            raise typer.Exit(1)

        result = store.blast_radius(node_id, filters=filters)

        if fmt == "json":
            typer.echo(json.dumps(result, indent=2))
        else:
            typer.echo(f"\nBlast radius for {asset}: {result['total']} affected assets")
            for kind, count in sorted(result.get("by_kind", {}).items()):
                typer.echo(f"  {kind}: {count}")
            for domain, count in sorted(result.get("by_domain", {}).items()):
                typer.echo(f"  [{domain}]: {count}")

    @app.command("explain-edge")
    def explain_edge_cmd(
        edge_id: str = typer.Argument(..., help="Edge ID"),
        config: Optional[str] = typer.Option(None, "--config", "-c"),
        graph_file: Optional[str] = typer.Option(None, "--graph", "-g"),
    ):
        """Show evidence and reasoning for a specific edge."""
        store = _build_store(config) if config else _load_graph(graph_file or "graph.json")
        result = store.explain_edge(edge_id)
        typer.echo(json.dumps(result, indent=2, default=str))

    @app.command()
    def stats(
        config: Optional[str] = typer.Option(None, "--config", "-c"),
        graph_file: Optional[str] = typer.Option(None, "--graph", "-g"),
    ):
        """Show coverage statistics for the lineage graph."""
        store = _build_store(config) if config else _load_graph(graph_file or "graph.json")
        coverage = store.get_stats()

        typer.echo(f"\nLineage Graph Statistics")
        typer.echo(f"{'='*40}")
        typer.echo(f"Nodes: {coverage.total_nodes}")
        typer.echo(f"Edges: {coverage.total_edges}")

        typer.echo(f"\nEdges by level:")
        for level, count in sorted(coverage.edges_by_level.items()):
            typer.echo(f"  {level}: {count}")

        typer.echo(f"\nEdges by source:")
        for src, count in sorted(coverage.edges_by_system.items()):
            typer.echo(f"  {src}: {count}")

        typer.echo(f"\nNodes by domain:")
        for domain, count in sorted(coverage.nodes_by_domain.items()):
            typer.echo(f"  {domain}: {count}")

        typer.echo(f"\nNodes by kind:")
        for kind, count in sorted(coverage.nodes_by_kind.items()):
            typer.echo(f"  {kind}: {count}")

        typer.echo(f"\nConfidence distribution:")
        typer.echo(f"  High (>0.8):   {coverage.high_confidence_pct:.1f}%")
        typer.echo(f"  Medium (0.5-0.8): {coverage.medium_confidence_pct:.1f}%")
        typer.echo(f"  Low (<0.5):    {coverage.low_confidence_pct:.1f}%")

        typer.echo(f"\nCoverage scores:")
        typer.echo(f"  Table:  {coverage.coverage_table:.0%}")
        typer.echo(f"  Column: {coverage.coverage_column:.0%}")
        typer.echo(f"  Tool:   {coverage.coverage_tool:.0%}")

    @app.command("validate-fixtures")
    def validate_fixtures(
        config: str = typer.Option(..., "--config", "-c", help="Path to config YAML"),
    ):
        """Build graph from fixtures and validate coverage."""
        store = _build_store(config)
        coverage = store.get_stats()

        typer.echo(f"\nFixture Validation")
        typer.echo(f"{'='*40}")
        typer.echo(f"Nodes: {coverage.total_nodes}")
        typer.echo(f"Edges: {coverage.total_edges}")
        typer.echo(f"Coverage — Table: {coverage.coverage_table:.0%}  "
                    f"Column: {coverage.coverage_column:.0%}  "
                    f"Tool: {coverage.coverage_tool:.0%}")

        if coverage.resolution_stats:
            rs = coverage.resolution_stats
            typer.echo(f"\nResolution:")
            typer.echo(f"  Deduplicated: {rs.get('nodes_deduplicated', 0)} nodes")
            typer.echo(f"  Merged: {rs.get('edges_merged', 0)} edges")
            typer.echo(f"  Unresolved: {rs.get('unresolved_refs', 0)} refs")


def _resolve_asset(store: GraphStore, asset: str) -> Optional[str]:
    """Resolve an asset identifier to a node ID."""
    if not store.graph:
        return None
    # Try direct ID match
    if asset in store.graph.nodes:
        return asset
    # Try FQN match
    for node_id, node in store.graph.nodes.items():
        if node.fqn == asset or node.name == asset:
            return node_id
    return None


def main():
    """Entry point."""
    if typer and app:
        app()
    else:
        print("typer is required for the CLI. Install with: pip install typer", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
