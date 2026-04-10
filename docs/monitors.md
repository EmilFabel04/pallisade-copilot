# Monitor System Architecture

Internal architecture reference for Pallisade's monitor and schedule system. Covers backend execution, API routes, database schema, UI components, UX flows, health scoring, and all monitor types.

---

## 1. Overview & Data Flow

### End-to-End Lifecycle

```
User creates monitor (UI)
  → POST /api/schedule/tasks (Next.js)
  → Prisma creates Monitor record
  → SchedulerService polls for due tasks (every 60s)
  → POST /api/v1/schedule/execute (FastAPI)
  → TaskExecutor.execute(task)
  → MonitorExecutor.run_monitor(monitor, db, schema, table)
    → monitor.build_query() → SQL
    → query_func(sql) → results
    → monitor.evaluate(results) → MonitorResult
  → Result persisted: MonitorRun record + baseline update
  → UI fetches /api/schedule/tasks/{id}/runs → RunHistoryTable
```

### Key Architecture Decisions

- **Dialect-agnostic SQL**: All monitors generate SQL via sqlglot, transpiled to target dialect (BigQuery, Snowflake, Postgres, Redshift)
- **Baseline injection**: Stored baselines allow monitors to work even when warehouse lacks sufficient history
- **Cadence-aware freshness**: Learns update frequency from historical gaps
- **Confidence scaling**: Low-confidence anomalies (< 50%) downgrade from FAIL to WARN
- **Effect-size filtering**: Prevents alerts on statistically significant but practically irrelevant changes

---

## 2. Monitor Types

### Warehouse SQL Monitors (`scanner/monitors/`)

#### Freshness (`freshness.py`)
Tracks data recency via timestamp columns.

| Config Key | Type | Default | Description |
|---|---|---|---|
| `timestamp_column` | string | auto | Column to check (auto-discovered if empty) |
| `freshness_mode` | string | auto | "ingestion", "business_event", or "auto" |
| `max_hours` | number | 24 | Maximum acceptable age |
| `warn_hours` | number | 75% of max | Warning threshold |
| `weekday_max_hours` | number | - | Day-specific SLA |
| `weekend_max_hours` | number | - | Day-specific SLA |
| `cadence_aware` | bool | false | Enable learned update frequency detection |
| `cadence_multiplier` | number | 1.5 | Gap multiplier for cadence mode |
| `cadence_gaps` | float[] | - | Historical gaps (auto-injected) |

**Auto-Discovery** (`discover_timestamp_column`):
- Queries INFORMATION_SCHEMA for timestamp/datetime columns
- Scores candidates by: name priority (0-50), non-null rate (0-30), recency (0-20)
- Prioritizes ingestion columns (`_loaded_at`, `_fivetran_synced`) over business-event columns (`created_at`)

**Cadence-Aware Mode** (`_evaluate_cadence`):
- Computes median gap and P95 gap from historical measurements
- Expected max = median x cadence_multiplier
- FAIL if current gap > P95 x multiplier, WARN if > median x multiplier

#### Volume (`volume.py`)
Detects row count anomalies via statistical analysis.

| Config Key | Type | Default | Description |
|---|---|---|---|
| `min_rows` / `max_rows` | number | - | Hard thresholds |
| `anomaly_threshold` | number | 3.0 | Z-score threshold |
| `volume_mode` | string | auto | "total", "period", or "auto" |
| `time_bucket_column` | string | - | Column for daily bucketing |
| `time_bucket_interval` | string | 1 day | "1 day" or "1 hour" |
| `partition_column` | string | - | For partition-scoped monitoring |
| `detrend` | bool | false | Remove linear trend before scoring |
| `seasonality` | string | - | "day_of_week" for weekend/weekday separation |
| `historical_mean` / `historical_stddev` | number | - | Pre-computed baseline stats |
| `min_abs_delta` / `min_rel_delta` | number | - | Effect-size thresholds |

**Three Evaluation Modes**:
1. **Simple** (`_evaluate_simple`): Total row count with min/max checks
2. **Time-Series** (`_evaluate_time_series`): Daily bucketed volume with StatEngine anomaly scoring
3. **Partitioned** (`_evaluate_partitioned`): Per-partition checks

**Auto-Detection** (executor.py):
- Detects full-refresh (80%+ of rows in 30 days) vs append-only
- Computes historical mean/stddev from 30-day history
- Sets fallback min/max thresholds if stddev is zero

#### Schema Change (`schema.py`)
Detects column additions, deletions, type changes, reordering.

| Config Key | Type | Default | Description |
|---|---|---|---|
| `baseline_columns` | object[] | auto | Expected column definitions (auto-established on first run) |
| `fail_on_column_added` | bool | false | Fail on new columns |
| `fail_on_column_removed` | bool | true | Fail on removed columns |
| `fail_on_type_change` | bool | true | Fail on type changes |
| `min_severity` | string | - | "critical"/"high"/"medium"/"low"/"info" (overrides flags) |
| `rename_similarity_threshold` | number | 0.6 | Threshold for detecting suspected renames |

**Severity Classification**:
- **CRITICAL**: PK/FK column removed or type changed
- **HIGH**: Non-nullable column removed, narrowing type change (bigint -> int)
- **MEDIUM**: Column added with NOT NULL, type widening (int -> bigint)
- **LOW**: Nullable column added, nullable-state change
- **INFO**: Ordering change only

**Type Normalization** (`_normalize_type`): Maps cross-dialect types to canonical form (INT64 -> integer, float64 -> double, strips length/precision)

#### Anomaly (`anomaly.py`)
Statistical anomaly detection on column-level metrics.

| Config Key | Type | Default | Description |
|---|---|---|---|
| `column` | string | "" | Target column ("" for table-level) |
| `metric` | string | row_count | "null_rate", "distinct_count", "distinct_rate", "min", "max", "avg", "sum", "stddev", "zero_rate", "row_count" |
| `anomaly_threshold` | number | 3.0 | Z-score threshold |
| `min_effect_size` | number | varies | Minimum absolute change to trigger |
| `detection_method` | string | auto | "auto", "zscore", "mad", "pct_change" |
| `seasonality` | string | - | "day_of_week" for day-based filtering |
| `lookback_days` | number | 30 | History window |
| `timestamp_column` | string | - | For time-bucketing |
| `historical_values` | float[] | - | Pre-computed baseline values |

**Adaptive Retry**: If initial lookback insufficient, retries with 30 -> 25 -> 20 -> 14 -> 7 days

#### Referential Integrity (`referential.py`)
Detects orphaned foreign key references.

| Config Key | Type | Default | Description |
|---|---|---|---|
| `parent_fqn` | string | required | Parent table FQN |
| `parent_column` | string | required | PK column in parent |
| `child_column` | string | required | FK column in child |
| `sample_pct` | number | 100 | Sampling percentage for large tables |
| `max_orphans` / `warn_orphans` | number | - | Orphan count thresholds |
| `max_orphan_pct` | number | - | Percentage-based threshold |
| `historical_orphan_rates` | float[] | - | Baseline for anomaly-based detection |

Supports TABLESAMPLE in BigQuery/Snowflake/Postgres.

#### Uniqueness (`uniqueness.py`)
Enforces uniqueness constraints on column combinations.

---

### Tool API Monitors (`scanner/monitors/tools.py`)

These query Fivetran, Airflow, and dbt APIs. **TOOL_MONITOR_TYPES**: `sync_lag`, `failed_syncs`, `connector_schema_drift`, `dag_last_run`, `dag_schedule_lag`, `task_failure_rate`, `dbt_test_failures`, `dbt_model_freshness`, `dbt_source_freshness`

#### Sync Lag
Monitors Fivetran connector freshness. Compares minutes since last sync to frequency-based thresholds.
- Config: `connector_id`, `max_lag_minutes`, `warn_multiplier`, `fail_multiplier`

#### Failed Syncs
Analyzes connector health for recent failures.
- Config: `connector_id`, `lookback_hours`

#### Connector Schema Drift
Detects schema changes in Fivetran connectors.

#### DAG Last Run / DAG Schedule Lag / Task Failure Rate
Airflow DAG monitoring via REST API. Requires live API connection (not GitHub DAG files).

#### dbt Test Failures / dbt Model Freshness / dbt Source Freshness
dbt Cloud monitoring via API. Requires dbt Cloud API key.

---

### BI API Monitors (`scanner/monitors/bi.py`)

**BI_MONITOR_TYPES**: `bi_freshness_proxy`, `bi_upstream_break_risk`, `bi_content_health`, `bi_refresh_failure`

#### BI Freshness Proxy
Checks BI asset `last_updated` time. Optionally verifies upstream table freshness via lineage engine.
- Config: `asset_id`, `asset_type`, `max_stale_hours`, `check_upstream`

#### BI Upstream Break Risk
Counts failing monitors on upstream warehouse tables. Uses lineage engine store to traverse upstream (depth=3).
- Config: `asset_id`, `lookback_hours`

#### BI Content Health
Verifies BI asset exists and scheduled deliveries aren't failing.

#### BI Refresh Failure
Checks for BI refresh/extract failures.

---

### Infrastructure SSH Monitors (`scanner/monitors/infrastructure.py`)

**INFRA_MONITOR_TYPES**: `certificate`, `server_health`, `log_analysis`

#### Certificate
Checks TLS/SSL certificate expiry and missing client certificates.
- Config: `cert_paths` (auto-discovered if empty), `warn_days`, `fail_days`

#### Server Health
Checks CPU, memory, disk usage against thresholds. Optionally against historical baselines via StatEngine.
- Config: `max_cpu`, `max_memory`, `max_disk`, `historical_cpu`, `historical_memory`

#### Log Analysis
Scans log files for error patterns via SSH.
- Config: `log_paths`, `error_patterns`

---

### Monitor Type Routing

**MONITOR_REGISTRY** (maps type string to class):
```
freshness → FreshnessMonitor
volume → VolumeMonitor
schema_change → SchemaMonitor
anomaly → AnomalyMonitor
referential → ReferentialIntegrityMonitor
uniqueness → UniquenessMonitor
```

**MONITOR_ROUTING** (UI-only types routed to backend implementations):
```
null_rate → anomaly (metric: "null_rate", column: "*")
distribution → anomaly (metric: "avg", column: "*")
```

`resolve_monitor_type(monitor_type, config)` applies MONITOR_ROUTING, merges default config with user config (user config wins).

---

## 3. Backend Architecture

### MonitorExecutor (`scanner/monitors/executor.py`)

Base class that abstracts monitor execution. Constructor takes `query_func` (callable) and `dialect` (string).

#### `run_monitor(monitor, database, schema, table)`
1. `monitor.build_query()` generates dialect-agnostic SQL
2. `query_func(sql)` executes against warehouse
3. `monitor.evaluate(results, target_fqn)` returns `MonitorResult`
4. Sets `executed_at`, `duration_ms`, `sql_executed`
5. `enrich_result()` adds structured explanation

#### `auto_configure(monitor_type, database, schema, table, existing_config)`
Non-destructive config merge (never overwrites user-provided values).

**Freshness auto-config** (`_auto_config_freshness`):
- Auto-discovers timestamp column
- Queries 30-day history to compute gaps between updates
- Sets `max_hours = P95_gap x 1.5`, clamped to [1h, 168h]
- Enables `cadence_aware` mode if >= 5 data points

**Volume auto-config**:
- Discovers timestamp column for daily bucketing
- Computes `historical_mean`/`historical_stddev` from 30-day history
- Auto-detects `volume_mode` (full-refresh vs append-only)

---

### TaskExecutor (`scanner/scheduler/executor.py`)

Main entry: `async execute(task)`. Routes based on `taskMode` and monitor type.

#### `_execute_structured(task)` — Core Execution Flow

1. **Parse FQN** (line ~318): `database.schema.table` or `schema.table` (2-part)
2. **Resolve monitor type**: Apply MONITOR_ROUTING
3. **Inject stored baseline** (line ~360):
   - Anomaly: builds synthetic `historical_values` from stored mean/stddev
   - Volume: injects `historical_mean`/`historical_stddev` directly
4. **Inject cadence gaps** (line ~385): For freshness monitors, queries BaselineStore
5. **Resolve integration config** (line ~420):
   - Try pre-fetched `integrationConfig` from task
   - Fall back to `_get_integration_config(integrationId, organizationId)`
   - Database remapping: if FQN database doesn't match integration project, remap to integration's project/database
6. **Create monitor + auto-configure + execute**
7. **Return normalized result**: `{status, value, threshold, message, details, sql_executed, duration_ms}`

#### `_get_integration_config(integration_id, organization_id)`
Fetches warehouse connection config from PipelineNode table.
- If `integration_id` provided: look up specific node
- Otherwise: auto-discover first connected warehouse node in org's pipeline stack
- Decrypts encrypted credentials
- Maps `username` -> `user` for Snowflake/Postgres/Redshift

---

### SchedulerService (`scanner/scheduler/service.py`)

In-process asyncio background loop.

#### Key Behavior
- Checks for due tasks every 60 seconds (configurable via `SCHEDULER_INTERVAL_SECONDS`)
- Queries `Monitor WHERE enabled=true AND nextRunAt <= now()` (up to 50 per cycle)
- Uses croniter to compute next run times

#### `_execute_task(task, conn)` — Result Persistence
1. Fetches stored `baselineMean`/`Stddev`/`Count` from Monitor record
2. Injects as `stored_baseline` into config
3. Calls `TaskExecutor.execute(task)` (async)
4. Inserts `MonitorRun` record with: status, value, threshold, message, details, sqlExecuted, duration
5. Updates `Monitor` with: `lastRunAt`, `lastStatus`, `nextRunAt`, baseline stats
6. Records baseline observations via `BaselineStore.record_batch()`

---

### Statistical Engine (`scanner/monitors/stats.py`)

#### `score_anomaly(current, baseline, threshold, min_effect_size, method)`

Returns `AnomalyScore` with: `z_score`, `mad_score`, `pct_change`, `is_anomaly`, `method_used`, `confidence_pct`, `direction`, `explanation`

**Method Selection** (`_resolve_method`):
- < 7 data points: use percentage change
- Baseline has outliers (max z-score > 4): use MAD
- Otherwise: use Z-score

**MAD (Median Absolute Deviation)** (`_mad_zscore`):
- Robust to outliers: `0.6745 x (current - median) / MAD`

**Confidence Scaling** (`baseline_confidence`):
```
< 3 points:  0% (unusable)
3 points:   30%
7 points:   50%
14 points:  65%
20 points:  80%
30 points:  90%
60+ points: 100%
```

**Adaptive Thresholds** (`adaptive_threshold`):
- High variability (CV > 0.5): widen threshold x 1.5
- Low variability (CV < 0.05): tighten threshold x 0.7

---

### BaselineStore (`scanner/monitors/baseline_store.py`)

Interface to `MonitorBaseline` time-series table.

| Method | Purpose |
|---|---|
| `record(monitor_id, metric_name, value, ...)` | Store single observation |
| `record_batch(monitor_id, metrics, target_fqn)` | Batch-store multiple metrics |
| `get_history(monitor_id, metric_name, days, ...)` | Historical values with optional day/hour filters |
| `get_cadence_gaps(monitor_id, metric_name, days)` | Gaps (hours) between consecutive measurements |
| `get_history_with_timestamps()` | (value, timestamp) pairs for trend analysis |
| `get_recent_statuses(monitor_id, limit)` | Last N run statuses |
| `get_latest(monitor_id, metric_name)` | Most recent value |
| `prune(monitor_id, keep_days)` | Delete entries older than keep_days |

---

## 4. API Layer

### Next.js API Routes (`app/api/schedule/`)

#### Tasks (Individual Monitors)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/schedule/tasks` | List standalone monitors (excludes group-owned). Params: `status`, `due`, `stackId` |
| POST | `/api/schedule/tasks` | Create monitor. Supports `taskMode: 'prompt' \| 'structured'` |
| GET | `/api/schedule/tasks/[taskId]` | Task detail with last 10 runs |
| PATCH | `/api/schedule/tasks/[taskId]` | Update task (name, schedule, config, enabled, alerts) |
| DELETE | `/api/schedule/tasks/[taskId]` | Delete task + cascade delete runs |
| GET | `/api/schedule/tasks/[taskId]/runs` | Paginated run history (default 25). Params: `limit`, `offset` |
| POST | `/api/schedule/tasks/[taskId]/run` | Trigger immediate execution via Python backend |

**Integration Resolution** (in `tasks/[taskId]/run`):
1. Try `task.integrationId` -> find connected PipelineNode
2. Try `config.nodeId` -> direct PipelineNode lookup
3. Fallback: auto-discover first warehouse node in org's pipeline stack
4. Special: infrastructure monitors use `config.serverNodeId`, tool monitors use `config.toolNodeId`

#### Watches (Group Monitors)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/schedule/watches` | List all watches (where `watchType IS NOT NULL`) |
| POST | `/api/schedule/watches` | Create watch with child monitors (transactional, 30s timeout) |
| GET | `/api/schedule/watches/[watchId]` | Watch detail with all monitors + last run each |
| PATCH | `/api/schedule/watches/[watchId]` | Update watch + propagate to child monitors. Supports `removeMonitorIds` |
| DELETE | `/api/schedule/watches/[watchId]` | Delete watch + all child monitors (cascade) |
| POST | `/api/schedule/watches/[watchId]/run` | Run all monitors + compute health report |

**Watch Creation** (POST):
- Validates `watchType` is one of: `pipeline_health`, `dashboard_shield`, `source_guard`, `model_quality`, `custom_watch`
- Creates MonitorGroup + child Monitor records in a transaction
- Deduplicates: reuses existing monitors (same org + targetFqn + monitorType)
- Stores `_watchDepth` and `_watchPriority` in monitor config

**Watch Run** (POST `/run`):
- Executes all enabled monitors sequentially
- Computes weighted health score from monitor signals
- Groups failures by category (stale_data, schema_break, ingestion_lag, etc.)
- Returns comprehensive health report

#### Bundles (Legacy Groups)

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/api/schedule/bundles` | List/create bundles (similar to watches, no health scoring) |
| GET/PATCH/DELETE | `/api/schedule/bundles/[groupId]` | Bundle CRUD |
| POST | `/api/schedule/bundles/[groupId]/run` | Run all monitors (simple worst-status aggregation) |

#### Other

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/schedule/monitor-catalog` | Available monitors for a pipeline stack. Filters by connected integrations. |
| POST | `/api/schedule/alert` | Dispatch alert notifications (Slack, Email, PagerDuty, Teams, Opsgenie) |

### FastAPI Routes (`scanner/api/routers/schedule.py`)

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/schedule/execute` | Execute a monitor. Called by Next.js `tasks/[taskId]/run`. Returns `{status, value, threshold, message, details, sql_executed}` |

---

## 5. Database Schema

### Monitor (`prisma/schema.prisma`)

```
id (CUID), name
monitorType (MonitorKind enum, nullable)
targetFqn, targetDatabase, targetSchema, targetTable
config (Json)
enabled, schedule, lastRunAt, lastStatus, nextRunAt
baselineMean, baselineStddev, baselineCount, baselineUpdatedAt
taskMode (prompt|structured), prompt, description
alertChannels[], alertConfig (Json), alertOnStatus[]
lastAlertStatus, lastAlertAt
timezone, createdBy, source (pallisade|elementary|monte_carlo)
externalId, createdAt, updatedAt
```

**Relations**: organization (FK, cascade), integration (optional FK), monitorGroup (optional FK, SetNull on delete), runs (MonitorRun[]), baselines (MonitorBaseline[])

**Unique constraint**: `(organizationId, targetFqn, monitorType)`

### MonitorRun

```
id (CUID)
status (PASS|WARN|FAIL|ERROR|SKIPPED|RUNNING)
value, threshold (floats)
message, details (Json), sqlExecuted
startedAt, completedAt, durationMs
```

**Relations**: monitor (FK, cascade delete)

### MonitorBaseline

```
id (CUID)
metricName (e.g., "row_count", "null_rate", "hours_since_update")
metricValue
measuredAt, dayOfWeek (0-6), hourOfDay (0-23)
targetFqn (denormalized), details (Json)
```

**Indexes**: `(monitorId, metricName, measuredAt)`, `(monitorId, metricName, dayOfWeek)`

### MonitorGroup

```
id (CUID), name, description
groupType (custom|upstream_stability|reporting_health|asset_stability)
anchorFqn, anchorNodeId
enabled, schedule, timezone
alertChannels[], alertOnStatus[], alertConfig (Json)
lastStatus, lastRunAt
```

**Watch-specific fields** (null for legacy bundles):
```
watchType (pipeline_health|dashboard_shield|source_guard|model_quality|custom_watch)
scopeConfig (Json: maxDepth, maxNodes, maxMonitors, domainFilters, includeNodeIds, excludeNodeIds)
coveragePct (0.0-1.0), healthScore (0-100), healthDetails (HealthReport Json)
lastHealthAt, anchorNodeType, anchorPlatform
```

### MonitorKind Enum

`FRESHNESS`, `VOLUME`, `SCHEMA_CHANGE`, `NULL_CHECK`, `UNIQUENESS_CHECK`, `RANGE_VALIDATION`, `ACCEPTED_VALUES`, `DATE_CONSISTENCY`, `DATA_TYPE_VALIDATION`, `OUTLIER_DETECTION`, `REFERENTIAL`, `CUSTOM_SQL`, `CERTIFICATE`, `SERVER_HEALTH`, `LOG_ANALYSIS`, `SYNC_LAG`, `FAILED_SYNCS`, `CONNECTOR_SCHEMA_DRIFT`, `DAG_LAST_RUN`, `DAG_SCHEDULE_LAG`, `TASK_FAILURE_RATE`, `DBT_TEST_FAILURES`, `DBT_MODEL_FRESHNESS`, `DBT_SOURCE_FRESHNESS`, `BI_FRESHNESS_PROXY`, `BI_UPSTREAM_BREAK_RISK`, `BI_CONTENT_HEALTH`, `BI_REFRESH_FAILURE`

---

## 6. TypeScript Types

### `types/schedule.ts`

**ScheduledTask**: `id`, `name`, `taskMode`, `prompt`, `monitorType`, `targetFqn`, `config`, `schedule`, `timezone`, `enabled`, `alertChannels`, `alertOnStatus`, `lastRunAt`, `lastStatus`, `nextRunAt`, `integrationId`, `integrationName`, `monitorGroupId`, `monitorGroupName`, `createdAt`, `updatedAt`

**TaskRun**: `id`, `status` (PASS|WARN|FAIL|ERROR|SKIPPED|RUNNING), `value`, `threshold`, `message`, `details` (with `llm_validation`, `z_score`, `baseline_mean`, etc.), `sqlExecuted`, `startedAt`, `completedAt`, `durationMs`

**Constants**: `MONITOR_TYPES` (derived from MONITOR_CATALOG), `SCHEDULE_PRESETS` (cron presets), `RUN_STATUS_COLORS` (Tailwind classes)

### `types/health-watch.ts`

**WatchType**: `pipeline_health` | `dashboard_shield` | `source_guard` | `model_quality` | `custom_watch`

**ScopeConfig**: `maxDepth`, `maxNodes`, `maxMonitors`, `domainFilters[]`, `includeNodeIds`, `excludeNodeIds`

**DEFAULT_SCOPE_CONFIGS**: Per-watch-type defaults (e.g., pipeline_health: maxDepth 3, maxNodes 15, maxMonitors 12)

**HealthStatus**: `healthy` | `degraded` | `at_risk` | `unhealthy`

**HealthReport**: `healthScore` (0-100), `healthStatus`, `summary`, `directStatus`, `upstreamStatus`, `coveragePct`, `failureGroups[]`, `computedAt`

**FailureCategory**: `stale_data` | `schema_break` | `ingestion_lag` | `orchestration_failure` | `quality_anomaly` | `transform_failure`

**FailureGroup**: `category`, `severity` (critical|warning), `summary`, `rootCauseHint`, `signalCount`

**WatchSummary**: Full watch detail with monitors, health report, coverage, counts.

### `types/monitor-catalog.ts`

**MonitorCategory**: `warehouse` | `ingestion` | `orchestration` | `transformation` | `infrastructure` | `reporting`

**ExecutorType**: `warehouse_sql` | `tool_api` | `ssh` | `bi_api`

**MonitorDefinition**: `key`, `label`, `description`, `category`, `required_integrations[]`, `target_selector_type`, `config_schema[]`, `executor_type`, `supports_baselines`, `auto_configurable`

**MONITOR_CATALOG**: 25+ monitor definitions with full config schemas and integration requirements.

**Utility Functions**: `getAvailableMonitors(connectedToolTypes)`, `groupMonitorsByCategory(monitors)`, `getMonitorDefinition(key)`

---

## 7. UI Components

### Schedule Page (`app/(dashboard)/dashboard/schedule/page.tsx`)

Main page with three view modes:

1. **List View** (default): Filter tabs (all/passing/failing/disabled) + Group Monitors section (WatchCards) + Individual Tasks section (TaskCards)
2. **Task Detail View**: Back button, task name + status, Edit/Run Now/Delete buttons, config summary, RunHistoryTable
3. **Watch Detail View**: Delegates to WatchDetailPanel

**State**: `tasks`, `watches`, `filter`, `selectedTask`, `selectedWatch`, `showCreateModal`, `integrations`

**Data fetching**: `cachedFetch` for lists, direct fetch for detail views. Invalidation via `invalidateCache("/api/schedule")`.

### TaskCard (`components/schedule/TaskCard.tsx`)

Compact list item for individual monitors. Shows: name, status badge, monitor type, schedule (human-readable cron), target FQN, last run timestamp, alert channels, integration name. Hover reveals Run Now button + enable/disable toggle.

### WatchCard (`components/schedule/WatchCard.tsx`)

List item for group monitors with health aggregation. Shows: shield icon, name, health status badge, watch type, schedule, monitor count, coverage percentage, health score bar (0-100), failure groups (up to 3), last run timestamp, anchor FQN. Run All + enable/disable toggle.

**Watch type colors**: pipeline_health (blue), dashboard_shield (purple), source_guard (emerald), model_quality (amber), custom_watch (white/50)

### WatchDetailPanel (`components/schedule/WatchDetailPanel.tsx`)

Full detail view of a watch. Sections:

1. **Header**: Back, name, health badge, enable toggle, Run All, Delete
2. **Health Summary Card**: Score (0-100), bar, direct/upstream status, coverage %
3. **Config Summary** (if no health report yet): Type, schedule, pass count, status
4. **Anchor Asset Info**: FQN + platform badge
5. **Failure Groups**: Cards with category, severity, summary, root cause hint
6. **Monitor List**: Expandable rows. On expand, fetches full run history via `/api/schedule/tasks/{monitorId}/runs` and displays with RunHistoryTable. "Remove from watch" button per monitor.

### RunHistoryTable (`components/schedule/RunHistoryTable.tsx`)

Tabular run history with expandable detail panels.

**Columns**: Expand toggle, Status (badge), Time, Value (2dp monospace), Duration, Message (truncated)

**Expansion Panel** (per run):
- **Message**: Full alert text
- **Details**: Grid of key-value pairs, ordered by priority (z_score, baseline_mean, etc.)
- **SQL Executed**: Monospace code block
- **AI Assessment**: If `llm_validation` in details — shows explanation, original/adjusted status, confidence %
- **Ask Scout**: Buttons for "Explain", "Double check", "Investigate" — navigates to `/dashboard/assistant` with run context in sessionStorage

### CreateTaskModal (`components/schedule/CreateTaskModal.tsx`)

Modal to create or edit individual monitors.

**Sections**:
1. **Mode**: AI Prompt vs. Structured Monitor
2. **Monitor type selection**: Grouped by category from monitor-catalog endpoint
3. **MonitorConfigForm**: Dynamic fields based on type (see below)
4. **Schedule**: Presets + custom cron
5. **Alerts**: AlertChannelPicker

**Edit mode**: Pre-fills from `editTask`, calls `onUpdate` instead of `onSubmit`.

### CreateWatchModal (`components/schedule/CreateWatchModal.tsx`)

4-step wizard to create a health watch.

**Step 1: Pick Asset**
- Search via lineage engine (`?action=search&q={query}`)
- Auto-detects watch type from node domain (dashboard -> dashboard_shield, source -> source_guard, dbt -> model_quality, default -> pipeline_health)

**Step 2: Review Scope & Monitors**
- Fetches recommendations via lineage engine (`?action=recommend-monitors&id={nodeId}&depth={maxDepth}`)
- Checkbox list: priority badge (P1/P2/P3), type, target, reason
- Coverage = monitors.length / upstream_count

**Step 3: Schedule**
- Preset buttons + custom cron input + timezone dropdown

**Step 4: Alerts & Confirm**
- AlertChannelPicker + summary card with editable name

**Prefill from lineage**: `WatchPrefillData` with `anchorFqn`, `anchorNodeId`, `anchorNodeType`, `anchorPlatform`. Pre-selected asset, inferred watch type, skips to step 2 if monitors provided.

### MonitorConfigForm (`components/schedule/MonitorConfigForm.tsx`)

Dynamic configuration UI per monitor type.

**Target selector** (varies by type): FQN text input, connector info, DAG info, dbt job info, server info

**Monitor-specific config fields**:
- Freshness: timestamp_column, max_hours
- Volume: min_rows, max_rows
- Uniqueness: column selector (all/specific)
- Anomaly: metric selector, column, z-score threshold, lookback days, timestamp column
- Custom SQL: SQL textarea
- Certificate: cert_paths, warn_days, fail_days
- Log Analysis: log file picker with "Discover" button, error patterns
- Tool monitors: catalog-driven fields from `config_schema[]`

**LLM Validation toggle**: Checkbox for AI-powered false positive reduction (all monitors except CUSTOM_SQL)

### AlertChannelPicker (`components/schedule/AlertChannelPicker.tsx`)

5 channels: Slack, Email, PagerDuty, Teams, Opsgenie. Multi-select.
3 status triggers: FAIL, WARN, ERROR. Multi-select (shown only if >= 1 channel selected).

### ScheduleInput (`components/schedule/ScheduleInput.tsx`)

5 preset buttons + custom cron input. Human-readable preview.

---

## 8. UX Flows

### Create Individual Monitor
```
"Create Task" button → CreateTaskModal
  → Select mode (Prompt / Structured)
  → Select monitor type (grouped by category)
  → Configure target + settings
  → Set schedule + timezone
  → Set alert channels + trigger statuses
  → Submit → POST /api/schedule/tasks
  → Modal closes, list refreshes
```

### Create Health Watch
```
"Create Health Watch" button → CreateWatchModal
  Step 1: Search asset → select → auto-detect watch type
  Step 2: Review recommended monitors → toggle on/off → see coverage
  Step 3: Pick schedule + timezone
  Step 4: Pick alerts + review summary + edit name
  → Submit → POST /api/schedule/watches
  → Modal closes, list refreshes
```

### Run Monitor
```
Click "Run Now" on TaskCard or task detail
  → POST /api/schedule/tasks/{id}/run
  → Next.js resolves integration config
  → Calls POST /api/v1/schedule/execute (FastAPI)
  → TaskExecutor runs monitor
  → Result saved to MonitorRun + Monitor updated
  → UI refetches task list + runs
```

### Run All Watch Monitors
```
Click "Run All" on WatchCard or WatchDetailPanel
  → POST /api/schedule/watches/{id}/run
  → Runs all child monitors sequentially
  → Aggregates health score + failure groups
  → Updates MonitorGroup health fields
  → UI refetches watch detail
```

### View Monitor Run History
```
Click task in list → detail view → RunHistoryTable loads
  → GET /api/schedule/tasks/{id}/runs?limit=25
  → Click row to expand → see message, details, SQL, AI assessment
  → Click "Ask Scout" → navigate to /dashboard/assistant with context
```

### View Watch Child Monitor Runs
```
Click watch → WatchDetailPanel loads
  → GET /api/schedule/watches/{id} (with last run per monitor)
  → Expand child monitor → lazy-fetch /api/schedule/tasks/{monitorId}/runs?limit=10
  → RunHistoryTable renders inside watch panel
```

---

## 9. Health & Coverage Scoring

### Health Score Formula (`scanner/monitors/health.py`)

```
score = sum(priority_weight x depth_multiplier x status_score) / sum(priority_weight x depth_multiplier) x 100
```

**Status Scores**:
| Status | Score |
|---|---|
| PASS | 1.0 |
| WARN | 0.5 |
| FAIL | 0.0 |
| ERROR | 0.0 |
| SKIPPED | 0.8 |

**Priority Weights**:
| Priority | Weight |
|---|---|
| 1 (Critical) | 3.0 |
| 2 (High) | 2.0 |
| 3 (Medium) | 1.0 |
| 4+ (Low) | 0.5 |

**Depth Multipliers**:
| Depth | Multiplier |
|---|---|
| 0 (Direct/Anchor) | 2.0 |
| 1 (Immediate upstream) | 1.5 |
| 2+ (Deeper) | 1.0 |

### Health Status Bands

| Score | Status |
|---|---|
| 90-100 | healthy |
| 70-89 | degraded |
| 40-69 | at_risk |
| 0-39 | unhealthy |

### Failure Grouping

- Groups failing signals by failure category
- Maps monitor types to categories:
  - freshness -> stale_data
  - schema_change -> schema_break
  - sync_lag/failed_syncs -> ingestion_lag
  - dag_*/task_failure_rate -> orchestration_failure
  - anomaly/null_rate/volume -> quality_anomaly
  - dbt_* -> transform_failure
- Picks deepest signal as root-cause hint
- Sorts by severity (critical first), then signal count

### Coverage Scoring (`scanner/monitors/asset_health.py`)

**Applicable monitors per node category**:
```
warehouse:      freshness, volume, schema_change, anomaly, uniqueness, null_rate, referential
bi:             bi_freshness_proxy, bi_content_health, bi_upstream_break_risk, bi_refresh_failure
ingestion:      sync_lag, failed_syncs, connector_schema_drift
orchestration:  dag_last_run, dag_schedule_lag, task_failure_rate
dbt_transform:  dbt_test_failures, dbt_model_freshness, dbt_source_freshness
infra:          server_health, certificate, log_analysis
```

Coverage = configured monitors / available monitors for category.

### Watch Scope Defaults (`scanner/monitors/scope.py`)

| Watch Type | maxDepth | maxNodes | maxMonitors |
|---|---|---|---|
| pipeline_health | 3 | 15 | 12 |
| dashboard_shield | 4 | 20 | 15 |
| source_guard | 1 | 5 | 6 |
| model_quality | 2 | 10 | 10 |
| custom_watch | 2 | 10 | 8 |

Scope selection: Bounded BFS via lineage engine, filter by domain, score by closeness/criticality/connectivity, cap at maxNodes, generate monitors per recipe, cap at maxMonitors.

---

## 10. Key Implementation Notes

### Transaction Timeouts
All `prisma.$transaction()` calls in watch/bundle CRUD use `{ maxWait: 10000, timeout: 30000 }` to prevent timeout errors when creating groups with many child monitors.

### FQN Database Remapping
When the FQN's database portion doesn't match the connected integration's project/database (e.g., `postgres.public.orders` from Fivetran lineage with BigQuery as the connected warehouse), the executor remaps to the integration's actual project. This handles cross-platform lineage nodes transparently.

### Baseline Injection Strategy
Stored baselines allow monitors to work even when warehouse lacks sufficient history:
- Anomaly: synthetic `historical_values` from stored mean/stddev
- Volume: injected `historical_mean`/`historical_stddev`
- Freshness: injected `cadence_gaps` from BaselineStore

### Config Storage Pattern
- Warehouse monitors: `integrationId` as FK or `nodeId` in config
- Infrastructure monitors: `serverNodeId` in config
- Tool monitors: `toolNodeId` in config
- BI monitors: `biNodeId` in config

### Source Mode Validation
- Airflow in GitHub mode -> ERROR (requires live API)
- dbt in static mode -> ERROR (requires dbt Cloud API)
- Checked before execution in `tasks/[taskId]/run`
