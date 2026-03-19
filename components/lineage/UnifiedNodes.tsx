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
import { CATEGORY_VISUALS, CATEGORY_LAYER_MAP, type UnifiedNodeCategory, type MonitorStatusSummary } from './types';
import { ToolIcon } from '@/components/icons/ToolIcon';
import { PolicyBadge } from './PolicyBadge';

// Map platform names to layer colors for multi-platform badges / split indicators
const PLATFORM_COLORS: Record<string, string> = {
  bigquery: LAYER_COLORS.WAREHOUSE,
  snowflake: LAYER_COLORS.WAREHOUSE,
  postgres: LAYER_COLORS.WAREHOUSE,
  redshift: LAYER_COLORS.WAREHOUSE,
  databricks: LAYER_COLORS.WAREHOUSE,
  dbt: LAYER_COLORS.TRANSFORMATION,
  dbt_core: LAYER_COLORS.TRANSFORMATION,
  fivetran: LAYER_COLORS.INGESTION,
  airbyte: LAYER_COLORS.INGESTION,
  looker: LAYER_COLORS.REPORTING,
  tableau: LAYER_COLORS.REPORTING,
  metabase: LAYER_COLORS.REPORTING,
  powerbi: LAYER_COLORS.REPORTING,
  power_bi: LAYER_COLORS.REPORTING,
};
function getPlatformColor(platform: string): string {
  return PLATFORM_COLORS[platform.toLowerCase()] || '#94A3B8';
}

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
  jobCount?: number;
  coverageGaps?: string[];
  // Aggregated monitor status across all child data assets
  monitorSummary?: { total: number; passing: number; warning: number; failing: number; error: number };
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
  // Monitor status
  monitorStatus?: MonitorStatusSummary;
  hasUpstreamFailure?: boolean;
  // Overlay mode (orchestration overlay on data tab)
  isOverlay?: boolean;
  // Inferred node (bridge node from investigator)
  isInferred?: boolean;
  // Policy mode
  isPolicyMode?: boolean;
  isPolicySelected?: boolean;
  policyStatus?: 'assigned' | 'inherited' | 'override' | 'none';
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
          backgroundColor: 'var(--surface-raised)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <Handle
          type="target"
          position={Position.Left}
          className="!w-3 !h-3 !border-2"
          style={{ backgroundColor: layerColor, borderColor: 'var(--border-medium)' }}
        />

        <div className="flex items-center gap-3 mb-3">
          <ToolIcon toolType={data.toolType || data.name} size={40} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-[var(--text)] font-semibold text-[14px] truncate">{data.name}</span>
              {(data.coverageGaps?.length ?? 0) > 0 && (
                <div className="w-2 h-2 rounded-full bg-amber-400 shrink-0" title={`${data.coverageGaps!.length} coverage gap(s)`} />
              )}
            </div>
            <span className="text-[10px] uppercase tracking-wide" style={{ color: layerColor }}>
              {data.toolType || data.category}
            </span>
          </div>
        </div>

        {/* Asset count */}
        {data.assetCount !== undefined && (
          <div className="flex items-center justify-between text-[11px] mb-2">
            <span className="text-[var(--muted)]">Data Assets</span>
            <span className="text-[var(--text)] font-semibold">{data.assetCount}</span>
          </div>
        )}

        {/* Job count */}
        {(data.jobCount ?? 0) > 0 && (
          <div className="flex items-center justify-between text-[11px] mb-2">
            <span className="text-[var(--muted)]">Jobs</span>
            <span className="text-[var(--text)] font-semibold">{data.jobCount}</span>
          </div>
        )}

        {/* Health bar */}
        {total > 0 && (
          <div>
            <div className="flex items-center justify-between text-[10px] text-[var(--muted)] mb-1">
              <span>Health</span>
              <span>{healthPct}%</span>
            </div>
            <div className="h-1.5 bg-[var(--overlay-medium)] rounded-full overflow-hidden flex">
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

        {/* Monitor summary bar */}
        {data.monitorSummary && data.monitorSummary.total > 0 && (() => {
          const ms = data.monitorSummary;
          const monTotal = ms.total;
          return (
            <div className="mt-2">
              <div className="flex items-center justify-between text-[10px] text-[var(--muted)] mb-1">
                <span>Monitors</span>
                <div className="flex items-center gap-1">
                  {ms.failing + ms.error > 0 && (
                    <span className="text-red-400 font-medium">{ms.failing + ms.error} fail</span>
                  )}
                  {ms.warning > 0 && (
                    <span className="text-amber-400 font-medium">{ms.warning} warn</span>
                  )}
                  {ms.failing + ms.error === 0 && ms.warning === 0 && (
                    <span className="text-emerald-400 font-medium">{ms.passing}/{monTotal}</span>
                  )}
                </div>
              </div>
              <div className="h-1.5 bg-[var(--overlay-medium)] rounded-full overflow-hidden flex">
                {ms.passing > 0 && (
                  <div className="h-full bg-emerald-400" style={{ width: `${(ms.passing / monTotal) * 100}%` }} />
                )}
                {ms.warning > 0 && (
                  <div className="h-full bg-amber-400" style={{ width: `${(ms.warning / monTotal) * 100}%` }} />
                )}
                {(ms.failing + ms.error) > 0 && (
                  <div className="h-full bg-red-400" style={{ width: `${((ms.failing + ms.error) / monTotal) * 100}%` }} />
                )}
              </div>
            </div>
          );
        })()}

        <Handle
          type="source"
          position={Position.Right}
          className="!w-3 !h-3 !border-2"
          style={{ backgroundColor: layerColor, borderColor: 'var(--border-medium)' }}
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
        backgroundColor: 'var(--surface-raised)',
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
          borderColor: 'var(--border-medium)',
        }}
      />

      {/* Header with icon and name */}
      <div className="flex items-center gap-3 mb-2">
        <ToolIcon toolType={data.toolType || data.name} size={36} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[var(--text)] font-medium text-sm truncate">{data.name}</span>
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
              <span className="text-[10px] text-[var(--muted)]">{data.toolType}</span>
            )}
          </div>
        </div>
      </div>

      {/* Health score bar */}
      {data.healthScore !== undefined && (
        <div className="mt-2">
          <div className="flex items-center justify-between text-[10px] text-[var(--muted)] mb-1">
            <span>Health</span>
            <span>{Math.round(data.healthScore)}%</span>
          </div>
          <div className="h-1.5 bg-[var(--overlay-medium)] rounded-full overflow-hidden">
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
            <span className="px-1.5 py-0.5 text-[10px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)] rounded">
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
          borderColor: 'var(--border-medium)',
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

  // Multi-platform detection (e.g., merged dbt + BigQuery node)
  const platforms = data.platforms || [];
  const isMultiPlatform = platforms.length > 1;

  // Layer-aware coloring: when the node's layer doesn't match the category's
  // default layer, use the layer color instead (e.g., ingestion TABLE nodes
  // should be green, not the default blue for tables).
  const defaultLayer = CATEGORY_LAYER_MAP[data.category];
  const layerOverride = data.layer && data.layer !== defaultLayer;
  const primaryColor = layerOverride ? (LAYER_COLORS[data.layer] || visuals.color) : visuals.color;
  const primaryBg = layerOverride
    ? `${primaryColor}20` // 12% opacity hex
    : visuals.bgColor;
  const primaryLabel = layerOverride
    ? data.layer.charAt(0) + data.layer.slice(1).toLowerCase()
    : visuals.label;

  // Determine overall health status
  const hasIssues = data.issues && data.issues.total > 0;
  const hasCritical = data.issues && data.issues.critical > 0;
  const hasHigh = data.issues && data.issues.high > 0;
  const isStale = data.freshnessStatus === 'stale';
  const monitorFailing = data.monitorStatus?.worstStatus === 'FAIL' || data.monitorStatus?.worstStatus === 'ERROR';
  const monitorWarning = data.monitorStatus?.worstStatus === 'WARN';

  // Determine border color based on health, then platform
  let borderColor = primaryColor;
  if (hasCritical || monitorFailing) {
    borderColor = '#EF4444'; // red
  } else if (hasHigh || isStale || monitorWarning) {
    borderColor = '#F59E0B'; // amber
  }

  const isInferred = data.isInferred || false;

  // Policy mode visual state
  const isPolicyMode = data.isPolicyMode || false;
  const isPolicySelected = data.isPolicySelected || false;
  const policyStatus = data.policyStatus || 'none';

  // Compute opacity: in policy mode, unselected nodes are dimmed
  let nodeOpacity = data.isOverlay ? 0.5 : isInferred ? 0.75 : 1;
  if (isPolicyMode && !isPolicySelected) {
    nodeOpacity = 0.5;
  }

  return (
    <div
      className={`relative rounded-lg border min-w-[160px] max-w-[220px] shadow-md transition-all hover:shadow-lg hover:scale-[1.02] overflow-hidden ${
        isPolicySelected ? 'ring-[3px] ring-slate-500' : ''
      }`}
      style={{
        borderColor: isInferred ? '#F59E0B60' : borderColor,
        backgroundColor: isInferred ? 'rgba(245,158,11,0.06)' : primaryBg,
        opacity: nodeOpacity,
        borderStyle: (data.isOverlay || isInferred || (isPolicyMode && policyStatus === 'none')) ? 'dashed' : 'solid',
      }}
    >
      {/* Split color strip for multi-platform nodes (e.g., dbt + BigQuery) */}
      {isMultiPlatform && (
        <div className="flex h-1.5">
          {platforms.map((p) => (
            <div key={p} className="flex-1" style={{ backgroundColor: getPlatformColor(p) }} />
          ))}
        </div>
      )}

      <div className="px-3 py-2.5">
        {/* Input handle (left side) */}
        <Handle
          type="target"
          position={Position.Left}
          className="!w-2.5 !h-2.5 !border-2"
          style={{
            backgroundColor: primaryColor,
            borderColor: 'var(--subtle-border)',
          }}
        />

        {/* Header with icon, type, policy badge and status */}
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <div style={{ color: primaryColor }}>{getDataAssetIcon(data.category)}</div>
            <span
              className="text-[10px] uppercase tracking-wide font-medium"
              style={{ color: primaryColor }}
            >
              {primaryLabel}
            </span>
            {data.category === 'model' && data.nodeType && data.nodeType !== 'model' && (
              <span className="text-[9px] text-[var(--text-faint)] lowercase">
                · {data.nodeType}
              </span>
            )}
            {isInferred && (
              <span className="text-[8px] text-amber-400/70 font-medium uppercase tracking-wide">
                inferred
              </span>
            )}
          </div>
          {/* Policy badge (inline, right side) */}
          <PolicyBadge status={policyStatus} />
        </div>

        {/* Status indicators row */}
        <div className="flex items-center gap-1 mb-1">
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
          {!hasIssues && !isStale && !data.monitorStatus && data.freshnessStatus !== 'unknown' && (
            <CheckCircle className="w-3 h-3 text-emerald-400" />
          )}
          {/* Monitor status dot */}
          {data.monitorStatus && (
            <div
              className="flex items-center"
              title={[
                data.monitorStatus.failing > 0 && `${data.monitorStatus.failing} failing`,
                data.monitorStatus.error > 0 && `${data.monitorStatus.error} error`,
                data.monitorStatus.warning > 0 && `${data.monitorStatus.warning} warning`,
                data.monitorStatus.passing > 0 && `${data.monitorStatus.passing} passing`,
              ].filter(Boolean).join(', ')}
            >
              <div
                className={`w-2 h-2 rounded-full ${
                  monitorFailing ? 'ring-1 ring-red-400/50' :
                  monitorWarning ? 'ring-1 ring-amber-400/50' : ''
                }`}
                style={{
                  backgroundColor: monitorFailing ? '#EF4444' :
                    monitorWarning ? '#F59E0B' :
                    data.monitorStatus.worstStatus === 'PASS' ? '#10B981' : '#6B7280',
                }}
              />
            </div>
          )}
          {/* Upstream failure indicator */}
          {data.hasUpstreamFailure && !monitorFailing && (
            <div title="Upstream monitor failure">
              <AlertCircle className="w-3 h-3 text-red-300/50" />
            </div>
          )}
        </div>

        {/* Name */}
        <div className="text-sm font-mono text-[var(--text)] truncate" title={data.fullName || data.name}>
          {shortName}
        </div>

        {/* Metadata row */}
        <div className="flex items-center flex-wrap gap-x-3 gap-y-0.5 mt-1.5 text-[10px] text-[var(--muted)]">
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

        {/* Platform provenance badges — colored per platform */}
        {isMultiPlatform && (
          <div className="flex items-center gap-1 mt-1.5">
            {platforms.map((p) => (
              <span
                key={p}
                className="px-1.5 py-0.5 text-[8px] font-semibold uppercase tracking-wide rounded"
                style={{
                  backgroundColor: `${getPlatformColor(p)}20`,
                  color: getPlatformColor(p),
                  border: `1px solid ${getPlatformColor(p)}40`,
                }}
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
              <span className="px-1.5 py-0.5 text-[9px] font-medium bg-[var(--overlay-medium)] text-[var(--muted)] rounded">
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
            backgroundColor: primaryColor,
            borderColor: 'var(--subtle-border)',
          }}
        />
      </div>
    </div>
  );
}

// Orphan group node — renders the label for the "Unconnected" container
function OrphanGroupNode({ data }: { data: { label?: string } }) {
  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <div
        style={{
          position: 'absolute',
          top: 12,
          left: 16,
          fontSize: 11,
          fontWeight: 500,
          color: 'var(--muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        }}
      >
        {data.label || 'Unconnected / Not Yet Mapped'}
      </div>
    </div>
  );
}

// Export unified node types for ReactFlow
export const unifiedNodeTypes = {
  toolNode: ToolNode,
  dataAssetNode: DataAssetNode,
  orphanGroup: OrphanGroupNode,
};
