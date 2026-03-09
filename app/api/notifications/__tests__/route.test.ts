/**
 * Notification API route tests.
 *
 * These tests mock NextAuth session and Prisma to verify API behavior.
 * To run, install a test runner (jest/vitest) and configure module
 * path aliases (@/ → project root).
 *
 * Example (with vitest):
 *   npx vitest run app/api/notifications/__tests__/route.test.ts
 */

// ── Mocks ──────────────────────────────────────────────────────────

const mockUser = { id: 'user-1', organizationId: 'org-1' };

jest.mock('next-auth', () => ({
  getServerSession: jest.fn().mockResolvedValue({
    user: { email: 'test@example.com', id: 'user-1', organizationId: 'org-1' },
  }),
}));

const mockFindUnique = jest.fn().mockResolvedValue(mockUser);
const mockFindMany = jest.fn().mockResolvedValue([]);
const mockCount = jest.fn().mockResolvedValue(0);
const mockCreateMany = jest.fn().mockResolvedValue({ count: 0 });

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    user: { findUnique: (...args: any[]) => mockFindUnique(...args) },
    notificationEvent: {
      findMany: (...args: any[]) => mockFindMany(...args),
      count: (...args: any[]) => mockCount(...args),
    },
    notificationRead: {
      createMany: (...args: any[]) => mockCreateMany(...args),
    },
  },
}));

jest.mock('@/lib/auth', () => ({ authOptions: {} }));

// ── Tests ──────────────────────────────────────────────────────────

describe('GET /api/notifications', () => {
  beforeEach(() => {
    mockFindMany.mockClear();
    mockFindUnique.mockClear();
    mockFindUnique.mockResolvedValue(mockUser);
  });

  it('returns paginated notifications scoped to org', async () => {
    const mockNotifications = [
      {
        id: 'n-1',
        eventType: 'monitor.failed',
        severity: 'ERROR',
        title: 'Monitor failed',
        message: 'Threshold exceeded',
        entityType: 'MONITOR',
        entityId: 'task-1',
        actionUrl: '/dashboard/schedule?task=task-1',
        metadata: null,
        pipelineStackId: 'pipe-1',
        createdAt: new Date('2026-03-01T12:00:00Z'),
        isRead: false,
        reads: [],
        actorUser: null,
      },
    ];
    mockFindMany.mockResolvedValue(mockNotifications);

    // Verify the query includes org scoping
    const { GET } = await import('../route');
    const request = new Request('http://localhost/api/notifications?limit=10');
    const response = await GET(request as any);
    const data = await response.json();

    expect(data.notifications).toHaveLength(1);
    expect(data.notifications[0].id).toBe('n-1');
    expect(data.notifications[0].isRead).toBe(false);

    // Verify org scoping in Prisma query
    const where = mockFindMany.mock.calls[0][0].where;
    expect(where.organizationId).toBe('org-1');
  });

  it('filters by unreadOnly', async () => {
    mockFindMany.mockResolvedValue([]);

    const { GET } = await import('../route');
    const request = new Request('http://localhost/api/notifications?unreadOnly=true');
    await GET(request as any);

    const where = mockFindMany.mock.calls[0][0].where;
    expect(where.reads).toEqual({ none: { userId: 'user-1' } });
  });

  it('rejects unauthenticated requests', async () => {
    const { getServerSession } = require('next-auth');
    getServerSession.mockResolvedValueOnce(null);

    const { GET } = await import('../route');
    const request = new Request('http://localhost/api/notifications');
    const response = await GET(request as any);

    expect(response.status).toBe(401);
  });
});

describe('GET /api/notifications/unread-count', () => {
  beforeEach(() => {
    mockCount.mockClear();
    mockFindUnique.mockClear();
    mockFindUnique.mockResolvedValue(mockUser);
  });

  it('returns correct unread count', async () => {
    mockCount.mockResolvedValue(5);

    const { GET } = await import('../unread-count/route');
    const response = await GET();
    const data = await response.json();

    expect(data.count).toBe(5);

    // Verify org scoping + unread filter
    const where = mockCount.mock.calls[0][0].where;
    expect(where.organizationId).toBe('org-1');
    expect(where.reads).toEqual({ none: { userId: 'user-1' } });
  });
});

describe('POST /api/notifications/mark-read', () => {
  beforeEach(() => {
    mockCreateMany.mockClear();
    mockFindMany.mockClear();
    mockFindUnique.mockClear();
    mockFindUnique.mockResolvedValue(mockUser);
  });

  it('creates NotificationRead records for valid IDs', async () => {
    mockFindMany.mockResolvedValue([{ id: 'n-1' }, { id: 'n-2' }]);
    mockCreateMany.mockResolvedValue({ count: 2 });

    const { POST } = await import('../mark-read/route');
    const request = new Request('http://localhost/api/notifications/mark-read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notificationIds: ['n-1', 'n-2', 'n-invalid'] }),
    });
    const response = await POST(request as any);
    const data = await response.json();

    expect(data.marked).toBe(2);
    expect(mockCreateMany).toHaveBeenCalledTimes(1);
  });

  it('rejects empty notificationIds', async () => {
    const { POST } = await import('../mark-read/route');
    const request = new Request('http://localhost/api/notifications/mark-read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notificationIds: [] }),
    });
    const response = await POST(request as any);

    expect(response.status).toBe(400);
  });
});
