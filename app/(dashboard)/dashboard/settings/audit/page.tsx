'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface AuditLog {
  id: string;
  action: string;
  category: string;
  description: string;
  userName?: string;
  userEmail?: string;
  resourceType?: string;
  resourceId?: string;
  resourceName?: string;
  status: string;
  errorMessage?: string;
  ipAddress?: string;
  createdAt: string;
  metadata?: any;
}

const CATEGORY_STYLES: Record<string, { icon: string; color: string; bg: string }> = {
  scan: { icon: '📊', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  integration: { icon: '🔗', color: 'text-purple-400', bg: 'bg-purple-500/10' },
  user: { icon: '👤', color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  schedule: { icon: '⏰', color: 'text-amber-400', bg: 'bg-amber-500/10' },
  settings: { icon: '⚙️', color: 'text-gray-400', bg: 'bg-gray-500/10' },
  incident: { icon: '🚨', color: 'text-red-400', bg: 'bg-red-500/10' },
  contract: { icon: '📄', color: 'text-indigo-400', bg: 'bg-indigo-500/10' },
};

const ACTION_LABELS: Record<string, string> = {
  'scan.started': 'Scan Started',
  'scan.completed': 'Scan Completed',
  'scan.failed': 'Scan Failed',
  'integration.created': 'Integration Connected',
  'integration.updated': 'Integration Updated',
  'integration.deleted': 'Integration Removed',
  'integration.tested': 'Integration Tested',
  'user.login': 'User Logged In',
  'user.logout': 'User Logged Out',
  'user.invited': 'User Invited',
  'schedule.created': 'Schedule Created',
  'schedule.updated': 'Schedule Updated',
  'schedule.deleted': 'Schedule Deleted',
  'schedule.triggered': 'Schedule Triggered',
  'incident.created': 'Incident Created',
  'incident.resolved': 'Incident Resolved',
  'contract.created': 'Contract Created',
  'contract.violated': 'Contract Violated',
};

export default function AuditLogsPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');
  const [expandedLog, setExpandedLog] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const limit = 30;

  useEffect(() => {
    fetchLogs();
  }, [filter, page]);

  const fetchLogs = async () => {
    try {
      const params = new URLSearchParams({
        limit: limit.toString(),
        offset: (page * limit).toString(),
      });
      if (filter !== 'all') params.append('category', filter);
      
      const res = await fetch(`/api/audit?${params}`);
      const data = await res.json();
      setLogs(data.logs || []);
      setTotal(data.total || 0);
    } catch (err) {
      console.error('Failed to fetch audit logs');
    } finally {
      setLoading(false);
    }
  };

  const formatTime = (date: string) => {
    const d = new Date(date);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString();
  };

  const categories = ['all', 'scan', 'integration', 'user', 'schedule', 'incident', 'settings'];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm text-[var(--muted)] mb-2">
            <Link href="/dashboard/settings" className="hover:text-white">Settings</Link>
            <span>→</span>
            <span className="text-white">Audit Logs</span>
          </div>
          <h1 className="text-2xl font-bold">Audit Logs</h1>
          <p className="text-[var(--muted)] mt-1">Track all activity in your organization</p>
        </div>
        <div className="text-sm text-[var(--muted)]">
          {total} total events
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 p-1 bg-[rgba(255,255,255,0.03)] rounded-lg w-fit">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => { setFilter(cat); setPage(0); }}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-all flex items-center gap-2 ${
              filter === cat 
                ? 'bg-[rgba(255,255,255,0.08)] text-white' 
                : 'text-[var(--muted)] hover:text-white'
            }`}
          >
            {cat !== 'all' && <span>{CATEGORY_STYLES[cat]?.icon || '📋'}</span>}
            <span className="capitalize">{cat}</span>
          </button>
        ))}
      </div>

      {/* Logs List */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
        </div>
      ) : logs.length === 0 ? (
        <div className="dashboard-card p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[rgba(255,255,255,0.03)] flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold mb-2">No audit logs yet</h3>
          <p className="text-[var(--muted)]">
            Activity will appear here as you use the platform.
          </p>
        </div>
      ) : (
        <div className="dashboard-card divide-y divide-[rgba(255,255,255,0.04)]">
          {logs.map((log) => {
            const catStyle = CATEGORY_STYLES[log.category] || CATEGORY_STYLES.settings;
            const isExpanded = expandedLog === log.id;
            
            return (
              <div key={log.id} className="p-4">
                <button
                  onClick={() => setExpandedLog(isExpanded ? null : log.id)}
                  className="w-full flex items-start gap-4 text-left"
                >
                  {/* Icon */}
                  <div className={`w-10 h-10 rounded-lg ${catStyle.bg} flex items-center justify-center text-lg flex-shrink-0`}>
                    {catStyle.icon}
                  </div>
                  
                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium">
                        {ACTION_LABELS[log.action] || log.action}
                      </span>
                      {log.status === 'failure' && (
                        <span className="px-2 py-0.5 text-xs rounded bg-red-500/10 text-red-400">
                          Failed
                        </span>
                      )}
                      {log.resourceName && (
                        <span className="text-[var(--muted)]">
                          • {log.resourceName}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-[var(--muted)] mt-0.5">
                      {log.description}
                    </p>
                    <div className="flex items-center gap-4 mt-2 text-xs text-[var(--muted)]">
                      {log.userName && (
                        <span className="flex items-center gap-1">
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                          </svg>
                          {log.userName}
                        </span>
                      )}
                      <span>{formatTime(log.createdAt)}</span>
                      {log.ipAddress && log.ipAddress !== 'unknown' && (
                        <span className="font-mono">{log.ipAddress}</span>
                      )}
                    </div>
                  </div>
                  
                  {/* Expand icon */}
                  <svg 
                    className={`w-5 h-5 text-[var(--muted)] transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                
                {/* Expanded details */}
                {isExpanded && (
                  <div className="mt-4 ml-14 p-4 rounded-lg bg-[rgba(255,255,255,0.02)] space-y-3">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-xs text-[var(--muted)] mb-1">Event ID</div>
                        <code className="text-xs">{log.id}</code>
                      </div>
                      <div>
                        <div className="text-xs text-[var(--muted)] mb-1">Category</div>
                        <span className="capitalize">{log.category}</span>
                      </div>
                      <div>
                        <div className="text-xs text-[var(--muted)] mb-1">Action</div>
                        <span>{log.action}</span>
                      </div>
                      <div>
                        <div className="text-xs text-[var(--muted)] mb-1">Timestamp</div>
                        <span>{new Date(log.createdAt).toLocaleString()}</span>
                      </div>
                    </div>
                    
                    {log.resourceType && (
                      <div className="text-sm">
                        <div className="text-xs text-[var(--muted)] mb-1">Resource</div>
                        <span>{log.resourceType}: {log.resourceId}</span>
                      </div>
                    )}
                    
                    {log.errorMessage && (
                      <div className="p-3 rounded bg-red-500/10 text-red-400 text-sm">
                        <div className="text-xs text-red-500 mb-1">Error</div>
                        {log.errorMessage}
                      </div>
                    )}
                    
                    {log.metadata && Object.keys(log.metadata).length > 0 && (
                      <div>
                        <div className="text-xs text-[var(--muted)] mb-1">Additional Data</div>
                        <pre className="text-xs bg-[rgba(0,0,0,0.3)] p-3 rounded overflow-x-auto">
                          {JSON.stringify(log.metadata, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {total > limit && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-[var(--muted)]">
            Showing {page * limit + 1}-{Math.min((page + 1) * limit, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-4 py-2 text-sm rounded-lg bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={(page + 1) * limit >= total}
              className="px-4 py-2 text-sm rounded-lg bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

