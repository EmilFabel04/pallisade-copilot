'use client';

import { Button } from '@/components/ui/button';
import type { DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  unmonitoredCriticalAssets: Array<{ fqn: string; reason: string }>;
  pendingRecommendations: DriftRecommendation[];
  onAddMonitor: (fqn: string) => void;
  onReviewRecs: () => void;
}

export function CoverageGaps({ unmonitoredCriticalAssets, pendingRecommendations, onAddMonitor, onReviewRecs }: Props) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Improve coverage
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] p-4">
          <div className="text-[12px] text-[var(--text)] font-semibold mb-1">
            {unmonitoredCriticalAssets.length} critical asset{unmonitoredCriticalAssets.length === 1 ? '' : 's'} unmonitored
          </div>
          {unmonitoredCriticalAssets.length === 0 ? (
            <p className="text-[11px] text-[var(--muted)] mb-3">All critical assets are monitored.</p>
          ) : (
            <ul className="text-[11px] text-[var(--muted)] mb-3 space-y-1">
              {unmonitoredCriticalAssets.slice(0, 3).map((a) => (
                <li key={a.fqn} className="flex items-center justify-between gap-2">
                  <code className="truncate">{a.fqn}</code>
                  <button onClick={() => onAddMonitor(a.fqn)} className="text-[var(--accent)] hover:underline shrink-0">+ Add</button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] p-4">
          <div className="text-[12px] text-[var(--text)] font-semibold mb-1">
            {pendingRecommendations.length} SLA recommendation{pendingRecommendations.length === 1 ? '' : 's'}
          </div>
          <p className="text-[11px] text-[var(--muted)] mb-3">
            {pendingRecommendations.length === 0
              ? 'No drift detected in current baselines.'
              : 'Pallisade detected drift in baselines. Suggested threshold updates pending review.'}
          </p>
          <Button size="sm" variant="secondary" onClick={onReviewRecs} disabled={pendingRecommendations.length === 0}>
            Review →
          </Button>
        </div>
      </div>
    </div>
  );
}
