'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { Button } from '@/components/ui/button';
import { TaskCard } from '@/components/schedule/TaskCard';
import { WatchCard } from '@/components/schedule/WatchCard';
import { BundleCard } from '@/components/schedule/BundleCard';
import { WatchDetailPanel } from '@/components/schedule/WatchDetailPanel';
import { CreateTaskModal } from '@/components/schedule/CreateTaskModal';
import { MultiMonitorModal } from '@/components/schedule/MultiMonitorModal';
import { SingleAssetMonitorModal } from '@/components/schedule/SingleAssetMonitorModal';
import { MonitoringPlanCard } from '@/components/schedule/MonitoringPlanCard';
import { RunHistoryTable } from '@/components/schedule/RunHistoryTable';
import { cn } from '@/lib/utils';
import type { ScheduledTask, TaskRun, MonitorGroupSummary } from '@/types/schedule';
import { RUN_STATUS_COLORS } from '@/types/schedule';
import type { WatchSummary, MonitoringPlanSummary } from '@/types/health-watch';

type FilterStatus = 'all' | 'passing' | 'failing' | 'disabled';

export default function SchedulePage() {
  const { data: session } = useSession();
  const { selectedPipeline } = usePipeline();

  // Task list state
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterStatus>('all');
  const [showMultiMonitorModal, setShowMultiMonitorModal] = useState(false);
  const [showSingleAssetModal, setShowSingleAssetModal] = useState(false);
  const [showPromptModal, setShowPromptModal] = useState(false);
  const [showNewDropdown, setShowNewDropdown] = useState(false);

  // Monitoring plans
  const [plans, setPlans] = useState<MonitoringPlanSummary[]>([]);

  // Watch state (preset-created)
  const [watches, setWatches] = useState<WatchSummary[]>([]);
  const [selectedWatch, setSelectedWatch] = useState<WatchSummary | null>(null);

  // Bundle state (manually-created bundle monitors)
  const [bundles, setBundles] = useState<MonitorGroupSummary[]>([]);
  const [watchDetailMonitors, setWatchDetailMonitors] = useState<any[]>([]);
  const [watchDetailLoading, setWatchDetailLoading] = useState(false);

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

  // Fetch watches (preset-created)
  const fetchWatches = useCallback(async () => {
    try {
      const res = await cachedFetch('/api/schedule/watches');
      if (res.ok) {
        const data = await res.json();
        setWatches(data.watches || []);
      }
    } catch (err) {
      console.error('[Schedule] Failed to fetch watches:', err);
    }
  }, []);

  // Fetch monitoring plans
  const fetchPlans = useCallback(async () => {
    try {
      const res = await cachedFetch('/api/schedule/plans');
      if (res.ok) {
        const data = await res.json();
        setPlans(data.plans || []);
      }
    } catch (err) {
      console.error('[Schedule] Failed to fetch plans:', err);
    }
  }, []);

  // Fetch bundles (manually-created bundle monitors)
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
    setSelectedWatch(null);
    setWatchDetailMonitors([]);
    setTaskRuns([]);
    fetchTasks();
    fetchWatches();
    fetchBundles();
    fetchPlans();
  }, [fetchTasks, fetchWatches, fetchBundles, fetchPlans]);

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

  // Fetch watch detail
  useEffect(() => {
    if (!selectedWatch) return;

    const fetchDetail = async () => {
      setWatchDetailLoading(true);
      try {
        const res = await fetch(`/api/schedule/watches/${selectedWatch.id}`);
        if (res.ok) {
          const data = await res.json();
          setWatchDetailMonitors(data.watch?.monitors || []);
          // Update the selected watch with latest data
          if (data.watch) {
            setSelectedWatch((prev) => prev ? { ...prev, ...data.watch } : prev);
          }
        }
      } catch (err) {
        console.error('[Schedule] Failed to fetch watch detail:', err);
      } finally {
        setWatchDetailLoading(false);
      }
    };

    fetchDetail();
  }, [selectedWatch?.id]);

  // Refresh all data after creation
  const handleMonitorCreated = useCallback(() => {
    invalidateCache('/api/schedule');
    fetchPlans();
    fetchWatches();
    fetchBundles();
    fetchTasks();
  }, [fetchPlans, fetchWatches, fetchBundles, fetchTasks]);

  // Toggle watch enabled
  const handleToggleWatchEnabled = async (watchId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/watches/${watchId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      invalidateCache('/api/schedule');
      setWatches((prev) =>
        prev.map((w) => (w.id === watchId ? { ...w, enabled } : w))
      );
      if (selectedWatch?.id === watchId) {
        setSelectedWatch((prev) => prev ? { ...prev, enabled } : prev);
      }
    } catch (err) {
      console.error('[Schedule] Failed to toggle watch:', err);
    }
  };

  // Run all monitors in a watch
  const handleRunWatch = async (watchId: string) => {
    try {
      const res = await fetch(`/api/schedule/watches/${watchId}/run`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchWatches();
        fetchTasks();
        if (selectedWatch?.id === watchId) {
          const detailRes = await fetch(`/api/schedule/watches/${watchId}`);
          if (detailRes.ok) {
            const data = await detailRes.json();
            if (data.watch) {
              setSelectedWatch(data.watch);
              setWatchDetailMonitors(data.watch.monitors || []);
            }
          }
        }
      }
    } catch (err) {
      console.error('[Schedule] Failed to run watch:', err);
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
      invalidateCache('/api/schedule/bundles');
      setBundles((prev) =>
        prev.map((b) => (b.id === bundleId ? { ...b, enabled } : b))
      );
    } catch (err) {
      console.error('[Schedule] Failed to toggle bundle:', err);
    }
  };

  // Run all monitors in a bundle
  const handleRunBundle = async (bundleId: string) => {
    try {
      await fetch(`/api/schedule/bundles/${bundleId}/run`, { method: 'POST' });
      fetchBundles();
      fetchTasks();
    } catch (err) {
      console.error('[Schedule] Failed to run bundle:', err);
    }
  };

  // Toggle plan enabled
  const handleTogglePlanEnabled = async (planId: string, enabled: boolean) => {
    try {
      await fetch(`/api/schedule/plans/${planId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      invalidateCache('/api/schedule');
      setPlans((prev) =>
        prev.map((p) => (p.id === planId ? { ...p, enabled } : p))
      );
    } catch (err) {
      console.error('[Schedule] Failed to toggle plan:', err);
    }
  };

  // Run all monitors in a plan
  const handleRunPlan = async (planId: string) => {
    try {
      await fetch(`/api/schedule/plans/${planId}/run`, { method: 'POST' });
      fetchPlans();
      fetchWatches();
      fetchTasks();
    } catch (err) {
      console.error('[Schedule] Failed to run plan:', err);
    }
  };

  // Delete watch
  const handleDeleteWatch = async (watchId: string) => {
    try {
      await fetch(`/api/schedule/watches/${watchId}`, { method: 'DELETE' });
      invalidateCache('/api/schedule');
      invalidateCache('/api/pipeline');
      setWatches((prev) => prev.filter((w) => w.id !== watchId));
      setSelectedWatch(null);
      setWatchDetailMonitors([]);
      fetchTasks();
      fetchWatches();
    } catch (err) {
      console.error('[Schedule] Failed to delete watch:', err);
    }
  };

  // Remove monitor from watch
  const handleRemoveMonitorFromWatch = async (monitorId: string) => {
    if (!selectedWatch) return;
    try {
      const res = await fetch(`/api/schedule/watches/${selectedWatch.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ removeMonitorIds: [monitorId] }),
      });
      if (res.ok) {
        invalidateCache('/api/schedule');
        // Re-fetch watch detail
        const detailRes = await fetch(`/api/schedule/watches/${selectedWatch.id}`);
        if (detailRes.ok) {
          const data = await detailRes.json();
          setWatchDetailMonitors(data.watch?.monitors || []);
          if (data.watch) setSelectedWatch(data.watch);
        }
        fetchWatches();
      }
    } catch (err) {
      console.error('[Schedule] Failed to remove monitor from watch:', err);
    }
  };

  // Create monitor/prompt task
  const handleCreateTask = async (taskData: any) => {
    try {
      const res = await fetch('/api/schedule/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(taskData),
      });
      if (res.ok) {
        setShowPromptModal(false);
        fetchTasks();
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

  // Watch detail view
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

  // Task list view
  return (
    <div className="flex flex-col h-full bg-[var(--surface-inset)]">
      {/* Page header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
        <div>
          <h1 className="text-[18px] font-semibold text-[var(--text)]">Monitoring</h1>
          <p className="text-[13px] text-[var(--muted)] mt-0.5">
            Monitoring plans, monitor groups, and individual monitors
          </p>
        </div>
        <div className="relative flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => setShowNewDropdown(!showNewDropdown)}
          >
            + New
          </Button>
          {showNewDropdown && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowNewDropdown(false)} />
              <div className="absolute right-0 top-full mt-1 z-20 w-64 rounded-lg border border-[var(--border)] bg-[var(--bg)] shadow-xl overflow-hidden">
                <button
                  onClick={() => { setShowNewDropdown(false); setShowMultiMonitorModal(true); }}
                  className="w-full text-left px-4 py-3 hover:bg-[var(--subtle-bg)] transition-colors border-b border-[var(--border)]"
                >
                  <p className="text-[13px] font-medium text-[var(--text)]">Multi Monitor</p>
                  <p className="text-[11px] text-[var(--muted)] mt-0.5">Select multiple assets visually and apply monitors across the group.</p>
                </button>
                <button
                  onClick={() => { setShowNewDropdown(false); setShowSingleAssetModal(true); }}
                  className="w-full text-left px-4 py-3 hover:bg-[var(--subtle-bg)] transition-colors border-b border-[var(--border)]"
                >
                  <p className="text-[13px] font-medium text-[var(--text)]">Single Asset Monitor</p>
                  <p className="text-[11px] text-[var(--muted)] mt-0.5">Create monitors for one asset.</p>
                </button>
                <button
                  onClick={() => { setShowNewDropdown(false); setShowPromptModal(true); }}
                  className="w-full text-left px-4 py-3 hover:bg-[var(--subtle-bg)] transition-colors"
                >
                  <p className="text-[13px] font-medium text-[var(--text)]">AI Prompt Monitor</p>
                  <p className="text-[11px] text-[var(--muted)] mt-0.5">Describe what you want monitored in natural language.</p>
                </button>
              </div>
            </>
          )}
        </div>
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
          {(plans.length + watches.length + bundles.length) > 0 && `${plans.length + watches.length + bundles.length} group${(plans.length + watches.length + bundles.length) !== 1 ? 's' : ''} · `}
          {tasks.length} monitor{tasks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 red-spinner" />
          </div>
        ) : plans.length === 0 && watches.length === 0 && bundles.length === 0 && tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20">
            <svg className="w-12 h-12 text-[var(--text-faint)] mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <h3 className="text-[15px] font-medium text-[var(--muted)] mb-1">No monitors yet</h3>
            <p className="text-[13px] text-[var(--text-faint)] mb-4">
              Set up monitoring to protect your pipeline — it's the fastest way to cover your data stack.
            </p>
            <Button size="sm" onClick={() => setShowMultiMonitorModal(true)}>
              Multi Monitor
            </Button>
            <p className="text-[12px] text-[var(--text-faint)] mt-3">
              Or create a{' '}
              <button onClick={() => setShowSingleAssetModal(true)} className="text-[var(--muted)] hover:text-[var(--text)] underline">single asset monitor</button>
              {' · '}
              <button onClick={() => setShowPromptModal(true)} className="text-[var(--muted)] hover:text-[var(--text)] underline">AI prompt monitor</button>
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Monitor Groups (unified: plans + bundles + watches) */}
            {(plans.length > 0 || bundles.length > 0 || watches.length > 0) && (
              <div>
                <h3 className="text-[12px] font-medium text-[var(--text-faint)] uppercase tracking-wider mb-2">
                  Monitor Groups
                </h3>
                <div className="space-y-2">
                  {plans.map((plan) => (
                    <MonitoringPlanCard
                      key={plan.id}
                      plan={plan}
                      onClick={() => {/* TODO: plan detail view */}}
                      onToggleEnabled={(enabled) => handleTogglePlanEnabled(plan.id, enabled)}
                      onRunAll={() => handleRunPlan(plan.id)}
                    />
                  ))}
                  {bundles.map((bundle) => (
                    <BundleCard
                      key={bundle.id}
                      bundle={bundle}
                      onClick={() => {/* TODO: bundle detail view */}}
                      onToggleEnabled={(enabled) => handleToggleBundleEnabled(bundle.id, enabled)}
                      onRunAll={() => handleRunBundle(bundle.id)}
                    />
                  ))}
                  {watches.map((watch) => (
                    <WatchCard
                      key={watch.id}
                      watch={watch}
                      onClick={() => setSelectedWatch(watch)}
                      onToggleEnabled={(enabled) => handleToggleWatchEnabled(watch.id, enabled)}
                      onRunAll={() => handleRunWatch(watch.id)}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Individual Monitors */}
            {tasks.length > 0 && (
              <div>
                <h3 className="text-[12px] font-medium text-[var(--text-faint)] uppercase tracking-wider mb-2">
                  Individual Monitors
                </h3>
                <div className="space-y-2">
                  {tasks.map((task) => (
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

      {/* Multi Monitor modal */}
      <MultiMonitorModal
        open={showMultiMonitorModal}
        onClose={() => setShowMultiMonitorModal(false)}
        onComplete={handleMonitorCreated}
        stackId={selectedPipeline?.id}
      />

      {/* Single Asset Monitor modal */}
      <SingleAssetMonitorModal
        open={showSingleAssetModal}
        onClose={() => setShowSingleAssetModal(false)}
        onComplete={handleMonitorCreated}
        stackId={selectedPipeline?.id}
      />

      {/* AI Prompt Monitor / Edit Task modal */}
      <CreateTaskModal
        open={showPromptModal || !!editingTask}
        onClose={() => { setShowPromptModal(false); setEditingTask(null); }}
        onSubmit={handleCreateTask}
        onUpdate={handleUpdateTask}
        editTask={editingTask}
        integrations={integrations}
        stackId={selectedPipeline?.id}
        initialMode="prompt"
      />

    </div>
  );
}
