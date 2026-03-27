'use client';

import React from 'react';
import type { DataSLASummary } from './useDataSLAs';

const TIER_STYLES: Record<string, { color: string; bg: string }> = {
  T0: { color: 'text-red-400', bg: 'bg-red-500/15' },
  T1: { color: 'text-amber-400', bg: 'bg-amber-500/15' },
  T2: { color: 'text-blue-400', bg: 'bg-blue-500/15' },
  T3: { color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
};

const SCOPE_COLORS: Record<string, string> = {
  schema: '#8B5CF6',
  dbt_model_group: '#F59E0B',
  dashboard: '#3B82F6',
  exception: '#F97316',
};

const SCOPE_LABELS: Record<string, string> = {
  schema: 'Schema',
  dbt_model_group: 'dbt Model',
  dashboard: 'Dashboard',
  exception: 'Exception',
};

interface DataSLACardProps {
  contract: DataSLASummary;
  editable: boolean;
  onClick: (contract: DataSLASummary) => void;
}

export function DataSLACard({ contract, editable, onClick }: DataSLACardProps) {
  const displayName = contract.name || contract.scopeRef;
  const nodeCount = contract.nodeFqns?.length || 0;
  const tierStyle = TIER_STYLES[(contract.slaTier || '').toUpperCase()] || TIER_STYLES.T2;
  const scopeColor = SCOPE_COLORS[contract.scope] || '#6B7280';
  const scopeLabel = SCOPE_LABELS[contract.scope] || contract.scope;

  return (
    <button
      onClick={() => onClick(contract)}
      className="w-full text-left p-4 rounded-xl border border-[var(--subtle-border)] bg-[var(--surface-raised)] hover:border-[var(--accent)]/30 hover:shadow-md hover:shadow-black/5 transition-all group"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-medium text-[var(--text)] truncate">
          {displayName}
        </span>
        {contract.slaTier && (
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${tierStyle.color} ${tierStyle.bg}`}>
            {contract.slaTier}
          </span>
        )}
      </div>

      {/* Metadata row */}
      <div className="flex items-center gap-2 mb-3">
        <span
          className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{ color: scopeColor, background: `${scopeColor}14`, border: `1px solid ${scopeColor}20` }}
        >
          {scopeLabel}
        </span>
        {contract.autoSynced && (
          <span className="text-[10px] text-blue-400">Auto-synced</span>
        )}
        {contract.isException && (
          <span className="text-[10px] text-amber-400">Exception</span>
        )}
        {nodeCount > 0 && (
          <span className="text-[10px] text-[var(--muted)]">{nodeCount} node{nodeCount !== 1 ? 's' : ''}</span>
        )}
      </div>

      {/* Key expectations */}
      <div className="space-y-1">
        {contract.freshnessConfig && (contract.freshnessConfig as any).maxHours != null && (
          <p className="text-[11px] text-[var(--muted)]">Freshness: {(contract.freshnessConfig as any).maxHours}h</p>
        )}
        {contract.schemaConfig && (contract.schemaConfig as any).strictness && (
          <p className="text-[11px] text-[var(--muted)]">Schema: {(contract.schemaConfig as any).strictness}</p>
        )}
        {!contract.freshnessConfig && !contract.schemaConfig && (
          <p className="text-[11px] text-[var(--muted)] italic">Profile assigned, no custom expectations</p>
        )}
      </div>
    </button>
  );
}
