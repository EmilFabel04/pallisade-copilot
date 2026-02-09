'use client';

import React from 'react';
import { Search } from 'lucide-react';
import { PipelineLayer, LAYER_COLORS } from '@/components/pipeline/types';
import {
  LineageFilterState,
  LineageFilterPreset,
  FILTER_PRESETS,
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
  };
}

const LAYER_ORDER: PipelineLayer[] = ['INGESTION', 'VERSION_CONTROL', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING'];

const LAYER_LABELS: Record<PipelineLayer, string> = {
  INGESTION: 'Ingestion',
  VERSION_CONTROL: 'VCS',
  TRANSFORMATION: 'Transformation',
  WAREHOUSE: 'Warehouse',
  REPORTING: 'Reporting',
};

export function LineageFilterBar({
  filters,
  onChange,
  availableLayers,
  stats,
}: LineageFilterBarProps) {
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

  // Apply a preset
  const applyPreset = (preset: LineageFilterPreset) => {
    const config = FILTER_PRESETS[preset];
    onChange({
      layers: new Set(config.layers),
      showToolNodes: config.showToolNodes,
      showTableNodes: config.showTableNodes,
      searchQuery: filters.searchQuery, // Preserve search
    });
  };

  // Update search
  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...filters, searchQuery: e.target.value });
  };

  // Check if a preset matches current state
  const isPresetActive = (preset: LineageFilterPreset): boolean => {
    const config = FILTER_PRESETS[preset];
    if (config.showToolNodes !== filters.showToolNodes) return false;
    if (config.showTableNodes !== filters.showTableNodes) return false;
    if (config.layers.length !== filters.layers.size) return false;
    for (const layer of config.layers) {
      if (!filters.layers.has(layer)) return false;
    }
    return true;
  };

  return (
    <div className="flex flex-wrap items-center gap-4">
      {/* Layer toggles */}
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
                    ? 'border-white/20 text-white'
                    : 'border-transparent text-white/40 hover:text-white/60 hover:border-white/10'
                }
              `}
              style={{
                backgroundColor: isActive ? `${color}20` : 'transparent',
              }}
            >
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: isActive ? color : 'rgba(255,255,255,0.2)' }}
              />
              {LAYER_LABELS[layer]}
            </button>
          );
        })}
      </div>

      {/* Separator */}
      <div className="w-px h-6 bg-white/10" />

      {/* Quick presets */}
      <div className="flex items-center gap-1">
        {(Object.keys(FILTER_PRESETS) as LineageFilterPreset[]).map((preset) => {
          const config = FILTER_PRESETS[preset];
          const isActive = isPresetActive(preset);
          return (
            <button
              key={preset}
              onClick={() => applyPreset(preset)}
              className={`
                px-2.5 py-1 rounded text-[11px] font-medium transition-all
                ${
                  isActive
                    ? 'bg-white/10 text-white border border-white/20'
                    : 'text-white/40 hover:text-white/60 hover:bg-white/5'
                }
              `}
              title={config.description}
            >
              {config.label}
            </button>
          );
        })}
      </div>

      {/* Separator */}
      <div className="w-px h-6 bg-white/10" />

      {/* Node type toggles */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => onChange({ ...filters, showToolNodes: !filters.showToolNodes })}
          className={`
            flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium transition-all
            ${filters.showToolNodes ? 'bg-indigo-500/20 text-indigo-300' : 'text-white/40 hover:text-white/60'}
          `}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-current" />
          Tools
          {stats && <span className="text-white/30">({stats.toolNodes})</span>}
        </button>
        <button
          onClick={() => onChange({ ...filters, showTableNodes: !filters.showTableNodes })}
          className={`
            flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium transition-all
            ${filters.showTableNodes ? 'bg-blue-500/20 text-blue-300' : 'text-white/40 hover:text-white/60'}
          `}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-current" />
          Data Assets
          {stats && (
            <span className="text-white/30">
              ({stats.tableNodes + stats.viewNodes + stats.modelNodes})
            </span>
          )}
        </button>
      </div>

      {/* Search */}
      <div className="ml-auto relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
        <input
          type="text"
          placeholder="Search nodes..."
          value={filters.searchQuery}
          onChange={handleSearch}
          className="pl-8 pr-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.06] text-[12px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.12] w-48"
        />
      </div>
    </div>
  );
}

export default LineageFilterBar;
