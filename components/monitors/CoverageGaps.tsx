'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import type { DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  unmonitoredCriticalAssets: Array<{ fqn: string; reason: string }>;
  lineageExtracted: boolean;
  pendingRecommendations: DriftRecommendation[];
  lastAnalyzedAt: string | null;
  stackId: string;
  onAddMonitor: (fqn: string) => void;
  onReviewRecs: () => void;
  onDriftRunComplete: () => void;
}

function timeSince(iso: string | null): string | null {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function CoverageGaps({
  unmonitoredCriticalAssets,
  lineageExtracted,
  pendingRecommendations,
  lastAnalyzedAt,
  stackId,
  onAddMonitor,
  onReviewRecs,
  onDriftRunComplete,
}: Props) {
  const [running, setRunning] = useState(false);
  const router = useRouter();

  const handleRunDrift = async () => {
    if (running) return;
    setRunning(true);
    try {
      const res = await fetch('/api/drift/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stackId }),
        signal: AbortSignal.timeout(125_000),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `drift run failed (${res.status})`);
      }
      const data = await res.json();
      const n = data.recommendationCount ?? 0;
      toast.success(n > 0
        ? `Drift discovery complete — ${n} recommendation${n === 1 ? '' : 's'}`
        : 'Drift discovery complete — no threshold drift detected');
      onDriftRunComplete();
    } catch (e: any) {
      toast.error(`Drift discovery failed: ${e?.message ?? 'unknown error'}`);
    } finally {
      setRunning(false);
    }
  };

  // Critical Assets card render state
  const N = unmonitoredCriticalAssets.length;
  const hideCritical = lineageExtracted && N === 0;
  const lineageMissing = !lineageExtracted;

  return (
    <section className="mb-4">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Coverage &amp; recommendations
      </div>
      <div className={cn('grid gap-3', hideCritical ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2')}>
        {!hideCritical && (
          <div className="rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] p-3">
            {lineageMissing ? (
              <>
                <div className="text-[13px] font-semibold">Lineage not yet extracted.</div>
                <div className="text-[11px] text-[var(--muted)] mt-1">
                  Critical-asset coverage needs lineage to identify what feeds your BI dashboards.
                </div>
                <button
                  onClick={() => router.push('/dashboard/pipeline')}
                  className="mt-2 text-[11px] px-2.5 py-1 rounded border border-[var(--subtle-border)] hover:bg-[var(--overlay-bg)]"
                >
                  Extract lineage →
                </button>
              </>
            ) : (
              <>
                <div className="text-[13px] font-semibold">
                  {N} critical asset{N === 1 ? '' : 's'} unmonitored
                </div>
                <div className="text-[11px] text-[var(--muted)] mt-1 truncate">
                  {unmonitoredCriticalAssets.slice(0, 3).map((a) => a.fqn).join(', ')}
                </div>
                <button
                  onClick={() => onAddMonitor(unmonitoredCriticalAssets[0]?.fqn || '')}
                  className="mt-2 text-[11px] px-2.5 py-1 rounded border border-[var(--subtle-border)] hover:bg-[var(--overlay-bg)]"
                >
                  Add monitors →
                </button>
              </>
            )}
          </div>
        )}

        <div className="rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] p-3">
          <div className="flex items-center justify-between">
            <div className="text-[13px] font-semibold">SLA recommendations</div>
            <button
              onClick={handleRunDrift}
              disabled={running}
              className={cn(
                'flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded border border-[var(--subtle-border)]',
                running ? 'opacity-60' : 'hover:bg-[var(--overlay-bg)]'
              )}
            >
              {running ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              {running ? 'Running…' : 'Run drift discovery'}
            </button>
          </div>
          <div className="text-[11px] text-[var(--muted)] mt-1">
            {pendingRecommendations.length > 0
              ? `${pendingRecommendations.length} threshold${pendingRecommendations.length === 1 ? '' : 's'} drifted.`
              : 'No threshold drift detected.'}
            {' '}
            {lastAnalyzedAt
              ? `Last analysis ${timeSince(lastAnalyzedAt)}.`
              : 'Drift discovery has not run yet.'}
          </div>
          {pendingRecommendations.length > 0 && (
            <button
              onClick={onReviewRecs}
              className="mt-2 text-[11px] px-2.5 py-1 rounded border border-[var(--subtle-border)] hover:bg-[var(--overlay-bg)]"
            >
              Review recommendations →
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
