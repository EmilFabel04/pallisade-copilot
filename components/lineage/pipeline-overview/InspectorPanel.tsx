'use client';

import React, { useState, useEffect, useRef } from 'react';
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
} from './types';
import { ToolDetailView } from './tool-details/ToolDetailView';
import { LoadingState } from './tool-details/SharedDetailComponents';

interface InspectorPanelProps {
  target: InspectorTarget;
  laneOverview: RenderedViewResponse | null;
  stackId: string | null;
  onClose: () => void;
}


// ─── Node Inspector (with tool-details fetch) ────────────────────────

function NodeInspector({
  node,
  laneOverview,
  stackId,
}: {
  node: ViewNode;
  laneOverview: RenderedViewResponse | null;
  stackId: string | null;
}) {
  const meta = getToolMeta(node);
  const health = getOverallHealth(meta.healthSummary);
  const healthColor = HEALTH_COLORS[health];
  const laneColor = LAYER_COLORS[node.layer as PipelineLayer] || LANE_COLORS[meta.lane as PipelineLaneName] || '#6366F1';
  const laneLabel = LAYER_LABELS[node.layer as PipelineLayer] || LANE_LABELS[meta.lane as PipelineLaneName] || meta.lane;

  // Fetch tool details on-demand
  const [details, setDetails] = useState<ToolDetailsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const cacheRef = useRef<Map<string, ToolDetailsResponse>>(new Map());

  // Clear cache when pipeline data changes (new extraction)
  const overviewStamp = laneOverview?.stats?.opsSummary?.totalAssets ?? laneOverview?.nodes?.length ?? 0;
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
            style={{ backgroundColor: healthColor, boxShadow: `0 0 6px ${healthColor}60` }}
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
          <span className="text-[11px] text-[var(--muted)] capitalize">{node.platform || 'Unknown'}</span>
        </div>
      </div>

      {/* Detail content */}
      {loading && <LoadingState />}

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
                .then(res => res.json())
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

      {details && !loading && <ToolDetailView details={details} />}
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
        <p className="text-[10px] text-[var(--muted)] capitalize">{node.platform} · {meta.assetCount} assets</p>
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
        <NodeInspector node={target.node} laneOverview={laneOverview} stackId={stackId} />
      ) : (
        <EdgeInspector edge={target.edge} laneOverview={laneOverview} />
      )}
    </div>
  );
}
