'use client';

import { useState } from 'react';
import { MONITOR_TYPES } from '@/types/schedule';

interface MonitorConfigFormProps {
  monitorType: string;
  onMonitorTypeChange: (type: string) => void;
  targetFqn: string;
  onTargetFqnChange: (fqn: string) => void;
  config: Record<string, any>;
  onConfigChange: (config: Record<string, any>) => void;
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
}: MonitorConfigFormProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const hasAdvanced = HAS_ADVANCED.includes(monitorType);
  const isAutoOnly = AUTO_ONLY_TYPES.includes(monitorType);

  return (
    <div className="space-y-4">
      {/* Monitor type */}
      <div>
        <label className="block text-[12px] font-medium text-white/50 mb-2">
          Monitor Type
        </label>
        <div className="grid grid-cols-2 gap-2">
          {MONITOR_TYPES.map((mt) => (
            <button
              key={mt.value}
              type="button"
              onClick={() => {
                onMonitorTypeChange(mt.value);
                // Set sensible defaults per monitor type
                if (mt.value === 'ANOMALY') {
                  onConfigChange({ metric: 'row_count', llm_validate: true });
                } else if (['NULL_RATE', 'UNIQUENESS', 'DISTRIBUTION'].includes(mt.value)) {
                  onConfigChange({ llm_validate: true });
                } else {
                  onConfigChange({});
                }
                setShowAdvanced(false);
              }}
              className={`
                flex flex-col items-start p-3 rounded-lg text-left transition-colors
                ${monitorType === mt.value
                  ? 'bg-white/[0.1] border border-white/[0.15]'
                  : 'bg-white/[0.03] border border-white/[0.06] hover:bg-white/[0.06]'
                }
              `}
            >
              <span className="text-[13px] font-medium text-white">{mt.label}</span>
              <span className="text-[11px] text-white/40 mt-0.5">{mt.description}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Target table (not for infrastructure monitors) */}
      {!INFRA_TYPES.includes(monitorType) && (
        <div>
          <label className="block text-[12px] font-medium text-white/50 mb-2">
            Target Table
          </label>
          <input
            type="text"
            value={targetFqn}
            onChange={(e) => onTargetFqnChange(e.target.value)}
            placeholder="dataset.table or project.dataset.table"
            className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
          />
          <p className="text-[11px] text-white/30 mt-1">
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
            className="w-4 h-4 rounded border-white/20 bg-white/[0.04] text-violet-500 focus:ring-violet-500/30 focus:ring-offset-0"
          />
          <div>
            <span className="text-[12px] text-white/70 group-hover:text-white/90">AI Validation</span>
            <span className="text-[11px] text-white/30 ml-1.5">
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
          className="flex items-center gap-1.5 text-[12px] text-white/40 hover:text-white/60 transition-colors"
        >
          <svg
            className={`w-3.5 h-3.5 transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          Advanced Settings
          {!showAdvanced && (
            <span className="text-[11px] text-white/25 ml-1">
              — auto-detected from warehouse if left blank
            </span>
          )}
        </button>
      )}

      {/* Advanced settings content */}
      {showAdvanced && (
        <div className="pl-3 border-l border-white/[0.06] space-y-3">
          {/* FRESHNESS */}
          {(monitorType === 'FRESHNESS' || monitorType === 'freshness') && (
            <div className="space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Timestamp column
                </label>
                <input
                  type="text"
                  value={config.timestamp_column || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, timestamp_column: e.target.value || undefined })
                  }
                  placeholder="Auto-detect (prefers _PARTITIONTIME, loaded_at, created_at)"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Max hours since last update
                </label>
                <input
                  type="number"
                  value={config.max_hours || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, max_hours: parseInt(e.target.value) || 0 })
                  }
                  placeholder="Auto-compute from historical update frequency"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                />
              </div>
            </div>
          )}

          {/* VOLUME */}
          {(monitorType === 'VOLUME' || monitorType === 'volume') && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Min expected rows
                </label>
                <input
                  type="number"
                  value={config.min_rows || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, min_rows: parseInt(e.target.value) || 0 })
                  }
                  placeholder="Auto-compute (mean - 3σ)"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Max expected rows
                </label>
                <input
                  type="number"
                  value={config.max_rows || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, max_rows: parseInt(e.target.value) || 0 })
                  }
                  placeholder="Auto-compute (mean + 3σ)"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                />
              </div>
            </div>
          )}

          {/* ANOMALY */}
          {(monitorType === 'ANOMALY' || monitorType === 'anomaly') && (
            <div className="space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
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
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white focus:outline-none focus:border-white/[0.2]"
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
                  <p className="text-[11px] text-white/30 mt-1">
                    Auto-discovers all numeric columns and checks each one
                  </p>
                )}
              </div>
              {config.metric && config.metric !== 'row_count' && config.column !== '*' && (
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
                    Column name <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={config.column || ''}
                    onChange={(e) => onConfigChange({ ...config, column: e.target.value })}
                    placeholder="revenue"
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                  />
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
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
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
                    Lookback days
                  </label>
                  <input
                    type="number"
                    value={config.lookback_days || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, lookback_days: parseInt(e.target.value) || 30 })
                    }
                    placeholder="30"
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Timestamp column
                </label>
                <input
                  type="text"
                  value={config.timestamp_column || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, timestamp_column: e.target.value || undefined })
                  }
                  placeholder="Auto-detect"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                />
              </div>
            </div>
          )}

          {/* CUSTOM_SQL */}
          {monitorType === 'CUSTOM_SQL' && (
            <div>
              <label className="block text-[12px] font-medium text-white/50 mb-2">
                Custom SQL (must return a single numeric value)
              </label>
              <textarea
                value={config.sql || ''}
                onChange={(e) => onConfigChange({ ...config, sql: e.target.value })}
                placeholder="SELECT COUNT(*) FROM orders WHERE created_at > NOW() - INTERVAL '24 hours'"
                rows={4}
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2] font-mono"
              />
            </div>
          )}

          {/* CERTIFICATE */}
          {monitorType === 'CERTIFICATE' && (
            <div className="space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
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
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2] font-mono"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
                    Warn (days before expiry)
                  </label>
                  <input
                    type="number"
                    value={config.warn_days || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, warn_days: parseInt(e.target.value) || 30 })
                    }
                    placeholder="30"
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
                    Fail (days before expiry)
                  </label>
                  <input
                    type="number"
                    value={config.fail_days || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, fail_days: parseInt(e.target.value) || 7 })
                    }
                    placeholder="7"
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                  />
                </div>
              </div>
            </div>
          )}

          {/* LOG_ANALYSIS */}
          {monitorType === 'LOG_ANALYSIS' && (
            <div className="space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
                  Log file paths (one per line) <span className="text-red-400">*</span>
                </label>
                <textarea
                  value={(config.log_paths || []).join('\n')}
                  onChange={(e) =>
                    onConfigChange({
                      ...config,
                      log_paths: e.target.value.split('\n').filter((p: string) => p.trim()),
                    })
                  }
                  placeholder={"/var/log/syslog\n/var/log/app/error.log"}
                  rows={3}
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2] font-mono"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
                    Max errors before FAIL
                  </label>
                  <input
                    type="number"
                    value={config.max_errors || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, max_errors: parseInt(e.target.value) || 10 })
                    }
                    placeholder="10"
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                  />
                </div>
                <div>
                  <label className="block text-[12px] font-medium text-white/50 mb-2">
                    Lines to scan
                  </label>
                  <input
                    type="number"
                    value={config.lookback_lines || ''}
                    onChange={(e) =>
                      onConfigChange({ ...config, lookback_lines: parseInt(e.target.value) || 1000 })
                    }
                    placeholder="1000"
                    className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[12px] font-medium text-white/50 mb-2">
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
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
