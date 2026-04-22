/**
 * Shared helpers for computing a watch (MonitorGroup) health score from its
 * constituent monitors' last statuses. Used by both the watch-level run
 * endpoint and the individual monitor-run endpoint (so the cached score on
 * MonitorGroup.healthScore stays fresh on every monitor run).
 */

export const WATCH_STATUS_SCORE: Record<string, number> = {
  PASS: 1.0,
  WARN: 0.5,
  FAIL: 0.0,
  ERROR: 0.0,
  SKIPPED: 0.8,
  RUNNING: 0.8,
};

export const WATCH_DEPTH_MULTIPLIER: Record<number, number> = { 0: 2.0, 1: 1.5 };
export const WATCH_PRIORITY_WEIGHT: Record<number, number> = { 1: 3.0, 2: 2.0, 3: 1.0 };

export interface WatchSignal {
  status: string | null;
  depth: number;
  priority: number;
}

/** Weighted health score in the 0–100 range (one decimal). */
export function computeWatchHealthScore(signals: WatchSignal[]): number {
  if (signals.length === 0) return 100;
  let totalWeightedValue = 0;
  let totalWeight = 0;
  for (const s of signals) {
    const statusVal = WATCH_STATUS_SCORE[(s.status || '').toUpperCase()] ?? 0;
    const depthMult = WATCH_DEPTH_MULTIPLIER[s.depth] ?? 1.0;
    const prioWeight = WATCH_PRIORITY_WEIGHT[s.priority] ?? 0.5;
    const weight = prioWeight * depthMult;
    totalWeightedValue += weight * statusVal;
    totalWeight += weight;
  }
  if (totalWeight === 0) return 100;
  return Math.round((totalWeightedValue / totalWeight) * 1000) / 10;
}

export function watchHealthStatusFromScore(score: number): string {
  if (score >= 90) return 'healthy';
  if (score >= 70) return 'degraded';
  if (score >= 40) return 'at_risk';
  return 'unhealthy';
}

/**
 * Build signals from a MonitorGroup's monitors. Uses each monitor's config
 * for its watch depth/priority (falling back to anchor-match / P2).
 */
export function signalsFromMonitors(
  monitors: Array<{
    targetFqn: string | null;
    lastStatus: string | null;
    config: any;
  }>,
  anchorFqn: string | null,
): WatchSignal[] {
  return monitors
    .filter((m) => m.lastStatus) // exclude never-run monitors from the score
    .map((m) => {
      const cfg = (m.config as any) || {};
      const depth = cfg._watchDepth ?? (m.targetFqn === anchorFqn ? 0 : 1);
      const priority = cfg._watchPriority ?? 2;
      return { status: m.lastStatus, depth, priority };
    });
}
