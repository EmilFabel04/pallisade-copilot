const mockFindMany = jest.fn().mockResolvedValue([]);

jest.mock('@/lib/db', () => ({
  __esModule: true,
  default: {
    monitorRun: {
      findMany: (...args: any[]) => mockFindMany(...args),
    },
  },
}));

import { detectHighImpactEvents } from '../high-impact-events';

describe('detectHighImpactEvents', () => {
  beforeEach(() => {
    mockFindMany.mockClear();
    mockFindMany.mockResolvedValue([]);
  });

  describe('detectHealthScoreDrop', () => {
    it('should detect health score drop from healthy to degraded', async () => {
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

    it('should NOT detect drop when score stays in same bucket', async () => {
      const events = await detectHighImpactEvents({
        watchId: 'w1',
        organizationId: 'org1',
        pipelineStackId: 'pipe1',
        currentHealthScore: 72,
        previousHealthScore: 85,
        results: [],
      });
      const drop = events.find((e) => e.eventType === 'monitor.health_score_dropped');
      expect(drop).toBeUndefined();
    });
  });

  describe('detectSustainedFailures', () => {
    it('should detect sustained failure (3 consecutive FAILs)', async () => {
      mockFindMany.mockResolvedValue([
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
      mockFindMany.mockResolvedValue([
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
      const events = await detectHighImpactEvents({
        watchId: 'w1',
        organizationId: 'org1',
        pipelineStackId: 'pipe1',
        currentHealthScore: 90,
        previousHealthScore: 90,
        results: [{ monitorId: 'm1', monitorName: 'Freshness Check', status: 'PASS' }],
      });
      expect(mockFindMany).not.toHaveBeenCalled();
      const sustained = events.find((e) => e.eventType === 'monitor.sustained_failure');
      expect(sustained).toBeUndefined();
    });
  });
});
