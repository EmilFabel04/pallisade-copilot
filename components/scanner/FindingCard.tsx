'use client';

import { useState } from 'react';
import { NLPExplanation } from './NLPExplanation';

interface Finding {
  id: string;
  title: string;
  description: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  category: string;
  table?: string;
  column?: string;
  hasAutoFix?: boolean;
  autoFix?: {
    type: string;
    code: string;
    description?: string;
  };
  aiContext?: Record<string, any>;
  // Suppression fields
  suppressed?: boolean;
  suppressionReason?: string;
  suppressionSource?: string;
  originalSeverity?: string;
}

interface FindingCardProps {
  finding: Finding;
  showExplanation?: boolean;
  onApplyFix?: (finding: Finding) => void;
  onDismiss?: (finding: Finding) => void;
  onApproveSuppression?: (finding: Finding) => void;
  onDenySuppression?: (finding: Finding) => void;
  isSuppressedView?: boolean; // True when shown in suppressed findings dropdown
}

const severityConfig = {
  critical: {
    bg: 'bg-red-500/10',
    border: 'border-red-500/30',
    text: 'text-red-400',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    ),
  },
  high: {
    bg: 'bg-orange-500/10',
    border: 'border-orange-500/30',
    text: 'text-orange-400',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  medium: {
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    text: 'text-amber-400',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  low: {
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
    text: 'text-blue-400',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  info: {
    bg: 'bg-[var(--subtle-bg)]',
    border: 'border-[var(--subtle-border)]',
    text: 'text-[var(--muted)]',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
};

// Suppression source labels for display
const suppressionSourceLabels: Record<string, string> = {
  semantic_classification: 'ML Classification',
  correlation: 'Correlation Analysis',
  baseline: 'Historical Baseline',
  user_override: 'User Override',
};

export function FindingCard({
  finding,
  showExplanation = true,
  onApplyFix,
  onDismiss,
  onApproveSuppression,
  onDenySuppression,
  isSuppressedView = false,
}: FindingCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showNLP, setShowNLP] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Use original severity for styling if this is a suppressed finding
  const displaySeverity = finding.suppressed && finding.originalSeverity 
    ? finding.originalSeverity as keyof typeof severityConfig 
    : finding.severity;
  const config = severityConfig[displaySeverity] || severityConfig.low;

  const handleCopyFix = () => {
    if (finding.autoFix?.code) {
      navigator.clipboard.writeText(finding.autoFix.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className={`rounded-lg border ${config.border} ${config.bg} overflow-hidden`}>
      {/* Header */}
      <div 
        className="p-4 cursor-pointer hover:bg-[var(--overlay-faint)] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-start gap-3">
          {/* Severity icon */}
          <div className={config.text}>
            {config.icon}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-medium text-[var(--text)]">{finding.title}</h3>
              <span className={`px-1.5 py-0.5 text-xs rounded ${config.text} ${config.bg} border ${config.border}`}>
                {displaySeverity}
              </span>
              {finding.suppressed && (
                <span className="px-1.5 py-0.5 text-xs rounded bg-purple-500/20 text-purple-400 border border-purple-500/30 flex items-center gap-1">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                  </svg>
                  Suppressed
                </span>
              )}
              {finding.hasAutoFix && !finding.suppressed && (
                <span className="px-1.5 py-0.5 text-xs rounded bg-green-500/20 text-green-400 border border-green-500/30">
                  Auto-fix
                </span>
              )}
            </div>
            
            <p className="text-sm text-[var(--muted)] mt-1 line-clamp-2">
              {finding.description}
            </p>

            {/* Table/Column info */}
            {(finding.table || finding.column) && (
              <div className="flex items-center gap-2 mt-2 text-xs text-[var(--muted)]">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                </svg>
                <span className="font-mono">
                  {finding.table}
                  {finding.column && <span className="text-[var(--accent)]">.{finding.column}</span>}
                </span>
              </div>
            )}
          </div>

          {/* Expand indicator */}
          <svg 
            className={`w-5 h-5 text-[var(--muted)] transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none" 
            stroke="currentColor" 
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-[var(--border-dim)] bg-[var(--overlay-faint)]">
          {/* Suppression Reason (for suppressed findings) */}
          {finding.suppressed && finding.suppressionReason && (
            <div className="p-4 border-b border-[var(--border-dim)] bg-purple-500/5">
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-lg bg-purple-500/10">
                  <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                </div>
                <div className="flex-1">
                  <h4 className="text-xs font-medium text-purple-400 uppercase tracking-wider mb-1">
                    Why This Was Suppressed
                  </h4>
                  <p className="text-sm text-[var(--muted)]">{finding.suppressionReason}</p>
                  {finding.suppressionSource && (
                    <p className="text-xs text-purple-400 mt-2">
                      Source: {suppressionSourceLabels[finding.suppressionSource] || finding.suppressionSource}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* AI Context */}
          {finding.aiContext && Object.keys(finding.aiContext).length > 0 && (
            <div className="p-4 border-b border-[var(--border-dim)]">
              <h4 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider mb-2">
                Context
              </h4>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {Object.entries(finding.aiContext).slice(0, 6).map(([key, value]) => (
                  <div key={key} className="bg-[var(--overlay-faint)] rounded p-2">
                    <p className="text-xs text-[var(--muted)]">{key.replace(/_/g, ' ')}</p>
                    <p className="text-sm text-[var(--text)] font-medium truncate">
                      {typeof value === 'number' ? value.toLocaleString() : String(value)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Auto-fix code */}
          {finding.hasAutoFix && finding.autoFix && (
            <div className="p-4 border-b border-[var(--border-dim)]">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider">
                  Auto-Fix: {finding.autoFix.type}
                </h4>
                <button
                  onClick={handleCopyFix}
                  className="text-xs text-[var(--accent)] hover:text-[var(--text)] transition-colors flex items-center gap-1"
                >
                  {copied ? (
                    <>
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      Copied!
                    </>
                  ) : (
                    <>
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                      Copy
                    </>
                  )}
                </button>
              </div>
              {finding.autoFix.description && (
                <p className="text-xs text-[var(--muted)] mb-2">{finding.autoFix.description}</p>
              )}
              <pre className="bg-[var(--overlay-bg)] rounded-lg p-3 overflow-x-auto text-xs text-green-400 font-mono">
                {finding.autoFix.code}
              </pre>
            </div>
          )}

          {/* NLP Explanation toggle */}
          {showExplanation && (
            <div className="p-4 border-b border-[var(--border-dim)]">
              <button
                onClick={() => setShowNLP(!showNLP)}
                className="flex items-center gap-2 text-sm text-[var(--accent)] hover:text-[var(--text)] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
                {showNLP ? 'Hide Explanation' : 'Explain This Issue'}
              </button>
              
              {showNLP && (
                <div className="mt-3">
                  <NLPExplanation finding={finding} />
                </div>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="p-4 flex items-center gap-2 flex-wrap">
            {/* Suppression feedback actions (for suppressed findings) */}
            {finding.suppressed && isSuppressedView && (
              <>
                {onApproveSuppression && (
                  <button
                    onClick={() => {
                      setIsSubmitting(true);
                      onApproveSuppression(finding);
                      setTimeout(() => setIsSubmitting(false), 1000);
                    }}
                    disabled={isSubmitting}
                    className="px-3 py-1.5 bg-green-500/20 text-green-400 text-sm rounded hover:bg-green-500/30 transition-colors flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    Confirm Suppression
                  </button>
                )}
                {onDenySuppression && (
                  <button
                    onClick={() => {
                      setIsSubmitting(true);
                      onDenySuppression(finding);
                      setTimeout(() => setIsSubmitting(false), 1000);
                    }}
                    disabled={isSubmitting}
                    className="px-3 py-1.5 bg-red-500/20 text-red-400 text-sm rounded hover:bg-red-500/30 transition-colors flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    This is a Real Alert
                  </button>
                )}
              </>
            )}

            {/* Regular finding actions */}
            {!finding.suppressed && finding.hasAutoFix && onApplyFix && (
              <button
                onClick={() => onApplyFix(finding)}
                className="px-3 py-1.5 bg-green-500/20 text-green-400 text-sm rounded hover:bg-green-500/30 transition-colors flex items-center gap-1.5"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Apply Fix
              </button>
            )}
            
            {!finding.suppressed && onDismiss && (
              <button
                onClick={() => onDismiss(finding)}
                className="px-3 py-1.5 bg-[var(--subtle-bg)] text-[var(--muted)] text-sm rounded hover:bg-[var(--overlay-medium)] hover:text-[var(--text)] transition-colors"
              >
                Dismiss
              </button>
            )}
            
            <button className="px-3 py-1.5 text-[var(--muted)] text-sm hover:text-[var(--text)] transition-colors ml-auto">
              View in Table →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

