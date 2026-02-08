'use client';

import { useState } from 'react';
import type { ChangePlan, ChangePlanStatus, ValidationLevel } from '@/types/change-plan';
import { FilePatchViewer } from './FilePatchViewer';
import { ValidationStatus } from './ValidationStatus';
import { ImpactAnalysisBadge } from './ImpactAnalysisBadge';

interface ChangePlanCardProps {
  plan: ChangePlan;
  onValidate?: (planId: string, level: ValidationLevel) => void;
  onApply?: (planId: string) => void;
  defaultExpanded?: boolean;
}

const STATUS_CONFIG: Record<ChangePlanStatus, { label: string; color: string; bg: string }> = {
  draft: { label: 'Draft', color: '#9ca3af', bg: 'rgba(156, 163, 175, 0.2)' },
  validating: { label: 'Validating', color: '#fbbf24', bg: 'rgba(251, 191, 36, 0.2)' },
  validated: { label: 'Validated', color: '#34d399', bg: 'rgba(52, 211, 153, 0.2)' },
  applying: { label: 'Applying', color: '#60a5fa', bg: 'rgba(96, 165, 250, 0.2)' },
  applied: { label: 'Applied', color: '#60a5fa', bg: 'rgba(96, 165, 250, 0.2)' },
  failed: { label: 'Failed', color: '#f87171', bg: 'rgba(248, 113, 113, 0.2)' },
  rejected: { label: 'Rejected', color: '#f87171', bg: 'rgba(248, 113, 113, 0.2)' },
};

export function ChangePlanCard({ plan, onValidate, onApply, defaultExpanded = true }: ChangePlanCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [showValidateMenu, setShowValidateMenu] = useState(false);

  const statusConfig = STATUS_CONFIG[plan.status];
  const canValidate = plan.status === 'draft' || plan.status === 'failed';
  const canApply = plan.status === 'validated';

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        backgroundColor: 'rgba(26, 26, 36, 0.8)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
      }}
    >
      {/* Header */}
      <div
        className="px-4 py-3 cursor-pointer hover:bg-white/[0.02] transition-colors"
        onClick={() => setExpanded(!expanded)}
        style={{ borderBottom: expanded ? '1px solid rgba(255, 255, 255, 0.06)' : 'none' }}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <svg className="w-5 h-5 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
                />
              </svg>
              <h3 className="text-sm font-medium text-white/90 truncate">{plan.title}</h3>
              <span
                className="px-2 py-0.5 rounded-full text-[10px] font-medium flex-shrink-0"
                style={{
                  backgroundColor: statusConfig.bg,
                  color: statusConfig.color,
                  border: `1px solid ${statusConfig.color}30`,
                }}
              >
                {statusConfig.label}
              </span>
            </div>

            <div className="flex items-center gap-3 text-xs text-white/50">
              <span className="font-mono">{plan.id}</span>
              <span>{plan.patches.length} file{plan.patches.length !== 1 ? 's' : ''}</span>
              {plan.pr_url && (
                <a
                  href={plan.pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="text-blue-400 hover:underline flex items-center gap-1"
                >
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
                  </svg>
                  PR #{plan.pr_number}
                </a>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {plan.impact_analysis && (
              <ImpactAnalysisBadge impact={plan.impact_analysis} />
            )}
            <svg
              className={`w-4 h-4 text-white/50 transition-transform ${expanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
      </div>

      {/* Expanded Content */}
      {expanded && (
        <div className="p-4 space-y-4">
          {/* Description */}
          {plan.description && (
            <div className="text-sm text-white/70">{plan.description}</div>
          )}

          {/* Root Cause */}
          {plan.root_cause && (
            <div className="text-xs">
              <span className="text-white/40 font-medium block mb-1">Root Cause:</span>
              <p className="text-white/60 bg-white/[0.02] p-2 rounded border border-white/[0.04]">
                {plan.root_cause}
              </p>
            </div>
          )}

          {/* Validation Status */}
          {Object.keys(plan.validations).length > 0 && (
            <div>
              <span className="text-xs text-white/40 font-medium block mb-2">Validations:</span>
              <ValidationStatus validations={plan.validations} />
            </div>
          )}

          {/* Patches */}
          <div>
            <span className="text-xs text-white/40 font-medium block mb-2">Changes:</span>
            <div className="space-y-2">
              {plan.patches.map((patch, i) => (
                <FilePatchViewer key={i} patch={patch} defaultCollapsed={plan.patches.length > 2} />
              ))}
            </div>
          </div>

          {/* Action Buttons */}
          {(canValidate || canApply) && (onValidate || onApply) && (
            <div className="flex items-center gap-2 pt-2 border-t border-white/[0.06]">
              {canValidate && onValidate && (
                <div className="relative">
                  <button
                    onClick={() => setShowValidateMenu(!showValidateMenu)}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.06] hover:bg-white/[0.1] transition-colors text-white/80"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    </svg>
                    Validate
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {showValidateMenu && (
                    <div
                      className="absolute bottom-full mb-1 left-0 w-32 rounded-lg overflow-hidden shadow-lg z-10"
                      style={{
                        backgroundColor: '#1a1a24',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                      }}
                    >
                      {(['static', 'ci', 'sandbox'] as ValidationLevel[]).map((level) => (
                        <button
                          key={level}
                          onClick={() => {
                            onValidate(plan.id, level);
                            setShowValidateMenu(false);
                          }}
                          className="w-full px-3 py-2 text-left text-xs hover:bg-white/[0.04] transition-colors text-white/80 capitalize"
                        >
                          {level}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {canApply && onApply && (
                <button
                  onClick={() => onApply(plan.id)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                  style={{
                    backgroundColor: 'rgba(16, 185, 129, 0.2)',
                    color: '#34d399',
                    border: '1px solid rgba(16, 185, 129, 0.3)',
                  }}
                >
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
                  </svg>
                  Create PR
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
