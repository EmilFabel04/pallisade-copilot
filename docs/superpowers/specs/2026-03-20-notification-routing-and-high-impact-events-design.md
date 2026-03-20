# Notification Routing & High-Impact Events

**Date:** 2026-03-20
**Status:** Draft

---

## Problem

The notification system currently creates in-app notifications for 13 event types, but:

1. **Missing high-impact events** — health score drops, sustained failures, schema breaks, anomaly spikes, and freshness breaches don't generate notifications
2. **No external platform routing** — monitor group results aren't automatically sent to Slack, PagerDuty, Teams, OpsGenie, or Email based on severity
3. **No manual forwarding** — users can't forward an in-app notification to an external platform or create a ticket from it

## Prerequisites

- **Watch run route must call `notifyEvents.monitorGroupCompleted()`** — currently only the plan run route does this. The watch run route (`/api/schedule/watches/[watchId]/run`) must be updated to create in-app notifications before any of this work can layer on top.
- **`monitorGroupCompleted` must support CRITICAL severity** — currently it only returns INFO/WARN/ERROR. Must be updated so that when health score drops below 40 (unhealthy) or sustained failures are detected, CRITICAL is produced.

## Design

### Two-Layer Notification System

**Layer 1 — In-App Notifications (always fire):**

All events go to in-app notifications as today. Every `NotificationCard` gets a 3-dot menu with:

- **"Mute notifications like this"** — suppress future in-app notifications for this event type or entity
- **"Send to Slack"** / **"Send to Teams"** / **"Send to PagerDuty"** / **"Send to OpsGenie"** / **"Send via Email"** — one-click forward this notification to connected notification platforms (only shows platforms that are actually connected; for Slack/Teams, user picks channel)
- **"Create Jira ticket"** — manual ticket creation from any notification (ticketing platforms never auto-fire). Linear and Asana deferred until their client libraries are built.

**Layer 2 — Auto-Routing (monitor group results only):**

In **Settings → Notifications**, users configure severity-based routing for monitor group run results:

| Severity | Enabled | Notify on Recovery | Destinations |
|----------|---------|-------------------|-------------|
| CRITICAL | ON/OFF  | ON/OFF            | Platform + channel picks |
| ERROR    | ON/OFF  | ON/OFF            | Platform + channel picks |
| WARN     | ON/OFF  | ON/OFF            | Platform + channel picks |
| INFO     | ON/OFF  | ON/OFF            | Platform + channel picks |

- Only applies to **monitor group run results** — the automated bread-and-butter alerts
- Other event types (integration created, lineage failed, etc.) are in-app only — user forwards manually via the 3-dot menu
- **"Notify on Recovery"** sends a notification when a group that previously failed now passes (recovery only, NOT every pass — avoids notification spam)
- Supported platforms: Slack, Teams, PagerDuty, OpsGenie, Email
- Routing rules are **organization-wide** (not scoped per pipeline profile) — all pipeline profiles share the same routing config

### New High-Impact Event Types

Detected in real-time when watch/group runs complete (no background daemon):

| Event Type | Trigger | Severity Source |
|---|---|---|
| `monitor.health_score_dropped` | Watch health transitions downward (e.g., healthy → degraded, degraded → at_risk) | Inherited from underlying failing monitor results |
| `monitor.sustained_failure` | Same monitor fails 3+ times consecutively (checked via last 3 MonitorRun records per monitor, excluding SKIPPED/RUNNING statuses). Evaluated per-monitor within the group. Threshold (3) is hardcoded for v1. | Inherited from the failing monitor's severity |
| `monitor.schema_break` | SCHEMA_CHANGE or CONNECTOR_SCHEMA_DRIFT monitor fails | From the monitor result |
| `monitor.anomaly_spike` | VOLUME, OUTLIER_DETECTION, or quality monitors exceed baseline by >2σ | From the monitor result |
| `monitor.freshness_breach` | FRESHNESS-family monitor fails (data staleness) | From the monitor result |

All high-impact events fire at the **group level** — the notification includes group summary context. These create in-app notifications and are subject to auto-routing like any group result based on their derived severity.

Note: `integration.health_degraded` is deferred — it would require a separate trigger point outside the group run flow.

### Notification Dispatch Flow

When a **watch/group run completes**:

1. **In-app notification** — always created via `notifyEvents.monitorGroupCompleted()` (must be wired into watch run route as a prerequisite)
2. **Detect high-impact events** — check results for health score drops, sustained failures, schema breaks, anomaly spikes, freshness breaches. Create additional in-app notifications for each detected event.
3. **Determine severity** — from the underlying monitor run results. CRITICAL when health score < 40 or sustained failures detected.
4. **Look up routing rules** — query `NotificationRoute` for org + severity
5. **Check recovery** — if `notifyOnRecovery` is enabled and the group previously had failures but now passes, send a recovery notification
6. **Dispatch to each destination** — using existing platform clients. `notification-router.ts` reuses the dispatch logic from the existing `/api/schedule/alert` route (credential decryption, config fallback chain, channel-specific formatting) rather than reimplementing it.

Message content sent to external platforms includes:
- Watch/group name
- Aggregate status + health score
- Failure summary (count by category: stale_data, schema_break, etc.)
- Link back to the watch in the dashboard

**Graceful handling:** If a destination's integration has been deleted or its credentials are invalid, the dispatch logs a warning and skips that destination (fire-and-forget pattern matching `lib/notifications.ts`).

### Data Model

**New table: `NotificationRoute`**

```prisma
model NotificationRoute {
  id              String               @id @default(cuid())
  organizationId  String
  organization    Organization         @relation(fields: [organizationId], references: [id], onDelete: Cascade)
  severity        NotificationSeverity
  enabled         Boolean              @default(true)
  notifyOnRecovery Boolean             @default(false)
  destinations    Json                 // [{ integrationId: string, channel?: string, config?: object }]
  createdAt       DateTime             @default(now())
  updatedAt       DateTime             @updatedAt

  @@unique([organizationId, severity])
  @@index([organizationId])
}
```

**New table: `NotificationMute`**

```prisma
model NotificationMute {
  id              String       @id @default(cuid())
  organizationId  String
  organization    Organization @relation(fields: [organizationId], references: [id], onDelete: Cascade)
  userId          String
  user            User         @relation(fields: [userId], references: [id], onDelete: Cascade)
  eventType       String       // e.g., "monitor.group_completed"
  entityType      String?      // optional — mute specific entity type
  entityId        String?      // optional — mute specific entity (e.g., watch ID)
  createdAt       DateTime     @default(now())

  @@index([organizationId, userId])
  @@index([eventType, entityType, entityId])
}
```

**Required backref additions to existing models:**
- `Organization` model: add `notificationRoutes NotificationRoute[]` and `notificationMutes NotificationMute[]`
- `User` model: add `notificationMutes NotificationMute[]`

No changes to existing `NotificationEvent` table. Mutes are checked at query time when fetching notifications and when computing unread count (`/api/notifications/unread-count`).

Existing `alertChannels`, `alertConfig`, `alertOnStatus` fields on Monitor/MonitorGroup models become deprecated in favor of centralized routing.

### API Routes

**New routes:**

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/settings/notification-routes` | GET | Fetch routing rules for org |
| `/api/settings/notification-routes` | PUT | Update routing rules for org (upserts all 4 severity rows) |
| `/api/notifications/[id]/forward` | POST | Forward notification to external platform. Body: `{ integrationId, channel?, config? }` |
| `/api/notifications/mute` | POST | Create a mute rule. Body: `{ eventType, entityType?, entityId? }` |
| `/api/notifications/mute/[id]` | DELETE | Remove a mute rule |
| `/api/notifications/mutes` | GET | List active mutes for current user |

Auth/session checking follows the pattern in `/api/notifications/route.ts`.

**Modified routes:**

| Route | Change |
|-------|--------|
| `POST /api/schedule/watches/[watchId]/run` | Add `notifyEvents.monitorGroupCompleted()` call. After group run, detect high-impact events, check routing rules, dispatch to external platforms. |
| `POST /api/schedule/plans/[planId]/run` | Same — detect high-impact events and dispatch after plan completes |
| `GET /api/notifications` | Filter out muted notifications for requesting user |
| `GET /api/notifications/unread-count` | Exclude muted notifications from count |

### Components

**New components:**

| Component | Purpose |
|-----------|---------|
| `components/notifications/NotificationCardMenu.tsx` | 3-dot menu on NotificationCard with mute/forward/create-ticket actions. Only shows connected platforms (fetches connected integrations). |
| `components/settings/NotificationRoutingSettings.tsx` | Severity → destination config table for settings page. Reuses channel picker from existing `AlertChannelPicker.tsx`. |

**Modified components:**

| Component | Change |
|-----------|--------|
| `components/notifications/NotificationCard.tsx` | Add 3-dot menu trigger |
| Settings page | Add notification routing section |

### New Lib Modules

**`lib/notification-router.ts`**

Given an event severity + org ID, looks up `NotificationRoute` rules and dispatches to each destination. **Extracts and reuses** the dispatch logic from the existing `/api/schedule/alert/route.ts` (credential decryption, config fallback chain, per-platform formatting) to avoid duplication.

```typescript
export async function routeNotification(params: {
  organizationId: string
  severity: NotificationSeverity
  title: string
  message: string
  metadata?: Record<string, unknown>
  actionUrl?: string
  isRecovery?: boolean
}): Promise<void>
```

**`lib/high-impact-events.ts`**

High-impact event detectors called after group runs complete. Each detector receives the group run results and returns detected events.

```typescript
export async function detectHighImpactEvents(params: {
  watchId: string
  organizationId: string
  pipelineStackId: string
  currentHealthScore: number
  previousHealthScore: number
  results: MonitorRunResult[]
}): Promise<HighImpactEvent[]>
```

Detectors:
- `detectHealthScoreDrop()` — compares current vs previous health score, maps to health status transitions
- `detectSustainedFailures()` — queries last 3 `MonitorRun` records per monitor (excluding SKIPPED/RUNNING), checks if all are FAIL/ERROR
- `detectSchemaBreaks()` — checks for SCHEMA_CHANGE/CONNECTOR_SCHEMA_DRIFT failures in results
- `detectAnomalySpikes()` — checks for baseline exceedance >2σ in VOLUME/OUTLIER_DETECTION results
- `detectFreshnessBreaches()` — checks for FRESHNESS-family failures in results

### Deprecation

The per-monitor/per-group `alertChannels`, `alertConfig`, and `alertOnStatus` fields are deprecated. They remain in the schema for backward compatibility but are no longer read by the new routing system. A future migration can remove them.

The existing `/api/schedule/alert` route's dispatch logic is extracted into `lib/notification-router.ts`. The route itself can remain as a legacy endpoint during transition.
