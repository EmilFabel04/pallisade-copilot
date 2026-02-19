# Structured Monitors

This document describes how every structured monitor type works in the Pallisade scheduled tasks system — what they check, how they're configured, how they auto-tune, and what results they produce.

---

## Overview

Scheduled tasks have two modes:

- **Structured monitors** — SQL-based or SSH-based checks that run automatically against a connected integration. This document covers these.
- **Prompt-based tasks** — Free-form LLM analysis using natural language. Not covered here.

### Status values

Every monitor run produces one of these statuses:

| Status | Meaning |
|--------|---------|
| `PASS` | All checks passed |
| `WARN` | Warning threshold exceeded but not critical |
| `FAIL` | Critical threshold exceeded or anomaly detected |
| `ERROR` | Query failed, column missing, invalid config, or connection issue |
| `SKIPPED` | Insufficient data to run a meaningful check |

### Source files

| File | Purpose |
|------|---------|
| `scanner/monitors/base.py` | `BaseMonitor`, `MonitorResult`, `MonitorStatus` |
| `scanner/monitors/freshness.py` | `FreshnessMonitor` |
| `scanner/monitors/volume.py` | `VolumeMonitor` |
| `scanner/monitors/anomaly.py` | `AnomalyMonitor` |
| `scanner/monitors/schema.py` | `SchemaMonitor` |
| `scanner/monitors/infrastructure.py` | `CertificateMonitor`, `ServerHealthMonitor`, `LogMonitor` |
| `scanner/monitors/executor.py` | `MonitorExecutor`, registry, auto-configuration, routing |
| `scanner/scheduler/executor.py` | `TaskExecutor` — orchestrates execution, LLM validation |
| `scanner/scheduler/service.py` | `SchedulerService` — cron loop, result persistence, alerting |

---

## SQL-Based Monitors

These monitors generate SQL, execute it against a connected warehouse (BigQuery, Snowflake, Postgres, Redshift), and evaluate the results. SQL is written in a generic Postgres-compatible dialect and transpiled to the target warehouse via `sqlglot`.

---

### 1. Freshness

**Purpose:** Detect when a table hasn't been updated recently.

**How it works:** Queries `MAX(timestamp_column)` and computes how many hours ago the last row was written.

#### Config

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `timestamp_column` | string | auto-detected | Column to check. If blank, auto-discovered from INFORMATION_SCHEMA. |
| `max_hours` | float | 24 | SLA threshold — hours before FAIL. |
| `warn_hours` | float | max_hours * 0.75 | Warning threshold — hours before WARN. |

#### Auto-detection: timestamp column

When no `timestamp_column` is provided, the system queries `INFORMATION_SCHEMA.COLUMNS` for all timestamp/datetime/date columns and picks the best match using this priority list (highest priority first):

1. `_partitiontime` (BigQuery load time)
2. `loaded_at`, `_loaded_at`
3. `ingested_at`, `_ingested_at`
4. `_etl_loaded_at`
5. `_fivetran_synced` (Fivetran)
6. `_airbyte_extracted_at` (Airbyte)
7. `created_at`, `created`, `inserted_at`
8. `updated_at`, `modified_at`
9. `timestamp`, `event_time`, `event_timestamp`

If none match the priority list, the first timestamp column found is used.

#### Auto-configuration: SLA threshold

When no `max_hours` is provided, the system queries the last 30 days of daily `MAX(timestamp_column)` values, computes the gaps between consecutive days, and:

1. Calculates the P95 gap (in hours)
2. Sets `max_hours = ceil(P95 * 1.5)`
3. Clamps the result to the range [1h, 168h] (1 hour to 1 week)

#### Status logic

| Condition | Status |
|-----------|--------|
| hours_since_update ≤ warn_hours | PASS |
| warn_hours < hours_since_update ≤ max_hours | WARN |
| hours_since_update > max_hours | FAIL |
| Table is empty (0 rows) | SKIPPED |
| User-specified column has all NULLs | ERROR |
| Auto-detected column has all NULLs | SKIPPED |

#### Generated SQL (BigQuery example)

```sql
SELECT
  MAX(timestamp_col) AS last_value,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), CAST(MAX(timestamp_col) AS TIMESTAMP), SECOND) / 3600.0 AS hours_since_update,
  COUNT(*) AS total_rows
FROM `project.dataset.table`
WHERE timestamp_col IS NOT NULL
```

#### Result details

```json
{
  "timestamp_column": "_fivetran_synced",
  "last_value": "2025-02-19T07:30:00Z",
  "total_rows": 1000000,
  "warn_hours": 18.0
}
```

---

### 2. Volume

**Purpose:** Detect anomalous row count changes — sudden drops or spikes.

**How it works:** Either counts total rows (simple mode) or counts rows per day over a lookback window (time-series mode), then applies threshold or Z-score analysis.

#### Config

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `min_rows` | int | null | Minimum acceptable row count (simple mode). |
| `max_rows` | int | null | Maximum acceptable row count (simple mode). |
| `anomaly_threshold` | float | 3.0 | Z-score threshold for anomaly detection. |
| `historical_mean` | float | null | Pre-computed baseline mean for Z-score. |
| `historical_stddev` | float | null | Pre-computed baseline stddev for Z-score. |
| `time_bucket_column` | string | null | Column to bucket by day (enables time-series mode). |
| `lookback_days` | int | 30 | Days of history to analyze in time-series mode. Clamped to `max_scan_days`. |
| `max_scan_days` | int | 90 | Upper bound for `lookback_days` to prevent unbounded scans. |
| `min_abs_delta` | int | 10 | Minimum absolute change to trigger WARN when stddev=0 (constant volume). |
| `min_rel_delta` | float | 0.01 | Minimum relative change (fraction) to trigger WARN when stddev=0. |

#### Two modes

**Simple mode** (no `time_bucket_column`): Runs `SELECT COUNT(*) FROM table`. Checks against `min_rows`/`max_rows` thresholds. If `historical_mean`/`historical_stddev` are provided, also applies Z-score analysis.

**Time-series mode** (with `time_bucket_column`): Runs `SELECT date, COUNT(*) GROUP BY date` for the lookback window. Uses all days except the most recent as the baseline, computes Z-score for the latest day's count.

#### Auto-configuration

When neither `min_rows` nor `max_rows` is provided:

1. Auto-discovers a timestamp column (same priority list as freshness)
2. Queries daily row counts for the last 30 days
3. Computes mean and stddev
4. Sets `min_rows = max(0, mean - 3σ)` and `max_rows = mean + 3σ`
5. Also sets `time_bucket_column` to the discovered timestamp column

#### Status logic (time-series mode)

| Condition | Status |
|-----------|--------|
| < 3 data points in lookback window | SKIPPED |
| Constant volume and delta ≥ min_abs_delta AND ≥ min_rel_delta | WARN |
| Constant volume and delta below thresholds | PASS |
| \|z_score\| > anomaly_threshold | FAIL |
| Within expected range | PASS |

#### Status logic (simple mode)

| Condition | Status |
|-----------|--------|
| Z-score exceeds threshold (if baseline provided) | FAIL |
| Row count < min_rows | FAIL |
| Row count > max_rows | FAIL |
| Within range | PASS |

---

### 3. Anomaly

**Purpose:** Statistical Z-score anomaly detection on any column metric.

**How it works:** Computes a metric (e.g., null rate, average, distinct count) per day over a lookback window, uses all prior days as the baseline, and flags the most recent value if its Z-score exceeds the threshold.

#### Config

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `column` | string | "" | Target column. Use `"*"` to auto-discover columns (all columns for null_rate/distinct_rate, numeric only for avg/min/max/etc.). |
| `metric` | string | "row_count" (no column) or "avg" (with column) | Metric to track. See table below. |
| `anomaly_threshold` | float | 3.0 | Z-score threshold. |
| `seasonality` | string | null | Set to `"day_of_week"` to compare only same-weekday baselines. |
| `lookback_days` | int | 30 | Days of history for baseline. |
| `timestamp_column` | string | null | Column for time bucketing. Without this, takes a single snapshot. |
| `historical_values` | float[] | null | Pre-computed baseline values (overrides warehouse query). |

#### Available metrics

**Column-level** (requires a `column`):

| Metric | SQL expression |
|--------|---------------|
| `null_rate` | `SUM(CASE WHEN col IS NULL THEN 1 ELSE 0 END) / COUNT(*)` |
| `distinct_count` | `COUNT(DISTINCT col)` |
| `distinct_rate` | `COUNT(DISTINCT col) / COUNT(*)` |
| `min` | `MIN(CAST(col AS FLOAT))` |
| `max` | `MAX(CAST(col AS FLOAT))` |
| `avg` | `AVG(CAST(col AS FLOAT))` |
| `sum` | `SUM(CAST(col AS FLOAT))` |
| `stddev` | `STDDEV(CAST(col AS FLOAT))` |
| `zero_rate` | `SUM(CASE WHEN col = 0 THEN 1 ELSE 0 END) / COUNT(*)` |

**Table-level** (no column needed):

| Metric | SQL expression |
|--------|---------------|
| `row_count` | `COUNT(*)` |

#### Seasonality

When `seasonality: "day_of_week"` is set, the baseline is filtered to only include data points from the same weekday as the current value. This prevents false positives for tables with strong weekly patterns (e.g., lower weekend volume).

Requires at least 3 same-weekday data points for the Z-score to activate.

#### Adaptive lookback

If the initial query (default 30 days) returns fewer than 3 data points, the system automatically retries with shorter windows:

1. 25 days
2. 20 days
3. 14 days
4. 7 days

All lookbacks are bounded — the system never falls back to scanning all available data (unbounded). If no retry produces ≥ 3 data points, the monitor reports the current value as a "baseline observation" (PASS) and notes that anomaly detection isn't ready yet.

#### Confidence scaling

The confidence of the Z-score analysis depends on how much baseline data is available:

| Baseline days | Confidence |
|---------------|------------|
| ≥ 30 | 100% |
| 20–29 | 85% |
| 14–19 | 75% |
| 7–13 | 60% |
| 3–6 | 40% |
| < 3 | 0% (observation mode) |

Confidence is reported in the result details and appended to the message when below 100%.

#### Multi-column mode

When `column: "*"`, the system:

1. Determines which columns to discover based on the metric:
   - **All-column metrics** (`null_rate`, `distinct_count`, `distinct_rate`): discovers ALL columns except complex types (STRUCT, ARRAY, JSON, GEOGRAPHY, RECORD, VARIANT, OBJECT)
   - **Numeric-only metrics** (`avg`, `min`, `max`, `sum`, `stddev`, `zero_rate`): discovers only numeric columns (INT, FLOAT, NUMERIC, etc.)
2. Caps the column list at `MAX_MULTI_COLUMNS` (50) to prevent excessive queries
3. Runs the specified metric on each column independently
4. Returns FAIL if any column is anomalous
5. Reports per-column results in `details.per_column`

#### Status logic

| Condition | Status |
|-----------|--------|
| \|z_score\| > anomaly_threshold | FAIL |
| stddev = 0 and current ≠ mean | FAIL |
| < 3 baseline data points | PASS (observation mode) |
| Within expected range | PASS |

#### Result details

```json
{
  "column": "revenue",
  "metric": "avg",
  "z_score": 4.23,
  "baseline_mean": 150.42,
  "baseline_stddev": 12.8,
  "baseline_count": 29,
  "seasonality": null,
  "confidence_pct": 100
}
```

---

### 4. Schema Change

**Purpose:** Detect column additions, removals, and data type changes.

**How it works:** Queries `INFORMATION_SCHEMA.COLUMNS` for the current schema and compares it against a stored baseline.

#### Config

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `baseline_columns` | array | null | Expected column definitions. Each entry has `column_name`, `data_type`, and optionally `is_nullable`. |
| `fail_on_column_added` | bool | false | Whether new columns trigger FAIL (otherwise WARN). |
| `fail_on_column_removed` | bool | true | Whether missing columns trigger FAIL. |
| `fail_on_type_change` | bool | true | Whether data type changes trigger FAIL. |

#### First-run behavior

When no `baseline_columns` is provided (first run), the monitor captures the current schema and returns PASS with `is_baseline_run: true` in the details. The captured schema becomes the baseline for subsequent runs.

#### Change detection

The monitor detects three types of changes:

| Change type | Description |
|-------------|-------------|
| `column_added` | Column exists in current schema but not in baseline |
| `column_removed` | Column exists in baseline but not in current schema |
| `type_changed` | Column exists in both but data type differs |

All comparisons are case-insensitive and use **dialect-aware type normalization** to prevent false positives across warehouses. For example, `INT64` (BigQuery) and `integer` (Postgres) are treated as the same type. Length/precision is stripped (e.g., `varchar(255)` → `varchar`). Key normalizations include:

- `INT64`, `int`, `int4` → `integer`
- `FLOAT64`, `float8`, `double precision` → `double`
- `STRING` → `text`
- `character varying` → `varchar`
- `NUMBER` → `numeric`
- `timestamp with time zone`, `TIMESTAMP_LTZ`, `TIMESTAMP_TZ` → `timestamptz`

#### Status logic

| Condition | Status |
|-----------|--------|
| No baseline (first run) | PASS (captures baseline) |
| No changes detected | PASS |
| Changes detected, none configured to fail | WARN |
| Changes detected, at least one configured to fail | FAIL |

#### Result details

```json
{
  "changes": [
    { "change_type": "column_removed", "column": "old_field", "old_type": "varchar" },
    { "change_type": "column_added", "column": "new_field", "new_type": "bigint" },
    { "change_type": "type_changed", "column": "amount", "old_type": "integer", "new_type": "bigint" }
  ],
  "change_count": 3,
  "baseline_column_count": 12,
  "current_column_count": 12
}
```

---

## Infrastructure Monitors

These monitors connect via SSH to a Linux server integration and do **not** use SQL. They check system-level health.

---

### 5. Certificate

**Purpose:** Monitor TLS/SSL certificate expiry and detect missing client certificates (mutual TLS).

#### Config

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `cert_paths` | string[] | auto-discover | Specific certificate file paths to check. |
| `warn_days` | int | 30 | Days before expiry to trigger WARN. |
| `fail_days` | int | 7 | Days before expiry to trigger FAIL. |

#### Status logic

| Condition | Status |
|-----------|--------|
| Any cert expired or expires within `fail_days` | FAIL |
| Server cert found but no matching client cert (mutual TLS) | FAIL |
| Any cert expires within `warn_days` | WARN |
| All certs valid with ≥ `warn_days` until expiry | PASS |

#### Result details

```json
{
  "certs_checked": 3,
  "issues": ["server cert found but no matching client cert"],
  "warnings": [],
  "certificates": [
    {
      "path": "/etc/ssl/certs/server.pem",
      "subject": "CN=myserver.example.com",
      "issuer": "CN=Let's Encrypt Authority X3",
      "not_after": "2025-06-15T00:00:00Z",
      "days_until_expiry": 116,
      "has_client_cert": true
    }
  ]
}
```

---

### 6. Server Health

**Purpose:** Monitor CPU, memory, and disk usage.

#### Config

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_cpu` | float | 90.0 | CPU usage % threshold for FAIL. |
| `max_memory` | float | 90.0 | Memory usage % threshold for FAIL. |
| `max_disk` | float | 85.0 | Disk usage % threshold for FAIL. |

#### Status logic

WARN triggers at 80% of the threshold (e.g., CPU at 72% when threshold is 90%).

| Condition | Status |
|-----------|--------|
| Any metric exceeds its threshold | FAIL |
| Any metric exceeds 80% of its threshold | WARN |
| All metrics within limits | PASS |

#### Result details

```json
{
  "hostname": "prod-server-01",
  "os": "Ubuntu 22.04.3 LTS",
  "cpu_percent": 45.2,
  "memory_percent": 68.1,
  "memory_total_gb": 32.0,
  "memory_used_gb": 21.8,
  "load_avg": [1.25, 1.10, 0.98],
  "uptime_seconds": 2592000,
  "disk_usage": [
    {
      "mount": "/",
      "percent": 55.3,
      "total_gb": 500.0,
      "used_gb": 276.5,
      "available_gb": 223.5
    }
  ]
}
```

---

### 7. Log Analysis

**Purpose:** Scan server log files for error patterns.

#### Config

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `log_paths` | string[] | required | Log file paths to scan (e.g., `["/var/log/app.log"]`). |
| `error_patterns` | string[] | `["ERROR", "FATAL", "CRITICAL"]` | Regex patterns to match against log lines. |
| `max_errors` | int | 10 | Error count threshold for FAIL. |
| `lookback_lines` | int | 1000 | Number of lines to tail from each file. |

#### Status logic

| Condition | Status |
|-----------|--------|
| total_errors > max_errors | FAIL |
| total_errors > max_errors / 2 | WARN |
| total_errors ≤ max_errors / 2 | PASS |
| No log_paths configured | ERROR |

#### Result details

```json
{
  "total_errors": 7,
  "files_checked": 2,
  "per_file": [
    { "path": "/var/log/app.log", "error_count": 5, "lines_checked": 1000 },
    { "path": "/var/log/worker.log", "error_count": 2, "lines_checked": 1000 }
  ],
  "sample_errors": [
    "[/var/log/app.log] 2025-02-19 ERROR: Connection timeout to database",
    "[/var/log/app.log] 2025-02-19 CRITICAL: Out of memory"
  ],
  "patterns": ["ERROR", "FATAL", "CRITICAL"]
}
```

---

## UI Routing Aliases

The frontend exposes three convenience monitor types that route to the Anomaly monitor backend with pre-set configurations:

| UI type | Routes to | Default config |
|---------|-----------|---------------|
| `null_rate` | `anomaly` | `metric: "null_rate", column: "*"` |
| `uniqueness` | `anomaly` | `metric: "distinct_rate", column: "*"` |
| `distribution` | `anomaly` | `metric: "avg", column: "*"` |

All three use `column: "*"` which triggers multi-column mode. For `null_rate` and `uniqueness`, **all** columns (including strings) are checked. For `distribution` (metric=avg), only numeric columns are checked.

Defined in `scanner/monitors/executor.py` as `MONITOR_ROUTING`.

---

## Execution Flow

When a scheduled task runs, here's what happens step by step:

### 1. Scheduler detects due task

`SchedulerService` runs a background loop every 60 seconds. It queries for monitors where `enabled = true AND nextRunAt <= now()`, taking up to 50 due tasks per iteration.

### 2. Resolve monitor type

`MonitorExecutor.resolve_monitor_type()` applies routing (e.g., `null_rate` → `anomaly` with `metric: "null_rate", column: "*"`). The resolved type and merged config are passed forward.

### 3. Parse target FQN

The `target_fqn` (e.g., `raw.orders` or `project.raw.orders`) is split into database, schema, and table. Two-part FQNs infer the database from the integration config.

### 4. Auto-configure

`MonitorExecutor.auto_configure()` fills in missing config by querying the warehouse:

- **Freshness**: discovers timestamp column, computes P95 gap → sets `max_hours`
- **Volume**: discovers timestamp column, computes daily count stats → sets `min_rows`/`max_rows`
- Other types: no auto-configuration needed

Auto-configuration never overwrites user-provided values.

### 5. Build and execute SQL

The monitor's `build_query()` generates SQL, which is transpiled to the target dialect via `sqlglot`. The query is executed against the warehouse via the adapter's `execute_query()`.

### 6. Evaluate results

The monitor's `evaluate()` interprets the query results and produces a `MonitorResult` with status, value, threshold, message, and details.

### 7. Adaptive retry (anomaly only)

If an anomaly monitor reports "not enough data" (< 3 data points), the executor retries with bounded shorter lookback windows: 25 → 20 → 14 → 7 days. The system never falls back to unbounded scans.

### 8. LLM validation (optional)

When a monitor returns FAIL or WARN, the system can optionally send the result to an LLM for validation. The LLM reviews the context (monitor type, value, threshold, z-score, baseline stats, confidence) and can suggest adjustments. However, the following constraints are enforced:

- **Never upgrade PASS → FAIL** — the LLM cannot escalate a passing result
- **Downgrade only when data is uncertain** — FAIL → WARN or WARN → PASS is only allowed when `confidence_pct < 60` or `baseline_count < 7`
- **Always track both statuses** — `raw_status` (pre-LLM) and `final_status` (post-LLM) are both persisted alongside the `llm_reason`

The original result is preserved in `raw_status` and the LLM assessment is appended to `details.llm_validation`.

### 9. Save result

A `MonitorRun` record is created with the status, value, threshold, message, details, SQL executed, and timing. The `Monitor` record is updated with `lastRunAt`, `lastStatus`, `nextRunAt` (next cron tick), and baseline stats (mean, stddev, count) if available in the result details.

### 10. Dispatch alerts

If the result status matches the monitor's `alertOnStatus` configuration, an alert is sent to the configured channels (Slack, Teams, PagerDuty, etc.) via the `/api/schedule/alert` endpoint. Alerts use `final_status` (post-LLM) when available.

---

## Baseline Persistence

Monitors that compute statistical baselines (anomaly, volume) persist their baseline stats in the `Monitor` database record:

| Field | Description |
|-------|-------------|
| `baselineMean` | Mean of the metric across the baseline window |
| `baselineStddev` | Standard deviation of the baseline |
| `baselineCount` | Number of data points in the baseline |

These values are saved after each run (extracted from `result.details`) and injected as `stored_baseline` into the monitor config on the next run. This allows monitors to maintain continuity even if the warehouse data changes or is unavailable.

For anomaly monitors with stored baselines, the values are reconstructed as:
- If stddev > 0: `[mean - σ, mean, mean + σ]` repeated to match the count
- If stddev = 0: `[mean]` repeated to match the count

---

## Walkthrough: Freshness Monitor

```
User creates task:
  name: "Orders Freshness Check"
  monitorType: "freshness"
  targetFqn: "raw.orders"
  config: {}  (empty — auto-configure everything)
  schedule: "0 8 * * *"  (daily at 8am)
  integrationId: "<bigquery-id>"

Scheduler triggers at 8:00 AM:

1. Parse FQN → database: "<project>", schema: "raw", table: "orders"

2. Auto-configure:
   a. discover_timestamp_column() queries INFORMATION_SCHEMA
   b. Finds: [created_at, updated_at, _fivetran_synced]
   c. Picks _fivetran_synced (priority rank 6, highest match)
   d. Queries daily MAX(_fivetran_synced) for last 30 days
   e. Computes inter-day gaps: [2h, 1.5h, 3h, 2h, ...]
   f. P95 gap = 4h → max_hours = ceil(4 * 1.5) = 6
   g. Config becomes: {timestamp_column: "_fivetran_synced", max_hours: 6}

3. Build query:
   SELECT MAX(_fivetran_synced) AS last_value,
          TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), CAST(MAX(_fivetran_synced) AS TIMESTAMP), SECOND) / 3600.0 AS hours_since_update,
          COUNT(*) AS total_rows
   FROM `project.raw.orders`
   WHERE _fivetran_synced IS NOT NULL

4. Execute → {last_value: "2025-02-19T07:30:00Z", hours_since_update: 0.5, total_rows: 1000000}

5. Evaluate:
   hours = 0.5
   warn_hours = 6 * 0.75 = 4.5
   0.5 ≤ 4.5 → PASS
   message: "Data is 0.5h old. Within the 6h SLA."

6. Save MonitorRun, update next run to tomorrow 8am
```

---

## Walkthrough: Multi-Column Anomaly (Null Rate)

```
User creates task:
  monitorType: "null_rate"  (UI alias)
  targetFqn: "analytics.user_events"
  config: {}

Execution:

1. Resolve: "null_rate" → ("anomaly", {metric: "null_rate", column: "*"})

2. Multi-column mode activates (null_rate → ALL columns, not just numeric):
   a. Query INFORMATION_SCHEMA for all columns (excluding complex types like STRUCT/ARRAY/JSON)
   b. Finds: [user_id, event_count, revenue, page_views, event_name, source]
   c. Capped at 50 columns max

3. For each column, run anomaly monitor independently:

   Column: user_id
   - Query: SELECT date, SUM(CASE WHEN user_id IS NULL THEN 1 ELSE 0 END) / COUNT(*) AS metric_value
            FROM analytics.user_events WHERE date >= CURRENT_DATE - 30 GROUP BY date
   - Results: 30 daily null rates, latest = 0.05
   - Baseline (29 days): mean = 0.001, stddev = 0.0005
   - Z-score: (0.05 - 0.001) / 0.0005 = 98.0 → FAIL

   Column: event_count → Z-score = 0.3 → PASS
   Column: revenue → Z-score = -1.2 → PASS
   Column: page_views → Z-score = 0.8 → PASS
   Column: event_name (string!) → Z-score = 0.1 → PASS
   Column: source (string!) → Z-score = 0.2 → PASS

4. Aggregate: 1 of 6 columns anomalous → overall FAIL
   Message: "Anomalies detected in 1/6 columns: user_id null_rate is anomalous (z=98.0)"
   Details: { columns_checked: 6, anomalies: 1, per_column: [...] }
```
