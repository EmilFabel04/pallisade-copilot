import { diagnoseIncident, __resetSemaphoresForTest } from '../diagnose';

const fetchMock = jest.fn();
(global as any).fetch = fetchMock;

const incidentMock = { update: jest.fn() };
const prismaMock = {
  incident: {
    findUnique: jest.fn(),
    update: incidentMock.update,
  },
  monitorRun: {
    findUnique: jest.fn().mockResolvedValue({ value: null, threshold: null, message: '', details: {}, status: 'FAIL' }),
  },
} as any;

beforeEach(() => {
  fetchMock.mockReset();
  incidentMock.update.mockReset();
  prismaMock.incident.findUnique.mockReset();
  prismaMock.monitorRun.findUnique.mockReset();
  prismaMock.monitorRun.findUnique.mockResolvedValue({ value: null, threshold: null, message: '', details: {}, status: 'FAIL' });
  __resetSemaphoresForTest();
});

describe('diagnoseIncident', () => {
  it('writes hypothesis/signature/owner back; resets consecutiveCount on signature change', async () => {
    prismaMock.incident.findUnique.mockResolvedValue({
      id: 'inc_1',
      pipelineStackId: 'stack_1',
      targetFqn: 'raw.orders',
      monitorId: 'mon_1',
      openingRunId: 'run_1',
      signature: 'previous-sig',
      consecutiveCount: 2,
      monitor: { monitorType: 'FRESHNESS' },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        hypothesis: 'Upstream sync stalled.',
        signature: 'fivetran-source-stalled',
        ownerSystem: 'ingestion',
        ownerConfidence: 0.85,
      }),
    });

    await diagnoseIncident('inc_1', prismaMock);

    expect(incidentMock.update).toHaveBeenCalledTimes(1);
    const data = incidentMock.update.mock.calls[0][0].data;
    expect(data.signature).toBe('fivetran-source-stalled');
    expect(data.llmHypothesis).toBe('Upstream sync stalled.');
    expect(data.ownerSystem).toBe('ingestion');
    expect(data.ownerConfidence).toBe(0.85);
    expect(data.consecutiveCount).toBe(1); // signature changed → reset
  });

  it('increments consecutiveCount when signature is unchanged', async () => {
    prismaMock.incident.findUnique.mockResolvedValue({
      id: 'inc_1',
      pipelineStackId: 'stack_1',
      targetFqn: 'raw.orders',
      monitorId: 'mon_1',
      openingRunId: 'run_1',
      signature: 'fivetran-source-stalled',
      consecutiveCount: 2,
      monitor: { monitorType: 'FRESHNESS' },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        hypothesis: 'Same as before.',
        signature: 'fivetran-source-stalled',
        ownerSystem: 'ingestion',
        ownerConfidence: 0.9,
      }),
    });

    await diagnoseIncident('inc_1', prismaMock);

    const data = incidentMock.update.mock.calls[0][0].data;
    expect(data.consecutiveCount).toBe(3);
  });

  it('falls back to deterministic signature on scanner error', async () => {
    prismaMock.incident.findUnique.mockResolvedValue({
      id: 'inc_1',
      pipelineStackId: 'stack_1',
      targetFqn: 'raw.orders',
      monitorId: 'mon_1',
      openingRunId: 'run_1',
      signature: null,
      consecutiveCount: 1,
      monitor: { monitorType: 'FRESHNESS' },
    });
    fetchMock.mockRejectedValue(new Error('connection refused'));

    await diagnoseIncident('inc_1', prismaMock);

    const data = incidentMock.update.mock.calls[0][0].data;
    expect(data.signature).toMatch(/^freshness-/);
    expect(data.llmHypothesis).toContain('Unable to generate'); // deterministic fallback string
  });
});
