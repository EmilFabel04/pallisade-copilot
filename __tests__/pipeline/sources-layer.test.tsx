import { TOOLS, LAYER_LABELS, LAYER_COLORS, PipelineLayer } from '@/components/pipeline/types';

describe('SOURCE pipeline layer', () => {
  it('exposes SOURCE in TOOLS with custom_source as the only live tile', () => {
    expect(TOOLS.SOURCE).toBeDefined();
    const ids = TOOLS.SOURCE.map(t => t.id).sort();
    expect(ids).toEqual(['custom_source', 'hubspot', 'salesforce', 'shopify']);

    const live = TOOLS.SOURCE.filter(t => (t.status ?? 'live') === 'live').map(t => t.id);
    expect(live).toEqual(['custom_source']);

    const comingSoon = TOOLS.SOURCE.filter(t => t.status === 'coming_soon').map(t => t.id).sort();
    expect(comingSoon).toEqual(['hubspot', 'salesforce', 'shopify']);
  });

  it('labels the SOURCE layer "Sources"', () => {
    expect(LAYER_LABELS.SOURCE).toBe('Sources');
  });

  it('assigns SOURCE its own color (slate)', () => {
    expect(LAYER_COLORS.SOURCE).toBe('#64748B');
  });

  it('includes SOURCE as a valid PipelineLayer key', () => {
    const sentinel: Record<PipelineLayer, true> = {
      SOURCE: true, INGESTION: true, TRANSFORMATION: true, WAREHOUSE: true,
      REPORTING: true, STORAGE: true, VERSION_CONTROL: true,
      ORCHESTRATION: true, INFRASTRUCTURE: true, NOTIFICATIONS: true, UNCATEGORIZED: true,
    };
    expect(sentinel.SOURCE).toBe(true);
  });
});
