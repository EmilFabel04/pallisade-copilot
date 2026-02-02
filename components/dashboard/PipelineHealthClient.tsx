'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Database, 
  GitBranch, 
  Download, 
  BarChart3, 
  CheckCircle, 
  AlertTriangle, 
  XCircle, 
  RefreshCw,
  ArrowRight,
  Layers
} from 'lucide-react';

interface LayerHealth {
  score: number;
  status: string;
  nodeCount: number;
  errorCount: number;
  tools: string[];
}

interface PipelineHealthData {
  hasStack: boolean;
  overallScore: number;
  overallStatus: string;
  layerHealth: Record<string, LayerHealth>;
  totalNodes: number;
  totalErrors: number;
  stacks: Array<{
    id: string;
    name: string;
    healthScore: number;
    status: string;
    nodeCount: number;
    lastScanAt: string | null;
  }>;
}

const LAYER_CONFIG: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
  INGESTION: { 
    icon: <Download className="w-4 h-4" />, 
    label: 'Ingestion', 
    color: 'from-blue-500/20 to-blue-600/10' 
  },
  TRANSFORMATION: { 
    icon: <GitBranch className="w-4 h-4" />, 
    label: 'Transformation', 
    color: 'from-purple-500/20 to-purple-600/10' 
  },
  WAREHOUSE: { 
    icon: <Database className="w-4 h-4" />, 
    label: 'Warehouse', 
    color: 'from-emerald-500/20 to-emerald-600/10' 
  },
  REPORTING: { 
    icon: <BarChart3 className="w-4 h-4" />, 
    label: 'Reporting', 
    color: 'from-orange-500/20 to-orange-600/10' 
  },
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'HEALTHY':
    case 'CONNECTED':
    case 'ACTIVE':
      return <CheckCircle className="w-4 h-4 text-emerald-400" />;
    case 'WARNING':
    case 'PENDING':
      return <AlertTriangle className="w-4 h-4 text-amber-400" />;
    case 'ERROR':
      return <XCircle className="w-4 h-4 text-red-400" />;
    default:
      return <div className="w-4 h-4 rounded-full bg-gray-500/50" />;
  }
};

const getScoreColor = (score: number) => {
  if (score >= 80) return 'text-emerald-400';
  if (score >= 50) return 'text-amber-400';
  return 'text-red-400';
};

const getScoreBg = (score: number) => {
  if (score >= 80) return 'bg-emerald-500/10 border-emerald-500/30';
  if (score >= 50) return 'bg-amber-500/10 border-amber-500/30';
  return 'bg-red-500/10 border-red-500/30';
};

export function PipelineHealthClient() {
  const [data, setData] = useState<PipelineHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    
    try {
      const response = await fetch('/api/pipeline/health');
      if (response.ok) {
        const result = await response.json();
        setData(result);
      }
    } catch (error) {
      console.error('Failed to fetch pipeline health:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Loading state
  if (loading) {
    return (
      <div className="dashboard-card p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-[var(--accent-2)]" />
            <h3 className="font-semibold">Pipeline Health</h3>
          </div>
        </div>
        <div className="flex items-center justify-center py-8">
          <RefreshCw className="w-5 h-5 animate-spin text-[var(--muted)]" />
          <span className="ml-2 text-[var(--muted)]">Loading pipeline health...</span>
        </div>
      </div>
    );
  }

  // No pipeline configured
  if (!data?.hasStack) {
    return (
      <div className="dashboard-card p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-[var(--accent-2)]" />
            <h3 className="font-semibold">Pipeline Health</h3>
          </div>
        </div>
        <div className="text-center py-6">
          <div className="w-12 h-12 rounded-xl bg-[rgba(255,255,255,0.03)] flex items-center justify-center mx-auto mb-3">
            <Layers className="w-6 h-6 text-[var(--muted)]" />
          </div>
          <p className="text-[var(--muted)] mb-4">No data pipeline configured yet</p>
          <Link 
            href="/dashboard/pipeline" 
            className="inline-flex items-center gap-2 text-sm text-[var(--accent-2)] hover:underline"
          >
            Configure your pipeline
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    );
  }

  const { overallScore, overallStatus, layerHealth, totalNodes, totalErrors, stacks } = data;

  return (
    <div className="dashboard-card p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-[var(--accent-2)]" />
          <h3 className="font-semibold">Pipeline Health</h3>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => fetchData(true)}
            disabled={refreshing}
            className="p-1.5 rounded-lg hover:bg-[rgba(255,255,255,0.05)] transition-colors disabled:opacity-50"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 text-[var(--muted)] ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <Link href="/dashboard/pipeline" className="text-sm text-[var(--accent-2)] hover:underline">
            View Pipeline →
          </Link>
        </div>
      </div>

      {/* Overall Score & Stats */}
      <div className="flex items-center gap-6 mb-6">
        <div className={`w-16 h-16 rounded-xl border flex items-center justify-center ${getScoreBg(overallScore)}`}>
          <span className={`text-2xl font-bold ${getScoreColor(overallScore)}`}>
            {overallScore}
          </span>
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            {getStatusIcon(overallStatus)}
            <span className="font-medium">
              {overallStatus === 'HEALTHY' ? 'Pipeline Healthy' :
               overallStatus === 'WARNING' ? 'Issues Detected' :
               overallStatus === 'ERROR' ? 'Critical Issues' : 'Not Configured'}
            </span>
          </div>
          <div className="text-sm text-[var(--muted)]">
            {totalNodes} nodes · {totalErrors} {totalErrors === 1 ? 'issue' : 'issues'} · {stacks.length} {stacks.length === 1 ? 'stack' : 'stacks'}
          </div>
        </div>
      </div>

      {/* Layer Health Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Object.entries(LAYER_CONFIG).map(([layer, config]) => {
          const health = layerHealth[layer];
          const isConfigured = health && health.nodeCount > 0;

          return (
            <div 
              key={layer}
              className={`relative rounded-lg border border-[rgba(255,255,255,0.06)] overflow-hidden ${
                isConfigured ? 'bg-gradient-to-br ' + config.color : 'bg-[rgba(255,255,255,0.02)]'
              }`}
            >
              <div className="p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    {config.icon}
                    <span>{config.label}</span>
                  </div>
                  {isConfigured && getStatusIcon(health.status)}
                </div>
                
                {isConfigured ? (
                  <>
                    <div className={`text-xl font-bold ${getScoreColor(health.score)}`}>
                      {health.score}%
                    </div>
                    <div className="text-xs text-[var(--muted)] mt-1">
                      {health.nodeCount} {health.nodeCount === 1 ? 'node' : 'nodes'}
                      {health.errorCount > 0 && (
                        <span className="text-red-400"> · {Math.round(health.errorCount)} issues</span>
                      )}
                    </div>
                    {health.tools.length > 0 && (
                      <div className="text-xs text-[var(--muted)] mt-1 truncate">
                        {health.tools.slice(0, 2).join(', ')}
                        {health.tools.length > 2 && ` +${health.tools.length - 2}`}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-xs text-[var(--muted)]">
                    Not configured
                  </div>
                )}
              </div>
              
              {/* Score bar */}
              {isConfigured && (
                <div className="h-1 bg-[rgba(0,0,0,0.2)]">
                  <div 
                    className={`h-full transition-all ${
                      health.score >= 80 ? 'bg-emerald-500' :
                      health.score >= 50 ? 'bg-amber-500' : 'bg-red-500'
                    }`}
                    style={{ width: `${health.score}%` }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Stack List (if multiple) */}
      {stacks.length > 1 && (
        <div className="mt-4 pt-4 border-t border-[rgba(255,255,255,0.06)]">
          <div className="text-xs text-[var(--muted)] uppercase tracking-wide mb-2">Pipeline Stacks</div>
          <div className="space-y-2">
            {stacks.slice(0, 3).map(stack => (
              <Link
                key={stack.id}
                href={`/dashboard/pipeline?stack=${stack.id}`}
                className="flex items-center gap-3 p-2 rounded-lg hover:bg-[rgba(255,255,255,0.03)] transition-colors"
              >
                <div className={`w-8 h-8 rounded flex items-center justify-center ${getScoreBg(stack.healthScore)}`}>
                  <span className={`text-sm font-bold ${getScoreColor(stack.healthScore)}`}>
                    {stack.healthScore}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{stack.name}</div>
                  <div className="text-xs text-[var(--muted)]">
                    {stack.nodeCount} nodes
                    {stack.lastScanAt && ` · Last scan ${new Date(stack.lastScanAt).toLocaleDateString()}`}
                  </div>
                </div>
                <ArrowRight className="w-4 h-4 text-[var(--muted)]" />
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
