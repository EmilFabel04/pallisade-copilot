'use client';

import { useState } from 'react';
import { Settings } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { MonitoringPlanSummary, HealthStatus } from '@/types/health-watch';
import {
  healthStatusFromScore,
  HEALTH_STATUS_COLORS,
  HEALTH_STATUS_LABELS,
} from '@/types/health-watch';
import { WatchEditModal } from './WatchEditModal';

interface MonitoringPlanCardProps {
  plan: MonitoringPlanSummary;
  onClick: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onRunAll: () => void;
  onDelete?: () => void;
  /** Number of monitors with policy coverage (0 = no policies) */
  policyMonitorCount?: number;
  /** Number of monitors with overrides */
  overrideMonitorCount?: number;
}

const MODE_COLORS: Record<string, string> = {
  recommended: 'bg-blue-500/15 text-blue-400',
  manual: 'bg-[var(--overlay-medium)] text-[var(--muted)]',
};

const SCOPE_TYPE_LABELS: Record<string, string> = {
  pipeline: 'Pipeline',
  stream: 'Stream',
  asset: 'Asset',
  tool: 'Tool',
  custom: 'Multi-Select',
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

export function MonitoringPlanCard({
  plan,
  onClick,
  onToggleEnabled,
  onRunAll,
  onDelete,
  policyMonitorCount = 0,
  overrideMonitorCount = 0,
}: MonitoringPlanCardProps) {
  const [showEditModal, setShowEditModal] = useState(false);
  const hasRun = plan.passCount > 0 || plan.warnCount > 0 || plan.failCount > 0 || plan.errorCount > 0;

  const healthStatus: HealthStatus | null =
    hasRun && plan.healthScore != null ? healthStatusFromScore(plan.healthScore) : null;

  const healthColor = healthStatus
    ? HEALTH_STATUS_COLORS[healthStatus]
    : 'bg-[var(--overlay-medium)] text-[var(--muted)]';

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
          {onDelete && (
            <button
              onClick={onDelete}
              className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-red-400 hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
              title="Delete plan"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          )}
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
            onClick={() => setShowEditModal(true)}
            className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors opacity-0 group-hover:opacity-100"
            title="Edit plan settings"
          >
            <Settings size={14} />
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
          <span className="text-[var(--muted)]">Monitors</span>
          <span className="text-[var(--text)] font-medium tabular-nums">
            {totalMonitors}
          </span>
        </div>
        {hasRun && plan.healthScore != null && (
          <div className="flex items-center gap-1">
            <span className="text-[var(--muted)]">Health</span>
            <span className="text-[var(--text)] font-medium tabular-nums">
              {Math.round(plan.healthScore)}
            </span>
          </div>
        )}
        {policyMonitorCount > 0 && (
          <div className="flex items-center gap-1">
            <span
              className={cn(
                'px-1.5 py-0.5 rounded text-[10px] font-medium',
                overrideMonitorCount > 0
                  ? 'bg-amber-500/15 text-amber-400'
                  : 'bg-violet-500/15 text-violet-400'
              )}
            >
              {overrideMonitorCount > 0
                ? `${overrideMonitorCount} override${overrideMonitorCount !== 1 ? 's' : ''}`
                : `${policyMonitorCount} policy-covered`}
            </span>
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="mt-3">
        {totalMonitors > 0 && hasRun ? (
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
                {(plan.failCount + plan.errorCount) > 0 && (
                  <div
                    className="bg-red-500/60 h-full"
                    style={{
                      width: `${((plan.failCount + plan.errorCount) / totalMonitors) * 100}%`,
                    }}
                  />
                )}
              </div>
            </div>
            <span className="text-[11px] text-[var(--muted)] shrink-0 tabular-nums">
              {plan.passCount > 0 && <span className="text-emerald-400">{plan.passCount} passed</span>}
              {plan.passCount > 0 && (plan.failCount + plan.errorCount + plan.warnCount) > 0 && ' · '}
              {(plan.failCount + plan.errorCount) > 0 && <span className="text-red-400">{plan.failCount + plan.errorCount} failed</span>}
              {(plan.failCount + plan.errorCount) > 0 && plan.warnCount > 0 && ' · '}
              {plan.warnCount > 0 && <span className="text-amber-400">{plan.warnCount} warn</span>}
            </span>
          </div>
        ) : totalMonitors > 0 ? (
          <div className="flex items-center gap-2 mb-1.5">
            <div className="flex-1 h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden" />
            <span className="text-[11px] text-[var(--muted)] shrink-0">
              Not yet run
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
                FAMILY_COLORS[family] || 'bg-[var(--overlay-medium)] text-[var(--muted)]'
              )}
            >
              {FAMILY_LABELS[family] || family.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center gap-3 mt-2 text-[11px] text-[var(--text-faint)]">
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

      {/* Edit modal */}
      {showEditModal && (
        <WatchEditModal
          watch={{
            id: plan.id,
            name: plan.name,
            schedule: plan.schedule,
            timezone: plan.timezone,
            alertChannels: plan.alertChannels || [],
            alertOnStatus: plan.alertOnStatus || [],
            enabled: plan.enabled,
          }}
          onSave={async (data: Record<string, any>) => {
            await fetch(`/api/schedule/plans/${plan.id}`, {
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
