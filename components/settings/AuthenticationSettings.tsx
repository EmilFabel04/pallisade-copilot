'use client';

import { useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import { cachedFetch } from '@/lib/fetch-cache';
import { Shield, Globe, Users, AlertTriangle, CheckCircle, XCircle, Loader2 } from 'lucide-react';

interface OidcConfig {
  id: string;
  issuerUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
  displayName: string;
  enabled: boolean;
}

interface MemberAuthInfo {
  id: string;
  name: string | null;
  email: string;
  role: string;
  providers: string[];
  hasPassword: boolean;
}

export default function AuthenticationSettings() {
  const { data: session } = useSession();
  const [authPolicy, setAuthPolicy] = useState<'FLEXIBLE' | 'SSO_ONLY'>('FLEXIBLE');
  const [graceUntil, setGraceUntil] = useState<string | null>(null);
  const [oidcConfig, setOidcConfig] = useState<OidcConfig | null>(null);
  const [members, setMembers] = useState<MemberAuthInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; error?: string } | null>(null);
  const [isOwner, setIsOwner] = useState(false);

  // Form state for OIDC config
  const [oidcForm, setOidcForm] = useState({
    issuerUrl: '',
    clientId: '',
    clientSecret: '',
    scopes: 'openid email profile',
    displayName: 'SSO',
    enabled: true,
  });

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [orgRes, oidcRes] = await Promise.all([
        cachedFetch('/api/organization'),
        cachedFetch('/api/organization/oidc'),
      ]);

      if (orgRes.ok) {
        const orgData = await orgRes.json();
        setAuthPolicy(orgData.authPolicy || 'FLEXIBLE');
        setGraceUntil(orgData.authPolicyGraceUntil);
        setIsOwner(orgData.userRole === 'OWNER');
      }

      if (oidcRes.ok) {
        const oidcData = await oidcRes.json();
        if (oidcData.config) {
          setOidcConfig(oidcData.config);
          setOidcForm({
            issuerUrl: oidcData.config.issuerUrl,
            clientId: oidcData.config.clientId,
            clientSecret: '',
            scopes: oidcData.config.scopes,
            displayName: oidcData.config.displayName,
            enabled: oidcData.config.enabled,
          });
        }
      }

      // Fetch member auth status
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

  const [policyError, setPolicyError] = useState('');

  const handleSavePolicy = async (newPolicy: 'FLEXIBLE' | 'SSO_ONLY') => {
    setPolicyError('');

    // Safety checks before enabling SSO_ONLY
    if (newPolicy === 'SSO_ONLY') {
      // Check 1: At least one OAuth provider or OIDC must be configured
      const hasOAuth = oidcConfig?.enabled; // Platform providers checked server-side
      // Check 2: Owner must have a linked OAuth account (checked server-side)
      // Check 3: Warn about members without OAuth
      if (!hasOAuth && !oidcConfig) {
        setPolicyError('Configure at least one OAuth provider or OIDC before enabling SSO.');
        return;
      }

      const confirmed = window.confirm(
        'Enabling SSO-only will prevent members from using password login. ' +
        'Members without a linked OAuth account may be locked out. Continue?'
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

  const handleSaveOidc = async () => {
    setSaving(true);
    try {
      const res = await fetch('/api/organization/oidc', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(oidcForm),
      });
      if (res.ok) {
        const data = await res.json();
        setOidcConfig(data.config);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setTestResult(null);
    try {
      const res = await fetch('/api/organization/oidc/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ issuerUrl: oidcForm.issuerUrl }),
      });
      const data = await res.json();
      setTestResult(data);
    } catch {
      setTestResult({ success: false, error: 'Failed to test connection' });
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
          Control how members of your organization can sign in.
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

      {/* OIDC Config Section */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Globe size={18} className="text-[var(--accent)]" />
          <h3 className="text-lg font-medium">OIDC Provider</h3>
        </div>
        <p className="text-sm text-[var(--muted)]">
          Configure a custom OIDC identity provider for your organization (e.g., Okta, Auth0).
        </p>

        {isOwner ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">Issuer URL</label>
                <input
                  type="url"
                  value={oidcForm.issuerUrl}
                  onChange={(e) => setOidcForm({ ...oidcForm, issuerUrl: e.target.value })}
                  placeholder="https://your-org.okta.com"
                  className="auth-input w-full"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Display Name</label>
                <input
                  type="text"
                  value={oidcForm.displayName}
                  onChange={(e) => setOidcForm({ ...oidcForm, displayName: e.target.value })}
                  placeholder="SSO"
                  className="auth-input w-full"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">Client ID</label>
                <input
                  type="text"
                  value={oidcForm.clientId}
                  onChange={(e) => setOidcForm({ ...oidcForm, clientId: e.target.value })}
                  className="auth-input w-full"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Client Secret</label>
                <input
                  type="password"
                  value={oidcForm.clientSecret}
                  onChange={(e) => setOidcForm({ ...oidcForm, clientSecret: e.target.value })}
                  placeholder={oidcConfig ? '••••••••' : ''}
                  className="auth-input w-full"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Scopes</label>
              <input
                type="text"
                value={oidcForm.scopes}
                onChange={(e) => setOidcForm({ ...oidcForm, scopes: e.target.value })}
                className="auth-input w-full"
              />
            </div>

            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={oidcForm.enabled}
                  onChange={(e) => setOidcForm({ ...oidcForm, enabled: e.target.checked })}
                />
                <span className="text-sm">Enabled</span>
              </label>
            </div>

            <div className="flex gap-3">
              <button
                onClick={handleTestConnection}
                disabled={!oidcForm.issuerUrl}
                className="btn btn-secondary"
              >
                Test Connection
              </button>
              <button
                onClick={handleSaveOidc}
                disabled={saving || !oidcForm.issuerUrl || !oidcForm.clientId || !oidcForm.clientSecret}
                className="btn btn-elevated"
              >
                {saving ? 'Saving...' : 'Save OIDC Config'}
              </button>
            </div>

            {testResult && (
              <div className={`flex items-center gap-2 p-3 rounded-lg text-sm ${
                testResult.success
                  ? 'bg-green-950/40 border border-green-900/40 text-green-400'
                  : 'bg-red-950/40 border border-red-900/40 text-red-400'
              }`}>
                {testResult.success ? <CheckCircle size={16} /> : <XCircle size={16} />}
                {testResult.success ? 'Connection successful' : testResult.error}
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">Only organization owners can configure OIDC.</p>
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
