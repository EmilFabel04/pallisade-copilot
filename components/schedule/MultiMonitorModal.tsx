'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { NodeSelectionSurface, type SelectionViewMode, type NodeMeta } from './NodeSelectionSurface';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import { ColumnPicker } from './ColumnPicker';
import { getMonitorDefinition, DOMAIN_MONITOR_MAP } from '@/types/monitor-catalog';
import type { MonitoringPlanPreview } from '@/types/health-watch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MultiMonitorModalProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
  stackId?: string;
  preselectedNodeIds?: string[];
  /** Pre-built node metadata (skips NodeSelectionSurface loading) */
  preselectedNodeMeta?: NodeMeta[];
  integrations?: Array<{ id: string; name: string; type: string }>;
}

type Step = 1 | 2 | 3;
type ConfigTab = 'presets' | 'ai-prompt';

interface MonitorOption {
  key: string;        // "FRESHNESS", etc.
  targetFqn: string;
  targetNodeId: string;
  family: string;
  reason: string;
  groupIdx: number;
  monIdx: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEP_LABELS: Record<Step, string> = {
  1: 'Select Assets',
  2: 'Configure Monitors',
  3: 'Finalize & Create',
};

const MONITOR_COLORS: Record<string, string> = {
  FRESHNESS: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  VOLUME: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  SCHEMA_CHANGE: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  SYNC_LAG: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  FAILED_SYNCS: 'bg-red-500/15 text-red-400 border-red-500/30',
  CONNECTOR_SCHEMA_DRIFT: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  DAG_LAST_RUN: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  DAG_SCHEDULE_LAG: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  DBT_TEST_FAILURES: 'bg-pink-500/15 text-pink-400 border-pink-500/30',
  DBT_MODEL_FRESHNESS: 'bg-pink-500/15 text-pink-400 border-pink-500/30',
  DBT_SOURCE_FRESHNESS: 'bg-pink-500/15 text-pink-400 border-pink-500/30',
  NULL_RATE: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  DISTRIBUTION: 'bg-teal-500/15 text-teal-400 border-teal-500/30',
  ANOMALY: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  REFERENTIAL: 'bg-lime-500/15 text-lime-400 border-lime-500/30',
  BI_FRESHNESS_PROXY: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  BI_CONTENT_HEALTH: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  BI_UPSTREAM_BREAK_RISK: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  BI_REFRESH_FAILURE: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  TASK_FAILURE_RATE: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  QUERY_PERFORMANCE: 'bg-sky-500/15 text-sky-400 border-sky-500/30',
  COST_ANOMALY: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  STORAGE_GROWTH: 'bg-lime-500/15 text-lime-400 border-lime-500/30',
  SERVER_HEALTH: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  CERTIFICATE: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  LOG_ANALYSIS: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  NULL_CHECK: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  UNIQUENESS_CHECK: 'bg-teal-500/15 text-teal-400 border-teal-500/30',
  RANGE_VALIDATION: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  ACCEPTED_VALUES: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
  DATE_CONSISTENCY: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  OUTLIER_DETECTION: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  CUSTOM_SQL: 'bg-white/10 text-white/50 border-white/20',
};

const DOMAIN_COLORS: Record<string, string> = {
  warehouse: 'bg-indigo-500/15 text-indigo-400',
  ingestion: 'bg-emerald-500/15 text-emerald-400',
  transform: 'bg-amber-500/15 text-amber-400',
  orchestration: 'bg-orange-500/15 text-orange-400',
  bi: 'bg-cyan-500/15 text-cyan-400',
  infrastructure: 'bg-slate-500/15 text-slate-400',
};

interface Preset {
  key: string;
  label: string;
  description: string;
  families: string[];
  iconPath: string;
}

const PRESETS: Preset[] = [
  {
    key: 'full_operability',
    label: 'Full Pipeline Operability',
    description: 'Maximum coverage — all applicable monitors for every selected asset',
    families: ['pipeline_health', 'data_drift', 'ingestion_reliability', 'bi_reliability', 'model_quality', 'ingestion_ops', 'orchestration_ops', 'transform_ops', 'warehouse_ops', 'bi_ops', 'infrastructure_ops'],
    iconPath: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
  },
  {
    key: 'pipeline_health',
    label: 'Pipeline Health',
    description: 'Freshness, volume & schema on data assets and upstream dependencies',
    families: ['pipeline_health'],
    iconPath: 'M13 10V3L4 14h7v7l9-11h-7z',
  },
  {
    key: 'data_quality',
    label: 'Data Quality',
    description: 'Schema drift, null rates, anomaly detection & volume checks',
    families: ['data_drift'],
    iconPath: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
  },
  {
    key: 'ingestion',
    label: 'Ingestion Reliability',
    description: 'Sync lag, failed syncs & connector schema drift',
    families: ['ingestion_reliability'],
    iconPath: 'M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12',
  },
  {
    key: 'bi_protection',
    label: 'BI & Reporting',
    description: 'Dashboard freshness, content health & upstream break risk',
    families: ['bi_reliability'],
    iconPath: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
  },
  {
    key: 'ingestion_ops',
    label: 'Ingestion Ops',
    description: 'Sync lag, failed syncs & connector schema drift for ingestion tools',
    families: ['ingestion_ops'],
    iconPath: 'M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4-4m0 0L8 12m4-4v12',
  },
  {
    key: 'orchestration_ops',
    label: 'Orchestration Ops',
    description: 'DAG run status, schedule lag & task failure rate for orchestrators',
    families: ['orchestration_ops'],
    iconPath: 'M5 12h14M12 5l7 7-7 7',
  },
  {
    key: 'transform_ops',
    label: 'Transform Ops',
    description: 'dbt test failures, model & source freshness for transformation tools',
    families: ['transform_ops'],
    iconPath: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z',
  },
  {
    key: 'warehouse_ops',
    label: 'Warehouse Ops',
    description: 'Query performance, cost anomalies & storage growth for your warehouse',
    families: ['warehouse_ops'],
    iconPath: 'M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4',
  },
  {
    key: 'bi_ops',
    label: 'BI Ops',
    description: 'Dashboard freshness, content health & refresh failures for BI tools',
    families: ['bi_ops'],
    iconPath: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
  },
  {
    key: 'infrastructure_ops',
    label: 'Infrastructure Ops',
    description: 'Server health, certificate expiry & log analysis for Linux servers',
    families: ['infrastructure_ops'],
    iconPath: 'M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-7-4h.01M12 16h.01',
  },
  {
    key: 'transform',
    label: 'Transform Quality',
    description: 'dbt test failures, model freshness & source freshness',
    families: ['model_quality'],
    iconPath: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z',
  },
];

/**
 * Monitor keys that strictly target tool-level nodes (connectors, DAGs,
 * warehouse ops, infra) — these should NOT appear on data nodes.
 *
 * dbt monitors and BI monitors are intentionally excluded from this set
 * because their targets (models, dashboards) appear as data-like nodes
 * in the lineage graph, not as tool service nodes.
 */
const TOOL_ONLY_MONITOR_KEYS = new Set([
  'SYNC_LAG', 'FAILED_SYNCS', 'CONNECTOR_SCHEMA_DRIFT',
  'DAG_LAST_RUN', 'DAG_SCHEDULE_LAG', 'TASK_FAILURE_RATE',
  'QUERY_PERFORMANCE', 'COST_ANOMALY', 'STORAGE_GROWTH',
  'CERTIFICATE', 'SERVER_HEALTH', 'LOG_ANALYSIS',
]);

/**
 * Returns true if any checked tool monitor has missing required config fields.
 * Only applies to tool nodes (subNodeIds.length > 0) with TOOL_ONLY_MONITOR_KEYS monitors.
 */
function hasIncompleteToolConfig(
  checks: Record<string, boolean>,
  configs: Record<string, Record<string, any>>,
  nodesWithMonitors: Array<{ meta: { subNodeIds?: string[] }; monitors: Array<{ targetNodeId: string; key: string }> }>,
): boolean {
  for (const { meta, monitors } of nodesWithMonitors) {
    if (!meta.subNodeIds?.length) continue;
    for (const mon of monitors) {
      const checkKey = `${mon.targetNodeId}::${mon.key}`;
      if (!checks[checkKey]) continue;
      if (!TOOL_ONLY_MONITOR_KEYS.has(mon.key)) continue;

      const def = getMonitorDefinition(mon.key);
      if (!def) continue;

      const config = configs[checkKey] || {};
      const hasMissing = def.config_schema
        .filter((f) => f.required)
        .some((f) => !config[f.key] && config[f.key] !== 0);

      if (hasMissing) return true;
    }
  }
  return false;
}

const CONFIG_TABS: { key: ConfigTab; label: string; icon: string }[] = [
  {
    key: 'presets',
    label: 'Monitors',
    icon: 'M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm0 8a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zm12 0a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z',
  },
  {
    key: 'ai-prompt',
    label: 'AI Prompt',
    icon: 'M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z',
  },
];

// ---------------------------------------------------------------------------
// Monitor Card sub-component
// ---------------------------------------------------------------------------

function MonitorCard({
  mon,
  checked,
  onToggle,
  showTarget,
  isToolNode,
  config,
  onConfigChange,
}: {
  mon: MonitorOption;
  checked: boolean;
  onToggle: () => void;
  showTarget?: boolean;
  isToolNode?: boolean;
  config?: Record<string, any>;
  onConfigChange?: (key: string, value: any) => void;
}) {
  const def = getMonitorDefinition(mon.key);
  const label = def?.label || mon.key;
  const description = def?.description || mon.reason;

  // Required config fields for tool monitors
  const requiredFields = isToolNode && def
    ? def.config_schema.filter((f) => f.required)
    : [];
  const showConfig = checked && requiredFields.length > 0;

  // Check if all required fields are filled
  const isConfigComplete = requiredFields.length === 0 || requiredFields.every(
    (f) => config?.[f.key] || config?.[f.key] === 0,
  );

  return (
    <div className={cn(
      'rounded-lg border transition-all overflow-hidden',
      checked
        ? (MONITOR_COLORS[mon.key] || 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/30')
        : 'border-[var(--border)] text-[var(--text)] hover:border-[var(--muted)]/50',
    )}>
      <button
        onClick={onToggle}
        className="flex items-start gap-3 p-3 text-left transition-all w-full"
      >
        {/* Checkbox */}
        <div
          className={cn(
            'w-4 h-4 mt-0.5 rounded-sm border flex items-center justify-center shrink-0 transition-colors',
            checked
              ? 'bg-current border-current'
              : 'border-[var(--muted)]/40',
          )}
        >
          {checked && (
            <svg className="w-2.5 h-2.5" fill="none" stroke="var(--bg)" strokeWidth={4} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
        </div>
        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-medium">{label}</span>
            {checked && isToolNode && requiredFields.length > 0 && (
              <span className={cn(
                'px-1.5 py-0.5 rounded text-[9px] font-medium',
                isConfigComplete
                  ? 'bg-emerald-500/15 text-emerald-400'
                  : 'bg-amber-500/15 text-amber-400',
              )}>
                {isConfigComplete ? 'Configured' : 'Requires config'}
              </span>
            )}
          </div>
          {description && (
            <p className={cn(
              'text-[11px] mt-0.5 leading-relaxed',
              checked ? 'opacity-80' : 'text-[var(--muted)]',
            )}>
              {description}
            </p>
          )}
          {showTarget && mon.targetFqn && (
            <p className="text-[10px] font-mono mt-1 opacity-60 truncate">
              {mon.targetFqn}
            </p>
          )}
        </div>
      </button>

      {/* Inline config form for tool monitors */}
      {showConfig && (
        <div
          className="px-3 pb-3 pt-1 border-t border-[var(--border)] bg-[var(--surface)]/50 space-y-2"
          onClick={(e) => e.stopPropagation()}
        >
          {requiredFields.map((field) => (
            <div key={field.key}>
              <label className="block text-[10px] text-[var(--muted)] uppercase tracking-wide mb-1">
                {field.label}
              </label>
              {field.type === 'select' ? (
                <select
                  value={config?.[field.key] ?? field.default_value ?? ''}
                  onChange={(e) => onConfigChange?.(field.key, e.target.value)}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded px-2 py-1.5 text-[12px] text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value="">{field.placeholder || 'Select...'}</option>
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              ) : field.type === 'multi-text' || field.type === 'textarea' ? (
                <textarea
                  value={config?.[field.key] ?? ''}
                  onChange={(e) => onConfigChange?.(field.key, e.target.value)}
                  placeholder={field.placeholder}
                  rows={3}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded px-2 py-1.5 text-[12px] text-[var(--text)] placeholder:text-[var(--muted)]/40 focus:outline-none focus:border-[var(--accent)] resize-none"
                />
              ) : field.type === 'checkbox' ? (
                <label className="flex items-center gap-2 text-[12px] text-[var(--text)]">
                  <input
                    type="checkbox"
                    checked={!!config?.[field.key]}
                    onChange={(e) => onConfigChange?.(field.key, e.target.checked)}
                    className="rounded border-[var(--border)]"
                  />
                  {field.placeholder || field.label}
                </label>
              ) : (
                <input
                  type={field.type === 'number' ? 'number' : 'text'}
                  value={config?.[field.key] ?? ''}
                  onChange={(e) => onConfigChange?.(
                    field.key,
                    field.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value,
                  )}
                  placeholder={field.placeholder}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded px-2 py-1.5 text-[12px] text-[var(--text)] placeholder:text-[var(--muted)]/40 focus:outline-none focus:border-[var(--accent)]"
                />
              )}
              {field.help_text && (
                <p className="text-[10px] text-[var(--muted)] mt-0.5">{field.help_text}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manual monitor entry type
// ---------------------------------------------------------------------------

interface ManualMonitorEntry {
  id: string;
  monitorType: string;
  targetFqn: string;
  config: Record<string, any>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MultiMonitorModal({
  open,
  onClose,
  onComplete,
  stackId,
  preselectedNodeIds,
  preselectedNodeMeta,
  integrations = [],
}: MultiMonitorModalProps) {
  const [step, setStep] = useState<Step>(1);
  const [viewMode, setViewMode] = useState<SelectionViewMode>('lineage');

  // Step 1: Node selection
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>(
    preselectedNodeIds || [],
  );
  const [allNodeMeta, setAllNodeMeta] = useState<NodeMeta[]>([]);

  // Step 2: Monitor configuration
  const [configTab, setConfigTab] = useState<ConfigTab>('presets');
  // preview is derived via useMemo from rawPreview + tool monitor injection (see below)
  const [previewLoading, setPreviewLoading] = useState(false);
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [monitorChecks, setMonitorChecks] = useState<Record<string, boolean>>({});
  const [monitorConfigs, setMonitorConfigs] = useState<Record<string, Record<string, any>>>({});

  // AI Prompt tab state
  const [aiPrompt, setAiPrompt] = useState('');
  const [aiIntegrationId, setAiIntegrationId] = useState('');

  // Manual tab state
  const [manualMonitors, setManualMonitors] = useState<ManualMonitorEntry[]>([]);
  const [manualMonitorType, setManualMonitorType] = useState('FRESHNESS');
  const [manualTargetFqn, setManualTargetFqn] = useState('');

  // Step 3: Finalize & Create
  const [planName, setPlanName] = useState('');
  const [schedule, setSchedule] = useState('0 */6 * * *');
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'ERROR']);
  const [creating, setCreating] = useState(false);

  // Collapsed node sections
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set());

  // Warehouse integrations for AI prompt
  const warehouseIntegrations = useMemo(() => {
    const seen = new Set<string>();
    return integrations.filter((i) => {
      const t = i.type.toLowerCase();
      if (!['bigquery', 'snowflake', 'postgres', 'redshift'].includes(t)) return false;
      if (seen.has(i.id)) return false;
      seen.add(i.id);
      return true;
    });
  }, [integrations]);

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setStep(preselectedNodeIds?.length ? 2 : 1);
      setSelectedNodeIds(preselectedNodeIds || []);
      // Seed node metadata if provided (skips NodeSelectionSurface requirement)
      if (preselectedNodeMeta?.length) {
        setAllNodeMeta(preselectedNodeMeta);
      }
      setRawPreview(null);
      setPreviewFailed(false);
      setMonitorChecks({});
      setMonitorConfigs({});
      setActivePreset(null);
      setConfigTab('presets');
      setAiPrompt('');
      setAiIntegrationId('');
      setManualMonitors([]);
      setPlanName('');
      setSchedule('0 */6 * * *');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'ERROR']);
      setCreating(false);
      setCollapsedNodes(new Set());
    }
  }, [open, preselectedNodeIds, preselectedNodeMeta]);

  // Node metadata callback from NodeSelectionSurface.
  // Merge with any preselected tool node meta (which has subNodeIds/domain
  // that the NodeSelectionSurface nodes won't have).
  const handleNodesLoaded = useCallback((nodes: NodeMeta[]) => {
    if (preselectedNodeMeta?.length) {
      const surfaceIds = new Set(nodes.map((n) => n.id));
      const extras = preselectedNodeMeta.filter((pm) => !surfaceIds.has(pm.id));
      setAllNodeMeta([...extras, ...nodes]);
    } else {
      setAllNodeMeta(nodes);
    }
  }, [preselectedNodeMeta]);

  // ---- Expand tool node IDs to actual graph node IDs ----
  const resolvedGraphNodeIds = useMemo(() => {
    const metaById = new Map(allNodeMeta.map((m) => [m.id, m]));
    const ids: string[] = [];
    const seen = new Set<string>();
    for (const nid of selectedNodeIds) {
      const meta = metaById.get(nid);
      if (meta?.subNodeIds?.length) {
        for (const sub of meta.subNodeIds) {
          if (!seen.has(sub)) {
            seen.add(sub);
            ids.push(sub);
          }
        }
      } else {
        if (!seen.has(nid)) {
          seen.add(nid);
          ids.push(nid);
        }
      }
    }
    return ids;
  }, [selectedNodeIds, allNodeMeta]);

  // ---- Fetch raw preview from API ----
  const [rawPreview, setRawPreview] = useState<MonitoringPlanPreview | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);

  const fetchFullPreview = useCallback(async () => {
    if (!stackId) return;
    setPreviewLoading(true);
    setPreviewFailed(false);
    const emptyPreview: MonitoringPlanPreview = {
      scope_type: 'custom', mode: 'recommended', families: ['full_coverage'],
      groups: [], total_nodes: 0, total_monitors: 0,
      raw_monitor_count: 0, dedup_count: 0, coverage_pct: 0,
      warnings: [], family_eligibility: [],
    };
    if (resolvedGraphNodeIds.length === 0) {
      setRawPreview(emptyPreview);
      setMonitorChecks({});
      setActivePreset(null);
      setPreviewLoading(false);
      return;
    }
    try {
      const res = await fetch('/api/schedule/plans/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scopeType: 'custom',
          scopeConfig: { nodeIds: resolvedGraphNodeIds },
          mode: 'recommended',
          families: ['full_coverage'],
          stackId,
        }),
      });
      if (res.ok) {
        const data: MonitoringPlanPreview = await res.json();
        setRawPreview(data);
      } else {
        setRawPreview(emptyPreview);
      }
      setMonitorChecks({});
      setActivePreset(null);
    } catch (err) {
      console.error('[MultiMonitor] Failed to fetch preview:', err);
      setRawPreview(emptyPreview);
    } finally {
      setPreviewLoading(false);
    }
  }, [stackId, resolvedGraphNodeIds]);

  // ---- Inject synthetic tool monitor groups (always uses current state) ----
  const preview = useMemo<MonitoringPlanPreview | null>(() => {
    if (!rawPreview) return null;
    const metaById = new Map(allNodeMeta.map((m) => [m.id, m]));
    const toolGroups: MonitoringPlanPreview['groups'] = [];

    for (const nid of selectedNodeIds) {
      const meta = metaById.get(nid);
      if (!meta?.subNodeIds?.length) continue;
      const domain = meta.domain || '';
      const domainMonitors = DOMAIN_MONITOR_MAP[domain];
      if (!domainMonitors) continue;

      const recommendations = [...domainMonitors].map((monKey) => {
        const def = getMonitorDefinition(monKey);
        return {
          monitor_key: monKey,
          target_fqn: meta.fqn,
          target_node_id: meta.id,
          source: 'tool_domain',
          reason: def?.description || `Recommended for ${domain} tools`,
          priority: 1,
          config_hints: {} as Record<string, any>,
          integration_type: meta.platform || '',
          already_monitored: false,
        };
      });

      toolGroups.push({
        group_index: rawPreview.groups.length + toolGroups.length,
        family: `${domain}_ops`,
        watch_type: 'tool_monitor',
        anchor_id: meta.id,
        anchor_name: meta.name,
        anchor_fqn: meta.fqn,
        anchor_node_type: 'tool',
        anchor_platform: meta.platform || '',
        node_count: 1,
        monitor_count: recommendations.length,
        coverage_pct: 100,
        shared_node_ids: [],
        recommendations,
      });
    }

    if (toolGroups.length === 0) return rawPreview;
    return {
      ...rawPreview,
      groups: [...rawPreview.groups, ...toolGroups],
      total_monitors: rawPreview.total_monitors + toolGroups.reduce((s, g) => s + g.recommendations.length, 0),
    };
  }, [rawPreview, allNodeMeta, selectedNodeIds]);

  // Auto-fetch preview when opening directly at step 2
  useEffect(() => {
    if (open && step === 2 && !rawPreview && !previewLoading && !previewFailed) {
      fetchFullPreview();
    }
  }, [open, step, rawPreview, previewLoading, previewFailed, fetchFullPreview]);

  // ---- Build per-node monitor map from preview (keyed by node ID) ----
  const nodeMonitorMap = useMemo(() => {
    if (!preview) return new Map<string, MonitorOption[]>();
    const map = new Map<string, MonitorOption[]>();
    preview.groups.forEach((group, gi) => {
      group.recommendations.forEach((rec, mi) => {
        const nodeId = rec.target_node_id;
        if (!nodeId) return;
        if (!map.has(nodeId)) map.set(nodeId, []);
        map.get(nodeId)!.push({
          key: rec.monitor_key,
          targetFqn: rec.target_fqn,
          targetNodeId: nodeId,
          family: group.family,
          reason: rec.reason || '',
          groupIdx: gi,
          monIdx: mi,
        });
      });
    });
    return map;
  }, [preview]);

  // ---- Selected nodes with their metadata and available monitors ----
  // Tool nodes (pipeline overview nodes with subNodeIds) only show domain-specific
  // tool monitors (e.g. Fivetran → SYNC_LAG, Airflow → DAG_LAST_RUN).
  // Data nodes only show data monitors (FRESHNESS, VOLUME, etc.).
  const selectedNodesWithMonitors = useMemo(() => {
    const selectedSet = new Set(selectedNodeIds);
    const nodes: { meta: NodeMeta; monitors: MonitorOption[] }[] = [];

    for (const nm of allNodeMeta) {
      if (!selectedSet.has(nm.id)) continue;

      const isToolNode = !!nm.subNodeIds?.length;
      let monitors: MonitorOption[];

      if (isToolNode) {
        // Tool/service node — show domain-specific tool monitors.
        // Synthetic tool monitors are injected under the tool node's own
        // ID (see injectToolMonitors); sub-nodes may also carry matching
        // keys from the preview, so deduplicate by monitor key.
        const domain = nm.domain || '';
        const domainMonitors = DOMAIN_MONITOR_MAP[domain];
        const allMons: MonitorOption[] = [];
        const seenKeys = new Set<string>();
        // Collect from the tool node's own ID first (synthetic tool monitors)
        for (const m of nodeMonitorMap.get(nm.id) || []) {
          if (!seenKeys.has(m.key)) { seenKeys.add(m.key); allMons.push(m); }
        }
        // Then from sub-nodes (skip duplicates)
        for (const subId of nm.subNodeIds!) {
          for (const m of nodeMonitorMap.get(subId) || []) {
            if (!seenKeys.has(m.key)) { seenKeys.add(m.key); allMons.push(m); }
          }
        }
        monitors = domainMonitors
          ? allMons.filter((m) => domainMonitors.has(m.key))
          : allMons.filter((m) => TOOL_ONLY_MONITOR_KEYS.has(m.key));
      } else {
        // Data node — only data monitors (exclude all tool monitors)
        const raw = nodeMonitorMap.get(nm.id) || [];
        monitors = raw.filter((m) => !TOOL_ONLY_MONITOR_KEYS.has(m.key));
      }

      nodes.push({ meta: nm, monitors });
    }

    nodes.sort((a, b) => {
      if (b.monitors.length !== a.monitors.length)
        return b.monitors.length - a.monitors.length;
      return a.meta.name.localeCompare(b.meta.name);
    });

    return nodes;
  }, [selectedNodeIds, allNodeMeta, nodeMonitorMap]);

  // (resolvedGraphNodeIds, rawPreview, preview, fetchFullPreview moved above nodeMonitorMap)

  // ---- Set of visible monitor keys after tool/data split filtering ----
  const visibleMonitorKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const { monitors } of selectedNodesWithMonitors) {
      for (const m of monitors) {
        keys.add(`${m.targetNodeId}::${m.key}`);
      }
    }
    return keys;
  }, [selectedNodesWithMonitors]);

  // ---- Apply preset (only checks monitors visible after tool/data split) ----
  const applyPreset = useCallback(
    (presetKey: string) => {
      const preset = PRESETS.find((p) => p.key === presetKey);
      if (!preset || !preview) return;

      if (activePreset === presetKey) {
        setActivePreset(null);
        setMonitorChecks({});
        return;
      }

      setActivePreset(presetKey);
      const newChecks: Record<string, boolean> = {};

      // First pass: mark all visible monitors as unchecked
      preview.groups.forEach((group) => {
        group.recommendations.forEach((rec) => {
          const checkKey = `${rec.target_node_id}::${rec.monitor_key}`;
          if (!visibleMonitorKeys.has(checkKey)) return; // skip filtered-out monitors
          if (!(checkKey in newChecks)) {
            newChecks[checkKey] = false;
          }
        });
      });

      // Second pass: check visible monitors belonging to matching families
      preview.groups.forEach((group) => {
        const familyMatch = preset.families.includes(group.family);
        if (!familyMatch) return;
        group.recommendations.forEach((rec) => {
          const checkKey = `${rec.target_node_id}::${rec.monitor_key}`;
          if (!visibleMonitorKeys.has(checkKey)) return;
          newChecks[checkKey] = true;
        });
      });

      setMonitorChecks(newChecks);
    },
    [preview, activePreset, visibleMonitorKeys],
  );

  // ---- Compute per-preset monitor counts for disabling empty presets ----
  const presetMonitorCounts = useMemo(() => {
    if (!preview) return new Map<string, number>();
    const counts = new Map<string, number>();
    for (const preset of PRESETS) {
      const keys = new Set<string>();
      preview.groups.forEach((group) => {
        if (!preset.families.includes(group.family)) return;
        group.recommendations.forEach((rec) => {
          const k = `${rec.target_node_id}::${rec.monitor_key}`;
          // Only count monitors that pass the tool/data filter
          if (visibleMonitorKeys.has(k)) keys.add(k);
        });
      });
      counts.set(preset.key, keys.size);
    }
    return counts;
  }, [preview, visibleMonitorKeys]);

  // ---- Toggle individual monitor ----
  const toggleMonitor = useCallback((nodeId: string, monitorKey: string) => {
    const key = `${nodeId}::${monitorKey}`;

    setMonitorChecks((prev) => {
      const willBeChecked = !prev[key];

      // Seed default values for tool monitors when checking
      if (willBeChecked && TOOL_ONLY_MONITOR_KEYS.has(monitorKey)) {
        const def = getMonitorDefinition(monitorKey);
        if (def) {
          const defaults: Record<string, any> = {};
          for (const field of def.config_schema) {
            if (field.default_value !== undefined) {
              defaults[field.key] = field.default_value;
            }
          }
          if (Object.keys(defaults).length > 0) {
            setMonitorConfigs((p) => ({
              ...p,
              [key]: { ...(p[key] || {}), ...defaults },
            }));
          }
        }
      }

      return { ...prev, [key]: willBeChecked };
    });
    setActivePreset(null);
  }, []);

  // ---- Toggle all monitors for a node ----
  const toggleAllForNode = useCallback(
    (_nodeId: string, monitors: MonitorOption[]) => {
      const allChecked =
        monitors.length > 0 &&
        monitors.every((m) => monitorChecks[`${m.targetNodeId}::${m.key}`]);
      const newChecks = { ...monitorChecks };
      for (const mon of monitors) {
        newChecks[`${mon.targetNodeId}::${mon.key}`] = !allChecked;
      }
      setMonitorChecks(newChecks);
      setActivePreset(null);

      // Seed default config values for tool monitors being checked
      if (!allChecked) {
        const newConfigs: Record<string, Record<string, any>> = {};
        for (const mon of monitors) {
          const key = `${mon.targetNodeId}::${mon.key}`;
          if (!TOOL_ONLY_MONITOR_KEYS.has(mon.key)) continue;
          const def = getMonitorDefinition(mon.key);
          if (!def) continue;
          const defaults: Record<string, any> = {};
          for (const field of def.config_schema) {
            if (field.default_value !== undefined) {
              defaults[field.key] = field.default_value;
            }
          }
          if (Object.keys(defaults).length > 0) {
            newConfigs[key] = defaults;
          }
        }
        if (Object.keys(newConfigs).length > 0) {
          setMonitorConfigs((prev) => {
            const merged = { ...prev };
            for (const [k, v] of Object.entries(newConfigs)) {
              merged[k] = { ...(prev[k] || {}), ...v };
            }
            return merged;
          });
        }
      }
    },
    [monitorChecks],
  );

  // ---- Toggle node section collapse ----
  const toggleNodeCollapse = useCallback((nodeId: string) => {
    setCollapsedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  // ---- Add manual monitor ----
  const addManualMonitor = useCallback(() => {
    if (!manualMonitorType || !manualTargetFqn.trim()) return;
    setManualMonitors((prev) => [
      ...prev,
      {
        id: `manual-${Date.now()}`,
        monitorType: manualMonitorType,
        targetFqn: manualTargetFqn.trim(),
        config: {},
      },
    ]);
    setManualTargetFqn('');
  }, [manualMonitorType, manualTargetFqn]);

  // ---- Remove manual monitor ----
  const removeManualMonitor = useCallback((id: string) => {
    setManualMonitors((prev) => prev.filter((m) => m.id !== id));
  }, []);

  // ---- Count checked monitors ----
  const checkedCount = useMemo(
    () => Object.values(monitorChecks).filter(Boolean).length,
    [monitorChecks],
  );

  // ---- Total monitor count (preset + manual) ----
  const totalMonitorCount = useMemo(() => {
    if (configTab === 'ai-prompt') return aiPrompt.trim().length > 0 ? 1 : 0;
    return checkedCount + manualMonitors.length;
  }, [configTab, checkedCount, manualMonitors.length, aiPrompt]);

  // ---- Step navigation ----
  const goToStep = useCallback(
    (target: Step) => {
      if (target === 2) fetchFullPreview();
      setStep(target);
    },
    [fetchFullPreview],
  );

  const incompleteToolConfig = useMemo(
    () => hasIncompleteToolConfig(monitorChecks, monitorConfigs, selectedNodesWithMonitors),
    [monitorChecks, monitorConfigs, selectedNodesWithMonitors],
  );

  const canGoNext = useMemo(() => {
    switch (step) {
      case 1:
        return selectedNodeIds.length > 0;
      case 2:
        if (configTab === 'ai-prompt') return aiPrompt.trim().length > 0;
        if (totalMonitorCount === 0) return false;
        return !incompleteToolConfig;
      case 3:
        return planName.trim().length > 0;
      default:
        return false;
    }
  }, [step, selectedNodeIds, configTab, aiPrompt, totalMonitorCount, planName, incompleteToolConfig]);

  // ---- Create plan or task ----
  const handleCreate = useCallback(async () => {
    if (!stackId) return;
    setCreating(true);
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

      if (configTab === 'ai-prompt') {
        // AI Prompt mode → wrap in a plan via POST /api/schedule/plans
        // Use selected node FQN as target, fall back to plan name
        const selectedMeta = allNodeMeta.find(n => selectedNodeIds.includes(n.id));
        const targetFqn = selectedMeta?.fqn || planName;
        const groups = [{
          anchor_name: planName,
          anchor_fqn: targetFqn,
          anchor_id: selectedMeta?.id || 'ai_prompt',
          anchor_node_type: 'prompt',
          anchor_platform: selectedMeta?.platform || 'ai',
          watch_type: 'custom_watch',
          recommendations: [{
            monitor_key: 'AI_PROMPT',
            target_fqn: targetFqn,
            config_hints: {
              taskMode: 'prompt',
              prompt: aiPrompt,
              ...(aiIntegrationId ? { integrationId: aiIntegrationId } : {}),
            },
          }],
        }];

        const res = await fetch('/api/schedule/plans', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: planName,
            scopeType: 'asset',
            mode: 'manual',
            families: [],
            schedule,
            timezone,
            alertChannels,
            alertOnStatus,
            groups,
          }),
        });
        if (res.ok) {
          onComplete();
          onClose();
        } else {
          const text = await res.text();
          try {
            const err = JSON.parse(text);
            alert(`Failed to create: ${err.error || 'Unknown error'}`);
          } catch {
            alert(`Failed to create: ${text || res.statusText}`);
          }
        }
      } else {
        // Presets / Manual mode → create plan via POST /api/schedule/plans
        if (!preview) return;

        // Reconstruct groups with only checked monitors
        const filteredGroups = preview.groups
          .map((g) => ({
            ...g,
            recommendations: g.recommendations
              .filter((rec) => {
                const key = `${rec.target_node_id}::${rec.monitor_key}`;
                return monitorChecks[key] ?? false;
              })
              .map((rec) => {
                const key = `${rec.target_node_id}::${rec.monitor_key}`;
                const extraConfig = monitorConfigs[key];
                if (extraConfig) {
                  return { ...rec, config_hints: { ...(rec.config_hints || {}), ...extraConfig } };
                }
                return rec;
              }),
          }))
          .filter((g) => g.recommendations.length > 0);

        // Add manual monitors as an extra group if any
        if (manualMonitors.length > 0) {
          filteredGroups.push({
            group_index: filteredGroups.length,
            family: 'manual',
            watch_type: 'manual',
            anchor_id: '',
            anchor_name: 'Manual Monitors',
            anchor_fqn: '',
            anchor_node_type: '',
            anchor_platform: '',
            node_count: manualMonitors.length,
            monitor_count: manualMonitors.length,
            coverage_pct: 100,
            shared_node_ids: [],
            recommendations: manualMonitors.map((m) => ({
              monitor_key: m.monitorType,
              target_fqn: m.targetFqn,
              target_node_id: '',
              source: 'manual',
              reason: 'Manually configured',
              priority: 1,
              config_hints: m.config,
              integration_type: '',
              already_monitored: false,
            })),
          });
        }

        const usedFamilies = [...new Set(filteredGroups.map((g) => g.family))];

        const res = await fetch('/api/schedule/plans', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: planName,
            scopeType: 'custom',
            scopeConfig: { nodeIds: resolvedGraphNodeIds },
            mode: activePreset || 'manual',
            families: usedFamilies,
            schedule,
            timezone,
            alertChannels,
            alertOnStatus,
            groups: filteredGroups,
          }),
        });

        if (res.ok) {
          onComplete();
          onClose();
        } else {
          const text = await res.text();
          try {
            const err = JSON.parse(text);
            alert(`Failed to create: ${err.error || 'Unknown error'}`);
          } catch {
            alert(`Failed to create: ${text || res.statusText}`);
          }
        }
      }
    } catch (err) {
      console.error('[MultiMonitor] Create error:', err);
    } finally {
      setCreating(false);
    }
  }, [
    stackId,
    configTab,
    preview,
    monitorChecks,
    monitorConfigs,
    manualMonitors,
    planName,
    resolvedGraphNodeIds,
    activePreset,
    schedule,
    alertChannels,
    alertOnStatus,
    aiPrompt,
    aiIntegrationId,
    onComplete,
    onClose,
  ]);

  if (!open) return null;

  // Count nodes that have at least one checked monitor
  const nodesWithCheckedMonitors = selectedNodesWithMonitors.filter((n) =>
    n.monitors.some((m) => monitorChecks[`${m.targetNodeId}::${m.key}`]),
  ).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal — near full-screen */}
      <div className="relative w-[95vw] max-w-[1400px] h-[92vh] bg-[var(--bg)] border border-[var(--border)] rounded-xl shadow-2xl flex flex-col overflow-hidden">
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-4">
            <h2 className="text-[16px] font-semibold text-[var(--text)]">
              New Monitor
            </h2>

            {/* Step indicators */}
            <div className="flex items-center gap-1">
              {([1, 2, 3] as Step[]).map((s) => (
                <button
                  key={s}
                  onClick={() => s < step && goToStep(s)}
                  disabled={s > step}
                  className={cn(
                    'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors',
                    s === step
                      ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                      : s < step
                        ? 'text-[var(--muted)] hover:text-[var(--text)] cursor-pointer'
                        : 'text-[var(--muted)]/40 cursor-default',
                  )}
                >
                  <span
                    className={cn(
                      'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold',
                      s === step
                        ? 'bg-[var(--accent)] text-white'
                        : s < step
                          ? 'bg-[var(--muted)]/20 text-[var(--text)]'
                          : 'bg-[var(--muted)]/10 text-[var(--muted)]/40',
                    )}
                  >
                    {s < step ? (
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : (
                      s
                    )}
                  </span>
                  <span className="hidden sm:inline">{STEP_LABELS[s]}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Close button */}
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-[var(--subtle-bg)] rounded-lg transition-colors"
          >
            <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* ---- Body ---- */}
        <div className="flex-1 overflow-y-auto">
          {/* ============ Step 1: Select Assets ============ */}
          {step === 1 && stackId && (
            <div className="h-full flex flex-col">
              <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--border)]">
                <span className="text-[11px] text-[var(--muted)] mr-1">View:</span>
                <button
                  onClick={() => setViewMode('lineage')}
                  className={cn(
                    'px-2.5 py-1 rounded text-[11px] font-medium transition-colors',
                    viewMode === 'lineage'
                      ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                      : 'text-[var(--muted)] hover:text-[var(--text)]',
                  )}
                >
                  Lineage
                </button>
                <button
                  onClick={() => setViewMode('pipeline-overview')}
                  className={cn(
                    'px-2.5 py-1 rounded text-[11px] font-medium transition-colors',
                    viewMode === 'pipeline-overview'
                      ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                      : 'text-[var(--muted)] hover:text-[var(--text)]',
                  )}
                >
                  Pipeline Overview
                </button>
              </div>
              <div className="flex-1">
                <NodeSelectionSurface
                  stackId={stackId}
                  mode={viewMode}
                  selectedNodeIds={selectedNodeIds}
                  onSelectionChange={setSelectedNodeIds}
                  preselectedNodeIds={preselectedNodeIds}
                  onNodesLoaded={handleNodesLoaded}
                />
              </div>
            </div>
          )}

          {/* ============ Step 2: Configure Monitors ============ */}
          {step === 2 && (
            <div className="h-full flex flex-col">
              {/* Tab bar */}
              <div className="shrink-0 px-6 pt-4 pb-0 border-b border-[var(--border)]">
                <div className="flex items-center gap-1">
                  {CONFIG_TABS.map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => setConfigTab(tab.key)}
                      className={cn(
                        'flex items-center gap-2 px-4 py-2.5 text-[13px] font-medium border-b-2 transition-colors -mb-px',
                        configTab === tab.key
                          ? 'border-[var(--accent)] text-[var(--accent)]'
                          : 'border-transparent text-[var(--muted)] hover:text-[var(--text)]',
                      )}
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={tab.icon} />
                      </svg>
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* ---- Presets Tab ---- */}
              {configTab === 'presets' && (
                <div className="flex-1 overflow-y-auto">
                  {/* Presets grid */}
                  <div className="shrink-0 px-6 py-4 border-b border-[var(--border)]">
                    <div className="flex items-center gap-2 mb-3">
                      <h3 className="text-[13px] font-medium text-[var(--text)]">Quick Setup</h3>
                      <span className="text-[11px] text-[var(--muted)]">— choose a preset or toggle monitors manually below</span>
                    </div>
                    <div className="grid grid-cols-3 lg:grid-cols-7 gap-2">
                      {PRESETS.map((preset) => {
                        const isActive = activePreset === preset.key;
                        const monCount = presetMonitorCounts.get(preset.key) ?? 0;
                        const isEmpty = !previewLoading && monCount === 0;
                        return (
                          <button
                            key={preset.key}
                            onClick={() => applyPreset(preset.key)}
                            disabled={previewLoading || isEmpty}
                            className={cn(
                              'text-left p-3 rounded-lg border transition-all',
                              isActive
                                ? 'border-[var(--accent)] bg-[var(--accent)]/5 shadow-[0_0_0_1px_var(--accent)]'
                                : isEmpty
                                  ? 'border-[var(--border)] bg-[var(--surface)] opacity-35 cursor-not-allowed'
                                  : 'border-[var(--border)] hover:border-[var(--accent)]/50 bg-[var(--surface)]',
                              previewLoading && 'opacity-50 cursor-not-allowed',
                            )}
                          >
                            <div className="flex items-center gap-2 mb-1">
                              <svg
                                className={cn('w-4 h-4 shrink-0', isActive ? 'text-[var(--accent)]' : 'text-[var(--muted)]')}
                                fill="none" stroke="currentColor" viewBox="0 0 24 24"
                              >
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={preset.iconPath} />
                              </svg>
                              <span className="text-[12px] font-medium text-[var(--text)] truncate">{preset.label}</span>
                            </div>
                            <p className="text-[10px] text-[var(--muted)] leading-relaxed line-clamp-2">
                              {isEmpty ? 'Not applicable for selected assets' : preset.description}
                            </p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Per-node monitor configuration with rich cards */}
                  <div className="px-6 py-4">
                    {previewLoading ? (
                      <div className="space-y-3">
                        {[1, 2, 3, 4, 5].map((i) => (
                          <div key={i} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 animate-pulse">
                            <div className="flex items-center gap-3 mb-3">
                              <div className="h-4 w-4 rounded bg-[var(--muted)]/20" />
                              <div className="h-4 w-32 rounded bg-[var(--muted)]/20" />
                              <div className="h-3 w-20 rounded bg-[var(--muted)]/15" />
                            </div>
                            <div className="flex gap-2 ml-7">
                              <div className="h-16 w-48 rounded bg-[var(--muted)]/10" />
                              <div className="h-16 w-44 rounded bg-[var(--muted)]/10" />
                              <div className="h-16 w-52 rounded bg-[var(--muted)]/10" />
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : selectedNodesWithMonitors.length === 0 ? (
                      <div className="flex items-center justify-center h-64 text-[13px] text-[var(--muted)]">
                        No monitor data available. Go back to select assets.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {/* Header stats */}
                        <div className="flex items-center gap-4 mb-3">
                          <span className="text-[13px] text-[var(--text)]">
                            <span className="font-medium">{selectedNodesWithMonitors.length}</span> assets
                          </span>
                          <span className="text-[13px] text-[var(--text)]">
                            <span className="font-medium text-[var(--accent)]">{checkedCount}</span> monitors selected
                          </span>
                          {activePreset && (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[var(--accent)]/15 text-[var(--accent)]">
                              {PRESETS.find((p) => p.key === activePreset)?.label}
                            </span>
                          )}
                          {!activePreset && checkedCount > 0 && (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-white/10 text-[var(--muted)]">
                              Custom
                            </span>
                          )}
                        </div>

                        {/* Node sections with rich monitor cards */}
                        {selectedNodesWithMonitors.map(({ meta, monitors }) => {
                          const allChecked =
                            monitors.length > 0 &&
                            monitors.every((m) => monitorChecks[`${m.targetNodeId}::${m.key}`]);
                          const someChecked = monitors.some(
                            (m) => monitorChecks[`${m.targetNodeId}::${m.key}`],
                          );
                          const checkedForNode = monitors.filter(
                            (m) => monitorChecks[`${m.targetNodeId}::${m.key}`],
                          ).length;
                          const isCollapsed = collapsedNodes.has(meta.id);

                          return (
                            <div
                              key={meta.id}
                              className={cn(
                                'rounded-lg border bg-[var(--surface)] transition-colors',
                                someChecked ? 'border-[var(--accent)]/30' : 'border-[var(--border)]',
                              )}
                            >
                              {/* Node header */}
                              <div
                                className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none"
                                onClick={() => toggleNodeCollapse(meta.id)}
                              >
                                {monitors.length > 0 && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      toggleAllForNode(meta.id, monitors);
                                    }}
                                    className={cn(
                                      'w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors',
                                      allChecked
                                        ? 'bg-[var(--accent)] border-[var(--accent)]'
                                        : someChecked
                                          ? 'bg-[var(--accent)]/50 border-[var(--accent)]'
                                          : 'border-[var(--border)] hover:border-[var(--muted)]',
                                    )}
                                  >
                                    {(allChecked || someChecked) && (
                                      <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d={allChecked ? 'M5 13l4 4L19 7' : 'M5 12h14'} />
                                      </svg>
                                    )}
                                  </button>
                                )}
                                <span className="text-[13px] font-medium text-[var(--text)]">{meta.name}</span>
                                <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', DOMAIN_COLORS[meta.domain] || 'bg-white/10 text-white/50')}>
                                  {meta.platform}
                                </span>
                                <span className="text-[11px] text-[var(--muted)] font-mono truncate max-w-[400px]" title={meta.fqn}>
                                  {meta.fqn}
                                </span>
                                {monitors.length > 0 && (
                                  <span className="ml-auto text-[11px] text-[var(--muted)] tabular-nums shrink-0">
                                    {checkedForNode}/{monitors.length}
                                  </span>
                                )}
                                {/* Collapse chevron */}
                                <svg
                                  className={cn('w-4 h-4 text-[var(--muted)] transition-transform shrink-0', isCollapsed ? '-rotate-90' : '')}
                                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                >
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                </svg>
                              </div>

                              {/* Monitor cards (collapsible) */}
                              {!isCollapsed && (
                                <div className="px-4 pb-4">
                                  {monitors.length > 0 ? (
                                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 ml-7">
                                      {monitors.map((mon) => {
                                        const checkKey = `${mon.targetNodeId}::${mon.key}`;
                                        const checked = monitorChecks[checkKey] ?? false;
                                        const isOutlier = mon.key === 'OUTLIER_DETECTION' || mon.key === 'ANOMALY';
                                        return (
                                          <div key={checkKey}>
                                            <MonitorCard
                                              mon={mon}
                                              checked={checked}
                                              onToggle={() => toggleMonitor(mon.targetNodeId, mon.key)}
                                              showTarget={!!meta.subNodeIds}
                                              isToolNode={!!meta.subNodeIds?.length}
                                              config={monitorConfigs[checkKey]}
                                              onConfigChange={(fieldKey, value) =>
                                                setMonitorConfigs((prev) => ({
                                                  ...prev,
                                                  [checkKey]: { ...(prev[checkKey] || {}), [fieldKey]: value },
                                                }))
                                              }
                                            />
                                            {checked && isOutlier && mon.targetFqn && (
                                              <div className="ml-7 mt-1 mb-2">
                                                <label className="text-[10px] text-[var(--muted)] uppercase tracking-wide mb-1 block">Column to monitor</label>
                                                <ColumnPicker
                                                  targetFqn={mon.targetFqn}
                                                  stackId={stackId}
                                                  value={monitorConfigs[checkKey]?.column || ''}
                                                  onChange={(col) => setMonitorConfigs(prev => ({
                                                    ...prev,
                                                    [checkKey]: { ...(prev[checkKey] || {}), column: col },
                                                  }))}
                                                  numericOnly
                                                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-2 py-1.5 text-[12px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)]"
                                                />
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  ) : (
                                    <p className="text-[11px] text-[var(--muted)] ml-7 italic">
                                      No applicable monitors for this asset type
                                    </p>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* ---- AI Prompt Tab ---- */}
              {configTab === 'ai-prompt' && (
                <div className="flex-1 overflow-y-auto px-6 py-6">
                  <div className="max-w-2xl mx-auto space-y-6">
                    <div>
                      <h3 className="text-[15px] font-medium text-[var(--text)] mb-1">
                        Describe your monitoring needs
                      </h3>
                      <p className="text-[12px] text-[var(--muted)]">
                        Write what you want monitored in natural language. The AI will create and configure the appropriate monitors.
                      </p>
                    </div>

                    <textarea
                      value={aiPrompt}
                      onChange={(e) => setAiPrompt(e.target.value)}
                      placeholder="e.g., Check if the orders table has received fresh data in the last 24 hours. If stale, report which datasets haven't been updated."
                      rows={6}
                      className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-lg px-4 py-3 text-[13px] text-[var(--text)] placeholder-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)] resize-none"
                      autoFocus
                    />

                    {/* Warehouse selector */}
                    {warehouseIntegrations.length > 0 && (
                      <div>
                        <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                          Run against warehouse
                        </label>
                        <select
                          value={aiIntegrationId}
                          onChange={(e) => setAiIntegrationId(e.target.value)}
                          className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--accent)] appearance-none"
                        >
                          <option value="">Auto-detect</option>
                          {warehouseIntegrations.map((i, idx) => (
                            <option key={`${i.id}-${idx}`} value={i.id}>
                              {i.name} ({i.type})
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                    {/* Selected assets context */}
                    <div className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--border)]">
                      <p className="text-[11px] text-[var(--muted)] mb-2">
                        Selected assets ({selectedNodeIds.length})
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {selectedNodesWithMonitors.slice(0, 10).map(({ meta }) => (
                          <span
                            key={meta.id}
                            className={cn(
                              'px-2 py-0.5 rounded text-[10px] font-medium',
                              DOMAIN_COLORS[meta.domain] || 'bg-white/10 text-white/50',
                            )}
                          >
                            {meta.name}
                          </span>
                        ))}
                        {selectedNodesWithMonitors.length > 10 && (
                          <span className="px-2 py-0.5 rounded text-[10px] text-[var(--muted)] bg-white/5">
                            +{selectedNodesWithMonitors.length - 10} more
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* ---- Manual Tab ---- */}
            </div>
          )}

          {/* ============ Step 3: Finalize & Create ============ */}
          {step === 3 && (
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-lg mx-auto py-8 px-6 space-y-6">
                {/* Title */}
                <div className="text-center">
                  <h3 className="text-[18px] font-semibold text-[var(--text)]">
                    {configTab === 'ai-prompt' ? 'Name Your AI Monitor' : 'Finalize Your Monitor'}
                  </h3>
                  <p className="text-[13px] text-[var(--muted)] mt-2">
                    {configTab === 'ai-prompt' ? (
                      'AI will configure monitors from your prompt'
                    ) : (
                      <>
                        <span className="font-medium text-[var(--accent)]">{totalMonitorCount}</span>{' '}
                        monitors across{' '}
                        <span className="font-medium">{nodesWithCheckedMonitors}</span>{' '}
                        assets
                      </>
                    )}
                  </p>
                </div>

                {/* Name */}
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Name</label>
                  <input
                    value={planName}
                    onChange={(e) => setPlanName(e.target.value)}
                    placeholder="e.g. Production Pipeline Health"
                    className="w-full px-4 py-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[14px] placeholder:text-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)] text-center"
                    autoFocus
                  />
                </div>

                {/* Schedule */}
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Schedule</label>
                  <ScheduleInput value={schedule} onChange={setSchedule} />
                </div>

                {/* Alert Channels */}
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Alerts</label>
                  <AlertChannelPicker
                    channels={alertChannels}
                    onChannelsChange={setAlertChannels}
                    alertOnStatus={alertOnStatus}
                    onAlertOnStatusChange={setAlertOnStatus}
                  />
                </div>

                {/* Summary badge */}
                {activePreset && configTab === 'presets' && (
                  <div className="text-center">
                    <span className="px-3 py-1 rounded-full text-[11px] font-medium bg-[var(--accent)]/10 text-[var(--accent)]">
                      {PRESETS.find((p) => p.key === activePreset)?.label}
                    </span>
                  </div>
                )}
                {/* Tool monitor config summary */}
                {configTab === 'presets' && (() => {
                  const toolMons = selectedNodesWithMonitors.flatMap(({ meta, monitors }) => {
                    if (!meta.subNodeIds?.length) return [];
                    return monitors
                      .filter((m) => TOOL_ONLY_MONITOR_KEYS.has(m.key) && monitorChecks[`${m.targetNodeId}::${m.key}`])
                      .map((m) => {
                        const def = getMonitorDefinition(m.key);
                        return { mon: m, label: def?.label || m.key, nodeName: meta.name };
                      });
                  });
                  if (toolMons.length === 0) return null;
                  return (
                    <div className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--border)]">
                      <p className="text-[11px] text-[var(--muted)] mb-2">Tool Monitors</p>
                      <div className="space-y-1.5">
                        {toolMons.map(({ mon, label, nodeName }) => (
                          <div key={`${mon.targetNodeId}::${mon.key}`} className="flex items-center gap-2">
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-emerald-500/15 text-emerald-400">
                              Configured
                            </span>
                            <span className="text-[12px] text-[var(--text)]">{label}</span>
                            <span className="text-[10px] text-[var(--muted)]">on {nodeName}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })()}
                {configTab === 'ai-prompt' && (
                  <div className="p-3 rounded-lg bg-[var(--surface)] border border-[var(--border)]">
                    <p className="text-[11px] text-[var(--muted)] mb-1">Prompt</p>
                    <p className="text-[12px] text-[var(--text)] line-clamp-3">{aiPrompt}</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ---- Footer ---- */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-[var(--border)] bg-[var(--surface)] shrink-0">
          <button
            onClick={() => step === 1 ? onClose() : goToStep((step - 1) as Step)}
            className="px-4 py-2 text-[13px] text-[var(--muted)] hover:text-[var(--text)] transition-colors"
          >
            {step === 1 ? 'Cancel' : 'Back'}
          </button>

          {step < 3 ? (
            <div className="flex items-center">
              {step === 2 && incompleteToolConfig && (
                <span className="text-[11px] text-amber-400 mr-3">
                  Configure all selected tool monitors before proceeding
                </span>
              )}
              <button
                onClick={() => goToStep((step + 1) as Step)}
                disabled={!canGoNext}
                className={cn(
                  'px-5 py-2 rounded-lg text-[13px] font-medium transition-colors',
                  canGoNext
                    ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90'
                    : 'bg-[var(--muted)]/20 text-[var(--muted)] cursor-not-allowed',
                )}
              >
                {step === 2
                  ? configTab === 'ai-prompt'
                    ? 'Next'
                    : `Next \u00b7 ${totalMonitorCount} monitors`
                  : 'Next'}
              </button>
            </div>
          ) : (
            <button
              onClick={handleCreate}
              disabled={!canGoNext || creating}
              className={cn(
                'px-5 py-2 rounded-lg text-[13px] font-medium transition-colors',
                canGoNext && !creating
                  ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90'
                  : 'bg-[var(--muted)]/20 text-[var(--muted)] cursor-not-allowed',
              )}
            >
              {creating ? 'Creating...' : configTab === 'ai-prompt' ? 'Create AI Monitor' : 'Create Monitor'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
