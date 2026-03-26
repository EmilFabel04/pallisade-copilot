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
  isMultiSelect?: boolean;
  selectedCount?: number;
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
  isMultiSelect,
  selectedCount,
}: SLASectionProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-[var(--foreground)] uppercase tracking-wide">
          SLA {isMultiSelect ? `(${selectedCount} nodes selected)` : ''}
        </h4>
        <ComplianceBadge status={overallCompliance} />
      </div>

      {hasContract && (
        <div className="p-2 rounded-md bg-blue-500/10 border border-blue-500/20 text-[11px] text-blue-400">
          This node has a data contract{contractScopeRef ? ` (${contractScopeRef})` : ''}.
          SLA changes will show as override or violation against the contract.
        </div>
      )}

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
      </div>

      {!isMultiSelect && (
        <p className="text-[10px] text-[var(--muted)] italic mt-2">
          Shift+Click nodes to select multiple
        </p>
      )}
    </div>
  );
}
