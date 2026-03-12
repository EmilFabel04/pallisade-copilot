'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { Button } from '@/components/ui/button';
import { TaskCard } from '@/components/schedule/TaskCard';
import { BundleCard } from '@/components/schedule/BundleCard';
import { CreateTaskModal } from '@/components/schedule/CreateTaskModal';
import { RunHistoryTable } from '@/components/schedule/RunHistoryTable';
import { cn } from '@/lib/utils';
import type { ScheduledTask, TaskRun, MonitorGroupSummary } from '@/types/schedule';
import { RUN_STATUS_COLORS } from '@/types/schedule';

type FilterStatus = 'all' | 'passing' | 'failing' | 'disabled';

export default function SchedulePage() {
  const { data: session } = useSession();
  const { selectedPipeline } = usePipeline();

  // Task list state
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterStatus>('all');
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Bundle state
  const [bundles, setBundles] = useState<MonitorGroupSummary[]>([]);
  const [selectedBundle, setSelectedBundle] = useState<MonitorGroupSummary | null>(null);
  const [bundleDetail, setBundleDetail] = useState<any>(null);
  const [bundleDetailLoading, setBundleDetailLoading] = useState(false);

  // Task detail state
  const [selectedTask, setSelectedTask] = useState<ScheduledTask | null>(null);
  const [taskRuns, setTaskRuns] = useState<TaskRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  // Edit modal state
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);

  // Integrations for create modal
  const [integrations, setIntegrations] = useState<Array<{ id: string; name: string; type: string }>>([]);

  // Fetch tasks scoped to current pipeline
  const fetchTasks = useCallback(async () => {
    if (!selectedPipeline?.id) {
      setTasks([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('status', filter);
      params.set('stackId', selectedPipeline.id);
      const res = await cachedFetch(`/api/schedule/tasks?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setTasks(data.tasks || []);
      }
    } catch (err) {
      console.error('[Schedule] Failed to fetch tasks:', err);
    } finally {
      setLoading(false);
    }
  }, [filter, selectedPipeline?.id]);

  // Fetch bundles
  const fetchBundles = useCallback(async () => {
    try {
      const res = await cachedFetch('/api/schedule/bundles');
      if (res.ok) {
        const data = await res.json();
        setBundles(data.bundles || []);
      }
    } catch (err) {
      console.error('[Schedule] Failed to fetch bundles:', err);
    }
  }, []);

  // Re-fetch and reset selection when pipeline changes
  useEffect(() => {
    setSelectedTask(null);
    setSelectedBundle(null);
    setBundleDetail(null);
    setTaskRuns([]);
    fetchTasks();
    fetchBundles();
  }, [fetchTasks, fetchBundles]);

  // Fetch integrations for create modal
  useEffect(() => {
    if (!selectedPipeline?.id) return;

    const fetchIntegrations = async () => {
      try {
        const res = await cachedFetch(`/api/pipeline/nodes?stackId=${selectedPipeline.id}`);
        if (res.ok) {
          const data = await res.json();
          const nodes = data.nodes || [];
          const intgs = nodes
            .filter((n: any) => ['CONNECTED', 'HEALTHY', 'WARNING'].includes(n.status))
            .map((n: any) => ({
              id: n.integrationId || n.id,
              integrationId: n.integrationId || null,
              nodeId: n.id,
              name: n.name,
              type: n.toolType || n.type,
            }));
          setIntegrations(intgs);
        }
      } catch (err) {
        console.error('[Schedule] Failed to fetch integrations:', err);
      }
    };

    fetchIntegrations();
  }, [selectedPipeline?.id]);

  // Fetch runs for selected task
  useEffect(() => {
    if (!selectedTask) return;

    const fetchRuns = async () => {
      setRunsLoading(true);
      try {
        const res = await cachedFetch(`/api/schedule/tasks/${selectedTask.id}/runs`);
        if (res.ok) {
          const data = await res.json();
          setTaskRuns(data.runs || []);
        }
      } catch (err) {
        console.error('[Schedule] Failed to fetch runs:', err);
      } finally {
        setRunsLoading(false);
      }
    };

    fetchRuns();
  }, [selectedTask]);

  // Fetch bundle detail
  useEffect(() => {
    if (!selectedBundle) return;

    const fetchDetail = async () => {
      setBundleDetailLoading(true);
      try {
        const res = await fetch(`/api/schedule/bundles/${selectedBundle.id}`);
        if (res.ok) {
          const data = await res.json();
          setBundleDetail(data.bundle);
        }
      } catch (err) {
        console.error('[Schedule] Failed to fetch bundle detail:', err);
      } finally {
        setBundleDetailLoading(false);
      }
    };

    fetchDetail();
  }, [selectedBundle]);

  // Create task or bundle
  const handleCreateTask = async (taskData: any) => {
    try {
      if (taskData._bundle) {
        const { _bundle, ...bundleData } = taskData;
        const res = await fetch('/api/schedule/bundles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(bundleData),
        });
        if (res.ok) {
          setShowCreateModal(false);
          fetchBundles();
          fetchTasks();
        }
      } else {
        const res = await fetch('/api/schedule/tasks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(taskData),
        });
        if (res.ok) {
          setShowCreateModal(false);
          fetchTasks();
        }
      }
    } catch (err) {
      console.error('[Schedule] Failed to create:', err);
    }
  };

  // Toggle task enabled
  const handleToggleEnabled = async (taskId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/tasks/${taskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      invalidateCache('/api/schedule');
      setTasks((prev) =>
        prev.map((t) => (t.id === taskId ? { ...t, enabled } : t))
      );
    } catch (err) {
      console.error('[Schedule] Failed to toggle task:', err);
    }
  };

  // Toggle bundle enabled
  const handleToggleBundleEnabled = async (bundleId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/bundles/${bundleId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      invalidateCache('/api/schedule');
      setBundles((prev) =>
        prev.map((b) => (b.id === bundleId ? { ...b, enabled } : b))
      );
    } catch (err) {
      console.error('[Schedule] Failed to toggle bundle:', err);
    }
  };

  // Run now
  const handleRunNow = async (taskId: string) => {
    try {
      const res = await fetch(`/api/schedule/tasks/${taskId}/run`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchTasks();
        if (selectedTask?.id === taskId) {
          const runsRes = await fetch(`/api/schedule/tasks/${taskId}/runs`);
          if (runsRes.ok) {
            const data = await runsRes.json();
            setTaskRuns(data.runs || []);
          }
        }
      }
    } catch (err) {
      console.error('[Schedule] Failed to run task:', err);
    }
  };

  // Run all monitors in a bundle
  const handleRunBundle = async (bundleId: string) => {
    try {
      const res = await fetch(`/api/schedule/bundles/${bundleId}/run`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchBundles();
        fetchTasks();
        // Refresh detail if viewing this bundle
        if (selectedBundle?.id === bundleId) {
          const detailRes = await fetch(`/api/schedule/bundles/${bundleId}`);
          if (detailRes.ok) {
            const data = await detailRes.json();
            setBundleDetail(data.bundle);
          }
        }
      }
    } catch (err) {
      console.error('[Schedule] Failed to run bundle:', err);
    }
  };

  // Delete task
  const handleDeleteTask = async (taskId: string) => {
    try {
      await fetch(`/api/schedule/tasks/${taskId}`, { method: 'DELETE' });
      invalidateCache('/api/schedule');
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
      if (selectedTask?.id === taskId) {
        setSelectedTask(null);
      }
    } catch (err) {
      console.error('[Schedule] Failed to delete task:', err);
    }
  };

  // Delete bundle
  const handleDeleteBundle = async (bundleId: string) => {
    try {
      await fetch(`/api/schedule/bundles/${bundleId}`, { method: 'DELETE' });
      invalidateCache('/api/schedule');
      setBundles((prev) => prev.filter((b) => b.id !== bundleId));
      setSelectedBundle(null);
      setBundleDetail(null);
      fetchTasks();
    } catch (err) {
      console.error('[Schedule] Failed to delete bundle:', err);
    }
  };

  // Update task
  const handleUpdateTask = async (taskId: string, taskData: any) => {
    try {
      const res = await fetch(`/api/schedule/tasks/${taskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(taskData),
      });
      if (res.ok) {
        setEditingTask(null);
        fetchTasks();
        const detailRes = await fetch(`/api/schedule/tasks/${taskId}`);
        if (detailRes.ok) {
          const detail = await detailRes.json();
          if (detail.task) setSelectedTask(detail.task);
        }
      }
    } catch (err) {
      console.error('[Schedule] Failed to update task:', err);
    }
  };

  // Bundle detail view
  if (selectedBundle) {
    const statusColor = selectedBundle.lastStatus
      ? RUN_STATUS_COLORS[selectedBundle.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
      : 'bg-[var(--overlay-medium)] text-[var(--muted)]';

    const monitors = bundleDetail?.monitors || selectedBundle.monitors || [];

    return (
      <div className="flex flex-col h-full bg-[var(--surface-inset)]">
        {/* Detail header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => { setSelectedBundle(null); setBundleDetail(null); }}
              className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <div>
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                <h2 className="text-[16px] font-semibold text-[var(--text)]">{selectedBundle.name}</h2>
                <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', statusColor)}>
                  {selectedBundle.lastStatus || 'NEW'}
                </span>
              </div>
              <p className="text-[12px] text-[var(--muted)] mt-0.5">
                {selectedBundle.groupType.replace(/_/g, ' ')}
                {' · '}
                {selectedBundle.monitorCount} monitor{selectedBundle.monitorCount !== 1 ? 's' : ''}
                {selectedBundle.schedule && ` · ${selectedBundle.schedule}`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleRunBundle(selectedBundle.id)}
            >
              Run All
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-red-400 hover:text-red-300"
              onClick={() => handleDeleteBundle(selectedBundle.id)}
            >
              Delete
            </Button>
          </div>
        </div>

        {/* Bundle config summary */}
        <div className="px-6 py-4 border-b border-[var(--border-faint)]">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Type</p>
              <p className="text-[13px] text-[var(--text-secondary)] capitalize">
                {selectedBundle.groupType.replace(/_/g, ' ')}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Schedule</p>
              <p className="text-[13px] text-[var(--text-secondary)]">{selectedBundle.schedule || 'None'}</p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Passing</p>
              <p className="text-[13px] text-[var(--text-secondary)]">
                {selectedBundle.passCount}/{selectedBundle.monitorCount}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Status</p>
              <p className="text-[13px] text-[var(--text-secondary)]">
                {selectedBundle.enabled ? 'Enabled' : 'Disabled'}
              </p>
            </div>
          </div>
          {selectedBundle.anchorFqn && (
            <div className="mt-3 p-3 bg-[var(--overlay-bg)] rounded-lg border border-[var(--subtle-border)]">
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Anchor</p>
              <p className="text-[13px] text-[var(--text-tertiary)] font-mono">{selectedBundle.anchorFqn}</p>
            </div>
          )}
        </div>

        {/* Member monitors */}
        <div className="flex-1 px-6 py-4 overflow-y-auto">
          <h3 className="text-[14px] font-medium text-[var(--text)] mb-3">Monitors</h3>
          {bundleDetailLoading ? (
            <div className="flex items-center justify-center py-10">
              <div className="w-5 h-5 red-spinner" />
            </div>
          ) : monitors.length === 0 ? (
            <p className="text-[13px] text-[var(--muted)] py-4">No monitors in this bundle.</p>
          ) : (
            <div className="space-y-2">
              {monitors.map((mon: any) => {
                const monStatus = mon.lastStatus
                  ? RUN_STATUS_COLORS[mon.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
                  : 'bg-[var(--overlay-medium)] text-[var(--muted)]';
                return (
                  <div
                    key={mon.id}
                    className="flex items-center gap-3 p-3 bg-[var(--surface)] border border-[var(--subtle-border)] rounded-lg"
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
                    {mon.lastRun && (
                      <span className="text-[11px] text-[var(--text-faint)] shrink-0">
                        {mon.lastRun.durationMs ? `${(mon.lastRun.durationMs / 1000).toFixed(1)}s` : ''}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Task detail view
  if (selectedTask) {
    const statusColor = selectedTask.lastStatus
      ? RUN_STATUS_COLORS[selectedTask.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
      : 'bg-[var(--overlay-medium)] text-[var(--muted)]';

    return (
      <div className="flex flex-col h-full bg-[var(--surface-inset)]">
        {/* Detail header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSelectedTask(null)}
              className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-[16px] font-semibold text-[var(--text)]">{selectedTask.name}</h2>
                <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', statusColor)}>
                  {selectedTask.lastStatus || 'NEW'}
                </span>
              </div>
              <p className="text-[12px] text-[var(--muted)] mt-0.5">
                {selectedTask.taskMode === 'prompt' ? 'AI Prompt' : (selectedTask.monitorType || 'Monitor')}
                {' · '}
                {selectedTask.schedule}
                {selectedTask.targetFqn && ` · ${selectedTask.targetFqn}`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEditingTask(selectedTask)}
            >
              Edit
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleRunNow(selectedTask.id)}
            >
              Run Now
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-red-400 hover:text-red-300"
              onClick={() => handleDeleteTask(selectedTask.id)}
            >
              Delete
            </Button>
          </div>
        </div>

        {/* Task config summary */}
        <div className="px-6 py-4 border-b border-[var(--border-faint)]">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Type</p>
              <p className="text-[13px] text-[var(--text-secondary)]">
                {selectedTask.taskMode === 'prompt' ? 'AI Prompt' : selectedTask.monitorType}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Schedule</p>
              <p className="text-[13px] text-[var(--text-secondary)]">{selectedTask.schedule}</p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Alerts</p>
              <p className="text-[13px] text-[var(--text-secondary)]">
                {selectedTask.alertChannels.length > 0
                  ? selectedTask.alertChannels.join(', ')
                  : 'None'}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Status</p>
              <p className="text-[13px] text-[var(--text-secondary)]">
                {selectedTask.enabled ? 'Enabled' : 'Disabled'}
              </p>
            </div>
          </div>
          {selectedTask.prompt && (
            <div className="mt-3 p-3 bg-[var(--overlay-bg)] rounded-lg border border-[var(--subtle-border)]">
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-1">Prompt</p>
              <p className="text-[13px] text-[var(--text-tertiary)]">{selectedTask.prompt}</p>
            </div>
          )}
        </div>

        {/* Run history */}
        <div className="flex-1 px-6 py-4 overflow-y-auto">
          <h3 className="text-[14px] font-medium text-[var(--text)] mb-3">Run History</h3>
          <RunHistoryTable
            runs={taskRuns}
            loading={runsLoading}
            taskName={selectedTask.name}
            monitorType={selectedTask.monitorType}
            targetFqn={selectedTask.targetFqn}
          />
        </div>

        {/* Edit modal (rendered inside detail view) */}
        <CreateTaskModal
          open={!!editingTask}
          onClose={() => setEditingTask(null)}
          onSubmit={handleCreateTask}
          onUpdate={handleUpdateTask}
          editTask={editingTask}
          integrations={integrations}
          stackId={selectedPipeline?.id}
        />
      </div>
    );
  }

  // Ungrouped tasks (not part of any bundle)
  const ungroupedTasks = tasks.filter((t) => {
    const raw = t as any;
    return !raw.monitorGroupId && !t.monitorGroupName && !raw.monitorGroup;
  });

  // Task list view
  return (
    <div className="flex flex-col h-full bg-[var(--surface-inset)]">
      {/* Page header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
        <div>
          <h1 className="text-[18px] font-semibold text-[var(--text)]">Scheduled Tasks</h1>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Schedule quality checks, anomaly detection, and pipeline monitoring
          </p>
        </div>
        <Button size="sm" onClick={() => setShowCreateModal(true)}>
          + Create Task
        </Button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-[var(--border-faint)]">
        {(['all', 'passing', 'failing', 'disabled'] as FilterStatus[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors capitalize',
              filter === f
                ? 'bg-[var(--overlay-medium)] text-[var(--text)]'
                : 'text-[var(--muted)] hover:text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)]'
            )}
          >
            {f}
          </button>
        ))}
        <span className="text-[12px] text-[var(--text-faint)] ml-2">
          {bundles.length > 0 && `${bundles.length} bundle${bundles.length !== 1 ? 's' : ''} · `}
          {tasks.length} task{tasks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 red-spinner" />
          </div>
        ) : bundles.length === 0 && tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20">
            <svg className="w-12 h-12 text-[var(--text-faint)] mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <h3 className="text-[15px] font-medium text-[var(--muted)] mb-1">No scheduled tasks</h3>
            <p className="text-[13px] text-[var(--text-faint)] mb-4">
              Create your first task to start monitoring your data pipeline
            </p>
            <Button size="sm" onClick={() => setShowCreateModal(true)}>
              + Create Task
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Bundles section */}
            {bundles.length > 0 && (
              <div>
                <h3 className="text-[12px] font-medium text-[var(--text-faint)] uppercase tracking-wider mb-2">
                  Bundles
                </h3>
                <div className="space-y-2">
                  {bundles.map((bundle) => (
                    <BundleCard
                      key={bundle.id}
                      bundle={bundle}
                      onClick={() => setSelectedBundle(bundle)}
                      onToggleEnabled={(enabled) => handleToggleBundleEnabled(bundle.id, enabled)}
                      onRunAll={() => handleRunBundle(bundle.id)}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Individual tasks section */}
            {ungroupedTasks.length > 0 && (
              <div>
                {bundles.length > 0 && (
                  <h3 className="text-[12px] font-medium text-[var(--text-faint)] uppercase tracking-wider mb-2">
                    Individual Tasks
                  </h3>
                )}
                <div className="space-y-2">
                  {ungroupedTasks.map((task) => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      onClick={() => setSelectedTask(task)}
                      onToggleEnabled={(enabled) => handleToggleEnabled(task.id, enabled)}
                      onRunNow={() => handleRunNow(task.id)}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Create / Edit modal */}
      <CreateTaskModal
        open={showCreateModal || !!editingTask}
        onClose={() => { setShowCreateModal(false); setEditingTask(null); }}
        onSubmit={handleCreateTask}
        onUpdate={handleUpdateTask}
        editTask={editingTask}
        integrations={integrations}
        stackId={selectedPipeline?.id}
      />
    </div>
  );
}
