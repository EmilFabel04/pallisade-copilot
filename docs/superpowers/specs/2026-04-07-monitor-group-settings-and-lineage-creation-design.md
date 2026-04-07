# Monitor Group Settings & Lineage Monitor Creation

## Summary

Add a gear icon to monitor groups (WatchCard + WatchDetailPanel) that opens a settings modal for editing schedule, alert platform, and toggling monitor types on/off. Also enable monitor creation from the lineage data asset detail panel, where monitors are automatically added to the asset's group (created if needed).

## Core Principle

**One group per asset.** Every data asset has at most one monitor group. All monitors on that asset belong to its group.

## Feature 1: Monitor Group Settings Modal

### Entry Point

A gear icon (⚙️) appears in two places:
- **WatchCard** (`components/schedule/WatchCard.tsx`) — in the card header, next to the existing overflow menu
- **WatchDetailPanel** (`components/schedule/WatchDetailPanel.tsx`) — in the panel header bar, next to the enable toggle

Clicking the gear icon opens the `MonitorGroupSettingsModal`.

### Modal Layout

A centered modal dialog (`MonitorGroupSettingsModal`) with three stacked sections (no tabs):

**1. Schedule**
- Cron expression / human-readable schedule input (reuse `ScheduleInput` component)
- Timezone selector
- Pre-filled with the group's current schedule

**2. Alert Platform**
- Alert channel chips with remove (×) action (reuse `AlertChannelPicker` component)
- "+ Add channel" button to add new channels
- "Alert on" status toggles: Fail, Warn, Pass (toggle chips)
- Pre-filled with the group's current alert config

**3. Monitors**
- Checklist of all available monitor types for this asset
- Active monitors show green checkmark + "Active" badge
- Inactive monitors show empty checkbox
- Toggling a checkbox on = creates the monitor and adds it to the group
- Toggling a checkbox off = removes/disables the monitor from the group

**Footer:** Cancel and Save Changes buttons.

### API Changes

The existing `PATCH /api/schedule/watches/[watchId]` endpoint already supports updating schedule, alert channels, and alert config. It also supports `removeMonitorIds[]`.

**New capability needed:** Adding monitors by type. When the user toggles on a new monitor type:
- Create a new `Monitor` record with the selected type, target FQN from the group's anchor, and default config
- Link it to the group via `monitorGroupId`

This can be handled by extending the PATCH endpoint to accept an `addMonitorTypes: string[]` field, or by calling the existing monitor creation logic from `lib/watch-helpers.ts`.

### Component: `MonitorGroupSettingsModal`

**File:** `components/schedule/MonitorGroupSettingsModal.tsx`

**Props:**
- `watchId: string` — the monitor group ID
- `open: boolean` — modal visibility
- `onClose: () => void` — close handler
- `onSaved: () => void` — refresh callback after save

**State:**
- Fetches current watch details on open (GET `/api/schedule/watches/[watchId]`)
- Tracks dirty state for schedule, alerts, and monitor type changes
- On save, sends PATCH with all changes

## Feature 2: Monitor Creation from Lineage Asset Detail Panel

### Entry Point

In `DataAssetDetailPanel.tsx`, add a **"Monitors" section** that shows:
- List of existing monitors on this asset (with status dot + name + last status)
- A "+ Create Monitor" button

### Create Monitor Flow

Clicking "+ Create Monitor" opens a **3-step modal** (consistent with existing `MultiMonitorModal` flow):

**Step 1 — Select Monitor Types**
- Checklist of available monitor types
- Already-existing types are greyed out with "Already exists" badge (not selectable)
- New types can be toggled on

**Step 2 — Schedule**
- If a group already exists for this asset: pre-fill with the group's schedule
- If no group exists: show default schedule (daily)

**Step 3 — Alerts**
- If a group already exists: pre-fill with the group's alert config
- If no group exists: show empty alert config

### On Save Behavior

**Group exists for this asset:**
- New monitors are created and added to the existing group
- Schedule/alert changes from steps 2-3 update the group settings (if user modified them)

**No group exists yet:**
- A new `MonitorGroup` is created with the asset as anchor (`anchorFqn`, `anchorNodeId`)
- Schedule and alert settings from steps 2-3 become the group's config
- All selected monitors are created and linked to the new group

### Finding the Asset's Group

Look up existing group by matching `anchorFqn` on the `MonitorGroup` table. The asset's FQN from the lineage node maps to `MonitorGroup.anchorFqn`.

### API

Reuse the existing `POST /api/schedule/watches` endpoint (which calls `createWatchInTransaction`). The deduplication logic already:
- Checks if a group with the same anchor exists
- Avoids duplicate monitors with the same (targetFqn, monitorType)

For the "group exists" case, extend to support adding monitors to an existing group rather than always creating a new one.

## Components Summary

| Component | File | Purpose |
|-----------|------|---------|
| `MonitorGroupSettingsModal` | `components/schedule/MonitorGroupSettingsModal.tsx` | **New.** Settings modal for schedule, alerts, monitor types |
| `WatchCard` | `components/schedule/WatchCard.tsx` | **Modified.** Add gear icon to card header |
| `WatchDetailPanel` | `components/schedule/WatchDetailPanel.tsx` | **Modified.** Add gear icon to panel header |
| `DataAssetDetailPanel` | `components/lineage/DataAssetDetailPanel.tsx` | **Modified.** Add Monitors section with status list + Create button |
| `AssetMonitorCreationModal` | `components/lineage/AssetMonitorCreationModal.tsx` | **New.** 3-step creation wizard scoped to a single asset |

## API Changes Summary

| Endpoint | Change |
|----------|--------|
| `PATCH /api/schedule/watches/[watchId]` | Extend to accept `addMonitorTypes: string[]` for adding new monitors by type |
| `POST /api/schedule/watches` | Extend `createWatchInTransaction` to support adding monitors to an existing group (not just creating new ones) |
| `GET /api/schedule/watches` | No change — already returns monitors per group |

## Data Model

No schema changes needed. The existing `Monitor.monitorGroupId` FK and `MonitorGroup.anchorFqn` fields support the one-group-per-asset model.

## Edge Cases

- **All monitor types already exist:** The Create Monitor modal shows all types greyed out. The "Next" button is disabled with a message like "All monitor types are already active."
- **Removing last monitor from group:** The group remains but becomes empty. User can re-add monitors via the settings modal.
- **Asset with no warehouse connection:** Monitor type list is filtered to types that are possible without a warehouse (e.g., schema change from metadata). If none are available, show an informational message.
