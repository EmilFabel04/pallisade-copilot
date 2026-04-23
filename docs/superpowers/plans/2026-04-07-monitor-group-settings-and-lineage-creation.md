# Monitor Group Settings & Lineage Monitor Creation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a gear icon to monitor groups that opens a settings modal (schedule, alerts, monitor type checklist), and enable monitor creation from the lineage data asset detail panel with automatic group assignment.

**Architecture:** New `MonitorGroupSettingsModal` component reuses existing `ScheduleInput` and `AlertChannelPicker`. New `AssetMonitorCreationModal` is a simplified 3-step wizard. The PATCH watches endpoint is extended to support `addMonitorTypes`. A new GET endpoint fetches monitors for an asset by FQN.

**Tech Stack:** React, Next.js API routes, Prisma, TypeScript, Tailwind CSS

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `components/schedule/MonitorGroupSettingsModal.tsx` | Create | Settings modal: schedule, alerts, monitor type toggle |
| `components/schedule/WatchCard.tsx` | Modify | Add gear icon button |
| `components/schedule/WatchDetailPanel.tsx` | Modify | Add gear icon button |
| `app/api/schedule/watches/[watchId]/route.ts` | Modify | Extend PATCH to accept `addMonitorTypes` |
| `components/lineage/AssetMonitorCreationModal.tsx` | Create | 3-step creation wizard scoped to one asset |
| `components/lineage/DataAssetDetailPanel.tsx` | Modify | Add Monitors section with create button |
| `app/api/schedule/watches/by-anchor/route.ts` | Create | GET monitors for an asset by anchorFqn |
| `app/(dashboard)/dashboard/monitors/page.tsx` | Modify | Wire up settings modal state |

---

### Task 1: Extend PATCH Endpoint to Support `addMonitorTypes`

**Files:**
- Modify: `app/api/schedule/watches/[watchId]/route.ts`

- [ ] **Step 1: Read the current PATCH handler**

Read `app/api/schedule/watches/[watchId]/route.ts` to confirm the current structure. The PATCH handler starts around line 143 and accepts `removeMonitorIds`. We will add `addMonitorTypes`.

- [ ] **Step 2: Add `addMonitorTypes` handling to PATCH**

In the PATCH handler, after the existing `removeMonitorIds` block, add logic to create new monitors for each type in `addMonitorTypes`. Add this code inside the existing transaction, after the monitor removal block:

```typescript
// --- Add new monitors by type ---
const addMonitorTypes = body.addMonitorTypes as string[] | undefined;
if (addMonitorTypes?.length) {
  const existingMonitors = await tx.monitor.findMany({
    where: { monitorGroupId: watchId, organizationId: org.id },
    select: { monitorType: true },
  });
  const existingTypes = new Set(existingMonitors.map((m) => m.monitorType));

  const anchorFqn = group.anchorFqn || group.name;
  const nextRunAt = group.schedule
    ? (() => {
        try {
          const { parseExpression } = require('cron-parser');
          return parseExpression(group.schedule, { tz: group.timezone || 'UTC' }).next().toDate();
        } catch {
          return null;
        }
      })()
    : null;

  for (const monitorType of addMonitorTypes) {
    if (existingTypes.has(monitorType)) continue; // skip duplicates

    await tx.monitor.create({
      data: {
        name: `${monitorType.replace(/_/g, ' ').toLowerCase()} — ${anchorFqn.split('.').pop()}`,
        monitorType,
        targetFqn: anchorFqn,
        config: {},
        enabled: group.enabled,
        schedule: group.schedule,
        timezone: group.timezone,
        alertChannels: group.alertChannels as any || [],
        alertOnStatus: group.alertOnStatus as any || [],
        nextRunAt,
        organizationId: org.id,
        monitorGroupId: watchId,
        taskMode: 'structured',
      },
    });
  }
}
```

- [ ] **Step 3: Verify the PATCH endpoint compiles**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "watches/\[watchId\]/route" | head -20`
Expected: No errors related to this file.

- [ ] **Step 4: Commit**

```bash
git add app/api/schedule/watches/\[watchId\]/route.ts
git commit -m "feat: extend PATCH watches endpoint to support addMonitorTypes"
```

---

### Task 2: Create `GET /api/schedule/watches/by-anchor` Endpoint

**Files:**
- Create: `app/api/schedule/watches/by-anchor/route.ts`

- [ ] **Step 1: Create the endpoint**

This endpoint returns the monitor group and its monitors for a given asset FQN. Used by both the settings modal and the lineage panel to find existing monitors.

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/auth-options';
import { prisma } from '@/lib/prisma';

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions);
  if (!session?.user?.organizationId) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const orgId = session.user.organizationId;

  const anchorFqn = req.nextUrl.searchParams.get('anchorFqn');
  if (!anchorFqn) {
    return NextResponse.json({ error: 'anchorFqn is required' }, { status: 400 });
  }

  const group = await prisma.monitorGroup.findFirst({
    where: {
      organizationId: orgId,
      anchorFqn,
      monitoringPlanId: null, // standalone groups only
    },
    include: {
      monitors: {
        select: {
          id: true,
          name: true,
          monitorType: true,
          enabled: true,
          lastStatus: true,
          lastRunAt: true,
          config: true,
        },
        orderBy: { createdAt: 'asc' },
      },
    },
  });

  return NextResponse.json({ group: group || null });
}
```

- [ ] **Step 2: Verify the endpoint compiles**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "by-anchor" | head -10`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add app/api/schedule/watches/by-anchor/route.ts
git commit -m "feat: add GET watches/by-anchor endpoint to look up group by asset FQN"
```

---

### Task 3: Create `MonitorGroupSettingsModal` Component

**Files:**
- Create: `components/schedule/MonitorGroupSettingsModal.tsx`

- [ ] **Step 1: Create the modal component**

```typescript
'use client';

import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { X, Loader2 } from 'lucide-react';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import { MONITOR_CATALOG, getMonitorDefinition } from '@/types/monitor-catalog';

interface MonitorGroupSettingsModalProps {
  watchId: string;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  integrations?: Array<{ id: string; name: string; type: string }>;
}

interface WatchDetail {
  id: string;
  name: string;
  anchorFqn: string | null;
  schedule: string | null;
  timezone: string | null;
  alertChannels: string[];
  alertOnStatus: string[];
  enabled: boolean;
  monitors: Array<{
    id: string;
    name: string;
    monitorType: string;
    enabled: boolean;
    lastStatus: string | null;
  }>;
}

/** Monitor types relevant for data asset groups (non-tool, non-BI) */
const ASSET_MONITOR_TYPES = [
  'FRESHNESS',
  'VOLUME',
  'SCHEMA_CHANGE',
  'NULL_CHECK',
  'UNIQUENESS_CHECK',
  'RANGE_VALIDATION',
  'ACCEPTED_VALUES',
  'CUSTOM_SQL',
  'OUTLIER_DETECTION',
  'REFERENTIAL',
  'DATA_TYPE_VALIDATION',
  'DATE_CONSISTENCY',
  'CONTRACT_CHECK',
];

export function MonitorGroupSettingsModal({
  watchId,
  open,
  onClose,
  onSaved,
  integrations,
}: MonitorGroupSettingsModalProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [watch, setWatch] = useState<WatchDetail | null>(null);

  // Form state
  const [schedule, setSchedule] = useState('');
  const [timezone, setTimezone] = useState('UTC');
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>([]);
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set());

  // Track original state for dirty detection
  const [originalTypes, setOriginalTypes] = useState<Set<string>>(new Set());

  const fetchWatch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/schedule/watches/${watchId}`);
      if (!res.ok) throw new Error('Failed to fetch watch');
      const data = await res.json();
      const w = data.watch || data;
      setWatch(w);
      setSchedule(w.schedule || '');
      setTimezone(w.timezone || 'UTC');
      setAlertChannels(w.alertChannels || []);
      setAlertOnStatus(w.alertOnStatus || []);
      const types = new Set<string>(w.monitors?.map((m: any) => m.monitorType) || []);
      setActiveTypes(types);
      setOriginalTypes(new Set(types));
    } catch (err) {
      console.error('[MonitorGroupSettings] fetch error:', err);
      toast.error('Failed to load group settings');
    } finally {
      setLoading(false);
    }
  }, [watchId]);

  useEffect(() => {
    if (open) fetchWatch();
  }, [open, fetchWatch]);

  const handleToggleType = (type: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (!watch) return;
    setSaving(true);
    try {
      // Compute diffs
      const addMonitorTypes = [...activeTypes].filter((t) => !originalTypes.has(t));
      const removedTypes = [...originalTypes].filter((t) => !activeTypes.has(t));
      const removeMonitorIds = watch.monitors
        .filter((m) => removedTypes.includes(m.monitorType))
        .map((m) => m.id);

      const res = await fetch(`/api/schedule/watches/${watchId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          schedule: schedule || undefined,
          timezone: timezone || undefined,
          alertChannels,
          alertOnStatus,
          ...(addMonitorTypes.length > 0 && { addMonitorTypes }),
          ...(removeMonitorIds.length > 0 && { removeMonitorIds }),
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Failed to save');
      }

      toast.success('Group settings saved');
      onSaved();
      onClose();
    } catch (err: any) {
      console.error('[MonitorGroupSettings] save error:', err);
      toast.error(err.message || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-lg bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl shadow-2xl max-h-[85vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div>
            <h2 className="text-base font-semibold text-[var(--text)]">Group Settings</h2>
            {watch && (
              <p className="text-xs text-[var(--muted)] mt-0.5">
                {watch.name}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
          </div>
        ) : (
          <div className="px-6 py-4 space-y-4">
            {/* Schedule Section */}
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Schedule
              </h3>
              <ScheduleInput value={schedule} onChange={setSchedule} />
            </div>

            {/* Alert Section */}
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Alert Platform
              </h3>
              <AlertChannelPicker
                channels={alertChannels}
                onChannelsChange={setAlertChannels}
                alertOnStatus={alertOnStatus}
                onAlertOnStatusChange={setAlertOnStatus}
                integrations={integrations}
              />
            </div>

            {/* Monitor Types Section */}
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Monitors
              </h3>
              <div className="space-y-1.5">
                {ASSET_MONITOR_TYPES.map((type) => {
                  const def = getMonitorDefinition(type);
                  if (!def) return null;
                  const isActive = activeTypes.has(type);
                  return (
                    <button
                      key={type}
                      onClick={() => handleToggleType(type)}
                      className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-left transition-colors ${
                        isActive
                          ? 'bg-emerald-500/10 border border-emerald-500/30'
                          : 'bg-[var(--overlay-light)] border border-transparent hover:border-[var(--subtle-border)]'
                      }`}
                    >
                      <div
                        className={`w-4 h-4 rounded flex items-center justify-center text-[10px] font-bold ${
                          isActive
                            ? 'bg-emerald-500 text-white'
                            : 'border border-[var(--overlay-strong)]'
                        }`}
                      >
                        {isActive && '✓'}
                      </div>
                      <span
                        className={`text-sm flex-1 ${
                          isActive ? 'text-[var(--text)]' : 'text-[var(--muted)]'
                        }`}
                      >
                        {def.label}
                      </span>
                      {isActive && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400">
                          Active
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-[var(--subtle-border)]">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg text-[var(--muted)] hover:text-[var(--text)] bg-[var(--overlay-light)] hover:bg-[var(--hover-bg)]"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the component compiles**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "MonitorGroupSettings" | head -10`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add components/schedule/MonitorGroupSettingsModal.tsx
git commit -m "feat: add MonitorGroupSettingsModal component"
```

---

### Task 4: Add Gear Icon to WatchCard

**Files:**
- Modify: `components/schedule/WatchCard.tsx`

- [ ] **Step 1: Read current WatchCard header**

Read `components/schedule/WatchCard.tsx` and find the header section where `onDelete` and toggle actions are rendered.

- [ ] **Step 2: Add `onSettings` prop and gear icon**

Add `onSettings?: () => void` to the `WatchCardProps` interface (alongside the existing `onDelete`, `onToggleEnabled`, etc.).

In the card header actions area (where the toggle/run/delete buttons are), add a gear icon button before the existing overflow menu:

```typescript
{onSettings && (
  <button
    onClick={(e) => {
      e.stopPropagation();
      onSettings();
    }}
    className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
    title="Group settings"
  >
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  </button>
)}
```

- [ ] **Step 3: Verify compilation**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "WatchCard" | head -10`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add components/schedule/WatchCard.tsx
git commit -m "feat: add gear icon to WatchCard for group settings"
```

---

### Task 5: Add Gear Icon to WatchDetailPanel

**Files:**
- Modify: `components/schedule/WatchDetailPanel.tsx`

- [ ] **Step 1: Read the WatchDetailPanel header section**

Read `components/schedule/WatchDetailPanel.tsx` and locate the header section (around lines 100-150) where the back button, toggle, run, and delete buttons are rendered.

- [ ] **Step 2: Add `onSettings` prop and gear icon**

Add `onSettings?: () => void` to `WatchDetailPanelProps`.

In the header's right-side actions (the `<div className="flex items-center gap-2">` that contains the toggle, run, delete buttons), add the gear icon before the enable toggle:

```typescript
{onSettings && (
  <button
    onClick={onSettings}
    className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
    title="Group settings"
  >
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  </button>
)}
```

- [ ] **Step 3: Verify compilation**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "WatchDetailPanel" | head -10`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add components/schedule/WatchDetailPanel.tsx
git commit -m "feat: add gear icon to WatchDetailPanel for group settings"
```

---

### Task 6: Wire Settings Modal into Monitors Page

**Files:**
- Modify: `app/(dashboard)/dashboard/monitors/page.tsx`

- [ ] **Step 1: Read the monitors page**

Read `app/(dashboard)/dashboard/monitors/page.tsx` to find where `WatchCard` and `WatchDetailPanel` are rendered, and how modal state is managed.

- [ ] **Step 2: Add settings modal state and rendering**

Add the following state and import to the monitors page:

```typescript
import { MonitorGroupSettingsModal } from '@/components/schedule/MonitorGroupSettingsModal';

// In the component body:
const [settingsWatchId, setSettingsWatchId] = useState<string | null>(null);
```

Pass `onSettings` to each `WatchCard`:

```typescript
onSettings={() => setSettingsWatchId(watch.id)}
```

Pass `onSettings` to `WatchDetailPanel`:

```typescript
onSettings={() => setSettingsWatchId(watch.id)}
```

Render the modal at the bottom of the component (before the closing fragment/div):

```typescript
<MonitorGroupSettingsModal
  watchId={settingsWatchId || ''}
  open={!!settingsWatchId}
  onClose={() => setSettingsWatchId(null)}
  onSaved={() => {
    setSettingsWatchId(null);
    fetchWatches(); // re-fetch watch list
  }}
  integrations={integrations}
/>
```

- [ ] **Step 3: Verify compilation**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "monitors/page" | head -10`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add app/\(dashboard\)/dashboard/monitors/page.tsx
git commit -m "feat: wire MonitorGroupSettingsModal into monitors page"
```

---

### Task 7: Create `AssetMonitorCreationModal` Component

**Files:**
- Create: `components/lineage/AssetMonitorCreationModal.tsx`

- [ ] **Step 1: Create the 3-step modal**

This modal is a simplified version of `MultiMonitorModal`, scoped to a single asset. Steps: 1) select monitor types, 2) schedule, 3) alerts.

```typescript
'use client';

import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { X, Loader2, ChevronRight, ChevronLeft } from 'lucide-react';
import { ScheduleInput } from '@/components/schedule/ScheduleInput';
import { AlertChannelPicker } from '@/components/schedule/AlertChannelPicker';
import { getMonitorDefinition } from '@/types/monitor-catalog';

interface AssetMonitorCreationModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  /** The asset's fully-qualified name */
  assetFqn: string;
  /** The asset's engine node ID */
  assetNodeId: string;
  /** Display name for the asset */
  assetName: string;
  integrations?: Array<{ id: string; name: string; type: string }>;
}

type Step = 1 | 2 | 3;

const STEP_LABELS: Record<Step, string> = {
  1: 'Monitors',
  2: 'Schedule',
  3: 'Alerts',
};

/** Monitor types available for data assets */
const ASSET_MONITOR_TYPES = [
  'FRESHNESS',
  'VOLUME',
  'SCHEMA_CHANGE',
  'NULL_CHECK',
  'UNIQUENESS_CHECK',
  'RANGE_VALIDATION',
  'ACCEPTED_VALUES',
  'CUSTOM_SQL',
  'OUTLIER_DETECTION',
  'REFERENTIAL',
  'DATA_TYPE_VALIDATION',
  'DATE_CONSISTENCY',
  'CONTRACT_CHECK',
];

export function AssetMonitorCreationModal({
  open,
  onClose,
  onCreated,
  assetFqn,
  assetNodeId,
  assetName,
  integrations,
}: AssetMonitorCreationModalProps) {
  const [step, setStep] = useState<Step>(1);
  const [saving, setSaving] = useState(false);
  const [existingTypes, setExistingTypes] = useState<Set<string>>(new Set());
  const [existingGroupId, setExistingGroupId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Step 1: Monitor type selection
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set());

  // Step 2: Schedule
  const [schedule, setSchedule] = useState('0 */6 * * *');
  const [timezone, setTimezone] = useState('UTC');

  // Step 3: Alerts
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN']);

  // Fetch existing group for this asset on open
  const fetchExisting = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/schedule/watches/by-anchor?anchorFqn=${encodeURIComponent(assetFqn)}`);
      if (res.ok) {
        const data = await res.json();
        if (data.group) {
          setExistingGroupId(data.group.id);
          setExistingTypes(new Set(data.group.monitors.map((m: any) => m.monitorType)));
          // Pre-fill schedule/alerts from existing group
          if (data.group.schedule) setSchedule(data.group.schedule);
          if (data.group.timezone) setTimezone(data.group.timezone);
          if (data.group.alertChannels?.length) setAlertChannels(data.group.alertChannels);
          if (data.group.alertOnStatus?.length) setAlertOnStatus(data.group.alertOnStatus);
        }
      }
    } catch (err) {
      console.error('[AssetMonitorCreation] fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [assetFqn]);

  useEffect(() => {
    if (open) {
      setStep(1);
      setSelectedTypes(new Set());
      setExistingTypes(new Set());
      setExistingGroupId(null);
      fetchExisting();
    }
  }, [open, fetchExisting]);

  const handleToggleType = (type: string) => {
    if (existingTypes.has(type)) return; // can't toggle existing
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (selectedTypes.size === 0) return;
    setSaving(true);
    try {
      if (existingGroupId) {
        // Add to existing group via PATCH
        const res = await fetch(`/api/schedule/watches/${existingGroupId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            schedule,
            timezone,
            alertChannels,
            alertOnStatus,
            addMonitorTypes: [...selectedTypes],
          }),
        });
        if (!res.ok) throw new Error('Failed to add monitors');
      } else {
        // Create new group via POST
        const monitors = [...selectedTypes].map((type) => ({
          monitorType: type,
          targetFqn: assetFqn,
          config: {},
          depth: 0,
          priority: 1,
        }));

        const res = await fetch('/api/schedule/watches', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: assetName,
            watchType: 'custom_watch',
            anchorFqn: assetFqn,
            anchorNodeId: assetNodeId,
            schedule,
            timezone,
            alertChannels,
            alertOnStatus,
            monitors,
          }),
        });
        if (!res.ok) throw new Error('Failed to create monitor group');
      }

      toast.success(
        existingGroupId ? 'Monitors added to group' : 'Monitor group created'
      );
      onCreated();
      onClose();
    } catch (err: any) {
      console.error('[AssetMonitorCreation] save error:', err);
      toast.error(err.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  const newSelectionCount = selectedTypes.size;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      <div className="relative z-10 w-full max-w-lg bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl shadow-2xl max-h-[85vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div>
            <h2 className="text-base font-semibold text-[var(--text)]">Create Monitor</h2>
            <p className="text-xs text-[var(--muted)] mt-0.5">
              {existingGroupId ? 'Adding to' : 'Creating group for'}{' '}
              <span className="text-blue-400">{assetName}</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-6 px-6 py-3 border-b border-[var(--subtle-border)]">
          {([1, 2, 3] as Step[]).map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${
                  s === step
                    ? 'bg-blue-600 text-white'
                    : s < step
                      ? 'bg-emerald-500/20 text-emerald-400'
                      : 'bg-[var(--overlay-medium)] text-[var(--muted)]'
                }`}
              >
                {s < step ? '✓' : s}
              </div>
              <span
                className={`text-xs ${
                  s === step ? 'text-[var(--text)] font-medium' : 'text-[var(--muted)]'
                }`}
              >
                {STEP_LABELS[s]}
              </span>
            </div>
          ))}
        </div>

        {/* Body */}
        <div className="px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
            </div>
          ) : step === 1 ? (
            /* Step 1: Monitor Types */
            <div className="space-y-1.5">
              {ASSET_MONITOR_TYPES.map((type) => {
                const def = getMonitorDefinition(type);
                if (!def) return null;
                const alreadyExists = existingTypes.has(type);
                const isSelected = selectedTypes.has(type);
                return (
                  <button
                    key={type}
                    onClick={() => handleToggleType(type)}
                    disabled={alreadyExists}
                    className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-left transition-colors ${
                      alreadyExists
                        ? 'opacity-50 cursor-not-allowed bg-[var(--overlay-light)]'
                        : isSelected
                          ? 'bg-blue-500/10 border border-blue-500/30'
                          : 'bg-[var(--overlay-light)] border border-transparent hover:border-[var(--subtle-border)]'
                    }`}
                  >
                    <div
                      className={`w-4 h-4 rounded flex items-center justify-center text-[10px] font-bold ${
                        alreadyExists
                          ? 'bg-[var(--overlay-strong)] text-[var(--muted)]'
                          : isSelected
                            ? 'bg-blue-500 text-white'
                            : 'border border-[var(--overlay-strong)]'
                      }`}
                    >
                      {(alreadyExists || isSelected) && '✓'}
                    </div>
                    <span className={`text-sm flex-1 ${alreadyExists ? 'text-[var(--muted)]' : 'text-[var(--text)]'}`}>
                      {def.label}
                    </span>
                    {alreadyExists && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--overlay-medium)] text-[var(--muted)]">
                        Already exists
                      </span>
                    )}
                    {isSelected && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-400">
                        New
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : step === 2 ? (
            /* Step 2: Schedule */
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Schedule
              </h3>
              <ScheduleInput value={schedule} onChange={setSchedule} />
            </div>
          ) : (
            /* Step 3: Alerts */
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Alert Platform
              </h3>
              <AlertChannelPicker
                channels={alertChannels}
                onChannelsChange={setAlertChannels}
                alertOnStatus={alertOnStatus}
                onAlertOnStatusChange={setAlertOnStatus}
                integrations={integrations}
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between px-6 py-4 border-t border-[var(--subtle-border)]">
          <button
            onClick={() => (step === 1 ? onClose() : setStep((step - 1) as Step))}
            className="flex items-center gap-1 px-4 py-2 text-sm rounded-lg text-[var(--muted)] hover:text-[var(--text)] bg-[var(--overlay-light)] hover:bg-[var(--hover-bg)]"
          >
            {step === 1 ? 'Cancel' : <><ChevronLeft className="w-3 h-3" /> Back</>}
          </button>

          {step < 3 ? (
            <button
              onClick={() => setStep((step + 1) as Step)}
              disabled={step === 1 && newSelectionCount === 0}
              className="flex items-center gap-1 px-5 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
            >
              Next <ChevronRight className="w-3 h-3" />
            </button>
          ) : (
            <button
              onClick={handleSave}
              disabled={saving || newSelectionCount === 0}
              className="px-5 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {saving
                ? 'Creating…'
                : `Create ${newSelectionCount} Monitor${newSelectionCount !== 1 ? 's' : ''}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify compilation**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "AssetMonitorCreation" | head -10`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add components/lineage/AssetMonitorCreationModal.tsx
git commit -m "feat: add AssetMonitorCreationModal for lineage monitor creation"
```

---

### Task 8: Add Monitors Section to DataAssetDetailPanel

**Files:**
- Modify: `components/lineage/DataAssetDetailPanel.tsx`

- [ ] **Step 1: Read the panel component**

Read `components/lineage/DataAssetDetailPanel.tsx` to find:
1. The props interface (around line 72)
2. Where sections are rendered (the Section components)
3. The existing monitor recommendation section

- [ ] **Step 2: Add `onCreateAssetMonitor` prop**

Add to `DataAssetDetailPanelProps`:

```typescript
onCreateAssetMonitor?: (assetFqn: string, assetNodeId: string, assetName: string) => void;
```

- [ ] **Step 3: Add monitors section state and fetch**

Inside the component body, add state for fetching existing monitors for this asset:

```typescript
const [assetMonitors, setAssetMonitors] = useState<Array<{
  id: string;
  name: string;
  monitorType: string;
  enabled: boolean;
  lastStatus: string | null;
}>>([]);
const [assetMonitorsLoading, setAssetMonitorsLoading] = useState(false);

useEffect(() => {
  const fqn = node.fullName || node.name;
  if (!fqn) return;
  setAssetMonitorsLoading(true);
  fetch(`/api/schedule/watches/by-anchor?anchorFqn=${encodeURIComponent(fqn)}`)
    .then((res) => res.ok ? res.json() : { group: null })
    .then((data) => {
      setAssetMonitors(data.group?.monitors || []);
    })
    .catch(() => setAssetMonitors([]))
    .finally(() => setAssetMonitorsLoading(false));
}, [node.fullName, node.name]);
```

- [ ] **Step 4: Add Monitors section before existing SLA section**

Find the SLA Profile section and add the Monitors section just before it:

```typescript
{/* Monitors */}
<Section title="Monitors" count={assetMonitors.length} defaultOpen>
  {assetMonitorsLoading ? (
    <div className="flex items-center justify-center py-4">
      <Loader2 className="w-4 h-4 animate-spin text-[var(--muted)]" />
    </div>
  ) : (
    <div className="space-y-2 mt-2">
      {assetMonitors.length > 0 ? (
        <div className="space-y-1">
          {assetMonitors.map((m) => (
            <div
              key={m.id}
              className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[var(--overlay-light)]"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  m.lastStatus === 'PASS'
                    ? 'bg-emerald-400'
                    : m.lastStatus === 'WARN'
                      ? 'bg-amber-400'
                      : m.lastStatus === 'FAIL'
                        ? 'bg-red-400'
                        : 'bg-[var(--overlay-strong)]'
                }`}
              />
              <span className="text-xs text-[var(--text)] flex-1">{m.name}</span>
              <span className={`text-[10px] ${
                m.lastStatus === 'PASS'
                  ? 'text-emerald-400'
                  : m.lastStatus === 'WARN'
                    ? 'text-amber-400'
                    : m.lastStatus === 'FAIL'
                      ? 'text-red-400'
                      : 'text-[var(--muted)]'
              }`}>
                {m.lastStatus || 'Pending'}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-[var(--muted)]">No monitors configured</p>
      )}

      {onCreateAssetMonitor && (
        <button
          onClick={() => {
            const fqn = node.fullName || node.name;
            const engineId = node.id.replace(/^lineage-/, '');
            const name = node.name.split('.').pop() || node.name;
            onCreateAssetMonitor(fqn, engineId, name);
          }}
          className="flex items-center gap-1 px-2 py-1.5 text-xs text-blue-400 hover:text-blue-300 rounded-md hover:bg-blue-500/10 w-full"
        >
          <Plus className="w-3 h-3" />
          Create Monitor
        </button>
      )}
    </div>
  )}
</Section>
```

Add `Loader2` to the existing lucide-react import if not already there.

- [ ] **Step 5: Verify compilation**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | grep -i "DataAssetDetail" | head -10`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add components/lineage/DataAssetDetailPanel.tsx
git commit -m "feat: add Monitors section to DataAssetDetailPanel with create button"
```

---

### Task 9: Wire AssetMonitorCreationModal into Lineage Page

**Files:**
- Modify: The parent component that renders `DataAssetDetailPanel` (likely the lineage page or a wrapper component)

- [ ] **Step 1: Find the lineage page that renders DataAssetDetailPanel**

Run: `grep -rl "DataAssetDetailPanel" --include="*.tsx" components/ app/` to find which page renders it.

- [ ] **Step 2: Add modal state and rendering**

In the parent component, add:

```typescript
import { AssetMonitorCreationModal } from '@/components/lineage/AssetMonitorCreationModal';

// State
const [assetMonitorCreate, setAssetMonitorCreate] = useState<{
  fqn: string;
  nodeId: string;
  name: string;
} | null>(null);
```

Pass the callback to `DataAssetDetailPanel`:

```typescript
onCreateAssetMonitor={(fqn, nodeId, name) =>
  setAssetMonitorCreate({ fqn, nodeId, name })
}
```

Render the modal:

```typescript
<AssetMonitorCreationModal
  open={!!assetMonitorCreate}
  onClose={() => setAssetMonitorCreate(null)}
  onCreated={() => {
    setAssetMonitorCreate(null);
    // Optionally refresh lineage data
  }}
  assetFqn={assetMonitorCreate?.fqn || ''}
  assetNodeId={assetMonitorCreate?.nodeId || ''}
  assetName={assetMonitorCreate?.name || ''}
  integrations={integrations}
/>
```

- [ ] **Step 3: Verify compilation**

Run: `npx tsc --noEmit --project tsconfig.json 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add <lineage-parent-file>
git commit -m "feat: wire AssetMonitorCreationModal into lineage page"
```

---

### Task 10: Manual Integration Testing

- [ ] **Step 1: Test settings modal from WatchCard**

1. Navigate to `/dashboard/monitors`
2. Click the gear icon on any WatchCard
3. Verify the modal shows current schedule, alerts, and active monitor types
4. Toggle a monitor type on, click Save
5. Verify the new monitor appears in the group

- [ ] **Step 2: Test settings modal from WatchDetailPanel**

1. Click into a watch to open the detail panel
2. Click the gear icon in the header
3. Verify same modal opens with correct data
4. Toggle a monitor type off, click Save
5. Verify the monitor is removed from the group

- [ ] **Step 3: Test monitor creation from lineage**

1. Navigate to the lineage page
2. Click on a data asset node
3. Verify the Monitors section shows existing monitors (or "No monitors configured")
4. Click "+ Create Monitor"
5. Select monitor types, set schedule, set alerts, click Create
6. Verify monitors are created and the Monitors section updates

- [ ] **Step 4: Test lineage creation when group already exists**

1. Navigate to lineage, click an asset that already has a monitor group
2. Click "+ Create Monitor"
3. Verify existing types show "Already exists" and are greyed out
4. Select a new type, click through steps, Create
5. Verify the new monitor is added to the existing group
