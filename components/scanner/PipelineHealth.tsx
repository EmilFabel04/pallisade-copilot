'use client';

import { useState, useEffect } from 'react';

interface DbtStats {
  totalModels: number;
  testedModels: number;
  documentedModels: number;
  sourcesWithFreshness: number;
  totalSources: number;
}

interface AirflowDAG {
  dagId: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  successRate: number;
  lastRun: string;
  avgDuration: number;
}

interface FivetranConnector {
  id: string;
  name: string;
  service: string;
  status: 'connected' | 'paused' | 'broken';
  lastSync: string;
  hoursSinceSync: number;
  isStale: boolean;
}

interface PipelineHealthProps {
  dbt?: DbtStats;
  airflowDAGs?: AirflowDAG[];
  fivetranConnectors?: FivetranConnector[];
  loading?: boolean;
  onRefresh?: () => void;
}

export function PipelineHealth({
  dbt,
  airflowDAGs = [],
  fivetranConnectors = [],
  loading = false,
  onRefresh,
}: PipelineHealthProps) {
  const [activeTab, setActiveTab] = useState<'dbt' | 'airflow' | 'fivetran'>('dbt');

  const statusColors = {
    healthy: 'bg-green-500',
    connected: 'bg-green-500',
    degraded: 'bg-amber-500',
    paused: 'bg-gray-500',
    unhealthy: 'bg-red-500',
    broken: 'bg-red-500',
  };

  const testCoverage = dbt ? (dbt.testedModels / dbt.totalModels) * 100 : 0;
  const docCoverage = dbt ? (dbt.documentedModels / dbt.totalModels) * 100 : 0;
  const freshnessCoverage = dbt && dbt.totalSources > 0 
    ? (dbt.sourcesWithFreshness / dbt.totalSources) * 100 
    : 0;

  const healthyDAGs = airflowDAGs.filter(d => d.status === 'healthy').length;
  const healthyConnectors = fivetranConnectors.filter(c => c.status === 'connected' && !c.isStale).length;

  return (
    <div className="bg-[var(--card-bg)] rounded-lg border border-[var(--border-dim)]">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--border-dim)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-[var(--accent)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <span className="text-sm font-medium text-white">Pipeline Health</span>
        </div>
        
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={loading}
            className="p-1.5 rounded hover:bg-white/5 transition-colors disabled:opacity-50"
          >
            <svg 
              className={`w-4 h-4 text-[var(--muted)] ${loading ? 'animate-spin' : ''}`} 
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        )}
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-3 gap-px bg-[var(--border-dim)]">
        <div className="bg-[var(--card-bg)] p-3 text-center">
          <p className="text-lg font-bold text-white">{testCoverage.toFixed(0)}%</p>
          <p className="text-xs text-[var(--muted)]">dbt Test Coverage</p>
        </div>
        <div className="bg-[var(--card-bg)] p-3 text-center">
          <p className="text-lg font-bold text-white">{healthyDAGs}/{airflowDAGs.length}</p>
          <p className="text-xs text-[var(--muted)]">Healthy DAGs</p>
        </div>
        <div className="bg-[var(--card-bg)] p-3 text-center">
          <p className="text-lg font-bold text-white">{healthyConnectors}/{fivetranConnectors.length}</p>
          <p className="text-xs text-[var(--muted)]">Healthy Connectors</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[var(--border-dim)]">
        {[
          { key: 'dbt', label: 'dbt', icon: '🔧' },
          { key: 'airflow', label: 'Airflow', icon: '🌀' },
          { key: 'fivetran', label: 'Fivetran', icon: '🔌' },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as typeof activeTab)}
            className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
              activeTab === tab.key
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] -mb-px'
                : 'text-[var(--muted)] hover:text-white'
            }`}
          >
            <span className="mr-1">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="p-4">
        {/* dbt Tab */}
        {activeTab === 'dbt' && (
          <div className="space-y-3">
            {dbt ? (
              <>
                {/* Coverage bars */}
                <div className="space-y-2">
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[var(--muted)]">Test Coverage</span>
                      <span className={testCoverage >= 80 ? 'text-green-400' : testCoverage >= 50 ? 'text-amber-400' : 'text-red-400'}>
                        {testCoverage.toFixed(0)}%
                      </span>
                    </div>
                    <div className="h-2 bg-black/20 rounded-full overflow-hidden">
                      <div 
                        className={`h-full rounded-full transition-all ${
                          testCoverage >= 80 ? 'bg-green-500' : testCoverage >= 50 ? 'bg-amber-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${testCoverage}%` }}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[var(--muted)]">Documentation</span>
                      <span className={docCoverage >= 80 ? 'text-green-400' : docCoverage >= 50 ? 'text-amber-400' : 'text-red-400'}>
                        {docCoverage.toFixed(0)}%
                      </span>
                    </div>
                    <div className="h-2 bg-black/20 rounded-full overflow-hidden">
                      <div 
                        className={`h-full rounded-full transition-all ${
                          docCoverage >= 80 ? 'bg-green-500' : docCoverage >= 50 ? 'bg-amber-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${docCoverage}%` }}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[var(--muted)]">Freshness SLOs</span>
                      <span className={freshnessCoverage >= 80 ? 'text-green-400' : freshnessCoverage >= 50 ? 'text-amber-400' : 'text-red-400'}>
                        {freshnessCoverage.toFixed(0)}%
                      </span>
                    </div>
                    <div className="h-2 bg-black/20 rounded-full overflow-hidden">
                      <div 
                        className={`h-full rounded-full transition-all ${
                          freshnessCoverage >= 80 ? 'bg-green-500' : freshnessCoverage >= 50 ? 'bg-amber-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${freshnessCoverage}%` }}
                      />
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 pt-2">
                  <div className="bg-black/20 rounded-lg p-2.5 text-center">
                    <p className="text-sm font-medium text-white">{dbt.totalModels}</p>
                    <p className="text-xs text-[var(--muted)]">Models</p>
                  </div>
                  <div className="bg-black/20 rounded-lg p-2.5 text-center">
                    <p className="text-sm font-medium text-white">{dbt.totalSources}</p>
                    <p className="text-xs text-[var(--muted)]">Sources</p>
                  </div>
                </div>
              </>
            ) : (
              <div className="text-center py-4">
                <p className="text-sm text-[var(--muted)]">No dbt project connected</p>
                <button className="mt-2 text-xs text-[var(--accent)] hover:underline">
                  Connect dbt →
                </button>
              </div>
            )}
          </div>
        )}

        {/* Airflow Tab */}
        {activeTab === 'airflow' && (
          <div className="space-y-2">
            {airflowDAGs.length > 0 ? (
              airflowDAGs.map((dag) => (
                <div key={dag.dagId} className="bg-black/20 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${statusColors[dag.status]}`} />
                      <span className="text-sm font-medium text-white">{dag.dagId}</span>
                    </div>
                    <span className={`text-xs ${
                      dag.successRate >= 90 ? 'text-green-400' : dag.successRate >= 75 ? 'text-amber-400' : 'text-red-400'
                    }`}>
                      {dag.successRate.toFixed(0)}% success
                    </span>
                  </div>
                  <div className="flex justify-between text-xs text-[var(--muted)]">
                    <span>Avg: {dag.avgDuration.toFixed(0)}m</span>
                    <span>Last: {dag.lastRun}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-4">
                <p className="text-sm text-[var(--muted)]">No Airflow DAGs connected</p>
                <button className="mt-2 text-xs text-[var(--accent)] hover:underline">
                  Connect Airflow →
                </button>
              </div>
            )}
          </div>
        )}

        {/* Fivetran Tab */}
        {activeTab === 'fivetran' && (
          <div className="space-y-2">
            {fivetranConnectors.length > 0 ? (
              fivetranConnectors.map((connector) => (
                <div key={connector.id} className="bg-black/20 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${
                        connector.isStale ? 'bg-amber-500' : statusColors[connector.status]
                      }`} />
                      <span className="text-sm font-medium text-white">{connector.name}</span>
                      <span className="text-xs text-[var(--muted)]">({connector.service})</span>
                    </div>
                    {connector.isStale && (
                      <span className="px-1.5 py-0.5 bg-amber-500/20 text-amber-400 text-xs rounded">
                        Stale
                      </span>
                    )}
                  </div>
                  <div className="flex justify-between text-xs text-[var(--muted)]">
                    <span>Status: {connector.status}</span>
                    <span>{connector.hoursSinceSync.toFixed(1)}h ago</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-4">
                <p className="text-sm text-[var(--muted)]">No Fivetran connectors connected</p>
                <button className="mt-2 text-xs text-[var(--accent)] hover:underline">
                  Connect Fivetran →
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

