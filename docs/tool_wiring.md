# Tool Wiring — IntegrationDriver Contract

## Overview

Every tool integration in Pallisade implements the `IntegrationDriver` interface defined in `scanner/drivers/base.py`. This provides a unified contract across all 8 surfaces: Integrations, Sources, Lineage, Copilot, Tasks/Monitors, Notifications, Contracts, and Icons.

## IntegrationDriver Contract

```python
class IntegrationDriver(ABC):
    # Identity
    def id() -> str                           # "bigquery"
    def integration_type() -> str             # "BIGQUERY"
    def layer() -> IntegrationLayer           # WAREHOUSE
    def graph_domain() -> GraphDomain         # DATA_PLANE | CONTROL_PLANE | NONE

    # Lifecycle
    def validate_config(config) -> ConfigValidation
    def test_connection(config) -> ConnectionResult
    def capabilities() -> DriverCapabilities

    # Extraction (DATA_PLANE only)
    def extract_metadata(config) -> List[AssetSummary]
    def extract_lineage(config) -> Tuple[List[nodes], List[edges]]  # GUARDED
    def _extract_lineage_impl(config) -> ...  # Override in DATA_PLANE drivers

    # Operational
    def fetch_logs(config, limit) -> List[LogEntry]
    def health_check(config) -> ConnectionResult

    # Metadata
    def events_emitted() -> List[str]
    def contract_schema() -> Optional[Dict]
    def ui_config_schema() -> Optional[Dict]
    def recommended_monitors() -> List[str]
```

## Graph Domain Rules

| Domain | Creates Lineage? | Surfaces |
|--------|-----------------|----------|
| `DATA_PLANE` | Yes — nodes + edges in lineage graph | All 8 surfaces |
| `CONTROL_PLANE` | **No** — `extract_lineage()` always returns `([], [])` | Integrations, Sources, Copilot, Tasks, Notifications, Contracts, Icons |
| `NONE` | No | Integrations only |

**Enforcement**: `extract_lineage()` is a guarded method in the base class. It checks `graph_domain()` before delegating to `_extract_lineage_impl()`. CONTROL_PLANE drivers cannot bypass this guard.

## Domain Assignments

### DATA_PLANE (29 tools)
- **Warehouses**: bigquery, snowflake, postgres, redshift, databricks, sqlserver, azure_sql, azure_synapse, mysql
- **Ingestion**: fivetran, airbyte, stitch
- **Transformation**: dbt_cloud, dbt_core
- **Orchestration**: airflow, dagster, prefect, n8n
- **Reporting/BI**: looker, tableau, metabase, powerbi
- **Observability**: monte_carlo, bigeye, soda, elementary
- **Storage**: amazon_s3, gcs, adls

### CONTROL_PLANE (13 tools)
- **Version Control**: github, github_issues, gitlab, bitbucket
- **Notifications**: slack, teams, pagerduty, opsgenie
- **Project Management**: jira, linear, asana
- **Infrastructure**: linux_server
- **Other**: custom_webhook

## Lineage Support Levels (DATA_PLANE only)

| Level | Description | Example |
|-------|-------------|---------|
| 0 | Integration node only (no assets) | Most scaffolds |
| 1 | Tool → asset nodes (tables/connectors/dashboards) | Fivetran connectors |
| 2 | Asset → asset edges (dependencies) | dbt model lineage, BQ query lineage |
| 3 | Column-level lineage | dbt column lineage (where available) |

## Registry

```python
from scanner.drivers import DriverRegistry

DriverRegistry.list_supported()       # All 42 types
DriverRegistry.list_data_plane()      # 29 DATA_PLANE types
DriverRegistry.list_control_plane()   # 13 CONTROL_PLANE types
DriverRegistry.get("BIGQUERY")        # -> BigQueryDriver class
DriverRegistry.create("BIGQUERY")     # -> BigQueryDriver instance
DriverRegistry.get_support_matrix()   # Full table for docs
```

## Required Fields per Layer

| Layer | Required Config Fields |
|-------|----------------------|
| Warehouse | host/project_id, credentials, database |
| Ingestion | api_key, api_secret |
| Transformation | api_token, account_id (cloud) or manifest (core) |
| Orchestration | base_url, username/password |
| Reporting | base_url or server, client_id/secret or token |
| Observability | api_key |
| Storage | bucket/container, credentials |
| VCS | token/access_token |
| Notifications | bot_token/webhook_url or routing_key |
| Ticketing | base_url, email, api_token |
| Infrastructure | host, username |

## How to Add a New Tool Integration

1. **Create the driver file** in `scanner/drivers/<category>/<tool>_driver.py`
2. **Implement `IntegrationDriver`** — all abstract methods (id, integration_type, layer, graph_domain, validate_config, test_connection, capabilities)
3. **Set graph_domain correctly** — DATA_PLANE if it produces data assets/lineage; CONTROL_PLANE otherwise
4. **Register in `scanner/drivers/loader.py`** — add the import + `DriverRegistry.register()`
5. **Add icon** in `components/icons/ToolIcon.tsx` (SVG or fallback)
6. **Add to GRAPH_DOMAIN_MAP** in `components/pipeline/types.ts`
7. **Add config fields** to the TOOLS constant in `components/pipeline/types.ts`
8. **(DATA_PLANE only)** Override `_extract_lineage_impl()` and optionally `extract_metadata()`
9. **Add copilot tools** if the tool supports actions (create ticket, send alert, etc.)
10. **Write tests** in `scanner/tests/drivers/`

## Support Matrix

| Tool | Integrations | Sources | Lineage | Copilot | Tasks | Notifications | Contracts | Icons |
|------|:-----------:|:-------:|:-------:|:-------:|:-----:|:------------:|:---------:|:-----:|
| bigquery | FULL | FULL | L2 | FULL | FULL | FULL | FULL | ✓ |
| snowflake | FULL | FULL | L2 | FULL | FULL | FULL | FULL | ✓ |
| dbt_cloud | FULL | FULL | L2 | FULL | FULL | FULL | FULL | ✓ |
| airflow | FULL | FULL | L2 | FULL | FULL | FULL | FULL | ✓ |
| fivetran | FULL | FULL | L2 | FULL | FULL | FULL | FULL | ✓ |
| postgres | scaffold | scaffold | L0 | basic | rec | events | schema | ✓ |
| redshift | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| databricks | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| sqlserver | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| azure_sql | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| azure_synapse | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| mysql | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| airbyte | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| stitch | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| dbt_core | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| dagster | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| prefect | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| n8n | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| looker | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| tableau | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| metabase | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| powerbi | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| monte_carlo | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| bigeye | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| soda | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| elementary | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| amazon_s3 | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| gcs | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| adls | scaffold | scaffold | L0 | basic | rec | events | — | ✓ |
| github | scaffold | scaffold | — | write | — | events | — | ✓ |
| github_issues | scaffold | scaffold | — | write | — | events | — | ✓ |
| gitlab | scaffold | scaffold | — | write | — | events | — | ✓ |
| bitbucket | scaffold | scaffold | — | write | — | events | — | ✓ |
| slack | scaffold | scaffold | — | write | — | events | — | ✓ |
| teams | scaffold | scaffold | — | write | — | events | — | ✓ |
| pagerduty | scaffold | scaffold | — | write | — | events | — | ✓ |
| opsgenie | scaffold | scaffold | — | write | — | events | — | ✓ |
| jira | scaffold | scaffold | — | write | — | events | — | ✓ |
| linear | scaffold | scaffold | — | write | — | events | — | ✓ |
| asana | scaffold | scaffold | — | write | — | events | — | ✓ |
| linux_server | scaffold | scaffold | — | basic | — | events | — | ✓ |
| custom_webhook | scaffold | scaffold | — | write | — | events | — | ✓ |

**Legend**: FULL = fully implemented, scaffold = metadata + config validation + TODOs, L0-L3 = lineage level, rec = recommended monitors defined, events = events_emitted defined, write = can_write capability, — = not applicable

## Testing Runbook

### 1. Unit tests
```bash
cd scanner && python -m pytest tests/drivers/ -v
```

### 2. API smoke test
```bash
# Start FastAPI server
uvicorn scanner.api.app:app --reload

# Verify all drivers loaded
curl http://localhost:8000/api/v1/drivers | python -m json.tool

# Check specific driver
curl http://localhost:8000/api/v1/drivers/BIGQUERY
curl http://localhost:8000/api/v1/drivers/BIGQUERY/capabilities
curl http://localhost:8000/api/v1/drivers/SLACK  # should be CONTROL_PLANE
```

### 3. Graph domain enforcement
```bash
# Verify CONTROL_PLANE tools return empty lineage
python -c "
from scanner.drivers.loader import register_all_drivers
from scanner.drivers.registry import DriverRegistry
register_all_drivers()
driver = DriverRegistry.create('SLACK')
nodes, edges = driver.extract_lineage({})
assert nodes == [] and edges == [], 'CONTROL_PLANE must return empty lineage'
print('OK: CONTROL_PLANE guard works')
"
```

### 4. Frontend verification
1. Open Sources page → verify "Data / Control / All" domain toggle appears
2. Open Lineage page → verify domain toggle in filter bar
3. Connect a CONTROL_PLANE tool (Slack) → verify it does NOT appear in data lineage view
