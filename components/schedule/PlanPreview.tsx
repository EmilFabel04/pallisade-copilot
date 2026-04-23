'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import type { MonitoringPlanPreview, GroupPreview } from '@/types/health-watch';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface PlanPreviewProps {
  preview: MonitoringPlanPreview | null;
  monitorToggles: Record<string, boolean>;
  onToggleMonitor: (key: string) => void;
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Family badge colours
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Skeleton placeholders
// ---------------------------------------------------------------------------

function SkeletonBanner() {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 animate-pulse">
      <div className="h-4 w-64 rounded bg-[var(--border)] mb-2" />
      <div className="h-3 w-48 rounded bg-[var(--border)]" />
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 animate-pulse">
      <div className="flex items-center gap-3">
        <div className="h-5 w-24 rounded bg-[var(--border)]" />
        <div className="h-4 w-40 rounded bg-[var(--border)]" />
        <div className="ml-auto h-4 w-20 rounded bg-[var(--border)]" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Monitor Key Badge
// ---------------------------------------------------------------------------

const MONITOR_KEY_COLORS: Record<string, string> = {
  freshness: 'bg-blue-500/15 text-blue-400',
  volume: 'bg-emerald-500/15 text-emerald-400',
  schema: 'bg-purple-500/15 text-purple-400',
  row_count: 'bg-emerald-500/15 text-emerald-400',
  null_rate: 'bg-amber-500/15 text-amber-400',
  custom_sql: 'bg-cyan-500/15 text-cyan-400',
};

function MonitorKeyBadge({ monitorKey }: { monitorKey: string }) {
  const color = MONITOR_KEY_COLORS[monitorKey] || 'bg-[var(--overlay-medium)] text-[var(--muted)]';
  return (
    <span
      className={cn(
        'px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap',
        color,
      )}
    >
      {monitorKey}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Group Card
// ---------------------------------------------------------------------------

interface GroupCardProps {
  group: GroupPreview;
  groupIdx: number;
  expanded: boolean;
  onToggle: () => void;
  monitorToggles: Record<string, boolean>;
  onToggleMonitor: (key: string) => void;
}

function GroupCard({
  group,
  groupIdx,
  expanded,
  onToggle,
  monitorToggles,
  onToggleMonitor,
}: GroupCardProps) {
  const familyColor = FAMILY_COLORS[group.family] || 'bg-[var(--overlay-medium)] text-[var(--muted)]';
  const familyLabel = FAMILY_LABELS[group.family] || group.family;
  const coveragePct = Math.round(group.coverage_pct * 100);

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
      {/* Header */}
      <button
        type="button"
        className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-[var(--border)]/30 transition-colors"
        onClick={onToggle}
      >
        {/* Expand chevron */}
        <svg
          className={cn(
            'w-3.5 h-3.5 text-[var(--muted)] shrink-0 transition-transform',
            expanded && 'rotate-90',
          )}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>

        {/* Family badge */}
        <span
          className={cn(
            'px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap',
            familyColor,
          )}
        >
          {familyLabel}
        </span>

        {/* Anchor name */}
        <span className="text-[13px] font-medium text-[var(--text)] truncate">
          {group.anchor_name}
        </span>

        {/* Stats */}
        <div className="ml-auto flex items-center gap-3 shrink-0">
          <span className="text-[11px] text-[var(--muted)]">
            {group.node_count} nodes
          </span>
          <span className="text-[11px] text-[var(--muted)]">
            {group.monitor_count} monitors
          </span>
          <span
            className={cn(
              'px-1.5 py-0.5 rounded text-[10px] font-medium',
              coveragePct >= 80
                ? 'bg-emerald-500/15 text-emerald-400'
                : coveragePct >= 50
                  ? 'bg-amber-500/15 text-amber-400'
                  : 'bg-red-500/15 text-red-400',
            )}
          >
            {coveragePct}%
          </span>
        </div>
      </button>

      {/* Expanded body — recommendation list */}
      {expanded && (
        <div className="border-t border-[var(--border)] px-4 py-2 space-y-1">
          {group.recommendations.map((rec, monIdx) => {
            const toggleKey = `${groupIdx}:${monIdx}`;
            const checked = monitorToggles[toggleKey] ?? !rec.already_monitored;
            const disabled = rec.already_monitored;

            return (
              <label
                key={toggleKey}
                className={cn(
                  'flex items-center gap-2.5 py-1.5 px-1 rounded hover:bg-[var(--border)]/20 transition-colors cursor-pointer',
                  disabled && 'opacity-50 cursor-default',
                )}
              >
                {/* Checkbox */}
                <input
                  type="checkbox"
                  checked={disabled ? false : checked}
                  disabled={disabled}
                  onChange={() => {
                    if (!disabled) onToggleMonitor(toggleKey);
                  }}
                  className="accent-[var(--accent)] w-3.5 h-3.5 shrink-0"
                />

                {/* Monitor key badge */}
                <MonitorKeyBadge monitorKey={rec.monitor_key} />

                {/* Target FQN */}
                <span
                  className={cn(
                    'text-[11px] font-mono text-[var(--muted)] truncate max-w-[280px]',
                    disabled && 'line-through',
                  )}
                  title={rec.target_fqn}
                >
                  {rec.target_fqn}
                </span>

                {/* Reason or already-monitored label */}
                {disabled ? (
                  <span className="ml-auto text-[10px] text-amber-400/80 whitespace-nowrap">
                    Already monitored in another group
                  </span>
                ) : (
                  <span className="ml-auto text-[10px] text-[var(--muted)] truncate max-w-[200px]">
                    {rec.reason}
                  </span>
                )}
              </label>
            );
          })}

          {group.recommendations.length === 0 && (
            <p className="text-[11px] text-[var(--muted)] py-2">
              No monitor recommendations for this group.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PlanPreview (main export)
// ---------------------------------------------------------------------------

export function PlanPreview({
  preview,
  monitorToggles,
  onToggleMonitor,
  loading,
}: PlanPreviewProps) {
  const [expandedGroup, setExpandedGroup] = useState<number | null>(null);

  // ----- Loading state -----
  if (loading) {
    return (
      <div className="space-y-3">
        <SkeletonBanner />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  // ----- No preview -----
  if (!preview) {
    return (
      <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-center">
        <p className="text-[13px] text-[var(--muted)]">
          No monitoring plan preview available. Go back and select families to
          generate a plan.
        </p>
      </div>
    );
  }

  const enabledCount = Object.values(monitorToggles).filter(Boolean).length;
  const hasDedups = preview.dedup_count > 0;

  return (
    <div className="space-y-3">
      {/* ---- Summary banner ---- */}
      <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 space-y-1.5">
        <p className="text-[13px] text-[var(--text)]">
          Your selections{' '}
          <span className="text-[var(--muted)]">&rarr;</span>{' '}
          <span className="font-medium">
            {preview.raw_monitor_count} monitors
          </span>{' '}
          across{' '}
          <span className="font-medium">{preview.total_nodes} assets</span>
        </p>

        {hasDedups && (
          <p className="text-[13px] text-[var(--text)]">
            After dedup{' '}
            <span className="text-[var(--muted)]">&rarr;</span>{' '}
            <span className="font-medium text-emerald-400">
              {preview.total_monitors} unique monitors
            </span>{' '}
            in{' '}
            <span className="font-medium">
              {preview.groups.length} groups
            </span>
          </p>
        )}

        {hasDedups && (
          <p className="text-[11px] text-[var(--muted)]">
            {preview.dedup_count} duplicate monitor
            {preview.dedup_count !== 1 ? 's' : ''} removed where assets appear
            in multiple group scopes.
          </p>
        )}

        {!hasDedups && (
          <p className="text-[11px] text-[var(--muted)]">
            {preview.total_monitors} unique monitors in{' '}
            {preview.groups.length} group
            {preview.groups.length !== 1 ? 's' : ''} — no duplicates found.
          </p>
        )}
      </div>

      {/* ---- Warnings ---- */}
      {preview.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-1">
          {preview.warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2">
              <svg
                className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
              <span className="text-[11px] text-amber-400/90">{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* ---- Group cards ---- */}
      <div className="space-y-2">
        {preview.groups.map((group, idx) => (
          <GroupCard
            key={idx}
            group={group}
            groupIdx={idx}
            expanded={expandedGroup === idx}
            onToggle={() =>
              setExpandedGroup(expandedGroup === idx ? null : idx)
            }
            monitorToggles={monitorToggles}
            onToggleMonitor={onToggleMonitor}
          />
        ))}
      </div>
    </div>
  );
}
