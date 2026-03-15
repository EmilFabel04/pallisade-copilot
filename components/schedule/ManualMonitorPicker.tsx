'use client';

import { useState, useMemo, useCallback } from 'react';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ManualNode {
  id: string;
  name: string;
  fqn: string;
  platform: string;
  platformDomain: string;
  assetKind: string;
  applicableMonitorTypes: string[];
}

interface ManualMonitorPickerProps {
  nodes: ManualNode[];
  selections: Record<string, string[]>;
  onSelectionChange: (selections: Record<string, string[]>) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LAYER_ORDER = ['Ingestion', 'Transformation', 'Warehouse', 'BI'] as const;

const LAYER_ICONS: Record<string, string> = {
  Ingestion: '\u2B07\uFE0F',
  Transformation: '\u2699\uFE0F',
  Warehouse: '\uD83C\uDFE0',
  BI: '\uD83D\uDCCA',
};

const LARGE_SCOPE_THRESHOLD = 50;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function groupByLayer(nodes: ManualNode[]): Record<string, ManualNode[]> {
  const groups: Record<string, ManualNode[]> = {};
  for (const node of nodes) {
    const layer = node.platformDomain || 'Other';
    if (!groups[layer]) groups[layer] = [];
    groups[layer].push(node);
  }
  // Sort nodes alphabetically within each layer
  for (const layer of Object.keys(groups)) {
    groups[layer].sort((a, b) => a.name.localeCompare(b.name));
  }
  return groups;
}

function sortedLayerKeys(groups: Record<string, ManualNode[]>): string[] {
  const ordered: string[] = [];
  for (const l of LAYER_ORDER) {
    if (groups[l]) ordered.push(l);
  }
  for (const k of Object.keys(groups)) {
    if (!ordered.includes(k)) ordered.push(k);
  }
  return ordered;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ManualMonitorPicker({
  nodes,
  selections,
  onSelectionChange,
}: ManualMonitorPickerProps) {
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set());
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [layerFilters, setLayerFilters] = useState<Record<string, string>>({});

  const grouped = useMemo(() => groupByLayer(nodes), [nodes]);
  const layerKeys = useMemo(() => sortedLayerKeys(grouped), [grouped]);

  // ------- toggle helpers -------

  const toggleLayer = useCallback((layer: string) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layer)) next.delete(layer);
      else next.add(layer);
      return next;
    });
  }, []);

  const toggleNode = useCallback((nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  // ------- selection helpers -------

  const toggleMonitor = useCallback(
    (nodeId: string, monitorType: string) => {
      const current = selections[nodeId] ?? [];
      const next = current.includes(monitorType)
        ? current.filter((m) => m !== monitorType)
        : [...current, monitorType];
      onSelectionChange({ ...selections, [nodeId]: next });
    },
    [selections, onSelectionChange],
  );

  const selectRecommended = useCallback(
    (node: ManualNode) => {
      const recommended = node.applicableMonitorTypes.slice(0, 3);
      onSelectionChange({ ...selections, [node.id]: recommended });
    },
    [selections, onSelectionChange],
  );

  const selectAllInLayer = useCallback(
    (layer: string) => {
      const layerNodes = grouped[layer] ?? [];
      const patch = { ...selections };
      for (const node of layerNodes) {
        patch[node.id] = [...node.applicableMonitorTypes];
      }
      onSelectionChange(patch);
    },
    [grouped, selections, onSelectionChange],
  );

  const clearAllInLayer = useCallback(
    (layer: string) => {
      const layerNodes = grouped[layer] ?? [];
      const patch = { ...selections };
      for (const node of layerNodes) {
        patch[node.id] = [];
      }
      onSelectionChange(patch);
    },
    [grouped, selections, onSelectionChange],
  );

  // ------- filter helper -------

  const getFilteredNodes = useCallback(
    (layer: string): ManualNode[] => {
      const layerNodes = grouped[layer] ?? [];
      const filter = (layerFilters[layer] ?? '').toLowerCase().trim();
      if (!filter) return layerNodes;
      return layerNodes.filter(
        (n) =>
          n.name.toLowerCase().includes(filter) ||
          n.fqn.toLowerCase().includes(filter),
      );
    },
    [grouped, layerFilters],
  );

  // ------- render -------

  return (
    <div className="flex flex-col gap-1">
      {/* Large scope warning */}
      {nodes.length > LARGE_SCOPE_THRESHOLD && (
        <div
          className="mb-2 rounded-md px-3 py-2 text-[13px]"
          style={{
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            color: 'rgb(245, 158, 11)',
            border: '1px solid rgba(245, 158, 11, 0.25)',
          }}
        >
          Large scope ({nodes.length} nodes) — consider using Recommended mode
        </div>
      )}

      {layerKeys.map((layer) => {
        const layerNodes = grouped[layer];
        const isExpanded = expandedLayers.has(layer);
        const filteredNodes = getFilteredNodes(layer);

        // Count selected monitors across this layer
        const layerSelectedCount = layerNodes.reduce(
          (sum, n) => sum + (selections[n.id]?.length ?? 0),
          0,
        );
        const layerTotalCount = layerNodes.reduce(
          (sum, n) => sum + n.applicableMonitorTypes.length,
          0,
        );

        return (
          <div
            key={layer}
            className="rounded-md overflow-hidden"
            style={{
              border: '1px solid var(--border)',
              backgroundColor: 'var(--surface)',
            }}
          >
            {/* Layer header */}
            <button
              type="button"
              onClick={() => toggleLayer(layer)}
              className={cn(
                'w-full flex items-center justify-between px-3 py-2',
                'hover:brightness-110 transition-all cursor-pointer',
              )}
              style={{ backgroundColor: 'var(--surface)' }}
            >
              <div className="flex items-center gap-2">
                {/* Chevron */}
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={cn(
                    'transition-transform duration-200',
                    isExpanded ? 'rotate-90' : 'rotate-0',
                  )}
                  style={{ color: 'var(--muted)' }}
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>

                <span className="text-[13px]" style={{ color: 'var(--muted)' }}>
                  {LAYER_ICONS[layer] ?? '\uD83D\uDD37'}
                </span>
                <span
                  className="text-[13px] font-medium"
                  style={{ color: 'var(--text)' }}
                >
                  {layer}
                </span>
                <span
                  className="text-[11px] ml-1"
                  style={{ color: 'var(--muted)' }}
                >
                  {layerNodes.length} node{layerNodes.length !== 1 ? 's' : ''}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <span
                  className="text-[11px]"
                  style={{ color: 'var(--muted)' }}
                >
                  {layerSelectedCount}/{layerTotalCount}
                </span>
              </div>
            </button>

            {/* Expanded layer content */}
            {isExpanded && (
              <div
                className="px-3 pb-3 pt-1 flex flex-col gap-2"
                style={{ borderTop: '1px solid var(--border)' }}
              >
                {/* Search + bulk actions row */}
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Filter nodes..."
                    value={layerFilters[layer] ?? ''}
                    onChange={(e) =>
                      setLayerFilters((prev) => ({
                        ...prev,
                        [layer]: e.target.value,
                      }))
                    }
                    className="flex-1 rounded-md px-2 py-1 text-[13px] outline-none"
                    style={{
                      backgroundColor: 'rgba(255,255,255,0.05)',
                      border: '1px solid var(--border)',
                      color: 'var(--text)',
                    }}
                  />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      selectAllInLayer(layer);
                    }}
                    className="text-[11px] px-2 py-1 rounded hover:brightness-125 transition-colors cursor-pointer"
                    style={{ color: 'var(--accent)' }}
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      clearAllInLayer(layer);
                    }}
                    className="text-[11px] px-2 py-1 rounded hover:brightness-125 transition-colors cursor-pointer"
                    style={{ color: 'var(--muted)' }}
                  >
                    Clear all
                  </button>
                </div>

                {/* Node rows */}
                {filteredNodes.length === 0 && (
                  <p
                    className="text-[11px] py-2 text-center"
                    style={{ color: 'var(--muted)' }}
                  >
                    No nodes match filter
                  </p>
                )}

                {filteredNodes.map((node) => {
                  const nodeExpanded = expandedNodes.has(node.id);
                  const nodeSelected = selections[node.id] ?? [];
                  const applicableCount = node.applicableMonitorTypes.length;

                  return (
                    <div
                      key={node.id}
                      className="rounded-md overflow-hidden"
                      style={{
                        border: '1px solid var(--border)',
                        backgroundColor: 'rgba(255,255,255,0.02)',
                      }}
                    >
                      {/* Node row header */}
                      <button
                        type="button"
                        onClick={() => toggleNode(node.id)}
                        className="w-full flex items-center justify-between px-3 py-1.5 hover:brightness-110 transition-all cursor-pointer"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <svg
                            width="12"
                            height="12"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            className={cn(
                              'flex-shrink-0 transition-transform duration-200',
                              nodeExpanded ? 'rotate-90' : 'rotate-0',
                            )}
                            style={{ color: 'var(--muted)' }}
                          >
                            <polyline points="9 18 15 12 9 6" />
                          </svg>

                          <span
                            className="text-[13px] truncate"
                            style={{ color: 'var(--text)' }}
                          >
                            {node.name}
                          </span>

                          {/* Platform badge */}
                          <span
                            className="flex-shrink-0 text-[10px] px-1.5 py-0.5 rounded-full uppercase tracking-wide"
                            style={{
                              backgroundColor: 'rgba(255,255,255,0.06)',
                              color: 'var(--muted)',
                              border: '1px solid var(--border)',
                            }}
                          >
                            {node.platform}
                          </span>
                        </div>

                        <span
                          className="flex-shrink-0 text-[11px] ml-2"
                          style={{
                            color:
                              nodeSelected.length > 0
                                ? 'var(--accent)'
                                : 'var(--muted)',
                          }}
                        >
                          {nodeSelected.length}/{applicableCount}
                        </span>
                      </button>

                      {/* Expanded node — monitor checkboxes */}
                      {nodeExpanded && (
                        <div
                          className="px-4 pb-2 pt-1 flex flex-col gap-1.5"
                          style={{ borderTop: '1px solid var(--border)' }}
                        >
                          {node.applicableMonitorTypes.map((monitorType) => {
                            const checked = nodeSelected.includes(monitorType);
                            return (
                              <label
                                key={monitorType}
                                className="flex items-center gap-2 cursor-pointer group"
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() =>
                                    toggleMonitor(node.id, monitorType)
                                  }
                                  className="rounded accent-[var(--accent)] cursor-pointer"
                                />
                                <span
                                  className="text-[13px] group-hover:brightness-125 transition-colors"
                                  style={{
                                    color: checked
                                      ? 'var(--text)'
                                      : 'var(--muted)',
                                  }}
                                >
                                  {monitorType}
                                </span>
                              </label>
                            );
                          })}

                          {/* Select recommended button */}
                          <button
                            type="button"
                            onClick={() => selectRecommended(node)}
                            className="self-start mt-1 text-[11px] px-2 py-1 rounded hover:brightness-125 transition-colors cursor-pointer"
                            style={{
                              color: 'var(--accent)',
                              backgroundColor: 'rgba(255,255,255,0.04)',
                              border: '1px solid var(--border)',
                            }}
                          >
                            Select recommended
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
