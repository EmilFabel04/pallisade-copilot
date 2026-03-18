'use client';

import React from 'react';
import type { PolicyStatus } from '@/types/policy';

interface PolicyModeToolbarProps {
  selectedCount: number;
  totalNodes: number;
  onSaveAll: () => void;
  onExit: () => void;
  saving?: boolean;
}

export function PolicyModeToolbar({
  selectedCount,
  totalNodes,
  onSaveAll,
  onExit,
  saving,
}: PolicyModeToolbarProps) {
  return (
    <div className="flex items-center gap-4 mt-4 pt-4 border-t border-violet-500/20">
      {/* Mode indicator */}
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 bg-violet-400 rounded-full animate-pulse" />
        <span className="text-[13px] font-medium text-violet-300">Policy Mode</span>
      </div>

      {/* Selection counter */}
      <div className="text-[12px] text-[var(--muted)]">
        {selectedCount > 0 ? (
          <span className="text-violet-300 font-medium">{selectedCount}</span>
        ) : (
          <span>0</span>
        )}
        {' of '}
        {totalNodes} nodes selected
      </div>

      {/* Badge legend */}
      <div className="flex items-center gap-3 ml-auto text-[11px] text-[var(--muted)]">
        <span className="flex items-center gap-1">
          <svg className="w-3 h-3 text-violet-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          Assigned
        </span>
        <span className="flex items-center gap-1">
          <svg className="w-3 h-3 text-violet-300/60" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          Inherited
        </span>
        <span className="flex items-center gap-1">
          <svg className="w-3 h-3 text-amber-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          Override
        </span>
      </div>

      {/* Actions */}
      <button
        onClick={onSaveAll}
        disabled={saving}
        className="px-3 py-1.5 text-[12px] font-medium rounded-lg bg-violet-500/20 text-violet-300 hover:bg-violet-500/30 border border-violet-500/30 transition-all disabled:opacity-50"
      >
        {saving ? 'Saving...' : 'Save All'}
      </button>
      <button
        onClick={onExit}
        className="px-3 py-1.5 text-[12px] font-medium rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-all flex items-center gap-1"
      >
        Exit Policy Mode
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
