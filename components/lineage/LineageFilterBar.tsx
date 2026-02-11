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

  // Update search
  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...filters, searchQuery: e.target.value });
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

      {/* Separator */}
      <div className="w-px h-6 bg-white/10" />

      {/* Lineage level toggle */}
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
                  : 'text-white/40 hover:text-white/60 hover:bg-white/5'
              }
            `}
          >
            {level === 'all' ? 'All Levels' : level}
          </button>
        ))}
      </div>

      {/* Confidence threshold */}
      {filters.minConfidence > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-white/40">Min Confidence</span>
          <span className="text-[11px] text-white font-medium">{Math.round(filters.minConfidence * 100)}%</span>
        </div>
      )}
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
