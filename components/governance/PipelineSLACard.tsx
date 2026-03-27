'use client';

import React from 'react';

export interface PipelineSLAItem {
  assignmentId: string;
  nodeFqn: string;
  profileId: string;
  profileName: string | null;
  nodeDomain: string | null;
  overrides: Record<string, any> | null;
  slaTier: string | null;
  updatedAt: string | null;
  // Enriched client-side
  nodeName?: string;
  platform?: string;
  layer?: string;
}

const DOMAIN_COLORS: Record<string, string> = {
  ingestion: '#10B981',
  orchestration: '#F97316',
  transform: '#F59E0B',
  bi: '#3B82F6',
  warehouse: '#8B5CF6',
};

const TIER_STYLES: Record<string, { color: string; bg: string }> = {
  T0: { color: 'text-red-400', bg: 'bg-red-500/15' },
  T1: { color: 'text-amber-400', bg: 'bg-amber-500/15' },
  T2: { color: 'text-blue-400', bg: 'bg-blue-500/15' },
  T3: { color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
};

function getKeyExpectations(overrides: Record<string, any> | null): string[] {
  if (!overrides) return [];
  const results: string[] = [];
  for (const [section, config] of Object.entries(overrides)) {
    if (typeof config !== 'object' || !config) continue;
    for (const [key, value] of Object.entries(config as Record<string, unknown>)) {
      if (key === 'enabled' || value == null) continue;
      const label = key
        .replace(/([A-Z])/g, ' $1')
        .replace(/^./, s => s.toUpperCase())
        .replace(/Minutes$/, ' (min)')
        .replace(/Hours$/, ' (hrs)');
      results.push(`${label}: ${value}`);
      if (results.length >= 3) return results;
    }
  }
  return results;
}

interface PipelineSLACardProps {
  item: PipelineSLAItem;
  onClick: (item: PipelineSLAItem) => void;
}

export function PipelineSLACard({ item, onClick }: PipelineSLACardProps) {
  const domainColor = DOMAIN_COLORS[item.nodeDomain || ''] || '#6B7280';
  const domainLabel = item.nodeDomain
    ? item.nodeDomain.charAt(0).toUpperCase() + item.nodeDomain.slice(1)
    : 'Unknown';
  const tierStyle = TIER_STYLES[(item.slaTier || '').toUpperCase()] || TIER_STYLES.T2;
  const expectations = getKeyExpectations(item.overrides);

  return (
    <button
      onClick={() => onClick(item)}
      className="w-full text-left p-4 rounded-xl border border-[var(--subtle-border)] bg-[var(--surface-raised)] hover:border-[var(--accent)]/30 hover:shadow-md hover:shadow-black/5 transition-all group"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-medium text-[var(--text)] truncate">
          {item.nodeName || item.nodeFqn.split('.').pop() || item.nodeFqn}
        </span>
        {item.slaTier && (
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${tierStyle.color} ${tierStyle.bg}`}>
            {item.slaTier.toUpperCase()}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 mb-3">
        <span
          className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{ color: domainColor, background: `${domainColor}14`, border: `1px solid ${domainColor}20` }}
        >
          {domainLabel}
        </span>
        {item.platform && (
          <span className="text-[10px] text-[var(--muted)] capitalize">{item.platform}</span>
        )}
        {item.profileName && (
          <span className="text-[10px] text-[var(--muted)]">{item.profileName}</span>
        )}
      </div>

      {expectations.length > 0 ? (
        <div className="space-y-1">
          {expectations.map((exp, i) => (
            <p key={i} className="text-[11px] text-[var(--muted)]">{exp}</p>
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-[var(--muted)] italic">Profile assigned, no custom expectations</p>
      )}
    </button>
  );
}
