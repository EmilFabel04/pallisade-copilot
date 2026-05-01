# Sources Category & Integration Verification — Design

**Date:** 2026-05-01
**Status:** Draft, awaiting user review
**Owner:** Emil
**Builds on:** [2026-04-30-custom-source-integration-design.md](./2026-04-30-custom-source-integration-design.md)

## Goal

Make Sources a first-class, leftmost layer in the Pallisade pipeline — both in the backend taxonomy (already half-done by the prior spec) and in the frontend pipeline UI (which currently misclassifies Custom Source as `INGESTION`). Restructure the integrations connect page so Sources is its own category that hosts named connectors. Add a multi-path discovery flow that auto-fills datasets from ingestion or warehouse anchors, and a save-gate that won't let an integration go live until a real dry-probe of every dataset succeeds — so an integration that exists in the DB is, by construction, a working integration.

## Why now

The prior Custom Source spec correctly added `IntegrationLayer.SOURCE` to the backend Python enum and `IntegrationType.CUSTOM_SOURCE` to Prisma, but the frontend pipeline taxonomy was never updated. Today the pipeline page (`app/(dashboard)/dashboard/pipeline/page.tsx:184–195`) shoves Custom Source into `layer: 'INGESTION'` because the frontend `PipelineLayer` union has no `SOURCE` value. The result reads as "Pallisade thinks an IoT portal is an ingestion tool," which is wrong — sources are upstream of ingestion (they are what ingestion *reads from*), and treating them as one connector hidden inside Ingestion makes the whole feature feel bolted-on rather than load-bearing. This spec fixes the taxonomy in the UI, makes Sources a real category that named connectors (Salesforce, Shopify, HubSpot) can join later, and tightens the integration-add flow so the operator gets a useful "this works" signal at config time rather than discovering breakage hours later when the first scheduled probe fails.

## Non-goals

This spec is explicitly carved-out per the project-wide *no open-ended work* rule:

- **No working Salesforce / Shopify / HubSpot connectors.** They appear in the Sources picker as "Coming soon" tiles (logos provided by user). Clicking opens a small request-access modal — never a wizard.
- **No new monitor types.** Existing four (freshness / volume / null / schema-drift) already cover Custom Source via the prior spec's wiring; no additions in this branch.
- **No OAuth / SAML for any source.** Auth flows remain api_key / bearer / basic per the prior spec.
- **No moving of customer data.** Pallisade remains monitor-only — only derived metrics are persisted, ever. (See `feedback_pallisade_role_monitor_only`.)
- **No discovery from ETL platforms we don't already have drivers for.** Path 2 (ingestion-anchored discovery) covers exactly Fivetran, Airbyte, Stitch — the three drivers in `scanner/drivers/ingestion/`. Anything else falls back to manual.
- **No fuzzy auto-suggestion of warehouse tables by name match.** Path 3 (warehouse-anchored) requires the user to pick the landing table from a typeahead — no name-similarity guessing.
- **No schema-drift comparison against warehouse-expected schema in this branch.** The data is captured but the upgraded comparator is deferred. Existing source-vs-history schema-drift continues to work.

## High-level architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Integrations connect page (NEW: connect/page.tsx)                   │
│   Category-grouped picker. Sources = leftmost category.              │
│   Custom Source (live) → wizard. Salesforce/Shopify/HubSpot          │
│   (coming soon) → request-access modal.                              │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ user picks Custom Source
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Custom Source Wizard  (REWORKED)                                    │
│   1. Identity                                                        │
│   2. Connection (test_connection gates Next)                         │
│   3. Discovery (NEW)  ──── runs Paths 1/2/3 in parallel ────┐        │
│   4. Schedule                                               │        │
│   5. Review & Verify (T2 dry-probe via SSE; Save gated)     │        │
└─────────────────────────────────────────────────────────────┼────────┘
                               │                              │
                               │ POST /verify (SSE)           │ POST /discover
                               ▼                              ▼
┌──────────────────────────────────────────┐   ┌──────────────────────────────┐
│  Verify endpoint                         │   │  Discovery orchestrator      │
│   probes every dataset; streams ✓/✗;     │   │   IngestionDiscoverer        │
│   integration persists ONLY on all-pass  │   │    (Fivetran/Airbyte/Stitch) │
└──────────────────────────────────────────┘   │   WarehouseDiscoverer        │
                                               │    (BQ/SF/PG/RS adapters)    │
                                               │   SourceProbeDiscoverer      │
                                               │    (wraps HttpProbeAdapter)  │
                                               └──────────────────────────────┘
```

Everything below the Connection step composes over infrastructure already built by the prior spec — `HttpProbeAdapter`, `CustomSourceDriver`, `CustomSourceProbeRun`, scheduled probe runner, monitor wiring. This spec does not touch that machinery; it sits on top.

## Frontend taxonomy changes

In `components/pipeline/types.ts`:

- **`PipelineLayer` union (line 8)** — prepend `'SOURCE'`. New union: `'SOURCE' | 'INGESTION' | 'TRANSFORMATION' | 'WAREHOUSE' | 'REPORTING' | 'STORAGE' | 'VERSION_CONTROL' | 'ORCHESTRATION' | 'INFRASTRUCTURE' | 'NOTIFICATIONS' | 'UNCATEGORIZED'`.
- **`LAYER_LABELS.SOURCE = 'Sources'`** (line 45 record).
- **`LAYER_COLORS.SOURCE = '#64748B'`** (slate) — distinct from the existing palette and reads visually as upstream of INGESTION's emerald.
- **`ToolDefinition`** — add optional `status?: 'live' | 'coming_soon'` (defaults to `'live'` when absent so existing tools are unaffected).
- **`TOOLS.SOURCE: ToolDefinition[]`** — four entries:
  - `custom_source` — `status: 'live'`, routes to existing wizard.
  - `salesforce`, `shopify`, `hubspot` — `status: 'coming_soon'`, no wizard route.

In `app/(dashboard)/dashboard/pipeline/page.tsx`:

- Prepend `'SOURCE'` to the local `ConnectorGroup` union (line 27) and `LAYER_ORDER` array (line 50) and `CORE_GROUP_ORDER` (line 49).
- Add `SOURCE` to the per-layer X-position map (line 119): `SOURCE: 0`, then shift `INGESTION: 120 → 180`, `VERSION_CONTROL: 300 → 360`, `ORCHESTRATION: 300 → 360`, `TRANSFORMATION: 480 → 540`, with downstream layers cascading by the same +60 delta. Concrete numbers committed here so layout is reproducible.
- **Delete** the feature-flag-conditional injection at lines 184–195 that registers Custom Source with `group: 'INGESTION', layer: 'INGESTION'`. Custom Source is now permanently registered via `TOOLS.SOURCE` like any other connector.
- The pipeline-page connector list-build code (the `...TOOLS.X.map(...)` chain at lines 171–179) gains one more spread: `...TOOLS.SOURCE.map(t => ({ ..., group: 'SOURCE' as const, layer: t.layer }))`.
- Coming-soon tiles render with the existing muted-card visual treatment used elsewhere for unsupported tools and disable the connect CTA. Clicking opens the request-access modal rather than navigating.

## Sources picker — connect page

Today the worktree has only `app/(dashboard)/dashboard/integrations/connect/custom-source/`. We add a new index route:

`app/(dashboard)/dashboard/integrations/connect/page.tsx` — category-grouped picker. Sources is the first category (leftmost in pipeline order). Within Sources:

| Tile | Status | Click behaviour |
|---|---|---|
| Custom Source | live | navigates to `/integrations/connect/custom-source` (existing wizard) |
| Salesforce | coming_soon | opens `<RequestAccessModal connector="salesforce" />` |
| Shopify | coming_soon | opens `<RequestAccessModal connector="shopify" />` |
| HubSpot | coming_soon | opens `<RequestAccessModal connector="hubspot" />` |

Other categories (Warehouses, Ingestion, Transformation, …) are populated from the existing `TOOLS` registry. No registry duplication; this page is purely picker + routing.

`<RequestAccessModal>` is a small new component: title, brief copy ("Salesforce source coming to Pallisade"), single-line email input pre-filled from the signed-in user, "Notify me" button that posts to `POST /api/v1/waitlist/source-connector` (new lightweight endpoint, persists `{user_id, connector_id, requested_at}` to a single `SourceConnectorWaitlist` Prisma model). No further UX commitment — we do not currently surface the waitlist anywhere customer-facing.

## Wizard restructure

The existing five-step Custom Source wizard becomes:

| Step | What happens | Change vs. today |
|---|---|---|
| 1. Identity | name + platform_label | unchanged |
| 2. Connection | base_url + auth.kind + credentials. **Next** button gated on `POST /test-connection` returning 2xx | gated (today the check only fires on step 5) |
| 3. **Discovery** (NEW) | Pallisade calls `POST /api/v1/integrations/source/discover` after step 2 lands. Renders three grouped sections (one per path) showing `DatasetCandidate` rows with inferred timestamp / json_root / columns, all editable per row. User accepts/rejects per row. *"+ Add endpoint manually"* button at the bottom (always available). | replaces today's manual Datasets entry |
| 4. Schedule | hourly / 6h / daily / weekly preset. The `lands_in` field that step 4 collects today is moved into step 3 (set automatically by Paths 2 & 3, manually editable per row). | simplified |
| 5. Review & Verify | Calls `POST /api/v1/integrations/source/verify` (SSE) on entry. Per-dataset ✓/✗ streams in live. Save button is disabled until SSE completes with all-pass. On any ✗, structured error per dataset; user clicks back to step 3 to fix. | new gate; today step 5 only runs `test_connection` |

## Discovery engine

New module: `scanner/discovery/source_discovery.py`.

```python
class SourceDiscoveryOrchestrator:
    async def discover(
        self,
        base_url: str,
        auth: AuthConfig,
        ingestion_hints: list[str] | None = None,    # connected ingestion driver IDs to scan
        warehouse_hints: list[str] | None = None,    # warehouse FQNs user picked as landing tables
    ) -> DiscoveryResult: ...
```

Runs three discoverers in parallel via `asyncio.gather`. Failure of one path is isolated — the path returns an empty result with a structured error code; the others continue.

```python
@dataclass(frozen=True)
class DatasetCandidate:
    source: Literal['ingestion', 'warehouse', 'probe']
    endpoint: str | None             # source endpoint path; None if discovered from warehouse only
    json_root: str | None
    timestamp_column: str | None
    expected_schema: list[ColumnMetadata]
    lands_in: str | None             # warehouse FQN; set by paths 2 & 3, null for path 1
    confidence: float                # 1.0 from ingestion config, 0.9 from warehouse, 0.7 from probe inference

@dataclass(frozen=True)
class DiscoveryError:
    code: Literal[
        'auth_failed', 'host_unreachable', 'response_too_large',
        'malformed_json', 'no_connectors_connected', 'no_warehouse_hint',
        'unknown'
    ]
    message: str                     # human-readable, surfaced in wizard

@dataclass(frozen=True)
class DiscoveryResult:
    candidates_by_path: dict[Literal['ingestion', 'warehouse', 'probe'], list[DatasetCandidate]]
    errors_by_path: dict[Literal['ingestion', 'warehouse', 'probe'], DiscoveryError | None]
```

The wizard merges candidates by `(endpoint, lands_in)` so the same dataset surfaced by multiple paths shows once with all confirming sources listed in the row's tooltip.

### Path 1 — `SourceProbeDiscoverer`

Wraps the existing `HttpProbeAdapter`. Hits `base_url`, parses JSON, finds top-level array roots (recursively up to depth 3 for V1), returns one `DatasetCandidate` per array with inferred columns / timestamp / `json_root`. Inference reuses `DatabaseAdapter.detect_timestamp_column` heuristics. Always runs. Confidence 0.7.

### Path 2 — `IngestionDiscoverer`

`scanner/discovery/ingestion/{fivetran,airbyte,stitch}.py` — one file per driver. Each implements:

```python
def find_matching_connectors(self, base_url: str, host: str) -> list[ConnectorMatch]: ...
def list_source_tables(self, connector: ConnectorMatch) -> list[DatasetCandidate]: ...
```

A `ConnectorMatch` exists when the ingestion connector's source config (Fivetran's `connector.config.host` / Airbyte's `source.connectionConfiguration.host` / Stitch's analogous field) matches the source's URL host. Per-driver because each ingestion tool stores connector config in a structurally different shape; one uniform interface, three distinct internals. Each match yields one `DatasetCandidate` per source-side table, with `lands_in` set to the warehouse landing table that ingestion config declares, and `expected_schema` populated from the ingestion config's column metadata. Confidence 1.0 (the ingestion tool is authoritative about what it pulls).

### Path 3 — `WarehouseDiscoverer`

Takes user-picked warehouse FQNs (UI presents a typeahead populated from already-discovered tables in the current pipeline profile — per `usePipeline()` context, scoped to `selectedPipelineId`). For each picked table, reads its schema via the existing warehouse adapter (`BigQueryAdapter` / `SnowflakeAdapter` / `PostgresAdapter` / `RedshiftAdapter` — covers all four warehouses we support). Returns one `DatasetCandidate` per picked FQN with `lands_in` set to that FQN, `expected_schema` populated from `INFORMATION_SCHEMA`, `endpoint=None` (the user still has to provide a source endpoint URL to pair with the candidate before it's actionable). Confidence 0.9.

## API endpoints

### `POST /api/v1/integrations/source/discover`

```json
// request
{
  "base_url": "https://portal.example.com/api/v1",
  "auth": { "kind": "api_key", "header_name": "X-API-Key", "secret_ref": "..." },
  "ingestion_hints": ["fivetran"],          // optional; if absent, scan all connected ingestion drivers
  "warehouse_hints": ["snowflake.raw.water_meters"]   // optional; warehouse FQNs user picked
}

// response (200)
{
  "candidates_by_path": { "ingestion": [...], "warehouse": [...], "probe": [...] },
  "errors_by_path":     { "ingestion": null,  "warehouse": null,  "probe": null }
}
```

Cached for **60s** keyed on `(base_url, auth.secret_ref, sorted(ingestion_hints), sorted(warehouse_hints))` so back-and-forth wizard navigation is responsive without re-probing the source unnecessarily. (`auth.secret_ref` is already a stable identifier for a stored secret, so it's safe to use directly in the cache key — no plaintext credentials touch the cache layer.) Cache lives in the existing FastAPI in-process cache.

### `POST /api/v1/integrations/source/verify`

```json
// request — full proposed integration config (the wizard's accumulated state)
{
  "name": "MyCiti — water sensors",
  "platform_label": "MyCiti",
  "base_url": "...",
  "auth": {...},
  "schedule": "daily",
  "datasets": [ {...}, {...} ]
}
```

Streams **Server-Sent Events**. One event per dataset:

```
event: dataset_result
data: {"dataset_id":"water_meters","status":"ok","row_count":1247,"latest_timestamp":"...","schema_match":true}

event: dataset_result
data: {"dataset_id":"sensor_alarms","status":"error","code":"json_root_returned_null","message":"json_root `data.alarms` resolved to null"}

event: complete
data: {"all_pass":false,"failed_count":1}
```

Backend implementation: instantiate `CustomSourceDriver` from the proposed config (without persisting), iterate datasets, call `HttpProbeAdapter.probe()` for each, emit per-dataset event as each completes. No DB writes anywhere in this endpoint.

### Persist-only-on-pass inversion

Today's flow: `POST /api/integrations` creates the row → `test_connection` runs after the fact → integration may sit broken in the DB if connection fails at scheduled probe time.

New flow: wizard step 5 calls `verify` first. On all-pass, wizard then calls existing `POST /api/integrations` to persist. On any-fail, no DB row is created — wizard surfaces errors and the user fixes. The integration test in the test plan asserts no orphan `Integration` rows are produced by failed verifies.

## Lineage & monitor placement

**Lineage:** Source `LineageNode`s already get `node_type = SOURCE` from the prior spec. The frontend lineage layout reads `LAYER_X` to position nodes; adding `SOURCE` at the smallest X in the same map the pipeline page uses propagates automatically. One-line change in the layout function — no graph algorithm changes.

**`lands_in` edges:** Discovery Paths 2 and 3 set `DatasetCandidate.lands_in` automatically. Path 1 leaves it null unless the user fills it in manually. `_extract_lineage_impl` in `CustomSourceDriver` already creates `LineageEdge` from the dataset → warehouse FQN when `lands_in` is set (per the prior spec). No driver changes — just ensure the new `DatasetCandidate.lands_in` is preserved through wizard state into the persisted dataset config.

**Monitors:** No change. The four monitors continue to run against `CustomSourceProbeRun` history per the worktree's existing wiring.

## Migration of existing worktree work

The worktree branch `feat/custom-source-integration` has 15 commits implementing the prior spec. Most stays.

**Keep (correct, unchanged):**
- `scanner/drivers/source/custom_source_driver.py`
- `scanner/adapters/http_probe.py` (the probe primitive)
- `CustomSourceProbeRun` Prisma model + persistence
- `scanner/scheduler/probe_runner.py`
- `scanner/monitors/custom_source_results.py` and the four monitor wirings
- `MonitorExecutor` dispatch for CUSTOM_SOURCE
- Backend `IntegrationLayer.SOURCE` enum + Prisma `IntegrationType.CUSTOM_SOURCE` + secret-store wiring
- `POST /api/v1/integrations/test-connection` CUSTOM_SOURCE branch + manual probe-now endpoint

**Rework:**
- Wizard step 3 (manual Datasets entry) → Discovery step. The existing "Test fetch" preview logic is preserved as the manual-fallback path inside the new step.
- Wizard step 5 — adds SSE-streamed `verify` call; Save disabled until all-pass. The `lands_in` field collected in step 4 today moves into step 3.
- Pipeline page `app/(dashboard)/dashboard/pipeline/page.tsx:184–195` — delete the misclassification block; rely on permanent `TOOLS.SOURCE` registration.

**Replace:**
- The single Custom Source tile on the integrations connect page (whichever commit added it) — replaced by the new category-grouped `connect/page.tsx`.

**Add:**
- `scanner/discovery/source_discovery.py` + `scanner/discovery/{ingestion,warehouse,probe}/` per-discoverer modules
- `POST /api/v1/integrations/source/discover` and `POST /api/v1/integrations/source/verify` endpoints
- `app/(dashboard)/dashboard/integrations/connect/page.tsx` (new picker index)
- `<RequestAccessModal>` component + `POST /api/v1/waitlist/source-connector` endpoint + `SourceConnectorWaitlist` Prisma model
- Frontend `PipelineLayer.SOURCE` + label + color + `TOOLS.SOURCE` + `ToolDefinition.status` field

**Feature flag:** `CUSTOM_SOURCE_INTEGRATION` → renamed to `SOURCES_CATEGORY`. The flag now gates the entire Sources category — the layer doesn't appear in the pipeline page or connect page until enabled. Rename is so the flag's name doesn't read as "only Custom Source is gated" once Salesforce/Shopify/HubSpot stubs are visible. Default off; flip on after pilot.

## What is stored vs. not stored

Inherits the prior spec's table verbatim — Pallisade still persists only derived metrics (counts, schemas, null-rates, timestamps, fingerprints), never row contents. The Discovery step's `expected_schema` is column metadata only, never values.

One addition: `SourceConnectorWaitlist` rows store `{user_id, connector_id, requested_at}` — no third-party data, just internal interest signal.

## Failure handling

- **Connection test fails** (step 2 → 3) — Next button stays disabled; structured error rendered inline. Same shape as today's step-5 error.
- **Discovery path errors** (step 3 render) — each path's section shows its own error state independently (e.g., "Couldn't reach Fivetran for connector list"). User can still proceed via the other paths or manual entry. Discovery is best-effort, not gating.
- **Verify failure** (step 5) — per-dataset ✗ rendered live. Save disabled. User clicks back to step 3.
- **Coming-soon tile clicks** — request-access modal opens. Fails closed (no wizard route exists).
- **Waitlist post failure** — modal shows "couldn't record interest, please try again." No silent failure.

## Test plan

**Backend unit tests:**
- `SourceDiscoveryOrchestrator` — parallel execution, result merge by `(endpoint, lands_in)`, per-path failure isolation.
- `IngestionDiscoverer` per-driver: `test_fivetran_discoverer.py`, `test_airbyte_discoverer.py`, `test_stitch_discoverer.py`. Each covers: matching host, non-matching host, no connectors connected, malformed config.
- `WarehouseDiscoverer` — mocked warehouse adapter returning INFORMATION_SCHEMA-shaped rows; assert `DatasetCandidate.expected_schema` / `timestamp_column` / `lands_in` correct.
- `SourceProbeDiscoverer` — thin wrapper smoke test (underlying `HttpProbeAdapter` already covered by prior spec's tests).

**Backend endpoint tests:**
- `/discover` — happy path (all three paths return), partial path failure, auth failure on source, bad warehouse hint.
- `/verify` — SSE stream emits one `dataset_result` event per dataset; all-pass / mixed / all-fail; **DB-scan assertion: no `Integration` row persisted on any verify failure path**.

**Frontend tests:**
- Wizard flow with mocked `/discover` and `/verify` — Save stays disabled until verify SSE completes all-pass.
- Sources category picker — Custom Source navigates, coming-soon tiles open `<RequestAccessModal>` and do not navigate to `/connect/<id>`.
- Pipeline page — SOURCE renders leftmost; Custom Source tile lives under SOURCE not INGESTION.

**Integration test (FastAPI test client + Next.js):**
- One end-to-end: drives wizard against a mocked HTTP source → connection ok → discovery returns probe-path candidates → verify dry-probes pass → integration persists → first scheduled probe runs → metric appears in monitor history. Single test; smoke-validates "the integration makes sense and is proper."

**Out of test scope:**
- No live Salesforce/Shopify/HubSpot API tests (connectors don't exist).
- Live-network smoke for Custom Source remains optional behind env flag (per prior spec).

## Sequencing for the implementation plan

Each step is shippable independently, all gated behind the renamed `SOURCES_CATEGORY` flag.

1. **Feature flag rename + frontend taxonomy.** `CUSTOM_SOURCE_INTEGRATION` → `SOURCES_CATEGORY`. Add `PipelineLayer.SOURCE` + label + color + `ToolDefinition.status` field + `TOOLS.SOURCE` (4 entries). Pipeline page: prepend `SOURCE` to layer/group ordering, add `LAYER_X.SOURCE`, **delete** lines 184–195 misclassification block. After this step: pipeline page shows Sources leftmost; Custom Source tile opens existing wizard untouched; coming-soon tiles render disabled.
2. **Integrations connect page (`connect/page.tsx`).** Category-grouped picker. Sources category first. Custom Source → wizard route. Coming-soon → `<RequestAccessModal>`. Add `<RequestAccessModal>` component + `POST /api/v1/waitlist/source-connector` endpoint + `SourceConnectorWaitlist` Prisma model + migration. After this step: a user can browse all integration categories from one page; standalone Custom Source tile is gone.
3. **Source-probe discoverer + `/discover` endpoint (Path 1 only).** New `scanner/discovery/` module. `SourceDiscoveryOrchestrator` wired to `SourceProbeDiscoverer` only. `POST /api/v1/integrations/source/discover` returns probe-path candidates. Wizard step 3 renamed to "Discovery"; calls `/discover` after step 2; renders *"From source probe"* section + manual fallback. After this step: wizard auto-discovers from source URL.
4. **Warehouse-anchored discoverer (Path 3).** Add `WarehouseDiscoverer` using existing warehouse adapters. Add `warehouse_hints[]` to `/discover`. Wizard adds warehouse-table typeahead populated from `usePipeline()` context. *"From your warehouse"* section in step 3.
5. **Ingestion-anchored discoverer (Path 2).** Add `IngestionDiscoverer` orchestrator + per-driver impls (Fivetran, Airbyte, Stitch). Discovery scans connected ingestion connectors for matching source URL/host. *"From {driver}"* section in step 3 when matches exist.
6. **`/verify` endpoint with SSE + Save-gate.** New `POST /api/v1/integrations/source/verify` streaming per-dataset probe results. Wizard step 5 calls it; Save disabled until SSE completes all-pass.
7. **Persist-only-on-pass inversion.** Wizard now calls `verify` first; on all-pass, calls existing `POST /api/integrations`. On fail, no DB row. Includes the integration test asserting no orphan rows.
8. **Pilot rollout.** Flag default off → enable for one pilot tenant → monitor → default on after two weeks of stable use.

## Open question for the user

None — every scope decision is closed and named. If something below feels wrong, push back and I'll revise before we move to the implementation plan.
