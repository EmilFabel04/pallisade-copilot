# MAAS — Multi-Agent Architecture System

Orchestration layer that delegates narrow tasks to RunPod-hosted specialist models,
verifies their output deterministically, and uses GPT-5 only for tool execution and
final narration. The existing CopilotLLM flow is preserved as fallback behind a
feature flag.

## Architecture

```
                   ┌──────────────────┐
    User Query ──▶ │ Intent Classifier │
                   └────────┬─────────┘
                            ▼
                   ┌────────────────┐
                   │     Router     │  ── maps Intent → SpecialistRoute
                   └────────┬───────┘
                            ▼
            ┌───────────────────────────────┐
            │    MAASOrchestrator.run_stream │
            ├───────────────────────────────┤
            │ Phase 1: Evidence Gathering   │  ToolExecutor calls
            │ Phase 2: Specialist Calls     │  RunPod vLLM → Verify
            │ Phase 3: GPT-5 Narration      │  CopilotLLM.chat_stream
            └───────────────────────────────┘
```

**Specialists** (RunPod vLLM, OpenAI-compatible):
- **SQL** — generates SELECT queries from natural language
- **Logs** — triages error logs, identifies root cause owner
- **CodeFix** — generates patches (SQL models, YAML, Python)

**Verifiers** (deterministic, no LLM):
- **SQLVerifier** — SELECT-only, balanced parens, schema match, warehouse targeting
- **LogsVerifier** — valid failure layers/owners, bounded evidence
- **PatchVerifier** — size bounds, valid types, diff format, optional StaticValidator

## Environment Variables

### Feature Flag
| Variable | Default | Description |
|----------|---------|-------------|
| `COPILOT_MAAS_ENABLED` | `false` | Enable MAAS orchestration |

### Specialist Endpoints
| Variable | Default | Description |
|----------|---------|-------------|
| `MAAS_SQL_ENDPOINT` | `""` | RunPod SQL specialist base URL |
| `MAAS_SQL_API_KEY` | `""` | API key for SQL endpoint |
| `MAAS_SQL_MODEL` | `specialist-sql` | Model name for SQL specialist |
| `MAAS_LOGS_ENDPOINT` | `""` | RunPod Logs specialist base URL |
| `MAAS_LOGS_API_KEY` | `""` | API key for Logs endpoint |
| `MAAS_LOGS_MODEL` | `specialist-logs` | Model name for Logs specialist |
| `MAAS_CODEFIX_ENDPOINT` | `""` | RunPod CodeFix specialist base URL |
| `MAAS_CODEFIX_API_KEY` | `""` | API key for CodeFix endpoint |
| `MAAS_CODEFIX_MODEL` | `specialist-codefix` | Model name for CodeFix specialist |

### General
| Variable | Default | Description |
|----------|---------|-------------|
| `MAAS_SPECIALIST_TIMEOUT` | `30` | HTTP timeout (seconds) per specialist call |
| `MAAS_ORCHESTRATOR_MODEL` | `gpt-5.2` | Model for GPT-5 narration phase |

## RunPod Endpoint Expectations

Specialists must expose OpenAI-compatible `/v1/chat/completions`. The client:
1. Sends `response_format: {"type": "json_object"}` to request structured output
2. Strips markdown code fences from responses (vLLM sometimes wraps JSON)
3. Extracts the first balanced `{...}` block if preamble text is present
4. Validates against Pydantic schemas (`SQLResponse`, `LogsResponse`, `CodeFixResponse`)
5. Retries once with a correction prompt on validation failure

## Intent Routing

| Intent  | Specialists | Condition |
|---------|-------------|-----------|
| INFO    | SQL | Only if `_is_data_query()` detects warehouse intent |
| INFO    | (none) | Non-data questions → GPT-5 only |
| DEBUG   | Logs (+CodeFix if secondary=FIX) | Always |
| FIX/PR  | Logs + CodeFix | Always |
| PLAN    | CodeFix | Always |
| EXPLAIN | (none) | GPT-5 only |

## Dialect Adaptation

The SQL specialist receives **only the target warehouse's dialect rules** in its prompt.
Five dialects are supported:

| Warehouse | Key Syntax |
|-----------|-----------|
| BigQuery | Backticks: `` `project.dataset.table` ``, `TIMESTAMP_SUB`, `SAFE_CAST`, `UNNEST` |
| Databricks | `catalog.schema.table`, `date_sub()`, `try_cast()` |
| Snowflake | Preserve exact FQN, `DATEADD('DAY', -N, CURRENT_TIMESTAMP())` |
| Postgres | `schema.table`, `NOW() - INTERVAL 'N days'` |
| Redshift | `schema.table`, `GETDATE() - INTERVAL 'N days'` |

### Forcing a specific warehouse

When multiple warehouses are connected, mention the warehouse in your query:

- "How many rows in orders **in BigQuery**?"
- "Count events **in Snowflake** for last 7 days"
- "Show me data from users **in BQ**"

Aliases: `bq` / `big query` → BigQuery, `spark` / `delta lake` → Databricks, `pg` / `postgresql` → Postgres.

If no warehouse is mentioned, the orchestrator uses the first connected warehouse.

## Warehouse Resolution

Deterministic — no inference from SQL syntax:

1. **Single warehouse** connected → use it automatically
2. **Multiple warehouses** → check user query for warehouse mentions (aliases above)
3. **No mention** → use first active warehouse from schema keys

The resolved warehouse is recorded in `maas_trace.selected_warehouse`.

## Repair Loop

If the SQL specialist's query passes the verifier but **fails execution** (syntax error,
missing table/column), the orchestrator:

1. Calls the SQL specialist **once more** with the original query, failed SQL, and exact error text
2. Verifies the repaired SQL
3. Executes the repaired SQL
4. If it still fails → falls back to legacy `CopilotLLM` flow

The trace records `repair_attempted: true` and `fallback_reason` if fallback occurred.

## Fallback Policy

- **Partial fallback**: If an optional specialist is down, MAAS continues with available ones
- **Full fallback**: Only when a required specialist is unavailable or on orchestration errors
- **Repair fallback**: If SQL repair also fails, falls back to legacy CopilotLLM
- **Circuit breaker**: 3 failures → open circuit (60s recovery) per endpoint

## Sanity Check

Verify endpoint connectivity before running the full system:

```bash
cd scanner
python -m copilot.maas.sanity_check --endpoint $MAAS_SQL_ENDPOINT --model sqlcoder
```

Optional BigQuery connectivity test:
```bash
python -m copilot.maas.sanity_check --endpoint $MAAS_SQL_ENDPOINT --model sqlcoder --test-bq
```

Expected output on success:
```
==================================================
MAAS Sanity Check
==================================================
Endpoint: https://your-pod-id-8000.proxy.runpod.net
Model:    sqlcoder

[1] GET .../v1/models
    Models: ['sqlcoder']
    PASS

[2] POST .../v1/chat/completions  model=sqlcoder
    Response: {"status": "ok"}
    PASS

==================================================
Result: ALL PASSED
==================================================
```

## Smoke Test Prompts

Use these in the UI with `COPILOT_MAAS_ENABLED=true` to verify the SQL path:

1. **"How many rows are in `<known_table>`?"** — simplest data query
2. **"Count rows in `<table>` for last 7 days"** — tests dialect time functions
3. **"Show me the top 10 rows from `<table>`"** — tests LIMIT handling

## Expected Logs

Look for these `[MAAS]` log lines in order:

```
[MAAS] Entering orchestration intent=INFO mode=maas
[MAAS] Target warehouse: bigquery
[MAAS] Calling sql endpoint=https://... model=sqlcoder
[MAAS] sql returned latency=1234ms sql=SELECT COUNT(*) FROM ...
[MAAS] Executing query_warehouse warehouse=bigquery
[MAAS] query_warehouse completed latency=567ms success=True
```

In `maas_trace` (inside the `done` SSE event):
- `route`: `"INFO/sql"`
- `selected_warehouse`: `"bigquery"`
- `verifier_results.sql.passed`: `true`
- `fallback_reason`: `null`
- `repair_attempted`: `false`

If repair was triggered:
```
[MAAS] SQL execution failed, attempting repair: Column not found: ...
[MAAS] Executing repaired SQL warehouse=bigquery
[MAAS] Repair query_warehouse completed latency=890ms success=True
```

## Testing

```bash
cd scanner
python -m pytest tests/copilot/maas/ -v
```

Tests cover schemas, client, evidence store, all three verifiers, router,
orchestrator, dialect adaptation, warehouse resolution, repair loop, and fallback scenarios.

## Key Design Decisions

1. **Feature-flagged**: `COPILOT_MAAS_ENABLED=false` by default. Zero impact when off.
2. **Same SSE events**: Produces identical `StreamEvent` types as `CopilotLLM.chat_stream()`.
3. **EvidenceStore prevents context burnout**: Bounded slices (4K per tool result, 50 log lines, 20K total).
4. **Hardened JSON extraction**: Handles vLLM code fences and preamble text.
5. **Tool call deduplication**: `args_hash` prevents re-executing identical tool calls.
6. **MAASTrace in done event**: Full observability (route, latencies, verifier results, fallback reason).
7. **Dialect adaptation**: Only target warehouse's rules injected into specialist prompt.
8. **Deterministic warehouse resolution**: No inference from SQL syntax — explicit mention or first active.
9. **One repair loop**: Single retry on SQL execution error before fallback to legacy.
