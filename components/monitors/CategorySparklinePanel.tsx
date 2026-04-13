'use client';

import { cn } from '@/lib/utils';
import { SparklineChart } from './SparklineChart';

interface MonitorTrend {
  id: string;
  name: string;
  targetFqn: string;
  latestStatus: string | null;
  latestValue: number | null;
  baselineMean: number | null;
  pctChange: number | null;
  runs: Array<{ value: number | null; status: string; at: string }>;
}

interface CategorySparklinePanelProps {
  label: string;
  failingCount: number;
  monitors: MonitorTrend[];
  borderColor?: string;
  onRunAnalysis?: () => void;
}

const STATUS_COLORS: Record<string, { bg: string; text: string; line: string }> = {
  PASS: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', line: '#34d399' },
  WARN: { bg: 'bg-amber-500/10', text: 'text-amber-400', line: '#fbbf24' },
  FAIL: { bg: 'bg-red-500/10', text: 'text-red-400', line: '#f87171' },
  ERROR: { bg: 'bg-red-500/10', text: 'text-red-400', line: '#f87171' },
};

function formatValue(val: number | null): string {
  if (val === null) return '—';
  if (Math.abs(val) >= 1000) return `${(val / 1000).toFixed(1)}k`;
  if (Number.isInteger(val)) return val.toString();
  return val.toFixed(1);
}

export function CategorySparklinePanel({
  label,
  failingCount,
  monitors,
  borderColor = 'border-[var(--subtle-border)]',
  onRunAnalysis,
}: CategorySparklinePanelProps) {
  return (
    <div className={cn('rounded-xl border bg-[var(--surface)] p-4', borderColor)}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-[var(--text)]">{label}</span>
          {failingCount > 0 && (
            <span className="text-[10px] text-red-400 font-medium">{failingCount} failing</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-[var(--muted)]">Last 30 runs</span>
          {onRunAnalysis && (
            <button
              onClick={onRunAnalysis}
              className="text-[10px] font-medium text-[var(--accent)] bg-[var(--accent)]/10 px-2 py-0.5 rounded hover:bg-[var(--accent)]/20 transition-colors"
            >
              Run Analysis
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {monitors.map((m) => {
          const status = (m.latestStatus || '').toUpperCase();
          const colors = STATUS_COLORS[status] || STATUS_COLORS.PASS;
          const values = m.runs.map((r) => r.value);

          return (
            <div key={m.id} className="bg-[var(--overlay-bg)] rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-medium text-[var(--text)] truncate">{m.name}</span>
                <span className={cn('text-[9px] font-medium px-1.5 py-0.5 rounded', colors.bg, colors.text)}>
                  {status || 'PENDING'}
                </span>
              </div>

              <SparklineChart values={values} color={colors.line} />

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

      {monitors.length === 0 && (
        <p className="text-[11px] text-[var(--muted)] text-center py-4">No run data yet</p>
      )}
    </div>
  );
}
