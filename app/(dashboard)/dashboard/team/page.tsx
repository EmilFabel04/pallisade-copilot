'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';

// Types
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

// Role configuration with Pallisade theme
const ROLE_CONFIG = {
  OWNER: {
    label: 'Owner',
    color: 'text-amber-500',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    description: 'Full control over the organization',
  },
  ADMIN: {
    label: 'Admin',
    color: 'text-rose-400',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
    description: 'Manage team, integrations, and settings',
  },
  MANAGER: {
    label: 'Manager',
    color: 'text-orange-400',
    bg: 'bg-orange-500/10',
    border: 'border-orange-500/30',
    description: 'Run scans, manage contracts and findings',
  },
  ENGINEER: {
    label: 'Engineer',
    color: 'text-red-400',
    bg: 'bg-red-500/10',
    border: 'border-red-500/30',
    description: 'Run scans, use sandbox, apply fixes',
  },
  VIEWER: {
    label: 'Viewer',
    color: 'text-slate-400',
    bg: 'bg-slate-500/10',
    border: 'border-slate-500/30',
    description: 'Read-only access to dashboards',
  },
};

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
  const [activeTab, setActiveTab] = useState<'members' | 'invites'>('members');
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
      const teamRes = await fetch('/api/team');
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
      const pipelinesRes = await fetch('/api/pipeline');
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
      <div className="max-w-6xl mx-auto py-8 flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-rose-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-white/50">Loading team data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Team Management</h1>
          <p className="text-white/50 mt-1">Manage team members and pipeline access permissions</p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowInviteModal(true)}
            className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-rose-600 to-orange-600 hover:from-rose-500 hover:to-orange-500 text-white font-medium rounded-lg transition-all shadow-lg shadow-rose-500/20"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
            </svg>
            Invite Member
          </button>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-5">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-rose-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
              </svg>
            </div>
            <div>
              <p className="text-2xl font-semibold text-white">{stats.totalMembers}</p>
              <p className="text-xs text-white/40 uppercase tracking-wide">Team Members</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-5">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5.636 18.364a9 9 0 010-12.728m12.728 0a9 9 0 010 12.728m-9.9-2.829a5 5 0 010-7.07m7.072 0a5 5 0 010 7.07M13 12a1 1 0 11-2 0 1 1 0 012 0z" />
              </svg>
            </div>
            <div>
              <p className="text-2xl font-semibold text-white">{stats.activeMembers}</p>
              <p className="text-xs text-white/40 uppercase tracking-wide">Active Now</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-5">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <div>
              <p className="text-2xl font-semibold text-white">{stats.pendingInvites}</p>
              <p className="text-xs text-white/40 uppercase tracking-wide">Pending Invites</p>
            </div>
          </div>
        </div>
        
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-5">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-orange-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <div>
              <p className="text-2xl font-semibold text-white">{stats.totalPipelines}</p>
              <p className="text-xs text-white/40 uppercase tracking-wide">Pipelines</p>
            </div>
          </div>
        </div>
      </div>

      {/* Search and Tabs */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-1 p-1 bg-white/[0.02] rounded-lg border border-white/[0.06]">
          <button
            onClick={() => setActiveTab('members')}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-all ${
              activeTab === 'members'
                ? 'bg-rose-500/20 text-rose-400'
                : 'text-white/50 hover:text-white/70'
            }`}
          >
            Members ({members.length})
          </button>
          <button
            onClick={() => setActiveTab('invites')}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-all ${
              activeTab === 'invites'
                ? 'bg-rose-500/20 text-rose-400'
                : 'text-white/50 hover:text-white/70'
            }`}
          >
            Pending Invites ({pendingInvites.length})
          </button>
        </div>

        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search members..."
            className="w-64 pl-10 pr-4 py-2 bg-white/[0.02] border border-white/[0.06] rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-rose-500/50 text-sm"
          />
        </div>
      </div>

      {/* Members Tab */}
      {activeTab === 'members' && (
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden">
          {/* Table Header */}
          <div className="grid grid-cols-12 gap-4 px-6 py-3 bg-white/[0.02] border-b border-white/[0.06] text-xs font-medium text-white/40 uppercase tracking-wider">
            <div className="col-span-4">Member</div>
            <div className="col-span-2">Role</div>
            <div className="col-span-2">Pipeline Access</div>
            <div className="col-span-2">Last Active</div>
            <div className="col-span-2 text-right">Actions</div>
          </div>

          {/* Members List */}
          <div className="divide-y divide-white/[0.04]">
            {filteredMembers.length === 0 ? (
              <div className="px-6 py-12 text-center">
                <p className="text-white/40">No members found</p>
              </div>
            ) : (
              filteredMembers.map((member) => {
                const roleConfig = ROLE_CONFIG[member.role];
                return (
                  <div
                    key={member.id}
                    className="grid grid-cols-12 gap-4 px-6 py-4 items-center hover:bg-white/[0.01] transition-colors"
                  >
                    {/* Member Info */}
                    <div className="col-span-4 flex items-center gap-3">
                      <div className="relative">
                        {member.image ? (
                          <img
                            src={member.image}
                            alt=""
                            className="w-10 h-10 rounded-full object-cover ring-2 ring-white/10"
                          />
                        ) : (
                          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-rose-600 to-orange-600 flex items-center justify-center text-white font-medium ring-2 ring-white/10">
                            {(member.name || member.email)[0].toUpperCase()}
                          </div>
                        )}
                        {member.status === 'ACTIVE' && (
                          <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-emerald-500 rounded-full border-2 border-[#0a0a0a]" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-white truncate">
                          {member.name || 'Unnamed'}
                        </p>
                        <p className="text-xs text-white/40 truncate">{member.email}</p>
                      </div>
                    </div>

                    {/* Role */}
                    <div className="col-span-2">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium ${roleConfig.bg} ${roleConfig.color} border ${roleConfig.border}`}>
                        {roleConfig.label}
                      </span>
                    </div>

                    {/* Pipeline Access */}
                    <div className="col-span-2">
                      {member.pipelineAccess && member.pipelineAccess.length > 0 ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm text-white/70">{member.pipelineAccess.length}</span>
                          <span className="text-xs text-white/40">pipeline{member.pipelineAccess.length !== 1 ? 's' : ''}</span>
                        </div>
                      ) : (
                        <span className="text-xs text-white/30">
                          {member.role === 'OWNER' || member.role === 'ADMIN' ? 'Full access' : 'No access'}
                        </span>
                      )}
                    </div>

                    {/* Last Active */}
                    <div className="col-span-2">
                      <span className="text-sm text-white/40">
                        {formatRelativeTime(member.lastActiveAt)}
                      </span>
                    </div>

                    {/* Actions */}
                    <div className="col-span-2 flex items-center justify-end gap-1">
                      {isAdmin && member.role !== 'OWNER' && (
                        <>
                          <button
                            onClick={() => openMemberModal(member)}
                            className="p-2 rounded-lg text-white/30 hover:text-white hover:bg-white/[0.04] transition-colors"
                            title="Edit member"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                            </svg>
                          </button>
                          <button
                            onClick={() => handleRemoveMember(member.id, member.name || member.email)}
                            className="p-2 rounded-lg text-white/30 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                            title="Remove member"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Pending Invites Tab */}
      {activeTab === 'invites' && (
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden">
          {pendingInvites.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <div className="w-12 h-12 mx-auto mb-4 rounded-xl bg-white/[0.02] border border-white/[0.06] flex items-center justify-center">
                <svg className="w-6 h-6 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>
              <p className="text-white/40 font-medium">No pending invites</p>
              <p className="text-sm text-white/25 mt-1">Send invitations to grow your team</p>
            </div>
          ) : (
            <div className="divide-y divide-white/[0.04]">
              {pendingInvites.map((invite) => {
                const roleConfig = ROLE_CONFIG[invite.role as keyof typeof ROLE_CONFIG];
                return (
                  <div
                    key={invite.id}
                    className="flex items-center justify-between px-6 py-4 hover:bg-white/[0.01] transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
                        <svg className="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-white">{invite.email}</p>
                        <p className="text-xs text-white/40">
                          Invited by {invite.inviterName || 'team member'} · Expires {formatDate(invite.expiresAt)}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {roleConfig && (
                        <span className={`px-2.5 py-1 rounded-md text-xs font-medium ${roleConfig.bg} ${roleConfig.color} border ${roleConfig.border}`}>
                          {roleConfig.label}
                        </span>
                      )}
                      {isAdmin && (
                        <button
                          onClick={() => handleRevokeInvite(invite.id)}
                          className="p-2 rounded-lg text-white/30 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                          title="Revoke invite"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Role Reference */}
      <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-6">
        <h3 className="text-sm font-medium text-white/70 mb-4 uppercase tracking-wide">Role Permissions</h3>
        <div className="grid grid-cols-5 gap-3">
          {Object.entries(ROLE_CONFIG).map(([role, config]) => (
            <div
              key={role}
              className={`p-4 rounded-lg border ${config.border} ${config.bg}`}
            >
              <p className={`text-sm font-medium ${config.color} mb-1`}>{config.label}</p>
              <p className="text-xs text-white/40 leading-relaxed">{config.description}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowInviteModal(false)} />
          <div className="relative bg-[#0c0c0c] border border-white/[0.08] rounded-xl w-full max-w-lg shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
              <div>
                <h2 className="text-lg font-semibold text-white">Invite Team Member</h2>
                <p className="text-sm text-white/40 mt-0.5">Add a new member to your organization</p>
              </div>
              <button
                onClick={() => setShowInviteModal(false)}
                className="p-2 rounded-lg text-white/30 hover:text-white hover:bg-white/[0.04] transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content */}
            <div className="p-6 space-y-5">
              {/* Email */}
              <div>
                <label className="block text-sm font-medium text-white/60 mb-2">Email Address</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@company.com"
                  className="w-full px-4 py-2.5 bg-white/[0.02] border border-white/[0.08] rounded-lg text-white placeholder-white/25 focus:outline-none focus:border-rose-500/50 text-sm"
                />
              </div>

              {/* Role */}
              <div>
                <label className="block text-sm font-medium text-white/60 mb-2">Organization Role</label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="w-full px-4 py-2.5 bg-white/[0.02] border border-white/[0.08] rounded-lg text-white focus:outline-none focus:border-rose-500/50 text-sm"
                >
                  <option value="ADMIN">Admin - Full management access</option>
                  <option value="MANAGER">Manager - Run scans, manage contracts</option>
                  <option value="ENGINEER">Engineer - Run scans, use sandbox</option>
                  <option value="VIEWER">Viewer - Read-only access</option>
                </select>
              </div>

              {/* Pipeline Access */}
              <div>
                <label className="block text-sm font-medium text-white/60 mb-2">Pipeline Access</label>
                <p className="text-xs text-white/30 mb-3">
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
                          className="flex items-center justify-between p-3 bg-white/[0.01] border border-white/[0.04] rounded-lg"
                        >
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-emerald-500" />
                            <span className="text-sm text-white/80">{pipeline.name}</span>
                          </div>
                          <select
                            value={access?.accessLevel || ''}
                            onChange={(e) => toggleInvitePipelineAccess(pipeline.id, e.target.value)}
                            className="px-3 py-1.5 bg-white/[0.02] border border-white/[0.06] rounded-md text-xs text-white/70 focus:outline-none focus:border-rose-500/50"
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
                  <p className="text-xs text-white/25 italic">No pipelines available</p>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-white/[0.06]">
              <button
                onClick={() => setShowInviteModal(false)}
                className="px-4 py-2 text-sm text-white/50 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleInvite}
                disabled={!inviteEmail || inviting}
                className="px-5 py-2 bg-gradient-to-r from-rose-600 to-orange-600 hover:from-rose-500 hover:to-orange-500 text-white text-sm font-medium rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
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
          <div className="relative bg-[#0c0c0c] border border-white/[0.08] rounded-xl w-full max-w-lg shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
              <div className="flex items-center gap-3">
                {selectedMember.image ? (
                  <img src={selectedMember.image} alt="" className="w-10 h-10 rounded-full ring-2 ring-white/10" />
                ) : (
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-rose-600 to-orange-600 flex items-center justify-center text-white font-medium ring-2 ring-white/10">
                    {(selectedMember.name || selectedMember.email)[0].toUpperCase()}
                  </div>
                )}
                <div>
                  <h2 className="text-lg font-semibold text-white">{selectedMember.name || 'Edit Member'}</h2>
                  <p className="text-sm text-white/40">{selectedMember.email}</p>
                </div>
              </div>
              <button
                onClick={() => setShowMemberModal(false)}
                className="p-2 rounded-lg text-white/30 hover:text-white hover:bg-white/[0.04] transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Content */}
            <div className="p-6 space-y-5">
              {/* Role */}
              <div>
                <label className="block text-sm font-medium text-white/60 mb-3">Organization Role</label>
                <div className="space-y-2">
                  {Object.entries(ROLE_CONFIG)
                    .filter(([role]) => role !== 'OWNER')
                    .map(([role, config]) => (
                      <button
                        key={role}
                        onClick={() => setEditRole(role)}
                        className={`w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left ${
                          editRole === role
                            ? `${config.border} ${config.bg}`
                            : 'border-white/[0.04] hover:border-white/[0.08] bg-white/[0.01]'
                        }`}
                      >
                        <div>
                          <p className={`text-sm font-medium ${editRole === role ? config.color : 'text-white/70'}`}>
                            {config.label}
                          </p>
                          <p className="text-xs text-white/40">{config.description}</p>
                        </div>
                      </button>
                    ))}
                </div>
              </div>

              {/* Pipeline Access */}
              {editRole !== 'ADMIN' && (
                <div>
                  <label className="block text-sm font-medium text-white/60 mb-2">Pipeline Access</label>
                  <div className="space-y-2 max-h-40 overflow-y-auto">
                    {pipelines.map((pipeline) => {
                      const access = editPipelineAccess.find(p => p.pipelineId === pipeline.id);
                      return (
                        <div
                          key={pipeline.id}
                          className="flex items-center justify-between p-3 bg-white/[0.01] border border-white/[0.04] rounded-lg"
                        >
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-emerald-500" />
                            <span className="text-sm text-white/80">{pipeline.name}</span>
                          </div>
                          <select
                            value={access?.accessLevel || ''}
                            onChange={(e) => toggleEditPipelineAccess(pipeline.id, e.target.value)}
                            className="px-3 py-1.5 bg-white/[0.02] border border-white/[0.06] rounded-md text-xs text-white/70 focus:outline-none focus:border-rose-500/50"
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
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-white/[0.06]">
              <button
                onClick={() => setShowMemberModal(false)}
                className="px-4 py-2 text-sm text-white/50 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleUpdateMember}
                disabled={saving}
                className="px-5 py-2 bg-gradient-to-r from-rose-600 to-orange-600 hover:from-rose-500 hover:to-orange-500 text-white text-sm font-medium rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
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
