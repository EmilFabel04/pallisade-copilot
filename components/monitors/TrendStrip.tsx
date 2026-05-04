'use client';

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import type { IncidentStats } from '@/types/incident';

interface Props { stackId: string; }

function formatMs(ms: number | null): string {
  if (ms == null) return '—';
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function delta(current: number | null, prior: number | null): { sign: '+' | '-' | ''; magnitude: number } {
  if (current == null || prior == null) return { sign: '', magnitude: 0 };
  const d = current - prior;
  return { sign: d > 0 ? '+' : d < 0 ? '-' : '', magnitude: Math.abs(d) };
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length === 0) return null;
  const max = Math.max(...data, 1);
  const points = data.map((v, i) => `${(i / (data.length - 1 || 1)) * 100},${20 - (v / max) * 16}`).join(' ');
  return (
    <svg width="100%" height="20" viewBox="0 0 100 20" className="mt-1">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

export function TrendStrip({ stackId }: Props) {
  const [stats, setStats] = useState<IncidentStats | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`/api/incidents/stats?stackId=${stackId}&window=7d`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (active) setStats(d); })
      .catch(() => {});
    const t = setInterval(() => {
      fetch(`/api/incidents/stats?stackId=${stackId}&window=7d`)
        .then((r) => r.ok ? r.json() : null)
        .then((d) => { if (active) setStats(d); })
        .catch(() => {});
    }, 60000);
    return () => { active = false; clearInterval(t); };
  }, [stackId]);

  if (!stats) return null;

  const passDelta = stats.passRate.current != null && stats.passRate.prior != null
    ? (stats.passRate.current - stats.passRate.prior) * 100
    : null;
  const mttrDelta = delta(stats.mttrMs.current, stats.mttrMs.prior);
  const incidentDelta = stats.opened.current - stats.opened.prior;

  return (
    <div className="mb-6">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">7-day trend</div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Pass rate"
              value={stats.passRate.current != null ? `${(stats.passRate.current * 100).toFixed(1)}%` : '—'}
              delta={passDelta != null ? `${passDelta >= 0 ? '▲' : '▼'} ${Math.abs(passDelta).toFixed(1)}` : ''}
              tone={passDelta == null ? 'neutral' : passDelta >= 0 ? 'good' : 'bad'} />
        <Tile label="MTTR"
              value={formatMs(stats.mttrMs.current)}
              delta={mttrDelta.sign ? `${mttrDelta.sign === '+' ? '▲' : '▼'} ${formatMs(mttrDelta.magnitude)}` : ''}
              tone={mttrDelta.sign === '-' ? 'good' : mttrDelta.sign === '+' ? 'bad' : 'neutral'} />
        <Tile label="Incidents"
              value={String(stats.opened.current)}
              delta={incidentDelta !== 0 ? `${incidentDelta > 0 ? '▲' : '▼'} ${Math.abs(incidentDelta)}` : ''}
              tone={incidentDelta < 0 ? 'good' : incidentDelta > 0 ? 'bad' : 'neutral'}>
          <Sparkline data={stats.opened.sparkline} color="#a1a1aa" />
        </Tile>
        <Tile label="Recovered"
              value={`${stats.recovered.current} / ${stats.opened.current}`}
              delta={stats.recovered.ratio != null ? `${Math.round(stats.recovered.ratio * 100)}%` : ''}
              tone="good" />
      </div>
    </div>
  );
}

function Tile({ label, value, delta, tone, children }: { label: string; value: string; delta: string; tone: 'good' | 'bad' | 'neutral'; children?: React.ReactNode }) {
  const deltaClr = tone === 'good' ? 'text-emerald-400' : tone === 'bad' ? 'text-red-400' : 'text-[var(--muted)]';
  return (
    <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] px-3 py-2.5">
      <div className="text-[9px] uppercase tracking-wider text-[var(--muted)]">{label}</div>
      <div className="text-[18px] font-bold tabular-nums text-[var(--text)] mt-0.5">
        {value}
        {delta && <span className={cn('text-[10px] font-medium ml-1.5', deltaClr)}>{delta}</span>}
      </div>
      {children}
    </div>
  );
}
