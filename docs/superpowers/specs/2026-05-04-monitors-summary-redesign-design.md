# Monitors Summary Redesign — Active Incidents + LLM Root Cause + MTTR Tracking

**Date:** 2026-05-04
**Status:** Draft

## Overview

The current Monitors Summary tab is a status board: category pills, per-asset rows with sparklines, six pipeline-tool tiles, and a collapsed SLA Recommendations panel. It tells the user *what's there*. It does not tell the user *what to do next*, *why something failed*, or *whether things are getting better*.

This redesign reframes the page around the question **"Should I be worried right now?"** with three supporting layers: triage (act now), trend (week-over-week), and coverage (gaps to close). The page introduces an `incidents` lifecycle so that monitor failures become first-class objects with an opened/acknowledged/resolved state, an LLM-generated root-cause hypothesis rendered inline, and an auditable resolution path that yields a real MTTR number.

The Pipeline Health tool tiles (Fivetran/Airflow/dbt/etc.) move out of Summary into the Pipeline Monitors tab so the Summary page stays focused.

---

## Page structure (top to bottom)

1. **Hero status banner.** Single colored band with the count of active incidents and the lineage-derived blast radius. Counts include `status = 'open'` and `muted_until <= now` only (acknowledged incidents are owned by a user, muted incidents are explicitly silenced, neither raises the worry signal). Three states:
   - Green — "All systems healthy. 28 assets monitored." (zero open incidents)
   - Amber — "1 warning. Affecting 0 dashboards." (only WARN-derived open incidents)
   - Red — "2 critical incidents · 1 warning. Affecting 3 BI dashboards and 14 downstream tables. Oldest 2h 14m." (any FAIL-derived open incidents)
2. **Active incidents list.** Expanded incident cards (B-style with collapsible evidence). Renders only when there is at least one open or acknowledged incident.
3. **7-day trend strip.** Four tiles in a row, all scoped to the last 7 days for the current pipeline profile:
   - **Pass rate** — `passing_runs / total_runs` across all monitor runs in the window
   - **MTTR** — `avg(resolved_at − opened_at)` across incidents resolved in the window
   - **Incidents opened** — count of incidents with `opened_at` in the window
   - **Recovered** — `count(incidents resolved in window) / count(incidents opened in window)` shown as `N / M` (so the user sees both the absolute and the ratio)
   Each tile renders the current value, the delta vs. the prior 7-day window, and a 7-point sparkline (one bucket per day).
4. **Asset health (lean).** A short table of failing/warning assets only, each with a 30-run sparkline. Healthy assets are collapsed under a "+ N healthy assets" expandable row to keep noise out. An asset shown here may also appear in Active Incidents above (the table aggregates per-asset; the incident card is per-monitor) — this overlap is intentional: the incident card is for triage, the asset row is for "how is this asset trending overall."
5. **Improve coverage.** Two side-by-side cards:
   - **Critical assets unmonitored** — assets flagged critical (or with downstream BI dashboards) that have zero monitors. Driven by lineage + criticality. CTA opens the create-monitor flow pre-targeted at the asset.
   - **SLA recommendations** — the existing drift-detected threshold recommendations, surfaced as an actionable CTA instead of a buried collapsible panel.

---

## Active incidents

### Card layout

Each card is the visual unit shown in the wireframe approved during brainstorming (B-style with collapsible evidence).

**Always visible:**
- Status dot (red/amber/grey for ack'd, dim purple for muted) + target FQN + monitor type + time-since-opened
- Blast-radius badge (e.g. "3 dashboards · 14 tables") when lineage shows downstream impact
- "Likely cause" — one paragraph rendered from the LLM hypothesis
- Action row: `Open in Co-pilot →` (primary), `Acknowledge` (when open), `Resolve` (when open or ack'd), `Mute ▾` (duration menu: 1h / 4h / 1d / 7d / custom datetime), `▸ Show evidence` toggle. When muted, `Mute ▾` is replaced by `Unmute (until 14:32 today)`.

**Collapsed by default ("Show evidence"):**
- Threshold and observed value (from `explainer.py` structured explanation)
- Last 5 runs with timestamps and statuses
- Lineage upstream summary (immediate parents and their last-run status)
- Owner-system classification from `copilot/root_cause.py` (airflow/dbt/ingestion/warehouse/infra/reporting + confidence)
- The signature slug ("fivetran-source-stalled") and the consecutive-fail count

### Sort order

Active incidents are ranked, from top:
1. Status (red before amber)
2. Lineage blast radius — number of downstream BI dashboards + critical tables, descending
3. Open age, descending (oldest first)

Acknowledged incidents render with reduced opacity at the bottom of the active list and do not contribute to the hero count. Muted incidents (where `muted_until > now`) are pulled out of the main list entirely and collapsed under a "+ N muted incidents (auto-unmute in …)" expandable row at the bottom of the Active Incidents section. Expanding the row reveals the muted cards in their normal style, with an `Unmute` button. When `muted_until` passes, the incident silently rejoins the main list — no notification fires, no LLM re-run is triggered by the unmute itself.

### "Open in Co-pilot" handoff

Clicking opens the existing co-pilot panel pre-seeded with:
- The failure summary (same payload that today's "Quick Link to Co-pilot" produces)
- The cached LLM hypothesis as the first assistant message ("Based on the failure, my current hypothesis is…")
- A user-facing prompt suggestion ("Investigate further" / "Suggest a fix")

This preserves today's quick-link behavior — the user can still ask follow-up questions in co-pilot — but the first answer arrives without a click.

If the diagnosis job is still in flight when the user clicks (rare, but possible if they hit Open in Co-pilot within seconds of the incident opening), the button shows an "Analyzing…" state and is disabled until the hypothesis lands; the user can also fall back to "Open in Co-pilot without hypothesis" which behaves exactly like today's quick link.

---

## Incidents data model

### `incidents` table

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `stack_id` | UUID | Pipeline profile FK; required for tenant isolation |
| `watch_id` | UUID | The watch group this incident belongs to (nullable for standalone tasks) |
| `monitor_id` | UUID | The specific monitor that failed |
| `target_fqn` | string | Asset FQN at time of opening |
| `status` | enum | `open`, `acknowledged`, `resolved` |
| `opened_at` | timestamp | Set when the monitor first transitioned to FAIL/WARN |
| `opening_run_id` | UUID | The monitor run that opened the incident |
| `signature` | string | LLM-emitted slug (e.g. `fivetran-source-stalled`) |
| `consecutive_count` | int | Count of consecutive same-signature failures since opening |
| `llm_hypothesis` | text | Latest hypothesis paragraph |
| `llm_hypothesis_at` | timestamp | When the hypothesis was last regenerated |
| `owner_system` | string | From `copilot/root_cause.py` classifier |
| `owner_confidence` | float | 0.0–1.0 |
| `acknowledged_at` | timestamp | nullable |
| `acknowledged_by` | string | user id, nullable |
| `resolved_at` | timestamp | nullable |
| `resolved_by` | string | user id (set when manual) or `'system'` (auto), nullable |
| `resolution_type` | enum | nullable: `auto_recovered`, `fixed`, `expected`, `false_positive`, `wont_fix` |
| `resolution_note` | text | optional free-text from the user |
| `muted_until` | timestamp | nullable; if `> now`, incident is muted |
| `muted_by` | string | user id who applied the mute, nullable |
| `muted_reason` | text | optional free-text note from the user |

One row per **fault episode**, not per failing run. A monitor that fails → recovers → fails again creates two incident rows. We do not modify monitor run history; incidents are derived metadata.

### Lifecycle transitions

```
   monitor transitions to FAIL/WARN with no open incident on this monitor
                            │
                            ▼
                          OPEN
                       │      │
                       │      └─ subsequent FAIL with same signature → stay OPEN, increment count
                       │      └─ subsequent FAIL with new  signature → stay OPEN, regenerate hypothesis, count=1
                       │
            ┌──────────┴──────────┐
            │                     │
   user clicks Acknowledge    monitor PASSes (1 run)
            │                     │
            ▼                     ▼
      ACKNOWLEDGED            RESOLVED (auto_recovered)
            │                  resolved_by = 'system'
   user clicks Resolve
   {fixed | expected | false_positive | wont_fix}
            │
            ▼
        RESOLVED (manual)
```

`resolved` is terminal. A monitor that resolves and then fails again opens a **new** incident row — the previous row is never re-opened. Two arrows out of `open` are mutually exclusive: whichever transition (Ack vs auto-recovery) lands first wins; the other is ignored.

**Open** — incident created when a monitor transitions from non-fail to fail (or warn). The incident stays open while the monitor continues to fail and nobody has acknowledged.

**Acknowledged** — user clicked Acknowledge. The incident remains in the active list with reduced opacity and is excluded from the hero red-count. The acknowledged user is recorded as the owner. Acknowledgement does not change the underlying monitor.

**Muted** is an orthogonal flag, not a status — `muted_until` can be set on any non-resolved incident. While muted, the incident is excluded from the hero count and the main active list (collapsed under "+ N muted"). Muting does not stop the underlying monitor from running, does not block auto-recovery (a muted incident that recovers still resolves normally), and does not change LLM diagnosis behavior (signature-change re-runs still fire so the cached hypothesis stays accurate when the user un-mutes). Auto-unmute is lazy: any read with `muted_until <= now` treats the incident as un-muted; no background job is needed.

**Resolved** — terminal state. Reached one of two ways:
- *Auto-recovered:* the next monitor run after `opened_at` returns PASS. Set `resolved_by = 'system'`, `resolution_type = 'auto_recovered'`, `resolved_at = run.completed_at`.
- *Manual:* user clicks Resolve and picks a reason from `{fixed, expected, false_positive, wont_fix}` with an optional note. Set `resolved_by = user.id`, `resolution_type = <reason>`.

If a manual resolution and an auto-recovery would both fire, whichever lands first wins; the second transition is ignored.

**Signature change while open.** If a subsequent failure produces a different LLM signature than the open incident's signature, we treat it as the same fault episode (the user still sees one ongoing failure for this monitor) but update `signature`, `llm_hypothesis`, `owner_system`, and reset `consecutive_count` to 1.

### MTTR computation

`MTTR = avg(resolved_at − opened_at)` over the selected window (default 7d), filtered to `stack_id`. Acknowledgement is tracked but not used in the MTTR formula — the user asked for resolved/unresolved tracking, and resolution is the meaningful endpoint. We expose `MTTA = avg(acknowledged_at − opened_at)` as a separate stat in the trend strip if needed later (out of scope for v1).

---

## LLM root cause + dedup

### When the LLM runs

The LLM hypothesis is generated on the **monitor failure event** — specifically when the monitor scheduler creates or updates an incident. There are three triggers:

1. **Incident opened.** First failing run after a healthy state. Always run the LLM.
2. **Signature changes on an open incident.** Run the LLM again so the hypothesis matches the new evidence.
3. **Consecutive same-signature failure, count < 3.** Re-run the LLM. (The first three runs of the same signature still get fresh analysis to give the LLM a chance to incorporate accumulating evidence.)

Once `consecutive_count >= 3` and the signature has not changed, the LLM is **not** called. The cached hypothesis on the incident continues to render as-is.

### Pipeline reuse

The hypothesis call reuses the existing co-pilot tool-calling pipeline (`scanner/copilot/llm.py`, `tool_executor.py`, `context_builder.py`) — the same path the user takes today via the Quick Link. The new wrapper adds:

- A scoped system prompt: "You are diagnosing a monitor failure. Output a JSON object with fields `hypothesis` (≤2 sentence paragraph), `signature` (≤32 char slug, lowercase, hyphenated, e.g. `fivetran-source-stalled`)."
- A constrained context bundle: the failed monitor result, its `explainer.py` structured explanation, the immediate lineage upstream summary, the latest run history of upstream monitors, and recent connector/dbt status if present.
- A budget cap: max ~6 tool calls per analysis (the existing copilot is capped higher; this is a tighter bound for cost containment).

The deterministic owner classifier (`copilot/root_cause.py`) runs **after** the LLM call to attach `owner_system` and `owner_confidence` deterministically from the evidence the LLM gathered.

### Failure modes

If the LLM call fails or times out (>30s), the incident still opens but `llm_hypothesis` is set to a deterministic fallback derived from `explainer.py`'s `status_reason` field, and `signature` is set to a hash of `(monitor_type, threshold_breach_class)` so dedup still works. A retry is queued once with backoff; if it still fails, the user sees the deterministic fallback and an inline "Re-analyze" link on the card.

---

## Architecture

### Backend

- `scanner/incidents/` (new module)
  - `models.py` — Pydantic + ORM definitions for the `incidents` table
  - `lifecycle.py` — open / acknowledge / resolve / auto-recover transitions; idempotent
  - `signature.py` — fallback deterministic signature when LLM is unavailable
- `scanner/copilot/incident_diagnosis.py` (new) — wraps `llm.py` with the scoped prompt, JSON output validation, retry, and ownership classifier
- `scanner/monitors/executor.py` (modify) — after each run, call `lifecycle.handle_run(result)` which decides open/update/auto-resolve based on prior incident state. `lifecycle.handle_run` is synchronous and fast (just DB writes); the LLM diagnosis is fired through `asyncio.create_task` (when called from the FastAPI request path) or a thread pool (when called from the scheduler path). A per-pipeline-profile semaphore caps concurrent diagnosis calls at a configurable default (e.g. 3) to prevent thundering-herd LLM spend when many monitors fail at once.
- `scanner/api/routers/incidents.py` (new) — REST endpoints:
  - `GET /api/v1/incidents?stackId=…&status=…` — list
  - `POST /api/v1/incidents/{id}/acknowledge`
  - `POST /api/v1/incidents/{id}/resolve` — body: `{reason, note?}`
  - `POST /api/v1/incidents/{id}/mute` — body: `{until: ISO8601, reason?}` — sets `muted_until`/`muted_by`/`muted_reason`
  - `POST /api/v1/incidents/{id}/unmute` — clears the three mute fields
  - `POST /api/v1/incidents/{id}/reanalyze` — manual re-run of LLM diagnosis
  - `GET /api/v1/incidents/stats?stackId=…&window=7d` — pass-rate, MTTR, opened count, recovered count, week-over-week deltas

### Frontend

- `app/api/incidents/route.ts` (new) — Next.js proxy to FastAPI
- `app/api/incidents/[id]/acknowledge/route.ts`, `.../resolve/route.ts`, `.../mute/route.ts`, `.../unmute/route.ts`, `.../reanalyze/route.ts` — proxies
- `app/api/incidents/stats/route.ts` (new) — proxy for trend strip
- `components/monitors/SummaryHero.tsx` (new) — colored banner with incident counts + blast radius
- `components/monitors/ActiveIncidents.tsx` (new) — list container, sort logic, polling
- `components/monitors/IncidentCard.tsx` (new) — single card, collapsible evidence, action handlers
- `components/monitors/TrendStrip.tsx` (new) — four-tile row with sparklines and deltas
- `components/monitors/CoverageGaps.tsx` (new) — two-card row for unmonitored critical assets and SLA recommendations
- `components/monitors/DriftSummaryTab.tsx` (replace) — composes the above; current asset rows become `AssetHealthLean.tsx` (failing/warning visible, healthy collapsed)

### Data flow per failure

```
monitor run completes (FAIL)
   │
   ▼
executor.py persists MonitorResult
   │
   ▼
lifecycle.handle_run(result)
   │ ┌── no open incident → open()
   │ │     └── enqueue diagnosis job
   │ ├── open incident, signature unchanged, count<3 → re-run diagnosis
   │ ├── open incident, signature unchanged, count>=3 → increment counter only
   │ └── open incident, signature changed → re-run diagnosis, reset counter
   ▼
diagnosis job (async)
   │ runs incident_diagnosis.diagnose(incident)
   │ writes hypothesis, signature, owner_system to incidents row
   ▼
Summary page polls /api/v1/incidents — re-renders
```

```
monitor run completes (PASS) on a target with an open incident
   │
   ▼
lifecycle.handle_run(result) → resolve(auto_recovered)
   │
   ▼
incident.resolved_at = now; resolved_by = 'system'
   │
   ▼
recovered count in /api/v1/incidents/stats increments
```

---

## Scope and non-goals

**In scope (v1):**
- New `incidents` table and lifecycle (open → acknowledged → resolved with reasons)
- LLM root-cause hypothesis on open + signature-change + same-signature counts < 3
- Deterministic fallback signature + hypothesis when LLM is unavailable
- Auto-recovery on next-run-pass
- Mute/suppression with duration presets (1h / 4h / 1d / 7d / custom) and lazy auto-unmute on read
- Summary page restructure: hero, active incidents, 7-day trend strip, lean asset health, coverage gaps
- Pipeline Health tiles relocated to the Pipeline Monitors tab (this means the Pipeline Monitors tab gets a header strip showing the six tool tiles; otherwise the tab is unchanged)
- Co-pilot handoff that pre-seeds the failure context plus the cached hypothesis
- MTTR + MTTA computed; only MTTR exposed in the trend strip

**Out of scope (v1):**
- Cross-incident grouping ("3 incidents share the same root cause") — every incident stays per-monitor for v1
- Historical incidents page/tab — incident history surfaces only on the watch detail panel for v1
- Incident assignment to specific users beyond `acknowledged_by`
- Notifications on incident state changes — handled by the existing notification routing system, no new wiring required
- Permission scoping beyond pipeline-profile membership (any signed-in user on the workspace can ack/resolve)

---

## Migration and backfill

- New `incidents` table is additive. No existing schema is modified.
- On first deploy after release, a one-shot backfill scans the most recent monitor run per (stack_id, monitor_id) and opens an incident for any currently-failing monitor, with `opened_at = latest_failing_run.started_at`, `signature = 'backfilled'`, and a deterministic fallback hypothesis. The diagnosis job then re-analyzes these in the background as users open the page.
- The current `DriftSummaryTab` is replaced wholesale; no feature flag is required because the new components fully supersede the old ones in a single PR. The current `DATA_CATEGORIES` mapping in `DriftSummaryTab.tsx` and the existing `CategorySparklinePanel` / `AssetHealthRow` components are retained where they continue to add value: `AssetHealthRow` is reused inside `AssetHealthLean` for the failing/warning rows.

---

## Open questions

None at design close. Confirmed during brainstorming:
- Primary job is "Should I be worried right now?" with B/C/D as supporting layers
- Hero is hybrid status pill + lineage-aware active-incidents list
- Card is B-style expanded with collapsible evidence
- LLM dedup signature is emitted by the LLM; runs every failure until 3 consecutive same-signature; signature change resets the counter
- Lifecycle is `open → acknowledged → resolved` with auto-recovery and manual reasons
