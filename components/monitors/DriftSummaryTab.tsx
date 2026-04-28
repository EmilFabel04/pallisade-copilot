'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Play, Activity, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { DriftRecommendationCard, type DriftRecommendation } from './DriftRecommendationCard';
import { CategorySparklinePanel } from './CategorySparklinePanel';
import { AssetHealthRow } from './AssetHealthRow';
import { usePipeline } from '@/contexts/PipelineContext';
import type { WatchSummary } from '@/types/health-watch';
import type { ScheduledTask } from '@/types/schedule';

const DATA_CATEGORIES = [
  { key: 'freshness', label: 'Freshness' },
  { key: 'volume', label: 'Volume' },
  { key: 'quality', label: 'Quality' },
  { key: 'schema', label: 'Schema' },
  { key: 'anomaly', label: 'Anomaly' },
  { key: 'uniqueness', label: 'Uniqueness' },
] as const;

const STATUS_STYLES: Record<string, { border: string; text: string; accent: string; badgeBg: string }> = {
  stable:   { border: 'border-emerald-500/30', text: 'text-emerald-500', accent: 'bg-emerald-500', badgeBg: 'bg-emerald-500/10' },
  healthy:  { border: 'border-emerald-500/30', text: 'text-emerald-500', accent: 'bg-emerald-500', badgeBg: 'bg-emerald-500/10' },
  warning:  { border: 'border-amber-500/30',   text: 'text-amber-500',   accent: 'bg-amber-500',   badgeBg: 'bg-amber-500/10' },
  degraded: { border: 'border-amber-500/30',   text: 'text-amber-500',   accent: 'bg-amber-500',   badgeBg: 'bg-amber-500/10' },
  drifting: { border: 'border-red-500/30',     text: 'text-red-500',     accent: 'bg-red-500',     badgeBg: 'bg-red-500/10' },
  down:     { border: 'border-red-500/30',     text: 'text-red-500',     accent: 'bg-red-500',     badgeBg: 'bg-red-500/10' },
  pending:  { border: 'border-[var(--subtle-border)]', text: 'text-[var(--muted)]', accent: 'bg-zinc-400', badgeBg: 'bg-zinc-500/10' },
};

const STATUS_LABELS: Record<string, string> = {
  stable: 'Stable', healthy: 'Healthy', warning: 'Warning',
  degraded: 'Degraded', drifting: 'Drifting', down: 'Down', pending: 'Pending',
};

function gridColsClass(count: number, max: number = 6): string {
  const map: Record<number, string> = {
    1: 'grid-cols-1', 2: 'grid-cols-2', 3: 'grid-cols-3',
    4: 'grid-cols-4', 5: 'grid-cols-5', 6: 'grid-cols-6',
  };
  return map[Math.min(count, max)] || `grid-cols-${max}`;
}

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

interface CategoryHealth {
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: MonitorTrend[];
}

interface AssetHealth {
  name: string;
  fqn: string;
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: MonitorTrend[];
}

interface TrendData {
  dataHealth: Record<string, CategoryHealth>;
  pipelineHealth: Record<string, CategoryHealth>;
  assets: Record<string, AssetHealth>;
  updatedAt: string;
}

interface Props {
  watches: WatchSummary[];
  tasks: ScheduledTask[];
  loading: boolean;
}

export function DriftSummaryTab({ watches, tasks, loading: monitorsLoading }: Props) {
  const { selectedPipelineId } = usePipeline();
  const [trendData, setTrendData] = useState<TrendData | null>(null);
  const [trendLoading, setTrendLoading] = useState(true);
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [driftLoading, setDriftLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [showDriftSection, setShowDriftSection] = useState(false);
  const [activeCategories, setActiveCategories] = useState<Set<string>>(new Set());

  const fetchTrends = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const res = await fetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`);
      if (res.ok) {
        const data = await res.json();
        setTrendData(data);
      }
    } catch (err) {
      console.error('[HealthDashboard] Fetch error:', err);
    } finally {
      setTrendLoading(false);
    }
  }, [selectedPipelineId]);

  useEffect(() => { fetchTrends(); }, [fetchTrends]);

  useEffect(() => {
    if (!selectedPipelineId) return;
    const timer = setInterval(fetchTrends, 30000);
    return () => clearInterval(timer);
  }, [fetchTrends, selectedPipelineId]);

  const fetchRecommendations = useCallback(async () => {
    if (!selectedPipelineId) return;
    setDriftLoading(true);
    try {
      const res = await fetch(`/api/drift?status=pending&stackId=${selectedPipelineId}`);
      if (res.ok) {
        const data = await res.json();
        setRecommendations(data.recommendations || []);
        setLastAnalyzedAt(data.lastAnalyzedAt);
        setCounts(data.counts || {});
      }
    } catch (err) {
      console.error('[DriftSummary] Fetch error:', err);
    } finally {
      setDriftLoading(false);
    }
  }, [selectedPipelineId]);

  useEffect(() => { fetchRecommendations(); }, [fetchRecommendations]);

  const handleRunAnalysis = async () => {
    if (!selectedPipelineId) return;
    setRunning(true);
    try {
      const res = await fetch('/api/drift/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stackId: selectedPipelineId }),
      });
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
    if (!selectedPipelineId) return;
    const action = value ? 'accept_with_value' : 'accept';
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, value, stackId: selectedPipelineId }),
    });
    if (res.ok) {
      toast.success('Recommendation applied');
      fetchRecommendations();
    } else {
      toast.error('Failed to apply');
    }
  };

  const handleDismiss = async (id: string) => {
    if (!selectedPipelineId) return;
    const res = await fetch(`/api/drift/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'dismiss', stackId: selectedPipelineId }),
    });
    if (res.ok) {
      fetchRecommendations();
    } else {
      toast.error('Failed to dismiss');
    }
  };

  const toggleSection = (key: string) => {
    setExpandedSection((prev) => (prev === key ? null : key));
  };

  const toggleCategoryFilter = (key: string) => {
    setActiveCategories((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const dataCategories = useMemo(() => {
    if (!trendData) return [];
    return DATA_CATEGORIES
      .filter((cat) => trendData.dataHealth[cat.key])
      .map((cat) => ({ ...cat, ...trendData.dataHealth[cat.key] }));
  }, [trendData]);

  const pipelineTools = useMemo(() => {
    if (!trendData) return [];
    return Object.entries(trendData.pipelineHealth).map(([key, data]) => ({
      key,
      label: key.charAt(0).toUpperCase() + key.slice(1),
      ...data,
    }));
  }, [trendData]);

  const assetList = useMemo(() => {
    if (!trendData?.assets) return [];
    let list = Object.values(trendData.assets);
    if (activeCategories.size > 0) {
      list = list.filter((a) => a.monitors.some((m) => activeCategories.has(m.category)));
    }
    list.sort((a, b) => {
      if (a.failing !== b.failing) return b.failing - a.failing;
      if (a.warning !== b.warning) return b.warning - a.warning;
      return a.name.localeCompare(b.name);
    });
    return list;
  }, [trendData, activeCategories]);

  const totalDataMonitors = dataCategories.reduce((s, c) => s + c.total, 0);
  const totalPipelineMonitors = pipelineTools.reduce((s, t) => s + t.total, 0);
  const pending = counts.pending || 0;

  useEffect(() => {
    if (expandedSection !== null || !trendData?.assets) return;
    const failing = assetList.find((a) => a.status === 'drifting');
    const warning = assetList.find((a) => a.status === 'warning');
    const first = failing || warning || assetList[0];
    if (first) setExpandedSection(`asset-${first.fqn}`);
  }, [trendData]); // eslint-disable-line react-hooks/exhaustive-deps

  if (trendLoading && monitorsLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  if (totalDataMonitors === 0 && totalPipelineMonitors === 0 && !trendLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Activity className="w-8 h-8 text-[var(--text-faint)] mb-3" />
        <p className="text-[13px] text-[var(--muted)]">No monitors configured yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 w-full">
      {/* Data Health */}
      {totalDataMonitors > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <h2 className="text-[14px] font-semibold text-[var(--text)]">Data Health</h2>
              <span className="text-[11px] text-[var(--muted)]">{assetList.length} assets · {totalDataMonitors} monitors</span>
            </div>
            {trendData?.updatedAt && (
              <span className="text-[10px] text-[var(--muted)]">
                Updated {new Date(trendData.updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5 mb-3">
            {dataCategories.map((cat) => {
              const isActive = activeCategories.has(cat.key);
              const style = STATUS_STYLES[cat.status] || STATUS_STYLES.pending;
              return (
                <button
                  key={cat.key}
                  onClick={() => toggleCategoryFilter(cat.key)}
                  className={cn(
                    'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium transition-all border',
                    isActive
                      ? `${style.border} ${style.badgeBg} ${style.text}`
                      : 'border-transparent bg-[var(--overlay-bg)] text-[var(--muted)] hover:text-[var(--text)]',
                  )}
                >
                  <div className={cn('w-1.5 h-1.5 rounded-full', style.accent)} />
                  {cat.label}
                  <span className="opacity-60">{cat.passing}/{cat.total}</span>
                </button>
              );
            })}
          </div>

          <div className="space-y-2">
            {assetList.map((asset) => (
              <AssetHealthRow
                key={asset.fqn}
                asset={asset}
                expanded={expandedSection === `asset-${asset.fqn}`}
                onToggle={() => toggleSection(`asset-${asset.fqn}`)}
                activeCategories={activeCategories}
                onRunAnalysis={handleRunAnalysis}
              />
            ))}
          </div>

          {assetList.length === 0 && activeCategories.size > 0 && (
            <p className="text-[12px] text-[var(--muted)] text-center py-6">No assets have monitors in the selected categories</p>
          )}
        </div>
      )}

      {/* Pipeline Health */}
      {totalPipelineMonitors > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <h2 className="text-[14px] font-semibold text-[var(--text)]">Pipeline Health</h2>
              <span className="text-[11px] text-[var(--muted)]">{totalPipelineMonitors} monitors</span>
            </div>
          </div>

          <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
            {pipelineTools.map((tool) => {
              const style = STATUS_STYLES[tool.status] || STATUS_STYLES.pending;
              const isExpanded = expandedSection === `pipeline-${tool.key}`;
              const passPct = tool.total > 0 ? (tool.passing / tool.total) * 100 : 0;
              return (
                <button
                  key={tool.key}
                  onClick={() => toggleSection(`pipeline-${tool.key}`)}
                  className={cn(
                    'rounded-xl border overflow-hidden text-left transition-all hover:shadow-md',
                    isExpanded ? `${style.border} bg-[var(--surface)] shadow-sm` : 'border-[var(--subtle-border)] bg-[var(--surface)]',
                  )}
                >
                  <div className={cn('h-1', style.accent, isExpanded ? 'opacity-100' : 'opacity-40')} />
                  <div className="px-4 py-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-semibold text-[var(--text)] uppercase tracking-wide">{tool.label}</span>
                      <span className={cn('text-[9px] font-medium px-1.5 py-0.5 rounded-full', style.badgeBg, style.text)}>
                        {STATUS_LABELS[tool.status] || tool.status}
                      </span>
                    </div>
                    <div className={cn('text-[22px] font-bold tabular-nums', tool.failing > 0 ? 'text-red-500' : tool.warning > 0 ? 'text-amber-500' : 'text-emerald-500')}>
                      {tool.passing}<span className="text-[14px] font-normal text-[var(--muted)]">/{tool.total}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-[var(--overlay-bg)] mt-2 overflow-hidden">
                      <div
                        className={cn('h-full rounded-full transition-all', style.accent)}
                        style={{ width: `${passPct}%` }}
                      />
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {pipelineTools.map((tool) => {
            if (expandedSection !== `pipeline-${tool.key}`) return null;
            const style = STATUS_STYLES[tool.status] || STATUS_STYLES.pending;
            return (
              <div key={tool.key} className="mt-2">
                <CategorySparklinePanel
                  label={tool.label}
                  failingCount={tool.failing}
                  monitors={tool.monitors}
                  borderColor={style.border}
                />
              </div>
            );
          })}
        </div>
      )}

      {/* SLA Recommendations */}
      <div className="rounded-xl border border-[var(--subtle-border)] bg-[var(--surface)] overflow-hidden">
        <button
          onClick={() => setShowDriftSection(!showDriftSection)}
          className="w-full px-5 py-3 flex items-center justify-between hover:bg-[var(--hover-bg)] transition-colors"
        >
          <div className="flex items-center gap-3">
            <span className="text-[13px] font-medium text-[var(--muted)]">SLA Recommendations</span>
            {pending > 0 && (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[var(--accent)]/10 text-[var(--accent)]">
                {pending} pending
              </span>
            )}
            {lastAnalyzedAt && (
              <span className="text-[10px] text-[var(--text-faint)]">
                Last run: {new Date(lastAnalyzedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[var(--text-faint)]">AI-powered threshold tuning</span>
            <ChevronDown className={cn('w-4 h-4 text-[var(--muted)] transition-transform', showDriftSection && 'rotate-180')} />
          </div>
        </button>

        {showDriftSection && (
          <div className="px-5 pb-5 border-t border-[var(--subtle-border)]">
            <div className="flex items-center justify-between pt-3 mb-4">
              <div className="flex items-center gap-2 text-[11px]">
                {(counts.accepted || 0) > 0 && <span className="text-emerald-400">{counts.accepted} applied</span>}
                {(counts.dismissed || 0) > 0 && <span className="text-zinc-400">{counts.dismissed} dismissed</span>}
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

            {driftLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
              </div>
            ) : recommendations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8">
                <Activity className="w-6 h-6 text-[var(--text-faint)] mb-2" />
                <p className="text-[12px] text-[var(--muted)]">No pending recommendations. Run an analysis to check for SLA drift.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {recommendations.map((rec) => (
                  <DriftRecommendationCard
                    key={rec.id}
                    rec={rec}
                    onAccept={handleAccept}
                    onDismiss={handleDismiss}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
