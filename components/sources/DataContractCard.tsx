'use client';

import React from 'react';
import { FileText, Shield, AlertTriangle } from 'lucide-react';
import type { DataContractSummary } from './useDataContracts';

const SCOPE_LABELS: Record<string, string> = {
  schema: 'Schema',
  dbt_model_group: 'dbt Group',
  dashboard: 'Dashboard',
  exception: 'Exception',
};

const SCOPE_ICONS: Record<string, React.ReactNode> = {
  schema: <FileText className="w-3.5 h-3.5" />,
  dbt_model_group: <Shield className="w-3.5 h-3.5" />,
  dashboard: <FileText className="w-3.5 h-3.5" />,
  exception: <AlertTriangle className="w-3.5 h-3.5" />,
};

interface DataContractCardProps {
  contract: DataContractSummary;
  editable: boolean;
  onClick: (contract: DataContractSummary) => void;
}

export function DataContractCard({ contract, editable, onClick }: DataContractCardProps) {
  return (
    <button
      onClick={() => onClick(contract)}
      className="w-full text-left p-4 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] hover:border-[var(--accent)] transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[var(--muted)]">{SCOPE_ICONS[contract.scope]}</span>
          <span className="text-xs font-medium text-[var(--muted)] uppercase">
            {SCOPE_LABELS[contract.scope] || contract.scope}
          </span>
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
      <h4 className="text-sm font-medium text-[var(--foreground)] truncate">{contract.scopeRef}</h4>
      <div className="flex items-center gap-3 mt-2 text-[11px] text-[var(--muted)]">
        {contract.ownerTeam && <span>Team: {contract.ownerTeam}</span>}
        {contract.expectedFreshnessMinutes != null && <span>Freshness: {contract.expectedFreshnessMinutes}m</span>}
        {contract.exceptions.length > 0 && (
          <span>{contract.exceptions.length} exception{contract.exceptions.length > 1 ? 's' : ''}</span>
        )}
      </div>
      {!editable && (
        <p className="text-[10px] text-[var(--muted)] mt-2 italic">View only — enable data contracts in settings to edit</p>
      )}
    </button>
  );
}
