'use client';

import { Fragment, useState } from 'react';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import type { TaskRun } from '@/types/schedule';
import { RUN_STATUS_COLORS } from '@/types/schedule';

interface RunHistoryTableProps {
  runs: TaskRun[];
  loading?: boolean;
  taskName?: string;
  monitorType?: string;
  targetFqn?: string;
}

const STATUS_BORDER_COLORS: Record<string, string> = {
  PASS: 'border-l-emerald-500/60',
  WARN: 'border-l-amber-500/60',
  FAIL: 'border-l-red-500/60',
  ERROR: 'border-l-red-400/60',
  SKIPPED: 'border-l-white/20',
  RUNNING: 'border-l-blue-500/60',
};

function formatDuration(ms?: number): string {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(dateStr?: string): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDetailValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(3);
  }
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

// Keys to display first in details, in this order
const DETAIL_KEY_ORDER = [
  'z_score', 'baseline_mean', 'baseline_stddev', 'confidence_pct',
  'baseline_count', 'column', 'metric', 'data_points',
  'timestamp_column', 'last_value', 'total_rows', 'warn_hours',
  'anomaly_ready', 'original_lookback_days', 'actual_lookback_days',
];

function sortDetailKeys(keys: string[]): string[] {
  const ordered: string[] = [];
  for (const k of DETAIL_KEY_ORDER) {
    if (keys.includes(k)) ordered.push(k);
  }
  for (const k of keys) {
    if (!ordered.includes(k) && !k.startsWith('_')) ordered.push(k);
  }
  return ordered;
}

function navigateToScout(
  router: ReturnType<typeof useRouter>,
  promptType: 'explain' | 'verify' | 'investigate',
  run: TaskRun,
  taskName?: string,
  monitorType?: string,
  targetFqn?: string,
) {
  const target = targetFqn || 'unknown table';
  const type = monitorType || 'monitor';
  const name = taskName || 'Monitor Task';

  let prompt: string;
  let display: string;
  switch (promptType) {
    case 'explain':
      prompt = `I have a ${type} monitor result on ${target} that returned ${run.status}. Using ONLY the monitor run data provided below, explain what happened, whether this is expected, and what it means for data quality. Do NOT query the warehouse or run additional checks — everything you need is in the context.`;
      display = `Explain the ${type} result on ${target} (${run.status})`;
      break;
    case 'verify':
      prompt = `I have a ${run.status} alert from the ${type} monitor on ${target}. Using ONLY the monitor run data provided below, determine if this is a true positive or a false positive. Explain your reasoning based on the z-score, baseline stats, and confidence. Do NOT re-run the monitor or query the warehouse.`;
      display = `Verify whether the ${run.status} alert on ${target} is a true positive`;
      break;
    case 'investigate':
      prompt = `/debug Using the monitor run data provided below, investigate the root cause of the ${run.status} result on ${target}. Focus on the specific values, thresholds, and any anomalies in the details. You may query the warehouse to compare current vs historical data if needed.`;
      display = `Investigate the ${run.status} result on ${target} from the ${type} monitor`;
      break;
  }

  // Build rich context with full run data
  const details = run.details || {};
  const { llm_validation, ...cleanDetails } = details;

  const context = JSON.stringify({
    taskName: name,
    monitorType: type,
    targetFqn: target,
    status: run.status,
    value: run.value,
    threshold: run.threshold,
    message: run.message,
    details: cleanDetails,
    sqlExecuted: run.sqlExecuted ? run.sqlExecuted.slice(0, 500) : undefined,
    llmValidation: llm_validation || undefined,
    startedAt: run.startedAt,
    durationMs: run.durationMs,
  });

  // Store in sessionStorage — survives React remounts unlike URL params
  sessionStorage.setItem('askScoutDeepLink', JSON.stringify({ prompt, context, display }));
  router.push('/dashboard/assistant');
}

export function RunHistoryTable({ runs, loading, taskName, monitorType, targetFqn }: RunHistoryTableProps) {
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const router = useRouter();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-5 h-5 border-2 border-white/20 border-t-white/60 rounded-full animate-spin" />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-[13px] text-white/30">No runs yet</p>
      </div>
    );
  }

  const toggleExpand = (runId: string) => {
    setExpandedRunId(prev => prev === runId ? null : runId);
  };

  return (
    <div className="overflow-hidden rounded-lg border border-white/[0.06]">
      <table className="w-full">
        <thead>
          <tr className="border-b border-white/[0.06]">
            <th className="w-8 px-2 py-2.5" />
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Status
            </th>
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Time
            </th>
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Value
            </th>
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Duration
            </th>
            <th className="text-left text-[11px] font-medium text-white/40 uppercase tracking-wider px-4 py-2.5">
              Message
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const isExpanded = expandedRunId === run.id;
            const hasDetails = run.details && Object.keys(run.details).length > 0;
            const hasSql = !!run.sqlExecuted;
            const hasLlmValidation = run.details?.llm_validation;

            return (
              <Fragment key={run.id}>
                {/* Main row */}
                <tr
                  onClick={() => toggleExpand(run.id)}
                  className={cn(
                    'border-b border-white/[0.04] last:border-0 cursor-pointer transition-colors',
                    isExpanded ? 'bg-white/[0.03]' : 'hover:bg-white/[0.02]'
                  )}
                >
                  <td className="px-2 py-2.5">
                    <svg
                      className={cn(
                        'w-3.5 h-3.5 text-white/30 transition-transform duration-200',
                        isExpanded && 'rotate-90'
                      )}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={cn(
                        'px-2 py-0.5 rounded text-[11px] font-medium',
                        RUN_STATUS_COLORS[run.status] || 'bg-white/10 text-white/40'
                      )}
                    >
                      {run.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-[12px] text-white/60">
                    {formatTime(run.startedAt)}
                  </td>
                  <td className="px-4 py-2.5 text-[12px] text-white/60 font-mono">
                    {run.value != null ? run.value.toFixed(2) : '-'}
                  </td>
                  <td className="px-4 py-2.5 text-[12px] text-white/40">
                    {formatDuration(run.durationMs)}
                  </td>
                  <td className="px-4 py-2.5 text-[12px] text-white/40 max-w-[300px] truncate">
                    {run.message || '-'}
                  </td>
                </tr>

                {/* Expanded logs panel */}
                {isExpanded && (
                  <tr key={`${run.id}-expanded`}>
                    <td colSpan={6} className="p-0">
                      <div
                        className={cn(
                          'mx-4 mb-3 rounded-lg bg-white/[0.02] border border-white/[0.06] border-l-2 overflow-hidden',
                          STATUS_BORDER_COLORS[run.status] || 'border-l-white/20'
                        )}
                      >
                        <div className="p-4 space-y-4">
                          {/* Message */}
                          {run.message && (
                            <div>
                              <h4 className="text-[11px] font-medium text-white/40 uppercase tracking-wider mb-1.5">
                                Message
                              </h4>
                              <p className="text-[13px] text-white/70 leading-relaxed">
                                {run.message}
                              </p>
                            </div>
                          )}

                          {/* Details */}
                          {hasDetails && (
                            <div>
                              <h4 className="text-[11px] font-medium text-white/40 uppercase tracking-wider mb-1.5">
                                Details
                              </h4>
                              <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1.5">
                                {sortDetailKeys(Object.keys(run.details!).filter(k => k !== 'llm_validation')).map((key) => {
                                  const val = run.details![key];
                                  const isComplex = typeof val === 'object' && val !== null;
                                  return (
                                    <div key={key} className={isComplex ? 'col-span-2 md:col-span-3' : ''}>
                                      <span className="text-[11px] text-white/30">{key.replace(/_/g, ' ')}: </span>
                                      {isComplex ? (
                                        <pre className="mt-1 text-[11px] text-white/50 font-mono bg-black/40 rounded p-2 overflow-x-auto">
                                          {JSON.stringify(val, null, 2)}
                                        </pre>
                                      ) : (
                                        <span className="text-[12px] text-white/60 font-mono">
                                          {formatDetailValue(val)}
                                        </span>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}

                          {/* SQL Executed */}
                          {hasSql && (
                            <div>
                              <h4 className="text-[11px] font-medium text-white/40 uppercase tracking-wider mb-1.5">
                                SQL Executed
                              </h4>
                              <pre className="text-[11px] text-white/50 font-mono bg-black/40 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">
                                {run.sqlExecuted}
                              </pre>
                            </div>
                          )}

                          {/* AI Assessment */}
                          {hasLlmValidation && (
                            <div>
                              <h4 className="text-[11px] font-medium text-white/40 uppercase tracking-wider mb-1.5">
                                AI Assessment
                              </h4>
                              <div className="bg-black/30 rounded-lg p-3 space-y-2">
                                {hasLlmValidation.explanation && (
                                  <p className="text-[12px] text-white/60 leading-relaxed">
                                    {hasLlmValidation.explanation}
                                  </p>
                                )}
                                <div className="flex items-center gap-3 text-[11px]">
                                  {hasLlmValidation.original_status && (
                                    <span className="text-white/30">
                                      Original: <span className="text-white/50 font-medium">{hasLlmValidation.original_status}</span>
                                    </span>
                                  )}
                                  {hasLlmValidation.adjusted_status && (
                                    <span className="text-white/30">
                                      Adjusted: <span className="text-white/50 font-medium">{hasLlmValidation.adjusted_status}</span>
                                    </span>
                                  )}
                                  {hasLlmValidation.confidence_pct != null && (
                                    <span className="text-white/30">
                                      Confidence: <span className="text-white/50 font-medium">{hasLlmValidation.confidence_pct}%</span>
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Ask Scout */}
                          <div className="flex items-center gap-2 pt-1">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                navigateToScout(router, 'explain', run, taskName, monitorType, targetFqn);
                              }}
                              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium text-[var(--accent)] bg-[var(--accent)]/10 hover:bg-[var(--accent)]/20 transition-colors"
                            >
                              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                              </svg>
                              Ask Scout
                            </button>

                            <div className="flex items-center gap-1.5 ml-1">
                              {[
                                { label: 'Explain this', type: 'explain' as const },
                                { label: 'Double check', type: 'verify' as const },
                                { label: 'Investigate', type: 'investigate' as const },
                              ].map((chip) => (
                                <button
                                  key={chip.type}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigateToScout(router, chip.type, run, taskName, monitorType, targetFqn);
                                  }}
                                  className="px-2.5 py-1 rounded-full text-[11px] text-white/50 bg-white/[0.06] hover:bg-white/[0.1] hover:text-white/70 transition-colors"
                                >
                                  {chip.label}
                                </button>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
