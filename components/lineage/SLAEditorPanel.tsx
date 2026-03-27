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
// Built-in profiles (client-side defaults matching the seeded DB profiles)
// ---------------------------------------------------------------------------

const BUILTIN_PROFILES: SLAProfile[] = [
  {
    id: 'builtin_t0',
    name: 'T0 — Critical',
    description: 'Strictest monitoring for mission-critical assets. 15min freshness, oncall required.',
    isBuiltIn: true,
    criticality: 'critical',
    freshnessConfig: { enabled: true, maxHours: 0.25, warningHours: 0.15 },
    schemaConfig: { enabled: true, strictness: 'strict', allowEvolution: false },
    volumeConfig: { enabled: true, growthRateThreshold: 0.05, minRows: 1 },
    anomalyConfig: { enabled: true, sensitivity: 0.99, lookbackDays: 30 },
    qualityConfig: { enabled: true, maxNullRate: 0.01, maxDuplicateRate: 0.005 },
    ingestionConfig: { syncLagToleranceMinutes: 15, failureTolerance: 'strict', schemaDriftStrictness: 'strict' },
    biConfig: { freshnessHours: 0.25, contentHealthEnabled: true, upstreamBreakStrictness: 'strict' },
    orchestrationConfig: { runLatencyMinutes: 15, scheduleLagMinutes: 5, failureTolerance: 'strict' },
    transformConfig: { testFailureTolerance: 'strict', modelFreshnessHours: 0.25 },
  },
  {
    id: 'builtin_t1',
    name: 'T1 — High',
    description: 'Tight monitoring for high-priority assets. 1hr freshness, oncall required.',
    isBuiltIn: true,
    criticality: 'high',
    freshnessConfig: { enabled: true, maxHours: 1, warningHours: 0.5 },
    schemaConfig: { enabled: true, strictness: 'warn', allowEvolution: false },
    volumeConfig: { enabled: true, growthRateThreshold: 0.10, minRows: 1 },
    anomalyConfig: { enabled: true, sensitivity: 0.97, lookbackDays: 21 },
    qualityConfig: { enabled: true, maxNullRate: 0.02, maxDuplicateRate: 0.01 },
    ingestionConfig: { syncLagToleranceMinutes: 60, failureTolerance: 'strict', schemaDriftStrictness: 'warn' },
    biConfig: { freshnessHours: 1, contentHealthEnabled: true, upstreamBreakStrictness: 'warn' },
    orchestrationConfig: { runLatencyMinutes: 30, scheduleLagMinutes: 10, failureTolerance: 'strict' },
    transformConfig: { testFailureTolerance: 'strict', modelFreshnessHours: 1 },
  },
  {
    id: 'builtin_t2',
    name: 'T2 — Standard',
    description: 'Balanced monitoring for standard-priority assets. 6hr freshness.',
    isBuiltIn: true,
    criticality: 'medium',
    freshnessConfig: { enabled: true, maxHours: 6, warningHours: 3 },
    schemaConfig: { enabled: true, strictness: 'warn', allowEvolution: true },
    volumeConfig: { enabled: true, growthRateThreshold: 0.15, minRows: 1 },
    anomalyConfig: { enabled: true, sensitivity: 0.95, lookbackDays: 14 },
    qualityConfig: { enabled: true, maxNullRate: 0.05, maxDuplicateRate: 0.02 },
    ingestionConfig: { syncLagToleranceMinutes: 360, failureTolerance: 'normal', schemaDriftStrictness: 'warn' },
    biConfig: { freshnessHours: 6, contentHealthEnabled: true, upstreamBreakStrictness: 'warn' },
    orchestrationConfig: { runLatencyMinutes: 60, scheduleLagMinutes: 15, failureTolerance: 'normal' },
    transformConfig: { testFailureTolerance: 'normal', modelFreshnessHours: 6 },
  },
  {
    id: 'builtin_t3',
    name: 'T3 — Low',
    description: 'Lenient monitoring for low-priority assets. 24hr freshness.',
    isBuiltIn: true,
    criticality: 'low',
    freshnessConfig: { enabled: true, maxHours: 24, warningHours: 12 },
    schemaConfig: { enabled: true, strictness: 'ignore', allowEvolution: true },
    volumeConfig: { enabled: true, growthRateThreshold: 0.30, minRows: 0, maxRows: 1000000000 },
    anomalyConfig: { enabled: true, sensitivity: 0.80, lookbackDays: 7 },
    qualityConfig: { enabled: true, maxNullRate: 0.10, maxDuplicateRate: 0.05 },
    ingestionConfig: { syncLagToleranceMinutes: 1440, failureTolerance: 'relaxed', schemaDriftStrictness: 'ignore' },
    biConfig: { freshnessHours: 24, contentHealthEnabled: false, upstreamBreakStrictness: 'ignore' },
    orchestrationConfig: { runLatencyMinutes: 120, scheduleLagMinutes: 30, failureTolerance: 'relaxed' },
    transformConfig: { testFailureTolerance: 'relaxed', modelFreshnessHours: 24 },
  },
];

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
  dataSLAsEnabled?: boolean;
  onApply: (request: SLAAssignRequest, scope: ApplyScope) => void;
  onRemoveSLA?: (nodeFqns: string[]) => void;
  onClose: () => void;
  onClearSelection: () => void;
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
      const target = edge.target;
      const source = edge.source;
      if (source === current && !visited.has(target)) {
        visited.add(target);
        queue.push(target);
      }
    }
  }
  return visited.size - nodeIds.size;
}

function countOfType(category: string, allNodes: UnifiedLineageNode[]): number {
  return allNodes.filter((n) => n.category === category).length;
}

// ---------------------------------------------------------------------------
// Strictness select component
// ---------------------------------------------------------------------------

function StrictnessSelect({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
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

function ToleranceSelect({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
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

function NumberInput({
  value,
  onChange,
  label,
  suffix,
  min,
  max,
}: {
  value: number | undefined;
  onChange: (v: number) => void;
  label: string;
  suffix?: string;
  min?: number;
  max?: number;
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
          className="w-full px-2 py-1.5 text-[12px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
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
  dataSLAsEnabled,
  onApply,
  onRemoveSLA,
  onClose,
  onClearSelection,
}: SLAEditorPanelProps) {
  const [selectedProfileId, setSelectedProfileId] = useState<string>('');
  const [applyScope, setApplyScope] = useState<ApplyScope>('selected');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [dbProfiles, setDbProfiles] = useState<SLAProfile[]>([]);
  // Tracks whether the current selection has been applied — stays true until
  // the user changes the profile, edits overrides, or selects different nodes.
  const [applied, setApplied] = useState(false);
  const prevSavingRef = React.useRef(false);

  // Detect when saving transitions from true → false (apply completed)
  React.useEffect(() => {
    if (prevSavingRef.current && !saving) {
      setApplied(true);
    }
    prevSavingRef.current = !!saving;
  }, [saving]);

  // Reset applied state when user changes anything
  React.useEffect(() => { setApplied(false); }, [selectedProfileId, applyScope]);
  React.useEffect(() => { setApplied(false); }, [selectedNodeIds]);

  // Local overrides — user edits on top of the selected profile.
  // Keys mirror the profile config shape. Only changed fields are tracked.
  const [overrides, setOverrides] = useState<Record<string, any>>({});

  // Reset overrides when profile changes
  const handleProfileChange = useCallback((id: string) => {
    setSelectedProfileId(id);
    setOverrides({});
  }, []);

  // Helper to set a nested override value: setOverride('freshnessConfig', 'maxHours', 6)
  const setOverride = useCallback((section: string, key: string, value: any) => {
    setApplied(false);
    setOverrides((prev) => ({
      ...prev,
      [section]: { ...(prev[section] || {}), [key]: value },
    }));
  }, []);

  // Get the effective value: override > profile > undefined
  const getVal = useCallback(
    (section: string, key: string): any => {
      const ov = overrides[section]?.[key];
      if (ov !== undefined) return ov;
      const profile = dbProfiles.length > 0
        ? dbProfiles.find((p) => p.id === selectedProfileId)
        : BUILTIN_PROFILES.find((p) => p.id === selectedProfileId);
      return (profile as any)?.[section]?.[key];
    },
    [overrides, selectedProfileId, dbProfiles]
  );

  const hasOverrides = Object.keys(overrides).length > 0;

  // Fetch real profiles from DB (seed first, then list)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Seed built-in profiles if they don't exist yet
        await fetch('/api/schedule/policies/seed', { method: 'POST' });
        // Fetch all profiles
        const res = await fetch('/api/schedule/policies/profiles');
        if (res.ok && !cancelled) {
          const data = await res.json();
          const allProfiles = data.profiles || data || [];
          // Filter out deprecated domain-specific profiles
          const DEPRECATED = ['BI Shield', 'Source Guard'];
          setDbProfiles(allProfiles.filter((p: SLAProfile) => !DEPRECATED.includes(p.name)));
        }
      } catch (err) {
        console.error('[PolicyEditor] Failed to load profiles:', err);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Use DB profiles when available, otherwise fall back to hardcoded list
  const profiles = dbProfiles.length > 0 ? dbProfiles : BUILTIN_PROFILES;

  const selectedNodes = useMemo(
    () => getSelectedNodes(selectedNodeIds, allNodes),
    [selectedNodeIds, allNodes]
  );

  const domains = useMemo(() => getDomainsFromNodes(selectedNodes), [selectedNodes]);

  const selectedProfile = profiles.find((p) => p.id === selectedProfileId);

  const applicableSections = useMemo(() => {
    const domainSections = getApplicableSections(domains);
    if (domainSections.length > 0) return domainSections;

    // Fallback: if no domain could be determined (uncategorized nodes),
    // show only the profile's warehouse-equivalent sections (safe default)
    if (selectedProfile) {
      return ['freshness', 'schema', 'volume', 'anomaly', 'quality'];
    }
    return [];
  }, [domains, selectedProfile]);
  const downstreamCount = useMemo(
    () => countDownstream(selectedNodeIds, allEdges),
    [selectedNodeIds, allEdges]
  );

  // Determine dominant category for "all of type" option
  const dominantCategory = selectedNodes.length > 0 ? selectedNodes[0].category : null;
  const typeCount = dominantCategory ? countOfType(dominantCategory, allNodes) : 0;

  // Current effective policy for first selected node
  const firstFqn = selectedNodes[0]?.fullName || selectedNodes[0]?.name || '';
  const currentPolicy = nodeSLAs.get(firstFqn);

  // Domain distribution label
  const domainLabels = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of selectedNodes) {
      const d = categoryToSLADomain(n.category) || n.category;
      counts[d] = (counts[d] || 0) + 1;
    }
    return Object.entries(counts)
      .map(([d, c]) => `${c} ${d}`)
      .join(', ');
  }, [selectedNodes]);

  const handleApply = useCallback(() => {
    if (!selectedProfileId) return;

    // Filter overrides to only include values that actually differ from the profile
    const effectiveOverrides: Record<string, any> = {};
    if (selectedProfile) {
      for (const [section, fields] of Object.entries(overrides)) {
        if (!fields || typeof fields !== 'object') continue;
        const profileSection = (selectedProfile as any)?.[section];
        const diffFields: Record<string, any> = {};
        for (const [key, value] of Object.entries(fields)) {
          const profileValue = profileSection?.[key];
          if (String(value) !== String(profileValue)) {
            diffFields[key] = value;
          }
        }
        if (Object.keys(diffFields).length > 0) {
          effectiveOverrides[section] = diffFields;
        }
      }
    }
    const hasEffectiveOverrides = Object.keys(effectiveOverrides).length > 0;

    const fqns = selectedNodes.map((n) => n.fullName || n.name);
    const request: SLAAssignRequest & { _profileName?: string } = {
      profileId: selectedProfileId,
      assignmentType: applyScope === 'downstream' ? 'branch' : 'direct',
      nodeFqns: applyScope === 'downstream' ? undefined : fqns,
      branchRootFqn: applyScope === 'downstream' ? fqns[0] : undefined,
      overrides: hasEffectiveOverrides ? effectiveOverrides : undefined,
      _profileName: selectedProfile?.name || undefined,
    };

    onApply(request, applyScope);
  }, [selectedProfileId, selectedProfile, selectedNodes, applyScope, onApply, overrides]);

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
        {/* Domain distribution */}
        {domains.size > 1 && (
          <p className="text-[11px] text-[var(--muted)] mt-1">Includes {domainLabels}</p>
        )}
        {/* Current SLA summary */}
        {currentPolicy && currentPolicy.status !== 'none' && selectedNodeIds.size === 1 && (
          <div className="mt-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <span className="text-[11px] text-[var(--muted)]">Current: </span>
            <span className="text-[11px] font-medium" style={{ color: 'var(--text)' }}>
              {currentPolicy.profileName || 'Default'}
            </span>
          </div>
        )}
      </div>

      {/* Data SLA info banner */}
      {dataSLAsEnabled && (
        <div className="mx-4 mt-3 p-2.5 rounded-lg bg-blue-500/10 border border-blue-500/20">
          <p className="text-[10px] text-blue-400">
            Data SLAs are managed in Governance. Changes here will sync automatically.
          </p>
        </div>
      )}

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Profile selector */}
        <div>
          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Apply Profile</label>
          <select
            value={selectedProfileId}
            onChange={(e) => handleProfileChange(e.target.value)}
            className="mt-1 w-full px-3 py-2 text-[13px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
          >
            <option value="">Select a profile...</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {selectedProfile?.description && (
            <p className="text-[11px] text-[var(--muted)] mt-1.5">{selectedProfile.description}</p>
          )}
        </div>

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

        {/* Advanced controls (collapsible) */}
        {selectedProfile && (
          <div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setAdvancedOpen(!advancedOpen)}
                className="flex items-center gap-1.5 text-[12px] text-[var(--muted)] hover:text-[var(--text)] transition-colors"
              >
                <svg
                  className={`w-3 h-3 transition-transform ${advancedOpen ? 'rotate-90' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                Advanced Controls
              </button>
              {hasOverrides && (
                <button
                  onClick={() => setOverrides({})}
                  className="text-[10px] text-amber-400 hover:text-amber-300 underline"
                >
                  Reset overrides
                </button>
              )}
            </div>

            {advancedOpen && (
              <div className="mt-3 space-y-4">
                {applicableSections.length === 0 && (
                  <p className="text-[11px] text-[var(--muted)] italic">
                    No domain-specific controls for selected node type.
                  </p>
                )}
                {/* Freshness section */}
                {applicableSections.includes('freshness') && (
                  <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                    <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Freshness</h4>
                    <NumberInput
                      label="Max hours"
                      value={getVal('freshnessConfig', 'maxHours')}
                      onChange={(v) => setOverride('freshnessConfig', 'maxHours', v)}
                      suffix="hrs"
                      min={1}
                    />
                    <NumberInput
                      label="Warning"
                      value={getVal('freshnessConfig', 'warningHours')}
                      onChange={(v) => setOverride('freshnessConfig', 'warningHours', v)}
                      suffix="hrs"
                      min={1}
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
                      onChange={(v) => setOverride('schemaConfig', 'strictness', v)}
                    />
                  </div>
                )}

                {/* Volume section */}
                {applicableSections.includes('volume') && (
                  <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                    <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Volume</h4>
                    <NumberInput
                      label="Growth threshold"
                      value={(() => { const v = getVal('volumeConfig', 'growthRateThreshold'); return v != null ? v * 100 : undefined; })()}
                      onChange={(v) => setOverride('volumeConfig', 'growthRateThreshold', v / 100)}
                      suffix="%"
                      min={1}
                      max={100}
                    />
                    <NumberInput
                      label="Min rows"
                      value={getVal('volumeConfig', 'minRows')}
                      onChange={(v) => setOverride('volumeConfig', 'minRows', v)}
                      min={0}
                    />
                    <NumberInput
                      label="Max rows"
                      value={getVal('volumeConfig', 'maxRows')}
                      onChange={(v) => setOverride('volumeConfig', 'maxRows', v)}
                      min={0}
                    />
                  </div>
                )}

                {/* Anomaly section */}
                {applicableSections.includes('anomaly') && (
                  <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                    <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Anomaly Detection</h4>
                    <NumberInput
                      label="Sensitivity"
                      value={(() => { const v = getVal('anomalyConfig', 'sensitivity'); return v != null ? v * 100 : undefined; })()}
                      onChange={(v) => setOverride('anomalyConfig', 'sensitivity', v / 100)}
                      suffix="%"
                      min={50}
                      max={100}
                    />
                    <NumberInput
                      label="Lookback days"
                      value={getVal('anomalyConfig', 'lookbackDays')}
                      onChange={(v) => setOverride('anomalyConfig', 'lookbackDays', v)}
                      suffix="days"
                      min={7}
                      max={90}
                    />
                  </div>
                )}

                {/* Quality section */}
                {applicableSections.includes('quality') && (
                  <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                    <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Quality</h4>
                    <NumberInput
                      label="Max null rate"
                      value={(() => { const v = getVal('qualityConfig', 'maxNullRate'); return v != null ? v * 100 : undefined; })()}
                      onChange={(v) => setOverride('qualityConfig', 'maxNullRate', v / 100)}
                      suffix="%"
                      min={0}
                      max={100}
                    />
                    <NumberInput
                      label="Max dupe rate"
                      value={(() => { const v = getVal('qualityConfig', 'maxDuplicateRate'); return v != null ? v * 100 : undefined; })()}
                      onChange={(v) => setOverride('qualityConfig', 'maxDuplicateRate', v / 100)}
                      suffix="%"
                      min={0}
                      max={100}
                    />
                  </div>
                )}

                {/* Ingestion section */}
                {applicableSections.includes('ingestion') && (
                  <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                    <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">Ingestion</h4>
                    <NumberInput
                      label="Sync lag tolerance"
                      value={getVal('ingestionConfig', 'syncLagToleranceMinutes')}
                      onChange={(v) => setOverride('ingestionConfig', 'syncLagToleranceMinutes', v)}
                      suffix="min"
                      min={1}
                    />
                    <ToleranceSelect
                      label="Failure tolerance"
                      value={getVal('ingestionConfig', 'failureTolerance') || 'normal'}
                      onChange={(v) => setOverride('ingestionConfig', 'failureTolerance', v)}
                    />
                    <StrictnessSelect
                      label="Schema drift"
                      value={getVal('ingestionConfig', 'schemaDriftStrictness') || 'warn'}
                      onChange={(v) => setOverride('ingestionConfig', 'schemaDriftStrictness', v)}
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
                      onChange={(v) => setOverride('biConfig', 'freshnessHours', v)}
                      suffix="hrs"
                      min={1}
                    />
                    <StrictnessSelect
                      label="Upstream break"
                      value={getVal('biConfig', 'upstreamBreakStrictness') || 'warn'}
                      onChange={(v) => setOverride('biConfig', 'upstreamBreakStrictness', v)}
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
                      onChange={(v) => setOverride('orchestrationConfig', 'runLatencyMinutes', v)}
                      suffix="min"
                      min={1}
                    />
                    <NumberInput
                      label="Schedule lag"
                      value={getVal('orchestrationConfig', 'scheduleLagMinutes')}
                      onChange={(v) => setOverride('orchestrationConfig', 'scheduleLagMinutes', v)}
                      suffix="min"
                      min={1}
                    />
                    <ToleranceSelect
                      label="Failure tolerance"
                      value={getVal('orchestrationConfig', 'failureTolerance') || 'normal'}
                      onChange={(v) => setOverride('orchestrationConfig', 'failureTolerance', v)}
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
                      onChange={(v) => setOverride('transformConfig', 'testFailureTolerance', v)}
                    />
                    <NumberInput
                      label="Model freshness"
                      value={getVal('transformConfig', 'modelFreshnessHours')}
                      onChange={(v) => setOverride('transformConfig', 'modelFreshnessHours', v)}
                      suffix="hrs"
                      min={1}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Apply scope selector */}
        {selectedProfileId && (
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
        )}
      </div>

      {/* Footer (sticky) */}
      <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0 space-y-2">
        {/* Apply button */}
        {selectedProfileId && (
          <>
            {applied ? (
              <div className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-green-600/90 text-white text-center flex items-center justify-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                {selectedProfile?.name || 'Data SLA'} applied
              </div>
            ) : (
              <button
                onClick={handleApply}
                disabled={saving}
                className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white transition-all disabled:opacity-70"
              >
                {saving ? 'Applying...' : (
                  <>
                    Apply {selectedProfile?.name || 'Data SLA'}{hasOverrides ? ' (custom)' : ''} to{' '}
                    {applyScope === 'selected'
                      ? `${selectedNodeIds.size} node${selectedNodeIds.size !== 1 ? 's' : ''}`
                      : applyScope === 'downstream'
                      ? `${downstreamCount} downstream`
                      : `${typeCount} ${dominantCategory} nodes`}
                  </>
                )}
              </button>
            )}
          </>
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
    </div>
  );
}
