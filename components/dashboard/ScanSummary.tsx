'use client';

import { useState } from 'react';
import { TypewriterLog } from '@/components/ui/TypewriterText';

interface TableDetail {
  name: string;
  rows: number;
  columns: number;
  lastUpdated?: string;
  sizeBytes?: number;
  issues: number;
  severity?: 'healthy' | 'low' | 'medium' | 'high' | 'critical';
}

interface ScanSummaryProps {
  scanId: string;
  scanType: string;
  integrationName: string;
  integrationType: string;
  database?: string;
  schema?: string;
  tablesScanned: number;
  totalRows: number;
  totalColumns?: number;
  duration: number;
  startTime: string;
  endTime: string;
  scanConfig?: {
    freshnessThreshold?: number;
    nullRateThreshold?: number;
    duplicateThreshold?: number;
    samplingEnabled?: boolean;
    sampleSize?: number;
  };
  tableDetails?: TableDetail[];
  scanLog?: Array<{
    text: string;
    type?: 'info' | 'success' | 'warning' | 'error' | 'data';
  }>;
}

export function ScanSummary({
  scanId,
  scanType,
  integrationName,
  integrationType,
  database,
  schema,
  tablesScanned,
  totalRows,
  totalColumns,
  duration,
  startTime,
  endTime,
  scanConfig,
  tableDetails = [],
  scanLog = [],
}: ScanSummaryProps) {
  const [showLog, setShowLog] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const [viewMode, setViewMode] = useState<'grid' | 'list' | 'compact'>('grid');

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const formatNumber = (num: number) => {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
  };

  const getSeverityColor = (severity?: string) => {
    switch (severity) {
      case 'critical': return 'bg-red-500';
      case 'high': return 'bg-amber-500';
      case 'medium': return 'bg-yellow-500';
      case 'low': return 'bg-blue-500';
      default: return 'bg-emerald-500';
    }
  };

  return (
    <div className="space-y-4">
      {/* Header with scan info */}
      <div className="bg-white/[0.02] border border-white/5 rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="text-xs text-white/40">Scan Details</div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowLog(!showLog)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                showLog ? 'bg-white/10 text-white' : 'text-white/40 hover:text-white/60'
              }`}
            >
              Log
            </button>
            <button
              onClick={() => setShowConfig(!showConfig)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                showConfig ? 'bg-white/10 text-white' : 'text-white/40 hover:text-white/60'
              }`}
            >
              Config
            </button>
          </div>
        </div>

        {/* Main info grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-[10px] text-white/30 uppercase tracking-wider mb-1">Integration</div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${
                integrationType === 'bigquery' ? 'bg-blue-500' :
                integrationType === 'snowflake' ? 'bg-cyan-500' :
                integrationType === 'postgres' ? 'bg-blue-600' : 'bg-white/50'
              }`} />
              <span className="text-white/80">{integrationName}</span>
            </div>
          </div>
          <div>
            <div className="text-[10px] text-white/30 uppercase tracking-wider mb-1">Scan Type</div>
            <div className="text-white/80 capitalize">{scanType.replace(/_/g, ' ')}</div>
          </div>
          <div>
            <div className="text-[10px] text-white/30 uppercase tracking-wider mb-1">Duration</div>
            <div className="text-white/80 font-mono">{(duration / 1000).toFixed(2)}s</div>
          </div>
          <div>
            <div className="text-[10px] text-white/30 uppercase tracking-wider mb-1">Scan ID</div>
            <div className="text-white/50 font-mono text-xs truncate">{scanId.slice(0, 12)}...</div>
          </div>
        </div>

        {/* Expanded config */}
        {showConfig && scanConfig && (
          <div className="mt-4 pt-4 border-t border-white/5">
            <div className="text-[10px] text-white/30 uppercase tracking-wider mb-2">Scan Configuration</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              {scanConfig.freshnessThreshold && (
                <div className="p-2 rounded bg-white/[0.02]">
                  <div className="text-white/40">Freshness SLO</div>
                  <div className="text-white/80 font-mono">{scanConfig.freshnessThreshold}h</div>
                </div>
              )}
              {scanConfig.nullRateThreshold && (
                <div className="p-2 rounded bg-white/[0.02]">
                  <div className="text-white/40">Null Threshold</div>
                  <div className="text-white/80 font-mono">{(scanConfig.nullRateThreshold * 100).toFixed(0)}%</div>
                </div>
              )}
              {scanConfig.duplicateThreshold && (
                <div className="p-2 rounded bg-white/[0.02]">
                  <div className="text-white/40">Duplicate Threshold</div>
                  <div className="text-white/80 font-mono">{(scanConfig.duplicateThreshold * 100).toFixed(0)}%</div>
                </div>
              )}
              {scanConfig.samplingEnabled && (
                <div className="p-2 rounded bg-white/[0.02]">
                  <div className="text-white/40">Sample Size</div>
                  <div className="text-white/80 font-mono">{formatNumber(scanConfig.sampleSize || 0)}</div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Expanded log */}
        {showLog && scanLog.length > 0 && (
          <div className="mt-4 pt-4 border-t border-white/5">
            <div className="text-[10px] text-white/30 uppercase tracking-wider mb-2">Scan Log</div>
            <div className="bg-black/30 rounded-lg p-3 max-h-48 overflow-y-auto">
              <TypewriterLog lines={scanLog} speed={10} />
            </div>
          </div>
        )}
      </div>

      {/* Data Overview */}
      <div className="bg-white/[0.02] border border-white/5 rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="text-xs text-white/40">Data Scanned</div>
          <div className="flex items-center gap-1">
            {(['grid', 'list', 'compact'] as const).map(mode => (
              <button
                key={mode}
                onClick={() => setViewMode(mode)}
                className={`p-1.5 rounded transition-colors ${
                  viewMode === mode ? 'bg-white/10 text-white' : 'text-white/30 hover:text-white/50'
                }`}
              >
                {mode === 'grid' ? (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                  </svg>
                ) : mode === 'list' ? (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
                  </svg>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          <div className="text-center p-3 rounded-lg bg-white/[0.02]">
            <div className="text-2xl font-light text-white/90">{tablesScanned}</div>
            <div className="text-[10px] text-white/40 uppercase">Tables</div>
          </div>
          <div className="text-center p-3 rounded-lg bg-white/[0.02]">
            <div className="text-2xl font-light text-white/90">{formatNumber(totalRows)}</div>
            <div className="text-[10px] text-white/40 uppercase">Rows</div>
          </div>
          {totalColumns && (
            <div className="text-center p-3 rounded-lg bg-white/[0.02]">
              <div className="text-2xl font-light text-white/90">{totalColumns}</div>
              <div className="text-[10px] text-white/40 uppercase">Columns</div>
            </div>
          )}
          {database && (
            <div className="text-center p-3 rounded-lg bg-white/[0.02]">
              <div className="text-sm font-mono text-white/70 truncate">{database}</div>
              <div className="text-[10px] text-white/40 uppercase">Database</div>
            </div>
          )}
        </div>

        {/* Table details */}
        {tableDetails.length > 0 && (
          <div className={viewMode === 'grid' ? 'grid grid-cols-2 md:grid-cols-3 gap-2' : 'space-y-1'}>
            {tableDetails.map((table, idx) => (
              <div
                key={idx}
                className={`rounded-lg transition-colors hover:bg-white/[0.02] ${
                  viewMode === 'compact' ? 'flex items-center gap-2 px-2 py-1' : 'p-3 bg-white/[0.01]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${getSeverityColor(table.severity)}`} />
                  <span className="font-mono text-xs text-white/70 truncate">
                    {table.name.split('.').pop()}
                  </span>
                </div>
                {viewMode !== 'compact' && (
                  <div className="mt-2 flex items-center gap-3 text-[10px] text-white/40">
                    <span>{formatNumber(table.rows)} rows</span>
                    <span>{table.columns} cols</span>
                    {table.issues > 0 && (
                      <span className="text-amber-400">{table.issues} issues</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
