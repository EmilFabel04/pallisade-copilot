# Structured Monitors Guide

Pallisade's scheduled monitors continuously watch your data pipeline for problems. Instead of waiting for a stakeholder to notice bad data, monitors run on a schedule you define and alert you when something looks off.

Each monitor targets a specific part of your stack — a warehouse table, an ingestion connector, an orchestration DAG, a dbt job, or a server. When a monitor runs, it produces one of these statuses:

| Status | What it means |
|--------|---------------|
| **PASS** | Everything looks good |
| **WARN** | Something is slightly off but not critical yet |
| **FAIL** | A threshold was breached or an anomaly was detected |
| **ERROR** | The check itself couldn't run (bad config, connection issue, etc.) |
| **SKIPPED** | Not enough data to produce a meaningful result |

Alerts go out to your configured channels (email, Slack, webhook) when a monitor produces a status you care about.

---

## Data Quality Monitors

These monitors check the actual data sitting in your warehouse (BigQuery, Snowflake, Postgres, Redshift, etc.). You point them at a table and they do the rest.

---

### Freshness

**What it watches:** When your table was last updated.

**Why it matters:** Stale data means dashboards and models show outdated information. If your `orders` table normally refreshes every hour but hasn't been updated in 12 hours, something upstream is broken.

**How it works:** Looks at the most recent timestamp in your table. If the gap between that timestamp and now exceeds your threshold, you get an alert. The system auto-detects the right timestamp column (like `_fivetran_synced`, `created_at`, or `updated_at`) and can auto-compute a reasonable threshold from your table's historical update patterns.

**Example alert:** "Orders table hasn't been updated in 8 hours (SLA: 6 hours)"

**Settings you can tweak:**
- Which timestamp column to use (auto-detected by default)
- Maximum hours before alerting (auto-computed from your table's history by default)

---

### Volume

**What it watches:** How many rows are in your table, compared to what's normal.

**Why it matters:** A sudden drop in rows might mean data was accidentally deleted. A spike could mean duplicates are being inserted. Either way, downstream numbers will be wrong.

**How it works:** Learns your table's normal row count range over time. If today's count is significantly higher or lower than expected, you get an alert. Uses statistical analysis to automatically determine what "normal" looks like.

**Example alert:** "Orders table has 12,000 rows today — expected range is 45,000-55,000"

**Settings you can tweak:**
- Min/max expected rows (auto-computed from historical patterns by default)

---

### Schema Change

**What it watches:** The structure of your table — column names and data types.

**Why it matters:** If a source system renames `user_id` to `customer_id` or changes a column type, everything downstream that references the old name or type will break.

**How it works:** Takes a snapshot of your table's columns on the first run, then compares against that snapshot on every subsequent run. Reports exactly which columns were added, removed, or had their type changed.

**Example alert:** "Schema changed: column 'old_status' removed, column 'status_v2' added"

**Settings:** None needed — fully automatic.

---

### Null Rate

**What it watches:** The percentage of null (empty) values in each column of your table.

**Why it matters:** A column that's normally 100% filled suddenly having 30% nulls is a clear sign something went wrong in the loading process.

**How it works:** Automatically checks every column and learns what the normal null rate looks like over time. Uses anomaly detection to spot unexpected spikes. No configuration needed — it discovers columns and learns baselines on its own.

**Example alert:** "Anomaly in user_id null rate: 5% today vs. baseline of 0.1%"

**Settings:** Fully automatic.

---

### Uniqueness

**What it watches:** Whether columns that should be unique (like IDs or email addresses) actually are.

**Why it matters:** Duplicate primary keys usually mean a join is producing extra rows or deduplication was skipped. This silently inflates metrics without anyone noticing.

**How it works:** Checks the ratio of unique values to total values for each column. Uses anomaly detection to spot when uniqueness drops below normal levels.

**Example alert:** "Uniqueness drop in order_id: 92% unique today vs. baseline of 99.9%"

**Settings:** Fully automatic.

---

### Distribution

**What it watches:** The statistical distribution (averages) of numeric columns in your table.

**Why it matters:** If the average order value suddenly doubles, or a rating column shifts from mostly 4-5 stars to mostly 1-2 stars, that's worth investigating even if row counts look fine.

**How it works:** Computes averages for numeric columns and uses anomaly detection to spot significant deviations from historical norms.

**Example alert:** "Average revenue shifted from $150 to $340 — z-score 4.2"

**Settings:** Fully automatic.

---

### Custom SQL

**What it watches:** Whatever you want — you write the SQL query.

**Why it matters:** Sometimes you need business-specific checks like "are there orders dated in the future?" or "does every customer have at least one address?"

**How it works:** You write a SQL query that returns a single number. The monitor runs it on schedule and evaluates the result.

**Example alert:** "Custom check returned 47 (threshold: 0) — 47 orders have future dates"

**Settings:**
- Your SQL query (required — must return a single number)

---

### Anomaly

**What it watches:** Any metric you choose (row count, average, sum, null rate, distinct count) across your table's columns.

**Why it matters:** This is the catch-all monitor. It watches for anything statistically unusual without requiring you to define specific rules upfront.

**How it works:** Uses z-score analysis — basically, it measures how far today's value is from what's been "normal" historically. It builds confidence over time: after 3 days of data, it starts watching at 40% confidence. After 30+ days, it's fully confident. The default sensitivity threshold is 3.0 standard deviations, but you can adjust this.

**Example alert:** "Row count anomaly: 5,200 today vs. baseline mean of 48,000 (z-score: -8.9)"

**Settings you can tweak:**
- Which metric to track (row count, average, sum, null rate, or distinct count)
- Sensitivity threshold (default: 3.0 — higher = less sensitive)
- How many days of history to use (default: 30)
- Timestamp column (auto-detected)

---

### Referential Integrity

**What it watches:** Whether foreign key values in one table actually exist in the parent table.

**Why it matters:** Orphaned records (like an order referencing a customer that doesn't exist) cause join failures, broken reports, and data inconsistencies.

**How it works:** Checks that every value in the child column has a matching value in the parent column. Any orphans trigger an alert.

**Example alert:** "142 orders reference customer_ids that don't exist in the customers table"

**Settings:**
- Parent table (required)
- Child column / foreign key (required)
- Parent column / primary key (required)

---

## Ingestion Monitors

These monitors check your data ingestion tools (Fivetran, Airbyte) through their APIs. They make sure data is actually flowing into your warehouse on schedule.

---

### Sync Lag

**What it watches:** How long it's been since a connector last synced successfully.

**Why it matters:** If your Fivetran connector is supposed to sync every hour but hasn't in 6 hours, your warehouse data is falling behind and dashboards are stale.

**How it works:** Checks the connector's last successful sync time and compares it to the expected frequency. The threshold can be auto-computed from the connector's own schedule.

**Example alert:** "Connector 'stripe_payments' last synced 4h ago (max lag: 2h)"

**Settings:**
- Connector ID (required)
- Max lag in minutes (auto-computed from sync frequency by default)

---

### Failed Syncs

**What it watches:** Whether a connector has had recent sync failures.

**Why it matters:** A single failure might be a blip, but multiple failures usually mean something real — expired credentials, API rate limits, or source system changes.

**How it works:** Checks the connector's sync history for failures within a lookback window.

**Example alert:** "Connector 'hubspot_contacts' had 3 sync failures in the last 24 hours"

**Settings:**
- Connector ID (required)
- How far back to look (default: 24 hours)

---

### Schema Drift (Connector)

**What it watches:** Whether the source schema seen by your connector has changed.

**Why it matters:** When a source system adds or removes fields, your pipeline might start loading unexpected data or missing important columns — often without any error.

**How it works:** Compares the connector's current schema against its previous snapshot and reports any differences.

**Example alert:** "Connector 'salesforce' schema changed: 2 columns added, 1 removed"

**Settings:**
- Connector ID (required)

---

## Orchestration Monitors

These monitors check your workflow orchestration tools (Airflow, Dagster) to make sure your pipelines are running on time and succeeding.

---

### DAG Last Run

**What it watches:** When a DAG (pipeline) last ran and whether it succeeded.

**Why it matters:** If your daily ETL pipeline hasn't run in 2 days, all downstream data is stale. If the last run failed, data might be incomplete or incorrect.

**How it works:** Checks both the status (success/failure) and the timestamp (how long ago) of the most recent run. Alerts on either a failure or staleness.

**Example alert:** "DAG 'etl_daily' last successful run was 52 hours ago (threshold: 26h)"

**Settings:**
- DAG ID (required)
- Max hours since last success (auto-computed from the DAG's schedule by default)

---

### DAG Schedule Lag

**What it watches:** The delay between when a DAG was supposed to run and when it actually started.

**Why it matters:** Growing schedule lag means your orchestrator is overloaded. A pipeline scheduled for midnight that doesn't start until 3am pushes everything downstream later and later.

**How it works:** Compares scheduled execution time to actual start time. Alerts when the gap exceeds your threshold.

**Example alert:** "DAG 'etl_daily' is running 45 minutes behind schedule (threshold: 30m)"

**Settings:**
- DAG ID (required)
- Max lag in minutes (default: 30)

---

### Task Failure Rate

**What it watches:** What percentage of individual tasks within a DAG are failing.

**Why it matters:** Even if a DAG technically "succeeds," individual task failures can mean partial data loads. A 15% task failure rate on your ETL DAG means 15% of your tables might have issues.

**How it works:** Looks at all task runs within a DAG over a time window and calculates the failure percentage.

**Example alert:** "DAG 'etl_daily' task failure rate is 18% in the last 24h (threshold: 10%)"

**Settings:**
- DAG ID (required)
- Max failure percentage (default: 10%)
- How far back to look (default: 24 hours)

---

## Transformation Monitors

These monitors check your dbt (data build tool) jobs to make sure transformations are running, passing tests, and staying fresh.

---

### Test Failures

**What it watches:** Whether any dbt tests failed in the latest run.

**Why it matters:** dbt tests are your assertions about data quality — things like "this column should never be null" or "every order must have a customer." Failures mean your transformed data doesn't meet its own quality contracts.

**How it works:** Checks the latest run of a dbt Cloud job for test failures and reports which tests failed.

**Example alert:** "3 dbt tests failed in job 'daily_transforms': not_null_orders_customer_id, unique_users_email, ..."

**Settings:**
- dbt Cloud Job ID (required)
- Whether to treat warnings as failures (default: no)

---

### Model Freshness

**What it watches:** When a dbt model (transformed table) was last built.

**Why it matters:** If dbt models aren't rebuilding on schedule, dashboards and reports show stale data.

**How it works:** Checks when the specified dbt job last completed a successful run. Alerts if it's been too long.

**Example alert:** "dbt job 'daily_transforms' last ran 36 hours ago (threshold: 24h)"

**Settings:**
- dbt Cloud Job ID (required)
- Max hours since last run (default: 24)

---

### Source Freshness

**What it watches:** Whether dbt's own source freshness checks are passing.

**Why it matters:** dbt can verify that its source tables (the raw data it transforms) are fresh enough. If sources are stale, building models on top of them just produces nicely-formatted outdated data.

**How it works:** Checks dbt's source freshness results from the latest run and alerts when sources are failing their SLAs.

**Example alert:** "2 dbt sources failing freshness SLA in job 'daily_transforms'"

**Settings:**
- dbt Cloud Job ID (required)

---

## Infrastructure Monitors

These monitors connect to your servers via SSH to check system-level health. They don't touch your data — they watch the machines that run your pipeline.

---

### Certificate

**What it watches:** SSL/TLS certificate expiration dates.

**Why it matters:** An expired certificate takes down HTTPS endpoints, API connections, and secure data transfers. Getting a 30-day warning gives you time to renew without an outage.

**How it works:** Checks certificate files on the server and reports how many days until they expire. Auto-discovers common certificate locations if you don't specify paths.

**Example alert:** "Certificate at /etc/ssl/certs/server.pem expires in 5 days"

**Settings:**
- Certificate file paths (auto-discovered by default)
- Warning threshold (default: 30 days before expiry)
- Failure threshold (default: 7 days before expiry)

---

### Server Health

**What it watches:** CPU usage, memory usage, and disk space.

**Why it matters:** A server at 95% disk capacity will crash when it runs out of space. High CPU or memory degrades performance and causes pipeline failures.

**How it works:** Checks resource utilization and alerts when any metric exceeds its threshold. Fully automatic — no configuration needed.

**Example alert:** "Disk usage at 92% on / (threshold: 85%)"

**Settings:** None required — uses sensible defaults (CPU: 90%, memory: 90%, disk: 85%).

---

### Log Analysis

**What it watches:** Server log files for error patterns.

**Why it matters:** Errors in logs often signal problems before they become visible in your data. Catching "connection refused" or "out of memory" early lets you fix issues before pipelines fail.

**How it works:** Scans the specified log files for patterns like ERROR, FATAL, and CRITICAL. Reports the count and a sample of matching lines.

**Example alert:** "7 errors found in /var/log/app.log (threshold: 10) — sample: 'ERROR: Connection timeout to database'"

**Settings:**
- Log file paths (required)
- Error patterns to search for (default: ERROR, FATAL, CRITICAL)

---

## How It All Fits Together

### Execution methods

Monitors use three different methods depending on what they're checking:

- **Warehouse SQL** — Connects to your data warehouse and runs queries. Used by all Data Quality monitors. Queries are automatically translated to work with your specific warehouse (BigQuery syntax is different from Snowflake, etc.).

- **Tool API** — Calls the APIs of your connected tools (Fivetran, Airbyte, Airflow, Dagster, dbt Cloud). Used by Ingestion, Orchestration, and Transformation monitors.

- **SSH** — Connects to servers over SSH to run system commands. Used by Infrastructure monitors.

### Smart defaults

Many monitors auto-configure themselves:
- **Freshness** auto-detects which column to check and computes a reasonable SLA from your table's history
- **Volume** learns your table's normal row count range over time
- **Null Rate, Uniqueness, Distribution** auto-discover columns and learn what "normal" looks like
- **Schema Change** takes a baseline snapshot on the first run

You can always override these defaults with manual settings if the auto-detection doesn't match your needs.

### Anomaly detection

Several monitors (Null Rate, Uniqueness, Distribution, Volume, Anomaly) use statistical anomaly detection instead of fixed thresholds:

1. **Baseline building** — Each run records the metric value, building a picture of "normal" over time
2. **Z-score analysis** — Measures how far today's value is from the historical average, in terms of standard deviations
3. **Confidence scaling** — The system starts cautious (40% confidence after 3 days) and becomes fully confident after 30+ days of data
4. **Adaptive lookback** — Automatically adjusts how much history to consider

### Alerting

When a monitor produces a status you care about (default: FAIL, WARN, ERROR), alerts go out to your configured channels:

- **Email** — Sends details about what failed and why
- **Slack** — Posts a summary to a channel
- **Webhook** — Sends a JSON payload to any URL you configure

Each monitor can have its own alert channels, so critical monitors can page on-call while informational ones just post to Slack.

---

## Source Files Reference

| File | What it does |
|------|-------------|
| `types/monitor-catalog.ts` | All 23 monitor definitions, config fields, categories |
| `scanner/monitors/base.py` | Base classes and result types |
| `scanner/monitors/freshness.py` | Freshness monitor implementation |
| `scanner/monitors/volume.py` | Volume monitor implementation |
| `scanner/monitors/anomaly.py` | Anomaly detection engine (also handles null rate, uniqueness, distribution) |
| `scanner/monitors/schema.py` | Schema change detection |
| `scanner/monitors/infrastructure.py` | Certificate, server health, and log analysis monitors |
| `scanner/monitors/executor.py` | Monitor routing, auto-configuration, SQL execution |
| `scanner/scheduler/executor.py` | Task orchestration and LLM validation |
| `scanner/scheduler/service.py` | Cron scheduling loop, result persistence, alerting |
| `components/schedule/MonitorConfigForm.tsx` | Dynamic UI form rendered from catalog |
