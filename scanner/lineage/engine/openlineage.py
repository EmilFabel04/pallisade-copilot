"""
OpenLineage Event Mapper

Maps OpenLineage RunEvent JSON → our LineageNode / LineageEdge format.

OpenLineage (Linux Foundation) is the standard lineage event format.
Airflow 2.7+ has native OL support, Spark/Flink/dbt emit OL events.
Instead of building custom adapters per tool, we accept the standard
format and map it to our graph.

Event structure:
    RunEvent
    ├── eventType: START | RUNNING | COMPLETE | FAIL | ABORT
    ├── eventTime: ISO timestamp
    ├── run: {runId, facets: {parent, nominalTime, ...}}
    ├── job: {namespace, name, facets: {sql, sourceCode, ...}}
    ├── inputs: [{namespace, name, facets: {schema, columnLineage}}]
    └── outputs: [{namespace, name, facets: {schema, columnLineage}}]

Mapping:
    job     → LineageNode (TASK/DAG, ORCHESTRATION domain)
    dataset → LineageNode (TABLE, WAREHOUSE domain)
    input   → READS_FROM edge (job reads from dataset)
    output  → WRITES_TO edge (job writes to dataset)
    columnLineage facet → ColumnMapping
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from ..graph import (
    AssetKind,
    ColumnMapping,
    EdgeType,
    Evidence,
    HealthStatus,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from .ids import generate_asset_id, generate_edge_id, normalize_identifier

logger = logging.getLogger(__name__)


def _parse_namespace(namespace: str) -> Tuple[str, str]:
    """
    Parse an OpenLineage namespace into (platform, instance).

    Examples:
        "airflow://prod-airflow" → ("airflow", "prod-airflow")
        "bigquery"               → ("bigquery", "")
        "spark://spark-cluster"  → ("spark", "spark-cluster")
        "snowflake://acme.snowflakecomputing.com" → ("snowflake", "acme")
    """
    match = re.match(r"^(\w+)://(.+)$", namespace)
    if match:
        return match.group(1).lower(), match.group(2)
    return namespace.lower(), ""


def _infer_platform_domain(platform: str) -> PlatformDomain:
    """Infer PlatformDomain from platform name."""
    warehouse_platforms = {"bigquery", "snowflake", "postgres", "redshift", "databricks", "trino", "duckdb"}
    orchestration_platforms = {"airflow", "dagster", "prefect", "spark", "flink", "n8n"}
    transform_platforms = {"dbt", "sqlmesh"}

    if platform in warehouse_platforms:
        return PlatformDomain.WAREHOUSE
    elif platform in orchestration_platforms:
        return PlatformDomain.ORCHESTRATION
    elif platform in transform_platforms:
        return PlatformDomain.TRANSFORM
    return PlatformDomain.OTHER


def _event_type_to_health(event_type: str) -> HealthStatus:
    """Map OpenLineage eventType to HealthStatus."""
    mapping = {
        "COMPLETE": HealthStatus.HEALTHY,
        "FAIL": HealthStatus.FAILING,
        "ABORT": HealthStatus.DEGRADED,
        "START": HealthStatus.UNKNOWN,
        "RUNNING": HealthStatus.UNKNOWN,
        "OTHER": HealthStatus.UNKNOWN,
    }
    return mapping.get(event_type.upper(), HealthStatus.UNKNOWN)


def _parse_fqn_parts(name: str) -> Tuple[str, str, str]:
    """
    Parse dataset name into (database, schema, table).

    Handles: "db.schema.table", "schema.table", "table"
    """
    parts = name.split(".")
    if len(parts) >= 3:
        return parts[0], parts[1], ".".join(parts[2:])
    elif len(parts) == 2:
        return "", parts[0], parts[1]
    return "", "", name


class OpenLineageMapper:
    """
    Stateless mapper: OpenLineage RunEvent dict → (nodes, edges).

    Usage:
        mapper = OpenLineageMapper()
        nodes, edges = mapper.map_event(event_dict)
        # Or batch:
        nodes, edges = mapper.map_events(list_of_events)
    """

    def __init__(self, adapter_id: str = "openlineage"):
        self._adapter_id = adapter_id

    def map_event(
        self, event: Dict[str, Any]
    ) -> Tuple[List[LineageNode], List[LineageEdge]]:
        """
        Map a single OpenLineage RunEvent to nodes and edges.

        Returns:
            (nodes, edges) — may contain duplicates across calls;
            feed through the resolver for deduplication.
        """
        nodes: List[LineageNode] = []
        edges: List[LineageEdge] = []

        event_type = event.get("eventType", "OTHER")
        event_time = self._parse_time(event.get("eventTime"))
        run_info = event.get("run", {})
        job_info = event.get("job", {})
        inputs = event.get("inputs", [])
        outputs = event.get("outputs", [])

        run_id = run_info.get("runId", "")

        # --- Job node ---
        job_ns = job_info.get("namespace", "")
        job_name = job_info.get("name", "")
        if not job_name:
            return nodes, edges

        job_platform, job_instance = _parse_namespace(job_ns)
        job_domain = _infer_platform_domain(job_platform)
        job_facets = job_info.get("facets", {})

        # Determine job node type from naming conventions
        job_node_type = NodeType.TASK
        job_asset_kind = AssetKind.TASK
        if "." in job_name:
            # Airflow convention: "dag_id.task_id" → task
            job_node_type = NodeType.TASK
        elif job_platform == "dbt":
            job_node_type = NodeType.MODEL
            job_asset_kind = AssetKind.MODEL

        job_asset_id = generate_asset_id(
            job_domain.value, job_platform, job_instance, "", job_name,
        )

        job_node = LineageNode(
            id=job_asset_id,
            name=job_name,
            fqn=f"{job_platform}.{job_instance}.{job_name}" if job_instance else f"{job_platform}.{job_name}",
            node_type=job_node_type,
            platform=job_platform,
            platform_domain=job_domain,
            asset_kind=job_asset_kind,
            namespace=job_instance,
            observed_at=event_time,
            health_status=_event_type_to_health(event_type),
            sources=[self._adapter_id],
            raw_metadata={
                "run_id": run_id,
                "event_type": event_type,
                "job_facets": {k: v for k, v in job_facets.items() if k != "sql"},
                "sql": (job_facets.get("sql", {}).get("query", ""))[:500] if job_facets.get("sql") else None,
            },
        )
        nodes.append(job_node)

        # --- Input datasets ---
        for inp in inputs:
            ds_nodes, ds_edges = self._map_dataset(
                inp, job_asset_id, is_input=True,
                event_time=event_time, run_id=run_id,
            )
            nodes.extend(ds_nodes)
            edges.extend(ds_edges)

        # --- Output datasets ---
        for out in outputs:
            ds_nodes, ds_edges = self._map_dataset(
                out, job_asset_id, is_input=False,
                event_time=event_time, run_id=run_id,
            )
            nodes.extend(ds_nodes)
            edges.extend(ds_edges)

        return nodes, edges

    def map_events(
        self, events: List[Dict[str, Any]]
    ) -> Tuple[List[LineageNode], List[LineageEdge]]:
        """Map a batch of OpenLineage events."""
        all_nodes: List[LineageNode] = []
        all_edges: List[LineageEdge] = []

        for event in events:
            try:
                nodes, edges = self.map_event(event)
                all_nodes.extend(nodes)
                all_edges.extend(edges)
            except Exception as e:
                logger.warning(f"[OpenLineage] Failed to map event: {e}")

        logger.info(
            f"[OpenLineage] Mapped {len(events)} events → "
            f"{len(all_nodes)} nodes, {len(all_edges)} edges"
        )
        return all_nodes, all_edges

    # ------------------------------------------------------------------
    # Dataset mapping
    # ------------------------------------------------------------------

    def _map_dataset(
        self,
        dataset: Dict[str, Any],
        job_asset_id: str,
        is_input: bool,
        event_time: Optional[datetime],
        run_id: str,
    ) -> Tuple[List[LineageNode], List[LineageEdge]]:
        """Map an OpenLineage input/output dataset to node + edge."""
        nodes: List[LineageNode] = []
        edges: List[LineageEdge] = []

        ds_ns = dataset.get("namespace", "")
        ds_name = dataset.get("name", "")
        if not ds_name:
            return nodes, edges

        ds_platform, ds_instance = _parse_namespace(ds_ns)
        ds_domain = _infer_platform_domain(ds_platform)
        facets = dataset.get("facets", {}) or {}

        db, schema, table = _parse_fqn_parts(ds_name)

        container = f"{db}.{schema}" if db or schema else ""
        ds_asset_id = generate_asset_id(
            ds_domain.value, ds_platform, ds_instance, container, table,
        )

        # Build columns from schema facet
        columns: List[Dict[str, Any]] = []
        schema_facet = facets.get("schema", {})
        for field in schema_facet.get("fields", []):
            columns.append({
                "name": field.get("name", ""),
                "type": field.get("type", ""),
                "description": field.get("description"),
            })

        fqn = ".".join(p for p in [db, schema, table] if p)

        ds_node = LineageNode(
            id=ds_asset_id,
            name=table,
            fqn=fqn or ds_name,
            node_type=NodeType.TABLE,
            database=db or None,
            schema=schema or None,
            platform=ds_platform,
            platform_domain=ds_domain,
            asset_kind=AssetKind.TABLE,
            namespace=ds_instance,
            columns=columns,
            observed_at=event_time,
            sources=[self._adapter_id],
            raw_metadata={"openlineage_namespace": ds_ns},
        )
        nodes.append(ds_node)

        # Edge: job reads_from / writes_to dataset
        if is_input:
            edge_type = EdgeType.READS_FROM
            source_id, target_id = ds_asset_id, job_asset_id
        else:
            edge_type = EdgeType.WRITES_TO
            source_id, target_id = job_asset_id, ds_asset_id

        source_ref = f"openlineage:run:{run_id}:{'input' if is_input else 'output'}:{ds_name}"
        ev = Evidence(
            adapter_id=self._adapter_id,
            source_ref=source_ref,
            observed_at=event_time,
            snippet=f"run_id={run_id}",
        )
        edge_id = generate_edge_id(
            source_id, target_id,
            edge_type.value, "table",
            source_ref,
        )
        edges.append(LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            lineage_level=LineageLevel.TABLE,
            confidence=0.95,
            discovered_from=source_ref,
            discovered_at=event_time,
            evidence=[ev],
            plane=LinePlane.CROSS,
        ))

        # Column-level lineage from columnLineage facet
        col_lineage_facet = facets.get("columnLineage", {})
        col_edges = self._map_column_lineage(
            col_lineage_facet, ds_asset_id, job_asset_id,
            is_input, event_time, run_id, ds_name,
        )
        edges.extend(col_edges)

        return nodes, edges

    def _map_column_lineage(
        self,
        facet: Dict[str, Any],
        ds_asset_id: str,
        job_asset_id: str,
        is_input: bool,
        event_time: Optional[datetime],
        run_id: str,
        ds_name: str,
    ) -> List[LineageEdge]:
        """Map OpenLineage columnLineage facet to column-level edges."""
        edges: List[LineageEdge] = []
        fields = facet.get("fields", {})
        if not fields:
            return edges

        # columnLineage facet on output datasets maps output columns → input columns
        # fields: {output_col_name: {inputFields: [{namespace, name, field}], ...}}
        col_mappings: List[ColumnMapping] = []
        for output_col, info in fields.items():
            input_fields = info.get("inputFields", [])
            for inp_field in input_fields:
                col_mappings.append(ColumnMapping(
                    from_column=inp_field.get("field", ""),
                    to_column=output_col,
                    transform_expr=info.get("transformationDescription"),
                    confidence=1.0,
                ))

        if col_mappings:
            source_ref = f"openlineage:run:{run_id}:column_lineage:{ds_name}"
            ev = Evidence(
                adapter_id=self._adapter_id,
                source_ref=source_ref,
                observed_at=event_time,
            )
            # For output datasets, the column lineage goes from input→output
            # We create a single column-level edge on the output dataset
            edge_id = generate_edge_id(
                job_asset_id, ds_asset_id,
                "depends_on", "column",
                source_ref,
            )
            edges.append(LineageEdge(
                id=edge_id,
                source_id=job_asset_id,
                target_id=ds_asset_id,
                edge_type=EdgeType.DEPENDS_ON,
                lineage_level=LineageLevel.COLUMN,
                confidence=1.0,
                discovered_from=source_ref,
                discovered_at=event_time,
                evidence=[ev],
                column_mappings=col_mappings,
                plane=LinePlane.CROSS,
            ))

        return edges

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
