'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { cn } from '@/lib/utils';
import type { RenderedViewResponse, ViewNode, ViewEdge, PipelineLaneName } from '../types';
import { LANE_COLORS, LANE_LABELS } from '../types';
import { LAYER_COLORS, LAYER_LABELS, type PipelineLayer } from '@/components/pipeline/types';
import type { InspectorTarget, ToolDetailsResponse } from './types';
import {
  getToolMeta,
  getEdgeMeta,
  getOverallHealth,
  HEALTH_COLORS,
  SEMANTIC_EDGE_STYLES,
  RELATIONSHIP_BASIS_LABELS,
} from './types';
import { ToolDetailView } from './tool-details/ToolDetailView';
import { LoadingState } from './tool-details/SharedDetailComponents';
import type { AssetPrefill } from '@/types/monitor-catalog';
import { computeMonitorScoring, resolveAssetCategory, type MonitorScoringResult } from '@/lib/monitor-scoring';
// Role badges shown when functional role differs from the lane name.
// "transformation" and "reporting" are excluded — they match their lane, so a badge is redundant.
const ROLE_BADGE_LABELS: Record<string, string> = {
  warehouse_raw: 'Raw',
  warehouse_analytics: 'Analytics',
  orchestration: 'Orchestration',
  ingestion: 'Ingestion',
  quality: 'Quality',
  version_control: 'Version Control',
  infrastructure: 'Infrastructure',
  semantic: 'Semantic',
  job_runtime: 'Job Runtime',
};

type MonitorInfo = {
  id: string;
  name: string;
  monitorType: string | null;
  targetFqn: string | null;
  lastStatus: string | null;
  lastRunAt: string | null;
  lastMessage?: string;
  integrationId: string | null;
};

interface InspectorPanelProps {
  target: InspectorTarget;
  laneOverview: RenderedViewResponse | null;
  stackId: string | null;
  allMonitors?: MonitorInfo[];
  onClose: () => void;
  onCreateSingleMonitor?: (prefill: AssetPrefill) => void;
  onCreateMultiMonitor?: (nodeIds: string[]) => void;
}


// ─── Node Inspector (with tool-details fetch) ────────────────────────

function NodeInspector({
  node,
  laneOverview,
  stackId,
  allMonitors,
  onCreateSingleMonitor,
  onCreateMultiMonitor,
}: {
  node: ViewNode;
  laneOverview: RenderedViewResponse | null;
  stackId: string | null;
  allMonitors?: MonitorInfo[];
  onCreateSingleMonitor?: (prefill: AssetPrefill) => void;
  onCreateMultiMonitor?: (nodeIds: string[]) => void;
}) {
  const meta = getToolMeta(node);
  const health = getOverallHealth(meta.healthSummary);
  const healthColor = HEALTH_COLORS[health];
  const laneColor = LAYER_COLORS[node.layer as PipelineLayer] || LANE_COLORS[meta.lane as PipelineLaneName] || '#6366F1';
  const laneLabel = LAYER_LABELS[node.layer as PipelineLayer] || LANE_LABELS[meta.lane as PipelineLaneName] || meta.lane;

  // Resolve monitors for this tool node
  const MONITOR_TYPE_TO_LAYER: Record<string, string> = {
    SERVER_HEALTH: 'INFRASTRUCTURE', CERTIFICATE: 'INFRASTRUCTURE', LOG_ANALYSIS: 'INFRASTRUCTURE',
    FAILED_SYNCS: 'INGESTION', SYNC_LAG: 'INGESTION', CONNECTOR_SCHEMA_DRIFT: 'INGESTION',
    DAG_LAST_RUN: 'ORCHESTRATION', DAG_SCHEDULE_LAG: 'ORCHESTRATION', TASK_FAILURE_RATE: 'ORCHESTRATION',
    DBT_TEST_FAILURES: 'TRANSFORMATION', DBT_MODEL_FRESHNESS: 'TRANSFORMATION', DBT_SOURCE_FRESHNESS: 'TRANSFORMATION',
  };

  const nodeMonitors = useMemo(() => {
    if (!allMonitors?.length) return [];
    const integrationId = node.metadata?.integrationId as string | undefined;
    return allMonitors.filter(m => {
      // Match by integrationId
      if (integrationId && m.integrationId === integrationId) return true;
      // Match by layer for monitors without integrationId
      if (!m.integrationId && m.monitorType) {
        const monLayer = MONITOR_TYPE_TO_LAYER[m.monitorType];
        if (monLayer && monLayer === node.layer) return true;
      }
      return false;
    });
  }, [allMonitors, node.id, node.layer, node.metadata?.integrationId]);

  // Tool-level monitor health & coverage scoring
  const toolScoring = useMemo((): MonitorScoringResult | null => {
    if (nodeMonitors.length === 0) return null;
    const category = resolveAssetCategory(node.layer, node.metadata?.platformDomain as string, node.platform ?? undefined);
    if (!category) return null;
    return computeMonitorScoring(
      nodeMonitors.map(m => ({ monitorType: m.monitorType || '', lastStatus: m.lastStatus })),
      category,
    );
  }, [nodeMonitors, node.layer, node.metadata?.platformDomain, node.platform]);

  // Compute effective header health color: use monitor-based when available
  const effectiveHealthColor = toolScoring?.healthScore != null
    ? (toolScoring.healthStatus === 'healthy' ? '#10B981'
      : toolScoring.healthStatus === 'degraded' ? '#F59E0B'
      : toolScoring.healthStatus === 'at_risk' ? '#F97316'
      : toolScoring.healthStatus === 'unhealthy' ? '#EF4444'
      : '#6B7280')
    : (nodeMonitors.length === 0 ? '#6B7280' : healthColor); // gray when no monitors

  // Fetch tool details on-demand
  const [details, setDetails] = useState<ToolDetailsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const cacheRef = useRef<Map<string, ToolDetailsResponse>>(new Map());

  // Clear cache when pipeline data changes (new extraction).
  // Use a composite stamp that detects real content changes, not just count matches.
  const overviewStamp = laneOverview
    ? `${laneOverview.nodes?.length ?? 0}:${laneOverview.edges?.length ?? 0}:${laneOverview.stats?.opsSummary?.totalAssets ?? 0}:${laneOverview.stats?.builtAt ?? ''}`
    : '0';
  useEffect(() => {
    cacheRef.current.clear();
  }, [overviewStamp]);

  useEffect(() => {
    if (!stackId || !node.id) return;

    // Check cache first
    const cached = cacheRef.current.get(node.id);
    if (cached) {
      setDetails(cached);
      setLoading(false);
      setFetchError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setFetchError(null);
    setDetails(null);

    fetch(`/api/pipeline/${stackId}/lineage/engine?action=view-tool-details&id=${encodeURIComponent(node.id)}`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: ToolDetailsResponse) => {
        if (cancelled) return;
        if (data.error) {
          setFetchError(data.error);
        } else {
          setDetails(data);
          cacheRef.current.set(node.id, data);
        }
      })
      .catch(err => {
        if (!cancelled) setFetchError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [node.id, stackId]);

  return (
    <div className="space-y-4">
      {/* Header — renders immediately from existing metadata */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: effectiveHealthColor, boxShadow: `0 0 6px ${effectiveHealthColor}60` }}
          />
          <span className="text-[15px] font-semibold text-[var(--text)]">{node.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: laneColor, background: `${laneColor}14`, border: `1px solid ${laneColor}20` }}
          >
            {laneLabel}
          </span>
          {meta.functionalRole && ROLE_BADGE_LABELS[meta.functionalRole] && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium text-[var(--muted)] bg-[var(--bg-secondary)] border border-[var(--border)]">
              {ROLE_BADGE_LABELS[meta.functionalRole]}
            </span>
          )}
          <span className="text-[11px] text-[var(--muted)] capitalize">{node.platform || 'Unknown'}</span>
        </div>
      </div>

      {/* Monitor Health & Coverage */}
      {toolScoring && toolScoring.healthScore != null && (
        <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Monitor Health</span>
            <div className="flex items-center gap-2">
              <div className="w-14 h-1.5 rounded-full bg-[var(--subtle-bg)] overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${toolScoring.healthScore}%`,
                    backgroundColor: toolScoring.healthStatus === 'healthy' ? '#10B981'
                      : toolScoring.healthStatus === 'degraded' ? '#F59E0B'
                      : toolScoring.healthStatus === 'at_risk' ? '#F97316'
                      : '#EF4444',
                  }}
                />
              </div>
              <span
                className="text-[11px] font-medium"
                style={{
                  color: toolScoring.healthStatus === 'healthy' ? '#10B981'
                    : toolScoring.healthStatus === 'degraded' ? '#F59E0B'
                    : toolScoring.healthStatus === 'at_risk' ? '#F97316'
                    : '#EF4444',
                }}
              >
                {Math.round(toolScoring.healthScore)}%
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Coverage</span>
            <div className="flex items-center gap-2">
              <div className="w-14 h-1.5 rounded-full bg-[var(--subtle-bg)] overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(toolScoring.coveragePct, 100)}%`,
                    backgroundColor: toolScoring.coverageStatus === 'good' ? '#10B981'
                      : toolScoring.coverageStatus === 'partial' ? '#F59E0B'
                      : '#6B7280',
                  }}
                />
              </div>
              <span
                className="text-[11px] font-medium"
                style={{
                  color: toolScoring.coverageStatus === 'good' ? '#10B981'
                    : toolScoring.coverageStatus === 'partial' ? '#F59E0B'
                    : '#6B7280',
                }}
              >
                {toolScoring.configured}/{toolScoring.available}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Detail content */}
      {loading && <LoadingState />}

      {/* Create monitors for this tool (after details load so subNodeIds are available) */}
      {onCreateSingleMonitor && (
        <button
          disabled={loading}
          onClick={() => {
            const platform = (node.platform || '').toLowerCase();
            const layer = (node.layer || '').toUpperCase();
            let domain = 'warehouse';
            if (['fivetran', 'airbyte', 'stitch', 'hevo', 'meltano'].some(t => platform.includes(t)) || layer === 'INGESTION') domain = 'ingestion';
            else if (['airflow', 'dagster', 'prefect', 'n8n', 'argo'].some(t => platform.includes(t)) || layer === 'ORCHESTRATION') domain = 'orchestration';
            else if (['dbt', 'dbt_cloud', 'dbt_core'].some(t => platform.includes(t)) || layer === 'TRANSFORMATION') domain = 'transform';
            else if (['metabase', 'looker', 'tableau', 'powerbi'].some(t => platform.includes(t)) || layer === 'REPORTING') domain = 'bi';
            else if (layer === 'INFRASTRUCTURE' || ['linux', 'server', 'docker', 'kubernetes', 'k8s', 'aws', 'gcp', 'azure', 'terraform', 'nginx', 'redis', 'kafka'].some(t => platform.includes(t))) domain = 'infrastructure';
            // Extract child asset node IDs for tool nodes.
            // Prefer IDs from fetched tool details (details.groups) since
            // node.metadata.subNodes may be empty or truncated.
            let subNodeIds: string[] = [];
            let childItems: Array<{ id: string; name: string; platformId: string }> = [];
            if (details?.groups) {
              const seen = new Set<string>();
              for (const [groupKey, items] of Object.entries(details.groups)) {
                for (const item of items) {
                  if (item.id && !seen.has(item.id)) {
                    seen.add(item.id);
                    subNodeIds.push(item.id);
                    // Extract platform-specific ID only for top-level entities:
                    // - Connectors (have connector_id)
                    // - DAGs (in "dags" group, not tasks which have a "container" field)
                    const isTask = groupKey === 'tasks' || !!item.container;
                    const pid = isTask
                      ? ''
                      : (item.metadata?.connector_id || item.metadata?.dag_id || '');
                    if (pid && !childItems.some((c) => c.platformId === pid)) {
                      childItems.push({ id: item.id, name: item.name || item.id, platformId: pid });
                    }
                  }
                }
              }
            }
            if (subNodeIds.length === 0) {
              const subNodes: Array<{ id: string; name?: string; platformId?: string }> = node.metadata?.subNodes || [];
              subNodeIds = subNodes.map((s) => s.id).filter(Boolean);
              childItems = subNodes
                .filter((s) => s.platformId)
                .map((s) => ({ id: s.id, name: s.name || s.id, platformId: s.platformId! }));
            }
            onCreateSingleMonitor({
              nodeId: node.id,
              fqn: (node.metadata?.fqn as string) || node.name,
              name: node.name || platform,
              platform: node.platform || undefined,
              domain,
              subNodeIds: subNodeIds.length > 0 ? subNodeIds : undefined,
              childItems: childItems.length > 0 ? childItems : undefined,
            });
          }}
          className={cn(
            'w-full text-left px-3 py-2.5 rounded-lg border transition-all text-[12px] font-medium flex items-center gap-2',
            loading
              ? 'bg-[var(--accent)]/5 border-[var(--accent)]/10 text-[var(--muted)] cursor-wait'
              : 'bg-[var(--accent)]/10 border-[var(--accent)]/20 hover:bg-[var(--accent)]/20 text-[var(--text)]',
          )}
        >
          <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          {loading ? 'Loading…' : 'Create Monitors'}
        </button>
      )}

      {fetchError && (
        <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/10">
          <p className="text-[12px] text-red-400">Failed to load details</p>
          <p className="text-[11px] text-[var(--muted)] mt-1">{fetchError}</p>
          <button
            onClick={() => {
              cacheRef.current.delete(node.id);
              setFetchError(null);
              setLoading(true);
              fetch(`/api/pipeline/${stackId}/lineage/engine?action=view-tool-details&id=${encodeURIComponent(node.id)}`)
                .then(res => {
                  if (!res.ok) throw new Error(`HTTP ${res.status}`);
                  return res.json();
                })
                .then((data: ToolDetailsResponse) => {
                  if (data.error) setFetchError(data.error);
                  else { setDetails(data); cacheRef.current.set(node.id, data); }
                })
                .catch(err => setFetchError(err.message))
                .finally(() => setLoading(false));
            }}
            className="mt-2 text-[11px] text-[var(--text)] underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {details && !loading && (
        <>
          {details.summary?.coverageGaps?.length > 0 && (
            <div className="mb-3 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/10">
              <p className="text-[11px] text-amber-400 font-medium">
                {details.summary.coverageGaps.includes('no_data_extracted')
                  ? 'No data extracted yet — run lineage extraction to populate this tool.'
                  : details.summary.coverageGaps.includes('no_activity_data_yet')
                  ? 'No activity data available yet.'
                  : `Coverage gaps: ${details.summary.coverageGaps.map(g => g.replace(/_/g, ' ')).join(', ')}`}
              </p>
            </div>
          )}
          <ToolDetailView details={details} monitors={nodeMonitors} />
        </>
      )}
    </div>
  );
}


// ─── Edge Inspector (unchanged) ──────────────────────────────────────

function Section({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-[var(--subtle-border)] pt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full group"
      >
        <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide group-hover:text-[var(--text-tertiary)] transition-colors">
          {title}
        </span>
        <div className="flex items-center gap-1.5">
          {count !== undefined && (
            <span className="text-[10px] text-[var(--text-faint)]">{count}</span>
          )}
          <svg
            className={`w-3.5 h-3.5 text-[var(--text-faint)] transition-transform ${open ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

function ToolSummaryRow({ node }: { node: ViewNode }) {
  const meta = getToolMeta(node);
  const laneColor = LAYER_COLORS[node.layer as PipelineLayer] || LANE_COLORS[meta.lane as PipelineLaneName] || '#6366F1';

  return (
    <div className="flex items-center gap-2 px-2 py-2 rounded bg-[var(--overlay-bg)]">
      <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: laneColor }} />
      <div className="flex-1 min-w-0">
        <p className="text-[12px] text-[var(--text)] font-medium truncate">{node.name}</p>
        <p className="text-[10px] text-[var(--muted)] capitalize">{node.platform}{(() => {
          const p = node.platform || '';
          // Ingestion/orchestration: use jobCount (connectors/DAGs), not raw asset count
          if (['fivetran', 'airbyte', 'stitch'].includes(p)) {
            return meta.jobCount > 0 ? ` · ${meta.jobCount} connector${meta.jobCount !== 1 ? 's' : ''}` : '';
          }
          if (p === 'airflow') {
            return meta.jobCount > 0 ? ` · ${meta.jobCount} DAG${meta.jobCount !== 1 ? 's' : ''}` : '';
          }
          if (['dagster', 'prefect', 'n8n'].includes(p)) {
            return meta.jobCount > 0 ? ` · ${meta.jobCount} workflow${meta.jobCount !== 1 ? 's' : ''}` : '';
          }
          if (['metabase', 'looker', 'tableau', 'powerbi'].includes(p))
            return meta.assetCount > 0 ? ` · ${meta.assetCount} dashboards` : '';
          if (['github', 'gitlab', 'bitbucket'].includes(p))
            return meta.assetCount > 0 ? ` · ${meta.assetCount} repos` : '';
          return meta.assetCount > 0 ? ` · ${meta.assetCount} assets` : '';
        })()}</p>
      </div>
    </div>
  );
}

function EdgeInspector({
  edge,
  laneOverview,
}: {
  edge: ViewEdge;
  laneOverview: RenderedViewResponse | null;
}) {
  const meta = getEdgeMeta(edge);
  const style = SEMANTIC_EDGE_STYLES[meta.semanticType] || SEMANTIC_EDGE_STYLES.data_flow;
  const nodeMap = new Map((laneOverview?.nodes || []).map(n => [n.id, n]));
  const src = nodeMap.get(edge.sourceId);
  const tgt = nodeMap.get(edge.targetId);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <div className="w-5 h-0.5 rounded" style={{ backgroundColor: style.color }} />
          <span
            className="text-[13px] font-semibold"
            style={{ color: style.color }}
          >
            {style.label}
          </span>
          {meta.evidenceType && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--overlay-bg)] text-[var(--muted)] capitalize">
              {meta.evidenceType.replace(/_/g, ' ')}
            </span>
          )}
        </div>
        <p className="text-[12px] text-[var(--muted)]">
          {src?.name || edge.sourceId} → {tgt?.name || edge.targetId}
        </p>
      </div>

      {/* Flow stats */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Data Flows</label>
          <p className="text-2xl font-semibold text-[var(--text)] mt-1">{meta.dataFlowCount}</p>
        </div>
        {meta.flowAssetCount != null && meta.flowAssetCount > 0 && (
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Assets Involved</label>
            <p className="text-2xl font-semibold text-[var(--text)] mt-1">{meta.flowAssetCount}</p>
          </div>
        )}
      </div>

      {/* Confidence */}
      <div>
        <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Confidence</label>
        <div className="flex items-center gap-2 mt-2">
          <div className="flex-1 h-1.5 rounded-full bg-[var(--overlay-faint)] overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{
                width: `${edge.confidence * 100}%`,
                backgroundColor: edge.confidence >= 0.8 ? '#10B981' : edge.confidence >= 0.5 ? '#F59E0B' : '#EF4444',
              }}
            />
          </div>
          <span className="text-[12px] font-semibold text-[var(--text)] tabular-nums">
            {Math.round(edge.confidence * 100)}%
          </span>
        </div>
      </div>

      {/* Top Flows */}
      {meta.topPairs && meta.topPairs.length > 0 && (
        <Section title="Top Flows" count={meta.topPairs.length} defaultOpen>
          <div className="space-y-1">
            {meta.topPairs.map((pair, i) => (
              <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded bg-[var(--overlay-bg)]">
                <span className="text-[11px] text-[var(--text)] font-mono truncate flex-1">
                  {pair.src} → {pair.tgt}
                </span>
                <span className="text-[10px] text-[var(--muted)] tabular-nums shrink-0">
                  ×{pair.count}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Evidence Sources */}
      {meta.evidenceMix && Object.keys(meta.evidenceMix).length > 0 && (
        <Section title="Evidence Sources" count={Object.keys(meta.evidenceMix).length} defaultOpen>
          <div className="space-y-1">
            {Object.entries(meta.evidenceMix)
              .sort(([, a], [, b]) => b - a)
              .map(([source, count]) => (
                <div key={source} className="flex items-center justify-between px-2 py-1 rounded bg-[var(--overlay-bg)]">
                  <span className="text-[11px] text-[var(--text)] capitalize">
                    {source.replace(/_/g, ' ')}
                  </span>
                  <span className="text-[10px] text-[var(--muted)] tabular-nums">
                    {count}
                  </span>
                </div>
              ))}
          </div>
        </Section>
      )}

      {/* Edge Provenance */}
      {meta.edgeOrigin && (
        <div>
          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Provenance</label>
          <p className="text-[12px] text-[var(--text)] mt-1">
            {meta.edgeOrigin === 'evidence' && 'Derived from observed lineage evidence'}
            {meta.edgeOrigin === 'structural' && 'Derived from configured pipeline relationships'}
            {meta.edgeOrigin === 'inferred' && 'Inferred from weak matching or bridge rules'}
          </p>
          {meta.relationshipBasis && (
            <p className="text-[11px] text-[var(--muted)] mt-0.5">
              Basis: {RELATIONSHIP_BASIS_LABELS[meta.relationshipBasis] || meta.relationshipBasis}
            </p>
          )}
        </div>
      )}

      {/* Bypass Path Drilldown */}
      {meta.bypassPath && meta.bypassPath.jobs.length > 0 && (
        <Section title="Compressed Path" count={meta.bypassPath.jobs.length} defaultOpen>
          <p className="text-[11px] text-[var(--muted)] mb-2">{meta.bypassPath.summary}</p>
          <div className="space-y-1">
            {meta.bypassPath.jobs.map((job, i) => (
              <div key={i} className="px-2 py-1 rounded bg-[var(--overlay-bg)]">
                <span className="text-[11px] text-[var(--text)] font-mono">{job.jobNodeName}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Source & Target details */}
      <Section title="Source" defaultOpen>
        {src ? (
          <ToolSummaryRow node={src} />
        ) : (
          <p className="text-[12px] text-[var(--muted)] italic">Unknown node</p>
        )}
      </Section>

      <Section title="Target" defaultOpen>
        {tgt ? (
          <ToolSummaryRow node={tgt} />
        ) : (
          <p className="text-[12px] text-[var(--muted)] italic">Unknown node</p>
        )}
      </Section>
    </div>
  );
}


// ─── Main Panel ──────────────────────────────────────────────────────

export function InspectorPanel({
  target,
  laneOverview,
  stackId,
  allMonitors,
  onClose,
  onCreateSingleMonitor,
  onCreateMultiMonitor,
}: InspectorPanelProps) {
  if (!target) return null;

  return (
    <div className="w-80 border-l border-[var(--subtle-border)] bg-[var(--surface-sunken)] p-4 overflow-y-auto">
      {/* Close button */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-medium text-[var(--text)]">
          {target.kind === 'node' ? 'Tool Details' : target.kind === 'multi' ? `${target.nodes.length} Selected` : 'Flow Details'}
        </h3>
        <button
          onClick={onClose}
          className="p-1 hover:bg-[var(--subtle-bg)] rounded transition-colors"
        >
          <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      {target.kind === 'node' ? (
        <NodeInspector node={target.node} laneOverview={laneOverview} stackId={stackId} allMonitors={allMonitors} onCreateSingleMonitor={onCreateSingleMonitor} onCreateMultiMonitor={onCreateMultiMonitor} />
      ) : target.kind === 'multi' ? (
        <div className="space-y-4">
          <p className="text-[12px] text-[var(--muted)]">
            {target.nodes.length} nodes selected
          </p>
          <div className="space-y-1">
            {target.nodes.map(n => (
              <div key={n.id} className="px-2 py-1.5 rounded bg-[var(--overlay-bg)] flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] shrink-0" />
                <span className="text-[12px] text-[var(--text)] truncate">{n.name}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <EdgeInspector edge={target.edge} laneOverview={laneOverview} />
      )}
    </div>
  );
}
