'use client';

import { cn } from '@/lib/utils';
import type { IncidentSummary } from '@/types/incident';
import type { MonitorHealthSummary } from '@/types/monitors-summary';
import {
  selectHeroTone,
  buildHeadline,
  buildSubline,
} from './SummaryHero.helpers';

export type { HeroTone } from './SummaryHero.helpers';

interface Props {
  health: MonitorHealthSummary;
  incidents: IncidentSummary[];   // active incidents (open + ack), already filtered
  blastRadius?: { dashboards: number; tables: number };
}

export function SummaryHero({ health, incidents, blastRadius }: Props) {
  const open = incidents.filter((i) => i.status === 'OPEN' && !i.isMuted);
  const failIncidentCount = open.filter((i) => i.severity === 'FAIL').length;
  const warnIncidentCount = open.filter((i) => i.severity === 'WARN').length;

  const tone = selectHeroTone(health, failIncidentCount, warnIncidentCount);

  const oldestOpenMs = open.length > 0
    ? Math.max(...open.map((i) => Date.now() - new Date(i.openedAt).getTime()))
    : null;

  const headline = buildHeadline(tone, {
    health,
    failIncidentCount,
    warnIncidentCount,
    oldestOpenMs,
    blastRadius,
  });

  const styles = {
    grey:  'from-zinc-500/12 to-zinc-500/[0.02] border-zinc-500/30 text-zinc-400',
    green: 'from-emerald-500/12 to-emerald-500/[0.02] border-emerald-500/30 text-emerald-400',
    amber: 'from-amber-500/12  to-amber-500/[0.02]  border-amber-500/30  text-amber-400',
    red:   'from-red-500/12    to-red-500/[0.02]    border-red-500/30    text-red-400',
  } as const;

  const dotColor = {
    grey: 'bg-zinc-500',
    green: 'bg-emerald-500',
    amber: 'bg-amber-500',
    red: 'bg-red-500',
  }[tone];

  const updatedLabel = health.lastRunAt
    ? new Date(health.lastRunAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className={cn('rounded-lg border bg-gradient-to-r px-5 py-4 mb-4', styles[tone])}>
      <div className="flex items-center gap-3">
        <div className={cn('w-2.5 h-2.5 rounded-full shadow', dotColor)} />
        <div className="flex-1">
          <div className="text-[14px] font-semibold">{headline}</div>
          {health.total > 0 && (
            <div className="text-[11px] opacity-70 mt-0.5">{buildSubline(health)}</div>
          )}
        </div>
        {updatedLabel && (
          <div className="text-[10px] opacity-60">Updated {updatedLabel}</div>
        )}
      </div>
    </div>
  );
}
