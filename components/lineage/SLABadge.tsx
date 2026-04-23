'use client';

import React from 'react';
import type { SLAStatus } from '@/types/sla';

interface SLABadgeProps {
  status: SLAStatus;
  profileName?: string | null;
  source?: string;
  onClick?: (e: React.MouseEvent) => void;
}

export function SLABadge({ status, profileName, onClick }: SLABadgeProps) {
  // Nodes are either assigned a policy profile or not — no badge if unassigned
  if (status === 'none') return null;

  // Short "SLA" tag on the node, full profile name in tooltip
  return (
    <div
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[9px] font-semibold tracking-wide uppercase whitespace-nowrap${onClick ? ' cursor-pointer hover:brightness-125' : ''}`}
      style={{
        backgroundColor: 'var(--subtle-bg)',
        color: 'var(--muted)',
        border: '1px solid var(--subtle-border)',
        backdropFilter: 'blur(4px)',
      }}
      title={profileName || 'SLA'}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(e); } : undefined}
    >
      SLA
    </div>
  );
}
