/**
 * Route-level test for /api/pipeline/[stackId]/lineage.
 * Mocks auth + prisma to assert filter shapes and the 404 ownership check.
 */

jest.mock('@/auth', () => ({
  auth: jest.fn().mockResolvedValue({
    user: { email: 'test@example.com', organizationId: 'org-1' },
  }),
}));

const mockStackFindFirst = jest.fn();
const mockNodeFindMany = jest.fn().mockResolvedValue([]);
const mockEdgeFindMany = jest.fn().mockResolvedValue([]);
const mockSnapshotFindFirst = jest.fn().mockResolvedValue(null);
const mockNodeDeleteMany = jest.fn().mockResolvedValue({ count: 0 });
const mockEdgeDeleteMany = jest.fn().mockResolvedValue({ count: 0 });
const mockSnapshotDeleteMany = jest.fn().mockResolvedValue({ count: 0 });

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    pipelineStack: { findFirst: (...a: any[]) => mockStackFindFirst(...a) },
    lineageNode: {
      findMany: (...a: any[]) => mockNodeFindMany(...a),
      deleteMany: (...a: any[]) => mockNodeDeleteMany(...a),
    },
    lineageEdge: {
      findMany: (...a: any[]) => mockEdgeFindMany(...a),
      deleteMany: (...a: any[]) => mockEdgeDeleteMany(...a),
    },
    lineageSnapshot: {
      findFirst: (...a: any[]) => mockSnapshotFindFirst(...a),
      deleteMany: (...a: any[]) => mockSnapshotDeleteMany(...a),
    },
  },
}));

jest.mock('@/lib/scanner-client', () => ({
  scannerClient: { fetch: jest.fn().mockResolvedValue({ ok: true }) },
}));

beforeEach(() => {
  mockStackFindFirst.mockReset();
  mockNodeFindMany.mockReset().mockResolvedValue([]);
  mockEdgeFindMany.mockReset().mockResolvedValue([]);
  mockSnapshotFindFirst.mockReset().mockResolvedValue(null);
  mockNodeDeleteMany.mockReset().mockResolvedValue({ count: 0 });
  mockEdgeDeleteMany.mockReset().mockResolvedValue({ count: 0 });
  mockSnapshotDeleteMany.mockReset().mockResolvedValue({ count: 0 });
});

describe('GET /api/pipeline/[stackId]/lineage', () => {
  it('filters by pipelineStackId on every query', async () => {
    mockStackFindFirst.mockResolvedValue({ id: 'stack-1' });
    const { GET } = await import('../route');
    const req = new Request('http://localhost/api/pipeline/stack-1/lineage');
    await GET(req as any, { params: Promise.resolve({ stackId: 'stack-1' }) });

    expect(mockNodeFindMany.mock.calls[0][0].where).toEqual({
      organizationId: 'org-1',
      pipelineStackId: 'stack-1',
    });
    expect(mockEdgeFindMany.mock.calls[0][0].where).toMatchObject({
      organizationId: 'org-1',
      pipelineStackId: 'stack-1',
    });
    expect(mockSnapshotFindFirst.mock.calls[0][0].where).toEqual({
      organizationId: 'org-1',
      pipelineStackId: 'stack-1',
    });
  });

  it('returns 404 for unknown stackId', async () => {
    mockStackFindFirst.mockResolvedValue(null);
    const { GET } = await import('../route');
    const req = new Request('http://localhost/api/pipeline/wrong/lineage');
    const res = await GET(req as any, { params: Promise.resolve({ stackId: 'wrong' }) });
    expect(res.status).toBe(404);
    expect(mockNodeFindMany).not.toHaveBeenCalled();
  });
});

describe('DELETE /api/pipeline/[stackId]/lineage', () => {
  it('404s on stackId not in caller org', async () => {
    mockStackFindFirst.mockResolvedValue(null);
    const { DELETE } = await import('../route');
    const req = new Request('http://localhost/api/pipeline/foreign/lineage', { method: 'DELETE' });
    const res = await DELETE(req as any, { params: Promise.resolve({ stackId: 'foreign' }) });

    expect(res.status).toBe(404);
    expect(mockNodeDeleteMany).not.toHaveBeenCalled();
    expect(mockEdgeDeleteMany).not.toHaveBeenCalled();
  });

  it('scopes deleteMany calls to (organizationId, pipelineStackId)', async () => {
    mockStackFindFirst.mockResolvedValue({ id: 'stack-1' });
    mockNodeDeleteMany.mockResolvedValue({ count: 5 });
    mockEdgeDeleteMany.mockResolvedValue({ count: 7 });
    mockSnapshotDeleteMany.mockResolvedValue({ count: 1 });

    const { DELETE } = await import('../route');
    const req = new Request('http://localhost/api/pipeline/stack-1/lineage', { method: 'DELETE' });
    const res = await DELETE(req as any, { params: Promise.resolve({ stackId: 'stack-1' }) });
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.deleted).toEqual({ nodes: 5, edges: 7, snapshots: 1 });
    expect(mockEdgeDeleteMany.mock.calls[0][0].where).toEqual({
      organizationId: 'org-1', pipelineStackId: 'stack-1',
    });
    expect(mockNodeDeleteMany.mock.calls[0][0].where).toEqual({
      organizationId: 'org-1', pipelineStackId: 'stack-1',
    });
    expect(mockSnapshotDeleteMany.mock.calls[0][0].where).toEqual({
      organizationId: 'org-1', pipelineStackId: 'stack-1',
    });
  });
});
