# Per-Asset Health Dashboard & SLA Recommendation Writeback

**Date:** 2026-04-13
**Status:** Approved

## Overview

Two related improvements:

1. **Per-Asset Data Health** — The summary tab's Data Health section currently groups monitors by category (Freshness, Volume, Quality, etc.). Change it to group by data asset (table/view), showing all monitor statuses for each asset in one row. Category cards stay as quick-filter toggles.

2. **SLA Recommendation Writeback** — When a drift recommendation is accepted, write the new threshold to both the monitor config (already happens) AND the PolicyAssignment/PolicyProfile SLA settings for that asset.

---

## Part 1: Per-Asset Data Health

### Current State

The Data Health section shows 6 category cards (Freshness 4/4, Volume 2/4, etc.). Clicking a card shows sparklines grouped by that category — e.g., clicking "Volume" shows volume sparklines for all tables.

### New Design

**Category cards** become a filter bar — smaller, horizontal, pill-shaped toggles that filter which monitor types are visible in the asset rows below.

**Asset rows** are the primary view — one row per data asset (table/view/model), showing:

- Asset name (e.g. `customers`) and FQN in mono
- Status badges for each monitor type on that asset (e.g. Freshness: PASS, Volume: FAIL, Quality: PASS, Schema: PASS)
- Overall health: pass count / total count with a small progress bar
- Expandable: click to show sparklines for all monitors on that asset

**Filtering:** Clicking a category pill in the filter bar highlights it and only shows assets that have monitors of that type (and only shows those monitor badges). Clicking again deselects. Multiple categories can be selected. No selection = show all.

### API Changes

Modify `GET /api/schedule/monitor-trends` response to also include an `assets` grouping:

```json
{
  "dataHealth": { ... },
  "assets": {
    "bigquery.dataset.customers": {
      "name": "customers",
      "fqn": "bigquery.dataset.customers",
      "total": 6,
      "passing": 5,
      "warning": 0,
      "failing": 1,
      "status": "drifting",
      "monitors": [
        {
          "id": "mon_1",
          "name": "FRESHNESS — customers",
          "category": "freshness",
          "latestStatus": "PASS",
          "latestValue": 2.5,
          "baselineMean": 3.1,
          "pctChange": -19.4,
          "runs": [...]
        },
        {
          "id": "mon_2",
          "name": "VOLUME — customers",
          "category": "volume",
          "latestStatus": "FAIL",
          ...
        }
      ]
    }
  },
  "pipelineHealth": { ... },
  "updatedAt": "..."
}
```

The `assets` record is keyed by `targetFqn`. Each asset has all its monitors with a `category` field added (derived from `MONITOR_TYPE_TO_CATEGORY`).

The existing `dataHealth` by-category grouping stays for the category filter pill counts.

### Component Changes

**DriftSummaryTab.tsx:**
- Replace the category card grid with a **category filter bar** — horizontal row of smaller pill-shaped buttons showing category name + pass/total. Multiple can be active. Clicking toggles.
- Below the filter bar, render **asset rows** — one per asset from `trendData.assets`. Each row is a card showing asset name, monitor status badges, health progress bar, and expand arrow.
- Clicking an asset row expands the accordion (same CategorySparklinePanel, but showing all monitors for that asset instead of all monitors for a category).
- When category filter pills are active, only show assets that have monitors in those categories, and only show those monitors' badges.

**New component: `AssetHealthRow.tsx`:**
- Compact row showing: asset name, FQN, per-category status dots/badges, pass/total, progress bar, expand button
- Expanded state: shows sparklines for each monitor on that asset

### Auto-expand behavior

Auto-expand the first asset that has failing monitors. If none are failing, expand the first asset with warnings. If all stable, don't auto-expand.

---

## Part 2: SLA Recommendation Writeback

### Current State

When accepting a drift recommendation in `PATCH /api/drift/[id]`, it only writes to `monitor.config`:

```typescript
config[rec.currentField.replace('.', '_')] = Number(applyValue);
await prisma.monitor.update({ where: { id: rec.monitorId }, data: { config } });
```

### New Behavior

On accept, also write to the **PolicyAssignment** for that asset:

1. Look up the monitor's `targetFqn`
2. Find the `PolicyAssignment` with `nodeFqn = targetFqn` and `assignmentType = 'direct'`
3. If it exists, update the appropriate config field on the linked `PolicyProfile` (or the `overrides` JSON on the assignment)
4. If no direct assignment exists, create one with a new PolicyProfile containing just the accepted threshold

### Field Mapping

The drift recommendation's `currentField` uses dot notation like `freshness.maxHours`, `volume.minRows`, `quality.maxNullRate`. These map to PolicyProfile columns:

| currentField | PolicyProfile column | JSON key |
|---|---|---|
| `freshness.maxHours` | `freshnessConfig` | `maxHours` |
| `freshness.warningHours` | `freshnessConfig` | `warningHours` |
| `volume.minRows` | `volumeConfig` | `minRows` |
| `volume.maxRows` | `volumeConfig` | `maxRows` |
| `volume.growthRateThreshold` | `volumeConfig` | `growthRateThreshold` |
| `quality.maxNullRate` | `qualityConfig` | `maxNullRate` |
| `quality.maxDuplicateRate` | `qualityConfig` | `maxDuplicateRate` |
| `schema.strictness` | `schemaConfig` | `strictness` |
| `anomaly.sensitivity` | `anomalyConfig` | `sensitivity` |
| `anomaly.lookbackDays` | `anomalyConfig` | `lookbackDays` |

### Implementation

In `app/api/drift/[id]/route.ts`, after writing to `monitor.config`, add:

```typescript
// Write to SLA policy assignment
const targetFqn = rec.targetFqn;
const [section, field] = rec.currentField.split('.');
const configColumn = `${section}Config`; // e.g. "freshnessConfig"

// Find or create direct policy assignment for this asset
let assignment = await prisma.policyAssignment.findFirst({
  where: { nodeFqn: targetFqn, assignmentType: 'direct', organizationId },
  include: { profile: true },
});

if (assignment) {
  // Update the profile's config
  const existing = (assignment.profile[configColumn] as Record<string, any>) || {};
  existing[field] = isNaN(Number(applyValue)) ? applyValue : Number(applyValue);
  await prisma.policyProfile.update({
    where: { id: assignment.profileId },
    data: { [configColumn]: existing },
  });
} else {
  // Create a new profile + assignment
  const profile = await prisma.policyProfile.create({
    data: {
      name: `Auto — ${targetFqn.split('.').pop()}`,
      description: 'Auto-created from drift recommendation',
      organizationId,
      [configColumn]: { [field]: isNaN(Number(applyValue)) ? applyValue : Number(applyValue) },
    },
  });
  await prisma.policyAssignment.create({
    data: {
      profileId: profile.id,
      nodeFqn: targetFqn,
      assignmentType: 'direct',
      organizationId,
    },
  });
}
```

### Edge Cases

- If the asset already has a direct assignment, update the existing profile's config section — don't create a duplicate
- If the profile is shared (isBuiltIn or used by multiple assignments), DON'T modify it. Instead, create a new profile with the override and reassign
- The `overrides` JSON on PolicyAssignment could also be used instead of modifying the profile directly — this is cleaner if the profile is shared. Use overrides by default: `{ "freshness": { "maxHours": 24 } }`

### Preferred approach: Use overrides

Rather than modifying profiles (which may be shared), write to `PolicyAssignment.overrides`:

```typescript
if (assignment) {
  const overrides = (assignment.overrides as Record<string, any>) || {};
  if (!overrides[section]) overrides[section] = {};
  overrides[section][field] = isNaN(Number(applyValue)) ? applyValue : Number(applyValue);
  await prisma.policyAssignment.update({
    where: { id: assignment.id },
    data: { overrides },
  });
} else {
  // Find or create a default profile, then create assignment with overrides
  let defaultProfile = await prisma.policyProfile.findFirst({
    where: { organizationId, isBuiltIn: true },
  });
  if (!defaultProfile) {
    defaultProfile = await prisma.policyProfile.findFirst({
      where: { organizationId },
      orderBy: { createdAt: 'asc' },
    });
  }
  if (defaultProfile) {
    await prisma.policyAssignment.create({
      data: {
        profileId: defaultProfile.id,
        nodeFqn: targetFqn,
        assignmentType: 'direct',
        organizationId,
        overrides: { [section]: { [field]: isNaN(Number(applyValue)) ? applyValue : Number(applyValue) } },
      },
    });
  }
}
```

---

## Files to Modify

### Per-Asset Health
| File | Change |
|------|--------|
| `app/api/schedule/monitor-trends/route.ts` | Add `assets` grouping to response |
| `components/monitors/DriftSummaryTab.tsx` | Replace category cards with filter pills + asset rows |
| `components/monitors/AssetHealthRow.tsx` | New — compact asset row with category badges + expand |

### SLA Writeback
| File | Change |
|------|--------|
| `app/api/drift/[id]/route.ts` | Add PolicyAssignment writeback after monitor config update |

---

## Testing

### Per-Asset Health
- Verify assets are grouped by targetFqn with all their monitors
- Verify category filter pills toggle correctly (multi-select)
- Verify clicking an asset row expands sparklines for all its monitors
- Verify auto-expand picks first failing asset

### SLA Writeback
- Verify accepting a recommendation writes to both monitor.config AND PolicyAssignment.overrides
- Verify existing direct assignment gets its overrides updated (not duplicated)
- Verify new direct assignment is created when none exists
- Verify the SLA panel on the lineage page reflects the updated value
