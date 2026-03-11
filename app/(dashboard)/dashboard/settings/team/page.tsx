'use client';

import { useState, useEffect } from 'react';
import { cachedFetch } from '@/lib/fetch-cache';
import {
  Users,
  UserPlus,
  Shield,
  Crown,
  Star,
  User,
  Eye,
  Mail,
  MoreVertical,
  Trash2,
  Edit,
  Clock,
  CheckCircle,
  XCircle,
  Copy,
  RefreshCw,
  Building2,
  Activity,
  AlertCircle,
} from 'lucide-react';

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
}

interface PendingInvite {
  id: string;
  email: string;
  role: string;
  inviterName: string | null;
  createdAt: string;
  expiresAt: string;
}

interface TeamData {
  organization: {
    id: string;
    name: string;
    logo: string | null;
    plan: string;
    createdAt: string;
  };
  members: TeamMember[];
  pendingInvites: PendingInvite[];
  activity: {
    totalMembers: number;
    activeMembers: number;
    scansLast30Days: number;
    fixesLast30Days: number;
  };
  permissions: {
    canInvite: boolean;
    canRemove: boolean;
    canEditRoles: boolean;
  };
}

const ROLE_CONFIG: Record<string, { icon: any; color: string; bg: string; description: string }> = {
  OWNER: {
    icon: Crown,
    color: 'text-amber-400',
    bg: 'bg-amber-400/10',
    description: 'Full control over organization',
  },
  ADMIN: {
    icon: Shield,
    color: 'text-purple-400',
    bg: 'bg-purple-400/10',
    description: 'Manage team and settings',
  },
  MANAGER: {
    icon: Star,
    color: 'text-blue-400',
    bg: 'bg-blue-400/10',
    description: 'Run scans, manage contracts',
  },
  ENGINEER: {
    icon: User,
    color: 'text-emerald-400',
    bg: 'bg-emerald-400/10',
    description: 'Run scans, use sandbox',
  },
  VIEWER: {
    icon: Eye,
    color: 'text-slate-400',
    bg: 'bg-slate-400/10',
    description: 'Read-only access',
  },
};

export default function TeamSettingsPage() {
  const [teamData, setTeamData] = useState<TeamData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Invite modal state
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<string>('ENGINEER');
  const [inviteNote, setInviteNote] = useState('');
  const [inviting, setInviting] = useState(false);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  
  // Edit member modal state
  const [editingMember, setEditingMember] = useState<TeamMember | null>(null);
  const [editRole, setEditRole] = useState<string>('');
  const [saving, setSaving] = useState(false);
  
  // Dropdown state
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  useEffect(() => {
    fetchTeamData();
  }, []);

  const fetchTeamData = async () => {
    try {
      setLoading(true);
      const res = await cachedFetch('/api/team');
      if (!res.ok) throw new Error('Failed to fetch team data');
      const data = await res.json();
      setTeamData(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleInvite = async () => {
    if (!inviteEmail) return;
    
    try {
      setInviting(true);
      const res = await fetch('/api/team/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: inviteEmail,
          role: inviteRole,
          personalNote: inviteNote || undefined,
        }),
      });
      
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      
      setInviteLink(data.inviteLink);
      await fetchTeamData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setInviting(false);
    }
  };

  const handleRevokeInvite = async (inviteId: string) => {
    if (!confirm('Are you sure you want to revoke this invite?')) return;
    
    try {
      const res = await fetch(`/api/team/invite?id=${inviteId}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Failed to revoke invite');
      await fetchTeamData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleUpdateMember = async (memberId: string, role: string) => {
    try {
      setSaving(true);
      const res = await fetch(`/api/team/members/${memberId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      });
      
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      
      setEditingMember(null);
      await fetchTeamData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveMember = async (memberId: string, memberName: string) => {
    if (!confirm(`Are you sure you want to remove ${memberName || 'this member'} from the team?`)) return;
    
    try {
      const res = await fetch(`/api/team/members/${memberId}`, {
        method: 'DELETE',
      });
      
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      
      await fetchTeamData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const copyInviteLink = () => {
    if (inviteLink) {
      navigator.clipboard.writeText(inviteLink);
    }
  };

  const resetInviteModal = () => {
    setShowInviteModal(false);
    setInviteEmail('');
    setInviteRole('ENGINEER');
    setInviteNote('');
    setInviteLink(null);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="w-8 h-8 red-spinner" />
      </div>
    );
  }

  if (error || !teamData) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-4" />
          <p className="text-slate-400">{error || 'Failed to load team data'}</p>
          <button
            onClick={fetchTeamData}
            className="mt-4 px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  const { organization, members, pendingInvites, activity, permissions } = teamData;

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white p-6">
      {/* Header */}
      <div className="max-w-6xl mx-auto mb-8">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <Building2 className="w-8 h-8 text-violet-400" />
              <h1 className="text-3xl font-bold">{organization.name}</h1>
              <span className="px-2 py-0.5 text-xs font-medium bg-violet-500/20 text-violet-300 rounded-full uppercase">
                {organization.plan}
              </span>
            </div>
            <p className="text-slate-400">Manage your team members and permissions</p>
          </div>
          
          {permissions.canInvite && (
            <button
              onClick={() => setShowInviteModal(true)}
              className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 rounded-lg font-medium transition-all shadow-lg shadow-violet-500/25"
            >
              <UserPlus className="w-4 h-4" />
              Invite Team Member
            </button>
          )}
        </div>
      </div>

      {/* Activity Stats */}
      <div className="max-w-6xl mx-auto mb-8">
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Team Members', value: activity.totalMembers, icon: Users, color: 'violet' },
            { label: 'Active (30d)', value: activity.activeMembers, icon: Activity, color: 'emerald' },
            { label: 'Scans Run', value: activity.scansLast30Days, icon: RefreshCw, color: 'blue' },
            { label: 'Fixes Applied', value: activity.fixesLast30Days, icon: CheckCircle, color: 'amber' },
          ].map((stat, i) => (
            <div key={i} className="bg-slate-900/50 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg bg-${stat.color}-500/10`}>
                  <stat.icon className={`w-5 h-5 text-${stat.color}-400`} />
                </div>
                <div>
                  <p className="text-2xl font-bold">{stat.value}</p>
                  <p className="text-xs text-slate-500">{stat.label}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Team Members */}
      <div className="max-w-6xl mx-auto mb-8">
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-800">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Users className="w-5 h-5 text-violet-400" />
              Team Members
              <span className="text-sm text-slate-500 font-normal">({members.length})</span>
            </h2>
          </div>
          
          <div className="divide-y divide-slate-800/50">
            {members.map((member) => {
              const roleConfig = ROLE_CONFIG[member.role];
              const RoleIcon = roleConfig.icon;
              
              return (
                <div key={member.id} className="px-6 py-4 hover:bg-slate-800/30 transition-colors">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      {/* Avatar */}
                      <div className="relative">
                        {member.image ? (
                          <img
                            src={member.image}
                            alt={member.name || ''}
                            className="w-10 h-10 rounded-full"
                          />
                        ) : (
                          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center text-white font-medium">
                            {(member.name || member.email)[0].toUpperCase()}
                          </div>
                        )}
                        {member.status === 'ACTIVE' && (
                          <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-emerald-500 rounded-full border-2 border-slate-900" />
                        )}
                      </div>
                      
                      {/* Info */}
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{member.name || 'No name'}</span>
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${roleConfig.bg} ${roleConfig.color}`}>
                            <RoleIcon className="w-3 h-3" />
                            {member.role}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-sm text-slate-400">
                          <span>{member.email}</span>
                          {member.title && (
                            <>
                              <span>•</span>
                              <span>{member.title}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                    
                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      <div className="text-xs text-slate-500 mr-4">
                        Joined {new Date(member.joinedAt).toLocaleDateString()}
                      </div>
                      
                      {(permissions.canEditRoles || permissions.canRemove) && member.role !== 'OWNER' && (
                        <div className="relative">
                          <button
                            onClick={() => setOpenDropdown(openDropdown === member.id ? null : member.id)}
                            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
                          >
                            <MoreVertical className="w-4 h-4 text-slate-400" />
                          </button>
                          
                          {openDropdown === member.id && (
                            <div className="absolute right-0 top-full mt-1 w-48 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-10 py-1">
                              {permissions.canEditRoles && (
                                <button
                                  onClick={() => {
                                    setEditingMember(member);
                                    setEditRole(member.role);
                                    setOpenDropdown(null);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-slate-700 flex items-center gap-2"
                                >
                                  <Edit className="w-4 h-4" />
                                  Change Role
                                </button>
                              )}
                              {permissions.canRemove && (
                                <button
                                  onClick={() => {
                                    handleRemoveMember(member.id, member.name || member.email);
                                    setOpenDropdown(null);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-slate-700 text-red-400 flex items-center gap-2"
                                >
                                  <Trash2 className="w-4 h-4" />
                                  Remove
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Pending Invites */}
      {pendingInvites.length > 0 && (
        <div className="max-w-6xl mx-auto mb-8">
          <div className="bg-slate-900/50 border border-slate-800 rounded-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-800">
              <h2 className="text-lg font-semibold flex items-center gap-2">
                <Mail className="w-5 h-5 text-amber-400" />
                Pending Invites
                <span className="text-sm text-slate-500 font-normal">({pendingInvites.length})</span>
              </h2>
            </div>
            
            <div className="divide-y divide-slate-800/50">
              {pendingInvites.map((invite) => (
                <div key={invite.id} className="px-6 py-4 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-full bg-amber-500/10 flex items-center justify-center">
                      <Clock className="w-5 h-5 text-amber-400" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{invite.email}</span>
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_CONFIG[invite.role]?.bg} ${ROLE_CONFIG[invite.role]?.color}`}>
                          {invite.role}
                        </span>
                      </div>
                      <div className="text-sm text-slate-400">
                        Invited by {invite.inviterName || 'team member'} • Expires {new Date(invite.expiresAt).toLocaleDateString()}
                      </div>
                    </div>
                  </div>
                  
                  {permissions.canInvite && (
                    <button
                      onClick={() => handleRevokeInvite(invite.id)}
                      className="p-2 hover:bg-red-500/10 rounded-lg transition-colors text-red-400"
                      title="Revoke invite"
                    >
                      <XCircle className="w-5 h-5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Role Reference */}
      <div className="max-w-6xl mx-auto">
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Shield className="w-5 h-5 text-violet-400" />
            Role Permissions
          </h2>
          
          <div className="grid grid-cols-5 gap-4">
            {Object.entries(ROLE_CONFIG).map(([role, config]) => {
              const Icon = config.icon;
              return (
                <div key={role} className={`p-4 rounded-lg ${config.bg} border border-slate-800`}>
                  <div className="flex items-center gap-2 mb-2">
                    <Icon className={`w-4 h-4 ${config.color}`} />
                    <span className="font-medium">{role}</span>
                  </div>
                  <p className="text-xs text-slate-400">{config.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md p-6 shadow-2xl">
            {!inviteLink ? (
              <>
                <div className="flex items-center gap-3 mb-6">
                  <div className="p-2 rounded-lg bg-violet-500/10">
                    <UserPlus className="w-6 h-6 text-violet-400" />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold">Invite Team Member</h3>
                    <p className="text-sm text-slate-400">Send an invite to join {organization.name}</p>
                  </div>
                </div>
                
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-1.5">
                      Email Address
                    </label>
                    <input
                      type="email"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      placeholder="colleague@company.com"
                      className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg focus:ring-2 focus:ring-violet-500 focus:border-transparent outline-none"
                    />
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-1.5">
                      Role
                    </label>
                    <select
                      value={inviteRole}
                      onChange={(e) => setInviteRole(e.target.value)}
                      className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg focus:ring-2 focus:ring-violet-500 focus:border-transparent outline-none"
                    >
                      <option value="ADMIN">Admin - Manage team and settings</option>
                      <option value="MANAGER">Manager - Run scans, manage contracts</option>
                      <option value="ENGINEER">Engineer - Run scans, use sandbox</option>
                      <option value="VIEWER">Viewer - Read-only access</option>
                    </select>
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-1.5">
                      Personal Note (optional)
                    </label>
                    <textarea
                      value={inviteNote}
                      onChange={(e) => setInviteNote(e.target.value)}
                      placeholder="Hey, join us on Pallisade to help monitor our data quality!"
                      rows={2}
                      className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg focus:ring-2 focus:ring-violet-500 focus:border-transparent outline-none resize-none"
                    />
                  </div>
                </div>
                
                <div className="flex gap-3 mt-6">
                  <button
                    onClick={resetInviteModal}
                    className="flex-1 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 rounded-lg font-medium transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleInvite}
                    disabled={!inviteEmail || inviting}
                    className="flex-1 px-4 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 rounded-lg font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    {inviting ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Sending...
                      </>
                    ) : (
                      <>
                        <Mail className="w-4 h-4" />
                        Send Invite
                      </>
                    )}
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="text-center mb-6">
                  <div className="w-16 h-16 rounded-full bg-emerald-500/10 flex items-center justify-center mx-auto mb-4">
                    <CheckCircle className="w-8 h-8 text-emerald-400" />
                  </div>
                  <h3 className="text-xl font-semibold">Invite Sent!</h3>
                  <p className="text-sm text-slate-400 mt-1">
                    Share this link with {inviteEmail}
                  </p>
                </div>
                
                <div className="bg-slate-800 rounded-lg p-3 flex items-center gap-2 mb-6">
                  <input
                    type="text"
                    value={inviteLink}
                    readOnly
                    className="flex-1 bg-transparent text-sm text-slate-300 outline-none"
                  />
                  <button
                    onClick={copyInviteLink}
                    className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
                    title="Copy link"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
                
                <button
                  onClick={resetInviteModal}
                  className="w-full px-4 py-2.5 bg-slate-800 hover:bg-slate-700 rounded-lg font-medium transition-colors"
                >
                  Done
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Edit Role Modal */}
      {editingMember && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md p-6 shadow-2xl">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 rounded-lg bg-violet-500/10">
                <Edit className="w-6 h-6 text-violet-400" />
              </div>
              <div>
                <h3 className="text-xl font-semibold">Change Role</h3>
                <p className="text-sm text-slate-400">{editingMember.name || editingMember.email}</p>
              </div>
            </div>
            
            <div className="space-y-2 mb-6">
              {Object.entries(ROLE_CONFIG)
                .filter(([role]) => role !== 'OWNER')
                .map(([role, config]) => {
                  const Icon = config.icon;
                  return (
                    <button
                      key={role}
                      onClick={() => setEditRole(role)}
                      className={`w-full p-3 rounded-lg border transition-colors flex items-center gap-3 ${
                        editRole === role
                          ? 'border-violet-500 bg-violet-500/10'
                          : 'border-slate-700 hover:border-slate-600 bg-slate-800/50'
                      }`}
                    >
                      <Icon className={`w-5 h-5 ${config.color}`} />
                      <div className="text-left">
                        <div className="font-medium">{role}</div>
                        <div className="text-xs text-slate-400">{config.description}</div>
                      </div>
                    </button>
                  );
                })}
            </div>
            
            <div className="flex gap-3">
              <button
                onClick={() => setEditingMember(null)}
                className="flex-1 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 rounded-lg font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleUpdateMember(editingMember.id, editRole)}
                disabled={saving || editRole === editingMember.role}
                className="flex-1 px-4 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 rounded-lg font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving ? 'Saving...' : 'Update Role'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Click outside to close dropdown */}
      {openDropdown && (
        <div
          className="fixed inset-0 z-0"
          onClick={() => setOpenDropdown(null)}
        />
      )}
    </div>
  );
}
