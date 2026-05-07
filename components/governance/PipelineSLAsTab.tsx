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
  // values keyed by "domain:fieldKey" to support per-domain config
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const selectedMetas = useMemo(
    () => allNodes.filter(n => selectedNodeIds.includes(n.id)),
    [allNodes, selectedNodeIds],
  );

  // Group selected nodes by domain
  const domainGroups = useMemo(() => {
    const groups: Record<string, NodeMeta[]> = {};
    for (const node of selectedMetas) {
      const domain = (PIPELINE_SLA_DOMAINS as readonly string[]).includes(node.domain)
        ? node.domain
        : 'warehouse';
      if (!groups[domain]) groups[domain] = [];
      groups[domain].push(node);
    }
    return groups;
  }, [selectedMetas]);

  const domainKeys = Object.keys(domainGroups);
  const isSingleDomain = domainKeys.length === 1;

  const handleSave = async () => {
    if (selectedMetas.length === 0) return;
    setSaving(true);

    try {
      // Create one assignment per domain group
      for (const [domain, nodes] of Object.entries(domainGroups)) {
        const domainFields = PIPELINE_SLA_FIELDS[domain] || [];
        const overrides: Record<string, Record<string, unknown>> = {};

        for (const f of domainFields) {
          const valKey = isSingleDomain ? f.key : `${domain}:${f.key}`;
          const val = values[valKey];
          if (!val) continue;
          const [section, field] = f.key.split('.');
          if (!overrides[section]) overrides[section] = {};
          overrides[section][field] = f.type === 'number' ? Number(val) : val;
        }

        const res = await fetch('/api/schedule/policies/assign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            stackId: pipelineId,
            profileId: '__custom',
            assignmentType: 'direct',
            nodeFqns: nodes.map(n => n.fqn),
            nodeDomain: domain,
            overrides,
          }),
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || 'Failed to create pipeline SLA');
        }
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
          <div className="flex-1 overflow-y-auto p-5 space-y-5">
            {/* Per-domain config sections */}
            {domainKeys.map(domain => {
              const nodes = domainGroups[domain];
              const domainFields = PIPELINE_SLA_FIELDS[domain] || [];
              const domainLabel = domain.charAt(0).toUpperCase() + domain.slice(1);

              return (
                <div key={domain} className="space-y-3">
                  {/* Domain header with node pills */}
                  <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-[11px] font-semibold text-[var(--foreground)] uppercase tracking-wide">
                        {domainLabel}
                      </span>
                      <span className="text-[10px] text-[var(--muted)]">
                        {nodes.length} node{nodes.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {nodes.slice(0, 6).map(n => (
                        <span key={n.id} className="text-[10px] px-2 py-0.5 rounded bg-[var(--surface-raised)] text-[var(--text)] font-mono truncate max-w-[200px]">
                          {n.name}
                        </span>
                      ))}
                      {nodes.length > 6 && <span className="text-[10px] text-[var(--muted)]">+{nodes.length - 6} more</span>}
                    </div>
                  </div>

                  {/* Domain fields */}
                  {domainFields.map(f => {
                    const valKey = isSingleDomain ? f.key : `${domain}:${f.key}`;
                    return (
                      <div key={valKey}>
                        <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide block mb-1">{f.label}</label>
                        {f.type === 'number' ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="number"
                              placeholder={f.placeholder}
                              value={values[valKey] || ''}
                              onChange={e => setValues(v => ({ ...v, [valKey]: e.target.value }))}
                              className="flex-1 px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)]"
                            />
                            {f.unit && <span className="text-[11px] text-[var(--muted)] whitespace-nowrap">{f.unit}</span>}
                          </div>
                        ) : (
                          <select
                            value={values[valKey] || ''}
                            onChange={e => setValues(v => ({ ...v, [valKey]: e.target.value }))}
                            className="w-full px-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-sm text-[var(--foreground)]"
                          >
                            <option value="">Select...</option>
                            {f.options?.map(o => (
                              <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
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
              <button onClick={handleSave} disabled={domainKeys.length === 0 || saving}
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

    if (domainFilter.size > 0) {
      result = result.filter(i => i.nodeDomain && domainFilter.has(i.nodeDomain));
    }

    if (statusFilter.size > 0) {
      result = result.filter(i => statusFilter.has(i.status || 'active'));
    }

    return result;
  }, [items, search, domainFilter, statusFilter]);

  const hasActiveFilters = search.length > 0 || domainFilter.size > 0 || statusFilter.size > 0;

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
              // No edit-mode drawer yet; route Edit to View so the menu
              // item isn't a silent no-op. Wire to a real edit drawer when
              // one ships.
              onClick={() => setViewItem(item)}
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
