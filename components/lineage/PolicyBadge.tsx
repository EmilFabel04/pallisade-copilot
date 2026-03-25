'use client';

import React from 'react';
import type { SLAStatus } from '@/types/sla';

interface PolicyBadgeProps {
  status: SLAStatus;
  profileName?: string | null;
  source?: string;
}

export function PolicyBadge({ status, profileName }: PolicyBadgeProps) {
  // Nodes are either assigned a policy profile or not — no badge if unassigned
  if (status === 'none') return null;

  // Always show the profile name (e.g. "Relaxed", "Critical SLA", "Standard")
  // "Override" only applies at the monitor level, not the node level.
  const label = profileName || 'Policy';

  return (
    <div
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[9px] font-semibold tracking-wide uppercase whitespace-nowrap"
      style={{
        backgroundColor: 'var(--subtle-bg)',
        color: 'var(--muted)',
        border: '1px solid var(--subtle-border)',
        backdropFilter: 'blur(4px)',
      }}
      title={label}
    >
      {label}
    </div>
  );
}
