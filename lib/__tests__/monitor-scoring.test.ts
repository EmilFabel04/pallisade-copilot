/**
 * Monitor scoring utility tests.
 *
 * To run:
 *   npx jest lib/__tests__/monitor-scoring.test.ts
 */

import {
  computeMonitorHealth,
  computeMonitorCoverage,
  computeMonitorScoring,
  resolveAssetCategory,
  healthStatusFromScore,
  getApplicableMonitorTypes,
  type AssetCategory,
} from '../monitor-scoring';

// ---------------------------------------------------------------------------
// Health scoring
// ---------------------------------------------------------------------------

describe('computeMonitorHealth', () => {
  it('single PASS → health 100', () => {
    const result = computeMonitorHealth([{ lastStatus: 'PASS' }]);
    expect(result.healthScore).toBe(100);
    expect(result.healthStatus).toBe('healthy');
  });

  it('single WARN → health 50', () => {
    const result = computeMonitorHealth([{ lastStatus: 'WARN' }]);
    expect(result.healthScore).toBe(50);
    expect(result.healthStatus).toBe('at_risk');
  });

  it('single FAIL → health 0', () => {
    const result = computeMonitorHealth([{ lastStatus: 'FAIL' }]);
    expect(result.healthScore).toBe(0);
    expect(result.healthStatus).toBe('unhealthy');
  });

  it('single ERROR → health 0', () => {
    const result = computeMonitorHealth([{ lastStatus: 'ERROR' }]);
    expect(result.healthScore).toBe(0);
    expect(result.healthStatus).toBe('unhealthy');
  });

  it('PASS + PASS + WARN → health 83.3', () => {
    const result = computeMonitorHealth([
      { lastStatus: 'PASS' },
      { lastStatus: 'PASS' },
      { lastStatus: 'WARN' },
    ]);
    expect(result.healthScore).toBeCloseTo(83.3, 0);
    expect(result.healthStatus).toBe('degraded');
  });

  it('PASS + FAIL → health 50', () => {
    const result = computeMonitorHealth([
      { lastStatus: 'PASS' },
      { lastStatus: 'FAIL' },
    ]);
    expect(result.healthScore).toBe(50);
    expect(result.healthStatus).toBe('at_risk');
  });

  it('WARN + FAIL + ERROR → health 16.7', () => {
    const result = computeMonitorHealth([
      { lastStatus: 'WARN' },
      { lastStatus: 'FAIL' },
      { lastStatus: 'ERROR' },
    ]);
    expect(result.healthScore).toBeCloseTo(16.7, 0);
    expect(result.healthStatus).toBe('unhealthy');
  });

  it('all SKIPPED/RUNNING → health null (no stable signals)', () => {
    const result = computeMonitorHealth([
      { lastStatus: 'SKIPPED' },
      { lastStatus: 'RUNNING' },
    ]);
    expect(result.healthScore).toBeNull();
    expect(result.healthStatus).toBe('unmonitored');
  });

  it('SKIPPED excluded from denominator', () => {
    const result = computeMonitorHealth([
      { lastStatus: 'PASS' },
      { lastStatus: 'SKIPPED' },
    ]);
    // Only PASS counts → 100/1 = 100
    expect(result.healthScore).toBe(100);
  });

  it('RUNNING excluded from denominator', () => {
    const result = computeMonitorHealth([
      { lastStatus: 'PASS' },
      { lastStatus: 'RUNNING' },
    ]);
    expect(result.healthScore).toBe(100);
  });

  it('null status excluded from denominator', () => {
    const result = computeMonitorHealth([
      { lastStatus: 'PASS' },
      { lastStatus: null },
    ]);
    expect(result.healthScore).toBe(100);
  });

  it('no monitors → unmonitored', () => {
    const result = computeMonitorHealth([]);
    expect(result.healthScore).toBeNull();
    expect(result.healthStatus).toBe('unmonitored');
  });

  it('case insensitive status matching', () => {
    const result = computeMonitorHealth([{ lastStatus: 'pass' }]);
    expect(result.healthScore).toBe(100);
  });
});

describe('healthStatusFromScore', () => {
  it('90 → healthy', () => expect(healthStatusFromScore(90)).toBe('healthy'));
  it('100 → healthy', () => expect(healthStatusFromScore(100)).toBe('healthy'));
  it('89 → degraded', () => expect(healthStatusFromScore(89)).toBe('degraded'));
  it('70 → degraded', () => expect(healthStatusFromScore(70)).toBe('degraded'));
  it('69 → at_risk', () => expect(healthStatusFromScore(69)).toBe('at_risk'));
  it('40 → at_risk', () => expect(healthStatusFromScore(40)).toBe('at_risk'));
  it('39 → unhealthy', () => expect(healthStatusFromScore(39)).toBe('unhealthy'));
  it('0 → unhealthy', () => expect(healthStatusFromScore(0)).toBe('unhealthy'));
});

// ---------------------------------------------------------------------------
// Coverage scoring
// ---------------------------------------------------------------------------

describe('computeMonitorCoverage', () => {
  it('warehouse 12/12 → coveragePct 100, coverageStatus good', () => {
    const result = computeMonitorCoverage(
      [
        'FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_CHECK',
        'UNIQUENESS_CHECK', 'REFERENTIAL', 'RANGE_VALIDATION',
        'ACCEPTED_VALUES', 'DATE_CONSISTENCY', 'DATA_TYPE_VALIDATION',
        'OUTLIER_DETECTION', 'CUSTOM_SQL',
      ],
      'warehouse',
    );
    expect(result.coveragePct).toBe(100);
    expect(result.coverageStatus).toBe('good');
    expect(result.missingTypes).toEqual([]);
  });

  it('warehouse 10/12 → coveragePct ~83.3, coverageStatus good (≥80%)', () => {
    const result = computeMonitorCoverage(
      [
        'FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_CHECK',
        'UNIQUENESS_CHECK', 'REFERENTIAL', 'RANGE_VALIDATION',
        'ACCEPTED_VALUES', 'OUTLIER_DETECTION', 'CUSTOM_SQL',
      ],
      'warehouse',
    );
    expect(result.coveragePct).toBeGreaterThanOrEqual(80);
    expect(result.coverageStatus).toBe('good');
  });

  it('warehouse 3/12 → coverageStatus partial', () => {
    const result = computeMonitorCoverage(
      ['FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE'],
      'warehouse',
    );
    expect(result.coveragePct).toBeLessThan(80);
    expect(result.coverageStatus).toBe('partial');
  });

  it('warehouse 0/12 → coverageStatus none', () => {
    const result = computeMonitorCoverage([], 'warehouse');
    expect(result.coveragePct).toBe(0);
    expect(result.coverageStatus).toBe('none');
  });

  it('legacy types (NULL_RATE, ANOMALY) expand to canonical equivalents', () => {
    const result = computeMonitorCoverage(
      ['FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_RATE', 'ANOMALY'],
      'warehouse',
    );
    // NULL_RATE → NULL_CHECK, ANOMALY → OUTLIER_DETECTION
    expect(result.configured).toBeGreaterThanOrEqual(5);
  });

  it('BI 4/4 → coverageStatus good', () => {
    const result = computeMonitorCoverage(
      ['BI_FRESHNESS_PROXY', 'BI_CONTENT_HEALTH', 'BI_UPSTREAM_BREAK_RISK', 'BI_REFRESH_FAILURE'],
      'bi',
    );
    expect(result.coveragePct).toBe(100);
    expect(result.coverageStatus).toBe('good');
  });

  it('BI 2/4 → coverageStatus partial (50% < 100%)', () => {
    const result = computeMonitorCoverage(
      ['BI_FRESHNESS_PROXY', 'BI_CONTENT_HEALTH'],
      'bi',
    );
    expect(result.coveragePct).toBe(50);
    expect(result.coverageStatus).toBe('partial');
  });

  it('orchestration 2/3 → coveragePct ~66.7', () => {
    const result = computeMonitorCoverage(
      ['DAG_LAST_RUN', 'DAG_SCHEDULE_LAG'],
      'orchestration',
    );
    expect(result.coveragePct).toBeCloseTo(66.7, 0);
    expect(result.coverageStatus).toBe('partial');
  });

  it('orchestration 3/3 → coveragePct 100', () => {
    const result = computeMonitorCoverage(
      ['DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE'],
      'orchestration',
    );
    expect(result.coveragePct).toBe(100);
    expect(result.coverageStatus).toBe('good');
  });

  it('non-applicable types are ignored (DAG_LAST_RUN in warehouse)', () => {
    const result = computeMonitorCoverage(
      ['FRESHNESS', 'DAG_LAST_RUN'],
      'warehouse',
    );
    expect(result.configured).toBe(1); // only FRESHNESS counts
    expect(result.coveragePct).toBeCloseTo(8.3, 0); // 1/12
  });

  it('case insensitive type matching', () => {
    const result = computeMonitorCoverage(['freshness'], 'warehouse');
    expect(result.configured).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Category resolver
// ---------------------------------------------------------------------------

describe('resolveAssetCategory', () => {
  it('warehouse platformDomain → warehouse', () => {
    expect(resolveAssetCategory(undefined, 'warehouse')).toBe('warehouse');
  });

  it('bi platformDomain → bi', () => {
    expect(resolveAssetCategory(undefined, 'bi')).toBe('bi');
  });

  it('reporting platformDomain → bi', () => {
    expect(resolveAssetCategory(undefined, 'reporting')).toBe('bi');
  });

  it('ingestion platformDomain → ingestion', () => {
    expect(resolveAssetCategory(undefined, 'ingestion')).toBe('ingestion');
  });

  it('orchestration platformDomain → orchestration', () => {
    expect(resolveAssetCategory(undefined, 'orchestration')).toBe('orchestration');
  });

  it('transform platformDomain → dbt_transform', () => {
    expect(resolveAssetCategory(undefined, 'transform')).toBe('dbt_transform');
  });

  it('WAREHOUSE layer fallback → warehouse', () => {
    expect(resolveAssetCategory('WAREHOUSE')).toBe('warehouse');
  });

  it('REPORTING layer fallback → bi', () => {
    expect(resolveAssetCategory('REPORTING')).toBe('bi');
  });

  it('unknown → null', () => {
    expect(resolveAssetCategory('UNKNOWN', 'other')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Combined scoring
// ---------------------------------------------------------------------------

describe('computeMonitorScoring', () => {
  it('orchestration 3/3 + all PASS → coveragePct 100, health 100', () => {
    const result = computeMonitorScoring(
      [
        { monitorType: 'DAG_LAST_RUN', lastStatus: 'PASS' },
        { monitorType: 'DAG_SCHEDULE_LAG', lastStatus: 'PASS' },
        { monitorType: 'TASK_FAILURE_RATE', lastStatus: 'PASS' },
      ],
      'orchestration',
    );
    expect(result.coveragePct).toBe(100);
    expect(result.coverageStatus).toBe('good');
    expect(result.healthScore).toBe(100);
    expect(result.healthStatus).toBe('healthy');
  });

  it('warehouse 80%+ configured → coverageStatus good', () => {
    // 10/12 types → 83.3% >= 80%
    const result = computeMonitorScoring(
      [
        { monitorType: 'FRESHNESS', lastStatus: 'PASS' },
        { monitorType: 'VOLUME', lastStatus: 'PASS' },
        { monitorType: 'SCHEMA_CHANGE', lastStatus: 'PASS' },
        { monitorType: 'NULL_CHECK', lastStatus: 'PASS' },
        { monitorType: 'UNIQUENESS_CHECK', lastStatus: 'PASS' },
        { monitorType: 'REFERENTIAL', lastStatus: 'PASS' },
        { monitorType: 'RANGE_VALIDATION', lastStatus: 'PASS' },
        { monitorType: 'ACCEPTED_VALUES', lastStatus: 'PASS' },
        { monitorType: 'OUTLIER_DETECTION', lastStatus: 'WARN' },
        { monitorType: 'CUSTOM_SQL', lastStatus: 'PASS' },
      ],
      'warehouse',
    );
    expect(result.coveragePct).toBeGreaterThanOrEqual(80);
    expect(result.coverageStatus).toBe('good');
  });

  it('warehouse few configured → coverageStatus partial', () => {
    const result = computeMonitorScoring(
      [
        { monitorType: 'FRESHNESS', lastStatus: 'PASS' },
        { monitorType: 'VOLUME', lastStatus: 'PASS' },
        { monitorType: 'SCHEMA_CHANGE', lastStatus: 'PASS' },
      ],
      'warehouse',
    );
    expect(result.coveragePct).toBeLessThan(80);
    expect(result.coverageStatus).toBe('partial');
  });

  it('non-table BI asset with BI monitors → health/coverage populated', () => {
    const result = computeMonitorScoring(
      [
        { monitorType: 'BI_FRESHNESS_PROXY', lastStatus: 'PASS' },
        { monitorType: 'BI_CONTENT_HEALTH', lastStatus: 'WARN' },
      ],
      'bi',
    );
    expect(result.healthScore).toBe(75);
    expect(result.healthStatus).toBe('degraded');
    expect(result.coveragePct).toBe(50); // 2/4
    expect(result.coverageStatus).toBe('partial');
    expect(result.configured).toBe(2);
    expect(result.available).toBe(4);
  });

  it('data asset detail and tool overview use the same scoring', () => {
    const monitors = [
      { monitorType: 'SYNC_LAG', lastStatus: 'PASS' },
      { monitorType: 'FAILED_SYNCS', lastStatus: 'FAIL' },
    ];
    const result1 = computeMonitorScoring(monitors, 'ingestion');
    const result2 = computeMonitorScoring(monitors, 'ingestion');
    expect(result1.healthScore).toBe(result2.healthScore);
    expect(result1.coveragePct).toBe(result2.coveragePct);
  });

  it('duplicate monitor types counted once for coverage', () => {
    const result = computeMonitorScoring(
      [
        { monitorType: 'FRESHNESS', lastStatus: 'PASS' },
        { monitorType: 'FRESHNESS', lastStatus: 'WARN' },
      ],
      'warehouse',
    );
    // Two monitors but same type → configured = 1
    expect(result.configured).toBe(1);
    // Health still averages both monitors
    expect(result.healthScore).toBe(75);
  });
});

// ---------------------------------------------------------------------------
// getApplicableMonitorTypes
// ---------------------------------------------------------------------------

describe('getApplicableMonitorTypes', () => {
  it('returns 12 types for warehouse', () => {
    expect(getApplicableMonitorTypes('warehouse')).toHaveLength(12);
  });

  it('returns 4 types for bi', () => {
    expect(getApplicableMonitorTypes('bi')).toHaveLength(4);
  });

  it('returns 3 types for ingestion', () => {
    expect(getApplicableMonitorTypes('ingestion')).toHaveLength(3);
  });

  it('returns empty array for unknown category', () => {
    expect(getApplicableMonitorTypes('unknown' as AssetCategory)).toEqual([]);
  });

  it('does not include CONTRACT_CHECK in any category', () => {
    for (const cat of ['warehouse', 'bi', 'ingestion', 'orchestration', 'dbt_transform', 'infra'] as const) {
      expect(getApplicableMonitorTypes(cat)).not.toContain('CONTRACT_CHECK');
    }
  });
});
