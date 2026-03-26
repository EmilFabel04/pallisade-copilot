'use client';

import React from 'react';

export type ComplianceBadgeStatus = 'compliant' | 'override' | 'violation' | 'missing_sla' | 'none';

const BADGE_CONFIG: Record<ComplianceBadgeStatus, { label: string; color: string; bg: string } | null> = {
  compliant: { label: 'Compliant', color: '#10B981', bg: 'rgba(16, 185, 129, 0.15)' },
  override: { label: 'Override', color: '#3B82F6', bg: 'rgba(59, 130, 246, 0.15)' },
  violation: { label: 'Violation', color: '#EF4444', bg: 'rgba(239, 68, 68, 0.15)' },
  missing_sla: { label: 'Missing SLA', color: '#F59E0B', bg: 'rgba(245, 158, 11, 0.15)' },
  none: null,
};

interface ComplianceBadgeProps {
  status: ComplianceBadgeStatus;
}

export function ComplianceBadge({ status }: ComplianceBadgeProps) {
  const config = BADGE_CONFIG[status];
  if (!config) return null;

  return (
    <div
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[9px] font-semibold tracking-wide uppercase whitespace-nowrap"
      style={{
        backgroundColor: config.bg,
        color: config.color,
        border: `1px solid ${config.color}33`,
      }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: config.color }}
      />
      {config.label}
    </div>
  );
}
