'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Plus, X, ChevronRight } from 'lucide-react';
import { usePipeline } from '@/contexts/PipelineContext';
import { GovernanceFilters } from './GovernanceFilters';
import { PipelineSLACard, type PipelineSLAItem } from './PipelineSLACard';
import { NodeSelectionSurface, type NodeMeta } from '@/components/schedule/NodeSelectionSurface';
import { toast } from 'sonner';

/* ------------------------------------------------------------------ */
/*  Domain-specific SLA fields                                         */
/* ------------------------------------------------------------------ */

type FieldDef = {
  key: string;
  label: string;
  type: 'number' | 'select';
  unit?: string;
  placeholder?: string;
  options?: { value: string; label: string }[];
};

const DOMAIN_FIELDS: Record<string, FieldDef[]> = {
  ingestion: [
    { key: 'ingestion.syncLagToleranceMinutes', label: 'Sync Lag Tolerance', type: 'number', placeholder: '30', unit: 'min' },
    { key: 'ingestion.failureTolerance', label: 'Failure Tolerance', type: 'select', options: [
      { value: 'strict', label: 'Strict' }, { value: 'normal', label: 'Normal' }, { value: 'relaxed', label: 'Relaxed' },
    ]},
    { key: 'ingestion.schemaDriftStrictness', label: 'Schema Drift', type: 'select', options: [
      { value: 'strict', label: 'Strict' }, { value: 'warn', label: 'Warn' }, { value: 'ignore', label: 'Ignore' },
    ]},
  ],
  orchestration: [
    { key: 'orchestration.runLatencyMinutes', label: 'Run Latency', type: 'number', placeholder: '60', unit: 'min' },
    { key: 'orchestration.scheduleLagMinutes', label: 'Schedule Lag', type: 'number', placeholder: '15', unit: 'min' },
    { key: 'orchestration.failureTolerance', label: 'Failure Tolerance', type: 'select', options: [
      { value: 'strict', label: 'Strict' }, { value: 'normal', label: 'Normal' }, { value: 'relaxed', label: 'Relaxed' },
    ]},
  ],
  transform: [
    { key: 'transform.testFailureTolerance', label: 'Test Failure Tolerance', type: 'select', options: [
      { value: 'strict', label: 'Strict' }, { value: 'normal', label: 'Normal' }, { value: 'relaxed', label: 'Relaxed' },
    ]},
    { key: 'transform.modelFreshnessHours', label: 'Model Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
  ],
  bi: [
    { key: 'bi.freshnessHours', label: 'Dashboard Freshness', type: 'number', placeholder: '12', unit: 'hrs' },
    { key: 'bi.upstreamBreakStrictness', label: 'Upstream Break', type: 'select', options: [
      { value: 'strict', label: 'Strict' }, { value: 'warn', label: 'Warn' }, { value: 'ignore', label: 'Ignore' },
    ]},
  ],
  warehouse: [
    { key: 'freshness.maxHours', label: 'Max Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
    { key: 'freshness.warningHours', label: 'Warning Threshold', type: 'number', placeholder: '12', unit: 'hrs' },
  ],
};

const DOMAINS = ['ingestion', 'orchestration', 'transform', 'bi', 'warehouse'] as const;
const TIERS = ['T0', 'T1', 'T2', 'T3'] as const;

/* ------------------------------------------------------------------ */
/*  PipelineSLACreatorModal                                            */
/* ------------------------------------------------------------------ */

function PipelineSLACreatorModal({
  pipelineId,
  onClose,
  onCreated,
}: {
  pipelineId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [allNodes, setAllNodes] = useState<NodeMeta[]>([]);
  const [selectedDomain, setSelectedDomain] = useState('');
  const [slaTier, setSlaTier] = useState('');
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const selectedMetas = useMemo(
    () => allNodes.filter(n => selectedNodeIds.includes(n.id)),
    [allNodes, selectedNodeIds],
  );

  // Auto-detect domain from selected nodes
  useEffect(() => {
    if (step !== 2) return;
    const domains = new Set(selectedMetas.map(n => n.domain).filter(Boolean));
    if (domains.size === 1) {
      const detected = [...domains][0];
      if (DOMAINS.includes(detected as typeof DOMAINS[number])) {
        setSelectedDomain(detected);
      }
    }
  }, [step, selectedMetas]);

  const fields = selectedDomain ? DOMAIN_FIELDS[selectedDomain] || [] : [];

  const handleSave = async () => {
    if (!selectedDomain || selectedMetas.length === 0) return;
    setSaving(true);

    try {
      const overrides: Record<string, Record<string, unknown>> = {};
      for (const [key, val] of Object.entries(values)) {
        if (!val) continue;
        const [section, field] = key.split('.');
        if (!overrides[section]) overrides[section] = {};
        const fieldDef = fields.find(f => f.key === key);
        overrides[section][field] = fieldDef?.type === 'number' ? Number(val) : val;
      }

      const res = await fetch('/api/schedule/policies/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stackId: pipelineId,
          profileId: '__custom',
          assignmentType: 'direct',
          nodeFqns: selectedMetas.map(n => n.fqn),
          nodeDomain: selectedDomain,
          slaTier: slaTier || undefined,
          overrides,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Failed to create pipeline SLA');
      }

      toast.success(`Pipeline SLA created for ${selectedMetas.length} node(s)`);
      onCreated();
      onClose();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Failed to create pipeline SLA');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-x-0 top-14 bottom-0 z-40 flex items-start justify-center bg-black/40 backdrop-blur-sm overflow-y-auto p-6">
      <div className="w-full max-w-2xl bg-[var(--surface-raised)] rounded-xl border border-[var(--subtle-border)] shadow-xl flex flex-col max-h-[calc(100vh-6rem)]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--subtle-border)]">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-semibold text-[var(--foreground)]">Create Pipeline SLA</h2>
            <div className="flex items-center gap-1 text-[11px]">
              <span className={`px-2 py-0.5 rounded-full font-medium ${step === 1 ? 'bg-[var(--accent)] text-white' : 'bg-[var(--surface)] text-[var(--muted)]'}`}>
                1. Select Nodes
              </span>
              <ChevronRight className="w-3 h-3 text-[var(--muted)]" />
              <span className={`px-2 py-0.5 rounded-full font-medium ${step === 2 ? 'bg-[var(--accent)] text-white' : 'bg-[var(--surface)] text-[var(--muted)]'}`}>
                2. Configure SLA
              </span>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--surface)] text-[var(--muted)] hover:text-[var(--foreground)] transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {step === 1 && (
            <NodeSelectionSurface
              stackId={pipelineId}
              mode="pipeline-overview"
              selectedNodeIds={selectedNodeIds}
              onSelectionChange={setSelectedNodeIds}
              onNodesLoaded={setAllNodes}
            />
          )}

          {step === 2 && (
            <div className="space-y-5">
              {/* SLA Tier */}
              <div>
                <label className="block text-xs font-medium text-[var(--foreground)] mb-1.5">SLA Tier</label>
                <div className="flex gap-2">
                  {TIERS.map(t => (
                    <button
                      key={t}
                      onClick={() => setSlaTier(slaTier === t ? '' : t)}
                      className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
                        slaTier === t
                          ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                          : 'bg-[var(--surface)] text-[var(--foreground)] border-[var(--subtle-border)] hover:border-[var(--muted)]'
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              {/* Domain */}
              <div>
                <label className="block text-xs font-medium text-[var(--foreground)] mb-1.5">Domain</label>
                <select
                  value={selectedDomain}
                  onChange={e => { setSelectedDomain(e.target.value); setValues({}); }}
                  className="w-full px-3 py-2 text-xs rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] text-[var(--foreground)]"
                >
                  <option value="">Select domain...</option>
                  {DOMAINS.map(d => (
                    <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
                  ))}
                </select>
              </div>

              {/* Domain-specific fields */}
              {fields.length > 0 && (
                <div className="space-y-3">
                  <p className="text-xs font-medium text-[var(--foreground)]">SLA Expectations</p>
                  {fields.map(f => (
                    <div key={f.key}>
                      <label className="block text-[11px] text-[var(--muted)] mb-1">{f.label}</label>
                      {f.type === 'number' ? (
                        <div className="flex items-center gap-2">
                          <input
                            type="number"
                            placeholder={f.placeholder}
                            value={values[f.key] || ''}
                            onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                            className="flex-1 px-3 py-1.5 text-xs rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] text-[var(--foreground)]"
                          />
                          {f.unit && <span className="text-[11px] text-[var(--muted)]">{f.unit}</span>}
                        </div>
                      ) : (
                        <select
                          value={values[f.key] || ''}
                          onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                          className="w-full px-3 py-1.5 text-xs rounded-md border border-[var(--subtle-border)] bg-[var(--surface)] text-[var(--foreground)]"
                        >
                          <option value="">Select...</option>
                          {f.options?.map(o => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Selected nodes summary */}
              <div className="text-[11px] text-[var(--muted)]">
                {selectedMetas.length} node(s) selected
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-[var(--subtle-border)]">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs font-medium rounded-md text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
          >
            Cancel
          </button>
          <div className="flex items-center gap-2">
            {step === 2 && (
              <button
                onClick={() => setStep(1)}
                className="px-3 py-1.5 text-xs font-medium rounded-md border border-[var(--subtle-border)] text-[var(--foreground)] hover:bg-[var(--surface)] transition-colors"
              >
                Back
              </button>
            )}
            {step === 1 ? (
              <button
                onClick={() => setStep(2)}
                disabled={selectedNodeIds.length === 0}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Continue <ChevronRight className="w-3 h-3" />
              </button>
            ) : (
              <button
                onClick={handleSave}
                disabled={!selectedDomain || saving}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {saving ? 'Creating...' : 'Create Pipeline SLA'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  PipelineSLAsTab                                                    */
/* ------------------------------------------------------------------ */

export function PipelineSLAsTab() {
  const { selectedPipelineId } = usePipeline();
  const [items, setItems] = useState<PipelineSLAItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const [search, setSearch] = useState('');
  const [tierFilter, setTierFilter] = useState<Set<string>>(new Set());
  const [domainFilter, setDomainFilter] = useState<Set<string>>(new Set());

  const refreshItems = useCallback(() => {
    if (!selectedPipelineId) return;
    setLoading(true);
    setError(null);

    fetch(`/api/schedule/policies/assignments?stackId=${selectedPipelineId}`)
      .then(res => {
        if (!res.ok) throw new Error('Failed to fetch');
        return res.json();
      })
      .then(data => setItems(data.assignments || []))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [selectedPipelineId]);

  useEffect(() => {
    refreshItems();
  }, [refreshItems]);

  const filtered = useMemo(() => {
    let result = items;

    if (search) {
      const q = search.toLowerCase();
      result = result.filter(i =>
        (i.nodeName || i.nodeFqn).toLowerCase().includes(q) ||
        (i.platform || '').toLowerCase().includes(q) ||
        (i.profileName || '').toLowerCase().includes(q)
      );
    }

    if (tierFilter.size > 0) {
      result = result.filter(i => i.slaTier && tierFilter.has(i.slaTier.toUpperCase()));
    }

    if (domainFilter.size > 0) {
      result = result.filter(i => i.nodeDomain && domainFilter.has(i.nodeDomain));
    }

    return result;
  }, [items, search, tierFilter, domainFilter]);

  const hasActiveFilters = search.length > 0 || tierFilter.size > 0 || domainFilter.size > 0;

  const toggleFilter = (set: Set<string>, setter: (s: Set<string>) => void, value: string) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setter(next);
  };

  if (loading) {
    return <div className="text-center py-12 text-[var(--muted)]">Loading pipeline SLAs...</div>;
  }

  if (error) {
    return <div className="text-center py-12 text-red-400">Failed to load pipeline SLAs: {error}</div>;
  }

  return (
    <div>
      <div className="flex items-center justify-end mb-4">
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 transition-opacity"
        >
          <Plus className="w-3.5 h-3.5" /> Create Pipeline SLA
        </button>
      </div>

      <GovernanceFilters
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="Search by node name, platform, or profile..."
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
            label: 'Domain',
            options: [
              { value: 'ingestion', label: 'Ingestion', dot: '#10B981' },
              { value: 'orchestration', label: 'Orchestration', dot: '#F97316' },
              { value: 'transform', label: 'Transform', dot: '#F59E0B' },
              { value: 'bi', label: 'BI', dot: '#3B82F6' },
              { value: 'warehouse', label: 'Warehouse', dot: '#8B5CF6' },
            ],
            selected: domainFilter,
            onToggle: v => toggleFilter(domainFilter, setDomainFilter, v),
          },
        ]}
        onClearAll={() => {
          setSearch('');
          setTierFilter(new Set());
          setDomainFilter(new Set());
        }}
        hasActiveFilters={hasActiveFilters}
        totalCount={items.length}
        filteredCount={filtered.length}
      />

      {filtered.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-[var(--muted)] text-[13px]">
            {items.length === 0
              ? 'No pipeline SLAs assigned yet. Use Pipeline SLA mode in lineage or create one here.'
              : 'No pipeline SLAs match your filters.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((item) => (
            <PipelineSLACard
              key={`${item.assignmentId}-${item.nodeFqn}`}
              item={item}
              onClick={() => {
                // Edit drawer will be added in a future iteration
              }}
            />
          ))}
        </div>
      )}

      {showCreate && selectedPipelineId && (
        <PipelineSLACreatorModal
          pipelineId={selectedPipelineId}
          onClose={() => setShowCreate(false)}
          onCreated={refreshItems}
        />
      )}
    </div>
  );
}
