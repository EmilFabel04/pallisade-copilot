'use client';

import React, { useState, useMemo, useCallback, useEffect } from 'react';
import type {
  SLAProfile,
  EffectiveSLAPolicy,
  SLAAssignRequest,
  SLADomain,
} from '@/types/sla';
import { PIPELINE_SLA_FIELDS, DOMAIN_LABELS, type PipelineSLAFieldDef } from '@/lib/pipeline-sla-fields';

// ---------------------------------------------------------------------------
// Built-in profiles (T0-T3 tiers)
// ---------------------------------------------------------------------------

const BUILTIN_PROFILES: SLAProfile[] = [
  {
    id: '__t0', name: 'T0 — Critical',
    description: 'Strictest operational expectations', isBuiltIn: true, criticality: 'critical',
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
    id: '__t1', name: 'T1 — High',
    description: 'High reliability expectations', isBuiltIn: true, criticality: 'high',
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
    id: '__t2', name: 'T2 — Standard',
    description: 'Standard operational baseline', isBuiltIn: true, criticality: 'medium',
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
    id: '__t3', name: 'T3 — Low',
    description: 'Relaxed expectations', isBuiltIn: true, criticality: 'low',
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
// Platform → domain mapping
// ---------------------------------------------------------------------------

const PLATFORM_DOMAIN_MAP: Record<string, SLADomain> = {
  fivetran: 'ingestion', airbyte: 'ingestion', stitch: 'ingestion', hevo: 'ingestion', meltano: 'ingestion',
  airflow: 'orchestration', dagster: 'orchestration', prefect: 'orchestration', n8n: 'orchestration', argo: 'orchestration',
  dbt: 'transform', dbt_cloud: 'transform', dbt_core: 'transform',
  metabase: 'bi', looker: 'bi', tableau: 'bi', powerbi: 'bi',
};

const LAYER_DOMAIN_MAP: Record<string, SLADomain> = {
  INGESTION: 'ingestion',
  ORCHESTRATION: 'orchestration',
  TRANSFORMATION: 'transform',
  REPORTING: 'bi',
};

function detectDomain(node: any): SLADomain {
  const platform = (node.platform || '').toLowerCase();
  if (PLATFORM_DOMAIN_MAP[platform]) return PLATFORM_DOMAIN_MAP[platform];
  const layer = (node.layer || '').toUpperCase();
  if (LAYER_DOMAIN_MAP[layer]) return LAYER_DOMAIN_MAP[layer];
  return 'warehouse';
}

// ---------------------------------------------------------------------------
// Types & helpers
// ---------------------------------------------------------------------------

export type ApplyScope = 'selected' | 'downstream' | 'all_of_domain';

interface PipelineSLAEditorPanelProps {
  selectedNodeIds: Set<string>;
  allNodes: any[];
  stackId: string;
  nodeSLAs: Map<string, EffectiveSLAPolicy>;
  saving: boolean;
  dataSLAsEnabled?: boolean;
  slaAllowOverrides?: boolean;
  onApply: (request: SLAAssignRequest & { _profileName?: string }, scope: string) => void;
  onRemoveSLA?: (nodeFqns: string[]) => void;
  onClose: () => void;
  onClearSelection: () => void;
}

function getSelectedNodes(ids: Set<string>, allNodes: any[]): any[] {
  return allNodes.filter((n) => ids.has(n.id));
}

function countOfDomain(domain: SLADomain, allNodes: any[]): number {
  return allNodes.filter((n) => detectDomain(n) === domain).length;
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function PipelineSLAEditorPanel({
  selectedNodeIds,
  allNodes,
  stackId,
  nodeSLAs,
  saving,
  dataSLAsEnabled,
  slaAllowOverrides,
  onApply,
  onRemoveSLA,
  onClose,
  onClearSelection,
}: PipelineSLAEditorPanelProps) {
  const [selectedProfileId, setSelectedProfileId] = useState<string>('');
  const [applyScope, setApplyScope] = useState<ApplyScope>('selected');
  const [dbProfiles, setDbProfiles] = useState<SLAProfile[]>([]);
  const [applied, setApplied] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const prevSavingRef = React.useRef(false);

  // Detect when saving transitions true -> false (apply completed)
  useEffect(() => {
    if (prevSavingRef.current && !saving) setApplied(true);
    prevSavingRef.current = saving;
  }, [saving]);

  // Reset applied state on user changes
  useEffect(() => { setApplied(false); }, [selectedProfileId, applyScope]);
  useEffect(() => { setApplied(false); }, [selectedNodeIds]);

  const handleProfileChange = useCallback((id: string) => {
    setSelectedProfileId(id);
    setOverrides({});
  }, []);

  // Fetch DB profiles
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await fetch('/api/schedule/policies/seed', { method: 'POST' });
        const res = await fetch('/api/schedule/policies/profiles');
        if (res.ok && !cancelled) {
          const data = await res.json();
          const all = data.profiles || data || [];
          const DEPRECATED = ['BI Shield', 'Source Guard'];
          setDbProfiles(all.filter((p: SLAProfile) => !DEPRECATED.includes(p.name)));
        }
      } catch (err) {
        console.error('[PipelineSLAEditorPanel] Failed to load profiles:', err);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const profiles = dbProfiles.length > 0 ? dbProfiles : BUILTIN_PROFILES;

  const selectedNodes = useMemo(
    () => getSelectedNodes(selectedNodeIds, allNodes),
    [selectedNodeIds, allNodes],
  );

  // Detect dominant domain from selected nodes
  const dominantDomain = useMemo<SLADomain>(() => {
    const counts: Record<string, number> = {};
    for (const n of selectedNodes) {
      const d = detectDomain(n);
      counts[d] = (counts[d] || 0) + 1;
    }
    let best: SLADomain = 'warehouse';
    let bestCount = 0;
    for (const [d, c] of Object.entries(counts)) {
      if (c > bestCount) { best = d as SLADomain; bestCount = c; }
    }
    return best;
  }, [selectedNodes]);

  const fields = PIPELINE_SLA_FIELDS[dominantDomain] || PIPELINE_SLA_FIELDS.warehouse;
  const domainCount = useMemo(() => countOfDomain(dominantDomain, allNodes), [dominantDomain, allNodes]);

  const selectedProfile = profiles.find((p) => p.id === selectedProfileId);

  // Get profile default for a field key like "ingestion.syncLagToleranceMinutes"
  const getProfileDefault = useCallback((fieldKey: string): string => {
    if (!selectedProfile) return '';
    const [section, key] = fieldKey.split('.');
    const configKey = section + 'Config';
    const val = (selectedProfile as any)?.[configKey]?.[key];
    return val != null ? String(val) : '';
  }, [selectedProfile]);

  // Effective value: override > profile default
  const getFieldValue = useCallback((fieldKey: string): string => {
    if (overrides[fieldKey] !== undefined) return overrides[fieldKey];
    return getProfileDefault(fieldKey);
  }, [overrides, getProfileDefault]);

  const hasOverrides = Object.keys(overrides).length > 0;

  // First selected node's current policy
  const firstNode = selectedNodes[0];
  const firstFqn = firstNode?.metadata?.fqn || firstNode?.name || '';
  const currentPolicy = nodeSLAs.get(firstFqn);

  // Domain label for selected nodes
  const domainLabels = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of selectedNodes) {
      const d = detectDomain(n);
      const label = DOMAIN_LABELS[d] || d;
      counts[label] = (counts[label] || 0) + 1;
    }
    return Object.entries(counts).map(([d, c]) => `${c} ${d}`).join(', ');
  }, [selectedNodes]);

  const handleApply = useCallback(() => {
    if (!selectedProfileId) return;

    // Build overrides object grouped by config section
    const effectiveOverrides: Record<string, Record<string, unknown>> = {};
    for (const f of fields) {
      const val = overrides[f.key];
      if (val === undefined) continue;
      const profileDefault = getProfileDefault(f.key);
      if (val === profileDefault) continue;
      const [section, key] = f.key.split('.');
      if (!effectiveOverrides[section]) effectiveOverrides[section] = {};
      effectiveOverrides[section][key] = f.type === 'number' ? Number(val) : val;
    }
    const hasEffective = Object.keys(effectiveOverrides).length > 0;

    const fqns = selectedNodes.map((n) => n.metadata?.fqn || n.name);
    const request: SLAAssignRequest & { _profileName?: string } = {
      profileId: selectedProfileId,
      assignmentType: applyScope === 'selected' ? 'direct' : 'direct',
      nodeFqns: fqns,
      nodeDomain: dominantDomain,
      overrides: hasEffective ? effectiveOverrides : undefined,
      _profileName: selectedProfile?.name,
    };

    onApply(request, applyScope);
  }, [selectedProfileId, selectedProfile, selectedNodes, applyScope, onApply, fields, overrides, getProfileDefault, dominantDomain]);

  // ─── Empty state ───────────────────────────────────────────────────
  if (selectedNodeIds.size === 0) {
    return (
      <div className="w-80 border-l border-slate-500/20 bg-[var(--surface-sunken)] p-4 flex flex-col items-center justify-center text-center h-full">
        <svg className="w-12 h-12 text-slate-400/30 mb-3" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
        <p className="text-[13px] text-[var(--muted)]">
          Click a node to define its Pipeline SLA.
        </p>
        <p className="text-[11px] text-[var(--muted)] mt-1">
          Shift+click to select multiple nodes.
        </p>
      </div>
    );
  }

  // ─── Main panel ────────────────────────────────────────────────────
  return (
    <div className="w-80 border-l border-slate-500/20 bg-[var(--surface-sunken)] flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-[var(--subtle-border)] flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-[14px] font-semibold text-[var(--text)] flex items-center gap-2">
            <svg className="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            Pipeline SLA Editor
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
        {selectedNodes.length > 1 && (
          <p className="text-[11px] text-[var(--muted)] mt-1">Includes {domainLabels}</p>
        )}
        {/* Domain tag */}
        <div className="mt-2 flex items-center gap-1.5">
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--muted)] border border-[var(--subtle-border)]">
            {DOMAIN_LABELS[dominantDomain] || dominantDomain}
          </span>
        </div>
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

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Profile selector */}
        {(!dataSLAsEnabled || slaAllowOverrides) && (
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Apply Profile</label>
            <select
              value={selectedProfileId}
              onChange={(e) => handleProfileChange(e.target.value)}
              className="mt-1 w-full px-3 py-2 text-[13px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
            >
              <option value="">Select a profile...</option>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            {selectedProfile?.description && (
              <p className="text-[11px] text-[var(--muted)] mt-1.5">{selectedProfile.description}</p>
            )}
          </div>
        )}

        {/* Selected node names (up to 5) */}
        {selectedNodes.length <= 5 && (
          <div className="space-y-1">
            {selectedNodes.map((n) => (
              <div key={n.id} className="text-[11px] text-[var(--text-tertiary)] font-mono truncate">
                {n.metadata?.fqn || n.name}
              </div>
            ))}
          </div>
        )}

        {/* Tool-specific fields — shown when a profile is selected */}
        {selectedProfile && (
          <div className="space-y-2.5 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">
                {DOMAIN_LABELS[dominantDomain]} Controls
              </h4>
              {hasOverrides && (
                <button
                  onClick={() => setOverrides({})}
                  className="text-[10px] text-amber-400 hover:text-amber-300 underline"
                >
                  Reset
                </button>
              )}
            </div>
            {fields.map((f) => (
              <div key={f.key}>
                <label className="text-[10px] text-[var(--muted)] block mb-1">
                  {f.label}{f.unit ? ` (${f.unit})` : ''}
                </label>
                {f.type === 'select' ? (
                  <select
                    value={getFieldValue(f.key)}
                    onChange={(e) => setOverrides((prev) => ({ ...prev, [f.key]: e.target.value }))}
                    className="w-full px-2 py-1.5 text-[11px] bg-[var(--surface-sunken)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
                  >
                    <option value="">Not set</option>
                    {f.options?.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="number"
                    value={getFieldValue(f.key)}
                    onChange={(e) => setOverrides((prev) => ({ ...prev, [f.key]: e.target.value }))}
                    placeholder={f.placeholder}
                    className="w-full px-2 py-1.5 text-[11px] bg-[var(--surface-sunken)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
                  />
                )}
              </div>
            ))}
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
                  name="pipeline-sla-scope"
                  checked={applyScope === 'selected'}
                  onChange={() => setApplyScope('selected')}
                  className="accent-slate-500"
                />
                <span className="text-[12px] text-[var(--text)]">
                  Selected nodes ({selectedNodeIds.size})
                </span>
              </label>
              {domainCount > selectedNodeIds.size && (
                <label className="flex items-center gap-2 p-2 rounded-lg hover:bg-[var(--overlay-bg)] cursor-pointer transition-colors">
                  <input
                    type="radio"
                    name="pipeline-sla-scope"
                    checked={applyScope === 'all_of_domain'}
                    onChange={() => setApplyScope('all_of_domain')}
                    className="accent-slate-500"
                  />
                  <span className="text-[12px] text-[var(--text)]">
                    All {DOMAIN_LABELS[dominantDomain]} nodes ({domainCount})
                  </span>
                </label>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0 space-y-2">
        {selectedProfileId && (!dataSLAsEnabled || slaAllowOverrides) && (
          <>
            {applied ? (
              <div className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-green-600/90 text-white text-center flex items-center justify-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                {selectedProfile?.name || 'Pipeline SLA'} applied
              </div>
            ) : (
              <button
                onClick={handleApply}
                disabled={saving}
                className="w-full px-4 py-2.5 text-[13px] font-medium rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white transition-all disabled:opacity-70"
              >
                {saving ? 'Applying...' : (
                  <>
                    Apply {selectedProfile?.name || 'Pipeline SLA'}{hasOverrides ? ' (custom)' : ''} to{' '}
                    {applyScope === 'selected'
                      ? `${selectedNodeIds.size} node${selectedNodeIds.size !== 1 ? 's' : ''}`
                      : `${domainCount} ${DOMAIN_LABELS[dominantDomain]} nodes`}
                  </>
                )}
              </button>
            )}
          </>
        )}

        {/* Remove Pipeline SLA */}
        {currentPolicy && currentPolicy.status !== 'none' && onRemoveSLA && (
          <button
            onClick={() => {
              const fqns = selectedNodes.map((n) => n.metadata?.fqn || n.name);
              onRemoveSLA(fqns);
            }}
            className="w-full px-4 py-2 text-[12px] font-medium rounded-lg text-red-400 hover:bg-red-500/10 border border-red-500/20 transition-colors"
          >
            Remove Pipeline SLA from {selectedNodeIds.size} node{selectedNodeIds.size !== 1 ? 's' : ''}
          </button>
        )}
      </div>
    </div>
  );
}
