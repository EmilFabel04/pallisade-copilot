'use client';

import { useState } from 'react';
import { Settings } from 'lucide-react';
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

interface WatchCardProps {
  watch: WatchSummary;
  policyMonitorCount?: number;
  overrideMonitorCount?: number;
  onClick: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRunAll: () => void;
}

const WATCH_TYPE_COLORS: Record<string, string> = {
  pipeline_health: 'bg-blue-500/15 text-blue-400',
  dashboard_shield: 'bg-purple-500/15 text-purple-400',
  source_guard: 'bg-emerald-500/15 text-emerald-400',
  model_quality: 'bg-amber-500/15 text-amber-400',
  data_drift: 'bg-orange-500/15 text-orange-400',
  custom_watch: 'bg-[var(--overlay-medium)] text-[var(--muted)]',
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

export function WatchCard({ watch, policyMonitorCount = 0, overrideMonitorCount = 0, onClick, onToggleEnabled, onRunAll }: WatchCardProps) {
  const [showEditModal, setShowEditModal] = useState(false);

  const totalMonitors = watch.monitorCount;
  const hasRun = watch.passCount > 0 || watch.warnCount > 0 || watch.failCount > 0;

  // Derive health from actual monitor statuses, not potentially stale stored score
  const liveHealthScore = hasRun && totalMonitors > 0
    ? Math.round(((watch.passCount + watch.warnCount * 0.5) / totalMonitors) * 100)
    : watch.healthScore;

  const healthStatus: HealthStatus | null = hasRun && liveHealthScore != null
    ? healthStatusFromScore(liveHealthScore)
    : watch.healthScore != null ? healthStatusFromScore(watch.healthScore) : null;

  const healthColor = healthStatus
    ? HEALTH_STATUS_COLORS[healthStatus]
    : 'bg-[var(--overlay-medium)] text-[var(--muted)]';

  const watchTypeColor = WATCH_TYPE_COLORS[watch.watchType] || WATCH_TYPE_COLORS.custom_watch;

  const coveragePct = watch.coveragePct != null ? Math.round(watch.coveragePct * 100) : null;
  const failureGroups = watch.healthDetails?.failureGroups || [];

  return (
    <div
      className="group relative bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl p-4 hover:border-[var(--overlay-strong)] transition-all cursor-pointer"
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-3">
        {/* Left: Name + type + health */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-[14px] font-medium text-[var(--text)] truncate">{watch.name}</h3>
            {healthStatus && (
              <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', healthColor)}>
                {HEALTH_STATUS_LABELS[healthStatus]}
              </span>
            )}
            {!healthStatus && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)]">
                NEW
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
            <span className="flex items-center gap-1">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {cronToHuman(watch.schedule || '')}
            </span>
            <span>
              {totalMonitors} monitor{totalMonitors !== 1 ? 's' : ''}
              {policyMonitorCount > 0 && (
                <>
                  {' · '}
                  {overrideMonitorCount > 0 && (
                    <span className="text-amber-400">{overrideMonitorCount} overridden</span>
                  )}
                  {overrideMonitorCount > 0 && (policyMonitorCount - overrideMonitorCount) > 0 && ', '}
                  {(policyMonitorCount - overrideMonitorCount) > 0 && (
                    <span className="text-violet-400">{policyMonitorCount - overrideMonitorCount} SLA covered</span>
                  )}
                </>
              )}
            </span>
            {coveragePct != null && policyMonitorCount === 0 && (
              <span className="text-[var(--text-faint)]">{coveragePct}% coverage</span>
            )}
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
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

      {/* Health score bar */}
      {hasRun && totalMonitors > 0 && (
        <div className="flex items-center gap-2 mt-3 mb-1.5">
          <div className="flex-1 h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden">
            <div className="flex h-full">
              {watch.passCount > 0 && (
                <div className="bg-emerald-500/60 h-full" style={{ width: `${(watch.passCount / totalMonitors) * 100}%` }} />
              )}
              {watch.warnCount > 0 && (
                <div className="bg-amber-500/60 h-full" style={{ width: `${(watch.warnCount / totalMonitors) * 100}%` }} />
              )}
              {watch.failCount > 0 && (
                <div className="bg-red-500/60 h-full" style={{ width: `${(watch.failCount / totalMonitors) * 100}%` }} />
              )}
            </div>
          </div>
          <span className="text-[11px] text-[var(--muted)] shrink-0">
            {watch.failCount > 0 ? `${watch.failCount} failed` : `${watch.passCount}/${totalMonitors} passing`}
          </span>
        </div>
      )}

      {/* Failure groups (compact) */}
      {failureGroups.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1">
          {failureGroups.slice(0, 3).map((fg, i) => (
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

      {/* Bottom: Last run + anchor */}
      <div className="flex items-center gap-3 mt-1 text-[11px] text-[var(--text-faint)]">
        <span>Last run: {timeAgo(watch.lastRunAt)}</span>
        {watch.anchorFqn && (
          <span className="truncate max-w-[250px] font-mono" title={watch.anchorFqn}>
            {watch.anchorFqn}
          </span>
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
