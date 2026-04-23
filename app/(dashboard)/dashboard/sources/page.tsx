'use client';

import { useState, useCallback, useMemo } from 'react';
import Link from 'next/link';
import { Search, Filter, SortAsc, SortDesc, Plus, Database, X } from 'lucide-react';
import { PipelineLayer, LAYER_COLORS, LAYER_LABELS } from '@/components/pipeline/types';
import { useSourcesData, filterAndSort } from '@/components/sources/useSourcesData';
import {
  ControlPlaneSource,
  SourceStatus,
  ExtractionStatus,
  SourceFilters,
  SortField,
  STATUS_CONFIG,
  EXTRACTION_STATUS_CONFIG,
  getDefaultFilters,
} from '@/components/sources/types';
import SourceSummaryBar from '@/components/sources/SourceSummaryBar';
import SourceCard from '@/components/sources/SourceCard';
import SourceDetailDrawer from '@/components/sources/SourceDetailDrawer';
// SLA editing removed — SLAs are defined in lineage, viewed read-only here

const ALL_LAYERS: PipelineLayer[] = ['INGESTION', 'ORCHESTRATION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'STORAGE'];
// Layers that don't participate in the data pipeline graph (alerting/ticketing destinations).
const NON_PIPELINE_LAYERS = new Set<PipelineLayer>(['NOTIFICATIONS']);
const ALL_STATUSES: SourceStatus[] = ['healthy', 'degraded', 'disconnected', 'expiring_soon', 'pending'];
const ALL_EXTRACTION_STATUSES: ExtractionStatus[] = ['ok', 'stale', 'failed', 'never'];
const SORT_OPTIONS: { field: SortField; label: string }[] = [
  { field: 'name', label: 'Name' },
  { field: 'status', label: 'Status' },
  { field: 'layer', label: 'Layer' },
  { field: 'lastTestedAt', label: 'Last Check' },
  { field: 'lastExtractedAt', label: 'Last Extracted' },
];

export default function SourcesPage() {
  const { sources, summary, pipelineSLA, loading, error, refresh, patchSource } = useSourcesData();
  const [filters, setFilters] = useState<SourceFilters>(getDefaultFilters());
  const [selectedSource, setSelectedSource] = useState<ControlPlaneSource | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [showLayerFilter, setShowLayerFilter] = useState(false);
  const [showExtractionFilter, setShowExtractionFilter] = useState(false);
  const filtered = useMemo(() => filterAndSort(sources, filters), [sources, filters]);
  const { pipelineSources, nonPipelineSources } = useMemo(() => {
    const pipe: ControlPlaneSource[] = [];
    const nonPipe: ControlPlaneSource[] = [];
    for (const s of filtered) {
      (NON_PIPELINE_LAYERS.has(s.layer) ? nonPipe : pipe).push(s);
    }
    return { pipelineSources: pipe, nonPipelineSources: nonPipe };
  }, [filtered]);

  const updateSearch = useCallback((search: string) => {
    setFilters(f => ({ ...f, search }));
  }, []);

  const toggleLayer = useCallback((layer: PipelineLayer) => {
    setFilters(f => {
      const next = new Set(f.layers);
      if (next.has(layer)) next.delete(layer); else next.add(layer);
      return { ...f, layers: next };
    });
  }, []);

  const toggleStatus = useCallback((status: SourceStatus) => {
    setFilters(f => {
      const next = new Set(f.statuses);
      if (next.has(status)) next.delete(status); else next.add(status);
      return { ...f, statuses: next };
    });
  }, []);

  const toggleExtractionStatus = useCallback((es: ExtractionStatus) => {
    setFilters(f => {
      const next = new Set(f.extractionStatuses);
      if (next.has(es)) next.delete(es); else next.add(es);
      return { ...f, extractionStatuses: next };
    });
  }, []);

  const setSort = useCallback((field: SortField) => {
    setFilters(f => ({
      ...f,
      sort: { field, dir: f.sort.field === field && f.sort.dir === 'asc' ? 'desc' : 'asc' },
    }));
  }, []);

  const handleTestConnection = useCallback(async (source: ControlPlaneSource) => {
    setTestingId(source.id);
    try {
      const res = await fetch(`/api/integrations/${source.id}/test`, { method: 'POST' });
      if (res.ok) refresh(true);
    } catch {} finally {
      setTestingId(null);
    }
  }, [refresh]);

  const handleDisconnect = useCallback(async (source: ControlPlaneSource) => {
    if (!confirm(`Disconnect ${source.name}? This will remove the integration.`)) return;
    try {
      await fetch(`/api/integrations/${source.id}`, { method: 'DELETE' });
      refresh(true);
      if (selectedSource?.id === source.id) setSelectedSource(null);
    } catch {}
  }, [refresh, selectedSource]);


  const activeFilterCount =
    filters.layers.size + filters.statuses.size + filters.extractionStatuses.size + filters.slaTiers.size +
    (filters.search ? 1 : 0);

  // Loading skeleton
  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)] p-4 animate-pulse">
              <div className="h-3 w-20 bg-[var(--overlay-medium)] rounded mb-2" />
              <div className="h-6 w-12 bg-[var(--overlay-medium)] rounded" />
            </div>
          ))}
        </div>
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)] p-4 animate-pulse">
              <div className="flex items-center gap-4">
                <div className="w-9 h-9 rounded-lg bg-[var(--overlay-medium)]" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-4 w-32 bg-[var(--overlay-medium)] rounded" />
                  <div className="h-3 w-48 bg-[var(--overlay-bg)] rounded" />
                </div>
                <div className="h-5 w-16 bg-[var(--overlay-medium)] rounded-full" />
                <div className="h-5 w-16 bg-[var(--overlay-bg)] rounded-full" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Empty state
  if (!loading && sources.length === 0) {
    return (
      <div className="p-6">
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[var(--overlay-bg)] flex items-center justify-center mb-4">
            <Database className="w-8 h-8 text-[var(--text-faint)]" />
          </div>
          <h2 className="text-lg font-semibold text-[var(--text)] mb-2">No sources connected</h2>
          <p className="text-sm text-[var(--text-tertiary)] max-w-sm mb-6">
            Connect your data warehouse, ingestion tools, and transformation layers to get started.
          </p>
          <Link
            href="/dashboard/pipeline"
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)]
                       text-white text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" />
            Open Integrations
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5">
      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
          {error}
        </div>
      )}

      <SourceSummaryBar summary={summary} />

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-faint)]" />
          <input
            type="text"
            value={filters.search}
            onChange={(e) => updateSearch(e.target.value)}
            placeholder="Search sources..."
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)]
                       text-sm text-[var(--text)] placeholder:text-[var(--text-faint)]
                       focus:outline-none focus:border-[var(--border-medium)]"
          />
          {filters.search && (
            <button
              onClick={() => updateSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-faint)]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Domain filter (Data Plane / Control Plane / All) */}
        <div className="flex items-center gap-1 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)] p-0.5">
          {(['ALL', 'DATA_PLANE', 'CONTROL_PLANE'] as const).map((d) => (
            <button
              key={d}
              onClick={() => setFilters(f => ({ ...f, graphDomain: d }))}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                filters.graphDomain === d
                  ? 'bg-[var(--active-bg)] text-[var(--text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              {d === 'ALL' ? 'All' : d === 'DATA_PLANE' ? 'Data' : 'Control'}
            </button>
          ))}
        </div>

        {/* Layer filter */}
        <FilterDropdown
          label="Layer"
          active={filters.layers.size > 0}
          count={filters.layers.size}
          open={showLayerFilter}
          onToggle={() => { setShowLayerFilter(!showLayerFilter); setShowExtractionFilter(false);}}
          onClear={() => setFilters(f => ({ ...f, layers: new Set() }))}
        >
          {ALL_LAYERS.map((layer) => (
            <FilterItem
              key={layer}
              label={LAYER_LABELS[layer]}
              active={filters.layers.has(layer)}
              onClick={() => toggleLayer(layer)}
              dot={LAYER_COLORS[layer]}
            />
          ))}
        </FilterDropdown>

        {/* Extraction status filter */}
        <FilterDropdown
          label="Extraction"
          active={filters.extractionStatuses.size > 0}
          count={filters.extractionStatuses.size}
          open={showExtractionFilter}
          onToggle={() => { setShowExtractionFilter(!showExtractionFilter); setShowLayerFilter(false);}}
          onClear={() => setFilters(f => ({ ...f, extractionStatuses: new Set() }))}
        >
          {ALL_EXTRACTION_STATUSES.map((es) => {
            const cfg = EXTRACTION_STATUS_CONFIG[es];
            const count = sources.filter(s => s.extractionStatus === es).length;
            return (
              <FilterItem
                key={es}
                label={`${cfg.label} (${count})`}
                active={filters.extractionStatuses.has(es)}
                onClick={() => toggleExtractionStatus(es)}
              />
            );
          })}
        </FilterDropdown>

        {/* Status filter pills */}
        <div className="flex items-center gap-1">
          {ALL_STATUSES.map((status) => {
            const cfg = STATUS_CONFIG[status];
            const active = filters.statuses.has(status);
            const count = sources.filter(s => s.status === status).length;
            if (count === 0) return null;
            return (
              <button
                key={status}
                onClick={() => toggleStatus(status)}
                className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-colors
                  ${active ? `${cfg.bg} ${cfg.color}` : 'text-[var(--text-faint)] hover:text-[var(--text-tertiary)]'}`}
              >
                {cfg.label}
                <span className="text-[10px] opacity-60">{count}</span>
              </button>
            );
          })}
        </div>

        {/* Sort */}
        <div className="flex items-center gap-1 ml-auto">
          {SORT_OPTIONS.map((opt) => {
            const active = filters.sort.field === opt.field;
            return (
              <button
                key={opt.field}
                onClick={() => setSort(opt.field)}
                className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-colors
                  ${active ? 'text-[var(--text)] bg-[var(--overlay-medium)]' : 'text-[var(--text-faint)] hover:text-[var(--text-tertiary)]'}`}
              >
                {opt.label}
                {active && (
                  filters.sort.dir === 'asc'
                    ? <SortAsc className="w-3 h-3" />
                    : <SortDesc className="w-3 h-3" />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Active filters */}
      {activeFilterCount > 0 && (
        <div className="flex items-center gap-2 text-xs text-[var(--text-faint)]">
          <span>Showing {filtered.length} of {sources.length} sources</span>
          <button onClick={() => setFilters(getDefaultFilters())} className="text-[var(--accent-2)] hover:underline">
            Clear all filters
          </button>
        </div>
      )}

      {/* Source list — split into pipeline vs non-pipeline (alerting/ticketing) */}
      <div className="space-y-6">
        <SourceSection
          title="Pipeline tools"
          description="Tools that move, store, or transform data in your pipeline"
          sources={pipelineSources}
          testingId={testingId}
          onSelect={setSelectedSource}
          onTestConnection={handleTestConnection}
          onDisconnect={handleDisconnect}
        />
        {nonPipelineSources.length > 0 && (
          <SourceSection
            title="Non-pipeline tools"
            description="Alerting, ticketing, and other destinations that react to pipeline events"
            sources={nonPipelineSources}
            testingId={testingId}
            onSelect={setSelectedSource}
            onTestConnection={handleTestConnection}
            onDisconnect={handleDisconnect}
          />
        )}
        {filtered.length === 0 && sources.length > 0 && (
          <div className="text-center py-12">
            <p className="text-sm text-[var(--text-faint)]">No sources match your filters</p>
            <button onClick={() => setFilters(getDefaultFilters())} className="mt-2 text-xs text-[var(--accent-2)] hover:underline">
              Clear filters
            </button>
          </div>
        )}
      </div>

      {/* Detail drawer */}
      {selectedSource && (
        <SourceDetailDrawer
          source={selectedSource}
          onClose={() => setSelectedSource(null)}
          onQuickLinksChange={(id, links) => {
            patchSource(id, { quickLinks: links });
            setSelectedSource((cur) => (cur && cur.id === id ? { ...cur, quickLinks: links } : cur));
          }}
        />
      )}

    </div>
  );
}

// ─── Source section (groups cards under a heading) ────────────────

function SourceSection({
  title,
  description,
  sources,
  testingId,
  onSelect,
  onTestConnection,
  onDisconnect,
}: {
  title: string;
  description: string;
  sources: ControlPlaneSource[];
  testingId: string | null;
  onSelect: (s: ControlPlaneSource) => void;
  onTestConnection: (s: ControlPlaneSource) => void;
  onDisconnect: (s: ControlPlaneSource) => void;
}) {
  if (sources.length === 0) {
    return (
      <div>
        <SectionHeader title={title} description={description} count={0} />
        <p className="text-xs text-[var(--text-faint)] px-1">No tools in this group.</p>
      </div>
    );
  }
  return (
    <div>
      <SectionHeader title={title} description={description} count={sources.length} />
      <div className="space-y-2">
        {sources.map((source) => (
          <div key={source.id} className="relative">
            <SourceCard
              source={source}
              onClick={onSelect}
              onTestConnection={onTestConnection}
              onDisconnect={onDisconnect}
            />
            {testingId === source.id && (
              <div className="absolute inset-0 rounded-lg bg-[var(--surface)]/60 flex items-center justify-center">
                <div className="w-5 h-5 border-2 border-[var(--overlay-strong)] border-t-[var(--text-tertiary)] rounded-full animate-spin" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function SectionHeader({ title, description, count }: { title: string; description: string; count: number }) {
  return (
    <div className="flex items-baseline justify-between mb-2 px-1">
      <div>
        <h3 className="text-[13px] font-semibold text-[var(--text)] uppercase tracking-wide">
          {title}
          <span className="ml-2 text-[11px] font-medium text-[var(--text-faint)]">{count}</span>
        </h3>
        <p className="text-[11px] text-[var(--text-faint)] mt-0.5">{description}</p>
      </div>
    </div>
  );
}

// ─── Reusable filter components ───────────────────────────────────

function FilterDropdown({
  label, active, count, open, onToggle, onClear, children,
}: {
  label: string; active: boolean; count: number; open: boolean;
  onToggle: () => void; onClear: () => void; children: React.ReactNode;
}) {
  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-sm transition-colors
          ${active
            ? 'border-[var(--accent)] text-[var(--accent-2)] bg-[var(--accent)]/5'
            : 'border-[var(--subtle-border)] text-[var(--text-tertiary)] hover:text-[var(--text)]'
          }`}
      >
        <Filter className="w-3.5 h-3.5" />
        {label}
        {count > 0 && (
          <span className="ml-1 px-1.5 py-0.5 rounded-full bg-[var(--accent)] text-white text-[10px] font-medium">
            {count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 w-52 rounded-lg border border-[var(--subtle-border)]
                       bg-[var(--surface)] shadow-xl z-50 py-1">
          {children}
          {active && (
            <button
              onClick={onClear}
              className="w-full px-3 py-2 text-xs text-[var(--text-faint)] hover:text-[var(--text-tertiary)]
                         border-t border-[var(--subtle-border)] transition-colors"
            >
              Clear filter
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function FilterItem({
  label, active, onClick, dot,
}: {
  label: string; active: boolean; onClick: () => void; dot?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors
        ${active ? 'bg-[var(--hover-bg)] text-[var(--text)]' : 'text-[var(--text-secondary)] hover:bg-[var(--hover-bg)]'}`}
    >
      {dot && <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: dot }} />}
      {label}
      {active && <span className="ml-auto text-[var(--accent-2)]">&#10003;</span>}
    </button>
  );
}
