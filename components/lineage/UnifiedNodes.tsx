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
  // Overlay mode (orchestration overlay on data tab)
  isOverlay?: boolean;
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
  const layerColor = LAYER_COLORS[data.layer] || '#6366F1';
  const statusConfig = getStatusConfig(data.status);
  const toolInitial = data.toolType?.charAt(0).toUpperCase() || data.name.charAt(0).toUpperCase();

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

  return (
    <div
      className="relative px-3 py-2.5 rounded-lg border min-w-[160px] max-w-[220px] shadow-md transition-all hover:shadow-lg hover:scale-[1.02]"
      style={{
        borderColor: borderColor,
        backgroundColor: visuals.bgColor,
        opacity: data.isOverlay ? 0.5 : 1,
        borderStyle: data.isOverlay ? 'dashed' : 'solid',
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
      </div>

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
