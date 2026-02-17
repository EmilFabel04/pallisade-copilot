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
              onClick={() => onMonitorTypeChange(mt.value)}
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
          Target Table (database.schema.table)
        </label>
        <input
          type="text"
          value={targetFqn}
          onChange={(e) => onTargetFqnChange(e.target.value)}
          placeholder="analytics.public.orders"
          className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.2]"
        />
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
