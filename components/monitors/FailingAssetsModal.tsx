'use client';

import { useEffect, useMemo, useState } from 'react';
import { X, AlertCircle, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { SparklineChart } from './SparklineChart';
import { DriftRecommendationCard, type DriftRecommendation } from './DriftRecommendationCard';

interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  category: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}

interface AssetTrend {
  name: string;
  fqn: string;
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: MonitorTrend[];
}

interface Props {
  open: boolean;
  onClose: () => void;
  assets: AssetTrend[];
  recommendations: DriftRecommendation[];
  stackId: string;
  onRecommendationsChanged: () => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  freshness: 'Freshness',
  volume: 'Volume',
  quality: 'Quality',
  schema: 'Schema',
  anomaly: 'Anomaly',
  uniqueness: 'Uniqueness',
};

const SPARKLINE_COLORS: Record<string, string> = {
  PASS: '#34d399',
  WARN: '#fbbf24',
  FAIL: '#f87171',
  ERROR: '#f87171',
};

function formatValue(val: number | null): string {
  if (val === null) return '—';
  if (Math.abs(val) >= 1000) return `${(val / 1000).toFixed(1)}k`;
  if (Number.isInteger(val)) return val.toString();
  return val.toFixed(1);
}

export function FailingAssetsModal({
  open,
  onClose,
  assets,
  recommendations,
  stackId,
  onRecommendationsChanged,
}: Props) {
  const [busyRecId, setBusyRecId] = useState<string | null>(null);

  const failingAssets = useMemo(
    () => assets.filter((a) => a.failing > 0 || a.status === 'drifting'),
    [assets],
  );

  // Build a map of failing recommendations indexed by FQN so we can show the
  // side panel scoped to the same assets when possible.
  const failingFqns = useMemo(
    () => new Set(failingAssets.map((a) => a.fqn)),
    [failingAssets],
  );

  const scopedRecs = useMemo(() => {
    if (failingFqns.size === 0) return recommendations;
    const matching = recommendations.filter((r) => failingFqns.has(r.targetFqn));
    return matching.length > 0 ? matching : recommendations;
  }, [recommendations, failingFqns]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const totalFailingMonitors = failingAssets.reduce((acc, a) => acc + a.failing, 0);
  const hasRecs = scopedRecs.length > 0;

  const onRecAction = async (recId: string, action: 'accept' | 'dismiss', value?: string) => {
    setBusyRecId(recId);
    try {
      const body: Record<string, unknown> = { stackId };
      if (action === 'accept' && value !== undefined) {
        body.action = 'accept_with_value';
        body.value = value;
      } else {
        body.action = action;
      }
      const res = await fetch(`/api/drift/${recId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error(err.error || 'Action failed');
      } else {
        onRecommendationsChanged();
      }
    } finally {
      setBusyRecId(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4 py-8"
      role="dialog"
      aria-modal="true"
      aria-label="Failing assets"
    >
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />

      <div className="relative flex items-stretch gap-4 max-w-[1200px] w-full max-h-full">
        {/* Failing assets — main modal */}
        <div className={cn(
          'flex flex-col rounded-xl border border-[var(--subtle-border)] bg-[var(--bg)] shadow-2xl',
          hasRecs ? 'flex-1 min-w-0' : 'mx-auto w-full max-w-[760px]',
        )}>
          <header className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--subtle-border)]">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-8 h-8 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center justify-center shrink-0">
                <AlertCircle className="w-4 h-4 text-red-400" />
              </div>
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Failing</div>
                <div className="text-[14px] font-semibold text-[var(--text)] truncate">
                  {failingAssets.length} asset{failingAssets.length === 1 ? '' : 's'}
                  <span className="text-[var(--muted)] font-normal">
                    {' · '}{totalFailingMonitors} failing monitor{totalFailingMonitors === 1 ? '' : 's'}
                  </span>
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-[var(--surface)] text-[var(--muted)] hover:text-[var(--text)]"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </header>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 max-h-[70vh]">
            {failingAssets.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center mb-3">
                  <AlertCircle className="w-5 h-5 text-emerald-400" />
                </div>
                <p className="text-[13px] font-medium text-[var(--text)]">No failing assets</p>
                <p className="text-[11px] text-[var(--muted)] mt-1">
                  Everything is passing right now.
                </p>
              </div>
            ) : (
              failingAssets.map((asset) => {
                const failingMonitors = asset.monitors.filter((m) => {
                  const s = (m.latestStatus || '').toUpperCase();
                  return s === 'FAIL' || s === 'ERROR' || s === 'WARN';
                });
                const passPct = asset.total > 0 ? (asset.passing / asset.total) * 100 : 0;

                return (
                  <div
                    key={asset.fqn}
                    className="rounded-lg border border-red-500/25 bg-red-500/[0.04] overflow-hidden"
                  >
                    <div className="px-4 py-3 flex items-center gap-3 border-b border-red-500/15">
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-semibold text-[var(--text)] truncate">
                          {asset.name}
                        </div>
                        <div className="text-[10px] text-[var(--text-faint)] font-mono truncate">
                          {asset.fqn}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <div className="w-20">
                          <div className="h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden">
                            <div
                              className="h-full rounded-full bg-red-500 transition-all"
                              style={{ width: `${passPct}%` }}
                            />
                          </div>
                        </div>
                        <span className="text-[12px] font-semibold tabular-nums text-red-400">
                          {asset.passing}/{asset.total}
                        </span>
                      </div>
                    </div>

                    <div className="px-4 py-3 grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                      {failingMonitors.map((m) => {
                        const status = (m.latestStatus || '').toUpperCase();
                        const lineColor = SPARKLINE_COLORS[status] || '#f87171';
                        const values = m.runs.map((r) => r.value);
                        const catLabel = CATEGORY_LABELS[m.category] || m.category;
                        const monitorTypeLabel = m.name.includes('—')
                          ? (m.name.split('—')[0]?.trim() || m.name)
                          : m.name;

                        return (
                          <div
                            key={m.id}
                            className="rounded-md bg-[var(--overlay-bg)] border border-[var(--subtle-border)] p-2.5"
                          >
                            <div className="flex items-center justify-between mb-1.5 gap-2">
                              <div className="flex items-center gap-1.5 min-w-0">
                                <span className="text-[9px] uppercase text-[var(--muted)] font-medium">
                                  {catLabel}
                                </span>
                                <span className="text-[11px] font-medium text-[var(--text)] truncate capitalize">
                                  {monitorTypeLabel}
                                </span>
                              </div>
                              <span className={cn(
                                'text-[9px] font-medium px-1.5 py-0.5 rounded shrink-0',
                                status === 'WARN'
                                  ? 'bg-amber-500/10 text-amber-400'
                                  : 'bg-red-500/10 text-red-400',
                              )}>
                                {status}
                              </span>
                            </div>
                            <SparklineChart values={values} color={lineColor} />
                            <div className="flex items-center justify-between mt-1 text-[9px] text-[var(--muted)]">
                              <span>
                                {formatValue(m.latestValue)}
                                {m.baselineMean !== null && (
                                  <span className="text-[var(--text-faint)]">
                                    {' '}(avg {formatValue(m.baselineMean)})
                                  </span>
                                )}
                              </span>
                              {m.pctChange !== null && (
                                <span className={m.pctChange >= 0 ? 'text-red-400' : 'text-emerald-400'}>
                                  {m.pctChange >= 0 ? '+' : ''}{m.pctChange}%
                                </span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* SLA recommendations — side panel, only when present */}
        {hasRecs && (
          <aside
            className="hidden md:flex w-[420px] shrink-0 flex-col rounded-xl border border-[var(--subtle-border)] bg-[var(--bg)] shadow-2xl"
            aria-label="SLA recommendations"
          >
            <header className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--subtle-border)]">
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-wider text-[var(--muted)]">
                  Drift discovery
                </div>
                <div className="text-[14px] font-semibold text-[var(--text)]">
                  {scopedRecs.length} SLA recommendation{scopedRecs.length === 1 ? '' : 's'}
                </div>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2 max-h-[70vh]">
              {scopedRecs.map((rec) => (
                <div
                  key={rec.id}
                  className={busyRecId === rec.id ? 'opacity-60 pointer-events-none' : ''}
                >
                  <DriftRecommendationCard
                    rec={rec}
                    onAccept={(id, value) => onRecAction(id, 'accept', value)}
                    onDismiss={(id) => onRecAction(id, 'dismiss')}
                  />
                </div>
              ))}
            </div>

            {busyRecId && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="bg-[var(--surface)]/90 rounded-md px-3 py-2 flex items-center gap-2 text-[12px]">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Updating…
                </div>
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
