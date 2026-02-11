'use client';

import React from 'react';
import {
  type UnifiedLineageNode,
  type UnifiedLineageEdge,
  getConfidenceColor,
  formatColumnMapping,
} from './types';

interface EdgeDetailPanelProps {
  edge: UnifiedLineageEdge;
  allNodes: UnifiedLineageNode[];
  onClose: () => void;
}

export function EdgeDetailPanel({ edge, allNodes, onClose }: EdgeDetailPanelProps) {
  const sourceNode = allNodes.find((n) => n.id === edge.source);
  const targetNode = allNodes.find((n) => n.id === edge.target);

  return (
    <div className="w-80 border-l border-white/[0.06] bg-[#030303] p-4 overflow-y-auto">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-[15px] font-medium text-white">Edge Details</h3>
        <button onClick={onClose} className="p-1 hover:bg-white/[0.05] rounded">
          <svg className="w-4 h-4 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="space-y-4">
        {/* Edge type */}
        <div>
          <label className="text-[11px] text-white/40 uppercase tracking-wide">Type</label>
          <p className="text-[13px] text-white mt-1 capitalize">{edge.edgeType.replace(/_/g, ' ')}</p>
        </div>

        {/* Lineage level */}
        {edge.lineageLevel && (
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Level</label>
            <p className="text-[13px] text-white mt-1 capitalize">{edge.lineageLevel}</p>
          </div>
        )}

        {/* Confidence */}
        {edge.confidence !== undefined && (
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Confidence</label>
            <div className="flex items-center gap-2 mt-1">
              <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${edge.confidence * 100}%`,
                    backgroundColor: getConfidenceColor(edge.confidence),
                  }}
                />
              </div>
              <span className="text-[13px] text-white">
                {Math.round(edge.confidence * 100)}%
              </span>
            </div>
          </div>
        )}

        {/* Source -> Target */}
        <div className="grid grid-cols-1 gap-2">
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Source</label>
            <p className="text-[12px] text-white font-mono mt-1 break-all">
              {sourceNode?.fullName || sourceNode?.name || edge.source}
            </p>
          </div>
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Target</label>
            <p className="text-[12px] text-white font-mono mt-1 break-all">
              {targetNode?.fullName || targetNode?.name || edge.target}
            </p>
          </div>
        </div>

        {/* Column mappings — fixed: handle both string and {from,to} formats */}
        {edge.columns && edge.columns.length > 0 && (
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide">Columns</label>
            <div className="mt-1 space-y-1">
              {edge.columns.map((col, i) => (
                <span
                  key={i}
                  className="inline-block px-2 py-0.5 text-[11px] bg-white/5 text-white/60 rounded font-mono mr-1"
                >
                  {formatColumnMapping(col)}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Evidence records */}
        {edge.evidence && edge.evidence.length > 0 && (
          <div>
            <label className="text-[11px] text-white/40 uppercase tracking-wide mb-2 block">
              Evidence ({edge.evidence.length})
            </label>
            <div className="space-y-2">
              {edge.evidence.map((ev, i) => (
                <div key={i} className="p-2.5 rounded-lg bg-white/[0.03] border border-white/[0.06]">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] text-violet-400 font-medium">{ev.adapterId}</span>
                    {ev.observedAt && (
                      <span className="text-[10px] text-white/30">
                        {new Date(ev.observedAt).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-white/60 font-mono break-all">{ev.sourceRef}</p>
                  {ev.snippet && (
                    <pre className="mt-1.5 p-2 text-[10px] text-white/50 bg-black/30 rounded overflow-x-auto">
                      {ev.snippet}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* No evidence fallback */}
        {(!edge.evidence || edge.evidence.length === 0) && (
          <div className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
            <p className="text-[12px] text-white/40">
              No evidence metadata available for this edge.
              {!edge.confidence && ' Engine graph not connected.'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
