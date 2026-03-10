'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { HEALTH_COLORS } from '../types';
import { ItemList, EmptyState, CardItem } from './SharedDetailComponents';

export function InfraDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  if (tabKey === 'services') {
    return <ServicesTab items={items} />;
  }
  if (tabKey === 'hosts') {
    return <HostsTab items={items} />;
  }
  return <ItemList items={items} />;
}

function ServicesTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No services detected" hint="Service discovery requires running_services metadata" />;
  }

  // Group by host (container)
  const byHost: Record<string, ToolDetailItem[]> = {};
  for (const item of items) {
    const host = item.container || 'Ungrouped';
    if (!byHost[host]) byHost[host] = [];
    byHost[host].push(item);
  }

  return (
    <div className="space-y-3">
      {Object.entries(byHost).map(([host, hostItems]) => (
        <div key={host}>
          <p className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-1.5">
            {host} ({hostItems.length})
          </p>
          <div className="space-y-1">
            {hostItems.map(item => (
              <div key={item.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">
                  {item.name}
                </span>
                <span className="text-[9px] text-[var(--muted)] uppercase shrink-0">
                  {item.originalType === 'hosted_tool' ? 'tool' : 'service'}
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function HostsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No hosts discovered" hint="Connect your infrastructure to discover hosts" />;
  }
  return (
    <div className="space-y-2">
      {items.map(item => {
        const runningServices = (item.metadata?.running_services as string[]) || [];
        const hostedTools = (item.metadata?.hosted_tools as string[]) || [];
        return (
          <CardItem key={item.id} item={item}>
            <div className="space-y-1 mt-1">
              {runningServices.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Services</span>
                  <span className="text-[11px] text-[var(--text)]">{runningServices.length} running</span>
                </div>
              )}
              {hostedTools.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Tools</span>
                  <span className="text-[11px] text-[var(--text)]">{hostedTools.join(', ')}</span>
                </div>
              )}
            </div>
          </CardItem>
        );
      })}
    </div>
  );
}
