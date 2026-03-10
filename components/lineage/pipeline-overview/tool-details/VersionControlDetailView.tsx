'use client';

import React from 'react';
import type { ToolDetailItem } from '../types';
import { EmptyState, formatRelativeTime } from './SharedDetailComponents';

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
  if (tabKey === 'activity') {
    return <ActivityTab items={items} />;
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
    const org = item.container || 'Other';
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
            {orgItems.map(item => (
              <div key={item.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                <span className="w-1.5 h-1.5 rounded-full bg-purple-400 shrink-0" />
                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">
                  {item.name}
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ActivityTab({ items }: { items: ToolDetailItem[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        message="No activity data"
        hint="VCS activity is tracked from integration events"
      />
    );
  }

  return (
    <div className="space-y-3">
      {items.map(item => {
        const m = item.metadata || {};
        const hasSynced = !!m.lastSyncAt || !!m.lastEventAt;
        const isConnected = m.connectionStatus === 'CONNECTED' || m.connectionStatus === 'HEALTHY';
        const statusColor = hasSynced ? '#10B981' : isConnected ? '#3B82F6' : '#6B7280';

        return (
          <div key={item.id} className="rounded-lg bg-[var(--overlay-bg)] p-3 space-y-2">
            {/* Header */}
            <div className="flex items-center gap-2">
              <div
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: statusColor }}
              />
              <span className="text-[12px] text-[var(--text)] font-medium truncate">
                {item.name}
              </span>
              {isConnected && !hasSynced && (
                <span className="text-[10px] text-blue-400 font-medium ml-auto shrink-0">Connected</span>
              )}
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-2">
              {m.repoCount != null && m.repoCount > 0 && (
                <StatCell label="Repos" value={m.repoCount} />
              )}
              {m.prs7d != null && m.prs7d > 0 && (
                <StatCell label="PRs (7d)" value={m.prs7d} />
              )}
              {m.mergedPrs7d != null && m.mergedPrs7d > 0 && (
                <StatCell label="Merged (7d)" value={m.mergedPrs7d} />
              )}
              {m.issues7d != null && m.issues7d > 0 && (
                <StatCell label="Issues (7d)" value={m.issues7d} />
              )}
            </div>

            {/* Connection status + Timestamps */}
            <div className="space-y-1">
              {m.connectionStatus && (
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Status</span>
                  <span className={`text-[11px] font-medium ${
                    isConnected ? 'text-emerald-500' : 'text-[var(--muted)]'
                  }`}>
                    {m.connectionStatus.toLowerCase()}
                  </span>
                </div>
              )}
              {m.platform && (
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Platform</span>
                  <span className="text-[11px] text-[var(--text)] capitalize">{m.platform}</span>
                </div>
              )}
              {m.org && (
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Organization</span>
                  <span className="text-[11px] text-[var(--text)] font-mono">{m.org}</span>
                </div>
              )}
              {m.lastEventAt && (
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Last Event</span>
                  <span className="text-[11px] text-[var(--text)] font-mono">
                    {formatRelativeTime(m.lastEventAt)}
                  </span>
                </div>
              )}
              {m.lastSyncAt && (
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Last Sync</span>
                  <span className="text-[11px] text-[var(--text)] font-mono">
                    {formatRelativeTime(m.lastSyncAt)}
                  </span>
                </div>
              )}
              {m.webhookStatus && m.webhookStatus !== 'unknown' && (
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--muted)] uppercase">Webhook</span>
                  <span className={`text-[11px] font-medium ${
                    m.webhookStatus === 'ok' ? 'text-emerald-500' :
                    m.webhookStatus === 'failing' ? 'text-red-500' :
                    'text-[var(--muted)]'
                  }`}>
                    {m.webhookStatus}
                  </span>
                </div>
              )}
              {!hasSynced && !isConnected && (
                <p className="text-[11px] text-[var(--muted)] italic">Not yet synced</p>
              )}
              {m.lastErrorMessage && (
                <div className="mt-1 px-2 py-1 rounded bg-red-500/10 border border-red-500/20">
                  <p className="text-[10px] text-red-400 truncate">{m.lastErrorMessage}</p>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatCell({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <p className="text-[10px] text-[var(--muted)] uppercase">{label}</p>
      <p className="text-[14px] font-semibold text-[var(--text)] tabular-nums">{value}</p>
    </div>
  );
}
