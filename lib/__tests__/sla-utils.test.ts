/**
 * SLA utility tests.
 *
 * To run:
 *   npx jest lib/__tests__/sla-utils.test.ts
 */

import {
  SLA_FIELD_MAP,
  getSLAValueForField,
  isLessStrictClient,
  getMonitorSLAStatus,
  type MonitorSLAStatus,
} from '../sla-utils';

describe('SLA_FIELD_MAP', () => {
  it('maps FRESHNESS monitor fields to SLA sections', () => {
    expect(SLA_FIELD_MAP.FRESHNESS.max_hours).toEqual(['freshness', 'maxHours']);
  });

  it('maps FRESHNESS warning_hours field', () => {
    expect(SLA_FIELD_MAP.FRESHNESS.warning_hours).toEqual(['freshness', 'warningHours']);
  });

  it('maps SYNC_LAG monitor fields to SLA sections', () => {
    expect(SLA_FIELD_MAP.SYNC_LAG.max_lag_minutes).toEqual(['ingestion', 'syncLagToleranceMinutes']);
  });

  it('maps VOLUME monitor fields', () => {
    expect(SLA_FIELD_MAP.VOLUME.min_rows).toEqual(['volume', 'minRows']);
    expect(SLA_FIELD_MAP.VOLUME.max_rows).toEqual(['volume', 'maxRows']);
  });

  it('maps SCHEMA_CHANGE strictness field', () => {
    expect(SLA_FIELD_MAP.SCHEMA_CHANGE.strictness).toEqual(['schema', 'strictness']);
  });

  it('maps NULL_CHECK monitor fields', () => {
    expect(SLA_FIELD_MAP.NULL_CHECK.max_null_rate).toEqual(['quality', 'maxNullRate']);
  });

  it('maps DBT_TEST_FAILURES monitor fields', () => {
    expect(SLA_FIELD_MAP.DBT_TEST_FAILURES.failure_tolerance).toEqual(['transform', 'testFailureTolerance']);
  });
});

describe('getSLAValueForField', () => {
  it('returns SLA value for a mapped field', () => {
    const sla = { freshness: { maxHours: 24 } };
    expect(getSLAValueForField('FRESHNESS', 'max_hours', sla)).toBe(24);
  });

  it('returns SLA value for SYNC_LAG', () => {
    const sla = { ingestion: { syncLagToleranceMinutes: 60 } };
    expect(getSLAValueForField('SYNC_LAG', 'max_lag_minutes', sla)).toBe(60);
  });

  it('returns SLA value for VOLUME min_rows', () => {
    const sla = { volume: { minRows: 1000 } };
    expect(getSLAValueForField('VOLUME', 'min_rows', sla)).toBe(1000);
  });

  it('returns undefined for unmapped monitor type', () => {
    expect(getSLAValueForField('UNKNOWN', 'field', {})).toBeUndefined();
  });

  it('returns undefined for unmapped field within a known monitor type', () => {
    expect(getSLAValueForField('FRESHNESS', 'nonexistent_field', { freshness: { maxHours: 24 } })).toBeUndefined();
  });

  it('returns undefined for null SLA', () => {
    expect(getSLAValueForField('FRESHNESS', 'max_hours', null)).toBeUndefined();
  });

  it('returns undefined when the policy section is missing', () => {
    const sla = { volume: { minRows: 100 } };
    expect(getSLAValueForField('FRESHNESS', 'max_hours', sla)).toBeUndefined();
  });

  it('returns undefined when the policy section field is missing', () => {
    const sla = { freshness: {} };
    expect(getSLAValueForField('FRESHNESS', 'max_hours', sla)).toBeUndefined();
  });

  it('converts sensitivity to zscore for ANOMALY anomaly_threshold', () => {
    const sla = { anomaly: { sensitivity: 0.99 } };
    const result = getSLAValueForField('ANOMALY', 'anomaly_threshold', sla);
    expect(typeof result).toBe('number');
    expect(result).toBe(2.0);
  });
});

describe('isLessStrictClient', () => {
  it('higher max_hours is less strict', () => {
    expect(isLessStrictClient('max_hours', 48, 24)).toBe(true);
  });

  it('lower max_hours is not less strict', () => {
    expect(isLessStrictClient('max_hours', 12, 24)).toBe(false);
  });

  it('equal max_hours is not less strict', () => {
    expect(isLessStrictClient('max_hours', 24, 24)).toBe(false);
  });

  it('strictness: ignore is less strict than warn', () => {
    expect(isLessStrictClient('strictness', 'ignore', 'warn')).toBe(true);
  });

  it('strictness: strict is not less strict than warn', () => {
    expect(isLessStrictClient('strictness', 'strict', 'warn')).toBe(false);
  });

  it('strictness: warn is less strict than strict', () => {
    expect(isLessStrictClient('strictness', 'warn', 'strict')).toBe(true);
  });

  it('strictness: equal values are not less strict', () => {
    expect(isLessStrictClient('strictness', 'warn', 'warn')).toBe(false);
  });

  it('failure_tolerance: relaxed is less strict than normal', () => {
    expect(isLessStrictClient('failure_tolerance', 'relaxed', 'normal')).toBe(true);
  });

  it('failure_tolerance: strict is not less strict than normal', () => {
    expect(isLessStrictClient('failure_tolerance', 'strict', 'normal')).toBe(false);
  });

  it('min_rows: lower value is less strict', () => {
    expect(isLessStrictClient('min_rows', 500, 1000)).toBe(true);
  });

  it('min_rows: higher value is not less strict', () => {
    expect(isLessStrictClient('min_rows', 2000, 1000)).toBe(false);
  });

  it('higher max_lag_minutes is less strict', () => {
    expect(isLessStrictClient('max_lag_minutes', 120, 60)).toBe(true);
  });

  it('higher max_null_rate is less strict', () => {
    expect(isLessStrictClient('max_null_rate', 0.2, 0.1)).toBe(true);
  });

  it('returns false when current value is null', () => {
    expect(isLessStrictClient('max_hours', null, 24)).toBe(false);
  });

  it('returns false when policy value is null', () => {
    expect(isLessStrictClient('max_hours', 48, null)).toBe(false);
  });

  it('returns false for an unknown field', () => {
    expect(isLessStrictClient('unknown_field', 10, 5)).toBe(false);
  });
});

describe('getMonitorSLAStatus', () => {
  // FRESHNESS requires timestamp_column in REQUIRED_CONFIG_FIELDS
  it('returns policy when config matches SLA', () => {
    const sla = { freshness: { maxHours: 24 } };
    const config = { max_hours: 24, timestamp_column: 'updated_at' };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('policy');
    expect(result.overriddenFields).toHaveLength(0);
    expect(result.violationFields).toHaveLength(0);
  });

  it('returns override when config is stricter', () => {
    const sla = { freshness: { maxHours: 24 } };
    const config = { max_hours: 12, timestamp_column: 'updated_at' };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('override');
    expect(result.overriddenFields).toContain('max_hours');
    expect(result.violationFields).toHaveLength(0);
  });

  it('returns violation when config is less strict', () => {
    const sla = { freshness: { maxHours: 24 } };
    const config = { max_hours: 48, timestamp_column: 'updated_at' };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('violation');
    expect(result.violationFields).toContain('max_hours');
  });

  it('returns needs_config when required fields are missing', () => {
    const sla = { freshness: { maxHours: 24 } };
    const config = { max_hours: 24 };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('needs_config');
  });

  it('returns none for null SLA with complete config', () => {
    const result = getMonitorSLAStatus('FRESHNESS', { max_hours: 24, timestamp_column: 'updated_at' }, null);
    expect(result.status).toBe('none');
  });

  it('returns needs_config for null SLA with missing required fields', () => {
    const result = getMonitorSLAStatus('FRESHNESS', { max_hours: 24 }, null);
    expect(result.status).toBe('needs_config');
  });

  it('returns needs_config for null config when monitor has required fields', () => {
    const sla = { freshness: { maxHours: 24 } };
    const result = getMonitorSLAStatus('FRESHNESS', null, sla);
    expect(result.status).toBe('needs_config');
  });

  it('returns needs_config for empty config when monitor has required fields', () => {
    const sla = { freshness: { maxHours: 24 } };
    const result = getMonitorSLAStatus('FRESHNESS', {}, sla);
    expect(result.status).toBe('needs_config');
  });

  it('returns none for null config when monitor has no required fields', () => {
    const sla = { schema: { strictness: 'strict' } };
    const result = getMonitorSLAStatus('SCHEMA_CHANGE', null, sla);
    expect(result.status).toBe('none');
  });

  it('returns none for empty config when monitor has no required fields', () => {
    const sla = { schema: { strictness: 'strict' } };
    const result = getMonitorSLAStatus('SCHEMA_CHANGE', {}, sla);
    expect(result.status).toBe('none');
  });

  it('returns none for unknown monitor type', () => {
    const sla = { freshness: { maxHours: 24 } };
    const result = getMonitorSLAStatus('UNKNOWN_TYPE', { max_hours: 24 }, sla);
    expect(result.status).toBe('none');
  });

  it('returns none when resolvedPolicy has status none', () => {
    const sla = { freshness: { maxHours: 24 }, status: 'none' };
    const result = getMonitorSLAStatus('FRESHNESS', { max_hours: 24, timestamp_column: 'updated_at' }, sla);
    expect(result.status).toBe('none');
  });

  it('violation status takes precedence over override', () => {
    const sla = { freshness: { maxHours: 24, warningHours: 12 } };
    // max_hours=48 is a violation, warning_hours=6 is an override (stricter)
    const config = { max_hours: 48, warning_hours: 6, timestamp_column: 'updated_at' };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('violation');
    expect(result.violationFields).toContain('max_hours');
    expect(result.overriddenFields).toContain('warning_hours');
  });

  it('returns policy for SCHEMA_CHANGE when strictness matches', () => {
    const sla = { schema: { strictness: 'strict' } };
    const config = { strictness: 'strict' };
    const result = getMonitorSLAStatus('SCHEMA_CHANGE', config, sla);
    expect(result.status).toBe('policy');
  });

  it('returns violation for SCHEMA_CHANGE when strictness is less strict', () => {
    const sla = { schema: { strictness: 'strict' } };
    const config = { strictness: 'ignore' };
    const result = getMonitorSLAStatus('SCHEMA_CHANGE', config, sla);
    expect(result.status).toBe('violation');
  });

  it('returns override for SCHEMA_CHANGE when strictness is stricter', () => {
    const sla = { schema: { strictness: 'warn' } };
    const config = { strictness: 'strict' };
    const result = getMonitorSLAStatus('SCHEMA_CHANGE', config, sla);
    expect(result.status).toBe('override');
  });

  it('skips fields not present in config', () => {
    // SLA has maxHours defined but config does not include max_hours — only timestamp_column
    const sla = { freshness: { maxHours: 24 } };
    const config = { timestamp_column: 'updated_at' };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('policy');
  });

  it('setting timestamp_column does not trigger override', () => {
    // Core scenario: monitor created with policy values, user adds required operational config
    const sla = { freshness: { maxHours: 24, warningHours: 12 } };
    const config = { max_hours: 24, warning_hours: 12, timestamp_column: 'updated_at' };
    const result = getMonitorSLAStatus('FRESHNESS', config, sla);
    expect(result.status).toBe('policy');
    expect(result.overriddenFields).toHaveLength(0);
  });

  it('OUTLIER_DETECTION: setting column does not trigger override', () => {
    const sla = { anomaly: { sensitivity: 0.95, lookbackDays: 14 } };
    const config = { column: 'revenue', anomaly_threshold: 3, lookback_days: 14 };
    const result = getMonitorSLAStatus('OUTLIER_DETECTION', config, sla);
    expect(result.status).toBe('policy');
  });
});
