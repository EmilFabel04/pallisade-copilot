'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { CardItem, ItemList, EmptyState } from './SharedDetailComponents';

export function ReportingDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  if (tabKey === 'dashboards') {
    return <DashboardsTab items={items} />;
  }
  if (tabKey === 'explores') {
    return <ExploresTab items={items} />;
  }
  return <ItemList items={items} />;
}

function DashboardsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No dashboards discovered" hint="Connect your BI tool to discover dashboards" />;
  }
  return (
    <div className="space-y-2">
      {items.map(item => {
        const viewCount = item.metadata?.view_count;
        const project = item.metadata?.project_name;
        return (
          <CardItem key={item.id} item={item}>
            <div className="flex items-center gap-3 mt-1">
              {project && (
                <span className="text-[11px] text-[var(--muted)]">
                  {project}
                </span>
              )}
              {viewCount !== undefined && viewCount > 0 && (
                <span className="text-[11px] text-[var(--muted)]">
                  {viewCount} view{viewCount !== 1 ? 's' : ''}
                </span>
              )}
            </div>
          </CardItem>
        );
      })}
    </div>
  );
}

function ExploresTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No explores / datasources discovered" hint="Explores are extracted from BI tool metadata" />;
  }
  return (
    <ItemList
      items={items}
      labelFn={(item) => {
        const connType = item.metadata?.connection_type;
        return connType ? String(connType) : item.originalType || 'datasource';
      }}
    />
  );
}
