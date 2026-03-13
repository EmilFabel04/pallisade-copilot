'use client';

import React, { useState, useMemo, useCallback, useEffect } from 'react';
import {
  ChevronDown,
  Table,
  Eye,
  ArrowDownToLine,
  Cog,
  AlertCircle,
  CheckCircle,
  Clock,
  Zap,
  ArrowRight,
  Workflow,
  Play,
  ShieldCheck,
  Plus,
  Sparkles,
} from 'lucide-react';
import type { MonitorPrefillData, WatchPrefillData } from '@/components/schedule/CreateTaskModal';
import {
  type UnifiedLineageNode,
  type UnifiedLineageEdge,
  type BlastRadiusResult,
  type OrchestrationContext,
  type UnifiedNodeCategory,
  CATEGORY_VISUALS,
  getConfidenceColor,
  getCrossLinkedOrchestration,
} from './types';

// Platform → color mapping for colored badges (mirrors UnifiedNodes.tsx PLATFORM_COLORS)
const _PLATFORM_BADGE_COLORS: Record<string, string> = {
  bigquery: '#3B82F6',
  snowflake: '#3B82F6',
  postgres: '#3B82F6',
  redshift: '#3B82F6',
  databricks: '#3B82F6',
  dbt: '#F59E0B',
  dbt_core: '#F59E0B',
  fivetran: '#10B981',
  airbyte: '#10B981',
  looker: '#8B5CF6',
  tableau: '#8B5CF6',
  metabase: '#8B5CF6',
  powerbi: '#8B5CF6',
  power_bi: '#8B5CF6',
};

interface MonitorRecommendation {
  monitor_key: string;
  target_fqn: string;
  target_node_id: string;
  source: 'direct' | 'upstream' | 'bundle';
  reason: string;
  priority: number;
  config_hints: Record<string, any>;
  integration_type: string;
  already_monitored: boolean;
}

interface DataAssetDetailPanelProps {
  node: UnifiedLineageNode;
  allNodes: UnifiedLineageNode[];
  allEdges: UnifiedLineageEdge[];
  stackId: string;
  onClose: () => void;
  onNodeNavigate: (nodeId: string) => void;
  onCreateMonitor?: (prefill: MonitorPrefillData) => void;
  onCreateWatch?: (prefill: WatchPrefillData) => void;
}

// ─── Collapsible Section ───────────────────────────────────────────
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
          <ChevronDown
            className={`w-3.5 h-3.5 text-[var(--text-faint)] transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </div>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

// ─── Category Icon (inline) ────────────────────────────────────────
function CategoryIcon({ category }: { category: UnifiedNodeCategory }) {
  const iconProps = { className: 'w-3 h-3' };
  switch (category) {
    case 'table':
      return <Table {...iconProps} />;
    case 'view':
      return <Eye {...iconProps} />;
    case 'source':
      return <ArrowDownToLine {...iconProps} />;
    case 'model':
      return <Cog {...iconProps} />;
    default:
      return <Table {...iconProps} />;
  }
}

// ─── Relationship Item ─────────────────────────────────────────────
function RelationshipItem({
  relNode,
  edge,
  direction,
  onNavigate,
}: {
  relNode: UnifiedLineageNode;
  edge: UnifiedLineageEdge;
  direction: 'upstream' | 'downstream';
  onNavigate: (id: string) => void;
}) {
  const visuals = CATEGORY_VISUALS[relNode.category] || CATEGORY_VISUALS.table;
  const shortName = relNode.tableName || relNode.name?.split('.').pop() || relNode.name;
  const evidenceSource = edge.evidence?.[0]?.adapterId || edge.edgeType?.replace(/_/g, ' ');

  return (
    <button
      onClick={() => onNavigate(relNode.id)}
      className="w-full text-left p-2 rounded-lg bg-[var(--overlay-faint)] hover:bg-[var(--hover-bg)] border border-[var(--border-faint)] hover:border-[var(--subtle-border)] transition-all"
    >
      <div className="flex items-center gap-2">
        <div style={{ color: visuals.color }}>
          <CategoryIcon category={relNode.category} />
        </div>
        <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1" title={relNode.fullName || relNode.name}>
          {shortName}
        </span>
        {edge.lineageLevel && edge.lineageLevel !== 'table' && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 shrink-0">
            {edge.lineageLevel}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 mt-1.5">
        {edge.confidence !== undefined && (
          <>
            <div className="flex-1 h-1 bg-[var(--overlay-medium)] rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${edge.confidence * 100}%`,
                  backgroundColor: getConfidenceColor(edge.confidence),
                }}
              />
            </div>
            <span className="text-[10px] text-[var(--muted)] shrink-0">
              {Math.round(edge.confidence * 100)}%
            </span>
          </>
        )}
        <span className="text-[10px] text-[var(--text-faint)] truncate shrink-0 max-w-[80px]" title={evidenceSource}>
          {evidenceSource}
        </span>
      </div>
    </button>
  );
}

// ─── Convert backend ViewNode/ViewEdge dicts to Unified types ─────
function _viewNodeToCategory(vn: any): UnifiedNodeCategory {
  if (vn.platformDomain === 'ingestion' &&
      (vn.originalType === 'table' || vn.originalType === 'source')) {
    return 'source';
  }
  const ot = vn.originalType as UnifiedNodeCategory;
  const known: UnifiedNodeCategory[] = [
    'table', 'view', 'source', 'model', 'dag', 'task', 'workflow',
    'connector', 'workbook', 'dataset', 'question', 'notebook',
    'file', 'test', 'dashboard', 'report',
  ];
  if (known.includes(ot)) return ot;
  switch (vn.canonicalType) {
    case 'dataset': return 'table';
    case 'semantic': return 'dashboard';
    case 'job': return 'workflow';
    case 'service': return vn.platformDomain === 'warehouse' ? 'table'
      : vn.platformDomain === 'transform' ? 'model'
      : vn.platformDomain === 'bi' ? 'dashboard'
      : 'table';
    default: return 'table';
  }
}

function viewNodeToUnified(vn: any): UnifiedLineageNode {
  return {
    id: `lineage-${vn.id}`,
    name: vn.name,
    fullName: vn.metadata?.fqn || vn.name,
    category: _viewNodeToCategory(vn),
    layer: (vn.layer || 'WAREHOUSE') as any,
    toolType: vn.platform || undefined,
    database: vn.metadata?.database || undefined,
    schema: vn.metadata?.schema || undefined,
    tableName: vn.name,
    platforms: vn.platform ? [vn.platform] : undefined,
  };
}

function viewEdgeToUnified(ve: any): UnifiedLineageEdge {
  return {
    id: ve.id,
    source: `lineage-${ve.sourceId || ve.source_id}`,
    target: `lineage-${ve.targetId || ve.target_id}`,
    edgeType: ve.canonicalType || ve.originalType || 'derives',
    confidence: ve.confidence,
    evidence: ve.evidenceRefs?.map((ref: string) => ({ adapterId: ref, sourceRef: ref })),
  };
}

type HopMap = Map<number, Array<{ node: UnifiedLineageNode; edge: UnifiedLineageEdge }>>;

// ─── Main Panel ────────────────────────────────────────────────────
export function DataAssetDetailPanel({
  node,
  allNodes,
  allEdges,
  stackId,
  onClose,
  onNodeNavigate,
  onCreateMonitor,
  onCreateWatch,
}: DataAssetDetailPanelProps) {
  const [blastRadius, setBlastRadius] = useState<BlastRadiusResult | null>(null);
  const [blastLoading, setBlastLoading] = useState(false);
  const [showAllUpstream, setShowAllUpstream] = useState(false);
  const [showAllDownstream, setShowAllDownstream] = useState(false);

  // Neighbors state — fetched from data_plane view endpoint
  const [neighborsLoading, setNeighborsLoading] = useState(true);
  const [upstreamByHop, setUpstreamByHop] = useState<HopMap>(new Map());
  const [downstreamByHop, setDownstreamByHop] = useState<HopMap>(new Map());
  const [totalUpstream, setTotalUpstream] = useState(0);
  const [totalDownstream, setTotalDownstream] = useState(0);
  const [allColumnMappings, setAllColumnMappings] = useState<Array<{ sourceName: string; from: string; to: string }>>([]);
  const [neighborSource, setNeighborSource] = useState<string>('');

  // Reset state when navigating to a different node
  useEffect(() => {
    setShowAllUpstream(false);
    setShowAllDownstream(false);
    setShowAllMonitors(false);
    setBlastRadius(null);
    setRecommendations(null);
  }, [node.id]);

  // Fetch neighbors from the data-plane adjacency endpoint
  useEffect(() => {
    if (!stackId) return;

    let cancelled = false;
    setNeighborsLoading(true);

    const engineId = node.id.replace(/^lineage-/, '');

    const fetchNeighbors = async () => {
      try {
        const [upRes, downRes] = await Promise.all([
          fetch(`/api/pipeline/${stackId}/lineage/engine?action=data-plane-neighbors&id=${encodeURIComponent(engineId)}&direction=upstream&depth=3`),
          fetch(`/api/pipeline/${stackId}/lineage/engine?action=data-plane-neighbors&id=${encodeURIComponent(engineId)}&direction=downstream&depth=3`),
        ]);

        if (cancelled) return;

        const upData = upRes.ok ? await upRes.json() : { neighbors: [], totalCount: 0, source: 'error' };
        const downData = downRes.ok ? await downRes.json() : { neighbors: [], totalCount: 0, source: 'error' };

        if (cancelled) return;

        const convertToHopMap = (data: any): HopMap => {
          const hopMap: HopMap = new Map();
          for (const hopGroup of data.neighbors || []) {
            const items = (hopGroup.items || []).map((item: any) => ({
              node: viewNodeToUnified(item.node),
              edge: viewEdgeToUnified(item.edge),
            }));
            if (items.length > 0) {
              hopMap.set(hopGroup.hop, items);
            }
          }
          return hopMap;
        };

        setUpstreamByHop(convertToHopMap(upData));
        setDownstreamByHop(convertToHopMap(downData));
        setTotalUpstream(upData.totalCount || 0);
        setTotalDownstream(downData.totalCount || 0);
        setNeighborSource(upData.source || downData.source || '');

        // Extract column mappings from hop-1 upstream edges (from allEdges as ViewEdge metadata doesn't carry columns yet)
        const colMappings: Array<{ sourceName: string; from: string; to: string }> = [];
        const nodeMap = new Map(allNodes.map((n) => [n.id, n]));
        const dataEdges = allEdges.filter(
          (e) =>
            e.edgeType !== 'pipeline_flow' &&
            e.edgeType !== 'contains' &&
            e.edgeType !== 'produces' &&
            e.edgeType !== 'reads_from'
        );
        const directUpEdges = dataEdges.filter((e) => e.target === node.id);
        for (const edge of directUpEdges) {
          if (edge.columns) {
            const srcNode = nodeMap.get(edge.source);
            for (const col of edge.columns) {
              if (typeof col === 'object' && col.from && col.to) {
                colMappings.push({
                  sourceName: srcNode?.tableName || srcNode?.name?.split('.').pop() || srcNode?.name || '',
                  from: col.from,
                  to: col.to,
                });
              }
            }
          }
        }
        setAllColumnMappings(colMappings);
      } catch (err) {
        console.error('[DataAssetDetailPanel] Failed to fetch neighbors:', err);
      } finally {
        if (!cancelled) setNeighborsLoading(false);
      }
    };

    fetchNeighbors();
    return () => { cancelled = true; };
  }, [node.id, stackId, allNodes, allEdges]);

  // Blast radius — lazy loaded on button click
  const fetchBlastRadius = useCallback(async () => {
    if (!stackId || blastLoading) return;
    setBlastLoading(true);
    try {
      // Strip the lineage- prefix used in the frontend
      const engineId = node.id.replace(/^lineage-/, '');
      const res = await fetch(
        `/api/pipeline/${stackId}/lineage/engine?action=blast-radius&id=${encodeURIComponent(engineId)}`
      );
      if (res.ok) {
        const data = await res.json();
        setBlastRadius(data);
      }
    } catch {
      // silent
    } finally {
      setBlastLoading(false);
    }
  }, [stackId, node.id, blastLoading]);

  // Orchestration context — find cross-linked DAGs/tasks
  const orchContexts = useMemo(
    () => getCrossLinkedOrchestration(node.id, allEdges, allNodes),
    [node.id, allEdges, allNodes]
  );

  const VISIBLE_LIMIT = 6;
  const MONITOR_VISIBLE_LIMIT = 5;
  const [showAllMonitors, setShowAllMonitors] = useState(false);

  // Monitor recommendations
  const [recommendations, setRecommendations] = useState<MonitorRecommendation[] | null>(null);
  const [recsLoading, setRecsLoading] = useState(false);

  const hasIssues = node.issues && node.issues.total > 0;
  const hasCritical = node.issues && node.issues.critical > 0;
  const isStale = node.freshnessStatus === 'stale';

  return (
    <div className="w-80 border-l border-[var(--subtle-border)] bg-[var(--surface-inset)] p-4 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-medium text-[var(--text)]">Data Asset Details</h3>
        <button onClick={onClose} className="p-1 hover:bg-[var(--subtle-bg)] rounded">
          <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="space-y-4">
        {/* Name */}
        <div>
          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Name</label>
          <p className="text-[13px] text-[var(--text)] font-mono mt-1 break-all">
            {node.fullName || node.name}
          </p>
        </div>

        {/* Type and Layer */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Type</label>
            <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{node.category}</p>
          </div>
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Layer</label>
            <p className="text-[13px] text-[var(--text)] mt-1">{node.layer}</p>
          </div>
        </div>

        {/* Health Status Card */}
        <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Health Status</span>
            {node.freshnessStatus === 'fresh' && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 text-[10px] font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Fresh
              </span>
            )}
            {isStale && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 text-[10px] font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                Stale
              </span>
            )}
            {node.freshnessStatus === 'unknown' && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--overlay-medium)] text-[var(--muted)] text-[10px] font-medium">
                Unknown
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 text-[12px]">
            <div>
              <span className="text-[var(--muted)]">Last Updated</span>
              <p className="text-[var(--text)] mt-0.5">
                {node.lastUpdated
                  ? node.freshnessHours !== undefined
                    ? node.freshnessHours < 1
                      ? 'Just now'
                      : node.freshnessHours < 24
                      ? `${node.freshnessHours}h ago`
                      : `${Math.round(node.freshnessHours / 24)}d ago`
                    : new Date(node.lastUpdated).toLocaleDateString()
                  : 'Unknown'}
              </p>
            </div>
            <div>
              <span className="text-[var(--muted)]">Row Count</span>
              <p className="text-[var(--text)] mt-0.5">
                {node.rowCount?.toLocaleString() ?? '\u2014'}
              </p>
            </div>
          </div>
        </div>

        {/* Issues Section */}
        {hasIssues && (
          <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Issues</span>
              <span className="text-[12px] text-[var(--text)] font-medium">{node.issues!.open} open</span>
            </div>
            <div className="flex items-center gap-2 mb-3">
              {node.issues!.critical > 0 && (
                <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-red-500/20">
                  <span className="w-2 h-2 rounded-full bg-red-500" />
                  <span className="text-[11px] text-red-300 font-medium">{node.issues!.critical} Critical</span>
                </div>
              )}
              {node.issues!.high > 0 && (
                <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-orange-500/20">
                  <span className="w-2 h-2 rounded-full bg-orange-500" />
                  <span className="text-[11px] text-orange-300 font-medium">{node.issues!.high} High</span>
                </div>
              )}
              {node.issues!.medium > 0 && (
                <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-yellow-500/20">
                  <span className="w-2 h-2 rounded-full bg-yellow-500" />
                  <span className="text-[11px] text-yellow-300 font-medium">{node.issues!.medium} Med</span>
                </div>
              )}
              {node.issues!.low > 0 && (
                <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-[var(--overlay-medium)]">
                  <span className="w-2 h-2 rounded-full bg-[var(--muted)]" />
                  <span className="text-[11px] text-[var(--text-tertiary)] font-medium">{node.issues!.low} Low</span>
                </div>
              )}
            </div>
            {Object.keys(node.issues!.byType).length > 0 && (
              <div className="pt-2 border-t border-[var(--subtle-border)]">
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(node.issues!.byType).map(([type, count]) => (
                    <span key={type} className="px-2 py-0.5 text-[10px] bg-[var(--subtle-bg)] text-[var(--text-tertiary)] rounded capitalize">
                      {type}: {count}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* No issues — only show if there's also no upstream failure */}
        {!hasIssues && !node.hasUpstreamFailure && (
          <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-4 h-4 text-emerald-400" />
              <span className="text-[12px] text-emerald-400 font-medium">No open issues</span>
            </div>
          </div>
        )}

        {/* Upstream failure banner */}
        {node.hasUpstreamFailure && (
          <div className="px-2 py-1.5 rounded bg-red-500/10 border border-red-500/20 flex items-center gap-2">
            <AlertCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
            <span className="text-[11px] text-red-300">An upstream dependency has a failing monitor</span>
          </div>
        )}

        {/* Monitors Section */}
        {node.monitorStatus && node.monitorStatus.total > 0 && (
          <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Monitors</span>
              <div className="flex items-center gap-1.5">
                {node.monitorStatus.failing > 0 && (
                  <span className="px-1.5 py-0.5 text-[10px] font-medium bg-red-500/20 text-red-300 rounded">
                    {node.monitorStatus.failing} failing
                  </span>
                )}
                {node.monitorStatus.error > 0 && (
                  <span className="px-1.5 py-0.5 text-[10px] font-medium bg-red-500/20 text-red-300 rounded">
                    {node.monitorStatus.error} error
                  </span>
                )}
                {node.monitorStatus.warning > 0 && (
                  <span className="px-1.5 py-0.5 text-[10px] font-medium bg-amber-500/20 text-amber-300 rounded">
                    {node.monitorStatus.warning} warn
                  </span>
                )}
                {node.monitorStatus.passing > 0 && (
                  <span className="px-1.5 py-0.5 text-[10px] font-medium bg-emerald-500/20 text-emerald-300 rounded">
                    {node.monitorStatus.passing} pass
                  </span>
                )}
              </div>
            </div>
            <div className="space-y-1.5">
              {(showAllMonitors
                ? node.monitorStatus.monitors
                : node.monitorStatus.monitors.slice(0, MONITOR_VISIBLE_LIMIT)
              ).map((m) => {
                const statusColor = m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR'
                  ? '#EF4444'
                  : m.lastStatus === 'WARN'
                  ? '#F59E0B'
                  : m.lastStatus === 'PASS'
                  ? '#10B981'
                  : '#6B7280';
                const lastEval = m.lastRunAt
                  ? (() => {
                      const hoursAgo = Math.round((Date.now() - new Date(m.lastRunAt).getTime()) / (1000 * 60 * 60));
                      if (hoursAgo < 1) return 'Just now';
                      if (hoursAgo < 24) return `${hoursAgo}h ago`;
                      return `${Math.round(hoursAgo / 24)}d ago`;
                    })()
                  : 'Never';
                return (
                  <a
                    key={m.id}
                    href={`/dashboard/schedule?monitor=${m.id}`}
                    className="block p-2 rounded-lg bg-[var(--overlay-faint)] hover:bg-[var(--hover-bg)] border border-[var(--border-faint)] hover:border-[var(--subtle-border)] transition-all"
                  >
                    <div className="flex items-center gap-2">
                      <div
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: statusColor }}
                      />
                      <span className="text-[12px] text-[var(--text)] truncate flex-1" title={m.name}>
                        {m.name}
                      </span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--text-faint)] shrink-0 uppercase">
                        {m.monitorType}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-[var(--muted)]">
                        Last evaluated {lastEval}
                      </span>
                    </div>
                    {m.lastMessage && (
                      <p className="text-[10px] text-[var(--text-faint)] mt-1 truncate" title={m.lastMessage}>
                        {m.lastMessage}
                      </p>
                    )}
                  </a>
                );
              })}
            </div>
            {!showAllMonitors && node.monitorStatus.monitors.length > MONITOR_VISIBLE_LIMIT && (
              <button
                onClick={() => setShowAllMonitors(true)}
                className="w-full text-center text-[11px] text-[var(--muted)] hover:text-[var(--text-tertiary)] py-1.5 mt-1.5 transition-colors"
              >
                Show all {node.monitorStatus.monitors.length} monitors
              </button>
            )}
          </div>
        )}

        {/* ─── Recommended Monitors ────────────────────────── */}
        {onCreateMonitor && (() => {
          const isBiNode = ['dashboard', 'report', 'workbook', 'question', 'dataset'].includes(node.category);
          const nodeTypeLabel = node.category === 'dashboard' ? 'dashboard'
            : node.category === 'report' ? 'report'
            : node.category === 'workbook' ? 'workbook'
            : node.category === 'question' ? 'question'
            : 'asset';

          // Monitor types to recommend per upstream node type (DB lineage fallback)
          const UPSTREAM_MONITOR_MAP: Record<string, Array<{ monitor_key: string; priority: number }>> = {
            table: [{ monitor_key: 'FRESHNESS', priority: 2 }, { monitor_key: 'SCHEMA_CHANGE', priority: 3 }],
            view: [{ monitor_key: 'FRESHNESS', priority: 2 }],
            materialized_view: [{ monitor_key: 'FRESHNESS', priority: 2 }],
            source: [{ monitor_key: 'FRESHNESS', priority: 2 }],
            model: [{ monitor_key: 'DBT_TEST_FAILURES', priority: 2 }, { monitor_key: 'FRESHNESS', priority: 3 }],
          };

          // Shared fetch helper — tries engine first, falls back to DB lineage
          const fetchRecs = () => {
            if (recommendations || recsLoading) return;
            setRecsLoading(true);
            const engineId = node.id.replace(/^lineage-/, '');
            const anchorFqn = node.fullName || node.name;
            const existingFqns = (node.monitorStatus?.monitors || [])
              .map((m: any) => `${m.monitorType}:${anchorFqn}`)
              .join(',');

            const parseEngineData = (data: any): MonitorRecommendation[] => {
              const topLevel = data?.recommendations || [];
              const bundleRecs = (data?.bundles || []).flatMap((b: any) => b.recommendations || []);
              const seen = new Set<string>();
              return [...topLevel, ...bundleRecs].filter((r: any) => {
                const key = `${r.monitor_key}:${r.target_fqn}`;
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
              });
            };

            // Fallback: generate recommendations from physical data lineage (upstreamByHop)
            const buildFromPhysicalLineage = () => {
              const recs: MonitorRecommendation[] = [];
              const seen = new Set<string>();
              for (const [, items] of upstreamByHop.entries()) {
                for (const { node: upNode } of items) {
                  const fqn = upNode.fullName || upNode.name;
                  const nt = (upNode.nodeType || upNode.category || 'table').toLowerCase();
                  const specs = UPSTREAM_MONITOR_MAP[nt] || UPSTREAM_MONITOR_MAP['table'];
                  for (const spec of specs) {
                    const key = `${spec.monitor_key}:${fqn}`;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    recs.push({
                      monitor_key: spec.monitor_key,
                      target_fqn: fqn,
                      target_node_id: upNode.id,
                      source: 'upstream',
                      reason: `Upstream dependency of ${anchorFqn.split('.').pop()}`,
                      priority: spec.priority,
                      config_hints: {},
                      integration_type: '',
                      already_monitored: false,
                    } as MonitorRecommendation);
                  }
                }
              }
              setRecommendations(recs);
              setRecsLoading(false);
            };

            fetch(`/api/pipeline/${stackId}/lineage/engine?action=recommend-monitors&id=${encodeURIComponent(engineId)}&depth=3${existingFqns ? `&existing_fqns=${encodeURIComponent(existingFqns)}` : ''}`)
              .then((res) => res.ok ? res.json() : null)
              .then((data) => {
                const merged = parseEngineData(data);
                if (merged.length > 0) {
                  setRecommendations(merged);
                  setRecsLoading(false);
                } else {
                  // Engine returned nothing — try DB lineage fallback
                  buildFromPhysicalLineage();
                }
              })
              .catch(() => {
                // Engine unavailable — try DB lineage fallback
                buildFromPhysicalLineage();
              });
          };

          // Shared recommendation card renderer
          const renderRecCard = (rec: MonitorRecommendation, i: number) => {
            const priorityColor = rec.priority === 1 ? 'text-red-300' : rec.priority === 2 ? 'text-amber-300' : 'text-[var(--muted)]';
            return (
              <div
                key={`${rec.monitor_key}-${rec.target_fqn}-${i}`}
                className={`p-2 rounded-lg border transition-all ${
                  rec.already_monitored
                    ? 'bg-emerald-500/5 border-emerald-500/15'
                    : 'bg-[var(--overlay-faint)] border-[var(--border-faint)] hover:bg-[var(--hover-bg)]'
                }`}
              >
                <div className="flex items-center gap-2">
                  {rec.already_monitored ? (
                    <CheckCircle className="w-3 h-3 text-emerald-400 shrink-0" />
                  ) : (
                    <ShieldCheck className={`w-3 h-3 ${priorityColor} shrink-0`} />
                  )}
                  <span className="text-[11px] text-[var(--text)] truncate flex-1">
                    {rec.monitor_key.replace(/_/g, ' ')}
                  </span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--text-faint)] shrink-0">
                    {rec.source}
                  </span>
                </div>
                <p className="text-[10px] text-[var(--text-faint)] mt-1 line-clamp-2">{rec.reason}</p>
                {rec.target_fqn !== (node.fullName || node.name) && (
                  <p className="text-[10px] text-[var(--muted)] mt-0.5 font-mono truncate" title={rec.target_fqn}>
                    {rec.target_fqn}
                  </p>
                )}
                {!rec.already_monitored && (
                  <button
                    onClick={() => onCreateMonitor({
                      name: `${rec.monitor_key.toLowerCase().replace(/_/g, ' ')} — ${rec.target_fqn.split('.').pop()}`,
                      monitorType: rec.monitor_key,
                      targetFqn: rec.target_fqn,
                      config: rec.config_hints,
                    })}
                    className="mt-1 flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-500/10 border border-blue-500/20 hover:bg-blue-500/20 transition-all text-[9px] text-blue-300"
                  >
                    <Plus className="w-2 h-2" />
                    Create
                  </button>
                )}
                {rec.already_monitored && (
                  <span className="block mt-1 text-[10px] text-emerald-400/60">Already covered</span>
                )}
              </div>
            );
          };

          /* ─── BI/Reporting node path ─────────────────────────── */
          if (isBiNode) {
            return (
              <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide flex items-center gap-1.5">
                    <Sparkles className="w-3 h-3" />
                    Monitoring
                  </span>
                </div>

                {/* Two actions: Monitor + Health Watch */}
                <div className="flex gap-1.5">
                  {onCreateMonitor && (
                    <button
                      onClick={() => onCreateMonitor({
                        name: `Monitor — ${node.tableName || node.name}`,
                        monitorType: 'BI_FRESHNESS_PROXY',
                        targetFqn: node.fullName || node.name,
                      })}
                      className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded bg-[var(--overlay-strong)] hover:bg-[var(--hover-bg)] transition-all text-[10px] text-[var(--text)] font-medium"
                    >
                      <Plus className="w-3 h-3" />
                      Create Monitor
                    </button>
                  )}
                  {onCreateWatch && (
                    <button
                      onClick={() => {
                        onCreateWatch({
                          anchorFqn: node.fullName || node.name,
                          anchorNodeId: node.id.replace(/^lineage-/, ''),
                          anchorNodeType: node.category,
                          watchType: 'dashboard_shield',
                          monitors: [],
                        });
                      }}
                      className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded bg-blue-500/10 border border-blue-500/20 hover:bg-blue-500/20 transition-all text-[10px] text-blue-300 font-medium"
                    >
                      <ShieldCheck className="w-3 h-3" />
                      Health Watch
                    </button>
                  )}
                </div>
              </div>
            );
          }

          /* ─── Non-BI node path ─────────────────────────────── */
          const defaultMonitorType = node.category === 'connector' ? 'SYNC_LAG'
            : ['dag', 'task', 'workflow'].includes(node.category) ? 'DAG_LAST_RUN'
            : ['model'].includes(node.category) && node.platforms?.includes('dbt') ? 'DBT_TEST_FAILURES'
            : 'FRESHNESS';
          const defaultWatchType = node.category === 'connector' ? 'source_guard' as const
            : ['model'].includes(node.category) && node.platforms?.includes('dbt') ? 'model_quality' as const
            : 'pipeline_health' as const;

          return (
            <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide flex items-center gap-1.5">
                  <Sparkles className="w-3 h-3" />
                  Monitoring
                </span>
              </div>

              {/* Two actions: Monitor + Health Watch */}
              <div className="flex gap-1.5">
                {onCreateMonitor && (
                  <button
                    onClick={() => onCreateMonitor({
                      name: `${defaultMonitorType.toLowerCase().replace(/_/g, ' ')} — ${node.tableName || node.name}`,
                      monitorType: defaultMonitorType,
                      targetFqn: node.fullName || node.name,
                    })}
                    className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded bg-[var(--overlay-strong)] hover:bg-[var(--hover-bg)] transition-all text-[10px] text-[var(--text)] font-medium"
                  >
                    <Plus className="w-3 h-3" />
                    Create Monitor
                  </button>
                )}
                {onCreateWatch && (
                  <button
                    onClick={() => {
                      onCreateWatch({
                        anchorFqn: node.fullName || node.name,
                        anchorNodeId: node.id.replace(/^lineage-/, ''),
                        anchorNodeType: node.category,
                        watchType: defaultWatchType,
                        monitors: [],
                      });
                    }}
                    className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded bg-blue-500/10 border border-blue-500/20 hover:bg-blue-500/20 transition-all text-[10px] text-blue-300 font-medium"
                  >
                    <ShieldCheck className="w-3 h-3" />
                    Health Watch
                  </button>
                )}
              </div>
            </div>
          );
        })()}

        {/* Fallback warning */}
        {neighborSource === 'engine_fallback' && (
          <div className="px-2 py-1.5 rounded bg-amber-500/10 border border-amber-500/20 text-[10px] text-amber-300">
            Showing fallback data — run a build for accurate results
          </div>
        )}

        {/* ─── Upstream ──────────────────────────────────────── */}
        <Section title="Upstream" count={neighborsLoading ? undefined : totalUpstream} defaultOpen={true}>
          {neighborsLoading ? (
            <div className="flex items-center justify-center gap-2 py-3 text-[12px] text-[var(--muted)]">
              <div className="w-3.5 h-3.5 border-2 border-[var(--overlay-strong)] border-t-white/60 rounded-full animate-spin" />
              Loading...
            </div>
          ) : totalUpstream === 0 ? (
            <div className="py-2 text-[12px] text-emerald-400/70 flex items-center gap-1.5">
              <ArrowDownToLine className="w-3.5 h-3.5" />
              Root source — no upstream dependencies
            </div>
          ) : (
            <div className="space-y-3">
              {Array.from(upstreamByHop.entries())
                .sort(([a], [b]) => a - b)
                .map(([hop, items]) => {
                  const visible = showAllUpstream ? items : items.slice(0, VISIBLE_LIMIT);
                  return (
                    <div key={hop}>
                      <div className="text-[10px] text-[var(--text-faint)] uppercase tracking-wide mb-1.5">
                        Hop {hop} <span className="text-[var(--text-faint)]">({items.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {visible.map(({ node: relNode, edge }) => (
                          <RelationshipItem
                            key={relNode.id}
                            relNode={relNode}
                            edge={edge}
                            direction="upstream"
                            onNavigate={onNodeNavigate}
                          />
                        ))}
                      </div>
                      {!showAllUpstream && items.length > VISIBLE_LIMIT && (
                        <button
                          onClick={() => setShowAllUpstream(true)}
                          className="w-full text-center text-[11px] text-[var(--muted)] hover:text-[var(--text-tertiary)] py-1.5 transition-colors"
                        >
                          Show all {items.length} at hop {hop}
                        </button>
                      )}
                    </div>
                  );
                })}
            </div>
          )}
        </Section>

        {/* ─── Downstream ────────────────────────────────────── */}
        <Section title="Downstream" count={neighborsLoading ? undefined : totalDownstream} defaultOpen={true}>
          {neighborsLoading ? (
            <div className="flex items-center justify-center gap-2 py-3 text-[12px] text-[var(--muted)]">
              <div className="w-3.5 h-3.5 border-2 border-[var(--overlay-strong)] border-t-white/60 rounded-full animate-spin" />
              Loading...
            </div>
          ) : totalDownstream === 0 ? (
            <div className="py-2 text-[12px] text-amber-400/70 flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5" />
              Leaf node — no downstream consumers
            </div>
          ) : (
            <div className="space-y-3">
              {Array.from(downstreamByHop.entries())
                .sort(([a], [b]) => a - b)
                .map(([hop, items]) => {
                  const visible = showAllDownstream ? items : items.slice(0, VISIBLE_LIMIT);
                  return (
                    <div key={hop}>
                      <div className="text-[10px] text-[var(--text-faint)] uppercase tracking-wide mb-1.5">
                        Hop {hop} <span className="text-[var(--text-faint)]">({items.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {visible.map(({ node: relNode, edge }) => (
                          <RelationshipItem
                            key={relNode.id}
                            relNode={relNode}
                            edge={edge}
                            direction="downstream"
                            onNavigate={onNodeNavigate}
                          />
                        ))}
                      </div>
                      {!showAllDownstream && items.length > VISIBLE_LIMIT && (
                        <button
                          onClick={() => setShowAllDownstream(true)}
                          className="w-full text-center text-[11px] text-[var(--muted)] hover:text-[var(--text-tertiary)] py-1.5 transition-colors"
                        >
                          Show all {items.length} at hop {hop}
                        </button>
                      )}
                    </div>
                  );
                })}
            </div>
          )}
        </Section>

        {/* ─── Column Lineage ────────────────────────────────── */}
        {allColumnMappings.length > 0 && (
          <Section title="Column Lineage" count={allColumnMappings.length}>
            <div className="space-y-1">
              {allColumnMappings.map((m, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[11px] font-mono py-1 px-2 rounded bg-[var(--overlay-faint)]">
                  <span className="text-[var(--muted)] truncate max-w-[70px]" title={m.sourceName}>
                    {m.sourceName}
                  </span>
                  <span className="text-[var(--text-faint)]">.</span>
                  <span className="text-[var(--text-tertiary)]">{m.from}</span>
                  <ArrowRight className="w-3 h-3 text-[var(--text-faint)] shrink-0" />
                  <span className="text-[var(--text-secondary)]">{m.to}</span>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* ─── Blast Radius ──────────────────────────────────── */}
        <Section title="Impact Analysis">
          {!blastRadius && !blastLoading && (
            <button
              onClick={fetchBlastRadius}
              className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)] hover:border-[var(--border-medium)] transition-all text-[12px] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            >
              <Zap className="w-3.5 h-3.5" />
              Analyze Impact
            </button>
          )}
          {blastLoading && (
            <div className="flex items-center justify-center gap-2 py-3 text-[12px] text-[var(--muted)]">
              <div className="w-3.5 h-3.5 border-2 border-[var(--overlay-strong)] border-t-white/60 rounded-full animate-spin" />
              Analyzing...
            </div>
          )}
          {blastRadius && (
            <div className="space-y-2.5">
              {/* Summary */}
              <div className="p-2.5 rounded-lg bg-[var(--overlay-bg)] border border-[var(--border-faint)]">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Affected Assets</span>
                  <span className="text-[16px] text-[var(--text)] font-semibold">{blastRadius.total_downstream}</span>
                </div>
                {Object.keys(blastRadius.by_kind || {}).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {Object.entries(blastRadius.by_kind).map(([kind, count]) => (
                      <span key={kind} className="px-2 py-0.5 text-[10px] bg-[var(--subtle-bg)] text-[var(--text-tertiary)] rounded capitalize">
                        {count} {kind}{count !== 1 ? 's' : ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Affected nodes with impact descriptions */}
              {blastRadius.affected && blastRadius.affected.length > 0 && (
                <div className="space-y-1.5 max-h-52 overflow-y-auto">
                  {blastRadius.affected.slice(0, 15).map((a) => {
                    const isCritical = a.criticality === 'critical' || a.criticality === 'high';
                    return (
                      <button
                        key={a.id}
                        onClick={() => onNodeNavigate(a.id)}
                        className="w-full text-left p-2 rounded-lg bg-[var(--overlay-faint)] hover:bg-[var(--hover-bg)] border border-[var(--border-faint)] transition-all"
                      >
                        <div className="flex items-center gap-2">
                          {isCritical && (
                            <AlertCircle className="w-3 h-3 text-red-400 shrink-0" />
                          )}
                          <span className="text-[11px] text-[var(--text)] font-mono truncate flex-1">
                            {a.name}
                          </span>
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--text-faint)] capitalize shrink-0">
                            {a.kind}
                          </span>
                        </div>
                        <div className="text-[10px] text-[var(--muted)] mt-1">
                          {a.impact}
                        </div>
                      </button>
                    );
                  })}
                  {blastRadius.affected.length > 15 && (
                    <div className="text-[10px] text-[var(--text-faint)] text-center py-1">
                      + {blastRadius.affected.length - 15} more
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </Section>

        {/* ─── Orchestration Context ────────────────────────── */}
        {orchContexts.length > 0 && (
          <Section title="Orchestration" count={orchContexts.length} defaultOpen={true}>
            <div className="space-y-2">
              {orchContexts.map((ctx, i) => {
                const orchNode = ctx.taskNode || ctx.dagNode;
                if (!orchNode) return null;
                const isTask = !!ctx.taskNode;
                return (
                  <div
                    key={i}
                    className="p-2.5 rounded-lg bg-orange-500/[0.06] border border-orange-500/[0.12]"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      {isTask ? (
                        <Play className="w-3.5 h-3.5 text-orange-300" />
                      ) : (
                        <Workflow className="w-3.5 h-3.5 text-orange-300" />
                      )}
                      <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">
                        {orchNode.name}
                      </span>
                      <span className="text-[10px] text-orange-300/60 capitalize">
                        {ctx.edgeType.replace(/_/g, ' ')}
                      </span>
                    </div>

                    {/* Run summary */}
                    {ctx.runSummary && (
                      <div className="space-y-1.5 mt-2 pt-2 border-t border-orange-500/[0.08]">
                        {ctx.runSummary.lastRunState && (
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] text-[var(--muted)]">Last Run</span>
                            <span className={`
                              px-1.5 py-0.5 text-[10px] font-medium rounded
                              ${ctx.runSummary.lastRunState === 'success'
                                ? 'bg-emerald-500/20 text-emerald-300'
                                : ctx.runSummary.lastRunState === 'failed'
                                ? 'bg-red-500/20 text-red-300'
                                : 'bg-blue-500/20 text-blue-300'}
                            `}>
                              {ctx.runSummary.lastRunState}
                            </span>
                          </div>
                        )}
                        {ctx.runSummary.lastRunDate && (
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] text-[var(--muted)]">When</span>
                            <span className="text-[10px] text-[var(--text-tertiary)]">
                              {new Date(ctx.runSummary.lastRunDate).toLocaleString()}
                            </span>
                          </div>
                        )}
                        {ctx.runSummary.successRate !== undefined && (
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] text-[var(--muted)]">Success Rate</span>
                            <span className="text-[10px] text-[var(--text-tertiary)]">
                              {Math.round(ctx.runSummary.successRate)}%
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* ─── Location ──────────────────────────────────────── */}
        <div className="space-y-3 border-t border-[var(--subtle-border)] pt-3">
          {node.database && (
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Database</label>
              <p className="text-[13px] text-[var(--text)] font-mono mt-1">{node.database}</p>
            </div>
          )}
          {node.schema && (
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Schema/Dataset</label>
              <p className="text-[13px] text-[var(--text)] font-mono mt-1">{node.schema}</p>
            </div>
          )}
        </div>

        {/* ─── dbt Transformation Details ──────────────────── */}
        {(node.materialization || node.platforms?.includes('dbt')) && (
          <div className="space-y-3 border-t border-[var(--subtle-border)] pt-3">
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">
              Transformation
            </label>
            {node.materialization && (
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-[var(--muted)]">Materialization</span>
                <span className="px-2 py-0.5 text-[11px] font-medium capitalize bg-amber-500/15 text-amber-300 rounded">
                  {node.materialization}
                </span>
              </div>
            )}
            {node.nodeType && node.nodeType !== node.category && (
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-[var(--muted)]">Resource Type</span>
                <span className="text-[13px] text-[var(--text)] capitalize">{node.nodeType}</span>
              </div>
            )}
          </div>
        )}

        {/* ─── Platforms (multi-platform provenance) ────────── */}
        {node.platforms && node.platforms.length > 0 && (
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Discovered In</label>
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {node.platforms.map((p) => {
                const color = _PLATFORM_BADGE_COLORS[p.toLowerCase()] || '#94A3B8';
                return (
                  <span
                    key={p}
                    className="px-2 py-1 text-[11px] font-semibold capitalize rounded"
                    style={{
                      backgroundColor: `${color}20`,
                      color: color,
                      border: `1px solid ${color}40`,
                    }}
                  >
                    {p}
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {/* Criticality & Owner */}
        <div className="grid grid-cols-2 gap-3">
          {node.criticality && (
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Criticality</label>
              <p
                className={`text-[13px] mt-1 font-medium ${
                  node.criticality === 'HIGH' || node.criticality === 'CRITICAL'
                    ? 'text-red-400'
                    : node.criticality === 'MEDIUM'
                    ? 'text-amber-400'
                    : 'text-[var(--text-tertiary)]'
                }`}
              >
                {node.criticality}
              </p>
            </div>
          )}
          {node.owner && (
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Owner</label>
              <p className="text-[13px] text-[var(--text)] mt-1">{node.owner}</p>
            </div>
          )}
        </div>

        {/* Tags */}
        {node.tags && node.tags.length > 0 && (
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Tags</label>
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {node.tags.map((tag, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 text-[11px] bg-[var(--accent)]/20 text-[var(--accent-2)] rounded"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Description */}
        {node.description && (
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Description</label>
            <p className="text-[13px] text-[var(--text-tertiary)] mt-1">{node.description}</p>
          </div>
        )}

        {/* ─── Column Schema ──────────────────────────────── */}
        {node.columns && node.columns.length > 0 && (
          <Section title="Columns" count={node.columns.length}>
            <div className="space-y-0.5 max-h-48 overflow-y-auto">
              {node.columns.map((col, i) => (
                <div key={i} className="flex items-center justify-between py-1 px-2 rounded bg-[var(--overlay-faint)]">
                  <span className="text-[11px] text-[var(--text-secondary)] font-mono">{col.name}</span>
                  {col.type && (
                    <span className="text-[10px] text-[var(--text-faint)] font-mono">{col.type}</span>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* ─── SQL Definition ─────────────────────────────── */}
        {node.sqlDefinition && (
          <Section title="SQL Definition">
            <pre className="text-[11px] text-[var(--text-tertiary)] font-mono bg-[var(--overlay-bg)] p-2 rounded overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-all">
              {node.sqlDefinition}
            </pre>
          </Section>
        )}
      </div>
    </div>
  );
}
