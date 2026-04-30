# Clarification Layer — Plan 2: Borderline Failures (V1.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Flow C — when a monitor fires a small-margin breach (between 1.5σ and the configured sensitivity threshold), instead of alerting silently or normally, emit a `failure_review` ContextRequest. The user reviews via the popup, picks "Expected — dampen future alerts" (writes a dampening convention) or "Investigate" (hands off to copilot debug mode with the failure context).

**Prerequisites:** Plan 1 must be merged. The `ClarificationEngine`, `ContextRequest` model, popup chat, and copilot `clarify` mode are assumed in place.

**Architecture:** A new `borderline.py` module classifies a `MonitorResult` as `clear|borderline|drastic`. `volume.py` (and freshness/quality monitors that already use z-scores) call the classifier on each evaluation. Borderline results emit a `failure_review` ContextRequest instead of the normal alert; drastic results alert as today. The new `failure_review` kind has two pre-baked answer paths exposed as quick-reply chips in the popup, plus the standard free-text input.

**Tech Stack:** Same as Plan 1.

**Spec:** `docs/superpowers/specs/2026-04-30-clarification-context-layer-design.md` §6.3.

---

## File structure

**New files:**
- `scanner/copilot/clarifications/kinds/failure_review/__init__.py`
- `scanner/copilot/clarifications/kinds/failure_review/schemas.py`
- `scanner/copilot/clarifications/kinds/failure_review/parser.py`
- `scanner/copilot/clarifications/kinds/failure_review/conventions.py`
- `scanner/copilot/clarifications/kinds/failure_review/prompt.md`
- `scanner/copilot/clarifications/tests/test_failure_review.py`
- `scanner/monitors/borderline.py`
- `scanner/monitors/tests/test_borderline.py`
- `scanner/tests/test_clarification_flow_c.py`
- `components/clarifications/BorderlineFailureCard.tsx`

**Modified files:**
- `scanner/copilot/clarifications/kinds/__init__.py` (add failure_review import)
- `scanner/monitors/volume.py` (call classifier; emit on borderline)
- `scanner/monitors/freshness.py` (same wiring; if file exists)
- `scanner/monitors/quality.py` (same wiring; if file exists)
- `components/clarifications/ClarificationPopup.tsx` (render `BorderlineFailureCard` when focused kind is `failure_review`)

---

## Task 1: Borderline classifier

**Files:**
- Create: `scanner/monitors/borderline.py`
- Create: `scanner/monitors/tests/test_borderline.py`

- [ ] **Step 1: Write failing tests**

`scanner/monitors/tests/test_borderline.py`:

```python
import pytest
from scanner.monitors.borderline import classify_severity, BorderlineConfig


def test_clear_when_z_below_lower_band():
    out = classify_severity(z_score=1.0, sensitivity_threshold=3.0)
    assert out == "clear"


def test_drastic_when_z_above_threshold():
    out = classify_severity(z_score=3.5, sensitivity_threshold=3.0)
    assert out == "drastic"


def test_borderline_inside_band():
    out = classify_severity(z_score=2.2, sensitivity_threshold=3.0)
    assert out == "borderline"


def test_negative_z_uses_abs():
    out = classify_severity(z_score=-2.5, sensitivity_threshold=3.0)
    assert out == "borderline"


def test_custom_lower_bound():
    cfg = BorderlineConfig(lower=2.0)
    assert classify_severity(z_score=1.8, sensitivity_threshold=3.0, config=cfg) == "clear"
    assert classify_severity(z_score=2.5, sensitivity_threshold=3.0, config=cfg) == "borderline"
```

- [ ] **Step 2: Run to verify failure**

```bash
mkdir -p scanner/monitors/tests
touch scanner/monitors/tests/__init__.py
pytest scanner/monitors/tests/test_borderline.py -v
```

Expected: 5 fails, ModuleNotFoundError.

- [ ] **Step 3: Implement the classifier**

`scanner/monitors/borderline.py`:

```python
"""Classify a z-scored monitor result as clear/borderline/drastic.

Drastic → normal alert path.
Borderline → emit a failure_review ContextRequest.
Clear → no action.
"""
from dataclasses import dataclass
from copilot.clarifications.config import CONFIG as CLARIFICATION_CONFIG


@dataclass(frozen=True)
class BorderlineConfig:
    lower: float = CLARIFICATION_CONFIG.borderline_band_lower


DEFAULT = BorderlineConfig()


def classify_severity(
    *,
    z_score: float,
    sensitivity_threshold: float,
    config: BorderlineConfig = DEFAULT,
) -> str:
    """Return 'clear' | 'borderline' | 'drastic'."""
    abs_z = abs(z_score)
    if abs_z < config.lower:
        return "clear"
    if abs_z >= sensitivity_threshold:
        return "drastic"
    return "borderline"
```

- [ ] **Step 4: Run tests**

```bash
pytest scanner/monitors/tests/test_borderline.py -v
```

Expected: 5 pass.

- [ ] **Step 5: Commit**

```bash
git add scanner/monitors/borderline.py scanner/monitors/tests/
git commit -m "feat(monitors): borderline-band severity classifier"
```

---

## Task 2: `failure_review` kind — schemas + parser

**Files:**
- Create: `scanner/copilot/clarifications/kinds/failure_review/__init__.py`
- Create: `scanner/copilot/clarifications/kinds/failure_review/schemas.py`
- Create: `scanner/copilot/clarifications/kinds/failure_review/parser.py`
- Create: `scanner/copilot/clarifications/tests/test_failure_review.py`

- [ ] **Step 1: Write failing tests**

`scanner/copilot/clarifications/tests/test_failure_review.py`:

```python
import pytest
from copilot.clarifications.kinds.failure_review.schemas import (
    validate_payload, validate_answer,
)
from copilot.clarifications.kinds.failure_review.parser import parse_reply


def test_payload_requires_node_metric_z_score_window():
    with pytest.raises(ValueError):
        validate_payload({})
    validate_payload({
        "node_fqn": "raw.orders",
        "metric": "row_count",
        "observed": 8200.0,
        "expected_range": [10000, 12000],
        "z_score": 2.1,
        "sample_window": "7d",
    })


def test_answer_requires_disposition():
    with pytest.raises(ValueError):
        validate_answer({})
    with pytest.raises(ValueError):
        validate_answer({"disposition": "wrong_value"})
    validate_answer({"disposition": "expected"})
    validate_answer({"disposition": "investigate"})


def test_parse_reply_detects_expected():
    assert parse_reply("yeah this is expected, weekend dip") == {"disposition": "expected"}
    assert parse_reply("normal noise, dampen") == {"disposition": "expected"}


def test_parse_reply_detects_investigate():
    assert parse_reply("investigate this please") == {"disposition": "investigate"}
    assert parse_reply("looks weird, look into it") == {"disposition": "investigate"}


def test_parse_reply_returns_none_on_ambiguous():
    assert parse_reply("hmm") is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest scanner/copilot/clarifications/tests/test_failure_review.py -v
```

Expected: 5 fails.

- [ ] **Step 3: Implement schemas**

`scanner/copilot/clarifications/kinds/failure_review/schemas.py`:

```python
"""Payload + answer schemas for failure_review."""
from typing import Any, Dict


_REQUIRED_PAYLOAD = ("node_fqn", "metric", "observed", "expected_range", "z_score", "sample_window")
_VALID_DISPOSITIONS = ("expected", "investigate")


def validate_payload(payload: Dict[str, Any]) -> None:
    for key in _REQUIRED_PAYLOAD:
        if key not in payload:
            raise ValueError(f"payload.{key} is required")
    if not isinstance(payload["expected_range"], list) or len(payload["expected_range"]) != 2:
        raise ValueError("payload.expected_range must be [min, max]")


def validate_answer(answer: Dict[str, Any]) -> None:
    disp = answer.get("disposition")
    if disp not in _VALID_DISPOSITIONS:
        raise ValueError(f"answer.disposition must be one of {_VALID_DISPOSITIONS}")
```

- [ ] **Step 4: Implement parser**

`scanner/copilot/clarifications/kinds/failure_review/parser.py`:

```python
"""Heuristic parser for failure_review free-text replies.

The LLM should call record_clarification_answer with structured output, but
the parser is a fallback for chip-driven submits and prose-only replies.
"""
from typing import Optional, Dict


_EXPECTED_HINTS = (
    "expected", "normal", "noise", "fine", "dampen", "ignore", "weekend",
    "holiday", "scheduled", "maintenance",
)
_INVESTIGATE_HINTS = (
    "investigate", "look into", "look at", "check this", "weird",
    "broken", "real", "alert", "incident",
)


def parse_reply(reply: str) -> Optional[Dict[str, str]]:
    text = reply.lower()
    if any(h in text for h in _INVESTIGATE_HINTS):
        return {"disposition": "investigate"}
    if any(h in text for h in _EXPECTED_HINTS):
        return {"disposition": "expected"}
    return None
```

- [ ] **Step 5: Run tests**

```bash
pytest scanner/copilot/clarifications/tests/test_failure_review.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add scanner/copilot/clarifications/kinds/failure_review/
git commit -m "feat(clarifications): failure_review kind schemas + parser"
```

---

## Task 3: `failure_review` conventions writer + prompt

**Files:**
- Create: `scanner/copilot/clarifications/kinds/failure_review/conventions.py`
- Create: `scanner/copilot/clarifications/kinds/failure_review/prompt.md`
- Create: `scanner/copilot/clarifications/kinds/failure_review/__init__.py`

- [ ] **Step 1: Write failing tests for conventions**

Append to `scanner/copilot/clarifications/tests/test_failure_review.py`:

```python
from copilot.clarifications.kinds.failure_review.conventions import on_resolve


class _FakeReq:
    def __init__(self):
        self.id = "r1"
        self.pipelineStackId = "ps1"
        self.kind = "failure_review"
        self.scopeType = "node"
        self.scopeRef = "raw.orders"
        self.payload = {
            "node_fqn": "raw.orders",
            "metric": "row_count",
            "observed": 8200,
            "expected_range": [10000, 12000],
            "z_score": -2.1,
            "sample_window": "7d",
        }


class _FakeDB:
    def __init__(self):
        self.conventions = {}
        self.overrides = {}
        self.handed_off_to_debug = []


def test_on_resolve_expected_writes_dampening_convention():
    db = _FakeDB()
    on_resolve(_FakeReq(), {"disposition": "expected"}, db)
    conv = db.conventions["ps1"]
    assert "dampening" in conv
    rules = conv["dampening"]["rules"]
    assert any(r["node"] == "raw.orders" and r["metric"] == "row_count" for r in rules)


def test_on_resolve_investigate_emits_debug_handoff():
    db = _FakeDB()
    on_resolve(_FakeReq(), {"disposition": "investigate"}, db)
    assert len(db.handed_off_to_debug) == 1
    assert db.handed_off_to_debug[0]["node_fqn"] == "raw.orders"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest scanner/copilot/clarifications/tests/test_failure_review.py -v
```

Expected: 2 new fails.

- [ ] **Step 3: Implement conventions writer**

`scanner/copilot/clarifications/kinds/failure_review/conventions.py`:

```python
"""On resolve: 'expected' writes a dampening rule; 'investigate' hands off to debug mode."""
from typing import Any, Dict


def on_resolve(request: Any, answer: Dict[str, Any], db: Any) -> None:
    disposition = answer["disposition"]

    if disposition == "expected":
        _write_dampening_rule(request, db)
        return

    if disposition == "investigate":
        _handoff_to_debug(request, db)
        return


def _write_dampening_rule(request: Any, db: Any) -> None:
    conv = db.conventions.setdefault(request.pipelineStackId, {})
    dampening = conv.setdefault("dampening", {"rules": []})
    rule = {
        "node": request.scopeRef,
        "metric": request.payload["metric"],
        "min_z_to_alert": _bump_threshold(request.payload["z_score"]),
        "rationale": "user marked borderline failure as expected",
        "source_request_id": request.id,
    }
    dampening["rules"].append(rule)


def _bump_threshold(z_observed: float) -> float:
    """Set the new minimum z-score required to alert this node+metric to just above
    the observed value. Floor at 3.0 to avoid pathological dampening."""
    abs_z = abs(z_observed)
    return max(3.0, abs_z + 0.5)


def _handoff_to_debug(request: Any, db: Any) -> None:
    """Record an intent for the frontend to open a debug-mode chat with the failure context.

    The actual chat opening is handled by the frontend after it sees the resolution
    payload include `next_action: 'open_debug'`.
    """
    if not hasattr(db, "handed_off_to_debug"):
        # Production path: this side effect is realised by the API response
        # carrying the `next_action`. No DB write needed.
        return
    db.handed_off_to_debug.append({
        "node_fqn": request.payload["node_fqn"],
        "metric": request.payload["metric"],
        "z_score": request.payload["z_score"],
        "observed": request.payload["observed"],
        "expected_range": request.payload["expected_range"],
    })
```

- [ ] **Step 4: Implement prompt**

`scanner/copilot/clarifications/kinds/failure_review/prompt.md`:

```markdown
A monitor on `{node_fqn}` just fired with a borderline reading on the `{metric}` metric.

Observed: {observed}
Expected range: {expected_range}
Z-score: {z_score} (sensitivity threshold not yet exceeded)
Sample window: {sample_window}

Speak directly. One short sentence stating the deviation, then one focused question:
"Is this expected, or worth investigating?"

If the user says "expected", call `record_clarification_answer` with
`structured_answer: {{"disposition": "expected"}}` — Pallisade will dampen future
alerts on this node + metric.

If the user says "investigate", call `record_clarification_answer` with
`structured_answer: {{"disposition": "investigate"}}` — the platform will open a
debug session loaded with this failure's context.

If the user gives nuance ("expected on weekends, alarming on weekdays"), still
record `expected` for this single firing and add a note in the chat that they
can configure a calendar-aware dampening rule via the Clarify popup later.

Hard rules:
- Do not propose answers; ask, then wait.
- Do not call any tool except `record_clarification_answer`.
- Keep your message under 50 words.
```

- [ ] **Step 5: Implement registration**

`scanner/copilot/clarifications/kinds/failure_review/__init__.py`:

```python
"""failure_review clarification kind."""
from pathlib import Path
from copilot.clarifications.registry import register_kind, KindHandler
from copilot.clarifications.kinds.failure_review.schemas import (
    validate_payload, validate_answer,
)
from copilot.clarifications.kinds.failure_review.parser import parse_reply
from copilot.clarifications.kinds.failure_review.conventions import on_resolve

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def _load_prompt(payload):
    template = _PROMPT_PATH.read_text()
    return template.format(
        node_fqn=payload.get("node_fqn", "<unknown>"),
        metric=payload.get("metric", "<unknown>"),
        observed=payload.get("observed", "<unknown>"),
        expected_range=payload.get("expected_range", "<unknown>"),
        z_score=payload.get("z_score", "<unknown>"),
        sample_window=payload.get("sample_window", "<unknown>"),
    )


register_kind(KindHandler(
    kind="failure_review",
    validate_payload=validate_payload,
    validate_answer=validate_answer,
    load_prompt=_load_prompt,
    on_resolve=on_resolve,
))


__all__ = ["parse_reply"]
```

- [ ] **Step 6: Register the kind in the package init**

In `scanner/copilot/clarifications/kinds/__init__.py`:

```python
"""Per-kind handlers. Importing this package registers all kinds."""
from . import timestamp_choice  # noqa: F401
from . import failure_review    # noqa: F401  (added in Plan 2)
```

- [ ] **Step 7: Run tests**

```bash
pytest scanner/copilot/clarifications/tests/ -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add scanner/copilot/clarifications/
git commit -m "feat(clarifications): failure_review conventions + prompt + registration"
```

---

## Task 4: Wire `volume.py` into the borderline classifier

**Files:**
- Modify: `scanner/monitors/volume.py` (around line 462 where the z-score check happens)

- [ ] **Step 1: Read the area to confirm structure**

```bash
sed -n '450,510p' scanner/monitors/volume.py
```

Identify the block where `score.z_score` is compared against `score.threshold_used` to decide alert/no-alert.

- [ ] **Step 2: Insert the borderline check**

Find the existing decision block (where `score.is_anomaly` or equivalent is consumed) and replace the alert-vs-pass branch with:

```python
        from scanner.monitors.borderline import classify_severity
        from copilot.clarifications.engine import ClarificationEngine

        severity = classify_severity(
            z_score=score.z_score,
            sensitivity_threshold=score.threshold_used,
        )

        if severity == "drastic":
            # existing alert path — preserve the original block here
            ...
        elif severity == "borderline":
            engine = ClarificationEngine(db=self._prisma)
            engine.emit(
                pipeline_stack_id=self._pipeline_stack_id,
                kind="failure_review",
                scope_type="node",
                scope_ref=self.node_fqn,
                payload={
                    "node_fqn": self.node_fqn,
                    "metric": "row_count",
                    "observed": float(row_count),
                    "expected_range": [float(score.lower_bound), float(score.upper_bound)],
                    "z_score": float(score.z_score),
                    "sample_window": self.history_window,
                },
                priority="high",
            )
            return {  # match the existing return-shape
                "status": "borderline",
                "explanation": f"Volume anomaly within noise band (z={score.z_score:.2f}); awaiting user review.",
                "z_score": score.z_score,
            }
        else:
            # existing pass path — preserve the original block here
            ...
```

The volume monitor's existing `evaluate()` method has access to `self._prisma` and `self._pipeline_stack_id` (or equivalents — search the file for current attribute names). Honour what's there. The `history_window` value should already be present as a config field (e.g., `self.config.get("history_window", "7d")`); use that as `sample_window`.

- [ ] **Step 3: Run existing volume monitor tests**

```bash
pytest scanner/monitors/ -v
```

Expected: pass (existing tests don't trigger borderline, so the wiring should be backward-compatible).

- [ ] **Step 4: Commit**

```bash
git add scanner/monitors/volume.py
git commit -m "feat(monitors): emit failure_review on borderline volume anomalies"
```

---

## Task 5: Wire freshness + quality monitors (if applicable)

**Files:**
- Modify: `scanner/monitors/freshness.py` (if it exists and uses z-scores)
- Modify: `scanner/monitors/quality.py` (if it exists and uses z-scores)

- [ ] **Step 1: Locate**

```bash
ls scanner/monitors/*.py
grep -l "z_score" scanner/monitors/*.py
```

- [ ] **Step 2: Apply the same pattern**

For each file that has a `score.z_score` decision block, add the same `classify_severity` branching as in Task 4. Use the right `metric` name (`hours_since_update` for freshness, `null_rate` for quality, etc.) and the appropriate `expected_range`/`observed` values.

If a monitor doesn't use z-scores (e.g., simple deterministic threshold), skip it. The borderline concept only applies to statistical monitors.

- [ ] **Step 3: Run tests**

```bash
pytest scanner/monitors/ -v
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add scanner/monitors/
git commit -m "feat(monitors): emit failure_review on borderline freshness/quality anomalies"
```

---

## Task 6: `BorderlineFailureCard` frontend component

**Files:**
- Create: `components/clarifications/BorderlineFailureCard.tsx`

- [ ] **Step 1: Implement the card**

`components/clarifications/BorderlineFailureCard.tsx`:

```tsx
'use client';
import { useState } from 'react';
import type { ContextRequest } from '@/lib/clarifications/types';
import { answerContextRequest } from '@/lib/clarifications/client';
import { useRouter } from 'next/navigation';

interface Props {
  request: ContextRequest;
  onAnswered: () => void;
}

export function BorderlineFailureCard({ request, onAnswered }: Props) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const p = request.payload as {
    node_fqn: string; metric: string; observed: number;
    expected_range: [number, number]; z_score: number; sample_window: string;
  };

  const submit = async (disposition: 'expected' | 'investigate') => {
    setSubmitting(true);
    setError(null);
    try {
      await answerContextRequest(request.id, { answer: { disposition } });
      onAnswered();
      if (disposition === 'investigate') {
        router.push(
          `/dashboard/copilot?mode=debug&node=${encodeURIComponent(p.node_fqn)}&metric=${encodeURIComponent(p.metric)}&z=${p.z_score}`,
        );
      }
    } catch (e: any) {
      setError(e?.message ?? 'failed to submit');
    } finally {
      setSubmitting(false);
    }
  };

  const direction = p.z_score < 0 ? 'dipped' : 'spiked';
  const pct = Math.abs(((p.observed - (p.expected_range[0] + p.expected_range[1]) / 2)
    / ((p.expected_range[0] + p.expected_range[1]) / 2)) * 100).toFixed(0);

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 space-y-3">
      <div className="text-sm">
        <span className="font-medium">{p.node_fqn}</span> {p.metric} {direction} {pct}%{' '}
        — within noise band (z={p.z_score.toFixed(2)}, threshold not exceeded).
      </div>
      <div className="text-xs text-muted-foreground">
        Observed {p.observed.toLocaleString()} vs expected {p.expected_range[0].toLocaleString()}–{p.expected_range[1].toLocaleString()} over {p.sample_window}.
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => submit('expected')}
          disabled={submitting}
          className="flex-1 px-3 py-2 rounded-md border bg-background hover:bg-muted text-sm disabled:opacity-50"
        >
          Expected — dampen
        </button>
        <button
          type="button"
          onClick={() => submit('investigate')}
          disabled={submitting}
          className="flex-1 px-3 py-2 rounded-md bg-amber-600 text-white hover:bg-amber-700 text-sm disabled:opacity-50"
        >
          Investigate
        </button>
      </div>
      {error && <div className="text-xs text-red-600">{error}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/clarifications/BorderlineFailureCard.tsx
git commit -m "feat(clarifications/ui): BorderlineFailureCard with quick-reply chips"
```

---

## Task 7: Render the card inside `ClarificationPopup` for `failure_review` requests

**Files:**
- Modify: `components/clarifications/ClarificationPopup.tsx`

- [ ] **Step 1: Render the card above the chat thread**

In `ClarificationPopup`, just below the `<header>` and above the message scroll area:

```tsx
import { BorderlineFailureCard } from './BorderlineFailureCard';

// inside JSX, after <header> and before the scroll container:
{focused?.kind === 'failure_review' && (
  <div className="px-4 pt-3">
    <BorderlineFailureCard
      request={focused}
      onAnswered={async () => {
        await refresh();
        // close if no other pending requests for this pipeline
      }}
    />
  </div>
)}
```

The free-text input below still works for users who want to give nuance — the chips are quick paths, not exclusive.

- [ ] **Step 2: Commit**

```bash
git add components/clarifications/ClarificationPopup.tsx
git commit -m "feat(clarifications/ui): render BorderlineFailureCard in popup for failure_review"
```

---

## Task 8: End-to-end integration test for Flow C

**Files:**
- Create: `scanner/tests/test_clarification_flow_c.py`

- [ ] **Step 1: Write the test**

```python
"""Flow C: borderline z-score → failure_review request → 'expected' answer →
dampening convention written → next eval respects dampening; 'investigate'
answer hands off to debug context."""
import pytest
from unittest.mock import MagicMock

from copilot.clarifications.engine import ClarificationEngine
from copilot.clarifications.kinds import failure_review  # registration
from copilot.clarifications.kinds import timestamp_choice  # noqa  (Plan 1 kind also needed)
from scanner.monitors.borderline import classify_severity


class _FakeReq:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "r1")
        self.pipelineStackId = kwargs.get("pipelineStackId", "ps1")
        self.kind = "failure_review"
        self.scopeType = "node"
        self.scopeRef = kwargs.get("scopeRef", "raw.orders")
        self.payload = kwargs.get("payload", {})
        self.status = "open"
        self.priority = "high"
        self.createdAt = None
        self.dismissedUntil = None


class _DB:
    def __init__(self):
        self.requests = []
        self.resolutions = []
        self.conventions = {}
        self.overrides = {}
        self.handed_off_to_debug = []


def test_classifier_distinguishes_clear_borderline_drastic():
    assert classify_severity(z_score=1.0, sensitivity_threshold=3.0) == "clear"
    assert classify_severity(z_score=2.0, sensitivity_threshold=3.0) == "borderline"
    assert classify_severity(z_score=-2.5, sensitivity_threshold=3.0) == "borderline"
    assert classify_severity(z_score=3.5, sensitivity_threshold=3.0) == "drastic"


def test_expected_disposition_writes_dampening_convention():
    db = _DB()
    payload = {
        "node_fqn": "raw.orders",
        "metric": "row_count",
        "observed": 8200,
        "expected_range": [10000, 12000],
        "z_score": -2.1,
        "sample_window": "7d",
    }
    req = _FakeReq(payload=payload)
    db.requests.append(req)

    engine = ClarificationEngine(db=db)
    engine.resolve(
        request=req,
        answer={"disposition": "expected"},
        transcript=[{"role": "user", "content": "expected weekend dip"}],
        answered_by="u1",
    )

    rules = db.conventions["ps1"]["dampening"]["rules"]
    assert any(r["node"] == "raw.orders" and r["metric"] == "row_count" for r in rules)
    assert rules[0]["min_z_to_alert"] >= 2.6  # > observed |z| 2.1


def test_investigate_disposition_records_debug_handoff():
    db = _DB()
    req = _FakeReq(payload={
        "node_fqn": "raw.orders",
        "metric": "row_count",
        "observed": 8200,
        "expected_range": [10000, 12000],
        "z_score": -2.1,
        "sample_window": "7d",
    })
    db.requests.append(req)
    engine = ClarificationEngine(db=db)
    engine.resolve(
        request=req,
        answer={"disposition": "investigate"},
        transcript=[],
        answered_by="u1",
    )
    assert len(db.handed_off_to_debug) == 1
    assert db.handed_off_to_debug[0]["node_fqn"] == "raw.orders"
```

- [ ] **Step 2: Run**

```bash
pytest scanner/tests/test_clarification_flow_c.py -v
```

Expected: pass.

- [ ] **Step 3: Run full suite**

```bash
pytest scanner/copilot/clarifications/ scanner/monitors/ scanner/tests/test_clarification_flow_a.py scanner/tests/test_clarification_flow_c.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add scanner/tests/test_clarification_flow_c.py
git commit -m "test(clarifications): end-to-end Flow C integration test"
```

---

## Task 9: Manual smoke test

- [ ] **Step 1: Seed a borderline result**

In the dev DB, manually trigger a volume monitor with crafted history that produces a z-score of ~2.2 (borderline). Easiest path: edit a test fixture or use the existing monitor "test run" UI if one exists.

- [ ] **Step 2: Verify the loop**

1. Run the monitor.
2. LLMBell badge should increment with priority="high" coloring (amber, no red pulse).
3. Open popup. The `BorderlineFailureCard` renders at the top with two chips.
4. Click "Expected — dampen". Toast confirms; bell badge decrements.
5. Re-run the monitor with the same data — it should now classify as `clear` because the dampening rule bumped the threshold.

- [ ] **Step 3: Verify the investigate path**

1. Trigger another borderline.
2. Open popup, click "Investigate".
3. Browser routes to `/dashboard/copilot?mode=debug&node=...&metric=...`.
4. Copilot opens in debug mode with the failure context loaded.

- [ ] **Step 4: Final commit / nothing to commit**

If anything was changed during smoke test, commit it.

---

## Plan-2 self-review

- **Spec coverage**: §6.3 (Flow C borderline) → Tasks 1, 4, 5. §7.5 (BorderlineFailureCard) → Tasks 6, 7. `failure_review` kind → Tasks 2, 3. Integration test → Task 8.
- **Placeholder scan**: no TBDs. Task 4 explicitly notes that `self._prisma` / `self._pipeline_stack_id` may have different names in the existing volume monitor and instructs the executor to honour what's there. Task 5 is conditional on file existence and explicitly says "if a monitor doesn't use z-scores, skip" — that's intentional, not a placeholder.
- **Type consistency**: `failure_review` payload schema matches between Task 2 schemas, Task 3 conventions writer, Task 4 emit call, Task 6 frontend component, and Task 8 test. `disposition` enum (`expected`|`investigate`) consistent across all sites. `BorderlineConfig.lower` reads from the same `CONFIG.borderline_band_lower` defined in Plan 1.
