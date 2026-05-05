'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { X, ExternalLink, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PIPELINE_TYPE_TO_FAMILY, TOOL_TYPE_BY_INTEGRATION_TYPE } from '@/lib/monitors/families';
import { ToolIcon } from '@/components/icons/ToolIcon';
import type { PipelineToolStatus } from '@/types/monitors-summary';

interface Props {
  tool: PipelineToolStatus;
  stackId: string;
  onClose: () => void;
}

interface MonitorRow {
  id: string;
  name: string;
  monitorType: string;
  lastStatus: string | null;
  lastRunAt: string | null;
  targetFqn: string | null;
}

export function PipelineToolDetailPanel({ tool, stackId, onClose }: Props) {
  const router = useRouter();
  const [monitors, setMonitors] = useState<MonitorRow[]>([]);
  const [loading, setLoading] = useState(true);

  // Close on ESC
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // Fetch monitors targeting this tool. /api/schedule/tasks already loads on the
  // page; if the tasks payload has integration.type, we filter; otherwise the
  // panel just shows aggregate stats with an empty monitor list.
  useEffect(() => {
    let active = true;
    fetch(`/api/schedule/tasks?stackId=${stackId}`)
      .then((r) => r.ok ? r.json() : { tasks: [] })
      .then((d) => {
        if (!active) return;
        const all: any[] = d.tasks || [];
        const filtered = all.filter((t) => {
          // Resolve integration.type (uppercase Prisma enum e.g. 'AIRFLOW') →
          // canonical lowercase tool key (e.g. 'airflow') using the same map
          // that health-summary and pipeline-status routes use.
          const integrationKey = t.integration?.type
            ? (TOOL_TYPE_BY_INTEGRATION_TYPE[t.integration.type] || t.integration.type.toLowerCase())
            : null;
          if (integrationKey && integrationKey === tool.toolType) return true;
          // Family match (e.g. tool.toolType === 'orchestration' and monitor is DAG_LAST_RUN)
          const family = PIPELINE_TYPE_TO_FAMILY[(t.monitorType || '').toUpperCase()];
          if (family && family === tool.toolType) return true;
          return false;
        });
        if (process.env.NODE_ENV !== 'production' && filtered.length === 0 && tool.monitorCount > 0) {
          console.debug('[PipelineToolDetailPanel] filter returned empty', {
            toolType: tool.toolType,
            monitorCount: tool.monitorCount,
            sampleTask: all[0],
          });
        }
        setMonitors(filtered as MonitorRow[]);
        setLoading(false);
      })
      .catch(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [stackId, tool.toolType]);

  const failures = monitors
    .filter((m) => {
      const s = (m.lastStatus || '').toUpperCase();
      return s === 'FAIL' || s === 'ERROR';
    })
    .slice(0, 5);

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        onTouchEnd={onClose}
        aria-hidden
      />
      <aside
        className="fixed right-0 top-0 bottom-0 w-[440px] max-w-[90vw] bg-[var(--bg)] border-l border-[var(--subtle-border)] z-50 flex flex-col"
        role="dialog"
        aria-label={`${tool.displayName} detail`}
      >
        <header className="flex items-center gap-3 px-4 py-3 border-b border-[var(--subtle-border)]">
          <ToolIcon toolType={tool.toolType} size={28} className="flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Pipeline tool</div>
            <div className="text-[14px] font-semibold truncate">{tool.displayName}</div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--surface)]" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Monitors" value={String(tool.monitorCount)} />
            <Stat label="Failing" value={String(tool.failCount)} tone={tool.failCount > 0 ? 'red' : undefined} />
            <Stat label="Warning" value={String(tool.warnCount)} tone={tool.warnCount > 0 ? 'amber' : undefined} />
          </div>

          <section>
            <div className="text-[11px] uppercase tracking-wide text-[var(--muted)] mb-2">Recent failures</div>
            {loading ? (
              <div className="h-12 animate-pulse rounded bg-[var(--surface)]" />
            ) : failures.length === 0 ? (
              <div className="text-[12px] text-[var(--muted)]">No recent failures.</div>
            ) : (
              <ul className="space-y-1.5">
                {failures.map((m) => (
                  <li key={m.id} className="flex items-center gap-2 text-[12px]">
                    <AlertCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />
                    <span className="truncate">{m.name}</span>
                    <span className="text-[10px] text-[var(--text-faint)] shrink-0">{m.targetFqn || m.monitorType}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <div className="text-[11px] uppercase tracking-wide text-[var(--muted)] mb-2">Monitors</div>
            {loading ? (
              <div className="h-20 animate-pulse rounded bg-[var(--surface)]" />
            ) : monitors.length === 0 ? (
              <div className="text-[12px] text-[var(--muted)]">No monitors target this tool yet.</div>
            ) : (
              <ul className="space-y-1">
                {monitors.map((m) => {
                  const s = (m.lastStatus || '').toUpperCase();
                  const badge = s === 'FAIL' || s === 'ERROR'
                    ? 'bg-red-500/10 text-red-500'
                    : s === 'WARN'
                      ? 'bg-amber-500/10 text-amber-500'
                      : 'bg-[var(--overlay-bg)] text-[var(--muted)]';
                  return (
                    <li key={m.id} className="flex items-center justify-between text-[12px] py-0.5">
                      <span className="truncate">{m.name}</span>
                      <span className={cn('text-[10px] px-1.5 py-0.5 rounded', badge)}>
                        {m.lastStatus || 'NEVER RUN'}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>

        <footer className="border-t border-[var(--subtle-border)] px-4 py-3">
          <button
            onClick={() => router.push(`/dashboard/monitors?tab=pipeline&tool=${encodeURIComponent(tool.toolType)}`)}
            className="w-full flex items-center justify-center gap-1.5 text-[12px] py-2 rounded border border-[var(--subtle-border)] hover:bg-[var(--surface)]"
          >
            View all in Pipeline Monitors <ExternalLink className="w-3 h-3" />
          </button>
        </footer>
      </aside>
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'red' | 'amber' }) {
  const color = tone === 'red' ? 'text-red-500' : tone === 'amber' ? 'text-amber-500' : 'text-[var(--text)]';
  return (
    <div className="rounded border border-[var(--subtle-border)] bg-[var(--surface)] px-2.5 py-2">
      <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">{label}</div>
      <div className={cn('text-[16px] font-semibold mt-0.5', color)}>{value}</div>
    </div>
  );
}
