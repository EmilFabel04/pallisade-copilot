"""Dagster knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

DAGSTER_ARTICLES = [
    KnowledgeArticle(
        id="dagster-asset-failures",
        title="Debugging Dagster Asset Failures",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["dagster", "asset", "failure", "debugging", "materialization", "ops"],
        tools=["DAGSTER"],
        summary="How to debug Dagster asset materialization failures: reading logs, run retries, and common error patterns.",
        content="""## Debugging Dagster Asset Failures

### Debugging Workflow
1. Open Dagster UI → Runs → Click failed run
2. Check the **Compute Logs** tab for the failing step
3. Look at the **structured events** for the exact error

### Common Failure Patterns

**MaterializationError**
- Asset function raised an exception
- Check compute logs for the stack trace
- Test locally: `dagster asset materialize --select my_asset`

**Upstream Asset Not Materialized**
- Dependency hasn't been materialized yet
- Fix: Materialize upstream assets first, or use `AutoMaterializePolicy`

**Resource Configuration Error**
- Missing or invalid resource config (DB credentials, API keys)
- Fix: Check `dagster.yaml` or environment variables for the resource

**Partition Failures**
- Specific partitions failed while others succeeded
- Check: Assets → Select asset → Partitions tab → Find failed partition
- Retry: Click the failed partition → Re-materialize

### Recovery
- **Retry run**: Runs → Failed run → "Re-execute from failure"
- **Materialize specific assets**: Assets → Select → Materialize
- **Backfill partitions**: Assets → Select → Backfill → Choose date range
""",
    ),
    KnowledgeArticle(
        id="dagster-best-practices",
        title="Dagster Best Practices",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["dagster", "assets", "resources", "testing", "partitions", "sensors"],
        tools=["DAGSTER"],
        summary="Best practices for Dagster: asset design, resource management, testing, and partition strategies.",
        content="""## Dagster Best Practices

### Asset Design
- One asset = one logical data artifact (table, file, model)
- Use `@asset` decorator for most cases
- Use `@multi_asset` when one computation produces multiple outputs
- Group related assets with `group_name` for UI organization

### Resources
- Define database connections, API clients as Dagster resources
- Resources are injectable, testable, and environment-aware
```python
@asset
def my_table(context, warehouse: SnowflakeResource):
    warehouse.execute("SELECT ...")
```

### Testing
- Use `materialize_to_memory()` for unit tests
- Mock resources for fast, isolated tests
- Integration tests with real resources in CI

### Partitions
- Use `DailyPartitionsDefinition` for time-series data
- `AutoMaterializePolicy.eager()` — materialize as soon as upstream is ready
- Backfills via UI or `dagster asset backfill`

### Sensors
- Use sensors to trigger on external events (file arrival, API webhook)
- Keep sensor evaluation fast (< 30s)
- Use `run_status_sensor` to alert on failures
""",
    ),
]
