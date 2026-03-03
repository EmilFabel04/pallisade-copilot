'use client';

import React, { useState } from 'react';
import type { RenderedViewResponse, ViewNode, ViewEdge, PipelineLaneName } from '../types';
import { LANE_COLORS, LANE_LABELS } from '../types';
import type { InspectorTarget, InspectorTab } from './types';
import {
  getToolMeta,
  getEdgeMeta,
  getOverallHealth,
  HEALTH_COLORS,
  COVERAGE_GAP_LABELS,
  SEMANTIC_EDGE_STYLES,
} from './types';

interface InspectorPanelProps {
  target: InspectorTarget;
  laneOverview: RenderedViewResponse | null;
  stackId: string | null;
  onClose: () => void;
}

// ─── Collapsible Section (mirrors DataAssetDetailPanel pattern) ──────

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


// ─── Node Inspector ──────────────────────────────────────────────────

function NodeInspector({
  node,
  laneOverview,
}: {
  node: ViewNode;
  laneOverview: RenderedViewResponse | null;
}) {
  const [activeTab, setActiveTab] = useState<InspectorTab>('overview');
  const meta = getToolMeta(node);
  const health = getOverallHealth(meta.healthSummary);
  const healthColor = HEALTH_COLORS[health];
  const laneColor = LANE_COLORS[meta.lane as PipelineLaneName] || '#6366F1';

  // Connected edges
  const connectedEdges = (laneOverview?.edges || []).filter(
    e => e.sourceId === node.id || e.targetId === node.id
  );
  const nodeMap = new Map((laneOverview?.nodes || []).map(n => [n.id, n]));

  const tabs: { key: InspectorTab; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'jobs', label: `Jobs (${meta.jobCount})` },
    { key: 'assets', label: `Assets (${meta.assetCount})` },
    { key: 'coverage', label: 'Coverage' },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: healthColor, boxShadow: `0 0 6px ${healthColor}60` }}
          />
          <span className="text-[15px] font-semibold text-[var(--text)]">{node.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: laneColor, background: `${laneColor}14`, border: `1px solid ${laneColor}20` }}
          >
            {LANE_LABELS[meta.lane as PipelineLaneName] || meta.lane}
          </span>
          <span className="text-[11px] text-[var(--muted)] capitalize">{node.platform || 'Unknown'}</span>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-0.5 p-0.5 rounded-lg bg-[var(--overlay-faint)]">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`flex-1 px-2 py-1.5 rounded-md text-[11px] font-medium transition-colors ${
              activeTab === t.key
                ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm'
                : 'text-[var(--muted)] hover:text-[var(--text-secondary)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'overview' && (
        <div className="space-y-4">
          {/* Metadata grid */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Type</label>
              <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{node.platform || 'Unknown'}</p>
            </div>
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Domain</label>
              <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{node.platformDomain}</p>
            </div>
          </div>

          {meta.integrationId && (
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Integration ID</label>
              <p className="text-[13px] text-[var(--text)] mt-1 font-mono break-all">{meta.integrationId}</p>
            </div>
          )}

          {/* Asset count */}
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Data Assets</label>
            <p className="text-2xl font-semibold text-[var(--text)] mt-1">{meta.assetCount}</p>
          </div>

          {/* Health summary */}
          <Section title="Health Summary" defaultOpen>
            <div className="space-y-2">
              {meta.healthSummary.healthy > 0 && (
                <HealthRow label="Healthy" count={meta.healthSummary.healthy} color="#10B981" />
              )}
              {meta.healthSummary.degraded > 0 && (
                <HealthRow label="Degraded" count={meta.healthSummary.degraded} color="#F59E0B" />
              )}
              {meta.healthSummary.failing > 0 && (
                <HealthRow label="Failing" count={meta.healthSummary.failing} color="#EF4444" />
              )}
              {meta.healthSummary.stale > 0 && (
                <HealthRow label="Stale" count={meta.healthSummary.stale} color="#F59E0B" />
              )}
              {meta.healthSummary.unknown > 0 && (
                <HealthRow label="Unknown" count={meta.healthSummary.unknown} color="#6B7280" />
              )}
              {health === 'unknown' && meta.assetCount === 0 && (
                <p className="text-[12px] text-[var(--muted)] italic">No health data available</p>
              )}
            </div>
          </Section>

          {/* Connected flows */}
          {connectedEdges.length > 0 && (
            <Section title="Data Flows" count={connectedEdges.length} defaultOpen>
              <div className="space-y-1.5">
                {connectedEdges.map(e => {
                  const otherId = e.sourceId === node.id ? e.targetId : e.sourceId;
                  const other = nodeMap.get(otherId);
                  const direction = e.sourceId === node.id ? '→' : '←';
                  const edgeMeta = getEdgeMeta(e);
                  return (
                    <div key={e.id} className="flex items-center justify-between px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                      <span className="text-[12px] text-[var(--text)] font-mono truncate">
                        {direction} {other?.name || otherId}
                      </span>
                      <span className="text-[10px] text-[var(--muted)] shrink-0 ml-2">{edgeMeta.label}</span>
                    </div>
                  );
                })}
              </div>
            </Section>
          )}
        </div>
      )}

      {activeTab === 'jobs' && (
        <div className="space-y-3">
          {meta.jobCount > 0 ? (
            <>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Jobs</span>
                <span className="text-[12px] text-[var(--text)] font-semibold">{meta.jobCount}</span>
              </div>
              {meta.lastRunTs && (
                <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Last Run</label>
                  <p className="text-[13px] text-[var(--text)] mt-1 font-mono">{formatRelativeTime(meta.lastRunTs)}</p>
                </div>
              )}
              {/* Sub-nodes filtered to jobs */}
              {meta.subNodes.filter(sn => sn.type === 'job').map(sn => (
                <div key={sn.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                  <svg className="w-3.5 h-3.5 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
                  </svg>
                  <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{sn.name}</span>
                  <span className="text-[9px] text-[var(--muted)] uppercase shrink-0">{sn.type}</span>
                </div>
              ))}
            </>
          ) : (
            <div className="py-8 text-center">
              <p className="text-[13px] text-[var(--muted)]">No jobs detected</p>
              <p className="text-[11px] text-[var(--text-faint)] mt-1">Job data not available yet</p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'assets' && (
        <div className="space-y-3">
          {meta.subNodes.length > 0 ? (
            <>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Assets</span>
                <span className="text-[12px] text-[var(--text)] font-semibold">{meta.totalSubNodeCount}</span>
              </div>
              {meta.subNodes.slice(0, 20).map(sn => (
                <div key={sn.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: laneColor }} />
                  <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1" title={sn.fqn}>{sn.name}</span>
                  <span className="text-[9px] text-[var(--muted)] uppercase shrink-0">{sn.type}</span>
                </div>
              ))}
              {meta.totalSubNodeCount > 20 && (
                <p className="text-[11px] text-[var(--muted)] text-center">
                  +{meta.totalSubNodeCount - 20} more assets
                </p>
              )}
            </>
          ) : (
            <div className="py-8 text-center">
              <p className="text-[13px] text-[var(--muted)]">No assets discovered</p>
              <p className="text-[11px] text-[var(--text-faint)] mt-1">
                {meta.fromPipelineStack ? 'Run lineage extraction to discover assets' : 'Not available yet'}
              </p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'coverage' && (
        <div className="space-y-3">
          {meta.coverageGaps.length > 0 ? (
            <>
              <div className="flex items-center gap-2 mb-2">
                <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
                </svg>
                <span className="text-[13px] text-amber-400 font-medium">
                  {meta.coverageGaps.length} coverage gap{meta.coverageGaps.length !== 1 ? 's' : ''}
                </span>
              </div>
              {meta.coverageGaps.map(gap => (
                <div key={gap} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/10">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                  <span className="text-[12px] text-[var(--text)]">{COVERAGE_GAP_LABELS[gap] || gap}</span>
                </div>
              ))}
            </>
          ) : (
            <div className="flex items-center gap-2 px-3 py-3 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
              <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-[13px] text-emerald-400 font-medium">Full coverage</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// ─── Edge Inspector ──────────────────────────────────────────────────

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
        </div>
        <p className="text-[12px] text-[var(--muted)]">
          {src?.name || edge.sourceId} → {tgt?.name || edge.targetId}
        </p>
      </div>

      {/* Flow count */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Data Flows</label>
          <p className="text-2xl font-semibold text-[var(--text)] mt-1">{meta.dataFlowCount}</p>
        </div>
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
      </div>

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


// ─── Helper components ───────────────────────────────────────────────

function HealthRow({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[12px]" style={{ color }}>{label}</span>
      <span className="text-[12px] text-[var(--text)]">{count}</span>
    </div>
  );
}

function ToolSummaryRow({ node }: { node: ViewNode }) {
  const meta = getToolMeta(node);
  const laneColor = LANE_COLORS[meta.lane as PipelineLaneName] || '#6366F1';

  return (
    <div className="flex items-center gap-2 px-2 py-2 rounded bg-[var(--overlay-bg)]">
      <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: laneColor }} />
      <div className="flex-1 min-w-0">
        <p className="text-[12px] text-[var(--text)] font-medium truncate">{node.name}</p>
        <p className="text-[10px] text-[var(--muted)] capitalize">{node.platform} · {meta.assetCount} assets</p>
      </div>
    </div>
  );
}

function formatRelativeTime(isoStr: string): string {
  try {
    const date = new Date(isoStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    return `${diffDays}d ago`;
  } catch {
    return isoStr;
  }
}


// ─── Main Panel ──────────────────────────────────────────────────────

export function InspectorPanel({
  target,
  laneOverview,
  stackId,
  onClose,
}: InspectorPanelProps) {
  if (!target) return null;

  return (
    <div className="w-80 border-l border-[var(--subtle-border)] bg-[var(--surface-sunken)] p-4 overflow-y-auto">
      {/* Close button */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-medium text-[var(--text)]">
          {target.kind === 'node' ? 'Tool Details' : 'Flow Details'}
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
        <NodeInspector node={target.node} laneOverview={laneOverview} />
      ) : (
        <EdgeInspector edge={target.edge} laneOverview={laneOverview} />
      )}
    </div>
  );
}
