'use client';

import { useState } from 'react';
import { Settings, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { WatchSummary } from '@/types/health-watch';
import { WatchEditModal } from './WatchEditModal';
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
  onClick: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRunAll: () => void;
  onDelete?: () => void;
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

export function WatchCard({ watch, policyMonitorCount = 0, overrideMonitorCount = 0, onClick, onToggleEnabled, onRunAll, onDelete }: WatchCardProps) {
  const [showEditModal, setShowEditModal] = useState(false);

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
      {hasRun && totalMonitors > 0 ? (
        <div className="flex h-1.5">
          {watch.passCount > 0 && (
            <div className="bg-emerald-500 h-full" style={{ width: `${(watch.passCount / totalMonitors) * 100}%` }} />
          )}
          {watch.warnCount > 0 && (
            <div className="bg-amber-500 h-full" style={{ width: `${(watch.warnCount / totalMonitors) * 100}%` }} />
          )}
          {watch.failCount > 0 && (
            <div className="bg-red-500 h-full" style={{ width: `${(watch.failCount / totalMonitors) * 100}%` }} />
          )}
          {/* Remaining = not yet run within group */}
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
              {needsConfigCount > 0 && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-400">
                  {needsConfigCount} needs config
                </span>
              )}
              {noRunYet && needsConfigCount === 0 && (
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
              className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors opacity-0 group-hover:opacity-100"
              title="Run all monitors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); setShowEditModal(true); }}
              className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] opacity-0 group-hover:opacity-100 transition-all"
              title="Edit watch settings"
            >
              <Settings size={14} />
            </button>
            <button
              onClick={() => onToggleEnabled(!watch.enabled)}
              className={cn(
                'relative w-8 h-[18px] rounded-full transition-colors',
                watch.enabled ? 'bg-emerald-500/40' : 'bg-[var(--overlay-medium)]'
              )}
            >
              <div className={cn(
                'absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform',
                watch.enabled ? 'left-[16px]' : 'left-[2px]'
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

      {showEditModal && (
        <WatchEditModal
          watch={{
            id: watch.id,
            name: watch.name,
            schedule: watch.schedule,
            timezone: watch.timezone,
            alertChannels: watch.alertChannels || [],
            alertOnStatus: watch.alertOnStatus || [],
            enabled: watch.enabled,
          }}
          onSave={async (data: Record<string, any>) => {
            await fetch(`/api/schedule/watches/${watch.id}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(data),
            });
          }}
          onClose={() => setShowEditModal(false)}
        />
      )}
    </div>
  );
}
