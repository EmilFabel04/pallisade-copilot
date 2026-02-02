'use client';

import { Crown, Shield, Star, User, Eye } from 'lucide-react';

type Role = 'OWNER' | 'ADMIN' | 'MANAGER' | 'ENGINEER' | 'VIEWER';

const ROLE_CONFIG: Record<Role, { icon: any; color: string; bg: string; label: string }> = {
  OWNER: {
    icon: Crown,
    color: 'text-amber-400',
    bg: 'bg-amber-400/10 border-amber-400/20',
    label: 'Owner',
  },
  ADMIN: {
    icon: Shield,
    color: 'text-purple-400',
    bg: 'bg-purple-400/10 border-purple-400/20',
    label: 'Admin',
  },
  MANAGER: {
    icon: Star,
    color: 'text-blue-400',
    bg: 'bg-blue-400/10 border-blue-400/20',
    label: 'Manager',
  },
  ENGINEER: {
    icon: User,
    color: 'text-emerald-400',
    bg: 'bg-emerald-400/10 border-emerald-400/20',
    label: 'Engineer',
  },
  VIEWER: {
    icon: Eye,
    color: 'text-slate-400',
    bg: 'bg-slate-400/10 border-slate-400/20',
    label: 'Viewer',
  },
};

interface RoleBadgeProps {
  role: Role;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
}

export function RoleBadge({ role, size = 'md', showLabel = true }: RoleBadgeProps) {
  const config = ROLE_CONFIG[role];
  const Icon = config.icon;

  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-xs gap-1',
    md: 'px-2 py-0.5 text-xs gap-1.5',
    lg: 'px-3 py-1 text-sm gap-2',
  };

  const iconSizes = {
    sm: 'w-3 h-3',
    md: 'w-3.5 h-3.5',
    lg: 'w-4 h-4',
  };

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium border ${config.bg} ${config.color} ${sizeClasses[size]}`}
    >
      <Icon className={iconSizes[size]} />
      {showLabel && <span>{config.label}</span>}
    </span>
  );
}

// Export role descriptions for tooltips or info displays
export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  OWNER: 'Full control over the organization, billing, and all settings. Can transfer ownership.',
  ADMIN: 'Manage team members, integrations, and settings. Cannot delete organization.',
  MANAGER: 'Run scans, configure contracts, and approve fixes. Cannot manage team.',
  ENGINEER: 'Run scans, use sandbox lab, and apply fixes. Day-to-day operations.',
  VIEWER: 'Read-only access to reports, findings, and dashboards.',
};
