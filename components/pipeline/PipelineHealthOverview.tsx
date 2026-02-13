'use client';

/**
 * Pipeline Health Overview
 * 
 * Shows health status across all 4 layers of the data pipeline:
 * - Ingestion (Fivetran, Airbyte)
 * - Transformation (dbt)
 * - Warehouse (Snowflake, BigQuery, etc.)
 * - Reporting (Looker, Tableau, etc.)
 */

import { useState } from 'react';
import { 
  ArrowDownToLine, 
  Wand2, 
  Database, 
  BarChart3,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  ChevronRight,
  Activity
} from 'lucide-react';
import { LAYER_COLORS, PipelineLayer } from './types';

interface LayerHealth {
  layer: PipelineLayer;
  name: string;
  icon: React.ReactNode;
  status: 'healthy' | 'warning' | 'critical' | 'unknown';
  healthScore: number;
  nodeCount: number;
  findingsCount: number;
  criticalCount: number;
  lastScanned?: string;
  trend?: 'up' | 'down' | 'stable';
}

interface CrossLayerCorrelation {
  id: string;
  type: string;
  description: string;
  upstreamLayer: string;
  downstreamLayer: string;
  cause: string;
  effect: string;
  severity: 'high' | 'medium' | 'low';
}

interface PipelineHealthOverviewProps {
  layerHealth: LayerHealth[];
  correlations: CrossLayerCorrelation[];
  overallScore: number;
  overallStatus: 'healthy' | 'warning' | 'critical';
  lastScanTime?: string;
  onLayerClick?: (layer: PipelineLayer) => void;
  onViewDetails?: () => void;
}

const LAYER_ICONS: Partial<Record<PipelineLayer, React.ReactNode>> = {
  INGESTION: <ArrowDownToLine className="w-5 h-5" />,
  TRANSFORMATION: <Wand2 className="w-5 h-5" />,
  WAREHOUSE: <Database className="w-5 h-5" />,
  REPORTING: <BarChart3 className="w-5 h-5" />,
};

const LAYER_NAMES: Partial<Record<PipelineLayer, string>> = {
  INGESTION: 'Ingestion',
  TRANSFORMATION: 'Transformation',
  WAREHOUSE: 'Warehouse',
  REPORTING: 'Reporting',
};

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'healthy':
      return <CheckCircle2 className="w-5 h-5 text-emerald-400" />;
    case 'warning':
      return <AlertTriangle className="w-5 h-5 text-amber-400" />;
    case 'critical':
      return <XCircle className="w-5 h-5 text-red-400" />;
    default:
      return <Minus className="w-5 h-5 text-gray-400" />;
  }
}

function TrendIcon({ trend }: { trend?: string }) {
  switch (trend) {
    case 'up':
      return <TrendingUp className="w-4 h-4 text-emerald-400" />;
    case 'down':
      return <TrendingDown className="w-4 h-4 text-red-400" />;
    default:
      return <Minus className="w-4 h-4 text-gray-400" />;
  }
}

function HealthScoreRing({ score, size = 80 }: { score: number; size?: number }) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  
  let color = '#10B981'; // Green
  if (score < 70) color = '#F59E0B'; // Amber
  if (score < 50) color = '#EF4444'; // Red
  
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg className="transform -rotate-90" style={{ width: size, height: size }}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.1)"
          strokeWidth="4"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-1000"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-2xl font-bold">{Math.round(score)}</span>
      </div>
    </div>
  );
}

export default function PipelineHealthOverview({
  layerHealth,
  correlations,
  overallScore,
  overallStatus,
  lastScanTime,
  onLayerClick,
  onViewDetails,
}: PipelineHealthOverviewProps) {
  const [expandedCorrelation, setExpandedCorrelation] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      {/* Overall Health Summary */}
      <div className="dashboard-card p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <Activity className="w-5 h-5 text-[var(--accent)]" />
              Pipeline Health
            </h2>
            <p className="text-sm text-[var(--muted)] mt-1">
              Cross-layer data observability
              {lastScanTime && ` • Last scan: ${lastScanTime}`}
            </p>
          </div>
          
          <div className="flex items-center gap-6">
            <HealthScoreRing score={overallScore} />
            
            {onViewDetails && (
              <button 
                onClick={onViewDetails}
                className="btn btn-secondary"
              >
                View Details
                <ChevronRight className="w-4 h-4 ml-1" />
              </button>
            )}
          </div>
        </div>

        {/* Layer Health Cards */}
        <div className="grid grid-cols-4 gap-4">
          {layerHealth.map((layer) => (
            <button
              key={layer.layer}
              onClick={() => onLayerClick?.(layer.layer)}
              className="relative group p-4 rounded-lg border border-white/5 bg-white/[0.02] hover:bg-white/[0.05] transition-all cursor-pointer"
            >
              {/* Colored accent line */}
              <div 
                className="absolute top-0 left-0 right-0 h-1 rounded-t-lg"
                style={{ backgroundColor: LAYER_COLORS[layer.layer] }}
              />
              
              <div className="flex items-center justify-between mb-3 mt-1">
                <div 
                  className="p-2 rounded-lg"
                  style={{ backgroundColor: `${LAYER_COLORS[layer.layer]}20` }}
                >
                  <div style={{ color: LAYER_COLORS[layer.layer] }}>
                    {LAYER_ICONS[layer.layer]}
                  </div>
                </div>
                <StatusIcon status={layer.status} />
              </div>
              
              <h3 className="font-medium text-white">
                {LAYER_NAMES[layer.layer]}
              </h3>
              
              <div className="mt-3 space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-[var(--muted)]">Health</span>
                  <span className="font-medium">{layer.healthScore}%</span>
                </div>
                
                <div className="flex items-center justify-between text-sm">
                  <span className="text-[var(--muted)]">Nodes</span>
                  <span className="font-medium">{layer.nodeCount}</span>
                </div>
                
                {layer.findingsCount > 0 && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[var(--muted)]">Findings</span>
                    <span className={layer.criticalCount > 0 ? 'text-red-400 font-medium' : 'font-medium'}>
                      {layer.findingsCount}
                      {layer.criticalCount > 0 && ` (${layer.criticalCount} critical)`}
                    </span>
                  </div>
                )}
              </div>
              
              {layer.trend && (
                <div className="absolute top-3 right-3">
                  <TrendIcon trend={layer.trend} />
                </div>
              )}
              
              {/* Hover effect */}
              <div className="absolute inset-0 rounded-lg ring-1 ring-inset ring-white/0 group-hover:ring-white/10 transition-all" />
            </button>
          ))}
        </div>
      </div>

      {/* Cross-Layer Correlations */}
      {correlations.length > 0 && (
        <div className="dashboard-card p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <svg className="w-5 h-5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Cross-Layer Correlations
            <span className="text-sm font-normal text-[var(--muted)] ml-2">
              Issues that cascade across layers
            </span>
          </h3>
          
          <div className="space-y-3">
            {correlations.map((corr) => (
              <div
                key={corr.id}
                className="p-4 rounded-lg border border-white/5 bg-white/[0.02]"
              >
                <button
                  onClick={() => setExpandedCorrelation(
                    expandedCorrelation === corr.id ? null : corr.id
                  )}
                  className="w-full flex items-center justify-between"
                >
                  <div className="flex items-center gap-3">
                    <div className={`px-2 py-1 rounded text-xs font-medium ${
                      corr.severity === 'high' ? 'bg-red-500/20 text-red-400' :
                      corr.severity === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                      'bg-blue-500/20 text-blue-400'
                    }`}>
                      {corr.type.replace('_', ' ').toUpperCase()}
                    </div>
                    
                    <div className="flex items-center gap-2 text-sm">
                      <span className="font-medium">{corr.upstreamLayer}</span>
                      <ChevronRight className="w-4 h-4 text-[var(--muted)]" />
                      <span className="font-medium">{corr.downstreamLayer}</span>
                    </div>
                  </div>
                  
                  <ChevronRight className={`w-5 h-5 text-[var(--muted)] transition-transform ${
                    expandedCorrelation === corr.id ? 'rotate-90' : ''
                  }`} />
                </button>
                
                {expandedCorrelation === corr.id && (
                  <div className="mt-4 pt-4 border-t border-white/5 space-y-3">
                    <p className="text-sm text-[var(--muted)]">{corr.description}</p>
                    
                    <div className="grid grid-cols-2 gap-4">
                      <div className="p-3 rounded bg-red-500/10 border border-red-500/20">
                        <div className="text-xs text-red-400 mb-1">Root Cause</div>
                        <div className="text-sm">{corr.cause}</div>
                      </div>
                      
                      <div className="p-3 rounded bg-amber-500/10 border border-amber-500/20">
                        <div className="text-xs text-amber-400 mb-1">Impact</div>
                        <div className="text-sm">{corr.effect}</div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data Flow Visualization */}
      <div className="dashboard-card p-6">
        <h3 className="text-lg font-semibold mb-4">Data Flow</h3>
        
        <div className="flex items-center justify-between px-8">
          {layerHealth.map((layer, index) => (
            <div key={layer.layer} className="flex items-center">
              {/* Node */}
              <div className="flex flex-col items-center">
                <div 
                  className="w-16 h-16 rounded-full flex items-center justify-center"
                  style={{ 
                    backgroundColor: `${LAYER_COLORS[layer.layer]}20`,
                    border: `2px solid ${LAYER_COLORS[layer.layer]}`,
                  }}
                >
                  <div style={{ color: LAYER_COLORS[layer.layer] }}>
                    {LAYER_ICONS[layer.layer]}
                  </div>
                </div>
                
                <div className="mt-2 text-center">
                  <div className="text-sm font-medium">{LAYER_NAMES[layer.layer]}</div>
                  <div className={`text-xs ${
                    layer.status === 'healthy' ? 'text-emerald-400' :
                    layer.status === 'warning' ? 'text-amber-400' :
                    layer.status === 'critical' ? 'text-red-400' :
                    'text-gray-400'
                  }`}>
                    {layer.healthScore}% healthy
                  </div>
                </div>
              </div>
              
              {/* Arrow between nodes */}
              {index < layerHealth.length - 1 && (
                <div className="flex-1 mx-4 flex items-center">
                  <div className="flex-1 h-0.5 bg-gradient-to-r from-white/20 to-white/10" />
                  <ChevronRight className="w-5 h-5 text-white/30 mx-1" />
                  <div className="flex-1 h-0.5 bg-gradient-to-r from-white/10 to-white/20" />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
