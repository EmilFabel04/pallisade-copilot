'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { usePipeline } from '@/contexts/PipelineContext';
import { Button } from '@/components/ui/button';
import { TaskCard } from '@/components/schedule/TaskCard';
import { CreateTaskModal } from '@/components/schedule/CreateTaskModal';
import { RunHistoryTable } from '@/components/schedule/RunHistoryTable';
import { cn } from '@/lib/utils';
import type { ScheduledTask, TaskRun } from '@/types/schedule';
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

  // Task detail state
  const [selectedTask, setSelectedTask] = useState<ScheduledTask | null>(null);
  const [taskRuns, setTaskRuns] = useState<TaskRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  // Edit modal state
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);

  // Integrations for create modal
  const [integrations, setIntegrations] = useState<Array<{ id: string; name: string; type: string }>>([]);

  // Fetch tasks
  const fetchTasks = useCallback(async () => {
    try {
      const params = filter !== 'all' ? `?status=${filter}` : '';
      const res = await fetch(`/api/schedule/tasks${params}`);
      if (res.ok) {
        const data = await res.json();
        setTasks(data.tasks || []);
      }
    } catch (err) {
      console.error('[Schedule] Failed to fetch tasks:', err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  // Fetch integrations for create modal
  useEffect(() => {
    if (!selectedPipeline?.id) return;

    const fetchIntegrations = async () => {
      try {
        const res = await fetch(`/api/pipeline/nodes?stackId=${selectedPipeline.id}`);
        if (res.ok) {
          const data = await res.json();
          const nodes = data.nodes || [];
          const intgs = nodes
            .filter((n: any) => n.status === 'active' || n.status === 'connected')
            .map((n: any) => ({
              id: n.integrationId || n.id,
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
        const res = await fetch(`/api/schedule/tasks/${selectedTask.id}/runs`);
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

  // Create task
  const handleCreateTask = async (taskData: any) => {
    try {
      const res = await fetch('/api/schedule/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(taskData),
      });
      if (res.ok) {
        setShowCreateModal(false);
        fetchTasks();
      }
    } catch (err) {
      console.error('[Schedule] Failed to create task:', err);
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
        // Refresh tasks to show updated lastRunAt/lastStatus
        fetchTasks();
        // If viewing this task's detail, refresh runs too
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
        // Refresh selected task with full data from GET endpoint
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

  // Task detail view
  if (selectedTask) {
    const statusColor = selectedTask.lastStatus
      ? RUN_STATUS_COLORS[selectedTask.lastStatus] || 'bg-white/10 text-white/40'
      : 'bg-white/10 text-white/40';

    return (
      <div className="flex flex-col h-full bg-[#050508]">
        {/* Detail header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSelectedTask(null)}
              className="p-1.5 rounded-lg text-white/40 hover:text-white hover:bg-white/[0.06]"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-[16px] font-semibold text-white">{selectedTask.name}</h2>
                <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', statusColor)}>
                  {selectedTask.lastStatus || 'NEW'}
                </span>
              </div>
              <p className="text-[12px] text-white/40 mt-0.5">
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
        <div className="px-6 py-4 border-b border-white/[0.04]">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-[11px] text-white/30 uppercase tracking-wider mb-1">Type</p>
              <p className="text-[13px] text-white/80">
                {selectedTask.taskMode === 'prompt' ? 'AI Prompt' : selectedTask.monitorType}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-white/30 uppercase tracking-wider mb-1">Schedule</p>
              <p className="text-[13px] text-white/80">{selectedTask.schedule}</p>
            </div>
            <div>
              <p className="text-[11px] text-white/30 uppercase tracking-wider mb-1">Alerts</p>
              <p className="text-[13px] text-white/80">
                {selectedTask.alertChannels.length > 0
                  ? selectedTask.alertChannels.join(', ')
                  : 'None'}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-white/30 uppercase tracking-wider mb-1">Status</p>
              <p className="text-[13px] text-white/80">
                {selectedTask.enabled ? 'Enabled' : 'Disabled'}
              </p>
            </div>
          </div>
          {selectedTask.prompt && (
            <div className="mt-3 p-3 bg-white/[0.03] rounded-lg border border-white/[0.06]">
              <p className="text-[11px] text-white/30 uppercase tracking-wider mb-1">Prompt</p>
              <p className="text-[13px] text-white/60">{selectedTask.prompt}</p>
            </div>
          )}
        </div>

        {/* Run history */}
        <div className="flex-1 px-6 py-4 overflow-y-auto">
          <h3 className="text-[14px] font-medium text-white mb-3">Run History</h3>
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
        />
      </div>
    );
  }

  // Task list view
  return (
    <div className="flex flex-col h-full bg-[#050508]">
      {/* Page header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
        <div>
          <h1 className="text-[18px] font-semibold text-white">Scheduled Tasks</h1>
          <p className="text-[13px] text-white/40 mt-0.5">
            Schedule quality checks, anomaly detection, and pipeline monitoring
          </p>
        </div>
        <Button size="sm" onClick={() => setShowCreateModal(true)}>
          + Create Task
        </Button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-white/[0.04]">
        {(['all', 'passing', 'failing', 'disabled'] as FilterStatus[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors capitalize',
              filter === f
                ? 'bg-white/[0.1] text-white'
                : 'text-white/40 hover:text-white/60 hover:bg-white/[0.04]'
            )}
          >
            {f}
          </button>
        ))}
        <span className="text-[12px] text-white/20 ml-2">
          {tasks.length} task{tasks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-white/20 border-t-white/60 rounded-full animate-spin" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20">
            <svg className="w-12 h-12 text-white/10 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <h3 className="text-[15px] font-medium text-white/50 mb-1">No scheduled tasks</h3>
            <p className="text-[13px] text-white/30 mb-4">
              Create your first task to start monitoring your data pipeline
            </p>
            <Button size="sm" onClick={() => setShowCreateModal(true)}>
              + Create Task
            </Button>
          </div>
        ) : (
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
      />
    </div>
  );
}
