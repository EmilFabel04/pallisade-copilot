'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import { PolicyFieldBadge } from './PolicyFieldBadge';
import { getMonitorDefinition } from '@/types/monitor-catalog';
import {
  POLICY_FIELD_MAP,
  getPolicyValueForField,
  isLessStrictClient,
} from '@/lib/policy-utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AssetPrefill {
  nodeId: string;
  fqn: string;
  name: string;
  platform?: string;
  domain?: string;
  criticality?: string;
  nodeType?: string;
}

export interface SingleAssetMonitorModalProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
  stackId?: string;
  prefill?: AssetPrefill | null;
}

interface MonitorRecommendation {
  monitor_key: string;
  target_fqn: string;
  target_node_id?: string;
  source: string;
  priority: number;
  reason: string;
  already_monitored: boolean;
  config_hints?: Record<string, any>;
  depth?: number;
}

type Step = 1 | 2 | 3 | 4 | 5;

const STEP_LABELS: Record<Step, string> = {
  1: 'Pick Asset',
  2: 'Select Monitors',
  3: 'Configure',
  4: 'Schedule',
  5: 'Create',
};

// ---------------------------------------------------------------------------
// Monitor type labels
// ---------------------------------------------------------------------------

const MONITOR_TYPE_LABELS: Record<string, string> = {
  FRESHNESS: 'Freshness',
  VOLUME: 'Volume',
  SCHEMA_CHANGE: 'Schema Change',
  NULL_RATE: 'Null Rate',
  DISTRIBUTION: 'Distribution',
  CUSTOM_SQL: 'Custom SQL',
  ANOMALY: 'Anomaly',
  REFERENTIAL: 'Referential Integrity',
  SYNC_LAG: 'Sync Lag',
  FAILED_SYNCS: 'Failed Syncs',
  CONNECTOR_SCHEMA_DRIFT: 'Connector Schema Drift',
  DAG_LAST_RUN: 'DAG Last Run',
  DAG_SCHEDULE_LAG: 'DAG Schedule Lag',
  TASK_FAILURE_RATE: 'Task Failure Rate',
  DBT_TEST_FAILURES: 'dbt Test Failures',
  DBT_MODEL_FRESHNESS: 'dbt Model Freshness',
  DBT_SOURCE_FRESHNESS: 'dbt Source Freshness',
  BI_FRESHNESS_PROXY: 'BI Freshness',
  BI_UPSTREAM_BREAK_RISK: 'BI Upstream Risk',
  BI_CONTENT_HEALTH: 'BI Content Health',
  BI_REFRESH_FAILURE: 'BI Refresh Failure',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SingleAssetMonitorModal({
  open,
  onClose,
  onComplete,
  stackId,
  prefill,
}: SingleAssetMonitorModalProps) {
  const [step, setStep] = useState<Step>(prefill ? 2 : 1);

  // Step 1: Asset search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<AssetPrefill[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<AssetPrefill | null>(
    prefill || null,
  );

  // Step 2: Monitor selection
  const [recommendations, setRecommendations] = useState<MonitorRecommendation[]>([]);
  const [selectedMonitors, setSelectedMonitors] = useState<Set<string>>(new Set());
  const [recsLoading, setRecsLoading] = useState(false);

  // Step 3: Configure & Policy
  const [resolvedPolicies, setResolvedPolicies] = useState<Record<string, any>>({});
  const [policyLoading, setPolicyLoading] = useState(false);
  const [monitorConfigs, setMonitorConfigs] = useState<Record<number, { config: Record<string, any>; overrides: string[] }>>({});

  // Step 4: Schedule
  const [schedule, setSchedule] = useState('0 */6 * * *');
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  );

  // Step 5: Alerts & Create
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);
  const [watchName, setWatchName] = useState('');
  const [creating, setCreating] = useState(false);

  // Reset on open
  useEffect(() => {
    if (open) {
      const asset = prefill || null;
      setSelectedAsset(asset);
      setStep(asset ? 2 : 1);
      setSearchQuery('');
      setSearchResults([]);
      setRecommendations([]);
      setSelectedMonitors(new Set());
      setResolvedPolicies({});
      setMonitorConfigs({});
      setWatchName(asset ? `Monitors — ${asset.name}` : '');
      setCreating(false);
    }
  }, [open, prefill]);

  // Fetch recommendations when asset is selected and entering step 2
  const fetchRecommendations = useCallback(async () => {
    if (!stackId || !selectedAsset) return;
    setRecsLoading(true);
    try {
      const params = new URLSearchParams({
        action: 'recommend-monitors',
        id: selectedAsset.nodeId,
      });
      const res = await fetch(
        `/api/pipeline/${stackId}/lineage/engine?${params}`,
      );
      if (res.ok) {
        const data = await res.json();
        const recs: MonitorRecommendation[] = data.recommendations || [];
        setRecommendations(recs);
        // Pre-select non-already-monitored recommendations
        const preSelected = new Set<string>();
        recs.forEach((rec, i) => {
          if (!rec.already_monitored) {
            preSelected.add(`${i}`);
          }
        });
        setSelectedMonitors(preSelected);
      }
    } catch (err) {
      console.error('[SingleAssetMonitor] recommendations error:', err);
    } finally {
      setRecsLoading(false);
    }
  }, [stackId, selectedAsset]);

  // Fetch policies when entering step 3
  const fetchPolicies = useCallback(async () => {
    if (!selectedAsset) return;
    setPolicyLoading(true);
    try {
      const res = await fetch('/api/schedule/policies/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nodes: [{ fqn: selectedAsset.fqn, domain: selectedAsset.domain, criticality: selectedAsset.criticality }],
          stackId,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setResolvedPolicies(data.policies || {});
      }
    } catch (err) {
      console.warn('[SingleAssetMonitor] Policy resolve failed:', err);
    } finally {
      setPolicyLoading(false);
    }
  }, [selectedAsset, stackId]);

  // Initialize configs from recommendations + policy
  const initConfigs = useCallback(() => {
    const policy = resolvedPolicies[selectedAsset?.fqn || ''];
    const configs: Record<number, { config: Record<string, any>; overrides: string[] }> = {};
    recommendations.forEach((rec, i) => {
      if (!selectedMonitors.has(`${i}`)) return;
      const baseConfig = { ...(rec.config_hints || {}) };
      const overrides: string[] = [];
      // Fill policy defaults for fields not already in config_hints
      if (policy) {
        const fieldMap = POLICY_FIELD_MAP[rec.monitor_key] || {};
        for (const fieldKey of Object.keys(fieldMap)) {
          const policyVal = getPolicyValueForField(rec.monitor_key, fieldKey, policy);
          if (policyVal == null) continue;
          if (!(fieldKey in baseConfig)) {
            // No config_hint — use policy default
            baseConfig[fieldKey] = policyVal;
          } else if (String(baseConfig[fieldKey]) !== String(policyVal)) {
            // config_hint differs from policy — mark as pre-existing override
            overrides.push(fieldKey);
          }
        }
      }
      configs[i] = { config: baseConfig, overrides };
    });
    setMonitorConfigs(configs);
  }, [recommendations, selectedMonitors, resolvedPolicies, selectedAsset]);

  // Search assets
  const handleSearch = useCallback(async () => {
    if (!stackId || !searchQuery.trim()) return;
    setSearchLoading(true);
    try {
      const params = new URLSearchParams({
        action: 'search',
        q: searchQuery,
      });
      const res = await fetch(
        `/api/pipeline/${stackId}/lineage/engine?${params}`,
      );
      if (res.ok) {
        const data = await res.json();
        const results: AssetPrefill[] = (data.results || []).map((r: any) => ({
          nodeId: r.id,
          fqn: r.fqn || r.name,
          name: r.name,
          platform: r.platform,
          domain: r.domain,
          criticality: r.criticality,
          nodeType: r.nodeType || r.node_type,
        }));
        setSearchResults(results);
      }
    } catch (err) {
      console.error('[SingleAssetMonitor] search error:', err);
    } finally {
      setSearchLoading(false);
    }
  }, [stackId, searchQuery]);

  // Step navigation
  const goToStep = useCallback(
    async (target: Step) => {
      if (target === 2) fetchRecommendations();
      if (target === 3) {
        await fetchPolicies();
        // initConfigs will be called via effect when policies load
      }
      setStep(target);
    },
    [fetchRecommendations, fetchPolicies],
  );

  // Initialize configs when policies finish loading (entering step 3)
  useEffect(() => {
    if (step === 3 && !policyLoading) {
      initConfigs();
    }
  }, [step, policyLoading, initConfigs]);

  const canGoNext = useMemo(() => {
    switch (step) {
      case 1: return selectedAsset !== null;
      case 2: return selectedMonitors.size > 0;
      case 3: return true; // configure step is always valid
      case 4: return schedule.trim().length > 0;
      case 5: return watchName.trim().length > 0;
      default: return false;
    }
  }, [step, selectedAsset, selectedMonitors, schedule, watchName]);

  // Toggle monitor
  const toggleMonitor = useCallback((key: string) => {
    setSelectedMonitors((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Update a config field for a monitor
  const handleConfigChange = useCallback((recIdx: number, fieldKey: string, value: any) => {
    setMonitorConfigs((prev) => {
      const mc = prev[recIdx] || { config: {}, overrides: [] };
      const newConfig = { ...mc.config, [fieldKey]: value };
      // Track overrides: check if value differs from policy
      const policy = resolvedPolicies[selectedAsset?.fqn || ''];
      const rec = recommendations[recIdx];
      const policyVal = rec ? getPolicyValueForField(rec.monitor_key, fieldKey, policy) : undefined;
      let newOverrides = [...mc.overrides];
      if (policyVal !== undefined && String(value) !== String(policyVal)) {
        if (!newOverrides.includes(fieldKey)) newOverrides.push(fieldKey);
      } else {
        newOverrides = newOverrides.filter((k) => k !== fieldKey);
      }
      return { ...prev, [recIdx]: { config: newConfig, overrides: newOverrides } };
    });
  }, [resolvedPolicies, selectedAsset, recommendations]);

  // Reset a config field to policy value
  const handleResetField = useCallback((recIdx: number, fieldKey: string) => {
    const policy = resolvedPolicies[selectedAsset?.fqn || ''];
    const rec = recommendations[recIdx];
    if (!rec) return;
    const policyVal = getPolicyValueForField(rec.monitor_key, fieldKey, policy);
    if (policyVal !== undefined) {
      handleConfigChange(recIdx, fieldKey, policyVal);
    }
  }, [resolvedPolicies, selectedAsset, recommendations, handleConfigChange]);

  // Create plan via 3-step pipeline
  const handleCreate = useCallback(async () => {
    if (!selectedAsset) return;
    setCreating(true);
    try {
      const selectedRecs = recommendations
        .map((rec, i) => ({ rec, origIdx: i }))
        .filter(({ origIdx }) => selectedMonitors.has(`${origIdx}`))
        .map(({ rec, origIdx }) => {
          const mc = monitorConfigs[origIdx];
          return {
            monitor_key: rec.monitor_key,
            target_fqn: rec.target_fqn,
            target_node_id: rec.target_node_id,
            config_hints: mc ? mc.config : (rec.config_hints || {}),
            depth: rec.depth || 0,
            priority: rec.priority || 1,
          };
        });

      const groups = [{
        anchor_name: selectedAsset.name,
        anchor_fqn: selectedAsset.fqn,
        anchor_id: selectedAsset.nodeId,
        anchor_node_type: selectedAsset.nodeType || 'table',
        anchor_platform: selectedAsset.platform || 'unknown',
        watch_type: 'pipeline_health',
        recommendations: selectedRecs,
      }];

      const res = await fetch('/api/schedule/plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: watchName,
          scopeType: 'asset',
          scopeConfig: { nodeIds: [selectedAsset.nodeId] },
          mode: 'manual',
          families: [],
          schedule,
          timezone,
          alertChannels,
          alertOnStatus,
          groups,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Failed to create monitors');
      }

      onComplete();
      onClose();
    } catch (err: any) {
      console.error('[SingleAssetMonitor] create error:', err);
    } finally {
      setCreating(false);
    }
  }, [
    selectedAsset, recommendations, selectedMonitors, monitorConfigs,
    watchName, schedule, timezone, alertChannels, alertOnStatus,
    onComplete, onClose,
  ]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-[640px] max-h-[85vh] bg-[var(--bg)] border border-[var(--border)] rounded-xl shadow-2xl flex flex-col overflow-hidden">
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-4">
            <h2 className="text-[16px] font-semibold text-[var(--text)]">
              Single Asset Monitor
            </h2>
            <div className="flex items-center gap-1">
              {([1, 2, 3, 4, 5] as Step[]).map((s) => (
                <span
                  key={s}
                  className={cn(
                    'w-2 h-2 rounded-full',
                    s === step ? 'bg-[var(--accent)]' : s < step ? 'bg-[var(--accent)]/40' : 'bg-[var(--muted)]/20',
                  )}
                />
              ))}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-[var(--subtle-bg)] rounded-lg transition-colors"
          >
            <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* ---- Body ---- */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Step 1: Pick Asset */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Pick an Asset
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Search for the asset you want to monitor.
                </p>
              </div>

              {/* Search */}
              <div className="flex gap-2">
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  placeholder="Search by name or FQN..."
                  className="flex-1 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] placeholder:text-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)]"
                />
                <button
                  onClick={handleSearch}
                  disabled={!searchQuery.trim() || searchLoading}
                  className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-[13px] font-medium disabled:opacity-40"
                >
                  {searchLoading ? '...' : 'Search'}
                </button>
              </div>

              {/* Results */}
              {searchResults.length > 0 && (
                <div className="space-y-1 max-h-[300px] overflow-y-auto">
                  {searchResults.map((asset) => (
                    <button
                      key={asset.nodeId}
                      onClick={() => {
                        setSelectedAsset(asset);
                        setWatchName(`Monitors — ${asset.name}`);
                      }}
                      className={cn(
                        'w-full text-left px-3 py-2.5 rounded-lg border transition-colors',
                        selectedAsset?.nodeId === asset.nodeId
                          ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                          : 'border-[var(--border)] hover:border-[var(--accent)] bg-[var(--surface)]',
                      )}
                    >
                      <p className="text-[13px] font-medium text-[var(--text)]">
                        {asset.name}
                      </p>
                      <p className="text-[11px] text-[var(--muted)] font-mono truncate">
                        {asset.fqn}
                      </p>
                      {asset.platform && (
                        <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] bg-[var(--muted)]/10 text-[var(--muted)]">
                          {asset.platform}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}

              {/* Selected asset indicator */}
              {selectedAsset && (
                <div className="rounded-lg border border-[var(--accent)]/30 bg-[var(--accent)]/5 p-3">
                  <p className="text-[12px] text-[var(--muted)]">Selected asset:</p>
                  <p className="text-[13px] font-medium text-[var(--text)] mt-0.5">
                    {selectedAsset.name}
                  </p>
                  <p className="text-[11px] text-[var(--muted)] font-mono">
                    {selectedAsset.fqn}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Step 2: Select Monitors */}
          {step === 2 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Select Monitors
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Choose which monitors to create for{' '}
                  <span className="font-medium text-[var(--text)]">
                    {selectedAsset?.name}
                  </span>
                </p>
              </div>

              {recsLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="p-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] animate-pulse">
                      <div className="flex gap-3">
                        <div className="w-4 h-4 rounded bg-[var(--muted)]/20 shrink-0" />
                        <div className="flex-1 space-y-1.5">
                          <div className="h-3 w-32 rounded bg-[var(--muted)]/20" />
                          <div className="h-2.5 w-48 rounded bg-[var(--muted)]/15" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : recommendations.length === 0 ? (
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-center">
                  <p className="text-[13px] text-[var(--muted)]">
                    No monitor recommendations found for this asset.
                  </p>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {recommendations.map((rec, idx) => {
                    const key = `${idx}`;
                    const isSelected = selectedMonitors.has(key);
                    const disabled = rec.already_monitored;

                    return (
                      <label
                        key={key}
                        className={cn(
                          'flex items-start gap-3 p-3 rounded-lg border transition-colors cursor-pointer',
                          disabled && 'opacity-50 cursor-default',
                          isSelected && !disabled
                            ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                            : 'border-[var(--border)] hover:border-[var(--accent)] bg-[var(--surface)]',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected && !disabled}
                          disabled={disabled}
                          onChange={() => !disabled && toggleMonitor(key)}
                          className="accent-[var(--accent)] w-4 h-4 shrink-0 mt-0.5"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-[13px] font-medium text-[var(--text)]">
                              {MONITOR_TYPE_LABELS[rec.monitor_key] || rec.monitor_key}
                            </span>
                            {disabled && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/15 text-amber-400">
                                Already monitored
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-[var(--muted)] mt-0.5">
                            {rec.reason}
                          </p>
                          <p className="text-[10px] text-[var(--muted)] font-mono mt-0.5 truncate">
                            {rec.target_fqn}
                          </p>
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Step 3: Configure & Policy */}
          {step === 3 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Configure & Policy
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Configure monitor settings. Policy defaults are pre-filled.
                </p>
              </div>

              {policyLoading ? (
                <div className="space-y-2">
                  {[1, 2].map((i) => (
                    <div key={i} className="p-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] animate-pulse">
                      <div className="h-4 w-40 rounded bg-[var(--muted)]/20 mb-2" />
                      <div className="h-8 w-full rounded bg-[var(--muted)]/15" />
                    </div>
                  ))}
                </div>
              ) : (
                recommendations
                  .map((rec, origIdx) => ({ rec, origIdx }))
                  .filter(({ origIdx }) => selectedMonitors.has(`${origIdx}`))
                  .map(({ rec, origIdx }) => {
                    const mc = monitorConfigs[origIdx] || { config: {}, overrides: [] };
                    const catalogDef = getMonitorDefinition(rec.monitor_key);
                    const policy = resolvedPolicies[selectedAsset?.fqn || ''];
                    const policyFieldMap = POLICY_FIELD_MAP[rec.monitor_key] || {};

                    // Get fields to show: from catalog config_schema, falling back to policy-mapped fields
                    const schemaFields = catalogDef?.config_schema || [];
                    const policyFieldKeys = Object.keys(policyFieldMap);
                    // Fields from catalog that have policy mapping, or all policy-mapped fields if no catalog
                    const fieldsToRender = schemaFields.length > 0
                      ? schemaFields.filter((f) => !f.advanced)
                      : policyFieldKeys.map((key) => ({
                          key,
                          label: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
                          type: 'number' as const,
                        }));

                    return (
                      <div key={origIdx} className="border border-[var(--border)] rounded-lg p-3">
                        <h4 className="font-medium text-[13px] text-[var(--text)] mb-3">
                          {MONITOR_TYPE_LABELS[rec.monitor_key] || rec.monitor_key}
                          <span className="text-[11px] text-[var(--muted)] font-normal ml-2">
                            {rec.target_fqn}
                          </span>
                        </h4>

                        {fieldsToRender.length === 0 ? (
                          <p className="text-[12px] text-[var(--muted)]">No configurable fields.</p>
                        ) : (
                          <div className="space-y-3">
                            {fieldsToRender.map((field) => {
                              const policyVal = getPolicyValueForField(rec.monitor_key, field.key, policy);
                              const currentVal = mc.config[field.key];
                              const isOverridden = mc.overrides.includes(field.key);
                              const lessStrict = isLessStrictClient(field.key, currentVal, policyVal);
                              const hasPolicyMapping = policyVal !== undefined;

                              return (
                                <div key={field.key} className="space-y-1">
                                  <div className="flex items-center gap-2">
                                    <label className="text-[12px] font-medium text-[var(--text)]">
                                      {field.label}
                                    </label>
                                    {hasPolicyMapping && (
                                      <PolicyFieldBadge
                                        fieldKey={field.key}
                                        currentValue={currentVal}
                                        policyValue={policyVal}
                                        isOverridden={isOverridden}
                                        isLessStrict={lessStrict}
                                        onReset={() => handleResetField(origIdx, field.key)}
                                      />
                                    )}
                                  </div>
                                  {field.type === 'select' && 'options' in field && field.options ? (
                                    <select
                                      value={currentVal ?? ''}
                                      onChange={(e) => handleConfigChange(origIdx, field.key, e.target.value)}
                                      className="w-full px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] focus:outline-none focus:border-[var(--accent)]"
                                    >
                                      <option value="">—</option>
                                      {field.options.map((opt) => (
                                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                                      ))}
                                    </select>
                                  ) : (
                                    <input
                                      type={field.type === 'number' ? 'number' : 'text'}
                                      value={currentVal ?? ''}
                                      onChange={(e) => handleConfigChange(
                                        origIdx,
                                        field.key,
                                        field.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value,
                                      )}
                                      placeholder={'placeholder' in field ? field.placeholder : undefined}
                                      className="w-full px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] focus:outline-none focus:border-[var(--accent)]"
                                    />
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })
              )}
            </div>
          )}

          {/* Step 4: Schedule */}
          {step === 4 && (
            <div className="space-y-6">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Schedule
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Set how often these monitors should run.
                </p>
              </div>

              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Frequency
                </label>
                <ScheduleInput value={schedule} onChange={setSchedule} />
              </div>

              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Timezone
                </label>
                <input
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] focus:outline-none focus:border-[var(--accent)]"
                />
              </div>
            </div>
          )}

          {/* Step 5: Alerts & Create */}
          {step === 5 && (
            <div className="space-y-6">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Alerts & Create
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Configure alert channels and finalize your monitor group.
                </p>
              </div>

              {/* Name */}
              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Monitor Group Name
                </label>
                <input
                  value={watchName}
                  onChange={(e) => setWatchName(e.target.value)}
                  placeholder="e.g. orders_table monitors"
                  className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] placeholder:text-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              {/* Alerts */}
              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Alerts
                </label>
                <AlertChannelPicker
                  channels={alertChannels}
                  onChannelsChange={setAlertChannels}
                  alertOnStatus={alertOnStatus}
                  onAlertOnStatusChange={setAlertOnStatus}
                />
              </div>

              {/* Summary */}
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 space-y-1">
                <p className="text-[13px] text-[var(--text)]">
                  <span className="font-medium">{selectedMonitors.size}</span> monitor
                  {selectedMonitors.size !== 1 ? 's' : ''} for{' '}
                  <span className="font-medium">{selectedAsset?.name}</span>
                </p>
                <p className="text-[11px] text-[var(--muted)]">
                  {schedule} ({timezone})
                </p>
              </div>
            </div>
          )}
        </div>

        {/* ---- Footer ---- */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-[var(--border)] bg-[var(--surface)]">
          <button
            onClick={() => (step === 1 || (step === 2 && prefill) ? onClose() : goToStep((step - 1) as Step))}
            className="px-4 py-2 text-[13px] text-[var(--muted)] hover:text-[var(--text)] transition-colors"
          >
            {step === 1 || (step === 2 && prefill) ? 'Cancel' : 'Back'}
          </button>

          {step < 5 ? (
            <button
              onClick={() => goToStep((step + 1) as Step)}
              disabled={!canGoNext}
              className={cn(
                'px-5 py-2 rounded-lg text-[13px] font-medium transition-colors',
                canGoNext
                  ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90'
                  : 'bg-[var(--muted)]/20 text-[var(--muted)] cursor-not-allowed',
              )}
            >
              Next
            </button>
          ) : (
            <button
              onClick={handleCreate}
              disabled={!canGoNext || creating}
              className={cn(
                'px-5 py-2 rounded-lg text-[13px] font-medium transition-colors',
                canGoNext && !creating
                  ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90'
                  : 'bg-[var(--muted)]/20 text-[var(--muted)] cursor-not-allowed',
              )}
            >
              {creating ? 'Creating...' : 'Create Monitors'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
