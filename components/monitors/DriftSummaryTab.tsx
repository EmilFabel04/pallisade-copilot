'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Activity } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { SummaryHero } from './SummaryHero';
import { ActiveIncidents } from './ActiveIncidents';
import { TrendStrip } from './TrendStrip';
import { AssetHealthLean } from './AssetHealthLean';
import { CoverageGaps } from './CoverageGaps';
import type { IncidentSummary, IncidentStats } from '@/types/incident';
import type { DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  watches: any[];
  tasks: any[];
  loading: boolean;
}

export function DriftSummaryTab({ watches, tasks, loading: _loading }: Props) {
  const { selectedPipelineId } = usePipeline();
  const router = useRouter();

  const [activeIncidents, setActiveIncidents] = useState<IncidentSummary[]>([]);
  const [stats, setStats] = useState<IncidentStats | null>(null);
  const [trendData, setTrendData] = useState<any | null>(null);
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [unmonitoredCritical, setUnmonitoredCritical] = useState<Array<{ fqn: string; reason: string }>>([]);
  const [expandedAssetFqn, setExpandedAssetFqn] = useState<string | null>(null);
  const [activeCategories] = useState<Set<string>>(new Set());

  // First paint only waits on incidents — the hero doesn't need trends, and
  // gating on the heaviest endpoint left users staring at a skeleton for the
  // full monitor-trends round-trip. AssetHealthLean still uses trendData but
  // renders its own loading state.
  const [firstLoadComplete, setFirstLoadComplete] = useState(false);

  const fetchIncidents = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/incidents?stackId=${selectedPipelineId}&status=active`);
      if (r.ok) {
        const d = await r.json();
        setActiveIncidents(d.incidents || []);
      }
    } catch {}
    setFirstLoadComplete(true);
  }, [selectedPipelineId]);

  const fetchStats = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/incidents/stats?stackId=${selectedPipelineId}&window=7d`);
      if (r.ok) setStats(await r.json());
    } catch {}
  }, [selectedPipelineId]);

  const fetchTrends = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`);
      if (r.ok) setTrendData(await r.json());
    } catch {}
  }, [selectedPipelineId]);

  const fetchDrift = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/drift?status=pending&stackId=${selectedPipelineId}`);
      if (r.ok) {
        const d = await r.json();
        setRecommendations(d.recommendations || []);
      }
    } catch {}
  }, [selectedPipelineId]);

  const fetchCoverage = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/coverage/unmonitored-critical?stackId=${selectedPipelineId}`);
      if (r.ok) {
        const d = await r.json();
        setUnmonitoredCritical(d.assets || []);
      }
    } catch {}
  }, [selectedPipelineId]);

  // Reset first-load flag when pipeline changes
  useEffect(() => {
    setFirstLoadComplete(false);
    setActiveIncidents([]);
    setStats(null);
    setTrendData(null);
    setRecommendations([]);
    setUnmonitoredCritical([]);
  }, [selectedPipelineId]);

  // Fire all five fetches independently — each section renders as its data arrives
  useEffect(() => {
    if (!selectedPipelineId) return;
    fetchIncidents();
    fetchStats();
    fetchTrends();
    fetchDrift();
    fetchCoverage();
  }, [selectedPipelineId, fetchIncidents, fetchStats, fetchTrends, fetchDrift, fetchCoverage]);

  // Periodic refresh (no skeleton on subsequent polls)
  useEffect(() => {
    if (!selectedPipelineId) return;
    const t = setInterval(() => {
      invalidateCache('/api/incidents');
      invalidateCache('/api/schedule/monitor-trends');
      invalidateCache('/api/drift');
      invalidateCache('/api/coverage');
      fetchIncidents();
      fetchStats();
      fetchTrends();
      fetchDrift();
      fetchCoverage();
    }, 30000);
    return () => clearInterval(t);
  }, [selectedPipelineId, fetchIncidents, fetchStats, fetchTrends, fetchDrift, fetchCoverage]);

  const handleOpenInCopilot = useCallback((incident: IncidentSummary) => {
    const params = new URLSearchParams({
      contextType: 'incident',
      incidentId: incident.id,
      monitorId: incident.monitorId,
      targetFqn: incident.targetFqn,
    });
    router.push(`/dashboard/assistant?${params.toString()}`);
  }, [router]);

  const onIncidentChanged = useCallback(() => {
    invalidateCache('/api/incidents');
    fetchIncidents();
  }, [fetchIncidents]);

  const assetList = useMemo(() => {
    if (!trendData?.assets) return [];
    return Object.values(trendData.assets) as any[];
  }, [trendData]);

  // Use task-derived count so the hero paints without waiting for monitor-trends.
  // Distinct targetFqn across data-tier monitors is what the spec calls "monitored assets".
  const monitoredAssetCount = useMemo(() => {
    const fqns = new Set<string>();
    for (const t of tasks) {
      const fqn = (t as any)?.targetFqn;
      if (typeof fqn === 'string' && fqn.length > 0) fqns.add(fqn);
    }
    return fqns.size;
  }, [tasks]);

  if (!selectedPipelineId) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {firstLoadComplete ? (
        <SummaryHero
          incidents={activeIncidents}
          monitoredAssetCount={monitoredAssetCount}
          updatedAt={trendData?.updatedAt}
        />
      ) : (
        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] px-5 py-4 mb-4 animate-pulse">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-[var(--subtle-border)]" />
            <div className="h-3.5 w-64 bg-[var(--subtle-border)] rounded" />
          </div>
        </div>
      )}

      <ActiveIncidents
        incidents={activeIncidents}
        onChanged={onIncidentChanged}
        onOpenInCopilot={handleOpenInCopilot}
      />

      <TrendStrip stats={stats} />

      <AssetHealthLean
        assets={assetList}
        expandedFqn={expandedAssetFqn}
        onToggle={(fqn) => setExpandedAssetFqn((p) => p === fqn ? null : fqn)}
        activeCategories={activeCategories}
        onRunAnalysis={() => {}}
      />

      <CoverageGaps
        unmonitoredCriticalAssets={unmonitoredCritical}
        pendingRecommendations={recommendations}
        onAddMonitor={(fqn) => router.push(`/dashboard/monitors?createFor=${encodeURIComponent(fqn)}`)}
        onReviewRecs={() => router.push('/dashboard/monitors?tab=recommendations')}
      />

      {firstLoadComplete
        && assetList.length === 0
        && activeIncidents.length === 0
        && (
          <div className="flex flex-col items-center justify-center py-12">
            <Activity className="w-8 h-8 text-[var(--text-faint)] mb-3" />
            <p className="text-[13px] text-[var(--muted)]">No monitors configured yet.</p>
          </div>
        )}
    </div>
  );
}
