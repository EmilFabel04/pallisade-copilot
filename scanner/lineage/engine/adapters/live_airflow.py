"""
Live Airflow Adapter — extracts lineage from Airflow DAGs.

Two modes:
  - **static**: Parse DAG Python files (from git repo or local filesystem)
  - **api**: Query a running Airflow instance via REST API

Emits DAG nodes, task nodes, table reference nodes, and the edges
between them — all in engine-canonical format with full evidence.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    EdgeType,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, normalize_identifier

logger = logging.getLogger(__name__)


class LiveAirflowAdapter(BaseLineageAdapter):
    """
    Adapter that discovers DAGs/tasks and extracts lineage from Airflow.

    Config keys:
        mode: "static" | "api"
        namespace: Airflow instance identifier (e.g., "production")
        integration_id: Pallisade integration ID for linking

    Static mode config:
        dag_files: Dict[str, str] — filename → Python source content

    API mode config:
        base_url: Airflow REST API base URL
        username: Airflow username
        password: Airflow password
    """

    def __init__(self, adapter_id: str = "live_airflow", **kwargs):
        super().__init__(adapter_id, **kwargs)
        self._mode = kwargs.get("mode", "static")

    def capabilities(self) -> Set[Capability]:
        caps = {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TOOL_LINEAGE,
            Capability.EXTRACT_TABLE_LINEAGE,
        }
        if self._mode == "api":
            caps.add(Capability.GET_RUNS_LOGS)
        return caps

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover DAGs, tasks, and referenced tables."""
        namespace = config.get("namespace", "airflow")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        hint = self.case_hint

        if self._mode == "api":
            return self._discover_from_api(config, namespace, integration_id, hint, now)
        return self._discover_from_static(config, namespace, integration_id, hint, now)

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract edges: DAG→task, task→task, task→table."""
        namespace = config.get("namespace", "airflow")
        now = datetime.utcnow()
        hint = self.case_hint

        if self._mode == "api":
            return self._extract_from_api(config, namespace, hint, now)
        return self._extract_from_static(config, namespace, hint, now)

    # ------------------------------------------------------------------
    # Static mode (DAG file parsing)
    # ------------------------------------------------------------------

    def _discover_from_static(
        self, config: Dict[str, Any], namespace: str,
        integration_id: Optional[str], hint: str, now: datetime,
    ) -> List[LineageNode]:
        from .airflow_parser import parse_dag_files

        dag_files = config.get("dag_files", {})
        if not dag_files:
            logger.warning("[LiveAirflow] No dag_files in config for static mode")
            return []

        parsed_dags = parse_dag_files(dag_files)
        nodes: List[LineageNode] = []

        for dag in parsed_dags:
            # DAG node
            dag_node = self._make_dag_node(dag.dag_id, namespace, integration_id, hint, now, dag)
            nodes.append(dag_node)

            # Task nodes
            for task in dag.tasks.values():
                task_node = self._make_task_node(
                    dag.dag_id, task, namespace, integration_id, hint, now,
                )
                nodes.append(task_node)

                # Table nodes referenced by this task
                table_nodes = self._make_table_nodes_for_task(
                    task, namespace, integration_id, hint, now,
                )
                nodes.extend(table_nodes)

        logger.info(f"[LiveAirflow] Static: discovered {len(nodes)} assets from {len(parsed_dags)} DAGs")
        return nodes

    def _extract_from_static(
        self, config: Dict[str, Any], namespace: str, hint: str, now: datetime,
    ) -> List[LineageEdge]:
        from .airflow_parser import parse_dag_files

        dag_files = config.get("dag_files", {})
        if not dag_files:
            return []

        parsed_dags = parse_dag_files(dag_files)
        edges: List[LineageEdge] = []

        for dag in parsed_dags:
            dag_asset_id = generate_asset_id("orchestration", "airflow", namespace, "", dag.dag_id)

            # DAG → Task edges (control-plane)
            for task in dag.tasks.values():
                task_asset_id = generate_asset_id(
                    "orchestration", "airflow", namespace, dag.dag_id, task.task_id,
                )
                edge = self._make_edge(
                    dag_asset_id, task_asset_id,
                    EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=f"dag_def:{dag.file_path}:{dag.dag_id}",
                    now=now,
                    plane=LinePlane.CONTROL,
                )
                edges.append(edge)

            # Task → Task dependency edges (control-plane)
            for upstream_id, downstream_id in dag.dependencies:
                up_asset = generate_asset_id(
                    "orchestration", "airflow", namespace, dag.dag_id, upstream_id,
                )
                down_asset = generate_asset_id(
                    "orchestration", "airflow", namespace, dag.dag_id, downstream_id,
                )
                edge = self._make_edge(
                    up_asset, down_asset,
                    EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=f"dag_def:{dag.file_path}:{upstream_id}>>{downstream_id}",
                    snippet=f"{upstream_id} >> {downstream_id}",
                    now=now,
                    plane=LinePlane.CONTROL,
                )
                edges.append(edge)

            # Task → Table edges
            for task in dag.tasks.values():
                if task.is_opaque:
                    continue
                task_asset_id = generate_asset_id(
                    "orchestration", "airflow", namespace, dag.dag_id, task.task_id,
                )
                task_edges = self._make_table_edges_for_task(
                    task, task_asset_id, dag, namespace, hint, now,
                )
                edges.extend(task_edges)

        logger.info(f"[LiveAirflow] Static: extracted {len(edges)} edges")
        return edges

    # ------------------------------------------------------------------
    # API mode (live Airflow REST API)
    # ------------------------------------------------------------------

    def _discover_from_api(
        self, config: Dict[str, Any], namespace: str,
        integration_id: Optional[str], hint: str, now: datetime,
    ) -> List[LineageNode]:
        try:
            from scanner.integrations.airflow import AirflowIntegration
        except ImportError:
            from integrations.airflow import AirflowIntegration

        client = AirflowIntegration(config=config)

        nodes: List[LineageNode] = []
        try:
            dags = client.get_dags()
        except Exception as e:
            logger.error(f"[LiveAirflow] API: failed to get DAGs: {e}")
            return []

        for dag_info in dags:
            dag_id = dag_info.dag_id if hasattr(dag_info, "dag_id") else dag_info.get("dag_id", "")
            if not dag_id:
                continue

            # DAG node
            dag_node = self._make_dag_node(
                dag_id, namespace, integration_id, hint, now,
                schedule=getattr(dag_info, "schedule_interval", None),
                owner=getattr(dag_info, "owners", [None])[0] if getattr(dag_info, "owners", None) else None,
                tags=[t.get("name", t) if isinstance(t, dict) else str(t) for t in getattr(dag_info, "tags", [])],
                description=getattr(dag_info, "description", None),
            )
            nodes.append(dag_node)

            # Task nodes from API
            try:
                tasks_resp = client.get_dag_task_details(dag_id)
                task_list = tasks_resp if isinstance(tasks_resp, list) else tasks_resp.get("tasks", [])
            except Exception as e:
                logger.warning(f"[LiveAirflow] API: failed to get tasks for {dag_id}: {e}")
                continue

            for task_info in task_list:
                tid = task_info.get("task_id", "") if isinstance(task_info, dict) else getattr(task_info, "task_id", "")
                operator = task_info.get("operator_name", task_info.get("class_ref", {}).get("class_name", "")) if isinstance(task_info, dict) else getattr(task_info, "operator", "")
                if not tid:
                    continue

                task_asset_id = generate_asset_id(
                    "orchestration", "airflow", namespace, dag_id, tid,
                )
                task_node = LineageNode(
                    id=task_asset_id,
                    name=tid,
                    fqn=f"airflow.{namespace}.{dag_id}.{tid}",
                    node_type=NodeType.TASK,
                    platform="airflow",
                    platform_domain=PlatformDomain.ORCHESTRATION,
                    asset_kind=AssetKind.TASK,
                    namespace=namespace,
                    observed_at=now,
                    sources=[self._id],
                    integration_id=integration_id,
                    raw_metadata={
                        "dag_id": dag_id,
                        "operator": operator,
                        "is_opaque": operator in ("PythonOperator", "BashOperator"),
                    },
                )
                nodes.append(task_node)

        logger.info(f"[LiveAirflow] API: discovered {len(nodes)} assets")
        return nodes

    def _extract_from_api(
        self, config: Dict[str, Any], namespace: str, hint: str, now: datetime,
    ) -> List[LineageEdge]:
        try:
            from scanner.integrations.airflow import AirflowIntegration
        except ImportError:
            from integrations.airflow import AirflowIntegration

        client = AirflowIntegration(config=config)

        edges: List[LineageEdge] = []
        try:
            dags = client.get_dags()
        except Exception as e:
            logger.error(f"[LiveAirflow] API: failed to get DAGs: {e}")
            return []

        for dag_info in dags:
            dag_id = dag_info.dag_id if hasattr(dag_info, "dag_id") else dag_info.get("dag_id", "")
            if not dag_id:
                continue

            dag_asset_id = generate_asset_id("orchestration", "airflow", namespace, "", dag_id)

            try:
                tasks_resp = client.get_dag_task_details(dag_id)
                task_list = tasks_resp if isinstance(tasks_resp, list) else tasks_resp.get("tasks", [])
            except Exception:
                continue

            for task_info in task_list:
                tid = task_info.get("task_id", "") if isinstance(task_info, dict) else getattr(task_info, "task_id", "")
                if not tid:
                    continue

                task_asset_id = generate_asset_id(
                    "orchestration", "airflow", namespace, dag_id, tid,
                )

                # DAG → Task (control-plane)
                edge = self._make_edge(
                    dag_asset_id, task_asset_id,
                    EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                    confidence=1.0,
                    source_ref=f"airflow_api:{dag_id}:{tid}",
                    now=now,
                    plane=LinePlane.CONTROL,
                )
                edges.append(edge)

                # Task → Task (from downstream_task_ids if available, control-plane)
                downstream_ids = (
                    task_info.get("downstream_task_ids", [])
                    if isinstance(task_info, dict)
                    else getattr(task_info, "downstream_task_ids", [])
                )
                for down_tid in downstream_ids:
                    down_asset = generate_asset_id(
                        "orchestration", "airflow", namespace, dag_id, down_tid,
                    )
                    dep_edge = self._make_edge(
                        task_asset_id, down_asset,
                        EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                        confidence=1.0,
                        source_ref=f"airflow_api:{dag_id}:{tid}>>{down_tid}",
                        now=now,
                        plane=LinePlane.CONTROL,
                    )
                    edges.append(dep_edge)

        logger.info(f"[LiveAirflow] API: extracted {len(edges)} edges")
        return edges

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def _make_dag_node(
        self, dag_id: str, namespace: str, integration_id: Optional[str],
        hint: str, now: datetime,
        dag=None,  # ParsedDag or None
        schedule: Optional[str] = None,
        owner: Optional[str] = None,
        tags: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> LineageNode:
        asset_id = generate_asset_id("orchestration", "airflow", namespace, "", dag_id)
        return LineageNode(
            id=asset_id,
            name=dag_id,
            fqn=f"airflow.{namespace}.{dag_id}",
            node_type=NodeType.DAG,
            platform="airflow",
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.JOB,
            namespace=namespace,
            description=description or (dag.description if dag else None),
            owner=owner or (dag.owner if dag else None),
            tags=tags or (dag.tags if dag else []),
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "schedule": schedule or (dag.schedule if dag else None),
                "file_path": dag.file_path if dag else None,
                "task_count": len(dag.tasks) if dag else 0,
            },
        )

    def _make_task_node(
        self, dag_id: str, task, namespace: str,
        integration_id: Optional[str], hint: str, now: datetime,
    ) -> LineageNode:
        """Create a task node from a ParsedTask."""
        asset_id = generate_asset_id(
            "orchestration", "airflow", namespace, dag_id, task.task_id,
        )
        return LineageNode(
            id=asset_id,
            name=task.task_id,
            fqn=f"airflow.{namespace}.{dag_id}.{task.task_id}",
            node_type=NodeType.TASK,
            platform="airflow",
            platform_domain=PlatformDomain.ORCHESTRATION,
            asset_kind=AssetKind.TASK,
            namespace=namespace,
            observed_at=now,
            sources=[self._id],
            integration_id=integration_id,
            raw_metadata={
                "dag_id": dag_id,
                "operator": task.operator_class,
                "is_opaque": task.is_opaque,
                "has_sql": task.sql is not None,
                "line_number": task.line_number,
            },
        )

    def _make_table_nodes_for_task(
        self, task, namespace: str,
        integration_id: Optional[str], hint: str, now: datetime,
    ) -> List[LineageNode]:
        """Create table nodes for tables referenced by a task."""
        if task.is_opaque:
            return []

        nodes: List[LineageNode] = []
        seen: Set[str] = set()

        all_tables = list(task.source_tables)
        if task.destination_table:
            all_tables.append(task.destination_table)

        for table_ref in all_tables:
            table_ref = normalize_identifier(table_ref, hint)
            if table_ref in seen or not table_ref:
                continue
            seen.add(table_ref)

            parts = table_ref.split(".")
            name = normalize_identifier(parts[-1], hint)
            schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
            db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
            container = f"{db}.{schema}"

            # Use warehouse domain so these dedup with BQ/Snowflake table nodes
            asset_id = generate_asset_id("warehouse", "airflow", namespace, container, name)

            node = LineageNode(
                id=asset_id,
                name=name,
                fqn=table_ref,
                node_type=NodeType.TABLE,
                database=db or None,
                schema=schema or None,
                platform="airflow",
                platform_domain=PlatformDomain.WAREHOUSE,
                asset_kind=AssetKind.TABLE,
                namespace=namespace,
                observed_at=now,
                sources=[self._id],
                integration_id=integration_id,
                raw_metadata={"discovered_via": "airflow_operator"},
            )
            nodes.append(node)

        return nodes

        edge_id = generate_edge_id(
            source_id, target_id,
            edge_type.value, level.value,
            source_ref,
        )
        return LineageEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            lineage_level=level,
            confidence=confidence,
            discovered_from=source_ref,
            discovered_at=now,
            evidence=[ev],
            plane=plane,
        )

    def _make_table_edges_for_task(
        self, task, task_asset_id: str, dag, namespace: str,
        hint: str, now: datetime,
    ) -> List[LineageEdge]:
        """Create task→table edges for a task's table references."""
        edges: List[LineageEdge] = []

        # Confidence: explicit param = 1.0, SQL-parsed = 0.8
        sql_confidence = 0.8

        # Source tables → READS_FROM (table → task) — cross-plane
        for table_ref in task.source_tables:
            table_ref = normalize_identifier(table_ref, hint)
            if not table_ref:
                continue
            parts = table_ref.split(".")
            name = normalize_identifier(parts[-1], hint)
            schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
            db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
            container = f"{db}.{schema}"
            table_asset_id = generate_asset_id("warehouse", "airflow", namespace, container, name)

            edge = self._make_edge(
                table_asset_id, task_asset_id,
                EdgeType.READS_FROM, LineageLevel.TABLE,
                confidence=sql_confidence,
                source_ref=f"dag_def:{dag.file_path}:{task.task_id}:reads:{table_ref}",
                snippet=task.sql[:200] if task.sql else None,
                now=now,
                plane=LinePlane.CROSS,
            )
            edges.append(edge)

        # Destination table → WRITES_TO (task → table) — cross-plane
        if task.destination_table:
            table_ref = normalize_identifier(task.destination_table, hint)
            parts = table_ref.split(".")
            name = normalize_identifier(parts[-1], hint)
            schema = normalize_identifier(parts[-2], hint) if len(parts) > 1 else ""
            db = normalize_identifier(parts[-3], hint) if len(parts) > 2 else ""
            container = f"{db}.{schema}"
            table_asset_id = generate_asset_id("warehouse", "airflow", namespace, container, name)

            # Explicit destination param = 1.0 confidence
            conf = 1.0 if not task.sql else sql_confidence
            edge = self._make_edge(
                task_asset_id, table_asset_id,
                EdgeType.WRITES_TO, LineageLevel.TABLE,
                confidence=conf,
                source_ref=f"dag_def:{dag.file_path}:{task.task_id}:writes:{table_ref}",
                snippet=task.sql[:200] if task.sql else None,
                now=now,
                plane=LinePlane.CROSS,
            )
            edges.append(edge)

        return edges
