# LLM architecture — Tier 4 follow-up

**Date:** 2026-04-29
**Status:** Spec — not started
**Predecessor commit:** `48ccabb` (feat(copilot/maas): LLM architecture hardening + MaaS quality lifts)

This plan tackles eight deferred architecture items identified after the
Tier 1–3 batch. Items are ordered by ROI; each is independently shippable.
Items 1–4 fit in a single focused session; items 5–8 are bigger.

---

## Background

After landing the Tier 1–3 hardening batch (`48ccabb`), the LLM stack has
correct fundamentals: prompt caching, schema-fetch visibility, dialect
quoting, tool-arg validation, SQL identifier whitelisting, parallel
evidence gathering, response cache, verifier confidence, hard budgets,
per-specialist health metrics. What's left is the genuinely
architectural work — deeper structural improvements that compound.

These eight items were enumerated together because each requires
either non-trivial design work, a focused refactor, or a correctness
analysis that didn't fit in a Tier 1–3 sweep.

---

## Item 1 — Adaptive reasoning effort (highest ROI)

### Problem
GPT-5 / o-series specialists run at a single fixed `reasoning_effort`
(per `MAAS_SQL_REASONING_EFFORT` etc.). Spending `medium`/`high` on
every call wastes cost on simple cases; spending `low`/`minimal`
under-thinks complex ones. The infrastructure for both *verifier
confidence scoring* (M5) and *per-specialist effort* (M2) is already
in place — it just needs an escalation loop.

### Proposed solution
On verification failure (or low confidence), retry once with the next
effort tier. Effort ladder: `minimal` → `low` → `medium` → `high`.
Skip tiers below the configured floor.

### Implementation sketch

`scanner/copilot/maas/orchestrator.py` — inside `_call_and_verify`,
when `vr["passed"]` is False on first try, escalate before retry:

```python
EFFORT_LADDER = ["minimal", "low", "medium", "high"]

def _next_effort(current: Optional[str]) -> Optional[str]:
    if current is None:
        return "medium"
    try:
        idx = EFFORT_LADDER.index(current)
    except ValueError:
        return "medium"
    return EFFORT_LADDER[idx + 1] if idx < len(EFFORT_LADDER) - 1 else None

# In retry path:
escalated = _next_effort(self._clients[spec_name].reasoning_effort)
if escalated:
    self._clients[spec_name].reasoning_effort = escalated  # transient
    logger.info(f"[MAAS] {spec_name} escalating to reasoning_effort={escalated}")
    result = await specialist.call(..., max_retries=0)
    self._clients[spec_name].reasoning_effort = original  # restore
```

### Files affected
- `scanner/copilot/maas/orchestrator.py` — escalation logic in `_call_and_verify`
- `scanner/copilot/maas/client.py` — make `reasoning_effort` mutable
  per-call rather than per-instance (cleaner than the swap-and-restore
  above; pass via `chat_completion` kwargs)
- `scanner/copilot/maas/schemas.py` — `SpecialistInvocation.escalated_to: Optional[str]`
- Tests: `tests/copilot/maas/test_orchestrator.py`

### Success criteria
- A failed first attempt at `low` retries at `medium`, observable in trace
- Trace records the effort level used per attempt
- Adaptive escalation is bounded (max one escalation per call)
- 365 existing tests pass; new test covers escalation path

### Effort: ~1 hour

---

## Item 2 — Per-pipeline cache scoping

### Problem
Three caches today are keyed globally instead of per-pipeline:
- `tool_executor.py:_anomaly_baselines` — anomaly metric baselines
- `lineage.py:_engine_tool_configs_map` — populated during investigate-llm
- `specialists/base.py:_response_cache` — added in M3

Memory file flags: *"Pipeline profiles are fully isolated workspaces …
Switching profiles means ZERO data persistence from the previous
one."* These caches violate that. A user switching from Pipeline A to
Pipeline B can see baselines from A applied to B's monitors, or get
a stale specialist response from A's schema.

### Proposed solution
Key all three caches on `(pipeline_id, …existing key…)`. Threading
`pipeline_id` is straightforward — `CopilotContext` already carries
`pipeline_stack_id`.

### Implementation sketch

`scanner/copilot/tool_executor.py`:
```python
# Was
self._anomaly_baselines: Dict[str, List[float]] = {}
# Becomes
self._anomaly_baselines: Dict[Tuple[str, str], List[float]] = {}
# All access sites
key = (self.context.pipeline_stack_id or "_default", baseline_key)
```

`scanner/copilot/maas/specialists/base.py`:
```python
def _hash_messages(messages: list, pipeline_id: str = "") -> str:
    blob = json.dumps([pipeline_id, messages], sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()
```

`BaseSpecialist.call` reads `kwargs.get("pipeline_id")` and passes it
to `_hash_messages`. Orchestrator passes `context.pipeline_stack_id`.

`scanner/api/routers/lineage.py:_engine_tool_configs_map` — same
treatment.

### Files affected
- `scanner/copilot/tool_executor.py`
- `scanner/copilot/maas/specialists/base.py`
- `scanner/copilot/maas/orchestrator.py` (pass pipeline_id through)
- `scanner/api/routers/lineage.py`
- Tests covering pipeline-switch isolation

### Success criteria
- Switching pipelines never returns cached results from another pipeline
- A new test asserts: cache hit for pipeline A misses for pipeline B
- 365 tests still pass

### Effort: ~1.5 hours

---

## Item 3 — MaaS repair-loop specialized prompt

### Problem
When SQL execution fails, the orchestrator calls the SQL specialist
again with `evidence_blob + previous_sql + error_text`, but uses the
*same generic SQL prompt*. The model often regenerates the same
broken query. A repair-specific prompt — "you are fixing a failed
query, focus on the specific error" — meaningfully improves the
repair pass rate.

### Proposed solution
Add a `repair_mode: bool = False` kwarg to `SQLSpecialist.build_messages`.
When true, swap in a repair-tuned system prompt that:
- Acknowledges the prior failure
- Names common failure modes (column not found, wrong cast, missing
  warehouse-specific function)
- Tells the model to make the *minimal change* that addresses the
  named error rather than rewriting

### Implementation sketch

`scanner/copilot/maas/specialists/sql.py`:
```python
REPAIR_PROMPT_PREFIX = """You are repairing a SQL query that failed at execution.
The PREVIOUS SQL and the warehouse's EXACT error are provided. Your job:
1. Identify the root cause from the error message
2. Make the MINIMAL change that fixes that specific error
3. Do not rewrite the query structure unless the error proves the
   structure is wrong
4. Common failure modes to look for first:
   - Column not found → check schema; use a column that exists
   - Type mismatch → add SAFE_CAST/TRY_CAST per dialect
   - Function not found → use the dialect-correct equivalent
   - Wrong warehouse syntax → confirm `warehouse` field matches

Do NOT regenerate the same query. The repair must differ from the
previous attempt in at least one substantive way.

"""

def build_messages(self, evidence: str, query: str, **kwargs) -> list:
    repair_mode = kwargs.get("repair_mode", False)
    # ... existing prompt assembly ...
    if repair_mode:
        system_prompt = REPAIR_PROMPT_PREFIX + system_prompt
    # ...
```

Orchestrator passes `repair_mode=True` in the repair call.

### Files affected
- `scanner/copilot/maas/specialists/sql.py`
- `scanner/copilot/maas/orchestrator.py` — repair call site

### Success criteria
- Repair call uses distinct prompt (verifiable in test by inspecting
  messages)
- Manual smoke test: a query that fails with "column not found"
  produces a fixed query with the corrected column name on repair
- Trace records that repair used `repair_mode`

### Effort: ~1 hour

---

## Item 4 — Self-consistency for high-stakes SQL

### Problem
SQL specialist runs once at `temperature=0.0`. For complex queries
this misses a class of subtle hallucinations (wrong joins, wrong
aggregations) that a second attempt at higher temperature would
disagree on, exposing uncertainty.

### Proposed solution
For queries flagged "high-stakes" (heuristic: multi-table, has
`JOIN`/`GROUP BY`, or user-flagged investigation), run the SQL
specialist twice:
- Attempt A: `temperature=0.0`
- Attempt B: `temperature=0.7`

Compare:
- If both produce SQL and they're semantically equivalent
  (canonicalized): use A. High confidence.
- If they differ: prefer the one that passes the verifier with higher
  confidence. Log disagreement.
- If both fail verifier: drop, fall back.

### Implementation sketch

`scanner/copilot/maas/orchestrator.py`:
```python
async def _call_and_verify_consistent(spec_name: str):
    # Determine if high-stakes
    if spec_name != "sql" or not _is_high_stakes(query):
        return await _call_and_verify(spec_name)

    # Fan out two calls
    a, b = await asyncio.gather(
        _call_one(spec_name, temperature=0.0),
        _call_one(spec_name, temperature=0.7),
    )
    # Pick: equivalent → A; different → higher-confidence; both bad → drop
    return _select_best(a, b)
```

`temperature` needs to flow through `BaseSpecialist.call` →
`RunPodClient.chat_completion`. Today temperature is hardcoded at the
specialist level; will need a kwarg.

### Files affected
- `scanner/copilot/maas/orchestrator.py`
- `scanner/copilot/maas/specialists/base.py` (temperature kwarg)
- `scanner/copilot/maas/client.py` (already accepts temperature)
- Tests

### Cost
Doubles SQL specialist cost on high-stakes path. Should be gated by
heuristic, not always-on.

### Success criteria
- Easy queries (single-table SELECT) take one call
- Complex queries take two calls in parallel
- Disagreement is recorded in trace as
  `self_consistency: {agreed: bool, picked: "A"|"B", reasons: ...}`
- 365 tests pass

### Effort: ~1.5 hours

---

## Item 5 — Speculative parallel orchestrator

### Problem
Today's flow is strictly sequential: Phase-1 evidence → specialists →
GPT-5 narration. Even with parallel evidence/specialist gather, the
orchestrator sits idle until specialists return.

### Proposed solution
Fire GPT-5 narration *as soon as* Phase-1 evidence is ready, in
parallel with specialists. As specialists return, the orchestrator
incorporates their output. If specialists fail or are slow, the
orchestrator already has a partial answer.

### Architecture sketch

Two parallel coroutines:
1. **Speculative narration**: GPT-5 with Phase-1 evidence + best-effort
   placeholders for specialist output ("SQL specialist still
   running…").
2. **Specialist phase**: Existing parallel specialists.

When specialists complete, replace placeholders in the in-progress
narration. The streaming layer must handle partial-text revision.

### Hard parts
- **Streaming UX**: user might see text that gets revised. Need
  either: (a) buffer narration until specialists return (loses some
  latency), (b) emit revisions client-side, or (c) only speculate when
  specialists are ≥2s slow.
- **Token cost**: 1.5–2× per request because narration may run twice.
- **Cancellation**: if specialists return *worse* than placeholders,
  what wins?

### Recommended approach
**Conservative speculation**: kick off narration only after a 1.5s
specialist deadline expires. If specialists return within 1.5s,
narrate normally. If they don't, narrate with whatever's available.
Reduces wasted narration calls on fast specialists.

### Files affected
- `scanner/copilot/maas/orchestrator.py` — major restructure
- Streaming event protocol — possibly add `text_revision` event type
- `scanner/copilot/llm.py` — confirm `chat_stream` can be cancelled

### Success criteria
- Specialists ≤1.5s: behavior unchanged from today
- Specialists >1.5s: narration starts immediately, total wall-clock
  reduced
- No user-facing text appears that is later contradicted by
  specialist output

### Effort: ~3–4 hours

### Verdict
Worth doing only after eval harness (item 8) exists to measure the
quality tradeoff. Speculative speed gains can come at a quality cost
that's hard to detect without measurement.

---

## Item 6 — Intent enum coverage

### Problem
`copilot/intent.py:Intent` has 6 values: `INFO, DEBUG, FIX, PR, PLAN, EXPLAIN`.
`copilot/modes.py:InteractionMode` defines 9: `ASK, DEBUG, PLAN, CREATE,
BUNDLE, EXPLAIN, SUGGEST, FIX, ONBOARD`. Mapping in
`intent_to_mode()` (intent.py:408–421) covers only 6. So `CREATE`,
`BUNDLE`, `ONBOARD`, `SUGGEST` are unreachable from natural language —
they fire only via explicit slash commands.

### Proposed solution
Add the four missing intent values, classifier patterns, and mapping.

```python
class Intent(Enum):
    INFO = "info"
    DEBUG = "debug"
    FIX = "fix"
    PR = "pr"
    PLAN = "plan"
    EXPLAIN = "explain"
    CREATE = "create"     # NEW — "create a watch for..."
    BUNDLE = "bundle"     # NEW — "bundle these monitors..."
    ONBOARD = "onboard"   # NEW — "set up..."
    SUGGEST = "suggest"   # NEW — "suggest checks for..."
```

Add patterns in `_score_intent`:
- CREATE: `\b(create|add|new|set up|configure)\s+(?:a\s+)?(watch|monitor|alert|check)\b`
- BUNDLE: `\b(bundle|combine|consolidate|merge)\s+(?:these\s+)?(monitor|alert|check)`
- ONBOARD: `\b(onboard|set\s*up|connect|integrate|wire\s+up)\b`
- SUGGEST: `\b(suggest|recommend|propose)\s+(?:some\s+)?(monitor|check|alert|test)`

Update `intent_to_mode()` mapping.

### Files affected
- `scanner/copilot/intent.py`
- `scanner/copilot/modes.py` (verify auto_detect_patterns align)
- Tests: `tests/copilot/test_intent.py`

### Success criteria
- "create a watch for table X" → `Intent.CREATE` → `CREATE` mode
- "bundle these monitors" → `Intent.BUNDLE` → `BUNDLE` mode
- New tests for each intent
- Existing intent tests still pass

### Effort: ~1.5 hours

---

## Item 7 — Anthropic↔OpenAI loop centralization

### Problem
`llm.py` has four near-identical chat methods totaling ~1500 lines:
- `_chat_anthropic` (~300 lines)
- `_chat_anthropic_stream` (~400 lines)
- `_chat_openai` (~400 lines)
- `_chat_openai_stream` (~400 lines)

Common shape across all four: pre-fetch schema, build prompt,
iterate tool loop, handle tool calls, handle stop reasons. Differences
are mostly: API client method, response shape, tool-call ID format,
streaming event extraction, max-tokens param name.

The drift between the four is where most provider-specific bugs hide
(see prior audit: mid-loop system message, root-cause injection,
tool-result serialization differences).

### Proposed solution
Single tool-loop driver `_run_tool_loop` parameterized by a `Provider`
adapter:

```python
class Provider(Protocol):
    def make_request(self, system, messages, tools, **kwargs) -> Awaitable[Response]: ...
    def extract_text(self, response) -> str: ...
    def extract_tool_calls(self, response) -> List[ToolCall]: ...
    def extract_stop_reason(self, response) -> str: ...
    def format_tool_result(self, tool_use_id, content) -> Dict: ...

class AnthropicProvider(Provider): ...
class OpenAIProvider(Provider): ...
```

`_run_tool_loop(provider, messages, context, ...)` becomes the only
implementation. Streaming variant takes a `StreamingProvider` subclass.

### Hard parts
- **Provider response heterogeneity**: Anthropic returns content blocks;
  OpenAI returns a flat message + tool_calls. Adapter abstraction
  needs to normalize.
- **Streaming events**: Anthropic emits content_block_delta; OpenAI emits
  delta with optional tool_calls partials. Need a unified event stream.
- **Stop reason canonicalization**: `end_turn` vs `stop`; `tool_use` vs
  `tool_calls`; `max_tokens` vs `length`. Already partially done in
  `StopReason` class.
- **Tool ID schemes**: `toolu_*` vs `call_*`. Provider should own ID
  generation/parsing.

### Risk
High — easy to introduce regressions during the consolidation. Should
be done in a focused session with thorough testing of both providers
side-by-side.

### Files affected
- `scanner/copilot/llm.py` — major restructure
- New: `scanner/copilot/llm_provider.py` (Provider abstractions)
- All `tests/copilot/` tests that mock the chat methods

### Success criteria
- Same behavior, both providers, both streaming and non-streaming
- 365 existing tests pass without modification
- ~1500 lines collapsed to ~600
- Future provider-specific bug fixes touch only the relevant
  Provider subclass

### Effort: ~4–8 hours

### Sequencing
Don't squeeze in alongside other work. Dedicated refactor session.
Best done after the eval harness (item 8) exists so regressions are
detectable beyond unit tests.

---

## Item 8 — Eval harness

### Problem
Every prompt change today is evaluated by:
- Static unit tests (do strings appear in output)
- Vibes (does the response look right when I try it manually)

There is no:
- Corpus of representative queries with expected behaviors
- Automated runner producing pass/fail or scored outcomes
- A/B framework for comparing prompt variations
- Regression detection (this prompt change degrades query class X)

This means prompt tuning is *guesswork*, and improvements one
session can silently regress in the next.

### Proposed solution
Build a minimal but real eval harness:

**Phase A — Corpus (1 day):**
- Seed file `tests/copilot/eval/corpus.yaml`:
  ```yaml
  - id: simple_count
    query: "how many orders are there?"
    intent: INFO
    expected:
      tool_calls: ["query_warehouse"]
      sql_pattern: "SELECT COUNT.*FROM"
      cites_table: "orders"

  - id: debug_dag_failure
    query: "why did my orders dag fail last night?"
    intent: DEBUG
    expected:
      tools_invoked: ["get_dag_run_history"]
      mentions_owner_system: ["airflow"]
  ```
- 50–100 representative queries spanning all intents
- Each query has `expected` clauses that can be programmatically
  checked

**Phase B — Runner (1 day):**
- `tests/copilot/eval/runner.py`:
  ```python
  async def run_eval(corpus_path, model="gpt-5.4-mini"):
      results = []
      for case in load_corpus(corpus_path):
          context = build_test_context(case)
          response = await run_copilot(case.query, context)
          checks = run_assertions(response, case.expected)
          results.append((case.id, checks))
      return results
  ```
- Stores results with timestamp + git SHA + model + prompt hashes
- Outputs: pass rate per intent, regressions vs last run

**Phase C — A/B (later):**
- Run two prompt variations on same corpus
- Statistical comparison (paired test)
- Recommendation: "variation B improves DEBUG pass rate by 12%, no
  regression on INFO"

### Files affected
- New: `tests/copilot/eval/`
- `Makefile` or runner script
- `pyproject.toml` for any new deps (probably none — stdlib + pytest)

### Cost
- Real OpenAI tokens per eval run. Ballpark: 100 queries × ~$0.005 =
  $0.50 per run with `gpt-5.4-mini`. Affordable.
- Engineering: ~2 days for Phase A + B; Phase C as needed

### Success criteria
- Single command runs the full corpus and outputs pass/fail per case
- Pass rate is durable — same code + same prompts → same results
  (within model-determinism limits at temp=0)
- Regression report: "this commit drops DEBUG pass rate from 0.85 to
  0.72"
- Used as a gate before merging prompt changes

### Effort: ~2 days for usable Phase A+B

### Verdict
Highest long-term value of all eight. Do this when there's appetite
for the prompt-tuning discipline (i.e., someone owning prompt
quality). Without it, you'll keep tuning by vibes.

---

## Recommended sequencing

| Order | Item | Effort | Why this order |
|---|---|---|---|
| 1 | #1 Adaptive reasoning effort | ~1 hr | Highest ROI; M2+M5 already in place |
| 2 | #2 Per-pipeline cache scoping | ~1.5 hr | Real correctness bug, low effort |
| 3 | #3 Repair-loop specialized prompt | ~1 hr | Cheap, narrow quality lift |
| 4 | #4 Self-consistency for hard SQL | ~1.5 hr | Quality lift on the long tail |
| 5 | #6 Intent enum coverage | ~1.5 hr | Polish; modes become reachable |
| 6 | #5 Speculative orchestrator | ~3–4 hr | Latency win, but trickier; do after #8 ideally |
| 7 | #7 Loop centralization | ~4–8 hr | Refactor session; do after #8 |
| 8 | #8 Eval harness | ~2 days | Different shape of work; unlocks data-driven tuning |

Items 1–4 are a tight session (~5 hours total). Items 5+ should each
get their own focused work block.

---

## Out of scope for this plan

- Provider additions (Bedrock, Azure OpenAI, on-prem vLLM) — covered
  if/when compliance requirements force them.
- Eval harness Phase C (A/B) — described above as a deferred subitem
  of #8.
- Multi-tenant cost attribution beyond the per-project-key setup
  documented in the env-var swap.
- Dashboard / UI work to display `trace.health` — backend exposes the
  data; frontend consumption is a separate plan.

---

## Definition of done for this plan

This plan is "done" when items 1–4 are shipped to `main` and items
5–8 either ship or are explicitly retired with a follow-up plan
explaining why.
