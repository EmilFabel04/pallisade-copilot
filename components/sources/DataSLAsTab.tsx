'use client';

import React, { useState, useMemo } from 'react';
import { GovernanceFilters } from '@/components/governance/GovernanceFilters';
import { Loader2, FileText, Plus, X, Clock, Shield, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { usePipeline } from '@/contexts/PipelineContext';
import { useDataSLAs, type DataSLASummary } from './useDataSLAs';
import { DataSLACard } from './DataSLACard';
import { DOMAIN_SLA_SECTIONS, categoryToSLADomain, type SLADomain } from '@/types/sla';
import { NodeSelectionSurface, type NodeMeta } from '@/components/schedule/NodeSelectionSurface';

// ─── Tier presets (same as SLAEditorPanel BUILTIN_PROFILES) ──────

const TIER_PRESETS: Record<string, Record<string, Record<string, any>>> = {
  T0: {
    freshnessConfig: { enabled: true, maxHours: 0.25, warningHours: 0.15 },
    schemaConfig: { enabled: true, strictness: 'strict', allowEvolution: false },
    volumeConfig: { enabled: true, growthRateThreshold: 0.05, minRows: 1, maxRows: 100000000 },
    anomalyConfig: { enabled: true, sensitivity: 0.99, lookbackDays: 30 },
    qualityConfig: { enabled: true, maxNullRate: 0.01, maxDuplicateRate: 0.005 },
    ingestionConfig: { syncLagToleranceMinutes: 15, failureTolerance: 'strict', schemaDriftStrictness: 'strict' },
    biConfig: { freshnessHours: 0.25, contentHealthEnabled: true, upstreamBreakStrictness: 'strict' },
    orchestrationConfig: { runLatencyMinutes: 15, scheduleLagMinutes: 5, failureTolerance: 'strict' },
    transformConfig: { testFailureTolerance: 'strict', modelFreshnessHours: 0.25 },
  },
  T1: {
    freshnessConfig: { enabled: true, maxHours: 1, warningHours: 0.5 },
    schemaConfig: { enabled: true, strictness: 'warn', allowEvolution: false },
    volumeConfig: { enabled: true, growthRateThreshold: 0.10, minRows: 1, maxRows: 500000000 },
    anomalyConfig: { enabled: true, sensitivity: 0.97, lookbackDays: 21 },
    qualityConfig: { enabled: true, maxNullRate: 0.02, maxDuplicateRate: 0.01 },
    ingestionConfig: { syncLagToleranceMinutes: 60, failureTolerance: 'strict', schemaDriftStrictness: 'warn' },
    biConfig: { freshnessHours: 1, contentHealthEnabled: true, upstreamBreakStrictness: 'warn' },
    orchestrationConfig: { runLatencyMinutes: 30, scheduleLagMinutes: 10, failureTolerance: 'strict' },
    transformConfig: { testFailureTolerance: 'strict', modelFreshnessHours: 1 },
  },
  T2: {
    freshnessConfig: { enabled: true, maxHours: 6, warningHours: 3 },
    schemaConfig: { enabled: true, strictness: 'warn', allowEvolution: true },
    volumeConfig: { enabled: true, growthRateThreshold: 0.15, minRows: 1, maxRows: 1000000000 },
    anomalyConfig: { enabled: true, sensitivity: 0.95, lookbackDays: 14 },
    qualityConfig: { enabled: true, maxNullRate: 0.05, maxDuplicateRate: 0.02 },
    ingestionConfig: { syncLagToleranceMinutes: 360, failureTolerance: 'normal', schemaDriftStrictness: 'warn' },
    biConfig: { freshnessHours: 6, contentHealthEnabled: true, upstreamBreakStrictness: 'warn' },
    orchestrationConfig: { runLatencyMinutes: 60, scheduleLagMinutes: 15, failureTolerance: 'normal' },
    transformConfig: { testFailureTolerance: 'normal', modelFreshnessHours: 6 },
  },
  T3: {
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
};

// ─── Shared SLA field helpers ────────────────────────────────────

function NumberInput({ value, onChange, label, suffix, min, max, step }: {
  value: number | undefined; onChange: (v: number) => void; label: string; suffix?: string; min?: number; max?: number; step?: number | string;
}) {
  return (
    <div>
      <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">{label}</label>
      <div className="flex items-center gap-1.5 mt-1">
        <input type="number" value={value ?? ''} step={step ?? 'any'}
          onChange={e => { const v = e.target.value; onChange(v === '' ? undefined as any : Number(v)); }}
          onWheel={e => (e.target as HTMLInputElement).blur()}
          min={min} max={max}
          className="w-full px-2 py-1.5 text-[12px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-[var(--accent)]/50 focus:outline-none" />
        {suffix && <span className="text-[11px] text-[var(--muted)] whitespace-nowrap">{suffix}</span>}
      </div>
    </div>
  );
}

function SelectInput({ value, onChange, label, options }: {
  value: string; onChange: (v: string) => void; label: string; options: Array<{ value: string; label: string }>;
}) {
  return (
    <div>
      <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)}
        className="mt-1 w-full px-2 py-1.5 text-[12px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-[var(--accent)]/50 focus:outline-none">
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

const STRICTNESS_OPTIONS = [{ value: 'strict', label: 'Strict' }, { value: 'warn', label: 'Warn' }, { value: 'ignore', label: 'Ignore' }];
const TOLERANCE_OPTIONS = [{ value: 'strict', label: 'Strict' }, { value: 'normal', label: 'Normal' }, { value: 'relaxed', label: 'Relaxed' }];

// ─── Main Tab ────────────────────────────────────────────────────

export function DataSLAsTab() {
  const { selectedPipelineId } = usePipeline();
  const { contracts, loading, error, refresh } = useDataSLAs();
  const [selectedContract, setSelectedContract] = useState<DataSLASummary | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const [search, setSearch] = useState('');
  const [tierFilter, setTierFilter] = useState<Set<string>>(new Set());
  const [scopeFilter, setScopeFilter] = useState<Set<string>>(new Set());

  const toggleFilter = (set: Set<string>, setter: (s: Set<string>) => void, value: string) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setter(next);
  };

  const filteredSLAs = useMemo(() => {
    let result = contracts;

    if (search) {
      const q = search.toLowerCase();
      result = result.filter(c =>
        (c.name || '').toLowerCase().includes(q) ||
        (c.scopeRef || '').toLowerCase().includes(q)
      );
    }

    if (tierFilter.size > 0) {
      result = result.filter(c => c.slaTier && tierFilter.has(c.slaTier));
    }

    if (scopeFilter.size > 0) {
      result = result.filter(c => scopeFilter.has(c.scope));
    }

    return result;
  }, [contracts, search, tierFilter, scopeFilter]);

  const groupContracts = filteredSLAs.filter(c => !c.isException);
  const exceptionContracts = filteredSLAs.filter(c => c.isException);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  if (error) {
    return <div className="text-center py-12 text-[var(--muted)]">Failed to load data SLAs</div>;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-end">
        <button onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 transition-opacity">
          <Plus className="w-3.5 h-3.5" /> Create Data SLA
        </button>
      </div>

      {/* Search and filters */}
      {contracts.length > 0 && (
        <GovernanceFilters
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search by name or scope..."
          filters={[
            {
              label: 'Tier',
              options: [
                { value: 'T0', label: 'T0' },
                { value: 'T1', label: 'T1' },
                { value: 'T2', label: 'T2' },
                { value: 'T3', label: 'T3' },
              ],
              selected: tierFilter,
              onToggle: v => toggleFilter(tierFilter, setTierFilter, v),
            },
            {
              label: 'Scope',
              options: [
                { value: 'schema', label: 'Schema' },
                { value: 'dbt_model_group', label: 'dbt Model Group' },
                { value: 'dashboard', label: 'Dashboard' },
                { value: 'exception', label: 'Exception' },
              ],
              selected: scopeFilter,
              onToggle: v => toggleFilter(scopeFilter, setScopeFilter, v),
            },
          ]}
          onClearAll={() => {
            setSearch('');
            setTierFilter(new Set());
            setScopeFilter(new Set());
          }}
          hasActiveFilters={search.length > 0 || tierFilter.size > 0 || scopeFilter.size > 0}
        />
      )}

      {/* Empty state */}
      {contracts.length === 0 && (
        <div className="text-center py-12">
          <FileText className="w-8 h-8 mx-auto mb-3 text-[var(--muted)]" />
          <p className="text-sm text-[var(--muted)]">
            No data SLAs yet. Click &quot;Create Data SLA&quot; to define SLA expectations for your data assets.
          </p>
        </div>
      )}

      {/* Cards */}
      {groupContracts.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-3">
            Group Data SLAs ({groupContracts.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {groupContracts.map(c => (
              <DataSLACard key={c.id} contract={c} editable={true} onClick={setSelectedContract} />
            ))}
          </div>
        </div>
      )}
      {exceptionContracts.length > 0 && (
        <div>
          <h3 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-3">
            Exception Data SLAs ({exceptionContracts.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {exceptionContracts.map(c => (
              <DataSLACard key={c.id} contract={c} editable={true} onClick={setSelectedContract} />
            ))}
          </div>
        </div>
      )}

      {/* Detail/Edit drawer */}
      {selectedContract && selectedPipelineId && (
        <ContractEditorDrawer
          contract={selectedContract}
          pipelineId={selectedPipelineId}
          editable={true}
          onClose={() => setSelectedContract(null)}
          onSaved={() => { setSelectedContract(null); refresh(true); }}
        />
      )}

      {/* Create modal */}
      {showCreate && selectedPipelineId && (
        <ContractCreatorModal
          pipelineId={selectedPipelineId}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); refresh(true); }}
        />
      )}

    </div>
  );
}

// ─── SLA Config Sections (shared between create and edit) ────────

function SLAConfigSections({ configs, setConfig, domain }: {
  configs: Record<string, Record<string, any>>;
  setConfig: (section: string, field: string, value: any) => void;
  domain: SLADomain;
}) {
  const sections = DOMAIN_SLA_SECTIONS[domain] || [];
  const getVal = (section: string, field: string) => configs[section]?.[field];

  return (
    <div className="space-y-3">
      {sections.includes('freshness') && (
        <ConfigSection title="Freshness">
          <NumberInput label="Max hours" value={getVal('freshnessConfig', 'maxHours')} onChange={v => setConfig('freshnessConfig', 'maxHours', v)} suffix="hrs" min={0} />
          <NumberInput label="Warning" value={getVal('freshnessConfig', 'warningHours')} onChange={v => setConfig('freshnessConfig', 'warningHours', v)} suffix="hrs" min={0} />
        </ConfigSection>
      )}
      {sections.includes('schema') && (
        <ConfigSection title="Schema">
          <SelectInput label="Strictness" value={getVal('schemaConfig', 'strictness') || 'warn'} onChange={v => setConfig('schemaConfig', 'strictness', v)} options={STRICTNESS_OPTIONS} />
        </ConfigSection>
      )}
      {sections.includes('volume') && (
        <ConfigSection title="Volume">
          <NumberInput label="Growth threshold" value={getVal('volumeConfig', 'growthRateThreshold') != null ? Math.round(getVal('volumeConfig', 'growthRateThreshold') * 100) : undefined} onChange={v => setConfig('volumeConfig', 'growthRateThreshold', v != null ? parseFloat((v / 100).toFixed(4)) : undefined)} suffix="%" min={1} max={100} step={1} />
          <NumberInput label="Min rows" value={getVal('volumeConfig', 'minRows')} onChange={v => setConfig('volumeConfig', 'minRows', v)} min={0} />
          <NumberInput label="Max rows" value={getVal('volumeConfig', 'maxRows')} onChange={v => setConfig('volumeConfig', 'maxRows', v)} min={0} />
        </ConfigSection>
      )}
      {sections.includes('anomaly') && (
        <ConfigSection title="Anomaly Detection">
          <NumberInput label="Sensitivity" value={getVal('anomalyConfig', 'sensitivity') != null ? Math.round(getVal('anomalyConfig', 'sensitivity') * 100) : undefined} onChange={v => setConfig('anomalyConfig', 'sensitivity', v != null ? parseFloat((v / 100).toFixed(4)) : undefined)} suffix="%" min={50} max={100} step={1} />
          <NumberInput label="Lookback days" value={getVal('anomalyConfig', 'lookbackDays')} onChange={v => setConfig('anomalyConfig', 'lookbackDays', v)} suffix="days" min={7} max={90} />
        </ConfigSection>
      )}
      {sections.includes('quality') && (
        <ConfigSection title="Quality">
          <NumberInput label="Max null rate" value={getVal('qualityConfig', 'maxNullRate') != null ? Math.round(getVal('qualityConfig', 'maxNullRate') * 100) : undefined} onChange={v => setConfig('qualityConfig', 'maxNullRate', v != null ? parseFloat((v / 100).toFixed(4)) : undefined)} suffix="%" min={0} max={100} step={1} />
          <NumberInput label="Max dupe rate" value={getVal('qualityConfig', 'maxDuplicateRate') != null ? Math.round(getVal('qualityConfig', 'maxDuplicateRate') * 100) : undefined} onChange={v => setConfig('qualityConfig', 'maxDuplicateRate', v != null ? parseFloat((v / 100).toFixed(4)) : undefined)} suffix="%" min={0} max={100} step={1} />
        </ConfigSection>
      )}
      {sections.includes('ingestion') && (
        <ConfigSection title="Ingestion">
          <NumberInput label="Sync lag tolerance" value={getVal('ingestionConfig', 'syncLagToleranceMinutes')} onChange={v => setConfig('ingestionConfig', 'syncLagToleranceMinutes', v)} suffix="min" min={1} />
          <SelectInput label="Failure tolerance" value={getVal('ingestionConfig', 'failureTolerance') || 'normal'} onChange={v => setConfig('ingestionConfig', 'failureTolerance', v)} options={TOLERANCE_OPTIONS} />
          <SelectInput label="Schema drift" value={getVal('ingestionConfig', 'schemaDriftStrictness') || 'warn'} onChange={v => setConfig('ingestionConfig', 'schemaDriftStrictness', v)} options={STRICTNESS_OPTIONS} />
        </ConfigSection>
      )}
      {sections.includes('bi') && (
        <ConfigSection title="BI / Reporting">
          <NumberInput label="BI freshness" value={getVal('biConfig', 'freshnessHours')} onChange={v => setConfig('biConfig', 'freshnessHours', v)} suffix="hrs" min={1} />
          <SelectInput label="Upstream break" value={getVal('biConfig', 'upstreamBreakStrictness') || 'warn'} onChange={v => setConfig('biConfig', 'upstreamBreakStrictness', v)} options={STRICTNESS_OPTIONS} />
        </ConfigSection>
      )}
      {sections.includes('orchestration') && (
        <ConfigSection title="Orchestration">
          <NumberInput label="Run latency" value={getVal('orchestrationConfig', 'runLatencyMinutes')} onChange={v => setConfig('orchestrationConfig', 'runLatencyMinutes', v)} suffix="min" min={1} />
          <NumberInput label="Schedule lag" value={getVal('orchestrationConfig', 'scheduleLagMinutes')} onChange={v => setConfig('orchestrationConfig', 'scheduleLagMinutes', v)} suffix="min" min={1} />
          <SelectInput label="Failure tolerance" value={getVal('orchestrationConfig', 'failureTolerance') || 'normal'} onChange={v => setConfig('orchestrationConfig', 'failureTolerance', v)} options={TOLERANCE_OPTIONS} />
        </ConfigSection>
      )}
      {sections.includes('transform') && (
        <ConfigSection title="Transform">
          <SelectInput label="Test failure tolerance" value={getVal('transformConfig', 'testFailureTolerance') || 'normal'} onChange={v => setConfig('transformConfig', 'testFailureTolerance', v)} options={TOLERANCE_OPTIONS} />
          <NumberInput label="Model freshness" value={getVal('transformConfig', 'modelFreshnessHours')} onChange={v => setConfig('transformConfig', 'modelFreshnessHours', v)} suffix="hrs" min={1} />
        </ConfigSection>
      )}
    </div>
  );
}

function ConfigSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
      <h4 className="text-[11px] font-medium text-[var(--text)] uppercase tracking-wide">{title}</h4>
      {children}
    </div>
  );
}

// ─── Contract Editor Drawer (view + edit) ────────────────────────

function ContractEditorDrawer({ contract, pipelineId, editable, onClose, onSaved }: {
  contract: DataSLASummary; pipelineId: string; editable: boolean; onClose: () => void; onSaved: () => void;
}) {
  const [configs, setConfigs] = useState<Record<string, Record<string, any>>>(() => {
    const c: Record<string, Record<string, any>> = {};
    const keys = ['freshnessConfig', 'schemaConfig', 'volumeConfig', 'anomalyConfig', 'qualityConfig', 'ingestionConfig', 'biConfig', 'orchestrationConfig', 'transformConfig'] as const;
    for (const k of keys) {
      if (contract[k]) c[k] = { ...contract[k] as Record<string, any> };
    }
    return c;
  });
  const [contractName, setContractName] = useState(contract.name || '');
  const [slaTier, setSlaTier] = useState(contract.slaTier || '');
  const [notes, setNotes] = useState(contract.notes || '');
  const [editNodeFqns, setEditNodeFqns] = useState<string[]>(contract.nodeFqns || []);
  const [showNodePicker, setShowNodePicker] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const domain = useMemo<SLADomain>(() => {
    // Infer domain from scope type
    if (contract.scope === 'dashboard') return 'bi';
    if (contract.scope === 'dbt_model_group') return 'transform';
    return 'warehouse';
  }, [contract.scope]);

  const setConfig = (section: string, field: string, value: any) => {
    setConfigs(prev => ({
      ...prev,
      [section]: { ...(prev[section] || {}), [field]: value },
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const body: Record<string, any> = {
        name: contractName.trim() || null,
        slaTier: slaTier || null,
        notes: notes.trim() || null,
        nodeFqns: editNodeFqns.length > 0 ? editNodeFqns : null,
      };
      for (const [k, v] of Object.entries(configs)) {
        if (Object.keys(v).length > 0) body[k] = v;
      }
      const res = await fetch(`/api/pipeline/${pipelineId}/data-slas/${contract.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        toast.success('Data SLA updated');
        onSaved();
      } else {
        const data = await res.json();
        toast.error(data.error || 'Failed to update');
      }
    } catch {
      toast.error('Failed to update data SLA');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-x-0 top-14 bottom-0 z-40 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className={`relative w-full bg-[var(--surface-sunken)] border-l border-[var(--subtle-border)] flex flex-col ${showNodePicker ? 'max-w-4xl' : 'max-w-lg'}`} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="p-5 border-b border-[var(--subtle-border)] flex-shrink-0">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-[var(--foreground)]">{editable ? 'Edit Data SLA' : 'Data SLA Details'}</h2>
              <p className="text-[11px] text-[var(--muted)] mt-0.5">{contract.name || contract.scopeRef}</p>
            </div>
            <button onClick={onClose} className="p-1 hover:bg-[var(--subtle-bg)] rounded transition-colors">
              <X className="w-4 h-4 text-[var(--muted)]" />
            </button>
          </div>
          <div className="flex gap-2 mt-3">
            {contract.slaTier && (
              <span className="text-[10px] px-2 py-0.5 rounded bg-[var(--accent)]/15 text-[var(--accent)] font-medium">{contract.slaTier}</span>
            )}
            {contract.autoSynced && (
              <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 font-medium">Auto-synced</span>
            )}
            {(contract.nodeFqns?.length || 0) > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--muted)] font-medium">
                {contract.nodeFqns!.length} node{contract.nodeFqns!.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
        </div>

        {/* Node picker overlay */}
        {showNodePicker && (
          <div className="absolute inset-0 z-10 bg-[var(--surface-sunken)] flex flex-col">
            <div className="p-4 border-b border-[var(--subtle-border)] flex items-center justify-between">
              <span className="text-xs font-medium text-[var(--foreground)]">Select Nodes ({editNodeFqns.length} selected)</span>
              <button onClick={() => setShowNodePicker(false)} className="text-xs text-[var(--accent)] font-medium">Done</button>
            </div>
            <div className="flex-1 min-h-0">
              <NodeSelectionSurface
                stackId={pipelineId}
                mode="lineage"
                selectedNodeIds={editNodeFqns}
                onSelectionChange={setEditNodeFqns}
              />
            </div>
          </div>
        )}

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Contract name */}
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">Data SLA Name</label>
            <input type="text" value={contractName} onChange={e => setContractName(e.target.value)} disabled={!editable}
              placeholder="Optional name for this contract"
              className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)] disabled:opacity-60" />
          </div>

          {/* Covered nodes */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Covered Nodes ({editNodeFqns.length})</label>
              {editable && (
                <button onClick={() => setShowNodePicker(true)} className="text-[10px] text-[var(--accent)] font-medium hover:underline">
                  Edit nodes
                </button>
              )}
            </div>
            {editNodeFqns.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {editNodeFqns.slice(0, 6).map(fqn => (
                  <span key={fqn} className="text-[10px] px-2 py-0.5 rounded bg-[var(--overlay-bg)] text-[var(--text)] font-mono truncate max-w-[200px]">{fqn}</span>
                ))}
                {editNodeFqns.length > 6 && <span className="text-[10px] text-[var(--muted)]">+{editNodeFqns.length - 6} more</span>}
              </div>
            ) : (
              <p className="text-[11px] text-[var(--muted)] italic">No nodes selected</p>
            )}
          </div>

          {/* SLA Tier */}
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">SLA Tier</label>
            <select value={slaTier} disabled={!editable} onChange={e => {
              const tier = e.target.value;
              setSlaTier(tier);
              if (tier && TIER_PRESETS[tier]) {
                const preset = TIER_PRESETS[tier];
                const newConfigs: Record<string, Record<string, any>> = {};
                for (const [k, v] of Object.entries(preset)) newConfigs[k] = { ...v };
                setConfigs(newConfigs);
              }
            }}
              className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)] disabled:opacity-60">
              <option value="">None</option>
              <option value="T0">T0 - Critical</option>
              <option value="T1">T1 - High</option>
              <option value="T2">T2 - Standard</option>
              <option value="T3">T3 - Low</option>
            </select>
            {slaTier && <p className="text-[10px] text-[var(--muted)] mt-1">Selecting a tier auto-populates SLA fields below. You can customize individual values.</p>}
          </div>

          {/* Domain SLA fields */}
          {editable ? (
            <SLAConfigSections configs={configs} setConfig={setConfig} domain={domain} />
          ) : (
            <SLAConfigSections configs={configs} setConfig={() => {}} domain={domain} />
          )}

          {/* Notes */}
          <div>
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">Notes</label>
            <textarea value={notes} onChange={e => setNotes(e.target.value)} disabled={!editable} rows={3} placeholder="Additional context..."
              className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-xs text-[var(--foreground)] disabled:opacity-60 resize-none" />
          </div>

          {/* Metadata */}
          <div className="flex items-center gap-1 text-[11px] text-[var(--muted)]">
            <Clock className="w-3 h-3" />
            Updated {new Date(contract.updatedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
          </div>
        </div>

        {/* Footer */}
        {editable && (
          <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0">
            {deleteConfirm ? (
              <div className="flex items-center justify-between">
                <span className="text-xs text-red-400">Delete this data SLA? This cannot be undone.</span>
                <div className="flex gap-2">
                  <button onClick={() => setDeleteConfirm(false)} className="px-3 py-1.5 text-xs font-medium rounded-md text-[var(--muted)] hover:text-[var(--foreground)]">
                    No, keep it
                  </button>
                  <button disabled={deleting} onClick={async () => {
                    setDeleting(true);
                    try {
                      const res = await fetch(`/api/pipeline/${pipelineId}/data-slas/${contract.id}`, { method: 'DELETE' });
                      if (res.ok) { toast.success('Data SLA deleted'); onSaved(); }
                      else { toast.error('Failed to delete'); }
                    } catch { toast.error('Failed to delete'); }
                    finally { setDeleting(false); }
                  }} className="px-3 py-1.5 text-xs font-medium rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-50">
                    {deleting ? 'Deleting...' : 'Yes, delete'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <button onClick={() => setDeleteConfirm(true)} className="px-3 py-1.5 text-xs font-medium rounded-md text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors">
                  Delete Data SLA
                </button>
                <div className="flex gap-2">
                  <button onClick={onClose} className="px-4 py-2 text-xs font-medium rounded-md text-[var(--muted)] hover:text-[var(--foreground)]">Cancel</button>
                  <button onClick={handleSave} disabled={saving}
                    className="px-4 py-2 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50">
                    {saving ? 'Saving...' : 'Save Changes'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Contract Creator Modal ──────────────────────────────────────

function ContractCreatorModal({ pipelineId, onClose, onCreated }: {
  pipelineId: string; onClose: () => void; onCreated: () => void;
}) {
  const [step, setStep] = useState<'pick-node' | 'configure'>('pick-node');
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [nodeMetas, setNodeMetas] = useState<NodeMeta[]>([]);
  const [contractName, setContractName] = useState('');
  const [slaTier, setSlaTier] = useState('');
  const [configs, setConfigs] = useState<Record<string, Record<string, any>>>({});
  const [saving, setSaving] = useState(false);

  const selectedMetas = useMemo(
    () => nodeMetas.filter(n => selectedNodeIds.includes(n.id)),
    [nodeMetas, selectedNodeIds],
  );

  const domain = useMemo<SLADomain>(() => {
    if (selectedMetas.length === 0) return 'warehouse';
    return categoryToSLADomain(selectedMetas[0].domain) || 'warehouse';
  }, [selectedMetas]);

  const setConfig = (section: string, field: string, value: any) => {
    setConfigs(prev => ({
      ...prev,
      [section]: { ...(prev[section] || {}), [field]: value },
    }));
  };

  const handleProceed = () => {
    if (selectedMetas.length === 0) return;
    // Auto-suggest a name from the first node's schema
    const first = selectedMetas[0];
    const parts = first.fqn.split('.');
    const suggestedName = parts.length >= 2 ? `${parts[0]}.${parts[1]}` : parts[0];
    if (!contractName) setContractName(suggestedName);
    setStep('configure');
  };

  const handleCreate = async () => {
    const fqns = selectedMetas.map(n => n.fqn);
    // Use contract name or auto-derive scopeRef from first FQN
    const first = selectedMetas[0];
    const parts = first?.fqn.split('.') || [];
    const scopeRef = contractName.trim() || (parts.length >= 2 ? `${parts[0]}.${parts[1]}` : parts[0] || 'default');

    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        scope: 'schema',
        scopeRef,
        name: contractName.trim() || null,
        nodeFqns: fqns,
        slaTier: slaTier || null,
      };
      for (const [k, v] of Object.entries(configs)) {
        if (Object.keys(v).length > 0) body[k] = v;
      }
      const res = await fetch(`/api/pipeline/${pipelineId}/data-slas`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        toast.success('Data SLA created');
        onCreated();
      } else {
        const data = await res.json();
        toast.error(data.error || 'Failed to create data SLA');
      }
    } catch {
      toast.error('Failed to create data SLA');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-x-0 top-14 bottom-0 z-40 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative w-[90vw] max-w-5xl h-[80vh] bg-[var(--surface-raised)] rounded-xl border border-[var(--subtle-border)] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="p-5 border-b border-[var(--subtle-border)] flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Shield className="w-5 h-5 text-[var(--accent)]" />
              <div>
                <h2 className="text-sm font-semibold text-[var(--foreground)]">Create Data SLA</h2>
                <p className="text-[11px] text-[var(--muted)] mt-0.5">
                  {step === 'pick-node' ? 'Click nodes in the graph to select data assets' : 'Configure SLA expectations'}
                </p>
              </div>
            </div>
            <button onClick={onClose} className="p-1 hover:bg-[var(--subtle-bg)] rounded transition-colors">
              <X className="w-4 h-4 text-[var(--muted)]" />
            </button>
          </div>
          {/* Step indicator */}
          <div className="flex items-center gap-2 mt-4">
            <span className={`text-[11px] font-medium px-2 py-0.5 rounded ${step === 'pick-node' ? 'bg-[var(--accent)]/15 text-[var(--accent)]' : 'text-[var(--muted)]'}`}>
              1. Select Nodes
            </span>
            <ChevronRight className="w-3 h-3 text-[var(--muted)]" />
            <span className={`text-[11px] font-medium px-2 py-0.5 rounded ${step === 'configure' ? 'bg-[var(--accent)]/15 text-[var(--accent)]' : 'text-[var(--muted)]'}`}>
              2. Configure SLA
            </span>
            {selectedNodeIds.length > 0 && step === 'pick-node' && (
              <span className="ml-auto text-[11px] text-[var(--accent)] font-medium">
                {selectedNodeIds.length} node{selectedNodeIds.length !== 1 ? 's' : ''} selected
              </span>
            )}
          </div>
        </div>

        {/* Body */}
        {step === 'pick-node' ? (
          <div className="flex-1 min-h-0">
            <NodeSelectionSurface
              stackId={pipelineId}
              mode="lineage"
              selectedNodeIds={selectedNodeIds}
              onSelectionChange={setSelectedNodeIds}
              onNodesLoaded={setNodeMetas}
            />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {/* Back button */}
            <button onClick={() => setStep('pick-node')} className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] flex items-center gap-1">
              <ChevronRight className="w-3 h-3 rotate-180" /> Back to node selection
            </button>

            {/* Selected nodes summary */}
            <div className="flex flex-wrap gap-1.5">
              {selectedMetas.slice(0, 8).map(n => (
                <span key={n.id} className="text-[10px] px-2 py-0.5 rounded bg-[var(--overlay-bg)] text-[var(--text)] font-mono">{n.fqn}</span>
              ))}
              {selectedMetas.length > 8 && <span className="text-[10px] text-[var(--muted)]">+{selectedMetas.length - 8} more</span>}
            </div>

            {/* Contract name */}
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">Data SLA Name (optional)</label>
              <input type="text" value={contractName} onChange={e => setContractName(e.target.value)} placeholder="e.g., Analytics Tables, Raw Ingestion"
                className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)]" />
            </div>

            {/* SLA Tier */}
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">SLA Tier</label>
              <select value={slaTier} onChange={e => {
                const tier = e.target.value;
                setSlaTier(tier);
                if (tier && TIER_PRESETS[tier]) {
                  const preset = TIER_PRESETS[tier];
                  const newConfigs: Record<string, Record<string, any>> = {};
                  for (const [k, v] of Object.entries(preset)) newConfigs[k] = { ...v };
                  setConfigs(newConfigs);
                }
              }}
                className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)]">
                <option value="">None</option>
                <option value="T0">T0 - Critical</option>
                <option value="T1">T1 - High</option>
                <option value="T2">T2 - Standard</option>
                <option value="T3">T3 - Low</option>
              </select>
              {slaTier && <p className="text-[10px] text-[var(--muted)] mt-1">Selecting a tier auto-populates SLA fields below. You can customize individual values.</p>}
            </div>

            {/* Domain SLA config */}
            <SLAConfigSections configs={configs} setConfig={setConfig} domain={domain} />
          </div>
        )}

        {/* Footer */}
        <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-xs font-medium rounded-md text-[var(--muted)] hover:text-[var(--foreground)]">Cancel</button>
          {step === 'pick-node' ? (
            <button onClick={handleProceed} disabled={selectedNodeIds.length === 0}
              className="px-4 py-2 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50">
              Continue
            </button>
          ) : (
            <button onClick={handleCreate} disabled={saving || selectedMetas.length === 0}
              className="px-4 py-2 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50">
              {saving ? 'Creating...' : 'Create Data SLA'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
