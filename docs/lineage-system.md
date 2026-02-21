# Pallisade Lineage System

> Automated, cross-tool data lineage extraction with evidence tracking, confidence scoring, and deterministic visualization.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Graph Model](#core-graph-model)
3. [Extraction Pipeline](#extraction-pipeline)
4. [Adapters](#adapters)
5. [Resolution & Deduplication](#resolution--deduplication)
6. [Canonical Type Taxonomy](#canonical-type-taxonomy)
7. [Bridge Rules](#bridge-rules)
8. [LLM Reconciliation](#llm-reconciliation)
9. [Rendered Views](#rendered-views)
10. [Run Versioning](#run-versioning)
11. [API Reference](#api-reference)
12. [Frontend](#frontend)
13. [Testing](#testing)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js 15)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  Data View    │  │ Control-Plane│  │  Lane Pipeline Overview  │  │
│  │  (ReactFlow)  │  │  (ReactFlow) │  │      (SVG lanes)         │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
│         │                   │                      │                │
│  ┌──────┴───────────────────┴──────────────────────┘                │
│  │  /api/pipeline/[stackId]/lineage/...  (Next.js proxy routes)    │
│  └──────────────────────────┬──────────────────────────────────────┘│
└─────────────────────────────┼──────────────────────────────────────-┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend (scanner/)                      │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              scanner/api/routers/lineage.py                  │    │
│  │   34 endpoints: extract, investigate, views, runs, query     │    │
│  └──────────────────────────┬──────────────────────────────────┘    │
│                              │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐    │
│  │           scanner/lineage/engine/pipeline.py                 │    │
│  │   ExtractionPipeline — 9-step orchestrator                   │    │
│  │                                                               │    │
│  │   0. start_run ──────────────────────────────────┐           │    │
│  │   1. (LLM planner)                               │           │    │
│  │   2. investigator → adapters → resolver           │           │    │
│  │   3. canonicalize (first pass)                    │           │    │
│  │   4. bridge rules                                 │ RunRegistry│   │
│  │   5. re-canonicalize                              │           │    │
│  │   6. (LLM reconciliation)                         │           │    │
│  │   7. build rendered views                         │           │    │
│  │   8. complete_run (atomic publish) ──────────────┘           │    │
│  │   9. update store.graph (backward compat)                    │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────┐  ┌─────────┐  ┌────────┐  ┌────────────────────┐  │
│  │  Adapters    │  │Resolver │  │ Bridge │  │   ViewBuilder      │  │
│  │  (17 live)   │  │Pipeline │  │ Rules  │  │  3 curated views   │  │
│  └─────────────┘  └─────────┘  └────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Data flow in one sentence:** Adapters extract raw nodes/edges from each tool → Resolver deduplicates → Canonicalization maps types → Bridge fills structural gaps → (optional) LLM patches the graph → ViewBuilder renders deterministic layouts → RunRegistry publishes atomically.

---

## Core Graph Model

**File:** `scanner/lineage/graph.py`

The graph is a directed multigraph where nodes represent data assets and tools, and edges represent relationships between them.

### LineageNode

Every entity in the graph is a `LineageNode`:

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique identifier (usually a deterministic hash) |
| `name` | str | Display name |
| `fqn` | str | Fully qualified name (`database.schema.table`) |
| `node_type` | NodeType | Granular type (TABLE, MODEL, DAG, DASHBOARD, etc.) |
| `platform` | str | Tool name (bigquery, dbt, looker, airflow, n8n, etc.) |
| `platform_domain` | PlatformDomain | Category (WAREHOUSE, TRANSFORM, BI, ORCHESTRATION, etc.) |
| `database` | str? | Database name |
| `schema` | str? | Schema/dataset name |
| `integration_id` | str? | Links node to a specific tool instance |
| `canonical_type` | str? | Mapped type: `system`, `service`, `job`, `dataset`, `semantic` |
| `urn` | str? | Stable URN: `urn:pallisade:{type}:{platform}:{namespace}:{name}` |
| `inferred` | bool | True if created by bridge rules (not directly observed) |
| `evidence` | Evidence[] | Provenance records from adapters |
| `confidence` | float | 0.0–1.0 reliability score |
| `health_status` | HealthStatus | HEALTHY, DEGRADED, FAILING, UNKNOWN, STALE |
| `columns` | dict[] | Column definitions (name, type, description) |
| `row_count` | int? | Number of rows |
| `owner` | str? | Asset owner |
| `tags` | str[] | User-assigned tags |
| `raw_metadata` | dict | Adapter-specific metadata |

**Property:** `stable_id` — deterministic hash from `(domain, namespace, container, name)`. Excludes platform so the same table discovered by BigQuery and dbt gets the same stable_id, enabling cross-adapter deduplication.

### LineageEdge

Every relationship is a `LineageEdge`:

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Deterministic ID from `(source, target, type, level, evidence_ref)` |
| `source_id` | str | Upstream node ID |
| `target_id` | str | Downstream node ID |
| `edge_type` | EdgeType | Relationship type (DEPENDS_ON, WRITES_TO, READS_FROM, etc.) |
| `lineage_level` | LineageLevel | Granularity: TOOL, TABLE, or COLUMN |
| `plane` | LinePlane | DATA, CONTROL, or CROSS |
| `confidence` | float | 0.0–1.0 reliability score |
| `canonical_edge_type` | str? | Mapped type: `hosts`, `runs`, `reads`, `writes`, `derives`, `serves` |
| `inferred` | bool | True if created by bridge rules |
| `evidence` | Evidence[] | Provenance records |
| `column_mappings` | ColumnMapping[] | Column-level lineage |
| `transformation` | str? | SQL snippet showing the transformation |

### Key Enums

**NodeType** (24 values): SOURCE, TABLE, VIEW, MATERIALIZED_VIEW, MODEL, SNAPSHOT, SEED, MACRO, TASK, DAG, FLOW, PIPELINE, WORKFLOW, NOTEBOOK, DASHBOARD, REPORT, DATASET, EXPLORE, WORKBOOK, QUESTION, CONNECTOR, MONITOR, FEATURE, MODEL_ARTIFACT, UNKNOWN

**EdgeType** (13 values): DEPENDS_ON, DERIVED_FROM, JOINS, REFERENCES, TRIGGERS, WRITES_TO, READS_FROM, REFRESHES, POPULATES, TESTS, PRODUCED_BY, MATERIALIZES, SYNCS_TO, QUERIES, MONITORS

**LinePlane** (3 values):
- `DATA` — asset-to-asset relationships (table → table)
- `CONTROL` — orchestration relationships (DAG → task)
- `CROSS` — links between planes (task → table it writes to)

**LineageLevel** (3 values): TOOL (system-level), TABLE (asset-level), COLUMN (field-level)

**PlatformDomain** (8 values): WAREHOUSE, TRANSFORM, ORCHESTRATION, BI, INGESTION, CATALOG, APP, OTHER

### LineageGraph

The `LineageGraph` class provides traversal and query methods:

```python
graph = LineageGraph()
graph.add_node(node)
graph.add_edge(edge)

# Traversal
upstream = graph.get_upstream(node_id, depth=3)
downstream = graph.get_downstream(node_id, depth=-1)  # unlimited
path = graph.get_path(from_id, to_id)
subgraph = graph.get_subgraph(center_id, upstream_depth=2, downstream_depth=2)

# Analysis
roots = graph.get_roots()       # nodes with no upstream
leaves = graph.get_leaves()     # nodes with no downstream
critical = graph.get_critical_path()  # longest path

# Serialization
d = graph.to_dict()
graph2 = LineageGraph.from_dict(d)
```

Internal indexes maintained: `_upstream`, `_downstream` (adjacency), `_by_platform`, `_by_type`, `_by_database`, `_by_lineage_level`, `_by_plane`, `_by_confidence_bucket`.

### Evidence

Every edge (and optionally node) carries provenance:

```python
Evidence(
    adapter_id="live_warehouse:bigquery",
    source_ref="bigquery:job:project.analytics.stg_customers",
    observed_at=datetime(2024, 1, 15),
    snippet="SELECT * FROM raw.customers WHERE ...",
)
```

Evidence enables:
- **Confidence scoring** — weighted by source reliability (declarative=1.0, compiled_sql=0.8, query_history=0.6, regex=0.3)
- **Explainability** — clicking an edge shows exactly why it exists
- **Deduplication** — same edge from multiple adapters gets merged evidence

---

## Extraction Pipeline

**File:** `scanner/lineage/engine/pipeline.py`

The `run_extraction_pipeline()` function orchestrates the full lineage extraction with correct step ordering:

```
Step 0: Start run_id via RunRegistry
           │
Step 1: (optional) LLM planner → adapter execution order
           │
Step 2: Investigator executes adapters → raw nodes/edges → resolver → graph
           │
Step 3: Canonicalize types (first pass)
           │
Step 4: Deterministic bridge rules (uses canonical types to identify orphans)
           │
Step 5: Re-canonicalize (bridge-added nodes need types too)
           │
Step 6: (optional) LLM reconciliation → patch → validate → apply
           │
Step 7: Build rendered views (PipelineOverview, DataPlane, LanePipelineOverview)
           │
Step 8: Persist artifacts under run_id, atomically publish current_run_id
           │
Step 9: Update store.graph for backward-compatible query endpoints
```

**Critical ordering constraint:** Bridge rules MUST run AFTER canonicalization (so nodes have `canonical_type` for orphan detection) but BEFORE views are built (so bridge-added nodes appear in views).

```python
async def run_extraction_pipeline(
    tool_configs: List[ToolConfig],
    registry: RunRegistry,
    store: GraphStore,
    config: ExtractionPipelineConfig,
) -> str:  # returns run_id
```

On **success**: `registry.current_run_id` is atomically updated and `store.graph` is set.
On **failure**: `current_run_id` stays pointing to the previous successful run — the frontend never sees a broken state.

### Investigator

**File:** `scanner/lineage/engine/investigator.py`

The `LineageInvestigator` executes adapters in data-flow order, accumulating context at each step:

```
WAREHOUSE (order=0) → INGESTION (1) → TRANSFORMATION (2) →
ORCHESTRATION (3) → REPORTING (4) → INFRASTRUCTURE (5) →
VERSION_CONTROL (6) → QUALITY (7)
```

Each adapter enriches a shared `InvestigationContext` — a "detective's notebook" that tracks:
- **Table inventory** — all discovered tables with their FQNs
- **Connections** — tool-to-tool relationships
- **Unresolved references** — table names that couldn't be matched
- **Tool profiles** — per-tool extraction metadata

After each adapter, the `CorrelationEngine` runs cross-tool pattern matching:
1. **Table reference matching** — match adapter table refs to warehouse tables
2. **Connection string matching** — align by host:port:database
3. **Schedule alignment** — compare cron expressions
4. **Retry unresolved** — re-attempt previously failed matches
5. **Infrastructure hosting** — detect which servers host which tools

---

## Adapters

**File:** `scanner/lineage/engine/adapter.py` (base), `scanner/lineage/engine/adapters/` (implementations)

### Adapter Framework

All adapters inherit from `BaseLineageAdapter` and declare capabilities:

```python
class BaseLineageAdapter:
    def id(self) -> str: ...
    def capabilities(self) -> Set[Capability]: ...
    def discover_assets(self, config) -> List[LineageNode]: ...
    def extract_lineage(self, config) -> List[LineageEdge]: ...
    def fetch_context(self, config) -> Dict: ...  # optional
    def case_hint(self) -> str: ...  # "lower", "upper", "preserve"
```

**Capabilities:** DISCOVER_ASSETS, EXTRACT_TOOL_LINEAGE, EXTRACT_TABLE_LINEAGE, EXTRACT_COLUMN_LINEAGE, GET_RUNS_LOGS, GET_QUERY_HISTORY, GET_OWNERSHIP, GET_CONTRACTS, GET_BI_EXPOSURES

The `AdapterRegistry` allows creating adapters by type name without hardcoding:

```python
registry = create_default_registry()
adapter = registry.create("live_warehouse", "bq-prod", project_id="my-project")
```

### Live Adapters (17 total)

#### Warehouse

| Adapter | Tool | Nodes | Edges | Notes |
|---------|------|-------|-------|-------|
| `live_warehouse` | BigQuery, Snowflake, Postgres, Redshift | TABLE, VIEW, SOURCE | Table-level lineage from queries/views | SQL parsing via sqlglot, platform-specific case hints |
| `live_dbt` | dbt Core/Cloud manifest | MODEL, SOURCE, SEED, SNAPSHOT | DEPENDS_ON (confidence 1.0) | Declarative — highest confidence |

#### BI / Reporting

| Adapter | Tool | Nodes | Edges | Notes |
|---------|------|-------|-------|-------|
| `live_looker` | Looker | DASHBOARD, MODEL | Model→Dashboard, Table→Dashboard | SQL parsing of tile queries and explore definitions |
| `live_metabase` | Metabase | DASHBOARD, QUESTION | Card→Dashboard, Table→Card | Handles native SQL and GUI query modes |
| `live_tableau` | Tableau | WORKBOOK, DATASET | Datasource→Workbook, Table→Datasource | Connection metadata parsing |
| `live_powerbi` | Power BI | REPORT, DATASET | Dataset→Report, Table→Dataset | Datasource connection string parsing |

#### Orchestration

| Adapter | Tool | Nodes | Edges | Notes |
|---------|------|-------|-------|-------|
| `live_airflow` | Apache Airflow | DAG, TASK | DAG→Task, Task→Task, Task↔Table | Static DAG parsing or REST API mode |
| `live_dagster` | Dagster | TASK (assets), PIPELINE | Asset→Asset, Asset→Table, Schedule→Asset | compute_kind hinting for materialization |
| `live_prefect` | Prefect | FLOW, PIPELINE | Deployment→Flow, Flow↔Table | Tag-based table refs (`reads:schema.table`) |
| `live_n8n` | n8n | WORKFLOW, TASK | Workflow→Task, Task↔Table | DB node parameter extraction + SQL regex |

#### Ingestion

| Adapter | Tool | Nodes | Edges | Notes |
|---------|------|-------|-------|-------|
| `live_fivetran` | Fivetran | SOURCE, TABLE | Connector→Table (POPULATES) | Connector schema introspection |
| `live_airbyte` | Airbyte | SOURCE, PIPELINE, TABLE | Connection→Table (POPULATES) | syncCatalog stream mapping |
| `live_storage` | S3, GCS, ADLS | SOURCE (buckets) | Storage→Table via known_mappings | Discovery-only unless mappings configured |

#### Other

| Adapter | Tool | Nodes | Edges | Notes |
|---------|------|-------|-------|-------|
| `live_elementary` | Elementary | MONITOR | Monitor→Table (MONITORS) | Data quality health enrichment |
| `live_openlineage` | Marquez, OL backends | From events | From events | Maps standard OpenLineage RunEvents |
| `live_databricks` | Databricks | NOTEBOOK, TABLE | Notebook↔Table | Unity Catalog integration |
| `live_linux` | Linux servers | DATASET (server) | None | Infrastructure discovery only |
| `live_github` | GitHub | (stub) | (stub) | Placeholder for future code-level lineage |

### SQL Parsing

**File:** `scanner/lineage/engine/sql_lineage.py`

The `SQLLineageExtractor` uses sqlglot for multi-dialect SQL parsing with regex fallback:

```python
extractor = SQLLineageExtractor()
refs = extractor.extract_table_refs(sql, dialect="bigquery")
# {"sources": ["raw.customers", "raw.orders"], "targets": ["analytics.dim_customers"]}
```

Supported dialects: snowflake, bigquery, databricks, spark, redshift, postgres, mysql, duckdb, trino, presto, sqlite, oracle, mssql/tsql.

Column-level lineage traces columns through CTEs and returns `ColumnMapping` objects.

---

## Resolution & Deduplication

**File:** `scanner/lineage/engine/resolver.py`

The `ResolverPipeline` normalizes and deduplicates after all adapters run:

```
Step 1: Normalize identifiers (case_hint per adapter)
Step 2: Deduplicate nodes by stable_id
         (priority: warehouse > transform > BI > orchestration > ingestion)
Step 3: Remap edge references through dedup mapping
Step 4: Merge edges by (source, target, type, level)
         → merge evidence, compute weighted confidence
```

**Why it matters:** The same table `raw.customers` appears as:
- A BigQuery TABLE from `live_warehouse`
- A dbt SOURCE from `live_dbt`
- A Fivetran destination from `live_fivetran`

All three get the same `stable_id` (since `generate_stable_id` uses domain/namespace/container/name, excluding platform). The resolver keeps the richest node (warehouse priority) and merges metadata from all three.

**Weighted confidence:**

```python
EVIDENCE_WEIGHTS = {
    "declarative": 1.0,      # dbt manifest, config files
    "api_metadata": 0.9,     # tool API responses
    "compiled_sql": 0.8,     # parsed SQL
    "query_history": 0.6,    # warehouse query logs
    "regex": 0.3,            # regex fallback
}
```

---

## Canonical Type Taxonomy

**File:** `scanner/lineage/engine/canonical.py`

Maps the 24 granular `NodeType` values and 13 `EdgeType` values to a strict **5-node, 6-edge** canonical taxonomy. This normalization enables consistent rendering and lane assignment regardless of which adapter discovered the node.

### Canonical Node Types

| Type | Description | Examples |
|------|-------------|----------|
| `system` | Infrastructure | Linux server, VM, cloud account |
| `service` | Tool instance | Snowflake cluster, dbt Cloud, Looker instance |
| `job` | Executable unit | DAG, task, workflow, connector, monitor |
| `dataset` | Data asset | Table, view, model, seed, snapshot, file, topic |
| `semantic` | Presentation | Dashboard, report, workbook, explore |

### Canonical Edge Types

| Type | From → To | Description |
|------|-----------|-------------|
| `hosts` | system → service | Infrastructure hosting |
| `runs` | service → job | Tool executes job |
| `reads` | job/semantic → dataset | Data consumption |
| `writes` | job → dataset | Data production |
| `derives` | dataset → dataset | Derivation chain |
| `serves` | dataset → semantic | Data presentation |

### URN Generation

Each node gets a stable URN: `urn:pallisade:{canonical_type}:{platform}:{namespace}:{name}`

### Layer Mapping

Canonical types map to layers for UI positioning:

```
INGESTION → ingestion
WAREHOUSE → warehouse
TRANSFORM → transformation
BI → reporting
ORCHESTRATION → orchestration
CATALOG → quality
OTHER → infrastructure
```

---

## Bridge Rules

**File:** `scanner/lineage/engine/bridge.py`

Deterministic (non-LLM) rules that fix structural gaps in the graph. Currently implements one rule:

### Rule: `bridge_missing_ingestion`

**Problem:** Raw warehouse tables (like `raw.customers`, `raw.orders`) appear as root nodes (no upstream) even though an ingestion tool (n8n, Fivetran, etc.) is present in the graph.

**Detection:**
1. Find ingestion platforms in graph (n8n, airbyte, fivetran, etc.)
2. Find raw datasets with `canonical_type == "dataset"` and `zone == RAW`
3. Check if any raw dataset has no upstream writer (no `writes` or `runs` edge from a `service` or `job` node)

**Fix:**
1. Create an **inferred loader job** per ingestion platform: `urn:job:{platform}:unknown_loader::{integration_id}`
2. Create **writes edges** from loader → each orphaned raw dataset
3. Connect **ingestion service → loader** via `runs` edge

All inferred nodes/edges are marked `inferred=True` with `confidence=0.4` and evidence from `"bridge_rule"`.

**Example:**
```
Before:                          After:
                                 n8n (service)
                                   │ runs
                                   ▼
raw.customers (orphan)           N8n Loader (inferred, job)
raw.orders    (orphan)             │ writes    │ writes
raw.events    (orphan)             ▼           ▼
                                 raw.customers  raw.orders  raw.events
```

### Zone Classification

**File:** `scanner/lineage/engine/zones.py`

Datasets are classified into zones for bridge rule detection and lane assignment:

| Zone | Detection | Examples |
|------|-----------|---------|
| RAW | dbt source type, schema name contains `raw`/`landing`/`staging_raw` | `raw.customers` |
| STAGING | dbt model path `/staging/`, schema `stg_`/`staging` | `stg_customers` |
| INTERMEDIATE | dbt path `/int/`/`/intermediate/`, schema `int_` | `int_customer_orders` |
| MART | dbt path `/mart/`, schema `mart`/`marts`/`analytics` | `dim_customers` |
| ANALYTICS | dbt model (default), schema `analytics`/`reporting` | `fct_daily_revenue` |
| UNKNOWN | No pattern matched | |

---

## LLM Reconciliation

**File:** `scanner/lineage/engine/reconciler.py`

Optional post-canonicalization phase where an LLM analyzes the graph for structural issues and produces a validated patch.

### Diagnostics

The `DiagnosticsBuilder` identifies:
- **Dataset roots** — datasets with no upstream (potential missing ingestion)
- **Disconnected components** — subgraphs not connected to the main component
- **Suspected duplicates** — nodes with same name across platforms
- **Missing link hints** — ingestion/transform tools with no downstream edges

### Patch Format

The LLM returns a `ReconciliationPatch`:

```python
ReconciliationPatch(
    merge_suggestions=[
        MergeSuggestion(keep_id="bq:raw.users", merge_ids=["dbt:raw.users"], reason="Same table", confidence=0.95)
    ],
    add_nodes=[
        AddNodePatch(canonical_id="fivetran_loader", node_type="job", platform="fivetran", ...)
    ],
    add_edges=[
        AddEdgePatch(from_id="fivetran_loader", to_id="raw.users", edge_type="writes", ...)
    ],
    layer_assignments=[
        LayerAssignment(canonical_id="raw.users", layer="warehouse_raw", ...)
    ],
    unknowns=[
        UnknownItem(entity_ref="mystery_table", issue="Cannot determine origin", ...)
    ],
)
```

### Validation & Application

The `PatchValidator` checks:
- Merge targets exist in graph
- Added nodes don't duplicate existing IDs
- Added edges reference valid node IDs
- Edge types are from the canonical 6-type taxonomy

The `PatchApplier` applies the validated patch:
- Merges nodes (keeps richest, remaps edges)
- Adds new nodes with evidence from reconciler
- Adds new edges
- Assigns layers

Re-canonicalization runs after patch application.

---

## Rendered Views

**File:** `scanner/lineage/engine/views.py`

The `ViewBuilder` produces three curated, deterministically-laid-out views from the canonical graph. Views are pre-computed during the pipeline and stored with the run artifacts — no client-side layout computation needed.

### Pipeline Overview

**Type:** `pipeline_overview`

Tool-sequence view showing how integrations connect:

```
Fivetran → Snowflake → dbt → Snowflake → Looker
```

- Groups nodes by `(platform, integration_id)` → service clusters
- Inter-cluster edges derived from cross-platform data edges
- Deterministic X/Y positioning by layer order

### Data Plane

**Type:** `data_plane`

Dataset-to-dataset derivation chains:

```
raw.customers → stg_customers → dim_customers → dashboard_tile
```

- Selects DATASET + SEMANTIC nodes
- Includes JOB nodes that have both upstream and downstream dataset connections
- Topological layout (longest-path layer assignment)
- Deduplicates Airflow table refs with warehouse nodes by FQN

### Lane Pipeline Overview

**Type:** `lane_pipeline_overview`

Fixed-lane layout with five horizontal lanes:

```
┌─────────────────────────────────────────────────────────────┐
│ INGESTION        │ Fivetran, n8n Loader (inferred)          │
├──────────────────┼──────────────────────────────────────────┤
│ WAREHOUSE (RAW)  │ raw.customers, raw.orders, raw.events    │
├──────────────────┼──────────────────────────────────────────┤
│ TRANSFORMATION   │ stg_customers, int_customer_orders        │
├──────────────────┼──────────────────────────────────────────┤
│ WAREHOUSE (ANALYTICS) │ dim_customers, fct_daily_revenue    │
├──────────────────┼──────────────────────────────────────────┤
│ REPORTING        │ Dashboard: Customer Overview              │
└──────────────────┴──────────────────────────────────────────┘

Orchestrator overlay (dashed lines):
  Airflow DAG "daily_pipeline" ──runs──► stg_customers, int_customer_orders
```

- Classifies nodes by zone (raw/staging/intermediate/mart/analytics) and capability (ingestion/transformation/reporting)
- Orchestration nodes rendered as overlays, not in data lanes
- Inferred nodes shown with dashed borders
- System/infra nodes excluded from lanes

### View Data Structures

```python
ViewNode(id, name, canonical_type, platform, layer, cluster_id, x, y, inferred, metadata)
ViewEdge(id, source_id, target_id, canonical_type, confidence, inferred, evidence_count)
ViewCluster(id, label, platform, layer, x, y, width, height, node_count)
RenderedView(view_type, nodes, edges, clusters, lanes, orchestrators, stats)
```

---

## Run Versioning

**File:** `scanner/lineage/engine/run_registry.py`

Each extraction creates a versioned `RunRecord` identified by a 12-character hex run_id. The `RunRegistry` provides atomic publish semantics.

### Lifecycle

```
start_run(["bigquery", "n8n", "dbt_core"])
    │
    ▼
RunStatus.RUNNING ──success──► RunStatus.COMPLETED
                   ──failure──► RunStatus.FAILED
```

### Atomic Publish

```python
registry.complete_run(run_id, artifacts)  # sets current_run_id atomically
registry.fail_run(run_id, errors)         # does NOT update current_run_id
```

The `current_run_id` pointer **only updates on success**. If extraction fails, the previous successful run's views stay visible to the frontend.

### RunArtifacts

Each completed run stores:
- `graph_dict` — serialized LineageGraph
- `views` — pre-computed views (pipeline_overview, data_plane, lane_pipeline_overview)
- `diagnostics` — graph structural analysis
- `reconciliation` — LLM patch results (if used)
- `stats` — extraction metrics
- `bridge_result` — bridge rule application results

### Eviction

The registry keeps at most `max_history` runs (default 10). The current run is never evicted.

---

## API Reference

**File:** `scanner/api/routers/lineage.py` (34 endpoints)

### Extraction

| Method | Path | Description |
|--------|------|-------------|
| POST | `/lineage/extract` | Extract lineage from single warehouse/tool |
| POST | `/lineage/extract-unified` | Extract cross-tool lineage from all integrations |
| POST | `/lineage/extract-tool` | Extract from any registered adapter by type |
| POST | `/lineage/investigate` | Sequential investigation across all tools |
| POST | `/lineage/investigate-llm` | LLM-enhanced investigation with planner + reconciler |

### Query

| Method | Path | Description |
|--------|------|-------------|
| GET | `/lineage/engine/upstream/{asset_id}` | Upstream lineage with filtering (depth, level, confidence) |
| GET | `/lineage/engine/downstream/{asset_id}` | Downstream lineage with filtering |
| GET | `/lineage/engine/blast-radius/{asset_id}` | Impact analysis — total downstream by domain/kind |
| GET | `/lineage/engine/explain-edge/{edge_id}` | Evidence chain and confidence calculation for an edge |
| GET | `/lineage/engine/graph` | Full engine graph (optional plane filter) |
| GET | `/lineage/node/{node_id}` | Lineage for specific node with depth control |

### Views (Pre-computed)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/lineage/engine/views/pipeline-overview` | Tool-sequence view |
| GET | `/lineage/engine/views/data-plane` | Dataset derivation chains |
| GET | `/lineage/engine/views/lane-pipeline-overview` | Lane-based pipeline view |

These endpoints serve from pre-computed run artifacts first, falling back to on-demand computation.

### Run Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/lineage/runs/current` | Current published run_id and status |
| GET | `/lineage/runs/{run_id}/status` | Lightweight polling endpoint |
| GET | `/lineage/runs/{run_id}/views/{view_type}` | View from specific run |
| GET | `/lineage/runs` | List recent runs (limit=5) |

### Control Plane

| Method | Path | Description |
|--------|------|-------------|
| GET | `/lineage/engine/control-plane` | Full orchestration subgraph |
| GET | `/lineage/engine/control-plane/{dag_id}` | Subgraph for specific DAG |
| GET | `/lineage/engine/control-plane-overview` | High-level tool sequence |
| GET | `/lineage/engine/cross-links/{asset_id}` | Cross-plane edges for an asset |
| GET | `/lineage/engine/run-history/{dag_id}` | Recent run history for DAG |

### LLM Reconciliation

| Method | Path | Description |
|--------|------|-------------|
| GET | `/lineage/engine/reconcile/diagnostics` | Graph diagnostics (no LLM call) |
| POST | `/lineage/engine/reconcile` | Run LLM reconciliation |
| POST | `/lineage/engine/reconcile/apply` | Apply a reviewed patch |

### Persistence & Export

| Method | Path | Description |
|--------|------|-------------|
| GET | `/lineage/engine/snapshot` | Serialize graph for DB storage |
| POST | `/lineage/engine/restore` | Restore graph from snapshot |
| GET | `/lineage/engine/export` | Export as JSON, GraphML, or DOT |
| GET | `/lineage/engine/stats` | Coverage statistics |
| POST | `/lineage/engine/clear-cache` | Reset engine cache |

### OpenLineage

| Method | Path | Description |
|--------|------|-------------|
| POST | `/lineage/openlineage/event` | Ingest single OpenLineage RunEvent |
| POST | `/lineage/openlineage/events` | Ingest batch of events |

### Query Parameters

Most query endpoints accept these filter parameters:
- `level` — tool, table, column
- `system` — filter by platform name
- `domain` — filter by platform domain
- `kind` — filter by asset kind
- `min_confidence` — minimum confidence threshold (0.0–1.0)
- `depth` — traversal depth (1–50, default 3)
- `plane` — data, control, cross, all

---

## Frontend

### Proxy Routes

The Next.js frontend proxies all lineage requests through two route files:

| Route | Purpose |
|-------|---------|
| `app/api/pipeline/[stackId]/lineage/route.ts` | POST: trigger extraction, GET: fetch stored, DELETE: clear |
| `app/api/pipeline/[stackId]/lineage/engine/route.ts` | GET/POST: proxy all engine actions to FastAPI |
| `app/api/pipeline/[stackId]/lineage/unified/route.ts` | GET: assemble unified graph (tool nodes + engine data) |

The engine proxy maps action names to FastAPI endpoints:
```
action=upstream&id=X  →  /api/v1/lineage/engine/upstream/X
action=runs-current   →  /api/v1/lineage/runs/current
action=run-status&id=X →  /api/v1/lineage/runs/X/status
```

### Extraction Flow

```
User clicks "Extract Lineage"
    │
    ├─ POST /api/pipeline/[stackId]/lineage
    │   ├─ Fetches all CONNECTED nodes from PipelineStack
    │   ├─ Decrypts configs, injects GitHub credentials
    │   ├─ Calls POST /api/v1/lineage/investigate (FastAPI)
    │   └─ Returns run_id
    │
    ├─ Frontend polls GET engine?action=runs-current (every 2s)
    │   ├─ Status: running → show "Updating..." badge, keep old view
    │   ├─ Status: completed → fetch unified graph, atomic swap
    │   └─ Status: failed → show error, keep old view
    │
    └─ GET /api/pipeline/[stackId]/lineage/unified
        ├─ Merges PipelineNodes (tool layer) with Engine graph (data layer)
        ├─ Deduplicates Airflow table refs with warehouse nodes
        ├─ Creates synthetic edges (tool ↔ data asset)
        └─ Returns UnifiedLineageResponse
```

### View Tabs

| Tab | Rendering | Layout | Source |
|-----|-----------|--------|--------|
| Data | ReactFlow + Dagre | Auto-layout | Unified graph (tool + data nodes) |
| Control-Plane | ReactFlow + Dagre | Auto-layout | Engine graph filtered to orchestration |
| Lane Overview | Custom SVG | Pre-positioned lanes | `lane_pipeline_overview` view from engine |

### Types

**File:** `components/lineage/types.ts`

Key interfaces:
- `UnifiedLineageNode` — complete node with category, layer, metadata
- `UnifiedLineageEdge` — edge with confidence, level, plane, evidence
- `ViewNode`, `ViewEdge`, `ViewCluster` — pre-positioned view elements
- `LaneMeta` — lane metadata (name, order, node count)
- `OrchestratorOverlay` — control-plane job runners
- `RunStatusResponse` — run polling response
- `EngineCoverageStats` — coverage metrics
- `EdgeEvidence` — provenance record

### Filters

**File:** `components/lineage/LineageFilterBar.tsx`

| Filter | Type | Notes |
|--------|------|-------|
| Layer toggles | Multi-select buttons | INGESTION, TRANSFORMATION, WAREHOUSE, etc. |
| Node type toggles | Boolean | Tools vs Data Assets |
| Lineage level | Radio | All / Table / Column |
| Confidence slider | Range 0–100% | Filters edges below threshold |
| Inferred nodes | Toggle | Show/hide bridge-created nodes |
| Search | Text input | Matches name, FQN, tool type |

### Visual Encoding

| Element | Encoding |
|---------|----------|
| Edge confidence ≥80% | Green |
| Edge confidence 50–80% | Amber |
| Edge confidence <50% | Red |
| Inferred nodes | Dashed border, purple accent |
| Cross-plane edges | Dashed orange lines |
| Node criticality | Badge (critical=red, high=orange, medium=yellow) |

---

## Testing

**File:** `scanner/lineage/engine/tests/`

The engine has 300+ tests covering:

| Test File | Coverage |
|-----------|----------|
| `test_run_pipeline.py` | RunRegistry lifecycle, pipeline step ordering, bridge nodes in views, failure handling, eviction |
| `test_lane_views.py` | Lane assignment, zone classification, orchestrator overlays, edge routing, view rendering |
| `test_bridge.py` | Bridge rule detection, inferred node creation, orphan identification |
| `test_canonical.py` | Type mapping, URN generation, layer assignment |
| `test_resolver.py` | Deduplication, evidence merging, confidence weighting |
| `test_views.py` | All three view types, cluster building, topological layout |
| `test_reconciler.py` | Patch validation, patch application, LLM prompt building |
| `test_zones.py` | Zone classification patterns, lane assignment logic |
| `test_adapters_*.py` | Per-adapter extraction tests |

Run all engine tests:
```bash
pytest scanner/lineage/engine/tests/ -v
```

---

## Key Design Decisions

### Evidence-based lineage
Every edge carries provenance records explaining WHY it exists. This enables confidence scoring, explainability, and trust.

### Cross-adapter deduplication via stable_id
The `stable_id` hash excludes `platform`, so `bigquery:raw.customers` and `dbt:raw.customers` get the same ID and are merged by the resolver.

### Canonical taxonomy (5+6)
Reducing 24 node types and 13 edge types to 5 canonical node types and 6 edge types enables consistent visualization and lane assignment across any combination of tools.

### Atomic publish semantics
Failed extractions never corrupt the frontend state. The `current_run_id` only updates on success.

### Pre-computed views
Views are built once during the pipeline and stored with run artifacts. Subsequent requests serve instantly from cache instead of recomputing.

### Bridge rules before views
Bridge rules MUST run after canonicalization (to detect orphans by `canonical_type`) but before views (so inferred nodes appear in the visualization). This ordering is enforced by the pipeline orchestrator.
