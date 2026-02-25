'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { MONITOR_TYPES } from '@/types/schedule';

interface DiscoveredLog {
  path: string;
  size_bytes: number;
  size_human: string;
}

interface MonitorConfigFormProps {
  monitorType: string;
  onMonitorTypeChange: (type: string) => void;
  targetFqn: string;
  onTargetFqnChange: (fqn: string) => void;
  config: Record<string, any>;
  onConfigChange: (config: Record<string, any>) => void;
  integrationId?: string;
}

// Monitor types that need no config — fully auto-configured
const AUTO_ONLY_TYPES = ['NULL_RATE', 'UNIQUENESS', 'DISTRIBUTION', 'SCHEMA_CHANGE', 'SERVER_HEALTH'];

// Monitor types where advanced settings are available
const HAS_ADVANCED = ['FRESHNESS', 'VOLUME', 'ANOMALY', 'CUSTOM_SQL', 'CERTIFICATE', 'LOG_ANALYSIS'];

// Infrastructure monitor types — don't need a target table (use server integration)
const INFRA_TYPES = ['CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS'];

export function MonitorConfigForm({
  monitorType,
  onMonitorTypeChange,
  targetFqn,
  onTargetFqnChange,
  config,
  onConfigChange,
  integrationId,
}: MonitorConfigFormProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [discoveredLogs, setDiscoveredLogs] = useState<DiscoveredLog[]>([]);
  const [discoverError, setDiscoverError] = useState('');

  const handleDiscoverLogs = async () => {
    setDiscovering(true);
    setDiscoverError('');
    setDiscoveredLogs([]);
    try {
      const res = await fetch('/api/schedule/discover-logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ integrationId: integrationId || undefined }),
      });
      const data = await res.json();
      if (data.success && data.log_files?.length > 0) {
        setDiscoveredLogs(data.log_files);
      } else {
        setDiscoverError(data.message || 'No log files found on the server');
      }
    } catch {
      setDiscoverError('Failed to connect to server');
    } finally {
      setDiscovering(false);
    }
  };

  const toggleLogPath = (path: string) => {
    const current: string[] = config.log_paths || [];
    const updated = current.includes(path)
      ? current.filter((p: string) => p !== path)
      : [...current, path];
    onConfigChange({ ...config, log_paths: updated });
  };

  const hasAdvanced = HAS_ADVANCED.includes(monitorType);
  const isAutoOnly = AUTO_ONLY_TYPES.includes(monitorType);

  return (
    <div className="space-y-4">
      {/* Monitor type */}
      <div>
        <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
          Monitor Type
        </label>

        {/* Data Quality monitors */}
        <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-2">Data Quality</p>
        <div className="grid grid-cols-2 gap-2 mb-4">
          {MONITOR_TYPES.filter((mt) => !INFRA_TYPES.includes(mt.value)).map((mt) => (
            <button
              key={mt.value}
              type="button"
              onClick={() => {
                onMonitorTypeChange(mt.value);
                if (mt.value === 'ANOMALY') {
                  onConfigChange({ metric: 'row_count', llm_validate: true });
                } else if (['NULL_RATE', 'UNIQUENESS', 'DISTRIBUTION'].includes(mt.value)) {
                  onConfigChange({ llm_validate: true });
                } else {
                  onConfigChange({});
                }
                setShowAdvanced(false);
              }}
              className={cn(
                'flex flex-col items-start p-3 rounded-lg text-left transition-colors',
                monitorType === mt.value
                  ? 'bg-[var(--overlay-medium)] border border-[var(--overlay-strong)]'
                  : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
              )}
            >
              <span className="text-[13px] font-medium text-[var(--text)]">{mt.label}</span>
              <span className="text-[11px] text-[var(--muted)] mt-0.5">{mt.description}</span>
            </button>
          ))}
        </div>

        {/* Infrastructure monitors */}
        <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-2">Infrastructure</p>
        <div className="grid grid-cols-2 gap-2">
          {MONITOR_TYPES.filter((mt) => INFRA_TYPES.includes(mt.value)).map((mt) => (
            <button
              key={mt.value}
              type="button"
              onClick={() => {
                onMonitorTypeChange(mt.value);
                onConfigChange({});
                setShowAdvanced(false);
              }}
              className={cn(
                'flex flex-col items-start p-3 rounded-lg text-left transition-colors',
                monitorType === mt.value
                  ? 'bg-[var(--overlay-medium)] border border-[var(--overlay-strong)]'
                  : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
              )}
            >
              <span className="text-[13px] font-medium text-[var(--text)]">{mt.label}</span>
              <span className="text-[11px] text-[var(--muted)] mt-0.5">{mt.description}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Target table (not for infrastructure monitors) */}
      {!INFRA_TYPES.includes(monitorType) && (
        <div>
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Target Table
          </label>
          <input
            type="text"
            value={targetFqn}
            onChange={(e) => onTargetFqnChange(e.target.value)}
            placeholder="dataset.table or project.dataset.table"
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
          />
          <p className="text-[11px] text-[var(--text-faint)] mt-1">
            e.g. raw.customers or acme-484520.raw.customers
          </p>
        </div>
      )}

      {/* Infrastructure hint */}
      {INFRA_TYPES.includes(monitorType) && monitorType && (
        <div className="flex items-start gap-2 px-3 py-2.5 bg-slate-500/[0.06] border border-slate-500/[0.12] rounded-lg">
          <svg className="w-4 h-4 text-slate-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2" />
          </svg>
          <p className="text-[12px] text-slate-300/80">
            This monitor runs against a connected Linux Server integration via SSH.
            {monitorType === 'CERTIFICATE' && ' It will scan for TLS/SSL certificates and detect missing client certs or expiring certificates.'}
            {monitorType === 'SERVER_HEALTH' && ' It checks CPU, memory, and disk usage against configurable thresholds.'}
            {monitorType === 'LOG_ANALYSIS' && ' Configure log file paths below to scan for error patterns.'}
          </p>
        </div>
      )}

      {/* Auto-config hint for types that don't need manual config */}
      {isAutoOnly && monitorType && !INFRA_TYPES.includes(monitorType) && (
        <div className="flex items-start gap-2 px-3 py-2.5 bg-emerald-500/[0.06] border border-emerald-500/[0.12] rounded-lg">
          <svg className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <p className="text-[12px] text-emerald-300/80">
            This monitor is fully auto-configured. Just provide the target table and it will
            auto-discover columns and compute baselines from your warehouse.
          </p>
        </div>
      )}

      {/* LLM Validation toggle */}
      {monitorType && monitorType !== 'CUSTOM_SQL' && (
        <label className="flex items-center gap-2.5 cursor-pointer group">
          <input
            type="checkbox"
            checked={config.llm_validate !== false}
            onChange={(e) => onConfigChange({ ...config, llm_validate: e.target.checked })}
            className="w-4 h-4 rounded border-[var(--overlay-strong)] bg-[var(--overlay-bg)] text-violet-500 focus:ring-violet-500/30 focus:ring-offset-0"
          />
          <div>
            <span className="text-[12px] text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)]">AI Validation</span>
            <span className="text-[11px] text-[var(--text-faint)] ml-1.5">
              LLM reviews alerts to reduce false positives
            </span>
          </div>
        </label>
      )}

      {/* Advanced settings toggle */}
      {hasAdvanced && (
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-1.5 text-[12px] text-[var(--muted)] hover:text-[var(--text-tertiary)] transition-colors"
        >
          <svg
            className={`w-3.5 h-3.5 transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          Advanced Settings
          {!showAdvanced && (
            <span className="text-[11px] text-[var(--text-faint)] ml-1">
              — auto-detected from warehouse if left blank
            </span>
          )}
        </button>
      )}

      {/* Advanced settings content */}
      {showAdvanced && (
        <div className="pl-3 border-l border-[var(--subtle-border)] space-y-3">
          {/* FRESHNESS */}
          {(monitorType === 'FRESHNESS' || monitorType === 'freshness') && (
            <div className="space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Timestamp column
                </label>
                <input
                  type="text"
                  value={config.timestamp_column || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, timestamp_column: e.target.value || undefined })
                  }
                  placeholder="Auto-detect (prefers _PARTITIONTIME, loaded_at, created_at)"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Max hours since last update
                </label>
                <input
                  type="number"
                  value={config.max_hours || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, max_hours: parseInt(e.target.value) || 0 })
                  }
                  placeholder="Auto-compute from historical update frequency"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                />
              </div>
            </div>
          )}

          {/* VOLUME */}
          {(monitorType === 'VOLUME' || monitorType === 'volume') && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Min expected rows
                </label>
                <input
                  type="number"
                  value={config.min_rows || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, min_rows: parseInt(e.target.value) || 0 })
                  }
                  placeholder="Auto-compute (mean - 3σ)"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Max expected rows
                </label>
                <input
                  type="number"
                  value={config.max_rows || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, max_rows: parseInt(e.target.value) || 0 })
                  }
                  placeholder="Auto-compute (mean + 3σ)"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                />
              </div>
            </div>
          )}

          {/* ANOMALY */}
          {(monitorType === 'ANOMALY' || monitorType === 'anomaly') && (
            <div className="space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Metric
                </label>
                <select
                  value={config.column === '*' ? `all_${config.metric}` : (config.metric || 'row_count')}
                  onChange={(e) => {
                    const { column: _col, ...rest } = config;
                    if (e.target.value === 'row_count') {
                      onConfigChange({ ...rest, metric: e.target.value });
                    } else if (e.target.value.startsWith('all_')) {
                      const realMetric = e.target.value.replace('all_', '');
                      onConfigChange({ ...rest, metric: realMetric, column: '*' });
                    } else {
                      const { column: prevCol, ...withoutCol } = config;
                      if (prevCol === '*') {
                        onConfigChange({ ...withoutCol, metric: e.target.value });
                      } else {
                        onConfigChange({ ...config, metric: e.target.value });
                      }
                    }
                  }}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)]"
                >
                  <optgroup label="Table-level">
                    <option value="row_count">Row Count</option>
                    <option value="all_null_rate">All Columns — Null Rate</option>
                    <option value="all_avg">All Columns — Average</option>
                    <option value="all_zero_rate">All Columns — Zero Rate</option>
                  </optgroup>
                  <optgroup label="Single column">
                    <option value="avg">Average</option>
                    <option value="sum">Sum</option>
                    <option value="min">Min</option>
                    <option value="max">Max</option>
                    <option value="null_rate">Null Rate</option>
                    <option value="distinct_count">Distinct Count</option>
                    <option value="distinct_rate">Distinct Rate</option>
                    <option value="stddev">Std Dev</option>
                    <option value="zero_rate">Zero Rate</option>
                  </optgroup>
                </select>
                {config.column === '*' && (
                  <p className="text-[11px] text-[var(--text-faint)] mt-1">
                    Auto-discovers all numeric columns and checks each one
                  </p>
                )}
              </div>
              {config.metric && config.metric !== 'row_count' && config.column !== '*' && (
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Column name <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={config.column || ''}
                    onChange={(e) => onConfigChange({ ...config, column: e.target.value })}
                    placeholder="revenue"
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  />
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Z-score threshold
                  </label>
                  <input
                    type="number"
                    step="0.5"
                    value={config.anomaly_threshold || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, anomaly_threshold: parseFloat(e.target.value) || 3.0 })
                    }
                    placeholder="3.0"
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Lookback days
                  </label>
                  <input
                    type="number"
                    value={config.lookback_days || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, lookback_days: parseInt(e.target.value) || 30 })
                    }
                    placeholder="30"
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Timestamp column
                </label>
                <input
                  type="text"
                  value={config.timestamp_column || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, timestamp_column: e.target.value || undefined })
                  }
                  placeholder="Auto-detect"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                />
              </div>
            </div>
          )}

          {/* CUSTOM_SQL */}
          {monitorType === 'CUSTOM_SQL' && (
            <div>
              <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                Custom SQL (must return a single numeric value)
              </label>
              <textarea
                value={config.sql || ''}
                onChange={(e) => onConfigChange({ ...config, sql: e.target.value })}
                placeholder="SELECT COUNT(*) FROM orders WHERE created_at > NOW() - INTERVAL '24 hours'"
                rows={4}
                className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] font-mono"
              />
            </div>
          )}

          {/* CERTIFICATE */}
          {monitorType === 'CERTIFICATE' && (
            <div className="space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Certificate paths (one per line)
                </label>
                <textarea
                  value={(config.cert_paths || []).join('\n')}
                  onChange={(e) =>
                    onConfigChange({
                      ...config,
                      cert_paths: e.target.value.split('\n').filter((p: string) => p.trim()),
                    })
                  }
                  placeholder={"/etc/ssl/certs/server.crt\n/etc/letsencrypt/live/example.com/fullchain.pem\n\nLeave empty to auto-discover"}
                  rows={3}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] font-mono"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Warn (days before expiry)
                  </label>
                  <input
                    type="number"
                    value={config.warn_days || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, warn_days: parseInt(e.target.value) || 30 })
                    }
                    placeholder="30"
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Fail (days before expiry)
                  </label>
                  <input
                    type="number"
                    value={config.fail_days || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, fail_days: parseInt(e.target.value) || 7 })
                    }
                    placeholder="7"
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  />
                </div>
              </div>
            </div>
          )}

          {/* LOG_ANALYSIS */}
          {monitorType === 'LOG_ANALYSIS' && (
            <div className="space-y-3">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-[12px] font-medium text-[var(--muted)]">
                    Log file paths <span className="text-red-400">*</span>
                  </label>
                  <button
                    type="button"
                    onClick={handleDiscoverLogs}
                    disabled={discovering}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium text-violet-400 bg-violet-500/[0.08] border border-violet-500/[0.15] rounded-md hover:bg-violet-500/[0.15] transition-colors disabled:opacity-50"
                  >
                    {discovering ? (
                      <>
                        <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Scanning server...
                      </>
                    ) : (
                      <>
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                        </svg>
                        Discover Log Files
                      </>
                    )}
                  </button>
                </div>

                {/* Discovered log files — click to toggle selection */}
                {discoveredLogs.length > 0 && (
                  <div className="mb-2 max-h-[180px] overflow-y-auto rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-faint)]">
                    {discoveredLogs.map((log) => {
                      const selected = (config.log_paths || []).includes(log.path);
                      return (
                        <button
                          key={log.path}
                          type="button"
                          onClick={() => toggleLogPath(log.path)}
                          className={cn(
                            'flex items-center justify-between w-full px-3 py-1.5 text-left transition-colors border-b border-[var(--border-faint)] last:border-b-0',
                            selected
                              ? 'bg-violet-500/[0.08]'
                              : 'hover:bg-[var(--overlay-bg)]'
                          )}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <div className={cn(
                              'w-3.5 h-3.5 rounded border flex-shrink-0 flex items-center justify-center',
                              selected
                                ? 'bg-violet-500 border-violet-500'
                                : 'border-[var(--overlay-strong)]'
                            )}>
                              {selected && (
                                <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                </svg>
                              )}
                            </div>
                            <span className="text-[12px] text-[var(--text-secondary)] font-mono truncate">{log.path}</span>
                          </div>
                          <span className="text-[11px] text-[var(--text-faint)] flex-shrink-0 ml-2">{log.size_human}</span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {discoverError && (
                  <p className="text-[11px] text-red-400 mb-2">{discoverError}</p>
                )}

                {/* Path input — Enter to add */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="/var/log/syslog — press Enter to add"
                    className="flex-1 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] font-mono"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const input = e.currentTarget;
                        const val = input.value.trim();
                        if (val) {
                          const current: string[] = config.log_paths || [];
                          if (!current.includes(val)) {
                            onConfigChange({ ...config, log_paths: [...current, val] });
                          }
                          input.value = '';
                        }
                      }
                    }}
                  />
                </div>

                {/* Selected paths as removable chips */}
                {(config.log_paths || []).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {(config.log_paths || []).map((p: string) => (
                      <span
                        key={p}
                        className="inline-flex items-center gap-1 px-2 py-1 bg-[var(--hover-bg)] border border-[var(--subtle-border)] rounded-md text-[12px] text-[var(--text-secondary)] font-mono"
                      >
                        {p}
                        <button
                          type="button"
                          onClick={() => {
                            const updated = (config.log_paths || []).filter((x: string) => x !== p);
                            onConfigChange({ ...config, log_paths: updated });
                          }}
                          className="text-[var(--text-faint)] hover:text-[var(--text-tertiary)] ml-0.5"
                        >
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Error patterns (comma-separated)
                </label>
                <input
                  type="text"
                  value={(config.error_patterns || []).join(', ')}
                  onChange={(e) =>
                    onConfigChange({
                      ...config,
                      error_patterns: e.target.value.split(',').map((p: string) => p.trim()).filter(Boolean),
                    })
                  }
                  placeholder="ERROR, FATAL, CRITICAL"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
