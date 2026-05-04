'use client';

import { cn } from '@/lib/utils';
import type { IncidentSummary } from '@/types/incident';

interface Props {
  incidents: IncidentSummary[];   // active incidents (open + ack), already filtered
  monitoredAssetCount: number;
  blastRadius?: { dashboards: number; tables: number };
  updatedAt?: string;
}

function timeSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d`;
}

export function SummaryHero({ incidents, monitoredAssetCount, blastRadius, updatedAt }: Props) {
  // Hero counts use status='OPEN' AND not muted
  const open = incidents.filter((i) => i.status === 'OPEN' && !i.isMuted);
  const fail = open.filter((i) => i.severity === 'FAIL');
  const warn = open.filter((i) => i.severity === 'WARN');

  let tone: 'green' | 'amber' | 'red' = 'green';
  if (open.length === 0) tone = 'green';
  else if (fail.length > 0) tone = 'red';
  else tone = 'amber';

  const oldestMs = open.length > 0
    ? Math.max(...open.map((i) => Date.now() - new Date(i.openedAt).getTime()))
    : null;

  const styles = {
    green: 'from-emerald-500/12 to-emerald-500/[0.02] border-emerald-500/30 text-emerald-400',
    amber: 'from-amber-500/12  to-amber-500/[0.02]  border-amber-500/30  text-amber-400',
    red:   'from-red-500/12    to-red-500/[0.02]    border-red-500/30    text-red-400',
  } as const;

  const dotColor = { green: 'bg-emerald-500', amber: 'bg-amber-500', red: 'bg-red-500' }[tone];

  const headline =
    tone === 'green'
      ? `All systems healthy. ${monitoredAssetCount} asset${monitoredAssetCount === 1 ? '' : 's'} monitored.`
      : tone === 'amber'
        ? `${warn.length} warning${warn.length === 1 ? '' : 's'}.${blastRadius ? ` Affecting ${blastRadius.dashboards} dashboards.` : ''}`
        : `${fail.length} critical incident${fail.length === 1 ? '' : 's'}${warn.length > 0 ? ` · ${warn.length} warning` : ''}.${blastRadius ? ` Affecting ${blastRadius.dashboards} BI dashboards and ${blastRadius.tables} downstream tables.` : ''}${oldestMs ? ` Oldest ${formatMs(oldestMs)}.` : ''}`;

  return (
    <div className={cn('rounded-lg border bg-gradient-to-r px-5 py-4 mb-4', styles[tone])}>
      <div className="flex items-center gap-3">
        <div className={cn('w-2.5 h-2.5 rounded-full shadow', dotColor)} />
        <div className="flex-1">
          <div className="text-[14px] font-semibold">{headline}</div>
        </div>
        {updatedAt && (
          <div className="text-[10px] opacity-60">Updated {new Date(updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
        )}
      </div>
    </div>
  );
}

function formatMs(ms: number): string {
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
