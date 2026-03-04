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
| Next.js API proxy | `app/api/pipeline/[stackId]/lineage/engine/route.ts` |
| FastAPI view endpoints | `scanner/api/routers/lineage.py` |
| ViewBuilder (all views) | `scanner/lineage/engine/views.py` |
| Platform registry | `scanner/lineage/engine/platforms.py` |
| Canonical type system | `scanner/lineage/engine/canonical.py` |
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

**Algorithm:**
1. Walk all graph nodes, classify each into a lane via `assign_lane()` using zone/capability/platform
2. Group by `(lane, platform, integration_id)` → one tool box per group
3. Merge pipeline stack tools not covered by engine discovery
4. Build tool-to-tool flow edges with semantic types (`ingests`, `feeds`, `transforms`, `serves`)
5. Infer edges for isolated tools (lane-adjacency, confidence=0.3)
6. Deduplicate: merge same tool across lanes into one canonical node
7. Compute topological order and assign positions

**Lane Assignment:**
- Orchestrators (Airflow, Dagster) → `transformation` lane
- Infrastructure (Linux) → `ingestion` lane
- Raw zone datasets → `warehouse_raw`
- Mart/analytics zone datasets → `warehouse_analytics`
- BI tools → `reporting`

**Semantic Edge Types:**

| Source Lane → Target Lane | Semantic Type | Label |
|---------------------------|---------------|-------|
| ingestion → warehouse_raw | `ingests` | Ingests |
| warehouse_raw → transformation | `feeds` | Feeds |
| transformation → warehouse_analytics | `transforms` | Builds |
| warehouse_analytics → reporting | `serves` | Serves |
| transformation → warehouse_raw | `orchestrates` | Orchestrates |

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
default                   → GenericDetailView
```

### Edge Inspector

When clicking an edge in the control plane, shows:
- Semantic type label (color-coded)
- Data flow count and confidence bar
- Source and target tool summaries

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
| Bridge rules (inferred) | ≤ 0.5 |
| Lane-adjacency (inferred) | 0.3 |
| Regex/pattern matching | 0.3 |

The data plane colors edges by confidence: green (≥0.8), amber (0.5–0.8), red (<0.5).

---

## Part 6: Key Design Decisions

1. **Three views, one graph** — Pipeline overview, lane overview, and data plane are all projections of the same canonical graph, each optimized for different analysis tasks.

2. **Deterministic layout** — All node positions are computed server-side. The frontend renders pre-computed x,y values (data plane) or applies Dagre (control plane).

3. **Job bypass in data plane** — Job nodes are excluded. When dataset→job→dataset exists, a direct bypass edge is created with evidence from both original edges.

4. **Resolver merge preserves provenance** — When dbt models merge into BigQuery nodes, `discovered_platforms` and `dbt_resource_type` are preserved in raw_metadata for the Inspector Panel to use.

5. **Atomic run publishing** — Failed extractions never update `current_run_id`, so the frontend always sees a complete graph.

6. **Infrastructure is discovery-only** — Linux servers create `system` nodes (excluded from data plane) with running_services/hosted_tools metadata, visible only in the control plane Inspector Panel.

7. **Non-fatal enrichment** — Health enrichment, LLM reconciliation, and cross-tool synthesis all fail silently without breaking the pipeline.
