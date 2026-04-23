'use client';

import { useState } from 'react';
import type { ApplyChangePlanResult, ChangePlan } from '@/types/change-plan';

type PRStatus = 'draft' | 'open' | 'merged' | 'closed';

interface PRCardProps {
  result: ApplyChangePlanResult;
  plan?: ChangePlan;
  onSaveToArtifacts?: (content: string) => void;
}

const STATUS_CONFIG: Record<PRStatus, { label: string; color: string; bg: string }> = {
  draft: { label: 'Draft', color: '#9ca3af', bg: 'rgba(156, 163, 175, 0.2)' },
  open: { label: 'Open', color: '#34d399', bg: 'rgba(52, 211, 153, 0.2)' },
  merged: { label: 'Merged', color: '#a78bfa', bg: 'rgba(167, 139, 250, 0.2)' },
  closed: { label: 'Closed', color: '#f87171', bg: 'rgba(248, 113, 113, 0.2)' },
};

export function PRCard({ result, plan, onSaveToArtifacts }: PRCardProps) {
  const [expanded, setExpanded] = useState(false);

  // Infer status - newly created PRs are 'open'
  const status: PRStatus = 'open';
  const statusConfig = STATUS_CONFIG[status];

  // Extract PR title from plan or generate from PR number
  const prTitle = plan?.title || `Pull Request #${result.pr_number}`;
  const prDescription = plan?.description || 'Changes applied to your data pipeline';

  // Build artifact content for saving
  const artifactContent = `## PR #${result.pr_number}: ${prTitle}

**Branch:** ${result.branch}
**Files Changed:** ${result.files_changed}
**URL:** ${result.pr_url}

### Description
${prDescription}

${plan?.root_cause ? `### Root Cause\n${plan.root_cause}\n` : ''}
### Changes
${plan?.patches?.map(p => `- \`${p.file_path}\`: ${p.rationale}`).join('\n') || 'See PR for details'}
`;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        backgroundColor: 'var(--surface)',
        border: '1px solid var(--hover-bg)',
      }}
    >
      {/* Header */}
      <div className="px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            {/* GitHub Icon */}
            <div className="w-10 h-10 rounded-lg bg-[var(--hover-bg)] flex items-center justify-center flex-shrink-0">
              <svg className="w-6 h-6 text-[var(--text)]" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
              </svg>
            </div>

            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium text-[var(--text)]">Pull Request Created</h3>
                {/* Status Badge */}
                <span
                  className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                  style={{
                    backgroundColor: statusConfig.bg,
                    color: statusConfig.color,
                    border: `1px solid ${statusConfig.color}30`,
                  }}
                >
                  {statusConfig.label}
                </span>
              </div>
              <div className="text-xs text-[var(--muted)] mt-0.5">
                #{result.pr_number} on branch <code className="font-mono text-[var(--text-tertiary)]">{result.branch}</code>
              </div>
            </div>
          </div>

          {/* Expand Toggle (only if plan has context) */}
          {plan && (plan.root_cause || plan.description || (plan.patches && plan.patches.length > 0)) && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-1.5 hover:bg-[var(--overlay-bg)] rounded transition-colors"
            >
              <svg
                className={`w-4 h-4 text-[var(--muted)] transition-transform ${expanded ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          )}
        </div>

        {/* PR Title */}
        <h4 className="mt-3 text-[13px] font-medium text-[var(--text-secondary)]">{prTitle}</h4>

        {/* Quick Stats */}
        <div className="flex items-center gap-4 mt-2 text-xs text-[var(--muted)]">
          <span className="flex items-center gap-1">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            {result.files_changed} file{result.files_changed !== 1 ? 's' : ''} changed
          </span>
        </div>
      </div>

      {/* Expanded Content: Deep Reasoning */}
      {expanded && plan && (
        <div className="px-4 pb-3 space-y-3 border-t border-[var(--subtle-border)] pt-3">
          {plan.description && (
            <div>
              <span className="text-xs text-[var(--muted)] font-medium">Description</span>
              <p className="text-sm text-[var(--text-tertiary)] mt-1">{plan.description}</p>
            </div>
          )}

          {plan.root_cause && (
            <div>
              <span className="text-xs text-[var(--muted)] font-medium">Root Cause</span>
              <p
                className="text-sm text-[var(--text-tertiary)] mt-1 p-2 rounded"
                style={{
                  backgroundColor: 'var(--overlay-faint)',
                  border: '1px solid var(--border-faint)',
                }}
              >
                {plan.root_cause}
              </p>
            </div>
          )}

          {plan.patches && plan.patches.length > 0 && (
            <div>
              <span className="text-xs text-[var(--muted)] font-medium">Files Changed</span>
              <ul className="mt-1 space-y-1">
                {plan.patches.map((patch, i) => (
                  <li key={i} className="text-xs text-[var(--text-tertiary)] flex items-start gap-2">
                    <span className="font-mono text-emerald-400">{patch.file_path}</span>
                    {patch.rationale && (
                      <span className="text-[var(--muted)]">- {patch.rationale}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="px-4 py-3 border-t border-[var(--subtle-border)] flex items-center gap-2">
        {/* Open in GitHub */}
        {result.pr_url && (
          <a
            href={result.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            style={{
              backgroundColor: 'rgba(52, 211, 153, 0.15)',
              color: '#34d399',
              border: '1px solid rgba(52, 211, 153, 0.3)',
            }}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
              />
            </svg>
            Open in GitHub
          </a>
        )}

        {/* Save to Artifacts */}
        {onSaveToArtifacts && (
          <button
            onClick={() => onSaveToArtifacts(artifactContent)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--hover-bg)] hover:bg-[var(--overlay-medium)] transition-colors text-[var(--text-secondary)]"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"
              />
            </svg>
            Save to Artifacts
          </button>
        )}
      </div>
    </div>
  );
}
