'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '../ui/button';
import { usePipeline } from '@/contexts/PipelineContext';

// Per-pipeline dismissal — a fresh empty profile shouldn't inherit a global
// "I already dismissed setup" flag from another profile.
const DISMISSED_KEY_PREFIX = 'pallisade-setup-banner-dismissed:';

type BannerState = 'no-warehouse' | 'no-monitors' | 'complete' | 'loading';

export function SetupBanner() {
  const router = useRouter();
  const { selectedPipelineId } = usePipeline();
  const [state, setState] = useState<BannerState>('loading');
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setState('loading');
    setDismissed(false);
    if (!selectedPipelineId) return;
    const key = `${DISMISSED_KEY_PREFIX}${selectedPipelineId}`;
    if (typeof window !== 'undefined' && localStorage.getItem(key)) {
      setDismissed(true);
      return;
    }

    let active = true;
    async function checkSetup() {
      try {
        const res = await fetch('/api/pipeline');
        if (!active) return;
        if (!res.ok) {
          setState('no-warehouse');
          return;
        }
        const data = await res.json();
        const pipelines = data.stacks || data.pipelines || [];
        // Only check the active profile — completion in another profile must
        // not satisfy the banner here.
        const me = pipelines.find((p: any) => p.id === selectedPipelineId);
        if (!me) {
          setState('no-warehouse');
          return;
        }
        setState(me.status === 'DRAFT' ? 'no-monitors' : 'complete');
      } catch {
        if (active) setState('complete');
      }
    }

    checkSetup();
    return () => { active = false; };
  }, [selectedPipelineId]);

  function handleDismiss() {
    if (!selectedPipelineId) return;
    localStorage.setItem(`${DISMISSED_KEY_PREFIX}${selectedPipelineId}`, 'true');
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
