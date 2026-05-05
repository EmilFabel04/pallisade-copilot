import type { MonitorHealthSummary } from '@/types/monitors-summary';

export type HeroTone = 'green' | 'amber' | 'red' | 'grey';

export interface HeadlineInputs {
  health: MonitorHealthSummary;
  failIncidentCount: number;
  warnIncidentCount: number;
  oldestOpenMs: number | null;
  blastRadius?: { dashboards: number; tables: number };
}

export function formatMs(ms: number): string {
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

/**
 * Picks the hero tone from monitor health + open incidents.
 * Empty profile → grey, any FAIL signal → red, any WARN signal → amber, else green.
 */
export function selectHeroTone(
  health: MonitorHealthSummary,
  failIncidentCount: number,
  warnIncidentCount: number,
): HeroTone {
  if (health.total === 0) return 'grey';
  if (health.failing > 0 || failIncidentCount > 0) return 'red';
  if (health.warning > 0 || warnIncidentCount > 0) return 'amber';
  return 'green';
}

/**
 * Builds the hero headline text. Pure — no DOM, no React.
 */
export function buildHeadline(tone: HeroTone, inputs: HeadlineInputs): string {
  const { health, failIncidentCount, warnIncidentCount, oldestOpenMs, blastRadius } = inputs;
  if (tone === 'grey') return 'Setting up. No monitors yet.';
  if (tone === 'green') return 'All systems healthy.';
  if (tone === 'amber') {
    const n = health.warning + warnIncidentCount;
    let s = `${n} warning${n === 1 ? '' : 's'}.`;
    if (blastRadius) s += ` Affecting ${blastRadius.dashboards} dashboards.`;
    return s;
  }
  // red
  const f = failIncidentCount || health.failing;
  let s = `${f} critical incident${f === 1 ? '' : 's'}`;
  if (warnIncidentCount > 0) s += ` · ${warnIncidentCount} warning`;
  s += '.';
  if (blastRadius) s += ` Affecting ${blastRadius.dashboards} BI dashboards and ${blastRadius.tables} downstream tables.`;
  if (oldestOpenMs) s += ` Oldest ${formatMs(oldestOpenMs)}.`;
  return s;
}

/** Sub-line is always shown when total > 0 — fixes the "0 assets monitored" bug. */
export function buildSubline(health: MonitorHealthSummary): string {
  return (
    `${health.total} monitor${health.total === 1 ? '' : 's'} · ` +
    `${health.healthy} healthy · ${health.warning} warning · ${health.failing} failing — ` +
    `${health.dataAssets} data asset${health.dataAssets === 1 ? '' : 's'}, ` +
    `${health.pipelineTools} pipeline tool${health.pipelineTools === 1 ? '' : 's'}`
  );
}
