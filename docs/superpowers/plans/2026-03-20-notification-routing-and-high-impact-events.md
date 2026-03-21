# Notification Routing & High-Impact Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add severity-based auto-routing of monitor group results to external platforms (Slack, PagerDuty, Teams, OpsGenie, Email), high-impact event detection (health score drops, sustained failures), notification card 3-dot menu (mute, forward, create ticket), and a centralized notification routing settings page.

**Architecture:** Two-layer system — Layer 1: in-app notifications always fire (with mute/forward 3-dot menu). Layer 2: auto-routing of monitor group results to external platforms based on severity config in settings. High-impact events detected inline after group runs. All dispatch reuses existing platform clients extracted from `/api/schedule/alert`.

**Tech Stack:** Next.js 15 (API routes + React), Prisma (schema + queries), existing platform clients (SlackClient, PagerDutyClient, TeamsClient, OpsgenieClient, EmailClient, JiraClient)

**Spec:** `docs/superpowers/specs/2026-03-20-notification-routing-and-high-impact-events-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `prisma/schema.prisma` | Modify | Add NotificationRoute, NotificationMute models + backrefs |
| `lib/notification-router.ts` | Create | Severity-based dispatch to external platforms |
| `lib/high-impact-events.ts` | Create | Health score drop + sustained failure detectors |
| `lib/notifications.ts` | Modify | Add CRITICAL support to monitorGroupCompleted, add new event helpers |
| `lib/__tests__/notification-router.test.ts` | Create | Tests for routing logic |
| `lib/__tests__/high-impact-events.test.ts` | Create | Tests for event detectors |
| `lib/__tests__/notifications.test.ts` | Modify | Tests for CRITICAL severity + new helpers |
| `app/api/settings/notification-routes/route.ts` | Create | GET/PUT routing rules API |
| `app/api/notifications/[id]/forward/route.ts` | Create | Forward notification to platform |
| `app/api/notifications/mutes/route.ts` | Create | POST mute rule + GET list mutes |
| `app/api/notifications/mutes/[id]/route.ts` | Create | DELETE mute rule |
| `app/api/notifications/route.ts` | Modify | Filter muted notifications |
| `app/api/notifications/unread-count/route.ts` | Modify | Exclude muted from count |
| `app/api/schedule/watches/[watchId]/run/route.ts` | Modify | Add notifyEvents call + high-impact detection + routing |
| `app/api/schedule/plans/[planId]/run/route.ts` | Modify | Add high-impact detection + routing |
| `components/notifications/NotificationCardMenu.tsx` | Create | 3-dot menu component |
| `components/notifications/NotificationCard.tsx` | Modify | Add 3-dot menu trigger |
| `components/settings/NotificationRoutingSettings.tsx` | Create | Settings page section |
| `app/(dashboard)/dashboard/settings/page.tsx` | Modify | Replace notifications tab content with routing settings |

---

### Task 1: Prisma Schema — Add NotificationRoute and NotificationMute

**Files:**
- Modify: `prisma/schema.prisma`

- [ ] **Step 1: Add NotificationRoute model**

Add after the `NotificationRead` model (around line 1513):

```prisma
model NotificationRoute {
  id               String               @id @default(cuid())
  organizationId   String
  organization     Organization         @relation(fields: [organizationId], references: [id], onDelete: Cascade)
  severity         NotificationSeverity
  enabled          Boolean              @default(true)
  notifyOnRecovery Boolean              @default(false)
  destinations     Json                 @default("[]")
  createdAt        DateTime             @default(now())
  updatedAt        DateTime             @updatedAt

  @@unique([organizationId, severity])
  @@index([organizationId])
}
```

- [ ] **Step 2: Add NotificationMute model**

Add directly after NotificationRoute:

```prisma
model NotificationMute {
  id             String       @id @default(cuid())
  organizationId String
  organization   Organization @relation(fields: [organizationId], references: [id], onDelete: Cascade)
  userId         String
  user           User         @relation(fields: [userId], references: [id], onDelete: Cascade)
  eventType      String
  entityType     String?
  entityId       String?
  createdAt      DateTime     @default(now())

  @@index([organizationId, userId])
  @@index([eventType, entityType, entityId])
}
```

- [ ] **Step 3: Add backrefs to Organization model**

Find the Organization model and add these relation fields:

```prisma
notificationRoutes NotificationRoute[]
notificationMutes  NotificationMute[]
```

- [ ] **Step 4: Add backref to User model**

Find the User model and add:

```prisma
notificationMutes NotificationMute[]
```

- [ ] **Step 5: Generate Prisma client**

Run: `npx prisma generate`
Expected: "Generated Prisma Client" success message

- [ ] **Step 6: Create migration**

Run: `npx prisma migrate dev --name add-notification-routes-and-mutes`
Expected: Migration created and applied successfully

- [ ] **Step 7: Commit**

```bash
git add prisma/
git commit -m "feat: add NotificationRoute and NotificationMute schema models"
```

---

### Task 2: Update monitorGroupCompleted to Support CRITICAL Severity

**Files:**
- Modify: `lib/notifications.ts:118-150`
- Modify: `lib/__tests__/notifications.test.ts`

- [ ] **Step 1: Write failing test for CRITICAL severity**

In `lib/__tests__/notifications.test.ts`, add a test in the monitorGroupCompleted describe block:

```typescript
it('should derive CRITICAL severity when health score is unhealthy (< 40)', () => {
  notifyEvents.monitorGroupCompleted(
    'org1', 'pipe1', 'user1',
    'Revenue Watch', 'group1',
    { total: 10, pass: 2, fail: 6, warn: 1, error: 1 },
    { currentHealthScore: 25, previousHealthScore: 70 },
  );
  expect(mockPrisma.notificationEvent.create).toHaveBeenCalledWith(
    expect.objectContaining({
      data: expect.objectContaining({ severity: 'CRITICAL' }),
    }),
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx jest lib/__tests__/notifications.test.ts --no-coverage -t "CRITICAL"`
Expected: FAIL — monitorGroupCompleted doesn't accept health params yet

- [ ] **Step 3: Update monitorGroupCompleted signature and severity logic**

In `lib/notifications.ts`, update the `monitorGroupCompleted` function (lines 118-150):

```typescript
monitorGroupCompleted: (
  orgId: string,
  pipelineId: string | undefined,
  actorId: string | undefined,
  groupName: string,
  groupId: string,
  summary: { total: number; pass: number; fail: number; warn: number; error: number },
  health?: { currentHealthScore: number; previousHealthScore: number },
) => {
  // Derive severity — CRITICAL when health is unhealthy (<40)
  const severity: 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL' =
    health && health.currentHealthScore < 40
      ? 'CRITICAL'
      : summary.fail > 0 || summary.error > 0
        ? 'ERROR'
        : summary.warn > 0
          ? 'WARN'
          : 'INFO';

  const parts: string[] = [];
  if (summary.pass > 0) parts.push(`${summary.pass} passed`);
  if (summary.warn > 0) parts.push(`${summary.warn} warn`);
  if (summary.fail > 0) parts.push(`${summary.fail} fail`);
  if (summary.error > 0) parts.push(`${summary.error} error`);

  return notify({
    organizationId: orgId,
    pipelineStackId: pipelineId,
    actorUserId: actorId,
    eventType: 'monitor.group_completed',
    severity,
    title: `Multi-monitor ${groupName} ran: ${parts.join(', ')}`,
    message: `${groupName}: ${parts.join(', ')} (${summary.total} monitors)`,
    dedupeKey: `monitor-group:${groupId}`,
    entityType: 'MONITOR',
    entityId: groupId,
    actionUrl: `/dashboard/schedule?group=${groupId}`,
    metadata: { ...summary, ...(health || {}) },
  });
},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx jest lib/__tests__/notifications.test.ts --no-coverage -t "CRITICAL"`
Expected: PASS

- [ ] **Step 5: Add new event helpers for high-impact events**

In `lib/notifications.ts`, add to the `notifyEvents` object after `monitorGroupCompleted`:

```typescript
healthScoreDropped: (
  orgId: string,
  pipelineId: string | undefined,
  actorId: string | undefined,
  groupName: string,
  groupId: string,
  previousScore: number,
  currentScore: number,
  severity: 'WARN' | 'ERROR' | 'CRITICAL',
) => {
  const previousStatus = previousScore >= 90 ? 'healthy' : previousScore >= 70 ? 'degraded' : previousScore >= 40 ? 'at_risk' : 'unhealthy';
  const currentStatus = currentScore >= 90 ? 'healthy' : currentScore >= 70 ? 'degraded' : currentScore >= 40 ? 'at_risk' : 'unhealthy';
  return notify({
    organizationId: orgId,
    pipelineStackId: pipelineId,
    actorUserId: actorId,
    eventType: 'monitor.health_score_dropped',
    severity,
    title: `${groupName} health dropped: ${previousStatus} → ${currentStatus}`,
    message: `Health score fell from ${previousScore.toFixed(0)} to ${currentScore.toFixed(0)}`,
    dedupeKey: `health-drop:${groupId}`,
    entityType: 'MONITOR',
    entityId: groupId,
    actionUrl: `/dashboard/schedule?group=${groupId}`,
    metadata: { previousScore, currentScore, previousStatus, currentStatus },
  });
},

sustainedFailure: (
  orgId: string,
  pipelineId: string | undefined,
  actorId: string | undefined,
  groupName: string,
  groupId: string,
  monitorName: string,
  monitorId: string,
  consecutiveFailures: number,
  severity: 'WARN' | 'ERROR' | 'CRITICAL',
) => {
  return notify({
    organizationId: orgId,
    pipelineStackId: pipelineId,
    actorUserId: actorId,
    eventType: 'monitor.sustained_failure',
    severity,
    title: `${monitorName} has failed ${consecutiveFailures} times in a row`,
    message: `Monitor "${monitorName}" in ${groupName} has failed ${consecutiveFailures} consecutive runs`,
    dedupeKey: `sustained-fail:${monitorId}`,
    entityType: 'MONITOR',
    entityId: groupId,
    actionUrl: `/dashboard/schedule?group=${groupId}`,
    metadata: { monitorId, monitorName, consecutiveFailures },
  });
},
```

- [ ] **Step 6: Add tests for new event helpers**

In `lib/__tests__/notifications.test.ts`, add tests for `healthScoreDropped` and `sustainedFailure`:

```typescript
describe('healthScoreDropped', () => {
  it('should create notification with correct event type and metadata', () => {
    notifyEvents.healthScoreDropped(
      'org1', 'pipe1', 'user1',
      'Revenue Watch', 'group1',
      92, 45, 'ERROR',
    );
    expect(mockPrisma.notificationEvent.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          eventType: 'monitor.health_score_dropped',
          severity: 'ERROR',
          dedupeKey: 'health-drop:group1',
        }),
      }),
    );
  });
});

describe('sustainedFailure', () => {
  it('should create notification with monitor name and consecutive count', () => {
    notifyEvents.sustainedFailure(
      'org1', 'pipe1', 'user1',
      'Revenue Watch', 'group1',
      'Freshness Check', 'monitor1', 3, 'CRITICAL',
    );
    expect(mockPrisma.notificationEvent.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          eventType: 'monitor.sustained_failure',
          severity: 'CRITICAL',
          dedupeKey: 'sustained-fail:monitor1',
        }),
      }),
    );
  });
});
```

- [ ] **Step 7: Run all notification tests**

Run: `npx jest lib/__tests__/notifications.test.ts --no-coverage`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add lib/notifications.ts lib/__tests__/notifications.test.ts
git commit -m "feat: add CRITICAL severity and high-impact event helpers to notifications"
```

---

### Task 3: High-Impact Event Detectors

**Files:**
- Create: `lib/high-impact-events.ts`
- Create: `lib/__tests__/high-impact-events.test.ts`

- [ ] **Step 1: Write failing tests for health score drop detector**

Create `lib/__tests__/high-impact-events.test.ts`:

```typescript
import { detectHighImpactEvents, type HighImpactEvent } from '../high-impact-events';

// Mock prisma
jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    monitorRun: { findMany: jest.fn() },
  },
}));

import prisma from '@/lib/db';
const mockPrisma = prisma as jest.Mocked<typeof prisma>;

describe('detectHighImpactEvents', () => {
  beforeEach(() => jest.clearAllMocks());

  describe('detectHealthScoreDrop', () => {
    it('should detect health score drop from healthy to degraded', async () => {
      (mockPrisma.monitorRun.findMany as jest.Mock).mockResolvedValue([]);
      const events = await detectHighImpactEvents({
        watchId: 'w1',
        organizationId: 'org1',
        pipelineStackId: 'pipe1',
        currentHealthScore: 65,
        previousHealthScore: 92,
        results: [],
      });
      const drop = events.find((e) => e.eventType === 'monitor.health_score_dropped');
      expect(drop).toBeDefined();
      expect(drop!.severity).toBe('ERROR');
    });

    it('should NOT detect drop when score improves', async () => {
      (mockPrisma.monitorRun.findMany as jest.Mock).mockResolvedValue([]);
      const events = await detectHighImpactEvents({
        watchId: 'w1',
        organizationId: 'org1',
        pipelineStackId: 'pipe1',
        currentHealthScore: 95,
        previousHealthScore: 70,
        results: [],
      });
      const drop = events.find((e) => e.eventType === 'monitor.health_score_dropped');
      expect(drop).toBeUndefined();
    });

    it('should produce CRITICAL when score drops below 40', async () => {
      (mockPrisma.monitorRun.findMany as jest.Mock).mockResolvedValue([]);
      const events = await detectHighImpactEvents({
        watchId: 'w1',
        organizationId: 'org1',
        pipelineStackId: 'pipe1',
        currentHealthScore: 30,
        previousHealthScore: 75,
        results: [],
      });
      const drop = events.find((e) => e.eventType === 'monitor.health_score_dropped');
      expect(drop).toBeDefined();
      expect(drop!.severity).toBe('CRITICAL');
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx jest lib/__tests__/high-impact-events.test.ts --no-coverage`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement health score drop detector**

Create `lib/high-impact-events.ts`:

```typescript
import prisma from '@/lib/db';

export interface HighImpactEvent {
  eventType: 'monitor.health_score_dropped' | 'monitor.sustained_failure';
  severity: 'WARN' | 'ERROR' | 'CRITICAL';
  title: string;
  message: string;
  metadata: Record<string, unknown>;
  /** For sustained failures, the specific monitor */
  monitorId?: string;
  monitorName?: string;
  consecutiveFailures?: number;
  /** For health score drops */
  previousScore?: number;
  currentScore?: number;
}

interface DetectParams {
  watchId: string;
  organizationId: string;
  pipelineStackId: string | undefined;
  currentHealthScore: number;
  previousHealthScore: number;
  results: Array<{ monitorId: string; monitorName: string; status: string }>;
}

function healthStatus(score: number): string {
  if (score >= 90) return 'healthy';
  if (score >= 70) return 'degraded';
  if (score >= 40) return 'at_risk';
  return 'unhealthy';
}

function detectHealthScoreDrop(params: DetectParams): HighImpactEvent | null {
  const { currentHealthScore, previousHealthScore } = params;

  // Only detect downward transitions
  if (currentHealthScore >= previousHealthScore) return null;

  const prevStatus = healthStatus(previousHealthScore);
  const currStatus = healthStatus(currentHealthScore);

  // Only fire if the status bucket actually changed
  if (prevStatus === currStatus) return null;

  const severity: 'WARN' | 'ERROR' | 'CRITICAL' =
    currentHealthScore < 40 ? 'CRITICAL' : currentHealthScore < 70 ? 'ERROR' : 'WARN';

  return {
    eventType: 'monitor.health_score_dropped',
    severity,
    title: `Health dropped: ${prevStatus} → ${currStatus}`,
    message: `Health score fell from ${previousHealthScore.toFixed(0)} to ${currentHealthScore.toFixed(0)}`,
    metadata: { previousScore: previousHealthScore, currentScore: currentHealthScore, prevStatus, currStatus },
    previousScore: previousHealthScore,
    currentScore: currentHealthScore,
  };
}

async function detectSustainedFailures(params: DetectParams): Promise<HighImpactEvent[]> {
  const events: HighImpactEvent[] = [];
  const CONSECUTIVE_THRESHOLD = 3;

  // Only check monitors that failed in this run
  const failedMonitors = params.results.filter(
    (r) => r.status === 'FAIL' || r.status === 'ERROR',
  );
  if (failedMonitors.length === 0) return events;

  const monitorIds = failedMonitors.map((m) => m.monitorId);

  // Fetch last N runs per monitor, ordered newest first, excluding SKIPPED/RUNNING
  const recentRuns = await prisma.monitorRun.findMany({
    where: {
      monitorId: { in: monitorIds },
      status: { notIn: ['SKIPPED', 'RUNNING'] },
    },
    orderBy: { startedAt: 'desc' },
    take: CONSECUTIVE_THRESHOLD * monitorIds.length,
    select: { monitorId: true, status: true },
  });

  // Group by monitor
  const runsByMonitor = new Map<string, string[]>();
  for (const run of recentRuns) {
    const runs = runsByMonitor.get(run.monitorId) || [];
    runs.push(run.status);
    runsByMonitor.set(run.monitorId, runs);
  }

  for (const monitor of failedMonitors) {
    const runs = runsByMonitor.get(monitor.monitorId) || [];
    // Check if last N runs are all failures
    const lastN = runs.slice(0, CONSECUTIVE_THRESHOLD);
    if (lastN.length >= CONSECUTIVE_THRESHOLD && lastN.every((s) => s === 'FAIL' || s === 'ERROR')) {
      events.push({
        eventType: 'monitor.sustained_failure',
        severity: 'CRITICAL',
        title: `${monitor.monitorName} has failed ${CONSECUTIVE_THRESHOLD}+ times`,
        message: `Monitor "${monitor.monitorName}" has failed ${CONSECUTIVE_THRESHOLD} consecutive runs`,
        metadata: { monitorId: monitor.monitorId, monitorName: monitor.monitorName, consecutiveFailures: CONSECUTIVE_THRESHOLD },
        monitorId: monitor.monitorId,
        monitorName: monitor.monitorName,
        consecutiveFailures: CONSECUTIVE_THRESHOLD,
      });
    }
  }

  return events;
}

export async function detectHighImpactEvents(params: DetectParams): Promise<HighImpactEvent[]> {
  const events: HighImpactEvent[] = [];

  const healthDrop = detectHealthScoreDrop(params);
  if (healthDrop) events.push(healthDrop);

  const sustained = await detectSustainedFailures(params);
  events.push(...sustained);

  return events;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx jest lib/__tests__/high-impact-events.test.ts --no-coverage`
Expected: PASS

- [ ] **Step 5: Add sustained failure tests**

Add to `lib/__tests__/high-impact-events.test.ts`:

```typescript
describe('detectSustainedFailures', () => {
  it('should detect sustained failure (3 consecutive FAILs)', async () => {
    (mockPrisma.monitorRun.findMany as jest.Mock).mockResolvedValue([
      { monitorId: 'm1', status: 'FAIL' },
      { monitorId: 'm1', status: 'FAIL' },
      { monitorId: 'm1', status: 'FAIL' },
    ]);
    const events = await detectHighImpactEvents({
      watchId: 'w1',
      organizationId: 'org1',
      pipelineStackId: 'pipe1',
      currentHealthScore: 50,
      previousHealthScore: 50,
      results: [{ monitorId: 'm1', monitorName: 'Freshness Check', status: 'FAIL' }],
    });
    const sustained = events.find((e) => e.eventType === 'monitor.sustained_failure');
    expect(sustained).toBeDefined();
    expect(sustained!.severity).toBe('CRITICAL');
    expect(sustained!.consecutiveFailures).toBe(3);
  });

  it('should NOT detect sustained failure when recent run passed', async () => {
    (mockPrisma.monitorRun.findMany as jest.Mock).mockResolvedValue([
      { monitorId: 'm1', status: 'FAIL' },
      { monitorId: 'm1', status: 'PASS' },
      { monitorId: 'm1', status: 'FAIL' },
    ]);
    const events = await detectHighImpactEvents({
      watchId: 'w1',
      organizationId: 'org1',
      pipelineStackId: 'pipe1',
      currentHealthScore: 50,
      previousHealthScore: 50,
      results: [{ monitorId: 'm1', monitorName: 'Freshness Check', status: 'FAIL' }],
    });
    const sustained = events.find((e) => e.eventType === 'monitor.sustained_failure');
    expect(sustained).toBeUndefined();
  });

  it('should skip monitors that passed in current run', async () => {
    (mockPrisma.monitorRun.findMany as jest.Mock).mockResolvedValue([]);
    const events = await detectHighImpactEvents({
      watchId: 'w1',
      organizationId: 'org1',
      pipelineStackId: 'pipe1',
      currentHealthScore: 90,
      previousHealthScore: 90,
      results: [{ monitorId: 'm1', monitorName: 'Freshness Check', status: 'PASS' }],
    });
    const sustained = events.find((e) => e.eventType === 'monitor.sustained_failure');
    expect(sustained).toBeUndefined();
  });
});
```

- [ ] **Step 6: Run all tests**

Run: `npx jest lib/__tests__/high-impact-events.test.ts --no-coverage`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add lib/high-impact-events.ts lib/__tests__/high-impact-events.test.ts
git commit -m "feat: add high-impact event detectors (health score drop, sustained failure)"
```

---

### Task 4: Notification Router — Extract Dispatch Logic

**Files:**
- Create: `lib/notification-router.ts`
- Create: `lib/__tests__/notification-router.test.ts`

- [ ] **Step 1: Write failing test for routeNotification**

Create `lib/__tests__/notification-router.test.ts`:

```typescript
import { routeNotification } from '../notification-router';

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    notificationRoute: { findUnique: jest.fn() },
    integration: { findMany: jest.fn() },
  },
}));
jest.mock('@/lib/crypto', () => ({ decrypt: jest.fn((v) => v) }));
jest.mock('@/lib/integrations/slack', () => ({
  SlackClient: jest.fn().mockImplementation(() => ({
    sendMessage: jest.fn().mockResolvedValue(undefined),
  })),
}));
jest.mock('@/lib/integrations/pagerduty', () => ({
  PagerDutyClient: jest.fn().mockImplementation(() => ({
    createIncident: jest.fn().mockResolvedValue({ dedup_key: 'dk' }),
  })),
}));
jest.mock('@/lib/integrations/teams', () => ({
  TeamsClient: jest.fn().mockImplementation(() => ({
    sendMessage: jest.fn().mockResolvedValue(undefined),
  })),
}));
jest.mock('@/lib/integrations/opsgenie', () => ({
  OpsgenieClient: jest.fn().mockImplementation(() => ({
    createAlert: jest.fn().mockResolvedValue({ requestId: 'r1' }),
  })),
}));
jest.mock('@/lib/integrations/email', () => ({
  EmailClient: jest.fn().mockImplementation(() => ({
    sendEmail: jest.fn().mockResolvedValue(undefined),
  })),
}));

import prisma from '@/lib/db';
const mockPrisma = prisma as jest.Mocked<typeof prisma>;

describe('routeNotification', () => {
  beforeEach(() => jest.clearAllMocks());

  it('should dispatch to Slack when route has Slack destination', async () => {
    (mockPrisma.notificationRoute.findUnique as jest.Mock).mockResolvedValue({
      enabled: true,
      notifyOnRecovery: false,
      destinations: [{ integrationId: 'int1', channel: '#alerts' }],
    });
    (mockPrisma.integration.findMany as jest.Mock).mockResolvedValue([
      { id: 'int1', type: 'SLACK', status: 'ACTIVE', accessToken: 'xoxb-test', credentials: '{}', config: {} },
    ]);

    await routeNotification({
      organizationId: 'org1',
      severity: 'ERROR',
      title: 'Test Alert',
      message: 'Something failed',
    });

    const { SlackClient } = require('@/lib/integrations/slack');
    expect(SlackClient).toHaveBeenCalled();
  });

  it('should do nothing when route is disabled', async () => {
    (mockPrisma.notificationRoute.findUnique as jest.Mock).mockResolvedValue({
      enabled: false,
      destinations: [{ integrationId: 'int1' }],
    });

    await routeNotification({
      organizationId: 'org1',
      severity: 'ERROR',
      title: 'Test',
      message: 'Test',
    });

    expect(mockPrisma.integration.findMany).not.toHaveBeenCalled();
  });

  it('should do nothing when no route exists', async () => {
    (mockPrisma.notificationRoute.findUnique as jest.Mock).mockResolvedValue(null);

    await routeNotification({
      organizationId: 'org1',
      severity: 'INFO',
      title: 'Test',
      message: 'Test',
    });

    expect(mockPrisma.integration.findMany).not.toHaveBeenCalled();
  });

  it('should skip recovery notifications when notifyOnRecovery is false', async () => {
    (mockPrisma.notificationRoute.findUnique as jest.Mock).mockResolvedValue({
      enabled: true,
      notifyOnRecovery: false,
      destinations: [{ integrationId: 'int1' }],
    });

    await routeNotification({
      organizationId: 'org1',
      severity: 'INFO',
      title: 'Recovered',
      message: 'All clear',
      isRecovery: true,
    });

    expect(mockPrisma.integration.findMany).not.toHaveBeenCalled();
  });

  it('should dispatch to PagerDuty when route has PagerDuty destination', async () => {
    (mockPrisma.notificationRoute.findUnique as jest.Mock).mockResolvedValue({
      enabled: true,
      notifyOnRecovery: false,
      destinations: [{ integrationId: 'int2', config: { routing_key: 'rk-test' } }],
    });
    (mockPrisma.integration.findMany as jest.Mock).mockResolvedValue([
      { id: 'int2', type: 'PAGERDUTY', status: 'ACTIVE', credentials: '{}', config: { api_key: 'ak', service_id: 'sid', routing_key: 'rk-test' } },
    ]);

    await routeNotification({
      organizationId: 'org1',
      severity: 'CRITICAL',
      title: 'Critical Alert',
      message: 'Something critical',
    });

    const { PagerDutyClient } = require('@/lib/integrations/pagerduty');
    expect(PagerDutyClient).toHaveBeenCalled();
  });

  it('should dispatch recovery when notifyOnRecovery is true', async () => {
    (mockPrisma.notificationRoute.findUnique as jest.Mock).mockResolvedValue({
      enabled: true,
      notifyOnRecovery: true,
      destinations: [{ integrationId: 'int1', channel: '#alerts' }],
    });
    (mockPrisma.integration.findMany as jest.Mock).mockResolvedValue([
      { id: 'int1', type: 'SLACK', status: 'ACTIVE', accessToken: 'xoxb-test', credentials: '{}', config: {} },
    ]);

    await routeNotification({
      organizationId: 'org1',
      severity: 'INFO',
      title: 'Recovered',
      message: 'All clear',
      isRecovery: true,
    });

    const { SlackClient } = require('@/lib/integrations/slack');
    expect(SlackClient).toHaveBeenCalled();
  });

  it('should gracefully handle missing integration', async () => {
    (mockPrisma.notificationRoute.findUnique as jest.Mock).mockResolvedValue({
      enabled: true,
      notifyOnRecovery: false,
      destinations: [{ integrationId: 'deleted-int' }],
    });
    (mockPrisma.integration.findMany as jest.Mock).mockResolvedValue([]);

    // Should not throw
    await routeNotification({
      organizationId: 'org1',
      severity: 'CRITICAL',
      title: 'Test',
      message: 'Test',
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx jest lib/__tests__/notification-router.test.ts --no-coverage`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement notification-router.ts**

Create `lib/notification-router.ts`. This extracts the dispatch pattern from `app/api/schedule/alert/route.ts` (lines 43-150):

```typescript
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { SlackClient } from '@/lib/integrations/slack';
import { PagerDutyClient } from '@/lib/integrations/pagerduty';
import { TeamsClient } from '@/lib/integrations/teams';
import { OpsgenieClient } from '@/lib/integrations/opsgenie';
import { EmailClient } from '@/lib/integrations/email';

type Severity = 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';

interface RouteParams {
  organizationId: string;
  severity: Severity;
  title: string;
  message: string;
  metadata?: Record<string, unknown>;
  actionUrl?: string;
  isRecovery?: boolean;
}

interface Destination {
  integrationId: string;
  channel?: string;
  config?: Record<string, unknown>;
}

function toSlackSeverity(s: Severity): 'critical' | 'high' | 'medium' | 'low' {
  if (s === 'CRITICAL') return 'critical';
  if (s === 'ERROR') return 'high';
  if (s === 'WARN') return 'medium';
  return 'low';
}

function toPdSeverity(s: Severity): 'critical' | 'error' | 'warning' | 'info' {
  if (s === 'CRITICAL') return 'critical';
  if (s === 'ERROR') return 'error';
  if (s === 'WARN') return 'warning';
  return 'info';
}

function toOgPriority(s: Severity): 'P1' | 'P2' | 'P3' | 'P4' {
  if (s === 'CRITICAL') return 'P1';
  if (s === 'ERROR') return 'P2';
  if (s === 'WARN') return 'P3';
  return 'P4';
}

export async function routeNotification(params: RouteParams): Promise<void> {
  try {
    const route = await prisma.notificationRoute.findUnique({
      where: {
        organizationId_severity: {
          organizationId: params.organizationId,
          severity: params.severity,
        },
      },
    });

    if (!route || !route.enabled) return;
    if (params.isRecovery && !route.notifyOnRecovery) return;

    const destinations = (route.destinations || []) as Destination[];
    if (destinations.length === 0) return;

    const integrationIds = destinations.map((d) => d.integrationId);
    const integrations = await prisma.integration.findMany({
      where: { id: { in: integrationIds }, status: 'ACTIVE' },
    });

    const integrationMap = new Map(integrations.map((i) => [i.id, i]));

    for (const dest of destinations) {
      const integration = integrationMap.get(dest.integrationId);
      if (!integration) {
        console.warn(`[NotificationRouter] Integration ${dest.integrationId} not found or inactive, skipping`);
        continue;
      }

      try {
        const type = integration.type.toLowerCase();
        const creds = integration.credentials
          ? (typeof integration.credentials === 'string'
              ? JSON.parse(integration.credentials)
              : integration.credentials) as Record<string, any>
          : {};
        const config = (integration.config || {}) as Record<string, any>;

        if (type === 'slack') {
          let botToken = '';
          if (integration.accessToken) {
            try { botToken = decrypt(integration.accessToken); } catch {}
          }
          if (!botToken) continue;
          const channel = dest.channel || creds.channel;
          const client = new SlackClient({ bot_token: botToken, channel });
          await client.sendMessage({
            title: params.title,
            text: params.message,
            severity: toSlackSeverity(params.severity),
            fields: params.actionUrl
              ? [{ label: 'Link', value: params.actionUrl }]
              : undefined,
          });
        } else if (type === 'pagerduty') {
          const routingKey = (dest.config as any)?.routing_key || config.routing_key;
          if (!routingKey) continue;
          const client = new PagerDutyClient({
            api_key: config.api_key || '',
            service_id: config.service_id || '',
            routing_key: routingKey,
          });
          await client.createIncident({
            title: params.title,
            description: params.message,
            severity: toPdSeverity(params.severity),
          });
        } else if (type === 'teams') {
          const webhookUrl = (dest.config as any)?.webhook_url || config.webhook_url;
          if (!webhookUrl) continue;
          const client = new TeamsClient({ webhook_url: webhookUrl });
          await client.sendMessage({
            title: params.title,
            text: params.message,
            severity: toSlackSeverity(params.severity),
          });
        } else if (type === 'opsgenie') {
          const apiKey = (dest.config as any)?.api_key || config.api_key;
          if (!apiKey) continue;
          const client = new OpsgenieClient({ api_key: apiKey });
          await client.createAlert({
            message: params.title,
            description: params.message,
            priority: toOgPriority(params.severity),
            tags: ['pallisade', 'notification-router'],
          });
        } else if (type === 'email') {
          const recipients = (dest.config as any)?.recipients || config.recipients;
          if (!recipients) continue;
          const client = new EmailClient({
            recipients,
            smtp_host: config.smtp_host,
            smtp_port: config.smtp_port,
          });
          await client.sendEmail({
            subject: params.title,
            text: params.message,
            html: `<p><strong>${params.title}</strong></p><p>${params.message}</p>`,
            severity: toSlackSeverity(params.severity),
          });
        }
      } catch (err: any) {
        console.error(`[NotificationRouter] Failed to dispatch to ${integration.type}:`, err.message);
      }
    }
  } catch (err: any) {
    console.error('[NotificationRouter] Route lookup error:', err.message);
  }
}
```

- [ ] **Step 4: Run tests**

Run: `npx jest lib/__tests__/notification-router.test.ts --no-coverage`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add lib/notification-router.ts lib/__tests__/notification-router.test.ts
git commit -m "feat: add notification-router with severity-based dispatch to external platforms"
```

---

### Task 5: Notification Routes API (Settings)

**Files:**
- Create: `app/api/settings/notification-routes/route.ts`

- [ ] **Step 1: Create the GET/PUT route**

Create `app/api/settings/notification-routes/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// GET /api/settings/notification-routes — fetch all severity routing rules for org
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const routes = await prisma.notificationRoute.findMany({
      where: { organizationId: user.organizationId },
      orderBy: { severity: 'asc' },
    });

    return NextResponse.json({ routes });
  } catch (error: any) {
    console.error('[NotificationRoutes] GET error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// PUT /api/settings/notification-routes — upsert all severity routing rules
export async function PUT(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { routes } = await request.json();
    if (!Array.isArray(routes)) {
      return NextResponse.json({ error: 'routes must be an array' }, { status: 400 });
    }

    const orgId = user.organizationId;
    const validSeverities = ['INFO', 'WARN', 'ERROR', 'CRITICAL'];

    const upserted = await prisma.$transaction(
      routes
        .filter((r: any) => validSeverities.includes(r.severity))
        .map((r: any) =>
          prisma.notificationRoute.upsert({
            where: {
              organizationId_severity: {
                organizationId: orgId,
                severity: r.severity,
              },
            },
            create: {
              organizationId: orgId,
              severity: r.severity,
              enabled: r.enabled ?? true,
              notifyOnRecovery: r.notifyOnRecovery ?? false,
              destinations: r.destinations ?? [],
            },
            update: {
              enabled: r.enabled ?? true,
              notifyOnRecovery: r.notifyOnRecovery ?? false,
              destinations: r.destinations ?? [],
            },
          }),
        ),
    );

    return NextResponse.json({ routes: upserted });
  } catch (error: any) {
    console.error('[NotificationRoutes] PUT error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/settings/notification-routes/route.ts
git commit -m "feat: add notification routes settings API (GET/PUT)"
```

---

### Task 6: Mute API Routes

**Files:**
- Create: `app/api/notifications/mutes/route.ts`
- Create: `app/api/notifications/mutes/[id]/route.ts`

- [ ] **Step 1: Create mute POST + GET route**

Create `app/api/notifications/mutes/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// POST /api/notifications/mutes — create a mute rule
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { eventType, entityType, entityId } = await request.json();
    if (!eventType) {
      return NextResponse.json({ error: 'eventType is required' }, { status: 400 });
    }

    const mute = await prisma.notificationMute.create({
      data: {
        organizationId: user.organizationId,
        userId: user.id,
        eventType,
        entityType: entityType || null,
        entityId: entityId || null,
      },
    });

    return NextResponse.json({ mute });
  } catch (error: any) {
    console.error('[NotificationMute] POST error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}

// GET /api/notifications/mutes — list active mutes for current user
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const mutes = await prisma.notificationMute.findMany({
      where: {
        organizationId: user.organizationId,
        userId: user.id,
      },
      orderBy: { createdAt: 'desc' },
    });

    return NextResponse.json({ mutes });
  } catch (error: any) {
    console.error('[NotificationMute] GET error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
```

- [ ] **Step 2: Create mute DELETE route**

Create `app/api/notifications/mutes/[id]/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';

// DELETE /api/notifications/mutes/[id] — remove a mute rule
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true },
    });
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { id } = await params;

    // Ensure the mute belongs to the requesting user
    const mute = await prisma.notificationMute.findFirst({
      where: { id, userId: user.id },
    });
    if (!mute) {
      return NextResponse.json({ error: 'Mute rule not found' }, { status: 404 });
    }

    await prisma.notificationMute.delete({ where: { id } });

    return NextResponse.json({ success: true });
  } catch (error: any) {
    console.error('[NotificationMute] DELETE error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add app/api/notifications/mutes/
git commit -m "feat: add notification mute API (create, list, delete)"
```

---

### Task 7: Forward Notification API

**Files:**
- Create: `app/api/notifications/[id]/forward/route.ts`

- [ ] **Step 1: Create forward route**

Create `app/api/notifications/[id]/forward/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import prisma from '@/lib/db';
import { decrypt } from '@/lib/crypto';
import { SlackClient } from '@/lib/integrations/slack';
import { PagerDutyClient } from '@/lib/integrations/pagerduty';
import { TeamsClient } from '@/lib/integrations/teams';
import { OpsgenieClient } from '@/lib/integrations/opsgenie';
import { EmailClient } from '@/lib/integrations/email';
import { JiraClient } from '@/lib/integrations/jira';

// POST /api/notifications/[id]/forward — forward a notification to an external platform
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    const user = await prisma.user.findUnique({
      where: { email: session.user.email! },
      select: { id: true, organizationId: true },
    });
    if (!user?.organizationId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { id } = await params;
    const { integrationId, channel, config } = await request.json();

    if (!integrationId) {
      return NextResponse.json({ error: 'integrationId is required' }, { status: 400 });
    }

    // Fetch the notification
    const notification = await prisma.notificationEvent.findFirst({
      where: { id, organizationId: user.organizationId },
    });
    if (!notification) {
      return NextResponse.json({ error: 'Notification not found' }, { status: 404 });
    }

    // Fetch the integration
    const integration = await prisma.integration.findFirst({
      where: { id: integrationId, organizationId: user.organizationId, status: 'ACTIVE' },
    });
    if (!integration) {
      return NextResponse.json({ error: 'Integration not found or inactive' }, { status: 404 });
    }

    const type = integration.type.toLowerCase();
    const creds = integration.credentials
      ? (typeof integration.credentials === 'string'
          ? JSON.parse(integration.credentials)
          : integration.credentials) as Record<string, any>
      : {};
    const intConfig = (integration.config || {}) as Record<string, any>;

    const severityMap: Record<string, 'critical' | 'high' | 'medium' | 'low'> = {
      CRITICAL: 'critical', ERROR: 'high', WARN: 'medium', INFO: 'low',
    };
    const severity = severityMap[notification.severity] || 'medium';

    if (type === 'slack') {
      let botToken = '';
      if (integration.accessToken) {
        try { botToken = decrypt(integration.accessToken); } catch {}
      }
      if (!botToken) return NextResponse.json({ error: 'No Slack bot token' }, { status: 400 });
      const client = new SlackClient({ bot_token: botToken, channel: channel || creds.channel });
      await client.sendMessage({
        title: notification.title,
        text: notification.message || '',
        severity,
        fields: notification.actionUrl ? [{ label: 'Link', value: notification.actionUrl }] : undefined,
      });
    } else if (type === 'pagerduty') {
      const routingKey = config?.routing_key || intConfig.routing_key;
      if (!routingKey) return NextResponse.json({ error: 'No PagerDuty routing key' }, { status: 400 });
      const pdSev: Record<string, 'critical' | 'error' | 'warning' | 'info'> = {
        CRITICAL: 'critical', ERROR: 'error', WARN: 'warning', INFO: 'info',
      };
      const client = new PagerDutyClient({
        api_key: intConfig.api_key || '', service_id: intConfig.service_id || '', routing_key: routingKey,
      });
      await client.createIncident({
        title: notification.title,
        description: notification.message || '',
        severity: pdSev[notification.severity] || 'info',
      });
    } else if (type === 'teams') {
      const webhookUrl = config?.webhook_url || intConfig.webhook_url;
      if (!webhookUrl) return NextResponse.json({ error: 'No Teams webhook URL' }, { status: 400 });
      const client = new TeamsClient({ webhook_url: webhookUrl });
      await client.sendMessage({ title: notification.title, text: notification.message || '', severity });
    } else if (type === 'opsgenie') {
      const apiKey = config?.api_key || intConfig.api_key;
      if (!apiKey) return NextResponse.json({ error: 'No OpsGenie API key' }, { status: 400 });
      const ogPriority: Record<string, 'P1' | 'P2' | 'P3' | 'P4'> = {
        CRITICAL: 'P1', ERROR: 'P2', WARN: 'P3', INFO: 'P4',
      };
      const client = new OpsgenieClient({ api_key: apiKey });
      await client.createAlert({
        message: notification.title,
        description: notification.message || '',
        priority: ogPriority[notification.severity] || 'P3',
        tags: ['pallisade', 'forwarded'],
      });
    } else if (type === 'email') {
      const recipients = config?.recipients || intConfig.recipients;
      if (!recipients) return NextResponse.json({ error: 'No email recipients' }, { status: 400 });
      const client = new EmailClient({ recipients, smtp_host: intConfig.smtp_host, smtp_port: intConfig.smtp_port });
      await client.sendEmail({
        subject: notification.title,
        text: notification.message || '',
        html: `<p><strong>${notification.title}</strong></p><p>${notification.message || ''}</p>`,
        severity,
      });
    } else if (type === 'jira') {
      const client = new JiraClient({
        base_url: intConfig.base_url || creds.base_url,
        email: intConfig.email || creds.email,
        api_token: intConfig.api_token || creds.api_token,
      });
      const priorityMap: Record<string, string> = {
        CRITICAL: 'Highest', ERROR: 'High', WARN: 'Medium', INFO: 'Low',
      };
      const issue = await client.createIssue({
        summary: notification.title,
        description: notification.message || '',
        priority: priorityMap[notification.severity] || 'Medium',
        labels: ['pallisade', 'notification'],
        project_key: config?.project_key || intConfig.project_key,
      });
      return NextResponse.json({ success: true, platform: type, issue });
    } else {
      return NextResponse.json({ error: `Unsupported platform: ${type}` }, { status: 400 });
    }

    return NextResponse.json({ success: true, platform: type });
  } catch (error: any) {
    console.error('[NotificationForward] Error:', error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/notifications/[id]/forward/route.ts
git commit -m "feat: add notification forward API for manual dispatch to platforms"
```

---

### Task 8: Filter Muted Notifications in Existing Routes

**Files:**
- Modify: `app/api/notifications/route.ts`
- Modify: `app/api/notifications/unread-count/route.ts`

- [ ] **Step 1: Add mute filtering to GET /api/notifications**

In `app/api/notifications/route.ts`, after the existing `user` lookup (around line 17), add a query for user's mutes and filter them from the results. Add this logic before the main query:

```typescript
// Fetch user's mute rules to exclude muted notifications
const mutes = await prisma.notificationMute.findMany({
  where: {
    organizationId: user.organizationId,
    userId: user.id,
  },
});

// Build mute exclusion conditions
const muteExclusions = mutes.map((m) => ({
  AND: [
    { eventType: m.eventType },
    ...(m.entityType ? [{ entityType: m.entityType }] : []),
    ...(m.entityId ? [{ entityId: m.entityId }] : []),
  ],
}));
```

Then add to the `where` clause of the main query:

```typescript
...(muteExclusions.length > 0 ? { NOT: { OR: muteExclusions } } : {}),
```

- [ ] **Step 2: Add mute filtering to GET /api/notifications/unread-count**

Apply the same mute exclusion pattern to the count query in `app/api/notifications/unread-count/route.ts`.

- [ ] **Step 3: Commit**

```bash
git add app/api/notifications/route.ts app/api/notifications/unread-count/route.ts
git commit -m "feat: filter muted notifications from list and unread count"
```

---

### Task 9: Wire Watch Run Route — Notifications + High-Impact Events + Routing

**Files:**
- Modify: `app/api/schedule/watches/[watchId]/run/route.ts`

- [ ] **Step 1: Add imports at top of file**

Add to imports section:

```typescript
import { notifyEvents } from '@/lib/notifications';
import { detectHighImpactEvents } from '@/lib/high-impact-events';
import { routeNotification } from '@/lib/notification-router';
```

- [ ] **Step 2: Add notification + detection + routing after health persist**

After the `prisma.monitorGroup.update()` call (line 263) and before the `return NextResponse.json(...)` (line 269), add:

```typescript
    // ── Notifications & routing (fire-and-forget) ──────────────
    const passCount = signals.filter((r) => r.status === 'PASS').length;
    const failCount = signals.filter((r) => r.status === 'FAIL' || r.status === 'ERROR').length;
    const warnCount = signals.filter((r) => r.status === 'WARN').length;
    const errorCount = signals.filter((r) => r.status === 'ERROR').length;
    const summary = { total: signals.length, pass: passCount, fail: failCount, warn: warnCount, error: errorCount };

    // Store previous health score (before this run's update)
    const previousHealthScore = group.healthScore ?? 100;

    // 1. In-app notification (always)
    notifyEvents.monitorGroupCompleted(
      group.organizationId,
      group.pipelineStackId ?? undefined,
      undefined, // actorUserId — system-triggered
      group.name,
      watchId,
      summary,
      { currentHealthScore: healthScore, previousHealthScore },
    ).catch(() => {});

    // 2. Detect high-impact events
    detectHighImpactEvents({
      watchId,
      organizationId: group.organizationId,
      pipelineStackId: group.pipelineStackId ?? undefined,
      currentHealthScore: healthScore,
      previousHealthScore,
      results: signals.map((s) => ({
        monitorId: s.monitorId,
        monitorName: s.monitorName,
        status: s.status,
      })),
    }).then((events) => {
      for (const event of events) {
        if (event.eventType === 'monitor.health_score_dropped') {
          notifyEvents.healthScoreDropped(
            group.organizationId, group.pipelineStackId ?? undefined, undefined,
            group.name, watchId,
            event.previousScore!, event.currentScore!, event.severity,
          ).catch(() => {});
        } else if (event.eventType === 'monitor.sustained_failure') {
          notifyEvents.sustainedFailure(
            group.organizationId, group.pipelineStackId ?? undefined, undefined,
            group.name, watchId,
            event.monitorName!, event.monitorId!, event.consecutiveFailures!, event.severity,
          ).catch(() => {});
        }
        // Route high-impact events to external platforms
        routeNotification({
          organizationId: group.organizationId,
          severity: event.severity,
          title: event.title,
          message: event.message,
          actionUrl: `/dashboard/schedule?group=${watchId}`,
        }).catch(() => {});
      }
    }).catch(() => {});

    // 3. Route the group result to external platforms
    const groupSeverity =
      healthScore < 40 ? 'CRITICAL' as const
      : failCount > 0 || errorCount > 0 ? 'ERROR' as const
      : warnCount > 0 ? 'WARN' as const
      : 'INFO' as const;

    // Check if this is a recovery (was failing, now passing)
    const isRecovery = previousHealthScore < 70 && healthScore >= 70 && failCount === 0;

    routeNotification({
      organizationId: group.organizationId,
      severity: groupSeverity,
      title: `${group.name}: ${passCount} pass, ${failCount} fail, ${warnCount} warn`,
      message: summary ? `Health score: ${healthScore.toFixed(0)} — ${healthStatus}` : '',
      metadata: { ...summary, healthScore, healthStatus },
      actionUrl: `/dashboard/schedule?group=${watchId}`,
      isRecovery,
    }).catch(() => {});
```

Note: move the `passCount`/`failCount`/`warnCount` calculation (currently lines 265-267) into this block since it's now used before the return.

- [ ] **Step 3: Fetch previous health score before update**

The `group` variable from the initial fetch (around line 155) should already have `healthScore`. Verify this is included in the `select` or full fetch. The `previousHealthScore` uses `group.healthScore ?? 100` (defaulting to 100 for first run).

- [ ] **Step 4: Commit**

```bash
git add app/api/schedule/watches/[watchId]/run/route.ts
git commit -m "feat: wire watch run to notifications, high-impact events, and external routing"
```

---

### Task 10: Wire Plan Run Route — External Routing

Note: high-impact event detection is NOT added here — the plan run route fans out to individual watch runs (which already have detection from Task 9). The plan route only needs to route its aggregate notification to external platforms.

**Files:**
- Modify: `app/api/schedule/plans/[planId]/run/route.ts`

- [ ] **Step 1: Add imports**

```typescript
import { routeNotification } from '@/lib/notification-router';
```

- [ ] **Step 2: Add routing after existing notifyEvents call**

After the existing `notifyEvents.monitorGroupCompleted()` call (around line 128-141), add routing dispatch:

```typescript
    // Route to external platforms based on severity
    const planSeverity =
      totalFailed > 0 ? 'ERROR' as const
      : totalWarn > 0 ? 'WARN' as const
      : 'INFO' as const;

    routeNotification({
      organizationId: plan.organizationId,
      severity: planSeverity,
      title: `Plan "${plan.name}": ${totalFailed} failed, ${totalPassed} passed`,
      message: `${groupsRun} groups run, ${totalTriggered} monitors total`,
      metadata: { planId, groupsRun, totalTriggered, totalFailed, totalPassed },
      actionUrl: `/dashboard/schedule?plan=${planId}`,
    }).catch(() => {});
```

- [ ] **Step 3: Commit**

```bash
git add app/api/schedule/plans/[planId]/run/route.ts
git commit -m "feat: wire plan run to notification routing"
```

---

### Task 11: NotificationCardMenu Component (3-dot menu)

**Files:**
- Create: `components/notifications/NotificationCardMenu.tsx`
- Modify: `components/notifications/NotificationCard.tsx`

- [ ] **Step 1: Create NotificationCardMenu component**

Create `components/notifications/NotificationCardMenu.tsx`:

```tsx
'use client';

import { useState, useRef, useEffect } from 'react';
import { MoreVertical, BellOff, Send, ExternalLink } from 'lucide-react';
import { cachedFetch } from '@/lib/fetch-cache';

interface Integration {
  id: string;
  type: string;
  status: string;
  metadata?: Record<string, any>;
}

interface NotificationCardMenuProps {
  notificationId: string;
  eventType: string;
  entityType?: string;
  entityId?: string;
  onMuted?: () => void;
  onForwarded?: () => void;
}

const PLATFORM_LABELS: Record<string, string> = {
  SLACK: 'Send to Slack',
  TEAMS: 'Send to Teams',
  PAGERDUTY: 'Send to PagerDuty',
  OPSGENIE: 'Send to OpsGenie',
  EMAIL: 'Send via Email',
  JIRA: 'Create Jira ticket',
};

const NOTIFICATION_PLATFORMS = ['SLACK', 'TEAMS', 'PAGERDUTY', 'OPSGENIE', 'EMAIL'];
const TICKETING_PLATFORMS = ['JIRA'];

export default function NotificationCardMenu({
  notificationId,
  eventType,
  entityType,
  entityId,
  onMuted,
  onForwarded,
}: NotificationCardMenuProps) {
  const [open, setOpen] = useState(false);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [sending, setSending] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && integrations.length === 0) {
      cachedFetch('/api/integrations?layer=notifications,ticketing')
        .then((res) => res.json())
        .then((data) => setIntegrations((data.integrations || []).filter((i: Integration) => i.status === 'ACTIVE')))
        .catch(() => {});
    }
  }, [open]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const handleMute = async () => {
    try {
      await fetch('/api/notifications/mutes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ eventType, entityType, entityId }),
      });
      setOpen(false);
      onMuted?.();
    } catch {}
  };

  const handleForward = async (integrationId: string) => {
    setSending(integrationId);
    try {
      await fetch(`/api/notifications/${notificationId}/forward`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ integrationId }),
      });
      setOpen(false);
      onForwarded?.();
    } catch {}
    setSending(null);
  };

  const notifPlatforms = integrations.filter((i) =>
    NOTIFICATION_PLATFORMS.includes(i.type.toUpperCase()),
  );
  const ticketPlatforms = integrations.filter((i) =>
    TICKETING_PLATFORMS.includes(i.type.toUpperCase()),
  );

  return (
    <div ref={menuRef} className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className="p-1 rounded hover:bg-[var(--overlay-faint)] transition-colors"
      >
        <MoreVertical className="w-4 h-4 text-[var(--muted)]" />
      </button>

      {open && (
        <div className="absolute right-0 top-6 z-50 w-56 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] shadow-xl py-1">
          {/* Mute */}
          <button
            onClick={handleMute}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--muted)] hover:bg-[var(--overlay-faint)] hover:text-[var(--text)]"
          >
            <BellOff className="w-4 h-4" />
            Mute notifications like this
          </button>

          {/* Notification platforms */}
          {notifPlatforms.length > 0 && (
            <>
              <div className="border-t border-[var(--subtle-border)] my-1" />
              {notifPlatforms.map((int) => (
                <button
                  key={int.id}
                  onClick={() => handleForward(int.id)}
                  disabled={sending === int.id}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--muted)] hover:bg-[var(--overlay-faint)] hover:text-[var(--text)] disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                  {sending === int.id ? 'Sending...' : PLATFORM_LABELS[int.type.toUpperCase()] || `Send to ${int.type}`}
                </button>
              ))}
            </>
          )}

          {/* Ticketing platforms */}
          {ticketPlatforms.length > 0 && (
            <>
              <div className="border-t border-[var(--subtle-border)] my-1" />
              {ticketPlatforms.map((int) => (
                <button
                  key={int.id}
                  onClick={() => handleForward(int.id)}
                  disabled={sending === int.id}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--muted)] hover:bg-[var(--overlay-faint)] hover:text-[var(--text)] disabled:opacity-50"
                >
                  <ExternalLink className="w-4 h-4" />
                  {sending === int.id ? 'Creating...' : PLATFORM_LABELS[int.type.toUpperCase()] || `Create ${int.type} ticket`}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add 3-dot menu to NotificationCard**

In `components/notifications/NotificationCard.tsx`, import the menu component:

```typescript
import NotificationCardMenu from './NotificationCardMenu';
```

Then add the menu in the card header area (next to the severity badge or timestamp). Find the top-right area of the card layout and add:

```tsx
<NotificationCardMenu
  notificationId={notification.id}
  eventType={notification.eventType}
  entityType={notification.entityType}
  entityId={notification.entityId}
  onMuted={() => { /* trigger refetch of notifications list */ }}
/>
```

The exact placement depends on the card's JSX layout — add it in the top-right corner of the card, next to the existing timestamp or severity badge.

- [ ] **Step 3: Commit**

```bash
git add components/notifications/NotificationCardMenu.tsx components/notifications/NotificationCard.tsx
git commit -m "feat: add 3-dot menu to notification cards (mute, forward, create ticket)"
```

---

### Task 12: Notification Routing Settings Component

**Files:**
- Create: `components/settings/NotificationRoutingSettings.tsx`
- Modify: `app/(dashboard)/dashboard/settings/page.tsx`

- [ ] **Step 1: Create NotificationRoutingSettings component**

Create `components/settings/NotificationRoutingSettings.tsx`:

```tsx
'use client';

import { useState, useEffect } from 'react';
import { cachedFetch } from '@/lib/fetch-cache';
import { Bell, Plus, X, Check } from 'lucide-react';

interface Integration {
  id: string;
  type: string;
  status: string;
  metadata?: Record<string, any>;
}

interface Destination {
  integrationId: string;
  channel?: string;
}

interface Route {
  severity: string;
  enabled: boolean;
  notifyOnRecovery: boolean;
  destinations: Destination[];
}

const SEVERITIES = ['CRITICAL', 'ERROR', 'WARN', 'INFO'];
const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'bg-red-500/20 text-red-400 border-red-500/30',
  ERROR: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  WARN: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  INFO: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
};

export default function NotificationRoutingSettings() {
  const [routes, setRoutes] = useState<Route[]>(
    SEVERITIES.map((s) => ({ severity: s, enabled: false, notifyOnRecovery: false, destinations: [] })),
  );
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    // Fetch existing routes
    cachedFetch('/api/settings/notification-routes')
      .then((r) => r.json())
      .then((data) => {
        if (data.routes?.length) {
          setRoutes((prev) =>
            prev.map((r) => {
              const existing = data.routes.find((er: any) => er.severity === r.severity);
              return existing
                ? { ...r, enabled: existing.enabled, notifyOnRecovery: existing.notifyOnRecovery, destinations: existing.destinations || [] }
                : r;
            }),
          );
        }
      })
      .catch(() => {});

    // Fetch connected notification integrations
    cachedFetch('/api/integrations?layer=notifications')
      .then((r) => r.json())
      .then((data) => setIntegrations((data.integrations || []).filter((i: Integration) => i.status === 'ACTIVE')))
      .catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch('/api/settings/notification-routes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ routes }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {}
    setSaving(false);
  };

  const updateRoute = (severity: string, updates: Partial<Route>) => {
    setRoutes((prev) => prev.map((r) => (r.severity === severity ? { ...r, ...updates } : r)));
  };

  const addDestination = (severity: string, integrationId: string) => {
    setRoutes((prev) =>
      prev.map((r) => {
        if (r.severity !== severity) return r;
        if (r.destinations.some((d) => d.integrationId === integrationId)) return r;
        return { ...r, destinations: [...r.destinations, { integrationId }] };
      }),
    );
  };

  const removeDestination = (severity: string, integrationId: string) => {
    setRoutes((prev) =>
      prev.map((r) => {
        if (r.severity !== severity) return r;
        return { ...r, destinations: r.destinations.filter((d) => d.integrationId !== integrationId) };
      }),
    );
  };

  const getIntegrationLabel = (id: string) => {
    const int = integrations.find((i) => i.id === id);
    if (!int) return 'Unknown';
    const name = int.metadata?.teamName || int.metadata?.workspace || int.type;
    return `${int.type} — ${name}`;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-[var(--text)]">Notification Routing</h3>
          <p className="text-sm text-[var(--muted)] mt-1">
            Configure where monitor group results are sent based on severity. In-app notifications always appear regardless of these settings.
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium disabled:opacity-50 flex items-center gap-2"
        >
          {saved ? <><Check className="w-4 h-4" /> Saved</> : saving ? 'Saving...' : 'Save'}
        </button>
      </div>

      <div className="space-y-4">
        {routes.map((route) => (
          <div
            key={route.severity}
            className="rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-faint)] p-4"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <span className={`px-2 py-0.5 rounded text-xs font-medium border ${SEVERITY_COLORS[route.severity]}`}>
                  {route.severity}
                </span>
                <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
                  <input
                    type="checkbox"
                    checked={route.enabled}
                    onChange={(e) => updateRoute(route.severity, { enabled: e.target.checked })}
                    className="rounded"
                  />
                  Enabled
                </label>
                <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
                  <input
                    type="checkbox"
                    checked={route.notifyOnRecovery}
                    onChange={(e) => updateRoute(route.severity, { notifyOnRecovery: e.target.checked })}
                    className="rounded"
                  />
                  Notify on recovery
                </label>
              </div>
            </div>

            {/* Destinations */}
            <div className="flex flex-wrap gap-2 items-center">
              {route.destinations.map((dest) => (
                <span
                  key={dest.integrationId}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-[var(--overlay-faint)] border border-[var(--subtle-border)] text-sm text-[var(--muted)]"
                >
                  {getIntegrationLabel(dest.integrationId)}
                  <button
                    onClick={() => removeDestination(route.severity, dest.integrationId)}
                    className="hover:text-red-400"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}

              {/* Add destination dropdown */}
              {integrations.filter(
                (i) => !route.destinations.some((d) => d.integrationId === i.id),
              ).length > 0 && (
                <select
                  onChange={(e) => {
                    if (e.target.value) addDestination(route.severity, e.target.value);
                    e.target.value = '';
                  }}
                  className="px-2 py-1 rounded-md bg-[var(--overlay-faint)] border border-[var(--subtle-border)] text-sm text-[var(--muted)] cursor-pointer"
                  defaultValue=""
                >
                  <option value="" disabled>
                    + Add platform
                  </option>
                  {integrations
                    .filter((i) => !route.destinations.some((d) => d.integrationId === i.id))
                    .map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.type} — {i.metadata?.teamName || i.metadata?.workspace || i.type}
                      </option>
                    ))}
                </select>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Replace notifications tab content in settings page**

In `app/(dashboard)/dashboard/settings/page.tsx`, a "Notifications" tab already exists at line 152. Replace its content (currently Slack-specific toggle switches, around lines 384-471) with the new routing component:

1. Import the component:
```typescript
import NotificationRoutingSettings from '@/components/settings/NotificationRoutingSettings';
```

2. Find the existing `{activeTab === 'notifications' && (...)}` block and replace its content with:
```tsx
{activeTab === 'notifications' && (
  <NotificationRoutingSettings />
)}
```

- [ ] **Step 3: Commit**

```bash
git add components/settings/NotificationRoutingSettings.tsx app/(dashboard)/dashboard/settings/page.tsx
git commit -m "feat: add notification routing settings UI with severity-based destination config"
```

---

### Task 13: Final Integration Test

- [ ] **Step 1: Run all tests**

Run: `npx jest --no-coverage --passWithNoTests`
Expected: All tests pass

- [ ] **Step 2: Run Prisma generate to verify schema**

Run: `npx prisma generate`
Expected: Success

- [ ] **Step 3: Build check**

Run: `npx next build`
Expected: Build succeeds (or only pre-existing warnings)

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address build/test issues from notification routing feature"
```
