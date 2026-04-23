'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '../ui/button';

const DISMISSED_KEY = 'pallisade-setup-banner-dismissed';

type BannerState = 'no-warehouse' | 'no-monitors' | 'complete' | 'loading';

export function SetupBanner() {
  const router = useRouter();
  const [state, setState] = useState<BannerState>('loading');
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' && localStorage.getItem(DISMISSED_KEY)) {
      setDismissed(true);
      return;
    }

    async function checkSetup() {
      try {
        const res = await fetch('/api/pipeline');
        if (!res.ok) {
          setState('no-warehouse');
          return;
        }
        const data = await res.json();
        const pipelines = data.stacks || data.pipelines || [];

        if (pipelines.length === 0) {
          setState('no-warehouse');
          return;
        }

        const hasConfigured = pipelines.some(
          (p: any) => p.status !== 'DRAFT'
        );

        setState(hasConfigured ? 'complete' : 'no-monitors');
      } catch {
        setState('complete');
      }
    }

    checkSetup();
  }, []);

  function handleDismiss() {
    localStorage.setItem(DISMISSED_KEY, 'true');
    setDismissed(true);
  }

  if (dismissed || state === 'loading' || state === 'complete') return null;

  const config = {
    'no-warehouse': {
      title: 'Connect your first warehouse to start monitoring',
      action: 'Set Up Pipeline',
      href: '/dashboard/pipeline',
    },
    'no-monitors': {
      title: 'Set up your first monitor to start watching your data',
      action: 'Configure Pipeline',
      href: '/dashboard/pipeline',
    },
  };

  const { title, action, href } = config[state];

  return (
    <div className="mb-6 rounded-xl border border-[var(--accent)]/20 bg-[var(--accent)]/5 p-4 flex items-center justify-between gap-4">
      <p className="text-sm text-[var(--text)]">{title}</p>
      <div className="flex items-center gap-2 shrink-0">
        <Button size="sm" onClick={() => router.push(href)}>
          {action}
        </Button>
        <button
          onClick={handleDismiss}
          className="text-xs text-[var(--muted)] hover:text-[var(--text)] px-2 py-1"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
