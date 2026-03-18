'use client';

import React from 'react';
import type { PolicyStatus } from '@/types/policy';

interface PolicyBadgeProps {
  status: PolicyStatus;
  profileName?: string | null;
  source?: string;
}

const BADGE_STYLES: Record<PolicyStatus, { bg: string; color: string; label: string }> = {
  assigned: {
    bg: 'rgba(139,92,246,0.20)',
    color: '#A78BFA',
    label: 'Policy',
  },
  inherited: {
    bg: 'rgba(167,139,250,0.15)',
    color: '#A78BFA',
    label: 'Inherited',
  },
  override: {
    bg: 'rgba(245,158,11,0.20)',
    color: '#FBBF24',
    label: 'Override',
  },
  none: {
    bg: 'transparent',
    color: 'transparent',
    label: '',
  },
};

export function PolicyBadge({ status, profileName, source }: PolicyBadgeProps) {
  if (status === 'none') return null;

  const style = BADGE_STYLES[status];
  const tooltip = profileName
    ? `${style.label}: ${profileName}${source ? ` (${source})` : ''}`
    : style.label;

  return (
    <div
      className="absolute top-1.5 right-1.5 z-10 flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[9px] font-semibold tracking-wide uppercase whitespace-nowrap"
      style={{
        backgroundColor: style.bg,
        color: style.color,
        border: `1px solid ${style.color}40`,
        backdropFilter: 'blur(4px)',
      }}
      title={tooltip}
    >
      <svg
        width="10"
        height="10"
        viewBox="0 0 24 24"
        fill={style.color}
        stroke="none"
      >
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
      {style.label}
    </div>
  );
}
