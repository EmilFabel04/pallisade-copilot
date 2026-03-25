export type ComplianceStatus = 'compliant' | 'override' | 'violation' | 'unknown';

// Fields where lower numeric value = stricter
const LOWER_IS_STRICTER = new Set([
  'expectedFreshnessMinutes',
  'expectedExtractionFrequencyMinutes',
  'maxQueryCostUsd',
  'maxSyncDelayMinutes',
  'retryBackoffMinutes',
  'refreshSlaMinutes',
  'expectedRunCadenceMinutes',
]);

// Fields where higher numeric value = stricter
const HIGHER_IS_STRICTER = new Set([
  'maxRetries',
  'retentionDays',
]);

// Boolean fields where true = stricter
const TRUE_IS_STRICTER = new Set([
  'requireDryRun',
  'oncallRequired',
  'encryptionRequired',
  'readOnlyEnforced',
  'freshnessTestsRequired',
  'ownerAckRequired',
]);

// Ordered enums: first = strictest
const ORDERED_ENUMS: Record<string, string[]> = {
  schemaChangePolicy: ['fail', 'warn', 'ignore'],
  connectorPriority: ['critical', 'high', 'normal', 'low'],
};

// Set fields where superset = stricter
const SET_FIELDS = new Set(['requiredTests']);

export function compareFieldToBaseline(
  fieldName: string,
  slaValue: unknown,
  baselineValue: unknown,
): ComplianceStatus {
  if (slaValue == null || baselineValue == null) return 'unknown';

  // Set comparison
  if (SET_FIELDS.has(fieldName)) {
    const slaSet = new Set(slaValue as string[]);
    const baseSet = new Set(baselineValue as string[]);
    const slaHasAll = [...baseSet].every(v => slaSet.has(v));
    const baseHasAll = [...slaSet].every(v => baseSet.has(v));
    if (slaHasAll && baseHasAll) return 'compliant';
    if (slaHasAll) return 'override';
    return 'violation';
  }

  // Ordered enum comparison
  if (fieldName in ORDERED_ENUMS) {
    const order = ORDERED_ENUMS[fieldName];
    const slaIdx = order.indexOf(String(slaValue));
    const baseIdx = order.indexOf(String(baselineValue));
    if (slaIdx === -1 || baseIdx === -1) return 'unknown';
    if (slaIdx === baseIdx) return 'compliant';
    return slaIdx < baseIdx ? 'override' : 'violation';
  }

  // Boolean comparison
  if (TRUE_IS_STRICTER.has(fieldName)) {
    if (slaValue === baselineValue) return 'compliant';
    return slaValue === true ? 'override' : 'violation';
  }

  // Numeric comparison
  const slaNum = Number(slaValue);
  const baseNum = Number(baselineValue);
  if (Number.isNaN(slaNum) || Number.isNaN(baseNum)) return 'unknown';

  if (slaNum === baseNum) return 'compliant';

  if (LOWER_IS_STRICTER.has(fieldName)) {
    return slaNum < baseNum ? 'override' : 'violation';
  }

  if (HIGHER_IS_STRICTER.has(fieldName)) {
    return slaNum > baseNum ? 'override' : 'violation';
  }

  return 'unknown';
}
