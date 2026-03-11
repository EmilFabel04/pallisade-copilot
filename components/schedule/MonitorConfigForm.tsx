'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import {
  type MonitorDefinition,
  type MonitorCategory,
  getMonitorDefinition,
  MONITOR_CATEGORY_LABELS,
} from '@/types/monitor-catalog';

interface DiscoveredLog {
  path: string;
  size_bytes: number;
  size_human: string;
}

interface MonitorGroup {
  category: MonitorCategory;
  label: string;
  monitors: MonitorDefinition[];
}

interface MonitorConfigFormProps {
  monitorType: string;
  onMonitorTypeChange: (type: string) => void;
  targetFqn: string;
  onTargetFqnChange: (fqn: string) => void;
  config: Record<string, any>;
  onConfigChange: (config: Record<string, any>) => void;
  integrationId?: string;
  /** Catalog-grouped monitors (from monitor-catalog endpoint) */
  groupedMonitors?: MonitorGroup[];
}

// Legacy constants for warehouse monitor special cases
const LEGACY_ADVANCED_MONITORS = ['FRESHNESS', 'VOLUME', 'ANOMALY', 'UNIQUENESS', 'CUSTOM_SQL', 'CERTIFICATE', 'LOG_ANALYSIS'];

export function MonitorConfigForm({
  monitorType,
  onMonitorTypeChange,
  targetFqn,
  onTargetFqnChange,
  config,
  onConfigChange,
  integrationId,
  groupedMonitors,
}: MonitorConfigFormProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [discoveredLogs, setDiscoveredLogs] = useState<DiscoveredLog[]>([]);
  const [discoverError, setDiscoverError] = useState('');

  const selectedDef = getMonitorDefinition(monitorType);
  const isAutoConfigurable = selectedDef?.auto_configurable && (selectedDef?.config_schema || []).length === 0;
  const hasAdvancedFields = selectedDef?.config_schema?.some((f) => f.advanced) ?? false;
  const hasNonAdvancedFields = selectedDef?.config_schema?.some((f) => !f.advanced && f.type !== 'checkbox') ?? false;
  const isToolApi = selectedDef?.executor_type === 'tool_api';

  // Whether this monitor uses a legacy hardcoded advanced settings panel
  const usesLegacyAdvanced = LEGACY_ADVANCED_MONITORS.includes(monitorType);

  // Determine if the monitor needs a target or uses non-FQN target
  const targetType = selectedDef?.target_selector_type || 'fqn';
  const needsFqn = targetType === 'fqn';
  const needsServerTarget = targetType === 'server';

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

  // Handle monitor type selection with appropriate defaults
  const handleSelectMonitor = (key: string) => {
    const def = getMonitorDefinition(key);
    onMonitorTypeChange(key);
    setShowAdvanced(false);

    // Set up default config from config_schema defaults
    const defaults: Record<string, any> = { llm_validate: true };
    if (def) {
      for (const field of def.config_schema) {
        if (field.default_value !== undefined) {
          defaults[field.key] = field.default_value;
        }
      }
    }
    // Special: ANOMALY defaults
    if (key === 'ANOMALY') {
      defaults.metric = 'row_count';
    }
    // Special: UNIQUENESS defaults — check all columns by default
    if (key === 'UNIQUENESS') {
      defaults.column = '*';
    }
    onConfigChange(defaults);
  };

  return (
    <div className="space-y-4">
      {/* Monitor type selector — grouped by category from catalog */}
      <div>
        <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
          Monitor Type
        </label>

        {groupedMonitors && groupedMonitors.length > 0 ? (
          // Catalog-driven grouped rendering
          groupedMonitors.map((group) => (
            <div key={group.category} className="mb-4 last:mb-0">
              <p className="text-[11px] text-[var(--text-faint)] uppercase tracking-wider mb-2">
                {group.label}
              </p>
              <div className="flex flex-wrap gap-2">
                {group.monitors.map((mt) => (
                  <button
                    key={mt.key}
                    type="button"
                    onClick={() => handleSelectMonitor(mt.key)}
                    className={cn(
                      'flex flex-col items-start p-3 rounded-lg text-left transition-colors w-[calc(25%-6px)] min-h-[88px]',
                      monitorType === mt.key
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
          ))
        ) : (
          // Fallback: no catalog loaded yet
          <div className="text-[12px] text-[var(--text-faint)] py-4 text-center">
            Loading monitor types...
          </div>
        )}
      </div>

      {/* Target selector — varies by monitor type */}
      {needsFqn && monitorType && (
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

      {/* Tool-specific target hints */}
      {targetType === 'connector' && monitorType && (
        <div className="flex items-start gap-2 px-3 py-2.5 bg-blue-500/[0.06] border border-blue-500/[0.12] rounded-lg">
          <svg className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <p className="text-[12px] text-blue-300/80">
            This monitor checks your ingestion connector via the Fivetran/Airbyte API.
            Configure the connector ID below.
          </p>
        </div>
      )}

      {targetType === 'dag' && monitorType && (
        <div className="flex items-start gap-2 px-3 py-2.5 bg-orange-500/[0.06] border border-orange-500/[0.12] rounded-lg">
          <svg className="w-4 h-4 text-orange-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <p className="text-[12px] text-orange-300/80">
            This monitor checks your Airflow DAG via the Airflow REST API.
            Requires a live Airflow instance connection (not GitHub DAG-file mode).
            Configure the DAG ID below.
          </p>
        </div>
      )}

      {targetType === 'dbt_job' && monitorType && (
        <div className="flex items-start gap-2 px-3 py-2.5 bg-green-500/[0.06] border border-green-500/[0.12] rounded-lg">
          <svg className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-[12px] text-green-300/80">
            This monitor checks your dbt Cloud job runs and test results via the dbt Cloud API.
            Requires a live dbt Cloud connection (not project upload or GitHub mode).
          </p>
        </div>
      )}

      {/* Infrastructure hint */}
      {needsServerTarget && monitorType && (
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

      {/* Auto-config hint for auto-only warehouse monitors */}
      {isAutoConfigurable && monitorType && !needsServerTarget && (
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

      {/* Dynamic config fields for tool monitors (non-legacy) */}
      {isToolApi && selectedDef && hasNonAdvancedFields && (
        <div className="space-y-3">
          {selectedDef.config_schema
            .filter((f) => !f.advanced)
            .map((field) => (
              <DynamicField
                key={field.key}
                field={field}
                value={config[field.key]}
                onChange={(val) => onConfigChange({ ...config, [field.key]: val })}
              />
            ))}
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
      {monitorType && (usesLegacyAdvanced || (isToolApi && hasAdvancedFields)) && (
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
              — auto-detected if left blank
            </span>
          )}
        </button>
      )}

      {/* Advanced settings content */}
      {showAdvanced && (
        <div className="pl-3 border-l border-[var(--subtle-border)] space-y-3">
          {/* Tool monitor advanced fields (dynamic from catalog) */}
          {isToolApi && selectedDef && selectedDef.config_schema
            .filter((f) => f.advanced)
            .map((field) => (
              <DynamicField
                key={field.key}
                field={field}
                value={config[field.key]}
                onChange={(val) => onConfigChange({ ...config, [field.key]: val })}
              />
            ))}

          {/* ================================================================ */}
          {/* Legacy hardcoded advanced settings for warehouse/infra monitors  */}
          {/* ================================================================ */}

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
                  Min expected rows / day
                </label>
                <input
                  type="number"
                  value={config.min_rows || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, min_rows: parseInt(e.target.value) || 0 })
                  }
                  placeholder="Auto-compute (baseline - 3\u03C3)"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Max expected rows / day
                </label>
                <input
                  type="number"
                  value={config.max_rows || ''}
                  onChange={(e) =>
                    onConfigChange({ ...config, max_rows: parseInt(e.target.value) || 0 })
                  }
                  placeholder="Auto-compute (baseline + 3\u03C3)"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                />
              </div>
            </div>
          )}

          {/* UNIQUENESS */}
          {(monitorType === 'UNIQUENESS' || monitorType === 'uniqueness') && (
            <div className="space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Column
                </label>
                <select
                  value={config.column || '*'}
                  onChange={(e) => {
                    if (e.target.value === '*') {
                      const { column: _col, ...rest } = config;
                      onConfigChange({ ...rest, column: '*' });
                    } else if (e.target.value === '__custom__') {
                      onConfigChange({ ...config, column: '' });
                    } else {
                      onConfigChange({ ...config, column: e.target.value });
                    }
                  }}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)]"
                >
                  <option value="*">All columns (auto-discover)</option>
                  <option value="__custom__">Specific column...</option>
                </select>
                {config.column === '*' && (
                  <p className="text-[11px] text-[var(--text-faint)] mt-1">
                    Auto-discovers all columns and checks uniqueness on each one
                  </p>
                )}
              </div>
              {config.column !== undefined && config.column !== '*' && (
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Column name <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={config.column || ''}
                    onChange={(e) => onConfigChange({ ...config, column: e.target.value })}
                    placeholder="e.g. user_id, email"
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  />
                </div>
              )}
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

                {/* Discovered log files */}
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

// ---------------------------------------------------------------------------
// Dynamic field renderer for catalog-driven config fields
// ---------------------------------------------------------------------------

function DynamicField({
  field,
  value,
  onChange,
}: {
  field: { key: string; label: string; type: string; placeholder?: string; required?: boolean; options?: Array<{ value: string; label: string }>; help_text?: string };
  value: any;
  onChange: (val: any) => void;
}) {
  const inputClass = 'w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]';

  return (
    <div>
      <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
        {field.label}
        {field.required && <span className="text-red-400 ml-0.5">*</span>}
      </label>

      {field.type === 'text' && (
        <input
          type="text"
          value={value || ''}
          onChange={(e) => onChange(e.target.value || undefined)}
          placeholder={field.placeholder}
          className={inputClass}
        />
      )}

      {field.type === 'number' && (
        <input
          type="number"
          value={value ?? ''}
          onChange={(e) => {
            const val = e.target.value;
            onChange(val === '' ? undefined : Number(val));
          }}
          placeholder={field.placeholder}
          className={inputClass}
        />
      )}

      {field.type === 'select' && field.options && (
        <select
          value={value || field.options[0]?.value || ''}
          onChange={(e) => onChange(e.target.value)}
          className={inputClass}
        >
          {field.options.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      )}

      {field.type === 'textarea' && (
        <textarea
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          rows={3}
          className={cn(inputClass, 'font-mono')}
        />
      )}

      {field.type === 'checkbox' && (
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => onChange(e.target.checked)}
            className="w-4 h-4 rounded border-[var(--overlay-strong)] bg-[var(--overlay-bg)] text-violet-500 focus:ring-violet-500/30 focus:ring-offset-0"
          />
          <span className="text-[12px] text-[var(--text-tertiary)]">{field.placeholder || ''}</span>
        </label>
      )}

      {field.help_text && (
        <p className="text-[11px] text-[var(--text-faint)] mt-1">{field.help_text}</p>
      )}
    </div>
  );
}
