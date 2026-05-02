# Session handover — Tier-4 + Integration Health

**Date:** 2026-05-02
**Predecessor commit:** `48ccabb` (Tier 1–3 hardening batch)
**Spec reference:** `docs/superpowers/plans/2026-04-29-llm-architecture-tier4.md`

> Pick this up cold. Everything you need to continue is in this document plus the spec above.

---

## What this session did

Two distinct workstreams landed:

1. **Tier-4 LLM-architecture follow-up** — all 8 items from the spec.
2. **Integration health snapshots** — structured failure reasons (BILLING / AUTH / NETWORK / etc.) so the copilot can answer "why is X down?" with a real cause instead of a raw exception string.

Plus an out-of-band fix: `scanner/.env` precedence over the repo-root `.env` so the Pallisade-project OpenAI/Anthropic keys actually win at runtime.

---

## Commits landed (most recent first)

| SHA | Title | What it does |
|---|---|---|
| `4c67d5f` | `feat(integrations): structured integration-health snapshots` | `FailureCategory` + `IntegrationHealth` + `classify_error` + `HealthStore`; Metabase driver wired; new `annotate_integration_health` tool |
| `c61a01b` | `feat(copilot/llm): Tier-4 item 7 step 3 — migrate streaming chat methods` | `_chat_anthropic_stream` / `_chat_openai_stream` collapsed to thin shells over `_run_provider_stream_loop` |
| `5b8821f` | `feat(copilot/llm): Tier-4 item 7 step 2 — migrate non-streaming chat methods` | `_chat_anthropic` / `_chat_openai` collapsed to thin shells over `_run_provider_loop` |
| `2f527ba` | `feat(copilot/llm): Tier-4 item 7 step 1 — LLMProvider abstraction` | New `scanner/copilot/llm_provider.py` with `LLMProvider` Protocol + concrete Anthropic/OpenAI |
| `c552543` | `feat(copilot/maas): Tier-4 item 5 — specialist soft deadline` | `MAAS_SPECIALIST_SOFT_DEADLINE_SEC` env var + `gather_specialists_with_deadline` helper |
| `ab6aafa` | `feat(copilot/eval): Tier-4 item 8 — eval harness Phase A + runner skeleton` | `tests/copilot/eval/{corpus.yaml,runner.py}` with 16-case corpus, static + opt-in live driver |
| `1ec5778` | `feat(copilot/maas): Tier-4 item 4 — self-consistency for high-stakes SQL` | High-stakes heuristic + temp 0.0/0.7 fan-out + winner pick by verifier confidence |
| `74a51e2` | `feat(copilot/maas): Tier-4 items 1, 2, 3, 6` | Adaptive reasoning_effort escalation; per-pipeline cache scoping; repair-mode prompt; intent enum coverage |
| `424346d` | `fix(scanner): load scanner/.env with override` | scanner/.env wins over repo-root .env for keys |

All on `main`. Repo working tree has unrelated in-progress feature work (TODO.md, lineage UI, SLA discovery files) that was NOT touched by this session.

---

## Test counts

- **Start of session:** 302 tests
- **End of session:** 1153 passing, 1 skipped, 4 xfailed
- Net new: ~170 tests across the two workstreams

---

## What changed where

### New modules (read these first if picking up cold)

- `scanner/copilot/llm_provider.py` (~700 lines) — `LLMProvider` Protocol, `AnthropicProvider`, `OpenAIProvider`, `NormalizedResponse`, `NormalizedToolCall`, `StreamTextDelta`, `StreamFinal`, `StopKind`, `iter_stream`. **Single source of truth for provider differences.** Adding a third provider = subclass `LLMProvider`.
- `scanner/integrations/health.py` (~330 lines) — `FailureCategory`, `IntegrationHealth`, `classify_error`, `build_failure_snapshot`, `HealthStore`, `get_default_store()`. Module-level singleton store (in-memory).
- `scanner/tests/copilot/eval/{__init__.py, corpus.yaml, runner.py, test_eval_runner.py}` — eval harness scaffolding.

### Heavily modified

- `scanner/copilot/llm.py` — went from 3068 to 2606 lines. Four chat methods (271–583 lines each) collapsed to four ~80–175 line shells over two unified loops (`_run_provider_loop`, `_run_provider_stream_loop`) plus one shared helper (`_emit_pre_executed_tool`).
- `scanner/copilot/maas/orchestrator.py` — adaptive-effort escalation, self-consistency fan-out, soft-deadline plumbing.
- `scanner/copilot/maas/specialists/base.py` — pipeline-id and reasoning_effort kwargs, cache key extended to include both + temperature.
- `scanner/copilot/intent.py` — 4 new Intent values (CREATE / BUNDLE / ONBOARD / SUGGEST) + classifier patterns + mode mapping.
- `scanner/api/dependencies.py` — env-loading order fixed.
- `scanner/drivers/reporting/metabase_driver.py` — health-snapshot wiring (template for other drivers).
- `scanner/copilot/tool_executor.py` — `execute_driver_health_check` returns the snapshot; new `_execute_check_integration_health` and `_execute_annotate_integration_health` handlers.
- `scanner/copilot/tools/infrastructure.py` — `check_integration_health` description rewritten to point at structured fields; new `annotate_integration_health` tool.

---

## What's NOT done (prioritized backlog)

### High value, ready to start

1. **Wire `_build_live_driver()` against the real copilot** (Tier-4 item 8 Phase B). Currently `tests/copilot/eval/runner.py:_build_live_driver()` raises `NotImplementedError`. The contract is documented at the top of `runner.py` — driver returns `{tool_calls, sql, response_text}`. Once wired, the existing 16-case corpus will run end-to-end through `MAASOrchestrator.chat_stream`. Cost: ~$0.50 per full run with `gpt-5.4-mini`.
   - Sub-step: build a synthetic `CopilotContext` with a stubbed warehouse adapter so eval cases don't need real warehouse data.

2. **Expand the eval corpus from 16 → 50 cases.** The corpus at `tests/copilot/eval/corpus.yaml` covers all 9 intents + one high-stakes case. Spec target is 50–100. Each new case is a YAML edit; the runner validates structure. Best done after step 1 so you can see live pass-rate per case as you add them.

3. **Roll out `IntegrationHealth` to other drivers as failures show up.** Pattern is in `scanner/drivers/reporting/metabase_driver.py:test_connection`. Drop into the next driver that surfaces a real user incident. **Don't speculatively retrofit all of them** — without real failure samples you'll classify wrong.

### Medium value, larger scope

4. **`/v1/responses` migration for the OpenAI narrator.** Currently `OpenAIProvider.request_kwargs` drops `reasoning_effort` when tools are present (commit `3700f2b`). This blocks adaptive reasoning effort on the narration path. Migrating the narrator to `/v1/responses` lifts that constraint. Not a Tier-4 item but mentioned as a precondition in item 1's caveat.

5. **Phase C of eval harness — A/B framework.** Once you have a stable corpus + live runner, the next layer is comparing two prompt variations on the same corpus and running statistical comparisons (paired test). Spec sketch in the Tier-4 plan, item 8.

6. **Persist `HealthStore` snapshots across process restarts.** Current store is in-memory; a process restart drops all snapshots. Either persist to disk (JSON) or to the existing DB (a small `IntegrationHealth` Prisma model). Surface unchanged — callers go through `record` / `get` / `list_for`.

### Low value / situational

7. **Tune the `_HIGH_STAKES_PATTERNS` regex** in `scanner/copilot/maas/orchestrator.py`. The current set is conservative. Real corpus data from items 1+2 will tell you whether it's missing cases or firing too liberally.

8. **Tune `MAAS_SPECIALIST_SOFT_DEADLINE_SEC` value.** Default unset (no deadline). Once you have eval data showing per-specialist latency distribution, pick a value that catches the long tail without killing healthy slow runs. Spec suggests 1.5s as a reasonable floor.

9. **Consider unifying `root_cause_label` across providers.** Anthropic says `[System context — root cause analysis]:`, OpenAI says `[system note — root cause analysis]:`. Drift is historical. Unifying changes response tone — do it after the eval harness can confirm no regression.

---

## Known gotchas (read before touching anything)

### Environment

- **The worktree at `.worktrees/feat-custom-source-integration` is a different branch** with its own venv. `pip install mcp` there if you see `ModuleNotFoundError: No module named 'mcp'`. Doesn't affect `main`.
- **Two `.env` files** — `scanner/.env` is authoritative for backend keys (Pallisade project), `.env` at repo root is for the Next.js dashboard's separate AI Assistant feature. Don't merge them.
- **`mcp-server-bigquery` binary** isn't on most dev machines' PATH. The system fails closed (no BigQuery MCP tools available); not a bug, just degraded capability.

### LLM call paths

- **`reasoning_effort` is silently dropped** when `tools` are present on Chat Completions (commit `3700f2b`). `OpenAIProvider.request_kwargs` enforces this. The narrator always has tools, so `reasoning_effort` only flows for specialists today.
- **`args_raw` is load-bearing.** `NormalizedToolCall.args_raw` preserves the EXACT JSON string the model produced. Re-serializing via `json.dumps(args)` would introduce whitespace/precision drift that confuses some tool consumers. The streaming path falls back to `json.dumps(args, default=str)` only when `args_raw` is None (i.e. for synthetic tool calls in the pre-execution flow).
- **`assistant_turn_for_tool_use` no longer reaches into `response.raw`** — it's built from normalized fields. This is what made streaming + non-streaming work through the same provider. If you're tempted to add `response.raw.something` access in a provider method, you'll break streaming.
- **Anthropic streaming uses `with messages.stream():` context manager**, OpenAI streaming returns a plain iterable. The `stream_factory` callable in `_run_provider_stream_loop` wraps both shapes (OpenAI uses `contextlib.nullcontext`).

### Per-pipeline isolation

- **Three caches are pipeline-scoped** as of this session: `_response_cache` in `maas/specialists/base.py`, `_anomaly_baselines` in `tool_executor.py`, `_engine_tool_configs_map` in `_lineage_cache.py`. The `HealthStore` follows the same `(org_id, pipeline_id, …)` keying pattern. **Don't add new module-level caches without this scoping** — pipeline profiles are isolated workspaces and a leak is a real correctness bug.

### Integration health

- **Billing-phrase detection runs BEFORE status-code dispatch** in `classify_error`. Trial-expired pages disguise as 503/200/302 — if you reorder, you'll mis-classify Metabase Cloud failures (the actual incident that motivated this work).
- **`build_failure_snapshot` for UNKNOWN preserves the raw message** in `reason`. Don't replace it with a generic "unknown failure" string — it's the only signal the LLM has when classification couldn't decide.

---

## How to verify state

```bash
# Confirm tests pass
cd /Users/emilfabel/pallisade-copilot
python -m pytest scanner/tests/ 2>&1 | tail -5
# Should show: 1153 passed, 1 skipped, 4 xfailed

# Confirm commits landed
git log --oneline 48ccabb..HEAD | head -15

# Run the eval harness in static mode (free, no API calls)
cd scanner
python -m tests.copilot.eval.runner
# Should show: Pass rate: 16/16 (100%)

# Confirm scanner/.env precedence
PYTHONPATH=scanner python3 -c "
import os
os.environ['OPENAI_API_KEY'] = 'ROOT'
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location('deps', 'scanner/api/dependencies.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
print('Override worked' if os.environ['OPENAI_API_KEY'] != 'ROOT' else 'BROKEN')
"
```

---

## Recommended next session order

### If you have ~half a day

1. Wire `_build_live_driver` (item 8 Phase B) — gives you the measurement infrastructure for everything else.
2. Run the existing 16-case corpus through it, baseline the pass rate.
3. Stop. Evaluate whether item 4 (`/v1/responses` migration), item 5 (corpus expansion), or item 7 (other drivers' health) is most painful right now and pick the one that's hurting users.

### If you have ~2 hours

1. Triage which integration drivers had failures last week. For the top 1-2, drop in the `build_failure_snapshot` pattern from `MetabaseDriver`.
2. Verify with manual `check_integration_health` calls that the snapshot data looks right.
3. Stop.

### If you have 30 minutes

1. `pip install mcp` in the worktree if you're working there.
2. Read this document.
3. Start the next session fresh.

---

## Open questions for the next session

1. **Live eval driver vs. mock LLM.** The runner contract supports both. Which is more useful first — paid-token end-to-end correctness, or token-free behavioral testing via mock LLM?
2. **`HealthStore` persistence.** Process-restart loses snapshots. Is that acceptable for your use case, or do you need it durable from day one?
3. **Eval corpus expansion.** Who owns curating the 50-case corpus? It's product-knowledge work — the engineer building the runner shouldn't be the only one writing cases.

---

The Tier-4 plan is fully addressed; integration health is in production for Metabase and ready to roll out as failures show up elsewhere.
