'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { HEALTH_COLORS } from '../types';
import { ItemList, EmptyState } from './SharedDetailComponents';

export function QualityDetailView({
  items,
  tabKey,
}: {
  items: ToolDetailItem[];
  tabKey: string;
}) {
  if (tabKey === 'monitors') {
    return <MonitorsTab items={items} />;
  }
  if (tabKey === 'status') {
    return <StatusTab items={items} />;
  }
  return <ItemList items={items} />;
}

function MonitorsTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No monitors discovered" hint="Connect Elementary to discover test monitors" />;
  }

  return (
    <div className="space-y-1.5">
      {items.map(item => {
        const totalTests = item.metadata?.total_tests ?? 0;
        const failedTests = item.metadata?.failed_tests ?? 0;
        const passingTests = totalTests - failedTests;
        return (
          <div key={item.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ backgroundColor: failedTests > 0 ? '#EF4444' : '#10B981' }}
            />
            <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1" title={item.fqn}>
              {item.name}
            </span>
            <div className="flex gap-2 shrink-0">
              {passingTests > 0 && (
                <span className="text-[10px] text-emerald-400">{passingTests} pass</span>
              )}
              {failedTests > 0 && (
                <span className="text-[10px] text-red-400">{failedTests} fail</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatusTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return <EmptyState message="No status data" />;
  }

  const summary = items[0];
  const passing = summary?.metadata?.passing ?? 0;
  const failing = summary?.metadata?.failing ?? 0;
  const total = summary?.metadata?.total ?? 0;

  return (
    <div className="space-y-4">
      {/* Pass/Fail summary */}
      <div className="grid grid-cols-3 gap-3">
        <div className="text-center">
          <p className="text-2xl font-semibold text-[var(--text)]">{total}</p>
          <p className="text-[11px] text-[var(--muted)]">Total</p>
        </div>
        <div className="text-center">
          <p className="text-2xl font-semibold text-emerald-400">{passing}</p>
          <p className="text-[11px] text-[var(--muted)]">Passing</p>
        </div>
        <div className="text-center">
          <p className="text-2xl font-semibold text-red-400">{failing}</p>
          <p className="text-[11px] text-[var(--muted)]">Failing</p>
        </div>
      </div>

      {/* Pass rate bar */}
      {total > 0 && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] text-[var(--muted)]">Pass Rate</span>
            <span className="text-[12px] font-semibold text-[var(--text)]">
              {Math.round((passing / total) * 100)}%
            </span>
          </div>
          <div className="h-2 rounded-full bg-[var(--overlay-faint)] overflow-hidden">
            <div
              className="h-full rounded-full bg-emerald-400"
              style={{ width: `${(passing / total) * 100}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
