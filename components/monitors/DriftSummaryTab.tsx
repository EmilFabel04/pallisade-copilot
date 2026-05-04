'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Loader2, Activity } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { usePipeline } from '@/contexts/PipelineContext';
import { SummaryHero } from './SummaryHero';
import { ActiveIncidents } from './ActiveIncidents';
import { TrendStrip } from './TrendStrip';
import { AssetHealthLean } from './AssetHealthLean';
import { CoverageGaps } from './CoverageGaps';
import type { IncidentSummary } from '@/types/incident';
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
  const [trendData, setTrendData] = useState<any | null>(null);
  const [recommendations, setRecommendations] = useState<DriftRecommendation[]>([]);
  const [unmonitoredCritical, setUnmonitoredCritical] = useState<Array<{ fqn: string; reason: string }>>([]);
  const [expandedAssetFqn, setExpandedAssetFqn] = useState<string | null>(null);
  const [activeCategories] = useState<Set<string>>(new Set());

  const fetchAll = useCallback(async () => {
    if (!selectedPipelineId) return;
    const [incRes, trRes, drRes, covRes] = await Promise.all([
      fetch(`/api/incidents?stackId=${selectedPipelineId}&status=active`).then((r) => r.ok ? r.json() : null),
      fetch(`/api/schedule/monitor-trends?stackId=${selectedPipelineId}`).then((r) => r.ok ? r.json() : null),
      fetch(`/api/drift?status=pending&stackId=${selectedPipelineId}`).then((r) => r.ok ? r.json() : null),
      fetch(`/api/coverage/unmonitored-critical?stackId=${selectedPipelineId}`).then((r) => r.ok ? r.json() : null).catch(() => null),
    ]);
    setActiveIncidents(incRes?.incidents || []);
    setTrendData(trRes);
    setRecommendations(drRes?.recommendations || []);
    setUnmonitoredCritical(covRes?.assets || []);
  }, [selectedPipelineId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  useEffect(() => {
    const t = setInterval(fetchAll, 30000);
    return () => clearInterval(t);
  }, [fetchAll]);

  const handleOpenInCopilot = useCallback((incident: IncidentSummary) => {
    const params = new URLSearchParams({
      contextType: 'incident',
      incidentId: incident.id,
      monitorId: incident.monitorId,
      targetFqn: incident.targetFqn,
    });
    router.push(`/dashboard/copilot?${params.toString()}`);
  }, [router]);

  const assetList = useMemo(() => {
    if (!trendData?.assets) return [];
    return Object.values(trendData.assets) as any[];
  }, [trendData]);

  const monitoredAssetCount = assetList.length;

  if (!selectedPipelineId) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-[var(--muted)]" /></div>;
  }

  return (
    <div className="space-y-2">
      <SummaryHero
        incidents={activeIncidents}
        monitoredAssetCount={monitoredAssetCount}
        updatedAt={trendData?.updatedAt}
      />
      <ActiveIncidents stackId={selectedPipelineId} onOpenInCopilot={handleOpenInCopilot} />
      <TrendStrip stackId={selectedPipelineId} />
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
      {assetList.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12">
          <Activity className="w-8 h-8 text-[var(--text-faint)] mb-3" />
          <p className="text-[13px] text-[var(--muted)]">No monitors configured yet.</p>
        </div>
      )}
    </div>
  );
}
