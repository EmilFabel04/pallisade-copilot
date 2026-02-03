// ============================================
// ROLE-BASED ACCESS CONTROL (RBAC)
// ============================================

import { TeamRole } from '@prisma/client';

// Permission definitions
export type Permission =
  // Organization
  | 'org:view'
  | 'org:edit'
  | 'org:delete'
  | 'org:transfer'
  // Team
  | 'team:view'
  | 'team:invite'
  | 'team:remove'
  | 'team:edit_roles'
  // Integrations
  | 'integrations:view'
  | 'integrations:create'
  | 'integrations:edit'
  | 'integrations:delete'
  | 'integrations:test'
  // Pipelines
  | 'pipelines:view'
  | 'pipelines:create'
  | 'pipelines:edit'
  | 'pipelines:delete'
  | 'pipelines:manage_access'
  | 'pipelines:manage_tokens'
  // Scans
  | 'scans:view'
  | 'scans:run'
  | 'scans:schedule'
  | 'scans:configure'
  // Reports
  | 'reports:view'
  | 'reports:create'
  | 'reports:export'
  // Findings
  | 'findings:view'
  | 'findings:respond'
  | 'findings:configure_rules'
  // Fixes
  | 'fixes:view'
  | 'fixes:apply'
  | 'fixes:approve'
  // Sandbox Lab
  | 'sandbox:view'
  | 'sandbox:use'
  // Data Contracts
  | 'contracts:view'
  | 'contracts:create'
  | 'contracts:edit'
  | 'contracts:delete'
  // Settings
  | 'settings:view'
  | 'settings:edit'
  // Billing
  | 'billing:view'
  | 'billing:manage'
  // Audit
  | 'audit:view';

// Role -> Permission mapping
const ROLE_PERMISSIONS: Record<TeamRole, Permission[]> = {
  OWNER: [
    // All permissions
    'org:view', 'org:edit', 'org:delete', 'org:transfer',
    'team:view', 'team:invite', 'team:remove', 'team:edit_roles',
    'integrations:view', 'integrations:create', 'integrations:edit', 'integrations:delete', 'integrations:test',
    'pipelines:view', 'pipelines:create', 'pipelines:edit', 'pipelines:delete', 'pipelines:manage_access', 'pipelines:manage_tokens',
    'scans:view', 'scans:run', 'scans:schedule', 'scans:configure',
    'reports:view', 'reports:create', 'reports:export',
    'findings:view', 'findings:respond', 'findings:configure_rules',
    'fixes:view', 'fixes:apply', 'fixes:approve',
    'sandbox:view', 'sandbox:use',
    'contracts:view', 'contracts:create', 'contracts:edit', 'contracts:delete',
    'settings:view', 'settings:edit',
    'billing:view', 'billing:manage',
    'audit:view',
  ],
  ADMIN: [
    // Everything except org deletion, transfer, and billing management
    'org:view', 'org:edit',
    'team:view', 'team:invite', 'team:remove', 'team:edit_roles',
    'integrations:view', 'integrations:create', 'integrations:edit', 'integrations:delete', 'integrations:test',
    'pipelines:view', 'pipelines:create', 'pipelines:edit', 'pipelines:delete', 'pipelines:manage_access', 'pipelines:manage_tokens',
    'scans:view', 'scans:run', 'scans:schedule', 'scans:configure',
    'reports:view', 'reports:create', 'reports:export',
    'findings:view', 'findings:respond', 'findings:configure_rules',
    'fixes:view', 'fixes:apply', 'fixes:approve',
    'sandbox:view', 'sandbox:use',
    'contracts:view', 'contracts:create', 'contracts:edit', 'contracts:delete',
    'settings:view', 'settings:edit',
    'billing:view',
    'audit:view',
  ],
  MANAGER: [
    // Can't manage team or settings
    'org:view',
    'team:view',
    'integrations:view', 'integrations:test',
    'pipelines:view', 'pipelines:create', 'pipelines:edit',
    'scans:view', 'scans:run', 'scans:schedule', 'scans:configure',
    'reports:view', 'reports:create', 'reports:export',
    'findings:view', 'findings:respond', 'findings:configure_rules',
    'fixes:view', 'fixes:apply', 'fixes:approve',
    'sandbox:view', 'sandbox:use',
    'contracts:view', 'contracts:create', 'contracts:edit',
    'settings:view',
    'audit:view',
  ],
  ENGINEER: [
    // Day-to-day operations: run scans, use sandbox, apply fixes
    'org:view',
    'team:view',
    'integrations:view', 'integrations:test',
    'pipelines:view', 'pipelines:create', 'pipelines:edit',
    'scans:view', 'scans:run',
    'reports:view', 'reports:export',
    'findings:view', 'findings:respond',
    'fixes:view', 'fixes:apply',
    'sandbox:view', 'sandbox:use',
    'contracts:view',
    'settings:view',
  ],
  VIEWER: [
    // Read-only: view reports, findings, contracts
    'org:view',
    'team:view',
    'integrations:view',
    'pipelines:view',
    'scans:view',
    'reports:view',
    'findings:view',
    'contracts:view',
    'settings:view',
  ],
};

// Check if a role has a specific permission
export function hasPermission(role: TeamRole, permission: Permission): boolean {
  return ROLE_PERMISSIONS[role]?.includes(permission) ?? false;
}

// Check if a role has ALL specified permissions
export function hasAllPermissions(role: TeamRole, permissions: Permission[]): boolean {
  return permissions.every(p => hasPermission(role, p));
}

// Check if a role has ANY of specified permissions
export function hasAnyPermission(role: TeamRole, permissions: Permission[]): boolean {
  return permissions.some(p => hasPermission(role, p));
}

// Get all permissions for a role
export function getPermissions(role: TeamRole): Permission[] {
  return ROLE_PERMISSIONS[role] ?? [];
}

// Role hierarchy (for checking if one role can manage another)
const ROLE_HIERARCHY: Record<TeamRole, number> = {
  OWNER: 100,
  ADMIN: 80,
  MANAGER: 60,
  ENGINEER: 40,
  VIEWER: 20,
};

// Check if one role can manage another
export function canManageRole(managerRole: TeamRole, targetRole: TeamRole): boolean {
  // Owners can manage everyone
  if (managerRole === 'OWNER') return true;
  // Can only manage roles below your level
  return ROLE_HIERARCHY[managerRole] > ROLE_HIERARCHY[targetRole];
}

// Get roles that a user can assign
export function getAssignableRoles(userRole: TeamRole): TeamRole[] {
  const userLevel = ROLE_HIERARCHY[userRole];
  return (Object.entries(ROLE_HIERARCHY) as [TeamRole, number][])
    .filter(([_, level]) => level < userLevel)
    .map(([role]) => role);
}

// Human-readable role names
export const ROLE_DISPLAY_NAMES: Record<TeamRole, string> = {
  OWNER: 'Owner',
  ADMIN: 'Admin',
  MANAGER: 'Manager',
  ENGINEER: 'Engineer',
  VIEWER: 'Viewer',
};

// Role descriptions
export const ROLE_DESCRIPTIONS: Record<TeamRole, string> = {
  OWNER: 'Full control over the organization, billing, and all settings. Can transfer ownership.',
  ADMIN: 'Manage team members, integrations, and settings. Cannot delete organization.',
  MANAGER: 'Run scans, configure contracts, and approve fixes. Cannot manage team.',
  ENGINEER: 'Run scans, use sandbox lab, and apply fixes. Day-to-day operations.',
  VIEWER: 'Read-only access to reports, findings, and dashboards.',
};

// Permission categories for UI
export const PERMISSION_CATEGORIES = {
  organization: ['org:view', 'org:edit', 'org:delete', 'org:transfer'],
  team: ['team:view', 'team:invite', 'team:remove', 'team:edit_roles'],
  integrations: ['integrations:view', 'integrations:create', 'integrations:edit', 'integrations:delete', 'integrations:test'],
  pipelines: ['pipelines:view', 'pipelines:create', 'pipelines:edit', 'pipelines:delete', 'pipelines:manage_access', 'pipelines:manage_tokens'],
  scans: ['scans:view', 'scans:run', 'scans:schedule', 'scans:configure'],
  reports: ['reports:view', 'reports:create', 'reports:export'],
  findings: ['findings:view', 'findings:respond', 'findings:configure_rules'],
  fixes: ['fixes:view', 'fixes:apply', 'fixes:approve'],
  sandbox: ['sandbox:view', 'sandbox:use'],
  contracts: ['contracts:view', 'contracts:create', 'contracts:edit', 'contracts:delete'],
  settings: ['settings:view', 'settings:edit'],
  billing: ['billing:view', 'billing:manage'],
  audit: ['audit:view'],
} as const;
