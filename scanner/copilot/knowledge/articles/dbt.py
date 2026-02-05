"""dbt Cloud and dbt Core knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

DBT_ARTICLES = [
    KnowledgeArticle(
        id="dbt-test-failure-debugging",
        title="Debugging dbt Test Failures",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["dbt", "testing", "debugging", "data-quality", "schema-tests"],
        tools=["DBT_CLOUD", "DBT_CORE"],
        summary="Common causes and fixes for dbt test failures including schema tests, data tests, and freshness checks.",
        content="""## Debugging dbt Test Failures

### Schema Test Failures

**not_null** — Column contains NULL values:
- Investigate: `SELECT * FROM <model> WHERE <column> IS NULL LIMIT 10`
- Fix: Use `COALESCE()` in staging models, or check upstream sources for missing data.

**unique** — Duplicate values found:
- Investigate: `SELECT <column>, COUNT(*) FROM <model> GROUP BY 1 HAVING COUNT(*) > 1`
- Fix: Add `QUALIFY ROW_NUMBER() OVER (PARTITION BY <column> ORDER BY updated_at DESC) = 1` for deduplication.

**accepted_values** — Unexpected values:
- Investigate: `SELECT DISTINCT <column> FROM <model> ORDER BY 1`
- Fix: Update the accepted values list in schema.yml or fix upstream data.

**relationships** — Broken foreign key reference:
- Investigate: `SELECT child.id FROM <child_model> child LEFT JOIN <parent_model> parent ON child.fk = parent.pk WHERE parent.pk IS NULL`
- Fix: Ensure parent table loads before child. Check for deleted parent records.

### Data Test (Custom SQL) Failures
- Check `tests/` directory for the failing SQL file
- Run the test query manually to see which rows fail
- Common causes: race conditions between model refreshes, timezone mismatches, NULL handling

### Freshness Failures
- Source data hasn't been updated within the expected window
- Check upstream ingestion pipeline (Fivetran/Airbyte connector status)
- Investigate: `SELECT MAX(<loaded_at_column>) FROM <source_table>`

### Debugging Workflow
1. Run `dbt test --select <model_name>` to isolate the failure
2. Check `target/run_results.json` for detailed error messages
3. Use `dbt test --select <model_name> --store-failures` to save failing rows
4. Query the `<schema>_dbt_test__audit` schema for stored failures
5. Trace upstream using lineage to find root cause

### dbt Cloud Specific
- Check run logs in dbt Cloud UI for the full stack trace
- Use "Rerun from failure" to retry only failed models
- Set up Slack/email notifications for test failures

### Prevention
- Run tests in CI before merging
- Use `severity: warn` for non-critical tests during development
- Implement `dbt_utils.recency` tests for freshness monitoring
""",
    ),
    KnowledgeArticle(
        id="dbt-incremental-model-issues",
        title="Fixing dbt Incremental Model Issues",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["dbt", "incremental", "materialization", "performance", "data-gaps"],
        tools=["DBT_CLOUD", "DBT_CORE"],
        summary="Common problems with dbt incremental models: data gaps, duplicate rows, full refreshes, and performance tuning.",
        content="""## Fixing dbt Incremental Model Issues

### Data Gaps After Incremental Runs
- **Cause**: The `is_incremental()` filter misses late-arriving data
- **Fix**: Add a lookback window:
  ```sql
  {% if is_incremental() %}
    WHERE updated_at > (SELECT DATEADD(hour, -3, MAX(updated_at)) FROM {{ this }})
  {% endif %}
  ```

### Duplicate Rows
- **Cause**: Missing or incorrect `unique_key` config
- **Fix**: Always set `unique_key` in the model config:
  ```yaml
  {{ config(materialized='incremental', unique_key='id') }}
  ```
- For composite keys: `unique_key=['order_id', 'line_item_id']`

### When to Full Refresh
- Schema changes (new columns, type changes)
- Logic changes that affect historical data
- Data corruption or backfill needs
- Run: `dbt run --select <model> --full-refresh`

### Performance Tuning
- **BigQuery**: Use `partition_by` and `cluster_by` in config
- **Snowflake**: Use `cluster_by` for large tables
- **Merge strategy**: Default merge can be slow on large tables. Consider `delete+insert` strategy:
  ```yaml
  {{ config(materialized='incremental', incremental_strategy='delete+insert', unique_key='date_day') }}
  ```

### on_schema_change Config
- `'ignore'` (default): New columns in source are silently dropped
- `'append_new_columns'`: Adds new columns automatically
- `'sync_all_columns'`: Adds new and removes old columns
- `'fail'`: Fails the run when schema changes detected
""",
    ),
    KnowledgeArticle(
        id="dbt-compilation-errors",
        title="Resolving dbt Compilation Errors",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["dbt", "compilation", "jinja", "ref", "source", "yaml"],
        tools=["DBT_CLOUD", "DBT_CORE"],
        summary="How to fix common dbt compilation errors: ref() failures, Jinja syntax issues, YAML parsing, and dependency cycles.",
        content="""## Resolving dbt Compilation Errors

### ref() / source() Not Found
- **Error**: `Compilation Error: Model 'model.project.stg_orders' not found`
- **Causes**: Typo in model name, model not in project path, model disabled
- **Fix**: Check `dbt_project.yml` model-paths. Verify model file exists. Run `dbt ls` to list all models.

### Jinja Syntax Errors
- **Error**: `Encountered unknown tag 'endfor'` or similar
- **Common mistakes**: Missing `{% endif %}`, wrong block nesting, using `{{ }}` inside `{% %}`
- **Fix**: Use `dbt compile --select <model>` to isolate. Check Jinja block nesting carefully.

### YAML Parsing Errors
- **Error**: `Syntax error: mapping values are not allowed here`
- **Causes**: Incorrect indentation, tabs instead of spaces, missing colons
- **Fix**: Validate YAML with an online linter. Use 2-space indentation consistently.

### Circular Dependencies
- **Error**: `Found a cycle: model.a -> model.b -> model.a`
- **Fix**: Refactor to break the cycle. Extract shared logic into a CTE or intermediate model.

### Macro Not Found
- **Error**: `Macro 'my_macro' not found`
- **Causes**: Macro file not in macro-paths, package not installed
- **Fix**: Check `dbt_project.yml` macro-paths. Run `dbt deps` if using packages.
""",
    ),
    KnowledgeArticle(
        id="dbt-project-structure",
        title="dbt Project Structure Best Practices",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["dbt", "project-structure", "naming", "staging", "marts", "intermediate"],
        tools=["DBT_CLOUD", "DBT_CORE"],
        summary="Recommended dbt project structure with staging, intermediate, and marts layers, plus naming conventions.",
        content="""## dbt Project Structure Best Practices

### Recommended Layer Structure
```
models/
  staging/          # 1:1 with source tables, light transformations
    stg_stripe__payments.sql
    stg_shopify__orders.sql
  intermediate/     # Business logic building blocks
    int_orders__pivoted.sql
    int_payments__aggregated.sql
  marts/            # Final business entities
    core/
      dim_customers.sql
      fct_orders.sql
    marketing/
      fct_ad_spend.sql
```

### Naming Conventions
- **Staging**: `stg_<source>__<table>` (e.g., `stg_stripe__payments`)
- **Intermediate**: `int_<entity>__<verb>` (e.g., `int_orders__pivoted`)
- **Marts**: `dim_<entity>` for dimensions, `fct_<entity>` for facts

### Materialization by Layer
- **Staging**: `view` (lightweight, always fresh)
- **Intermediate**: `ephemeral` or `view` (no warehouse storage cost)
- **Marts**: `table` or `incremental` (fast for BI queries)

### Testing Strategy
- **Staging**: `not_null`, `unique` on primary keys, `accepted_values` on status columns
- **Intermediate**: `not_null` on join keys
- **Marts**: Full test coverage — `unique`, `not_null`, `relationships`, custom data tests

### Key Principles
- Source data should only be referenced once (in staging)
- Business logic belongs in intermediate/marts, not staging
- Use `{{ ref() }}` everywhere — never hardcode table names
- One model per file, file name matches model name
""",
    ),
    KnowledgeArticle(
        id="dbt-ci-cd-setup",
        title="Setting Up CI/CD for dbt",
        category=KnowledgeCategory.HOW_TO,
        tags=["dbt", "ci-cd", "github-actions", "pull-request", "slim-ci"],
        tools=["DBT_CLOUD", "DBT_CORE"],
        summary="How to set up CI/CD for dbt projects using dbt Cloud CI jobs or GitHub Actions with slim CI.",
        content="""## Setting Up CI/CD for dbt

### dbt Cloud CI Jobs
1. Create a CI job in dbt Cloud → Jobs → New Job
2. Set trigger to "Pull Request"
3. Enable "Defer to production" for slim CI (only builds modified models)
4. Commands: `dbt build --select state:modified+`
5. Set up GitHub/GitLab webhook for automatic triggers

### GitHub Actions (dbt Core)
```yaml
name: dbt CI
on: [pull_request]
jobs:
  dbt-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install dbt-<adapter>
      - run: dbt deps
      - run: dbt build --select state:modified+ --defer --state ./prod-manifest/
```

### Slim CI Pattern
- Compare current branch against production manifest
- Only build and test modified models and their downstream dependents
- `dbt build --select state:modified+` — the `+` includes downstream
- Store production `manifest.json` as artifact between runs

### What to Run in CI
1. `dbt deps` — install packages
2. `dbt compile` — catch compilation errors early
3. `dbt build --select state:modified+` — build and test modified models
4. Optional: `dbt source freshness` — check source freshness
""",
    ),
]
