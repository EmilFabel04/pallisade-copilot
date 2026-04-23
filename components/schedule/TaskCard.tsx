'use client';

import { cn } from '@/lib/utils';
import type { ScheduledTask } from '@/types/schedule';
import { RUN_STATUS_COLORS } from '@/types/schedule';

interface TaskCardProps {
  task: ScheduledTask;
  onClick: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRunNow: () => void;
}

function cronToHuman(cron: string): string {
  const presets: Record<string, string> = {
    '0 * * * *': 'Every hour',
    '0 */6 * * *': 'Every 6 hours',
    '0 8 * * *': 'Daily at 8am',
    '0 8 * * 1-5': 'Weekdays at 8am',
    '0 8 * * 1': 'Weekly (Mon 8am)',
  };
  return presets[cron] || cron;
}

function timeAgo(dateStr?: string): string {
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

export function TaskCard({ task, onClick, onToggleEnabled, onRunNow }: TaskCardProps) {
  const statusColor = task.lastStatus
    ? RUN_STATUS_COLORS[task.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
    : 'bg-[var(--overlay-medium)] text-[var(--muted)]';

  return (
    <div
      className="group relative bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl p-4 hover:border-[var(--overlay-strong)] transition-all cursor-pointer"
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-3">
        {/* Left: Name + type */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-[14px] font-medium text-[var(--text)] truncate">{task.name}</h3>
            <span className={cn(
              'px-1.5 py-0.5 rounded text-[10px] font-medium uppercase',
              statusColor
            )}>
              {task.lastStatus || 'NEW'}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
            <span className="flex items-center gap-1">
              {task.taskMode === 'prompt' ? (
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
              ) : (
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              )}
              {task.taskMode === 'prompt' ? 'AI Prompt' : (task.monitorType || 'Monitor')}
            </span>
            <span className="flex items-center gap-1">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {cronToHuman(task.schedule)}
            </span>
            {task.targetFqn && (
              <span className="truncate max-w-[200px]" title={task.targetFqn}>
                {task.targetFqn}
              </span>
            )}
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          {/* Run Now */}
          <button
            onClick={onRunNow}
            className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors opacity-0 group-hover:opacity-100"
            title="Run now"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>

          {/* Toggle */}
          <button
            onClick={() => onToggleEnabled(!task.enabled)}
            className={cn(
              'relative w-8 h-[18px] rounded-full transition-colors',
              task.enabled ? 'bg-emerald-500/40' : 'bg-[var(--overlay-medium)]'
            )}
          >
            <div className={cn(
              'absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform',
              task.enabled ? 'left-[16px]' : 'left-[2px]'
            )} />
          </button>
        </div>
      </div>

      {/* Bottom: Last run + alerts */}
      <div className="flex items-center gap-3 mt-2.5 text-[11px] text-[var(--text-faint)]">
        <span>Last run: {timeAgo(task.lastRunAt)}</span>
        {task.alertChannels.length > 0 && (
          <span className="flex items-center gap-1">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
            {task.alertChannels.join(', ')}
          </span>
        )}
        {task.integrationName && (
          <span>{task.integrationName}</span>
        )}
      </div>
    </div>
  );
}
