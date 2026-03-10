'use client';

import React, { useState } from 'react';
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
        const hasAnyHealth = healthBreakdown && Object.values(healthBreakdown).some(v => v > 0);
        return (
          <CardItem key={item.id} item={item}>
            <div className="flex items-center gap-3 mt-1">
              <span className="text-[11px] text-[var(--muted)]">
                {item.itemCount ?? 0} table{(item.itemCount ?? 0) !== 1 ? 's' : ''}
              </span>
              {healthBreakdown && hasAnyHealth && (
                <div className="flex gap-2">
                  {healthBreakdown.healthy > 0 && (
                    <span className="text-[10px] text-emerald-400">{healthBreakdown.healthy} ok</span>
                  )}
                  {healthBreakdown.failing > 0 && (
                    <span className="text-[10px] text-red-400">{healthBreakdown.failing} fail</span>
                  )}
                </div>
              )}
              {healthBreakdown && !hasAnyHealth && (
                <span className="text-[10px] text-[var(--muted)]">No health issues</span>
              )}
            </div>
          </CardItem>
        );
      })}
    </div>
  );
}

const TABLES_PAGE_SIZE = 30;

function TablesTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No tables discovered" hint="Tables are extracted from warehouse metadata" />;
  }

  // Group by schema/container
  const groups: Record<string, ToolDetailItem[]> = {};
  for (const item of items) {
    const schema = item.container || 'Ungrouped';
    if (!groups[schema]) groups[schema] = [];
    groups[schema].push(item);
  }

  return (
    <div className="space-y-3">
      {Object.entries(groups).map(([schema, schemaItems]) => (
        <SchemaGroup key={schema} schema={schema} items={schemaItems} />
      ))}
    </div>
  );
}

function SchemaGroup({ schema, items }: { schema: string; items: ToolDetailItem[] }) {
  const [visibleCount, setVisibleCount] = useState(TABLES_PAGE_SIZE);
  const hasMore = items.length > visibleCount;
  const remaining = items.length - visibleCount;

  return (
    <div>
      <p className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-1.5">
        {schema} ({items.length})
      </p>
      <div className="space-y-1">
        {items.slice(0, visibleCount).map(item => (
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
        {hasMore && (
          <button
            onClick={() => setVisibleCount(c => c + TABLES_PAGE_SIZE)}
            className="w-full text-[11px] text-[var(--muted)] hover:text-[var(--text)] text-center py-1 transition-colors"
          >
            Show {Math.min(remaining, TABLES_PAGE_SIZE)} more ({remaining} remaining)
          </button>
        )}
      </div>
    </div>
  );
}
