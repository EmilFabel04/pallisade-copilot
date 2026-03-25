const SYNCABLE_FIELDS = [
  'ownerUser', 'ownerTeam', 'contactChannel', 'slaTier',
  'expectedFreshnessMinutes', 'expectedExtractionFrequencyMinutes',
  'alertPolicyJson', 'notes',
] as const;

export function computeGroupContractFromSLAs(
  slas: Record<string, unknown>[],
): Record<string, unknown> {
  if (slas.length === 0) return {};

  const result: Record<string, unknown> = {};

  for (const field of SYNCABLE_FIELDS) {
    const counts = new Map<string, number>();

    for (const sla of slas) {
      const val = sla[field];
      if (val == null) {
        continue;
      }
      const key = JSON.stringify(val);
      counts.set(key, (counts.get(key) || 0) + 1);
    }

    if (counts.size === 0) {
      result[field] = null;
      continue;
    }

    let maxCount = 0;
    let modeKey = '';
    for (const [key, count] of counts) {
      if (count > maxCount) {
        maxCount = count;
        modeKey = key;
      }
    }

    result[field] = JSON.parse(modeKey);
  }

  return result;
}

export function findDeviatingNodes(
  slas: Array<{ nodeId: string; values: Record<string, unknown> }>,
  groupContract: Record<string, unknown>,
): string[] {
  const deviating: string[] = [];

  for (const { nodeId, values } of slas) {
    for (const field of SYNCABLE_FIELDS) {
      const slaVal = values[field];
      const contractVal = groupContract[field];
      if (slaVal != null && contractVal != null && JSON.stringify(slaVal) !== JSON.stringify(contractVal)) {
        deviating.push(nodeId);
        break;
      }
    }
  }

  return deviating;
}
