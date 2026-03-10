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

### Key Files

| Component | Path |
|-----------|------|
| Frontend page | `app/(dashboard)/dashboard/lineage/page.tsx` |
| Pipeline overview types | `components/lineage/pipeline-overview/types.ts` |
| Inspector panel | `components/lineage/pipeline-overview/InspectorPanel.tsx` |
| Tool detail views | `components/lineage/pipeline-overview/tool-details/` |
| VCS detail view | `components/lineage/pipeline-overview/tool-details/VersionControlDetailView.tsx` |
| Next.js API proxy | `app/api/pipeline/[stackId]/lineage/engine/route.ts` |
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
| Tests | `scanner/lineage/engine/tests/test_lane_overview.py` |

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

| Adapter | Tool(s) | Nodes | Edges |
|---------|---------|-------|-------|
| `live_warehouse` | BigQuery, Snowflake, Postgres | Tables, views | SQL-parsed derivations, query history |
| `live_fivetran` | Fivetran | Connectors, destination tables | Connector → table WRITES_TO |
| `live_dbt` | dbt Core/Cloud | Models, sources, tests | DEPENDS_ON from manifest (confidence=1.0) |
| `live_airflow` | Airflow | DAGs, tasks, table refs | DAG→task, task→table edges |
| `live_linux` | Linux servers | Host node (canonical_type=system) | None (discovery-only) |
| `live_elementary` | Elementary | Health enrichment | None (enrichment-only) |
| `live_looker` | Looker | Dashboards, explores | Dashboard→explore→table |
| `live_tableau` | Tableau | Workbooks, datasources | Workbook→datasource→table |

**Infrastructure tools** (linux_server) run in discovery-only mode — they create nodes but skip lineage extraction and correlation.

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

**Algorithm (`build_lane_pipeline_overview` in `views.py`):**

#### Step 1 — Discover Tools per Lane from Engine Graph

Walk all graph nodes. For each node, determine its lane via `assign_lane()` using zone patterns, actor capabilities, and platform category. Build `tool_info` dict keyed by `(lane, tool_id)` where `tool_id = f"{platform}:{integration_id}"` (or just `platform` if no integration).

**Lane Assignment Rules:**
- Orchestrators (Airflow, Dagster) → `transformation` lane
- Infrastructure (Linux) → `ingestion` lane
- Raw zone datasets → `warehouse_raw`
- Mart/analytics zone datasets → `warehouse_analytics`
- BI tools → `reporting`

Each `tool_info` entry tracks: `platform`, `display_name`, `integration_id`, `asset_count`, `is_orchestrator`, `is_infra`.

Also builds two indexes:
- `node_to_tool: Dict[node_id → (lane, tool_id)]` — for edge traversal in Step 4
- `tool_key_to_graph_nodes: Dict[(lane, tool_id) → List[LineageNode]]` — for enrichment in Step 3

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

#### Step 4c — Build ViewEdges from Aggregations

Each `_ToolEdgeAgg` is converted to a `ViewEdge` via `_aggregate_tool_edge()`:

- **evidence_count** = `len(agg.edges)` — number of cross-tool data flow edges
- **flowAssetCount** = `len(agg.asset_ids)` — unique nodes involved
- **Weighted confidence** = `sum(confidence × w) / sum(w)` where `w = 1.0 + log(1.0 + evidence_count_per_edge)`, clamped to [0.3, 0.95]
- **Evidence mix** — normalized counter of evidence source labels (e.g. `dbt_manifest: 0.6, query_history: 0.4`)
- **Top pairs** — up to 10 most frequent `(src_name, tgt_name)` asset pairs
- **Semantic type** — derived by `edge_semantics.derive_semantic_type()` from tool categories and evidence type (see Part 7), then validated by `enforce_semantic_constraints()`. The dominant lane pair is tracked via `_ToolEdgeAgg.lane_pair_counts` so merges don't corrupt semantics.

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

#### Step 4d — Config-Driven Control-Plane Edges

Tools like Airflow, GitHub, and Linux often have no graph-evidence edges because their adapters are stubs or discovery-only. Instead of the old lane-adjacency inference (which created nonsensical edges like Fivetran→GitHub), control-plane edges are derived from **category pairing rules**:

```python
_CP_RULES = [
    ("orchestration",   {"transformation", "ingestion"},                    JOB_ORCHESTRATION),
    ("version_control", {"transformation", "orchestration"},                CODE_OWNERSHIP),
    ("infrastructure",  {"ingestion", "orchestration", "transformation"},   HOSTING),
    ("quality",         {"warehouse", "transformation"},                    MONITORING),
]
```

For each rule, every tool in the source category gets an edge to every tool in each target category, provided no evidence-based edge already exists between that pair. These edges use `derive_semantic_type()` + `enforce_semantic_constraints()` for correct labels.

**Properties:**
- `confidence=0.6` — higher than old inferred (0.3) but lower than evidence-based
- `inferred=False` — these are real structural relationships from the pipeline config
- `evidence_count=0` — distinguishes from data-evidence edges in the UI (dashed lines)
- Only created when no evidence-based edge already exists for that pair

**Example** (BigQuery + dbt + Airflow + Fivetran + Linux + GitHub pipeline):
- Airflow → dbt: `orchestrates` (config-derived)
- Airflow → Fivetran: `orchestrates` (config-derived)
- GitHub → dbt: `manages_code_for` (config-derived)
- GitHub → Airflow: `manages_code_for` (config-derived)
- Linux → Fivetran: `hosts` (config-derived)
- Linux → Airflow: `hosts` (config-derived)

#### Step 4e — Cross-Lane Deduplication

The same tool may appear in multiple lanes (e.g. BigQuery in both `warehouse_raw` and `warehouse_analytics`). This step:

1. Groups view nodes by canonical tool_id (stripped of lane prefix)
2. Merges multi-lane entries: aggregates health, assets, jobs, sub-nodes; keeps latest timestamp
3. Remaps all edge source/target IDs to canonical tool IDs
4. Merges duplicate edges for the same (source, target) pair: sums evidence_count, takes max confidence, prefers real edges over inferred, drops self-loops

Final node ID format: `f"tool:{tool_id}"` (no lane prefix).

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
| `version_control` | Repos, Activity | Repo list from config (owner/org); connection status, sync timestamps |

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

1. **Header renders immediately** from existing `ViewNode.metadata` (health dot, name, lane badge, platform)
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
| Query history (BigQuery jobs) | 0.6 |
| Config-derived control-plane | 0.6 |
| Bridge rules (inferred) | ≤ 0.5 |
| Regex/pattern matching | 0.3 |

The data plane colors edges by confidence: green (≥0.8), amber (0.5–0.8), red (<0.5).

---

## Part 6: Key Design Decisions

1. **Three views, one graph** — Pipeline overview, lane overview, and data plane are all projections of the same canonical graph, each optimized for different analysis tasks.

2. **Deterministic layout** — All node positions are computed server-side. The frontend renders pre-computed x,y values (data plane) or applies Dagre (control plane).

3. **Job bypass in data plane** — Job nodes are excluded. When dataset→job→dataset exists, a direct bypass edge is created with evidence from both original edges.

4. **Resolver merge preserves provenance** — When dbt models merge into BigQuery nodes, `discovered_platforms` and `dbt_resource_type` are preserved in raw_metadata. The pipeline overview uses these to recover cross-tool edges (via `_platform_to_tks` alias-aware index) even when both endpoints share the same primary platform after merge.

5. **Atomic run publishing** — Failed extractions never update `current_run_id`, so the frontend always sees a complete graph.

6. **Infrastructure is discovery-only** — Linux servers create `system` nodes (excluded from data plane) with running_services/hosted_tools metadata, visible only in the control plane Inspector Panel.

7. **Non-fatal enrichment** — Health enrichment, LLM reconciliation, and cross-tool synthesis all fail silently without breaking the pipeline.

8. **Category-driven edge semantics** — Edge labels are derived from `(src_category, tgt_category, evidence_type)` via `edge_semantics.py`, not from lane adjacency. This prevents nonsensical labels like "BigQuery orchestrates dbt". Constraint enforcement (`enforce_semantic_constraints`) downgrades invalid labels to `data_flow` (e.g. `orchestrates` must originate from an orchestration tool).

9. **Config-driven control-plane edges replace lane-adjacency inference** — The old system connected disconnected tools to their nearest lane neighbors, creating false edges (Fivetran→GitHub, Airflow→BigQuery). The new system derives edges from category pairing rules (orchestration→transformation = orchestrates, version_control→transformation = manages_code_for, etc.), producing only structurally meaningful connections.

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

### `derive_semantic_type(src_category, tgt_category, evidence_type, src_lane?, tgt_lane?)`

Returns `(semantic_type_code, display_label)` based on the rules matrix:

- **DATA_DERIVATION**: Uses explicit `(src_cat, tgt_cat)` lookup table (ingestion→warehouse = "ingests", warehouse→transformation = "feeds", etc.)
- **JOB_ORCHESTRATION**: Returns "orchestrates" only if `src_cat == "orchestration"` and `tgt_cat` is in `{ingestion, transformation, warehouse, reporting}`
- **CODE_OWNERSHIP**: Returns "manages_code_for" only if `src_cat == "version_control"` and `tgt_cat` is in `{transformation, orchestration, warehouse, reporting}`
- **HOSTING**: Returns "hosts" only if `src_cat == "infrastructure"` and `tgt_cat` is in `{ingestion, orchestration, transformation, warehouse, reporting}`
- **MONITORING**: Returns "monitors" only if `src_cat == "quality"` and `tgt_cat` is in `{warehouse, transformation, orchestration, reporting}`
- **INFERRED_ADJACENCY**: Falls back to lane-pair map for legacy compatibility
- **Unknown**: Returns `("data_flow", "Data Flow")`

### `enforce_semantic_constraints(semantic_type, label, src_category, tgt_category, evidence_type)`

Guardrail that downgrades invalid labels to `("data_flow", "Data Flow")`:

- `orchestrates` requires `src_category == "orchestration"`
- `hosts` requires `src_category == "infrastructure"`
- `manages_code_for` requires `src_category == "version_control"`
- `monitors` requires `src_category == "quality"`
- Data-flow verbs (`ingests`, `feeds`, `builds`, `serves`) require `evidence_type` in `{DATA_DERIVATION, INFERRED_ADJACENCY}`
