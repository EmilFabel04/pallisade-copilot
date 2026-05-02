'use client';

import React from 'react';
import { Search } from 'lucide-react';
import { PipelineLayer, LAYER_COLORS } from '@/components/pipeline/types';
import {
  LineageFilterState,
} from './types';

interface LineageFilterBarProps {
  filters: LineageFilterState;
  onChange: (filters: LineageFilterState) => void;
  availableLayers: PipelineLayer[];
  stats?: {
    toolNodes: number;
    tableNodes: number;
    viewNodes: number;
    modelNodes: number;
    dashboardNodes?: number;
    dagNodes?: number;
    taskNodes?: number;
  };
  activeTab?: 'data' | 'control-plane' | 'lane-overview';
}

const LAYER_ORDER: PipelineLayer[] = ['SOURCE', 'INGESTION', 'ORCHESTRATION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'STORAGE'];

const LAYER_LABELS: Record<PipelineLayer, string> = {
  SOURCE: 'Sources',
  INGESTION: 'Ingestion',
  VERSION_CONTROL: 'VCS',
  ORCHESTRATION: 'Orchestration',
  TRANSFORMATION: 'Transformation',
  WAREHOUSE: 'Warehouse',
  REPORTING: 'Reporting',
  STORAGE: 'Storage',
  INFRASTRUCTURE: 'Infrastructure',
  NOTIFICATIONS: 'Notifications',
  UNCATEGORIZED: 'Uncategorized',
};

export function LineageFilterBar({
  filters,
  onChange,
  availableLayers,
  stats,
  activeTab = 'data',
}: LineageFilterBarProps) {
  const isControlPlane = activeTab === 'control-plane';

  // Toggle a single layer
  const toggleLayer = (layer: PipelineLayer) => {
    const newLayers = new Set(filters.layers);
    if (newLayers.has(layer)) {
      newLayers.delete(layer);
    } else {
      newLayers.add(layer);
    }
    onChange({ ...filters, layers: newLayers });
  };

  // Update search
  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...filters, searchQuery: e.target.value });
  };

  return (
    <div className="flex flex-wrap items-center gap-4">
      {/* Layer toggles (data tab only) */}
      {!isControlPlane && (
        <div className="flex items-center gap-1">
          {LAYER_ORDER.filter((layer) => availableLayers.includes(layer)).map((layer) => {
            const isActive = filters.layers.has(layer);
            const color = LAYER_COLORS[layer];
            return (
              <button
                key={layer}
                onClick={() => toggleLayer(layer)}
                className={`
                  flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium
                  transition-all border
                  ${
                    isActive
                      ? 'border-[var(--overlay-strong)] text-[var(--text)]'
                      : 'border-transparent text-[var(--muted)] hover:text-[var(--text-tertiary)] hover:border-[var(--border-medium)]'
                  }
                `}
                style={{
                  backgroundColor: isActive ? `${color}20` : 'transparent',
                }}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: isActive ? color : 'var(--overlay-strong)' }}
                />
                {LAYER_LABELS[layer]}
              </button>
            );
          })}
        </div>
      )}

      {/* Graph Domain toggle */}
      {!isControlPlane && (
        <div className="flex items-center gap-0.5 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] p-0.5">
          {(['ALL', 'DATA_PLANE', 'CONTROL_PLANE'] as const).map((d) => (
            <button
              key={d}
              onClick={() => onChange({ ...filters, graphDomain: d })}
              className={`
                px-2 py-1 rounded-md text-[11px] font-medium transition-colors
                ${filters.graphDomain === d
                  ? 'bg-[var(--overlay-strong)] text-[var(--text)]'
                  : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'}
              `}
            >
              {d === 'ALL' ? 'All' : d === 'DATA_PLANE' ? 'Data' : 'Control'}
            </button>
          ))}
        </div>
      )}

      {/* Separator */}
      {!isControlPlane && <div className="w-px h-6 bg-[var(--overlay-medium)]" />}

      {/* Node type toggles */}
      {!isControlPlane && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => onChange({ ...filters, showToolNodes: !filters.showToolNodes })}
            className={`
              flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium transition-all
              ${filters.showToolNodes ? 'bg-indigo-500/20 text-indigo-300' : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'}
            `}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            Tools
            {stats && <span className="text-[var(--text-faint)]">({stats.toolNodes})</span>}
          </button>
          <button
            onClick={() => onChange({ ...filters, showTableNodes: !filters.showTableNodes })}
            className={`
              flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium transition-all
              ${filters.showTableNodes ? 'bg-blue-500/20 text-blue-300' : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'}
            `}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            Data Assets
            {stats && (
              <span className="text-[var(--text-faint)]">
                ({stats.tableNodes + stats.viewNodes + stats.modelNodes + (stats.dashboardNodes || 0) + (stats.dagNodes || 0) + (stats.taskNodes || 0)})
              </span>
            )}
          </button>
        </div>
      )}

      {/* Search */}
      <div className="ml-auto relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-faint)]" />
        <input
          type="text"
          placeholder="Search nodes..."
          value={filters.searchQuery}
          onChange={handleSearch}
          className="pl-8 pr-3 py-1.5 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] text-[12px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] w-48"
        />
      </div>
    </div>
  );
}

export default LineageFilterBar;
