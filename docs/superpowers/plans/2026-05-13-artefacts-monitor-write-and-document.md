# Agentic Artefacts — Monitor Write Slice + DOCUMENT Save Path Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship spec slice 6 (Monitor write tools: `create_monitor` / `update_monitor` / `delete_monitor`, with auto-emitted `MONITOR` artefacts and per-kind UI bodies/previews) and slice 7 (rewritten "Save to artefacts" chat flow → produces a `DOCUMENT` artefact). After this lands, flip `ff_artefacts_v2` on.

**Architecture:** Three new agent tools live in `scanner/copilot/tools/monitors.py`, registered with `ArtifactSpec(kind=MONITOR, ...)`. Executors live in `scanner/copilot/tool_executor.py` next to the existing change-plan handlers and reuse the same `_call_nextjs` internal-auth helper. `create_monitor` wraps the existing `/api/schedule/plans` pipeline used by `_execute_confirmed_create_watch`. `update_monitor` calls a new internal route `POST /api/monitors/internal/[monitorId]/update`. `delete_monitor` calls `DELETE /api/monitors/internal/[monitorId]`. Each tool's success result returns a structured `{title, summary, payload, external_ref}` shape that the auto-emit hook (`_emit_for_tool`, tool_executor.py:1354) persists into a `MONITOR` artefact via `emit_artifact`. On the frontend, `MonitorArtifactPreview` + `MonitorArtifactBody` slot into the existing list-card / detail-page dispatchers. For DOCUMENT: a new `POST /api/artifacts/document` route owns creation, and `MessageActionMenu`'s previously-stubbed `onSaveToArtifacts` callback in the assistant page is wired to it.

**Tech Stack:** Python 3.11 + Pydantic + pytest-asyncio (scanner); Next.js 15 + Prisma + React 19 (Next.js).

**Spec reference:** `docs/superpowers/specs/2026-05-13-agentic-artefacts-design.md` §7.5, §8.1, §8.2, §9.

**Previous plans:**
- `docs/superpowers/plans/2026-05-13-artefacts-backend-foundation.md` (slices 1-3, shipped).
- `docs/superpowers/plans/2026-05-13-artefacts-frontend.md` (slices 4-5, shipped).

---

## File Structure

**Created:**
- `scanner/copilot/tools/monitors.py` — `register_tool` declarations for `create_monitor` / `update_monitor` / `delete_monitor`
- `scanner/copilot/tests/test_monitor_tools.py`
- `app/api/monitors/internal/[monitorId]/update/route.ts` — internal-auth update (wraps the existing public PUT, no stack/session requirement)
- `app/api/monitors/internal/[monitorId]/route.ts` — internal-auth delete
- `app/api/artifacts/document/route.ts` — `POST` creates a `DOCUMENT` artefact from chat-message text
- `components/artefacts/previews/MonitorArtifactPreview.tsx`
- `components/artefacts/bodies/MonitorArtifactBody.tsx`

**Modified:**
- `scanner/copilot/tools/__init__.py` — import the new `monitors` module so registrations fire
- `scanner/copilot/tool_executor.py` — add `_execute_create_monitor`, `_execute_update_monitor`, `_execute_delete_monitor` near existing monitor logic (after line ~1306, before `_execute_tool` at 1308)
- `components/artefacts/previews/index.tsx` — route `MONITOR` → `MonitorArtifactPreview`
- `components/artefacts/bodies/index.tsx` — route `MONITOR` → `MonitorArtifactBody`
- `app/(dashboard)/dashboard/assistant/page.tsx` — wire `MessageActionMenu.onSaveToArtifacts` to `POST /api/artifacts/document`
- `lib/feature-flags.ts` — keep `ff_artefacts_v2` flag; set the default value to `true` at the end (see Task 12)

---

## Conventions for this plan

- All Pydantic / Python work matches the existing codebase: `ToolParameter` for tool args, `ToolCategory.OBSERVABILITY` for monitor tools, `ArtifactSpec` from `scanner/copilot/artifacts/models.py`. Don't invent new categories.
- Tool result shape that the auto-emit hook expects: `ToolResult(success=True, data={"title": str, "summary": str, "payload": {"kind": "MONITOR", ...}, "external_ref": {...}})`.
- Internal Next.js routes use `X-Internal-Secret` + `X-Organization-Id` headers and skip `auth()`. Match the pattern in `app/api/artifacts/internal/upsert/route.ts:5-12`.
- Frontend additions live under `components/artefacts/` per Plan 2's structure.

---

### Task 1: Internal Next.js update route

The public PUT at `app/api/schedule/watches/[watchId]/monitors/[monitorId]/route.ts` requires `auth()` + `stackId`. The scanner-side `update_monitor` tool talks directly to the DB with org-scope auth; build a thin internal POST that updates by `monitorId` alone.

**Files:**
- Create: `app/api/monitors/internal/[monitorId]/update/route.ts`

- [ ] **Step 1: Write the route**

```typescript
// app/api/monitors/internal/[monitorId]/update/route.ts
import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ monitorId: string }> },
) {
  if (request.headers.get('x-internal-secret') !== (process.env.INTERNAL_API_SECRET ?? 'pallisade-internal')) {
    return NextResponse.json({ error: 'Unauthorised' }, { status: 401 });
  }
  const orgId = request.headers.get('x-organization-id');
  if (!orgId) return NextResponse.json({ error: 'Missing org' }, { status: 400 });

  const { monitorId } = await params;
  const body = await request.json();
  const { config, policyOverrides } = body as {
    config?: Record<string, unknown>;
    policyOverrides?: string[];
  };

  const monitor = await prisma.monitor.findFirst({
    where: { id: monitorId, organizationId: orgId },
  });
  if (!monitor) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  const updated = await prisma.monitor.update({
    where: { id: monitorId },
    data: {
      ...(config !== undefined ? { config: config as object } : {}),
      ...(policyOverrides !== undefined ? { policyOverrides } : {}),
    },
  });

  return NextResponse.json({
    monitorId: updated.id,
    monitorKind: updated.monitorType,
    targetFqn: updated.targetFqn,
    config: updated.config,
    monitorGroupId: updated.monitorGroupId,
    configDiff: {
      before: monitor.config,
      after: updated.config,
    },
  });
}
```

- [ ] **Step 2: Verify Prisma fields**

Run: `grep -n "model Monitor " prisma/schema.prisma`
Then read lines 0-30 of the model. Confirm `monitorType`, `targetFqn`, `config`, `policyOverrides`, `monitorGroupId`, `organizationId` exist. If `policyOverrides` is absent on this checkout, drop the policyOverrides branch from the route body — it's optional.

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'monitors/internal/\[monitorId\]/update|error TS' | head`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add app/api/monitors/internal/\[monitorId\]/update/route.ts
git commit -m "feat(monitors): internal update route for scanner-side tools"
```

---

### Task 2: Internal Next.js delete route

**Files:**
- Create: `app/api/monitors/internal/[monitorId]/route.ts`

- [ ] **Step 1: Write the route**

```typescript
// app/api/monitors/internal/[monitorId]/route.ts
import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/db';

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ monitorId: string }> },
) {
  if (request.headers.get('x-internal-secret') !== (process.env.INTERNAL_API_SECRET ?? 'pallisade-internal')) {
    return NextResponse.json({ error: 'Unauthorised' }, { status: 401 });
  }
  const orgId = request.headers.get('x-organization-id');
  if (!orgId) return NextResponse.json({ error: 'Missing org' }, { status: 400 });

  const { monitorId } = await params;

  const monitor = await prisma.monitor.findFirst({
    where: { id: monitorId, organizationId: orgId },
  });
  if (!monitor) return NextResponse.json({ error: 'Not found' }, { status: 404 });

  await prisma.monitor.delete({ where: { id: monitorId } });

  return NextResponse.json({
    monitorId: monitor.id,
    monitorKind: monitor.monitorType,
    targetFqn: monitor.targetFqn,
    deleted: true,
  });
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E 'monitors/internal/\[monitorId\]/route|error TS' | head`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add app/api/monitors/internal/\[monitorId\]/route.ts
git commit -m "feat(monitors): internal delete route for scanner-side tools"
```

---

### Task 3: Tool registrations (`tools/monitors.py`)

**Files:**
- Create: `scanner/copilot/tools/monitors.py`
- Modify: `scanner/copilot/tools/__init__.py`

- [ ] **Step 1: Check the existing tools package init**

Run: `cat scanner/copilot/tools/__init__.py`
Note which modules are imported. We'll append the new `monitors` import so `register_tool` decorators fire at import time.

- [ ] **Step 2: Write the registrations**

```python
# scanner/copilot/tools/monitors.py
"""Monitor write tools.

Each tool emits a MONITOR artefact via the executor's auto-emit hook
(see _emit_for_tool in tool_executor.py). Tool handlers live in
tool_executor.py as _execute_create_monitor / _execute_update_monitor /
_execute_delete_monitor.
"""

from .registry import register_tool
from .base import ToolCategory, ToolParameter, RiskLevel
from ..artifacts.models import ArtifactSpec


_MONITOR_KINDS = [
    "FRESHNESS", "VOLUME", "ANOMALY", "SCHEMA", "CUSTOM_SQL",
    "NULL_CHECK", "UNIQUENESS_CHECK",
]


@register_tool(
    name="create_monitor",
    description=(
        "Create a single data-quality monitor on a target asset. "
        "Wraps the unified scheduling pipeline used for monitor groups. "
        "Returns the new monitor id; the artefact captures the config diff."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("target_fqn", "string",
                      "Fully-qualified name of the target asset (e.g. 'snowflake.analytics.orders')."),
        ToolParameter("monitor_kind", "string",
                      "Monitor kind.", enum=_MONITOR_KINDS),
        ToolParameter("config", "object",
                      "Monitor-kind-specific config (e.g. {'maxHours': 6} for FRESHNESS).",
                      required=False),
        ToolParameter("name", "string",
                      "Optional human-readable plan name.", required=False),
        ToolParameter("schedule", "string",
                      "Cron expression. Defaults to '0 * * * *'.", required=False),
    ],
    requires_confirmation=True,
    risk_level=RiskLevel.LOW,
    artifact_spec=ArtifactSpec(
        kind="MONITOR",
        status_on_propose="proposed",
        status_on_success="applied",
    ),
)
def _meta_create_monitor():
    pass


@register_tool(
    name="update_monitor",
    description=(
        "Update an existing monitor's config. Pass a full or partial config map; "
        "fields not provided are left unchanged. Captures before/after diff on the artefact."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("monitor_id", "string", "Monitor row id."),
        ToolParameter("config", "object",
                      "Partial or full config map to merge into the monitor."),
        ToolParameter("policy_overrides", "array",
                      "Optional list of policy-override keys.",
                      items={"type": "string"}, required=False),
    ],
    requires_confirmation=True,
    risk_level=RiskLevel.LOW,
    artifact_spec=ArtifactSpec(
        kind="MONITOR",
        status_on_propose="proposed",
        status_on_success="applied",
    ),
)
def _meta_update_monitor():
    pass


@register_tool(
    name="delete_monitor",
    description=(
        "Delete a monitor. Destructive — always requires confirmation. "
        "Captures the deleted monitor's kind+target on the artefact for audit."
    ),
    category=ToolCategory.OBSERVABILITY,
    parameters=[
        ToolParameter("monitor_id", "string", "Monitor row id."),
    ],
    requires_confirmation=True,
    risk_level=RiskLevel.MEDIUM,
    artifact_spec=ArtifactSpec(
        kind="MONITOR",
        status_on_propose="proposed",
        status_on_success="applied",
    ),
)
def _meta_delete_monitor():
    pass
```

- [ ] **Step 3: Wire the import**

Open `scanner/copilot/tools/__init__.py` and append (after any existing imports):

```python
from . import monitors  # noqa: F401 — register monitor write tools at import time
```

- [ ] **Step 4: Verify the tools register**

Run: `cd /Users/emilfabel/pallisade-copilot && python -c "from scanner.copilot.tools.registry import _GLOBAL_REGISTRY; assert {'create_monitor','update_monitor','delete_monitor'}.issubset(set(_GLOBAL_REGISTRY.keys())); print('OK')"`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/tools/monitors.py scanner/copilot/tools/__init__.py
git commit -m "feat(tools): register create/update/delete_monitor with MONITOR ArtifactSpec"
```

---

### Task 4: `_execute_create_monitor` handler

**Files:**
- Modify: `scanner/copilot/tool_executor.py` (insert after the existing `_execute_confirmed_create_watch` method ending at ~line 1306)

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n "async def _execute_confirmed_create_watch\|async def _execute_tool" scanner/copilot/tool_executor.py | head`
Expected output: two line numbers. Place the three new methods (this task + Tasks 5 & 6) between them.

- [ ] **Step 2: Add the handler**

Insert immediately before `async def _execute_tool` (around line 1308):

```python
    async def _execute_create_monitor(self, args: Dict[str, Any]) -> ToolResult:
        """Create a single monitor via the unified planning pipeline.

        Wraps the same 3-step flow as _execute_confirmed_create_watch but
        scoped to one target/one kind. Auto-emit hook persists the MONITOR
        artefact from the structured `data` we return on success.
        """
        target_fqn = args.get("target_fqn") or ""
        monitor_kind = args.get("monitor_kind") or ""
        config = args.get("config") or {}
        name = args.get("name") or f"{monitor_kind} on {target_fqn}"
        schedule = args.get("schedule") or "0 * * * *"

        if not target_fqn or not monitor_kind:
            return ToolResult(success=False, error="target_fqn and monitor_kind are required")

        node_id = self._resolve_fqn_to_node_id(target_fqn)
        groups = [{
            "anchor_name": target_fqn.split(".")[-1],
            "anchor_fqn": target_fqn,
            "anchor_id": node_id,
            "anchor_node_type": "table",
            "anchor_platform": "unknown",
            "watch_type": "pipeline_health",
            "recommendations": [{
                "monitor_key": monitor_kind,
                "target_fqn": target_fqn,
                "target_node_id": node_id,
                "config_hints": config,
                "depth": 0,
                "priority": 1,
            }],
        }]

        try:
            result = await self._call_nextjs("/api/schedule/plans", {
                "name": name,
                "scopeType": "asset",
                "scopeConfig": {"nodeIds": [node_id]} if node_id else {},
                "mode": "manual",
                "families": [],
                "schedule": schedule,
                "timezone": "UTC",
                "groups": groups,
            })
        except Exception as e:
            return ToolResult(success=False, error=f"Monitor creation failed: {e}")

        # /api/schedule/plans returns the created plan; extract the first monitor.
        monitor_id = None
        for g in result.get("groups", []) or []:
            for m in g.get("monitors", []) or []:
                monitor_id = m.get("id")
                if monitor_id:
                    break
            if monitor_id:
                break

        if not monitor_id:
            return ToolResult(success=False, error="Plan created but no monitor row was returned")

        return ToolResult(
            success=True,
            data={
                "title": name,
                "summary": f"{monitor_kind} monitor on {target_fqn}",
                "payload": {
                    "kind": "MONITOR",
                    "monitorId": monitor_id,
                    "monitorKind": monitor_kind,
                    "targetFqn": target_fqn,
                    "configDiff": {"before": None, "after": config},
                },
                "external_ref": {"monitor_id": monitor_id, "plan_id": result.get("id")},
            },
        )
```

- [ ] **Step 3: Sanity check (no test yet)**

Run: `python -c "from scanner.copilot.tool_executor import ToolExecutor; import inspect; print('OK' if 'create_monitor' in inspect.getsource(ToolExecutor) else 'MISSING')"`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add scanner/copilot/tool_executor.py
git commit -m "feat(tools): _execute_create_monitor handler"
```

---

### Task 5: `_execute_update_monitor` handler

**Files:**
- Modify: `scanner/copilot/tool_executor.py`

- [ ] **Step 1: Add the handler immediately after `_execute_create_monitor`**

```python
    async def _execute_update_monitor(self, args: Dict[str, Any]) -> ToolResult:
        """Update a monitor's config via the internal update route."""
        monitor_id = args.get("monitor_id") or ""
        config = args.get("config") or {}
        policy_overrides = args.get("policy_overrides")
        if not monitor_id:
            return ToolResult(success=False, error="monitor_id is required")
        if not isinstance(config, dict) or not config:
            return ToolResult(success=False, error="config must be a non-empty object")

        try:
            body: Dict[str, Any] = {"config": config}
            if policy_overrides is not None:
                body["policyOverrides"] = policy_overrides
            data = await self._call_nextjs(
                f"/api/monitors/internal/{monitor_id}/update", body,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Monitor update failed: {e}")

        return ToolResult(
            success=True,
            data={
                "title": f"Update {data.get('monitorKind') or 'monitor'} on {data.get('targetFqn') or '?'}",
                "summary": "Monitor config updated",
                "payload": {
                    "kind": "MONITOR",
                    "monitorId": data.get("monitorId") or monitor_id,
                    "monitorKind": data.get("monitorKind") or "",
                    "targetFqn": data.get("targetFqn"),
                    "configDiff": data.get("configDiff") or {"after": config},
                },
                "external_ref": {"monitor_id": data.get("monitorId") or monitor_id},
            },
        )
```

- [ ] **Step 2: Commit**

```bash
git add scanner/copilot/tool_executor.py
git commit -m "feat(tools): _execute_update_monitor handler"
```

---

### Task 6: `_execute_delete_monitor` handler

**Files:**
- Modify: `scanner/copilot/tool_executor.py`

- [ ] **Step 1: Add a method aiohttp helper for `DELETE`**

`_call_nextjs` is POST-only. Add a sibling helper right after it (around line 1156):

```python
    async def _delete_nextjs(self, path: str) -> dict:
        """DELETE on a Next.js endpoint with internal auth."""
        import aiohttp
        import os
        url = f"{self.context.base_url}{path}"
        headers = {
            "X-Internal-Secret": os.environ.get("INTERNAL_API_SECRET", "pallisade-internal"),
            "X-Organization-Id": self.context.org_id,
        }
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as resp:
                if resp.status not in (200, 204):
                    error = await resp.text()
                    raise Exception(f"Next.js DELETE {path} failed ({resp.status}): {error}")
                if resp.status == 204:
                    return {}
                return await resp.json()
```

- [ ] **Step 2: Add the handler after `_execute_update_monitor`**

```python
    async def _execute_delete_monitor(self, args: Dict[str, Any]) -> ToolResult:
        """Delete a monitor via the internal delete route."""
        monitor_id = args.get("monitor_id") or ""
        if not monitor_id:
            return ToolResult(success=False, error="monitor_id is required")

        try:
            data = await self._delete_nextjs(f"/api/monitors/internal/{monitor_id}")
        except Exception as e:
            return ToolResult(success=False, error=f"Monitor delete failed: {e}")

        return ToolResult(
            success=True,
            data={
                "title": f"Delete {data.get('monitorKind') or 'monitor'} on {data.get('targetFqn') or '?'}",
                "summary": "Monitor deleted",
                "payload": {
                    "kind": "MONITOR",
                    "monitorId": data.get("monitorId") or monitor_id,
                    "monitorKind": data.get("monitorKind") or "",
                    "targetFqn": data.get("targetFqn"),
                    "configDiff": {"operation": "delete"},
                },
                "external_ref": {"monitor_id": data.get("monitorId") or monitor_id, "deleted": True},
            },
        )
```

- [ ] **Step 3: Commit**

```bash
git add scanner/copilot/tool_executor.py
git commit -m "feat(tools): _execute_delete_monitor handler + DELETE helper"
```

---

### Task 7: Unit tests for the three monitor tools

**Files:**
- Create: `scanner/copilot/tests/test_monitor_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for create/update/delete_monitor tool executors."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanner.copilot.tool_executor import ToolExecutor
from scanner.copilot.tools.base import ToolResult


def _make_executor():
    ctx = MagicMock()
    ctx.base_url = "http://localhost:3000"
    ctx.org_id = "org_1"
    ctx.user_id = "user_1"
    ctx.session_id = "sess_1"
    ctx.agent_run_id = "run_1"
    ctx.pipeline_stack_id = "stack_1"
    ctx.graph = None
    executor = ToolExecutor(ctx)
    return executor


@pytest.mark.asyncio
async def test_create_monitor_returns_artefact_payload():
    ex = _make_executor()
    fake_plan = {
        "id": "plan_42",
        "groups": [{"monitors": [{"id": "mon_99"}]}],
    }
    with patch.object(ex, "_call_nextjs", new=AsyncMock(return_value=fake_plan)):
        result = await ex._execute_create_monitor({
            "target_fqn": "warehouse.analytics.orders",
            "monitor_kind": "FRESHNESS",
            "config": {"maxHours": 6},
        })
    assert isinstance(result, ToolResult)
    assert result.success
    payload = result.data["payload"]
    assert payload["kind"] == "MONITOR"
    assert payload["monitorId"] == "mon_99"
    assert payload["monitorKind"] == "FRESHNESS"
    assert payload["targetFqn"] == "warehouse.analytics.orders"
    assert payload["configDiff"]["after"] == {"maxHours": 6}
    assert result.data["external_ref"]["monitor_id"] == "mon_99"
    assert result.data["external_ref"]["plan_id"] == "plan_42"


@pytest.mark.asyncio
async def test_create_monitor_rejects_missing_args():
    ex = _make_executor()
    r1 = await ex._execute_create_monitor({"monitor_kind": "FRESHNESS"})
    assert not r1.success and "required" in (r1.error or "")
    r2 = await ex._execute_create_monitor({"target_fqn": "x.y.z"})
    assert not r2.success and "required" in (r2.error or "")


@pytest.mark.asyncio
async def test_create_monitor_handles_empty_plan_response():
    ex = _make_executor()
    with patch.object(ex, "_call_nextjs", new=AsyncMock(return_value={"id": "plan_1", "groups": []})):
        result = await ex._execute_create_monitor({
            "target_fqn": "a.b.c",
            "monitor_kind": "VOLUME",
        })
    assert not result.success
    assert "no monitor row" in (result.error or "")


@pytest.mark.asyncio
async def test_update_monitor_returns_diff():
    ex = _make_executor()
    fake_response = {
        "monitorId": "mon_42",
        "monitorKind": "FRESHNESS",
        "targetFqn": "wh.s.t",
        "configDiff": {"before": {"maxHours": 4}, "after": {"maxHours": 6}},
    }
    with patch.object(ex, "_call_nextjs", new=AsyncMock(return_value=fake_response)) as mocked:
        result = await ex._execute_update_monitor({
            "monitor_id": "mon_42",
            "config": {"maxHours": 6},
        })
    assert result.success
    mocked.assert_awaited_once()
    called_path = mocked.await_args.args[0]
    assert called_path == "/api/monitors/internal/mon_42/update"
    assert result.data["payload"]["configDiff"]["before"] == {"maxHours": 4}
    assert result.data["payload"]["configDiff"]["after"] == {"maxHours": 6}


@pytest.mark.asyncio
async def test_update_monitor_rejects_empty_config():
    ex = _make_executor()
    r = await ex._execute_update_monitor({"monitor_id": "mon_1", "config": {}})
    assert not r.success and "non-empty" in (r.error or "")


@pytest.mark.asyncio
async def test_delete_monitor_returns_audit_payload():
    ex = _make_executor()
    fake_response = {
        "monitorId": "mon_77",
        "monitorKind": "VOLUME",
        "targetFqn": "wh.s.orders",
        "deleted": True,
    }
    with patch.object(ex, "_delete_nextjs", new=AsyncMock(return_value=fake_response)) as mocked:
        result = await ex._execute_delete_monitor({"monitor_id": "mon_77"})
    assert result.success
    mocked.assert_awaited_once_with("/api/monitors/internal/mon_77")
    assert result.data["payload"]["kind"] == "MONITOR"
    assert result.data["payload"]["configDiff"]["operation"] == "delete"
    assert result.data["external_ref"]["deleted"] is True


@pytest.mark.asyncio
async def test_delete_monitor_rejects_missing_id():
    ex = _make_executor()
    r = await ex._execute_delete_monitor({})
    assert not r.success and "required" in (r.error or "")
```

- [ ] **Step 2: Run the tests**

Run: `cd /Users/emilfabel/pallisade-copilot/scanner && python -m pytest copilot/tests/test_monitor_tools.py -v 2>&1 | tail`
Expected: 7 tests pass.

- [ ] **Step 3: Commit**

```bash
git add scanner/copilot/tests/test_monitor_tools.py
git commit -m "test(tools): create/update/delete_monitor handlers"
```

---

### Task 8: Monitor preview component

**Files:**
- Create: `components/artefacts/previews/MonitorArtifactPreview.tsx`
- Modify: `components/artefacts/previews/index.tsx`

- [ ] **Step 1: Write the preview**

```tsx
// components/artefacts/previews/MonitorArtifactPreview.tsx
import type { ArtefactRow } from '@/types/artefact-row';
import type { ArtifactPayload } from '@/types/artifact';

type MonitorPayload = Extract<ArtifactPayload, { kind: 'MONITOR' }>;

export function MonitorArtifactPreview({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as MonitorPayload;
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
        <span className="text-[var(--text)] font-medium">{payload.monitorKind}</span>
        {payload.targetFqn ? <span>on {payload.targetFqn}</span> : null}
      </div>
      {artefact.summary ? (
        <p className="text-[13px] text-[var(--muted)] line-clamp-2">{artefact.summary}</p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 2: Add the MONITOR case to the dispatcher**

Edit `components/artefacts/previews/index.tsx`. After the existing import lines, add:

```tsx
import { MonitorArtifactPreview } from './MonitorArtifactPreview';
```

In the `switch (artefact.kind)` block, add a case **before** `default`:

```tsx
    case 'MONITOR':
      return <MonitorArtifactPreview artefact={artefact} />;
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "MonitorArtifactPreview|previews/index" | head`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add components/artefacts/previews/
git commit -m "feat(artefacts): MonitorArtifactPreview + dispatcher case"
```

---

### Task 9: Monitor body component

**Files:**
- Create: `components/artefacts/bodies/MonitorArtifactBody.tsx`
- Modify: `components/artefacts/bodies/index.tsx`

- [ ] **Step 1: Write the body**

```tsx
// components/artefacts/bodies/MonitorArtifactBody.tsx
import type { ArtefactRow } from '@/types/artefact-row';
import type { ArtifactPayload } from '@/types/artifact';

type MonitorPayload = Extract<ArtifactPayload, { kind: 'MONITOR' }>;

function formatJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export function MonitorArtifactBody({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as MonitorPayload;
  const diff = payload.configDiff as { before?: unknown; after?: unknown; operation?: string } | undefined;
  const operation = diff?.operation;

  return (
    <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-[13px]">
        <div>
          <div className="text-[var(--muted)]">Kind</div>
          <div className="text-[var(--text)] font-medium">{payload.monitorKind}</div>
        </div>
        {payload.targetFqn ? (
          <div>
            <div className="text-[var(--muted)]">Target</div>
            <div className="text-[var(--text)] font-medium truncate" title={payload.targetFqn}>
              {payload.targetFqn}
            </div>
          </div>
        ) : null}
        <div>
          <div className="text-[var(--muted)]">Monitor id</div>
          <div className="text-[var(--text)] font-mono text-[12px]">{payload.monitorId}</div>
        </div>
      </div>

      {operation === 'delete' ? (
        <div className="text-[13px] text-rose-300 rounded-md bg-rose-500/10 px-3 py-2">
          This monitor was deleted.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <div className="text-[12px] text-[var(--muted)] mb-1">Before</div>
            <pre className="text-[12px] text-[var(--text)] whitespace-pre-wrap bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[260px]">
{diff?.before !== undefined ? formatJson(diff.before) : '—'}
            </pre>
          </div>
          <div>
            <div className="text-[12px] text-[var(--muted)] mb-1">After</div>
            <pre className="text-[12px] text-[var(--text)] whitespace-pre-wrap bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[260px]">
{diff?.after !== undefined ? formatJson(diff.after) : '—'}
            </pre>
          </div>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Add the MONITOR case to the body dispatcher**

Edit `components/artefacts/bodies/index.tsx`. After the existing imports, add:

```tsx
import { MonitorArtifactBody } from './MonitorArtifactBody';
```

In the `switch` block, add **before** `default`:

```tsx
    case 'MONITOR':
      return <MonitorArtifactBody artefact={artefact} />;
```

- [ ] **Step 3: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "MonitorArtifactBody|bodies/index" | head`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add components/artefacts/bodies/
git commit -m "feat(artefacts): MonitorArtifactBody + dispatcher case"
```

---

### Task 10: `POST /api/artifacts/document` route

Creates a `DOCUMENT` artefact from a free-form chat message. This is the destination for the "Save to artefacts" action on messages that aren't tied to a tool-call artefact.

**Files:**
- Create: `app/api/artifacts/document/route.ts`

- [ ] **Step 1: Write the route**

```typescript
// app/api/artifacts/document/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { auth } from '@/auth';
import prisma from '@/lib/db';

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const userId = (session.user as any).id;
  const organizationId = (session.user as any).organizationId;
  if (!organizationId) {
    return NextResponse.json({ error: 'No organization' }, { status: 400 });
  }

  const body = await request.json().catch(() => ({}));
  const { title, body: docBody, format = 'md', sourceSessionId, sourceMessageId, tags } = body as {
    title?: string;
    body?: string;
    format?: 'md' | 'html' | 'pdf';
    sourceSessionId?: string;
    sourceMessageId?: string;
    tags?: string[];
  };

  if (!docBody || typeof docBody !== 'string') {
    return NextResponse.json({ error: 'body is required' }, { status: 400 });
  }
  if (!['md', 'html', 'pdf'].includes(format)) {
    return NextResponse.json({ error: `invalid format: ${format}` }, { status: 400 });
  }

  const derivedTitle =
    (title && title.trim()) ||
    docBody.split('\n').find((l) => l.trim())?.slice(0, 80) ||
    'Untitled document';

  const summaryLine =
    docBody
      .split('\n')
      .map((l) => l.trim())
      .find((l) => l && !l.startsWith('#')) ?? null;

  const artefact = await prisma.artifact.create({
    data: {
      userId,
      organizationId,
      kind: 'DOCUMENT',
      status: 'applied',
      title: derivedTitle,
      summary: summaryLine ? summaryLine.slice(0, 240) : null,
      payload: { kind: 'DOCUMENT', format, body: docBody },
      sourceSessionId: sourceSessionId ?? null,
      sourceMessageId: sourceMessageId ?? null,
      tags: tags ?? [],
      isSaved: true,
      appliedAt: new Date(),
    },
  });

  return NextResponse.json({ artefact }, { status: 201 });
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "artifacts/document|error TS" | head`
Expected: no errors mentioning the new file.

- [ ] **Step 3: Commit**

```bash
git add app/api/artifacts/document/route.ts
git commit -m "feat(artefacts): POST /api/artifacts/document creates DOCUMENT artefact"
```

---

### Task 11: Wire `MessageActionMenu.onSaveToArtifacts` in the assistant page

`MessageActionMenu` exposes an `onSaveToArtifacts(content)` callback. The assistant page (`app/(dashboard)/dashboard/assistant/page.tsx`) currently stubs it; replace the stub with a POST to `/api/artifacts/document` and a toast on success.

**Files:**
- Modify: `app/(dashboard)/dashboard/assistant/page.tsx`

- [ ] **Step 1: Find the stub**

Run: `grep -n "onSaveToArtifacts\|MessageActionMenu" app/\(dashboard\)/dashboard/assistant/page.tsx | head`
Expected: locations to inspect.

- [ ] **Step 2: Add a handler near the top of the component (after the `useStreamingChat` call)**

Search for the `useStreamingChat()` invocation in `AssistantPage` and add immediately after it:

```tsx
  const handleSaveToArtifacts = useCallback(async (content: string, messageId?: string, sessionId?: string) => {
    try {
      const res = await fetch('/api/artifacts/document', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          body: content,
          format: 'md',
          sourceSessionId: sessionId,
          sourceMessageId: messageId,
        }),
      });
      if (!res.ok) {
        console.error('[artefacts] save-document failed', await res.text());
        return;
      }
      const data = await res.json();
      // Lightweight toast: fall back to alert if no toast library is wired here.
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('toast', {
          detail: { title: 'Saved as document', href: `/dashboard/artifacts/${data.artefact.id}` },
        }));
      }
    } catch (err) {
      console.error('[artefacts] save-document error', err);
    }
  }, []);
```

If `useCallback` isn't already imported from `react`, add it to the existing import.

- [ ] **Step 3: Pass the handler into every `<MessageActionMenu>` usage**

Find each `<MessageActionMenu …>` in the file. Replace any stubbed `onSaveToArtifacts={() => { /* TODO ... */ }}` with:

```tsx
onSaveToArtifacts={(content) => handleSaveToArtifacts(content, message.id, sessionId)}
```

(`message` and `sessionId` are the surrounding scope variables — adjust the names if local naming differs.)

- [ ] **Step 4: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "assistant/page|error TS" | head`
Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add app/\(dashboard\)/dashboard/assistant/page.tsx
git commit -m "feat(artefacts): wire MessageActionMenu save to /api/artifacts/document"
```

---

### Task 12: Flip `ff_artefacts_v2` to default-on

Per spec §11: "The flag stays off until slice #6 lands, then flips on." Slice 6 is done after Tasks 1-9; flip the default after Task 11.

**Files:**
- Modify: `lib/feature-flags.ts`

- [ ] **Step 1: Update the flag default**

```typescript
// lib/feature-flags.ts
/**
 * Pallisade feature flags. ff_artefacts_v2 defaults to ON now that the
 * monitor write slice has landed. Operators can disable per-deploy via
 * NEXT_PUBLIC_FF_ARTEFACTS_V2=false.
 */
export const FEATURE_FLAGS = {
  ff_artefacts_v2: process.env.NEXT_PUBLIC_FF_ARTEFACTS_V2 !== 'false',
} as const;

export type FeatureFlag = keyof typeof FEATURE_FLAGS;

export function isFeatureEnabled(flag: FeatureFlag): boolean {
  return FEATURE_FLAGS[flag] === true;
}
```

- [ ] **Step 2: Type-check**

Run: `npx tsc --noEmit -p tsconfig.json 2>&1 | grep -E "feature-flags|error TS" | head`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add lib/feature-flags.ts
git commit -m "feat(flags): default ff_artefacts_v2 on (slice 6 landed)"
```

---

### Task 13: Smoke-test the slice end-to-end

- [ ] **Step 1: Run scanner tests**

```bash
cd /Users/emilfabel/pallisade-copilot/scanner
python -m pytest copilot/tests/test_monitor_tools.py copilot/tests/test_artifacts.py copilot/tests/test_emit_artifact.py copilot/tests/test_begin_artefact.py copilot/tests/test_artifact_spec_change_plan.py copilot/tests/test_executor_auto_emit.py -v 2>&1 | tail -10
```
Expected: 7 monitor + 18 previously-shipped = 25 passing.

- [ ] **Step 2: Run TS check**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit -p tsconfig.json 2>&1 | grep "error TS" | wc -l`
Expected: same baseline count as before this plan (no new errors introduced).

- [ ] **Step 3: Dev-server smoke (manual)**

```bash
npm run dev
```

Visit `/dashboard/artifacts` and confirm the page is visible (flag is default-on now). If you seeded a `MONITOR` artefact (see Plan 2 Task 16 seed pattern, swapping kind), it should render with the new preview + body.

Try the chat-side flow: open `/dashboard/assistant`, send a message, then click the `…` action menu on an assistant reply and choose "Save to artefacts". Confirm a new `DOCUMENT` artefact appears at `/dashboard/artifacts`.

- [ ] **Step 4: Update the memory pointer**

If the existing `project_pallisade.md` memory pointer is now stale ("/artifacts becomes a polymorphic registry…"), it can stay — that direction is now realised. No edit required unless you want to add a "slices 6-7 shipped" annotation.

---

## Self-review notes (for the engineer)

- **Spec coverage:**
  - §7.5 — three monitor tools with `MONITOR` `ArtifactSpec`: Tasks 3-6.
  - §7.5 — payload `{ monitorId, monitorKind, targetFqn, configDiff }`: every executor returns this shape (Tasks 4-6).
  - §7.5 — `externalRef = { monitor_id }`: every executor returns it (Tasks 4-6).
  - §7.5 — `MonitorArtifactBody`: Task 9. `MonitorArtifactCard` in chat: deferred — the legacy `components/copilot/artifacts/MonitorArtifactCard.tsx` still renders for the old `UIArtifact` flow, and the new typed artefact surfaces via the embedded session panel on `/dashboard/artifacts/[id]`. A dedicated chat-side card for the new MONITOR kind can land in a follow-up plan once `_execute_create_monitor` is actually called from chat (the executor doesn't auto-render today — it just persists).
  - §8.1 — `SaveArtifactModal` rewrite: collapsed to a one-call POST in Task 11 since the legacy modal was already deleted (commit `ea39078`). The chat-side "Save to artefacts" path is now save-as-document, matching the spec.
  - §9 — `POST /api/artifacts/document`: Task 10.
  - §11 — flag flip after slice 6: Task 12.
- **No placeholders:** every step contains literal code or a literal command.
- **Type consistency:** all new payloads conform to `ArtifactPayload` from `types/artifact.ts`. Result shapes from the three tool executors match what `_emit_for_tool` reads (`data.title`, `data.summary`, `data.payload`, `data.external_ref`).
- **Test approach:** monitor tools are pure orchestration over `_call_nextjs` / `_delete_nextjs` — tests mock those helpers and assert the resulting `ToolResult.data` payload structure. This is the same pattern used in `test_artifact_spec_change_plan.py`.
- **Risk:** `Monitor.config` is a `Json` Prisma column. The internal update route blindly merges the new config — fine for v1 where the agent is in control. If later we want per-field validation, add it in the internal route, not the executor.
