'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { X, ExternalLink, AlertCircle, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { ToolIcon } from '@/components/icons/ToolIcon';
import type { PipelineToolStatus } from '@/types/monitors-summary';
import {
  DriftRecommendationCard,
  type DriftRecommendation,
} from './DriftRecommendationCard';

interface Props {
  tool: PipelineToolStatus;
  stackId: string;
  onClose: () => void;
  /** Optional: pending SLA recommendations to surface in the right-hand panel. */
  recommendations?: DriftRecommendation[];
  onRecommendationsChanged?: () => void;
}

interface MonitorRow {
  id: string;
  name: string;
  monitorType: string;
  targetFqn: string | null;
  lastStatus: string | null;
  lastRunAt: string | null;
}

function timeSince(iso: string | null): string {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function PipelineToolDetailPanel({
  tool,
  stackId,
  onClose,
  recommendations = [],
  onRecommendationsChanged,
}: Props) {
  const router = useRouter();
  const [monitors, setMonitors] = useState<MonitorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyRecId, setBusyRecId] = useState<string | null>(null);

  // Close on ESC
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetch(`/api/monitors/by-tool?stackId=${stackId}&toolType=${encodeURIComponent(tool.toolType)}`)
      .then((r) => r.ok ? r.json() : { monitors: [] })
      .then((d) => {
        if (!active) return;
        setMonitors((d.monitors as MonitorRow[]) ?? []);
        setLoading(false);
      })
      .catch(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [stackId, tool.toolType]);

  const failures = useMemo(
    () => monitors.filter((m) => {
      const s = (m.lastStatus || '').toUpperCase();
      return s === 'FAIL' || s === 'ERROR';
    }),
    [monitors],
  );

  // Scope SLA recs to the FQNs in this tool when possible; fall back to all.
  const scopedRecs = useMemo(() => {
    if (recommendations.length === 0) return [];
    const fqns = new Set(monitors.map((m) => m.targetFqn).filter(Boolean) as string[]);
    if (fqns.size === 0) return recommendations;
    const matching = recommendations.filter((r) => fqns.has(r.targetFqn));
    return matching.length > 0 ? matching : recommendations;
  }, [recommendations, monitors]);

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
        onRecommendationsChanged?.();
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
      aria-label={`${tool.displayName} detail`}
    >
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />

      <div className="relative flex items-stretch gap-4 max-w-[1200px] w-full max-h-full">
        {/* Tool detail — main modal */}
        <div className={cn(
          'flex flex-col rounded-xl border border-[var(--subtle-border)] bg-[var(--bg)] shadow-2xl',
          hasRecs ? 'flex-1 min-w-0' : 'mx-auto w-full max-w-[640px]',
        )}>
          <header className="flex items-center gap-3 px-5 py-4 border-b border-[var(--subtle-border)]">
            <ToolIcon toolType={tool.toolType} size={32} className="flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Pipeline tool</div>
              <div className="text-[14px] font-semibold truncate">{tool.displayName}</div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-[var(--surface)] text-[var(--muted)] hover:text-[var(--text)]"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </header>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 max-h-[70vh]">
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Monitors" value={String(tool.monitorCount)} />
              <Stat label="Failing" value={String(tool.failCount)} tone={tool.failCount > 0 ? 'red' : undefined} />
              <Stat label="Warning" value={String(tool.warnCount)} tone={tool.warnCount > 0 ? 'amber' : undefined} />
            </div>

            <section>
              <div className="text-[11px] uppercase tracking-wide text-[var(--muted)] mb-2">
                Recent failures
              </div>
              {loading ? (
                <div className="h-12 animate-pulse rounded bg-[var(--surface)]" />
              ) : failures.length === 0 ? (
                <div className="text-[12px] text-[var(--muted)]">No recent failures.</div>
              ) : (
                <ul className="space-y-1.5">
                  {failures.slice(0, 8).map((m) => (
                    <li
                      key={m.id}
                      className="flex items-center gap-2 text-[12px] rounded-md border border-red-500/20 bg-red-500/[0.04] px-2.5 py-1.5"
                    >
                      <AlertCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                      <span className="truncate text-[var(--text)] font-medium">{m.name}</span>
                      <span className="text-[10px] text-[var(--text-faint)] shrink-0 ml-auto">
                        {m.targetFqn || m.monitorType}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <div className="text-[11px] uppercase tracking-wide text-[var(--muted)] mb-2">
                Monitors
              </div>
              {loading ? (
                <div className="h-20 animate-pulse rounded bg-[var(--surface)]" />
              ) : monitors.length === 0 ? (
                <div className="text-[12px] text-[var(--muted)]">No monitors target this tool yet.</div>
              ) : (
                <ul className="space-y-1">
                  {monitors.map((m) => {
                    const s = (m.lastStatus || '').toUpperCase();
                    const badge = s === 'FAIL' || s === 'ERROR'
                      ? 'bg-red-500/10 text-red-400'
                      : s === 'WARN'
                        ? 'bg-amber-500/10 text-amber-400'
                        : s === 'PASS'
                          ? 'bg-emerald-500/10 text-emerald-400'
                          : 'bg-[var(--overlay-bg)] text-[var(--muted)]';
                    return (
                      <li
                        key={m.id}
                        className="flex items-center justify-between gap-3 text-[12px] py-1.5 px-2 rounded-md hover:bg-[var(--surface)]"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[var(--text)]">{m.name}</div>
                          {m.targetFqn && (
                            <div className="text-[10px] font-mono text-[var(--text-faint)] truncate">
                              {m.targetFqn}
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-[10px] text-[var(--text-faint)]">
                            {timeSince(m.lastRunAt)}
                          </span>
                          <span className={cn('text-[10px] font-medium px-1.5 py-0.5 rounded', badge)}>
                            {m.lastStatus || 'NEVER RUN'}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </div>

          <footer className="border-t border-[var(--subtle-border)] px-5 py-3">
            <button
              onClick={() => router.push(`/dashboard/monitors?tab=pipeline&tool=${encodeURIComponent(tool.toolType)}`)}
              className="w-full flex items-center justify-center gap-1.5 text-[12px] py-2 rounded border border-[var(--subtle-border)] hover:bg-[var(--surface)]"
            >
              View all in Pipeline Monitors <ExternalLink className="w-3 h-3" />
            </button>
          </footer>
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

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'red' | 'amber' }) {
  const color = tone === 'red' ? 'text-red-400' : tone === 'amber' ? 'text-amber-400' : 'text-[var(--text)]';
  return (
    <div className="rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] px-2.5 py-2">
      <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">{label}</div>
      <div className={cn('text-[16px] font-semibold mt-0.5', color)}>{value}</div>
    </div>
  );
}
