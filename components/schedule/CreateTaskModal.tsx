'use client';

import { useState, useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import { MonitorConfigForm } from './MonitorConfigForm';
import type { ScheduledTask } from '@/types/schedule';
import {
  type MonitorDefinition,
  type MonitorCategory,
  getMonitorDefinition,
  TOOL_MONITOR_TYPES,
} from '@/types/monitor-catalog';

interface MonitorGroup {
  category: MonitorCategory;
  label: string;
  monitors: MonitorDefinition[];
}

interface IntegrationNode {
  id: string;
  name: string;
  toolType: string;
  layer: string;
  integrationId: string | null;
  sourceMode: string | null;
  hasLiveConnection: boolean;
}

export interface MonitorPrefillData {
  name: string;
  monitorType: string;
  targetFqn?: string;
  config?: Record<string, any>;
  integrationId?: string;
}

export interface BundlePrefillData {
  name: string;
  groupType: string;
  anchorFqn: string;
  anchorNodeId?: string;
  monitors: Array<{
    name: string;
    monitorType: string;
    targetFqn: string;
    config?: Record<string, any>;
  }>;
}

interface CreateTaskModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (task: any) => void;
  onUpdate?: (taskId: string, task: any) => void;
  editTask?: ScheduledTask | null;
  prefillData?: MonitorPrefillData | null;
  bundlePrefillData?: BundlePrefillData | null;
  integrations?: Array<{ id: string; name: string; type: string }>;
  stackId?: string;
}

export function CreateTaskModal({ open, onClose, onSubmit, onUpdate, editTask, prefillData, bundlePrefillData, integrations = [], stackId }: CreateTaskModalProps) {
  const [step, setStep] = useState(1);
  const isEditing = !!editTask;

  // Step 1: Mode + content
  const [taskMode, setTaskMode] = useState<'prompt' | 'structured' | 'bundle'>('prompt');
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [monitorType, setMonitorType] = useState('');
  const [targetFqn, setTargetFqn] = useState('');
  const [config, setConfig] = useState<Record<string, any>>({});

  // Bundle mode state
  const [bundleGroupType, setBundleGroupType] = useState('upstream_stability');
  const [bundleAnchorFqn, setBundleAnchorFqn] = useState('');
  const [bundleAnchorNodeId, setBundleAnchorNodeId] = useState('');
  const [bundleMonitors, setBundleMonitors] = useState<Array<{
    name: string;
    monitorType: string;
    targetFqn: string;
    config?: Record<string, any>;
  }>>([]);
  const [bundleSearchQuery, setBundleSearchQuery] = useState('');
  const [bundleSearchResults, setBundleSearchResults] = useState<Array<{ id: string; name: string; fqn: string }>>([]);
  const [bundleSearching, setBundleSearching] = useState(false);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Step 2: Schedule
  const [schedule, setSchedule] = useState('0 8 * * *');
  const [timezone, setTimezone] = useState('UTC');

  // Step 3: Alerts
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);
  const [integrationId, setIntegrationId] = useState('');
  const [connectedChannels, setConnectedChannels] = useState<string[]>(['email']);

  // Catalog data
  const [groupedMonitors, setGroupedMonitors] = useState<MonitorGroup[]>([]);
  const [integrationNodes, setIntegrationNodes] = useState<IntegrationNode[]>([]);

  // Fetch monitor catalog when modal opens
  useEffect(() => {
    if (!open) return;
    const url = stackId
      ? `/api/schedule/monitor-catalog?stackId=${stackId}`
      : '/api/schedule/monitor-catalog';
    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        setGroupedMonitors(data.grouped || []);
        setIntegrationNodes(data.integrationNodes || []);
      })
      .catch(() => {
        setGroupedMonitors([]);
        setIntegrationNodes([]);
      });
  }, [open, stackId]);

  // Pre-fill form when editing an existing task or from recommendation prefill
  useEffect(() => {
    if (editTask) {
      setName(editTask.name);
      setTaskMode(editTask.taskMode);
      setPrompt(editTask.prompt || '');
      setMonitorType(editTask.monitorType || '');
      setTargetFqn(editTask.targetFqn || '');
      setConfig(editTask.config || {});
      setSchedule(editTask.schedule);
      setTimezone(editTask.timezone);
      setAlertChannels(editTask.alertChannels || []);
      setAlertOnStatus(editTask.alertOnStatus || ['FAIL', 'WARN', 'ERROR']);
      setIntegrationId(editTask.integrationId || '');
      setStep(1);
    } else if (bundlePrefillData && open) {
      setName(bundlePrefillData.name);
      setTaskMode('bundle');
      setBundleGroupType(bundlePrefillData.groupType);
      setBundleAnchorFqn(bundlePrefillData.anchorFqn);
      setBundleAnchorNodeId(bundlePrefillData.anchorNodeId || '');
      setBundleMonitors(bundlePrefillData.monitors);
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setIntegrationId('');
      setStep(1);
    } else if (prefillData && open) {
      setName(prefillData.name);
      setTaskMode('structured');
      setPrompt('');
      setMonitorType(prefillData.monitorType);
      setTargetFqn(prefillData.targetFqn || '');
      setConfig(prefillData.config || {});
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setIntegrationId(prefillData.integrationId || '');
      setStep(1);
    } else if (open) {
      setName('');
      setTaskMode('prompt');
      setPrompt('');
      setMonitorType('');
      setTargetFqn('');
      setConfig({});
      setBundleGroupType('upstream_stability');
      setBundleAnchorFqn('');
      setBundleAnchorNodeId('');
      setBundleMonitors([]);
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setIntegrationId('');
      setStep(1);
    }
  }, [editTask, prefillData, bundlePrefillData, open]);

  // Fetch connected channel status when modal opens
  useEffect(() => {
    if (!open) return;
    const channels = ['email'];
    fetch('/api/integrations/slack')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data?.connected) channels.push('slack');
        setConnectedChannels(channels);
      })
      .catch(() => setConnectedChannels(channels));
  }, [open]);

  if (!open) return null;

  // Get the selected monitor definition from catalog
  const selectedDef = getMonitorDefinition(monitorType);
  const targetType = selectedDef?.target_selector_type || 'fqn';
  const isToolMonitor = TOOL_MONITOR_TYPES.includes(monitorType);
  const isInfraMonitor = targetType === 'server';
  const needsFqnTarget = targetType === 'fqn';

  // Filter integrations based on selected monitor's target type
  const warehouseIntegrations = integrations.filter((i, idx, arr) => {
    const t = i.type.toLowerCase();
    return ['bigquery', 'snowflake', 'postgres', 'redshift'].includes(t) &&
      arr.findIndex((x) => x.id === i.id) === idx;
  });
  const serverIntegrations = integrations.filter((i, idx, arr) => {
    const t = i.type.toLowerCase();
    return ['linux_server'].includes(t) &&
      arr.findIndex((x) => x.id === i.id) === idx;
  });

  // For tool monitors, find matching integration nodes
  const toolIntegrations = isToolMonitor && selectedDef
    ? integrationNodes.filter((n) =>
        selectedDef.required_integrations.includes(n.toolType.toLowerCase())
      )
    : [];

  // Check if any matching tool integration lacks a live API connection
  const selectedToolNode = toolIntegrations.find((n) => n.id === integrationId) || toolIntegrations[0];
  const toolNeedsLiveConnection = isToolMonitor && selectedToolNode && !selectedToolNode.hasLiveConnection;
  const toolConnectionModeLabel = (() => {
    if (!selectedToolNode) return '';
    const mode = selectedToolNode.sourceMode;
    const tool = selectedToolNode.toolType.toLowerCase();
    if (tool === 'airflow' && mode === 'github') return 'GitHub DAG Files';
    if (tool === 'dbt_core') {
      if (mode === 'upload') return 'Manifest Upload';
      if (mode === 'project') return 'Project Upload';
      if (mode === 'github') return 'GitHub Repository';
      return 'Static Files';
    }
    return mode || 'static';
  })();

  // Validation for step 1
  const needsColumn = ['ANOMALY', 'anomaly'].includes(monitorType)
    && config.metric && config.metric !== 'row_count' && config.column !== '*'
    && !config.column?.trim();
  const needsSql = monitorType === 'CUSTOM_SQL' && !config.sql?.trim();
  const needsLogPaths = monitorType === 'LOG_ANALYSIS' && !(config.log_paths?.length > 0);

  // Tool monitor required fields check
  const hasRequiredToolFields = (() => {
    if (!isToolMonitor || !selectedDef) return true;
    return selectedDef.config_schema
      .filter((f) => f.required)
      .every((f) => {
        const val = config[f.key];
        return val !== undefined && val !== null && val !== '';
      });
  })();

  const canProceedStep1 = name.trim() && (
    taskMode === 'prompt'
      ? prompt.trim()
      : taskMode === 'bundle'
      ? true
      : (monitorType && (
          isInfraMonitor || isToolMonitor
            ? hasRequiredToolFields && !needsLogPaths
            : (targetFqn.trim() && !needsColumn && !needsSql)
        ))
  );
  const canProceedStep2 = schedule.trim();

  // Bundle: search for lineage nodes to use as anchor (with debounce)
  const searchLineageNodes = (query: string) => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!query.trim()) {
      setBundleSearchResults([]);
      setBundleSearching(false);
      return;
    }
    setBundleSearching(true);
    searchTimerRef.current = setTimeout(async () => {
      try {
        let results: Array<{ id: string; name: string; fqn: string }> = [];

        // Only show data-asset node types that appear on the visual lineage canvas.
        // Engine search returns node_type/platform_domain; Prisma returns nodeType.
        const VISIBLE_SEARCH_TYPES = new Set(['table', 'view', 'materialized_view', 'source', 'model']);

        // Try engine search first (in-memory graph)
        if (stackId) {
          const engineRes = await fetch(
            `/api/pipeline/${stackId}/lineage/engine?action=search&q=${encodeURIComponent(query)}&limit=20`
          );
          if (engineRes.ok) {
            const data = await engineRes.json();
            results = (data.results || [])
              .filter((r: any) => {
                const nt = (r.node_type || '').toLowerCase();
                return !nt || VISIBLE_SEARCH_TYPES.has(nt);
              })
              .slice(0, 10)
              .map((r: any) => ({
                id: r.id,
                name: r.name,
                fqn: r.fqn || r.name,
              }));
          }
        }

        // Fall back to Prisma search if engine returned nothing
        if (results.length === 0) {
          const dbRes = await fetch(
            `/api/lineage/search?q=${encodeURIComponent(query)}&limit=20`
          );
          if (dbRes.ok) {
            const data = await dbRes.json();
            results = (data.results || [])
              .filter((r: any) => {
                const nt = (r.nodeType || '').toLowerCase();
                return !nt || VISIBLE_SEARCH_TYPES.has(nt);
              })
              .slice(0, 10)
              .map((r: any) => ({
                id: r.id,
                name: r.name,
                fqn: r.fqn || r.name,
              }));
          }
        }

        setBundleSearchResults(results);
      } catch {}
      setBundleSearching(false);
    }, 300);
  };

  // Available scanner types for bundle per-node selection
  const BUNDLE_SCANNER_OPTIONS = [
    { value: 'FRESHNESS', label: 'Freshness' },
    { value: 'VOLUME', label: 'Volume' },
    { value: 'SCHEMA_CHANGE', label: 'Schema Change' },
    { value: 'ANOMALY', label: 'Anomaly' },
    { value: 'UNIQUENESS', label: 'Uniqueness' },
    { value: 'CUSTOM_SQL', label: 'Custom SQL' },
    { value: 'SYNC_LAG', label: 'Sync Lag' },
    { value: 'FAILED_SYNCS', label: 'Failed Syncs' },
    { value: 'DAG_LAST_RUN', label: 'DAG Last Run' },
    { value: 'TASK_FAILURE_RATE', label: 'Task Failure Rate' },
    { value: 'DBT_TEST_FAILURES', label: 'dbt Test Failures' },
    { value: 'DBT_MODEL_FRESHNESS', label: 'dbt Model Freshness' },
    { value: 'DBT_SOURCE_FRESHNESS', label: 'dbt Source Freshness' },
    { value: 'SERVER_HEALTH', label: 'Server Health' },
  ];

  // Pick a default monitor type based on engine node metadata
  const getDefaultMonitorType = (node: any): string => {
    const platform = (node.platform || '').toLowerCase();
    const nodeType = (node.node_type || '').toLowerCase();
    const domain = (node.platform_domain || '').toLowerCase();
    const dbtType = (node.dbt_resource_type || '').toLowerCase();

    // Tool / connector nodes
    if (['fivetran', 'airbyte'].includes(platform) || domain === 'ingestion') return 'SYNC_LAG';
    if (platform === 'airflow' && nodeType === 'dag') return 'DAG_LAST_RUN';
    if (platform === 'airflow' && nodeType === 'task') return 'TASK_FAILURE_RATE';

    // dbt nodes
    if (['dbt', 'dbt_core', 'dbt_cloud'].includes(platform)) {
      if (dbtType === 'source') return 'DBT_SOURCE_FRESHNESS';
      return 'DBT_MODEL_FRESHNESS';
    }

    // Server / infra
    if (nodeType === 'server' || domain === 'infrastructure') return 'SERVER_HEALTH';

    // Default for data assets (tables, views, models, dashboards)
    return 'FRESHNESS';
  };

  // DESIGN RULE: Bundle/watch creation launched from the data-lineage surface
  // must use the same upstream visibility semantics as that surface.
  // We restrict BFS to DATA-plane edges only (via plane=data) and post-filter
  // to match the ViewBuilder's data-plane view which only includes 'dataset'
  // and 'semantic' canonical types. The unified route maps plane=data to
  // "data,cross" (BI→table edges use CROSS plane), and the canonical type
  // whitelist prevents orchestration nodes from leaking through.
  // Future bundle/watch templates can opt into non-data-plane nodes later.

  // Visibility filter matching the ViewBuilder data-plane view (views.py:2840-2843).
  // The visual lineage canvas only renders nodes with canonical_type 'dataset' or
  // 'semantic'. Everything else (system, service, job — including connectors like
  // Fivetran/Postgres, orchestration DAGs/tasks, infrastructure nodes) is excluded.
  const DATA_PLANE_CANONICAL_TYPES = new Set(['dataset', 'semantic']);

  const isVisibleInDataLineage = (node: any): boolean => {
    const canonicalType = (node.canonical_type || '').toLowerCase();
    return DATA_PLANE_CANONICAL_TYPES.has(canonicalType);
  };

  // Bundle: fetch visible upstream data assets for the selected anchor
  const fetchUpstreamNodes = async (nodeId: string, nodeFqn: string) => {
    if (stackId) {
      try {
        // Fetch upstream via DATA+CROSS plane edges — matches the unified route's
        // "data,cross" mapping. CROSS is needed for BI→table edges.
        // The canonical type whitelist below prevents orchestration nodes from
        // leaking through CROSS edges.
        const upstreamRes = await fetch(
          `/api/pipeline/${stackId}/lineage/engine?action=upstream&id=${encodeURIComponent(nodeId)}&depth=5&plane=data,cross`
        );
        if (!upstreamRes.ok) throw new Error('upstream failed');
        const upstreamData = await upstreamRes.json();
        const upstreamNodes: any[] = upstreamData.upstream || [];

        // Post-filter: only include nodes visible in the data-lineage surface.
        // The ViewBuilder data-plane view only shows 'dataset' and 'semantic'
        // canonical types — this excludes connectors, DAGs, tasks, services, etc.
        const visibleNodes = upstreamNodes.filter(isVisibleInDataLineage);

        // FQN-based dedup: Airflow/Fivetran adapters create table reference nodes
        // that duplicate real warehouse nodes. The visual lineage merges these by
        // FQN — we do the same here, preferring non-tool-platform nodes.
        const DEDUP_PLATFORMS = new Set(['airflow', 'fivetran']);
        const fqnToNode = new Map<string, any>();
        for (const n of visibleNodes) {
          const fqn = n.fqn || n.name || n.id;
          const existing = fqnToNode.get(fqn);
          if (!existing) {
            fqnToNode.set(fqn, n);
          } else {
            // Prefer the non-tool-platform node (warehouse node over Airflow ref)
            const existingPlatform = (existing.platform || '').toLowerCase();
            const nPlatform = (n.platform || '').toLowerCase();
            if (DEDUP_PLATFORMS.has(existingPlatform) && !DEDUP_PLATFORMS.has(nPlatform)) {
              fqnToNode.set(fqn, n);
            }
          }
        }

        const monitors: Array<{ name: string; monitorType: string; targetFqn: string; config: Record<string, any> }> = [];
        for (const [fqn, n] of fqnToNode) {
          const monType = getDefaultMonitorType(n);
          const shortName = fqn.split('.').pop() || fqn;
          monitors.push({
            name: `${monType.toLowerCase().replace(/_/g, ' ')} — ${shortName}`,
            monitorType: monType,
            targetFqn: fqn,
            config: {},
          });
        }

        if (monitors.length > 0) {
          setBundleMonitors(monitors);
          return;
        }
      } catch {}
    }

    // Fallback: fetch upstream from Prisma lineage edges.
    // Apply same visibility rule: only data asset node types that appear on the
    // visual lineage canvas (tables, views, models, sources).
    const VISIBLE_NODE_TYPES = new Set(['table', 'view', 'materialized_view', 'source', 'model']);
    try {
      const res = await fetch(`/api/lineage/upstream?fqn=${encodeURIComponent(nodeFqn)}&limit=20`);
      if (res.ok) {
        const data = await res.json();
        const allNodes = data.nodes || [];
        const nodes = allNodes.filter((n: any) => {
          const nt = (n.nodeType || '').toLowerCase();
          return !nt || VISIBLE_NODE_TYPES.has(nt);
        });
        if (nodes.length > 0) {
          const seen = new Set<string>();
          setBundleMonitors(
            nodes.filter((n: any) => {
              const fqn = n.fqn || n.name;
              if (seen.has(fqn)) return false;
              seen.add(fqn);
              return true;
            }).map((n: any) => {
              const fqn = n.fqn || n.name;
              const shortName = fqn.split('.').pop() || fqn;
              return {
                name: `freshness — ${shortName}`,
                monitorType: 'FRESHNESS',
                targetFqn: fqn,
                config: {},
              };
            })
          );
          return;
        }
      }
    } catch {}

    // Last fallback: just the anchor itself
    const shortName = nodeFqn.split('.').pop() || nodeFqn;
    setBundleMonitors([
      { name: `freshness — ${shortName}`, monitorType: 'FRESHNESS', targetFqn: nodeFqn, config: {} },
    ]);
  };

  const handleSubmit = () => {
    if (taskMode === 'bundle') {
      // Submit as bundle
      const bundleData = {
        name,
        description: `${bundleGroupType.replace(/_/g, ' ')} bundle for ${bundleAnchorFqn || 'selected assets'}`,
        groupType: bundleGroupType,
        anchorFqn: bundleAnchorFqn || undefined,
        anchorNodeId: bundleAnchorNodeId || undefined,
        schedule,
        timezone,
        alertChannels,
        alertOnStatus,
        integrationId: integrationId || undefined,
        monitors: bundleMonitors,
      };
      // Use onSubmit with a special _bundle flag so the parent knows to POST to /bundles
      onSubmit({ ...bundleData, _bundle: true });
      return;
    }

    // For tool monitors, store the integration node ID in config.toolNodeId
    const finalConfig = { ...(config || {}) };
    if (isToolMonitor && integrationId) {
      finalConfig.toolNodeId = integrationId;
    }

    const taskData = {
      name,
      taskMode,
      prompt: taskMode === 'prompt' ? prompt : undefined,
      monitorType: taskMode === 'structured' ? monitorType : undefined,
      targetFqn: taskMode === 'structured' ? (targetFqn || (isInfraMonitor ? 'server' : (isToolMonitor ? (config.connector_id || config.dag_id || config.job_id || monitorType) : undefined))) : undefined,
      config: taskMode === 'structured' ? finalConfig : undefined,
      schedule,
      timezone,
      alertChannels,
      alertOnStatus,
      integrationId: (isToolMonitor ? undefined : integrationId) || undefined,
    };
    if (isEditing && onUpdate) {
      onUpdate(editTask!.id, taskData);
    } else {
      onSubmit(taskData);
    }
  };

  // Determine which integration selector to show
  const renderIntegrationSelector = () => {
    if (taskMode === 'prompt') {
      // Prompt mode: show warehouse selector
      if (warehouseIntegrations.length === 0) return null;
      return (
        <div>
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Run against warehouse
          </label>
          <select
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
          >
            <option value="">Auto-detect</option>
            {warehouseIntegrations.map((i) => (
              <option key={i.id} value={i.id}>{i.name} ({i.type})</option>
            ))}
          </select>
        </div>
      );
    }

    if (!monitorType) return null;

    // Tool monitors: show matching tool integration
    if (isToolMonitor && toolIntegrations.length > 0) {
      return (
        <div className="space-y-2">
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Run against integration
          </label>
          <select
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
          >
            <option value="">Auto-detect</option>
            {toolIntegrations.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name} ({n.toolType}){!n.hasLiveConnection ? ' — static mode' : ''}
              </option>
            ))}
          </select>
          {toolNeedsLiveConnection && (
            <div className="flex items-start gap-2 px-3 py-2.5 bg-amber-500/[0.08] border border-amber-500/[0.2] rounded-lg">
              <svg className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <div className="text-[12px] text-amber-300/90">
                <p className="font-medium mb-0.5">Live API connection required</p>
                <p className="text-amber-300/70">
                  {selectedToolNode?.toolType.toLowerCase() === 'airflow' ? (
                    <>Your Airflow integration &quot;{selectedToolNode.name}&quot; is connected in <strong>{toolConnectionModeLabel}</strong> mode (read-only static files). Monitors need a live Airflow API connection to check DAG run status. Switch the integration to <strong>Airflow API</strong> mode with a host URL to enable monitors.</>
                  ) : selectedToolNode?.toolType.toLowerCase() === 'dbt_core' ? (
                    <>Your dbt integration &quot;{selectedToolNode.name}&quot; is connected in <strong>{toolConnectionModeLabel}</strong> mode. Monitors need a live dbt Cloud API to check job runs and test results. Switch to a <strong>dbt Cloud</strong> integration with an API key to enable monitors.</>
                  ) : (
                    <>This integration is not connected to a live instance. Monitors require a live API connection to work. Update the integration settings to use API mode.</>
                  )}
                </p>
              </div>
            </div>
          )}
        </div>
      );
    }

    // Infra monitors: show server selector
    if (isInfraMonitor && serverIntegrations.length > 0) {
      return (
        <div>
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Run against server
          </label>
          <select
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
          >
            <option value="">Auto-detect</option>
            {serverIntegrations.map((i) => (
              <option key={i.id} value={i.id}>{i.name} ({i.type})</option>
            ))}
          </select>
        </div>
      );
    }

    // Warehouse monitors: show warehouse selector
    if (needsFqnTarget && warehouseIntegrations.length > 0) {
      return (
        <div>
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Run against warehouse
          </label>
          <select
            value={integrationId}
            onChange={(e) => setIntegrationId(e.target.value)}
            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
          >
            <option value="">Auto-detect</option>
            {warehouseIntegrations.map((i) => (
              <option key={i.id} value={i.id}>{i.name} ({i.type})</option>
            ))}
          </select>
        </div>
      );
    }

    return null;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-3xl mx-4 bg-[var(--surface)] rounded-2xl border border-[var(--subtle-border)] shadow-2xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex-shrink-0 flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <h2 className="text-[16px] font-semibold text-[var(--text)]">{isEditing ? 'Edit Task' : 'Create Scheduled Task'}</h2>
          <button onClick={onClose} className="text-[var(--muted)] hover:text-[var(--text)]">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Step indicators */}
        <div className="flex-shrink-0 flex items-center gap-3 px-6 py-3 border-b border-[var(--border-faint)]">
          {[1, 2, 3].map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div className={cn(
                'w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-medium',
                step === s
                  ? 'bg-[var(--overlay-strong)] text-[var(--text)]'
                  : step > s
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-[var(--overlay-bg)] text-[var(--text-faint)]'
              )}>
                {step > s ? '\u2713' : s}
              </div>
              <span className={cn(
                'text-[12px]',
                step === s ? 'text-[var(--text)]' : 'text-[var(--text-faint)]'
              )}>
                {s === 1 ? 'Task' : s === 2 ? 'Schedule' : 'Alerts'}
              </span>
              {s < 3 && <div className="w-8 h-px bg-[var(--hover-bg)]" />}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-6 py-6 space-y-5">
          {step === 1 && (
            <>
              {/* Task name */}
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Task Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Daily freshness check on orders"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  autoFocus
                />
              </div>

              {/* Mode toggle */}
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Task Type
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setTaskMode('prompt')}
                    className={cn(
                      'flex-1 flex items-center gap-2 p-3 rounded-lg transition-colors text-left',
                      taskMode === 'prompt'
                        ? 'bg-[var(--overlay-medium)] border border-[var(--overlay-strong)]'
                        : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                    )}
                  >
                    <svg className="w-5 h-5 text-[var(--text-tertiary)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                    <div>
                      <span className="text-[13px] font-medium text-[var(--text)] block">AI Prompt</span>
                      <span className="text-[11px] text-[var(--muted)]">Natural language</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTaskMode('structured')}
                    className={cn(
                      'flex-1 flex items-center gap-2 p-3 rounded-lg transition-colors text-left',
                      taskMode === 'structured'
                        ? 'bg-[var(--overlay-medium)] border border-[var(--overlay-strong)]'
                        : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                    )}
                  >
                    <svg className="w-5 h-5 text-[var(--text-tertiary)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <div>
                      <span className="text-[13px] font-medium text-[var(--text)] block">Monitor</span>
                      <span className="text-[11px] text-[var(--muted)]">Specific check</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTaskMode('bundle')}
                    className={cn(
                      'flex-1 flex items-center gap-2 p-3 rounded-lg transition-colors text-left',
                      taskMode === 'bundle'
                        ? 'bg-[var(--overlay-medium)] border border-[var(--overlay-strong)]'
                        : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                    )}
                  >
                    <svg className="w-5 h-5 text-[var(--text-tertiary)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                    </svg>
                    <div>
                      <span className="text-[13px] font-medium text-[var(--text)] block">Bundle</span>
                      <span className="text-[11px] text-[var(--muted)]">Group of assets</span>
                    </div>
                  </button>
                </div>
              </div>

              {/* Mode-specific content */}
              {taskMode === 'prompt' ? (
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Prompt
                  </label>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="e.g., Check if the orders table has received fresh data in the last 24 hours. If stale, report which datasets haven't been updated."
                    rows={4}
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2.5 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] resize-none"
                  />
                </div>
              ) : taskMode === 'bundle' ? (
                <div className="space-y-4">
                  {/* Bundle group type */}
                  <div>
                    <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                      Bundle Type
                    </label>
                    <div className="flex gap-2">
                      {[
                        { value: 'upstream_stability', label: 'Upstream Stability', desc: 'Watch upstream dependencies' },
                        { value: 'reporting_health', label: 'Reporting Health', desc: 'End-to-end BI pipeline' },
                        { value: 'asset_stability', label: 'Asset Stability', desc: 'Core quality for an asset' },
                        { value: 'custom', label: 'Custom', desc: 'Pick targets manually' },
                      ].map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setBundleGroupType(opt.value)}
                          className={cn(
                            'flex-1 p-2 rounded-lg text-left transition-colors',
                            bundleGroupType === opt.value
                              ? 'bg-amber-500/10 border border-amber-500/30'
                              : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                          )}
                        >
                          <span className="text-[12px] font-medium text-[var(--text)] block">{opt.label}</span>
                          <span className="text-[10px] text-[var(--muted)]">{opt.desc}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Anchor node picker */}
                  <div>
                    <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                      Anchor Node
                    </label>
                    {bundleAnchorFqn ? (
                      <div className="flex items-center gap-2 p-2.5 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg">
                        <span className="text-[12px] text-[var(--text)] font-mono flex-1 truncate">{bundleAnchorFqn}</span>
                        <button
                          type="button"
                          onClick={() => {
                            setBundleAnchorFqn('');
                            setBundleAnchorNodeId('');
                            setBundleMonitors([]);
                          }}
                          className="text-[var(--muted)] hover:text-[var(--text)] text-[11px]"
                        >
                          Change
                        </button>
                      </div>
                    ) : (
                      <div className="relative">
                        <input
                          type="text"
                          value={bundleSearchQuery}
                          onChange={(e) => {
                            setBundleSearchQuery(e.target.value);
                            searchLineageNodes(e.target.value);
                          }}
                          placeholder="Search for a table, model, or dashboard..."
                          className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                        />
                        {bundleSearchResults.length > 0 && (
                          <div className="absolute z-10 mt-1 w-full bg-[var(--surface)] border border-[var(--subtle-border)] rounded-lg shadow-xl max-h-48 overflow-y-auto">
                            {bundleSearchResults.map((r) => (
                              <button
                                key={r.id}
                                type="button"
                                onClick={() => {
                                  setBundleAnchorFqn(r.fqn);
                                  setBundleAnchorNodeId(r.id);
                                  setBundleSearchQuery('');
                                  setBundleSearchResults([]);
                                  fetchUpstreamNodes(r.id, r.fqn);
                                }}
                                className="w-full text-left px-3 py-2 hover:bg-[var(--hover-bg)] transition-colors"
                              >
                                <span className="text-[12px] text-[var(--text)] font-mono block truncate">{r.fqn}</span>
                                <span className="text-[10px] text-[var(--muted)]">{r.name}</span>
                              </button>
                            ))}
                          </div>
                        )}
                        {bundleSearching && (
                          <div className="absolute right-3 top-2.5">
                            <div className="w-3.5 h-3.5 border-2 border-[var(--overlay-strong)] border-t-white/60 rounded-full animate-spin" />
                          </div>
                        )}
                      </div>
                    )}
                    <p className="text-[10px] text-[var(--text-faint)] mt-1">
                      Select the asset whose upstream dependencies you want to monitor as a group.
                    </p>
                  </div>

                  {/* Upstream nodes with scanner selector */}
                  {bundleMonitors.length > 0 && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-[12px] font-medium text-[var(--muted)]">
                          Upstream Nodes ({bundleMonitors.length})
                        </label>
                        <button
                          type="button"
                          onClick={() => setBundleMonitors([])}
                          className="text-[10px] text-red-400 hover:text-red-300"
                        >
                          Clear all
                        </button>
                      </div>
                      <div className="space-y-1.5 max-h-56 overflow-y-auto">
                        {bundleMonitors.map((mon, i) => (
                          <div
                            key={`${mon.targetFqn}-${i}`}
                            className="flex items-center gap-2 px-2.5 py-2 bg-[var(--overlay-bg)] border border-[var(--border-faint)] rounded-lg"
                          >
                            <span className="text-[11px] text-[var(--text)] font-mono truncate flex-1 min-w-0" title={mon.targetFqn}>
                              {mon.targetFqn.split('.').pop() || mon.targetFqn}
                            </span>
                            <select
                              value={mon.monitorType}
                              onChange={(e) => {
                                const newType = e.target.value;
                                const shortName = mon.targetFqn.split('.').pop() || mon.targetFqn;
                                setBundleMonitors((prev) =>
                                  prev.map((m, j) =>
                                    j === i
                                      ? { ...m, monitorType: newType, name: `${newType.toLowerCase().replace(/_/g, ' ')} — ${shortName}` }
                                      : m
                                  )
                                );
                              }}
                              className="bg-[var(--surface)] border border-[var(--subtle-border)] rounded px-1.5 py-1 text-[10px] text-[var(--text)] focus:outline-none shrink-0 appearance-none"
                            >
                              {BUNDLE_SCANNER_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={() => setBundleMonitors((prev) => prev.filter((_, j) => j !== i))}
                              className="text-[var(--muted)] hover:text-red-400 shrink-0"
                            >
                              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Empty / loading state */}
                  {bundleMonitors.length === 0 && bundleAnchorFqn && (
                    <div className="py-4 text-center text-[12px] text-[var(--muted)]">
                      Fetching upstream nodes...
                    </div>
                  )}

                  {/* Integration selector for bundle */}
                  {bundleMonitors.length > 0 && warehouseIntegrations.length > 0 && (
                    <div>
                      <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                        Run against warehouse
                      </label>
                      <select
                        value={integrationId}
                        onChange={(e) => setIntegrationId(e.target.value)}
                        className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
                      >
                        <option value="">Auto-detect</option>
                        {warehouseIntegrations.map((i) => (
                          <option key={i.id} value={i.id}>{i.name} ({i.type})</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              ) : (
                <MonitorConfigForm
                  monitorType={monitorType}
                  onMonitorTypeChange={setMonitorType}
                  targetFqn={targetFqn}
                  onTargetFqnChange={setTargetFqn}
                  config={config}
                  onConfigChange={setConfig}
                  integrationId={integrationId}
                  groupedMonitors={groupedMonitors}
                />
              )}

              {/* Integration selection — dynamic based on monitor type (non-bundle) */}
              {taskMode !== 'bundle' && renderIntegrationSelector()}
            </>
          )}

          {step === 2 && (
            <>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Schedule
                </label>
                <ScheduleInput value={schedule} onChange={setSchedule} />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Timezone
                </label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
                >
                  <option value="UTC">UTC</option>
                  <option value="America/New_York">Eastern (ET)</option>
                  <option value="America/Chicago">Central (CT)</option>
                  <option value="America/Denver">Mountain (MT)</option>
                  <option value="America/Los_Angeles">Pacific (PT)</option>
                  <option value="Europe/London">London (GMT/BST)</option>
                  <option value="Europe/Berlin">Berlin (CET)</option>
                  <option value="Asia/Tokyo">Tokyo (JST)</option>
                </select>
              </div>
            </>
          )}

          {step === 3 && (
            <AlertChannelPicker
              channels={alertChannels}
              onChannelsChange={setAlertChannels}
              alertOnStatus={alertOnStatus}
              onAlertOnStatusChange={setAlertOnStatus}
              connectedChannels={connectedChannels}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 flex items-center justify-between px-6 py-4 border-t border-[var(--subtle-border)]">
          <div>
            {step > 1 && (
              <Button variant="ghost" size="sm" onClick={() => setStep(step - 1)}>
                Back
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            {step < 3 ? (
              <Button
                size="sm"
                onClick={() => setStep(step + 1)}
                disabled={step === 1 ? !canProceedStep1 : !canProceedStep2}
              >
                Next
              </Button>
            ) : (
              <Button size="sm" onClick={handleSubmit}>
                {isEditing ? 'Save Changes' : taskMode === 'bundle' ? `Create Bundle (${bundleMonitors.length})` : 'Create Task'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
