'use client';

import React from 'react';

interface SLAModeToolbarProps {
  selectedCount: number;
  totalNodes: number;
  onExit: () => void;
}

export function SLAModeToolbar({
  selectedCount,
  totalNodes,
  onExit,
}: SLAModeToolbarProps) {
  return (
    <div className="flex items-center gap-4 mt-4 pt-4 border-t border-slate-500/20">
      {/* Mode indicator */}
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 bg-[var(--accent)] rounded-full animate-pulse" />
        <span className="text-[13px] font-medium" style={{ color: 'var(--text)' }}>Data SLA Mode</span>
      </div>

      {/* Selection counter */}
      <div className="text-[12px] text-[var(--muted)]">
        {selectedCount > 0 ? (
          <span className="font-medium" style={{ color: 'var(--text)' }}>{selectedCount}</span>
        ) : (
          <span>0</span>
        )}
        {' of '}
        {totalNodes} nodes selected
      </div>

      {/* Badge legend — matches the profile name badges on nodes */}
      <div className="flex items-center gap-3 ml-auto text-[11px]">
        <span className="flex items-center gap-1.5">
          <span className="inline-block px-1.5 py-0.5 rounded-sm text-[8px] font-semibold uppercase" style={{ background: 'var(--subtle-bg)', color: 'var(--muted)', border: '1px solid var(--subtle-border)' }}>Profile</span>
          <span style={{ color: 'var(--text-secondary)' }}>= Data SLA assigned</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full" style={{ background: 'var(--text-faint)', border: '1px dashed var(--muted)' }} />
          <span style={{ color: 'var(--text-secondary)' }}>= no Data SLA</span>
        </span>
      </div>

      {/* Actions */}
      <button
        onClick={onExit}
        className="px-3 py-1.5 text-[12px] font-medium rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-all flex items-center gap-1"
      >
        Exit Data SLA Mode
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
