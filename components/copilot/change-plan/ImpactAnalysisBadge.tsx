'use client';

import { useState } from 'react';
import type { ImpactAnalysis } from '@/types/change-plan';

interface ImpactAnalysisBadgeProps {
  impact: ImpactAnalysis;
  showDetails?: boolean;
}

const RISK_COLORS = {
  LOW: { bg: 'rgba(16, 185, 129, 0.2)', text: '#34d399', border: 'rgba(16, 185, 129, 0.3)' },
  MEDIUM: { bg: 'rgba(234, 179, 8, 0.2)', text: '#fbbf24', border: 'rgba(234, 179, 8, 0.3)' },
  HIGH: { bg: 'rgba(239, 68, 68, 0.2)', text: '#f87171', border: 'rgba(239, 68, 68, 0.3)' },
};

export function ImpactAnalysisBadge({ impact, showDetails = false }: ImpactAnalysisBadgeProps) {
  const [expanded, setExpanded] = useState(showDetails);
  const colors = RISK_COLORS[impact.risk_level];

  return (
    <div className="inline-flex flex-col">
      <button
        onClick={() => setExpanded(!expanded)}
        className="inline-flex items-center gap-2 px-2 py-1 rounded-md text-xs transition-colors hover:opacity-80"
        style={{
          backgroundColor: colors.bg,
          color: colors.text,
          border: `1px solid ${colors.border}`,
        }}
      >
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
          />
        </svg>
        <span className="font-medium">{impact.risk_level} Risk</span>
        {impact.affected_tables.length > 0 && (
          <span className="opacity-70">
            {impact.affected_tables.length} table{impact.affected_tables.length !== 1 ? 's' : ''}
          </span>
        )}
        <svg
          className={`w-3 h-3 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div
          className="mt-2 p-3 rounded-lg text-xs space-y-2"
          style={{
            backgroundColor: 'rgba(255, 255, 255, 0.02)',
            border: '1px solid rgba(255, 255, 255, 0.06)',
          }}
        >
          {impact.affected_tables.length > 0 && (
            <div>
              <span className="text-white/50 block mb-1">Affected Tables:</span>
              <div className="flex flex-wrap gap-1">
                {impact.affected_tables.map((table) => (
                  <span
                    key={table}
                    className="px-1.5 py-0.5 rounded bg-white/[0.06] text-white/80 font-mono"
                  >
                    {table}
                  </span>
                ))}
              </div>
            </div>
          )}

          {impact.downstream_dependencies.length > 0 && (
            <div>
              <span className="text-white/50 block mb-1">Downstream:</span>
              <div className="flex flex-wrap gap-1">
                {impact.downstream_dependencies.map((dep) => (
                  <span
                    key={dep}
                    className="px-1.5 py-0.5 rounded bg-white/[0.06] text-white/80 font-mono"
                  >
                    {dep}
                  </span>
                ))}
              </div>
            </div>
          )}

          {impact.expected_data_changes && (
            <div>
              <span className="text-white/50 block mb-1">Expected Changes:</span>
              <p className="text-white/70">{impact.expected_data_changes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
