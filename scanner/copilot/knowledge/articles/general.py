"""General data pipeline knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

GENERAL_ARTICLES = [
    KnowledgeArticle(
        id="pipeline-idempotency",
        title="Building Idempotent Data Pipelines",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["pipeline", "idempotent", "data-engineering", "reliability", "backfill", "retry"],
        tools=[],
        summary="How to build idempotent data pipelines that produce the same result regardless of how many times they run.",
        content="""## Building Idempotent Data Pipelines

### What Is Idempotency?
Running the same pipeline twice produces the same result. Essential for safe retries and backfills.

### Patterns

**1. INSERT OVERWRITE (Replace)**
- Delete and recreate the partition/table for the time period
- dbt: `materialized='incremental'` with `unique_key`
- SQL: `INSERT OVERWRITE INTO table PARTITION (date='2024-01-15') SELECT ...`

**2. MERGE / UPSERT**
- Insert new rows, update existing rows based on key
- `MERGE INTO target USING source ON target.id = source.id WHEN MATCHED THEN UPDATE ... WHEN NOT MATCHED THEN INSERT ...`

**3. DELETE + INSERT**
- Delete all rows for the time period, then insert fresh data
- Simpler than MERGE, works when you want full replacement
- dbt: `incremental_strategy='delete+insert'`

### Anti-Patterns (Not Idempotent)
- `INSERT INTO` without deduplication → duplicates on retry
- `UPDATE SET counter = counter + 1` → increments on retry
- Using `datetime.now()` instead of execution date → different results each run

### Testing Idempotency
1. Run pipeline for date X
2. Run pipeline for date X again
3. Verify row counts and data are identical
""",
    ),
    KnowledgeArticle(
        id="pipeline-monitoring",
        title="Data Pipeline Monitoring Setup",
        category=KnowledgeCategory.HOW_TO,
        tags=["monitoring", "alerting", "observability", "freshness", "quality", "sla"],
        tools=[],
        summary="How to set up data pipeline monitoring: freshness checks, quality metrics, SLOs, and alerting strategies.",
        content="""## Data Pipeline Monitoring Setup

### What to Monitor

**1. Data Freshness**
- When was the table last updated?
- Query: `SELECT MAX(updated_at) FROM <table>`
- Alert if: Freshness exceeds expected SLO (e.g., > 2 hours for hourly pipeline)

**2. Data Volume**
- How many rows were loaded?
- Compare to historical average — alert on significant deviations (>50% drop)
- Query: `SELECT COUNT(*) FROM <table> WHERE load_date = CURRENT_DATE`

**3. Data Quality**
- Null rates on critical columns
- Uniqueness violations on primary keys
- Value distributions outside expected ranges
- dbt tests are the best first line of defense

**4. Pipeline Execution**
- DAG/flow run success/failure rates
- Execution duration trends (alerting on unusual increases)
- Task-level failure tracking

### SLO Framework
| Data Type | Freshness SLO | Quality SLO |
|-----------|--------------|-------------|
| Real-time (payments) | < 5 min | 99.9% |
| Near-real-time (inventory) | < 1 hour | 99.5% |
| Batch (analytics) | < 24 hours | 99% |
| Historical (reporting) | Weekly | 95% |

### Alerting Strategy
- **P1 (page)**: Revenue-impacting data missing, pipeline down > 1 hour
- **P2 (Slack alert)**: Data delayed, quality below SLO
- **P3 (daily digest)**: Minor anomalies, slow trends
""",
    ),
    KnowledgeArticle(
        id="data-contracts",
        title="Implementing Data Contracts",
        category=KnowledgeCategory.ARCHITECTURE,
        tags=["data-contracts", "schema", "api", "governance", "producer", "consumer"],
        tools=[],
        summary="How to implement data contracts between data producers and consumers: schema definitions, versioning, and enforcement.",
        content="""## Implementing Data Contracts

### What Is a Data Contract?
An agreement between data producer and consumer about the schema, quality, and SLAs of a dataset.

### Components of a Data Contract
1. **Schema**: Column names, types, nullability, constraints
2. **Quality**: Freshness SLO, completeness, uniqueness guarantees
3. **Semantics**: Column descriptions, business definitions
4. **SLAs**: Update frequency, availability guarantees
5. **Owner**: Team/person responsible for the data

### Implementation Approaches

**1. dbt Schema Tests (Simplest)**
- Define expectations in `schema.yml`
- Run `dbt test` in CI and production
- Catches: null violations, uniqueness, accepted values, relationships

**2. Great Expectations / Soda**
- More expressive expectations (distributions, outliers)
- Standalone — works outside dbt
- Good for raw data before transformation

**3. Schema Registry (Kafka)**
- Enforce schema on streaming data at write time
- Compatibility modes prevent breaking changes
- See: Kafka Schema Registry article

### Enforcement
- **Soft enforcement**: Tests run, failures generate alerts but don't block
- **Hard enforcement**: Tests must pass before data is available to consumers
- Start soft, move to hard as contracts mature
""",
    ),
    KnowledgeArticle(
        id="elt-pipeline-architecture",
        title="Modern ELT Pipeline Architecture",
        category=KnowledgeCategory.ARCHITECTURE,
        tags=["elt", "architecture", "pipeline", "data-stack", "modern", "warehouse"],
        tools=[],
        summary="Reference architecture for modern ELT data pipelines: ingestion, transformation, warehousing, and BI layers.",
        content="""## Modern ELT Pipeline Architecture

### The Modern Data Stack
```
Sources (SaaS, DBs, APIs)
    ↓
Ingestion (Fivetran / Airbyte)
    ↓ raw data
Cloud Warehouse (Snowflake / BigQuery / Redshift)
    ↓
Transformation (dbt)
    ↓ clean, modeled data
BI & Analytics (Looker / Tableau / Metabase)
    ↓
Orchestration (Airflow / Dagster / Prefect) — coordinates everything
```

### Layer Responsibilities

**Ingestion**
- Replicate source data to warehouse with minimal transformation
- Raw data lands in a `raw_*` schema
- Fivetran/Airbyte handle CDC, incremental loads, schema mapping

**Transformation (dbt)**
- `staging` layer: 1:1 with source, light cleanup (renaming, casting)
- `intermediate` layer: business logic building blocks
- `marts` layer: final analytics-ready tables (dims, facts)

**Warehousing**
- Store everything (storage is cheap)
- Compute scales independently
- Partition/cluster for performance

**BI / Analytics**
- Semantic layer (dbt metrics, Looker LookML)
- Self-service analytics for business users
- Dashboard caching for performance

### Key Principles
- **ELT over ETL**: Load raw data first, transform in warehouse (cheapest, most flexible)
- **Version control everything**: dbt code, pipeline configs, dashboard definitions
- **Test at every layer**: Source freshness, staging uniqueness, mart quality
- **Document as you go**: dbt descriptions, column-level documentation
""",
    ),
]
