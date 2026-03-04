'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { HEALTH_COLORS } from '../types';
import { CardItem, ItemList, EmptyState, HealthRow } from './SharedDetailComponents';

export function WarehouseDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  if (tabKey === 'datasets') {
    return <DatasetsTab items={items} />;
  }
  if (tabKey === 'tables') {
    return <TablesTab items={items} />;
  }
  return <ItemList items={items} />;
}

function DatasetsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No datasets / schemas discovered" hint="Run lineage extraction to discover warehouse schemas" />;
  }
  return (
    <div className="space-y-2">
      {items.map(item => {
        const healthBreakdown = item.metadata?.healthBreakdown as Record<string, number> | undefined;
        return (
          <CardItem key={item.id} item={item}>
            <div className="flex items-center gap-3 mt-1">
              <span className="text-[11px] text-[var(--muted)]">
                {item.itemCount ?? 0} table{(item.itemCount ?? 0) !== 1 ? 's' : ''}
              </span>
              {healthBreakdown && (
                <div className="flex gap-2">
                  {healthBreakdown.healthy > 0 && (
                    <span className="text-[10px] text-emerald-400">{healthBreakdown.healthy} ok</span>
                  )}
                  {healthBreakdown.failing > 0 && (
                    <span className="text-[10px] text-red-400">{healthBreakdown.failing} fail</span>
                  )}
                </div>
              )}
            </div>
          </CardItem>
        );
      })}
    </div>
  );
}

function TablesTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No tables discovered" hint="Tables are extracted from warehouse metadata" />;
  }

  // Group by schema/container
  const groups: Record<string, ToolDetailItem[]> = {};
  for (const item of items) {
    const schema = item.container || 'default';
    if (!groups[schema]) groups[schema] = [];
    groups[schema].push(item);
  }

  return (
    <div className="space-y-3">
      {Object.entries(groups).map(([schema, schemaItems]) => (
        <div key={schema}>
          <p className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-1.5">
            {schema} ({schemaItems.length})
          </p>
          <div className="space-y-1">
            {schemaItems.slice(0, 30).map(item => (
              <div key={item.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ backgroundColor: HEALTH_COLORS[item.healthStatus || 'unknown'] || '#6B7280' }}
                />
                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1" title={item.fqn}>
                  {item.name}
                </span>
                <span className="text-[9px] text-[var(--muted)] uppercase shrink-0">
                  {item.originalType || item.canonicalType}
                </span>
              </div>
            ))}
            {schemaItems.length > 30 && (
              <p className="text-[11px] text-[var(--muted)] text-center">
                +{schemaItems.length - 30} more
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
