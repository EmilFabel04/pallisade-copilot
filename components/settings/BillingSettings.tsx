'use client';

import { useState, useEffect } from 'react';
import { CreditCard, Coins, FileText } from 'lucide-react';

interface Subscription {
  plan: string;
  status: string;
  currentPeriodEnd: string;
  tokenAllowance: number;
  storageAllowanceGb: number;
  memberAllowance: number;
}

interface CreditPurchase {
  id: string;
  tokensAmount: number;
  pricePaid: number;
  createdAt: string;
}

interface BillingData {
  subscription: Subscription | null;
  usage: {
    tokensUsed: number;
    storageUsedGb: number;
    memberCount: number;
  };
  credits: {
    tokensRemaining: number;
    purchases: CreditPurchase[];
  };
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toString();
}

function UsageBar({ label, used, total, unit }: { label: string; used: number; total: number; unit?: string }) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const isHigh = pct >= 80;
  const isOver = pct >= 100;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] text-[var(--text-tertiary)]">{label}</span>
        <span className="text-[13px] text-[var(--text)]">
          {unit === 'tokens' ? formatTokens(used) : used.toFixed(1)} / {unit === 'tokens' ? formatTokens(total) : total}{unit === 'GB' ? ' GB' : ''}
        </span>
      </div>
      <div className="h-2 rounded-full bg-[var(--overlay-medium)]">
        <div
          className={`h-full rounded-full transition-all ${isOver ? 'bg-red-500' : isHigh ? 'bg-amber-500' : 'bg-[var(--accent)]'}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
    </div>
  );
}

export default function BillingSettings() {
  const [data, setData] = useState<BillingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/billing/subscription')
      .then((r) => r.ok ? r.json() : null)
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  const handleCheckout = async (plan: string) => {
    setActionLoading(plan);
    try {
      const res = await fetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan }),
      });
      const { url } = await res.json();
      if (url) window.location.href = url;
    } finally {
      setActionLoading(null);
    }
  };

  const handleCreditPurchase = async (block: string) => {
    setActionLoading(`credit-${block}`);
    try {
      const res = await fetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'credit', block }),
      });
      const { url } = await res.json();
      if (url) window.location.href = url;
    } finally {
      setActionLoading(null);
    }
  };

  const handleCancelSubscription = async () => {
    if (!confirm('Are you sure you want to cancel your subscription? You will retain access until the end of your billing period.')) return;
    setActionLoading('cancel');
    try {
      const res = await fetch('/api/billing/portal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'cancel' }),
      });
      if (res.ok) {
        window.location.reload();
      }
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-6 h-6 red-spinner" />
      </div>
    );
  }

  const sub = data?.subscription;
  const usage = data?.usage;
  const credits = data?.credits;

  // No subscription — show plan selection
  if (!sub) {
    return (
      <div className="space-y-6">
        <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
          <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
            <CreditCard size={16} className="text-[var(--muted)]" /> Choose a Plan
          </h2>
          <p className="text-[13px] text-[var(--muted)] mb-6">Select a plan to activate billing and unlock the full platform.</p>

          <div className="grid grid-cols-2 gap-4">
            {/* Growth */}
            <div className="p-5 rounded-xl border border-[var(--subtle-border)] bg-[var(--overlay-faint)] space-y-3">
              <div>
                <p className="text-[16px] font-semibold text-[var(--text)]">Growth</p>
                <p className="text-[24px] font-bold text-[var(--text)] mt-1">$1,500<span className="text-[14px] font-normal text-[var(--muted)]">/mo</span></p>
              </div>
              <ul className="text-[13px] text-[var(--muted)] space-y-1">
                <li>5M tokens / month</li>
                <li>100 GB storage</li>
                <li>5 team members</li>
              </ul>
              <button
                onClick={() => handleCheckout('GROWTH')}
                disabled={!!actionLoading}
                className="w-full py-2.5 bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
              >
                {actionLoading === 'GROWTH' ? 'Redirecting...' : 'Get Started'}
              </button>
            </div>

            {/* Business */}
            <div className="p-5 rounded-xl border border-[var(--accent)]/30 bg-[var(--accent)]/5 space-y-3">
              <div>
                <p className="text-[16px] font-semibold text-[var(--text)]">Business</p>
                <p className="text-[24px] font-bold text-[var(--text)] mt-1">$3,000<span className="text-[14px] font-normal text-[var(--muted)]">/mo</span></p>
              </div>
              <ul className="text-[13px] text-[var(--muted)] space-y-1">
                <li>20M tokens / month</li>
                <li>500 GB storage</li>
                <li>15 team members</li>
              </ul>
              <button
                onClick={() => handleCheckout('BUSINESS')}
                disabled={!!actionLoading}
                className="w-full py-2.5 bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
              >
                {actionLoading === 'BUSINESS' ? 'Redirecting...' : 'Get Started'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Active subscription — show current plan + usage
  const statusColor: Record<string, string> = {
    ACTIVE: 'bg-emerald-500/15 text-emerald-400',
    PAST_DUE: 'bg-red-500/15 text-red-400',
    CANCELED: 'bg-zinc-500/15 text-zinc-400',
    TRIALING: 'bg-blue-500/15 text-blue-400',
  };

  return (
    <div className="space-y-6">
      {/* Plan & Usage */}
      <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <h2 className="text-[15px] font-semibold text-[var(--text)] flex items-center gap-2">
              <CreditCard size={16} className="text-[var(--muted)]" /> {sub.plan} Plan
            </h2>
            <span className={`text-xs px-2 py-0.5 rounded-full ${statusColor[sub.status] ?? ''}`}>
              {sub.status}
            </span>
          </div>
          <p className="text-[13px] text-[var(--muted)]">
            Renews {new Date(sub.currentPeriodEnd).toLocaleDateString()}
          </p>
        </div>

        {usage && (
          <div className="space-y-4 mb-6">
            <UsageBar label="Tokens" used={usage.tokensUsed} total={sub.tokenAllowance} unit="tokens" />
            <UsageBar label="Storage" used={usage.storageUsedGb} total={sub.storageAllowanceGb} unit="GB" />
            <UsageBar label="Team Members" used={usage.memberCount} total={sub.memberAllowance} />
          </div>
        )}

        <div className="flex items-center gap-3 pt-4 border-t border-[var(--subtle-border)]">
          <button
            onClick={() => handleCheckout(sub.plan === 'GROWTH' ? 'BUSINESS' : 'GROWTH')}
            disabled={!!actionLoading}
            className="px-4 py-2 text-sm bg-[var(--hover-bg)] hover:bg-[var(--overlay-medium)] text-[var(--text)] rounded-lg transition-colors disabled:opacity-50"
          >
            Change Plan
          </button>
          <button
            onClick={handleCancelSubscription}
            disabled={!!actionLoading}
            className="px-4 py-2 text-sm text-red-400 hover:text-red-300 transition-colors disabled:opacity-50"
          >
            {actionLoading === 'cancel' ? 'Canceling...' : 'Cancel Subscription'}
          </button>
        </div>
      </div>

      {/* Token Credits */}
      <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
        <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
          <Coins size={16} className="text-[var(--muted)]" /> Token Credits
        </h2>

        <p className="text-[13px] text-[var(--muted)] mb-4">
          Credit balance: <span className="text-[var(--text)] font-medium">{formatTokens(credits?.tokensRemaining ?? 0)} tokens</span>
        </p>

        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => handleCreditPurchase('5M')}
            disabled={!!actionLoading}
            className="px-4 py-2 text-sm bg-[var(--hover-bg)] hover:bg-[var(--overlay-medium)] text-[var(--text)] rounded-lg transition-colors disabled:opacity-50"
          >
            {actionLoading === 'credit-5M' ? 'Redirecting...' : 'Buy 5M tokens — $100'}
          </button>
          <button
            onClick={() => handleCreditPurchase('20M')}
            disabled={!!actionLoading}
            className="px-4 py-2 text-sm bg-[var(--hover-bg)] hover:bg-[var(--overlay-medium)] text-[var(--text)] rounded-lg transition-colors disabled:opacity-50"
          >
            {actionLoading === 'credit-20M' ? 'Redirecting...' : 'Buy 20M tokens — $350'}
          </button>
        </div>

        {credits?.purchases && credits.purchases.length > 0 && (
          <div>
            <h3 className="text-[13px] font-medium text-[var(--text-tertiary)] mb-2">Purchase History</h3>
            <div className="space-y-1">
              {credits.purchases.map((p) => (
                <div key={p.id} className="flex items-center justify-between py-2 px-3 rounded-lg bg-[var(--overlay-faint)] text-[13px]">
                  <span className="text-[var(--text)]">{formatTokens(p.tokensAmount)} tokens</span>
                  <div className="flex items-center gap-4">
                    <span className="text-[var(--muted)]">${(p.pricePaid / 100).toFixed(2)}</span>
                    <span className="text-[var(--text-faint)]">{new Date(p.createdAt).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Invoices */}
      <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
        <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
          <FileText size={16} className="text-[var(--muted)]" /> Invoices
        </h2>
        <p className="text-[13px] text-[var(--muted)]">
          Invoice receipts are sent to your email after each payment.
        </p>
      </div>
    </div>
  );
}
