'use client';

import { Clock, Database, Cloud, BarChart3, GitBranch, Server, Layers, Eye, Cog, HardDrive, User } from 'lucide-react';
import { LAYER_COLORS, LAYER_LABELS, getToolById } from '@/components/pipeline/types';
import { ControlPlaneSource, STATUS_CONFIG, EXTRACTION_STATUS_CONFIG, SLA_CONFIG } from './types';
import { CAPABILITY_CONFIG } from './capabilities';
import SourceActionsMenu from './SourceActionsMenu';

const TOOL_ICONS: Record<string, typeof Database> = {
  bigquery: Database, snowflake: Database, postgres: Database, redshift: Database,
  sqlserver: Database, azure_sql: Database, azure_synapse: Database, databricks: Database, mysql: Database,
  fivetran: Cloud, airbyte: Cloud, stitch: Cloud,
  dbt_cloud: GitBranch, dbt_core: GitBranch,
  airflow: Cog, dagster: Cog, prefect: Cog, n8n: Cog,
  looker: BarChart3, tableau: BarChart3, powerbi: BarChart3, metabase: BarChart3,
  elementary: Eye, monte_carlo: Eye, bigeye: Eye, soda: Eye,
  amazon_s3: HardDrive, gcs: HardDrive, adls: HardDrive,
  github: Server,
};

function formatTimeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

interface Props {
  source: ControlPlaneSource;
  onClick: (source: ControlPlaneSource) => void;
  onTestConnection: (source: ControlPlaneSource) => void;
  onDisconnect: (source: ControlPlaneSource) => void;
  onEditContract: (source: ControlPlaneSource) => void;
}

export default function SourceCard({ source, onClick, onTestConnection, onDisconnect, onEditContract }: Props) {
  const Icon = TOOL_ICONS[source.toolType] || Layers;
  const tool = getToolById(source.toolType);
  const displayName = tool?.name || source.name;
  const statusCfg = STATUS_CONFIG[source.status];
  const extractCfg = EXTRACTION_STATUS_CONFIG[source.extractionStatus];
  const layerColor = LAYER_COLORS[source.layer] || '#6B7280';
  const layerLabel = LAYER_LABELS[source.layer] || source.layer;
  const slaCfg = source.contract?.slaTier ? SLA_CONFIG[source.contract.slaTier] : null;

  return (
    <div
      onClick={() => onClick(source)}
      className="flex items-center gap-4 px-4 py-3.5 rounded-lg border border-[var(--subtle-border)]
                 bg-[var(--surface-raised)] hover:border-[var(--border-medium)] hover:bg-[var(--hover-bg)]
                 transition-colors cursor-pointer group"
    >
      {/* Icon + Name */}
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={{ backgroundColor: `${layerColor}15` }}
        >
          <Icon className="w-4.5 h-4.5" style={{ color: layerColor }} />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-medium text-[var(--text)] truncate">{displayName}</div>
          {source.scopeSummary && (
            <div className="text-xs text-[var(--text-faint)] truncate mt-0.5">{source.scopeSummary}</div>
          )}
        </div>
      </div>

      {/* Layer badge */}
      <div
        className="hidden sm:flex items-center shrink-0 px-2 py-0.5 rounded-full text-xs font-medium"
        style={{ backgroundColor: `${layerColor}15`, color: layerColor }}
      >
        {layerLabel}
      </div>

      {/* Status badge */}
      <div className={`shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${statusCfg.bg} ${statusCfg.color}`}>
        <div className={`w-1.5 h-1.5 rounded-full ${statusCfg.color.replace('text-', 'bg-')}`} />
        {statusCfg.label}
      </div>

      {/* Extraction status badge */}
      <div className={`shrink-0 px-2 py-0.5 rounded-full text-xs font-medium ${extractCfg.bg} ${extractCfg.color}`}>
        {extractCfg.label}
      </div>

      {/* SLA tier */}
      {slaCfg && (
        <div className={`hidden md:flex shrink-0 px-2 py-0.5 rounded-full text-xs font-medium ${slaCfg.bg} ${slaCfg.color}`}>
          {source.contract!.slaTier}
        </div>
      )}

      {/* Owner */}
      {source.contract?.ownerUser && (
        <div className="hidden lg:flex items-center gap-1 text-xs text-[var(--text-faint)] shrink-0 max-w-[100px] truncate">
          <User className="w-3 h-3 shrink-0" />
          <span className="truncate">{source.contract.ownerUser}</span>
        </div>
      )}

      {/* Last extracted */}
      <div className="hidden md:flex items-center gap-1 text-xs text-[var(--text-faint)] shrink-0 w-20">
        <Clock className="w-3 h-3" />
        {source.lastExtractedAt ? formatTimeAgo(source.lastExtractedAt) : 'Never'}
      </div>

      {/* Capabilities */}
      <div className="hidden xl:flex items-center gap-1 shrink-0">
        {source.capabilities.map((cap) => {
          const cfg = CAPABILITY_CONFIG[cap];
          return (
            <span
              key={cap}
              className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${cfg.bg} ${cfg.color}`}
            >
              {cfg.label}
            </span>
          );
        })}
      </div>

      {/* Actions */}
      <div className="shrink-0">
        <SourceActionsMenu
          source={source}
          onTestConnection={onTestConnection}
          onViewDetails={onClick}
          onDisconnect={onDisconnect}
          onEditContract={onEditContract}
        />
      </div>
    </div>
  );
}
