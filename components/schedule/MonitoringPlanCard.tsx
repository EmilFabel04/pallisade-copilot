'use client';

import { cn } from '@/lib/utils';
import type { MonitoringPlanSummary, HealthStatus } from '@/types/health-watch';
import {
  healthStatusFromScore,
  HEALTH_STATUS_COLORS,
  HEALTH_STATUS_LABELS,
} from '@/types/health-watch';

interface MonitoringPlanCardProps {
  plan: MonitoringPlanSummary;
  onClick: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRunAll: () => void;
}

const MODE_COLORS: Record<string, string> = {
  recommended: 'bg-blue-500/15 text-blue-400',
  manual: 'bg-white/10 text-white/50',
};

const SCOPE_TYPE_LABELS: Record<string, string> = {
  pipeline: 'Pipeline',
  stream: 'Stream',
  asset: 'Asset',
  tool: 'Tool',
};

const FAMILY_COLORS: Record<string, string> = {
  pipeline_health: 'bg-blue-500/15 text-blue-400',
  data_drift: 'bg-orange-500/15 text-orange-400',
  ingestion_reliability: 'bg-emerald-500/15 text-emerald-400',
  bi_reliability: 'bg-purple-500/15 text-purple-400',
  model_quality: 'bg-amber-500/15 text-amber-400',
  full_coverage: 'bg-cyan-500/15 text-cyan-400',
};

const FAMILY_LABELS: Record<string, string> = {
  pipeline_health: 'Pipeline Health',
  data_drift: 'Data Drift',
  ingestion_reliability: 'Ingestion',
  bi_reliability: 'BI Reliability',
  model_quality: 'Model Quality',
  full_coverage: 'Full Coverage',
};

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

export function MonitoringPlanCard({
  plan,
  onClick,
  onToggleEnabled,
  onRunAll,
}: MonitoringPlanCardProps) {
  const healthStatus: HealthStatus | null =
    plan.healthScore != null ? healthStatusFromScore(plan.healthScore) : null;

  const healthColor = healthStatus
    ? HEALTH_STATUS_COLORS[healthStatus]
    : 'bg-[var(--overlay-medium)] text-[var(--muted)]';

  const coveragePct =
    plan.coveragePct != null ? Math.round(plan.coveragePct * 100) : null;

  const groupCount = plan.monitorGroups?.length ?? 0;
  const totalMonitors = plan.totalMonitors;

  return (
    <div
      className="group relative bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl p-4 hover:border-[var(--overlay-strong)] transition-all cursor-pointer"
      onClick={onClick}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {/* Plan icon */}
            <svg
              className="w-3.5 h-3.5 text-[var(--accent)] shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2"
              />
            </svg>
            <h3 className="text-[14px] font-medium text-[var(--text)] truncate">
              {plan.name}
            </h3>
            <span
              className={cn(
                'px-1.5 py-0.5 rounded text-[10px] font-medium',
                MODE_COLORS[plan.mode] || MODE_COLORS.manual
              )}
            >
              {plan.mode === 'recommended' ? 'Recommended' : 'Manual'}
            </span>
            {healthStatus && (
              <span
                className={cn(
                  'px-1.5 py-0.5 rounded text-[10px] font-medium',
                  healthColor
                )}
              >
                {HEALTH_STATUS_LABELS[healthStatus]}
              </span>
            )}
            {!healthStatus && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)]">
                NEW
              </span>
            )}
          </div>
        </div>

        {/* Right: Actions */}
        <div
          className="flex items-center gap-2"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={onRunAll}
            className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors opacity-0 group-hover:opacity-100"
            title="Run all monitors"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </button>
          <button
            onClick={() => onToggleEnabled(!plan.enabled)}
            className={cn(
              'relative w-8 h-[18px] rounded-full transition-colors',
              plan.enabled
                ? 'bg-emerald-500/40'
                : 'bg-[var(--overlay-medium)]'
            )}
          >
            <div
              className={cn(
                'absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform',
                plan.enabled ? 'left-[16px]' : 'left-[2px]'
              )}
            />
          </button>
        </div>
      </div>

      {/* Metrics row */}
      <div className="flex items-center gap-4 mt-2 text-[13px]">
        <div className="flex items-center gap-1">
          <span className="text-[var(--muted)]">Groups</span>
          <span className="text-[var(--text)] font-medium tabular-nums">
            {groupCount}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[var(--muted)]">Monitors</span>
          <span className="text-[var(--text)] font-medium tabular-nums">
            {totalMonitors}
          </span>
        </div>
        {coveragePct != null && (
          <div className="flex items-center gap-1">
            <span className="text-[var(--muted)]">Coverage</span>
            <span className="text-[var(--text)] font-medium tabular-nums">
              {coveragePct}%
            </span>
          </div>
        )}
        {plan.healthScore != null && (
          <div className="flex items-center gap-1">
            <span className="text-[var(--muted)]">Health</span>
            <span className="text-[var(--text)] font-medium tabular-nums">
              {Math.round(plan.healthScore)}
            </span>
          </div>
        )}
      </div>

      {/* Health bar */}
      <div className="mt-3">
        {totalMonitors > 0 ? (
          <div className="flex items-center gap-2 mb-1.5">
            <div className="flex-1 h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden">
              <div className="flex h-full">
                {plan.passCount > 0 && (
                  <div
                    className="bg-emerald-500/60 h-full"
                    style={{
                      width: `${(plan.passCount / totalMonitors) * 100}%`,
                    }}
                  />
                )}
                {plan.warnCount > 0 && (
                  <div
                    className="bg-amber-500/60 h-full"
                    style={{
                      width: `${(plan.warnCount / totalMonitors) * 100}%`,
                    }}
                  />
                )}
                {plan.failCount > 0 && (
                  <div
                    className="bg-red-500/60 h-full"
                    style={{
                      width: `${(plan.failCount / totalMonitors) * 100}%`,
                    }}
                  />
                )}
              </div>
            </div>
            <span className="text-[11px] text-[var(--muted)] shrink-0 tabular-nums">
              {plan.passCount}/{totalMonitors} passing
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-2 mb-1.5">
            <div className="flex-1 h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden" />
            <span className="text-[11px] text-[var(--muted)] shrink-0">
              No monitors
            </span>
          </div>
        )}
      </div>

      {/* Family tags */}
      {plan.families.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1">
          {plan.families.map((family) => (
            <span
              key={family}
              className={cn(
                'px-1.5 py-0.5 rounded text-[10px] font-medium',
                FAMILY_COLORS[family] || 'bg-white/10 text-white/50'
              )}
            >
              {FAMILY_LABELS[family] || family.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center gap-3 mt-2 text-[11px] text-[var(--text-faint)]">
        <span>Aggregated: {timeAgo(plan.lastAggregatedAt)}</span>
        <span
          className={cn(
            'px-1.5 py-0.5 rounded text-[10px] font-medium',
            'bg-[var(--overlay-medium)] text-[var(--muted)]'
          )}
        >
          {SCOPE_TYPE_LABELS[plan.scopeType] || plan.scopeType}
        </span>
        {plan.anchorFqn && (
          <span
            className="truncate max-w-[250px] font-mono"
            title={plan.anchorFqn}
          >
            {plan.anchorFqn}
          </span>
        )}
      </div>
    </div>
  );
}
