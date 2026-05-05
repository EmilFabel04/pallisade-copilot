'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Activity, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import { SummaryHero } from './SummaryHero';
import { ActiveIncidents } from './ActiveIncidents';
import { TrendStrip } from './TrendStrip';
import { AssetHealthLean } from './AssetHealthLean';
import { PipelineTier } from './PipelineTier';
import { CoverageGaps } from './CoverageGaps';
import type { IncidentSummary, IncidentStats } from '@/types/incident';
import type {
  MonitorHealthSummary,
  PipelineToolStatusResponse,
} from '@/types/monitors-summary';
import type { DriftRecommendation } from './DriftRecommendationCard';

interface Props {
  watches: any[];
  tasks: any[];
  loading: boolean;
}

export function DriftSummaryTab({ watches: _w, tasks: _t, loading: _l }: Props) {
  const { selectedPipelineId } = usePipeline();
  const router = useRouter();

  const [activeIncidents, setActiveIncidents] = useState<IncidentSummary[]>([]);
  const [health, setHealth] = useState<MonitorHealthSummary | null>(null);
  const [stats, setStats] = useState<IncidentStats | null>(null);
  const [pipelineTools, setPipelineTools] = useState<PipelineToolStatusResponse['tools']>([]);
  const [trendData, setTrendData] = useState<any | null>(null);
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState<string | null>(null);
  const [unmonitoredCritical, setUnmonitoredCritical] = useState<Array<{ fqn: string; reason: string }>>([]);
  const [lineageExtracted, setLineageExtracted] = useState(false);
  const [expandedAssetFqn, setExpandedAssetFqn] = useState<string | null>(null);
  const [activeCategories] = useState<Set<string>>(new Set());

  // Per-section ready flags. Each section paints its own skeleton; no global gate.
  const [healthReady, setHealthReady] = useState(false);
  const [incidentsReady, setIncidentsReady] = useState(false);
  const [pipelineReady, setPipelineReady] = useState(false);
  const [trendsReady, setTrendsReady] = useState(false);
  const [coverageReady, setCoverageReady] = useState(false);
  const [driftReady, setDriftReady] = useState(false);

  const fetchHealth = useCallback(async () => {
    if (!selectedPipelineId) return;
    let nextHealth: MonitorHealthSummary = {
      total: 0, healthy: 0, warning: 0, failing: 0,
      dataAssets: 0, pipelineTools: 0, lastRunAt: null,
    };
    try {
      const r = await cachedFetch(`/api/monitors/health-summary?stackId=${selectedPipelineId}`);
      if (r.ok) nextHealth = await r.json();
    } catch {}
    setHealth(nextHealth);
    setHealthReady(true);
  }, [selectedPipelineId]);

  const fetchIncidents = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/incidents?stackId=${selectedPipelineId}&status=active`);
      if (r.ok) {
        const d = await r.json();
        setActiveIncidents(d.incidents || []);
      }
    } catch {}
    setIncidentsReady(true);
  }, [selectedPipelineId]);

  const fetchStats = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/incidents/stats?stackId=${selectedPipelineId}&window=7d`);
      if (r.ok) setStats(await r.json());
    } catch {}
  }, [selectedPipelineId]);

  const fetchPipelineStatus = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/monitors/pipeline-status?stackId=${selectedPipelineId}`);
      if (r.ok) {
        const d: PipelineToolStatusResponse = await r.json();
        setPipelineTools(d.tools || []);
      }
    } catch {}
    setPipelineReady(true);
  }, [selectedPipelineId]);

  const fetchTrends = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`);
      if (r.ok) setTrendData(await r.json());
    } catch {}
    setTrendsReady(true);
  }, [selectedPipelineId]);

  const fetchDrift = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/drift?status=pending&stackId=${selectedPipelineId}`);
      if (r.ok) {
        const d = await r.json();
        setRecommendations(d.recommendations || []);
        setLastAnalyzedAt(d.lastAnalyzedAt || null);
      }
    } catch {}
    setDriftReady(true);
  }, [selectedPipelineId]);

  const fetchCoverage = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const r = await cachedFetch(`/api/coverage/unmonitored-critical?stackId=${selectedPipelineId}`);
      if (r.ok) {
        const d = await r.json();
        setUnmonitoredCritical(d.assets || []);
        setLineageExtracted(!!d.lineageExtracted);
      }
    } catch {}
    setCoverageReady(true);
  }, [selectedPipelineId]);

  // Reset per-section flags + state on pipeline change.
  useEffect(() => {
    setHealth(null);
    setActiveIncidents([]);
    setStats(null);
    setPipelineTools([]);
    setTrendData(null);
    setRecommendations([]);
    setLastAnalyzedAt(null);
    setUnmonitoredCritical([]);
    setLineageExtracted(false);
    setHealthReady(false);
    setIncidentsReady(false);
    setPipelineReady(false);
    setTrendsReady(false);
    setCoverageReady(false);
    setDriftReady(false);
  }, [selectedPipelineId]);

  // Fan out independent fetches; each section gates on its own readiness.
  useEffect(() => {
    if (!selectedPipelineId) return;
    fetchHealth();
    fetchIncidents();
    fetchStats();
    fetchPipelineStatus();
    fetchTrends();
    fetchDrift();
    fetchCoverage();
  }, [
    selectedPipelineId,
    fetchHealth, fetchIncidents, fetchStats, fetchPipelineStatus,
    fetchTrends, fetchDrift, fetchCoverage,
  ]);

  // Periodic refresh — invalidate first so cachedFetch re-fetches.
  useEffect(() => {
    if (!selectedPipelineId) return;
    const t = setInterval(() => {
      invalidateCache('/api/monitors/health-summary');
      invalidateCache('/api/incidents');
      invalidateCache('/api/monitors/pipeline-status');
      invalidateCache('/api/schedule/monitor-trends');
      invalidateCache('/api/drift');
      invalidateCache('/api/coverage');
      fetchHealth();
      fetchIncidents();
      fetchStats();
      fetchPipelineStatus();
      fetchTrends();
      fetchDrift();
      fetchCoverage();
    }, 30_000);
    return () => clearInterval(t);
  }, [
    selectedPipelineId,
    fetchHealth, fetchIncidents, fetchStats, fetchPipelineStatus,
    fetchTrends, fetchDrift, fetchCoverage,
  ]);

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

  const onDriftRunComplete = useCallback(() => {
    invalidateCache('/api/drift');
    fetchDrift();
  }, [fetchDrift]);

  const assetList = useMemo(() => {
    if (!trendData?.assets) return [];
    return Object.values(trendData.assets) as any[];
  }, [trendData]);

  if (!selectedPipelineId) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {healthReady && incidentsReady && health ? (
        <SummaryHero health={health} incidents={activeIncidents} />
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

      <PipelineTier
        tools={pipelineTools}
        loading={!pipelineReady}
        stackId={selectedPipelineId}
      />

      <AssetHealthLean
        assets={assetList}
        expandedFqn={expandedAssetFqn}
        onToggle={(fqn) => setExpandedAssetFqn((p) => p === fqn ? null : fqn)}
        activeCategories={activeCategories}
        onRunAnalysis={() => {}}
      />

      {coverageReady && driftReady && (
        <CoverageGaps
          unmonitoredCriticalAssets={unmonitoredCritical}
          lineageExtracted={lineageExtracted}
          pendingRecommendations={recommendations}
          lastAnalyzedAt={lastAnalyzedAt}
          stackId={selectedPipelineId}
          onAddMonitor={(fqn) => router.push(`/dashboard/monitors?createFor=${encodeURIComponent(fqn)}`)}
          onReviewRecs={() => router.push('/dashboard/monitors?tab=recommendations')}
          onDriftRunComplete={onDriftRunComplete}
        />
      )}

      {healthReady
        && incidentsReady
        && trendsReady
        && pipelineReady
        && (health?.total ?? 0) === 0
        && activeIncidents.length === 0
        && pipelineTools.length === 0
        && assetList.length === 0
        && (
          <div className="flex flex-col items-center justify-center py-12">
            <Activity className="w-8 h-8 text-[var(--text-faint)] mb-3" />
            <p className="text-[13px] text-[var(--muted)]">No monitors configured yet.</p>
          </div>
        )}
    </div>
  );
}
