'use client';

import { useEffect, useState, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { CategorySparklinePanel } from './CategorySparklinePanel';
import { usePipeline } from '@/contexts/PipelineContext';

const STATUS_STYLES: Record<string, { border: string; text: string; accent: string; badgeBg: string }> = {
  stable:   { border: 'border-emerald-500/30', text: 'text-emerald-500', accent: 'bg-emerald-500', badgeBg: 'bg-emerald-500/10' },
  healthy:  { border: 'border-emerald-500/30', text: 'text-emerald-500', accent: 'bg-emerald-500', badgeBg: 'bg-emerald-500/10' },
  warning:  { border: 'border-amber-500/30',   text: 'text-amber-500',   accent: 'bg-amber-500',   badgeBg: 'bg-amber-500/10' },
  degraded: { border: 'border-amber-500/30',   text: 'text-amber-500',   accent: 'bg-amber-500',   badgeBg: 'bg-amber-500/10' },
  drifting: { border: 'border-red-500/30',     text: 'text-red-500',     accent: 'bg-red-500',     badgeBg: 'bg-red-500/10' },
  down:     { border: 'border-red-500/30',     text: 'text-red-500',     accent: 'bg-red-500',     badgeBg: 'bg-red-500/10' },
  pending:  { border: 'border-[var(--subtle-border)]', text: 'text-[var(--muted)]', accent: 'bg-zinc-400', badgeBg: 'bg-zinc-500/10' },
};
const STATUS_LABELS: Record<string, string> = { stable: 'Stable', healthy: 'Healthy', warning: 'Warning', degraded: 'Degraded', drifting: 'Drifting', down: 'Down', pending: 'Pending' };

export function PipelineHealthTiles() {
  const { selectedPipelineId } = usePipeline();
  const [trendData, setTrendData] = useState<any | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedPipelineId) return;
    let active = true;
    fetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (active) setTrendData(d); })
      .catch(() => {});
    const t = setInterval(() => {
      fetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`)
        .then((r) => r.ok ? r.json() : null)
        .then((d) => { if (active) setTrendData(d); })
        .catch(() => {});
    }, 30000);
    return () => { active = false; clearInterval(t); };
  }, [selectedPipelineId]);

  const tools = useMemo(() => {
    if (!trendData?.pipelineHealth) return [];
    return Object.entries(trendData.pipelineHealth).map(([key, data]: any) => ({
      key, label: key.charAt(0).toUpperCase() + key.slice(1), ...data,
    }));
  }, [trendData]);

  if (tools.length === 0) return null;

  return (
    <div className="mb-4">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">Pipeline Health</div>
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        {tools.map((tool) => {
          const style = STATUS_STYLES[tool.status] || STATUS_STYLES.pending;
          const isExpanded = expanded === `pipeline-${tool.key}`;
          const passPct = tool.total > 0 ? (tool.passing / tool.total) * 100 : 0;
          return (
            <button key={tool.key} onClick={() => setExpanded(isExpanded ? null : `pipeline-${tool.key}`)}
              className={cn('rounded-xl border overflow-hidden text-left transition-all hover:shadow-md',
                isExpanded ? `${style.border} bg-[var(--surface)] shadow-sm` : 'border-[var(--subtle-border)] bg-[var(--surface)]')}>
              <div className={cn('h-1', style.accent, isExpanded ? 'opacity-100' : 'opacity-40')} />
              <div className="px-4 py-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wide">{tool.label}</span>
                  <span className={cn('text-[9px] font-medium px-1.5 py-0.5 rounded-full', style.badgeBg, style.text)}>
                    {STATUS_LABELS[tool.status] || tool.status}
                  </span>
                </div>
                <div className={cn('text-[22px] font-bold tabular-nums',
                  tool.failing > 0 ? 'text-red-500' : tool.warning > 0 ? 'text-amber-500' : 'text-emerald-500')}>
                  {tool.passing}<span className="text-[14px] font-normal text-[var(--muted)]">/{tool.total}</span>
                </div>
                <div className="h-1.5 rounded-full bg-[var(--overlay-bg)] mt-2 overflow-hidden">
                  <div className={cn('h-full rounded-full transition-all', style.accent)} style={{ width: `${passPct}%` }} />
                </div>
              </div>
            </button>
          );
        })}
      </div>
      {tools.map((tool) => {
        if (expanded !== `pipeline-${tool.key}`) return null;
        const style = STATUS_STYLES[tool.status] || STATUS_STYLES.pending;
        return (
          <div key={tool.key} className="mt-2">
            <CategorySparklinePanel label={tool.label} failingCount={tool.failing} monitors={tool.monitors} borderColor={style.border} />
          </div>
        );
      })}
    </div>
  );
}
