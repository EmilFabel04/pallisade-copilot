'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Play, Activity, AlertTriangle, CheckCircle, XCircle, Shield } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { DriftRecommendationCard, type DriftRecommendation } from './DriftRecommendationCard';
import type { WatchSummary } from '@/types/health-watch';
import type { ScheduledTask } from '@/types/schedule';

const CATEGORIES = [
  { key: 'freshness', label: 'Freshness', color: 'text-blue-400' },
  { key: 'volume', label: 'Volume', color: 'text-purple-400' },
  { key: 'quality', label: 'Quality', color: 'text-amber-400' },
  { key: 'schema', label: 'Schema', color: 'text-orange-400' },
  { key: 'anomaly', label: 'Anomaly', color: 'text-red-400' },
  { key: 'uniqueness', label: 'Uniqueness', color: 'text-cyan-400' },
];

type MonitorStatusFilter = 'all' | 'passing' | 'warning' | 'failing' | 'error' | 'new';

const STATUS_FILTERS: { key: MonitorStatusFilter; label: string; color: string }[] = [
  { key: 'all', label: 'All', color: 'text-[var(--text)]' },
  { key: 'passing', label: 'Passing', color: 'text-emerald-400' },
  { key: 'warning', label: 'Warning', color: 'text-amber-400' },
  { key: 'failing', label: 'Failing', color: 'text-red-400' },
  { key: 'error', label: 'Error', color: 'text-red-500' },
  { key: 'new', label: 'New', color: 'text-zinc-400' },
];

function getWatchStatus(w: WatchSummary): MonitorStatusFilter {
  if (w.failCount > 0) return 'failing';
  if (w.warnCount > 0) return 'warning';
  if (w.passCount > 0) return 'passing';
  return 'new';
}

function getTaskStatus(t: ScheduledTask): MonitorStatusFilter {
  const s = (t.lastStatus || '').toUpperCase();
  if (s === 'FAIL') return 'failing';
  if (s === 'WARN') return 'warning';
  if (s === 'ERROR') return 'error';
  if (s === 'PASS') return 'passing';
  return 'new';
}

interface Props {
  watches: WatchSummary[];
  tasks: ScheduledTask[];
  loading: boolean;
}

export function DriftSummaryTab({ watches, tasks, loading: monitorsLoading }: Props) {
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});

  const [categoryFilter, setCategoryFilter] = useState<Set<string>>(new Set());
  const [driftStatusFilter, setDriftStatusFilter] = useState<string>('pending');
  const [monitorStatusFilter, setMonitorStatusFilter] = useState<MonitorStatusFilter>('all');

  const fetchRecommendations = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (driftStatusFilter) params.set('status', driftStatusFilter);
      const res = await fetch(`/api/drift?${params}`);
      if (res.ok) {
        const data = await res.json();
        setRecommendations(data.recommendations || []);
        setLastAnalyzedAt(data.lastAnalyzedAt);
        setCounts(data.counts || {});
      }
    } catch (err) {
      console.error('[DriftSummary] Fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [driftStatusFilter]);

  useEffect(() => { fetchRecommendations(); }, [fetchRecommendations]);

  const handleRunAnalysis = async () => {
    setRunning(true);
    try {
      const res = await fetch('/api/drift/run', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        toast.success(`Analysis complete — ${data.recommendationCount} recommendation${data.recommendationCount !== 1 ? 's' : ''}`);
        fetchRecommendations();
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.error || 'Analysis failed');
      }
    } catch {
      toast.error('Failed to run analysis');
    } finally {
      setRunning(false);
    }
  };

  const handleAccept = async (id: string, value?: string) => {
    const action = value ? 'accept_with_value' : 'accept';
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, value }),
    });
    if (res.ok) {
      toast.success('Recommendation applied');
      fetchRecommendations();
    } else {
      toast.error('Failed to apply');
    }
  };

  const handleDismiss = async (id: string) => {
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'dismiss' }),
    });
    if (res.ok) {
      fetchRecommendations();
    } else {
      toast.error('Failed to dismiss');
    }
  };

  const toggleCategory = (key: string) => {
    setCategoryFilter(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const filteredDrift = useMemo(() => {
    let result = recommendations;
    if (categoryFilter.size > 0) {
      result = result.filter(r => categoryFilter.has(r.driftCategory));
    }
    return result;
  }, [recommendations, categoryFilter]);

  // Monitor status counts
  const monitorCounts = useMemo(() => {
    const c = { all: 0, passing: 0, warning: 0, failing: 0, error: 0, new: 0 };
    for (const w of watches) {
      const s = getWatchStatus(w);
      c[s]++;
      c.all++;
    }
    for (const t of tasks) {
      const s = getTaskStatus(t);
      c[s]++;
      c.all++;
    }
    return c;
  }, [watches, tasks]);

  // Filtered monitors for the status section
  const filteredWatches = useMemo(() => {
    if (monitorStatusFilter === 'all') return watches;
    return watches.filter(w => getWatchStatus(w) === monitorStatusFilter);
  }, [watches, monitorStatusFilter]);

  const filteredTasks = useMemo(() => {
    if (monitorStatusFilter === 'all') return tasks;
    return tasks.filter(t => getTaskStatus(t) === monitorStatusFilter);
  }, [tasks, monitorStatusFilter]);

  const pending = counts.pending || 0;
  const accepted = counts.accepted || 0;
  const dismissed = counts.dismissed || 0;
  const highCount = filteredDrift.filter(r => r.severity === 'high').length;
  const mediumCount = filteredDrift.filter(r => r.severity === 'medium').length;
  const lowCount = filteredDrift.filter(r => r.severity === 'low').length;

  return (
    <div className="space-y-6">
      {/* ── Monitor Status Overview ─────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-[var(--accent)]" />
            <h2 className="text-[14px] font-semibold text-[var(--text)]">Monitor Status</h2>
          </div>
          {/* Status filter pills */}
          <div className="flex items-center bg-[var(--overlay-bg)] rounded-lg p-0.5">
            {STATUS_FILTERS.map(f => (
              <button
                key={f.key}
                onClick={() => setMonitorStatusFilter(f.key)}
                className={cn(
                  'px-3 py-1 text-[11px] font-medium rounded-md transition-colors',
                  monitorStatusFilter === f.key
                    ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm'
                    : 'text-[var(--muted)] hover:text-[var(--text)]'
                )}
              >
                {f.label}
                {f.key !== 'all' && monitorCounts[f.key] > 0 && (
                  <span className={`ml-1 ${f.color}`}>{monitorCounts[f.key]}</span>
                )}
                {f.key === 'all' && (
                  <span className="ml-1 text-[var(--muted)]">{monitorCounts.all}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Status bar */}
        {monitorCounts.all > 0 && (
          <div className="flex h-2 rounded-full overflow-hidden bg-[var(--overlay-bg)] mb-3">
            {monitorCounts.passing > 0 && (
              <div className="bg-emerald-500 h-full" style={{ width: `${(monitorCounts.passing / monitorCounts.all) * 100}%` }} />
            )}
            {monitorCounts.warning > 0 && (
              <div className="bg-amber-500 h-full" style={{ width: `${(monitorCounts.warning / monitorCounts.all) * 100}%` }} />
            )}
            {monitorCounts.failing > 0 && (
              <div className="bg-red-500 h-full" style={{ width: `${(monitorCounts.failing / monitorCounts.all) * 100}%` }} />
            )}
            {monitorCounts.error > 0 && (
              <div className="bg-red-700 h-full" style={{ width: `${(monitorCounts.error / monitorCounts.all) * 100}%` }} />
            )}
            {monitorCounts.new > 0 && (
              <div className="bg-zinc-600 h-full" style={{ width: `${(monitorCounts.new / monitorCounts.all) * 100}%` }} />
            )}
          </div>
        )}

        {/* Filtered monitor list */}
        {monitorsLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-4 h-4 animate-spin text-[var(--muted)]" />
          </div>
        ) : (filteredWatches.length > 0 || filteredTasks.length > 0) ? (
          <div className="space-y-1.5">
            {filteredWatches.map(w => {
              const status = getWatchStatus(w);
              return (
                <div key={w.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] transition-colors">
                  <div className={cn('w-2 h-2 rounded-full shrink-0', {
                    'bg-emerald-500': status === 'passing',
                    'bg-amber-500': status === 'warning',
                    'bg-red-500': status === 'failing',
                    'bg-red-700': status === 'error',
                    'bg-zinc-500': status === 'new',
                  })} />
                  <span className="text-[13px] font-medium text-[var(--text)] truncate flex-1">{w.name}</span>
                  <span className="text-[11px] text-[var(--muted)] font-mono truncate max-w-[250px]">{w.anchorFqn}</span>
                  <div className="flex items-center gap-2 text-[11px] shrink-0">
                    {w.passCount > 0 && <span className="text-emerald-400">{w.passCount} pass</span>}
                    {w.warnCount > 0 && <span className="text-amber-400">{w.warnCount} warn</span>}
                    {w.failCount > 0 && <span className="text-red-400">{w.failCount} fail</span>}
                    {status === 'new' && <span className="text-zinc-400">Not run</span>}
                  </div>
                </div>
              );
            })}
            {filteredTasks.map(t => {
              const status = getTaskStatus(t);
              return (
                <div key={t.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] transition-colors">
                  <div className={cn('w-2 h-2 rounded-full shrink-0', {
                    'bg-emerald-500': status === 'passing',
                    'bg-amber-500': status === 'warning',
                    'bg-red-500': status === 'failing',
                    'bg-red-700': status === 'error',
                    'bg-zinc-500': status === 'new',
                  })} />
                  <span className="text-[13px] font-medium text-[var(--text)] truncate flex-1">{t.name}</span>
                  <span className="text-[11px] text-[var(--muted)] font-mono truncate max-w-[250px]">{t.targetFqn}</span>
                  <span className={cn('text-[11px] font-medium', {
                    'text-emerald-400': status === 'passing',
                    'text-amber-400': status === 'warning',
                    'text-red-400': status === 'failing',
                    'text-red-500': status === 'error',
                    'text-zinc-400': status === 'new',
                  })}>
                    {t.lastStatus || 'New'}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-[12px] text-[var(--muted)] text-center py-4">
            {monitorCounts.all === 0 ? 'No monitors configured yet.' : 'No monitors match this filter.'}
          </p>
        )}
      </div>

      {/* ── Drift Analysis ──────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-[var(--accent)]" />
            <h2 className="text-[14px] font-semibold text-[var(--text)]">Drift Analysis</h2>
          </div>
          <button
            onClick={handleRunAnalysis}
            disabled={running}
            className="flex items-center gap-1.5 px-4 py-1.5 text-[11px] font-medium rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {running ? 'Analyzing...' : 'Run Analysis'}
          </button>
        </div>

        {/* Overview bar */}
        <div className="flex items-stretch gap-0 rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)] divide-x divide-[var(--subtle-border)] mb-4">
          <div className="flex-1 px-5 py-4">
            <div className="flex items-center gap-2 mb-1.5">
              <Activity className="w-3.5 h-3.5 text-[var(--accent)]" />
              <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Last Analysis</span>
            </div>
            <p className="text-[15px] font-semibold text-[var(--text)]">
              {lastAnalyzedAt
                ? new Date(lastAnalyzedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                : 'Never'}
            </p>
          </div>
          <div className="flex-1 px-5 py-4">
            <div className="flex items-center gap-2 mb-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Pending</span>
            </div>
            <p className="text-[15px] font-semibold text-[var(--text)]">{pending}</p>
          </div>
          <div className="flex-1 px-5 py-4">
            <div className="flex items-center gap-2 mb-1.5">
              <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
              <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Applied</span>
            </div>
            <p className="text-[15px] font-semibold text-[var(--text)]">{accepted}</p>
          </div>
          <div className="flex-1 px-5 py-4">
            <div className="flex items-center gap-2 mb-1.5">
              <XCircle className="w-3.5 h-3.5 text-zinc-400" />
              <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Dismissed</span>
            </div>
            <p className="text-[15px] font-semibold text-[var(--text)]">{dismissed}</p>
          </div>
        </div>

        {/* Drift toolbar */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="flex items-center bg-[var(--overlay-bg)] rounded-lg p-0.5">
              {[
                { key: 'pending', label: 'Pending' },
                { key: 'accepted', label: 'Applied' },
                { key: 'dismissed', label: 'Dismissed' },
                { key: '', label: 'All' },
              ].map(s => (
                <button
                  key={s.key}
                  onClick={() => setDriftStatusFilter(s.key)}
                  className={cn(
                    'px-3 py-1 text-[11px] font-medium rounded-md transition-colors',
                    driftStatusFilter === s.key
                      ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm'
                      : 'text-[var(--muted)] hover:text-[var(--text)]'
                  )}
                >
                  {s.label}
                </button>
              ))}
            </div>

            <div className="w-px h-5 bg-[var(--subtle-border)] mx-1" />
            <div className="flex items-center gap-0.5">
              {CATEGORIES.map(cat => (
                <button
                  key={cat.key}
                  onClick={() => toggleCategory(cat.key)}
                  className={cn(
                    'px-2 py-1 text-[10px] font-medium rounded-md transition-colors',
                    categoryFilter.has(cat.key)
                      ? `${cat.color} bg-[var(--surface)] shadow-sm`
                      : 'text-[var(--muted)] hover:text-[var(--text)]'
                  )}
                >
                  {cat.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Drift results */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
          </div>
        ) : filteredDrift.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Activity className="w-8 h-8 text-[var(--text-faint)] mb-3" />
            <p className="text-[13px] text-[var(--muted)]">
              {recommendations.length === 0
                ? 'No drift analysis results yet. Run an analysis to detect SLA drift.'
                : 'No recommendations match your filters.'}
            </p>
            {recommendations.length === 0 && (
              <button
                onClick={handleRunAnalysis}
                disabled={running}
                className="mt-3 px-4 py-1.5 text-[11px] font-medium rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {running ? 'Analyzing...' : 'Run First Analysis'}
              </button>
            )}
          </div>
        ) : (
          <div>
            {(highCount > 0 || mediumCount > 0) && (
              <div className="flex items-center gap-3 mb-3 text-[11px]">
                {highCount > 0 && <span className="text-red-400 font-medium">{highCount} high severity</span>}
                {mediumCount > 0 && <span className="text-amber-400 font-medium">{mediumCount} medium</span>}
                {lowCount > 0 && <span className="text-zinc-400">{lowCount} low</span>}
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {filteredDrift.map(rec => (
                <DriftRecommendationCard
                  key={rec.id}
                  rec={rec}
                  onAccept={handleAccept}
                  onDismiss={handleDismiss}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
