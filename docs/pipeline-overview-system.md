# Pipeline Overview System — Technical Documentation

## Overview

The Pipeline Overview system provides two views of a data stack's lineage:

- **Data Plane** — Dataset-to-dataset derivation chains (table → table)
- **Control Plane** — Tool-to-tool pipeline flows (Fivetran → BigQuery → dbt → Looker)

Both are rendered from a single canonical `LineageGraph` built by the extraction pipeline.

---

## Architecture

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│   Frontend    │────▶│  Next.js API  │────▶│  FastAPI Backend  │
│  (React Flow) │     │   Proxy       │     │  (ViewBuilder)    │
└──────────────┘     └───────────────┘     └──────────────────┘
                                                    │
                                           ┌────────┴────────┐
                                           │  LineageGraph    │
                                           │  (GraphStore)    │
                                           └────────┬────────┘
                                                    │
                                    ┌───────────────┼───────────────┐
                                    ▼               ▼               ▼
                              Adapters        Resolver        Canonicalizer
                           (per-tool)      (dedup/merge)    (type mapping)
```

### Core Design Principle: Driver-First Metadata

Every tool in the unified driver framework is a first-class citizen. **Drivers emit their own control-plane (CP) metadata** during discovery — they declare which tools they orchestrate, manage, host, or monitor. The ViewBuilder reads this metadata directly from graph nodes. No vendor-specific heuristics in the frontend or API layer.

```
Driver (discover_assets)  →  Graph Nodes (raw_metadata)  →  ViewBuilder (Step 1b aggregation)  →  CP Prober
     ↑                                                                                              ↓
  Config from frontend                                                              Evidence-gated CP edges
  (e.g. managed_tools)
```

### Key Files

| Component | Path |
|-----------|------|
| Frontend page | `app/(dashboard)/dashboard/lineage/page.tsx` |
| Pipeline overview types | `components/lineage/pipeline-overview/types.ts` |
| Inspector panel | `components/lineage/pipeline-overview/InspectorPanel.tsx` |
| Tool detail views | `components/lineage/pipeline-overview/tool-details/` |
| VCS detail view | `components/lineage/pipeline-overview/tool-details/VersionControlDetailView.tsx` |
| Next.js API proxy | `app/api/pipeline/[stackId]/lineage/engine/route.ts` |
| Next.js extraction route | `app/api/pipeline/[stackId]/lineage/extract-llm/route.ts` |
| Next.js investigate route | `app/api/pipeline/[stackId]/lineage/route.ts` |
| FastAPI view endpoints | `scanner/api/routers/lineage.py` |
| ViewBuilder (all views) | `scanner/lineage/engine/views.py` |
| Platform registry | `scanner/lineage/engine/platforms.py` |
| Canonical type system | `scanner/lineage/engine/canonical.py` |
| Edge semantic policy | `scanner/lineage/engine/edge_semantics.py` |
| Zone/lane classification | `scanner/lineage/engine/zones.py` |
| Investigator (extraction) | `scanner/lineage/engine/investigator.py` |
| Resolver (dedup) | `scanner/lineage/engine/resolver.py` |
| Bridge rules | `scanner/lineage/engine/bridge.py` |
| Graph store | `scanner/lineage/engine/store.py` |
| Run registry | `scanner/lineage/engine/run_registry.py` |
| **Driver adapters** | `scanner/lineage/engine/adapters/live_*.py` |
| Tests (lane overview) | `scanner/lineage/engine/tests/test_lane_overview.py` |
| Tests (tool details) | `scanner/lineage/engine/tests/test_tool_details.py` |

---

## Part 1: Extraction Pipeline

The graph is built when a user triggers lineage extraction. The pipeline runs in 9 steps:

### Step 0 — Initialize Run

`RunRegistry.start_run(tool_names)` creates a `RunRecord` with a UUID. Only successful runs atomically update `current_run_id` — failed runs leave the previous graph intact.

### Step 1 — Plan Extraction Order

An optional LLM planner determines adapter execution sequence. Falls back to heuristic ordering:

```
WAREHOUSE (1) → INGESTION (2) → TRANSFORMATION (3) → ORCHESTRATION (4) →
REPORTING (5) → INFRASTRUCTURE (6) → VERSION_CONTROL (7) → QUALITY (8)
```

Order matters: warehouse tables are discovered first so later adapters can cross-reference them.

### Step 2A — Sequential Adapter Execution

Each tool adapter implements two methods:

```python
class BaseLineageAdapter:
    def discover_assets(config) → List[LineageNode]   # Tables, models, dashboards, jobs
    def extract_lineage(config) → List[LineageEdge]   # Relationships between nodes
```

**Adapters and what they extract:**

| Adapter | Tool(s) | Nodes | Edges | CP Metadata |
|---------|---------|-------|-------|-------------|
| `live_warehouse` | BigQuery, Snowflake, Postgres | Tables, views | SQL-parsed derivations, query history | — |
| `live_fivetran` | Fivetran | Connectors, dest tables, service node | Connector → table WRITES_TO | — |
| `live_airbyte` | Airbyte | Connections, streams | Connection → table WRITES_TO | — |
| `live_dbt` | dbt Core/Cloud | Models, sources, tests | DEPENDS_ON from manifest (confidence=1.0) | — |
| `live_airflow` | Airflow | DAGs, tasks, table refs | DAG→task, task→table edges | `orchestrated_tools` (from operators, task IDs, DAG names) |
| `live_dagster` | Dagster | Assets, schedules, sensors | Asset dependencies | `orchestrated_tools` (from `compute_kind`) |
| `live_prefect` | Prefect | Flows, deployments | Deployment→flow, flow→table | `orchestrated_tools` (from flow names/tags) |
| `live_linux` | Linux servers | Host node (canonical_type=system) | None (discovery-only) | `hosted_tools`, `running_services` (from config) |
| `live_github` | GitHub | Service node (canonical_type=service) | None (discovery-only) | `managed_targets` (from `managed_tools` in config) |
| `live_elementary` | Elementary | Monitor nodes | Monitor→table MONITORS | `monitored_tables` (from test targets) |
| `live_looker` | Looker | Dashboards, explores | Dashboard→explore→table | — |
| `live_tableau` | Tableau | Workbooks, datasources | Workbook→datasource→table | — |
| `live_n8n` | n8n | Workflows, triggers | Workflow→table | — |

**Discovery-only tools** (infrastructure, version_control) run adapter `discover_assets()` to create graph nodes with CP metadata, but skip lineage extraction and correlation. This ensures they appear in the pipeline overview with proper evidence for CP edges.

#### Driver-Emitted CP Metadata

Drivers emit control-plane metadata on their graph nodes during `discover_assets()`. This metadata is the **primary source of evidence** for CP edge creation in the ViewBuilder.

| Driver | Metadata Key | How Derived |
|--------|-------------|-------------|
| `live_airflow` | `orchestrated_tools` | Scans task operator class names for dbt/fivetran/spark patterns, task IDs for tool keywords, and DAG names for tool references |
| `live_dagster` | `orchestrated_tools` | Checks asset `compute_kind` values (dbt, spark, etc.) |
| `live_prefect` | `orchestrated_tools` | Scans flow names and tags for tool keywords (dbt, fivetran, etc.) |
| `live_linux` | `hosted_tools` | Reads from `config.hosted_tools` / `config.running_services` |
| `live_github` | `managed_targets` | Reads from `config.managed_tools` (injected by frontend — see below) |
| `live_elementary` | `monitored_tables` | Collects distinct table names from test result queries |

**GitHub `managed_tools` injection:** The GitHub driver can't discover which tools it manages on its own — that's relational knowledge (which tools received GitHub attachments). The frontend resolves this by checking which `toolConfigs` have a `github.token` or `github_repo` matching the GitHub attachment, then injects `managed_tools: ["dbt_core", "airflow"]` into GitHub's config before sending to the backend. This is the **only** piece of frontend enrichment — everything else comes from drivers.

### Step 2B — Correlation Engine

After all adapters finish, 3 cross-tool correlation passes link nodes across tools:

1. **FQN matching** — dbt source `raw.customers` ↔ warehouse table `project.raw.customers`
2. **Connection matching** — Fivetran dest_schema matches warehouse schema
3. **Unresolved retry** — Fuzzy matching on remaining references

### Step 3 — Resolution (Deduplication)

The resolver merges duplicate nodes across adapters in 4 passes:

| Pass | Strategy | Example |
|------|----------|---------|
| 1. stable_id | (domain, namespace, container, name) | dbt model + BQ view with same FQN |
| 2. schema+name | Platform-independent, no database | dbt omits database, BQ includes it |
| 2.5. db-qualified | (database, schema, name) for WAREHOUSE only | Fivetran dest table + BQ table |
| 3. cross-domain | (namespace, name) across warehouse↔transform | dbt `stg_customers` + BQ `analytics.stg_customers` |

**After merge**, the winning (primary) node keeps its `platform` field. The secondary's platform is tracked in `raw_metadata["discovered_platforms"]` for multi-tool provenance. `dbt_resource_type` is preserved in raw_metadata so the UI can still identify dbt-derived assets.

### Step 4 — Canonicalize

Maps every node to one of 5 canonical types:

| Canonical Type | Included In Data Plane | Maps From |
|----------------|----------------------|-----------|
| `system` | No | Infrastructure nodes (linux servers) |
| `service` | No | Tool instances |
| `job` | No (bypassed) | DAGs, tasks, connectors, monitors |
| `dataset` | **Yes** | Tables, views, models, seeds, sources |
| `semantic` | **Yes** | Dashboards, reports, explores |

The data plane only renders `dataset` + `semantic` nodes. Jobs are bypassed (dataset→job→dataset becomes direct dataset→dataset with evidence preserved).

### Step 5 — Bridge Rules

Finds "orphan" raw tables with no upstream writer and scores them against ingestion jobs:

```
raw.orders (orphan) → score against Fivetran connectors
  → synced_table_name match (0.85) → create WRITES_TO edge
```

All bridge edges are marked `inferred=True` with confidence ≤ 0.5.

### Step 6 — Cross-Tool Edge Synthesis

Creates explicit edges across tool boundaries:

```
Fivetran connector → BigQuery raw table (synced_table match)
dbt source → warehouse table (FQN match)
```

### Step 7 — Build Rendered Views

`ViewBuilder` produces 3 pre-computed views from the graph. See Part 2.

### Step 8 — Persist & Publish

Artifacts are persisted to `RunRegistry`. `current_run_id` atomically updates to point at the new run. Frontend always reads from the current run.

---

## Part 2: View System

### ViewBuilder

All views are produced by `ViewBuilder(graph, tool_nodes)` in `views.py`. It outputs `RenderedView` objects containing `ViewNode[]`, `ViewEdge[]`, clusters, lanes, and stats.

```python
class ViewNode:
    id, name, canonical_type, original_type, platform, platform_domain
    layer, cluster_id, x, y  # deterministic pixel positions
    inferred, needs_mapping
    metadata: dict            # view-specific enrichment

class ViewEdge:
    id, source_id, target_id, canonical_type, original_type
    confidence, inferred, evidence_count, evidence_refs
    metadata: dict
```

### View 1: Lane Pipeline Overview (Control Plane)

**Endpoint:** `GET /api/v1/lineage/engine/views/lane-pipeline-overview`

Shows tools organized in fixed horizontal lanes:

```
INGESTION → WAREHOUSE_RAW → TRANSFORMATION → WAREHOUSE_ANALYTICS → REPORTING
 Fivetran      BigQuery          dbt              BigQuery            Looker
```

**Lanes are presentation groupings, not a 1:1 mapping of functional roles.** Multiple roles may share a lane for compact layout — for example, orchestration and quality tools appear in the transformation lane, while version_control and infrastructure tools appear in the ingestion lane. Each tool's actual functional role is available in `ViewNode.metadata.functionalRole` and displayed as a role badge in the inspector panel. See Part 8 for the full role-to-lane mapping.

**Algorithm (`build_lane_pipeline_overview` in `views.py`):**

#### Step 1 — Discover Tools per Lane from Engine Graph

Walk all graph nodes. For each node:

1. **Compute functional role** via `resolve_functional_role(node, canonical_type, dataset_zone, actor_capability)` — returns a `FunctionalRole` value string (see Part 8)
2. **Assign lane** via `assign_lane(node, ..., functional_role=role)` — role-aware lane placement (see Part 8)
3. Store `functional_role` in `tool_info[tk]["functional_role"]`

Build `tool_info` dict keyed by `(lane, tool_id)` where `tool_id = f"{platform}:{integration_id}"` (or just `platform` if no integration).

**Lane Assignment Precedence (in `assign_lane()`):**
1. Explicit `lane_override` in `raw_metadata` — if a valid `PipelineLane` value
2. Functional role mapping via `_ROLE_TO_LANE` dict
3. Zone/capability classification (original logic)

Each `tool_info` entry tracks: `platform`, `display_name`, `integration_id`, `asset_count`, `is_orchestrator`, `is_infra`, `functional_role`.

Also builds two indexes:
- `node_to_tool: Dict[node_id → (lane, tool_id)]` — for edge traversal in Step 4
- `tool_key_to_graph_nodes: Dict[(lane, tool_id) → List[LineageNode]]` — for enrichment in Step 3

#### Step 1b — Aggregate CP Metadata from Graph Nodes

Drivers emit CP-relevant metadata (`orchestrated_tools`, `managed_targets`, `hosted_tools`, etc.) directly on their graph nodes during `discover_assets()`. Step 1b aggregates these from ALL graph nodes belonging to each tool into `tool_info["raw_metadata"]`.

**Aggregated keys** (defined in `_CP_META_KEYS`):
```
orchestrated_tools, managed_targets, managed_repos (backward compat), managed_connectors,
triggered_tools, hosted_tools, hosted_platforms, hosted_services, managed_services,
monitored_tools, monitored_platforms, code_targets, project_repos, repository_tools
```

Values are deduplicated across multiple nodes. For example, two Airflow DAG nodes — one with `orchestrated_tools: ["dbt"]` and one with `orchestrated_tools: ["spark"]` — produce aggregated `orchestrated_tools: ["dbt", "spark"]`.

This replaces the old Step 2a approach where CP metadata was derived externally by the API layer and passed through `tool_nodes`. Drivers now own their metadata.

#### Step 2 — Merge Pipeline Tool Nodes Not in Graph

Tools from the frontend pipeline config (`self.tool_nodes`) that have no engine-discovered nodes are added to `tool_info`. Skips tools already covered by integration ID. For tools where the platform already exists in a lane, merges into the existing entry instead of creating duplicates.

#### Step 2.5 — Cross-Tool Asset Counting (Platform Index)

Builds `_platform_to_tks` — a reverse index mapping platform names → all `tool_info` keys for that platform. Uses `get_platform()` from the platform registry for alias resolution (e.g. both `"dbt"` and `"dbt_core"` map to the same tool key).

Then counts assets under secondary platforms: for each graph node, collects all platforms it belongs to (primary `node.platform` + `discovered_platforms` from raw_metadata + `dbt_resource_type` fallback). Increments `asset_count` in the corresponding secondary tool entries.

This is critical for resolver-merged nodes: a BigQuery table that was originally a dbt model has `discovered_platforms: ["bigquery", "dbt_core"]` — the dbt tool's asset count gets incremented even though the node's primary platform is now `bigquery`.

#### Step 3 — Build One ViewNode per Tool per Lane

For each tool in `tool_info`, enrich with:
- **Health summary** — aggregate healthy/degraded/failing/unknown/stale counts from graph nodes
- **Job count** — count job-like nodes (`canonical_type=job`, `dbt_resource_type in (model,seed,snapshot)`, Airflow `dag_id`/`is_task`, Fivetran `connector_id`/`sync_id`)
- **Last run timestamp** — most recent `observed_at` across all nodes
- **Sub-nodes** — up to 20 sample nodes with id, name, type, fqn, isJob
- **Coverage gaps** — `"no_data_extracted"` if from pipeline stack with 0 assets; `"sparse_lineage"` if many assets but few cross-tool edges

ViewNode metadata now includes `functionalRole` (string from `FunctionalRole` enum).

ViewNode ID format: `f"tool:{lane}:{tool_id}"`, canonical_type: `"service"`.

#### Step 4a — Evidence-Based Cross-Tool Edges

Iterate all data-plane edges in the graph. For each edge, look up the source and target tool keys via `node_to_tool`. If they belong to different tools → aggregate into `_ToolEdgeAgg`.

**Resolver-merge handling:** After the resolver merges dbt models into warehouse nodes, both edge endpoints may have the same primary platform (e.g. both `platform=bigquery`). When `src_tk == tgt_tk`, the algorithm recovers the original cross-tool relationship:

1. **Collect all platforms per node** via `_node_platforms()`: primary platform + `discovered_platforms` from `raw_metadata` + fallback: if `dbt_resource_type in ("model","seed","snapshot")`, inject `"dbt"`
2. **Resolve to tool keys** via `_resolve_tks()`: look up each platform in `_platform_to_tks` with alias resolution (`get_platform()` maps `"dbt"` → `"dbt_core"`)
3. **Select best cross-pair**: prefer the pair where `src_tk` matches the source node's primary platform (natural data-flow direction: warehouse→transformation)

This works generically for any resolver merge: bigquery+dbt, snowflake+dbt, postgres+spark, databricks+dataform, etc.

#### Step 4b — Job Bypass Synthesis Edges

Compress `dataset→job→dataset` paths into direct tool-to-tool edges. `_compute_job_bypass_edges()` finds JOB nodes with upstream and downstream dataset/semantic nodes, creates synthetic edges with `edge_type` from the upstream leg and confidence = min of both legs. Added to aggregations with source `"bridge:job_bypass"`.

**Bypass Drilldown Metadata:** Each bypass info now carries `job_node_id` and `job_node_name`. After ViewEdges are built, bypass drilldown is attached as `bypassPath` metadata (capped at 5 jobs per edge):

```json
{
  "bypassPath": {
    "jobs": [
      {"jobNodeId": "airflow:dag_sync", "jobNodeName": "dag_sync", "originalEdgeIds": ["e1", "e2"]}
    ],
    "summary": "1 job compressed: dag_sync"
  }
}
```

Bypass paths represent **compressed evidence** — these are real observed job chains, not inferred connections. An edge with `edgeOrigin: "evidence"` can still have a `bypassPath`.

#### Step 4c — Build ViewEdges from Aggregations

Each `_ToolEdgeAgg` is converted to a `ViewEdge` via `_aggregate_tool_edge()`:

- **evidence_count** = `len(agg.edges)` — number of cross-tool data flow edges
- **flowAssetCount** = `len(agg.asset_ids)` — unique nodes involved
- **Weighted confidence** = `sum(confidence × w) / sum(w)` where `w = 1.0 + log(1.0 + evidence_count_per_edge)`, clamped to [0.3, 0.95]
- **Evidence mix** — normalized counter of evidence source labels (e.g. `dbt_manifest: 0.6, query_history: 0.4`)
- **Top pairs** — up to 10 most frequent `(src_name, tgt_name)` asset pairs
- **Edge origin (`edgeOrigin`)** — classifies how the edge was discovered:
  - `"evidence"` — backed by observed lineage evidence (data derivation, query history, manifest)
  - `"inferred"` — from bridge rules, weak matching, or unresolved association logic
  - `"structural"` — config-derived control-plane edges (set in Step 4d)
- **Semantic type** — derived by `edge_semantics.derive_semantic_type()` from tool categories, evidence type, and **functional roles** (see Part 7). When `src_role`/`tgt_role` are available, role-pair rules are checked before category-pair rules for finer-grained semantics (e.g. `warehouse_raw→transformation = "feeds"` vs generic `warehouse→transformation`). Validated by `enforce_semantic_constraints()`. The dominant lane pair is tracked via `_ToolEdgeAgg.lane_pair_counts` so merges don't corrupt semantics.

| Evidence Type | Category Pair | Semantic Type | Label |
|---------------|---------------|---------------|-------|
| `data_derivation` | ingestion → warehouse | `ingests` | Ingests |
| `data_derivation` | warehouse → transformation | `feeds` | Feeds |
| `data_derivation` | transformation → warehouse | `builds` | Builds |
| `data_derivation` | warehouse → reporting | `serves` | Serves |
| `job_orchestration` | orchestration → transformation | `orchestrates` | Orchestrates |
| `code_ownership` | version_control → transformation | `manages_code_for` | Manages Code |
| `hosting` | infrastructure → ingestion | `hosts` | Hosts |
| `monitoring` | quality → warehouse | `monitors` | Monitors |
| *(fallback)* | any | `data_flow` | Data Flow |

#### Step 4d — Evidence-Gated Control-Plane Edges

CP edges represent tool-to-tool relationships like orchestration, code management, hosting, and monitoring. Unlike data-plane edges (which come from SQL parsing, manifests, etc.), CP edges are created through a **three-probe evidence gate** (`_probe_control_plane_evidence()`).

**Evidence flows from drivers, not from external enrichment.** Each driver emits CP metadata on its graph nodes during `discover_assets()` (see Step 2A). Step 1b aggregates that metadata into `tool_info`. The prober reads it from there.

```python
_CP_CATEGORY_PAIRS = [
    ("orchestration",   {"transformation", "ingestion"},                    JOB_ORCHESTRATION),
    ("version_control", {"transformation", "orchestration"},                CODE_OWNERSHIP),
    ("infrastructure",  {"warehouse", "ingestion", "orchestration", "transformation"},   HOSTING),
    ("quality",         {"warehouse", "transformation"},                    MONITORING),
]
```

For each category pair, the prober checks three evidence sources in order:

1. **Metadata cross-reference** (confidence 0.7) — `raw_metadata` contains explicit tool references emitted by drivers (e.g. `orchestrated_tools: ["dbt_core"]`, `managed_targets: ["dbt_core", "airflow"]`). Matches against target tool's normalized identity set (canonical name + aliases + integration_id + display name) via `_build_normalized_identity_set()`.

2. **PipelineEdge structural evidence** (confidence 0.8) — User-drawn PipelineEdge records from the database connecting the two tools.

3. **Pipeline co-presence fallback** (confidence 0.5) — If both tools exist in the same pipeline AND the source tool has NO explicit metadata targets. Guardrails:
   - **HOSTING**: never uses coexistence (too noisy — infrastructure needs real evidence)
   - **JOB_ORCHESTRATION/CODE_OWNERSHIP**: only if source has no metadata-specified targets (if `orchestrated_tools` or `managed_targets` is set, those are the only targets)
   - **MONITORING**: always allows coexistence (quality tools monitor everything co-located)

**Where metadata comes from:**
- **Drivers** (primary): Each driver emits its own CP metadata during `discover_assets()`. Airflow scans operators/task IDs/DAG names for tool patterns. GitHub reads `managed_tools` from config. Linux reads `hosted_tools` from config. Elementary collects `monitored_tables` from test results.
- **Frontend** (single exception): The frontend injects `managed_tools` into GitHub's config — this is relational knowledge (which tools received GitHub attachments) that only the frontend can resolve. No other frontend enrichment exists.
- **Backend `_derive_cp_metadata()`**: Thin passthrough for VCS `managed_tools` and infrastructure host-matching. No heuristic derivation.

**Relationship basis** (`relationshipBasis` in edge metadata):
- `"metadata_reference"` — backed by explicit metadata cross-reference from driver
- `"explicit_config"` — from PipelineEdge records
- `"pipeline_coexistence"` — tools co-exist in the pipeline (weak signal)
- `"monitoring_coexistence"` — quality tool monitors co-located data

**Example** (BigQuery + dbt + Airflow + Fivetran + Linux + GitHub pipeline):
- Airflow → dbt: `orchestrates` (metadata_reference — driver emitted `orchestrated_tools: ["dbt"]` from DAG name pattern)
- GitHub → dbt: `manages_code_for` (metadata_reference — `managed_targets: ["dbt_core", "airflow"]` from frontend-injected `managed_tools`)
- GitHub → Airflow: `manages_code_for` (metadata_reference — same)
- Linux: no edges (no `hosted_tools` in config, no coexistence fallback for HOSTING)

#### Step 4e — Role-Aware Cross-Lane Deduplication

The same tool may appear in multiple lanes (e.g. BigQuery in both `warehouse_raw` and `warehouse_analytics`). This step uses **role-aware splitting** to decide whether multi-lane entries should merge or stay split:

**Split decision (`_should_split()`):**
- Collects all distinct `functionalRole` values for a canonical tool_id across lanes
- Checks if the role set matches `_SPLITTABLE_ROLE_PAIRS` (currently: `{warehouse_raw, warehouse_analytics}`)
- If matched → keep as separate nodes (e.g. BigQuery raw ≠ BigQuery analytics)
- If not matched → merge as before

**For split tools:**
- Each role gets its own node with ID `tool:{tool_id}:role:{role}` (e.g. `tool:bigquery:role:warehouse_raw`)
- Health, assets, jobs, sub-nodes are per-role (not aggregated)
- Edges target the role-specific node

**For merged tools (non-splittable):**
1. Groups view nodes by canonical tool_id (stripped of lane prefix)
2. Merges multi-lane entries: aggregates health, assets, jobs, sub-nodes; keeps latest timestamp
3. Final node ID format: `f"tool:{tool_id}"` (no lane prefix)

**Edge merge:**
- Remaps all edge source/target IDs to canonical (or role-suffixed) IDs
- Merges duplicate edges for the same (source, target) pair: sums evidence_count, takes max confidence, prefers real edges over inferred, drops self-loops
- **Evidence-backed `edgeOrigin` wins over structural** on merge — if any constituent edge has `edgeOrigin: "evidence"`, the merged edge keeps `"evidence"`

#### Step 4f — Topological Ordering

Computes a topo order for each tool within its layer based on the average layer order of upstream tools. Used for deterministic vertical positioning in Step 5.

#### Step 5 — Layout

Groups nodes by layer, sorts within each layer (orchestrators/infra last, then by topo order, then alphabetically). Assigns compact x/y positions:
- `LANE_X_SPACING = 300px` between layers
- `TOOL_Y_SPACING = 80px` between tools in the same layer
- Only non-empty layers get x positions (empty layers are skipped)

Layer layout order: INGESTION(0) → WAREHOUSE(1) → TRANSFORMATION(2) → ORCHESTRATION(3) → REPORTING(4) → INFRASTRUCTURE(5) → VERSION_CONTROL(6) → STORAGE(7)

#### Step 6 — Stats & Metadata

Builds the final `RenderedView` with:
- **lanes** — per-layer metadata: name, label, order, x position, node count
- **stats** — totalNodes, totalEdges, orchestratorCount, laneDistribution, opsSummary (totalTools, totalAssets, healthDistribution, coverageGapCount)

### View 2: Data Plane

**Endpoint:** `GET /api/v1/lineage/engine/views/data-plane`

Shows dataset-to-dataset derivation chains with deterministic layout.

**Algorithm:**
1. Select only `dataset` + `semantic` canonical types
2. Build job bypass edges: when dataset→job→dataset exists, create direct dataset→dataset edge (evidence preserved)
3. Dedup tool-platform table duplicates by FQN (safety net)
4. Cluster by `(database, schema)` for datasets, `platform` for semantics
5. Apply transitive reduction (remove A→C when A→B→C exists)
6. Compute semantic topological layout (7 layers: INGESTION → RAW → STAGING → INTERMEDIATE → MART → SERVING → REPORTING)
7. Assign deterministic x,y positions

**Key design:** Job nodes never appear in the data plane. Their contributions are preserved via bypass edges with original confidence and evidence refs.

### View 3: Tool Details (On-Demand)

**Endpoint:** `GET /api/v1/lineage/engine/views/tool-details/{tool_view_id}`

Fetched when user clicks a tool node in the control plane. Returns domain-specific tabs and grouped items.

**Node Matching:**
- Primary: `node.platform` matches tool platform (with alias resolution via platform registry)
- Secondary: `raw_metadata["discovered_platforms"]` contains the platform (handles resolver-merged nodes like dbt models merged into BigQuery)

**Domain-specific tabs:**

| Category | Tabs | Content |
|----------|------|---------|
| `ingestion` | Connectors, Destinations | Connector jobs with dest_schema; destination tables grouped by schema |
| `transformation` | Models, Tests, Exposures | Models grouped by zone (staging/mart); test pass/fail; dbt exposures |
| `orchestration` | DAGs/Flows, Tasks | DAGs with task counts; tasks grouped by dag_id |
| `warehouse` | Datasets/Schemas, Tables & Views | Schema-level summaries; individual tables with health |
| `reporting` | Dashboards, Explores/Sources | Dashboards with view counts; explores with connection info |
| `infrastructure` | Services, Hosts | Running services extracted from raw_metadata; host nodes |
| `quality` | Monitors, Status | Test monitors with pass/fail; aggregate pass rate |
| `version_control` | Repos | Repository list from config and driver-discovered repos via API |

**Response shape:**
```json
{
  "toolId": "tool:dbt",
  "platform": "dbt",
  "category": "transformation",
  "summary": {
    "totalAssets": 14,
    "healthSummary": {"healthy": 10, "degraded": 2, "failing": 1, "unknown": 1},
    "jobCount": 0,
    "lastRunTs": "2026-03-04T12:30:00Z",
    "coverageGaps": []
  },
  "tabs": [
    {"key": "models", "label": "Models", "count": 10},
    {"key": "tests", "label": "Tests", "count": 3},
    {"key": "exposures", "label": "Exposures", "count": 1}
  ],
  "groups": {
    "models": [{"id": "...", "name": "stg_customers", "zone": "staging", ...}],
    "tests": [...],
    "exposures": [...]
  },
  "connections": {
    "upstream": [{"toolId": "tool:bigquery", "name": "BigQuery", "edgeCount": 4}],
    "downstream": [{"toolId": "tool:bigquery", "name": "BigQuery", "edgeCount": 10}]
  }
}
```

**Version control example** (GitHub):
```json
{
  "toolId": "tool:github:gh_001",
  "platform": "github",
  "category": "version_control",
  "summary": {
    "totalAssets": 2,
    "healthSummary": {"healthy": 0, "degraded": 0, "failing": 0, "unknown": 0},
    "jobCount": 0,
    "lastRunTs": null,
    "coverageGaps": []
  },
  "tabs": [
    {"key": "repos", "label": "Repositories", "count": 2}
  ],
  "groups": {
    "repos": [
      {"id": "repo:acme/data-pipelines", "name": "acme/data-pipelines", "canonicalType": "repository", "container": "acme"},
      {"id": "repo:acme/analytics", "name": "acme/analytics", "canonicalType": "repository", "container": "acme"}
    ]
  },
  "connections": {
    "upstream": [],
    "downstream": [
      {"toolId": "tool:dbt_core", "name": "dbt Core", "edgeCount": 1},
      {"toolId": "tool:airflow", "name": "Airflow", "edgeCount": 1}
    ]
  }
}
```

---

## Part 3: Frontend Rendering

### Page Structure

`app/(dashboard)/dashboard/lineage/page.tsx` has two tabs:

- **Data Lineage** tab → fetches `view-data-plane` → renders with backend pre-computed positions
- **Pipeline Overview** tab → fetches `view-lane-pipeline-overview` → renders with Dagre layout

Both use React Flow for interactive graph rendering.

### Fetch Chain

```
Frontend: fetch(/api/pipeline/{stackId}/lineage/engine?action=view-lane-pipeline-overview)
    ↓
Next.js proxy (route.ts): GET /api/v1/lineage/engine/views/lane-pipeline-overview?stack_id={stackId}
    ↓
FastAPI (lineage.py): ViewBuilder(store.graph, tool_nodes).build_lane_pipeline_overview()
    ↓
Response: RenderedView { nodes, edges, lanes, stats }
```

**Graph Recovery:** If the backend returns empty nodes (graph lost after restart), the proxy restores from a DB snapshot and retries. This only triggers for responses that have a `nodes` field (pipeline-overview, data-plane) — not for tool-details responses which use `tabs`/`groups`.

### Inspector Panel

When a user clicks a tool node in the control plane:

1. **Header renders immediately** from existing `ViewNode.metadata` (health dot, name, lane badge, functional role badge, platform)
2. **Detail fetch fires:** `GET ...?action=view-tool-details&id={node.id}`
3. **Loading skeleton** shown while fetching
4. **On success:** `<ToolDetailView>` renders domain-specific tabs
5. **Caching:** Results cached in a `useRef` Map by node.id (cleared on retry)

The `ToolDetailView` component routes to the correct domain component based on `response.category`:

```
category="ingestion"      → IngestionDetailView
category="transformation" → TransformDetailView
category="orchestration"  → OrchestrationDetailView
category="warehouse"      → WarehouseDetailView
category="reporting"      → ReportingDetailView
category="infrastructure" → InfraDetailView
category="quality"        → QualityDetailView
category="version_control" → VersionControlDetailView
default                   → GenericDetailView
```

### Edge Inspector

When clicking an edge in the control plane, shows:
- Semantic type label (color-coded) with evidence type badge (e.g. "data derivation", "job orchestration")
- Data flow count and confidence bar
- Source and target tool summaries
- **Provenance** — plain-language explanation of the edge origin:
  - `"evidence"` → "Derived from observed lineage evidence"
  - `"structural"` → "Derived from configured pipeline relationships"
  - `"inferred"` → "Inferred from weak matching, bridge rules, or unresolved association logic"
- **Compressed Path** (collapsible) — when `bypassPath` exists, shows the intermediate job names that were compressed into the direct edge, with a summary string

Config-derived edges (evidence_count=0) show the semantic label without a flow count. Evidence-based edges show `"Label · N flows"`.

---

## Part 4: Platform Registry

`scanner/lineage/engine/platforms.py` is the single source of truth for tool metadata:

```python
PlatformInfo(
    name="dbt_core",
    category=ToolCategory.TRANSFORMATION,
    domain=PlatformDomain.TRANSFORM,
    adapter_id="live_dbt",
    heuristic_order=30,
    aliases=("dbt",),
)
```

**Categories:** `WAREHOUSE`, `INGESTION`, `TRANSFORMATION`, `ORCHESTRATION`, `REPORTING`, `INFRASTRUCTURE`, `VERSION_CONTROL`, `QUALITY`

**Key aliases:**
- `dbt` → `dbt_core` (primary)
- `linux` → `linux_server` (primary)

The `get_platform(name)` function does case-insensitive lookup. Aliases are used by `build_tool_details()` to match graph nodes that may use either form.

---

## Part 5: Confidence & Evidence

Every edge carries a confidence score (0.0–1.0) and evidence refs:

| Source | Confidence |
|--------|-----------|
| dbt manifest (declarative) | 1.0 |
| API metadata (Fivetran) | 0.9 |
| Compiled SQL (view definitions) | 0.8 |
| CP PipelineEdge (explicit config) | 0.8 |
| CP metadata cross-reference | 0.7 |
| Query history (BigQuery jobs) | 0.6 |
| CP pipeline co-presence | 0.5 |
| Bridge rules (inferred) | ≤ 0.5 |
| CP monitoring coexistence | 0.4 |
| Regex/pattern matching | 0.3 |

The data plane colors edges by confidence: green (≥0.8), amber (0.5–0.8), red (<0.5).

Confidence constants are defined in `edge_semantics.py` as `CONFIDENCE_EXPLICIT_CONFIG`, `CONFIDENCE_METADATA_XREF`, `CONFIDENCE_MONITORING_COEX`, `CONFIDENCE_PIPELINE_COEX`.

### CP Metadata Key Contract

The authoritative set of `raw_metadata` keys that the CP prober recognises. Adapters MUST use these exact keys. Any key not listed here is ignored by the CP prober (legacy aliases are accepted for backward compatibility).

| Key | Type | Emitted By | Evidence Type |
|-----|------|------------|---------------|
| `orchestrated_tools` | `List[str]` | Airflow, Dagster, Prefect | `JOB_ORCHESTRATION` |
| `managed_targets` | `List[str]` | GitHub (VCS adapters) | `CODE_OWNERSHIP` |
| `managed_repos` | `List[str]` | GitHub (alias) | `CODE_OWNERSHIP` |
| `hosted_tools` | `List[str]` | Linux (infra adapters) | `HOSTING` |
| `hosted_platforms` | `List[str]` | Linux (alias) | `HOSTING` |
| `running_services` | `List[str]` | Linux (alias) | `HOSTING` |
| `monitored_tools` | `List[str]` | Elementary (quality) | `MONITORING` |
| `monitored_tables` | `List[str]` | Elementary (alias) | `MONITORING` |

Contract constants: `CP_META_KEYS_ORCHESTRATION`, `CP_META_KEYS_CODE_OWNERSHIP`, `CP_META_KEYS_HOSTING`, `CP_META_KEYS_MONITORING` in `edge_semantics.py`.

### System Invariants

1. **HOSTING edges are NEVER created from coexistence alone** — Infrastructure tools need explicit `hosted_tools`/`hosted_platforms` metadata to produce hosting edges.
2. **ORCHESTRATION coexistence only fires when source has NO explicit targets** — If an orchestrator has `orchestrated_tools` metadata, coexistence edges to tools NOT in that list are suppressed.
3. **Split nodes collapse when one side has zero assets** — Warehouse role-split nodes (raw + analytics) merge back to a single node if one side discovers zero datasets.
4. **Metadata cross-reference edges have `edgeOrigin: "evidence"`** — Only user-drawn PipelineEdge records produce `"structural"` origin. Driver-emitted metadata is observed evidence.
5. **Null containers render as "Ungrouped"** — All tool detail views use the consistent label `"Ungrouped"` for items without a container/schema.

### Schema Evolution Strategy

To add a new CP metadata key:
1. Add the key to the appropriate `CP_META_KEYS_*` constant in `edge_semantics.py`
2. Add it to the corresponding list in `_CP_EVIDENCE_KEYS` in `views.py`
3. Emit the key from the adapter's `discover_assets()` method
4. Add a test in `test_lane_overview.py` verifying the CP edge is created

To add a new adapter type:
1. Create `live_<type>.py` implementing `BaseLineageAdapter`
2. Register in `create_default_registry()`
3. Emit CP metadata using contract keys during `discover_assets()`
4. No changes needed to the CP prober — it works off the contract keys

---

## Part 6: Key Design Decisions

1. **Three views, one graph** — Pipeline overview, lane overview, and data plane are all projections of the same canonical graph, each optimized for different analysis tasks.

2. **Deterministic layout** — All node positions are computed server-side. The frontend renders pre-computed x,y values (data plane) or applies Dagre (control plane).

3. **Job bypass in data plane** — Job nodes are excluded. When dataset→job→dataset exists, a direct bypass edge is created with evidence from both original edges.

4. **Resolver merge preserves provenance** — When dbt models merge into BigQuery nodes, `discovered_platforms` and `dbt_resource_type` are preserved in raw_metadata. The pipeline overview uses these to recover cross-tool edges (via `_platform_to_tks` alias-aware index) even when both endpoints share the same primary platform after merge.

5. **Atomic run publishing** — Failed extractions never update `current_run_id`, so the frontend always sees a complete graph.

6. **Infrastructure and VCS are discovery-only** — Linux servers and GitHub create `system`/`service` nodes (excluded from data plane) with CP metadata (`hosted_tools`, `managed_targets`), visible only in the control plane. Their drivers run `discover_assets()` but skip lineage extraction and correlation. This is controlled by `_DISCOVERY_ONLY_CATEGORIES = {INFRASTRUCTURE, VERSION_CONTROL}` in the investigator.

7. **Non-fatal enrichment** — Health enrichment, LLM reconciliation, and cross-tool synthesis all fail silently without breaking the pipeline.

8. **Category-driven edge semantics** — Edge labels are derived from `(src_category, tgt_category, evidence_type)` via `edge_semantics.py`, not from lane adjacency. This prevents nonsensical labels like "BigQuery orchestrates dbt". Constraint enforcement (`enforce_semantic_constraints`) downgrades invalid labels to `data_flow` (e.g. `orchestrates` must originate from an orchestration tool).

9. **Driver-first CP metadata replaces external enrichment** — The old system derived CP metadata through fragile frontend config introspection and backend heuristics (repo-name matching, config key scanning). The new system has each driver emit its own CP metadata during `discover_assets()` — Airflow declares `orchestrated_tools` by scanning its own operators/tasks/DAG names, GitHub declares `managed_targets` from injected `managed_tools`, Linux declares `hosted_tools` from config. ViewBuilder Step 1b aggregates this metadata from graph nodes. Zero vendor-specific branching in edge creation.

10. **Functional roles over platform categories** — Platform category is too coarse (Databricks is both warehouse and orchestration, BigQuery serves raw and analytics). `FunctionalRole` resolves what each node actually does using metadata, zone classification, and capability signals. This enables role-aware dedup, role-pair edge semantics, and correct lane assignment.

11. **Role-aware dedup preserves warehouse topology** — Warehouse platforms with both raw and analytics datasets split into two nodes (e.g. BigQuery raw + BigQuery analytics) rather than collapsing into one. This correctly represents the data flow: ingestion→BQ(raw)→transformation→BQ(analytics)→reporting. Split decisions are controlled by `_SPLITTABLE_ROLE_PAIRS`, currently limited to `{warehouse_raw, warehouse_analytics}`.

12. **Three-tier edge provenance** — Every control-plane edge carries `edgeOrigin` distinguishing evidence-backed (metadata cross-reference or data lineage), structural (user-drawn PipelineEdge records), and inferred (coexistence fallback) edges. Mapping defined by `BASIS_TO_EDGE_ORIGIN` in `edge_semantics.py`. Bypass paths (compressed job chains) are orthogonal to provenance.

13. **Evidence-gated CP edges prevent false connections** — CP edges are never created by lane adjacency or co-location alone (except monitoring). Three probes gate every CP edge: metadata cross-reference (from driver-emitted metadata), PipelineEdge records (user-drawn), and co-presence fallback (only when no explicit targets exist, never for HOSTING). This prevents false edges like "Airflow orchestrates Fivetran" when the Airflow DAGs have no Fivetran-related operators.

---

## Part 7: Edge Semantic Policy (`edge_semantics.py`)

The edge semantics module is the single source of truth for how tool-to-tool edges get labeled. It replaces the old lane-pair-based `_derive_semantic_type()` that was fragile and produced wrong labels after cross-lane merges.

### Evidence Types

| Constant | Meaning | Source |
|----------|---------|--------|
| `DATA_DERIVATION` | Asset A derives from asset B | SQL parsing, dbt manifest, query history |
| `JOB_ORCHESTRATION` | Tool A schedules/triggers tool B | Airflow DAG refs, orchestrator configs |
| `CODE_OWNERSHIP` | Tool A manages source code for tool B | VCS repo → project mapping |
| `HOSTING` | Tool A hosts/runs tool B | Infrastructure → service mapping |
| `MONITORING` | Tool A monitors/tests tool B | Quality tool → warehouse monitoring |
| `INFERRED_ADJACENCY` | Legacy fallback for lane-pair heuristics | Lane adjacency (deprecated for new edges) |

### `derive_semantic_type(src_category, tgt_category, evidence_type, src_lane?, tgt_lane?, src_role?, tgt_role?)`

Returns `(semantic_type_code, display_label)` based on the rules matrix:

- **DATA_DERIVATION**: **Role-pair rules checked first** when `src_role`/`tgt_role` are provided (see below), then falls back to explicit `(src_cat, tgt_cat)` lookup table (ingestion→warehouse = "ingests", warehouse→transformation = "feeds", etc.)
- **JOB_ORCHESTRATION**: Returns "orchestrates" only if `src_cat == "orchestration"` and `tgt_cat` is in `{ingestion, transformation, warehouse, reporting}`
- **CODE_OWNERSHIP**: Returns "manages_code_for" only if `src_cat == "version_control"` and `tgt_cat` is in `{transformation, orchestration, warehouse, reporting}`
- **HOSTING**: Returns "hosts" only if `src_cat == "infrastructure"` and `tgt_cat` is in `{ingestion, orchestration, transformation, warehouse, reporting}`
- **MONITORING**: Returns "monitors" only if `src_cat == "quality"` and `tgt_cat` is in `{warehouse, transformation, orchestration, reporting}`
- **INFERRED_ADJACENCY**: Falls back to lane-pair map for legacy compatibility
- **Unknown**: Returns `("data_flow", "Data Flow")`

#### Role-Pair Derivation Rules (`_ROLE_DERIVATION_RULES`)

When functional roles are available, these finer-grained rules take precedence over category-pair rules for `DATA_DERIVATION` edges:

| Source Role | Target Role | Semantic Type | Label |
|-------------|-------------|---------------|-------|
| `warehouse_raw` | `transformation` | `feeds` | Feeds |
| `ingestion` | `warehouse_raw` | `ingests` | Ingests |
| `transformation` | `warehouse_analytics` | `builds` | Builds |
| `warehouse_analytics` | `reporting` | `serves` | Serves |
| `warehouse_analytics` | `semantic` | `serves` | Serves |
| `warehouse_raw` | `warehouse_analytics` | `feeds` | Feeds |
| `ingestion` | `transformation` | `ingests` | Ingests |

This matters because category-pair rules can't distinguish warehouse_raw from warehouse_analytics (both are category=`warehouse`). With role-pair rules, BigQuery(raw)→dbt correctly becomes "Feeds" while dbt→BigQuery(analytics) correctly becomes "Builds".

### `enforce_semantic_constraints(semantic_type, label, src_category, tgt_category, evidence_type, src_role?, tgt_role?)`

Guardrail that downgrades invalid labels to `("data_flow", "Data Flow")`:

- `orchestrates` requires `src_category == "orchestration"`
- `hosts` requires `src_category == "infrastructure"`
- `manages_code_for` requires `src_category == "version_control"`
- `monitors` requires `src_category == "quality"`
- Data-flow verbs (`ingests`, `feeds`, `builds`, `serves`) require `evidence_type` in `{DATA_DERIVATION, INFERRED_ADJACENCY}`

---

## Part 8: Functional Roles (`zones.py`)

### FunctionalRole Enum

More specific than platform category — captures what a node actually does in the pipeline regardless of which platform hosts it.

| Value | Description |
|-------|-------------|
| `warehouse_raw` | Raw/source data storage (raw zone, landing, bronze) |
| `warehouse_analytics` | Transformed/curated data (mart, analytics, gold) |
| `transformation` | Data transformation (dbt models, Spark jobs) |
| `orchestration` | Pipeline scheduling (Airflow DAGs, Dagster) |
| `ingestion` | Data loading (Fivetran, Airbyte) |
| `reporting` | BI and visualization (Looker, Tableau) |
| `quality` | Data quality monitoring (Elementary, Great Expectations) |
| `version_control` | Source code management (GitHub, GitLab) |
| `infrastructure` | Hosting/compute (Linux servers, K8s) |
| `semantic` | Semantic layer (dashboards, explores, metrics) |
| `job_runtime` | Generic job/service with no specific capability |

### `resolve_functional_role(node, canonical_type, dataset_zone?, actor_capability?) → str`

4-tier priority chain:

1. **Explicit override** — `node.raw_metadata["functional_role"]` if a valid `FunctionalRole` value
2. **Metadata heuristics** — `dag_id` or `is_orchestrator` → `orchestration`
3. **Canonical type routing:**
   - `"semantic"` → `semantic`
   - `"dataset"` → zone-based: RAW/UNKNOWN → `warehouse_raw`, STAGING/INTERMEDIATE → `warehouse_raw` (if warehouse platform) or `transformation`, MART/ANALYTICS → `warehouse_analytics`
   - `"system"` → `infrastructure`
   - `"service"`/`"job"` → capability-based mapping, else `job_runtime`
4. **Platform category fallback** — `get_category(platform)` → role via `_CAT_TO_ROLE`

### Role-to-Lane Mapping (`_ROLE_TO_LANE`)

| Functional Role | Pipeline Lane |
|----------------|---------------|
| `warehouse_raw` | `warehouse_raw` |
| `warehouse_analytics` | `warehouse_analytics` |
| `transformation` | `transformation` |
| `orchestration` | `transformation` |
| `ingestion` | `ingestion` |
| `reporting` | `reporting` |
| `quality` | `transformation` |
| `version_control` | `ingestion` |
| `infrastructure` | `ingestion` |
| `semantic` | `reporting` |
| `job_runtime` | `transformation` |

**Functional role and visible lane are intentionally separate concepts.** The lane determines where a tool is visually placed in the pipeline layout; the functional role describes what the tool actually does. Orchestration tools (Airflow, Dagster, Prefect) render in the transformation lane for compact architecture layout, but their functional role remains `orchestration` — visible via the role badge in the inspector header. The UI shows both the lane label and the role badge so users can distinguish layout grouping from actual capability.

### Lane Assignment Precedence (`assign_lane()`)

1. **Explicit `lane_override`** — `node.raw_metadata["lane_override"]` if valid `PipelineLane` value
2. **Functional role mapping** — via `_ROLE_TO_LANE` dict
3. **Original zone/capability logic** — unchanged fallback

---

## Part 9: Edge Provenance

Every tool-to-tool edge in the control plane carries an `edgeOrigin` field classifying how the edge was discovered:

| Origin | Meaning | When Set |
|--------|---------|----------|
| `"evidence"` | Backed by observed evidence | Data-plane edges with real evidence (SQL parsing, dbt manifest, query history), or CP edges backed by metadata cross-reference (driver-emitted targets like `orchestrated_tools`, `managed_targets`) |
| `"structural"` | Explicitly declared by user | CP edges backed by PipelineEdge records (user-drawn edges in the pipeline config) |
| `"inferred"` | Weak fallback or co-presence logic | Monitoring coexistence edges, pipeline co-presence fallback edges, bridge-sourced edges, or unresolved weak-matched associations |

**Key distinction:** Bypass paths (`bypassPath`) are **not** "inferred" — they represent compressed evidence from real job chains (dataset→job→dataset). An edge with `edgeOrigin: "evidence"` can carry a `bypassPath`.

**Merge behavior:** When edges merge during dedup (Step 4e), evidence-backed origin wins: if any constituent edge has `edgeOrigin: "evidence"`, the merged edge keeps `"evidence"`.

### Frontend Display

The Inspector Panel shows provenance as a plain-language explanation:
- `"evidence"` → "Derived from observed data lineage evidence (SQL parsing, dbt manifest, query history)"
- `"structural"` → "Derived from explicitly declared control-plane relationships (driver metadata targets, PipelineEdge records)"
- `"inferred"` → "Inferred from co-presence, bridge rules, or weak matching"

The bypass drilldown is a separate collapsible section showing compressed job paths with job names and a summary string.

### Frontend Types

```typescript
// EdgeMetadata additions
edgeOrigin?: 'evidence' | 'structural' | 'inferred';
bypassPath?: BypassPath;

interface BypassJob {
  jobNodeId: string;
  jobNodeName: string;
  originalEdgeIds: string[];
}

interface BypassPath {
  jobs: BypassJob[];
  summary: string;
}

// ToolNodeMetadata addition
functionalRole?: string;
```
