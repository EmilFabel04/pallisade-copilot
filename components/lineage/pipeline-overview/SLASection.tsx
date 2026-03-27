'use client';

import React from 'react';
import { ComplianceBadge, type ComplianceBadgeStatus } from '../ComplianceBadge';
import type { ComplianceStatus } from '@/lib/compliance/field-comparison';

interface SLAFieldDisplay {
  fieldName: string;
  label: string;
  slaValue: unknown;
  baselineValue: unknown | null;
  complianceStatus: ComplianceStatus | null;
}

interface SLASectionProps {
  fields: SLAFieldDisplay[];
  overallCompliance: ComplianceBadgeStatus;
  hasContract: boolean;
  contractScopeRef?: string;
  profileName?: string | null;
  isMultiSelect?: boolean;
  selectedCount?: number;
  onEditPipelineSLA?: () => void;
}

const COMPLIANCE_COLORS: Record<string, string> = {
  compliant: '#10B981',
  override: '#3B82F6',
  violation: '#EF4444',
  unknown: '#6B7280',
};

export function SLASection({
  fields,
  overallCompliance,
  hasContract,
  contractScopeRef,
  profileName,
  isMultiSelect,
  selectedCount,
  onEditPipelineSLA,
}: SLASectionProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-[var(--foreground)] uppercase tracking-wide">
          Pipeline SLA {isMultiSelect ? `(${selectedCount} nodes selected)` : ''}
        </h4>
        <ComplianceBadge status={overallCompliance} />
      </div>

      {profileName && (
        <div className="text-[11px] text-[var(--muted)]">
          Profile: <span className="text-[var(--foreground)] font-medium">{profileName}</span>
        </div>
      )}

      {hasContract && (
        <div className="p-2 rounded-md bg-blue-500/10 border border-blue-500/20 text-[11px] text-blue-400">
          This node has a data SLA{contractScopeRef ? ` (${contractScopeRef})` : ''}.
          Monitor changes will show as override or violation against the contract.
        </div>
      )}

      {fields.length > 0 ? (
        <div className="space-y-2">
          {fields.map(f => (
            <div key={f.fieldName} className="flex items-center justify-between">
              <span className="text-[11px] text-[var(--muted)]">{f.label}</span>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-[var(--foreground)]">
                  {f.slaValue != null ? String(f.slaValue) : '\u2014'}
                </span>
                {f.complianceStatus && f.complianceStatus !== 'unknown' && (
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: COMPLIANCE_COLORS[f.complianceStatus] || '#6B7280' }}
                    title={f.complianceStatus}
                  />
                )}
              </div>
            </div>
          ))}
          {onEditPipelineSLA && (
            <button
              onClick={onEditPipelineSLA}
              className="mt-1 text-[11px] text-slate-400 hover:text-slate-300 hover:underline flex items-center gap-1"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              Edit Expectations
            </button>
          )}
        </div>
      ) : !profileName ? (
        <div>
          <p className="text-[11px] text-[var(--muted)] italic">
            No pipeline SLA set.
          </p>
          {onEditPipelineSLA && (
            <button
              onClick={onEditPipelineSLA}
              className="mt-2 text-[11px] text-slate-400 hover:text-slate-300 hover:underline flex items-center gap-1"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Set Expectations
            </button>
          )}
        </div>
      ) : null}

      {!isMultiSelect && (
        <p className="text-[10px] text-[var(--muted)] italic mt-2">
          Shift+Click nodes to select multiple
        </p>
      )}
    </div>
  );
}
