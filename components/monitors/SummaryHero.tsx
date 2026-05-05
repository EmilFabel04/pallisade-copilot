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
    grey:  'from-zinc-500/[0.18] via-zinc-500/[0.08] to-transparent border-zinc-500/40',
    green: 'from-emerald-500/[0.18] via-emerald-500/[0.06] to-transparent border-emerald-500/40',
    amber: 'from-amber-500/[0.22] via-amber-500/[0.08] to-transparent border-amber-500/45',
    red:   'from-red-500/[0.24] via-red-500/[0.10] to-transparent border-red-500/50',
  } as const;

  const headlineColor = {
    grey:  'text-zinc-300',
    green: 'text-emerald-300',
    amber: 'text-amber-300',
    red:   'text-red-300',
  }[tone];

  const dotColor = {
    grey:  'bg-zinc-500',
    green: 'bg-emerald-500',
    amber: 'bg-amber-500',
    red:   'bg-red-500',
  }[tone];

  const dotPulse = tone === 'red' || tone === 'amber';

  const updatedLabel = health.lastRunAt
    ? new Date(health.lastRunAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className={cn('rounded-lg border bg-gradient-to-r px-5 py-4 mb-4', styles[tone])}>
      <div className="flex items-center gap-3">
        <div className={cn('w-2.5 h-2.5 rounded-full shadow-lg', dotColor, dotPulse && 'animate-pulse')} />
        <div className="flex-1">
          <div className={cn('text-[14px] font-semibold', headlineColor)}>{headline}</div>
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
