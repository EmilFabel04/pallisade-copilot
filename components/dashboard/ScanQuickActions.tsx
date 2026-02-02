'use client';

import { useState } from 'react';

interface QuickAction {
  id: string;
  name: string;
  icon: React.ReactNode;
  onClick: () => void;
  badge?: string;
  color?: string;
}

interface ScanQuickActionsProps {
  reportId: string;
  tableName?: string;
  alertCount?: number;
  onViewLineage?: () => void;
  onCreateIssue?: () => void;
  onShare?: () => void;
  onExport?: () => void;
  onViewAlerts?: () => void;
}

export function ScanQuickActions({
  reportId,
  tableName,
  alertCount = 0,
  onViewLineage,
  onCreateIssue,
  onShare,
  onExport,
  onViewAlerts,
}: ScanQuickActionsProps) {
  const [copied, setCopied] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);

  const handleCopyLink = async () => {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    onShare?.();
  };

  const handleExport = () => {
    // Generate and download report as JSON
    const reportData = {
      reportId,
      exportedAt: new Date().toISOString(),
      url: window.location.href,
    };
    const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `scan-report-${reportId}.json`;
    a.click();
    URL.revokeObjectURL(url);
    onExport?.();
  };

  const actions: QuickAction[] = [
    {
      id: 'lineage',
      name: 'View Lineage',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
        </svg>
      ),
      onClick: () => onViewLineage?.(),
      color: 'text-violet-400',
    },
    {
      id: 'alerts',
      name: 'View Alerts',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
        </svg>
      ),
      onClick: () => onViewAlerts?.(),
      badge: alertCount > 0 ? String(alertCount) : undefined,
      color: alertCount > 0 ? 'text-red-400' : 'text-white/60',
    },
    {
      id: 'issue',
      name: 'Create Issue',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v6m3-3H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
      onClick: () => onCreateIssue?.(),
      color: 'text-amber-400',
    },
    {
      id: 'share',
      name: copied ? 'Copied!' : 'Copy Link',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
        </svg>
      ),
      onClick: handleCopyLink,
      color: copied ? 'text-emerald-400' : 'text-blue-400',
    },
    {
      id: 'export',
      name: 'Export',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
      ),
      onClick: handleExport,
      color: 'text-emerald-400',
    },
  ];

  return (
    <div 
      className={`fixed right-0 top-1/2 -translate-y-1/2 z-40 transition-all duration-200 ${
        isCollapsed ? 'translate-x-[calc(100%-32px)]' : ''
      }`}
    >
      {/* Toggle Button */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-full w-6 h-12 bg-white/[0.03] border border-white/10 border-r-0 rounded-l-lg flex items-center justify-center hover:bg-white/[0.05] transition-colors"
        title={isCollapsed ? 'Show quick actions' : 'Hide quick actions'}
      >
        <svg 
          className={`w-3 h-3 text-white/40 transition-transform ${isCollapsed ? 'rotate-180' : ''}`} 
          fill="none" 
          stroke="currentColor" 
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </button>

      {/* Actions Panel */}
      <div className="bg-[#0a0a0a]/95 backdrop-blur-sm border border-white/10 border-r-0 rounded-l-xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-4 py-3 border-b border-white/5">
          <h3 className="text-xs font-medium text-white/60 uppercase tracking-wider">Quick Actions</h3>
        </div>

        {/* Actions */}
        <div className="p-2 space-y-1">
          {actions.map((action) => (
            <button
              key={action.id}
              onClick={action.onClick}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left hover:bg-white/[0.05] transition-colors group ${action.color || 'text-white/60'}`}
            >
              <span className="flex-shrink-0 opacity-80 group-hover:opacity-100 transition-opacity">
                {action.icon}
              </span>
              <span className="text-sm font-medium text-white/80 group-hover:text-white transition-colors">
                {action.name}
              </span>
              {action.badge && (
                <span className="ml-auto px-1.5 py-0.5 text-[10px] font-medium rounded bg-red-500/20 text-red-400">
                  {action.badge}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Divider */}
        <div className="mx-3 border-t border-white/5" />

        {/* External Links */}
        <div className="p-2 space-y-1">
          <a
            href="https://docs.pallisade.io"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left hover:bg-white/[0.05] transition-colors group text-white/40"
          >
            <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
            </svg>
            <span className="text-xs text-white/50 group-hover:text-white/70 transition-colors">Docs</span>
            <svg className="w-3 h-3 ml-auto opacity-0 group-hover:opacity-50 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>
          
          <a
            href="https://github.com/pallisade"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left hover:bg-white/[0.05] transition-colors group text-white/40"
          >
            <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
              <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
            </svg>
            <span className="text-xs text-white/50 group-hover:text-white/70 transition-colors">GitHub</span>
            <svg className="w-3 h-3 ml-auto opacity-0 group-hover:opacity-50 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>
        </div>

        {/* Keyboard Shortcuts Hint */}
        <div className="px-4 py-2 bg-white/[0.02] border-t border-white/5">
          <p className="text-[10px] text-white/30">
            Press <kbd className="px-1 py-0.5 rounded bg-white/10 text-white/50 font-mono">?</kbd> for shortcuts
          </p>
        </div>
      </div>
    </div>
  );
}
