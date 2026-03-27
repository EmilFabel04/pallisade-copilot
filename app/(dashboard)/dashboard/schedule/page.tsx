'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { Button } from '@/components/ui/button';
import { TaskCard } from '@/components/schedule/TaskCard';
import { WatchCard } from '@/components/schedule/WatchCard';
import { WatchDetailPanel } from '@/components/schedule/WatchDetailPanel';
import { CreateTaskModal } from '@/components/schedule/CreateTaskModal';
import { MultiMonitorModal } from '@/components/schedule/MultiMonitorModal';
import { MonitoringPlanCard } from '@/components/schedule/MonitoringPlanCard';
import { RunHistoryTable } from '@/components/schedule/RunHistoryTable';
import { cn } from '@/lib/utils';
import type { ScheduledTask, TaskRun } from '@/types/schedule';
import { RUN_STATUS_COLORS } from '@/types/schedule';
import type { WatchSummary, MonitoringPlanSummary } from '@/types/health-watch';
import { getMonitorSLAStatus } from '@/lib/sla-utils';

type FilterStatus = 'all' | 'passing' | 'failing' | 'disabled';

export default function SchedulePage() {
  const router = useRouter();
  const { data: session } = useSession();
  const { selectedPipeline } = usePipeline();

  // Core state
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [plans, setPlans] = useState<MonitoringPlanSummary[]>([]);
  const [watches, setWatches] = useState<WatchSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterStatus>('all');

  // Modal state
  const [showMonitorModal, setShowMonitorModal] = useState(false);

  // Detail views
  const [selectedWatch, setSelectedWatch] = useState<WatchSummary | null>(null);
  const [watchDetailMonitors, setWatchDetailMonitors] = useState<any[]>([]);
  const [watchDetailLoading, setWatchDetailLoading] = useState(false);
  const [selectedTask, setSelectedTask] = useState<ScheduledTask | null>(null);
  const [taskRuns, setTaskRuns] = useState<TaskRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsVersion, setRunsVersion] = useState(0);
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);
  const [integrations, setIntegrations] = useState<Array<{ id: string; name: string; type: string }>>([]);
  const [resolvedPolicies, setResolvedPolicies] = useState<Record<string, any>>({});

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchTasks = useCallback(async () => {
    if (!selectedPipeline?.id) { setTasks([]); setLoading(false); return; }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('status', filter);
      params.set('stackId', selectedPipeline.id);
      const res = await cachedFetch(`/api/schedule/tasks?${params.toString()}`);
      if (res.ok) { const data = await res.json(); setTasks(data.tasks || []); }
    } catch (err) { console.error('[Schedule] Failed to fetch tasks:', err); }
    finally { setLoading(false); }
  }, [filter, selectedPipeline?.id]);

  const fetchPlans = useCallback(async () => {
    try {
      const res = await cachedFetch('/api/schedule/plans');
      if (res.ok) { const data = await res.json(); setPlans(data.plans || []); }
    } catch (err) { console.error('[Schedule] Failed to fetch plans:', err); }
  }, []);

  const fetchWatches = useCallback(async () => {
    try {
      const res = await cachedFetch('/api/schedule/watches');
      if (res.ok) { const data = await res.json(); setWatches(data.watches || []); }
    } catch (err) { console.error('[Schedule] Failed to fetch watches:', err); }
  }, []);

  useEffect(() => {
    setSelectedTask(null);
    setSelectedWatch(null);
    setWatchDetailMonitors([]);
    setTaskRuns([]);
    fetchTasks();
    fetchPlans();
    fetchWatches();
  }, [fetchTasks, fetchPlans, fetchWatches]);

  // Resolve policies for all monitor targets across plans and watches
  useEffect(() => {
    const allFqns = new Set<string>();
    for (const plan of plans) {
      for (const group of plan.monitorGroups || []) {
        for (const mon of group.monitors || []) {
          if (mon.targetFqn) allFqns.add(mon.targetFqn);
        }
      }
    }
    for (const watch of watches) {
      for (const mon of watch.monitors || []) {
        if (mon.targetFqn) allFqns.add(mon.targetFqn);
      }
    }
    if (allFqns.size === 0) return;
    fetch('/api/schedule/policies/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nodes: [...allFqns].map((fqn) => ({ fqn, domain: 'warehouse', criticality: 'medium' })),
        stackId: selectedPipeline?.id,
      }),
    })
      .then((res) => res.ok ? res.json() : null)
      .then((data) => { if (data?.policies) setResolvedPolicies(data.policies); })
      .catch(() => {});
  }, [plans, watches]);

  useEffect(() => {
    if (!selectedPipeline?.id) return;
    // Fetch pipeline nodes (warehouses, transforms, etc.)
    const nodesPromise = cachedFetch(`/api/pipeline/nodes?stackId=${selectedPipeline.id}`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!data) return [];
        return (data.nodes || [])
          .filter((n: any) => ['CONNECTED', 'HEALTHY', 'WARNING'].includes(n.status))
          .map((n: any) => ({ id: n.integrationId || n.id, name: n.name, type: n.toolType || n.type }));
      })
      .catch(() => [] as Array<{ id: string; name: string; type: string }>);
    // Fetch alert/notification integrations (Slack, PagerDuty, etc.)
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

  // Fetch runs for selected task (uses fetch, not cachedFetch, so runs are always fresh)
  useEffect(() => {
    if (!selectedTask) return;
    setRunsLoading(true);
    fetch(`/api/schedule/tasks/${selectedTask.id}/runs`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => { if (data) setTaskRuns(data.runs || []); })
      .catch(() => {})
      .finally(() => setRunsLoading(false));
  }, [selectedTask, runsVersion]);

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
    fetchPlans();
    fetchWatches();
    fetchTasks();
  }, [fetchPlans, fetchWatches, fetchTasks]);

  // Plans
  const handleTogglePlanEnabled = async (planId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/plans/${planId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
      invalidateCache('/api/schedule');
      setPlans((prev) => prev.map((p) => (p.id === planId ? { ...p, enabled } : p)));
    } catch (err) { console.error('[Schedule] Failed to toggle plan:', err); }
  };

  const handleRunPlan = async (planId: string) => {
    try { await fetch(`/api/schedule/plans/${planId}/run`, { method: 'POST' }); refreshAll(); }
    catch (err) { console.error('[Schedule] Failed to run plan:', err); }
  };

  const handleDeletePlan = async (planId: string) => {
    if (!confirm('Delete this monitoring plan and all its monitors?')) return;
    try {
      await fetch(`/api/schedule/plans/${planId}`, { method: 'DELETE' });
      invalidateCache('/api/schedule');
      setPlans((prev) => prev.filter((p) => p.id !== planId));
      fetchTasks();
      fetchWatches();
    } catch (err) { console.error('[Schedule] Failed to delete plan:', err); }
  };

  // Watches
  const handleToggleWatchEnabled = async (watchId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/watches/${watchId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
      invalidateCache('/api/schedule');
      setWatches((prev) => prev.map((w) => (w.id === watchId ? { ...w, enabled } : w)));
      if (selectedWatch?.id === watchId) setSelectedWatch((prev) => prev ? { ...prev, enabled } : prev);
    } catch (err) { console.error('[Schedule] Failed to toggle watch:', err); }
  };

  const handleRunWatch = async (watchId: string) => {
    try {
      await fetch(`/api/schedule/watches/${watchId}/run`, { method: 'POST' });
      invalidateCache('/api/schedule');
      fetchWatches(); fetchTasks();
      if (selectedWatch?.id === watchId) {
        const res = await fetch(`/api/schedule/watches/${watchId}`);
        if (res.ok) { const data = await res.json(); if (data.watch) { setSelectedWatch(data.watch); setWatchDetailMonitors(data.watch.monitors || []); } }
      }
      // Trigger runs refetch for any selected task
      setRunsVersion((v) => v + 1);
    } catch (err) { console.error('[Schedule] Failed to run watch:', err); }
  };

  const handleDeleteWatch = async (watchId: string) => {
    if (!confirm('Delete this monitor group and its monitors?')) return;
    try {
      await fetch(`/api/schedule/watches/${watchId}`, { method: 'DELETE' });
      invalidateCache('/api/schedule');
      setWatches((prev) => prev.filter((w) => w.id !== watchId));
      setSelectedWatch(null);
      setWatchDetailMonitors([]);
      fetchTasks();
    } catch (err) { console.error('[Schedule] Failed to delete watch:', err); }
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
    } catch (err) { console.error('[Schedule] Failed to remove monitor:', err); }
  };

  const handleToggleEnabled = async (taskId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/tasks/${taskId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
      invalidateCache('/api/schedule');
      setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, enabled } : t)));
    } catch (err) { console.error('[Schedule] Failed to toggle task:', err); }
  };

  const handleRunNow = async (taskId: string) => {
    try {
      const res = await fetch(`/api/schedule/tasks/${taskId}/run`, { method: 'POST' });
      if (res.ok) {
        invalidateCache('/api/schedule');
        fetchTasks();
        setRunsVersion((v) => v + 1);
      }
    } catch (err) { console.error('[Schedule] Failed to run task:', err); }
  };

  const handleDeleteTask = async (taskId: string) => {
    if (!confirm('Delete this monitor?')) return;
    try {
      await fetch(`/api/schedule/tasks/${taskId}`, { method: 'DELETE' });
      invalidateCache('/api/schedule');
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
      if (selectedTask?.id === taskId) setSelectedTask(null);
    } catch (err) { console.error('[Schedule] Failed to delete task:', err); }
  };

  const handleUpdateTask = async (taskId: string, taskData: any) => {
    try {
      const res = await fetch(`/api/schedule/tasks/${taskId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(taskData) });
      if (res.ok) { setEditingTask(null); fetchTasks(); const r = await fetch(`/api/schedule/tasks/${taskId}`); if (r.ok) { const d = await r.json(); if (d.task) setSelectedTask(d.task); } }
    } catch (err) { console.error('[Schedule] Failed to update task:', err); }
  };

  // ---------------------------------------------------------------------------
  // Detail views
  // ---------------------------------------------------------------------------

  if (selectedWatch) {
    return (
      <WatchDetailPanel
        watch={selectedWatch}
        detailMonitors={watchDetailMonitors}
        detailLoading={watchDetailLoading}
        onBack={() => { setSelectedWatch(null); setWatchDetailMonitors([]); }}
        onRunAll={() => handleRunWatch(selectedWatch.id)}
        onDelete={() => handleDeleteWatch(selectedWatch.id)}
        onToggleEnabled={(enabled) => handleToggleWatchEnabled(selectedWatch.id, enabled)}
        onRemoveMonitor={handleRemoveMonitorFromWatch}
      />
    );
  }

  if (selectedTask) {
    const statusColor = selectedTask.lastStatus
      ? RUN_STATUS_COLORS[selectedTask.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
      : 'bg-[var(--overlay-medium)] text-[var(--muted)]';

    return (
      <div className="flex flex-col h-full bg-[var(--surface-inset)]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div className="flex items-center gap-3">
            <button onClick={() => setSelectedTask(null)} className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-[16px] font-semibold text-[var(--text)]">{selectedTask.name}</h2>
                <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', statusColor)}>{selectedTask.lastStatus || 'NEW'}</span>
              </div>
              <p className="text-[12px] text-[var(--muted)] mt-0.5">
                {selectedTask.taskMode === 'prompt' ? 'AI Prompt' : (selectedTask.monitorType || 'Monitor')} · {selectedTask.schedule}{selectedTask.targetFqn && ` · ${selectedTask.targetFqn}`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setEditingTask(selectedTask)}>Edit</Button>
            <Button variant="ghost" size="sm" onClick={() => handleRunNow(selectedTask.id)}>Run Now</Button>
            <Button variant="ghost" size="sm" className="text-red-400 hover:text-red-300" onClick={() => handleDeleteTask(selectedTask.id)}>Delete</Button>
          </div>
        </div>
        <div className="px-6 py-4 border-b border-[var(--border-faint)]">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div><p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Type</p><p className="text-[13px] text-[var(--text-secondary)]">{selectedTask.taskMode === 'prompt' ? 'AI Prompt' : selectedTask.monitorType}</p></div>
            <div><p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Schedule</p><p className="text-[13px] text-[var(--text-secondary)]">{selectedTask.schedule}</p></div>
            <div><p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Alerts</p><p className="text-[13px] text-[var(--text-secondary)]">{selectedTask.alertChannels.length > 0 ? selectedTask.alertChannels.join(', ') : 'None'}</p></div>
            <div><p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Status</p><p className="text-[13px] text-[var(--text-secondary)]">{selectedTask.enabled ? 'Enabled' : 'Disabled'}</p></div>
          </div>
          {selectedTask.prompt && (
            <div className="mt-3 p-3 bg-[var(--overlay-bg)] rounded-lg border border-[var(--subtle-border)]">
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Prompt</p>
              <p className="text-[13px] text-[var(--text-tertiary)]">{selectedTask.prompt}</p>
            </div>
          )}
        </div>
        <div className="flex-1 px-6 py-4 overflow-y-auto">
          <h3 className="text-[14px] font-medium text-[var(--text)] mb-3">Run History</h3>
          <RunHistoryTable runs={taskRuns} loading={runsLoading} taskName={selectedTask.name} monitorType={selectedTask.monitorType} targetFqn={selectedTask.targetFqn} />
        </div>
        <CreateTaskModal open={!!editingTask} onClose={() => setEditingTask(null)} onUpdate={handleUpdateTask} onComplete={refreshAll} editTask={editingTask} integrations={integrations} stackId={selectedPipeline?.id} />
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Main list view
  // ---------------------------------------------------------------------------

  const groupCount = plans.length + watches.length;
  const hasItems = groupCount > 0 || tasks.length > 0;
  const initializing = !selectedPipeline?.id && loading;

  return (
    <div className="flex flex-col h-full bg-[var(--surface-inset)]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
        <div>
          <h1 className="text-[18px] font-semibold text-[var(--text)]">Monitoring</h1>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">Monitoring plans and individual monitors</p>
        </div>
        <Button size="sm" onClick={() => setShowMonitorModal(true)}>+ New</Button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-[var(--border-faint)]">
        {(['all', 'passing', 'failing', 'disabled'] as FilterStatus[]).map((f) => (
          <button key={f} onClick={() => setFilter(f)} className={cn('px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors capitalize', filter === f ? 'bg-[var(--overlay-medium)] text-[var(--text)]' : 'text-[var(--muted)] hover:text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)]')}>{f}</button>
        ))}
        <span className="text-[12px] text-[var(--text-faint)] ml-2">
          {groupCount > 0 && `${groupCount} group${groupCount !== 1 ? 's' : ''} · `}{tasks.length} monitor{tasks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {(loading || initializing) ? (
          <div className="flex items-center justify-center py-20"><div className="w-6 h-6 red-spinner" /></div>
        ) : !hasItems ? (
          <div className="flex flex-col items-center justify-center py-20">
            <svg className="w-12 h-12 text-[var(--text-faint)] mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
            <h3 className="text-[15px] font-medium text-[var(--muted)] mb-1">No monitors yet</h3>
            <p className="text-[13px] text-[var(--text-faint)] mb-4">Set up monitoring to protect your pipeline.</p>
            <Button size="sm" onClick={() => setShowMonitorModal(true)}>Create Monitor</Button>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Monitor Groups (plans + standalone watches) */}
            {(plans.length > 0 || watches.length > 0) && (
              <div>
                <h3 className="text-[12px] font-medium text-[var(--text-faint)] uppercase tracking-wider mb-2">Monitor Groups</h3>
                <div className="space-y-2">
                  {plans.map((plan) => (
                    <MonitoringPlanCard
                      key={plan.id}
                      plan={plan}
                      onClick={() => router.push(`/dashboard/schedule/plan/${plan.id}`)}
                      onToggleEnabled={(enabled) => handleTogglePlanEnabled(plan.id, enabled)}
                      onRunAll={() => handleRunPlan(plan.id)}
                      onDelete={() => handleDeletePlan(plan.id)}
                      policyMonitorCount={
                        (plan.monitorGroups || []).flatMap((g) => g.monitors || [])
                          .filter((m) => {
                            const ps = getMonitorSLAStatus(
                              (m as any).monitorType || '', (m as any).config || {},
                              m.targetFqn ? resolvedPolicies[m.targetFqn] : null
                            );
                            return ps.status !== 'none';
                          }).length
                      }
                      overrideMonitorCount={
                        (plan.monitorGroups || []).flatMap((g) => g.monitors || [])
                          .filter((m) => {
                            const ps = getMonitorSLAStatus(
                              (m as any).monitorType || '', (m as any).config || {},
                              m.targetFqn ? resolvedPolicies[m.targetFqn] : null
                            );
                            return ps.status === 'override' || ps.status === 'violation';
                          }).length
                      }
                    />
                  ))}
                  {watches.map((watch) => {
                    const watchMonitors = watch.monitors || [];
                    const watchPolicyCount = watchMonitors.filter((m) => {
                      const ps = getMonitorSLAStatus(
                        m.monitorType || '', (m as any).config || {},
                        m.targetFqn ? resolvedPolicies[m.targetFqn] : null
                      );
                      return ps.status !== 'none';
                    }).length;
                    const watchOverrideCount = watchMonitors.filter((m) => {
                      const ps = getMonitorSLAStatus(
                        m.monitorType || '', (m as any).config || {},
                        m.targetFqn ? resolvedPolicies[m.targetFqn] : null
                      );
                      return ps.status === 'override' || ps.status === 'violation';
                    }).length;
                    return (
                      <WatchCard
                        key={watch.id}
                        watch={watch}
                        policyMonitorCount={watchPolicyCount}
                        overrideMonitorCount={watchOverrideCount}
                        onClick={() => setSelectedWatch(watch)}
                        onToggleEnabled={(enabled) => handleToggleWatchEnabled(watch.id, enabled)}
                        onRunAll={() => handleRunWatch(watch.id)}
                      />
                    );
                  })}
                </div>
              </div>
            )}

            {/* Individual Monitors */}
            {tasks.length > 0 && (
              <div>
                <h3 className="text-[12px] font-medium text-[var(--text-faint)] uppercase tracking-wider mb-2">Individual Monitors</h3>
                <div className="space-y-2">
                  {tasks.map((task) => (
                    <TaskCard key={task.id} task={task} onClick={() => setSelectedTask(task)} onToggleEnabled={(enabled) => handleToggleEnabled(task.id, enabled)} onRunNow={() => handleRunNow(task.id)} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Modals */}
      <MultiMonitorModal open={showMonitorModal} onClose={() => setShowMonitorModal(false)} onComplete={refreshAll} stackId={selectedPipeline?.id} integrations={integrations} />
      {/* Edit modal for existing tasks (opened from task detail view) */}
      <CreateTaskModal open={!!editingTask} onClose={() => setEditingTask(null)} onUpdate={handleUpdateTask} onComplete={refreshAll} editTask={editingTask} integrations={integrations} stackId={selectedPipeline?.id} />
    </div>
  );
}
