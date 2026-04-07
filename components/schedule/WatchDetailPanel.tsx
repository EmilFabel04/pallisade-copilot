'use client';

import { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import type { WatchSummary } from '@/types/health-watch';
import {
  WATCH_TYPE_LABELS,
  HEALTH_STATUS_COLORS,
  HEALTH_STATUS_LABELS,
  FAILURE_CATEGORY_LABELS,
  healthStatusFromScore,
  type HealthStatus,
  type FailureCategory,
  type HealthReport,
} from '@/types/health-watch';
import { RUN_STATUS_COLORS } from '@/types/schedule';
import type { TaskRun } from '@/types/schedule';
import { RunHistoryTable } from './RunHistoryTable';
import { MonitorEditPanel } from './MonitorEditPanel';
import { getMonitorDefinition, MONITOR_CATEGORY_LABELS, MONITOR_CATEGORY_ORDER, type MonitorCategory } from '@/types/monitor-catalog';

interface WatchDetailPanelProps {
  watch: WatchSummary;
  detailMonitors: any[];
  detailLoading: boolean;
  onBack: () => void;
  onRunAll: () => void;
  onDelete: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRemoveMonitor?: (monitorId: string) => void;
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

export function WatchDetailPanel({
  watch,
  detailMonitors,
  detailLoading,
  onBack,
  onRunAll,
  onDelete,
  onToggleEnabled,
  onRemoveMonitor,
}: WatchDetailPanelProps) {
  const healthStatus: HealthStatus | null = watch.healthScore != null
    ? healthStatusFromScore(watch.healthScore)
    : null;

  const healthReport = watch.healthDetails as HealthReport | undefined;
  const failureGroups = healthReport?.failureGroups || [];
  const coveragePct = watch.coveragePct != null ? Math.round(watch.coveragePct * 100) : null;
  const [expandedMonitorId, setExpandedMonitorId] = useState<string | null>(null);
  const [editingMonitorId, setEditingMonitorId] = useState<string | null>(null);
  const [monitorRuns, setMonitorRuns] = useState<Record<string, TaskRun[]>>({});
  const [monitorRunsLoading, setMonitorRunsLoading] = useState<Record<string, boolean>>({});

  const fetchMonitorRuns = useCallback(async (monitorId: string) => {
    if (monitorRuns[monitorId]) return; // already fetched
    setMonitorRunsLoading((prev) => ({ ...prev, [monitorId]: true }));
    try {
      const res = await fetch(`/api/schedule/tasks/${monitorId}/runs?limit=10`);
      if (res.ok) {
        const data = await res.json();
        setMonitorRuns((prev) => ({ ...prev, [monitorId]: data.runs || [] }));
      }
    } catch (err) {
      console.error('[WatchDetail] Failed to fetch monitor runs:', err);
    } finally {
      setMonitorRunsLoading((prev) => ({ ...prev, [monitorId]: false }));
    }
  }, [monitorRuns]);

  const handleToggleMonitor = useCallback((monitorId: string) => {
    if (expandedMonitorId === monitorId) {
      setExpandedMonitorId(null);
    } else {
      setExpandedMonitorId(monitorId);
      fetchMonitorRuns(monitorId);
    }
  }, [expandedMonitorId, fetchMonitorRuns]);

  return (
    <div className={cn("flex flex-col h-full bg-[var(--surface-inset)]", !watch.enabled && "opacity-60")}>
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
              {!watch.enabled && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)]">
                  Disabled
                </span>
              )}
              {watch.enabled && healthStatus && (
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
          <button
            onClick={() => onToggleEnabled(!watch.enabled)}
            className={cn(
              'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
              watch.enabled ? 'bg-blue-500' : 'bg-[var(--overlay-strong)]'
            )}
            title={watch.enabled ? 'Disable watch' : 'Enable watch'}
          >
            <span
              className={cn(
                'pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-lg transition-transform',
                watch.enabled ? 'translate-x-4' : 'translate-x-0'
              )}
            />
          </button>
          <Button variant="ghost" size="sm" onClick={onRunAll}>
            Run All
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
      {healthReport && (
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
      )}

      {/* Config summary (when no health report yet) */}
      {!healthReport && (
        <div className="px-6 py-4 border-b border-[var(--border-faint)]">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Schedule</p>
              <p className="text-[13px] text-[var(--text-secondary)]">{cronToHuman(watch.schedule || '')}</p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Monitors</p>
              <p className="text-[13px] text-[var(--text-secondary)]">
                {watch.passCount}/{watch.monitorCount} passing
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Status</p>
              <p className="text-[13px] text-[var(--text-secondary)]">
                {watch.enabled ? 'Enabled' : 'Disabled'}
              </p>
            </div>
          </div>
        </div>
      )}

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
                      const monStatus = mon.lastStatus
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
                              {mon.lastStatus || 'NEW'}
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
                                    await fetch(`/api/schedule/watches/${watch.id}/monitors/${monitorId}`, {
                                      method: 'PUT',
                                      headers: { 'Content-Type': 'application/json' },
                                      body: JSON.stringify({ config, policyOverrides }),
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
                </div>
              );
            })}
          </div>
        ) : (
          <div className="space-y-2">
            {detailMonitors.map((mon: any) => {
              const monStatus = mon.lastStatus
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
                      {mon.lastStatus || 'NEW'}
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
                            await fetch(`/api/schedule/watches/${watch.id}/monitors/${monitorId}`, {
                              method: 'PUT',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ config, policyOverrides }),
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
