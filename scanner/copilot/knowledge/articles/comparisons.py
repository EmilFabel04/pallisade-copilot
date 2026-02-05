"""Cross-tool comparison articles."""

from .. import KnowledgeArticle, KnowledgeCategory

COMPARISON_ARTICLES = [
    KnowledgeArticle(
        id="snowflake-vs-bigquery",
        title="Snowflake vs BigQuery Comparison",
        category=KnowledgeCategory.COMPARISON,
        tags=["snowflake", "bigquery", "warehouse", "comparison", "migration", "differences"],
        tools=["SNOWFLAKE", "BIGQUERY"],
        summary="Key differences between Snowflake and BigQuery: pricing, architecture, SQL syntax, performance, and when to use each.",
        content="""## Snowflake vs BigQuery

### Architecture
| Aspect | Snowflake | BigQuery |
|--------|-----------|----------|
| Compute model | Virtual warehouses (you size them) | Serverless slots (auto-scaled) |
| Storage | Micro-partitions, auto-compressed | Columnar Capacitor format |
| Pricing | Credits (compute) + storage | Per-TB scanned or slot reservations |
| Concurrency | Multi-cluster warehouses | Automatic, slots-based |
| Caching | Result cache (24h) + local disk cache | Result cache + BI Engine |

### SQL Syntax Differences
| Feature | Snowflake | BigQuery |
|---------|-----------|----------|
| Quoting | `"DATABASE"."SCHEMA"."TABLE"` | `` `project.dataset.table` `` |
| Case sensitivity | Case-insensitive (uppercase stored) | Case-insensitive columns, case-sensitive strings |
| Date functions | `DATEADD(day, 7, col)` | `DATE_ADD(col, INTERVAL 7 DAY)` |
| Merge | Standard MERGE | Standard MERGE |
| Array handling | `ARRAY_AGG()`, `FLATTEN()` | `ARRAY_AGG()`, `UNNEST()` |
| Semi-structured | VARIANT type, `:` accessor | STRUCT/ARRAY types, `.` accessor |
| QUALIFY | Native support | Native support |
| Regex | `REGEXP_LIKE()` | `REGEXP_CONTAINS()` |

### Cost Comparison
- **Snowflake**: Predictable per-warehouse costs. Easy to budget. Credits consumed only when warehouse is running.
- **BigQuery**: On-demand is pay-per-query (great for sporadic use). Editions better for heavy use.
- **Break-even**: BigQuery on-demand cheaper < 5TB/day scanning. Snowflake cheaper for sustained high-concurrency.

### When to Choose
- **Snowflake**: Multi-cloud flexibility, heavy ETL workloads, need fine-grained compute control, strong SQL ecosystem
- **BigQuery**: GCP-native, serverless simplicity, ML integration (BigQuery ML), cost-effective for variable workloads

### Migration Tips
- Snowflake → BigQuery: Convert VARIANT to STRUCT/ARRAY. Replace `DATEADD` with `DATE_ADD`. Use backticks.
- BigQuery → Snowflake: Convert STRUCT to VARIANT. Replace `UNNEST` with `FLATTEN`. Use uppercase identifiers.
""",
    ),
    KnowledgeArticle(
        id="airflow-vs-dagster",
        title="Airflow vs Dagster Comparison",
        category=KnowledgeCategory.COMPARISON,
        tags=["airflow", "dagster", "orchestration", "comparison", "dags", "assets"],
        tools=["AIRFLOW", "DAGSTER"],
        summary="Key differences between Airflow and Dagster: DAGs vs assets, testing, development experience, and when to use each.",
        content="""## Airflow vs Dagster

### Core Philosophy
| Aspect | Airflow | Dagster |
|--------|---------|---------|
| Paradigm | Task-based (DAGs) | Asset-based (Software-Defined Assets) |
| Focus | "When do things run?" | "What data exists?" |
| Testing | Limited built-in testing | First-class testing framework |
| Local dev | Requires Airflow instance | `dagster dev` runs locally easily |
| UI | Mature, widely-used | Modern, asset-focused |

### Key Differences
- **Airflow**: Define tasks and their order. Great for workflow orchestration.
- **Dagster**: Define data assets and their dependencies. Great for data pipelines.

### Development Experience
- **Airflow**: Write DAG files, deploy to scheduler, check UI for results. Testing requires running tasks.
- **Dagster**: Write assets with type annotations, test locally with `materialize_to_memory()`, rich IDE support.

### When to Choose
- **Airflow**: Large existing investment, diverse task types (API calls, file moves, not just data), mature ecosystem with 1000+ operators
- **Dagster**: Greenfield data platform, want strong testing/typing, asset-centric thinking, data lineage built-in

### Can They Coexist?
Yes. Dagster can orchestrate Airflow DAGs via the `dagster-airflow` integration. Common migration pattern: keep existing Airflow DAGs, build new pipelines in Dagster.
""",
    ),
    KnowledgeArticle(
        id="fivetran-vs-airbyte",
        title="Fivetran vs Airbyte Comparison",
        category=KnowledgeCategory.COMPARISON,
        tags=["fivetran", "airbyte", "ingestion", "etl", "comparison", "connectors"],
        tools=["FIVETRAN", "AIRBYTE"],
        summary="Key differences between Fivetran and Airbyte: pricing, connectors, deployment, and when to use each.",
        content="""## Fivetran vs Airbyte

### Overview
| Aspect | Fivetran | Airbyte |
|--------|----------|---------|
| Deployment | Fully managed SaaS | Self-hosted or Cloud |
| Pricing | Per monthly active row (MAR) | Free (self-hosted) or per credit |
| Connectors | 300+ fully managed | 350+ (community + certified) |
| Reliability | Enterprise-grade, 99.9% SLA | Varies by connector maturity |
| Schema handling | Auto-propagates changes | Configurable normalization |

### Pricing
- **Fivetran**: Starts ~$1/month per connector (free tier). Enterprise pricing based on MAR.
- **Airbyte Cloud**: Per sync credit (~$1-5/connector/month for small volumes)
- **Airbyte Self-Hosted**: Free, but you manage infrastructure

### Connector Quality
- **Fivetran**: All connectors managed by Fivetran. Consistent quality, guaranteed SLAs.
- **Airbyte**: Mix of Airbyte-maintained and community. Certified connectors are reliable, community ones vary.

### When to Choose
- **Fivetran**: Want zero maintenance, enterprise support, compliance requirements, budget for SaaS
- **Airbyte**: Want cost control (self-host), need custom connectors (CDK), open-source preference

### Schema Drift Handling
- **Fivetran**: Automatically adds new columns, never drops. Notifies on changes.
- **Airbyte**: Configurable — can auto-propagate, ignore, or fail on schema changes.
""",
    ),
    KnowledgeArticle(
        id="dbt-cloud-vs-core",
        title="dbt Cloud vs dbt Core",
        category=KnowledgeCategory.COMPARISON,
        tags=["dbt", "dbt-cloud", "dbt-core", "comparison", "hosting", "pricing"],
        tools=["DBT_CLOUD", "DBT_CORE"],
        summary="Key differences between dbt Cloud and dbt Core: features, pricing, CI/CD, and when to use each.",
        content="""## dbt Cloud vs dbt Core

### Feature Comparison
| Feature | dbt Core (OSS) | dbt Cloud |
|---------|---------------|-----------|
| Price | Free | $100+/month per seat |
| Hosting | Self-managed | Fully managed |
| Scheduler | Need Airflow/cron/etc | Built-in scheduler |
| CI/CD | DIY (GitHub Actions) | Built-in CI jobs |
| IDE | VS Code + extension | Web-based Cloud IDE |
| Discovery API | No | Yes (metadata, lineage) |
| Semantic Layer | No | Yes (metrics, dimensions) |
| Admin controls | DIY | Role-based access, audit logs |

### When to Choose dbt Core
- Small team, budget-conscious
- Already have orchestrator (Airflow, Dagster)
- Want full control over infrastructure
- Comfortable with CLI and git workflows

### When to Choose dbt Cloud
- Want managed scheduling and CI out-of-box
- Need the Semantic Layer for BI tools
- Want Discovery API for metadata/lineage
- Enterprise compliance requirements (SOC 2, SSO)
- Team needs web IDE for less technical users

### Hybrid Approach
- Use dbt Core locally for development
- Use dbt Cloud for scheduling, CI, and production runs
- Both use the same project code and git repo
""",
    ),
]
