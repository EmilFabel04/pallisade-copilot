'use client';

import { cn } from '@/lib/utils';
import type { TaskRun } from '@/types/schedule';
import { RUN_STATUS_COLORS } from '@/types/schedule';

interface RunHistoryTableProps {
  runs: TaskRun[];
  loading?: boolean;
}

function formatDuration(ms?: number): string {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(dateStr?: string): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function RunHistoryTable({ runs, loading }: RunHistoryTableProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-5 h-5 border-2 border-white/20 border-t-white/60 rounded-full animate-spin" />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-[13px] text-white/30">No runs yet</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-white/[0.06]">
      <table className="w-full">
        <thead>
          <tr className="border-b border-white/[0.06]">
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Status
            </th>
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Time
            </th>
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Value
            </th>
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Duration
            </th>
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Message
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr
              key={run.id}
              className="border-b border-white/[0.04] last:border-0 hover:bg-white/[0.02]"
            >
              <td className="px-4 py-2.5">
                <span
                  className={cn(
                    'px-2 py-0.5 rounded text-[11px] font-medium',
                    RUN_STATUS_COLORS[run.status] || 'bg-white/10 text-white/40'
                  )}
                >
                  {run.status}
                </span>
              </td>
              <td className="px-4 py-2.5 text-[12px] text-white/60">
                {formatTime(run.startedAt)}
              </td>
              <td className="px-4 py-2.5 text-[12px] text-white/60 font-mono">
                {run.value != null ? run.value.toFixed(2) : '-'}
              </td>
              <td className="px-4 py-2.5 text-[12px] text-white/40">
                {formatDuration(run.durationMs)}
              </td>
              <td className="px-4 py-2.5 text-[12px] text-white/40 max-w-[300px] truncate">
                {run.message || '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
