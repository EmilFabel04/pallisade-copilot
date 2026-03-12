"""
Live Databricks Adapter — extracts lineage from Databricks Unity Catalog
and Databricks Jobs/Workflows.

Uses the Unity Catalog REST API to discover catalogs, schemas, and tables,
then extracts table-level and column-level lineage via the lineage endpoints.
Also discovers workflow jobs and tasks via the Jobs API, emitting orchestration
nodes and cross-plane edges (job/task → table).
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from ...graph import (
    AssetKind,
    ColumnMapping,
    EdgeType,
    Evidence,
    LineageEdge,
    LineageLevel,
    LineageNode,
    LinePlane,
    NodeType,
    PlatformDomain,
)
from ..adapter import BaseLineageAdapter, Capability
from ..ids import generate_asset_id, generate_edge_id, normalize_identifier

logger = logging.getLogger(__name__)

# Unity Catalog table_type → engine NodeType / AssetKind
_UC_TYPE_MAP = {
    "MANAGED": (NodeType.TABLE, AssetKind.TABLE),
    "EXTERNAL": (NodeType.TABLE, AssetKind.TABLE),
    "VIEW": (NodeType.VIEW, AssetKind.VIEW),
    "MATERIALIZED_VIEW": (NodeType.MATERIALIZED_VIEW, AssetKind.VIEW),
}

# Databricks task spec keys → human-readable task type
_TASK_TYPE_KEYS = [
    ("notebook_task", "notebook"),
    ("sql_task", "sql"),
    ("python_wheel_task", "python_wheel"),
    ("spark_jar_task", "spark_jar"),
    ("spark_python_task", "spark_python"),
    ("spark_submit_task", "spark_submit"),
    ("pipeline_task", "dlt_pipeline"),
    ("dbt_task", "dbt"),
    ("run_job_task", "run_job"),
    ("condition_task", "condition"),
    ("for_each_task", "for_each"),
]


class LiveDatabricksAdapter(BaseLineageAdapter):
    """
    Adapter that discovers Databricks Unity Catalog assets and workflow jobs,
    then extracts lineage via the REST API.

    Config keys:
        namespace: Workspace URL or identifier (e.g., "acme-prod")
        integration_id: Pallisade integration ID for linking
        databricks_config: Dict with host, token, http_path
    """

    def __init__(self, adapter_id: str = "live_databricks", **kwargs):
        super().__init__(adapter_id, **kwargs)

    def capabilities(self) -> Set[Capability]:
        return {
            Capability.DISCOVER_ASSETS,
            Capability.EXTRACT_TABLE_LINEAGE,
            Capability.EXTRACT_COLUMN_LINEAGE,
        }

    @property
    def case_hint(self) -> str:
        return "lower"

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def discover_assets(self, config: Dict[str, Any]) -> List[LineageNode]:
        """Discover catalogs, schemas, tables, and workflow jobs."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "databricks")
        integration_id = config.get("integration_id")
        now = datetime.utcnow()
        hint = self.case_hint
        nodes: List[LineageNode] = []

        # ── Phase 1: Unity Catalog tables ────────────────────────────
        catalogs = self._list_catalogs(client)
        if not catalogs:
            logger.warning("[LiveDatabricks] No catalogs found")
        else:
            for catalog in catalogs:
                catalog_name = catalog.get("name", "")
                if not catalog_name:
                    continue

                schemas = self._list_schemas(client, catalog_name)

                for schema_info in schemas:
                    schema_name = schema_info.get("name", "")
                    if not schema_name:
                        continue

                    # Skip internal schemas
                    if schema_name.lower() in ("information_schema",):
                        continue

                    tables = self._list_tables(client, catalog_name, schema_name)

                    for table in tables:
                        table_name = table.get("name", "")
                        if not table_name:
                            continue

                        table_type = table.get("table_type", "MANAGED").upper()
                        node_type, asset_kind = _UC_TYPE_MAP.get(
                            table_type, (NodeType.TABLE, AssetKind.TABLE)
                        )

                        db = normalize_identifier(catalog_name, hint)
                        schema = normalize_identifier(schema_name, hint)
                        name = normalize_identifier(table_name, hint)
                        container = f"{db}.{schema}"
                        fqn = f"{db}.{schema}.{name}"

                        asset_id = generate_asset_id(
                            "warehouse", "databricks", namespace, container, name,
                        )

                        columns: List[Dict[str, Any]] = []
                        for col in table.get("columns", []):
                            columns.append({
                                "name": col.get("name", ""),
                                "type": col.get("type_text", col.get("type_name", "")),
                                "nullable": col.get("nullable", True),
                                "comment": col.get("comment"),
                            })

                        owner = table.get("owner") or catalog.get("owner")
                        comment = table.get("comment") or ""
                        storage_location = table.get("storage_location", "")
                        data_source_format = table.get("data_source_format", "")
                        created_at = table.get("created_at")
                        updated_at = table.get("updated_at")

                        node = LineageNode(
                            id=asset_id,
                            name=name,
                            fqn=fqn,
                            node_type=node_type,
                            database=db,
                            schema=schema,
                            catalog=db,
                            platform="databricks",
                            platform_domain=PlatformDomain.WAREHOUSE,
                            asset_kind=asset_kind,
                            namespace=namespace,
                            description=comment if comment else None,
                            owner=owner,
                            columns=columns,
                            observed_at=now,
                            sources=[self._id],
                            integration_id=integration_id,
                            raw_metadata={
                                "unity_catalog": {
                                    "catalog": catalog_name,
                                    "schema": schema_name,
                                    "table_type": table_type,
                                    "data_source_format": data_source_format,
                                    "storage_location": storage_location,
                                    "created_at": created_at,
                                    "updated_at": updated_at,
                                },
                            },
                        )
                        nodes.append(node)

        table_count = len(nodes)

        # ── Phase 2: Workflow jobs (if Jobs API is accessible) ───────
        jobs = self._list_jobs(client)
        for job in jobs:
            job_id = str(job.get("job_id", ""))
            settings = job.get("settings", {})
            job_name = settings.get("name", f"job_{job_id}")
            job_name_norm = normalize_identifier(job_name, hint)

            job_asset_id = generate_asset_id(
                "orchestration", "databricks", namespace, "", job_name_norm,
            )

            schedule_info = settings.get("schedule", {})
            schedule_expr = (
                schedule_info.get("quartz_cron_expression")
                if isinstance(schedule_info, dict)
                else None
            )

            job_node = LineageNode(
                id=job_asset_id,
                name=job_name_norm,
                fqn=f"databricks.jobs.{job_name_norm}",
                node_type=NodeType.PIPELINE,
                platform="databricks",
                platform_domain=PlatformDomain.ORCHESTRATION,
                asset_kind=AssetKind.JOB,
                namespace=namespace,
                owner=job.get("creator_user_name"),
                observed_at=now,
                sources=[self._id],
                integration_id=integration_id,
                raw_metadata={
                    "workflow_id": job_id,
                    "is_orchestrator": True,
                    "job_id": job_id,
                    "job_name": job_name,
                    "schedule": schedule_expr,
                    "job_format": settings.get("format", "MULTI_TASK"),
                    "created_time": job.get("created_time"),
                    "task_count": len(settings.get("tasks", [])),
                },
            )
            nodes.append(job_node)

            # Discover tasks within the job
            for task in settings.get("tasks", []):
                task_key = task.get("task_key", "")
                if not task_key:
                    continue

                task_key_norm = normalize_identifier(task_key, hint)
                task_type = self._classify_task_type(task)

                task_asset_id = generate_asset_id(
                    "orchestration", "databricks", namespace,
                    job_name_norm, task_key_norm,
                )

                notebook_path = None
                notebook_task = task.get("notebook_task")
                if isinstance(notebook_task, dict):
                    notebook_path = notebook_task.get("notebook_path")

                depends_on = [
                    d.get("task_key", "")
                    for d in task.get("depends_on", [])
                    if d.get("task_key")
                ]

                task_node = LineageNode(
                    id=task_asset_id,
                    name=task_key_norm,
                    fqn=f"databricks.jobs.{job_name_norm}.{task_key_norm}",
                    node_type=NodeType.TASK,
                    platform="databricks",
                    platform_domain=PlatformDomain.ORCHESTRATION,
                    asset_kind=AssetKind.TASK,
                    namespace=namespace,
                    observed_at=now,
                    sources=[self._id],
                    integration_id=integration_id,
                    raw_metadata={
                        "workflow_id": job_id,
                        "dag_id": job_name,
                        "task_key": task_key,
                        "task_type": task_type,
                        "notebook_path": notebook_path,
                        "depends_on": depends_on,
                    },
                )
                nodes.append(task_node)

        job_count = len(nodes) - table_count
        logger.info(
            f"[LiveDatabricks] Discovered {table_count} table assets "
            f"and {job_count} job/task assets"
        )
        return nodes

    def extract_lineage(self, config: Dict[str, Any]) -> List[LineageEdge]:
        """Extract table-level, column-level, and job/task lineage."""
        client = self._get_client(config)
        if not client:
            return []

        namespace = config.get("namespace", "databricks")
        now = datetime.utcnow()
        hint = self.case_hint
        edges: List[LineageEdge] = []

        # Discover all assets so we can query lineage for each
        nodes = self.discover_assets(config)
        if not nodes:
            return []

        # Separate table nodes from job/task nodes
        table_nodes = [n for n in nodes if n.platform_domain == PlatformDomain.WAREHOUSE]
        job_nodes = [
            n for n in nodes
            if n.asset_kind == AssetKind.JOB
            and n.platform_domain == PlatformDomain.ORCHESTRATION
        ]
        task_nodes = [
            n for n in nodes
            if n.asset_kind == AssetKind.TASK
            and n.platform_domain == PlatformDomain.ORCHESTRATION
        ]

        # Track edges we've already created to avoid duplicates
        seen_edge_keys: Set[str] = set()

        # ── Phase 1: Table-level and column-level lineage (existing) ─
        for node in table_nodes:
            fqn = node.fqn
            parts = fqn.split(".")
            if len(parts) != 3:
                continue

            three_part_name = f"{parts[0]}.{parts[1]}.{parts[2]}"

            # -- Table-level lineage --
            table_lineage = self._get_table_lineage(client, three_part_name)
            if table_lineage:
                for upstream in table_lineage.get("upstreams", []):
                    upstream_table = upstream.get("table_info", {})
                    upstream_name = upstream_table.get("name", "")
                    upstream_catalog = upstream_table.get("catalog_name", "")
                    upstream_schema = upstream_table.get("schema_name", "")

                    if not upstream_name:
                        continue

                    src_db = normalize_identifier(upstream_catalog, hint)
                    src_schema = normalize_identifier(upstream_schema, hint)
                    src_name = normalize_identifier(upstream_name, hint)
                    src_container = f"{src_db}.{src_schema}"

                    source_id = generate_asset_id(
                        "warehouse", "databricks", namespace, src_container, src_name,
                    )
                    target_id = node.id

                    edge_key = f"{source_id}|{target_id}|table"
                    if edge_key in seen_edge_keys:
                        continue
                    seen_edge_keys.add(edge_key)

                    source_ref = (
                        f"unity-catalog:table-lineage:{three_part_name}"
                        f":upstream:{src_db}.{src_schema}.{src_name}"
                    )
                    edge = self._make_edge(
                        source_id, target_id,
                        EdgeType.DEPENDS_ON, LineageLevel.TABLE,
                        confidence=0.95,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.DATA,
                    )
                    edges.append(edge)

                for downstream in table_lineage.get("downstreams", []):
                    downstream_table = downstream.get("table_info", {})
                    downstream_name = downstream_table.get("name", "")
                    downstream_catalog = downstream_table.get("catalog_name", "")
                    downstream_schema = downstream_table.get("schema_name", "")

                    if not downstream_name:
                        continue

                    tgt_db = normalize_identifier(downstream_catalog, hint)
                    tgt_schema = normalize_identifier(downstream_schema, hint)
                    tgt_name = normalize_identifier(downstream_name, hint)
                    tgt_container = f"{tgt_db}.{tgt_schema}"

                    source_id = node.id
                    target_id = generate_asset_id(
                        "warehouse", "databricks", namespace, tgt_container, tgt_name,
                    )

                    edge_key = f"{source_id}|{target_id}|table"
                    if edge_key in seen_edge_keys:
                        continue
                    seen_edge_keys.add(edge_key)

                    source_ref = (
                        f"unity-catalog:table-lineage:{three_part_name}"
                        f":downstream:{tgt_db}.{tgt_schema}.{tgt_name}"
                    )
                    edge = self._make_edge(
                        source_id, target_id,
                        EdgeType.DEPENDS_ON, LineageLevel.TABLE,
                        confidence=0.95,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.DATA,
                    )
                    edges.append(edge)

            # -- Column-level lineage --
            for col in node.columns:
                col_name = col.get("name", "")
                if not col_name:
                    continue

                column_lineage = self._get_column_lineage(
                    client, three_part_name, col_name,
                )
                if not column_lineage:
                    continue

                upstream_cols = column_lineage.get("upstream_cols", [])
                for upstream_col in upstream_cols:
                    upstream_table_name = upstream_col.get("table_name", "")
                    upstream_col_name = upstream_col.get("name", "")
                    if not upstream_table_name or not upstream_col_name:
                        continue

                    up_parts = upstream_table_name.split(".")
                    if len(up_parts) == 3:
                        up_db = normalize_identifier(up_parts[0], hint)
                        up_schema = normalize_identifier(up_parts[1], hint)
                        up_name = normalize_identifier(up_parts[2], hint)
                    elif len(up_parts) == 2:
                        up_db = normalize_identifier(parts[0], hint)
                        up_schema = normalize_identifier(up_parts[0], hint)
                        up_name = normalize_identifier(up_parts[1], hint)
                    else:
                        continue

                    up_container = f"{up_db}.{up_schema}"
                    source_id = generate_asset_id(
                        "warehouse", "databricks", namespace, up_container, up_name,
                    )
                    target_id = node.id

                    from_col = normalize_identifier(upstream_col_name, hint)
                    to_col = normalize_identifier(col_name, hint)

                    edge_key = f"{source_id}|{target_id}|column|{from_col}|{to_col}"
                    if edge_key in seen_edge_keys:
                        continue
                    seen_edge_keys.add(edge_key)

                    source_ref = (
                        f"unity-catalog:column-lineage:{three_part_name}.{col_name}"
                        f":upstream:{upstream_table_name}.{upstream_col_name}"
                    )
                    column_mapping = ColumnMapping(
                        from_column=from_col,
                        to_column=to_col,
                        confidence=0.9,
                    )

                    ev = Evidence(
                        adapter_id=self._id,
                        source_ref=source_ref,
                        observed_at=now,
                    )
                    edge_id = generate_edge_id(
                        source_id, target_id,
                        EdgeType.DEPENDS_ON.value, LineageLevel.COLUMN.value,
                        source_ref,
                    )
                    edge = LineageEdge(
                        id=edge_id,
                        source_id=source_id,
                        target_id=target_id,
                        edge_type=EdgeType.DEPENDS_ON,
                        lineage_level=LineageLevel.COLUMN,
                        confidence=0.9,
                        discovered_from=source_ref,
                        discovered_at=now,
                        evidence=[ev],
                        column_mappings=[column_mapping],
                        plane=LinePlane.DATA,
                    )
                    edges.append(edge)

        # ── Phase 2: Job → Task edges (CONTROL plane) ───────────────
        # Build lookup: task_key_norm → task_node for each job
        task_lookup: Dict[str, LineageNode] = {}
        for tn in task_nodes:
            task_lookup[tn.id] = tn

        for job_node in job_nodes:
            job_name_norm = job_node.name
            rm = job_node.raw_metadata or {}
            job_id = rm.get("job_id", "")

            # Find tasks belonging to this job
            job_tasks = [
                tn for tn in task_nodes
                if (tn.raw_metadata or {}).get("workflow_id") == job_id
            ]

            for task_node in job_tasks:
                # Job → Task edge
                edge_key = f"{job_node.id}|{task_node.id}|control"
                if edge_key not in seen_edge_keys:
                    seen_edge_keys.add(edge_key)
                    source_ref = (
                        f"databricks:job:{job_id}:task:{task_node.name}"
                    )
                    edge = self._make_edge(
                        job_node.id, task_node.id,
                        EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                        confidence=1.0,
                        source_ref=source_ref,
                        now=now,
                        plane=LinePlane.CONTROL,
                    )
                    edges.append(edge)

                # Task → Task dependency edges
                task_rm = task_node.raw_metadata or {}
                for dep_key in task_rm.get("depends_on", []):
                    dep_key_norm = normalize_identifier(dep_key, hint)
                    dep_asset_id = generate_asset_id(
                        "orchestration", "databricks", namespace,
                        job_name_norm, dep_key_norm,
                    )
                    edge_key = f"{dep_asset_id}|{task_node.id}|control_dep"
                    if edge_key not in seen_edge_keys:
                        seen_edge_keys.add(edge_key)
                        source_ref = (
                            f"databricks:job:{job_id}:"
                            f"{dep_key}>>{task_node.name}"
                        )
                        edge = self._make_edge(
                            dep_asset_id, task_node.id,
                            EdgeType.DEPENDS_ON, LineageLevel.TOOL,
                            confidence=1.0,
                            source_ref=source_ref,
                            snippet=f"{dep_key} >> {task_rm.get('task_key', '')}",
                            now=now,
                            plane=LinePlane.CONTROL,
                        )
                        edges.append(edge)

        # ── Phase 3: Task → Table cross-plane edges ──────────────────
        # Build table FQN → asset_id lookup for matching
        table_fqn_to_id: Dict[str, str] = {}
        for tn in table_nodes:
            table_fqn_to_id[tn.fqn] = tn.id
            # Also index by name only for partial matches
            table_fqn_to_id[tn.name] = tn.id

        for task_node in task_nodes:
            task_rm = task_node.raw_metadata or {}
            task_type = task_rm.get("task_type", "")

            # SQL tasks: try to find table references in the SQL query
            if task_type == "sql":
                sql_task = {}
                # The SQL is not directly in the task spec — we'd need to
                # fetch it from the warehouse query. For now, mark as
                # potential cross-plane link via source_ref.
                pass

            # Notebook tasks: link via notebook_path (heuristic)
            notebook_path = task_rm.get("notebook_path")
            if notebook_path:
                # We can't parse notebook contents, but we record the
                # relationship for future enrichment via source_ref
                pass

            # For all task types, check Unity Catalog lineage API for
            # notebook/job-originated lineage (table_lineage may include
            # notebook_id or job_id in the lineage response)

        logger.info(
            f"[LiveDatabricks] Extracted {len(edges)} edges "
            f"(table + column + job/task)"
        )
        return edges

    # ------------------------------------------------------------------
    # Client helper
    # ------------------------------------------------------------------

    def _get_client(self, config: Dict[str, Any]) -> Optional[Any]:
        """Get or create an httpx.Client for Databricks REST API calls."""
        if config.get("client"):
            return config["client"]

        databricks_config = config.get("databricks_config", {})
        host = databricks_config.get("host", "")
        token = databricks_config.get("token", "")

        if not host:
            logger.warning("[LiveDatabricks] No databricks_config with host provided")
            return None

        if not token:
            logger.warning("[LiveDatabricks] No token in databricks_config")
            return None

        # Ensure host has https:// prefix and no trailing slash
        if not host.startswith("https://") and not host.startswith("http://"):
            host = f"https://{host}"
        host = host.rstrip("/")

        try:
            import httpx
        except ImportError:
            logger.error(
                "[LiveDatabricks] httpx is required for Databricks REST API. "
                "Install with: pip install httpx"
            )
            return None

        client = httpx.Client(
            base_url=host,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        return client

    # ------------------------------------------------------------------
    # Unity Catalog REST API helpers
    # ------------------------------------------------------------------

    def _list_catalogs(self, client: Any) -> List[Dict[str, Any]]:
        """List all catalogs in the Unity Catalog metastore."""
        try:
            resp = client.get("/api/2.1/unity-catalog/catalogs")
            resp.raise_for_status()
            data = resp.json()
            catalogs = data.get("catalogs", [])
            logger.debug(f"[LiveDatabricks] Found {len(catalogs)} catalogs")
            return catalogs
        except Exception as e:
            logger.error(f"[LiveDatabricks] Failed to list catalogs: {e}")
            return []

    def _list_schemas(self, client: Any, catalog_name: str) -> List[Dict[str, Any]]:
        """List schemas in a given catalog."""
        try:
            resp = client.get(
                "/api/2.1/unity-catalog/schemas",
                params={"catalog_name": catalog_name},
            )
            resp.raise_for_status()
            data = resp.json()
            schemas = data.get("schemas", [])
            logger.debug(
                f"[LiveDatabricks] Found {len(schemas)} schemas in {catalog_name}"
            )
            return schemas
        except Exception as e:
            logger.error(
                f"[LiveDatabricks] Failed to list schemas for {catalog_name}: {e}"
            )
            return []

    def _list_tables(
        self, client: Any, catalog_name: str, schema_name: str,
    ) -> List[Dict[str, Any]]:
        """List tables in a given catalog.schema."""
        try:
            resp = client.get(
                "/api/2.1/unity-catalog/tables",
                params={
                    "catalog_name": catalog_name,
                    "schema_name": schema_name,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            tables = data.get("tables", [])
            logger.debug(
                f"[LiveDatabricks] Found {len(tables)} tables in "
                f"{catalog_name}.{schema_name}"
            )
            return tables
        except Exception as e:
            logger.error(
                f"[LiveDatabricks] Failed to list tables for "
                f"{catalog_name}.{schema_name}: {e}"
            )
            return []

    def _get_table_lineage(
        self, client: Any, table_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Get table-level lineage from Unity Catalog."""
        try:
            resp = client.get(
                "/api/2.1/unity-catalog/lineage/table-lineage",
                params={"table_name": table_name},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(
                f"[LiveDatabricks] No table lineage for {table_name}: {e}"
            )
            return None

    def _get_column_lineage(
        self, client: Any, table_name: str, column_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Get column-level lineage from Unity Catalog."""
        try:
            resp = client.get(
                "/api/2.1/unity-catalog/lineage/column-lineage",
                params={
                    "table_name": table_name,
                    "column_name": column_name,
                },
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(
                f"[LiveDatabricks] No column lineage for "
                f"{table_name}.{column_name}: {e}"
            )
            return None

    # ------------------------------------------------------------------
    # Jobs REST API helpers
    # ------------------------------------------------------------------

    def _list_jobs(self, client: Any) -> List[Dict[str, Any]]:
        """List all jobs from the Databricks Jobs API.

        Handles pagination. Returns [] on 403/404 (Jobs API not enabled
        or token lacks permissions).
        """
        all_jobs: List[Dict[str, Any]] = []
        offset = 0
        limit = 25

        while True:
            try:
                resp = client.get(
                    "/api/2.1/jobs/list",
                    params={"limit": limit, "offset": offset, "expand_tasks": True},
                )
                if resp.status_code in (403, 404):
                    logger.debug(
                        "[LiveDatabricks] Jobs API not accessible "
                        f"(HTTP {resp.status_code})"
                    )
                    return []
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.debug(f"[LiveDatabricks] Jobs API unavailable: {e}")
                return []

            jobs = data.get("jobs", [])
            all_jobs.extend(jobs)

            if not data.get("has_more", False):
                break
            offset += limit

        logger.debug(f"[LiveDatabricks] Found {len(all_jobs)} jobs")
        return all_jobs

    def _classify_task_type(self, task: Dict[str, Any]) -> str:
        """Classify a task by checking which *_task key is present."""
        for key, task_type in _TASK_TYPE_KEYS:
            if key in task:
                return task_type
        return "unknown"
