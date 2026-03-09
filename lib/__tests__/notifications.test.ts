/**
 * Notification helper unit tests.
 *
 * These tests mock Prisma and verify that notify() and notifyEvents.*
 * behave correctly. To run, install a test runner (jest/vitest) and
 * configure module path aliases (@/ → project root).
 *
 * Example (with vitest):
 *   npx vitest run lib/__tests__/notifications.test.ts
 */

// ── Mocks ──────────────────────────────────────────────────────────

const mockCreate = jest.fn().mockResolvedValue({ id: 'test-id' });
const mockFindFirst = jest.fn().mockResolvedValue(null);

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    notificationEvent: {
      create: (...args: any[]) => mockCreate(...args),
      findFirst: (...args: any[]) => mockFindFirst(...args),
    },
  },
}));

import { notify, notifyEvents } from '../notifications';

// ── Tests ──────────────────────────────────────────────────────────

describe('notify()', () => {
  beforeEach(() => {
    mockCreate.mockClear();
    mockFindFirst.mockClear();
    mockFindFirst.mockResolvedValue(null);
  });

  it('creates a NotificationEvent record', async () => {
    await notify({
      organizationId: 'org-1',
      eventType: 'monitor.failed',
      severity: 'ERROR',
      title: 'Monitor failed',
      message: 'Threshold exceeded',
    });

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const data = mockCreate.mock.calls[0][0].data;
    expect(data.organizationId).toBe('org-1');
    expect(data.eventType).toBe('monitor.failed');
    expect(data.severity).toBe('ERROR');
  });

  it('skips creation when dedupeKey matches within window', async () => {
    mockFindFirst.mockResolvedValue({ id: 'existing' });

    await notify({
      organizationId: 'org-1',
      eventType: 'monitor.failed',
      severity: 'ERROR',
      title: 'Monitor failed',
      message: 'Same event',
      dedupeKey: 'monitor:task-1',
    });

    expect(mockFindFirst).toHaveBeenCalledTimes(1);
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('creates when dedupeKey has no recent match', async () => {
    mockFindFirst.mockResolvedValue(null);

    await notify({
      organizationId: 'org-1',
      eventType: 'monitor.failed',
      severity: 'ERROR',
      title: 'Monitor failed',
      message: 'New event',
      dedupeKey: 'monitor:task-1',
    });

    expect(mockFindFirst).toHaveBeenCalledTimes(1);
    expect(mockCreate).toHaveBeenCalledTimes(1);
  });

  it('never throws on database error', async () => {
    mockCreate.mockRejectedValue(new Error('DB connection lost'));

    // Should not throw
    await expect(
      notify({
        organizationId: 'org-1',
        eventType: 'test.error',
        title: 'Test',
        message: 'Test',
      }),
    ).resolves.toBeUndefined();
  });
});

describe('notifyEvents convenience helpers', () => {
  beforeEach(() => {
    mockCreate.mockClear();
    mockFindFirst.mockClear();
    mockFindFirst.mockResolvedValue(null);
  });

  it('monitorFailed sets correct eventType and severity', async () => {
    await notifyEvents.monitorFailed('org-1', 'pipe-1', 'user-1', 'Freshness', 'task-1', 'Late');

    const data = mockCreate.mock.calls[0][0].data;
    expect(data.eventType).toBe('monitor.failed');
    expect(data.severity).toBe('ERROR');
    expect(data.entityType).toBe('MONITOR');
    expect(data.dedupeKey).toBe('monitor:task-1');
  });

  it('monitorPassed sets INFO severity', async () => {
    await notifyEvents.monitorPassed('org-1', 'pipe-1', 'Freshness', 'task-1');

    const data = mockCreate.mock.calls[0][0].data;
    expect(data.eventType).toBe('monitor.passed');
    expect(data.severity).toBe('INFO');
  });

  it('integrationCreated sets correct fields', async () => {
    await notifyEvents.integrationCreated('org-1', 'pipe-1', 'user-1', 'My BQ', 'BIGQUERY', 'int-1');

    const data = mockCreate.mock.calls[0][0].data;
    expect(data.eventType).toBe('integration.created');
    expect(data.entityType).toBe('SOURCE');
    expect(data.entityId).toBe('int-1');
  });

  it('teamInviteSent sets correct fields', async () => {
    await notifyEvents.teamInviteSent('org-1', 'user-1', 'new@example.com');

    const data = mockCreate.mock.calls[0][0].data;
    expect(data.eventType).toBe('team.invite_sent');
    expect(data.entityType).toBe('INVITE');
  });

  it('planApplied includes actionUrl', async () => {
    await notifyEvents.planApplied('org-1', 'pipe-1', 'user-1', 'Fix schema', 'https://github.com/org/repo/pull/1');

    const data = mockCreate.mock.calls[0][0].data;
    expect(data.eventType).toBe('plan.applied');
    expect(data.actionUrl).toBe('https://github.com/org/repo/pull/1');
  });

  it('lineageExtractionFailed sets ERROR severity', async () => {
    await notifyEvents.lineageExtractionFailed('org-1', 'pipe-1', 'user-1', 'BigQuery', 'Timeout');

    const data = mockCreate.mock.calls[0][0].data;
    expect(data.eventType).toBe('lineage.extraction_failed');
    expect(data.severity).toBe('ERROR');
  });
});
