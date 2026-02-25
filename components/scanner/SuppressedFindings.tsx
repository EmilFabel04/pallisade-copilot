'use client';

import { useState } from 'react';
import { FindingCard } from './FindingCard';

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
  suppressed?: boolean;
  suppressionReason?: string;
  suppressionSource?: string;
  originalSeverity?: string;
}

interface SuppressedFindingsProps {
  findings: Finding[];
  onApproveSuppression: (finding: Finding) => Promise<void>;
  onDenySuppression: (finding: Finding) => Promise<void>;
}

// Group suppressed findings by suppression source
function groupBySuppression(findings: Finding[]): Record<string, Finding[]> {
  const groups: Record<string, Finding[]> = {};
  
  for (const finding of findings) {
    const source = finding.suppressionSource || 'unknown';
    if (!groups[source]) {
      groups[source] = [];
    }
    groups[source].push(finding);
  }
  
  return groups;
}

const sourceLabels: Record<string, { label: string; description: string; icon: JSX.Element }> = {
  semantic_classification: {
    label: 'ML Classification',
    description: 'Suppressed because the LLM classified this column type as naturally high-variance',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  correlation: {
    label: 'Correlation Analysis',
    description: 'Suppressed because outliers are explained by correlation with other columns',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
      </svg>
    ),
  },
  baseline: {
    label: 'Historical Baseline',
    description: 'Suppressed because this pattern matches historical behavior',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  unknown: {
    label: 'Other',
    description: 'Suppressed by scanner logic',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
};

export function SuppressedFindings({
  findings,
  onApproveSuppression,
  onDenySuppression,
}: SuppressedFindingsProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  if (findings.length === 0) {
    return null;
  }

  const groupedFindings = groupBySuppression(findings);
  const groupKeys = Object.keys(groupedFindings).sort();

  const toggleGroup = (source: string) => {
    const newExpanded = new Set(expandedGroups);
    if (newExpanded.has(source)) {
      newExpanded.delete(source);
    } else {
      newExpanded.add(source);
    }
    setExpandedGroups(newExpanded);
  };

  return (
    <div className="rounded-lg border border-purple-500/30 bg-purple-500/5 overflow-hidden">
      {/* Header - Click to expand */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full p-4 flex items-center justify-between hover:bg-purple-500/10 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-purple-500/20">
            <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
            </svg>
          </div>
          <div className="text-left">
            <h3 className="text-sm font-medium text-[var(--text)]">
              Suppressed Findings ({findings.length})
            </h3>
            <p className="text-xs text-[var(--muted)]">
              Issues filtered by ML/baseline that you can review and override
            </p>
          </div>
        </div>
        <svg 
          className={`w-5 h-5 text-purple-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none" 
          stroke="currentColor" 
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="border-t border-purple-500/20">
          {/* Summary by source */}
          <div className="p-4 bg-[var(--overlay-faint)]">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {groupKeys.map((source) => {
                const info = sourceLabels[source] || sourceLabels.unknown;
                const count = groupedFindings[source].length;
                return (
                  <div 
                    key={source}
                    className="bg-[var(--overlay-bg)] rounded-lg p-2 flex items-center gap-2"
                  >
                    <div className="text-purple-400">
                      {info.icon}
                    </div>
                    <div>
                      <p className="text-xs text-[var(--muted)]">{info.label}</p>
                      <p className="text-sm text-[var(--text)] font-medium">{count}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Grouped findings */}
          <div className="divide-y divide-purple-500/20">
            {groupKeys.map((source) => {
              const info = sourceLabels[source] || sourceLabels.unknown;
              const sourceFindings = groupedFindings[source];
              const isGroupExpanded = expandedGroups.has(source);

              return (
                <div key={source}>
                  {/* Group header */}
                  <button
                    onClick={() => toggleGroup(source)}
                    className="w-full p-3 flex items-center justify-between hover:bg-[var(--subtle-bg)] transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <div className="text-purple-400">{info.icon}</div>
                      <div className="text-left">
                        <span className="text-sm text-[var(--text)] font-medium">{info.label}</span>
                        <span className="text-xs text-[var(--muted)] ml-2">
                          ({sourceFindings.length} {sourceFindings.length === 1 ? 'finding' : 'findings'})
                        </span>
                      </div>
                    </div>
                    <svg 
                      className={`w-4 h-4 text-[var(--muted)] transition-transform ${isGroupExpanded ? 'rotate-180' : ''}`}
                      fill="none" 
                      stroke="currentColor" 
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {/* Group description */}
                  {isGroupExpanded && (
                    <div className="px-4 pb-2">
                      <p className="text-xs text-[var(--muted)]">{info.description}</p>
                    </div>
                  )}

                  {/* Findings list */}
                  {isGroupExpanded && (
                    <div className="px-4 pb-4 space-y-3">
                      {sourceFindings.map((finding) => (
                        <FindingCard
                          key={finding.id}
                          finding={finding}
                          showExplanation={false}
                          isSuppressedView={true}
                          onApproveSuppression={async (f) => {
                            await onApproveSuppression(f);
                          }}
                          onDenySuppression={async (f) => {
                            await onDenySuppression(f);
                          }}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Help text */}
          <div className="p-4 bg-[var(--overlay-faint)] border-t border-purple-500/20">
            <div className="flex items-start gap-2">
              <svg className="w-4 h-4 text-purple-400 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-xs text-[var(--muted)]">
                <strong className="text-purple-400">Tip:</strong> Click "Confirm Suppression" to approve the ML's decision, 
                or "This is a Real Alert" if you think this should be flagged. Your feedback helps improve future scans.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
