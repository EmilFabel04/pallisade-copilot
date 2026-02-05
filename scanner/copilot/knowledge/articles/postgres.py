"""PostgreSQL and Redshift knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

POSTGRES_ARTICLES = [
    KnowledgeArticle(
        id="postgres-vacuum-bloat",
        title="PostgreSQL VACUUM and Table Bloat",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["postgres", "vacuum", "bloat", "autovacuum", "dead-tuples", "maintenance"],
        tools=["POSTGRES", "REDSHIFT"],
        summary="How to diagnose and fix PostgreSQL table bloat: VACUUM strategies, autovacuum tuning, and when to use VACUUM FULL.",
        content="""## PostgreSQL VACUUM and Table Bloat

### What Is Bloat?
PostgreSQL's MVCC creates dead tuples on UPDATE/DELETE. VACUUM reclaims this space.
Without regular VACUUM, tables grow indefinitely (bloat).

### Checking for Bloat
```sql
SELECT schemaname, tablename,
       n_dead_tup, n_live_tup,
       ROUND(n_dead_tup::numeric / NULLIF(n_live_tup, 0) * 100, 2) AS dead_pct,
       last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC LIMIT 20;
```

### Autovacuum Tuning
Default settings are conservative. For high-write tables:
```sql
ALTER TABLE my_table SET (
    autovacuum_vacuum_scale_factor = 0.01,  -- Vacuum after 1% dead tuples (default 20%)
    autovacuum_analyze_scale_factor = 0.005  -- Analyze after 0.5% changes
);
```

### VACUUM Types
- `VACUUM` — Reclaims space for reuse but doesn't shrink file on disk
- `VACUUM FULL` — Rewrites entire table, reclaims disk space. **Locks table!**
- `VACUUM ANALYZE` — Vacuum + update query planner statistics

### When to VACUUM FULL
- Only when bloat is extreme (>50% dead tuples)
- Schedule during maintenance window (exclusive lock)
- Alternative: `pg_repack` extension (no lock required)

### Redshift Note
Redshift has automatic VACUUM. Run `ANALYZE` manually after large loads.
""",
    ),
    KnowledgeArticle(
        id="postgres-connection-limits",
        title="PostgreSQL Connection Limit Issues",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["postgres", "connections", "pool", "pgbouncer", "too-many-connections"],
        tools=["POSTGRES"],
        summary="How to fix 'too many connections' errors: connection pooling with PgBouncer, tuning max_connections, and identifying leaks.",
        content="""## PostgreSQL Connection Limit Issues

### "Too many connections" Error
- Default `max_connections = 100`
- Each connection uses ~5-10 MB of RAM
- Common culprits: BI tools holding connections, connection leaks in applications

### Diagnosing
```sql
SELECT count(*) FROM pg_stat_activity;  -- Current connections
SELECT usename, application_name, count(*)
FROM pg_stat_activity GROUP BY 1, 2 ORDER BY 3 DESC;  -- By user/app
SELECT * FROM pg_stat_activity WHERE state = 'idle' AND query_start < now() - interval '10 minutes';  -- Idle connections
```

### Solutions

**1. Connection Pooling (PgBouncer)**
- Sits between app and Postgres, multiplexes connections
- 100 app connections → 10 actual Postgres connections
- Transaction pooling mode: best for most workloads
- Most cloud providers offer built-in pooling

**2. Tune max_connections**
- Increase cautiously: each connection costs memory
- Rule of thumb: `max_connections = 2 * CPU cores * number of connection pools`

**3. Kill Idle Connections**
```sql
-- Set idle timeout
ALTER SYSTEM SET idle_in_transaction_session_timeout = '5min';
-- Or kill specific connections
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle' AND query_start < now() - interval '1 hour';
```
""",
    ),
    KnowledgeArticle(
        id="postgres-indexing",
        title="PostgreSQL Indexing Best Practices",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["postgres", "indexing", "performance", "b-tree", "explain", "slow-queries"],
        tools=["POSTGRES"],
        summary="When and how to add PostgreSQL indexes: B-tree, partial indexes, composite indexes, and using EXPLAIN ANALYZE.",
        content="""## PostgreSQL Indexing Best Practices

### When to Add an Index
- Query filters (WHERE) on a column that doesn't have an index
- JOIN columns without indexes
- ORDER BY on large tables
- Check with `EXPLAIN ANALYZE` — look for "Seq Scan" on large tables

### Index Types
- **B-tree** (default): Best for equality and range queries. Use for most cases.
- **GIN**: Best for full-text search, JSONB, arrays
- **BRIN**: Best for naturally ordered data (timestamps). Very small index size.
- **Hash**: Only for equality comparisons (rarely used)

### Composite Indexes
- Order matters: put the most selective column first
- `CREATE INDEX idx_orders ON orders (customer_id, order_date)` — helps queries filtering on customer_id, or both columns, but NOT order_date alone

### Partial Indexes
- Index only rows matching a condition (smaller, faster)
- `CREATE INDEX idx_active_users ON users (email) WHERE active = true`

### Index Maintenance
- Indexes slow down writes (INSERT/UPDATE/DELETE)
- Don't over-index: check `pg_stat_user_indexes` for unused indexes
- `REINDEX` periodically for heavily-updated indexes (bloat)

### EXPLAIN ANALYZE
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT * FROM orders WHERE customer_id = 123;
```
Look for: Seq Scan (bad on large tables), Index Scan (good), Bitmap Scan (acceptable).
""",
    ),
]
