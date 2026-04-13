'use client';

import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { SparklineChart } from './SparklineChart';

interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  category: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}

interface AssetHealth {
  name: string;
  fqn: string;
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: MonitorTrend[];
}

interface AssetHealthRowProps {
  asset: AssetHealth;
  expanded: boolean;
  onToggle: () => void;
  activeCategories: Set<string>;
  onRunAnalysis?: () => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  freshness: 'Fresh',
  volume: 'Vol',
  quality: 'Qual',
  schema: 'Schema',
  anomaly: 'Anom',
  uniqueness: 'Uniq',
};

const STATUS_DOT: Record<string, string> = {
  PASS: 'bg-emerald-500',
  WARN: 'bg-amber-500',
  FAIL: 'bg-red-500',
  ERROR: 'bg-red-500',
};

const SPARKLINE_COLORS: Record<string, string> = {
  PASS: '#34d399',
  WARN: '#fbbf24',
  FAIL: '#f87171',
  ERROR: '#f87171',
};

function formatValue(val: number | null): string {
  if (val === null) return '\u2014';
  if (Math.abs(val) >= 1000) return `${(val / 1000).toFixed(1)}k`;
  if (Number.isInteger(val)) return val.toString();
  return val.toFixed(1);
}

export function AssetHealthRow({ asset, expanded, onToggle, activeCategories, onRunAnalysis }: AssetHealthRowProps) {
  // Group monitors by category for badge display
  const byCategory = new Map<string, { status: string; count: number }>();
  for (const m of asset.monitors) {
    if (activeCategories.size > 0 && !activeCategories.has(m.category)) continue;
    const existing = byCategory.get(m.category);
    const s = (m.latestStatus || '').toUpperCase();
    if (!existing) {
      byCategory.set(m.category, { status: s || 'PENDING', count: 1 });
    } else {
      existing.count++;
      if (s === 'FAIL' || s === 'ERROR') existing.status = 'FAIL';
      else if (s === 'WARN' && existing.status === 'PASS') existing.status = 'WARN';
    }
  }

  const filteredMonitors = activeCategories.size > 0
    ? asset.monitors.filter((m) => activeCategories.has(m.category))
    : asset.monitors;

  const passPct = asset.total > 0 ? (asset.passing / asset.total) * 100 : 0;

  return (
    <div className="rounded-xl border border-[var(--subtle-border)] bg-[var(--surface)] overflow-hidden transition-all">
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-[var(--hover-bg)] transition-colors"
      >
        <ChevronRight className={cn(
          'w-4 h-4 text-[var(--muted)] transition-transform shrink-0',
          expanded && 'rotate-90',
        )} />

        <div className="flex-1 min-w-0 text-left">
          <div className="text-[13px] font-medium text-[var(--text)] truncate">{asset.name}</div>
          <div className="text-[10px] text-[var(--text-faint)] font-mono truncate">{asset.fqn}</div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {Array.from(byCategory.entries()).map(([cat, info]) => (
            <div key={cat} className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-[var(--overlay-bg)]">
              <div className={cn('w-1.5 h-1.5 rounded-full', STATUS_DOT[info.status] || 'bg-zinc-400')} />
              <span className="text-[9px] text-[var(--muted)] font-medium">{CATEGORY_LABELS[cat] || cat}</span>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2 shrink-0 w-24">
          <div className="flex-1">
            <div className="h-1.5 rounded-full bg-[var(--overlay-bg)] overflow-hidden">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  asset.failing > 0 ? 'bg-red-500' : asset.warning > 0 ? 'bg-amber-500' : 'bg-emerald-500',
                )}
                style={{ width: `${passPct}%` }}
              />
            </div>
          </div>
          <span className={cn(
            'text-[12px] font-semibold tabular-nums',
            asset.failing > 0 ? 'text-red-500' : asset.warning > 0 ? 'text-amber-500' : 'text-emerald-500',
          )}>
            {asset.passing}/{asset.total}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-[var(--subtle-border)]">
          <div className="flex items-center justify-between pt-3 mb-3">
            <span className="text-[11px] text-[var(--muted)]">Last 30 runs</span>
            {onRunAnalysis && (
              <button
                onClick={(e) => { e.stopPropagation(); onRunAnalysis(); }}
                className="text-[10px] font-medium text-[var(--accent)] bg-[var(--accent)]/10 px-2 py-0.5 rounded hover:bg-[var(--accent)]/20 transition-colors"
              >
                Run Analysis
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {filteredMonitors.map((m) => {
              const status = (m.latestStatus || '').toUpperCase();
              const lineColor = SPARKLINE_COLORS[status] || '#34d399';
              const values = m.runs.map((r) => r.value);
              const catLabel = CATEGORY_LABELS[m.category] || m.category;

              return (
                <div key={m.id} className="bg-[var(--overlay-bg)] rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[9px] text-[var(--muted)] font-medium uppercase">{catLabel}</span>
                      <span className="text-[11px] font-medium text-[var(--text)] truncate">{m.name.split('\u2014').pop()?.trim() || m.name}</span>
                    </div>
                    <span className={cn(
                      'text-[9px] font-medium px-1.5 py-0.5 rounded shrink-0',
                      status === 'PASS' ? 'bg-emerald-500/10 text-emerald-400' :
                      status === 'WARN' ? 'bg-amber-500/10 text-amber-400' :
                      status === 'FAIL' || status === 'ERROR' ? 'bg-red-500/10 text-red-400' :
                      'bg-zinc-500/10 text-[var(--muted)]',
                    )}>
                      {status || 'PENDING'}
                    </span>
                  </div>
                  <SparklineChart values={values} color={lineColor} />
                  <div className="flex items-center justify-between mt-1 text-[9px] text-[var(--muted)]">
                    <span>
                      {formatValue(m.latestValue)}
                      {m.baselineMean !== null && (
                        <span className="text-[var(--text-faint)]"> (avg {formatValue(m.baselineMean)})</span>
                      )}
                    </span>
                    {m.pctChange !== null && (
                      <span className={m.pctChange >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                        {m.pctChange >= 0 ? '+' : ''}{m.pctChange}%
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {filteredMonitors.length === 0 && (
            <p className="text-[11px] text-[var(--muted)] text-center py-4">No monitors match the selected filters</p>
          )}
        </div>
      )}
    </div>
  );
}
