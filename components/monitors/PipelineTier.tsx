'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import type { PipelineToolStatus } from '@/types/monitors-summary';
import { PipelineToolDetailPanel } from './PipelineToolDetailPanel';
import { ToolIcon } from '@/components/icons/ToolIcon';

interface Props {
  tools: PipelineToolStatus[];
  loading: boolean;
  stackId: string;
}

const STATUS_COLOR: Record<string, string> = {
  PASS:      'text-emerald-500',
  WARN:      'text-amber-500',
  FAIL:      'text-red-500',
  ERROR:     'text-red-500',
  NEVER_RUN: 'text-[var(--muted)]',
};

const STATUS_ACCENT: Record<string, string> = {
  PASS:      'bg-emerald-500',
  WARN:      'bg-amber-500',
  FAIL:      'bg-red-500',
  ERROR:     'bg-red-500',
  NEVER_RUN: 'bg-zinc-500',
};

const STATUS_LABEL: Record<string, (t: PipelineToolStatus) => string> = {
  PASS:      () => 'healthy',
  WARN:      (t) => `${t.warnCount} warn`,
  FAIL:      (t) => `${t.failCount} fail`,
  ERROR:     (t) => `${t.failCount} error`,
  NEVER_RUN: () => 'never run',
};

function timeSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function PipelineTier({ tools, loading, stackId }: Props) {
  const [openTool, setOpenTool] = useState<PipelineToolStatus | null>(null);

  if (!loading && tools.length === 0) return null; // suppress section on empty

  return (
    <section className="mb-4">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold flex items-center justify-between">
        <span>Pipeline tier</span>
        {!loading && tools.length > 0 && (
          <span className="text-[10px] text-[var(--text-faint)] font-normal normal-case tracking-normal">
            {tools.length} tool{tools.length === 1 ? '' : 's'}
          </span>
        )}
      </div>
      {loading ? (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-16 rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
          {tools.map((tool) => (
            <button
              key={tool.toolType}
              onClick={() => setOpenTool(tool)}
              className="text-left rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] hover:border-[var(--border)] hover:bg-[var(--overlay-bg)] transition-colors overflow-hidden group"
              aria-label={`${tool.displayName}: ${STATUS_LABEL[tool.status](tool)}`}
            >
              <div className={cn('h-0.5', STATUS_ACCENT[tool.status])} />
              <div className="px-2.5 py-2.5 flex items-start gap-2">
                <ToolIcon toolType={tool.toolType} size={20} className="flex-shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] font-semibold truncate">{tool.displayName}</div>
                  <div className={cn('text-[11px] mt-0.5 font-medium', STATUS_COLOR[tool.status])}>
                    {STATUS_LABEL[tool.status](tool)}
                  </div>
                  {tool.lastRunAt && (
                    <div className="text-[10px] text-[var(--text-faint)] mt-0.5">{timeSince(tool.lastRunAt)}</div>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {openTool && (
        <PipelineToolDetailPanel
          tool={openTool}
          stackId={stackId}
          onClose={() => setOpenTool(null)}
        />
      )}
    </section>
  );
}
