'use client';

import { useState } from 'react';
import type { FilePatch, PatchType } from '@/types/change-plan';

interface FilePatchViewerProps {
  patch: FilePatch;
  showRationale?: boolean;
  defaultCollapsed?: boolean;
}

const PATCH_TYPE_LABELS: Record<PatchType, { label: string; color: string }> = {
  sql_model: { label: 'SQL', color: '#60a5fa' },
  yaml_config: { label: 'YAML', color: '#c084fc' },
  python_script: { label: 'Python', color: '#fbbf24' },
  orchestration: { label: 'Orchestration', color: '#34d399' },
  text_file: { label: 'Text', color: '#94a3b8' },
};

function getFileExtension(filePath: string): string {
  const parts = filePath.split('.');
  return parts.length > 1 ? parts[parts.length - 1] : '';
}

function parseDiffLines(diff: string | undefined): Array<{ type: 'add' | 'remove' | 'context' | 'header'; content: string }> {
  if (!diff) return [];

  return diff.split('\n').map((line) => {
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')) {
      return { type: 'header', content: line };
    } else if (line.startsWith('+')) {
      return { type: 'add', content: line };
    } else if (line.startsWith('-')) {
      return { type: 'remove', content: line };
    } else {
      return { type: 'context', content: line };
    }
  });
}

export function FilePatchViewer({ patch, showRationale = true, defaultCollapsed = false }: FilePatchViewerProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [copied, setCopied] = useState(false);
  const [showNewContent, setShowNewContent] = useState(false);

  const typeConfig = PATCH_TYPE_LABELS[patch.patch_type];
  const diffLines = parseDiffLines(patch.diff);
  const hasDiff = diffLines.length > 0;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(patch.new_content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        backgroundColor: 'var(--overlay-faint)',
        border: '1px solid var(--hover-bg)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-[var(--overlay-faint)] transition-colors"
        onClick={() => setCollapsed(!collapsed)}
        style={{ borderBottom: collapsed ? 'none' : '1px solid var(--subtle-border)' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <svg className="w-4 h-4 text-[var(--muted)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
            />
          </svg>
          <span className="text-sm font-mono text-[var(--text-secondary)] truncate">{patch.file_path}</span>
          <span
            className="px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0"
            style={{
              backgroundColor: `${typeConfig.color}20`,
              color: typeConfig.color,
              border: `1px solid ${typeConfig.color}30`,
            }}
          >
            {typeConfig.label}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleCopy();
            }}
            className="p-1 rounded hover:bg-[var(--hover-bg)] transition-colors text-[var(--muted)] hover:text-[var(--text-secondary)]"
            title="Copy new content"
          >
            {copied ? (
              <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
              </svg>
            )}
          </button>
          <svg
            className={`w-4 h-4 text-[var(--muted)] transition-transform ${collapsed ? '' : 'rotate-180'}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>

      {/* Content */}
      {!collapsed && (
        <div className="p-3 space-y-3">
          {/* Rationale */}
          {showRationale && patch.rationale && (
            <div className="text-xs text-[var(--text-tertiary)] bg-[var(--overlay-faint)] p-2 rounded border border-[var(--border-faint)]">
              <span className="text-[var(--muted)] font-medium">Rationale: </span>
              {patch.rationale}
            </div>
          )}

          {/* View Toggle */}
          {hasDiff && (
            <div className="flex gap-2">
              <button
                onClick={() => setShowNewContent(false)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  !showNewContent ? 'bg-[var(--hover-bg)] text-[var(--text-secondary)]' : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'
                }`}
              >
                Diff View
              </button>
              <button
                onClick={() => setShowNewContent(true)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  showNewContent ? 'bg-[var(--hover-bg)] text-[var(--text-secondary)]' : 'text-[var(--muted)] hover:text-[var(--text-tertiary)]'
                }`}
              >
                New Content
              </button>
            </div>
          )}

          {/* Diff or New Content */}
          <div
            className="rounded-lg overflow-x-auto text-xs font-mono"
            style={{ backgroundColor: 'var(--overlay-bg)' }}
          >
            {hasDiff && !showNewContent ? (
              <pre className="p-3 m-0">
                {diffLines.map((line, i) => (
                  <div
                    key={i}
                    className={`
                      ${line.type === 'add' ? 'bg-emerald-500/10 text-emerald-300' : ''}
                      ${line.type === 'remove' ? 'bg-red-500/10 text-red-300' : ''}
                      ${line.type === 'header' ? 'text-blue-400 font-medium' : ''}
                      ${line.type === 'context' ? 'text-[var(--text-tertiary)]' : ''}
                    `}
                  >
                    {line.content}
                  </div>
                ))}
              </pre>
            ) : (
              <pre className="p-3 m-0 text-[var(--text-secondary)] whitespace-pre-wrap">{patch.new_content}</pre>
            )}
          </div>

          {/* Rollback Steps */}
          {patch.rollback_steps && patch.rollback_steps.length > 0 && (
            <div className="text-xs">
              <span className="text-[var(--muted)] font-medium block mb-1">Rollback Steps:</span>
              <ol className="list-decimal list-inside text-[var(--text-tertiary)] space-y-0.5">
                {patch.rollback_steps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
