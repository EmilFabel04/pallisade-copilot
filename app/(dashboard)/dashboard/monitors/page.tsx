'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { Button } from '@/components/ui/button';
import { WatchCard } from '@/components/schedule/WatchCard';
import { WatchDetailPanel } from '@/components/schedule/WatchDetailPanel';
import { TaskCard } from '@/components/schedule/TaskCard';
import { MultiMonitorModal } from '@/components/schedule/MultiMonitorModal';
import { MonitorGroupSettingsModal } from '@/components/schedule/MonitorGroupSettingsModal';
import { DriftSummaryTab } from '@/components/monitors/DriftSummaryTab';
import { cn } from '@/lib/utils';
import type { ScheduledTask } from '@/types/schedule';
import type { WatchSummary, MonitoringPlanSummary } from '@/types/health-watch';
import { getMonitorSLAStatus } from '@/lib/sla-utils';

// ---------------------------------------------------------------------------
// Monitor type buckets
// ---------------------------------------------------------------------------

const DATA_MONITOR_TYPES = new Set([
  'FRESHNESS',
  'VOLUME',
  'SCHEMA_CHANGE',
  'NULL_CHECK',
  'UNIQUENESS_CHECK',
  'OUTLIER_DETECTION',
  'ANOMALY',
  'RANGE_VALIDATION',
  'ACCEPTED_VALUES',
  'DATE_CONSISTENCY',
  'DATA_TYPE_VALIDATION',
]);

const PIPELINE_MONITOR_TYPES = new Set([
  'SYNC_LAG',
  'FAILED_SYNCS',
  'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN',
  'DAG_SCHEDULE_LAG',
  'TASK_FAILURE_RATE',
  'DBT_TEST_FAILURES',
  'DBT_MODEL_FRESHNESS',
  'DBT_SOURCE_FRESHNESS',
  'BI_FRESHNESS_PROXY',
  'BI_UPSTREAM_BREAK_RISK',
  'BI_REFRESH_FAILURE',
  'BI_CONTENT_HEALTH',
  'SERVER_HEALTH',
  'CERTIFICATE',
  'LOG_ANALYSIS',
]);

type Tab = 'summary' | 'data' | 'pipeline';

function watchMatchesBucket(watch: WatchSummary, bucket: Set<string>): boolean {
  const monitors = watch.monitors || [];
  if (monitors.length === 0) return false;
  return monitors.some((m) => bucket.has((m.monitorType || '').toUpperCase()));
}

export default function MonitorsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: session } = useSession();
  const { selectedPipeline } = usePipeline();

  const rawTab = searchParams.get('tab');
  const activeTab: Tab = rawTab === 'data' || rawTab === 'pipeline' ? rawTab : 'summary';

  // Core state
  const [watches, setWatches] = useState<WatchSummary[]>([]);
  const [plans, setPlans] = useState<MonitoringPlanSummary[]>([]);
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);

  // Modal state
  const [showMonitorModal, setShowMonitorModal] = useState(false);
  const [settingsWatchId, setSettingsWatchId] = useState<string | null>(null);

  // Detail view
  const [selectedWatch, setSelectedWatch] = useState<WatchSummary | null>(null);
  const selectedWatchRef = useRef<WatchSummary | null>(null);
  const [watchDetailMonitors, setWatchDetailMonitors] = useState<any[]>([]);
  const [watchDetailLoading, setWatchDetailLoading] = useState(false);

  // Keep ref in sync with state to prevent stale closures in async callbacks
  useEffect(() => {
    selectedWatchRef.current = selectedWatch;
  }, [selectedWatch]);

  // Integrations for modal
  const [integrations, setIntegrations] = useState<Array<{ id: string; name: string; type: string }>>([]);

  // Running state for run-all indication
  const [runningWatchIds, setRunningWatchIds] = useState<Set<string>>(new Set());

  // Resolved policies for SLA badges
  const [resolvedPolicies, setResolvedPolicies] = useState<Record<string, any>>({});

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchWatches = useCallback(async () => {
    if (!selectedPipeline?.id) { setWatches([]); return; }
    try {
      const res = await cachedFetch(`/api/schedule/watches?stackId=${selectedPipeline.id}`);
      if (res.ok) { const data = await res.json(); setWatches(data.watches || []); }
    } catch (err) { console.error('[Monitors] Failed to fetch watches:', err); }
  }, [selectedPipeline?.id]);

  const fetchPlans = useCallback(async () => {
    if (!selectedPipeline?.id) { setPlans([]); return; }
    try {
      const res = await cachedFetch(`/api/schedule/plans?stackId=${selectedPipeline.id}`);
      if (res.ok) { const data = await res.json(); setPlans(data.plans || []); }
    } catch (err) { console.error('[Monitors] Failed to fetch plans:', err); }
  }, [selectedPipeline?.id]);

  const fetchTasks = useCallback(async () => {
    try {
      const res = await cachedFetch('/api/schedule/tasks');
      if (res.ok) { const data = await res.json(); setTasks(data.tasks || []); }
    } catch (err) { console.error('[Monitors] Failed to fetch tasks:', err); }
  }, []);

  // Live-refresh: bypass cache to get fresh monitor statuses
  const refreshLive = useCallback(async () => {
    if (!selectedPipeline?.id) return;
    invalidateCache('/api/schedule');
    try {
      const [watchRes, planRes] = await Promise.all([
        fetch(`/api/schedule/watches?stackId=${selectedPipeline.id}`),
        fetch(`/api/schedule/plans?stackId=${selectedPipeline.id}`),
      ]);
      if (watchRes.ok) { const d = await watchRes.json(); setWatches(d.watches || []); }
      if (planRes.ok) { const d = await planRes.json(); setPlans(d.plans || []); }
      // Also refresh detail panel if open — use ref to avoid stale closure
      const currentWatch = selectedWatchRef.current;
      if (currentWatch) {
        const detailRes = await fetch(`/api/schedule/watches/${currentWatch.id}`);
        if (detailRes.ok) {
          const d = await detailRes.json();
          // Re-check ref: user may have navigated away while fetch was in-flight
          if (d.watch && selectedWatchRef.current?.id === currentWatch.id) {
            setSelectedWatch(d.watch);
            setWatchDetailMonitors(d.watch.monitors || []);
          }
        }
      }
    } catch {}
  }, [selectedPipeline?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setSelectedWatch(null);
    setWatchDetailMonitors([]);
    setLoading(true);
    Promise.all([fetchWatches(), fetchPlans(), fetchTasks()]).finally(() => {
      setLoading(false);
    });
  }, [fetchWatches, fetchPlans, fetchTasks]);

  // Poll every 5s while monitors are running, otherwise every 30s
  useEffect(() => {
    if (!selectedPipeline?.id) return;
    const interval = runningWatchIds.size > 0 ? 5000 : 30000;
    const timer = setInterval(refreshLive, interval);
    return () => clearInterval(timer);
  }, [selectedPipeline?.id, runningWatchIds.size, refreshLive]);

  // Resolve policies
  // Stable key from monitor FQNs to avoid re-fetching when array refs change
  const policyFqnKey = useMemo(() => {
    const allFqns = new Set<string>();
    for (const watch of watches) {
      for (const mon of watch.monitors || []) {
        if (mon.targetFqn) allFqns.add(mon.targetFqn);
      }
    }
    for (const plan of plans) {
      for (const group of plan.monitorGroups || []) {
        for (const mon of group.monitors || []) {
          if (mon.targetFqn) allFqns.add(mon.targetFqn);
        }
      }
    }
    return [...allFqns].sort().join(',');
  }, [watches, plans]);

  useEffect(() => {
    if (!policyFqnKey || !selectedPipeline?.id) return;
    const fqns = policyFqnKey.split(',').filter(Boolean);
    if (fqns.length === 0) return;
    const timer = setTimeout(() => {
      fetch('/api/schedule/policies/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nodes: fqns.map((fqn) => ({ fqn, domain: 'warehouse', criticality: 'medium' })),
          stackId: selectedPipeline?.id,
        }),
      })
        .then((res) => res.ok ? res.json() : null)
        .then((data) => { if (data?.policies) setResolvedPolicies(data.policies); })
        .catch(() => {});
    }, 300);
    return () => clearTimeout(timer);
  }, [policyFqnKey, selectedPipeline?.id]);

  // Fetch integrations for the modal
  useEffect(() => {
    if (!selectedPipeline?.id) return;
    const nodesPromise = cachedFetch(`/api/pipeline/nodes?stackId=${selectedPipeline.id}`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!data) return [];
        return (data.nodes || [])
          .filter((n: any) => ['CONNECTED', 'HEALTHY', 'WARNING'].includes(n.status))
          .map((n: any) => ({ id: n.integrationId || n.id, name: n.name, type: n.toolType || n.type }));
      })
      .catch(() => [] as Array<{ id: string; name: string; type: string }>);
    const alertsPromise = cachedFetch(`/api/integrations?stackId=${selectedPipeline.id}`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!data?.integrations) return [];
        return (data.integrations as any[])
          .filter((i: any) => i.status === 'ACTIVE')
          .map((i: any) => ({ id: i.id, name: i.name || i.type, type: i.type }));
      })
      .catch(() => [] as Array<{ id: string; name: string; type: string }>);
    Promise.all([nodesPromise, alertsPromise]).then(([nodes, alerts]) => {
      const seen = new Set<string>();
      const merged = [...(nodes || []), ...(alerts || [])].filter((i) => {
        if (seen.has(i.id)) return false;
        seen.add(i.id);
        return true;
      });
      setIntegrations(merged);
    });
  }, [selectedPipeline?.id]);

  // Fetch watch detail
  useEffect(() => {
    if (!selectedWatch) return;
    setWatchDetailLoading(true);
    fetch(`/api/schedule/watches/${selectedWatch.id}`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (data?.watch) {
          setWatchDetailMonitors(data.watch.monitors || []);
          setSelectedWatch((prev) => prev ? { ...prev, ...data.watch } : prev);
        }
      })
      .catch(() => {})
      .finally(() => setWatchDetailLoading(false));
  }, [selectedWatch?.id]);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const refreshAll = useCallback(() => {
    invalidateCache('/api/schedule');
    fetchWatches();
    fetchPlans();
    fetchTasks();
  }, [fetchWatches, fetchPlans, fetchTasks]);

  const handleToggleWatchEnabled = async (watchId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/watches/${watchId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
      invalidateCache('/api/schedule');
      setWatches((prev) => prev.map((w) => (w.id === watchId ? { ...w, enabled } : w)));
      if (selectedWatch?.id === watchId) setSelectedWatch((prev) => prev ? { ...prev, enabled } : prev);
    } catch (err) { console.error('[Monitors] Failed to toggle watch:', err); }
  };

  const handleRunWatch = (watchId: string) => {
    setRunningWatchIds((prev) => new Set(prev).add(watchId));
    // Fire and forget — polling handles real-time updates while running
    fetch(`/api/schedule/watches/${watchId}/run`, { method: 'POST' })
      .then(async () => {
        invalidateCache('/api/schedule');
        await refreshLive();
      })
      .catch((err) => console.error('[Monitors] Failed to run watch:', err))
      .finally(() => {
        setRunningWatchIds((prev) => { const next = new Set(prev); next.delete(watchId); return next; });
      });
  };

  const handleDeleteWatch = async (watchId: string) => {
    if (!confirm('Delete this monitor group and its monitors?')) return;
    try {
      await fetch(`/api/schedule/watches/${watchId}`, { method: 'DELETE' });
      invalidateCache('/api/schedule');
      setWatches((prev) => prev.filter((w) => w.id !== watchId));
      setSelectedWatch(null);
      setWatchDetailMonitors([]);
    } catch (err) { console.error('[Monitors] Failed to delete watch:', err); }
  };

  const handleRemoveMonitorFromWatch = async (monitorId: string) => {
    if (!selectedWatch) return;
    try {
      const res = await fetch(`/api/schedule/watches/${selectedWatch.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ removeMonitorIds: [monitorId] }) });
      if (res.ok) {
        invalidateCache('/api/schedule');
        const detailRes = await fetch(`/api/schedule/watches/${selectedWatch.id}`);
        if (detailRes.ok) { const data = await detailRes.json(); setWatchDetailMonitors(data.watch?.monitors || []); if (data.watch) setSelectedWatch(data.watch); }
        fetchWatches();
      }
    } catch (err) { console.error('[Monitors] Failed to remove monitor:', err); }
  };

  // ---------------------------------------------------------------------------
  // Tab navigation
  // ---------------------------------------------------------------------------

  const setTab = (tab: Tab) => {
    const params = new URLSearchParams(searchParams.toString());
    if (tab === 'summary') {
      params.delete('tab');
    } else {
      params.set('tab', tab);
    }
    const qs = params.toString();
    router.push(`/dashboard/monitors${qs ? `?${qs}` : ''}`);
  };

  // ---------------------------------------------------------------------------
  // Filtered watches per tab
  // ---------------------------------------------------------------------------

  // Combine standalone watches + groups from plans, deduplicate by anchorFqn
  const planGroups = plans.flatMap((p) => (p.monitorGroups || []) as WatchSummary[]);
  const planFqns = new Set(planGroups.map((g) => g.anchorFqn).filter(Boolean));
  const uniqueWatches = watches.filter((w) => !w.anchorFqn || !planFqns.has(w.anchorFqn));
  const allWatches = [...uniqueWatches, ...planGroups];

  const dataWatches = allWatches.filter((w) => watchMatchesBucket(w, DATA_MONITOR_TYPES));
  const pipelineWatches = allWatches.filter((w) => watchMatchesBucket(w, PIPELINE_MONITOR_TYPES));

  // Standalone monitors (not in a watch group)
  const dataTasks = tasks.filter((t) => DATA_MONITOR_TYPES.has((t.monitorType || '').toUpperCase()));
  const pipelineTasks = tasks.filter((t) => PIPELINE_MONITOR_TYPES.has((t.monitorType || '').toUpperCase()));

  // ---------------------------------------------------------------------------
  // Policy / override counts helper
  // ---------------------------------------------------------------------------

  function policyCountsForWatch(watch: WatchSummary) {
    const watchMonitors = watch.monitors || [];
    const policyMonitorCount = watchMonitors.filter((m) => {
      const policy = m.targetFqn ? resolvedPolicies[m.targetFqn] : null;
      if (!policy || !['direct_profile', 'direct_override', 'imported_dbt', 'branch'].includes(policy.source)) return false;
      const ps = getMonitorSLAStatus(m.monitorType || '', (m as any).config || {}, policy);
      return ps.status !== 'none';
    }).length;
    const overrideMonitorCount = watchMonitors.filter((m) => {
      const policy = m.targetFqn ? resolvedPolicies[m.targetFqn] : null;
      if (!policy || !['direct_profile', 'direct_override', 'imported_dbt', 'branch'].includes(policy.source)) return false;
      const ps = getMonitorSLAStatus(m.monitorType || '', (m as any).config || {}, policy);
      return ps.status === 'override' || ps.status === 'violation';
    }).length;
    return { policyMonitorCount, overrideMonitorCount };
  }

  // ---------------------------------------------------------------------------
  // Detail view
  // ---------------------------------------------------------------------------

  if (selectedWatch) {
    return (
      <>
        <WatchDetailPanel
          watch={selectedWatch}
          detailMonitors={watchDetailMonitors}
          detailLoading={watchDetailLoading}
          onBack={() => { setSelectedWatch(null); setWatchDetailMonitors([]); }}
          running={runningWatchIds.has(selectedWatch.id)}
          onRunAll={() => handleRunWatch(selectedWatch.id)}
          onDelete={() => handleDeleteWatch(selectedWatch.id)}
          onToggleEnabled={(enabled) => handleToggleWatchEnabled(selectedWatch.id, enabled)}
          onRemoveMonitor={handleRemoveMonitorFromWatch}
          onSettings={() => setSettingsWatchId(selectedWatch.id)}
          onMonitorConfigSaved={(monitorId, config, policyOverrides) => {
            setWatchDetailMonitors((prev) =>
              prev.map((m: any) => m.id === monitorId ? { ...m, config, policyOverrides } : m)
            );
          }}
        />
        <MonitorGroupSettingsModal
          watchId={settingsWatchId || ''}
          open={!!settingsWatchId}
          onClose={() => setSettingsWatchId(null)}
          onSaved={() => {
            setSettingsWatchId(null);
            fetchWatches();
          }}
          integrations={integrations}
        />
      </>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const tabs: { key: Tab; label: string }[] = [
    { key: 'summary', label: 'Summary' },
    { key: 'data', label: 'Data Monitors' },
    { key: 'pipeline', label: 'Pipeline Monitors' },
  ];

  const handleToggleTaskEnabled = async (taskId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/tasks/${taskId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
      invalidateCache('/api/schedule');
      setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, enabled } : t)));
    } catch (err) { console.error('[Monitors] Failed to toggle task:', err); }
  };

  const handleRunTask = async (taskId: string) => {
    try {
      await fetch(`/api/schedule/tasks/${taskId}/run`, { method: 'POST' });
      invalidateCache('/api/schedule');
      fetchTasks();
    } catch (err) { console.error('[Monitors] Failed to run task:', err); }
  };

  const renderMonitorList = (watchList: WatchSummary[], taskList: ScheduledTask[]) => {
    if (loading) {
      return <div className="flex items-center justify-center py-20"><div className="w-6 h-6 red-spinner" /></div>;
    }
    if (watchList.length === 0 && taskList.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center py-20">
          <svg className="w-12 h-12 text-[var(--text-faint)] mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
          <h3 className="text-[15px] font-medium text-[var(--muted)] mb-1">No monitors found</h3>
          <p className="text-[13px] text-[var(--text-faint)] mb-4">Create a monitor to get started.</p>
          <Button size="sm" onClick={() => setShowMonitorModal(true)}>+ Create Monitor</Button>
        </div>
      );
    }
    return (
      <div className="space-y-2">
        {watchList.map((watch) => {
          const { policyMonitorCount, overrideMonitorCount } = policyCountsForWatch(watch);
          return (
            <WatchCard
              key={watch.id}
              watch={watch}
              policyMonitorCount={policyMonitorCount}
              overrideMonitorCount={overrideMonitorCount}
              onClick={() => setSelectedWatch(watch)}
              onToggleEnabled={(enabled) => handleToggleWatchEnabled(watch.id, enabled)}
              running={runningWatchIds.has(watch.id)}
              onRunAll={() => handleRunWatch(watch.id)}
              onDelete={() => handleDeleteWatch(watch.id)}
              onSettings={() => setSettingsWatchId(watch.id)}
            />
          );
        })}
        {taskList.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onClick={() => {}}
            onToggleEnabled={(enabled) => handleToggleTaskEnabled(task.id, enabled)}
            onRunNow={() => handleRunTask(task.id)}
          />
        ))}
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full bg-[var(--surface-inset)]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
        <div>
          <h1 className="text-[18px] font-semibold text-[var(--text)]">Monitors</h1>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Data quality and pipeline health monitors
          </p>
        </div>
        <Button size="sm" onClick={() => setShowMonitorModal(true)}>+ Create Monitor</Button>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-6 px-6 border-b border-[var(--border-faint)]">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'py-3 text-[13px] font-medium border-b-2 transition-colors',
              activeTab === t.key
                ? 'border-[var(--accent)] text-[var(--foreground)]'
                : 'border-transparent text-[var(--muted)] hover:text-[var(--foreground)]',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {activeTab === 'summary' && <DriftSummaryTab watches={allWatches} tasks={tasks} loading={loading} />}
        {activeTab === 'data' && renderMonitorList(dataWatches, dataTasks)}
        {activeTab === 'pipeline' && renderMonitorList(pipelineWatches, pipelineTasks)}
      </div>

      {/* Modal */}
      <MultiMonitorModal
        open={showMonitorModal}
        onClose={() => setShowMonitorModal(false)}
        onComplete={refreshAll}
        stackId={selectedPipeline?.id}
        integrations={integrations}
      />

      {/* Settings modal */}
      <MonitorGroupSettingsModal
        watchId={settingsWatchId || ''}
        open={!!settingsWatchId}
        onClose={() => setSettingsWatchId(null)}
        onSaved={() => {
          setSettingsWatchId(null);
          fetchWatches();
        }}
        integrations={integrations}
      />
    </div>
  );
}
