# Agentic Copilot Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the copilot to create watches and run them on demand, rendering interactive summary cards in chat that users can edit and confirm before execution.

**Architecture:** Extends the existing tool system with a new `ToolArtifactResult` return type that `llm.py` converts to `ui_artifact` SSE events. The frontend renders these as interactive cards with Confirm/Edit/Cancel. Confirmation triggers a new LLM call with `confirmed_artifacts` context, bypassing the server-side write guard.

**Tech Stack:** Python (FastAPI, dataclasses), TypeScript (Next.js, React), SSE streaming, Prisma (existing)

**Spec:** `docs/superpowers/specs/2026-03-18-agentic-copilot-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `scanner/copilot/artifacts.py` | `ToolArtifactResult` dataclass, `WRITE_TOOLS` set, artifact ID generation |
| `types/artifacts.ts` | TypeScript interfaces: `UIArtifact`, `ActionPlan`, `ActionStep`, `Checkpoint` |
| `components/copilot/ArtifactRenderer.tsx` | Routes artifact type to correct card component |
| `components/copilot/artifacts/MonitorArtifactCard.tsx` | Summary card for monitor/watch creation with Confirm/Edit/Cancel |
| `components/copilot/artifacts/ArtifactEditPanel.tsx` | Side panel wrapper that hosts MonitorConfigForm for editing (deferred to after Phase 1 — Edit button is rendered but opens a TODO placeholder until this is built) |
| `scanner/copilot/tests/test_artifacts.py` | Tests for ToolArtifactResult and artifact helpers |
| `scanner/copilot/tests/test_write_tools.py` | Tests for create_watch and run_watch tool execution |

### Modified Files
| File | Change |
|------|--------|
| `scanner/copilot/tools.py` | Add `create_watch` and `run_watch` tool definitions, add `POLICY` to ToolCategory |
| `scanner/copilot/context_builder.py` | Add `base_url` and `auth_token` fields to `CopilotContext` |
| `scanner/copilot/tool_executor.py` | Import `ToolArtifactResult`, update `execute()` return type to `Union[ToolResult, ToolArtifactResult]`, implement `_execute_create_watch()` and `_execute_run_watch()` |
| `scanner/copilot/llm.py` | Handle `ToolArtifactResult` in tool loop → yield `ui_artifact` SSE, add server-side write guard, accept `confirmed_artifacts` param |
| `scanner/api/routers/copilot.py` | Add `confirmed_artifacts` and `artifact_context` to `ChatStreamRequest`, pass to LLM |
| `app/api/copilot/chat/route.ts` | Parse `__action:*` messages, extract artifact data, rewrite to human-readable, add `confirmed_artifacts` to FastAPI request |
| `hooks/useStreamingChat.ts` | Parse `ui_artifact` events, add `artifacts` field to `StreamingMessage` |
| `app/(dashboard)/dashboard/assistant/page.tsx` | Render artifacts via `ArtifactRenderer`, handle confirm/edit/cancel callbacks |
| `scanner/copilot/llm.py` (system prompt) | Add write action policy and create mode update |

---

## Task 1: ToolArtifactResult and Artifact Helpers

**Files:**
- Create: `scanner/copilot/artifacts.py`
- Create: `scanner/copilot/tests/test_artifacts.py`

- [ ] **Step 1: Write the failing test for ToolArtifactResult**

```python
# scanner/copilot/tests/test_artifacts.py
import pytest
from scanner.copilot.artifacts import ToolArtifactResult, generate_artifact_id, WRITE_TOOLS


def test_tool_artifact_result_to_dict():
    result = ToolArtifactResult(
        artifact_type="watch_preview",
        action="create",
        data={"name": "Orders Freshness", "watchType": "pipeline_health", "anchorFqn": "analytics.public.orders"},
        editable_fields=["schedule", "monitors"],
        confirmation_tier="inline",
    )
    d = result.to_dict()
    assert d["artifact_id"].startswith("art_")
    assert d["type"] == "watch_preview"
    assert d["action"] == "create"
    assert d["status"] == "proposed"
    assert d["confirmation_tier"] == "inline"
    assert d["editable_fields"] == ["schedule", "monitors"]
    assert d["data"]["name"] == "Orders Freshness"
    assert d["tool_name"] != ""  # Must include tool_name for confirmation routing


def test_tool_artifact_result_synthetic_text():
    result = ToolArtifactResult(
        artifact_type="watch_preview",
        action="create",
        data={},
        editable_fields=[],
        confirmation_tier="inline",
    )
    text = result.to_synthetic_tool_result()
    assert "watch_preview" in text
    assert "create" in text
    assert "Awaiting user confirmation" in text


def test_generate_artifact_id():
    aid = generate_artifact_id()
    assert aid.startswith("art_")
    assert len(aid) > 8


def test_write_tools_set():
    assert "create_watch" in WRITE_TOOLS
    assert "run_watch" not in WRITE_TOOLS  # run_watch is tier "none"
    assert "get_upstream" not in WRITE_TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/copilot/tests/test_artifacts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scanner.copilot.artifacts'`

- [ ] **Step 3: Implement artifacts.py**

```python
# scanner/copilot/artifacts.py
"""Artifact types for agentic copilot write actions."""
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Tools that require user confirmation before execution (server-side guard).
# run_watch is excluded — it's tier "none" (read-only execution).
WRITE_TOOLS = frozenset({
    "create_watch",
    "update_watch",
    "delete_watch",
    "create_monitoring_plan",
    "update_node_metadata",
    "assign_policy",
    "configure_alerts",
})


def generate_artifact_id() -> str:
    """Generate a unique artifact ID."""
    return f"art_{uuid.uuid4().hex[:12]}"


@dataclass
class ToolArtifactResult:
    """Result from a write tool that needs user confirmation before execution.

    Instead of executing immediately, this result is converted to a ui_artifact
    SSE event. The LLM receives a synthetic tool result string and the frontend
    renders an interactive card.
    """
    artifact_type: str
    action: str  # "create", "update", "delete"
    data: dict
    editable_fields: list
    confirmation_tier: str  # "none", "inline", "modal"
    artifact_id: str = field(default_factory=generate_artifact_id)

    tool_name: str = ""  # The tool that generated this artifact (for confirmation routing)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to the ui_artifact SSE event payload."""
        return {
            "artifact_id": self.artifact_id,
            "type": self.artifact_type,
            "action": self.action,
            "status": "proposed",
            "data": self.data,
            "confirmation_tier": self.confirmation_tier,
            "editable_fields": self.editable_fields,
            "tool_name": self.tool_name,
        }

    def to_synthetic_tool_result(self) -> str:
        """Generate the synthetic result string fed back to the LLM.

        This tells the LLM that an artifact was emitted and it should wait
        for user confirmation before proceeding with write actions.
        """
        return (
            f"[Artifact emitted: {self.artifact_type} for {self.action}. "
            f"Awaiting user confirmation. Do not proceed with write actions "
            f"until you receive __action:confirm.]"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/copilot/tests/test_artifacts.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/artifacts.py scanner/copilot/tests/test_artifacts.py
git commit -m "feat: add ToolArtifactResult dataclass and artifact helpers"
```

---

## Task 2: Register create_watch and run_watch Tool Definitions

**Files:**
- Modify: `scanner/copilot/tools.py` (ToolCategory enum ~line 14, tool registration ~line 993+)

- [ ] **Step 1: Add POLICY to ToolCategory enum**

In `scanner/copilot/tools.py`, add `POLICY = "policy"` to the `ToolCategory` enum (after `COVERAGE`).

- [ ] **Step 2: Register the `create_watch` tool definition**

Add after the existing coverage tools (after `run_coverage_monitor` definition, around line 1064):

```python
self._register(Tool(
    name="create_watch",
    description=(
        "Create a watch (monitor group) for a data asset. A watch bundles "
        "multiple monitors (freshness, volume, schema_change, anomaly, etc.) "
        "with a shared schedule and alert configuration. Returns an interactive "
        "card for the user to review and confirm before creation."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter("name", "string", "Name for the watch (e.g., 'Orders Pipeline Health')"),
        ToolParameter("watch_type", "string", "Type of watch",
                      enum=["pipeline_health", "dashboard_shield", "source_guard",
                            "model_quality", "data_drift", "custom_watch"]),
        ToolParameter("anchor_fqn", "string", "Fully qualified name of the anchor asset (e.g., 'analytics.public.orders')"),
        ToolParameter("monitors", "array", "Array of monitors to include",
                      items={
                          "type": "object",
                          "properties": {
                              "monitor_type": {"type": "string", "enum": [
                                  "FRESHNESS", "VOLUME", "SCHEMA_CHANGE", "ANOMALY",
                                  "NULL_CHECK", "UNIQUENESS_CHECK", "RANGE_VALIDATION",
                                  "ACCEPTED_VALUES", "DATE_CONSISTENCY"
                              ]},
                              "target_fqn": {"type": "string", "description": "Target table FQN"},
                              "config": {"type": "object", "description": "Monitor-specific config"},
                          },
                          "required": ["monitor_type", "target_fqn"],
                      }),
        ToolParameter("schedule", "string", "Cron schedule (e.g., '0 */6 * * *' for every 6 hours)"),
        ToolParameter("timezone", "string", "Timezone for schedule (e.g., 'UTC', 'America/New_York')",
                      required=False, default="UTC"),
    ],
    requires_confirmation=False,  # Confirmation handled by artifact flow, NOT the old tool_confirmation_required path
))
```

- [ ] **Step 3: Register the `run_watch` tool definition**

Add immediately after `create_watch`:

```python
self._register(Tool(
    name="run_watch",
    description=(
        "Run all monitors in an existing watch immediately. Returns health score, "
        "individual monitor results, and failure categories. Does not require confirmation."
    ),
    category=ToolCategory.COVERAGE,
    parameters=[
        ToolParameter("watch_id", "string", "The ID of the watch to run"),
    ],
    requires_confirmation=False,
))
```

- [ ] **Step 4: Verify tools are registered**

Run: `cd /Users/emilfabel/pallisade-copilot && python -c "from scanner.copilot.tools import get_tool_registry; r = get_tool_registry(); print(r.get_tool('create_watch').name, r.get_tool('run_watch').name)"`
Expected: `create_watch run_watch`

- [ ] **Step 5: Commit**

```bash
git add scanner/copilot/tools.py
git commit -m "feat: register create_watch and run_watch tool definitions"
```

---

## Task 3: Implement create_watch and run_watch Tool Executors

**Files:**
- Modify: `scanner/copilot/context_builder.py` (add `base_url` and `auth_token` to `CopilotContext`)
- Modify: `scanner/copilot/tool_executor.py` (add `_execute_create_watch` and `_execute_run_watch`, update return types)
- Create: `scanner/copilot/tests/test_write_tools.py`

- [ ] **Step 0a: Add base_url and auth_token to CopilotContext**

In `scanner/copilot/context_builder.py`, add two new fields to the `CopilotContext` dataclass (after `pipeline_stack_id`):

```python
    # For write tools that call Next.js API endpoints
    base_url: str = ""
    auth_token: str = ""
```

- [ ] **Step 0b: Populate base_url and auth_token from the FastAPI request**

In `scanner/api/routers/copilot.py`, where `CopilotContext` is built (or where it's passed to `CopilotLLM`), add:

```python
# Pass through the Next.js base URL and auth for write tool API calls
copilot_context.base_url = os.environ.get("NEXTJS_BASE_URL", "http://localhost:3000")
copilot_context.auth_token = request.headers.get("Authorization", "").replace("Bearer ", "")
```

- [ ] **Step 0c: Update execute() and _execute_tool() return type annotations**

In `scanner/copilot/tool_executor.py`, update the return type:

```python
from typing import Union
from scanner.copilot.artifacts import ToolArtifactResult

# Update both signatures:
async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Union[ToolResult, ToolArtifactResult]:

async def _execute_tool(self, tool: Tool, arguments: Dict[str, Any]) -> Union[ToolResult, ToolArtifactResult]:
```

- [ ] **Step 1: Write failing tests for create_watch executor**

```python
# scanner/copilot/tests/test_write_tools.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from scanner.copilot.artifacts import ToolArtifactResult


@pytest.mark.asyncio
async def test_execute_create_watch_returns_artifact():
    """create_watch should return a ToolArtifactResult, not execute immediately."""
    from scanner.copilot.tool_executor import ToolExecutor

    mock_context = MagicMock()
    mock_context.integration_types = set()
    mock_context.integrations = []
    mock_context.org_id = "org_123"
    mock_context.base_url = "http://localhost:3000"
    mock_context.auth_token = "test-token"

    executor = ToolExecutor(mock_context)
    result = await executor.execute("create_watch", {
        "name": "Orders Health",
        "watch_type": "pipeline_health",
        "anchor_fqn": "analytics.public.orders",
        "monitors": [
            {"monitor_type": "FRESHNESS", "target_fqn": "analytics.public.orders", "config": {"timestamp_column": "updated_at"}},
        ],
        "schedule": "0 */6 * * *",
        "timezone": "UTC",
    })

    assert isinstance(result, ToolArtifactResult)
    assert result.artifact_type == "watch_preview"
    assert result.action == "create"
    assert result.confirmation_tier == "inline"  # 1 monitor = inline
    assert result.data["name"] == "Orders Health"
    assert result.data["watchType"] == "pipeline_health"
    assert len(result.data["monitors"]) == 1


@pytest.mark.asyncio
async def test_create_watch_modal_tier_for_many_monitors():
    """create_watch with 5+ monitors should use modal confirmation."""
    from scanner.copilot.tool_executor import ToolExecutor

    mock_context = MagicMock()
    mock_context.integration_types = set()
    mock_context.integrations = []
    mock_context.org_id = "org_123"
    mock_context.base_url = "http://localhost:3000"
    mock_context.auth_token = "test-token"

    executor = ToolExecutor(mock_context)
    monitors = [
        {"monitor_type": t, "target_fqn": "analytics.public.orders"}
        for t in ["FRESHNESS", "VOLUME", "SCHEMA_CHANGE", "ANOMALY", "NULL_CHECK"]
    ]
    result = await executor.execute("create_watch", {
        "name": "Orders Full Coverage",
        "watch_type": "pipeline_health",
        "anchor_fqn": "analytics.public.orders",
        "monitors": monitors,
        "schedule": "0 */6 * * *",
    })

    assert isinstance(result, ToolArtifactResult)
    assert result.confirmation_tier == "modal"  # 5 monitors = modal


@pytest.mark.asyncio
async def test_execute_run_watch_calls_api():
    """run_watch should call the Next.js API and return a ToolResult (not artifact)."""
    from scanner.copilot.tool_executor import ToolExecutor, ToolResult

    mock_context = MagicMock()
    mock_context.integration_types = set()
    mock_context.integrations = []
    mock_context.org_id = "org_123"
    mock_context.base_url = "http://localhost:3000"
    mock_context.auth_token = "test-token"

    executor = ToolExecutor(mock_context)

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "watch": {"id": "w_123", "healthScore": 85, "summary": "3/4 monitors passing"}
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await executor.execute("run_watch", {"watch_id": "w_123"})

    assert isinstance(result, ToolResult)
    assert result.success is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/copilot/tests/test_write_tools.py -v`
Expected: FAIL — `_execute_create_watch` not found or returns wrong type

- [ ] **Step 3: Implement _execute_create_watch in tool_executor.py**

Add to `ToolExecutor` class (after existing `_execute_run_coverage_monitor`):

```python
async def _execute_create_watch(self, arguments: Dict[str, Any]) -> "ToolArtifactResult":
    """Propose creating a watch — returns artifact for user confirmation, does not execute."""
    from scanner.copilot.artifacts import ToolArtifactResult

    name = arguments.get("name", "Untitled Watch")
    watch_type = arguments.get("watch_type", "custom_watch")
    anchor_fqn = arguments.get("anchor_fqn", "")
    monitors = arguments.get("monitors", [])
    schedule = arguments.get("schedule", "0 */6 * * *")
    timezone = arguments.get("timezone", "UTC")

    confirmation_tier = "modal" if len(monitors) >= 5 else "inline"

    return ToolArtifactResult(
        artifact_type="watch_preview",
        action="create",
        data={
            "name": name,
            "watchType": watch_type,
            "anchorFqn": anchor_fqn,
            "monitors": monitors,
            "schedule": schedule,
            "timezone": timezone,
        },
        editable_fields=["name", "schedule", "timezone", "monitors"],
        confirmation_tier=confirmation_tier,
        tool_name="create_watch",
    )
```

- [ ] **Step 4: Implement _execute_run_watch in tool_executor.py**

```python
async def _execute_run_watch(self, arguments: Dict[str, Any]) -> ToolResult:
    """Run all monitors in a watch immediately via Next.js API."""
    import aiohttp

    watch_id = arguments.get("watch_id")
    if not watch_id:
        return ToolResult(success=False, error="watch_id is required")

    url = f"{self.context.base_url}/api/schedule/watches/{watch_id}/run"
    headers = {
        "Authorization": f"Bearer {self.context.auth_token}",
        "X-Organization-Id": self.context.org_id,
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return ToolResult(success=False, error=f"Watch run failed ({resp.status}): {body}")
                data = await resp.json()
                watch = data.get("watch", {})
                return ToolResult(
                    success=True,
                    data={
                        "watchId": watch_id,
                        "healthScore": watch.get("healthScore"),
                        "summary": watch.get("summary", "Watch run completed"),
                        "failureGroups": watch.get("failureGroups", []),
                    }
                )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to run watch: {str(e)}")
```

- [ ] **Step 5: Update the execute() method routing**

In the `_execute_tool` method (or however tool routing works), ensure `_execute_create_watch` and `_execute_run_watch` are discoverable. The existing pattern uses `getattr(self, f"_execute_{tool_name}")` — verify these method names match exactly: `_execute_create_watch`, `_execute_run_watch`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/copilot/tests/test_write_tools.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add scanner/copilot/tool_executor.py scanner/copilot/tests/test_write_tools.py
git commit -m "feat: implement create_watch and run_watch tool executors"
```

---

## Task 4: Handle ToolArtifactResult in LLM Streaming Loop

**Files:**
- Modify: `scanner/copilot/llm.py` (~lines 1038-1107 for Anthropic, ~lines 1433-1500 for OpenAI)

This is the core backend change. When the tool executor returns a `ToolArtifactResult`, the streaming loop must:
1. Yield a `ui_artifact` SSE event
2. Feed a synthetic result string back to the LLM
3. Block execution of write tools unless confirmed

- [ ] **Step 1: Add imports and WRITE_TOOLS guard at top of llm.py**

Near the existing imports (around line 1-30), add:

```python
from scanner.copilot.artifacts import ToolArtifactResult, WRITE_TOOLS
```

- [ ] **Step 2: Add `confirmed_artifacts` parameter to `chat_stream()`**

Update the `chat_stream()` method signature (line ~821) to accept:

```python
async def chat_stream(
    self,
    messages: List[Message],
    context: CopilotContext,
    max_tool_iterations: int = 15,
    confirmed_tool_ids: Optional[Set[str]] = None,
    pending_tool_call: Optional[Dict[str, Any]] = None,
    system_prompt_override: Optional[str] = None,
    confirmed_artifacts: Optional[Dict[str, Dict[str, Any]]] = None,  # NEW
) -> AsyncGenerator[StreamEvent, None]:
```

Pass `confirmed_artifacts` through to `_chat_anthropic_stream()` and `_chat_openai_stream()`.

- [ ] **Step 3: Handle ToolArtifactResult in Anthropic tool execution block**

**IMPORTANT:** The new write tools (`create_watch`, `run_watch`) have `requires_confirmation=False`, so they will NOT be caught by the existing `tool_confirmation_required` path (lines 1038-1077). They flow through to the normal tool execution block where we add the `ToolArtifactResult` check.

In `_chat_anthropic_stream()`, find the tool execution section (around lines 1080-1107, where it calls `executor.execute(tool_name, tool_input)` and yields `tool_call_result`). Replace the execution block with logic that checks for `ToolArtifactResult`:

```python
# After getting the tool result from executor.execute():
result = await executor.execute(tool_name, tool_input)

if isinstance(result, ToolArtifactResult):
    # This is a write tool proposing an action — emit artifact, don't execute
    artifact_data = result.to_dict()
    yield StreamEvent("ui_artifact", artifact_data)

    # Feed synthetic result back to LLM so it can explain what it proposed
    synthetic_text = result.to_synthetic_tool_result()
    tool_results_for_llm.append({
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": synthetic_text,
    })
    all_tool_calls.append({
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "arguments": tool_input,
        "result": {"artifact": artifact_data},
    })
else:
    # Normal tool result — existing behavior
    yield StreamEvent("tool_call_result", {
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "result": result.to_dict() if hasattr(result, 'to_dict') else {"data": str(result)},
    })
    # ... existing tool result injection into messages ...
```

- [ ] **Step 4: Add server-side write guard**

Before the tool execution in the Anthropic loop, add the server-side confirmation guard. This goes right before `executor.execute()`:

```python
# Server-side write guard
if tool_name in WRITE_TOOLS and confirmed_artifacts:
    # Check if this tool call has been confirmed via __action:confirm
    # confirmed_artifacts is keyed by artifact_id with the confirmed data
    # For first-time calls (proposing), confirmed_artifacts won't have the key
    # For confirmed calls (executing), the artifact_id will be present
    pass  # Let it through to executor, which returns ToolArtifactResult on first call
```

The guard works naturally: on first call, `_execute_create_watch` returns `ToolArtifactResult` (proposal, not execution). On the confirmation round-trip, the Next.js route parses `__action:confirm` and adds `confirmed_artifacts` to the request. The LLM will call `create_watch` again, but this time `tool_executor.py` needs to detect the confirmation and actually execute. We handle this in Task 6 (the actual API call on confirmation).

- [ ] **Step 5: Apply the same changes to `_chat_openai_stream()`**

Mirror the ToolArtifactResult handling in the OpenAI streaming method (around lines 1433-1500). The logic is identical — check `isinstance(result, ToolArtifactResult)`, yield `ui_artifact`, feed synthetic result.

- [ ] **Step 6: Verify existing tests still pass**

Run: `cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/copilot/ -v --timeout=30 -x`
Expected: All existing tests pass (no regression)

- [ ] **Step 7: Commit**

```bash
git add scanner/copilot/llm.py
git commit -m "feat: handle ToolArtifactResult in LLM streaming loop with ui_artifact events"
```

---

## Task 5: Update FastAPI Router for Confirmed Artifacts

**Files:**
- Modify: `scanner/api/routers/copilot.py` (~lines 51-75 for models, ~lines 246-424 for stream endpoint)

- [ ] **Step 1: Add confirmed_artifacts to ChatStreamRequest**

In `scanner/api/routers/copilot.py`, update `ChatStreamRequest` (around line 72):

```python
class ChatStreamRequest(ChatRequest):
    """Extended request for streaming chat."""
    confirmed_tool_ids: Optional[List[str]] = Field(None, description="Tool use IDs the user has already confirmed")
    pending_tool_call: Optional[PendingToolCall] = Field(None, description="Tool call to execute directly (from confirmation)")
    confirmed_artifacts: Optional[Dict[str, Dict[str, Any]]] = Field(None, description="Artifacts confirmed by user, keyed by artifact_id")
    artifact_context: Optional[Dict[str, Any]] = Field(None, description="Context about the artifact being confirmed")
```

- [ ] **Step 2: Pass confirmed_artifacts to llm.chat_stream()**

In the `/chat/stream` endpoint's `event_generator()` function (around line 377), update the `llm.chat_stream()` call to pass the new param:

```python
async for event in llm.chat_stream(
    messages=formatted_messages,
    context=copilot_context,
    confirmed_tool_ids=set(request.confirmed_tool_ids or []),
    pending_tool_call=pending_tool_dict,
    confirmed_artifacts=request.confirmed_artifacts,  # NEW
):
```

- [ ] **Step 3: Verify the router loads without errors**

Run: `cd /Users/emilfabel/pallisade-copilot && python -c "from scanner.api.routers.copilot import router; print('Router loaded OK')"`
Expected: `Router loaded OK`

- [ ] **Step 4: Commit**

```bash
git add scanner/api/routers/copilot.py
git commit -m "feat: add confirmed_artifacts to ChatStreamRequest model"
```

---

## Task 6: Implement Confirmed Artifact Execution in Tool Executor

**Files:**
- Modify: `scanner/copilot/tool_executor.py` (update `_execute_create_watch` to handle confirmed execution)

When the user confirms an artifact, the Next.js route sends `confirmed_artifacts` with the (possibly edited) data. The tool executor needs to detect this and actually call the API instead of returning another `ToolArtifactResult`.

- [ ] **Step 1: Write failing test for confirmed execution**

Add to `scanner/copilot/tests/test_write_tools.py`:

```python
@pytest.mark.asyncio
async def test_create_watch_executes_when_confirmed():
    """When confirmed_data is passed, create_watch should call the API."""
    from scanner.copilot.tool_executor import ToolExecutor, ToolResult

    mock_context = MagicMock()
    mock_context.integration_types = set()
    mock_context.integrations = []
    mock_context.org_id = "org_123"
    mock_context.base_url = "http://localhost:3000"
    mock_context.auth_token = "test-token"

    executor = ToolExecutor(mock_context)

    confirmed_data = {
        "name": "Orders Health",
        "watchType": "pipeline_health",
        "anchorFqn": "analytics.public.orders",
        "monitors": [{"monitor_type": "FRESHNESS", "target_fqn": "analytics.public.orders"}],
        "schedule": "0 */6 * * *",
        "timezone": "UTC",
    }

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "watch": {"id": "w_456", "name": "Orders Health", "monitorCount": 1}
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await executor.execute_confirmed("create_watch", confirmed_data)

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.data["watchId"] == "w_456"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/copilot/tests/test_write_tools.py::test_create_watch_executes_when_confirmed -v`
Expected: FAIL — `execute_confirmed` not found

- [ ] **Step 3: Implement execute_confirmed method**

Add to `ToolExecutor` class:

```python
async def execute_confirmed(self, tool_name: str, confirmed_data: Dict[str, Any]) -> ToolResult:
    """Execute a confirmed write action by calling the Next.js API.

    This is called when the user has confirmed a ui_artifact and we need
    to actually perform the write operation.
    """
    handler = getattr(self, f"_execute_confirmed_{tool_name}", None)
    if not handler:
        return ToolResult(success=False, error=f"No confirmed handler for {tool_name}")
    try:
        return await handler(confirmed_data)
    except Exception as e:
        logger.exception(f"Error executing confirmed {tool_name}")
        return ToolResult(success=False, error=str(e))

async def _execute_confirmed_create_watch(self, data: Dict[str, Any]) -> ToolResult:
    """Actually create the watch via Next.js API."""
    import aiohttp

    url = f"{self.context.base_url}/api/schedule/watches"
    headers = {
        "Authorization": f"Bearer {self.context.auth_token}",
        "X-Organization-Id": self.context.org_id,
        "Content-Type": "application/json",
    }

    body = {
        "name": data.get("name"),
        "watchType": data.get("watchType"),
        "anchorFqn": data.get("anchorFqn"),
        "monitors": data.get("monitors", []),
        "schedule": data.get("schedule"),
        "timezone": data.get("timezone", "UTC"),
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers) as resp:
                if resp.status not in (200, 201):
                    error_body = await resp.text()
                    return ToolResult(success=False, error=f"Watch creation failed ({resp.status}): {error_body}")
                result = await resp.json()
                watch = result.get("watch", {})
                return ToolResult(
                    success=True,
                    data={
                        "watchId": watch.get("id"),
                        "name": watch.get("name"),
                        "monitorCount": watch.get("monitorCount", len(data.get("monitors", []))),
                        "message": f"Watch '{watch.get('name')}' created with {watch.get('monitorCount', 0)} monitors.",
                    }
                )
    except Exception as e:
        return ToolResult(success=False, error=f"Failed to create watch: {str(e)}")
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/emilfabel/pallisade-copilot && python -m pytest scanner/copilot/tests/test_write_tools.py -v`
Expected: 4 passed

- [ ] **Step 5: Wire confirmed execution into llm.py**

In `_chat_anthropic_stream()` and `_chat_openai_stream()`, when `confirmed_artifacts` is provided and the LLM calls a write tool, check if it matches a confirmed artifact and call `executor.execute_confirmed()` instead:

```python
# In the tool execution block, before the normal executor.execute() call:
if tool_name in WRITE_TOOLS and confirmed_artifacts:
    # Find matching confirmed artifact by checking if this tool call's
    # arguments match any confirmed artifact
    for art_id, art_data in confirmed_artifacts.items():
        if art_data.get("_tool_name") == tool_name:
            result = await executor.execute_confirmed(tool_name, art_data)
            yield StreamEvent("tool_call_result", {
                "tool_use_id": tool_use_id,
                "tool_name": tool_name,
                "result": result.to_dict(),
            })
            # Remove from confirmed so it doesn't re-execute
            confirmed_artifacts.pop(art_id, None)
            break
    else:
        # Not confirmed — fall through to normal execution (returns ToolArtifactResult)
        result = await executor.execute(tool_name, tool_input)
        # ... handle ToolArtifactResult as in Task 4 ...
```

- [ ] **Step 6: Commit**

```bash
git add scanner/copilot/tool_executor.py scanner/copilot/tests/test_write_tools.py scanner/copilot/llm.py
git commit -m "feat: implement confirmed artifact execution via Next.js API"
```

---

## Task 7: TypeScript Artifact Types

**Files:**
- Create: `types/artifacts.ts`

- [ ] **Step 1: Create the TypeScript interfaces**

```typescript
// types/artifacts.ts

export type ArtifactStatus = "proposed" | "confirmed" | "executing" | "completed" | "failed" | "cancelled";
export type ConfirmationTier = "none" | "inline" | "modal";
export type ArtifactType = "monitor_card" | "watch_preview" | "plan_preview" | "node_edit" | "policy_assignment" | "alert_config";
export type ArtifactAction = "create" | "update" | "delete";

export interface UIArtifact {
  artifact_id: string;
  type: ArtifactType;
  action: ArtifactAction;
  status: ArtifactStatus;
  data: Record<string, any>;
  confirmation_tier: ConfirmationTier;
  editable_fields: string[];
  tool_name: string;
}

export interface ActionStep {
  step_id: string;
  artifact: UIArtifact;
  order: number;
}

export interface ActionPlan {
  plan_id: string;
  description: string;
  steps: ActionStep[];
  requires_approval: boolean;
}

export interface Checkpoint {
  completed: string[];
  pending: string[];
  failed: string | null;
  error: { step_id: string; message: string; recoverable: boolean } | null;
  summary: string;
}
```

- [ ] **Step 2: Commit**

```bash
git add types/artifacts.ts
git commit -m "feat: add TypeScript interfaces for UI artifacts"
```

---

## Task 8: Update useStreamingChat to Parse ui_artifact Events

**Files:**
- Modify: `hooks/useStreamingChat.ts`

- [ ] **Step 1: Import artifact types**

At the top of `useStreamingChat.ts`, add:

```typescript
import { UIArtifact } from '@/types/artifacts';
```

- [ ] **Step 2: Add artifacts field to StreamingMessage interface**

Update the `StreamingMessage` interface to add:

```typescript
artifacts: UIArtifact[];
```

- [ ] **Step 3: Initialize artifacts in the streaming message creation**

Where `StreamingMessage` is initialized (when streaming starts), add:

```typescript
artifacts: [],
```

- [ ] **Step 4: Handle ui_artifact event in the SSE parser**

In the event parsing switch/if-else block (where `text_delta`, `tool_call_start`, etc. are handled), add a case for `ui_artifact`:

```typescript
case 'ui_artifact': {
  const artifact = eventData as UIArtifact;
  setStreamingMessage(prev => prev ? {
    ...prev,
    artifacts: [...prev.artifacts, artifact],
  } : prev);
  break;
}
```

- [ ] **Step 5: Verify no type errors**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit --pretty 2>&1 | head -20`
Expected: No new errors related to artifacts

- [ ] **Step 6: Commit**

```bash
git add hooks/useStreamingChat.ts
git commit -m "feat: parse ui_artifact SSE events in useStreamingChat"
```

---

## Task 9: MonitorArtifactCard Component

**Files:**
- Create: `components/copilot/artifacts/MonitorArtifactCard.tsx`

- [ ] **Step 1: Create the MonitorArtifactCard component**

```tsx
// components/copilot/artifacts/MonitorArtifactCard.tsx
'use client';

import { UIArtifact } from '@/types/artifacts';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Pencil, Check, X, Loader2 } from 'lucide-react';

interface MonitorArtifactCardProps {
  artifact: UIArtifact;
  onConfirm: (artifactId: string, editedData?: Record<string, any>) => void;
  onCancel: (artifactId: string) => void;
  onEdit: (artifact: UIArtifact) => void;
}

const WATCH_TYPE_COLORS: Record<string, string> = {
  pipeline_health: 'bg-blue-500/20 text-blue-400',
  dashboard_shield: 'bg-purple-500/20 text-purple-400',
  source_guard: 'bg-green-500/20 text-green-400',
  model_quality: 'bg-amber-500/20 text-amber-400',
  data_drift: 'bg-red-500/20 text-red-400',
  custom_watch: 'bg-gray-500/20 text-gray-400',
};

const ACTION_LABELS: Record<string, { text: string; color: string }> = {
  create: { text: 'CREATE', color: 'bg-emerald-500/20 text-emerald-400' },
  update: { text: 'UPDATE', color: 'bg-blue-500/20 text-blue-400' },
  delete: { text: 'DELETE', color: 'bg-red-500/20 text-red-400' },
};

function formatCron(cron: string): string {
  const parts = cron.split(' ');
  if (parts.length !== 5) return cron;
  const [min, hour] = parts;
  if (min === '0' && hour.startsWith('*/')) return `Every ${hour.slice(2)}h`;
  if (min === '0' && hour === '0') return 'Daily at midnight';
  if (min === '0') return `Daily at ${hour}:00`;
  return cron;
}

export default function MonitorArtifactCard({ artifact, onConfirm, onCancel, onEdit }: MonitorArtifactCardProps) {
  const { data, action, status } = artifact;
  const actionLabel = ACTION_LABELS[action] || ACTION_LABELS.create;
  const watchTypeColor = WATCH_TYPE_COLORS[data.watchType] || WATCH_TYPE_COLORS.custom_watch;
  const isProposed = status === 'proposed';
  const isExecuting = status === 'executing';
  const isCompleted = status === 'completed';
  const isFailed = status === 'failed';

  return (
    <div className="border border-border rounded-lg p-4 my-2 bg-card">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className={actionLabel.color}>
            {actionLabel.text}
          </Badge>
          <span className="font-semibold text-sm">{data.name || 'Watch'}</span>
          {data.watchType && (
            <Badge variant="outline" className={watchTypeColor}>
              {data.watchType.replace(/_/g, ' ')}
            </Badge>
          )}
        </div>
        {isProposed && (
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => onEdit(artifact)}>
              <Pencil className="h-3.5 w-3.5 mr-1" /> Edit
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onCancel(artifact.artifact_id)}>
              <X className="h-3.5 w-3.5 mr-1" /> Cancel
            </Button>
            <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => onConfirm(artifact.artifact_id)}>
              <Check className="h-3.5 w-3.5 mr-1" /> Confirm
            </Button>
          </div>
        )}
        {isExecuting && (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" /> Creating...
          </div>
        )}
        {isCompleted && (
          <Badge variant="outline" className="bg-emerald-500/20 text-emerald-400">
            <Check className="h-3 w-3 mr-1" /> Created
          </Badge>
        )}
        {isFailed && (
          <Badge variant="outline" className="bg-red-500/20 text-red-400">
            <X className="h-3 w-3 mr-1" /> Failed
          </Badge>
        )}
      </div>

      <div className="text-muted-foreground text-xs space-y-1">
        <div>
          <code className="text-indigo-400">{data.anchorFqn}</code>
          {data.schedule && <span className="ml-3">{formatCron(data.schedule)}</span>}
          {data.timezone && data.timezone !== 'UTC' && <span className="ml-2">({data.timezone})</span>}
        </div>
        {data.monitors && data.monitors.length > 0 && (
          <div className="flex gap-2 flex-wrap mt-1">
            {data.monitors.map((m: any, i: number) => (
              <Badge key={i} variant="secondary" className="text-xs">
                {(m.monitor_type || m.monitorType || '').replace(/_/g, ' ').toLowerCase()}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/copilot/artifacts/MonitorArtifactCard.tsx
git commit -m "feat: add MonitorArtifactCard component for watch artifacts"
```

---

## Task 10: ArtifactRenderer Component

**Files:**
- Create: `components/copilot/ArtifactRenderer.tsx`

- [ ] **Step 1: Create the ArtifactRenderer**

```tsx
// components/copilot/ArtifactRenderer.tsx
'use client';

import { UIArtifact } from '@/types/artifacts';
import MonitorArtifactCard from './artifacts/MonitorArtifactCard';

interface ArtifactRendererProps {
  artifacts: UIArtifact[];
  onConfirm: (artifactId: string, editedData?: Record<string, any>) => void;
  onCancel: (artifactId: string) => void;
  onEdit: (artifact: UIArtifact) => void;
}

export default function ArtifactRenderer({ artifacts, onConfirm, onCancel, onEdit }: ArtifactRendererProps) {
  if (!artifacts || artifacts.length === 0) return null;

  return (
    <div className="space-y-2">
      {artifacts.map((artifact) => {
        switch (artifact.type) {
          case 'watch_preview':
          case 'monitor_card':
            return (
              <MonitorArtifactCard
                key={artifact.artifact_id}
                artifact={artifact}
                onConfirm={onConfirm}
                onCancel={onCancel}
                onEdit={onEdit}
              />
            );
          default:
            return (
              <div key={artifact.artifact_id} className="border border-border rounded-lg p-3 my-2 bg-card text-sm text-muted-foreground">
                Unknown artifact type: {artifact.type}
              </div>
            );
        }
      })}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add components/copilot/ArtifactRenderer.tsx
git commit -m "feat: add ArtifactRenderer component to route artifacts to cards"
```

---

## Task 11: Integrate Artifacts into Assistant Page

**Files:**
- Modify: `app/(dashboard)/dashboard/assistant/page.tsx`
- Modify: `app/api/copilot/chat/route.ts`

This task wires everything together: rendering artifacts in chat messages, handling confirm/edit/cancel, and parsing `__action:*` messages in the proxy route.

- [ ] **Step 1: Import ArtifactRenderer in assistant page**

Add to imports in `page.tsx`:

```typescript
import ArtifactRenderer from '@/components/copilot/ArtifactRenderer';
import { UIArtifact } from '@/types/artifacts';
```

- [ ] **Step 2: Add artifact state and handlers**

Add state for the edit panel and handler functions:

```typescript
const [editingArtifact, setEditingArtifact] = useState<UIArtifact | null>(null);

const handleArtifactConfirm = useCallback(async (artifactId: string, editedData?: Record<string, any>) => {
  // Find the artifact in streamingMessage or messages
  const artifact = streamingMessage?.artifacts.find(a => a.artifact_id === artifactId);
  if (!artifact) return;

  // Build the __action:confirm message (includes tool_name for routing)
  const toolName = artifact.tool_name || 'create_watch';
  const actionMessage = editedData
    ? `__action:confirm:${artifactId}:${toolName}:${JSON.stringify(editedData)}`
    : `__action:confirm:${artifactId}:${toolName}`;

  // Send as a new chat message — this triggers a new LLM call
  await sendStreamingMessage(actionMessage, {
    sessionId,
    model: selectedModel,
    mode: selectedMode,
    pipelineStackId: selectedPipelineId,
  });
}, [streamingMessage, sessionId, selectedModel, selectedMode, selectedPipelineId]);

const handleArtifactCancel = useCallback(async (artifactId: string) => {
  const actionMessage = `__action:cancel:${artifactId}`;
  await sendStreamingMessage(actionMessage, {
    sessionId,
    model: selectedModel,
    mode: selectedMode,
    pipelineStackId: selectedPipelineId,
  });
}, [sessionId, selectedModel, selectedMode, selectedPipelineId]);

const handleArtifactEdit = useCallback((artifact: UIArtifact) => {
  setEditingArtifact(artifact);
}, []);
```

- [ ] **Step 3: Render artifacts in the streaming message section**

In the JSX where `streamingMessage` content is rendered (around the tool calls / tool confirmation rendering), add artifact rendering:

```tsx
{/* Render artifacts from streaming message */}
{streamingMessage?.artifacts && streamingMessage.artifacts.length > 0 && (
  <ArtifactRenderer
    artifacts={streamingMessage.artifacts}
    onConfirm={handleArtifactConfirm}
    onCancel={handleArtifactCancel}
    onEdit={handleArtifactEdit}
  />
)}
```

Also add rendering for artifacts in completed messages. Update the `Message` type to include artifacts:

```typescript
type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
  artifacts?: UIArtifact[];  // NEW
};
```

In the message finalization logic (where `streamingMessage` is converted to a `Message` and pushed to `messages` array), carry over artifacts:

```typescript
artifacts: streamingMessage.artifacts,
```

- [ ] **Step 4: Parse __action:* messages in the Next.js proxy route**

In `app/api/copilot/chat/route.ts`, in the `handleStreamingChat()` function, before sending the request to FastAPI, add parsing:

```typescript
// Parse __action:* messages
// The frontend sends __action:confirm:<artifactId>:<toolName> or
// __action:confirm:<artifactId>:<toolName>:<editedDataJSON>
let confirmedArtifacts: Record<string, any> | undefined;
let displayMessage = message;

if (message.startsWith('__action:confirm:')) {
  // Format: __action:confirm:<artifactId>:<toolName>[:<editedDataJSON>]
  const withoutPrefix = message.slice('__action:confirm:'.length);
  const firstColon = withoutPrefix.indexOf(':');
  const artifactId = firstColon === -1 ? withoutPrefix : withoutPrefix.slice(0, firstColon);
  const rest = firstColon === -1 ? '' : withoutPrefix.slice(firstColon + 1);

  // Extract toolName (second segment)
  const secondColon = rest.indexOf(':');
  const toolName = secondColon === -1 ? rest : rest.slice(0, secondColon);
  const jsonPart = secondColon === -1 ? '' : rest.slice(secondColon + 1);

  let editedData: Record<string, any> | undefined;
  if (jsonPart) {
    try {
      editedData = JSON.parse(jsonPart);
    } catch (e) {
      // No valid JSON, treat as confirm without edits
    }
  }

  confirmedArtifacts = {
    [artifactId]: {
      _tool_name: toolName,
      ...(editedData || {}),
    },
  };
  displayMessage = `Confirmed: ${toolName.replace(/_/g, ' ')} (${artifactId})`;
} else if (message.startsWith('__action:cancel:')) {
  const artifactId = message.split(':')[2];
  displayMessage = `Cancelled action ${artifactId}`;
}
```

Then include `confirmed_artifacts` in the body sent to FastAPI:

```typescript
body: JSON.stringify({
  message: displayMessage,
  // ... existing fields ...
  confirmed_artifacts: confirmedArtifacts,
}),
```

- [ ] **Step 5: Verify the page compiles**

Run: `cd /Users/emilfabel/pallisade-copilot && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No new type errors

- [ ] **Step 6: Commit**

```bash
git add app/\(dashboard\)/dashboard/assistant/page.tsx app/api/copilot/chat/route.ts
git commit -m "feat: integrate artifact rendering and __action parsing into chat UI"
```

---

## Task 12: Update System Prompt

**Files:**
- Modify: `scanner/copilot/llm.py` (system prompt building section, around lines 154-789)

- [ ] **Step 1: Add write action policy to system prompt**

Find the system prompt building section in `llm.py` (the method that constructs the system prompt string). Append the write action policy after the existing tool policy section:

```python
WRITE_ACTION_POLICY = """
## Write Actions

You can create and modify resources in Pallisade. Write actions emit interactive
cards that the user reviews before execution.

RULES:
- ALWAYS gather information first (read-only tools) before proposing write actions
- For a SINGLE write action: emit the artifact directly by calling the write tool
- For MULTIPLE write actions (2+): call each write tool separately — each will emit
  its own artifact card for user review
- NEVER assume user confirmation. Wait for explicit __action:confirm before proceeding.
- When you receive __action:confirm, acknowledge the creation and summarize what was done.
- If a user cancels (__action:cancel), acknowledge gracefully and ask what they'd like instead.
- After completing all actions, summarize what was done and ask if anything else is needed.

AVAILABLE WRITE TOOLS:
- create_watch: Create a watch (monitor group) with bundled monitors and schedule
- run_watch: Run all monitors in an existing watch immediately (no confirmation needed)
"""
```

- [ ] **Step 2: Update create mode instructions**

Find the create mode section in the system prompt and update it:

```python
CREATE_MODE_ADDITION = """
When the user asks you to CREATE monitors, watches, or monitoring:
1. Understand what they want to monitor and why
2. Use read-only tools to gather context: get_monitor_recommendations, get_upstream,
   get_downstream, get_table_stats
3. Call create_watch with a well-configured monitor bundle
4. The tool will emit an interactive card — do NOT tell the user to go create it manually
5. Wait for __action:confirm or __action:cancel
6. On confirm: acknowledge and summarize what was created
7. On cancel: ask what they'd like to change
"""
```

- [ ] **Step 3: Verify prompt builds without errors**

Run: `cd /Users/emilfabel/pallisade-copilot && python -c "from scanner.copilot.llm import CopilotLLM; print('LLM module loads OK')"`
Expected: `LLM module loads OK`

- [ ] **Step 4: Commit**

```bash
git add scanner/copilot/llm.py
git commit -m "feat: add write action policy and create mode update to system prompt"
```

---

## Task 13: End-to-End Smoke Test

**Files:** None (manual testing)

- [ ] **Step 1: Start the dev servers**

```bash
# Terminal 1: Next.js
cd /Users/emilfabel/pallisade-copilot && npm run dev

# Terminal 2: FastAPI
cd /Users/emilfabel/pallisade-copilot && python -m uvicorn scanner.api.app:app --reload --port 8000
```

- [ ] **Step 2: Test create_watch flow**

In the copilot chat, type: "Create a freshness monitor for analytics.public.orders that checks every 6 hours"

**Expected behavior:**
1. LLM calls `get_monitor_recommendations` or `get_table_stats` first (read-only)
2. LLM calls `create_watch` with proposed config
3. A `ui_artifact` SSE event is emitted
4. A `MonitorArtifactCard` appears in chat with:
   - "CREATE" badge
   - Watch name
   - Anchor FQN
   - Schedule
   - Monitor type badges
   - Confirm / Edit / Cancel buttons
5. LLM explains what it's proposing in text around the card
6. Clicking "Confirm" sends `__action:confirm:<artifact_id>` as a new message
7. LLM acknowledges the creation

- [ ] **Step 3: Test cancel flow**

Repeat step 2, but click "Cancel" instead of "Confirm".

**Expected:** LLM acknowledges cancellation and asks what the user would like instead.

- [ ] **Step 4: Test run_watch flow**

Type: "Run my orders watch" (requires a watch to exist)

**Expected:** `run_watch` executes immediately (no confirmation card), returns health score and results as normal tool output.

- [ ] **Step 5: Verify existing tools still work**

Type: "What tables do I have?" or "Show me the lineage for orders"

**Expected:** Existing read-only tools work normally, no regression.

- [ ] **Step 6: Final commit with any smoke test fixes**

```bash
git add -A
git commit -m "fix: smoke test adjustments for agentic copilot phase 1"
```

---

## Summary

| Task | Description | New Files | Modified Files |
|------|-------------|-----------|----------------|
| 1 | ToolArtifactResult & helpers | `artifacts.py`, `test_artifacts.py` | — |
| 2 | Tool definitions | — | `tools.py` |
| 3 | Tool executors | `test_write_tools.py` | `tool_executor.py` |
| 4 | LLM streaming loop | — | `llm.py` |
| 5 | FastAPI router | — | `copilot.py` |
| 6 | Confirmed execution | — | `tool_executor.py`, `llm.py` |
| 7 | TypeScript types | `artifacts.ts` | — |
| 8 | useStreamingChat | — | `useStreamingChat.ts` |
| 9 | MonitorArtifactCard | `MonitorArtifactCard.tsx` | — |
| 10 | ArtifactRenderer | `ArtifactRenderer.tsx` | — |
| 11 | Page integration | — | `page.tsx`, `route.ts` |
| 12 | System prompt | — | `llm.py` |
| 13 | Smoke test | — | — |
