'use client';

import { useState } from 'react';
import {
  UserPlus,
  Mail,
  RefreshCw,
  CheckCircle,
  Copy,
  X,
  Shield,
  Crown,
  Star,
  User,
  Eye,
} from 'lucide-react';

interface InviteTeamMemberModalProps {
  isOpen: boolean;
  onClose: () => void;
  organizationName?: string;
  onInviteSent?: () => void;
}

const ROLE_OPTIONS = [
  {
    value: 'ADMIN',
    label: 'Admin',
    description: 'Manage team and settings',
    icon: Shield,
    color: 'text-purple-400',
    bg: 'bg-purple-400/10',
  },
  {
    value: 'MANAGER',
    label: 'Manager',
    description: 'Run scans, manage contracts',
    icon: Star,
    color: 'text-blue-400',
    bg: 'bg-blue-400/10',
  },
  {
    value: 'ENGINEER',
    label: 'Engineer',
    description: 'Run scans, use sandbox',
    icon: User,
    color: 'text-emerald-400',
    bg: 'bg-emerald-400/10',
  },
  {
    value: 'VIEWER',
    label: 'Viewer',
    description: 'Read-only access',
    icon: Eye,
    color: 'text-slate-400',
    bg: 'bg-slate-400/10',
  },
];

export function InviteTeamMemberModal({
  isOpen,
  onClose,
  organizationName = 'your organization',
  onInviteSent,
}: InviteTeamMemberModalProps) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('ENGINEER');
  const [personalNote, setPersonalNote] = useState('');
  const [inviting, setInviting] = useState(false);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleInvite = async () => {
    if (!email) return;

    try {
      setInviting(true);
      setError(null);

      const res = await fetch('/api/team/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          role,
          personalNote: personalNote || undefined,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error);

      setInviteLink(data.inviteLink);
      onInviteSent?.();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setInviting(false);
    }
  };

  const copyInviteLink = () => {
    if (inviteLink) {
      navigator.clipboard.writeText(inviteLink);
    }
  };

  const handleClose = () => {
    setEmail('');
    setRole('ENGINEER');
    setPersonalNote('');
    setInviteLink(null);
    setError(null);
    onClose();
  };

  if (!isOpen) return null;

  const selectedRole = ROLE_OPTIONS.find((r) => r.value === role);

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md p-6 shadow-2xl">
        {!inviteLink ? (
          <>
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-violet-500/10">
                  <UserPlus className="w-6 h-6 text-violet-400" />
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-white">Invite Team Member</h3>
                  <p className="text-sm text-slate-400">Add someone to {organizationName}</p>
                </div>
              </div>
              <button
                onClick={handleClose}
                className="p-2 hover:bg-slate-800 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-slate-400" />
              </button>
            </div>

            {/* Error */}
            {error && (
              <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
                {error}
              </div>
            )}

            {/* Form */}
            <div className="space-y-4">
              {/* Email */}
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">
                  Email Address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="colleague@company.com"
                  className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg focus:ring-2 focus:ring-violet-500 focus:border-transparent outline-none text-white placeholder:text-slate-500"
                  autoFocus
                />
              </div>

              {/* Role Selection */}
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  Role
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {ROLE_OPTIONS.map((option) => {
                    const Icon = option.icon;
                    const isSelected = role === option.value;
                    return (
                      <button
                        key={option.value}
                        onClick={() => setRole(option.value)}
                        className={`p-3 rounded-lg border transition-all text-left ${
                          isSelected
                            ? 'border-violet-500 bg-violet-500/10 ring-1 ring-violet-500/50'
                            : 'border-slate-700 hover:border-slate-600 bg-slate-800/50'
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <Icon className={`w-4 h-4 ${option.color}`} />
                          <span className="font-medium text-white text-sm">{option.label}</span>
                        </div>
                        <p className="text-xs text-slate-400">{option.description}</p>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Personal Note */}
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">
                  Personal Note <span className="text-slate-500 font-normal">(optional)</span>
                </label>
                <textarea
                  value={personalNote}
                  onChange={(e) => setPersonalNote(e.target.value)}
                  placeholder="Hey! Join us on Pallisade to help monitor our data quality..."
                  rows={2}
                  className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg focus:ring-2 focus:ring-violet-500 focus:border-transparent outline-none resize-none text-white placeholder:text-slate-500"
                />
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-3 mt-6">
              <button
                onClick={handleClose}
                className="flex-1 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 rounded-lg font-medium text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleInvite}
                disabled={!email || inviting}
                className="flex-1 px-4 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 rounded-lg font-medium text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
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
            {/* Success State */}
            <div className="text-center mb-6">
              <div className="w-16 h-16 rounded-full bg-emerald-500/10 flex items-center justify-center mx-auto mb-4">
                <CheckCircle className="w-8 h-8 text-emerald-400" />
              </div>
              <h3 className="text-xl font-semibold text-white">Invite Sent!</h3>
              <p className="text-sm text-slate-400 mt-1">
                Share this link with <span className="text-white">{email}</span>
              </p>
            </div>

            {/* Invite Link */}
            <div className="bg-slate-800 rounded-lg p-3 flex items-center gap-2 mb-4">
              <input
                type="text"
                value={inviteLink}
                readOnly
                className="flex-1 bg-transparent text-sm text-slate-300 outline-none"
              />
              <button
                onClick={copyInviteLink}
                className="p-2 hover:bg-slate-700 rounded-lg transition-colors text-slate-400 hover:text-white"
                title="Copy link"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>

            {/* Role Badge */}
            {selectedRole && (
              <div className="flex items-center justify-center gap-2 mb-6">
                <span className="text-sm text-slate-400">Invited as</span>
                <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium ${selectedRole.bg} ${selectedRole.color}`}>
                  <selectedRole.icon className="w-3.5 h-3.5" />
                  {selectedRole.label}
                </span>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setEmail('');
                  setInviteLink(null);
                }}
                className="flex-1 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 rounded-lg font-medium text-white transition-colors"
              >
                Invite Another
              </button>
              <button
                onClick={handleClose}
                className="flex-1 px-4 py-2.5 bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 rounded-lg font-medium text-white transition-all"
              >
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
