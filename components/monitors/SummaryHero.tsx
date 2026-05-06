'use client';

import { cn } from '@/lib/utils';
import { ArrowRight } from 'lucide-react';
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
  onViewFailing?: () => void;
}

export function SummaryHero({ health, incidents, blastRadius, onViewFailing }: Props) {
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

  const surface = {
    grey:  'bg-zinc-500/[0.06] border-zinc-500/30',
    green: 'bg-emerald-500/[0.06] border-emerald-500/30',
    amber: 'bg-amber-500/[0.08] border-amber-500/35',
    red:   'bg-red-500/[0.08] border-red-500/40',
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

  const showFailingCta = !!onViewFailing && (health.failing > 0 || failIncidentCount > 0);

  return (
    <div className={cn('rounded-lg border px-5 py-4 mb-4', surface[tone])}>
      <div className="flex items-center gap-3">
        <div className={cn('w-2.5 h-2.5 rounded-full shadow-lg', dotColor, dotPulse && 'animate-pulse')} />
        <div className="flex-1 min-w-0">
          <div className={cn('text-[14px] font-semibold', headlineColor)}>{headline}</div>
          {health.total > 0 && (
            <div className="text-[11px] opacity-70 mt-0.5">{buildSubline(health)}</div>
          )}
        </div>
        {showFailingCta && (
          <button
            type="button"
            onClick={onViewFailing}
            className={cn(
              'flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-md border whitespace-nowrap transition-colors',
              tone === 'red'
                ? 'border-red-500/40 text-red-200 hover:bg-red-500/10'
                : 'border-amber-500/40 text-amber-200 hover:bg-amber-500/10',
            )}
          >
            View failing
            <ArrowRight className="w-3 h-3" />
          </button>
        )}
        {updatedLabel && (
          <div className="text-[10px] opacity-60 shrink-0">Updated {updatedLabel}</div>
        )}
      </div>
    </div>
  );
}
