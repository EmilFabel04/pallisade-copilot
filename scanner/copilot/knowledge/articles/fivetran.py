"""Fivetran knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

FIVETRAN_ARTICLES = [
    KnowledgeArticle(
        id="fivetran-connector-failures",
        title="Fixing Fivetran Connector Failures",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["fivetran", "connector", "failure", "sync", "credentials", "debugging"],
        tools=["FIVETRAN"],
        summary="Common Fivetran connector failure causes and fixes: credential expiry, API limits, network issues, and schema problems.",
        content="""## Fixing Fivetran Connector Failures

### Common Failure Causes

**Credential Expiry**
- OAuth tokens expired (Google, Salesforce, HubSpot)
- Fix: Re-authenticate in Fivetran UI → Connectors → Setup → Re-authorize
- Prevention: Use service accounts with long-lived tokens where possible

**API Rate Limits**
- Source API throttling Fivetran requests
- Symptom: Sync fails with "429 Too Many Requests" or "rate limit exceeded"
- Fix: Reduce sync frequency, contact source provider for higher limits

**Network / Firewall Issues**
- Fivetran can't reach the source (self-hosted databases)
- Fix: Whitelist Fivetran IPs in firewall. Use SSH tunnel or VPN connector.
- Fivetran IPs: Check dashboard.fivetran.com → Setup → Network settings

**Schema Changes in Source**
- Column dropped or renamed in source system
- Fix: Check Fivetran's schema change notifications. Re-sync affected tables.

### Debugging Workflow
1. Fivetran Dashboard → Connectors → Select failed connector
2. Check **Logs** tab for error details
3. **Test connection** to verify connectivity
4. Check source system status (is the API/DB up?)

### Recovery
- Fix the underlying issue, then click "Sync Now"
- For data gaps: Fivetran auto-backfills missed data on next successful sync
- For corrupted data: Use "Historical Sync" to re-sync from scratch
""",
    ),
    KnowledgeArticle(
        id="fivetran-schema-drift",
        title="Handling Fivetran Schema Changes",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["fivetran", "schema", "drift", "columns", "new-tables", "blocking"],
        tools=["FIVETRAN"],
        summary="How Fivetran handles schema changes and how to manage schema drift: new columns, dropped columns, and type changes.",
        content="""## Handling Fivetran Schema Changes

### How Fivetran Handles Schema Changes
- **New columns**: Automatically added to destination (opt-in per connector)
- **New tables**: Automatically synced if "Allow new tables" is enabled
- **Dropped columns**: Fivetran keeps the column in destination (doesn't delete)
- **Type changes**: Fivetran widens the type (e.g., INT → BIGINT) or converts to STRING

### Schema Management Settings
- Connectors → Schema → "Allow new schemas/tables/columns"
- **Recommended**: Enable for development, review manually in production

### Blocking Schema Changes
If a schema change breaks downstream models:
1. Check Fivetran notifications for what changed
2. Update your dbt models to handle the change
3. If needed, pause the connector until downstream is fixed

### Best Practices
- Use dbt `schema.yml` tests to catch unexpected schema changes
- Set up Fivetran alerts for schema changes (email/Slack)
- Use `dbt_utils.get_column_values` for dynamic handling of changing enum values
- Stage all Fivetran data through a dbt staging layer for schema stability
""",
    ),
    KnowledgeArticle(
        id="fivetran-sync-optimization",
        title="Fivetran Sync Optimization",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["fivetran", "sync", "frequency", "incremental", "performance", "cost"],
        tools=["FIVETRAN"],
        summary="How to optimize Fivetran sync frequency, reduce MAR costs, and configure incremental vs full syncs.",
        content="""## Fivetran Sync Optimization

### Sync Frequency
- **Default**: Every 6 hours for most connectors
- **Reduce for cost savings**: Daily syncs for slowly-changing data (HR, finance)
- **Increase for freshness**: 5-15 min for real-time needs (payments, inventory)
- **Impact on MAR**: Higher frequency = more rows synced = higher cost

### Incremental vs Full Sync
- **Incremental**: Only new/changed rows. Faster, cheaper. Most connectors support this.
- **Full sync**: Entire dataset every time. Use for small tables or when source lacks change tracking.
- Check: Connector docs specify which tables support incremental.

### Reducing MAR (Monthly Active Rows)
- Exclude tables you don't need: Schema tab → Uncheck unused tables
- Exclude columns with PII or large text: Reduces transfer time (not MAR directly)
- Use column hashing for PII compliance

### Performance Tips
- Ensure source database has indexes on cursor columns (updated_at, id)
- For databases: Grant Fivetran user SELECT-only access
- For APIs: Use service accounts with appropriate rate limits
""",
    ),
]
