'use client';

import { useState } from 'react';
import Link from 'next/link';

interface QuickActionsProps {
  reportId: string;
  reportTitle: string;
  findingsCount: number;
  criticalCount: number;
  autoFixCount: number;
  integrationName?: string;
  onCreateIssue?: () => void;
  onExport?: (format: 'json' | 'csv' | 'pdf') => void;
}

export function QuickActions({
  reportId,
  reportTitle,
  findingsCount,
  criticalCount,
  autoFixCount,
  integrationName,
  onCreateIssue,
  onExport,
}: QuickActionsProps) {
  const [showShareMenu, setShowShareMenu] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);

  const shareUrl = typeof window !== 'undefined' ? window.location.href : '';

  const handleCopyLink = async () => {
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleShare = async (method: 'slack' | 'email' | 'jira') => {
    const subject = encodeURIComponent(`Scan Report: ${reportTitle}`);
    const body = encodeURIComponent(
      `Scan Report Summary:\n\n` +
      `- Findings: ${findingsCount}\n` +
      `- Critical: ${criticalCount}\n` +
      `- Auto-fixes available: ${autoFixCount}\n\n` +
      `View full report: ${shareUrl}`
    );

    switch (method) {
      case 'email':
        window.open(`mailto:?subject=${subject}&body=${body}`);
        break;
      case 'slack':
        // Slack webhook integration would go here
        alert('Slack integration coming soon');
        break;
      case 'jira':
        // Jira integration would go here
        alert('Jira integration coming soon');
        break;
    }
    setShowShareMenu(false);
  };

  return (
    <div className="bg-[var(--overlay-faint)] border border-[var(--subtle-border)] rounded-xl p-4">
      <div className="text-xs text-[var(--muted)] mb-3">Quick Actions</div>
      
      <div className="space-y-2">
        {/* Share */}
        <div className="relative">
          <button
            onClick={() => setShowShareMenu(!showShareMenu)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-[var(--subtle-bg)] text-[var(--text-tertiary)] text-xs hover:bg-[var(--overlay-medium)] transition-colors"
          >
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
              </svg>
              Share Report
            </div>
            <svg className={`w-4 h-4 transition-transform ${showShareMenu ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showShareMenu && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-[var(--surface)] border border-[var(--border-medium)] rounded-lg overflow-hidden z-10">
              <button
                onClick={handleCopyLink}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[var(--text-tertiary)] hover:bg-[var(--subtle-bg)] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                </svg>
                {copied ? 'Copied!' : 'Copy Link'}
              </button>
              <button
                onClick={() => handleShare('email')}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[var(--text-tertiary)] hover:bg-[var(--subtle-bg)] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                Send via Email
              </button>
              <button
                onClick={() => handleShare('slack')}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[var(--text-tertiary)] hover:bg-[var(--subtle-bg)] transition-colors"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/>
                </svg>
                Share to Slack
              </button>
            </div>
          )}
        </div>

        {/* Create Issue */}
        <button
          onClick={onCreateIssue}
          className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-[var(--subtle-bg)] text-[var(--text-tertiary)] text-xs hover:bg-[var(--overlay-medium)] transition-colors"
        >
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v3m0 0v3m0-3h3m-3 0H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Create Jira Issue
          </div>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </button>

        {/* Export */}
        <div className="relative">
          <button
            onClick={() => setShowExportMenu(!showExportMenu)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-[var(--subtle-bg)] text-[var(--text-tertiary)] text-xs hover:bg-[var(--overlay-medium)] transition-colors"
          >
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Export Report
            </div>
            <svg className={`w-4 h-4 transition-transform ${showExportMenu ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showExportMenu && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-[var(--surface)] border border-[var(--border-medium)] rounded-lg overflow-hidden z-10">
              {(['json', 'csv', 'pdf'] as const).map(format => (
                <button
                  key={format}
                  onClick={() => { onExport?.(format); setShowExportMenu(false); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-[var(--text-tertiary)] hover:bg-[var(--subtle-bg)] transition-colors uppercase"
                >
                  <span className="w-8 text-left font-mono">.{format}</span>
                  Export as {format.toUpperCase()}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Auto-Fixes */}
        {autoFixCount > 0 && (
          <Link
            href={`/dashboard/reports/${reportId}?tab=fixes`}
            className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-emerald-500/10 text-emerald-400 text-xs hover:bg-emerald-500/20 transition-colors"
          >
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Apply {autoFixCount} Auto-Fixes
            </div>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        )}

        {/* AI Assistant */}
        <Link
          href="/dashboard/assistant"
          className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-[var(--subtle-bg)] text-[var(--text-tertiary)] text-xs hover:bg-[var(--overlay-medium)] transition-colors"
        >
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            Ask AI Assistant
          </div>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </Link>
      </div>
    </div>
  );
}
