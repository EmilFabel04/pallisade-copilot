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
} from 'lucide-react';
import {
  type UnifiedLineageNode,
  type UnifiedLineageEdge,
  type BlastRadiusResult,
  type OrchestrationContext,
  type UnifiedNodeCategory,
  CATEGORY_VISUALS,
  getConfidenceColor,
  formatColumnMapping,
  getCrossLinkedOrchestration,
} from './types';

interface DataAssetDetailPanelProps {
  node: UnifiedLineageNode;
  allNodes: UnifiedLineageNode[];
  allEdges: UnifiedLineageEdge[];
  stackId: string;
  onClose: () => void;
  onNodeNavigate: (nodeId: string) => void;
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
    <div className="border-t border-white/[0.06] pt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full group"
      >
        <span className="text-[11px] text-white/40 uppercase tracking-wide group-hover:text-white/60 transition-colors">
          {title}
        </span>
        <div className="flex items-center gap-1.5">
          {count !== undefined && (
            <span className="text-[10px] text-white/30">{count}</span>
          )}
          <ChevronDown
            className={`w-3.5 h-3.5 text-white/30 transition-transform ${open ? 'rotate-180' : ''}`}
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
      className="w-full text-left p-2 rounded-lg bg-white/[0.02] hover:bg-white/[0.06] border border-white/[0.04] hover:border-white/[0.08] transition-all"
    >
      <div className="flex items-center gap-2">
        <div style={{ color: visuals.color }}>
          <CategoryIcon category={relNode.category} />
        </div>
        <span className="text-[12px] text-white font-mono truncate flex-1" title={relNode.fullName || relNode.name}>
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
            <div className="flex-1 h-1 bg-white/10 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${edge.confidence * 100}%`,
                  backgroundColor: getConfidenceColor(edge.confidence),
                }}
              />
            </div>
            <span className="text-[10px] text-white/40 shrink-0">
              {Math.round(edge.confidence * 100)}%
            </span>
          </>
        )}
        <span className="text-[10px] text-white/30 truncate shrink-0 max-w-[80px]" title={evidenceSource}>
          {evidenceSource}
        </span>
      </div>
    </button>
  );
}

// ─── Main Panel ────────────────────────────────────────────────────
export function DataAssetDetailPanel({
  node,
  allNodes,
  allEdges,
  stackId,
  onClose,
  onNodeNavigate,
}: DataAssetDetailPanelProps) {
  const [blastRadius, setBlastRadius] = useState<BlastRadiusResult | null>(null);
  const [blastLoading, setBlastLoading] = useState(false);
  const [showAllUpstream, setShowAllUpstream] = useState(false);
  const [showAllDownstream, setShowAllDownstream] = useState(false);

  // Reset expand/blast state when navigating to a different node
  useEffect(() => {
    setShowAllUpstream(false);
    setShowAllDownstream(false);
    setBlastRadius(null);
  }, [node.id]);

  // BFS traversal to find upstream/downstream grouped by hop depth
  const { upstreamByHop, downstreamByHop, totalUpstream, totalDownstream, allColumnMappings } = useMemo(() => {
    const nodeMap = new Map(allNodes.map((n) => [n.id, n]));
    const MAX_DEPTH = 3;

    // Only traverse data-level edges (exclude synthetic tool edges)
    const dataEdges = allEdges.filter(
      (e) =>
        e.edgeType !== 'pipeline_flow' &&
        e.edgeType !== 'contains' &&
        e.edgeType !== 'produces' &&
        e.edgeType !== 'reads_from'
    );

    function bfs(
      startId: string,
      direction: 'upstream' | 'downstream',
    ): Map<number, Array<{ node: UnifiedLineageNode; edge: UnifiedLineageEdge }>> {
      const result = new Map<number, Array<{ node: UnifiedLineageNode; edge: UnifiedLineageEdge }>>();
      const visited = new Set<string>([startId]);
      let frontier = [startId];
      let depth = 0;

      while (frontier.length > 0 && depth < MAX_DEPTH) {
        depth++;
        const nextFrontier: string[] = [];
        const hopItems: Array<{ node: UnifiedLineageNode; edge: UnifiedLineageEdge }> = [];

        for (const currentId of frontier) {
          const edges =
            direction === 'upstream'
              ? dataEdges.filter((e) => e.target === currentId)
              : dataEdges.filter((e) => e.source === currentId);

          for (const edge of edges) {
            const neighborId = direction === 'upstream' ? edge.source : edge.target;
            if (visited.has(neighborId)) continue;
            visited.add(neighborId);

            const neighborNode = nodeMap.get(neighborId);
            if (!neighborNode) continue;

            hopItems.push({ node: neighborNode, edge });
            nextFrontier.push(neighborId);
          }
        }

        if (hopItems.length > 0) result.set(depth, hopItems);
        frontier = nextFrontier;
      }
      return result;
    }

    const upByHop = bfs(node.id, 'upstream');
    const downByHop = bfs(node.id, 'downstream');

    const upTotal = Array.from(upByHop.values()).reduce((sum, items) => sum + items.length, 0);
    const downTotal = Array.from(downByHop.values()).reduce((sum, items) => sum + items.length, 0);

    // Aggregate column mappings from direct upstream (hop 1) edges
    const colMappings: Array<{ sourceName: string; from: string; to: string }> = [];
    const hop1Up = upByHop.get(1) || [];
    for (const item of hop1Up) {
      if (item.edge.columns) {
        for (const col of item.edge.columns) {
          if (typeof col === 'object' && col.from && col.to) {
            colMappings.push({
              sourceName: item.node.tableName || item.node.name?.split('.').pop() || item.node.name,
              from: col.from,
              to: col.to,
            });
          }
        }
      }
    }

    return {
      upstreamByHop: upByHop,
      downstreamByHop: downByHop,
      totalUpstream: upTotal,
      totalDownstream: downTotal,
      allColumnMappings: colMappings,
    };
  }, [node.id, allNodes, allEdges]);

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

  const hasIssues = node.issues && node.issues.total > 0;
  const hasCritical = node.issues && node.issues.critical > 0;
  const isStale = node.freshnessStatus === 'stale';

  return (
    <div className="w-80 border-l border-white/[0.06] bg-[#030303] p-4 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-medium text-white">Data Asset Details</h3>
        <button onClick={onClose} className="p-1 hover:bg-white/[0.05] rounded">
          <svg className="w-4 h-4 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="space-y-4">
        {/* Name */}
        <div>
          <label className="text-[11px] text-white/40 uppercase tracking-wide">Name</label>
          <p className="text-[13px] text-white font-mono mt-1 break-all">
            {node.fullName || node.name}
          </p>
        </div>

        {/* Type and Layer */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Type</label>
            <p className="text-[13px] text-white mt-1 capitalize">{node.category}</p>
          </div>
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Layer</label>
            <p className="text-[13px] text-white mt-1">{node.layer}</p>
          </div>
        </div>

        {/* Health Status Card */}
        <div className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] text-white/40 uppercase tracking-wide">Health Status</span>
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
              <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-white/10 text-white/50 text-[10px] font-medium">
                Unknown
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 text-[12px]">
            <div>
              <span className="text-white/40">Last Updated</span>
              <p className="text-white mt-0.5">
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
              <span className="text-white/40">Row Count</span>
              <p className="text-white mt-0.5">
                {node.rowCount?.toLocaleString() ?? '\u2014'}
              </p>
            </div>
          </div>
        </div>

        {/* Issues Section */}
        {hasIssues && (
          <div className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] text-white/40 uppercase tracking-wide">Issues</span>
              <span className="text-[12px] text-white font-medium">{node.issues!.open} open</span>
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
                <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-white/10">
                  <span className="w-2 h-2 rounded-full bg-white/50" />
                  <span className="text-[11px] text-white/60 font-medium">{node.issues!.low} Low</span>
                </div>
              )}
            </div>
            {Object.keys(node.issues!.byType).length > 0 && (
              <div className="pt-2 border-t border-white/[0.06]">
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(node.issues!.byType).map(([type, count]) => (
                    <span key={type} className="px-2 py-0.5 text-[10px] bg-white/5 text-white/60 rounded capitalize">
                      {type}: {count}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* No issues */}
        {!hasIssues && (
          <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-4 h-4 text-emerald-400" />
              <span className="text-[12px] text-emerald-400 font-medium">No open issues</span>
            </div>
          </div>
        )}

        {/* ─── Upstream ──────────────────────────────────────── */}
        <Section title="Upstream" count={totalUpstream} defaultOpen={true}>
          {totalUpstream === 0 ? (
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
                      <div className="text-[10px] text-white/30 uppercase tracking-wide mb-1.5">
                        Hop {hop} <span className="text-white/20">({items.length})</span>
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
                          className="w-full text-center text-[11px] text-white/40 hover:text-white/60 py-1.5 transition-colors"
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
        <Section title="Downstream" count={totalDownstream} defaultOpen={true}>
          {totalDownstream === 0 ? (
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
                      <div className="text-[10px] text-white/30 uppercase tracking-wide mb-1.5">
                        Hop {hop} <span className="text-white/20">({items.length})</span>
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
                          className="w-full text-center text-[11px] text-white/40 hover:text-white/60 py-1.5 transition-colors"
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
                <div key={i} className="flex items-center gap-1.5 text-[11px] font-mono py-1 px-2 rounded bg-white/[0.02]">
                  <span className="text-white/40 truncate max-w-[70px]" title={m.sourceName}>
                    {m.sourceName}
                  </span>
                  <span className="text-white/30">.</span>
                  <span className="text-white/60">{m.from}</span>
                  <ArrowRight className="w-3 h-3 text-white/20 shrink-0" />
                  <span className="text-white/80">{m.to}</span>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* ─── Blast Radius ──────────────────────────────────── */}
        <Section title="Blast Radius">
          {!blastRadius && !blastLoading && (
            <button
              onClick={fetchBlastRadius}
              className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-white/[0.03] border border-white/[0.06] hover:bg-white/[0.06] hover:border-white/[0.1] transition-all text-[12px] text-white/60 hover:text-white/80"
            >
              <Zap className="w-3.5 h-3.5" />
              Calculate Blast Radius
            </button>
          )}
          {blastLoading && (
            <div className="flex items-center justify-center gap-2 py-3 text-[12px] text-white/40">
              <div className="w-3.5 h-3.5 border-2 border-white/20 border-t-white/60 rounded-full animate-spin" />
              Calculating...
            </div>
          )}
          {blastRadius && (
            <div className="space-y-2">
              <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/[0.04]">
                <span className="text-[10px] text-white/40 uppercase tracking-wide">Total Downstream</span>
                <p className="text-[18px] text-white font-medium mt-0.5">
                  {blastRadius.total_downstream}
                </p>
              </div>
              {Object.keys(blastRadius.by_kind || {}).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(blastRadius.by_kind).map(([kind, count]) => (
                    <span
                      key={kind}
                      className="px-2 py-0.5 text-[10px] bg-white/5 text-white/60 rounded capitalize"
                    >
                      {count} {kind}{count !== 1 ? 's' : ''}
                    </span>
                  ))}
                </div>
              )}
              {Object.keys(blastRadius.by_domain || {}).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(blastRadius.by_domain).map(([domain, count]) => (
                    <span
                      key={domain}
                      className="px-2 py-0.5 text-[10px] bg-violet-500/10 text-violet-300/70 rounded capitalize"
                    >
                      {count} {domain}
                    </span>
                  ))}
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
                      <span className="text-[12px] text-white font-mono truncate flex-1">
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
                            <span className="text-[10px] text-white/40">Last Run</span>
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
                            <span className="text-[10px] text-white/40">When</span>
                            <span className="text-[10px] text-white/60">
                              {new Date(ctx.runSummary.lastRunDate).toLocaleString()}
                            </span>
                          </div>
                        )}
                        {ctx.runSummary.successRate !== undefined && (
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] text-white/40">Success Rate</span>
                            <span className="text-[10px] text-white/60">
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
        <div className="space-y-3 border-t border-white/[0.06] pt-3">
          {node.database && (
            <div>
              <label className="text-[11px] text-white/40 uppercase tracking-wide">Database</label>
              <p className="text-[13px] text-white font-mono mt-1">{node.database}</p>
            </div>
          )}
          {node.schema && (
            <div>
              <label className="text-[11px] text-white/40 uppercase tracking-wide">Schema/Dataset</label>
              <p className="text-[13px] text-white font-mono mt-1">{node.schema}</p>
            </div>
          )}
        </div>

        {/* ─── Platforms (multi-platform provenance) ────────── */}
        {node.platforms && node.platforms.length > 0 && (
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Discovered In</label>
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {node.platforms.map((p) => (
                <span
                  key={p}
                  className="px-2 py-1 text-[11px] font-medium capitalize bg-indigo-500/15 text-indigo-300 rounded border border-indigo-500/20"
                >
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Criticality & Owner */}
        <div className="grid grid-cols-2 gap-3">
          {node.criticality && (
            <div>
              <label className="text-[11px] text-white/40 uppercase tracking-wide">Criticality</label>
              <p
                className={`text-[13px] mt-1 font-medium ${
                  node.criticality === 'HIGH' || node.criticality === 'CRITICAL'
                    ? 'text-red-400'
                    : node.criticality === 'MEDIUM'
                    ? 'text-amber-400'
                    : 'text-white/70'
                }`}
              >
                {node.criticality}
              </p>
            </div>
          )}
          {node.owner && (
            <div>
              <label className="text-[11px] text-white/40 uppercase tracking-wide">Owner</label>
              <p className="text-[13px] text-white mt-1">{node.owner}</p>
            </div>
          )}
        </div>

        {/* Tags */}
        {node.tags && node.tags.length > 0 && (
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Tags</label>
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
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Description</label>
            <p className="text-[13px] text-white/70 mt-1">{node.description}</p>
          </div>
        )}

        {/* ─── Column Schema ──────────────────────────────── */}
        {node.columns && node.columns.length > 0 && (
          <Section title="Columns" count={node.columns.length}>
            <div className="space-y-0.5 max-h-48 overflow-y-auto">
              {node.columns.map((col, i) => (
                <div key={i} className="flex items-center justify-between py-1 px-2 rounded bg-white/[0.02]">
                  <span className="text-[11px] text-white/80 font-mono">{col.name}</span>
                  {col.type && (
                    <span className="text-[10px] text-white/30 font-mono">{col.type}</span>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* ─── SQL Definition ─────────────────────────────── */}
        {node.sqlDefinition && (
          <Section title="SQL Definition">
            <pre className="text-[11px] text-white/60 font-mono bg-white/[0.03] p-2 rounded overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-all">
              {node.sqlDefinition}
            </pre>
          </Section>
        )}
      </div>
    </div>
  );
}
