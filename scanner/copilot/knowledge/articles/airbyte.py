"""Airbyte knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

AIRBYTE_ARTICLES = [
    KnowledgeArticle(
        id="airbyte-sync-failures",
        title="Debugging Airbyte Sync Failures",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["airbyte", "sync", "failure", "debugging", "connection", "normalization"],
        tools=["AIRBYTE"],
        summary="How to debug Airbyte sync failures: connection issues, normalization errors, and schema mismatches.",
        content="""## Debugging Airbyte Sync Failures

### Debugging Workflow
1. Airbyte UI → Connections → Select failed connection
2. Check **Job History** → Click failed sync
3. Read **Logs** — expand source and destination logs separately

### Common Failures

**Source Connection Failed**
- Credentials invalid or expired
- Network/firewall blocking access
- Fix: Test connection in source settings. Check credentials.

**Destination Write Failed**
- Destination full, permissions error, or schema conflict
- Fix: Check destination logs. Verify write permissions.

**Normalization Failed**
- Airbyte's dbt-based normalization hit an error
- Common cause: Column name conflicts, unsupported data types
- Fix: Check normalization logs. Try "Basic normalization" or "Raw (no normalization)"

**Schema Mismatch**
- Source schema changed since last sync
- Fix: Reset connection → "Reset data" (re-syncs from scratch)
- Or: Update schema in connection settings → "Refresh schema"

### Recovery
- **Retry**: Click "Sync now" after fixing the issue
- **Reset**: Connection → Settings → "Reset data" (full re-sync)
- **Partial sync**: Not supported — Airbyte re-syncs entire streams on failure

### Self-Hosted Issues
- **Worker OOM**: Increase worker memory in docker-compose or Kubernetes config
- **Temporal workflow timeout**: Increase `MAX_SYNC_TIMEOUT_DAYS` in .env
""",
    ),
    KnowledgeArticle(
        id="airbyte-connector-development",
        title="Airbyte Custom Connector Development",
        category=KnowledgeCategory.HOW_TO,
        tags=["airbyte", "connector", "cdk", "custom", "development", "api"],
        tools=["AIRBYTE"],
        summary="How to build custom Airbyte connectors using the Connector Development Kit (CDK) for unsupported sources.",
        content="""## Airbyte Custom Connector Development

### When to Build Custom
- Source/destination not in Airbyte catalog
- Need custom transformation during extraction
- Proprietary internal APIs

### Using the CDK (Python)
1. Install: `pip install airbyte-cdk`
2. Generate scaffold: `airbyte-cdk scaffold source my-source`
3. Implement: `check_connection()`, `streams()`, `read_records()`

### Key Concepts
- **Streams**: Each data endpoint (e.g., /users, /orders)
- **Incremental sync**: Implement `cursor_field` and `get_updated_state()`
- **Full refresh**: Simplest — read all records every sync

### Testing
```bash
# Test connection
python main.py check --config config.json
# Discover schema
python main.py discover --config config.json
# Read data
python main.py read --config config.json --catalog catalog.json
```

### Deployment
- Build Docker image: `docker build . -t airbyte/source-my-source:latest`
- Add to Airbyte via Settings → Sources → New connector
""",
    ),
]
