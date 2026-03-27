'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { cachedFetch } from '@/lib/fetch-cache';
import {
  Users,
  UserPlus,
  Shield,
  Crown,
  Briefcase,
  Code2,
  Eye,
  Search,
  Pencil,
  Trash2,
  X,
  Mail,
  Clock,
  Workflow,
  Activity,
  KeyRound,
  RefreshCw,
} from 'lucide-react';
import AuthenticationSettings from '@/components/settings/AuthenticationSettings';

// --- Types ---

interface PipelineAccess {
  pipelineId: string;
  pipelineName: string;
  accessLevel: 'OWNER' | 'EDITOR' | 'VIEWER';
  tokensUsed: number;
}

interface TeamMember {
  id: string;
  userId: string;
  email: string;
  name: string | null;
  image: string | null;
  role: 'OWNER' | 'ADMIN' | 'MANAGER' | 'ENGINEER' | 'VIEWER';
  status: 'ACTIVE' | 'INACTIVE' | 'SUSPENDED';
  title: string | null;
  department: string | null;
  joinedAt: string;
  lastActiveAt: string | null;
  pipelineAccess?: PipelineAccess[];
}

interface PendingInvite {
  id: string;
  email: string;
  role: string;
  inviterName: string | null;
  createdAt: string;
  expiresAt: string;
  emailSentAt: string | null;
}

interface Pipeline {
  id: string;
  name: string;
  status: string;
}

interface TeamStats {
  totalMembers: number;
  activeMembers: number;
  pendingInvites: number;
  totalPipelines: number;
}

// --- Role configuration ---

const ROLE_CONFIG = {
  OWNER: {
    label: 'Owner',
    icon: Crown,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/20',
    description: 'Full control over the organization',
  },
  ADMIN: {
    label: 'Admin',
    icon: Shield,
    color: 'text-[var(--text-secondary)]',
    bg: 'bg-[var(--hover-bg)]',
    border: 'border-[var(--border-medium)]',
    description: 'Manage team, integrations, and settings',
  },
  MANAGER: {
    label: 'Manager',
    icon: Briefcase,
    color: 'text-[var(--text-tertiary)]',
    bg: 'bg-[var(--subtle-bg)]',
    border: 'border-[var(--subtle-border)]',
    description: 'Run scans, manage contracts and findings',
  },
  ENGINEER: {
    label: 'Engineer',
    icon: Code2,
    color: 'text-[var(--text-tertiary)]',
    bg: 'bg-[var(--subtle-bg)]',
    border: 'border-[var(--subtle-border)]',
    description: 'Run scans, use sandbox, apply fixes',
  },
  VIEWER: {
    label: 'Viewer',
    icon: Eye,
    color: 'text-[var(--muted)]',
    bg: 'bg-[var(--overlay-bg)]',
    border: 'border-[var(--subtle-border)]',
    description: 'Read-only access to dashboards',
  },
};

// --- Animations ---

const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.06 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: 'easeOut' as const } },
};

// --- Component ---

export default function TeamPage() {
  const { data: session } = useSession();

  // State
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [pendingInvites, setPendingInvites] = useState<PendingInvite[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [stats, setStats] = useState<TeamStats>({ totalMembers: 0, activeMembers: 0, pendingInvites: 0, totalPipelines: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // User permissions
  const [isAdmin, setIsAdmin] = useState(false);

  // UI State
  const [activeTab, setActiveTab] = useState<'members' | 'invites' | 'authentication'>('members');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedMember, setSelectedMember] = useState<TeamMember | null>(null);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [showMemberModal, setShowMemberModal] = useState(false);

  // Invite form
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<string>('ENGINEER');
  const [invitePipelines, setInvitePipelines] = useState<{ pipelineId: string; accessLevel: string }[]>([]);
  const [inviting, setInviting] = useState(false);

  // Edit form
  const [editRole, setEditRole] = useState<string>('');
  const [editPipelineAccess, setEditPipelineAccess] = useState<{ pipelineId: string; accessLevel: string }[]>([]);
  const [saving, setSaving] = useState(false);

  // Fetch team data
  const fetchTeamData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch team members
      const teamRes = await cachedFetch('/api/team');
      if (teamRes.ok) {
        const teamData = await teamRes.json();
        setMembers(teamData.members || []);
        setPendingInvites(teamData.pendingInvites || []);
        setIsAdmin(teamData.permissions?.canEditRoles || false);

        setStats({
          totalMembers: teamData.members?.length || 0,
          activeMembers: teamData.members?.filter((m: TeamMember) => m.status === 'ACTIVE').length || 0,
          pendingInvites: teamData.pendingInvites?.length || 0,
          totalPipelines: 0,
        });
      }

      // Fetch pipelines
      const pipelinesRes = await cachedFetch('/api/pipeline');
      if (pipelinesRes.ok) {
        const pipelinesData = await pipelinesRes.json();
        setPipelines(pipelinesData.stacks || []);
        setStats(prev => ({ ...prev, totalPipelines: pipelinesData.stacks?.length || 0 }));
      }
    } catch (err) {
      console.error('Failed to fetch team data:', err);
      setError('Failed to load team data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTeamData();
  }, [fetchTeamData]);

  // Fetch member's pipeline access
  const fetchMemberAccess = async (memberId: string) => {
    try {
      const res = await fetch(`/api/team/members/${memberId}/access`);
      if (res.ok) {
        const data = await res.json();
        return data.access || [];
      }
    } catch (err) {
      console.error('Failed to fetch member access:', err);
    }
    return [];
  };

  // Handle invite
  const handleInvite = async () => {
    if (!inviteEmail) return;

    setInviting(true);
    try {
      const res = await fetch('/api/team/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: inviteEmail,
          role: inviteRole,
          pipelineAccess: invitePipelines,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to send invite');
      }

      setShowInviteModal(false);
      setInviteEmail('');
      setInviteRole('ENGINEER');
      setInvitePipelines([]);
      await fetchTeamData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setInviting(false);
    }
  };

  // Handle update member
  const handleUpdateMember = async () => {
    if (!selectedMember) return;

    setSaving(true);
    try {
      // Update role
      const roleRes = await fetch(`/api/team/members/${selectedMember.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: editRole }),
      });

      if (!roleRes.ok) {
        throw new Error('Failed to update role');
      }

      // Update pipeline access
      for (const access of editPipelineAccess) {
        await fetch(`/api/pipeline/${access.pipelineId}/access`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            userId: selectedMember.userId,
            accessLevel: access.accessLevel,
          }),
        });
      }

      setShowMemberModal(false);
      setSelectedMember(null);
      await fetchTeamData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  };

  // Handle remove member
  const handleRemoveMember = async (memberId: string, memberName: string) => {
    if (!confirm(`Remove ${memberName} from the team? This will revoke all their access.`)) return;

    try {
      const res = await fetch(`/api/team/members/${memberId}`, {
        method: 'DELETE',
      });

      if (!res.ok) {
        throw new Error('Failed to remove member');
      }

      await fetchTeamData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  // Handle revoke invite
  const handleRevokeInvite = async (inviteId: string) => {
    if (!confirm('Revoke this invite?')) return;

    try {
      const res = await fetch(`/api/team/invite?id=${inviteId}`, {
        method: 'DELETE',
      });

      if (!res.ok) {
        throw new Error('Failed to revoke invite');
      }

      await fetchTeamData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  // Handle resend invite
  const handleResendInvite = async (inviteId: string) => {
    try {
      const res = await fetch('/api/team/invite', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ inviteId }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to resend invite');
      }
      fetchTeamData(); // Refresh to show updated emailSentAt
    } catch (err: any) {
      console.error('Resend invite failed:', err);
    }
  };

  // Open member modal
  const openMemberModal = async (member: TeamMember) => {
    setSelectedMember(member);
    setEditRole(member.role);

    // Fetch current pipeline access
    const access = await fetchMemberAccess(member.id);
    setEditPipelineAccess(access.map((a: any) => ({
      pipelineId: a.pipelineId,
      accessLevel: a.accessLevel,
    })));

    setShowMemberModal(true);
  };

  // Toggle pipeline access in invite form
  const toggleInvitePipelineAccess = (pipelineId: string, accessLevel: string) => {
    setInvitePipelines(prev => {
      const existing = prev.find(p => p.pipelineId === pipelineId);
      if (existing) {
        if (existing.accessLevel === accessLevel || !accessLevel) {
          return prev.filter(p => p.pipelineId !== pipelineId);
        }
        return prev.map(p => p.pipelineId === pipelineId ? { ...p, accessLevel } : p);
      }
      if (!accessLevel) return prev;
      return [...prev, { pipelineId, accessLevel }];
    });
  };

  // Toggle pipeline access in edit form
  const toggleEditPipelineAccess = (pipelineId: string, accessLevel: string) => {
    setEditPipelineAccess(prev => {
      const existing = prev.find(p => p.pipelineId === pipelineId);
      if (existing) {
        if (existing.accessLevel === accessLevel || !accessLevel) {
          return prev.filter(p => p.pipelineId !== pipelineId);
        }
        return prev.map(p => p.pipelineId === pipelineId ? { ...p, accessLevel } : p);
      }
      if (!accessLevel) return prev;
      return [...prev, { pipelineId, accessLevel }];
    });
  };

  // Filter members
  const filteredMembers = members.filter(member => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      member.name?.toLowerCase().includes(query) ||
      member.email.toLowerCase().includes(query) ||
      member.role.toLowerCase().includes(query)
    );
  });

  // Format date
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  // Format relative time
  const formatRelativeTime = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    return formatDate(dateStr);
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto flex items-center justify-center min-h-[400px]">
        <div className="w-8 h-8 red-spinner" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="flex items-center justify-between"
      >
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text)]">Team</h1>
          <p className="text-[var(--muted)] text-[15px] mt-1">Manage members and pipeline access</p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowInviteModal(true)}
            className="flex items-center gap-2 px-4 py-2.5 bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-sm font-medium rounded-lg transition-colors"
          >
            <UserPlus className="w-4 h-4" />
            Invite Member
          </button>
        )}
      </motion.div>

      {/* Stats */}
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 md:grid-cols-4 gap-3"
      >
        <motion.div variants={itemVariants}>
          <div className="flex items-center gap-3 p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <div className="w-9 h-9 rounded-lg bg-[var(--hover-bg)] flex items-center justify-center">
              <Users className="w-5 h-5 text-[var(--text-tertiary)]" />
            </div>
            <div>
              <span className="text-xl font-semibold text-[var(--text)]">{stats.totalMembers}</span>
              <p className="text-[12px] text-[var(--muted)]">Members</p>
            </div>
          </div>
        </motion.div>

        <motion.div variants={itemVariants}>
          <div className="flex items-center gap-3 p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <Activity className="w-5 h-5 text-emerald-400" />
            </div>
            <div>
              <span className="text-xl font-semibold text-[var(--text)]">{stats.activeMembers}</span>
              <p className="text-[12px] text-[var(--muted)]">Active</p>
            </div>
          </div>
        </motion.div>

        <motion.div variants={itemVariants}>
          <div className="flex items-center gap-3 p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <div className="w-9 h-9 rounded-lg bg-amber-500/10 flex items-center justify-center">
              <Mail className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <span className="text-xl font-semibold text-[var(--text)]">{stats.pendingInvites}</span>
              <p className="text-[12px] text-[var(--muted)]">Pending</p>
            </div>
          </div>
        </motion.div>

        <motion.div variants={itemVariants}>
          <div className="flex items-center gap-3 p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <div className="w-9 h-9 rounded-lg bg-indigo-500/10 flex items-center justify-center">
              <Workflow className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <span className="text-xl font-semibold text-[var(--text)]">{stats.totalPipelines}</span>
              <p className="text-[12px] text-[var(--muted)]">Pipelines</p>
            </div>
          </div>
        </motion.div>
      </motion.div>

      {/* Search and Tabs */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.15 }}
        className="flex items-center justify-between gap-4"
      >
        <div className="flex items-center gap-1 p-1 bg-[var(--overlay-bg)] rounded-lg border border-[var(--subtle-border)]">
          <button
            onClick={() => setActiveTab('members')}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-all',
              activeTab === 'members'
                ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'
            )}
          >
            Members ({members.length})
          </button>
          <button
            onClick={() => setActiveTab('invites')}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-all',
              activeTab === 'invites'
                ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'
            )}
          >
            Invites ({pendingInvites.length})
          </button>
          <button
            onClick={() => setActiveTab('authentication')}
            className={cn(
              'flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-md transition-all',
              activeTab === 'authentication'
                ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'
            )}
          >
            <KeyRound className="w-3.5 h-3.5" />
            Authentication
          </button>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-faint)]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search members..."
            className="w-64 pl-10 pr-4 py-2 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] text-sm transition-colors"
          />
        </div>
      </motion.div>

      {/* Members Tab */}
      {activeTab === 'members' && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl overflow-hidden"
        >
          {/* Table Header */}
          <div className="grid grid-cols-12 gap-4 px-6 py-3 border-b border-[var(--subtle-border)] text-[11px] font-medium text-[var(--text-faint)] uppercase tracking-wider">
            <div className="col-span-4">Member</div>
            <div className="col-span-2">Role</div>
            <div className="col-span-2">Pipelines</div>
            <div className="col-span-2">Last Active</div>
            <div className="col-span-2 text-right">Actions</div>
          </div>

          {/* Members List */}
          <div className="divide-y divide-white/[0.04]">
            {filteredMembers.length === 0 ? (
              <div className="px-6 py-12 text-center">
                <Users className="w-8 h-8 text-[var(--text-faint)] mx-auto mb-3" />
                <p className="text-[13px] text-[var(--muted)]">No members found</p>
              </div>
            ) : (
              filteredMembers.map((member) => {
                const roleConfig = ROLE_CONFIG[member.role];
                const RoleIcon = roleConfig.icon;
                return (
                  <div
                    key={member.id}
                    className="grid grid-cols-12 gap-4 px-6 py-4 items-center hover:bg-[var(--overlay-faint)] transition-colors"
                  >
                    {/* Member Info */}
                    <div className="col-span-4 flex items-center gap-3">
                      <div className="relative flex-shrink-0">
                        {member.image ? (
                          <img
                            src={member.image}
                            alt=""
                            className="w-9 h-9 rounded-full object-cover ring-1 ring-[var(--subtle-border)]"
                          />
                        ) : (
                          <div className="w-9 h-9 rounded-full bg-[var(--hover-bg)] flex items-center justify-center text-[var(--text-tertiary)] text-sm font-medium ring-1 ring-[var(--subtle-border)]">
                            {(member.name || member.email)[0].toUpperCase()}
                          </div>
                        )}
                        {member.status === 'ACTIVE' && (
                          <div className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 bg-emerald-500 rounded-full border-2 border-[var(--bg)]" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <p className="text-[13px] font-medium text-[var(--text)] truncate">
                          {member.name || 'Unnamed'}
                        </p>
                        <p className="text-[11px] text-[var(--muted)] truncate">{member.email}</p>
                      </div>
                    </div>

                    {/* Role */}
                    <div className="col-span-2">
                      <span className={cn(
                        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border',
                        roleConfig.bg, roleConfig.color, roleConfig.border,
                      )}>
                        <RoleIcon className="w-3 h-3" />
                        {roleConfig.label}
                      </span>
                    </div>

                    {/* Pipeline Access */}
                    <div className="col-span-2">
                      {member.pipelineAccess && member.pipelineAccess.length > 0 ? (
                        <span className="text-[13px] text-[var(--muted)]">
                          {member.pipelineAccess.length} pipeline{member.pipelineAccess.length !== 1 ? 's' : ''}
                        </span>
                      ) : (
                        <span className="text-[12px] text-[var(--text-faint)]">
                          {member.role === 'OWNER' || member.role === 'ADMIN' ? 'Full access' : 'None'}
                        </span>
                      )}
                    </div>

                    {/* Last Active */}
                    <div className="col-span-2">
                      <span className="text-[13px] text-[var(--muted)]">
                        {formatRelativeTime(member.lastActiveAt)}
                      </span>
                    </div>

                    {/* Actions */}
                    <div className="col-span-2 flex items-center justify-end gap-1">
                      {isAdmin && member.role !== 'OWNER' && (
                        <>
                          <button
                            onClick={() => openMemberModal(member)}
                            className="p-2 rounded-lg text-[var(--text-faint)] hover:text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] transition-colors"
                            title="Edit member"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleRemoveMember(member.id, member.name || member.email)}
                            className="p-2 rounded-lg text-[var(--text-faint)] hover:text-red-400 hover:bg-red-500/10 transition-colors"
                            title="Remove member"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </motion.div>
      )}

      {/* Pending Invites Tab */}
      {activeTab === 'invites' && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl overflow-hidden"
        >
          {pendingInvites.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-[var(--subtle-bg)] flex items-center justify-center">
                <Mail className="w-6 h-6 text-[var(--text-faint)]" />
              </div>
              <p className="text-[13px] text-[var(--muted)] font-medium">No pending invites</p>
              <p className="text-[12px] text-[var(--text-faint)] mt-1">Send invitations to grow your team</p>
            </div>
          ) : (
            <div className="divide-y divide-white/[0.04]">
              {pendingInvites.map((invite) => {
                const roleConfig = ROLE_CONFIG[invite.role as keyof typeof ROLE_CONFIG];
                const RoleIcon = roleConfig?.icon || Eye;
                return (
                  <div
                    key={invite.id}
                    className="flex items-center justify-between px-6 py-4 hover:bg-[var(--overlay-faint)] transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-full bg-amber-500/10 flex items-center justify-center">
                        <Clock className="w-4 h-4 text-amber-400" />
                      </div>
                      <div>
                        <p className="text-[13px] font-medium text-[var(--text)]">{invite.email}</p>
                        <p className="text-[11px] text-[var(--text-faint)]">
                          Invited by {invite.inviterName || 'team member'} &middot; Expires {formatDate(invite.expiresAt)}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {roleConfig && (
                        <span className={cn(
                          'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border',
                          roleConfig.bg, roleConfig.color, roleConfig.border,
                        )}>
                          <RoleIcon className="w-3 h-3" />
                          {roleConfig.label}
                        </span>
                      )}
                      {invite.emailSentAt && (
                        <span className="text-[10px] text-[var(--text-faint)]">
                          Emailed {formatDate(invite.emailSentAt)}
                        </span>
                      )}
                      {isAdmin && (
                        <button
                          onClick={() => handleResendInvite(invite.id)}
                          className="p-2 rounded-lg text-[var(--text-faint)] hover:text-violet-400 hover:bg-violet-500/10 transition-colors"
                          title="Resend invite email"
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                        </button>
                      )}
                      {isAdmin && (
                        <button
                          onClick={() => handleRevokeInvite(invite.id)}
                          className="p-2 rounded-lg text-[var(--text-faint)] hover:text-red-400 hover:bg-red-500/10 transition-colors"
                          title="Revoke invite"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </motion.div>
      )}

      {/* Authentication Tab */}
      {activeTab === 'authentication' && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <AuthenticationSettings />
        </motion.div>
      )}

      {/* Role Reference */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.2 }}
        className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-5"
      >
        <h3 className="text-[13px] font-medium text-[var(--muted)] mb-4 uppercase tracking-wider">Roles</h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {Object.entries(ROLE_CONFIG).map(([role, config]) => {
            const Icon = config.icon;
            return (
              <div
                key={role}
                className={cn('p-3 rounded-lg border', config.border, config.bg)}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <Icon className={cn('w-3.5 h-3.5', config.color)} />
                  <p className={cn('text-[13px] font-medium', config.color)}>{config.label}</p>
                </div>
                <p className="text-[11px] text-[var(--text-faint)] leading-relaxed">{config.description}</p>
              </div>
            );
          })}
        </div>
      </motion.div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowInviteModal(false)} />
          <div className="relative bg-[var(--bg-soft)] border border-[var(--subtle-border)] rounded-xl w-full max-w-lg shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
              <div>
                <h2 className="text-lg font-semibold text-[var(--text)]">Invite Member</h2>
                <p className="text-[13px] text-[var(--muted)] mt-0.5">Add a new member to your organization</p>
              </div>
              <button
                onClick={() => setShowInviteModal(false)}
                className="p-2 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Content */}
            <div className="p-6 space-y-5">
              {/* Email */}
              <div>
                <label className="block text-[13px] font-medium text-[var(--muted)] mb-2">Email Address</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@company.com"
                  className="w-full px-4 py-2.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] text-sm transition-colors"
                />
              </div>

              {/* Role */}
              <div>
                <label className="block text-[13px] font-medium text-[var(--muted)] mb-2">Role</label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="w-full px-4 py-2.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] text-sm transition-colors"
                >
                  <option value="ADMIN">Admin — Full management access</option>
                  <option value="MANAGER">Manager — Run scans, manage contracts</option>
                  <option value="ENGINEER">Engineer — Run scans, use sandbox</option>
                  <option value="VIEWER">Viewer — Read-only access</option>
                </select>
              </div>

              {/* Pipeline Access */}
              <div>
                <label className="block text-[13px] font-medium text-[var(--muted)] mb-2">Pipeline Access</label>
                <p className="text-[11px] text-[var(--text-faint)] mb-3">
                  {inviteRole === 'ADMIN'
                    ? 'Admins automatically have access to all pipelines'
                    : 'Configure which pipelines this member can access'}
                </p>

                {inviteRole !== 'ADMIN' && pipelines.length > 0 && (
                  <div className="space-y-2 max-h-40 overflow-y-auto">
                    {pipelines.map((pipeline) => {
                      const access = invitePipelines.find(p => p.pipelineId === pipeline.id);
                      return (
                        <div
                          key={pipeline.id}
                          className="flex items-center justify-between p-3 bg-[var(--overlay-faint)] border border-[var(--border-faint)] rounded-lg"
                        >
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-emerald-500" />
                            <span className="text-[13px] text-[var(--text-tertiary)]">{pipeline.name}</span>
                          </div>
                          <select
                            value={access?.accessLevel || ''}
                            onChange={(e) => toggleInvitePipelineAccess(pipeline.id, e.target.value)}
                            className="px-3 py-1.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[11px] text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--overlay-strong)] transition-colors"
                          >
                            <option value="">No access</option>
                            <option value="VIEWER">Viewer</option>
                            <option value="EDITOR">Editor</option>
                            <option value="OWNER">Owner</option>
                          </select>
                        </div>
                      );
                    })}
                  </div>
                )}

                {pipelines.length === 0 && inviteRole !== 'ADMIN' && (
                  <p className="text-[11px] text-[var(--text-faint)] italic">No pipelines available</p>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-[var(--subtle-border)]">
              <button
                onClick={() => setShowInviteModal(false)}
                className="px-4 py-2 text-sm text-[var(--muted)] hover:text-[var(--text-tertiary)] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleInvite}
                disabled={!inviteEmail || inviting}
                className="px-5 py-2 bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {inviting ? 'Sending...' : 'Send Invite'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Member Modal */}
      {showMemberModal && selectedMember && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowMemberModal(false)} />
          <div className="relative bg-[var(--bg-soft)] border border-[var(--subtle-border)] rounded-xl w-full max-w-lg shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
              <div className="flex items-center gap-3">
                {selectedMember.image ? (
                  <img src={selectedMember.image} alt="" className="w-9 h-9 rounded-full ring-1 ring-[var(--subtle-border)]" />
                ) : (
                  <div className="w-9 h-9 rounded-full bg-[var(--hover-bg)] flex items-center justify-center text-[var(--text-tertiary)] text-sm font-medium ring-1 ring-[var(--subtle-border)]">
                    {(selectedMember.name || selectedMember.email)[0].toUpperCase()}
                  </div>
                )}
                <div>
                  <h2 className="text-[15px] font-semibold text-[var(--text)]">{selectedMember.name || 'Edit Member'}</h2>
                  <p className="text-[12px] text-[var(--muted)]">{selectedMember.email}</p>
                </div>
              </div>
              <button
                onClick={() => setShowMemberModal(false)}
                className="p-2 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Content */}
            <div className="p-6 space-y-5">
              {/* Role */}
              <div>
                <label className="block text-[13px] font-medium text-[var(--muted)] mb-3">Role</label>
                <div className="space-y-2">
                  {Object.entries(ROLE_CONFIG)
                    .filter(([role]) => role !== 'OWNER')
                    .map(([role, config]) => {
                      const Icon = config.icon;
                      return (
                        <button
                          key={role}
                          onClick={() => setEditRole(role)}
                          className={cn(
                            'w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left',
                            editRole === role
                              ? `${config.border} ${config.bg}`
                              : 'border-[var(--border-faint)] hover:border-[var(--subtle-border)] bg-[var(--overlay-faint)]'
                          )}
                        >
                          <Icon className={cn('w-4 h-4 flex-shrink-0', editRole === role ? config.color : 'text-[var(--text-faint)]')} />
                          <div>
                            <p className={cn('text-[13px] font-medium', editRole === role ? config.color : 'text-[var(--text-tertiary)]')}>
                              {config.label}
                            </p>
                            <p className="text-[11px] text-[var(--text-faint)]">{config.description}</p>
                          </div>
                        </button>
                      );
                    })}
                </div>
              </div>

              {/* Pipeline Access */}
              {editRole !== 'ADMIN' && (
                <div>
                  <label className="block text-[13px] font-medium text-[var(--muted)] mb-2">Pipeline Access</label>
                  <div className="space-y-2 max-h-40 overflow-y-auto">
                    {pipelines.map((pipeline) => {
                      const access = editPipelineAccess.find(p => p.pipelineId === pipeline.id);
                      return (
                        <div
                          key={pipeline.id}
                          className="flex items-center justify-between p-3 bg-[var(--overlay-faint)] border border-[var(--border-faint)] rounded-lg"
                        >
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-emerald-500" />
                            <span className="text-[13px] text-[var(--text-tertiary)]">{pipeline.name}</span>
                          </div>
                          <select
                            value={access?.accessLevel || ''}
                            onChange={(e) => toggleEditPipelineAccess(pipeline.id, e.target.value)}
                            className="px-3 py-1.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[11px] text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--overlay-strong)] transition-colors"
                          >
                            <option value="">No access</option>
                            <option value="VIEWER">Viewer</option>
                            <option value="EDITOR">Editor</option>
                            <option value="OWNER">Owner</option>
                          </select>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-[var(--subtle-border)]">
              <button
                onClick={() => setShowMemberModal(false)}
                className="px-4 py-2 text-sm text-[var(--muted)] hover:text-[var(--text-tertiary)] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleUpdateMember}
                disabled={saving}
                className="px-5 py-2 bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {saving ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
