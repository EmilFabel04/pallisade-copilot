'use client';

import React, { useState, useMemo, useCallback, useEffect } from 'react';
import type { UnifiedLineageNode, UnifiedLineageEdge } from './types';
import type {
  SLAProfile,
  EffectiveSLAPolicy,
  SLAAssignRequest,
  SLADomain,
} from '@/types/sla';
import { categoryToSLADomain, DOMAIN_SLA_SECTIONS } from '@/types/sla';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ApplyScope = 'selected' | 'downstream' | 'all_of_type';

interface SLAEditorPanelProps {
  selectedNodeIds: Set<string>;
  allNodes: UnifiedLineageNode[];
  allEdges: UnifiedLineageEdge[];
  stackId: string;
  nodeSLAs: Map<string, EffectiveSLAPolicy>;
  saving?: boolean;
  discoveryDefaults?: Record<string, any> | null;
  onApply: (request: SLAAssignRequest, scope: ApplyScope) => void;
  onRemoveSLA?: (nodeFqns: string[]) => void;
  onClose: () => void;
  onClearSelection: () => void;
  onApplyBulkDiscovery?: (entries: Array<{ nodeFqn: string; overrides: Record<string, any> }>) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getSelectedNodes(ids: Set<string>, allNodes: UnifiedLineageNode[]): UnifiedLineageNode[] {
  return allNodes.filter((n) => ids.has(n.id) || ids.has(n.id.replace('lineage-', '')));
}

function getDomainsFromNodes(nodes: UnifiedLineageNode[]): Set<SLADomain> {
  const domains = new Set<SLADomain>();
  for (const n of nodes) {
    const d = categoryToSLADomain(n.category);
    if (d) domains.add(d);
  }
  return domains;
}

function getApplicableSections(domains: Set<SLADomain>): string[] {
  const sections = new Set<string>();
  for (const d of domains) {
    const s = DOMAIN_SLA_SECTIONS[d];
    if (s) s.forEach((sec) => sections.add(sec));
  }
  return Array.from(sections);
}

function countDownstream(nodeIds: Set<string>, allEdges: UnifiedLineageEdge[]): number {
  const visited = new Set<string>(nodeIds);
  const queue = Array.from(nodeIds);
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const edge of allEdges) {
      if (edge.source === current && !visited.has(edge.target)) {
        visited.add(edge.target);
        queue.push(edge.target);
      }
    }
  }
  return visited.size - nodeIds.size;
}

function countOfType(category: string, allNodes: UnifiedLineageNode[]): number {
  return allNodes.filter((n) => n.category === category).length;
}

// ---------------------------------------------------------------------------
// Strictness / Tolerance selects
// ---------------------------------------------------------------------------

function StrictnessSelect({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div>
      <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full px-2 py-1.5 text-[12px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
      >
        <option value="strict">Strict</option>
        <option value="warn">Warn</option>
        <option value="ignore">Ignore</option>
      </select>
    </div>
  );
}

function ToleranceSelect({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div>
      <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full px-2 py-1.5 text-[12px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
      >
        <option value="strict">Strict</option>
        <option value="normal">Normal</option>
        <option value="relaxed">Relaxed</option>
      </select>
    </div>
  );
}

function NumberInput({ value, onChange, label, suffix, min, max, placeholder }: {
  value: number | undefined;
  onChange: (v: number) => void;
  label: string;
  suffix?: string;
  min?: number;
  max?: number;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">{label}</label>
      <div className="flex items-center gap-1.5 mt-1">
        <input
          type="number"
          value={value ?? ''}
          onChange={(e) => onChange(Number(e.target.value))}
          min={min}
          max={max}
          placeholder={placeholder}
          className="w-full px-2 py-1.5 text-[12px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-slate-500/50 focus:outline-none placeholder:text-[var(--text-faint)]"
        />
        {suffix && <span className="text-[11px] text-[var(--muted)] whitespace-nowrap">{suffix}</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function SLAEditorPanel({
  selectedNodeIds,
  allNodes,
  allEdges,
  stackId,
  nodeSLAs,
  saving,
  discoveryDefaults,
  onApply,
  onRemoveSLA,
  onClose,
  onClearSelection,
  onApplyBulkDiscovery,
}: SLAEditorPanelProps) {
  const [applyScope, setApplyScope] = useState<ApplyScope>('selected');
  const [applied, setApplied] = useState(false);
  const prevSavingRef = React.useRef(false);

  const [bulkDiscoveryState, setBulkDiscoveryState] = useState<'idle' | 'loading' | 'results'>('idle');
  const [bulkResults, setBulkResults] = useState<Array<{
    node_fqn: string;
    unsupported?: boolean;
    skipped_reason?: string;
    freshness?: any;
    volume?: any;
    quality?: any;
    schema_profile?: any;
    uniqueness?: any;
  }>>([]);

  useEffect(() => {
    setBulkDiscoveryState('idle');
    setBulkResults([]);
  }, [selectedNodeIds]);

  // Flat values state — initialized from discoveryDefaults when provided
  const [values, setValues] = useState<Record<string, any>>(() => {
    console.log('[SLAEditor] Initial discoveryDefaults:', JSON.stringify(discoveryDefaults, null, 2));
    if (!discoveryDefaults) return {};
    return { ...discoveryDefaults };
  });

  // Re-initialize values when discoveryDefaults change
  useEffect(() => {
    if (discoveryDefaults) {
      setValues({ ...discoveryDefaults });
    }
  }, [discoveryDefaults]);

  const hasDiscovery = !!discoveryDefaults;

  // Detect when saving transitions from true -> false (apply completed)
  useEffect(() => {
    if (prevSavingRef.current && !saving) {
      setApplied(true);
    }
    prevSavingRef.current = !!saving;
  }, [saving]);

  useEffect(() => { setApplied(false); }, [applyScope]);
  useEffect(() => { setApplied(false); }, [selectedNodeIds]);

  const setVal = useCallback((section: string, key: string, value: any) => {
    setApplied(false);
    setValues((prev) => ({
      ...prev,
      [section]: { ...(prev[section] || {}), [key]: value },
    }));
  }, []);

  const getVal = useCallback(
    (section: string, key: string): any => {
      return values[section]?.[key];
    },
    [values]
  );

  const selectedNodes = useMemo(
    () => getSelectedNodes(selectedNodeIds, allNodes),
    [selectedNodeIds, allNodes]
  );

  const domains = useMemo(() => getDomainsFromNodes(selectedNodes), [selectedNodes]);

  const applicableSections = useMemo(() => {
    const domainSections = getApplicableSections(domains);
    if (domainSections.length > 0) return domainSections;
    // Fallback for uncategorized nodes
    return ['freshness', 'schema', 'volume', 'quality'];
  }, [domains]);

  const downstreamCount = useMemo(
    () => countDownstream(selectedNodeIds, allEdges),
    [selectedNodeIds, allEdges]
  );

  const dominantCategory = selectedNodes.length > 0 ? selectedNodes[0].category : null;
  const typeCount = dominantCategory ? countOfType(dominantCategory, allNodes) : 0;

  const firstFqn = selectedNodes[0]?.fullName || selectedNodes[0]?.name || '';
  const currentPolicy = nodeSLAs.get(firstFqn);

  // Check if user has entered any values
  const hasAnyValues = Object.values(values).some(
    (section) => section && typeof section === 'object' && Object.values(section).some((v) => v != null && v !== '')
  );

  const handleApply = useCallback(() => {
    if (!hasAnyValues) return;

    const fqns = selectedNodes.map((n) => n.fullName || n.name);

    // Build the overrides from the values state
    const overrides: Record<string, any> = {};
    for (const [section, fields] of Object.entries(values)) {
      if (!fields || typeof fields !== 'object') continue;
      const nonEmpty: Record<string, any> = {};
      for (const [key, value] of Object.entries(fields)) {
        if (value != null && value !== '') nonEmpty[key] = value;
      }
      if (Object.keys(nonEmpty).length > 0) overrides[section] = nonEmpty;
    }

    const request: SLAAssignRequest & { _profileName?: string } = {
      profileId: hasDiscovery ? `auto-discovered-${fqns[0] || 'node'}` : `manual-${fqns[0] || 'node'}`,
      assignmentType: hasDiscovery ? 'auto_discovered' : 'direct',
      nodeFqns: applyScope === 'downstream' ? undefined : fqns,
      branchRootFqn: applyScope === 'downstream' ? fqns[0] : undefined,
      overrides,
      _profileName: hasDiscovery ? 'Discovered from Data' : 'Manual',
    };

    onApply(request, applyScope);
  }, [hasAnyValues, hasDiscovery, selectedNodes, applyScope, onApply, values]);

  const handleBulkDiscover = useCallback(async () => {
    setBulkDiscoveryState('loading');
    try {
      const engineIds = Array.from(selectedNodeIds).map((id) => id.replace(/^lineage-/, ''));
      const res = await fetch('/api/nodes/sla/discover-bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nodeIds: engineIds, stackId }),
      });
      if (res.ok) {
        const data = await res.json();
        setBulkResults(data.results || []);
        setBulkDiscoveryState('results');
      } else {
        setBulkDiscoveryState('idle');
      }
    } catch {
      setBulkDiscoveryState('idle');
    }
  }, [selectedNodeIds, stackId]);

  const handleApplyAll = useCallback(() => {
    if (!onApplyBulkDiscovery) return;

    // Build a map from engine node FQN → UI node FQN (fullName || name)
    // The assign endpoint needs the UI FQN, not the engine FQN
    const engineFqnToUiFqn = new Map<string, string>();
    for (const node of selectedNodes) {
      const uiFqn = node.fullName || node.name;
      // The engine FQN might match fullName, name, or the ID (minus lineage- prefix)
      engineFqnToUiFqn.set(uiFqn, uiFqn);
      engineFqnToUiFqn.set(node.name, uiFqn);
      engineFqnToUiFqn.set(node.id, uiFqn);
      engineFqnToUiFqn.set(node.id.replace(/^lineage-/, ''), uiFqn);
    }

    const entries: Array<{ nodeFqn: string; overrides: Record<string, any> }> = [];
    for (const r of bulkResults) {
      if (r.unsupported) continue;
      // Map back to UI FQN for the assign endpoint
      const uiFqn = engineFqnToUiFqn.get(r.node_fqn) || r.node_fqn;
      const overrides: Record<string, any> = {};
      if (r.freshness) overrides.freshnessConfig = r.freshness;
      if (r.volume) overrides.volumeConfig = r.volume;
      if (r.quality) overrides.qualityConfig = r.quality;
      if (r.schema_profile) overrides.schemaConfig = r.schema_profile;
      if (r.uniqueness) overrides.uniquenessConfig = r.uniqueness;
      entries.push({ nodeFqn: uiFqn, overrides });
    }
    console.log('[SLA Bulk] FQN mapping (engine→UI):', Array.from(engineFqnToUiFqn.entries()).map(([k, v]) => `${k} → ${v}`));
    console.log('[SLA Bulk] bulkResults node_fqns:', bulkResults.map(r => r.node_fqn));
    console.log('[SLA Bulk] Entries to apply:', entries.map(e => e.nodeFqn));
    onApplyBulkDiscovery(entries);
  }, [bulkResults, onApplyBulkDiscovery, selectedNodes]);

  const discoveredCount = bulkResults.filter((r) => !r.unsupported).length;
  const skippedCount = bulkResults.filter((r) => r.unsupported).length;

  if (selectedNodeIds.size === 0) {
    return (
      <div className="w-80 border-l border-slate-500/20 bg-[var(--surface-sunken)] p-4 flex flex-col items-center justify-center text-center h-full">
        <svg className="w-12 h-12 text-slate-400/30 mb-3" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
        <p className="text-[13px] text-[var(--muted)]">
          Click a node to define its Data SLA.
        </p>
        <p className="text-[11px] text-[var(--muted)] mt-1">
          Shift+click to select multiple nodes.
        </p>
      </div>
    );
  }

  return (
    <div className="w-80 border-l border-slate-500/20 bg-[var(--surface-sunken)] flex flex-col h-full">
      {/* Header (sticky) */}
      <div className="p-4 border-b border-[var(--subtle-border)] flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-[14px] font-semibold text-[var(--text)] flex items-center gap-2">
            <svg className="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            Data SLA Editor
          </h3>
          <button onClick={onClose} className="p-1 hover:bg-[var(--subtle-bg)] rounded">
            <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[12px] font-medium" style={{ color: 'var(--text)' }}>
            {selectedNodeIds.size} node{selectedNodeIds.size !== 1 ? 's' : ''} selected
          </span>
          <button
            onClick={onClearSelection}
            className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] underline"
          >
            Clear
          </button>
        </div>
        {currentPolicy && currentPolicy.status !== 'none' && selectedNodeIds.size === 1 && (
          <div className="mt-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <span className="text-[11px] text-[var(--muted)]">Current: </span>
            <span className="text-[11px] font-medium" style={{ color: 'var(--text)' }}>
              {currentPolicy.profileName || 'Default'}
            </span>
          </div>
        )}
      </div>

      {/* Bulk discover button */}
      {bulkDiscoveryState === 'idle' && !hasDiscovery && selectedNodeIds.size >= 1 && (
        <div className="mx-4 mt-3">
          <button
            onClick={handleBulkDiscover}
            className="w-full px-3 py-2 text-[12px] font-medium rounded-lg border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10 transition-colors flex items-center justify-center gap-2"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            Discover from data ({selectedNodeIds.size} node{selectedNodeIds.size !== 1 ? 's' : ''})
          </button>
        </div>
      )}

      {/* Bulk discovery loading */}
      {bulkDiscoveryState === 'loading' && (
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
          <div className="w-8 h-8 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin mb-3" />
          <p className="text-[13px] text-[var(--text)]">Discovering {selectedNodeIds.size} nodes...</p>
          <p className="text-[11px] text-[var(--muted)] mt-1">Querying warehouse metadata</p>
        </div>
      )}

      {/* Bulk discovery results */}
      {bulkDiscoveryState === 'results' && (
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-[12px] font-medium text-[var(--text)]">
              {discoveredCount} discovered, {skippedCount} skipped
            </p>
            <button
              onClick={() => { setBulkDiscoveryState('idle'); setBulkResults([]); }}
              className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] underline"
            >
              Dismiss
            </button>
          </div>

          {bulkResults.map((r) => {
            const shortName = r.node_fqn.split('.').pop() || r.node_fqn;
            const dims = [
              r.freshness ? 'F' : null,
              r.volume ? 'V' : null,
              r.quality ? 'Q' : null,
              r.schema_profile ? 'S' : null,
              r.uniqueness && !r.uniqueness.skipped ? 'U' : null,
            ].filter(Boolean);

            return (
              <div
                key={r.node_fqn}
                className={`p-2.5 rounded-lg border ${r.unsupported ? 'border-[var(--subtle-border)] opacity-50' : 'border-cyan-500/20 bg-cyan-500/5'}`}
              >
                <p className="text-[11px] font-mono text-[var(--text)] truncate" title={r.node_fqn}>
                  {shortName}
                </p>
                {r.unsupported ? (
                  <p className="text-[10px] text-[var(--text-faint)] mt-0.5">{r.skipped_reason}</p>
                ) : (
                  <div className="flex gap-1 mt-1">
                    {dims.map((d) => (
                      <span key={d} className="px-1.5 py-0.5 text-[9px] font-medium rounded bg-cyan-500/20 text-cyan-400">
                        {d}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {bulkDiscoveryState !== 'results' && bulkDiscoveryState !== 'loading' && (
        <>

      {/* Source badge */}
      {hasDiscovery && (
        <div className="mx-4 mt-3 p-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
          <p className="text-[11px] text-cyan-400 font-medium">Discovered from Data</p>
          <p className="text-[10px] text-cyan-400/70 mt-0.5">
            Thresholds derived from warehouse history. Edit below to adjust.
          </p>
        </div>
      )}

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Selected node names */}
        {selectedNodes.length <= 5 && (
          <div className="space-y-1">
            {selectedNodes.map((n) => (
              <div key={n.id} className="text-[11px] text-[var(--text-tertiary)] font-mono truncate">
                {n.fullName || n.name}
              </div>
            ))}
          </div>
        )}

        {/* SLA Controls — always visible, no collapsible */}
        <div className="space-y-4">
          {/* Freshness section */}
          {applicableSections.includes('freshness') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Freshness</h4>
              <NumberInput
                label="Max hours"
                value={getVal('freshnessConfig', 'maxHours')}
                onChange={(v) => setVal('freshnessConfig', 'maxHours', v)}
                suffix="hrs"
                min={0}
                placeholder={hasDiscovery ? '' : 'e.g. 6'}
              />
              <NumberInput
                label="Warning"
                value={getVal('freshnessConfig', 'warningHours')}
                onChange={(v) => setVal('freshnessConfig', 'warningHours', v)}
                suffix="hrs"
                min={0}
                placeholder={hasDiscovery ? '' : 'e.g. 3'}
              />
            </div>
          )}

          {/* Schema section */}
          {applicableSections.includes('schema') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Schema</h4>
              <StrictnessSelect
                label="Strictness"
                value={getVal('schemaConfig', 'strictness') || 'warn'}
                onChange={(v) => setVal('schemaConfig', 'strictness', v)}
              />
              {getVal('schemaConfig', 'columnCount') != null && (
                <p className="text-[11px] text-[var(--muted)]">
                  Columns: <span className="text-[var(--text)] font-medium">{getVal('schemaConfig', 'columnCount')}</span>
                </p>
              )}
              {getVal('schemaConfig', 'columns') && (
                <details className="mt-1">
                  <summary className="text-[10px] text-[var(--muted)] cursor-pointer hover:text-[var(--text)]">
                    Column snapshot ({(getVal('schemaConfig', 'columns') as any[]).length} columns)
                  </summary>
                  <div className="mt-1 space-y-0.5 max-h-40 overflow-y-auto">
                    {(getVal('schemaConfig', 'columns') as { name: string; type: string; nullable: boolean; ordinal: number }[]).map((col) => (
                      <div key={col.name} className="flex justify-between text-[10px] font-mono">
                        <span className="text-[var(--muted)] truncate mr-2">{col.name}</span>
                        <span className="text-[var(--text)] whitespace-nowrap">{col.type}{col.nullable ? '' : ' NOT NULL'}</span>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          )}

          {/* Volume section */}
          {applicableSections.includes('volume') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Volume</h4>
              {getVal('volumeConfig', 'currentRows') != null && (
                <p className="text-[11px] text-[var(--muted)]">
                  Total rows now: <span className="text-[var(--text)] font-medium">{Number(getVal('volumeConfig', 'currentRows')).toLocaleString()}</span>
                </p>
              )}
              <NumberInput
                label="Min rows"
                value={getVal('volumeConfig', 'minRows')}
                onChange={(v) => setVal('volumeConfig', 'minRows', v)}
                min={0}
                placeholder="Set based on expected load"
              />
              <NumberInput
                label="Max rows"
                value={getVal('volumeConfig', 'maxRows')}
                onChange={(v) => setVal('volumeConfig', 'maxRows', v)}
                min={0}
                placeholder="Set based on expected load"
              />
            </div>
          )}

          {/* Quality section */}
          {applicableSections.includes('quality') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Quality</h4>
              {getVal('qualityConfig', 'currentAvgNullRate') != null && (
                <div className="text-[11px] text-[var(--muted)] space-y-0.5">
                  <p>Avg null rate: <span className="text-[var(--text)] font-medium">{(getVal('qualityConfig', 'currentAvgNullRate') * 100).toFixed(1)}%</span></p>
                  <p>Max null rate: <span className="text-[var(--text)] font-medium">{(getVal('qualityConfig', 'currentMaxNullRate') * 100).toFixed(1)}%</span></p>
                  {getVal('qualityConfig', 'rowsScanned') != null && (
                    <p>Rows scanned: <span className="text-[var(--text)]">{Number(getVal('qualityConfig', 'rowsScanned')).toLocaleString()}</span></p>
                  )}
                </div>
              )}
              {/* Per-column breakdown */}
              {getVal('qualityConfig', 'perColumn') && (
                <details className="mt-1">
                  <summary className="text-[10px] text-[var(--muted)] cursor-pointer hover:text-[var(--text)]">
                    Per-column null rates
                  </summary>
                  <div className="mt-1 space-y-0.5 max-h-32 overflow-y-auto">
                    {Object.entries(getVal('qualityConfig', 'perColumn') as Record<string, number>)
                      .sort(([,a], [,b]) => b - a)
                      .map(([col, rate]) => (
                        <div key={col} className="flex justify-between text-[10px] font-mono">
                          <span className="text-[var(--muted)] truncate mr-2">{col}</span>
                          <span className={rate > 0.05 ? 'text-amber-400' : 'text-[var(--text)]'}>{(rate * 100).toFixed(1)}%</span>
                        </div>
                      ))}
                  </div>
                </details>
              )}
              <NumberInput
                label="Max null rate threshold"
                value={(() => { const v = getVal('qualityConfig', 'maxNullRate'); return v != null ? Math.round(v * 100 * 10) / 10 : undefined; })()}
                onChange={(v) => setVal('qualityConfig', 'maxNullRate', v / 100)}
                suffix="%"
                min={0}
                max={100}
                placeholder={hasDiscovery ? '' : 'e.g. 5'}
              />
            </div>
          )}

          {/* Uniqueness section */}
          {applicableSections.includes('uniqueness') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Uniqueness</h4>
              {getVal('uniquenessConfig', 'skipped') ? (
                <p className="text-[11px] text-[var(--text-faint)]">
                  Skipped — {getVal('uniquenessConfig', 'reason') || 'no PK detected'}
                </p>
              ) : (
                <>
                  {getVal('uniquenessConfig', 'duplicateRate') != null && (
                    <div className="text-[11px] text-[var(--muted)] space-y-0.5">
                      <p>Duplicate rate: <span className={`font-medium ${getVal('uniquenessConfig', 'duplicateRate') > 0 ? 'text-amber-400' : 'text-[var(--text)]'}`}>{(getVal('uniquenessConfig', 'duplicateRate') * 100).toFixed(2)}%</span></p>
                      <p>PK columns: <span className="text-[var(--text)] font-mono">{(getVal('uniquenessConfig', 'primaryKeyColumns') || []).join(', ')}</span></p>
                      <p>Detection: <span className="text-[var(--text)]">{getVal('uniquenessConfig', 'detectionMethod')}</span>
                        {getVal('uniquenessConfig', 'approximate') && <span className="text-[var(--text-faint)]"> (approx)</span>}
                      </p>
                      <p>Rows: <span className="text-[var(--text)]">{Number(getVal('uniquenessConfig', 'distinctRows') || 0).toLocaleString()} distinct / {Number(getVal('uniquenessConfig', 'totalRows') || 0).toLocaleString()} total</span></p>
                    </div>
                  )}
                  <NumberInput
                    label="Max duplicate rate"
                    value={(() => { const v = getVal('uniquenessConfig', 'maxDuplicateRate') ?? getVal('uniquenessConfig', 'suggestedThreshold'); return v != null ? Math.round(v * 100 * 100) / 100 : undefined; })()}
                    onChange={(v) => setVal('uniquenessConfig', 'maxDuplicateRate', v / 100)}
                    suffix="%"
                    min={0}
                    max={100}
                    placeholder={hasDiscovery ? '' : 'e.g. 1'}
                  />
                </>
              )}
            </div>
          )}

          {/* Ingestion section */}
          {applicableSections.includes('ingestion') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Ingestion</h4>
              <NumberInput
                label="Sync lag tolerance"
                value={getVal('ingestionConfig', 'syncLagToleranceMinutes')}
                onChange={(v) => setVal('ingestionConfig', 'syncLagToleranceMinutes', v)}
                suffix="min"
                min={1}
              />
              <ToleranceSelect
                label="Failure tolerance"
                value={getVal('ingestionConfig', 'failureTolerance') || 'normal'}
                onChange={(v) => setVal('ingestionConfig', 'failureTolerance', v)}
              />
              <StrictnessSelect
                label="Schema drift"
                value={getVal('ingestionConfig', 'schemaDriftStrictness') || 'warn'}
                onChange={(v) => setVal('ingestionConfig', 'schemaDriftStrictness', v)}
              />
            </div>
          )}

          {/* BI section */}
          {applicableSections.includes('bi') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">BI / Reporting</h4>
              <NumberInput
                label="BI freshness"
                value={getVal('biConfig', 'freshnessHours')}
                onChange={(v) => setVal('biConfig', 'freshnessHours', v)}
                suffix="hrs"
                min={1}
              />
              <StrictnessSelect
                label="Upstream break"
                value={getVal('biConfig', 'upstreamBreakStrictness') || 'warn'}
                onChange={(v) => setVal('biConfig', 'upstreamBreakStrictness', v)}
              />
            </div>
          )}

          {/* Orchestration section */}
          {applicableSections.includes('orchestration') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Orchestration</h4>
              <NumberInput
                label="Run latency"
                value={getVal('orchestrationConfig', 'runLatencyMinutes')}
                onChange={(v) => setVal('orchestrationConfig', 'runLatencyMinutes', v)}
                suffix="min"
                min={1}
              />
              <NumberInput
                label="Schedule lag"
                value={getVal('orchestrationConfig', 'scheduleLagMinutes')}
                onChange={(v) => setVal('orchestrationConfig', 'scheduleLagMinutes', v)}
                suffix="min"
                min={1}
              />
              <ToleranceSelect
                label="Failure tolerance"
                value={getVal('orchestrationConfig', 'failureTolerance') || 'normal'}
                onChange={(v) => setVal('orchestrationConfig', 'failureTolerance', v)}
              />
            </div>
          )}

          {/* Transform section */}
          {applicableSections.includes('transform') && (
            <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Transform</h4>
              <ToleranceSelect
                label="Test failure tolerance"
                value={getVal('transformConfig', 'testFailureTolerance') || 'normal'}
                onChange={(v) => setVal('transformConfig', 'testFailureTolerance', v)}
              />
              <NumberInput
                label="Model freshness"
                value={getVal('transformConfig', 'modelFreshnessHours')}
                onChange={(v) => setVal('transformConfig', 'modelFreshnessHours', v)}
                suffix="hrs"
                min={1}
              />
            </div>
          )}
        </div>

        {/* Apply scope selector */}
        <div className="space-y-2">
          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Apply Scope</label>
          <div className="space-y-1.5">
            <label className="flex items-center gap-2 p-2 rounded-lg hover:bg-[var(--overlay-bg)] cursor-pointer transition-colors">
              <input
                type="radio"
                name="scope"
                checked={applyScope === 'selected'}
                onChange={() => setApplyScope('selected')}
                className="accent-slate-500"
              />
              <span className="text-[12px] text-[var(--text)]">
                Apply to selected nodes ({selectedNodeIds.size})
              </span>
            </label>
            {downstreamCount > 0 && (
              <label className="flex items-center gap-2 p-2 rounded-lg hover:bg-[var(--overlay-bg)] cursor-pointer transition-colors">
                <input
                  type="radio"
                  name="scope"
                  checked={applyScope === 'downstream'}
                  onChange={() => setApplyScope('downstream')}
                  className="accent-slate-500"
                />
                <span className="text-[12px] text-[var(--text)]">
                  Apply to downstream ({downstreamCount})
                </span>
              </label>
            )}
            {dominantCategory && typeCount > 1 && (
              <label className="flex items-center gap-2 p-2 rounded-lg hover:bg-[var(--overlay-bg)] cursor-pointer transition-colors">
                <input
                  type="radio"
                  name="scope"
                  checked={applyScope === 'all_of_type'}
                  onChange={() => setApplyScope('all_of_type')}
                  className="accent-slate-500"
                />
                <span className="text-[12px] text-[var(--text)]">
                  Apply to all {dominantCategory} nodes ({typeCount})
                </span>
              </label>
            )}
          </div>
        </div>
      </div>

      {/* Footer (sticky) */}
      <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0 space-y-2">
        {applied ? (
          <div className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-green-600/90 text-white text-center flex items-center justify-center gap-2">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Data SLA applied
          </div>
        ) : (
          <button
            onClick={handleApply}
            disabled={saving || !hasAnyValues}
            className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'Applying...' : (
              <>
                Apply {hasDiscovery ? 'Discovered' : ''} Data SLA to{' '}
                {applyScope === 'selected'
                  ? `${selectedNodeIds.size} node${selectedNodeIds.size !== 1 ? 's' : ''}`
                  : applyScope === 'downstream'
                  ? `${downstreamCount} downstream`
                  : `${typeCount} ${dominantCategory} nodes`}
              </>
            )}
          </button>
        )}

        {/* Remove Data SLA button */}
        {currentPolicy && currentPolicy.status !== 'none' && onRemoveSLA && (
          <button
            onClick={() => {
              const fqns = selectedNodes.map(n => n.fullName || n.name);
              onRemoveSLA(fqns);
            }}
            className="w-full px-4 py-2 text-[12px] font-medium rounded-lg text-red-400 hover:bg-red-500/10 border border-red-500/20 transition-colors"
          >
            Remove Data SLA from {selectedNodeIds.size} node{selectedNodeIds.size !== 1 ? 's' : ''}
          </button>
        )}
      </div>
        </>
      )}

      {/* Bulk apply footer */}
      {bulkDiscoveryState === 'results' && discoveredCount > 0 && (
        <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0">
          {applied ? (
            <div className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-green-600/90 text-white text-center flex items-center justify-center gap-2">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              Data SLA applied to {discoveredCount} nodes
            </div>
          ) : (
            <button
              onClick={handleApplyAll}
              disabled={saving}
              className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? 'Applying...' : `Apply All (${discoveredCount} nodes)`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
