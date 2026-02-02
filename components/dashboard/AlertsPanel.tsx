'use client';

import { useState } from 'react';
import Link from 'next/link';

interface Finding {
  id: string;
  title: string;
  severity: string;
  table?: string;
  column?: string;
  description?: string;
  scan_type?: string;
}

interface Alert {
  id: string;
  findingId: string;
  title: string;
  severity: 'critical' | 'high' | 'medium';
  table?: string;
  status: 'active' | 'acknowledged' | 'resolved';
  createdAt: string;
  assignee?: string;
}

interface AlertsPanelProps {
  findings: Finding[];
  onCreateAlert?: (finding: Finding) => void;
  onViewFinding?: (findingId: string) => void;
}

export function AlertsPanel({ findings, onCreateAlert, onViewFinding }: AlertsPanelProps) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [filter, setFilter] = useState<'all' | 'active' | 'acknowledged' | 'resolved'>('all');

  // Filter findings that can become alerts (critical and high)
  const alertableFindings = findings.filter(f => f.severity === 'critical' || f.severity === 'high');

  const handleCreateAlert = (finding: Finding) => {
    const newAlert: Alert = {
      id: `alert-${Date.now()}`,
      findingId: finding.id,
      title: finding.title,
      severity: finding.severity as 'critical' | 'high',
      table: finding.table,
      status: 'active',
      createdAt: new Date().toISOString(),
    };
    setAlerts(prev => [newAlert, ...prev]);
    onCreateAlert?.(finding);
    setShowCreateModal(false);
    setSelectedFinding(null);
  };

  const handleUpdateStatus = (alertId: string, status: Alert['status']) => {
    setAlerts(prev => prev.map(a => a.id === alertId ? { ...a, status } : a));
  };

  // Sort by severity (critical first) then filter
  const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const filteredAlerts = alerts
    .filter(a => filter === 'all' || a.status === filter)
    .sort((a, b) => (severityOrder[a.severity] ?? 4) - (severityOrder[b.severity] ?? 4));

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-medium text-white/80">Alerts</h3>
          {alerts.filter(a => a.status === 'active').length > 0 && (
            <span className="px-2 py-0.5 rounded-full text-xs bg-red-500/20 text-red-400 animate-pulse">
              {alerts.filter(a => a.status === 'active').length} active
            </span>
          )}
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="text-xs text-white/40 hover:text-white/60 flex items-center gap-1.5"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Create Alert
        </button>
      </div>

      {/* Filter Tabs */}
      {alerts.length > 0 && (
        <div className="flex items-center gap-1 text-xs">
          {(['all', 'active', 'acknowledged', 'resolved'] as const).map(status => (
            <button
              key={status}
              onClick={() => setFilter(status)}
              className={`px-2.5 py-1 rounded-lg capitalize transition-colors ${
                filter === status ? 'bg-white/10 text-white' : 'text-white/40 hover:text-white/60'
              }`}
            >
              {status}
              {status !== 'all' && (
                <span className="ml-1 opacity-60">
                  {alerts.filter(a => a.status === status).length}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Alerts List */}
      {alerts.length === 0 ? (
        <div className="bg-white/[0.02] border border-white/5 rounded-xl p-6 text-center">
          <div className="w-10 h-10 mx-auto mb-3 rounded-full bg-white/5 flex items-center justify-center">
            <svg className="w-5 h-5 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
          </div>
          <p className="text-white/40 text-sm mb-2">No alerts created</p>
          <p className="text-white/30 text-xs">
            Create alerts from critical or high severity findings to track and resolve issues
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filteredAlerts.map(alert => (
            <div
              key={alert.id}
              className={`bg-white/[0.02] border rounded-xl p-4 transition-colors ${
                alert.status === 'active' 
                  ? alert.severity === 'critical' 
                    ? 'border-red-500/30 bg-red-500/5' 
                    : 'border-amber-500/30 bg-amber-500/5'
                  : 'border-white/5'
              }`}
            >
              <div className="flex items-start gap-3">
                {/* Status Icon */}
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                  alert.status === 'active'
                    ? alert.severity === 'critical' ? 'bg-red-500/20' : 'bg-amber-500/20'
                    : alert.status === 'acknowledged' ? 'bg-blue-500/20' : 'bg-emerald-500/20'
                }`}>
                  {alert.status === 'active' ? (
                    <svg className={`w-4 h-4 ${alert.severity === 'critical' ? 'text-red-400' : 'text-amber-400'} animate-pulse`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                  ) : alert.status === 'acknowledged' ? (
                    <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h4 className="text-sm font-medium text-white/90 truncate">{alert.title}</h4>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${
                      alert.severity === 'critical' ? 'bg-red-500/15 text-red-400' : 'bg-amber-500/15 text-amber-400'
                    }`}>
                      {alert.severity}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-white/40">
                    {alert.table && <span className="font-mono">{alert.table}</span>}
                    <span>{new Date(alert.createdAt).toLocaleString()}</span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2">
                  {alert.status === 'active' && (
                    <button
                      onClick={() => handleUpdateStatus(alert.id, 'acknowledged')}
                      className="px-2 py-1 text-xs rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20"
                    >
                      Acknowledge
                    </button>
                  )}
                  {alert.status === 'acknowledged' && (
                    <button
                      onClick={() => handleUpdateStatus(alert.id, 'resolved')}
                      className="px-2 py-1 text-xs rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
                    >
                      Resolve
                    </button>
                  )}
                  <button
                    onClick={() => onViewFinding?.(alert.findingId)}
                    className="p-1.5 rounded hover:bg-white/5 text-white/40 hover:text-white/60"
                    title="View Finding"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Alert Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-[#0a0a0a] border border-white/10 rounded-2xl w-full max-w-lg mx-4 overflow-hidden">
            <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
              <h3 className="font-medium">Create Alert from Finding</h3>
              <button
                onClick={() => { setShowCreateModal(false); setSelectedFinding(null); }}
                className="text-white/40 hover:text-white/60"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="p-6 max-h-96 overflow-y-auto">
              {alertableFindings.length === 0 ? (
                <p className="text-center text-white/40 py-8">
                  No critical or high severity findings to create alerts from
                </p>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-white/40 mb-4">
                    Select a critical or high severity finding to create an alert:
                  </p>
                  {alertableFindings.map(finding => {
                    const isSelected = selectedFinding?.id === finding.id;
                    const alreadyHasAlert = alerts.some(a => a.findingId === finding.id);

                    return (
                      <button
                        key={finding.id}
                        onClick={() => setSelectedFinding(finding)}
                        disabled={alreadyHasAlert}
                        className={`w-full p-3 rounded-xl text-left transition-colors ${
                          alreadyHasAlert 
                            ? 'bg-white/[0.02] opacity-50 cursor-not-allowed' 
                            : isSelected 
                              ? 'bg-white/10 border border-white/20' 
                              : 'bg-white/[0.02] border border-white/5 hover:border-white/10'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <span className={`w-2 h-2 rounded-full ${
                            finding.severity === 'critical' ? 'bg-red-500' : 'bg-amber-500'
                          }`} />
                          <div className="flex-1 min-w-0">
                            <div className="text-sm text-white/80 truncate">{finding.title}</div>
                            <div className="text-xs text-white/40 flex items-center gap-2">
                              {finding.dataset && <span className="px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 text-[10px]">{finding.dataset}</span>}
                              {finding.table && <span className="font-mono">{finding.table}</span>}
                              {alreadyHasAlert && <span className="ml-2 text-amber-400">Alert exists</span>}
                            </div>
                          </div>
                          {isSelected && (
                            <svg className="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {selectedFinding && (
              <div className="px-6 py-4 border-t border-white/5 flex justify-end gap-3">
                <button
                  onClick={() => { setShowCreateModal(false); setSelectedFinding(null); }}
                  className="px-4 py-2 text-sm text-white/60 hover:text-white/80"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleCreateAlert(selectedFinding)}
                  className="px-4 py-2 text-sm bg-white text-black rounded-lg hover:bg-white/90"
                >
                  Create Alert
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
