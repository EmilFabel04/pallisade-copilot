'use client';

import React from 'react';
import { Handle, Position } from 'reactflow';
import {
  Upload,
  Shuffle,
  Database,
  BarChart3,
  Table,
  Eye,
  ArrowDownToLine,
  Cog,
  AlertCircle,
  CheckCircle,
  Clock,
  XCircle,
  Workflow,
  Play,
  GitBranch,
  Plug,
  BookOpen,
  HelpCircle,
  FileCode,
  FileArchive,
  LayoutDashboard,
  FileBarChart,
} from 'lucide-react';
import { LAYER_COLORS, type PipelineLayer } from '@/components/pipeline/types';
import { CATEGORY_VISUALS, type UnifiedNodeCategory } from './types';

interface ToolNodeData {
  name: string;
  category: UnifiedNodeCategory;
  layer: PipelineLayer;
  toolType?: string;
  status?: string;
  healthScore?: number;
  findingsCount?: number;
  criticalCount?: number;
  highCount?: number;
  // Control plane mode
  isControlPlane?: boolean;
  domainColor?: string;
  assetCount?: number;
  healthSummary?: { healthy: number; degraded: number; failing: number; unknown: number };
}

interface DataAssetIssues {
  total: number;
  open: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  byType: Record<string, number>;
}

interface DataAssetNodeData {
  name: string;
  fullName?: string;
  category: UnifiedNodeCategory;
  layer: PipelineLayer;
  database?: string;
  schema?: string;
  tableName?: string;
  nodeType?: string;
  criticality?: string;
  rowCount?: number;
  upstreamCount?: number;
  downstreamCount?: number;
  // Health & freshness
  lastUpdated?: string;
  freshnessStatus?: 'fresh' | 'stale' | 'unknown';
  freshnessHours?: number;
  issues?: DataAssetIssues;
  owner?: string;
  tags?: string[];
  // Multi-platform provenance
  platforms?: string[];
  // Enrichment indicators
  columnCount?: number;
  materialization?: string;
  // Overlay mode (orchestration overlay on data tab)
  isOverlay?: boolean;
  // Inferred node (bridge node from investigator)
  isInferred?: boolean;
}

// Get layer icon component
function getLayerIcon(category: UnifiedNodeCategory) {
  const iconProps = { className: 'w-4 h-4' };
  switch (category) {
    case 'ingestion':
      return <Upload {...iconProps} />;
    case 'transformation':
      return <Shuffle {...iconProps} />;
    case 'warehouse':
      return <Database {...iconProps} />;
    case 'reporting':
      return <BarChart3 {...iconProps} />;
    case 'orchestration':
      return <Workflow {...iconProps} />;
    default:
      return <Database {...iconProps} />;
  }
}

// Get data asset icon component
function getDataAssetIcon(category: UnifiedNodeCategory) {
  const iconProps = { className: 'w-3.5 h-3.5' };
  switch (category) {
    case 'table':
      return <Table {...iconProps} />;
    case 'view':
      return <Eye {...iconProps} />;
    case 'source':
      return <ArrowDownToLine {...iconProps} />;
    case 'model':
      return <Cog {...iconProps} />;
    case 'dag':
      return <Workflow {...iconProps} />;
    case 'task':
      return <Play {...iconProps} />;
    case 'workflow':
      return <GitBranch {...iconProps} />;
    case 'connector':
      return <Plug {...iconProps} />;
    case 'workbook':
      return <BookOpen {...iconProps} />;
    case 'dataset':
      return <Database {...iconProps} />;
    case 'question':
      return <HelpCircle {...iconProps} />;
    case 'notebook':
      return <FileCode {...iconProps} />;
    case 'file':
      return <FileArchive {...iconProps} />;
    case 'test':
      return <CheckCircle {...iconProps} />;
    case 'dashboard':
      return <LayoutDashboard {...iconProps} />;
    case 'report':
      return <FileBarChart {...iconProps} />;
    default:
      return <Table {...iconProps} />;
  }
}

// Get status icon and color
function getStatusConfig(status?: string): { icon: React.ReactNode; color: string } {
  switch (status?.toUpperCase()) {
    case 'CONNECTED':
    case 'ACTIVE':
    case 'HEALTHY':
      return {
        icon: <CheckCircle className="w-3 h-3" />,
        color: '#10B981',
      };
    case 'WARNING':
      return {
        icon: <AlertCircle className="w-3 h-3" />,
        color: '#F59E0B',
      };
    case 'ERROR':
      return {
        icon: <XCircle className="w-3 h-3" />,
        color: '#EF4444',
      };
    case 'TESTING':
      return {
        icon: <Clock className="w-3 h-3" />,
        color: '#F59E0B',
      };
    case 'PENDING':
    default:
      return {
        icon: <Clock className="w-3 h-3" />,
        color: '#6B7280',
      };
  }
}

/**
 * ToolNode - Renders a pipeline tool node (ingestion, transformation, warehouse, reporting)
 * Dimensions: ~220x90px
 */
export function ToolNode({ data }: { data: ToolNodeData }) {
  const layerColor = data.isControlPlane
    ? (data.domainColor || '#6366F1')
    : (LAYER_COLORS[data.layer] || '#6366F1');
  const statusConfig = getStatusConfig(data.status);
  const toolInitial = data.toolType?.charAt(0).toUpperCase() || data.name.charAt(0).toUpperCase();

  // Control Plane mode: larger tool cards with asset count + health bar
  if (data.isControlPlane) {
    const health = data.healthSummary;
    const total = health ? health.healthy + health.degraded + health.failing + health.unknown : 0;
    const healthPct = total > 0 && health ? Math.round((health.healthy / total) * 100) : 0;

    return (
      <div
        className="relative px-5 py-4 rounded-xl border-2 min-w-[220px] max-w-[260px] shadow-lg transition-all hover:shadow-xl hover:scale-[1.02]"
        style={{
          borderColor: layerColor,
          backgroundColor: 'rgba(0,0,0,0.7)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <Handle
          type="target"
          position={Position.Left}
          className="!w-3 !h-3 !border-2"
          style={{ backgroundColor: layerColor, borderColor: 'rgba(255,255,255,0.3)' }}
        />

        <div className="flex items-center gap-3 mb-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold text-base"
            style={{ backgroundColor: layerColor }}
          >
            {toolInitial}
          </div>
          <div className="flex-1 min-w-0">
            <span className="text-white font-semibold text-[14px] truncate block">{data.name}</span>
            <span className="text-[10px] uppercase tracking-wide" style={{ color: layerColor }}>
              {data.toolType || data.category}
            </span>
          </div>
        </div>

        {/* Asset count */}
        {data.assetCount !== undefined && (
          <div className="flex items-center justify-between text-[11px] mb-2">
            <span className="text-white/50">Data Assets</span>
            <span className="text-white font-semibold">{data.assetCount}</span>
          </div>
        )}

        {/* Health bar */}
        {total > 0 && (
          <div>
            <div className="flex items-center justify-between text-[10px] text-white/50 mb-1">
              <span>Health</span>
              <span>{healthPct}%</span>
            </div>
            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden flex">
              {health!.healthy > 0 && (
                <div className="h-full bg-emerald-400" style={{ width: `${(health!.healthy / total) * 100}%` }} />
              )}
              {health!.degraded > 0 && (
                <div className="h-full bg-amber-400" style={{ width: `${(health!.degraded / total) * 100}%` }} />
              )}
              {health!.failing > 0 && (
                <div className="h-full bg-red-400" style={{ width: `${(health!.failing / total) * 100}%` }} />
              )}
            </div>
          </div>
        )}

        <Handle
          type="source"
          position={Position.Right}
          className="!w-3 !h-3 !border-2"
          style={{ backgroundColor: layerColor, borderColor: 'rgba(255,255,255,0.3)' }}
        />
      </div>
    );
  }

  // Standard ToolNode (data plane)
  return (
    <div
      className="relative px-4 py-3 rounded-lg border-2 min-w-[200px] max-w-[240px] shadow-lg transition-all hover:shadow-xl hover:scale-[1.02]"
      style={{
        borderColor: layerColor,
        backgroundColor: 'rgba(0,0,0,0.6)',
        backdropFilter: 'blur(8px)',
      }}
    >
      {/* Input handle (left side) */}
      <Handle
        type="target"
        position={Position.Left}
        className="!w-3 !h-3 !border-2"
        style={{
          backgroundColor: layerColor,
          borderColor: 'rgba(255,255,255,0.3)',
        }}
      />

      {/* Header with icon and name */}
      <div className="flex items-center gap-3 mb-2">
        {/* Tool icon circle */}
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center text-white font-bold text-sm"
          style={{ backgroundColor: layerColor }}
        >
          {toolInitial}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-white font-medium text-sm truncate">{data.name}</span>
            <div className="flex items-center gap-1" style={{ color: statusConfig.color }}>
              {statusConfig.icon}
            </div>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <div
              className="flex items-center gap-1 text-[10px] uppercase tracking-wide"
              style={{ color: layerColor }}
            >
              {getLayerIcon(data.category)}
              <span>{data.category}</span>
            </div>
            {data.toolType && (
              <span className="text-[10px] text-white/40">{data.toolType}</span>
            )}
          </div>
        </div>
      </div>

      {/* Health score bar */}
      {data.healthScore !== undefined && (
        <div className="mt-2">
          <div className="flex items-center justify-between text-[10px] text-white/50 mb-1">
            <span>Health</span>
            <span>{Math.round(data.healthScore)}%</span>
          </div>
          <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${data.healthScore}%`,
                backgroundColor:
                  data.healthScore >= 80
                    ? '#10B981'
                    : data.healthScore >= 60
                    ? '#F59E0B'
                    : '#EF4444',
              }}
            />
          </div>
        </div>
      )}

      {/* Findings badges */}
      {(data.findingsCount ?? 0) > 0 && (
        <div className="flex items-center gap-2 mt-2">
          {(data.criticalCount ?? 0) > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium bg-red-500/20 text-red-400 rounded">
              {data.criticalCount} Critical
            </span>
          )}
          {(data.highCount ?? 0) > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium bg-orange-500/20 text-orange-400 rounded">
              {data.highCount} High
            </span>
          )}
          {(data.findingsCount ?? 0) > (data.criticalCount ?? 0) + (data.highCount ?? 0) && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium bg-white/10 text-white/50 rounded">
              +{(data.findingsCount ?? 0) - (data.criticalCount ?? 0) - (data.highCount ?? 0)}
            </span>
          )}
        </div>
      )}

      {/* Output handle (right side) */}
      <Handle
        type="source"
        position={Position.Right}
        className="!w-3 !h-3 !border-2"
        style={{
          backgroundColor: layerColor,
          borderColor: 'rgba(255,255,255,0.3)',
        }}
      />
    </div>
  );
}

/**
 * DataAssetNode - Renders a data asset node (table, view, source, model)
 * Enhanced with status indicators for freshness and issues
 */
export function DataAssetNode({ data }: { data: DataAssetNodeData }) {
  const visuals = CATEGORY_VISUALS[data.category] || CATEGORY_VISUALS.table;
  const shortName = data.tableName || data.name?.split('.').pop() || data.name;

  // Determine overall health status
  const hasIssues = data.issues && data.issues.total > 0;
  const hasCritical = data.issues && data.issues.critical > 0;
  const hasHigh = data.issues && data.issues.high > 0;
  const isStale = data.freshnessStatus === 'stale';

  // Determine border color based on health
  let borderColor = visuals.borderColor;
  if (hasCritical) {
    borderColor = '#EF4444'; // red
  } else if (hasHigh || isStale) {
    borderColor = '#F59E0B'; // amber
  }

  const isInferred = data.isInferred || false;

  return (
    <div
      className="relative px-3 py-2.5 rounded-lg border min-w-[160px] max-w-[220px] shadow-md transition-all hover:shadow-lg hover:scale-[1.02]"
      style={{
        borderColor: isInferred ? '#F59E0B60' : borderColor,
        backgroundColor: isInferred ? 'rgba(245,158,11,0.06)' : visuals.bgColor,
        opacity: data.isOverlay ? 0.5 : isInferred ? 0.75 : 1,
        borderStyle: (data.isOverlay || isInferred) ? 'dashed' : 'solid',
      }}
    >
      {/* Input handle (left side) */}
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !border-2"
        style={{
          backgroundColor: visuals.color,
          borderColor: 'rgba(255,255,255,0.2)',
        }}
      />

      {/* Header with icon, type and status */}
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <div style={{ color: visuals.color }}>{getDataAssetIcon(data.category)}</div>
          <span
            className="text-[10px] uppercase tracking-wide font-medium"
            style={{ color: visuals.color }}
          >
            {visuals.label}
          </span>
          {data.category === 'model' && data.nodeType && data.nodeType !== 'model' && (
            <span className="text-[9px] text-white/30 lowercase">
              · {data.nodeType}
            </span>
          )}
          {isInferred && (
            <span className="text-[8px] text-amber-400/70 font-medium uppercase tracking-wide">
              inferred
            </span>
          )}
        </div>
        {/* Status indicators */}
        <div className="flex items-center gap-1">
          {data.freshnessStatus === 'fresh' && (
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" title="Fresh" />
          )}
          {isStale && (
            <div className="flex items-center" title={`Stale (${data.freshnessHours}h ago)`}>
              <Clock className="w-3 h-3 text-amber-400" />
            </div>
          )}
          {hasCritical && (
            <div className="flex items-center" title={`${data.issues?.critical} critical issues`}>
              <AlertCircle className="w-3 h-3 text-red-400" />
            </div>
          )}
          {!hasCritical && hasHigh && (
            <div className="flex items-center" title={`${data.issues?.high} high severity issues`}>
              <AlertCircle className="w-3 h-3 text-amber-400" />
            </div>
          )}
          {!hasIssues && !isStale && data.freshnessStatus !== 'unknown' && (
            <CheckCircle className="w-3 h-3 text-emerald-400" />
          )}
        </div>
      </div>

      {/* Name */}
      <div className="text-sm font-mono text-white truncate" title={data.fullName || data.name}>
        {shortName}
      </div>

      {/* Metadata row */}
      <div className="flex items-center flex-wrap gap-x-3 gap-y-0.5 mt-1.5 text-[10px] text-white/40">
        {(data.upstreamCount ?? 0) > 0 && <span>↑{data.upstreamCount}</span>}
        {(data.downstreamCount ?? 0) > 0 && <span>↓{data.downstreamCount}</span>}
        {data.rowCount !== undefined && data.rowCount > 0 && (
          <span>{data.rowCount.toLocaleString()} rows</span>
        )}
        {(data.columnCount ?? 0) > 0 && (
          <span>{data.columnCount} cols</span>
        )}
        {data.materialization && (
          <span className="capitalize">{data.materialization}</span>
        )}
      </div>

      {/* Platform provenance badges (only when multi-platform) */}
      {data.platforms && data.platforms.length > 1 && (
        <div className="flex items-center gap-1 mt-1">
          {data.platforms.map((p) => (
            <span
              key={p}
              className="px-1 py-0.5 text-[8px] font-medium uppercase tracking-wide rounded bg-white/[0.06] text-white/40 border border-white/[0.06]"
            >
              {p}
            </span>
          ))}
        </div>
      )}

      {/* Issue badges */}
      {hasIssues && (
        <div className="flex items-center gap-1.5 mt-2">
          {data.issues!.critical > 0 && (
            <span className="px-1.5 py-0.5 text-[9px] font-medium bg-red-500/25 text-red-300 rounded">
              {data.issues!.critical}C
            </span>
          )}
          {data.issues!.high > 0 && (
            <span className="px-1.5 py-0.5 text-[9px] font-medium bg-orange-500/25 text-orange-300 rounded">
              {data.issues!.high}H
            </span>
          )}
          {(data.issues!.medium > 0 || data.issues!.low > 0) && (
            <span className="px-1.5 py-0.5 text-[9px] font-medium bg-white/10 text-white/50 rounded">
              +{data.issues!.medium + data.issues!.low}
            </span>
          )}
        </div>
      )}

      {/* Output handle (right side) */}
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !border-2"
        style={{
          backgroundColor: visuals.color,
          borderColor: 'rgba(255,255,255,0.2)',
        }}
      />
    </div>
  );
}

// Export unified node types for ReactFlow
export const unifiedNodeTypes = {
  toolNode: ToolNode,
  dataAssetNode: DataAssetNode,
};
