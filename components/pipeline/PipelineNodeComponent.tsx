'use client';

/**
 * Pipeline Node Component
 * 
 * Custom React Flow node - n8n style blocks
 */

import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { PipelineNode, ToolDefinition, LAYER_COLORS, STATUS_COLORS, PipelineLayer } from './types';

interface PipelineNodeData extends PipelineNode {
  tool?: ToolDefinition;
  onConfigure: () => void;
  onDelete: () => void;
}

function PipelineNodeComponent({ data, selected }: NodeProps<PipelineNodeData>) {
  const layerColor = LAYER_COLORS[data.layer] || '#6366f1';
  const statusColor = STATUS_COLORS[data.status] || '#6B7280';

  return (
    <div
      className={`
        pipeline-node
        min-w-[220px] rounded-xl overflow-hidden
        bg-[var(--surface-inset)] border-2 transition-all duration-200
        ${selected ? 'shadow-2xl scale-[1.02]' : 'shadow-xl'}
        hover:shadow-2xl
      `}
      style={{
        borderColor: selected ? layerColor : 'var(--border-medium)',
        boxShadow: selected ? `0 0 30px ${layerColor}30` : undefined,
      }}
    >
      {/* Input Handle (Left) - except for Ingestion */}
      {data.layer !== 'INGESTION' && (
        <Handle
          type="target"
          position={Position.Left}
          className="!w-4 !h-4 !-left-2 !border-2 !border-[var(--surface-inset)] !rounded-full"
          style={{ backgroundColor: layerColor }}
        />
      )}

      {/* Header */}
      <div
        className="px-4 py-3 flex items-center gap-3"
        style={{ backgroundColor: `${layerColor}15` }}
      >
        {/* Tool Icon Circle */}
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center text-lg font-bold"
          style={{ backgroundColor: `${layerColor}25`, color: layerColor }}
        >
          {data.name.charAt(0).toUpperCase()}
        </div>
        
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm text-[var(--text)] truncate">{data.name}</div>
          <div className="text-[10px] text-[var(--muted)] uppercase tracking-wider mt-0.5">
            {data.layer}
          </div>
        </div>
        
        {/* Status Dot */}
        <div
          className={`w-3 h-3 rounded-full ${data.status === 'TESTING' ? 'animate-pulse' : ''}`}
          style={{ backgroundColor: statusColor }}
          title={data.status}
        />
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3 border-t border-[var(--subtle-border)]">
        {/* Config Status */}
        {!data.config ? (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <svg className="w-4 h-4 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span className="text-xs text-amber-400">Click to configure</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <svg className="w-4 h-4 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <span className="text-xs text-emerald-400">Connected</span>
          </div>
        )}

        {/* Health Score */}
        {data.healthScore !== null && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-[var(--muted)]">Health</span>
              <span className={`font-semibold ${
                data.healthScore >= 80 ? 'text-emerald-400' :
                data.healthScore >= 60 ? 'text-amber-400' : 'text-red-400'
              }`}>
                {data.healthScore.toFixed(0)}%
              </span>
            </div>
            <div className="h-1.5 bg-[var(--subtle-border)] rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${data.healthScore}%`,
                  backgroundColor: 
                    data.healthScore >= 80 ? '#10B981' :
                    data.healthScore >= 60 ? '#F59E0B' : '#EF4444',
                }}
              />
            </div>
          </div>
        )}

        {/* Findings */}
        {data.findingsCount > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            {data.criticalCount > 0 && (
              <span className="px-2 py-0.5 rounded bg-red-500/20 text-red-400 text-xs font-medium">
                {data.criticalCount} critical
              </span>
            )}
            {data.highCount > 0 && (
              <span className="px-2 py-0.5 rounded bg-orange-500/20 text-orange-400 text-xs font-medium">
                {data.highCount} high
              </span>
            )}
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onConfigure();
            }}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-[var(--subtle-bg)] hover:bg-[var(--overlay-medium)] text-[var(--text)] border border-[var(--border-medium)] hover:border-[var(--overlay-strong)] transition-all"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            {data.config ? 'Settings' : 'Configure'}
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete();
            }}
            className="p-2 rounded-lg bg-[var(--subtle-bg)] hover:bg-red-500/20 text-[var(--muted)] hover:text-red-400 border border-[var(--border-medium)] hover:border-red-500/30 transition-all"
            title="Remove"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {/* Output Handle (Right) - except for Reporting */}
      {data.layer !== 'REPORTING' && (
        <Handle
          type="source"
          position={Position.Right}
          className="!w-4 !h-4 !-right-2 !border-2 !border-[var(--surface-inset)] !rounded-full"
          style={{ backgroundColor: layerColor }}
        />
      )}

      {/* Layer Badge */}
      <div
        className="absolute -top-px -right-px px-2 py-0.5 text-[9px] font-bold rounded-bl-lg text-white uppercase tracking-wider"
        style={{ backgroundColor: layerColor }}
      >
        {data.layer.slice(0, 3)}
      </div>
    </div>
  );
}

export default memo(PipelineNodeComponent);
