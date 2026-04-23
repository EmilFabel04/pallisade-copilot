# Agentic Copilot: Interactive Write Actions & Multi-Step Execution

**Date:** 2026-03-18
**Status:** Draft
**Scope:** Monitors, watches, monitoring plans, lineage metadata, policies, alerts

## Problem

The Pallisade copilot is currently a single-turn request/response system. The LLM can recommend and test-run monitors, but cannot create watches, edit lineage, manage policies, or take any persistent write actions. Tool results render as collapsible JSON blocks with no interactivity. Once the LLM responds, it's done — there is no mechanism for it to persist through a multi-step task until completion.

## Goals

1. Give the LLM write capabilities: create/edit/delete monitors, watches, plans, lineage metadata, policies, and alert configs
2. Render LLM-proposed actions as interactive UI cards in chat that the user can review and edit before execution
3. Support multi-step execution where the LLM proposes an editable plan, the user approves, and the LLM executes with progress checkpoints
4. Maintain user control through tiered confirmation (none/inline/modal) based on action risk

## Non-Goals

- User/team management (security-sensitive, future phase)
- Integration/connection management (credential handling too sensitive)
- Pipeline profile management (admin-level)
- Custom user-defined tools
- Fully autonomous background agents (user stays in the loop)

## Architecture: Tool Extension + UI Artifact Protocol

Extends the existing copilot architecture rather than replacing it. Three new concepts are introduced: UI Artifacts, Action Plans, and Checkpoints.

### 1. UI Artifact Protocol

A **UI Artifact** is a structured SSE event the LLM emits that the frontend renders as an interactive summary card in chat.

#### New SSE Event Types

**`ui_artifact`** — a single proposed action:

```json
{
  "artifact_id": "art_abc123",
  "type": "monitor_card | watch_preview | plan_preview | node_edit | policy_assignment | alert_config",
  "action": "create | update | delete",
  "status": "proposed | confirmed | executing | completed | failed | cancelled",
  "data": {},
  "confirmation_tier": "none | inline | modal",
  "editable_fields": ["schedule", "threshold", "alertChannels"]
}
```

**`action_plan`** — a bundle of proposed actions (emitted when 2+ write operations needed):

```json
{
  "plan_id": "plan_abc123",
  "description": "Set up monitoring for the orders pipeline",
  "steps": [
    { "step_id": "s1", "artifact": { "...ui_artifact..." }, "order": 1 },
    { "step_id": "s2", "artifact": { "...ui_artifact..." }, "order": 2 }
  ],
  "requires_approval": true
}
```

**`checkpoint`** — progress update during plan execution:

```json
{
  "completed": ["s1", "s2"],
  "pending": ["s3"],
  "failed": null,
  "error": null,
  "summary": "Created freshness and volume monitors. Next: configure alerts."
}
```

When a step fails:

```json
{
  "completed": ["s1"],
  "pending": ["s3"],
  "failed": "s2",
  "error": { "step_id": "s2", "message": "Monitor already exists for this FQN", "recoverable": true },
  "summary": "Created freshness monitor. Volume monitor failed: duplicate. Awaiting user decision."
}
```

#### Confirmation Tiers

| Tier | Actions | UX |
|------|---------|-----|
| `none` | `run_watch` (read-only execution) | Execute immediately, show result |
| `inline` | Create single monitor/watch (1-4 monitors), `update_node_metadata`, `assign_policy`, `configure_alerts` on new resource | Summary card + Confirm/Edit/Cancel buttons in chat |
| `modal` | `delete_watch`, `create_monitoring_plan`, `create_watch` with 5+ monitors, `configure_alerts` on live watch with active alerts | Modal dialog with impact summary |

### 2. New Write Tools

Added to `scanner/copilot/tools.py` and implemented in `scanner/copilot/tool_executor.py`. Same pattern as existing tools but return `ToolArtifactResult` instead of plain text.

#### Tool Definitions

| Tool | Category | Parameters | Confirmation |
|------|----------|-----------|--------------|
| `create_watch` | COVERAGE | `name, watchType, anchorFqn, monitors[], schedule, timezone` | `inline` (1-4 monitors), `modal` (5+) |
| `update_watch` | COVERAGE | `watchId, schedule?, enabled?, alertChannels?, removeMonitorIds?` | `inline` |
| `delete_watch` | COVERAGE | `watchId` | `modal` |
| `create_monitoring_plan` | COVERAGE | `name, scopeType, scopeConfig, mode, families[]` | `modal` |
| `run_watch` | COVERAGE | `watchId` | `none` |
| `update_node_metadata` | LINEAGE | `nodeId, description?, owner?, tags?, criticality?, businessDomain?` | `inline` |
| `assign_policy` | POLICY | `nodeFqn, profileId, overrides?` | `inline` |
| `configure_alerts` | COVERAGE | `targetId, targetType (watch|plan), alertChannels[], alertOnStatus[]` | `inline` (new), `modal` (live) |

#### Tool Return Type

```python
class ToolArtifactResult:
    artifact_type: str          # "monitor_card", "watch_preview", etc.
    action: str                 # "create", "update", "delete"
    data: dict                  # The resource data to render
    editable_fields: list[str]  # Which fields user can modify in side panel
    confirmation_tier: str      # "none", "inline", "modal"
```

**How `ToolArtifactResult` interacts with the LLM tool loop:**

When `llm.py` receives a `ToolArtifactResult` from tool execution:
1. It feeds back a synthetic tool result string to the LLM: `"[Artifact emitted: {artifact_type} for {action}. Awaiting user confirmation. Do not proceed with write actions until you receive __action:confirm.]"`
2. It yields a `ui_artifact` SSE event to the frontend
3. The LLM's natural response to the synthetic result is a text message explaining what it proposed (this becomes the chat message around the card)
4. The SSE stream **ends** (the LLM call completes normally — this is NOT a held-open connection)
5. When the user confirms/cancels, the frontend sends a new chat message with the `__action:*` prefix
6. This triggers a **new LLM call** with the full conversation history (original request + proposed artifacts + confirmation), not a resumed call

This means "same session" refers to conversation history continuity, not a single HTTP connection.

#### Server-Side Confirmation Guard

Write tools are protected by a server-side guard, not just prompt instructions. This extends the existing `confirmed_tool_ids` pattern in `llm.py`:

```python
# In the streaming tool loop:
WRITE_TOOLS = {"create_watch", "update_watch", "delete_watch",
               "create_monitoring_plan", "update_node_metadata",
               "assign_policy", "configure_alerts"}

# pending_artifacts tracks artifacts awaiting confirmation
# confirmed_artifacts tracks artifacts the user has confirmed

if tool_name in WRITE_TOOLS:
    if tool_name == "run_watch":
        pass  # tier "none", execute immediately
    elif artifact_id not in confirmed_artifacts:
        # Emit ui_artifact, do NOT execute the write
        yield ui_artifact_event(...)
        # Feed synthetic "awaiting confirmation" result back to LLM
        continue
    else:
        # Confirmed — execute the write
        result = execute_write_tool(tool_name, arguments, confirmed_data)
```

The LLM cannot bypass confirmation by ignoring the prompt — the server blocks write tool execution unless the artifact ID has been confirmed via an `__action:confirm` message.

#### Backend Endpoints for Write Tools

Write tools in `tool_executor.py` call existing Next.js API routes (not FastAPI endpoints) because the Prisma database is managed by Next.js. The tool executor makes HTTP calls to these endpoints using the user's session context passed through from the copilot request:

| Tool | Endpoint | Method | Exists? |
|------|----------|--------|---------|
| `create_watch` | `/api/schedule/watches` | POST | Yes |
| `update_watch` | `/api/schedule/watches/[watchId]` | PATCH | Yes |
| `delete_watch` | `/api/schedule/watches/[watchId]` | DELETE | Yes |
| `create_monitoring_plan` | `/api/schedule/plans` | POST | Yes |
| `run_watch` | `/api/schedule/watches/[watchId]/run` | POST | Yes |
| `update_node_metadata` | `/api/lineage/nodes/[nodeId]` | PATCH | **New** — needs creation |
| `assign_policy` | `/api/schedule/policies/assignments` | POST | Check `app/api/schedule/policies/` |
| `configure_alerts` | `/api/schedule/watches/[watchId]` | PATCH (alertChannels field) | Yes (part of watch PATCH) |

For `tool_executor.py` to call these endpoints, it needs:
1. The base URL of the Next.js app (passed via copilot request context or environment variable)
2. A service-level auth token or the user's session cookie (passed through from the original request)
3. The `organizationId` (already available in the copilot request)

#### `editable_fields` Behavior

The `editable_fields` array controls which fields are highlighted/promoted in the side panel, but does NOT disable other fields. When "Edit" opens `MonitorConfigForm` in the side panel:
1. The form is pre-populated with the LLM-proposed values from `artifact.data`
2. All form fields remain editable (the existing form components are not modified)
3. `editable_fields` is used by the summary card to show which fields the LLM chose and by the side panel to scroll/highlight the relevant fields
4. When the user saves edits, the full form state (not just edited fields) is sent back in the confirmation

This avoids modifying existing form components for partial-field editing.

#### Multi-Step Awareness

When the LLM needs multiple write actions:
1. Gathers information first via read-only tools (`get_monitor_recommendations`, `get_upstream`, etc.)
2. Returns a single `action_plan` containing all proposed artifacts
3. Does NOT execute any write tools until the plan is confirmed
4. After confirmation, executes steps sequentially with `checkpoint` events between each

The decision between single artifact and action plan is driven by the system prompt based on the number of write operations.

### 3. Frontend Artifact Renderer

#### Component Architecture

```
ChatMessage
  └── ArtifactRenderer (new)
        ├── MonitorArtifactCard    → Edit opens MonitorConfigForm in side panel
        ├── WatchArtifactCard      → Edit opens WatchCard edit in side panel
        ├── PlanArtifactCard       → Edit opens PlanPreview in side panel
        ├── NodeEditArtifactCard   → Edit opens DataAssetDetailPanel in side panel
        ├── PolicyArtifactCard     → Edit opens PolicyEditorPanel in side panel
        └── AlertArtifactCard      → Edit opens alert config in side panel
  └── ActionPlanRenderer (new)
        ├── Step list (reorderable via drag-and-drop)
        ├── Per-step ArtifactCard (summary mode)
        ├── "Execute Plan" button
        └── Progress tracker (during execution)
```

#### Key Behaviors

**ArtifactRenderer:**
- Receives `ui_artifact` event data, picks the right card component based on `type`
- Renders a read-only summary card inline in chat
- "Edit" button opens the corresponding existing form component in a right-side panel
- "Confirm" sends `__action:confirm:artifact_id` back through the chat
- "Cancel" sends `__action:cancel:artifact_id`
- Edits made in the side panel update the artifact data before confirmation is sent

**ActionPlanRenderer:**
- Receives `action_plan` event data
- Shows all steps as a vertical list of summary cards
- Each step is draggable to reorder
- Each step has Edit (opens side panel) and Remove (strikes through with undo)
- "Execute Plan" button at the bottom sends the final step list back to the LLM
- During execution: steps show spinner then checkmark as they complete
- If a step fails: stops execution, shows error, lets user retry/skip/abort

#### Reused Components

No new form UI is needed. The side panel hosts existing components:
- `MonitorConfigForm` for monitor artifacts
- `WatchCard` edit mode for watch artifacts
- `PlanPreview` for monitoring plan artifacts
- `DataAssetDetailPanel` for node metadata
- `PolicyEditorPanel` for policy assignments

New UI is limited to: summary cards in chat and the ActionPlanRenderer wrapper.

#### Updated `StreamingMessage` Interface

The `useStreamingChat.ts` hook's message type needs new fields:

```typescript
interface StreamingMessage {
  // ... existing fields (content, toolCalls, pendingConfirmation) ...
  artifacts: UIArtifact[];        // Artifacts proposed in this message
  actionPlan: ActionPlan | null;  // Multi-step plan if present
  checkpoints: Checkpoint[];      // Execution progress updates
}

interface UIArtifact {
  artifact_id: string;
  type: string;
  action: string;
  status: "proposed" | "confirmed" | "executing" | "completed" | "failed" | "cancelled";
  data: Record<string, any>;
  confirmation_tier: "none" | "inline" | "modal";
  editable_fields: string[];
}

interface ActionPlan {
  plan_id: string;
  description: string;
  steps: ActionStep[];
  requires_approval: boolean;
}

interface ActionStep {
  step_id: string;
  artifact: UIArtifact;
  order: number;
}

interface Checkpoint {
  completed: string[];
  pending: string[];
  failed: string | null;
  error: { step_id: string; message: string; recoverable: boolean } | null;
  summary: string;
}
```

#### Action Plan Step Ordering

Steps in an action plan are **sequentially executed in order** — there are no dependency edges between steps. The LLM is responsible for proposing steps in a valid order (e.g., create watch before configuring alerts on it). When the user reorders steps via drag-and-drop, no validation is performed — if the reordering creates an invalid sequence (e.g., alerting on a watch that hasn't been created yet), the step will fail at execution time and the checkpoint error handling kicks in (retry/skip/abort).

### 4. Multi-Step Execution & Checkpoint Loop

#### Execution Flow

```
User sends message
  → LLM gathers context via read-only tools
  → LLM emits action_plan or single ui_artifact
  → LLM PAUSES (stops tool loop)
  → User reviews, edits, confirms
  → Frontend sends __action:confirm or __action:execute_plan as next chat message
  → LLM RESUMES in same session with confirmation context
  → Executes write tools sequentially
  → Emits checkpoint after each step
  → On completion: summary + "anything else?"
```

#### Pause/Resume Mechanism

No new task engine or agent thread infrastructure. The SSE stream ends normally after the LLM proposes artifacts. Confirmation triggers a new LLM call with full conversation history.

**Action message format** — sent as chat messages with a special prefix:

- `__action:confirm:<artifact_id>` — confirmed as-is
- `__action:confirm:<artifact_id>:<edited_data_json>` — confirmed with edits
- `__action:execute_plan:<plan_id>:<steps_json>` — execute plan with possibly reordered/edited steps
- `__action:cancel:<artifact_id>` — cancelled

**Action message routing** — parsed in the Next.js proxy route (`app/api/copilot/chat/route.ts`), NOT in FastAPI:
1. Next.js intercepts `__action:*` messages before forwarding to FastAPI
2. Extracts artifact_id, action type, and any edited data
3. Adds `confirmed_artifacts` and `artifact_context` fields to the FastAPI request body
4. FastAPI passes these to `CopilotLLM` which uses them for server-side confirmation guards
5. The `__action:*` message is rewritten to a human-readable form before being stored in conversation history (e.g., "Confirmed: create freshness monitor for analytics.public.orders") to avoid polluting the LLM context with machine-readable strings

**Token budget management** — after a step executes successfully, its full artifact data is summarized in history (e.g., "Step 1 completed: created freshness monitor art_abc123") rather than keeping the full JSON. This prevents multi-step plans from bloating conversation context.

#### Failure Handling

- **Step fails** (API error): LLM emits checkpoint with error, asks user to retry/skip/abort
- **User disconnects mid-plan**: On reconnect, chat history has everything up to last checkpoint. User sends "continue" and LLM resumes
- **LLM loses coherence**: System prompt includes recovery instruction — re-read the action_plan and last checkpoint from history to reorient

### 5. System Prompt Changes

#### Write Action Policy (appended to existing tool policy)

```
## Write Actions

You can create and modify resources in Pallisade. Write actions emit interactive
cards that the user reviews before execution.

RULES:
- ALWAYS gather information first (read-only tools) before proposing write actions
- For a SINGLE write action: emit the artifact directly
- For MULTIPLE write actions (2+): bundle them into an action_plan so the user
  can review and reorder all steps before any execute
- NEVER execute write tools without user confirmation unless confirmation_tier is "none"
- When you receive __action:confirm or __action:execute_plan, execute the confirmed
  actions. Report results via checkpoint events between steps.
- If a step fails, stop and ask the user how to proceed. Do not retry automatically.
- After completing all actions, summarize what was done and ask if anything else is needed.

CONFIRMATION TIERS:
- none: run_watch (read-only execution, no side effects beyond monitor run)
- inline: create single monitor/watch (<=4 monitors), update_node_metadata, assign_policy,
  configure_alerts on new resource
- modal: delete_watch, create_monitoring_plan, create_watch with 5+ monitors,
  configure_alerts on live watch with active alerts
```

#### Create Mode Update

```
When mode is CREATE:
1. Understand what the user wants to create
2. Use read-only tools to gather context (recommendations, schema, upstream/downstream)
3. Propose the action(s) as ui_artifact or action_plan
4. Wait for confirmation — do NOT proceed until you receive __action:confirm
5. Execute confirmed actions, checkpoint between steps
6. Summarize results
```

### 6. What Changes vs What Stays

#### Changes

| Layer | File(s) | Change |
|-------|---------|--------|
| Backend | `scanner/copilot/tools.py` | Add 8 new tool definitions |
| Backend | `scanner/copilot/tool_executor.py` | Implement `_execute_*` for each new tool, add `ToolArtifactResult` |
| Backend | `scanner/copilot/llm.py` | Handle `ToolArtifactResult` → yield `ui_artifact` SSE; pause tool loop on artifacts; handle `__action:*` messages |
| Backend | `scanner/api/routers/copilot.py` | Parse `__action:*` messages, pass artifact context to LLM |
| Frontend | New: `components/copilot/ArtifactRenderer.tsx` | Route artifact types to card components |
| Frontend | New: `components/copilot/artifacts/MonitorArtifactCard.tsx` (and siblings) | Summary cards for each artifact type |
| Frontend | New: `components/copilot/ActionPlanRenderer.tsx` | Editable step list with drag-reorder and execution progress |
| Frontend | `app/(dashboard)/dashboard/assistant/page.tsx` | Handle new SSE events, render artifacts in message stream |
| Frontend | `hooks/useStreamingChat.ts` | Parse `ui_artifact`, `action_plan`, `checkpoint` events |
| Prompt | System prompt in `llm.py` | Add write action policy, update create mode instructions |

#### Unchanged

- All existing read-only tools
- Intent classification and mode system
- Streaming protocol (new events are additive)
- Conversation history storage (artifacts/confirmations are just messages)
- Model selection
- Existing form components (reused in side panels, not modified)

## Implementation Phases

### Phase 1 — Foundation

- `ui_artifact` SSE event type in `llm.py` streaming
- `ToolArtifactResult` return type in `tool_executor.py`
- `ArtifactRenderer` component + `MonitorArtifactCard`
- `create_watch` tool (single watch, up to 4 monitors)
- `run_watch` tool
- Confirmation flow (`__action:confirm/cancel`)
- Updated system prompt for write actions

**Delivers:** "Create a freshness monitor for my orders table" works end-to-end with interactive card + confirm flow.

### Phase 2 — Multi-Step Plans

- `action_plan` SSE event type
- `ActionPlanRenderer` with drag-reorder and per-step edit
- `checkpoint` SSE event type
- `create_monitoring_plan` tool
- `configure_alerts` tool
- Plan execution loop with pause/resume

**Delivers:** "Set up full monitoring for my orders pipeline" produces an editable multi-step plan.

### Phase 3 — Lineage & Policy Actions

- `update_node_metadata` tool + `NodeEditArtifactCard`
- `assign_policy` tool + `PolicyArtifactCard`
- `update_watch` and `delete_watch` tools
- Modal confirmation for destructive actions

**Delivers:** Full write capability across monitors, lineage, and policies.

## Design Decisions

1. **Artifact immutability**: Artifact cards become immutable historical records after confirmation. Their `status` field updates (proposed → confirmed → executing → completed) but data is frozen. Users who want to redo an action ask the copilot again ("create another monitor like the one you just made but with a 24h threshold").
2. **Rate limiting**: No per-session limit initially. The confirmation requirement is the natural throttle. If abuse becomes an issue, add a configurable max (default 20 write actions per session).
3. **Undo**: No one-click undo. Users delete/update resources through the copilot ("delete the monitor you just created") or through the existing Schedule UI. Undo would require transaction-level rollback infrastructure that's out of scope.

## UX Details

**Loading states during write execution**: When a step is executing (between "confirmed" and "completed"), the artifact card shows a spinner overlay with "Creating..." / "Updating..." / "Deleting..." text. The ActionPlanRenderer shows the current step highlighted with a pulse animation. Individual step execution is expected to take 1-5 seconds (API calls to Next.js endpoints).
