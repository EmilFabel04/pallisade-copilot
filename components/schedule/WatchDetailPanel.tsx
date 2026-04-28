'use client';

import { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { usePipeline } from '@/contexts/PipelineContext';
import type { WatchSummary } from '@/types/health-watch';
import {
  WATCH_TYPE_LABELS,
  HEALTH_STATUS_COLORS,
  HEALTH_STATUS_LABELS,
  FAILURE_CATEGORY_LABELS,
  healthStatusFromScore,
  type HealthStatus,
  type FailureCategory,
  type FailureGroup,
  type HealthReport,
} from '@/types/health-watch';
import { RUN_STATUS_COLORS } from '@/types/schedule';
import type { TaskRun } from '@/types/schedule';
import { RunHistoryTable } from './RunHistoryTable';
import { MonitorEditPanel } from './MonitorEditPanel';
import { getMonitorDefinition, isMonitorConfigIncomplete, MONITOR_CATEGORY_LABELS, MONITOR_CATEGORY_ORDER, type MonitorCategory } from '@/types/monitor-catalog';

interface WatchDetailPanelProps {
  watch: WatchSummary;
  detailMonitors: any[];
  detailLoading: boolean;
  running?: boolean;
  onBack: () => void;
  onRunAll: () => void;
  onDelete: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRemoveMonitor?: (monitorId: string) => void;
  onSettings?: () => void;
  onMonitorConfigSaved?: (monitorId: string, config: Record<string, any>, policyOverrides: string[]) => void;
}

function cronToHuman(cron: string): string {
  const presets: Record<string, string> = {
    '0 * * * *': 'Every hour',
    '0 */6 * * *': 'Every 6 hours',
    '0 8 * * *': 'Daily at 8am',
    '0 8 * * 1-5': 'Weekdays at 8am',
    '0 8 * * 1': 'Weekly (Mon 8am)',
  };
  return presets[cron || ''] || cron || 'No schedule';
}

function timeAgo(dateStr?: string | null): string {
  if (!dateStr) return 'Never';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

// Mirror of scanner/monitors/health.py and the run-route mapping. Kept local
// because this is a UI-only fallback — authoritative categorization happens
// server-side when Run All writes healthDetails.
const MONITOR_TYPE_CATEGORY: Record<string, FailureCategory> = {
  FRESHNESS: 'stale_data',
  DBT_MODEL_FRESHNESS: 'stale_data',
  DBT_SOURCE_FRESHNESS: 'stale_data',
  BI_FRESHNESS_PROXY: 'stale_data',
  SCHEMA_CHANGE: 'schema_break',
  CONNECTOR_SCHEMA_DRIFT: 'schema_break',
  SYNC_LAG: 'ingestion_lag',
  FAILED_SYNCS: 'ingestion_lag',
  DAG_LAST_RUN: 'orchestration_failure',
  DAG_SCHEDULE_LAG: 'orchestration_failure',
  TASK_FAILURE_RATE: 'orchestration_failure',
  VOLUME: 'quality_anomaly',
  NULL_CHECK: 'quality_anomaly',
  NULL_RATE: 'quality_anomaly',
  UNIQUENESS_CHECK: 'quality_anomaly',
  RANGE_VALIDATION: 'quality_anomaly',
  ACCEPTED_VALUES: 'quality_anomaly',
  DATE_CONSISTENCY: 'quality_anomaly',
  DATA_TYPE_VALIDATION: 'quality_anomaly',
  DISTRIBUTION: 'quality_anomaly',
  ANOMALY: 'quality_anomaly',
  REFERENTIAL: 'quality_anomaly',
  CUSTOM_SQL: 'quality_anomaly',
  BI_UPSTREAM_BREAK_RISK: 'quality_anomaly',
  BI_CONTENT_HEALTH: 'quality_anomaly',
  BI_REFRESH_FAILURE: 'quality_anomaly',
  DBT_TEST_FAILURES: 'transform_failure',
};

function aggregateStatus(mons: Array<{ lastStatus?: string }>): string {
  if (mons.length === 0) return 'none';
  const statuses = new Set(mons.map((m) => m.lastStatus));
  const hasFail = statuses.has('FAIL') || statuses.has('ERROR');
  const hasPass = statuses.has('PASS');
  if (hasFail && hasPass) return 'mixed';
  if (hasFail) return 'fail';
  if (statuses.has('WARN')) return hasPass ? 'mixed' : 'warn';
  if (hasPass) return 'pass';
  return 'none';
}

function buildFallbackHealthReport(
  watch: WatchSummary,
  detailMonitors: any[],
): HealthReport {
  const total = watch.monitorCount || detailMonitors.length || 0;
  const pass = watch.passCount ?? 0;
  const warn = watch.warnCount ?? 0;

  // Always recompute from live pass/warn counts when we have monitors.
  // The persisted `watch.healthScore` only updates on full "Run All" passes,
  // so it goes stale whenever an individual monitor reruns — e.g. a group
  // whose last "Run All" failed everything stays at 0 even after a single
  // monitor flips back to PASS. The counts in `watch` are computed from
  // current monitor statuses each time the list is fetched, so they're
  // always fresh.
  const score = total > 0
    ? Math.round(((pass + 0.5 * warn) / total) * 1000) / 10
    : watch.healthScore != null
      ? watch.healthScore
      : 100;

  const depthOf = (m: any): number =>
    m.config?._watchDepth ?? (m.targetFqn === watch.anchorFqn ? 0 : 1);

  const direct = detailMonitors.filter((m) => depthOf(m) === 0);
  const upstream = detailMonitors.filter((m) => depthOf(m) > 0);

  const failing = detailMonitors.filter(
    (m) => m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR' || m.lastStatus === 'WARN',
  );

  const buckets = new Map<FailureCategory, any[]>();
  for (const m of failing) {
    const cat = (MONITOR_TYPE_CATEGORY[m.monitorType || ''] || 'quality_anomaly') as FailureCategory;
    const arr = buckets.get(cat) || [];
    arr.push(m);
    buckets.set(cat, arr);
  }

  const failureGroups: FailureGroup[] = Array.from(buckets.entries())
    .map(([category, mons]) => {
      const hasCritical = mons.some((m) => m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR');
      const parts = mons.slice(0, 3).map((m) => `${m.name}: ${m.lastStatus}`);
      if (mons.length > 3) parts.push(`+${mons.length - 3} more`);
      return {
        category,
        severity: hasCritical ? ('critical' as const) : ('warning' as const),
        summary: parts.join(', '),
        rootCauseHint: mons[0]?.targetFqn || 'unknown',
        signalCount: mons.length,
      };
    })
    .sort((a, b) => {
      if (a.severity !== b.severity) return a.severity === 'critical' ? -1 : 1;
      return b.signalCount - a.signalCount;
    });

  let summary: string;
  if (failureGroups.length === 0) {
    summary = total === 0
      ? 'No monitors yet'
      : `${pass} of ${total} monitor${total !== 1 ? 's' : ''} passing`;
  } else {
    const topLabel = FAILURE_CATEGORY_LABELS[failureGroups[0].category].toLowerCase();
    const totalSignals = failureGroups.reduce((s, g) => s + g.signalCount, 0);
    summary = totalSignals === 1
      ? `1 ${topLabel} signal`
      : `${totalSignals} signals across ${topLabel}${failureGroups.length > 1 ? ' and more' : ''}`;
  }

  return {
    healthScore: score,
    healthStatus: healthStatusFromScore(score),
    summary,
    directStatus: aggregateStatus(direct),
    upstreamStatus: aggregateStatus(upstream),
    coveragePct: watch.coveragePct ?? 1,
    failureGroups,
    computedAt: watch.lastHealthAt || watch.lastRunAt || new Date().toISOString(),
  };
}

export function WatchDetailPanel({
  watch,
  detailMonitors,
  detailLoading,
  running = false,
  onBack,
  onRunAll,
  onDelete,
  onToggleEnabled,
  onRemoveMonitor,
  onSettings,
  onMonitorConfigSaved,
}: WatchDetailPanelProps) {
  const { selectedPipelineId } = usePipeline();
  const storedReport = watch.healthDetails as HealthReport | undefined;
  // Prefer a fresh computation whenever we have live monitor counts or
  // detail rows — the stored report is only refreshed on a full "Run All"
  // and quickly goes stale as individual monitors rerun.
  const hasFreshSignal = (watch.monitorCount ?? 0) > 0 || detailMonitors.length > 0;
  const healthReport: HealthReport = hasFreshSignal
    ? buildFallbackHealthReport(watch, detailMonitors)
    : (storedReport || buildFallbackHealthReport(watch, detailMonitors));
  const healthStatus: HealthStatus = healthReport.healthStatus;
  const failureGroups = healthReport.failureGroups || [];
  const coveragePct = watch.coveragePct != null ? Math.round(watch.coveragePct * 100) : null;
  const [expandedMonitorId, setExpandedMonitorId] = useState<string | null>(null);
  const [editingMonitorId, setEditingMonitorId] = useState<string | null>(null);
  const [monitorRuns, setMonitorRuns] = useState<Record<string, TaskRun[]>>({});
  const [monitorRunsLoading, setMonitorRunsLoading] = useState<Record<string, boolean>>({});

  const fetchMonitorRuns = useCallback(async (monitorId: string) => {
    if (monitorRuns[monitorId]) return; // already fetched
    if (!selectedPipelineId) return;
    setMonitorRunsLoading((prev) => ({ ...prev, [monitorId]: true }));
    try {
      const res = await fetch(`/api/schedule/tasks/${monitorId}/runs?limit=10&stackId=${selectedPipelineId}`);
      if (res.ok) {
        const data = await res.json();
        setMonitorRuns((prev) => ({ ...prev, [monitorId]: data.runs || [] }));
      }
    } catch (err) {
      console.error('[WatchDetail] Failed to fetch monitor runs:', err);
    } finally {
      setMonitorRunsLoading((prev) => ({ ...prev, [monitorId]: false }));
    }
  }, [monitorRuns, selectedPipelineId]);

  const handleToggleMonitor = useCallback((monitorId: string) => {
    if (expandedMonitorId === monitorId) {
      setExpandedMonitorId(null);
    } else {
      setExpandedMonitorId(monitorId);
      fetchMonitorRuns(monitorId);
    }
  }, [expandedMonitorId, fetchMonitorRuns]);

  return (
    <div className={cn("flex flex-col h-full bg-[var(--surface-inset)]", watch.enabled === false && "opacity-60")}>
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[16px] font-semibold text-[var(--text)]">{watch.name}</h2>
              {watch.enabled === false && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)]">
                  Disabled
                </span>
              )}
              {watch.enabled !== false && healthStatus && (
                <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', HEALTH_STATUS_COLORS[healthStatus])}>
                  {HEALTH_STATUS_LABELS[healthStatus]}
                </span>
              )}
            </div>
            <p className="text-[12px] text-[var(--muted)] mt-0.5">
              {watch.monitorCount} monitor{watch.monitorCount !== 1 ? 's' : ''}
              {watch.schedule && ` · ${cronToHuman(watch.schedule)}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {onSettings && (
            <button
              onClick={onSettings}
              className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
              title="Group settings"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>
          )}
          <button
            onClick={() => onToggleEnabled(watch.enabled === false)}
            className={cn(
              'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
              watch.enabled !== false ? 'bg-blue-500' : 'bg-[var(--overlay-strong)]'
            )}
            title={watch.enabled !== false ? 'Disable watch' : 'Enable watch'}
          >
            <span
              className={cn(
                'pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-lg transition-transform',
                watch.enabled !== false ? 'translate-x-4' : 'translate-x-0'
              )}
            />
          </button>
          <Button variant="ghost" size="sm" onClick={onRunAll} disabled={running}>
            {running ? 'Running...' : 'Run All'}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-red-400 hover:text-red-300"
            onClick={onDelete}
          >
            Delete
          </Button>
        </div>
      </div>

      {/* Scrollable content area */}
      <div className="flex-1 overflow-y-auto">

      {/* Health summary card */}
      <div className="px-6 py-4 border-b border-[var(--border-faint)]">
        <div className="p-4 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)]">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <div className="text-[28px] font-bold text-[var(--text)] tabular-nums">
                {Math.round(healthReport.healthScore)}
              </div>
              <div>
                <p className="text-[13px] font-medium text-[var(--text)]">Health Score</p>
                <p className="text-[11px] text-[var(--muted)]">
                  {healthReport.summary}
                </p>
              </div>
            </div>
            {healthReport.computedAt && (
              <span className="text-[10px] text-[var(--text-faint)]">
                {timeAgo(healthReport.computedAt)}
              </span>
            )}
          </div>

          {/* Score bar */}
          <div className="h-2 rounded-full bg-[var(--overlay-bg)] overflow-hidden mb-3">
            <div
              className={cn(
                'h-full rounded-full transition-all',
                healthReport.healthScore >= 90 ? 'bg-emerald-500' :
                healthReport.healthScore >= 70 ? 'bg-amber-500' :
                healthReport.healthScore >= 40 ? 'bg-orange-500' :
                'bg-red-500'
              )}
              style={{ width: `${Math.min(healthReport.healthScore, 100)}%` }}
            />
          </div>

          {/* Status chips */}
          <div className="flex items-center gap-4 text-[11px]">
            <div>
              <span className="text-[var(--text-faint)]">Direct: </span>
              <span className="text-[var(--text-secondary)] capitalize">{healthReport.directStatus}</span>
            </div>
            <div>
              <span className="text-[var(--text-faint)]">Upstream: </span>
              <span className="text-[var(--text-secondary)] capitalize">{healthReport.upstreamStatus}</span>
            </div>
            {coveragePct != null && (
              <div>
                <span className="text-[var(--text-faint)]">Coverage: </span>
                <span className="text-[var(--text-secondary)]">{coveragePct}%</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Anchor info */}
      {watch.anchorFqn && (
        <div className="px-6 py-3 border-b border-[var(--border-faint)]">
          <div className="p-3 bg-[var(--overlay-bg)] rounded-lg border border-[var(--subtle-border)]">
            <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Anchor Asset</p>
            <div className="flex items-center gap-2">
              <p className="text-[13px] text-[var(--text-tertiary)] font-mono">{watch.anchorFqn}</p>
              {watch.anchorPlatform && (
                <span className="px-1.5 py-0.5 rounded text-[9px] font-medium uppercase bg-white/5 text-[var(--muted)]">
                  {watch.anchorPlatform}
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Failure groups */}
      {failureGroups.length > 0 && (
        <div className="px-6 py-3 border-b border-[var(--border-faint)]">
          <h3 className="text-[12px] font-medium text-[var(--text-faint)] uppercase tracking-wider mb-2">
            Issues
          </h3>
          <div className="space-y-2">
            {failureGroups.map((fg, i) => (
              <div
                key={i}
                className={cn(
                  'p-3 rounded-lg border',
                  fg.severity === 'critical'
                    ? 'border-red-500/20 bg-red-500/5'
                    : 'border-amber-500/20 bg-amber-500/5'
                )}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className={cn(
                    'text-[12px] font-medium',
                    fg.severity === 'critical' ? 'text-red-400' : 'text-amber-400'
                  )}>
                    {FAILURE_CATEGORY_LABELS[fg.category as FailureCategory] || fg.category.replace(/_/g, ' ')}
                  </span>
                  <span className={cn(
                    'px-1.5 py-0.5 rounded text-[10px] font-medium uppercase',
                    fg.severity === 'critical' ? 'bg-red-500/15 text-red-400' : 'bg-amber-500/15 text-amber-400'
                  )}>
                    {fg.severity}
                  </span>
                </div>
                <p className="text-[11px] text-[var(--muted)]">{fg.summary}</p>
                {fg.rootCauseHint && fg.rootCauseHint !== 'unknown' && (
                  <p className="text-[10px] text-[var(--text-faint)] mt-1 font-mono truncate" title={fg.rootCauseHint}>
                    Root: {fg.rootCauseHint}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Monitor list */}
      <div className="px-6 py-4">
        <h3 className="text-[14px] font-medium text-[var(--text)] mb-3">Monitors</h3>
        {detailLoading ? (
          <div className="flex items-center justify-center py-10">
            <div className="w-5 h-5 red-spinner" />
          </div>
        ) : detailMonitors.length === 0 ? (
          <p className="text-[13px] text-[var(--muted)] py-4">No monitors in this watch.</p>
        ) : watch.watchType === 'tool_health' ? (
          <div className="space-y-2">
            {(() => {
              const grouped = detailMonitors.reduce<Record<string, any[]>>((acc, mon) => {
                const def = getMonitorDefinition(mon.monitorType || '');
                const cat = def?.category || 'other';
                if (!acc[cat]) acc[cat] = [];
                acc[cat].push(mon);
                return acc;
              }, {});
              const orderedKeys = [
                ...MONITOR_CATEGORY_ORDER.filter((k) => grouped[k]),
                ...Object.keys(grouped).filter((k) => !MONITOR_CATEGORY_ORDER.includes(k as MonitorCategory)),
              ];
              return orderedKeys;
            })().map((category) => {
              const monitors = detailMonitors.reduce<any[]>((acc, mon) => {
                const def = getMonitorDefinition(mon.monitorType || '');
                const cat = def?.category || 'other';
                if (cat === category) acc.push(mon);
                return acc;
              }, []);
              const worstStatus = monitors.some((m) => m.lastStatus === 'FAIL') ? 'FAIL'
                : monitors.some((m) => m.lastStatus === 'WARN') ? 'WARN'
                : monitors.some((m) => m.lastStatus === 'PASS') ? 'PASS'
                : 'PENDING';
              const catLabel = MONITOR_CATEGORY_LABELS[category as MonitorCategory] || 'Uncategorized';
              return (
                <div key={category} className="rounded-lg border border-[var(--border)] bg-[var(--surface)]">
                  <div className="flex items-center gap-2 px-3 py-2">
                    <span className={cn('w-2 h-2 rounded-full', {
                      'bg-emerald-400': worstStatus === 'PASS',
                      'bg-amber-400': worstStatus === 'WARN',
                      'bg-red-400': worstStatus === 'FAIL',
                      'bg-[var(--muted)]/40': worstStatus === 'PENDING',
                    })} />
                    <span className="text-[12px] font-medium text-[var(--text)]">{catLabel}</span>
                    <span className="text-[10px] text-[var(--muted)] ml-auto">
                      {monitors.filter((m) => m.lastStatus === 'PASS').length}/{monitors.length} passing
                    </span>
                  </div>
                  <div className="px-3 pb-2 space-y-1">
                    {monitors.map((mon: any) => {
                      const monNeedsConfig = isMonitorConfigIncomplete(mon.monitorType, mon.config);
                      const monStatus = monNeedsConfig
                        ? 'bg-amber-500/15 text-amber-400'
                        : mon.lastStatus
                          ? RUN_STATUS_COLORS[mon.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
                          : 'bg-[var(--overlay-medium)] text-[var(--muted)]';
                      const isExpanded = expandedMonitorId === mon.id;
                      return (
                        <div
                          key={mon.id}
                          className="bg-[var(--surface)] border border-[var(--subtle-border)] rounded-lg overflow-hidden"
                        >
                          <button
                            type="button"
                            onClick={() => handleToggleMonitor(mon.id)}
                            className="flex items-center gap-3 p-3 w-full text-left hover:bg-[var(--hover-bg)] transition-colors"
                          >
                            <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium uppercase shrink-0', monStatus)}>
                              {monNeedsConfig ? 'NEEDS CONFIG' : mon.lastStatus || 'NEW'}
                            </span>
                            <div className="flex-1 min-w-0">
                              <p className="text-[13px] text-[var(--text)] truncate">{mon.name}</p>
                              <div className="flex items-center gap-2 text-[11px] text-[var(--muted)]">
                                {mon.monitorType && (
                                  <span className="px-1 py-0.5 rounded bg-white/5 text-[10px] uppercase">
                                    {mon.monitorType.replace(/_/g, ' ')}
                                  </span>
                                )}
                                {mon.targetFqn && (
                                  <span className="font-mono truncate max-w-[200px]" title={mon.targetFqn}>
                                    {mon.targetFqn}
                                  </span>
                                )}
                              </div>
                            </div>
                            {mon.lastRunAt && (
                              <span className="text-[11px] text-[var(--text-faint)] shrink-0">
                                {timeAgo(mon.lastRunAt)}
                              </span>
                            )}
                            <svg
                              className={cn('w-4 h-4 text-[var(--muted)] shrink-0 transition-transform', isExpanded && 'rotate-180')}
                              fill="none" stroke="currentColor" viewBox="0 0 24 24"
                            >
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                            </svg>
                          </button>
                          {isExpanded && (
                            <div className="px-4 pb-3 pt-1 border-t border-[var(--border-faint)]">
                              <RunHistoryTable
                                runs={monitorRuns[mon.id] || []}
                                loading={monitorRunsLoading[mon.id] || false}
                                taskName={mon.name}
                                monitorType={mon.monitorType}
                                targetFqn={mon.targetFqn}
                              />
                              {editingMonitorId === mon.id && (
                                <MonitorEditPanel
                                  monitor={{
                                    id: mon.id,
                                    name: mon.name,
                                    monitorType: mon.monitorType || '',
                                    targetFqn: mon.targetFqn,
                                    config: mon.config || {},
                                    policyOverrides: mon.policyOverrides || [],
                                  }}
                                  resolvedPolicy={mon.resolvedPolicy || null}
                                  onSave={async (monitorId: string, config: Record<string, any>, policyOverrides: string[]) => {
                                    if (!selectedPipelineId) return;
                                    const res = await fetch(`/api/schedule/watches/${watch.id}/monitors/${monitorId}`, {
                                      method: 'PUT',
                                      headers: { 'Content-Type': 'application/json' },
                                      body: JSON.stringify({ config, policyOverrides, stackId: selectedPipelineId }),
                                    });
                                    if (!res.ok) throw new Error('Failed to save');
                                    onMonitorConfigSaved?.(monitorId, config, policyOverrides);
                                    setEditingMonitorId(null);
                                  }}
                                />
                              )}
                              <div className="mt-2 pt-2 border-t border-[var(--border-faint)] flex items-center justify-between">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setEditingMonitorId(
                                      editingMonitorId === mon.id ? null : mon.id
                                    );
                                  }}
                                  className="text-[10px] text-[var(--text-faint)] hover:text-[var(--text-secondary)] underline"
                                >
                                  {editingMonitorId === mon.id ? 'Close' : 'Edit config'}
                                </button>
                                {onRemoveMonitor && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onRemoveMonitor(mon.id);
                                    }}
                                    className="text-[10px] text-red-400/70 hover:text-red-400 transition-colors"
                                  >
                                    Remove from watch
                                  </button>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="space-y-2">
            {detailMonitors.map((mon: any) => {
              const monNeedsConfig = isMonitorConfigIncomplete(mon.monitorType, mon.config);
              const monStatus = monNeedsConfig
                ? 'bg-amber-500/15 text-amber-400'
                : mon.lastStatus
                  ? RUN_STATUS_COLORS[mon.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
                  : 'bg-[var(--overlay-medium)] text-[var(--muted)]';
              const isExpanded = expandedMonitorId === mon.id;
              return (
                <div
                  key={mon.id}
                  className="bg-[var(--surface)] border border-[var(--subtle-border)] rounded-lg overflow-hidden"
                >
                  <button
                    type="button"
                    onClick={() => handleToggleMonitor(mon.id)}
                    className="flex items-center gap-3 p-3 w-full text-left hover:bg-[var(--hover-bg)] transition-colors"
                  >
                    <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium uppercase shrink-0', monStatus)}>
                      {monNeedsConfig ? 'NEEDS CONFIG' : mon.lastStatus || 'NEW'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] text-[var(--text)] truncate">{mon.name}</p>
                      <div className="flex items-center gap-2 text-[11px] text-[var(--muted)]">
                        {mon.monitorType && (
                          <span className="px-1 py-0.5 rounded bg-white/5 text-[10px] uppercase">
                            {mon.monitorType.replace(/_/g, ' ')}
                          </span>
                        )}
                        {mon.targetFqn && (
                          <span className="font-mono truncate max-w-[200px]" title={mon.targetFqn}>
                            {mon.targetFqn}
                          </span>
                        )}
                      </div>
                    </div>
                    {mon.lastRunAt && (
                      <span className="text-[11px] text-[var(--text-faint)] shrink-0">
                        {timeAgo(mon.lastRunAt)}
                      </span>
                    )}
                    <svg
                      className={cn('w-4 h-4 text-[var(--muted)] shrink-0 transition-transform', isExpanded && 'rotate-180')}
                      fill="none" stroke="currentColor" viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  {isExpanded && (
                    <div className="px-4 pb-3 pt-1 border-t border-[var(--border-faint)]">
                      <RunHistoryTable
                        runs={monitorRuns[mon.id] || []}
                        loading={monitorRunsLoading[mon.id] || false}
                        taskName={mon.name}
                        monitorType={mon.monitorType}
                        targetFqn={mon.targetFqn}
                      />
                      {editingMonitorId === mon.id && (
                        <MonitorEditPanel
                          monitor={{
                            id: mon.id,
                            name: mon.name,
                            monitorType: mon.monitorType || '',
                            targetFqn: mon.targetFqn,
                            config: mon.config || {},
                            policyOverrides: mon.policyOverrides || [],
                          }}
                          resolvedPolicy={mon.resolvedPolicy || null}
                          onSave={async (monitorId: string, config: Record<string, any>, policyOverrides: string[]) => {
                            if (!selectedPipelineId) return;
                            await fetch(`/api/schedule/watches/${watch.id}/monitors/${monitorId}`, {
                              method: 'PUT',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ config, policyOverrides, stackId: selectedPipelineId }),
                            });
                            setEditingMonitorId(null);
                          }}
                        />
                      )}
                      <div className="mt-2 pt-2 border-t border-[var(--border-faint)] flex items-center justify-between">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingMonitorId(
                              editingMonitorId === mon.id ? null : mon.id
                            );
                          }}
                          className="text-[10px] text-[var(--text-faint)] hover:text-[var(--text-secondary)] underline"
                        >
                          {editingMonitorId === mon.id ? 'Close' : 'Edit config'}
                        </button>
                        {onRemoveMonitor && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemoveMonitor(mon.id);
                            }}
                            className="text-[10px] text-red-400/70 hover:text-red-400 transition-colors"
                          >
                            Remove from watch
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      </div>{/* end scrollable content */}
    </div>
  );
}
