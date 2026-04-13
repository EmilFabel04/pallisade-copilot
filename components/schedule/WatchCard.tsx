'use client';

import { Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { WatchSummary } from '@/types/health-watch';
import {
  WATCH_TYPE_LABELS,
  HEALTH_STATUS_COLORS,
  HEALTH_STATUS_LABELS,
  FAILURE_CATEGORY_LABELS,
  healthStatusFromScore,
  type HealthStatus,
  type FailureCategory,
} from '@/types/health-watch';
import { DOMAIN_COLORS, isMonitorConfigIncomplete } from '@/types/monitor-catalog';

interface WatchCardProps {
  watch: WatchSummary;
  policyMonitorCount?: number;
  overrideMonitorCount?: number;
  running?: boolean;
  onClick: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRunAll: () => void;
  onDelete?: () => void;
  onSettings?: () => void;
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

export function WatchCard({ watch, policyMonitorCount = 0, overrideMonitorCount = 0, running = false, onClick, onToggleEnabled, onRunAll, onDelete, onSettings }: WatchCardProps) {

  const totalMonitors = watch.monitorCount;
  const hasRun = watch.passCount > 0 || watch.warnCount > 0 || watch.failCount > 0;
  const noRunYet = !hasRun && totalMonitors > 0;
  const needsConfigCount = watch.monitors.filter(
    (m) => isMonitorConfigIncomplete(m.monitorType, m.config),
  ).length;

  const liveHealthScore = hasRun && totalMonitors > 0
    ? Math.round(((watch.passCount + watch.warnCount * 0.5) / totalMonitors) * 100)
    : watch.healthScore;

  const healthStatus: HealthStatus | null = hasRun && liveHealthScore != null
    ? healthStatusFromScore(liveHealthScore)
    : watch.healthScore != null ? healthStatusFromScore(watch.healthScore) : null;

  return (
    <div
      className="group relative bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl overflow-hidden hover:border-[var(--overlay-strong)] transition-all cursor-pointer"
      onClick={onClick}
    >
      {/* Status bar at top */}
      <style>{`@keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }`}</style>
      {running ? (
        <div className="h-1.5 relative overflow-hidden">
          {/* Show live results underneath if available */}
          {hasRun && totalMonitors > 0 ? (
            <div className="flex h-full absolute inset-0">
              {watch.passCount > 0 && (
                <div className="bg-emerald-500 h-full transition-all duration-500" style={{ width: `${(watch.passCount / totalMonitors) * 100}%` }} />
              )}
              {watch.warnCount > 0 && (
                <div className="bg-amber-500 h-full transition-all duration-500" style={{ width: `${(watch.warnCount / totalMonitors) * 100}%` }} />
              )}
              {watch.failCount > 0 && (
                <div className="bg-red-500 h-full transition-all duration-500" style={{ width: `${(watch.failCount / totalMonitors) * 100}%` }} />
              )}
              {(watch.passCount + watch.warnCount + watch.failCount) < totalMonitors && (
                <div className="bg-[var(--overlay-bg)] h-full flex-1" />
              )}
            </div>
          ) : (
            <div className="absolute inset-0 bg-[var(--accent)]/20" />
          )}
          {/* Shimmer sweep overlay */}
          <div className="absolute inset-0">
            <div className="h-full w-1/3 bg-white/25" style={{ animation: 'shimmer 1.5s ease-in-out infinite' }} />
          </div>
        </div>
      ) : hasRun && totalMonitors > 0 ? (
        <div className="flex h-1.5">
          {watch.passCount > 0 && (
            <div className="bg-emerald-500 h-full transition-all duration-500" style={{ width: `${(watch.passCount / totalMonitors) * 100}%` }} />
          )}
          {watch.warnCount > 0 && (
            <div className="bg-amber-500 h-full transition-all duration-500" style={{ width: `${(watch.warnCount / totalMonitors) * 100}%` }} />
          )}
          {watch.failCount > 0 && (
            <div className="bg-red-500 h-full transition-all duration-500" style={{ width: `${(watch.failCount / totalMonitors) * 100}%` }} />
          )}
          {(watch.passCount + watch.warnCount + watch.failCount) < totalMonitors && (
            <div className="bg-[var(--overlay-bg)] h-full flex-1" />
          )}
        </div>
      ) : (
        <div className="h-1.5 bg-[var(--overlay-bg)]" />
      )}

      <div className="p-4">
        {/* Row 1: Name + actions */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <h3 className="text-[14px] font-medium text-[var(--text)] truncate">{watch.name}</h3>
              {needsConfigCount > 0 && !running && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-400">
                  {needsConfigCount} needs config
                </span>
              )}
              {noRunYet && !running && needsConfigCount === 0 && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)]">
                  NEW
                </span>
              )}
              {watch.watchType === 'tool_health' && watch.anchorPlatform && (
                <span className={cn(
                  'px-1.5 py-0.5 rounded text-[10px] font-medium',
                  DOMAIN_COLORS[watch.anchorPlatform?.toLowerCase()] || 'bg-white/10 text-white/50',
                )}>
                  {watch.anchorPlatform}
                </span>
              )}
            </div>
            {watch.anchorFqn && (
              <p className="text-[11px] text-[var(--text-faint)] font-mono truncate" title={watch.anchorFqn}>
                {watch.anchorFqn}
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            {onSettings && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onSettings();
                }}
                className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
                title="Group settings"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </button>
            )}
            {onDelete && (
              <button
                onClick={onDelete}
                className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-red-400 hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
                title="Delete"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={onRunAll}
              disabled={running}
              className={cn(
                "p-1.5 rounded-lg transition-colors",
                running
                  ? "text-[var(--accent)] animate-pulse cursor-not-allowed"
                  : "text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
              )}
              title="Run all monitors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onToggleEnabled(!watch.enabled); }}
              className={cn(
                'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                watch.enabled ? 'bg-blue-500' : 'bg-[var(--overlay-strong)]'
              )}
              title={watch.enabled ? 'Disable' : 'Enable'}
            >
              <span className={cn(
                'pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-lg transition-transform',
                watch.enabled ? 'translate-x-4' : 'translate-x-0'
              )} />
            </button>
          </div>
        </div>

        {/* Row 2: Stats */}
        <div className="flex items-center gap-4 mt-3">
          {/* Monitor counts */}
          <div className="flex items-center gap-3 text-[12px]">
            <span className="text-[var(--muted)]">{totalMonitors} monitor{totalMonitors !== 1 ? 's' : ''}</span>
            {hasRun && (
              <>
                <span className="text-emerald-400 font-medium">{watch.passCount} pass</span>
                {watch.warnCount > 0 && <span className="text-amber-400 font-medium">{watch.warnCount} warn</span>}
                {watch.failCount > 0 && <span className="text-red-400 font-medium">{watch.failCount} fail</span>}
              </>
            )}
          </div>

          {/* SLA coverage */}
          {policyMonitorCount > 0 && (
            <div className="flex items-center gap-2 text-[11px] border-l border-[var(--subtle-border)] pl-3">
              {overrideMonitorCount > 0 && (
                <span className="text-amber-400">{overrideMonitorCount} overridden</span>
              )}
              {(policyMonitorCount - overrideMonitorCount) > 0 && (
                <span className="text-violet-400">{policyMonitorCount - overrideMonitorCount} SLA covered</span>
              )}
            </div>
          )}
        </div>

        {/* Row 3: Schedule + last run */}
        <div className="flex items-center gap-3 mt-2 text-[11px] text-[var(--text-faint)]">
          <span className="flex items-center gap-1">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {cronToHuman(watch.schedule || '')}
          </span>
          <span>Last run: {timeAgo(watch.lastRunAt)}</span>
        </div>

        {/* Failure groups */}
        {(watch.healthDetails?.failureGroups || []).length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {(watch.healthDetails?.failureGroups || []).slice(0, 3).map((fg, i) => (
              <span
                key={i}
                className={cn(
                  'px-1.5 py-0.5 rounded text-[10px] font-medium',
                  fg.severity === 'critical' ? 'bg-red-500/10 text-red-400' : 'bg-amber-500/10 text-amber-400'
                )}
              >
                {FAILURE_CATEGORY_LABELS[fg.category as FailureCategory] || fg.category.replace(/_/g, ' ')}
                {fg.signalCount > 1 && ` (${fg.signalCount})`}
              </span>
            ))}
          </div>
        )}
      </div>

    </div>
  );
}
