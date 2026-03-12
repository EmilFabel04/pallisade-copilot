'use client';

import { cn } from '@/lib/utils';
import type { MonitorGroupSummary } from '@/types/schedule';
import { RUN_STATUS_COLORS } from '@/types/schedule';

interface BundleCardProps {
  bundle: MonitorGroupSummary;
  onClick: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRunAll: () => void;
}

const GROUP_TYPE_COLORS: Record<string, string> = {
  upstream_stability: 'bg-blue-500/15 text-blue-400',
  reporting_health: 'bg-purple-500/15 text-purple-400',
  asset_stability: 'bg-amber-500/15 text-amber-400',
  custom: 'bg-white/10 text-white/50',
};

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

export function BundleCard({ bundle, onClick, onToggleEnabled, onRunAll }: BundleCardProps) {
  const statusColor = bundle.lastStatus
    ? RUN_STATUS_COLORS[bundle.lastStatus] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
    : 'bg-[var(--overlay-medium)] text-[var(--muted)]';

  const groupTypeColor = GROUP_TYPE_COLORS[bundle.groupType] || GROUP_TYPE_COLORS.custom;

  const totalMonitors = bundle.monitorCount;
  const passRate = totalMonitors > 0 ? (bundle.passCount / totalMonitors) * 100 : 0;

  return (
    <div
      className="group relative bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl p-4 hover:border-[var(--overlay-strong)] transition-all cursor-pointer"
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-3">
        {/* Left: Name + type */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <svg className="w-3.5 h-3.5 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            <h3 className="text-[14px] font-medium text-[var(--text)] truncate">{bundle.name}</h3>
            <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium uppercase', statusColor)}>
              {bundle.lastStatus || 'NEW'}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
            <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', groupTypeColor)}>
              {bundle.groupType.replace(/_/g, ' ')}
            </span>
            <span className="flex items-center gap-1">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {cronToHuman(bundle.schedule || '')}
            </span>
            <span>{bundle.monitorCount} monitor{bundle.monitorCount !== 1 ? 's' : ''}</span>
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          {/* Run All */}
          <button
            onClick={onRunAll}
            className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors opacity-0 group-hover:opacity-100"
            title="Run all monitors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>

          {/* Toggle */}
          <button
            onClick={() => onToggleEnabled(!bundle.enabled)}
            className={cn(
              'relative w-8 h-[18px] rounded-full transition-colors',
              bundle.enabled ? 'bg-emerald-500/40' : 'bg-[var(--overlay-medium)]'
            )}
          >
            <div className={cn(
              'absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform',
              bundle.enabled ? 'left-[16px]' : 'left-[2px]'
            )} />
          </button>
        </div>
      </div>

      {/* Progress bar + counts */}
      <div className="mt-3">
        <div className="flex items-center gap-2 mb-1.5">
          <div className="flex-1 h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden">
            {totalMonitors > 0 && (
              <div className="flex h-full">
                {bundle.passCount > 0 && (
                  <div
                    className="bg-emerald-500/60 h-full"
                    style={{ width: `${(bundle.passCount / totalMonitors) * 100}%` }}
                  />
                )}
                {bundle.warnCount > 0 && (
                  <div
                    className="bg-amber-500/60 h-full"
                    style={{ width: `${(bundle.warnCount / totalMonitors) * 100}%` }}
                  />
                )}
                {bundle.failCount > 0 && (
                  <div
                    className="bg-red-500/60 h-full"
                    style={{ width: `${(bundle.failCount / totalMonitors) * 100}%` }}
                  />
                )}
              </div>
            )}
          </div>
          <span className="text-[11px] text-[var(--muted)] shrink-0">
            {bundle.passCount}/{totalMonitors} passing
          </span>
        </div>
      </div>

      {/* Bottom: Last run */}
      <div className="flex items-center gap-3 mt-1 text-[11px] text-[var(--text-faint)]">
        <span>Last run: {timeAgo(bundle.lastRunAt)}</span>
        {bundle.anchorFqn && (
          <span className="truncate max-w-[250px] font-mono" title={bundle.anchorFqn}>
            {bundle.anchorFqn}
          </span>
        )}
      </div>
    </div>
  );
}
