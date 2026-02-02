'use client';

/**
 * Node Sidebar
 * 
 * Tool palette for adding nodes to the pipeline canvas
 */

import { useState } from 'react';
import { TOOLS, LAYER_COLORS, PipelineLayer } from './types';

interface NodeSidebarProps {
  onAddNode: (toolType: string, layer: string) => void;
}

// Layer icons as SVG components
const LayerIcon = ({ layer }: { layer: PipelineLayer }) => {
  switch (layer) {
    case 'INGESTION':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
        </svg>
      );
    case 'TRANSFORMATION':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
        </svg>
      );
    case 'WAREHOUSE':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <ellipse cx="12" cy="6" rx="8" ry="3" />
          <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
          <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
        </svg>
      );
    case 'REPORTING':
      return (
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75z" />
          <path d="M9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625z" />
          <path d="M16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
        </svg>
      );
  }
};

export default function NodeSidebar({ onAddNode }: NodeSidebarProps) {
  const [expandedLayers, setExpandedLayers] = useState<Set<PipelineLayer>>(
    new Set(['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING'])
  );

  const toggleLayer = (layer: PipelineLayer) => {
    const newExpanded = new Set(expandedLayers);
    if (newExpanded.has(layer)) {
      newExpanded.delete(layer);
    } else {
      newExpanded.add(layer);
    }
    setExpandedLayers(newExpanded);
  };

  const layers: PipelineLayer[] = ['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'REPORTING'];

  return (
    <div className="w-72 flex flex-col bg-[#0F0F14] border border-[rgba(255,255,255,0.08)] rounded-xl overflow-hidden flex-shrink-0">
      {/* Header */}
      <div className="px-4 py-4 border-b border-[rgba(255,255,255,0.08)]">
        <h2 className="font-semibold text-white text-sm">Pipeline Tools</h2>
        <p className="text-xs text-gray-500 mt-1">Click to add to canvas</p>
      </div>

      {/* Tool List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {layers.map((layer) => (
          <div key={layer} className="rounded-lg overflow-hidden">
            {/* Layer Header */}
            <button
              onClick={() => toggleLayer(layer)}
              className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-[rgba(255,255,255,0.04)] transition-colors rounded-lg"
            >
              <div className="flex items-center gap-3">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{ backgroundColor: `${LAYER_COLORS[layer]}15`, color: LAYER_COLORS[layer] }}
                >
                  <LayerIcon layer={layer} />
                </div>
                <div className="text-left">
                  <div className="text-sm font-medium text-white">
                    {layer === 'TRANSFORMATION' ? 'Transform' : layer.charAt(0) + layer.slice(1).toLowerCase()}
                  </div>
                  <div className="text-[10px] text-gray-500">{TOOLS[layer].length} tools</div>
                </div>
              </div>
              <svg
                className={`w-4 h-4 text-gray-500 transition-transform ${expandedLayers.has(layer) ? 'rotate-180' : ''}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {/* Tools in Layer */}
            {expandedLayers.has(layer) && (
              <div className="mt-1 space-y-1 pl-2">
                {TOOLS[layer].map((tool) => (
                  <button
                    key={tool.id}
                    onClick={() => {
                      console.log('Sidebar: Adding tool', tool.id, layer);
                      onAddNode(tool.id, layer);
                    }}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-[rgba(255,255,255,0.02)] hover:bg-[rgba(255,255,255,0.06)] border border-transparent hover:border-[rgba(255,255,255,0.1)] transition-all group"
                  >
                    {/* Tool Icon Circle */}
                    <div
                      className="w-9 h-9 rounded-lg flex items-center justify-center text-sm font-bold group-hover:scale-105 transition-transform"
                      style={{ backgroundColor: `${LAYER_COLORS[layer]}20`, color: LAYER_COLORS[layer] }}
                    >
                      {tool.name.charAt(0)}
                    </div>
                    <div className="flex-1 text-left min-w-0">
                      <div className="text-sm font-medium text-white truncate">{tool.name}</div>
                      <div className="text-[10px] text-gray-500 truncate">{tool.description}</div>
                    </div>
                    <svg 
                      className="w-4 h-4 text-gray-600 group-hover:text-white group-hover:translate-x-0.5 transition-all flex-shrink-0" 
                      viewBox="0 0 24 24" 
                      fill="none" 
                      stroke="currentColor" 
                      strokeWidth="2"
                    >
                      <path d="M12 4v16m8-8H4" />
                    </svg>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Footer - Data Flow Legend */}
      <div className="px-4 py-3 border-t border-[rgba(255,255,255,0.08)] bg-[rgba(0,0,0,0.2)]">
        <div className="text-[10px] text-gray-500 mb-2 uppercase tracking-wider">Data Flow</div>
        <div className="flex items-center gap-1.5">
          {layers.map((layer, i) => (
            <div key={layer} className="flex items-center gap-1.5">
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: LAYER_COLORS[layer] }}
              />
              {i < layers.length - 1 && (
                <svg className="w-3 h-3 text-gray-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12h14M12 5l7 7-7 7" />
                </svg>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
