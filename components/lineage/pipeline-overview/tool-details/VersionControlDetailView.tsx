'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { EmptyState } from './SharedDetailComponents';

export function VersionControlDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  if (tabKey === 'repos') {
    return <ReposTab items={items} />;
  }
  return <EmptyState message="Unknown tab" />;
}

function ReposTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        message="No repositories configured"
        hint="Connect GitHub repos to track version control activity"
      />
    );
  }

  // Group by org (container)
  const byOrg: Record<string, ToolDetailItem[]> = {};
  for (const item of items) {
    const org = item.container || 'Ungrouped';
    if (!byOrg[org]) byOrg[org] = [];
    byOrg[org].push(item);
  }

  return (
    <div className="space-y-3">
      {Object.entries(byOrg).map(([org, orgItems]) => (
        <div key={org}>
          <p className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-1.5">
            {org} ({orgItems.length})
          </p>
          <div className="space-y-1">
            {orgItems.map(item => {
              const detected = (item.metadata?.detectedTools as string[]) || [];
              const isPrivate = item.metadata?.private as boolean;
              return (
                <div key={item.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                  <span className="w-1.5 h-1.5 rounded-full bg-purple-400 shrink-0" />
                  <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">
                    {item.name.split('/').pop()}
                  </span>
                  {isPrivate && (
                    <span className="text-[9px] text-[var(--muted)] uppercase shrink-0">private</span>
                  )}
                  {detected.length > 0 && (
                    <span className="text-[9px] text-purple-400 shrink-0">
                      {detected.join(', ')}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
