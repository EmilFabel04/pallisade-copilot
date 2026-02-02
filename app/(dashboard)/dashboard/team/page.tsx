'use client';

import { useState } from 'react';

interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: 'OWNER' | 'ADMIN' | 'MEMBER' | 'VIEWER';
  status: 'ACTIVE' | 'PENDING';
  avatar?: string;
  lastActive?: string;
}

const mockMembers: TeamMember[] = [
  { id: '1', name: 'Emil Fabel', email: 'emil@pallisade.io', role: 'OWNER', status: 'ACTIVE', lastActive: 'Just now' },
  { id: '2', name: 'Sarah Chen', email: 'sarah@pallisade.io', role: 'ADMIN', status: 'ACTIVE', lastActive: '2 hours ago' },
  { id: '3', name: 'Mike Johnson', email: 'mike@pallisade.io', role: 'MEMBER', status: 'ACTIVE', lastActive: 'Yesterday' },
  { id: '4', name: 'alex@company.com', email: 'alex@company.com', role: 'VIEWER', status: 'PENDING', lastActive: undefined },
];

const roleColors: Record<string, { bg: string; text: string }> = {
  OWNER: { bg: 'bg-purple-500/10', text: 'text-purple-400' },
  ADMIN: { bg: 'bg-blue-500/10', text: 'text-blue-400' },
  MEMBER: { bg: 'bg-emerald-500/10', text: 'text-emerald-400' },
  VIEWER: { bg: 'bg-white/10', text: 'text-white/60' },
};

export default function TeamPage() {
  const [members, setMembers] = useState<TeamMember[]>(mockMembers);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<'ADMIN' | 'MEMBER' | 'VIEWER'>('MEMBER');

  const handleInvite = () => {
    if (!inviteEmail) return;
    // In production, call API to send invite
    const newMember: TeamMember = {
      id: Date.now().toString(),
      name: inviteEmail,
      email: inviteEmail,
      role: inviteRole,
      status: 'PENDING',
    };
    setMembers([...members, newMember]);
    setInviteEmail('');
    setShowInviteModal(false);
  };

  const getRoleDisplay = (role: string) => {
    return role.charAt(0) + role.slice(1).toLowerCase();
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-1">Team</h1>
          <p className="text-white/50 text-[14px]">
            Manage team members and their access
          </p>
        </div>
        <button
          onClick={() => setShowInviteModal(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-[13px] font-medium transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Invite Member
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <p className="text-2xl font-semibold text-white mb-1">{members.filter(m => m.status === 'ACTIVE').length}</p>
          <p className="text-[13px] text-white/50">Active Members</p>
        </div>
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <p className="text-2xl font-semibold text-white mb-1">{members.filter(m => m.status === 'PENDING').length}</p>
          <p className="text-[13px] text-white/50">Pending Invites</p>
        </div>
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <p className="text-2xl font-semibold text-white mb-1">{members.filter(m => m.role === 'ADMIN' || m.role === 'OWNER').length}</p>
          <p className="text-[13px] text-white/50">Admins</p>
        </div>
      </div>

      {/* Members List */}
      <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-white/[0.06]">
          <h2 className="text-[14px] font-medium text-white">Members</h2>
        </div>
        <div className="divide-y divide-white/[0.04]">
          {members.map((member) => (
            <div key={member.id} className="flex items-center gap-4 px-4 py-3 hover:bg-white/[0.02] transition-colors">
              {/* Avatar */}
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[var(--accent)]/30 to-[var(--accent-2)]/30 flex items-center justify-center text-white font-medium text-[14px]">
                {member.avatar ? (
                  <img src={member.avatar} alt="" className="w-full h-full rounded-full object-cover" />
                ) : (
                  member.name[0].toUpperCase()
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <p className="text-[14px] font-medium text-white truncate">
                  {member.name}
                  {member.status === 'PENDING' && (
                    <span className="ml-2 text-[11px] text-amber-400">(Pending)</span>
                  )}
                </p>
                <p className="text-[12px] text-white/40 truncate">{member.email}</p>
              </div>

              {/* Last Active */}
              {member.lastActive && (
                <div className="hidden sm:block text-[12px] text-white/40">
                  {member.lastActive}
                </div>
              )}

              {/* Role Badge */}
              <div className={`px-2.5 py-1 rounded-full text-[11px] font-medium ${roleColors[member.role].bg} ${roleColors[member.role].text}`}>
                {getRoleDisplay(member.role)}
              </div>

              {/* Actions */}
              <button className="p-2 rounded-lg hover:bg-white/[0.05] text-white/40 hover:text-white transition-colors">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowInviteModal(false)} />
          <div className="relative w-full max-w-md bg-[#080808] rounded-2xl border border-white/[0.06] shadow-2xl">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
              <h2 className="text-lg font-semibold text-white">Invite Team Member</h2>
              <button
                onClick={() => setShowInviteModal(false)}
                className="p-2 rounded-lg hover:bg-white/[0.05] text-white/50 hover:text-white transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-[13px] font-medium text-white/70 mb-2">Email Address</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@company.com"
                  className="w-full px-4 py-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white placeholder-white/40 focus:outline-none focus:border-white/[0.15] text-[14px]"
                />
              </div>

              <div>
                <label className="block text-[13px] font-medium text-white/70 mb-2">Role</label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as 'ADMIN' | 'MEMBER' | 'VIEWER')}
                  className="w-full px-4 py-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white focus:outline-none focus:border-white/[0.15] text-[14px]"
                >
                  <option value="ADMIN">Admin - Full access</option>
                  <option value="MEMBER">Member - Can edit and chat</option>
                  <option value="VIEWER">Viewer - Read-only access</option>
                </select>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-white/[0.06]">
              <button
                onClick={() => setShowInviteModal(false)}
                className="px-4 py-2 rounded-lg text-white/70 hover:text-white text-[13px] font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleInvite}
                disabled={!inviteEmail}
                className="px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 disabled:hover:bg-[var(--accent)] text-white text-[13px] font-medium transition-colors"
              >
                Send Invite
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
