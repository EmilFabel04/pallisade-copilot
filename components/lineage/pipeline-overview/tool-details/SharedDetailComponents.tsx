'use client';

import React, { useState } from 'react';
import type { ToolDetailItem, ToolConnection, HealthSummary } from '../types';
import { HEALTH_COLORS, COVERAGE_GAP_LABELS } from '../types';

// ─── Collapsible Section ──────────────────────────────────────────────

export function Section({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-[var(--subtle-border)] pt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full group"
      >
        <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide group-hover:text-[var(--text-tertiary)] transition-colors">
          {title}
        </span>
        <div className="flex items-center gap-1.5">
          {count !== undefined && (
            <span className="text-[10px] text-[var(--text-faint)]">{count}</span>
          )}
          <svg
            className={`w-3.5 h-3.5 text-[var(--text-faint)] transition-transform ${open ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

// ─── Health Row ───────────────────────────────────────────────────────

export function HealthRow({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2 flex-1">
        <span className="text-[12px]" style={{ color }}>{label}</span>
        <div className="flex-1 h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden">
          <div className="h-full rounded-full" style={{ backgroundColor: color, width: `${pct}%` }} />
        </div>
      </div>
      <span className="text-[12px] text-[var(--text)] ml-2 w-10 text-right">{pct}%</span>
    </div>
  );
}

// ─── Health Summary Display ───────────────────────────────────────────

export function HealthSummaryDisplay({ summary }: { summary: HealthSummary }) {
  const total = summary.healthy + summary.degraded + summary.failing + summary.stale + summary.unknown;
  if (total === 0) {
    return <p className="text-[12px] text-[var(--muted)] italic">No health data available</p>;
  }
  const pct = (n: number) => Math.round((n / total) * 100);
  return (
    <div className="space-y-1.5">
      {summary.healthy > 0 && <HealthRow label="Healthy" pct={pct(summary.healthy)} color="#10B981" />}
      {summary.degraded > 0 && <HealthRow label="Degraded" pct={pct(summary.degraded)} color="#F59E0B" />}
      {summary.failing > 0 && <HealthRow label="Failing" pct={pct(summary.failing)} color="#EF4444" />}
      {summary.stale > 0 && <HealthRow label="Stale" pct={pct(summary.stale)} color="#F59E0B" />}
      {summary.unknown > 0 && <HealthRow label="Unknown" pct={pct(summary.unknown)} color="#6B7280" />}
    </div>
  );
}

// ─── Empty State ──────────────────────────────────────────────────────

export function EmptyState({
  message,
  hint,
}: {
  message: string;
  hint?: string;
}) {
  return (
    <div className="py-8 text-center">
      <p className="text-[13px] text-[var(--muted)]">{message}</p>
      {hint && (
        <p className="text-[11px] text-[var(--text-faint)] mt-1">{hint}</p>
      )}
    </div>
  );
}

// ─── Loading State ────────────────────────────────────────────────────

export function LoadingState() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="flex gap-1 p-0.5 rounded-lg bg-[var(--overlay-faint)]">
        {[1, 2, 3].map(i => (
          <div key={i} className="flex-1 h-8 rounded-md bg-[var(--overlay-bg)]" />
        ))}
      </div>
      <div className="space-y-2">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="h-10 rounded bg-[var(--overlay-bg)]" />
        ))}
      </div>
    </div>
  );
}

// ─── Item Row (single detail item) ───────────────────────────────────

export function ItemRow({
  item,
  laneColor,
  rightLabel,
}: {
  item: ToolDetailItem;
  laneColor?: string;
  rightLabel?: string;
}) {
  const healthColor = HEALTH_COLORS[item.healthStatus || 'unknown'] || '#6B7280';
  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{ backgroundColor: laneColor || healthColor }}
      />
      <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1" title={item.fqn}>
        {item.name}
      </span>
      {rightLabel && (
        <span className="text-[9px] text-[var(--muted)] uppercase shrink-0">{rightLabel}</span>
      )}
    </div>
  );
}

// ─── Item List (flat list with optional max) ─────────────────────────

export function ItemList({
  items,
  laneColor,
  labelFn,
  maxItems = 50,
}: {
  items: ToolDetailItem[];
  laneColor?: string;
  labelFn?: (item: ToolDetailItem) => string;
  maxItems?: number;
}) {
  if (items.length === 0) {
    return <EmptyState message="No items discovered" hint="Run lineage extraction to discover assets" />;
  }
  const shown = items.slice(0, maxItems);
  return (
    <div className="space-y-1.5">
      {shown.map(item => (
        <ItemRow
          key={item.id}
          item={item}
          laneColor={laneColor}
          rightLabel={labelFn ? labelFn(item) : item.canonicalType}
        />
      ))}
      {items.length > maxItems && (
        <p className="text-[11px] text-[var(--muted)] text-center">
          +{items.length - maxItems} more
        </p>
      )}
    </div>
  );
}

// ─── Grouped Item List ───────────────────────────────────────────────

export function GroupedItemList({
  items,
  groupKey = 'container',
  laneColor,
  labelFn,
  maxPerGroup = 20,
}: {
  items: ToolDetailItem[];
  groupKey?: keyof ToolDetailItem;
  laneColor?: string;
  labelFn?: (item: ToolDetailItem) => string;
  maxPerGroup?: number;
}) {
  if (items.length === 0) {
    return <EmptyState message="No items discovered" hint="Run lineage extraction to discover assets" />;
  }

  const groups: Record<string, ToolDetailItem[]> = {};
  for (const item of items) {
    const key = String(item[groupKey] || 'Other');
    if (!groups[key]) groups[key] = [];
    groups[key].push(item);
  }

  return (
    <div className="space-y-3">
      {Object.entries(groups).map(([group, groupItems]) => (
        <Section key={group} title={group} count={groupItems.length} defaultOpen={Object.keys(groups).length <= 3}>
          <ItemList items={groupItems} laneColor={laneColor} labelFn={labelFn} maxItems={maxPerGroup} />
        </Section>
      ))}
    </div>
  );
}

// ─── Card Item (richer display for connectors, DAGs, etc.) ───────────

export function CardItem({
  item,
  children,
}: {
  item: ToolDetailItem;
  children?: React.ReactNode;
}) {
  const healthColor = HEALTH_COLORS[item.healthStatus || 'unknown'] || '#6B7280';
  return (
    <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
      <div className="flex items-center gap-2 mb-1.5">
        <div
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: healthColor }}
        />
        <span className="text-[13px] text-[var(--text)] font-medium truncate" title={item.fqn}>
          {item.name}
        </span>
        {item.itemCount !== undefined && (
          <span className="text-[10px] text-[var(--muted)] ml-auto shrink-0">
            {item.itemCount} items
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

// ─── Connection List ─────────────────────────────────────────────────

export function ConnectionList({
  connections,
  direction,
}: {
  connections: ToolConnection[];
  direction: 'upstream' | 'downstream';
}) {
  if (connections.length === 0) {
    return <p className="text-[12px] text-[var(--muted)] italic">No {direction} connections</p>;
  }
  return (
    <div className="space-y-1.5">
      {connections.map(conn => (
        <div key={conn.toolId} className="flex items-center justify-between px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
          <span className="text-[12px] text-[var(--text)] font-mono truncate">
            {direction === 'upstream' ? '← ' : '→ '}{conn.name}
          </span>
          <span className="text-[10px] text-[var(--muted)] shrink-0 ml-2">
            {conn.edgeCount} flow{conn.edgeCount !== 1 ? 's' : ''}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── Coverage Gaps ───────────────────────────────────────────────────

export function CoverageGapsList({ gaps }: { gaps: string[] }) {
  if (gaps.length === 0) {
    return (
      <div className="flex items-center gap-2 px-3 py-3 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
        <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span className="text-[13px] text-emerald-400 font-medium">Full coverage</span>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 mb-2">
        <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
        </svg>
        <span className="text-[13px] text-amber-400 font-medium">
          {gaps.length} coverage gap{gaps.length !== 1 ? 's' : ''}
        </span>
      </div>
      {gaps.map(gap => (
        <div key={gap} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/10">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
          <span className="text-[12px] text-[var(--text)]">{COVERAGE_GAP_LABELS[gap] || gap}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Format Relative Time ────────────────────────────────────────────

export function formatRelativeTime(isoStr: string): string {
  try {
    const date = new Date(isoStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    return `${diffDays}d ago`;
  } catch {
    return isoStr;
  }
}
