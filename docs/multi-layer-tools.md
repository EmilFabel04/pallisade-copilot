# Multi-Layer Tool Support

Some modern data platforms serve multiple roles in a pipeline. Pallisade models this using a three-level capability system where platforms can appear in multiple pipeline layers when there is **observed evidence** of each role.

## Design Rule

> Observed usage beats theoretical capability. A platform splits into multiple roles ONLY when the current stack provides evidence that those roles are actually in use. `PlatformInfo.capabilities` is an eligibility hint, not proof of active usage.

## Three-Level Capability Model

| Level | Meaning | Where It Lives |
|-------|---------|---------------|
| **Supported** | What the platform *can* do (vendor-level) | `PlatformInfo.capabilities` tuple in `platforms.py` |
| **Observed** | What the platform *is doing* in this tenant | `driver.observed_capabilities()` → `ObservedCapability` structs |
| **Resolved** | What each discovered node *actually does* | `resolve_functional_role()` on each node via metadata |

## Multi-Layer Tools

### Databricks

| Layer | Role | Evidence Required | Adapter |
|-------|------|------------------|---------|
| **Warehouse** (primary) | Tables, views, materialized views | Unity Catalog discovery (always) | `live_databricks` |
| **Orchestration** | Workflow jobs, tasks | Jobs API returns jobs (`workflow_id` in metadata) | `live_databricks` |
| **Transformation** | Notebooks, Spark jobs | `notebook_path` or `spark_job_id` in metadata | `live_databricks` |

**How splitting works**: When Databricks has both table nodes (warehouse) and job nodes (orchestration), the pipeline overview shows separate nodes: "Databricks · Raw/Analytics" and "Databricks · Workflows". If only tables exist, Databricks appears as a single warehouse node — no speculative split.

**Driver probing**: `DatabricksDriver.observed_capabilities()` probes `/api/2.1/jobs/list` with `limit=1`. Only reports orchestration if the API responds 200.

**Metadata signals**:
- `workflow_id` + `is_orchestrator` → ORCHESTRATION role
- `notebook_path` → TRANSFORMATION role
- No orchestration metadata → falls through to WAREHOUSE (platform set membership)

### Snowflake

| Layer | Role | Evidence Required | Adapter |
|-------|------|------------------|---------|
| **Warehouse** (primary) | Tables, views | Schema discovery (always) | `live_warehouse` |
| **Transformation** | Dynamic Tables, Tasks | Dynamic Table metadata or Task discovery | Not yet implemented |

**Status**: Capability declared (`ToolCategory.TRANSFORMATION`) but no adapter emits transformation evidence yet. Snowflake will NOT split until a future PR adds Dynamic Table / Task discovery.

## Single-Layer Tools

All other tools serve a single role. The table below shows every registered platform and its primary layer.

### Warehouses

| Tool | Primary Layer | Adapter | Lineage Level | Multi-Role |
|------|-------------|---------|--------------|------------|
| BigQuery | Warehouse | `live_warehouse` | L2 (table + column) | No |
| Snowflake | Warehouse | `live_warehouse` | L2 | Eligible (transformation) |
| PostgreSQL | Warehouse | `live_warehouse` | L0 | No |
| Redshift | Warehouse | `live_warehouse` | L0 | No |
| Databricks | Warehouse | `live_databricks` | L2 + orchestration | Yes |
| Trino | Warehouse | — | L0 | No |
| DuckDB | Warehouse | — | L0 | No |
| MySQL | Warehouse | — | L0 | No |
| MSSQL | Warehouse | — | L0 | No |

### Transformation

| Tool | Primary Layer | Adapter | Lineage Level |
|------|-------------|---------|--------------|
| dbt Cloud | Transformation | `live_dbt` | L2 (table + column) |
| dbt Core | Transformation | `live_dbt` | L2 |
| Spark | Transformation | — | L0 |
| Dataform | Transformation | — | L0 |
| SQLMesh | Transformation | — | L0 |

### Ingestion

| Tool | Primary Layer | Adapter | Lineage Level |
|------|-------------|---------|--------------|
| Fivetran | Ingestion | `live_fivetran` | L2 |
| Airbyte | Ingestion | `live_airbyte` | L0 |
| n8n | Ingestion | `live_n8n` | L0 |
| Meltano | Ingestion | — | L0 |
| Stitch | Ingestion | — | L0 |
| Hevo | Ingestion | — | L0 |
| Matillion | Ingestion | — | L0 |
| Rivery | Ingestion | — | L0 |
| Singer | Ingestion | — | L0 |

### Orchestration

| Tool | Primary Layer | Adapter | Lineage Level |
|------|-------------|---------|--------------|
| Airflow | Orchestration | `live_airflow` | L2 (DAG + task + cross-plane) |
| Dagster | Orchestration | `live_dagster` | L0 |
| Prefect | Orchestration | `live_prefect` | L0 |
| Flink | Orchestration | — | L0 |

### Reporting / BI

| Tool | Primary Layer | Adapter | Lineage Level |
|------|-------------|---------|--------------|
| Looker | Reporting | `live_looker` | L0 |
| Tableau | Reporting | `live_tableau` | L0 |
| Power BI | Reporting | `live_powerbi` | L0 |
| Metabase | Reporting | `live_metabase` | L0 |
| Superset | Reporting | — | L0 |
| Mode | Reporting | — | L0 |
| Sigma | Reporting | — | L0 |
| ThoughtSpot | Reporting | — | L0 |

### Quality

| Tool | Primary Layer | Adapter | Lineage Level |
|------|-------------|---------|--------------|
| Elementary | Quality | `live_elementary` | L0 |

### Infrastructure

| Tool | Primary Layer | Adapter | Graph Domain |
|------|-------------|---------|-------------|
| Linux Server | Infrastructure | `live_linux` | Control Plane |
| SSH | Infrastructure | `live_linux` | Control Plane |

### Version Control

| Tool | Primary Layer | Adapter | Graph Domain |
|------|-------------|---------|-------------|
| GitHub | Version Control | `live_github` | Control Plane |
| GitLab | Version Control | `live_github` | Control Plane |

### Storage

| Tool | Primary Layer | Adapter | Graph Domain |
|------|-------------|---------|-------------|
| Storage | Infrastructure | `live_storage` | Data Plane |

### Non-Pipeline Integrations (Control Plane)

| Tool | Category | Adapter |
|------|----------|---------|
| Slack | Notifications | — |
| Microsoft Teams | Notifications | — |
| PagerDuty | Notifications | — |
| OpsGenie | Notifications | — |
| Jira | Ticketing | — |
| Linear | Ticketing | — |
| Asana | Ticketing | — |

## How Multi-Role Splitting Works

1. **Adapter discovery**: `LiveDatabricksAdapter.discover_assets()` discovers both Unity Catalog tables (warehouse) and workflow jobs (orchestration)
2. **Metadata tagging**: Job nodes carry `workflow_id` and `is_orchestrator` in `raw_metadata`
3. **Evidence-first classification**: `classify_actor_capability()` checks metadata keys before platform set membership
4. **Role resolution**: `resolve_functional_role()` assigns each node a functional role (e.g., `warehouse_raw`, `orchestration`)
5. **Split decision**: `_should_split()` checks:
   - 2+ distinct resolved roles exist
   - Roles map to different pipeline lanes
   - Each role group has meaningful content (min 1 node)
6. **Pipeline display**: Split platforms show as separate nodes (e.g., "Databricks · Raw" + "Databricks · Workflows")
7. **Control plane**: `build_control_plane_graph()` creates separate CP nodes per role when split criteria are met

## Future Multi-Role Candidates

| Platform | Potential Roles | Blocker |
|----------|----------------|---------|
| Snowflake | Warehouse + Transformation (Dynamic Tables) | Adapter needs to discover Dynamic Tables |
| BigQuery + Dataform | Warehouse + Transformation | Dataform adapter integration |
| Microsoft Fabric | Warehouse + Orchestration + Transformation | No adapter exists |
| Databricks + DLT | Warehouse + Orchestration + Quality | DLT pipeline discovery not yet implemented |

## Key Files

| File | Purpose |
|------|---------|
| `scanner/lineage/engine/platforms.py` | Platform registry with `capabilities` eligibility hints |
| `scanner/drivers/base.py` | `ObservedCapability` struct + `observed_capabilities()` contract |
| `scanner/drivers/warehouse/databricks_driver.py` | Databricks driver with Jobs API probing |
| `scanner/lineage/engine/adapters/live_databricks.py` | Adapter: table + job/task discovery |
| `scanner/lineage/engine/zones.py` | Evidence-first `classify_actor_capability()` + `resolve_functional_role()` |
| `scanner/lineage/engine/control_plane.py` | Role-aware CP graph with evidence-gated splitting |
| `components/pipeline/types.ts` | Frontend tool definitions (single-layer, multi-layer deferred) |
