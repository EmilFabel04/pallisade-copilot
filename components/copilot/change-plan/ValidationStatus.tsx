'use client';

import { useState } from 'react';
import type { ValidationLevel, ValidationResult, ValidationStatus as VStatus } from '@/types/change-plan';

interface ValidationStatusProps {
  validations: Partial<Record<ValidationLevel, ValidationResult>>;
  compact?: boolean;
  onRunValidation?: (level: ValidationLevel) => void;
}

const LEVELS: ValidationLevel[] = ['static', 'ci', 'sandbox'];

const STATUS_CONFIG: Record<VStatus, { icon: React.ReactNode; color: string; label: string }> = {
  passed: {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
      </svg>
    ),
    color: '#34d399',
    label: 'Passed',
  },
  failed: {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
      </svg>
    ),
    color: '#f87171',
    label: 'Failed',
  },
  running: {
    icon: (
      <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
        />
      </svg>
    ),
    color: '#fbbf24',
    label: 'Running',
  },
  pending: {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
    ),
    color: '#9ca3af',
    label: 'Pending',
  },
  skipped: {
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
      </svg>
    ),
    color: '#6b7280',
    label: 'Skipped',
  },
};

const LEVEL_LABELS: Record<ValidationLevel, string> = {
  static: 'Static',
  ci: 'CI',
  sandbox: 'Sandbox',
};

export function ValidationStatus({ validations, compact = false, onRunValidation }: ValidationStatusProps) {
  const [expandedLevel, setExpandedLevel] = useState<ValidationLevel | null>(null);

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        {LEVELS.map((level) => {
          const result = validations[level];
          const status = result?.status || 'pending';
          const config = STATUS_CONFIG[status];

          return (
            <div
              key={level}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs"
              style={{ color: config.color }}
              title={`${LEVEL_LABELS[level]}: ${config.label}`}
            >
              {config.icon}
              <span className="hidden sm:inline">{LEVEL_LABELS[level]}</span>
            </div>
          );
        })}
      </div>
    );
  }

  const handleClick = (level: ValidationLevel) => {
    const result = validations[level];
    const status = result?.status || 'pending';

    // If pending and we have a callback, run validation
    if (status === 'pending' && onRunValidation) {
      onRunValidation(level);
      return;
    }

    // Otherwise toggle expanded view
    setExpandedLevel(expandedLevel === level ? null : level);
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2">
        {LEVELS.map((level) => {
          const result = validations[level];
          const status = result?.status || 'pending';
          const config = STATUS_CONFIG[status];
          const hasDetails = result && (result.errors.length > 0 || result.warnings.length > 0);
          const hasResult = result && result.status !== 'pending';
          const canClick = hasDetails || hasResult || (status === 'pending' && onRunValidation);

          return (
            <button
              key={level}
              onClick={() => handleClick(level)}
              disabled={!canClick}
              className={`
                flex flex-col items-center gap-1 p-2 rounded-lg transition-all
                ${canClick ? 'cursor-pointer hover:bg-white/[0.04]' : 'cursor-default opacity-60'}
              `}
              style={{
                backgroundColor: 'rgba(255, 255, 255, 0.02)',
                border: `1px solid ${expandedLevel === level ? config.color : 'rgba(255, 255, 255, 0.06)'}`,
              }}
              title={status === 'pending' && onRunValidation ? `Click to run ${level} validation` : undefined}
            >
              <div style={{ color: config.color }}>{config.icon}</div>
              <span className="text-xs font-medium text-white/80">{LEVEL_LABELS[level]}</span>
              <span className="text-[10px]" style={{ color: config.color }}>
                {config.label}
              </span>
              {hasDetails && (
                <div className="flex gap-1 text-[10px]">
                  {result.errors.length > 0 && (
                    <span className="text-red-400">{result.errors.length} errors</span>
                  )}
                  {result.warnings.length > 0 && (
                    <span className="text-yellow-400">{result.warnings.length} warnings</span>
                  )}
                </div>
              )}
              {status === 'pending' && onRunValidation && (
                <span className="text-[9px] text-white/40">Click to run</span>
              )}
            </button>
          );
        })}
      </div>

      {expandedLevel && validations[expandedLevel] && (
        <div
          className="p-3 rounded-lg text-xs space-y-2"
          style={{
            backgroundColor: 'rgba(255, 255, 255, 0.02)',
            border: '1px solid rgba(255, 255, 255, 0.06)',
          }}
        >
          {/* Show status summary */}
          {validations[expandedLevel]!.errors.length === 0 &&
            validations[expandedLevel]!.warnings.length === 0 &&
            validations[expandedLevel]!.status === 'passed' && (
              <div className="flex items-center gap-2 text-emerald-400">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                <span>All checks passed</span>
              </div>
            )}

          {validations[expandedLevel]!.errors.length > 0 && (
            <div>
              <span className="text-red-400 font-medium block mb-1">Errors:</span>
              <ul className="space-y-1">
                {validations[expandedLevel]!.errors.map((error, i) => (
                  <li key={i} className="text-white/70 pl-2 border-l-2 border-red-400/30">
                    {error}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {validations[expandedLevel]!.warnings.length > 0 && (
            <div>
              <span className="text-yellow-400 font-medium block mb-1">Warnings:</span>
              <ul className="space-y-1">
                {validations[expandedLevel]!.warnings.map((warning, i) => (
                  <li key={i} className="text-white/70 pl-2 border-l-2 border-yellow-400/30">
                    {warning}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {validations[expandedLevel]!.duration_seconds && (
            <div className="text-white/50">
              Duration: {validations[expandedLevel]!.duration_seconds.toFixed(2)}s
            </div>
          )}
        </div>
      )}
    </div>
  );
}
