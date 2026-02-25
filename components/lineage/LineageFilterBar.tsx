'use client';

import React from 'react';
import { Search } from 'lucide-react';
import { PipelineLayer, LAYER_COLORS } from '@/components/pipeline/types';
import {
  LineageFilterState,
  LineageLevelFilter,
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
    dagNodes?: number;
    taskNodes?: number;
  };
  activeTab?: 'data' | 'control-plane' | 'lane-overview';
}

const LAYER_ORDER: PipelineLayer[] = ['INGESTION', 'ORCHESTRATION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING', 'STORAGE'];

const LAYER_LABELS: Record<PipelineLayer, string> = {
  INGESTION: 'Ingestion',
  VERSION_CONTROL: 'VCS',
  ORCHESTRATION: 'Orchestration',
  TRANSFORMATION: 'Transformation',
  WAREHOUSE: 'Warehouse',
  REPORTING: 'Reporting',
  STORAGE: 'Storage',
  INFRASTRUCTURE: 'Infrastructure',
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
                ({stats.tableNodes + stats.viewNodes + stats.modelNodes + (stats.dagNodes || 0) + (stats.taskNodes || 0)})
              </span>
            )}
          </button>
        </div>
      )}

      {/* Separator */}
      {!isControlPlane && <div className="w-px h-6 bg-[var(--overlay-medium)]" />}

      {/* Lineage level toggle */}
      {!isControlPlane && (
        <div className="flex items-center gap-1">
          {(['all', 'table', 'column'] as LineageLevelFilter[]).map((level) => (
            <button
              key={level}
              onClick={() => onChange({ ...filters, lineageLevel: level })}
              className={`
                px-2 py-1 rounded text-[11px] font-medium transition-all capitalize
                ${
                  filters.lineageLevel === level
                    ? 'bg-violet-500/20 text-violet-300 border border-violet-500/30'
                    : 'text-[var(--muted)] hover:text-[var(--text-tertiary)] hover:bg-[var(--subtle-bg)]'
                }
              `}
            >
              {level === 'all' ? 'All Levels' : level}
            </button>
          ))}
        </div>
      )}

      {/* Inferred toggle */}
      {!isControlPlane && (
        <button
          onClick={() => onChange({ ...filters, showInferred: !filters.showInferred })}
          className={`
            flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium transition-all
            ${filters.showInferred ? 'bg-amber-500/20 text-amber-300' : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'}
          `}
          title={filters.showInferred ? 'Hide inferred nodes/edges' : 'Show inferred nodes/edges'}
        >
          <span
            className="w-3 h-0.5 rounded"
            style={{ borderTop: '1.5px dashed currentColor' }}
          />
          Inferred
        </button>
      )}

      {/* Separator */}
      {!isControlPlane && <div className="w-px h-6 bg-[var(--overlay-medium)]" />}

      {/* Confidence threshold */}
      {!isControlPlane && filters.minConfidence > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[var(--muted)]">Min Confidence</span>
          <span className="text-[11px] text-[var(--text)] font-medium">{Math.round(filters.minConfidence * 100)}%</span>
        </div>
      )}
      {!isControlPlane && (
        <input
          type="range"
          min="0"
          max="100"
          step="10"
          value={filters.minConfidence * 100}
          onChange={(e) => onChange({ ...filters, minConfidence: parseInt(e.target.value) / 100 })}
          className="w-16 h-1 accent-violet-500 cursor-pointer"
          title={`Min confidence: ${Math.round(filters.minConfidence * 100)}%`}
        />
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
