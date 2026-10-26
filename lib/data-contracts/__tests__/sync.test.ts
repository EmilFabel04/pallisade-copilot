import { computeGroupContractFromSLAs, findDeviatingNodes } from '../sync';

describe('computeGroupContractFromSLAs', () => {
  it('returns mode value for numeric fields', () => {
    const slas = [
      { expectedFreshnessMinutes: 30 },
      { expectedFreshnessMinutes: 30 },
      { expectedFreshnessMinutes: 60 },
    ];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.expectedFreshnessMinutes).toBe(30);
  });

  it('returns mode value for string fields', () => {
    const slas = [
      { slaTier: 'T1' },
      { slaTier: 'T1' },
      { slaTier: 'T0' },
    ];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.slaTier).toBe('T1');
  });

  it('returns null for field where all values are null', () => {
    const slas = [
      { expectedFreshnessMinutes: null },
      { expectedFreshnessMinutes: null },
    ];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.expectedFreshnessMinutes).toBeNull();
  });

  it('handles single SLA', () => {
    const slas = [{ expectedFreshnessMinutes: 15, slaTier: 'T0' }];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.expectedFreshnessMinutes).toBe(15);
    expect(result.slaTier).toBe('T0');
  });

  it('handles empty array', () => {
    const result = computeGroupContractFromSLAs([]);
    expect(result).toEqual({});
  });

  it('ignores null values when computing mode', () => {
    const slas = [
      { expectedFreshnessMinutes: null },
      { expectedFreshnessMinutes: 30 },
      { expectedFreshnessMinutes: 30 },
    ];
    const result = computeGroupContractFromSLAs(slas);
    expect(result.expectedFreshnessMinutes).toBe(30);
  });
});

describe('findDeviatingNodes', () => {
  it('returns nodes that differ from group contract', () => {
    const slas = [
      { nodeId: 'a', values: { expectedFreshnessMinutes: 30 } },
      { nodeId: 'b', values: { expectedFreshnessMinutes: 60 } },
      { nodeId: 'c', values: { expectedFreshnessMinutes: 30 } },
    ];
    const groupContract = { expectedFreshnessMinutes: 30 };
    const result = findDeviatingNodes(slas, groupContract);
    expect(result).toEqual(['b']);
  });

  it('returns empty array when all match', () => {
    const slas = [
      { nodeId: 'a', values: { slaTier: 'T1' } },
      { nodeId: 'b', values: { slaTier: 'T1' } },
    ];
    const groupContract = { slaTier: 'T1' };
    expect(findDeviatingNodes(slas, groupContract)).toEqual([]);
  });

  it('ignores null SLA values', () => {
    const slas = [
      { nodeId: 'a', values: { expectedFreshnessMinutes: null } },
    ];
    const groupContract = { expectedFreshnessMinutes: 30 };
    expect(findDeviatingNodes(slas, groupContract)).toEqual([]);
  });
});
