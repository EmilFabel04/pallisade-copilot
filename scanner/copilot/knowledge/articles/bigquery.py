"""BigQuery knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

BIGQUERY_ARTICLES = [
    KnowledgeArticle(
        id="bigquery-cost-optimization",
        title="BigQuery Cost Optimization",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["bigquery", "cost", "optimization", "billing", "slots", "on-demand"],
        tools=["BIGQUERY"],
        summary="How to reduce BigQuery costs: partitioning, clustering, slot reservations, and query best practices.",
        content="""## BigQuery Cost Optimization

### Pricing Models
- **On-demand**: $6.25/TB scanned. Best for unpredictable workloads.
- **Capacity (Editions)**: $0.04-0.06/slot-hour. Best for heavy, predictable workloads.
- **Free tier**: 1 TB/month of queries, 10 GB/month of storage

### Reduce Data Scanned
- **Partition tables** by date: `PARTITION BY DATE(created_at)` — only scan relevant partitions
- **Cluster tables** by frequently filtered columns: `CLUSTER BY customer_id, product_id`
- **Avoid SELECT ***: BigQuery is columnar — only select columns you need
- **Use preview** instead of queries for quick data checks
- **Materialize intermediate results**: Create tables for reused subqueries

### Monitoring Costs
- `INFORMATION_SCHEMA.JOBS` — see bytes billed per query
- `INFORMATION_SCHEMA.TABLE_STORAGE` — storage costs per table
- Set up **custom cost controls**: project-level and user-level quotas
- BigQuery BI Engine caches frequent queries ($0 additional scans)

### Common Expensive Patterns
- `SELECT *` on large tables: Only select needed columns
- Missing partition filter: Always filter on partition column
- Cross-join or UNNEST without limits: Can explode data volume
- Frequent full table scans from BI tools: Use materialized views

### Slot Reservations (Editions)
- **Autoscale**: Set baseline + max slots, pay for actual usage
- Best for: teams with 3+ analysts running regular queries
- Break-even: ~5-10 TB/day of scanning
""",
    ),
    KnowledgeArticle(
        id="bigquery-partitioning-clustering",
        title="BigQuery Partitioning and Clustering Guide",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["bigquery", "partitioning", "clustering", "performance", "optimization"],
        tools=["BIGQUERY"],
        summary="When and how to use BigQuery partitioning and clustering for performance and cost reduction.",
        content="""## BigQuery Partitioning and Clustering

### Partitioning
Divides a table into segments by a column value. BigQuery only scans relevant partitions.

**Types**:
- **Time-unit** (most common): `PARTITION BY DATE(created_at)` — daily, monthly, yearly
- **Integer range**: `PARTITION BY RANGE_BUCKET(user_id, GENERATE_ARRAY(0, 1000000, 1000))`
- **Ingestion time**: `PARTITION BY _PARTITIONDATE` — automatic based on load time

**When to partition**:
- Table > 1 GB
- Queries consistently filter on a date/time column
- Need to expire old data (partition expiration)

**Limits**: Max 4,000 partitions per table

### Clustering
Sorts data within partitions by specified columns. Improves filter and join performance.

```sql
CREATE TABLE `project.dataset.orders`
PARTITION BY DATE(order_date)
CLUSTER BY customer_id, product_category
AS SELECT * FROM ...
```

**When to cluster**:
- Queries filter or aggregate on specific columns
- Columns have high cardinality (many distinct values)
- Up to 4 clustering columns

### Partition + Clustering Together
- Partition by date (coarse filter)
- Cluster by high-cardinality filter columns (fine filter)
- Example: Partition by `order_date`, cluster by `customer_id, region`

### dbt Config
```yaml
{{ config(
    materialized='incremental',
    partition_by={'field': 'order_date', 'data_type': 'date'},
    cluster_by=['customer_id', 'product_category']
) }}
```
""",
    ),
    KnowledgeArticle(
        id="bigquery-common-errors",
        title="Common BigQuery Query Errors",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["bigquery", "errors", "syntax", "quota", "permissions", "debugging"],
        tools=["BIGQUERY"],
        summary="How to fix common BigQuery errors: quota exceeded, column not found, permission denied, and syntax issues.",
        content="""## Common BigQuery Query Errors

### "Quota exceeded" / "Resources exceeded"
- **Cause**: Query too complex or scans too much data
- **Fix**: Add partition filters, reduce data scanned, break into smaller queries
- **For slots**: Increase reservation or switch to on-demand

### "Not found: Table/Dataset"
- **Cause**: Wrong project, dataset, or table name
- **Fix**: Use fully qualified names: `project.dataset.table`
- Check: `SELECT * FROM `project.dataset.INFORMATION_SCHEMA.TABLES``

### "Column not found"
- **Cause**: Column name misspelled or doesn't exist
- **Fix**: Check exact column names: `SELECT column_name FROM `project.dataset.INFORMATION_SCHEMA.COLUMNS` WHERE table_name = 'my_table'`
- BigQuery is case-insensitive for column names but case-sensitive for string values

### "Access Denied"
- **Cause**: Missing IAM permissions
- **Required roles**: `roles/bigquery.dataViewer` (read), `roles/bigquery.dataEditor` (write), `roles/bigquery.jobUser` (run queries)
- **Fix**: Grant role at project or dataset level in IAM

### "Syntax error"
- **Common**: Missing backticks around project.dataset.table names
- **Correct**: `SELECT * FROM `my-project.my_dataset.my_table``
- **Note**: Project names with hyphens MUST use backticks

### "UPDATE/DELETE requires a WHERE clause with partition filter"
- **Cause**: DML on partitioned tables requires partition filter for safety
- **Fix**: Add `WHERE _PARTITIONDATE = '2024-01-15'` or relevant partition filter
""",
    ),
    KnowledgeArticle(
        id="bigquery-streaming-inserts",
        title="BigQuery Data Loading Best Practices",
        category=KnowledgeCategory.HOW_TO,
        tags=["bigquery", "loading", "streaming", "batch", "storage-write-api"],
        tools=["BIGQUERY"],
        summary="Best practices for loading data into BigQuery: batch loads vs streaming inserts vs Storage Write API.",
        content="""## BigQuery Data Loading Best Practices

### Loading Methods Comparison
| Method | Latency | Cost | Best For |
|--------|---------|------|----------|
| Batch load (LOAD/COPY) | Minutes | Free | Bulk ETL, daily loads |
| Storage Write API | Seconds | $0.025/200MB | Near-real-time, high throughput |
| Legacy Streaming | Seconds | $0.05/GB | Simple streaming (deprecated) |
| Federated queries | Real-time | Per query | Ad-hoc external data |

### Batch Loading Best Practices
- Use **Parquet or Avro** format (columnar, compressed, schema-aware)
- Load from GCS for best performance: `bq load --source_format=PARQUET`
- Partition target table to enable efficient appends
- Use `WRITE_TRUNCATE` for full refresh, `WRITE_APPEND` for incremental

### Storage Write API
- Preferred over legacy streaming API (cheaper, exactly-once semantics)
- Supports committed and pending write modes
- Use for Fivetran/Airbyte connectors and real-time pipelines

### Common Mistakes
- Loading many small files: Batch into larger files (>100MB each)
- Not using partition decorators: Load directly into partitions for efficiency
- Streaming to clustered tables: Clustering only applies after data settles
""",
    ),
]
