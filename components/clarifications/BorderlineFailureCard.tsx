'use client';

/**
 * BorderlineFailureCard — quick-reply chip surface for `failure_review`
 * clarifications. Renders inside the ClarificationPopup above the chat
 * thread; the free-text input stays available below for nuanced answers.
 *
 * "Expected" submits `{disposition: 'expected'}` and writes a dampening
 * convention. "Investigate" submits `{disposition: 'investigate'}` and
 * routes to the copilot debug session loaded with this failure's context.
 */

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import type { ContextRequest } from '@/lib/clarifications/types';

interface Props {
  request: ContextRequest;
  onAnswered: () => void;
}

interface FailureReviewPayload {
  node_fqn: string;
  metric: string;
  observed: number;
  expected_range: [number, number];
  z_score: number;
  sample_window: string;
}

export function BorderlineFailureCard({ request, onAnswered }: Props) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const p = request.payload as unknown as FailureReviewPayload;

  const submit = async (disposition: 'expected' | 'investigate') => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch('/api/clarifications/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          requestId: request.id,
          answer: { disposition },
          proposeConvention: disposition === 'expected',
        }),
      });
      if (!res.ok) {
        const errText = (await res.text().catch(() => null)) || `HTTP ${res.status}`;
        throw new Error(errText);
      }
      onAnswered();
      if (disposition === 'investigate') {
        router.push(
          `/dashboard/copilot?mode=debug&node=${encodeURIComponent(p.node_fqn)}&metric=${encodeURIComponent(p.metric)}&z=${p.z_score}`,
        );
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'failed to submit';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const safeNumber = (n: number | null | undefined): number =>
    typeof n === 'number' && Number.isFinite(n) ? n : 0;

  const z = safeNumber(p.z_score);
  const observed = safeNumber(p.observed);
  const lo = safeNumber(p.expected_range?.[0]);
  const hi = safeNumber(p.expected_range?.[1]);
  const direction = z < 0 ? 'dipped' : 'spiked';
  const mid = (lo + hi) / 2;
  const pct = mid > 0 ? Math.abs(((observed - mid) / mid) * 100).toFixed(0) : 'n/a';

  return (
    <div className="rounded-md border border-[var(--subtle-border)] bg-[var(--overlay-bg)] p-3 space-y-3">
      <div className="text-[13px] text-[var(--text)] leading-snug">
        <span className="font-medium">{p.node_fqn ?? request.scope_ref}</span>{' '}
        {p.metric ?? 'metric'} {direction} {pct}
        {pct !== 'n/a' && '%'}
        {' '}— within noise band (z={z.toFixed(2)}, threshold not exceeded).
      </div>
      <div className="text-[11px] text-[var(--muted)] leading-snug">
        Observed {observed.toLocaleString()} vs expected{' '}
        {lo.toLocaleString()}–{hi.toLocaleString()} over {p.sample_window ?? 'n/a'}.
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => submit('expected')}
          disabled={submitting}
          className="flex-1 px-3 py-2 rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] text-[var(--text)] text-[13px] hover:bg-[var(--hover-bg)] disabled:opacity-50"
        >
          Expected — dampen
        </button>
        <button
          type="button"
          onClick={() => submit('investigate')}
          disabled={submitting}
          className="flex-1 px-3 py-2 rounded-md bg-[var(--accent)] text-white text-[13px] hover:opacity-90 disabled:opacity-50"
        >
          Investigate
        </button>
      </div>
      {error && (
        <div className="text-[11px] text-red-500" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
