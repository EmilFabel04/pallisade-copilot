# Custom Source Integration — Design

**Date:** 2026-04-30
**Status:** Draft, awaiting user review
**Owner:** Emil

## Goal

Add a new Pallisade integration type — **Custom Source** — that lets a customer admin register an arbitrary web-hosted application (e.g. MyCiti for municipal water sensors) as a first-class pipeline source via a no-code wizard. Once registered, Pallisade probes the source on a schedule, computes the standard monitoring metrics (freshness, volume, null rate, schema drift) on the result, and surfaces the source in lineage and monitors **identically to a Snowflake table** — same UI, same alert paths, same monitor cards.

## Why now

South African municipalities use proprietary IoT / SCADA portals such as MyCiti to capture water-sensor data. Their data flow is `MyCiti → [their ETL] → warehouse → analytics / ML`. Today Pallisade can monitor everything to the right of `MyCiti`, but cannot see the source itself — so when warehouse data goes stale, the customer can't tell whether the upstream portal is broken or their own ETL is broken. This integration closes that gap. The same machinery generalises to any "custom web-hosted source with an API" — every vertical-SaaS / IoT / utilities portal looks roughly the same shape.

## Non-goals

This is **not** an ingestion platform. Pallisade does not move, load, transform, or persist customer data — only derived monitoring metrics. The customer continues to run their own ETL into their warehouse; Pallisade only observes the source. Out of V1 scope (named, so we know what we're punting): file-drop transports (ADLS / SFTP / inbox), OAuth / SAML, GraphQL endpoints, pagination beyond a single cursor parameter, webhook *receive*, AI-assisted discovery, multi-page or deeply nested JSON parsing, and any persistence of customer rows.

## High-level architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Wizard (Next.js)                                               │
│   step 1 name → step 2 URL+auth → step 3 datasets               │
│   → step 4 schedule → step 5 review                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │  POST /api/integrations
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  CustomSourceDriver  (scanner/drivers/source/custom_source_     │
│   driver.py)                                                    │
│   id() = "custom_source"   layer = SOURCE                       │
│   integration_type = "CUSTOM_SOURCE"   graph_domain = DATA_PLANE│
│   validate_config / test_connection / extract_metadata          │
│   _extract_lineage_impl  (uses "lands_in" hint)                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ composes over
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  HttpProbeAdapter  (scanner/adapters/http_probe.py — NEW)       │
│   probe(dataset_config) → MetricBundle                          │
│   — NEVER returns rows. Returns counts, schemas, null-rates,    │
│   timestamps, fingerprints only.                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │ persisted via existing path
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Existing monitor results store                                 │
│   freshness / volume / null / schema-drift monitors run         │
│   on the metric history exactly like for warehouse tables       │
└─────────────────────────────────────────────────────────────────┘
```

## New components

### 1. New `IntegrationLayer.SOURCE` value

Add a new value `SOURCE = "SOURCE"` to the `IntegrationLayer` enum in `scanner/drivers/base.py:38`. Position it first in the enum (it's the leftmost layer in any data flow). No existing layer fits an "operational source" — `WAREHOUSE` implies a queryable SQL store, `INGESTION` implies a connector tool that *moves* data — so `SOURCE` is genuinely new taxonomy, not a renaming.

This unblocks future first-class source integrations (Salesforce, HubSpot, custom CRMs, other vertical-SaaS / IoT portals) without further taxonomy work.

### 2. `IntegrationType.CUSTOM_SOURCE` (Prisma enum)

Add `CUSTOM_SOURCE` under a new `SOURCE (Layer: SOURCE)` group in `prisma/schema.prisma:1754`. No schema migration needed beyond the enum addition — Custom Source uses the existing `Integration.config` JSON column for everything, with the structure defined below.

### 3. `CustomSourceDriver` (`scanner/drivers/source/custom_source_driver.py`)

Implements `IntegrationDriver` from `scanner/drivers/base.py`. Replaces nothing; composes over the new `HttpProbeAdapter`. Lives in a new `scanner/drivers/source/` package (created alongside the existing `warehouse/`, `ingestion/`, etc.).

- `id() = "custom_source"`
- `integration_type() = "CUSTOM_SOURCE"`
- `layer() = IntegrationLayer.SOURCE`
- `graph_domain() = GraphDomain.DATA_PLANE`
- `capabilities()`: `can_extract_metadata=True`, `can_extract_lineage=True`, `can_health_check=True`, `supported_monitors=["freshness", "volume", "null_check", "schema_change"]`
- `validate_config()`: required fields are `name`, `base_url`, `auth.kind`, `datasets[].endpoint`, `datasets[].timestamp_column`. URL must be `https://` (V1 only allows TLS).
- `test_connection()`: issues a single `HEAD` (or `GET` with `?limit=1`) against `base_url` + the first dataset's endpoint, using the configured auth. Returns `ConnectionResult.ok=True` if HTTP 2xx within 10s.
- `extract_metadata()`: returns one `AssetSummary` per configured dataset.
- `_extract_lineage_impl()`: emits one `LineageNode` per dataset. If `dataset.lands_in` is set, emits a `LineageEdge` from the dataset → the named warehouse FQN (the warehouse-side node already exists from the existing lineage extraction).
- `recommended_monitors()`: `["freshness", "volume", "null_check", "schema_change"]`.

### 4. `HttpProbeAdapter` (`scanner/adapters/http_probe.py`)

A new lightweight adapter family — *deliberately not* a `DatabaseAdapter` subclass, because the SQL surface (quote_identifier, get_random_sample_sql, etc.) doesn't apply. Sits alongside `DatabaseAdapter` in `scanner/adapters/`.

Single public method:

```python
def probe(self, dataset_config: Dict[str, Any]) -> MetricBundle: ...
```

`MetricBundle` is a frozen dataclass containing **only derived metrics** — never any rows or cell values:

| Field | Type | Purpose |
|---|---|---|
| `probed_at` | `datetime` | When the probe ran |
| `row_count` | `int` | Volume monitor |
| `latest_timestamp` | `datetime \| None` | Freshness monitor |
| `column_schema` | `list[ColumnMetadata]` | Schema drift monitor |
| `null_counts` | `dict[str, int]` | Null-rate monitor |
| `distinct_counts` | `dict[str, int]` | Cardinality drift |
| `value_fingerprints` | `dict[str, bytes]` | HyperLogLog sketch per column for distribution drift, **no actual values** |
| `min_max_numeric` | `dict[str, tuple[float, float]]` | Range monitor (optional) |

Implementation:

1. Build `requests.Session` with auth applied per `config.auth.kind`:
   - `api_key`: header `X-API-Key: <secret>` (header name configurable, defaults to `X-API-Key`)
   - `bearer`: `Authorization: Bearer <secret>`
   - `basic`: standard HTTP basic
2. Issue `GET base_url + dataset.endpoint`, with optional cursor-style query param (e.g. `?since=<last_probe_at>`).
3. Hard caps for V1: max response size **10 MiB**, max rows processed **50,000**, request timeout **30s**. Anything larger → probe fails with `ProbeError("response too large")`.
4. Parse JSON. If `dataset.json_root` is set, navigate to that key (e.g. `data.items`). Result must be a JSON array of objects; reject anything else.
5. Stream-iterate rows in memory (never write to disk). For each row, update accumulators: count, per-column null tally, per-column HLL sketch, max-of-timestamp-column.
6. Build and return `MetricBundle`. **Discard the parsed rows.** No caching, no persistence, no return-of-rows.

Failure modes (HTTP 4xx/5xx, auth failure, timeout, malformed JSON, schema mismatch) raise `ProbeError` with a structured `code` field consumed by the alert layer.

### 5. Probe scheduler hook (`scanner/scheduler/`)

Reuses the existing scheduler. Adds a new task type `custom_source_probe` whose payload is `{integration_id, dataset_id}`. The scheduler service picks up due tasks and dispatches them to a worker that:

1. Loads integration config from the DB
2. Resolves secrets via the existing secret store
3. Instantiates `CustomSourceDriver`, calls its probe method per-dataset
4. Persists the resulting `MetricBundle` to the existing monitor-results store (same shape as warehouse SLA discovery results)
5. Emits `extraction.completed` or `extraction.failed` events on the existing event bus

Schedule is configurable per integration with fixed presets only for V1: **{hourly, every 6 hours, daily, weekly}**. Cron expressions deferred.

### 6. Wizard UI (`app/(dashboard)/integrations/connect/custom-source/`)

Five-step Next.js wizard mirroring the existing Snowflake / BigQuery wizards:

1. **Identity** — `name` (display label, e.g. "MyCiti — water sensors") + `platform_label` (free-text, used as the lineage node platform name).
2. **Connection** — `base_url`, `auth.kind` (radio: API key / bearer / basic), `auth` credential field(s). Credentials are POSTed straight to the secret store, never stored in the integration config JSON.
3. **Datasets** — admin adds one or more datasets. Per dataset: `endpoint` path, optional `cursor_param`, optional `json_root`. "Test fetch" button performs a one-off probe with `?limit=10` and shows: parsed row count, inferred column list & types, a "Pick timestamp column" dropdown auto-suggested via the same heuristic as `DatabaseAdapter.detect_timestamp_column()`. The preview shows the schema only — never the actual cell values, to keep the no-data-storage promise consistent end-to-end.
4. **Schedule & lands-in** — schedule preset, plus optional `lands_in` field per dataset (warehouse FQN where the customer's own pipeline writes this data, e.g. `snowflake.raw.water_meters`). Used for auto-edge creation in lineage.
5. **Review** — config summary; "Save & test connection" button calls `validate_config` + `test_connection` and shows results inline.

### 7. Configuration JSON shape

Stored in the existing `Integration.config` JSON column.

```json
{
  "name": "MyCiti — water sensors",
  "platform_label": "MyCiti",
  "base_url": "https://portal.example.com/api/v1",
  "auth": {
    "kind": "api_key",
    "header_name": "X-API-Key",
    "secret_ref": "<secret-store-id>"
  },
  "schedule": "daily",
  "datasets": [
    {
      "id": "water_meters",
      "endpoint": "/sensors/readings",
      "cursor_param": "since",
      "json_root": "data",
      "timestamp_column": "reading_at",
      "unique_key_columns": ["sensor_id", "reading_at"],
      "lands_in": "snowflake.raw.water_meters"
    }
  ]
}
```

## What is stored vs. not stored

| Stored in Pallisade | Never stored |
|---|---|
| Per-probe row count | Any row contents |
| Per-probe latest-timestamp value (single number) | Cell values, sample data |
| Per-probe column list & types | Anything joinable back to a customer record |
| Per-probe null counts per column | The null *values* themselves |
| Per-probe distinct counts | The distinct values |
| Per-probe HLL sketches per column | The values that went into the sketch |
| Per-probe min/max numeric | (already aggregates, not values) |
| Connection credentials (in secret store) | — |

**HyperLogLog gives us distribution-drift detection without storing values** — we compare today's sketch to yesterday's; divergence is the drift signal. Same trick the warehouse SLA discovery already uses.

## Lineage integration

A Custom Source dataset becomes a `LineageNode` with `node_type = SOURCE`, `platform = config.platform_label`, `kind = AssetKind.DATASET`. It is the leftmost node in the customer's pipeline graph for that dataset.

For V1, lineage edges from the source to downstream warehouse tables are auto-discovered **only** via the per-dataset `lands_in` config field. When `lands_in = "snowflake.raw.water_meters"` is set, `_extract_lineage_impl` emits one `LineageEdge` from the dataset → the existing warehouse node, with `Evidence.kind = "user_config"` and `confidence = 0.9` (high but not 1.0 — the user told us, but they could be wrong). If the warehouse node does not exist at edge-creation time, the edge is held pending and resolved when the warehouse-side extraction next runs (existing pending-edge mechanism in `scanner/lineage/engine/store.py`).

Auto-discovery via SQL parsing (matching warehouse INSERT statements that smell like the source) is **deferred to V2** — it requires a heuristic that is hard to get right and is not needed if the admin can fill in `lands_in`.

## Monitor integration

No new monitor types. The four standard monitors run on the metric history exactly as they do for warehouse tables:

| Monitor | What it looks at |
|---|---|
| Freshness | Time delta from `latest_timestamp` to `probed_at` |
| Volume | `row_count` over the metric history |
| Null check | `null_counts[col] / row_count` over history |
| Schema drift | `column_schema` diffs between successive probes |

Distribution-drift on top of HLL sketches is a stretch goal for V1 — the data is captured but no monitor consumes it yet. If time permits, add a "cardinality drift" monitor that flags when the HLL sketch divergence exceeds a threshold.

The monitor UI does not need to know the source is a custom source. The existing per-asset monitor cards (`components/lineage/SLAEditorPanel.tsx`, the asset health pages) already render against any node that has metric history — no special-casing required.

## Failure handling & "remediation"

- **Probe failure** → integration goes `unhealthy`, fires the existing `health.disconnected` event, surfaces in the integrations health page exactly like a Snowflake auth failure.
- **Schema mismatch** (column went away mid-flight) → schema-drift monitor fires; the probe still completes with the new schema and metrics for the still-present columns.
- **Source down for >24h** → escalation policy (existing alert engine) handles it.
- **"Remediation"** is alerting + linking the human investigator to the source's status in the integrations panel. **Pallisade does not attempt to fix or replay anything** — consistent with the project-wide rule that Pallisade is monitor-only.

## Test plan

- **Unit:** `HttpProbeAdapter.probe()` against an in-process `responses` mock — covers each auth shape, json_root navigation, cursor param, size/row caps, malformed-JSON and HTTP-error paths. `MetricBundle` invariants (no row data leakage).
- **Driver:** `CustomSourceDriver.validate_config / test_connection / _extract_lineage_impl` against the mocked adapter.
- **Integration:** end-to-end via FastAPI test client — POST integration config, trigger probe, assert metrics persisted, assert lineage edge created when `lands_in` set, assert no row data persisted (DB scan for any value matching a known fixture row).
- **Live smoke:** one optional CI job hitting a public open-data REST endpoint (e.g. a city open-data CSV-as-JSON), gated behind env flag; verifies real-network behaviour.

## Rollout

1. Implement behind feature flag `CUSTOM_SOURCE_INTEGRATION` (default off).
2. Internal dogfood on a public open-data API for one week.
3. Enable for one pilot municipality; iterate on wizard friction & error messages based on their actual MyCiti config.
4. Default-on after 2 weeks of stable pilot.

## Sequencing for the implementation plan

The writing-plans phase should structure work in this order, each step shippable independently:

1. **IntegrationLayer.SOURCE enum value + Prisma `CUSTOM_SOURCE` enum + secret-store wiring** — the smallest possible change that lets the integration exist in the taxonomy and DB.
2. **`HttpProbeAdapter` + unit tests** — the core data-handling logic in isolation, no driver, no UI.
3. **`CustomSourceDriver` + driver tests** — composes over the adapter, registered in the driver loader.
4. **Scheduler probe-task type + worker** — wires the driver into the existing scheduler.
5. **Wizard UI** — the only Next.js / React change in the whole spec.
6. **Lineage edge from `lands_in`** — small addition once the rest works.
7. **Feature-flag gating + pilot rollout.**

## Open question for the user

None — every scope decision is closed and named. If something below feels wrong, push back and I'll revise before we move to the implementation plan.
