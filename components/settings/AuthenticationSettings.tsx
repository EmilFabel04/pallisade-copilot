'use client';

import { useState, useEffect } from 'react';
import { cachedFetch } from '@/lib/fetch-cache';
import { Shield, Users, AlertTriangle, Loader2 } from 'lucide-react';

interface MemberAuthInfo {
  id: string;
  name: string | null;
  email: string;
  role: string;
  providers: string[];
  hasPassword: boolean;
}

export default function AuthenticationSettings() {
  const [authPolicy, setAuthPolicy] = useState<'FLEXIBLE' | 'SSO_ONLY'>('FLEXIBLE');
  const [graceUntil, setGraceUntil] = useState<string | null>(null);
  const [members, setMembers] = useState<MemberAuthInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [isOwner, setIsOwner] = useState(false);
  const [policyError, setPolicyError] = useState('');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    try {
      const orgRes = await cachedFetch('/api/organization');
      if (orgRes.ok) {
        const orgData = await orgRes.json();
        setAuthPolicy(orgData.authPolicy || 'FLEXIBLE');
        setGraceUntil(orgData.authPolicyGraceUntil);
        setIsOwner(orgData.userRole === 'OWNER');
      }

      const membersRes = await cachedFetch('/api/team/members/auth-status');
      if (membersRes.ok) {
        const membersData = await membersRes.json();
        setMembers(membersData.members);
      }
    } catch (err) {
      console.error('Failed to fetch auth settings:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSavePolicy = async (newPolicy: 'FLEXIBLE' | 'SSO_ONLY') => {
    setPolicyError('');

    if (newPolicy === 'SSO_ONLY') {
      const confirmed = window.confirm(
        'Enabling SSO-only will prevent members from using password login. ' +
        'Members without a linked Google, GitHub, or Microsoft account may be locked out. Continue?'
      );
      if (!confirmed) return;
    }

    setSaving(true);
    try {
      const res = await fetch('/api/organization', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ authPolicy: newPolicy }),
      });
      if (res.ok) {
        setAuthPolicy(newPolicy);
      } else {
        const data = await res.json();
        setPolicyError(data.error || 'Failed to update policy');
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="animate-spin text-[var(--muted)]" size={24} />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Auth Policy Section */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Shield size={18} className="text-[var(--accent)]" />
          <h3 className="text-lg font-medium">Authentication Policy</h3>
        </div>
        <p className="text-sm text-[var(--muted)]">
          Control how members of your organization can sign in. Supported sign-in methods:
          email &amp; password, Google, GitHub, and Microsoft.
        </p>

        <div className="flex gap-3">
          <button
            onClick={() => handleSavePolicy('FLEXIBLE')}
            disabled={!isOwner || saving}
            className={`flex-1 p-4 rounded-lg border text-left ${
              authPolicy === 'FLEXIBLE'
                ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                : 'border-[var(--subtle-border)] hover:border-[var(--muted)]'
            }`}
          >
            <div className="font-medium text-sm">Flexible</div>
            <div className="text-xs text-[var(--muted)] mt-1">
              Members can use password or OAuth
            </div>
          </button>
          <button
            onClick={() => handleSavePolicy('SSO_ONLY')}
            disabled={!isOwner || saving}
            className={`flex-1 p-4 rounded-lg border text-left ${
              authPolicy === 'SSO_ONLY'
                ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                : 'border-[var(--subtle-border)] hover:border-[var(--muted)]'
            }`}
          >
            <div className="font-medium text-sm">Require SSO</div>
            <div className="text-xs text-[var(--muted)] mt-1">
              Password login disabled for all members
            </div>
          </button>
        </div>

        {authPolicy === 'SSO_ONLY' && graceUntil && new Date(graceUntil) > new Date() && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-yellow-950/40 border border-yellow-900/40 text-yellow-400 text-sm">
            <AlertTriangle size={16} />
            Grace period active until {new Date(graceUntil).toLocaleDateString()}. Password login still works.
          </div>
        )}

        {policyError && (
          <div className="p-3 rounded-lg bg-red-950/40 border border-red-900/40 text-red-400 text-sm">
            {policyError}
          </div>
        )}
      </div>

      {/* Member Auth Status Section */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Users size={18} className="text-[var(--accent)]" />
          <h3 className="text-lg font-medium">Member Auth Status</h3>
        </div>
        <p className="text-sm text-[var(--muted)]">
          Shows which authentication methods each member has linked.
        </p>

        {members.length > 0 ? (
          <div className="border border-[var(--subtle-border)] rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-[var(--overlay-faint)]">
                <tr>
                  <th className="text-left p-3 font-medium">Member</th>
                  <th className="text-left p-3 font-medium">Role</th>
                  <th className="text-left p-3 font-medium">Auth Methods</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.id} className="border-t border-[var(--subtle-border)]">
                    <td className="p-3">
                      <div>{m.name || m.email}</div>
                      <div className="text-xs text-[var(--muted)]">{m.email}</div>
                    </td>
                    <td className="p-3 text-[var(--muted)]">{m.role}</td>
                    <td className="p-3">
                      <div className="flex gap-1 flex-wrap">
                        {m.hasPassword && (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
                            Password
                          </span>
                        )}
                        {m.providers.map((p) => (
                          <span key={p} className="px-2 py-0.5 rounded-full text-xs bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
                            {p}
                          </span>
                        ))}
                        {!m.hasPassword && m.providers.length === 0 && (
                          <span className="text-xs text-red-400">No auth method</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">Loading member data...</p>
        )}
      </div>
    </div>
  );
}
