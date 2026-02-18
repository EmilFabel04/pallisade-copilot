'use client';

import { MONITOR_TYPES } from '@/types/schedule';

interface MonitorConfigFormProps {
  monitorType: string;
  onMonitorTypeChange: (type: string) => void;
  targetFqn: string;
  onTargetFqnChange: (fqn: string) => void;
  config: Record<string, any>;
  onConfigChange: (config: Record<string, any>) => void;
}

export function MonitorConfigForm({
  monitorType,
  onMonitorTypeChange,
  targetFqn,
  onTargetFqnChange,
  config,
  onConfigChange,
}: MonitorConfigFormProps) {
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
                  onConfigChange({ metric: 'row_count' });
                } else {
                  onConfigChange({});
                }
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

      {/* Target table */}
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

      {/* Threshold config (varies by type) */}
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
            <p className="text-[11px] text-white/30 mt-1">
              Leave blank to auto-detect the best timestamp column from the table schema
            </p>
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
              placeholder="24"
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
            />
          </div>
        </div>
      )}

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
              placeholder="1000"
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
              placeholder="1000000"
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
            />
          </div>
        </div>
      )}

      {(monitorType === 'NULL_RATE' || monitorType === 'UNIQUENESS') && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[12px] font-medium text-white/50 mb-2">
              Column name
            </label>
            <input
              type="text"
              value={config.column || ''}
              onChange={(e) => onConfigChange({ ...config, column: e.target.value })}
              placeholder="email"
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-white/50 mb-2">
              Threshold %
            </label>
            <input
              type="number"
              value={config.threshold_pct || ''}
              onChange={(e) =>
                onConfigChange({ ...config, threshold_pct: parseFloat(e.target.value) || 0 })
              }
              placeholder="5"
              className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
            />
          </div>
        </div>
      )}

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
                  // "All columns" mode: set column to "*" with the real metric
                  const realMetric = e.target.value.replace('all_', '');
                  onConfigChange({ ...rest, metric: realMetric, column: '*' });
                } else {
                  // Single-column mode: clear the "*" if switching from all-columns
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
              <p className="text-[11px] text-white/30 mt-1">
                Standard deviations from mean to flag as anomaly (default: 3.0)
              </p>
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
            <p className="text-[11px] text-white/30 mt-1">
              Leave blank to auto-detect from table schema
            </p>
          </div>
        </div>
      )}

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
    </div>
  );
}
