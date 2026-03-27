'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Plus, X, ChevronRight, Shield } from 'lucide-react';
import { usePipeline } from '@/contexts/PipelineContext';
import { GovernanceFilters } from './GovernanceFilters';
import { PipelineSLACard, type PipelineSLAItem } from './PipelineSLACard';
import { NodeSelectionSurface, type NodeMeta } from '@/components/schedule/NodeSelectionSurface';
import { toast } from 'sonner';
import { SLAViewDrawer } from './SLAViewDrawer';
import { PIPELINE_SLA_FIELDS, PIPELINE_SLA_DOMAINS, type PipelineSLAFieldDef } from '@/lib/pipeline-sla-fields';

/* ------------------------------------------------------------------ */
/*  Component types and constants                                      */
/* ------------------------------------------------------------------ */

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
      if (PIPELINE_SLA_DOMAINS.includes(detected as typeof PIPELINE_SLA_DOMAINS[number])) {
        setSelectedDomain(detected);
      }
    }
  }, [step, selectedMetas]);

  const fields = selectedDomain ? PIPELINE_SLA_FIELDS[selectedDomain] || [] : [];

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
    <div className="fixed inset-x-0 top-14 bottom-0 z-40 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative w-[90vw] max-w-5xl h-[80vh] bg-[var(--surface-raised)] rounded-xl border border-[var(--subtle-border)] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="p-5 border-b border-[var(--subtle-border)] flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-[var(--accent)]/15 flex items-center justify-center">
                <Shield className="w-4 h-4 text-[var(--accent)]" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-[var(--foreground)]">Create Pipeline SLA</h2>
                <p className="text-[11px] text-[var(--muted)] mt-0.5">
                  {step === 1 ? 'Click nodes in the graph to select pipeline tools' : 'Configure operational SLA expectations'}
                </p>
              </div>
            </div>
            <button onClick={onClose} className="p-1 hover:bg-[var(--subtle-bg)] rounded transition-colors">
              <X className="w-4 h-4 text-[var(--muted)]" />
            </button>
          </div>
          {/* Step indicator */}
          <div className="flex items-center gap-3 mt-4">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors ${
              step === 1
                ? 'bg-[var(--accent)]/15 text-[var(--accent)] border border-[var(--accent)]/20'
                : 'text-[var(--muted)] bg-[var(--overlay-bg)] border border-[var(--subtle-border)]'
            }`}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                step === 1 ? 'bg-[var(--accent)] text-white' : 'bg-[var(--subtle-border)] text-[var(--muted)]'
              }`}>1</span>
              Select Nodes
            </div>
            <ChevronRight className="w-3.5 h-3.5 text-[var(--muted)]" />
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors ${
              step === 2
                ? 'bg-[var(--accent)]/15 text-[var(--accent)] border border-[var(--accent)]/20'
                : 'text-[var(--muted)] bg-[var(--overlay-bg)] border border-[var(--subtle-border)]'
            }`}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                step === 2 ? 'bg-[var(--accent)] text-white' : 'bg-[var(--subtle-border)] text-[var(--muted)]'
              }`}>2</span>
              Configure SLA
            </div>
            {selectedNodeIds.length > 0 && step === 1 && (
              <span className="ml-auto text-[11px] text-[var(--accent)] font-medium bg-[var(--accent)]/10 px-2 py-1 rounded-md">
                {selectedNodeIds.length} node{selectedNodeIds.length !== 1 ? 's' : ''} selected
              </span>
            )}
          </div>
        </div>

        {/* Body */}
        {step === 1 ? (
          <div className="flex-1 min-h-0">
            <NodeSelectionSurface
              stackId={pipelineId}
              mode="pipeline-overview"
              selectedNodeIds={selectedNodeIds}
              onSelectionChange={setSelectedNodeIds}
              onNodesLoaded={setAllNodes}
            />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {/* Selected nodes summary */}
            <div className="flex flex-wrap gap-1.5">
              {selectedMetas.slice(0, 8).map(n => (
                <span key={n.id} className="text-[10px] px-2 py-0.5 rounded bg-[var(--overlay-bg)] text-[var(--text)] font-mono">{n.fqn}</span>
              ))}
              {selectedMetas.length > 8 && <span className="text-[10px] text-[var(--muted)]">+{selectedMetas.length - 8} more</span>}
            </div>

            {/* Domain */}
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">Domain</label>
              <select
                value={selectedDomain}
                onChange={e => { setSelectedDomain(e.target.value); setValues({}); }}
                className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)]"
              >
                <option value="">Select domain...</option>
                {PIPELINE_SLA_DOMAINS.map(d => (
                  <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
                ))}
              </select>
            </div>

            {/* SLA Tier */}
            <div>
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">SLA Tier</label>
              <select value={slaTier} onChange={e => setSlaTier(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)]">
                <option value="">None</option>
                <option value="T0">T0 - Critical</option>
                <option value="T1">T1 - High</option>
                <option value="T2">T2 - Standard</option>
                <option value="T3">T3 - Low</option>
              </select>
            </div>

            {/* Domain-specific fields */}
            {fields.length > 0 && (
              <div className="space-y-3">
                {fields.map(f => (
                  <div key={f.key}>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">{f.label}</label>
                    {f.type === 'number' ? (
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          placeholder={f.placeholder}
                          value={values[f.key] || ''}
                          onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                          className="flex-1 px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)]"
                        />
                        {f.unit && <span className="text-[11px] text-[var(--muted)] whitespace-nowrap">{f.unit}</span>}
                      </div>
                    ) : (
                      <select
                        value={values[f.key] || ''}
                        onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                        className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)]"
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
          </div>
        )}

        {/* Footer */}
        <div className="p-4 border-t border-[var(--subtle-border)] flex-shrink-0 flex items-center justify-between">
          <button onClick={onClose} className="px-4 py-2 text-xs font-medium rounded-md text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--overlay-bg)] transition-colors">
            Cancel
          </button>
          <div className="flex gap-2">
            {step === 2 && (
              <button onClick={() => setStep(1)} className="px-4 py-2 text-xs font-medium rounded-md text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--overlay-bg)] transition-colors">
                Back
              </button>
            )}
            {step === 1 ? (
              <button onClick={() => setStep(2)} disabled={selectedNodeIds.length === 0}
                className="px-5 py-2 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity">
                Continue
              </button>
            ) : (
              <button onClick={handleSave} disabled={!selectedDomain || saving}
                className="px-5 py-2 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 disabled:opacity-50 transition-opacity">
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
  const [viewItem, setViewItem] = useState<PipelineSLAItem | null>(null);
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());

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

    if (statusFilter.size > 0) {
      result = result.filter(i => statusFilter.has(i.status || 'active'));
    }

    return result;
  }, [items, search, tierFilter, domainFilter, statusFilter]);

  const hasActiveFilters = search.length > 0 || tierFilter.size > 0 || domainFilter.size > 0 || statusFilter.size > 0;

  const toggleFilter = (set: Set<string>, setter: (s: Set<string>) => void, value: string) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setter(next);
  };

  const handleDeleteAssignment = async (item: PipelineSLAItem) => {
    if (!confirm(`Delete pipeline SLA for "${item.nodeName || item.nodeFqn}"?`)) return;
    try {
      const res = await fetch(`/api/schedule/policies/assign?id=${item.assignmentId}`, { method: 'DELETE' });
      if (res.ok) { toast.success('Pipeline SLA deleted'); refreshItems(); }
      else { toast.error('Failed to delete'); }
    } catch { toast.error('Failed to delete'); }
  };

  const handleStatusChange = async (item: PipelineSLAItem, newStatus: string) => {
    try {
      const res = await fetch('/api/schedule/policies/assign', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: item.assignmentId, status: newStatus }),
      });
      if (res.ok) {
        toast.success(`SLA ${newStatus === 'archived' ? 'archived' : newStatus === 'active' ? 'activated' : 'deactivated'}`);
        refreshItems();
      } else { toast.error('Failed to update status'); }
    } catch { toast.error('Failed to update status'); }
  };

  const buildViewFields = (item: PipelineSLAItem) => {
    const fields: { label: string; value: string | number | null }[] = [];
    if (!item.overrides) return fields;
    for (const [section, config] of Object.entries(item.overrides)) {
      if (typeof config !== 'object' || !config) continue;
      for (const [key, value] of Object.entries(config as Record<string, unknown>)) {
        if (key === 'enabled' || value == null) continue;
        const label = key.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase())
          .replace(/Minutes$/, ' (min)').replace(/Hours$/, ' (hrs)');
        fields.push({ label: `${section}: ${label}`, value: String(value) });
      }
    }
    return fields;
  };

  if (loading) {
    return <div className="text-center py-12 text-[var(--muted)]">Loading pipeline SLAs...</div>;
  }

  if (error) {
    return <div className="text-center py-12 text-red-400">Failed to load pipeline SLAs: {error}</div>;
  }

  return (
    <div>
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
          {
            label: 'Status',
            options: [
              { value: 'active', label: 'Active' },
              { value: 'inactive', label: 'Inactive' },
              { value: 'archived', label: 'Archived' },
            ],
            selected: statusFilter,
            onToggle: v => toggleFilter(statusFilter, setStatusFilter, v),
          },
        ]}
        onClearAll={() => {
          setSearch('');
          setTierFilter(new Set());
          setDomainFilter(new Set());
          setStatusFilter(new Set());
        }}
        hasActiveFilters={hasActiveFilters}
        totalCount={items.length}
        filteredCount={filtered.length}
        actionButton={
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90 transition-opacity"
          >
            <Plus className="w-3.5 h-3.5" /> Create Pipeline SLA
          </button>
        }
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
              onView={() => setViewItem(item)}
              onClick={() => {}}
              onDelete={() => handleDeleteAssignment(item)}
              onArchive={() => handleStatusChange(item, (item.status || 'active') === 'archived' ? 'active' : 'archived')}
              onToggleActive={() => handleStatusChange(item, (item.status || 'active') === 'active' ? 'inactive' : 'active')}
            />
          ))}
        </div>
      )}

      {viewItem && (
        <SLAViewDrawer
          title={viewItem.nodeName || viewItem.nodeFqn.split('.').pop() || viewItem.nodeFqn}
          subtitle={viewItem.nodeFqn}
          slaTier={viewItem.slaTier}
          status={viewItem.status || 'active'}
          fields={buildViewFields(viewItem)}
          notes={null}
          updatedAt={viewItem.updatedAt}
          onClose={() => setViewItem(null)}
        />
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
