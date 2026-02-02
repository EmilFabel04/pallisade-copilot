'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { toast } from 'sonner';

interface Finding {
  id: string;
  title: string;
  severity: string;
  type?: string;
  category?: string;
  scan_type?: string;
  description?: string;
  table?: string;
  column?: string;
  has_auto_fix?: boolean;
  auto_fix?: {
    type: string;
    code?: string;
    steps?: string[];
    description?: string;
  };
  ai_context?: {
    table?: string;
    timestamp_column?: string;
    last_update?: string;
    hours_stale?: number;
    slo_hours?: number;
    total_rows?: number;
    null_rate?: number;
    duplicate_rate?: number;
    outlier_count?: number;
    min_value?: number;
    max_value?: number;
    avg_value?: number;
    std_dev?: number;
    possible_causes?: string[];
    impact_assessment?: {
      is_critical_table?: boolean;
      potential_impacts?: string[];
      severity_reason?: string;
    };
    recommended_actions?: Array<{
      priority: string;
      action: string;
      reason: string;
    }>;
    distribution?: Array<{ bucket: string; count: number }>;
    trend_data?: Array<{ timestamp: string; value: number }>;
  };
  metrics?: {
    current_value?: number;
    threshold?: number;
    historical_values?: Array<{ timestamp: string; value: number }>;
  };
}

interface FindingDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  finding: Finding | null;
  onShowFix?: () => void;
  businessImpact?: {
    dataTier?: string;
    criticality?: string;
    stakeholders?: string[];
    usedInReports?: string[];
    businessImpact?: string;
    owner?: string;
    priority?: string;
    lineage?: {
      downstreamCount: number;
      downstreamTables: string[];
    };
  };
}

const severityConfig: Record<string, { bg: string; text: string; gradient: string; icon: string }> = {
  critical: { 
    bg: 'bg-red-500/15', 
    text: 'text-red-400', 
    gradient: 'from-red-500 to-red-600',
    icon: '🔴'
  },
  high: { 
    bg: 'bg-amber-500/15', 
    text: 'text-amber-400', 
    gradient: 'from-amber-500 to-orange-600',
    icon: '🟠'
  },
  medium: { 
    bg: 'bg-blue-500/15', 
    text: 'text-blue-400', 
    gradient: 'from-blue-500 to-cyan-600',
    icon: '🟡'
  },
  low: { 
    bg: 'bg-emerald-500/15', 
    text: 'text-emerald-400', 
    gradient: 'from-emerald-500 to-teal-600',
    icon: '🟢'
  },
};

// Simple bar chart component
function BarChart({ 
  data, 
  label,
  color = '#8b5cf6'
}: { 
  data: Array<{ bucket: string; count: number }>; 
  label: string;
  color?: string;
}) {
  if (!data || data.length === 0) return null;
  
  const maxValue = Math.max(...data.map(d => d.count));
  
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider">{label}</div>
      <div className="space-y-1.5">
        {data.map((item, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-xs text-[var(--muted)] w-16 truncate" title={item.bucket}>{item.bucket}</span>
            <div className="flex-1 h-5 bg-[rgba(255,255,255,0.05)] rounded overflow-hidden">
              <div 
                className="h-full rounded transition-all duration-500"
                style={{ 
                  width: `${(item.count / maxValue) * 100}%`,
                  backgroundColor: color
                }}
              />
            </div>
            <span className="text-xs font-mono w-10 text-right">{item.count.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Simple line chart component
function LineChart({ 
  data, 
  label,
  threshold,
  yLabel = 'Value',
  color = '#10b981'
}: { 
  data: Array<{ timestamp: string; value: number }>; 
  label: string;
  threshold?: number;
  yLabel?: string;
  color?: string;
}) {
  if (!data || data.length === 0) return null;
  
  const minValue = Math.min(...data.map(d => d.value));
  const maxValue = Math.max(...data.map(d => d.value), threshold || 0);
  const range = maxValue - minValue || 1;
  
  // Create SVG path
  const width = 300;
  const height = 100;
  const padding = 10;
  
  const points = data.map((d, i) => ({
    x: padding + (i / (data.length - 1 || 1)) * (width - 2 * padding),
    y: height - padding - ((d.value - minValue) / range) * (height - 2 * padding),
  }));
  
  const pathD = points.reduce((acc, point, i) => {
    if (i === 0) return `M ${point.x} ${point.y}`;
    return `${acc} L ${point.x} ${point.y}`;
  }, '');
  
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider">{label}</span>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
            {yLabel}
          </span>
          {threshold && (
            <span className="flex items-center gap-1">
              <span className="w-2 h-0.5 bg-red-400" />
              Threshold
            </span>
          )}
        </div>
      </div>
      <div className="relative bg-[rgba(0,0,0,0.3)] rounded-lg p-2 overflow-hidden">
        <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
          {/* Grid lines */}
          {[0.25, 0.5, 0.75].map(ratio => (
            <line 
              key={ratio}
              x1={padding} 
              y1={height - padding - ratio * (height - 2 * padding)} 
              x2={width - padding} 
              y2={height - padding - ratio * (height - 2 * padding)}
              stroke="rgba(255,255,255,0.05)"
              strokeDasharray="4 4"
            />
          ))}
          
          {/* Threshold line */}
          {threshold && (
            <line 
              x1={padding} 
              y1={height - padding - ((threshold - minValue) / range) * (height - 2 * padding)} 
              x2={width - padding} 
              y2={height - padding - ((threshold - minValue) / range) * (height - 2 * padding)}
              stroke="#ef4444"
              strokeWidth={1.5}
              strokeDasharray="4 4"
            />
          )}
          
          {/* Area fill */}
          <path 
            d={`${pathD} L ${points[points.length - 1]?.x || padding} ${height - padding} L ${padding} ${height - padding} Z`}
            fill={`${color}20`}
          />
          
          {/* Line */}
          <path 
            d={pathD}
            fill="none"
            stroke={color}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          
          {/* Points */}
          {points.map((point, i) => (
            <circle 
              key={i}
              cx={point.x}
              cy={point.y}
              r={3}
              fill={color}
              className="transition-all hover:r-4"
            />
          ))}
        </svg>
        
        {/* X-axis labels */}
        <div className="flex justify-between mt-1 text-[10px] text-[var(--muted)]">
          {data.length > 0 && (
            <>
              <span>{new Date(data[0].timestamp).toLocaleDateString()}</span>
              <span>{new Date(data[data.length - 1].timestamp).toLocaleDateString()}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Gauge chart component
function GaugeChart({
  value,
  threshold,
  maxValue = 100,
  label,
  unit = '%',
  invertColors = false,
}: {
  value: number;
  threshold?: number;
  maxValue?: number;
  label: string;
  unit?: string;
  invertColors?: boolean;
}) {
  const percentage = Math.min((value / maxValue) * 100, 100);
  const isAboveThreshold = threshold !== undefined && value > threshold;
  
  let color = '#10b981'; // green
  if (invertColors) {
    if (percentage > 50) color = '#ef4444';
    else if (percentage > 25) color = '#f59e0b';
    else color = '#10b981';
  } else {
    if (percentage > 75) color = '#10b981';
    else if (percentage > 50) color = '#f59e0b';
    else color = '#ef4444';
  }
  
  if (isAboveThreshold) color = '#ef4444';
  
  return (
    <div className="flex flex-col items-center">
      <div className="relative w-20 h-20">
        <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
          <circle
            cx="18"
            cy="18"
            r="15.915"
            fill="none"
            stroke="rgba(255,255,255,0.05)"
            strokeWidth="3"
          />
          <circle
            cx="18"
            cy="18"
            r="15.915"
            fill="none"
            stroke={color}
            strokeWidth="3"
            strokeDasharray={`${percentage} ${100 - percentage}`}
            strokeLinecap="round"
            className="transition-all duration-1000"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-bold" style={{ color }}>{value.toFixed(1)}{unit}</span>
        </div>
      </div>
      <span className="text-xs text-[var(--muted)] mt-1">{label}</span>
      {threshold !== undefined && (
        <span className={`text-[10px] ${isAboveThreshold ? 'text-red-400' : 'text-emerald-400'}`}>
          Threshold: {threshold}{unit}
        </span>
      )}
    </div>
  );
}

// Stats card component
function StatCard({ 
  label, 
  value, 
  subValue,
  icon,
  color = 'text-[var(--text)]'
}: { 
  label: string; 
  value: string | number; 
  subValue?: string;
  icon?: React.ReactNode;
  color?: string;
}) {
  return (
    <div className="p-3 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)]">
      <div className="flex items-center gap-2 mb-1">
        {icon && <span className="text-sm">{icon}</span>}
        <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">{label}</span>
      </div>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
      {subValue && <div className="text-xs text-[var(--muted)]">{subValue}</div>}
    </div>
  );
}

export function FindingDetailModal({
  isOpen,
  onClose,
  finding,
  onShowFix,
  businessImpact
}: FindingDetailModalProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'analysis' | 'impact' | 'history'>('overview');
  const [mounted, setMounted] = useState(false);
  
  useEffect(() => {
    setMounted(true);
  }, []);
  
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    
    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    }
    
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);
  
  if (!mounted || !isOpen || !finding) return null;
  
  const severity = severityConfig[finding.severity] || severityConfig.medium;
  const isPipeline = finding.category === 'pipeline' || finding.scan_type === 'dbt';
  const isFreshness = finding.category === 'freshness' || finding.scan_type === 'freshness';
  const isQuality = finding.category === 'quality' || finding.scan_type === 'quality';
  
  // Generate demo data for visualization if not available
  const distributionData = finding.ai_context?.distribution || [
    { bucket: '0-10', count: Math.floor(Math.random() * 500) },
    { bucket: '10-20', count: Math.floor(Math.random() * 1000) },
    { bucket: '20-30', count: Math.floor(Math.random() * 800) },
    { bucket: '30-40', count: Math.floor(Math.random() * 600) },
    { bucket: '40-50', count: Math.floor(Math.random() * 400) },
    { bucket: '50+', count: Math.floor(Math.random() * 200) },
  ];
  
  const trendData = finding.ai_context?.trend_data || finding.metrics?.historical_values || [
    { timestamp: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(), value: 85 },
    { timestamp: new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString(), value: 82 },
    { timestamp: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(), value: 88 },
    { timestamp: new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString(), value: 75 },
    { timestamp: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(), value: 72 },
    { timestamp: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(), value: 68 },
    { timestamp: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(), value: 55 },
  ];
  
  const content = (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/80 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative w-full max-w-4xl max-h-[90vh] bg-[#0c0c14] border border-[rgba(255,255,255,0.08)] rounded-2xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className={`px-6 py-4 border-b border-[rgba(255,255,255,0.06)] bg-gradient-to-r ${severity.gradient} bg-opacity-10`}>
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              {/* Severity indicator */}
              <div className={`w-12 h-12 rounded-xl ${severity.bg} flex items-center justify-center`}>
                <span className="text-2xl">{severity.icon}</span>
              </div>
              
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className={`px-2 py-0.5 rounded text-xs font-bold uppercase ${severity.bg} ${severity.text}`}>
                    {finding.severity}
                  </span>
                  {isPipeline ? (
                    <span className="px-2 py-0.5 rounded text-xs font-medium uppercase bg-orange-500/15 text-orange-400">
                      Pipeline
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded text-xs font-medium uppercase bg-purple-500/15 text-purple-400">
                      Database
                    </span>
                  )}
                  {finding.scan_type && (
                    <span className="px-2 py-0.5 rounded text-xs bg-[rgba(255,255,255,0.05)] text-[var(--muted)]">
                      {finding.scan_type}
                    </span>
                  )}
                </div>
                <h2 className="text-xl font-bold text-white">{finding.title}</h2>
                <div className="flex items-center gap-3 mt-2 text-sm text-[var(--muted)]">
                  {/* Dataset badge (for multi-dataset scans) */}
                  {finding.dataset && (
                    <span className="px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-xs font-medium">
                      {finding.dataset}
                    </span>
                  )}
                  {finding.table && (
                    <span className="flex items-center gap-1.5">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                      </svg>
                      <code>{finding.table}</code>
                    </span>
                  )}
                  {finding.column && (
                    <span className="flex items-center gap-1.5">
                      <span className="text-[var(--muted)]">•</span>
                      <code>.{finding.column}</code>
                    </span>
                  )}
                </div>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              {finding.has_auto_fix && onShowFix && (
                <button
                  onClick={onShowFix}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-400 border border-emerald-500/30 hover:from-emerald-500/30 hover:to-teal-500/30 transition-all flex items-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  View Fix
                </button>
              )}
              <button
                onClick={onClose}
                className="p-2 rounded-lg hover:bg-[rgba(255,255,255,0.05)] transition-colors"
              >
                <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
        </div>
        
        {/* Tabs */}
        <div className="px-6 py-2 border-b border-[rgba(255,255,255,0.06)] bg-[rgba(0,0,0,0.3)]">
          <div className="flex gap-1">
            {[
              { id: 'overview', label: 'Overview', icon: '📋' },
              { id: 'analysis', label: 'Analysis', icon: '📊' },
              { id: 'impact', label: 'Impact', icon: '⚡' },
              { id: 'history', label: 'History', icon: '📈' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2 ${
                  activeTab === tab.id
                    ? 'bg-[rgba(255,255,255,0.08)] text-white'
                    : 'text-[var(--muted)] hover:text-white hover:bg-[rgba(255,255,255,0.04)]'
                }`}
              >
                <span>{tab.icon}</span>
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        
        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Description */}
              <div>
                <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Description</h3>
                <p className="text-[var(--text)] leading-relaxed">
                  {finding.description || finding.title}
                </p>
              </div>
              
              {/* Key Metrics */}
              <div>
                <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Key Metrics</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {finding.ai_context?.null_rate !== undefined && (
                    <StatCard 
                      label="Null Rate" 
                      value={`${(finding.ai_context.null_rate * 100).toFixed(1)}%`}
                      icon="📉"
                      color={finding.ai_context.null_rate > 0.1 ? 'text-red-400' : 'text-emerald-400'}
                    />
                  )}
                  {finding.ai_context?.duplicate_rate !== undefined && (
                    <StatCard 
                      label="Duplicate Rate" 
                      value={`${(finding.ai_context.duplicate_rate * 100).toFixed(1)}%`}
                      icon="📋"
                      color={finding.ai_context.duplicate_rate > 0.05 ? 'text-amber-400' : 'text-emerald-400'}
                    />
                  )}
                  {finding.ai_context?.hours_stale !== undefined && (
                    <StatCard 
                      label="Hours Stale" 
                      value={finding.ai_context.hours_stale.toFixed(1)}
                      subValue={`SLO: ${finding.ai_context.slo_hours || 24}h`}
                      icon="⏰"
                      color={finding.ai_context.hours_stale > (finding.ai_context.slo_hours || 24) ? 'text-red-400' : 'text-emerald-400'}
                    />
                  )}
                  {finding.ai_context?.total_rows !== undefined && (
                    <StatCard 
                      label="Total Rows" 
                      value={finding.ai_context.total_rows.toLocaleString()}
                      icon="📊"
                    />
                  )}
                  {finding.ai_context?.outlier_count !== undefined && (
                    <StatCard 
                      label="Outliers" 
                      value={finding.ai_context.outlier_count.toLocaleString()}
                      icon="⚠️"
                      color="text-amber-400"
                    />
                  )}
                  {finding.ai_context?.avg_value !== undefined && (
                    <StatCard 
                      label="Average" 
                      value={finding.ai_context.avg_value.toFixed(2)}
                      icon="📐"
                    />
                  )}
                  {finding.ai_context?.min_value !== undefined && (
                    <StatCard 
                      label="Min" 
                      value={finding.ai_context.min_value.toFixed(2)}
                      icon="⬇️"
                    />
                  )}
                  {finding.ai_context?.max_value !== undefined && (
                    <StatCard 
                      label="Max" 
                      value={finding.ai_context.max_value.toFixed(2)}
                      icon="⬆️"
                    />
                  )}
                </div>
              </div>
              
              {/* Possible Causes */}
              {finding.ai_context?.possible_causes && finding.ai_context.possible_causes.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Possible Causes</h3>
                  <div className="p-4 rounded-xl bg-amber-500/5 border border-amber-500/20">
                    <ul className="space-y-2">
                      {finding.ai_context.possible_causes.map((cause, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className="text-amber-400 mt-0.5">•</span>
                          <span className="text-[var(--text)]">{cause}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
              
              {/* Recommended Actions */}
              {finding.ai_context?.recommended_actions && finding.ai_context.recommended_actions.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Recommended Actions</h3>
                  <div className="space-y-2">
                    {finding.ai_context.recommended_actions.map((action, i) => (
                      <div key={i} className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/20 flex gap-3">
                        <span className={`px-2 py-0.5 h-fit rounded text-xs font-medium ${
                          action.priority === 'immediate' 
                            ? 'bg-red-500/20 text-red-400' 
                            : action.priority === 'high'
                            ? 'bg-amber-500/20 text-amber-400'
                            : 'bg-blue-500/20 text-blue-400'
                        }`}>
                          {action.priority}
                        </span>
                        <div className="flex-1">
                          <div className="text-sm font-medium text-[var(--text)]">{action.action}</div>
                          <div className="text-xs text-[var(--muted)] mt-0.5">{action.reason}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          
          {/* Analysis Tab */}
          {activeTab === 'analysis' && (
            <div className="space-y-6">
              {/* Gauges */}
              <div>
                <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-4">Health Indicators</h3>
                <div className="flex justify-center gap-8 flex-wrap">
                  {finding.ai_context?.null_rate !== undefined && (
                    <GaugeChart 
                      value={finding.ai_context.null_rate * 100}
                      threshold={10}
                      label="Null Rate"
                      invertColors
                    />
                  )}
                  {finding.ai_context?.duplicate_rate !== undefined && (
                    <GaugeChart 
                      value={finding.ai_context.duplicate_rate * 100}
                      threshold={5}
                      label="Duplicates"
                      invertColors
                    />
                  )}
                  {finding.ai_context?.hours_stale !== undefined && (
                    <GaugeChart 
                      value={finding.ai_context.hours_stale}
                      threshold={finding.ai_context.slo_hours || 24}
                      maxValue={Math.max(finding.ai_context.hours_stale * 1.5, 48)}
                      label="Hours Stale"
                      unit="h"
                      invertColors
                    />
                  )}
                </div>
              </div>
              
              {/* Distribution Chart */}
              <div className="p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)]">
                <BarChart 
                  data={distributionData}
                  label="Value Distribution"
                  color="#8b5cf6"
                />
              </div>
              
              {/* Trend Chart */}
              <div className="p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)]">
                <LineChart 
                  data={trendData}
                  label="Historical Trend"
                  threshold={finding.metrics?.threshold}
                  yLabel={isFreshness ? 'Hours' : isQuality ? 'Health %' : 'Value'}
                  color="#10b981"
                />
              </div>
              
              {/* Statistical Summary */}
              {(finding.ai_context?.avg_value || finding.ai_context?.std_dev) && (
                <div>
                  <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Statistical Summary</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {finding.ai_context?.min_value !== undefined && (
                      <div className="p-3 rounded-lg bg-[rgba(255,255,255,0.02)]">
                        <div className="text-xs text-[var(--muted)]">Minimum</div>
                        <div className="text-lg font-bold text-blue-400">{finding.ai_context.min_value.toFixed(2)}</div>
                      </div>
                    )}
                    {finding.ai_context?.max_value !== undefined && (
                      <div className="p-3 rounded-lg bg-[rgba(255,255,255,0.02)]">
                        <div className="text-xs text-[var(--muted)]">Maximum</div>
                        <div className="text-lg font-bold text-blue-400">{finding.ai_context.max_value.toFixed(2)}</div>
                      </div>
                    )}
                    {finding.ai_context?.avg_value !== undefined && (
                      <div className="p-3 rounded-lg bg-[rgba(255,255,255,0.02)]">
                        <div className="text-xs text-[var(--muted)]">Average</div>
                        <div className="text-lg font-bold text-purple-400">{finding.ai_context.avg_value.toFixed(2)}</div>
                      </div>
                    )}
                    {finding.ai_context?.std_dev !== undefined && (
                      <div className="p-3 rounded-lg bg-[rgba(255,255,255,0.02)]">
                        <div className="text-xs text-[var(--muted)]">Std Deviation</div>
                        <div className="text-lg font-bold text-amber-400">{finding.ai_context.std_dev.toFixed(2)}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
          
          {/* Impact Tab */}
          {activeTab === 'impact' && (
            <div className="space-y-6">
              {businessImpact ? (
                <>
                  {/* Priority & Criticality */}
                  <div className="flex gap-4">
                    {businessImpact.priority && (
                      <div className={`flex-1 p-4 rounded-xl text-center ${
                        businessImpact.priority === 'P0' ? 'bg-red-500/10 border border-red-500/30' :
                        businessImpact.priority === 'P1' ? 'bg-amber-500/10 border border-amber-500/30' :
                        businessImpact.priority === 'P2' ? 'bg-yellow-500/10 border border-yellow-500/30' :
                        'bg-slate-500/10 border border-slate-500/30'
                      }`}>
                        <div className="text-3xl font-bold">{businessImpact.priority}</div>
                        <div className="text-xs text-[var(--muted)]">Priority</div>
                      </div>
                    )}
                    {businessImpact.criticality && (
                      <div className="flex-1 p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)] text-center">
                        <div className="text-3xl font-bold text-purple-400">{businessImpact.criticality}</div>
                        <div className="text-xs text-[var(--muted)]">Criticality</div>
                      </div>
                    )}
                    {businessImpact.lineage?.downstreamCount && (
                      <div className="flex-1 p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)] text-center">
                        <div className="text-3xl font-bold text-blue-400">{businessImpact.lineage.downstreamCount}</div>
                        <div className="text-xs text-[var(--muted)]">Downstream Tables</div>
                      </div>
                    )}
                  </div>
                  
                  {/* Stakeholders */}
                  {businessImpact.stakeholders && businessImpact.stakeholders.length > 0 && (
                    <div>
                      <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Stakeholders</h3>
                      <div className="flex flex-wrap gap-2">
                        {businessImpact.stakeholders.map((s, i) => (
                          <span key={i} className="px-3 py-1.5 rounded-full text-sm bg-blue-500/10 text-blue-400 border border-blue-500/20">
                            👤 {s}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* Used In Reports */}
                  {businessImpact.usedInReports && businessImpact.usedInReports.length > 0 && (
                    <div>
                      <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Used In Reports</h3>
                      <div className="flex flex-wrap gap-2">
                        {businessImpact.usedInReports.map((r, i) => (
                          <span key={i} className="px-3 py-1.5 rounded-lg text-sm bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            📊 {r}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* Business Impact Statement */}
                  {businessImpact.businessImpact && (
                    <div className="p-4 rounded-xl bg-amber-500/5 border border-amber-500/20">
                      <h3 className="text-sm font-medium text-amber-400 mb-2">If This Issue Persists:</h3>
                      <p className="text-[var(--text)] italic">"{businessImpact.businessImpact}"</p>
                    </div>
                  )}
                  
                  {/* Downstream Tables */}
                  {businessImpact.lineage?.downstreamTables && businessImpact.lineage.downstreamTables.length > 0 && (
                    <div>
                      <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Downstream Tables Affected</h3>
                      <div className="grid grid-cols-2 gap-2">
                        {businessImpact.lineage.downstreamTables.map((table, i) => (
                          <div key={i} className="flex items-center gap-2 p-2 rounded-lg bg-[rgba(255,255,255,0.02)]">
                            <span className="text-purple-400">→</span>
                            <code className="text-sm text-[var(--text)]">{table}</code>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* Owner */}
                  {businessImpact.owner && (
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-[rgba(255,255,255,0.02)]">
                      <span className="text-[var(--muted)]">Owner:</span>
                      <span className="font-medium">{businessImpact.owner}</span>
                    </div>
                  )}
                </>
              ) : (
                <div className="text-center py-12">
                  <div className="w-16 h-16 rounded-full bg-[rgba(255,255,255,0.05)] flex items-center justify-center mx-auto mb-4">
                    <svg className="w-8 h-8 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-medium mb-2">Impact Analysis</h3>
                  <p className="text-[var(--muted)] mb-4">
                    Business impact data is not available for this finding.
                  </p>
                  <p className="text-sm text-[var(--muted)]">
                    Connect your data catalog to see stakeholders, downstream dependencies, and business impact.
                  </p>
                </div>
              )}
            </div>
          )}
          
          {/* History Tab */}
          {activeTab === 'history' && (
            <div className="space-y-6">
              {/* Trend Chart */}
              <div className="p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)]">
                <LineChart 
                  data={trendData}
                  label="Health Score Over Time"
                  yLabel="Score"
                  color="#8b5cf6"
                />
              </div>
              
              {/* Recent occurrences */}
              <div>
                <h3 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Recent Occurrences</h3>
                <div className="space-y-2">
                  {[
                    { date: 'Today', count: 1, status: 'open' },
                    { date: '2 days ago', count: 2, status: 'resolved' },
                    { date: '5 days ago', count: 1, status: 'resolved' },
                    { date: '1 week ago', count: 3, status: 'resolved' },
                  ].map((occurrence, i) => (
                    <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-[rgba(255,255,255,0.02)]">
                      <div className="flex items-center gap-3">
                        <div className={`w-2 h-2 rounded-full ${
                          occurrence.status === 'open' ? 'bg-red-400' : 'bg-emerald-400'
                        }`} />
                        <span className="text-sm">{occurrence.date}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-sm text-[var(--muted)]">{occurrence.count} occurrence{occurrence.count > 1 ? 's' : ''}</span>
                        <span className={`px-2 py-0.5 rounded text-xs ${
                          occurrence.status === 'open' 
                            ? 'bg-red-500/10 text-red-400' 
                            : 'bg-emerald-500/10 text-emerald-400'
                        }`}>
                          {occurrence.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              
              {/* Detection info */}
              <div className="p-4 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)]">
                <h3 className="text-sm font-medium mb-3">Detection Information</h3>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-[var(--muted)]">First Detected:</span>
                    <span className="ml-2">{new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toLocaleDateString()}</span>
                  </div>
                  <div>
                    <span className="text-[var(--muted)]">Last Seen:</span>
                    <span className="ml-2">Today</span>
                  </div>
                  <div>
                    <span className="text-[var(--muted)]">Total Occurrences:</span>
                    <span className="ml-2">7</span>
                  </div>
                  <div>
                    <span className="text-[var(--muted)]">Avg Resolution Time:</span>
                    <span className="ml-2 text-emerald-400">4.2 hours</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
        
        {/* Footer */}
        <div className="px-6 py-4 border-t border-[rgba(255,255,255,0.06)] bg-[rgba(0,0,0,0.3)] flex items-center justify-between">
          <div className="text-xs text-[var(--muted)]">
            Finding ID: {finding.id?.substring(0, 8)}...
          </div>
          <div className="flex items-center gap-2">
            {finding.has_auto_fix && onShowFix && (
              <button
                onClick={onShowFix}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-emerald-600 to-teal-600 text-white hover:from-emerald-500 hover:to-teal-500 transition-all flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                View Fix
              </button>
            )}
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-[rgba(255,255,255,0.05)] hover:bg-[rgba(255,255,255,0.1)] transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
  
  return createPortal(content, document.body);
}
