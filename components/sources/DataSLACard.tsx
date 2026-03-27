'use client';

import React from 'react';
import { FileText, Shield } from 'lucide-react';
import type { DataSLASummary } from './useDataSLAs';

interface DataSLACardProps {
  contract: DataSLASummary;
  editable: boolean;
  onClick: (contract: DataSLASummary) => void;
}

export function DataSLACard({ contract, editable, onClick }: DataSLACardProps) {
  const nodeCount = contract.nodeFqns?.length || 0;
  const displayName = contract.name || contract.scopeRef;

  return (
    <button
      onClick={() => onClick(contract)}
      className="w-full text-left p-4 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] hover:border-[var(--accent)] transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Shield className="w-3.5 h-3.5 text-[var(--muted)]" />
          {contract.autoSynced && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 font-medium">
              Auto-synced
            </span>
          )}
          {contract.isException && (
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium">
              Exception
            </span>
          )}
        </div>
        {contract.slaTier && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--muted)] font-medium">
            {contract.slaTier}
          </span>
        )}
      </div>
      <h4 className="text-sm font-medium text-[var(--foreground)] truncate">{displayName}</h4>
      <div className="flex items-center gap-3 mt-2 text-[11px] text-[var(--muted)]">
        {nodeCount > 0 && <span>{nodeCount} node{nodeCount !== 1 ? 's' : ''}</span>}
        {contract.freshnessConfig && (contract.freshnessConfig as any).maxHours != null && (
          <span>Freshness: {(contract.freshnessConfig as any).maxHours}h</span>
        )}
      </div>
    </button>
  );
}
