"""Snowflake knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

SNOWFLAKE_ARTICLES = [
    KnowledgeArticle(
        id="snowflake-query-performance",
        title="Snowflake Query Performance Optimization",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["snowflake", "performance", "query", "slow", "optimization", "clustering"],
        tools=["SNOWFLAKE"],
        summary="How to diagnose and fix slow Snowflake queries: clustering, warehouse sizing, pruning, and query profiling.",
        content="""## Snowflake Query Performance Optimization

### Diagnosing Slow Queries
1. Check Query Profile in Snowflake UI (or `QUERY_HISTORY` view)
2. Look for: bytes scanned, partitions scanned vs total, spillage to local/remote storage
3. Key metric: **partition pruning ratio** — if scanning >50% of partitions, clustering may help

### Clustering Keys
- Add clustering on columns used in WHERE/JOIN clauses
- Best for tables > 1TB with predictable filter patterns
- `ALTER TABLE <table> CLUSTER BY (<column1>, <column2>)`
- Check effectiveness: `SELECT SYSTEM$CLUSTERING_INFORMATION('<table>')`
- Snowflake auto-reclusters in background (costs credits)

### Warehouse Sizing
| Size | Credits/hr | Best For |
|------|-----------|----------|
| X-Small | 1 | Simple queries, development |
| Small | 2 | Light dashboards |
| Medium | 4 | Most analytics workloads |
| Large | 8 | Complex joins, large scans |
| X-Large+ | 16+ | Heavy ETL, large aggregations |

- **Auto-suspend**: Set to 60s for dev, 300s for production
- **Auto-resume**: Always enabled
- **Multi-cluster**: Enable for concurrent dashboard loads

### Common Performance Fixes
- **Avoid SELECT ***: Only select needed columns (columnar storage benefits)
- **Use LIMIT during dev**: Add `LIMIT 1000` while iterating
- **Avoid functions on filter columns**: `WHERE DATE(created_at) = '2024-01-01'` is slower than `WHERE created_at >= '2024-01-01' AND created_at < '2024-01-02'`
- **Materialize CTEs**: If a CTE is referenced multiple times, create it as a temp table
- **Use COPY INTO for loads**: Faster than INSERT INTO ... SELECT

### Query Profile Red Flags
- **Spillage**: Query ran out of memory. Upsize warehouse.
- **Exploding joins**: Join produces more rows than expected. Check join keys.
- **Full table scans**: No partition pruning. Add clustering or improve WHERE clause.
""",
    ),
    KnowledgeArticle(
        id="snowflake-warehouse-sizing",
        title="Snowflake Warehouse Sizing Guide",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["snowflake", "warehouse", "sizing", "cost", "credits", "concurrency"],
        tools=["SNOWFLAKE"],
        summary="How to choose the right Snowflake warehouse size and configure auto-suspend, multi-cluster, and scaling policies.",
        content="""## Snowflake Warehouse Sizing Guide

### Sizing Principles
- Start small (X-Small or Small), scale up only when queries are slow
- Larger warehouses don't help with more concurrent queries — use multi-cluster instead
- Doubling warehouse size roughly halves query time but doubles cost

### Recommended Setup
- **Dev/Analytics**: X-Small, auto-suspend 60s
- **dbt runs**: Medium or Large (depends on model complexity), auto-suspend 60s
- **BI dashboards**: Small with multi-cluster (min 1, max 3), auto-suspend 300s
- **ETL/ELT loads**: Large, auto-suspend 60s, dedicated warehouse

### Multi-Cluster Configuration
- **Standard scaling**: Add clusters when queries queue. Best for BI.
- **Economy scaling**: Add clusters only when enough queries queue to keep busy. Best for cost control.
- Set `MIN_CLUSTER_COUNT = 1`, `MAX_CLUSTER_COUNT = 3` for typical BI workloads

### Cost Monitoring
- `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY` — credits consumed per warehouse
- `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` — identify expensive queries
- Set resource monitors: `CREATE RESOURCE MONITOR <name> WITH CREDIT_QUOTA = <n>`

### Common Mistakes
- Running dbt on the same warehouse as dashboards (contention)
- Auto-suspend too high (wasting credits while idle)
- Using X-Large for simple queries (same speed as X-Small, 16x cost)
""",
    ),
    KnowledgeArticle(
        id="snowflake-time-travel-cloning",
        title="Snowflake Time Travel and Zero-Copy Cloning",
        category=KnowledgeCategory.HOW_TO,
        tags=["snowflake", "time-travel", "clone", "undo", "recovery", "data-loss"],
        tools=["SNOWFLAKE"],
        summary="How to use Snowflake Time Travel to recover data and zero-copy cloning for safe development.",
        content="""## Snowflake Time Travel and Zero-Copy Cloning

### Time Travel — Recovering Data
- Query data as it existed at a past point in time (up to 90 days on Enterprise)
- **Undo accidental deletes**:
  ```sql
  INSERT INTO my_table SELECT * FROM my_table AT(OFFSET => -3600);  -- 1 hour ago
  ```
- **Undo accidental updates**:
  ```sql
  CREATE TABLE my_table_backup CLONE my_table AT(TIMESTAMP => '2024-01-15 10:00:00'::timestamp);
  ```
- **Undo DROP TABLE**: `UNDROP TABLE my_table;`

### Time Travel Retention
| Edition | Default | Max |
|---------|---------|-----|
| Standard | 1 day | 1 day |
| Enterprise | 1 day | 90 days |

- Set per table: `ALTER TABLE my_table SET DATA_RETENTION_TIME_IN_DAYS = 30`

### Zero-Copy Cloning
- Create instant copy of a table/schema/database with no additional storage cost
- **Dev environment**: `CREATE DATABASE dev_db CLONE prod_db;`
- **Safe testing**: Clone before running destructive operations
- Storage only grows for changed data (copy-on-write)

### Best Practices
- Clone production to dev weekly for realistic testing
- Set higher retention on critical tables (30-90 days)
- Use Time Travel queries for auditing: compare current vs historical data
""",
    ),
    KnowledgeArticle(
        id="snowflake-rbac-setup",
        title="Snowflake Role-Based Access Control",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["snowflake", "rbac", "roles", "security", "access-control", "governance"],
        tools=["SNOWFLAKE"],
        summary="Best practices for Snowflake RBAC: role hierarchy, functional roles, and least-privilege access patterns.",
        content="""## Snowflake RBAC Best Practices

### Recommended Role Hierarchy
```
ACCOUNTADMIN
  └── SYSADMIN
        ├── TRANSFORM_ROLE    (dbt, ETL writers)
        ├── ANALYTICS_ROLE    (BI tools, analysts — read-only)
        └── LOADER_ROLE       (Fivetran, Airbyte — write raw data)
  └── SECURITYADMIN
        └── Manages role grants
```

### Key Principles
- Never use ACCOUNTADMIN for daily work
- Create functional roles (TRANSFORM_ROLE, ANALYTICS_ROLE) not personal roles
- Grant roles to roles, then roles to users
- Separate read and write access

### Setup Commands
```sql
-- Create roles
CREATE ROLE TRANSFORM_ROLE;
CREATE ROLE ANALYTICS_ROLE;
CREATE ROLE LOADER_ROLE;

-- Grant hierarchy
GRANT ROLE TRANSFORM_ROLE TO ROLE SYSADMIN;
GRANT ROLE ANALYTICS_ROLE TO ROLE SYSADMIN;

-- Grant warehouse access
GRANT USAGE ON WAREHOUSE TRANSFORM_WH TO ROLE TRANSFORM_ROLE;
GRANT USAGE ON WAREHOUSE ANALYTICS_WH TO ROLE ANALYTICS_ROLE;

-- Grant database access
GRANT USAGE ON DATABASE ANALYTICS TO ROLE ANALYTICS_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA ANALYTICS.MARTS TO ROLE ANALYTICS_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ANALYTICS.MARTS TO ROLE ANALYTICS_ROLE;
```
""",
    ),
]
