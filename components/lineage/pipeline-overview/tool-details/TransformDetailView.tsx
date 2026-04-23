'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { HEALTH_COLORS } from '../types';
import { ItemList, GroupedItemList, EmptyState, CardItem } from './SharedDetailComponents';

const ZONE_LABELS: Record<string, string> = {
  raw: 'Raw / Sources',
  staging: 'Staging',
  intermediate: 'Intermediate',
  mart: 'Marts',
  analytics: 'Analytics',
  unknown: 'Other',
};

const ZONE_ORDER: Record<string, number> = {
  raw: 0, staging: 1, intermediate: 2, mart: 3, analytics: 4, unknown: 5,
};

export function TransformDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  if (tabKey === 'models') {
    return <ModelsTab items={items} />;
  }
  if (tabKey === 'tests') {
    return <TestsTab items={items} />;
  }
  if (tabKey === 'exposures') {
    return <ExposuresTab items={items} />;
  }
  return <ItemList items={items} />;
}

function ModelsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No models discovered" hint="Run lineage extraction with dbt manifest" />;
  }

  // Group by zone
  const groups: Record<string, ToolDetailItem[]> = {};
  for (const item of items) {
    const zone = item.zone || 'unknown';
    if (!groups[zone]) groups[zone] = [];
    groups[zone].push(item);
  }

  const sortedZones = Object.keys(groups).sort(
    (a, b) => (ZONE_ORDER[a] ?? 99) - (ZONE_ORDER[b] ?? 99)
  );

  return (
    <div className="space-y-3">
      {/* Zone summary */}
      <div className="flex flex-wrap gap-2">
        {sortedZones.map(zone => (
          <span
            key={zone}
            className="px-2 py-0.5 rounded text-[10px] font-medium bg-[var(--overlay-bg)] text-[var(--text)]"
          >
            {ZONE_LABELS[zone] || zone}: {groups[zone].length}
          </span>
        ))}
      </div>

      {/* Models list grouped by zone */}
      {sortedZones.map(zone => (
        <div key={zone}>
          <p className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-1.5">
            {ZONE_LABELS[zone] || zone} ({groups[zone].length})
          </p>
          <div className="space-y-1">
            {groups[zone].slice(0, 30).map(item => {
              const materialized = item.metadata?.materialized || '';
              return (
                <div key={item.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ backgroundColor: HEALTH_COLORS[item.healthStatus || 'unknown'] || '#6B7280' }}
                  />
                  <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1" title={item.fqn}>
                    {item.name}
                  </span>
                  {materialized && (
                    <span className="text-[9px] text-[var(--muted)] uppercase shrink-0">{materialized}</span>
                  )}
                </div>
              );
            })}
            {groups[zone].length > 30 && (
              <p className="text-[11px] text-[var(--muted)] text-center">
                +{groups[zone].length - 30} more
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function TestsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No tests discovered" hint="Tests appear from dbt test definitions" />;
  }
  return (
    <div className="space-y-2">
      {/* Summary */}
      <div className="flex gap-3 mb-2">
        <span className="text-[12px] text-emerald-400">
          {items.filter(i => i.healthStatus === 'healthy').length} passing
        </span>
        <span className="text-[12px] text-red-400">
          {items.filter(i => i.healthStatus === 'failing').length} failing
        </span>
      </div>
      <ItemList
        items={items}
        labelFn={(item) => item.healthStatus === 'failing' ? 'FAIL' : item.healthStatus === 'healthy' ? 'PASS' : 'N/A'}
      />
    </div>
  );
}

function ExposuresTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No exposures defined" hint="Exposures track downstream consumers of dbt models" />;
  }
  return <ItemList items={items} labelFn={(item) => item.originalType || 'exposure'} />;
}
