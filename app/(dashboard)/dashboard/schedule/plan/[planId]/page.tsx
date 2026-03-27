'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { usePipeline } from '@/contexts/PipelineContext';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { RunHistoryTable } from '@/components/schedule/RunHistoryTable';
import { RUN_STATUS_COLORS } from '@/types/schedule';
import type { TaskRun } from '@/types/schedule';
import {
  healthStatusFromScore,
  HEALTH_STATUS_COLORS,
  HEALTH_STATUS_LABELS,
  type HealthStatus,
} from '@/types/health-watch';
import { MonitorEditPanel } from '@/components/schedule/MonitorEditPanel';
import { WatchEditModal } from '@/components/schedule/WatchEditModal';
import { Settings } from 'lucide-react';
import { getMonitorSLAStatus } from '@/lib/sla-utils';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PlanDetailPage() {
  const { planId } = useParams<{ planId: string }>();
  const router = useRouter();
  const { selectedPipelineId } = usePipeline();

  const [plan, setPlan] = useState<any>(null);
  const [aggregate, setAggregate] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  // Monitor run expansion
  const [expandedMonitorId, setExpandedMonitorId] = useState<string | null>(null);
  const [monitorRuns, setMonitorRuns] = useState<Record<string, TaskRun[]>>({});
  const [monitorRunsLoading, setMonitorRunsLoading] = useState<Record<string, boolean>>({});
  const [editingMonitorId, setEditingMonitorId] = useState<string | null>(null);
  const [showPlanEditModal, setShowPlanEditModal] = useState(false);
  const [resolvedPolicies, setResolvedPolicies] = useState<Record<string, any>>({});
  const [runningMonitorIds, setRunningMonitorIds] = useState<Set<string>>(new Set());
  const [runStartedAt, setRunStartedAt] = useState<string | null>(null);

  // Fetch plan data (initialLoad controls whether full-page spinner shows)
  const fetchPlan = useCallback(async (initialLoad = false) => {
    if (!planId) return;
    if (initialLoad) setLoading(true);
    try {
      const res = await fetch(`/api/schedule/plans/${planId}`);
      if (res.ok) {
        const data = await res.json();
        setPlan(data.plan);
        setAggregate(data.aggregate);

        // Resolve policies for all monitor targets
        const allMons = (data.plan?.monitorGroups || []).flatMap(
          (g: any) => g.monitors || []
        );
        const fqns = [...new Set(
          allMons.map((m: any) => m.targetFqn).filter(Boolean)
        )] as string[];
        if (fqns.length > 0) {
          try {
            const policyRes = await fetch('/api/schedule/policies/resolve', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                nodes: fqns.map((fqn) => ({
                  fqn, domain: 'warehouse', criticality: 'medium',
                })),
                stackId: selectedPipelineId,
              }),
            });
            if (policyRes.ok) {
              const policyData = await policyRes.json();
              setResolvedPolicies(policyData.policies || {});
            }
          } catch {
            // Policy resolution is non-fatal
          }
        }
      }
    } catch (err) {
      console.error('[PlanDetail] Failed to fetch plan:', err);
    } finally {
      if (initialLoad) setLoading(false);
    }
  }, [planId]);

  useEffect(() => {
    fetchPlan(true);
  }, [fetchPlan]);

  // Fetch runs for a specific monitor
  const fetchMonitorRuns = useCallback(async (monitorId: string) => {
    if (monitorRuns[monitorId]) return;
    setMonitorRunsLoading((prev) => ({ ...prev, [monitorId]: true }));
    try {
      const res = await fetch(`/api/schedule/tasks/${monitorId}/runs?limit=10`);
      if (res.ok) {
        const data = await res.json();
        setMonitorRuns((prev) => ({ ...prev, [monitorId]: data.runs || [] }));
      }
    } catch (err) {
      console.error('[PlanDetail] Failed to fetch monitor runs:', err);
    } finally {
      setMonitorRunsLoading((prev) => ({ ...prev, [monitorId]: false }));
    }
  }, [monitorRuns]);

  // Auto-refetch runs when the expanded monitor's cache is cleared (after a run completes)
  useEffect(() => {
    if (expandedMonitorId && !monitorRuns[expandedMonitorId]) {
      fetchMonitorRuns(expandedMonitorId);
    }
  }, [expandedMonitorId, monitorRuns, fetchMonitorRuns]);

  const handleToggleMonitor = useCallback((monitorId: string) => {
    if (expandedMonitorId === monitorId) {
      setExpandedMonitorId(null);
    } else {
      setExpandedMonitorId(monitorId);
      fetchMonitorRuns(monitorId);
    }
  }, [expandedMonitorId, fetchMonitorRuns]);

  // Toggle plan enabled
  const handleToggleEnabled = useCallback(async (enabled: boolean) => {
    if (!planId) return;
    try {
      await fetch(`/api/schedule/plans/${planId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      fetchPlan();
    } catch (err) {
      console.error('[PlanDetail] Failed to toggle plan:', err);
    }
  }, [planId, fetchPlan]);

  // Run all monitors (fire-and-forget, runs in background)
  const handleRunAll = useCallback(async () => {
    if (!plan) return;
    const allMons = (plan.monitorGroups || []).flatMap((g: any) => g.monitors || []);
    const monIds = allMons.map((m: any) => m.id);
    const startTime = new Date().toISOString();
    setRunningMonitorIds(new Set(monIds));
    setRunStartedAt(startTime);

    // Fire the plan-level run endpoint (non-blocking)
    fetch(`/api/schedule/plans/${planId}/run`, { method: 'POST' }).catch((err) => {
      console.error('[PlanDetail] Run all failed:', err);
    });

    // Poll for updated results — check which monitors have completed since startTime
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`/api/schedule/plans/${planId}`);
        if (!res.ok) return;
        const data = await res.json();
        setPlan(data.plan);
        setAggregate(data.aggregate);

        // Check which monitors have run since we started
        const currentMons = (data.plan?.monitorGroups || []).flatMap((g: any) => g.monitors || []);
        const stillRunning = new Set<string>();
        const justCompleted: string[] = [];
        for (const id of monIds) {
          const mon = currentMons.find((m: any) => m.id === id);
          // Still running if no lastRunAt or lastRunAt is before we started
          if (!mon?.lastRunAt || new Date(mon.lastRunAt) < new Date(startTime)) {
            stillRunning.add(id);
          } else if (runningMonitorIds.has(id)) {
            justCompleted.push(id);
          }
        }
        // Clear cached runs for monitors that just completed so logs refresh
        if (justCompleted.length > 0) {
          setMonitorRuns((prev) => {
            const next = { ...prev };
            for (const id of justCompleted) delete next[id];
            return next;
          });
        }
        setRunningMonitorIds(stillRunning);
        if (stillRunning.size === 0) {
          clearInterval(poll);
          setRunStartedAt(null);
        }
      } catch {
        // Keep polling
      }
    }, 3000);

    // Safety: stop polling after 2 minutes
    setTimeout(() => {
      clearInterval(poll);
      setRunningMonitorIds(new Set());
      setRunStartedAt(null);
    }, 120000);
  }, [plan, planId]);

  // Delete plan
  const handleDelete = useCallback(async () => {
    if (!planId || !confirm('Delete this monitoring plan? Groups will become standalone.')) return;
    try {
      await fetch(`/api/schedule/plans/${planId}`, { method: 'DELETE' });
      router.push('/dashboard/schedule');
    } catch (err) {
      console.error('[PlanDetail] Failed to delete plan:', err);
    }
  }, [planId, router]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-6 h-6 red-spinner" />
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <p className="text-[14px] text-[var(--muted)]">Plan not found</p>
        <Button variant="ghost" onClick={() => router.push('/dashboard/schedule')}>
          Back to Schedule
        </Button>
      </div>
    );
  }

  // Flatten all monitors from all groups
  const allMonitors: any[] = (plan.monitorGroups || []).flatMap((g: any) =>
    (g.monitors || []).map((m: any) => ({ ...m, groupName: g.name, groupId: g.id }))
  );

  const totalMonitors = aggregate?.totalMonitors || allMonitors.length;
  const passCount = aggregate?.passCount || 0;
  const warnCount = aggregate?.warnCount || 0;
  const failCount = aggregate?.failCount || 0;
  const errorCount = aggregate?.errorCount || 0;
  const pendingCount = totalMonitors - passCount - warnCount - failCount - errorCount;
  const ranCount = passCount + warnCount + failCount + errorCount;

  // Compute health from actual results (pass=100, warn=50, fail/error=0)
  const computedHealth = ranCount > 0
    ? Math.round(((passCount * 100) + (warnCount * 50)) / ranCount)
    : null;
  const healthStatus: HealthStatus | null =
    computedHealth != null ? healthStatusFromScore(computedHealth) : null;

  return (
    <div className="flex flex-col h-full bg-[var(--surface-inset)]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)] bg-[var(--surface)]">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push('/dashboard/schedule')}
            className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-[var(--accent)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
              </svg>
              <h2 className="text-[16px] font-semibold text-[var(--text)]">{plan.name}</h2>
              {!plan.enabled && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)]">
                  Disabled
                </span>
              )}
              {healthStatus && (
                <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', HEALTH_STATUS_COLORS[healthStatus])}>
                  {HEALTH_STATUS_LABELS[healthStatus]}
                </span>
              )}
              {!healthStatus && plan.enabled && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)]">
                  NEW
                </span>
              )}
            </div>
            <p className="text-[12px] text-[var(--muted)] mt-0.5">
              {totalMonitors} monitor{totalMonitors !== 1 ? 's' : ''}
              {plan.schedule && ` · ${cronToHuman(plan.schedule)}`}
              {plan.timezone && plan.timezone !== 'UTC' && ` · ${plan.timezone}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowPlanEditModal(true)}
            className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors"
            title="Edit plan settings"
          >
            <Settings size={16} />
          </button>
          <button
            onClick={() => handleToggleEnabled(!plan.enabled)}
            className={cn(
              'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
              plan.enabled ? 'bg-blue-500' : 'bg-[var(--overlay-strong)]'
            )}
            title={plan.enabled ? 'Disable plan' : 'Enable plan'}
          >
            <span
              className={cn(
                'pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-lg transition-transform',
                plan.enabled ? 'translate-x-4' : 'translate-x-0'
              )}
            />
          </button>
          <Button variant="ghost" size="sm" onClick={handleRunAll} disabled={runningMonitorIds.size > 0}>
            {runningMonitorIds.size > 0 ? `Running (${runningMonitorIds.size})...` : 'Run All'}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-red-400 hover:text-red-300"
            onClick={handleDelete}
          >
            Delete
          </Button>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto">
        {/* Summary metrics */}
        <div className="px-6 py-5 border-b border-[var(--border-faint)]">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <MetricCard
              label="Total"
              value={totalMonitors}
              color="text-[var(--text)]"
            />
            <MetricCard
              label="Passing"
              value={passCount}
              color="text-emerald-400"
              bar={totalMonitors > 0 ? passCount / totalMonitors : 0}
              barColor="bg-emerald-500"
            />
            <MetricCard
              label="Warning"
              value={warnCount}
              color="text-amber-400"
              bar={totalMonitors > 0 ? warnCount / totalMonitors : 0}
              barColor="bg-amber-500"
            />
            <MetricCard
              label="Failing"
              value={failCount + errorCount}
              color="text-red-400"
              bar={totalMonitors > 0 ? (failCount + errorCount) / totalMonitors : 0}
              barColor="bg-red-500"
            />
            <MetricCard
              label="Pending"
              value={pendingCount}
              color="text-[var(--muted)]"
              bar={totalMonitors > 0 ? pendingCount / totalMonitors : 0}
              barColor="bg-[var(--overlay-strong)]"
            />
          </div>

          {/* Status bar */}
          {totalMonitors > 0 && (
            <div className="mt-4 h-2 rounded-full bg-[var(--overlay-bg)] overflow-hidden flex">
              {passCount > 0 && (
                <div
                  className="bg-emerald-500/70 h-full transition-all"
                  style={{ width: `${(passCount / totalMonitors) * 100}%` }}
                />
              )}
              {warnCount > 0 && (
                <div
                  className="bg-amber-500/70 h-full transition-all"
                  style={{ width: `${(warnCount / totalMonitors) * 100}%` }}
                />
              )}
              {(failCount + errorCount) > 0 && (
                <div
                  className="bg-red-500/70 h-full transition-all"
                  style={{ width: `${((failCount + errorCount) / totalMonitors) * 100}%` }}
                />
              )}
            </div>
          )}
        </div>

        {/* Plan info row */}
        <div className="px-6 py-3 border-b border-[var(--border-faint)] flex items-center gap-6 text-[12px] text-[var(--muted)]">
          {plan.schedule && (
            <div>
              <span className="text-[var(--text-faint)]">Schedule: </span>
              <span className="text-[var(--text-secondary)]">{cronToHuman(plan.schedule)}</span>
            </div>
          )}
          <div>
            <span className="text-[var(--text-faint)]">Groups: </span>
            <span className="text-[var(--text-secondary)]">{plan.monitorGroups?.length || 0}</span>
          </div>
          {plan.createdAt && (
            <div>
              <span className="text-[var(--text-faint)]">Created: </span>
              <span className="text-[var(--text-secondary)]">{timeAgo(plan.createdAt)}</span>
            </div>
          )}
        </div>

        {/* Monitor list */}
        <div className="px-6 py-4">
          <h3 className="text-[14px] font-medium text-[var(--text)] mb-3">
            Monitors
            <span className="text-[var(--muted)] font-normal ml-2">({allMonitors.length})</span>
          </h3>

          {allMonitors.length === 0 ? (
            <p className="text-[13px] text-[var(--muted)] py-4">No monitors in this plan yet.</p>
          ) : (
            <div className="space-y-2">
              {allMonitors.map((mon: any) => {
                const monStatus = mon.lastStatus
                  ? RUN_STATUS_COLORS[mon.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
                  : 'bg-[var(--overlay-medium)] text-[var(--muted)]';
                const isExpanded = expandedMonitorId === mon.id;
                const monPolicy = mon.targetFqn ? resolvedPolicies[mon.targetFqn] : null;
                const policyStatus = getMonitorSLAStatus(
                  mon.monitorType || '', mon.config || {}, monPolicy
                );
                const needsConfig = policyStatus.status === 'needs_config';
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
                      {runningMonitorIds.has(mon.id) ? (
                        <div className="w-4 h-4 shrink-0 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium uppercase shrink-0', monStatus)}>
                          {mon.lastStatus || 'NEW'}
                        </span>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] text-[var(--text)] truncate">{mon.name}</p>
                        <div className="flex items-center gap-2 text-[11px] text-[var(--muted)]">
                          {mon.monitorType && (
                            <span className="px-1 py-0.5 rounded bg-white/5 text-[10px] uppercase">
                              {mon.monitorType.replace(/_/g, ' ')}
                            </span>
                          )}
                          {mon.targetFqn && (
                            <span className="font-mono truncate max-w-[250px]" title={mon.targetFqn}>
                              {mon.targetFqn}
                            </span>
                          )}
                        </div>
                      </div>
                      {/* Policy badge on the row */}
                      {policyStatus.status === 'violation' && (
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 bg-red-500/15 text-red-400"
                          title={`${policyStatus.violationFields.length} field(s) less strict than ${monPolicy?.profileName || 'policy'}: ${policyStatus.violationFields.join(', ')}`}
                        >
                          Policy violation
                        </span>
                      )}
                      {policyStatus.status === 'override' && (
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 bg-amber-500/15 text-amber-400"
                          title={`${policyStatus.overriddenFields.length} field(s) overridden from ${monPolicy?.profileName || 'policy'}: ${policyStatus.overriddenFields.join(', ')}`}
                        >
                          Override
                        </span>
                      )}
                      {policyStatus.status === 'policy' && (
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 bg-slate-500/15 text-slate-400"
                          title={`Following ${monPolicy?.profileName || 'policy'}`}
                        >
                          {monPolicy?.profileName || 'Policy'}
                        </span>
                      )}
                      {needsConfig && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 bg-amber-500/15 text-amber-400 animate-pulse">
                          Needs config
                        </span>
                      )}
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
                        <div className="flex items-center justify-end mb-2">
                          <button
                            onClick={() => setEditingMonitorId(
                              editingMonitorId === mon.id ? null : mon.id
                            )}
                            className={`text-[11px] underline ${needsConfig ? 'text-amber-400 hover:text-amber-300 font-medium' : 'text-[var(--muted)] hover:text-[var(--text-secondary)]'}`}
                          >
                            {editingMonitorId === mon.id ? 'Close editor' : needsConfig ? 'Configure required fields' : 'Edit config'}
                          </button>
                        </div>
                        {editingMonitorId === mon.id && (
                          <div className="mb-3">
                            <MonitorEditPanel
                              monitor={{
                                id: mon.id,
                                name: mon.name,
                                monitorType: mon.monitorType || '',
                                targetFqn: mon.targetFqn,
                                config: mon.config || {},
                                policyOverrides: mon.policyOverrides || [],
                              }}
                              resolvedPolicy={mon.targetFqn ? resolvedPolicies[mon.targetFqn] || null : null}
                              onSave={async (monitorId: string, config: Record<string, any>, policyOverrides: string[]) => {
                                await fetch(`/api/schedule/watches/${mon.groupId}/monitors/${monitorId}`, {
                                  method: 'PUT',
                                  headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ config, policyOverrides }),
                                });
                                setEditingMonitorId(null);
                                await fetchPlan();
                              }}
                            />
                          </div>
                        )}
                        <RunHistoryTable
                          runs={monitorRuns[mon.id] || []}
                          loading={monitorRunsLoading[mon.id] || false}
                          taskName={mon.name}
                          monitorType={mon.monitorType}
                          targetFqn={mon.targetFqn}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Plan edit modal */}
      {showPlanEditModal && (
        <WatchEditModal
          watch={{
            id: plan.id,
            name: plan.name,
            schedule: plan.schedule,
            timezone: plan.timezone,
            alertChannels: [],
            alertOnStatus: [],
            enabled: plan.enabled,
          }}
          onSave={async (data: Record<string, any>) => {
            await fetch(`/api/schedule/plans/${planId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(data),
            });
            fetchPlan();
          }}
          onClose={() => setShowPlanEditModal(false)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MetricCard
// ---------------------------------------------------------------------------

function MetricCard({
  label,
  value,
  color,
  bar,
  barColor,
}: {
  label: string;
  value: number;
  color: string;
  bar?: number;
  barColor?: string;
}) {
  return (
    <div className="p-3 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)]">
      <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">{label}</p>
      <p className={cn('text-[24px] font-bold tabular-nums', color)}>{value}</p>
      {bar != null && barColor && (
        <div className="mt-2 h-1 rounded-full bg-[var(--overlay-bg)] overflow-hidden">
          <div
            className={cn('h-full rounded-full transition-all', barColor)}
            style={{ width: `${Math.round(bar * 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}
