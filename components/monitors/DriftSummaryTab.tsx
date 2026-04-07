'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Play, Activity, AlertTriangle, CheckCircle, XCircle, Database, Workflow } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { DriftRecommendationCard, type DriftRecommendation } from './DriftRecommendationCard';
import type { WatchSummary } from '@/types/health-watch';
import type { ScheduledTask } from '@/types/schedule';

const DATA_MONITOR_TYPES = new Set([
  'FRESHNESS', 'VOLUME', 'SCHEMA_CHANGE', 'NULL_CHECK', 'UNIQUENESS_CHECK',
  'OUTLIER_DETECTION', 'ANOMALY', 'RANGE_VALIDATION', 'ACCEPTED_VALUES',
  'DATE_CONSISTENCY', 'DATA_TYPE_VALIDATION',
]);

const PIPELINE_MONITOR_TYPES = new Set([
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES', 'DBT_MODEL_FRESHNESS', 'DBT_SOURCE_FRESHNESS',
  'BI_FRESHNESS_PROXY', 'BI_UPSTREAM_BREAK_RISK', 'BI_REFRESH_FAILURE', 'BI_CONTENT_HEALTH',
  'SERVER_HEALTH', 'CERTIFICATE', 'LOG_ANALYSIS',
]);

const CATEGORIES = [
  { key: 'freshness', label: 'Freshness', color: 'text-blue-400' },
  { key: 'volume', label: 'Volume', color: 'text-purple-400' },
  { key: 'quality', label: 'Quality', color: 'text-amber-400' },
  { key: 'schema', label: 'Schema', color: 'text-orange-400' },
  { key: 'anomaly', label: 'Anomaly', color: 'text-red-400' },
  { key: 'uniqueness', label: 'Uniqueness', color: 'text-cyan-400' },
];

function countMonitors(watches: WatchSummary[], tasks: ScheduledTask[], typeSet: Set<string>) {
  let total = 0, passing = 0, failing = 0;
  for (const w of watches) {
    const monitors = w.monitors || [];
    const matched = monitors.filter(m => typeSet.has((m.monitorType || '').toUpperCase()));
    total += matched.length;
    passing += matched.filter(m => m.lastStatus === 'PASS').length;
    failing += matched.filter(m => m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR' || m.lastStatus === 'WARN').length;
  }
  for (const t of tasks) {
    if (!typeSet.has((t.monitorType || '').toUpperCase())) continue;
    total++;
    const s = (t.lastStatus || '').toUpperCase();
    if (s === 'PASS') passing++;
    if (s === 'FAIL' || s === 'ERROR' || s === 'WARN') failing++;
  }
  return { total, passing, failing };
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

  const dataCounts = useMemo(() => countMonitors(watches, tasks, DATA_MONITOR_TYPES), [watches, tasks]);
  const pipelineCounts = useMemo(() => countMonitors(watches, tasks, PIPELINE_MONITOR_TYPES), [watches, tasks]);

  const pending = counts.pending || 0;
  const accepted = counts.accepted || 0;
  const dismissed = counts.dismissed || 0;
  const highCount = filteredDrift.filter(r => r.severity === 'high').length;
  const mediumCount = filteredDrift.filter(r => r.severity === 'medium').length;
  const lowCount = filteredDrift.filter(r => r.severity === 'low').length;

  return (
    <div className="space-y-6">
      {/* ── Overview Bar ────────────────────────────────────────── */}
      <div className="flex items-stretch rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)] divide-x divide-[var(--subtle-border)]">
        {/* Data Monitors */}
        <div className="flex-1 px-5 py-4">
          <div className="flex items-center gap-2 mb-2">
            <Database className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Data Monitors</span>
          </div>
          {dataCounts.total > 0 ? (
            <div className="flex items-baseline gap-3">
              <span className="text-[20px] font-semibold text-[var(--text)]">{dataCounts.passing}<span className="text-[12px] text-[var(--muted)] font-normal">/{dataCounts.total}</span></span>
              <span className="text-[11px] text-emerald-400 font-medium">passing</span>
              {dataCounts.failing > 0 && <span className="text-[11px] text-red-400 font-medium">{dataCounts.failing} failing</span>}
            </div>
          ) : (
            <p className="text-[13px] text-[var(--muted)]">No monitors</p>
          )}
        </div>

        {/* Pipeline Monitors */}
        <div className="flex-1 px-5 py-4">
          <div className="flex items-center gap-2 mb-2">
            <Workflow className="w-3.5 h-3.5 text-purple-400" />
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Pipeline Monitors</span>
          </div>
          {pipelineCounts.total > 0 ? (
            <div className="flex items-baseline gap-3">
              <span className="text-[20px] font-semibold text-[var(--text)]">{pipelineCounts.passing}<span className="text-[12px] text-[var(--muted)] font-normal">/{pipelineCounts.total}</span></span>
              <span className="text-[11px] text-emerald-400 font-medium">passing</span>
              {pipelineCounts.failing > 0 && <span className="text-[11px] text-red-400 font-medium">{pipelineCounts.failing} failing</span>}
            </div>
          ) : (
            <p className="text-[13px] text-[var(--muted)]">No monitors</p>
          )}
        </div>

        {/* Drift Pending */}
        <div className="flex-1 px-5 py-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Drift Pending</span>
          </div>
          <p className="text-[20px] font-semibold text-[var(--text)]">{pending}</p>
        </div>

        {/* Last Analysis */}
        <div className="flex-1 px-5 py-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-3.5 h-3.5 text-[var(--accent)]" />
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Last Analysis</span>
          </div>
          <p className="text-[15px] font-semibold text-[var(--text)]">
            {lastAnalyzedAt
              ? new Date(lastAnalyzedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
              : 'Never'}
          </p>
        </div>
      </div>

      {/* ── Drift Analysis ──────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {/* Drift status tabs */}
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

          <button
            onClick={handleRunAnalysis}
            disabled={running}
            className="flex items-center gap-1.5 px-4 py-1.5 text-[11px] font-medium rounded-lg bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {running ? 'Analyzing...' : 'Run Analysis'}
          </button>
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
