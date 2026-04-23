'use client';

import { useState, useEffect } from 'react';
import { signIn } from 'next-auth/react';
import { Link2, Unlink, Loader2 } from 'lucide-react';

interface LinkedAccount {
  id: string;
  provider: string;
  providerAccountId: string;
}

const PROVIDER_LABELS: Record<string, string> = {
  google: 'Google',
  github: 'GitHub',
  'microsoft-entra-id': 'Microsoft',
};

export default function ConnectedAccounts() {
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [hasPassword, setHasPassword] = useState(false);
  const [loading, setLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchAccounts();
  }, []);

  const fetchAccounts = async () => {
    try {
      const res = await fetch('/api/user/accounts');
      if (res.ok) {
        const data = await res.json();
        setAccounts(data.accounts);
        setHasPassword(data.hasPassword);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async (accountId: string) => {
    setDisconnecting(accountId);
    setError('');
    try {
      const res = await fetch('/api/user/accounts', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accountId }),
      });
      if (res.ok) {
        setAccounts(accounts.filter((a) => a.id !== accountId));
      } else {
        const data = await res.json();
        setError(data.error);
      }
    } finally {
      setDisconnecting(null);
    }
  };

  const handleConnect = (provider: string) => {
    signIn(provider, { callbackUrl: '/dashboard/settings' });
  };

  const linkedProviders = new Set(accounts.map((a) => a.provider));
  const availableProviders = Object.keys(PROVIDER_LABELS).filter(
    (p) => !linkedProviders.has(p)
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="animate-spin text-[var(--muted)]" size={20} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Link2 size={18} className="text-[var(--accent)]" />
        <h3 className="text-lg font-medium">Connected Accounts</h3>
      </div>
      <p className="text-sm text-[var(--muted)]">
        Manage your linked sign-in providers.
      </p>

      {error && (
        <div className="p-3 rounded-lg bg-red-950/40 border border-red-900/40 text-red-400 text-sm">
          {error}
        </div>
      )}

      <div className="space-y-2">
        {accounts.map((account) => (
          <div
            key={account.id}
            className="flex items-center justify-between p-3 rounded-lg border border-[var(--subtle-border)]"
          >
            <span className="text-sm font-medium">
              {PROVIDER_LABELS[account.provider] || account.provider}
            </span>
            <button
              onClick={() => handleDisconnect(account.id)}
              disabled={disconnecting === account.id}
              className="btn btn-secondary btn-sm flex items-center gap-1"
            >
              {disconnecting === account.id ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Unlink size={14} />
              )}
              Disconnect
            </button>
          </div>
        ))}

        {hasPassword && (
          <div className="flex items-center justify-between p-3 rounded-lg border border-[var(--subtle-border)]">
            <span className="text-sm font-medium">Password</span>
            <span className="text-xs text-[var(--muted)]">Active</span>
          </div>
        )}
      </div>

      {availableProviders.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-[var(--muted)]">Connect another provider:</p>
          <div className="flex gap-2">
            {availableProviders.map((provider) => (
              <button
                key={provider}
                onClick={() => handleConnect(provider)}
                className="btn btn-secondary btn-sm"
              >
                Connect {PROVIDER_LABELS[provider]}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
