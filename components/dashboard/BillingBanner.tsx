'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, X } from 'lucide-react';

interface UsageData {
  tokensUsed: number;
  tokenAllowance: number;
  status?: string;
}

export default function BillingBanner() {
  const router = useRouter();
  const [data, setData] = useState<UsageData | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/billing/subscription')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.subscription) {
          setData({
            tokensUsed: d.usage?.tokensUsed ?? 0,
            tokenAllowance: d.subscription.tokenAllowance,
            status: d.subscription.status,
          });
        }
      })
      .catch(() => {});
  }, []);

  if (!data) return null;

  let banner: { message: string; color: string; key: string } | null = null;

  if (data.status === 'PAST_DUE') {
    banner = {
      message: 'Payment failed — update your payment method to avoid service interruption.',
      color: 'bg-red-500/10 border-red-500/20 text-red-400',
      key: 'past_due',
    };
  } else if (data.tokenAllowance > 0 && data.tokensUsed >= data.tokenAllowance) {
    banner = {
      message: 'Token limit reached. Purchase more tokens or wait for your renewal.',
      color: 'bg-amber-500/10 border-amber-500/20 text-amber-400',
      key: 'token_100',
    };
  } else if (data.tokenAllowance > 0 && data.tokensUsed >= data.tokenAllowance * 0.8) {
    banner = {
      message: `You've used ${Math.round((data.tokensUsed / data.tokenAllowance) * 100)}% of your monthly tokens.`,
      color: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
      key: 'token_80',
    };
  }

  if (!banner || dismissed === banner.key) return null;

  return (
    <div className={`flex items-center justify-between px-4 py-2 border-b text-[13px] ${banner.color}`}>
      <div className="flex items-center gap-2">
        <AlertTriangle size={14} />
        <span>{banner.message}</span>
        <button
          onClick={() => router.push('/dashboard/settings?tab=billing')}
          className="ml-1 underline hover:no-underline"
        >
          View billing
        </button>
      </div>
      <button onClick={() => setDismissed(banner!.key)} className="p-1 hover:opacity-70">
        <X size={14} />
      </button>
    </div>
  );
}
