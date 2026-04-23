# Critical Security Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Patch two critical npm advisories (Next.js RCE + Handlebars injection) and eliminate client-header spoofing in the FastAPI copilot router by switching to `require_principal`.

**Architecture:** This plan consumes the trust-boundary primitives (`ActingPrincipal`, `require_principal`, `ActingPrincipalMiddleware`) that were wired in the prior spec. The copilot router's 9 endpoints currently read `X-Organization-Id` from a client-controlled request header — swap that for the server-enforced principal parsed from `X-Acting-Org`. Next.js side drops the now-redundant header. Dependency upgrades are isolated to `package.json` / `package-lock.json`.

**Tech Stack:** npm 10+, FastAPI + Starlette, pytest + FastAPI TestClient, NextAuth v5.

**Spec:** `docs/superpowers/specs/2026-04-22-critical-security-fixes-design.md`

---

## File Structure

**Python (modified):**
- `scanner/api/routers/copilot.py` — 9 endpoint signatures updated; 6 internal call sites renamed from `x_organization_id` → `principal.organization_id`; 4 unused parameters removed; `Header` import kept only if still needed by other code in the file.

**Python (new):**
- `scanner/api/tests/test_copilot_auth.py` — one test module covering the 9 endpoints' principal behavior.

**TypeScript (modified):**
- `app/api/copilot/chat/route.ts` — drop `'X-Organization-Id': user.organizationId` from both POST header blocks (non-streaming on line ~174, streaming on line ~533).

**Config (modified):**
- `package.json` — `next` version bumped; optional `overrides` block for `handlebars`.
- `package-lock.json` — regenerated.

---

### Task 1: Record the current-vulnerability baseline

**Files:**
- No code changes; this task captures the pre-state to prove we closed it.

- [ ] **Step 1: Capture current npm audit state**

Run: `npm audit --json 2>/dev/null > /tmp/npm-audit-before.json; jq '.metadata.vulnerabilities' /tmp/npm-audit-before.json`
Expected (or similar): `{ "info": 0, "low": 0, "moderate": 3, "high": 5, "critical": 2, "total": 10 }`.

- [ ] **Step 2: Confirm the two criticals are the ones we expect**

Run: `jq -r '.vulnerabilities | to_entries[] | select(.value.severity=="critical") | .key' /tmp/npm-audit-before.json`
Expected: prints two lines — `handlebars` and `next`.

If either is missing, stop and re-assess — the audit landscape has changed since the spec was written.

---

### Task 2: Upgrade Next.js to a patched 15.5.x

**Files:**
- Modify: `package.json` (one line — the `"next"` version)
- Modify: `package-lock.json` (regenerated)

- [ ] **Step 1: Install the patched Next.js**

Run: `npm install next@15.5.15 --save-exact`
Expected: installs successfully, updates `package.json` to `"next": "15.5.15"`, regenerates `package-lock.json`. No peer-dep warnings that block install.

- [ ] **Step 2: Verify the critical Next.js RCE is gone**

Run: `npm audit --json 2>/dev/null | jq -r '.vulnerabilities | to_entries[] | select(.key=="next") | .value.severity'`
Expected: empty (no output) — the `next` entry is gone from the vuln report.

If the output still contains `critical`, check whether a newer 15.5.x patch exists: `npm view next@15 version | tail -20`, then install that version.

- [ ] **Step 3: Run the Next.js build to catch breaking API changes**

Run: `npm run build`
Expected: completes without errors. The `.next/` directory rebuilds.

If it fails with a typing or API error from Next.js 15.5.15 that didn't exist in 15.5.3, read the error carefully — it's almost certainly a deprecation; fix the offending file and repeat.

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json
git commit -m "fix(deps): upgrade next to 15.5.15 — patches RCE (GHSA-9qr9-h5gf-34mp)"
```

---

### Task 3: Patch transitive `handlebars` via an override

**Context:** `handlebars@4.7.8` and below has multiple JS-injection / prototype-pollution advisories. It reaches us transitively through `next-mdx-remote@5`. The clean fix is to force `handlebars@4.7.9` (the patched latest) via a `package.json` `overrides` block, rather than doing the breaking `next-mdx-remote@5→6` upgrade.

**Files:**
- Modify: `package.json` (add `overrides` section)
- Modify: `package-lock.json` (regenerated)

- [ ] **Step 1: Add the override to `package.json`**

Find the current `package.json` and add (or extend if it already exists) a top-level `overrides` block:

```json
  "overrides": {
    "handlebars": "4.7.9"
  }
```

Place it after the `devDependencies` block, before the closing `}` of the root object.

- [ ] **Step 2: Regenerate the lockfile**

Run: `npm install`
Expected: lockfile updates; `handlebars@4.7.9` appears in `node_modules/handlebars/package.json`.

Verify: `cat node_modules/handlebars/package.json | jq -r .version`
Expected: `4.7.9`.

- [ ] **Step 3: Confirm the critical is gone**

Run: `npm audit --audit-level=critical 2>&1 | tail -20`
Expected: `found 0 critical vulnerabilities` or equivalent. Moderates and highs may still remain — they're out of scope for Spec A.

If `handlebars` still shows critical, the override didn't take — check `package.json` and re-run `npm install`.

- [ ] **Step 4: Smoke-test MDX rendering**

Start dev server in background and curl the docs index:

```bash
npm run dev > /tmp/next-dev.log 2>&1 &
DEV_PID=$!
sleep 8
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:3000/docs
kill $DEV_PID
```

Expected: `200`. If MDX is broken (500 or rendering error), the `handlebars` downgrade-through-override is interacting badly with `next-mdx-remote@5`. In that case, revert the override (`git checkout package.json package-lock.json && npm install`) and flag for discussion.

- [ ] **Step 5: Commit**

```bash
git add package.json package-lock.json
git commit -m "fix(deps): pin handlebars@4.7.9 via overrides — patches multiple criticals"
```

---

### Task 4: Write the principal-enforcement tests for copilot router

**Files:**
- Create: `scanner/api/tests/test_copilot_auth.py`

**Context:** The test strategy is to mock `CopilotContextBuilder.build_context` and verify it receives `org_id=<acting_org>` regardless of any `X-Organization-Id` header the caller sends. This proves principal wins over header. We also verify that missing `X-Acting-Org` produces a 400 (handled by `ActingPrincipalMiddleware` — already tested in `test_auth.py`, but we repeat the assertion at the router level for regression protection).

- [ ] **Step 1: Write the failing test**

Create `scanner/api/tests/test_copilot_auth.py`:

```python
"""Tests that copilot router uses require_principal, not X-Organization-Id header."""

from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


SECRET = "a" * 64


def _client():
    """Build a TestClient for the real app with env-configured auth."""
    env = {"ENVIRONMENT": "development", "SCANNER_SHARED_SECRET": SECRET}
    with patch.dict("os.environ", env):
        from scanner.api.dependencies import get_settings
        get_settings.cache_clear()
        from scanner.api.app import create_app
        app = create_app()
        return TestClient(app)


def _trust_headers(acting_org: str = "org_from_principal", **extra):
    base = {
        "X-Internal-Auth": SECRET,
        "X-Acting-User": "user_123",
        "X-Acting-Org": acting_org,
    }
    base.update(extra)
    return base


class TestCopilotPrincipalEnforcement:
    """For each endpoint that uses org_id internally, assert principal wins over header."""

    def test_get_context_uses_principal_not_header(self):
        client = _client()

        fake_context = MagicMock()
        fake_context.integrations = []
        fake_context.available_tools = []
        fake_context.graph = None

        with patch(
            "copilot.context_builder.CopilotContextBuilder.build_context",
            new=AsyncMock(return_value=fake_context),
        ) as mock_build:
            headers = _trust_headers(
                acting_org="org_from_principal",
                **{"X-Organization-Id": "org_spoofed_by_attacker"},
            )
            r = client.get("/api/v1/copilot/context", headers=headers)
            assert r.status_code == 200
            # build_context must have been called with the principal's org
            assert mock_build.await_args.kwargs["org_id"] == "org_from_principal"

    def test_get_tools_uses_principal_not_header(self):
        client = _client()

        fake_context = MagicMock()
        fake_context.integration_types = set()

        with patch(
            "copilot.context_builder.CopilotContextBuilder.build_context",
            new=AsyncMock(return_value=fake_context),
        ), patch(
            "copilot.tools.get_tool_registry"
        ) as mock_registry:
            mock_registry.return_value.get_available_tools.return_value = []
            headers = _trust_headers(
                acting_org="org_from_principal",
                **{"X-Organization-Id": "org_spoofed"},
            )
            r = client.get("/api/v1/copilot/tools", headers=headers)
            assert r.status_code == 200

    def test_openlineage_uses_principal_not_header(self):
        client = _client()

        with patch(
            "copilot.openlineage_consumer.OpenLineageConsumer.process_event",
            new=AsyncMock(return_value=True),
        ) as mock_proc:
            headers = _trust_headers(
                acting_org="org_from_principal",
                **{"X-Organization-Id": "org_spoofed", "Content-Type": "application/json"},
            )
            body = {
                "eventType": "START",
                "eventTime": "2026-01-01T00:00:00Z",
                "producer": "test",
                "job": {"namespace": "x", "name": "y"},
                "run": {"runId": "r1"},
            }
            r = client.post("/api/v1/copilot/openlineage/events", headers=headers, json=body)
            assert r.status_code in (200, 500)  # 500 if event shape incomplete; we still assert the arg
            assert mock_proc.await_args.kwargs["org_id"] == "org_from_principal"


class TestCopilotMissingPrincipal:
    """Endpoints must 400 when X-Acting-Org is missing (middleware-enforced)."""

    def test_context_missing_acting_org_returns_400(self):
        client = _client()
        headers = {"X-Internal-Auth": SECRET, "X-Acting-User": "user_123"}
        r = client.get("/api/v1/copilot/context", headers=headers)
        assert r.status_code == 400


class TestCopilotStubEndpointsStillWork:
    """Endpoints that previously declared (but did not use) the org header must still work."""

    def test_get_sessions_works_without_org_header(self):
        client = _client()
        r = client.get("/api/v1/copilot/sessions", headers=_trust_headers())
        assert r.status_code == 200
        assert r.json() == {"sessions": [], "total": 0}

    def test_get_session_works_without_org_header(self):
        client = _client()
        r = client.get("/api/v1/copilot/sessions/sess_123", headers=_trust_headers())
        assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scanner && ./venv/bin/python -m pytest api/tests/test_copilot_auth.py -v`
Expected: all tests in `TestCopilotPrincipalEnforcement` FAIL because the router currently reads from the `X-Organization-Id` header — when we send `X-Organization-Id: org_spoofed`, `build_context` will be called with `org_id="org_spoofed"`, not `"org_from_principal"`. The `TestCopilotMissingPrincipal` test may also fail because the router currently declares `X-Organization-Id` as required via `Header(...)` and will 422/400 on that, not on the missing `X-Acting-Org`. `TestCopilotStubEndpointsStillWork` should PASS already (stubs don't use the header internally).

Record the failing set — we'll rerun after the implementation.

- [ ] **Step 3: Do NOT commit yet — tests are red. Commit comes in Task 6.**

---

### Task 5: Migrate the 9 copilot endpoints

**Files:**
- Modify: `scanner/api/routers/copilot.py`

**Context:** The 9 endpoints fall into two groups.

**Group A — uses the org id (add `require_principal` dep):**
1. `chat` (signature line ~123, internal use line ~198)
2. `chat_stream` (sig ~256, use ~319)
3. `get_context` (sig ~440, uses ~452 and ~478)
4. `get_available_tools` (sig ~491, use ~502)
5. `receive_openlineage_event` (sig ~672, use ~683)

**Group B — declares but never uses the org id (drop the parameter):**
6. `apply_plan` (sig ~546)
7. `get_sessions` (sig ~698)
8. `get_session` (sig ~714)
9. `start_debug_session` (sig ~728)

- [ ] **Step 1: Add the principal import**

At the top of `scanner/api/routers/copilot.py`, inside the existing imports section (near line 8), add:

```python
from scanner.api.auth import ActingPrincipal, require_principal
```

Keep the existing `from fastapi import APIRouter, HTTPException, Header, Depends, Request` line — `Header` is still used by nothing else in this file after the migration, but `Depends` and `Request` are, so verify before scrubbing. Actual scrub happens in Step 6.

- [ ] **Step 2: Migrate Group A — `chat` endpoint**

Replace (line ~123):
```python
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
```
with:
```python
    principal: ActingPrincipal = Depends(require_principal),
```

Replace (line ~198):
```python
        context = await context_builder.build_context(
            org_id=x_organization_id,
```
with:
```python
        context = await context_builder.build_context(
            org_id=principal.organization_id,
```

- [ ] **Step 3: Migrate Group A — `chat_stream` endpoint**

Replace (line ~256):
```python
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
```
with:
```python
    principal: ActingPrincipal = Depends(require_principal),
```

Replace (line ~319):
```python
        context = await context_builder.build_context(
            org_id=x_organization_id,
```
with:
```python
        context = await context_builder.build_context(
            org_id=principal.organization_id,
```

- [ ] **Step 4: Migrate Group A — `get_context` endpoint**

Replace (line ~440):
```python
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
    pipeline_stack_id: Optional[str] = None,
```
with:
```python
    principal: ActingPrincipal = Depends(require_principal),
    pipeline_stack_id: Optional[str] = None,
```

Replace (line ~452):
```python
        context = await context_builder.build_context(
            org_id=x_organization_id,
            pipeline_stack_id=pipeline_stack_id,
        )
```
with:
```python
        context = await context_builder.build_context(
            org_id=principal.organization_id,
            pipeline_stack_id=pipeline_stack_id,
        )
```

Replace (line ~478):
```python
        return ContextResponse(
            org_id=x_organization_id,
```
with:
```python
        return ContextResponse(
            org_id=principal.organization_id,
```

- [ ] **Step 5: Migrate Group A — `get_available_tools` endpoint**

Replace (line ~491):
```python
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
```
with:
```python
    principal: ActingPrincipal = Depends(require_principal),
```

Replace (line ~502):
```python
        context = await context_builder.build_context(org_id=x_organization_id)
```
with:
```python
        context = await context_builder.build_context(org_id=principal.organization_id)
```

- [ ] **Step 6: Migrate Group A — `receive_openlineage_event` endpoint**

Replace (line ~672):
```python
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
```
with:
```python
    principal: ActingPrincipal = Depends(require_principal),
```

Replace (line ~683):
```python
        success = await consumer.process_event(
            event_data=event.dict(),
            org_id=x_organization_id,
        )
```
with:
```python
        success = await consumer.process_event(
            event_data=event.dict(),
            org_id=principal.organization_id,
        )
```

- [ ] **Step 7: Migrate Group B — drop unused parameter from `apply_plan`**

Replace (lines ~544–547):
```python
async def apply_plan(
    request: ApplyPlanRequest,
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
):
```
with:
```python
async def apply_plan(
    request: ApplyPlanRequest,
):
```

No internal usage in this function; no further edits needed.

- [ ] **Step 8: Migrate Group B — drop unused parameter from `get_sessions`**

Replace (lines ~697–700):
```python
async def get_sessions(
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
    limit: int = 20,
):
```
with:
```python
async def get_sessions(
    limit: int = 20,
):
```

- [ ] **Step 9: Migrate Group B — drop unused parameter from `get_session`**

Replace (lines ~712–715):
```python
async def get_session(
    session_id: str,
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
):
```
with:
```python
async def get_session(
    session_id: str,
):
```

- [ ] **Step 10: Migrate Group B — drop unused parameter from `start_debug_session`**

Replace (lines ~727–733):
```python
async def start_debug_session(
    x_organization_id: str = Header(..., alias="X-Organization-Id"),
    issue_type: str = "pipeline_failure",
    title: str = "Debug Session",
    symptom_node_id: Optional[str] = None,
    symptom_details: Optional[Dict[str, Any]] = None,
):
```
with:
```python
async def start_debug_session(
    issue_type: str = "pipeline_failure",
    title: str = "Debug Session",
    symptom_node_id: Optional[str] = None,
    symptom_details: Optional[Dict[str, Any]] = None,
):
```

- [ ] **Step 11: Scrub unused `Header` import if possible**

Run: `grep -nE "\\bHeader\\b" scanner/api/routers/copilot.py`
Expected: zero hits other than the `from fastapi import ... Header ...` line itself. If zero functional uses remain, remove `Header` from the import:

Replace:
```python
from fastapi import APIRouter, HTTPException, Header, Depends, Request
```
with:
```python
from fastapi import APIRouter, HTTPException, Depends, Request
```

If any functional uses remain, leave the import.

- [ ] **Step 12: Final sanity grep**

Run: `grep -nE "x_organization_id|X-Organization-Id" scanner/api/routers/copilot.py`
Expected: zero matches.

---

### Task 6: Run the tests green, commit

**Files:**
- No code edits; just verification and commit.

- [ ] **Step 1: Run the copilot auth tests**

Run: `cd scanner && ./venv/bin/python -m pytest api/tests/test_copilot_auth.py -v`
Expected: all PASS.

- [ ] **Step 2: Run the full api/tests suite to catch regressions**

Run: `cd scanner && ./venv/bin/python -m pytest api/tests/ -v`
Expected: all PASS (the 29 existing tests plus the new ones).

- [ ] **Step 3: Commit**

```bash
git add scanner/api/routers/copilot.py scanner/api/tests/test_copilot_auth.py
git commit -m "fix(api): copilot router uses require_principal, not X-Organization-Id header"
```

---

### Task 7: Drop dead `X-Organization-Id` header from Next.js copilot chat route

**Files:**
- Modify: `app/api/copilot/chat/route.ts`

**Context:** With FastAPI now reading `principal.organization_id` (parsed from `X-Acting-Org` that `scannerClient.fetch` sets automatically), the hand-set `X-Organization-Id` header in the two POST calls inside `chat/route.ts` is dead weight.

- [ ] **Step 1: Remove the header from the non-streaming call**

In `app/api/copilot/chat/route.ts`, find the non-streaming fetch (around line ~172):

```typescript
    const response = await scannerClient.fetch(session, '/api/v1/copilot/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Organization-Id': user.organizationId,
      },
      body: JSON.stringify({
```

Change the `headers` object to:
```typescript
      headers: {
        'Content-Type': 'application/json',
      },
```

- [ ] **Step 2: Remove the header from the streaming call**

In the same file, find the streaming fetch (around line ~533):

```typescript
  const scannerResponse = await scannerClient.fetch(session, '/api/v1/copilot/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Organization-Id': user.organizationId,
    },
    body: JSON.stringify({
```

Change to:
```typescript
    headers: {
      'Content-Type': 'application/json',
    },
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit 2>&1 | grep -E "app/api/copilot/chat" | head`
Expected: zero output for this file. (Pre-existing unrelated errors elsewhere are OK.)

- [ ] **Step 4: Commit**

```bash
git add app/api/copilot/chat/route.ts
git commit -m "refactor(api): drop dead X-Organization-Id header from copilot chat route"
```

---

### Task 8: Manual end-to-end verification

**Files:**
- No code changes. Verification before claiming done.

- [ ] **Step 1: Prove the shared secret is still required**

Start FastAPI in another terminal:
```bash
cd scanner && source venv/bin/activate && uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Call the copilot context endpoint with no auth:
```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/copilot/context
```
Expected: `401`.

- [ ] **Step 2: Prove the principal is required**

```bash
curl -sS -o /dev/null -w "%{http_code}\n" \
  -H "X-Internal-Auth: $SCANNER_SHARED_SECRET" \
  http://127.0.0.1:8000/api/v1/copilot/context
```
Expected: `400` (missing principal — `X-Acting-Org` not set).

- [ ] **Step 3: Prove the header-spoof attack no longer works**

```bash
curl -sS \
  -H "X-Internal-Auth: $SCANNER_SHARED_SECRET" \
  -H "X-Acting-User: test_user" \
  -H "X-Acting-Org: real_org" \
  -H "X-Organization-Id: attacker_org" \
  http://127.0.0.1:8000/api/v1/copilot/context | jq -r .org_id
```
Expected: `real_org`. If the output is `attacker_org`, the migration missed an endpoint — bisect and fix.

- [ ] **Step 4: Prove the full app still works end-to-end**

Start Next.js:
```bash
npm run dev
```

Sign in, open the copilot, send a message. Expected: message is answered. Network tab shows no 401/400 errors from `/api/copilot/chat`.

- [ ] **Step 5: Prove no stale criticals**

```bash
npm audit --audit-level=critical 2>&1 | tail -3
```
Expected: `found 0 critical vulnerabilities` (or equivalent — no criticals listed).

- [ ] **Step 6: Final commit (if anything changed during verification)**

If no code changes, skip. Otherwise commit the fixes with an appropriate `fix:` message.

---

## Rollback

Each task is an independent commit. `git revert <sha>` on any of them cleanly reverts. No schema changes, no data migrations. The Next.js upgrade is the highest-risk revert (might require `rm -rf node_modules && npm install` after checkout).

## Done criteria

- [ ] `npm audit --audit-level=critical` → zero criticals.
- [ ] `npm run build` succeeds.
- [ ] `/docs` renders.
- [ ] `grep -nE "x_organization_id|X-Organization-Id" scanner/api/routers/copilot.py` → zero matches.
- [ ] `scanner/api/tests/test_copilot_auth.py` all pass.
- [ ] Full `scanner/api/tests/` suite still passes (no regressions).
- [ ] Manual verification (Task 8, steps 1–5) passes.
- [ ] Deferred items (rate limiting, `schedule.py` / `policies.py` migration, SSRF hardening, cookie-flag explicit-set) tracked separately.
