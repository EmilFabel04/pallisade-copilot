# Pallisade — AI-Powered Data Pipeline Reliability Platform

Pallisade is a data reliability platform that gives data teams a single control plane for monitoring, debugging, and improving their data pipelines. At its core is **Scout**, an AI copilot that understands your warehouse schemas, lineage graph, and monitor history — so you can ask questions, investigate incidents, and ship fixes without context-switching between tools.

---

## Platform Overview

### AI Copilot (Scout)

Scout is an AI assistant purpose-built for data engineering. It connects directly to your warehouses, transformation layer, and orchestration tools so it can answer questions with real data rather than guesswork.

**8 interaction modes** tailor Scout's behavior to the task:

| Mode | Purpose |
|------|---------|
| Ask | General questions — Scout runs queries and gives direct answers |
| Debug | Root cause analysis with structured Problem → Cause → Fix output |
| Plan | Strategic migration/refactoring plans with lineage impact analysis |
| Create | Generate production-ready SQL, dbt models, tests, or documentation |
| Explain | Deep-dive explanations of tables, models, or pipeline behavior |
| Suggest | Improvement recommendations for performance, quality, or structure |
| Fix | Apply validated changes via GitHub PRs |
| Bundle | Package deliverables (reports, migration bundles, handoff docs) |

**Key capabilities:**

- Execute read queries instantly against connected warehouses
- Trace upstream and downstream dependencies through the lineage graph
- Run ad-hoc quality checks (freshness, volume, null rates, schema drift)
- Create change plans with impact analysis, validation, and GitHub PR creation
- Reference tables, models, and columns via @mentions in the chat
- Save useful responses as persistent artifacts for the team
- Onboarding flow that teaches Scout about your specific setup

**Supported models:** GPT-5.4, GPT-5.4 Mini, Claude Opus, Claude Sonnet, Claude Haiku

---

### Data Lineage

Pallisade builds a unified lineage graph that spans your entire stack — from ingestion through transformation to reporting.

**Two visualization planes:**

- **Data lineage** — Table and view dependencies extracted from SQL, dbt manifests, and warehouse metadata. Nodes are color-coded by layer (ingestion, staging, warehouse, reporting).
- **Orchestration lineage** — DAG and task execution flow from Airflow, Dagster, or Prefect. Can be overlaid on data lineage to show which orchestration tasks produce which tables.

**Features:**

- Confidence scoring on every edge (based on evidence strength)
- Edge evidence panel showing the exact SQL or manifest entry that created the relationship
- Coverage stats (% of tables and columns with traced lineage)
- Filter by layer, node type, or minimum confidence level
- Click-to-inspect with upstream/downstream neighbor lists, freshness, row counts, and health scores
- Automatic layout via Dagre with direction toggle
- Cross-adapter deduplication (same table referenced by dbt and warehouse SQL resolves to one node)

---

### Scheduled Monitoring

Create automated quality checks that run on a cron schedule and alert your team when something breaks.

**Data quality monitors:**

| Monitor | What it checks |
|---------|---------------|
| Freshness | Time since the last row was written to a table |
| Volume | Row count anomalies (Z-score against historical baseline) |
| Schema Change | Column additions, removals, and type changes |
| Null Rate | Null percentage per column, flagged via Z-score anomaly detection |
| Uniqueness | Distinct value rate per column |
| Distribution | Statistical distribution shifts (mean, stddev) per numeric column |
| Anomaly | General-purpose Z-score detection on any metric/column combination |
| Custom SQL | User-defined SQL that returns a value to evaluate against a threshold |

**Infrastructure monitors:**

| Monitor | What it checks |
|---------|---------------|
| Certificate | TLS/SSL certificate expiry on servers (via SSH) |
| Server Health | CPU, memory, and disk usage on Linux servers (via SSH) |
| Log Analysis | Error pattern scanning in server log files (via SSH) |

**Monitor features:**

- Auto-configuration: Pallisade discovers timestamp columns, computes baseline statistics, and sets initial thresholds automatically
- Adaptive lookback: If the default 30-day window has too few data points, the system retries with shorter windows (25 → 20 → 14 → 7 days) without falling back to unbounded scans
- LLM validation: Optionally sends FAIL/WARN results to an LLM for false-positive review (can downgrade but never upgrade severity)
- Multi-column mode: Null rate, uniqueness, and distribution monitors can scan all columns in a table automatically
- Dialect-aware SQL generation: Monitors generate SQL via sqlglot and transpile to the target warehouse's dialect
- Seasonality support: Day-of-week baseline comparison for metrics with weekly patterns

**Alert channels:** Slack, Microsoft Teams, PagerDuty, OpsGenie — configurable per-task with status filters (alert on FAIL only, FAIL + WARN, etc.)

**Run history:** Every execution is logged with status, value, threshold, Z-score, SQL executed, duration, and full detail JSON. From any run, you can "Ask Scout" to explain, verify, or investigate the result.

---

### Change Plans

Scout can create structured change plans for schema migrations, dbt model refactors, or pipeline modifications.

**Workflow:**

1. **Impact analysis** — Scout traces the lineage graph to identify all affected tables, downstream consumers, and breaking changes
2. **Plan creation** — Generates file patches (SQL, YAML, Python) with a description, root cause, and risk assessment
3. **Validation** — Three levels: static analysis, CI pipeline, and sandbox execution
4. **Application** — Creates a GitHub PR with the patches, linked to the change plan
5. **Rollback** — Every plan includes rollback instructions

---

### Sources Browser

Browse all tables, dbt models, and connectors across your connected warehouses.

- **Tables** — Schema, row count, column details, last updated timestamp
- **Models** — dbt models with materialization type, description, and test counts
- **Connectors** — Integration status and last sync time
- Search across all sources, link directly to lineage viewer

---

### Artifacts Library

Save any Scout response as a persistent, searchable artifact.

- Tag and categorize (queries, fixes, insights, documentation)
- Pin favorites for quick access
- Link back to the source chat session
- Share with the team

---

### Team & Access Control

- **Organization roles:** Owner, Admin, Manager, Engineer, Viewer
- **Per-pipeline roles:** Owner, Editor, Viewer
- Invite members, manage access levels, view activity
- Audit log for compliance

---

## Supported Integrations

### Warehouses & Data Platforms

| Platform | Capabilities |
|----------|-------------|
| BigQuery | Full schema discovery, query cost tracking, dataset browsing |
| Snowflake | Warehouse/database/schema navigation, role-based access |
| PostgreSQL | Standard SQL, SSL modes, schema support |
| Redshift | AWS-native features, Spectrum support |
| SQL Server | Windows auth, Azure compatibility |
| Azure SQL | Cloud-native, AAD integration |
| Databricks | Unity Catalog support |

### Transformation & Orchestration

| Tool | Integration |
|------|------------|
| dbt Cloud | Model metadata, manifest parsing, test results |
| dbt Core | Local manifest reading, model lineage extraction |
| Apache Airflow | DAG parsing, task dependency extraction, run status |
| Dagster | Asset lineage, job execution tracking |
| Prefect | Flow run monitoring |

### Data Integration

| Tool | Integration |
|------|------------|
| Fivetran | Connector status, sync monitoring |
| Airbyte | Connection health, sync tracking |
| Stitch | Replication monitoring |

### BI & Reporting

| Tool | Integration |
|------|------------|
| Looker | Dashboard/explore metadata |
| Tableau | Workbook/data source tracking |
| Power BI | Dataset/report metadata |
| Metabase | Question/dashboard tracking |

### Alerts & Notifications

Slack, Microsoft Teams, PagerDuty, OpsGenie

### Ticketing

Jira, Linear, Asana, GitHub Issues

### Cloud Storage

Amazon S3, Google Cloud Storage, Azure Data Lake Storage

### Infrastructure

Linux servers via SSH (for certificate, health, and log monitoring)

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Next.js 15 Frontend               │
│  React 19 · TypeScript · Tailwind · React Flow      │
│                                                     │
│  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐ │
│  │ Copilot │ │ Lineage  │ │Schedule │ │ Sources  │ │
│  │  Chat   │ │ Viewer   │ │ Tasks   │ │ Browser  │ │
│  └────┬────┘ └────┬─────┘ └────┬────┘ └────┬─────┘ │
└───────┼───────────┼────────────┼────────────┼───────┘
        │           │            │            │
┌───────┴───────────┴────────────┴────────────┴───────┐
│              Next.js API Routes (BFF)               │
│         Auth · Sessions · Proxying · CRUD           │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│              FastAPI Backend (scanner/)              │
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Copilot  │ │ Monitors │ │ Lineage  │            │
│  │ LLM +    │ │ Executor │ │ Engine   │            │
│  │ Tools    │ │          │ │          │            │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘            │
│       │            │            │                   │
│  ┌────┴────────────┴────────────┴─────┐             │
│  │         Adapter Layer              │             │
│  │  BigQuery · Snowflake · Postgres   │             │
│  │  Redshift · dbt · Airflow · SSH    │             │
│  └────────────────────────────────────┘             │
└─────────────────────────────────────────────────────┘
                       │
              ┌────────┴────────┐
              │   PostgreSQL    │
              │   (Prisma ORM)  │
              └─────────────────┘
```

**Key design decisions:**

- **Schema pre-fetch**: Before every copilot conversation turn, the backend fetches the current warehouse schema so the LLM always has accurate column names and types
- **Dialect-agnostic monitors**: Monitors generate SQL in a neutral dialect, then transpile to the target warehouse via sqlglot
- **Multi-warehouse support**: A single pipeline can connect multiple warehouses; schema keys use compound format (`BIGQUERY:raw`, `SNOWFLAKE:PUBLIC`) to avoid collisions
- **Streaming**: Copilot responses stream token-by-token via Server-Sent Events for real-time feedback
- **Tool confirmation**: Destructive operations (schema changes, PR creation) pause for user approval before executing

---

## Getting Started

1. **Create a pipeline** — Give it a name and select a stack template (or start from scratch)
2. **Connect your warehouse** — Add BigQuery, Snowflake, or Postgres credentials and test the connection
3. **Add your transformation layer** — Connect dbt Cloud/Core for model metadata and lineage
4. **Run onboarding** — Let Scout ask you a few questions about your setup so it can help without repeated clarification
5. **Start asking questions** — Use the AI assistant to query your data, debug issues, and set up monitors
6. **Schedule monitors** — Create automated checks for freshness, volume, and schema changes on your critical tables
7. **Set up alerts** — Connect Slack or PagerDuty so your team gets notified when monitors fail
