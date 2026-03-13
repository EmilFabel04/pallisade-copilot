'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
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
import {
  type WatchType,
  WATCH_TYPE_LABELS,
  WATCH_TYPE_DESCRIPTIONS,
  DEFAULT_SCOPE_CONFIGS,
} from '@/types/health-watch';

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

export interface WatchPrefillData {
  anchorFqn: string;
  anchorNodeId?: string;
  anchorNodeType?: string;
  anchorPlatform?: string;
  watchType?: WatchType;
  monitors?: Array<{
    name: string;
    monitorType: string;
    targetFqn: string;
    config?: Record<string, any>;
  }>;
}

interface ScopeMonitor {
  name: string;
  monitorType: string;
  targetFqn: string;
  priority: number;
  reason: string;
  config?: Record<string, any>;
  checked: boolean;
}

const WATCH_TYPES: WatchType[] = [
  'pipeline_health',
  'dashboard_shield',
  'source_guard',
  'model_quality',
  'custom_watch',
];

const WATCH_TYPE_ICONS: Record<WatchType, string> = {
  pipeline_health: 'M13 5l7 7-7 7M5 5l7 7-7 7',
  dashboard_shield: 'M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm0 8a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zm10 0a1 1 0 011-1h4a1 1 0 011 1v6a1 1 0 01-1 1h-4a1 1 0 01-1-1v-6z',
  source_guard: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
  model_quality: 'M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z',
  custom_watch: 'M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4',
};

const PRIORITY_COLORS: Record<number, string> = {
  1: 'bg-red-500/15 text-red-400',
  2: 'bg-amber-500/15 text-amber-400',
  3: 'bg-white/10 text-[var(--muted)]',
};

interface CreateTaskModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (task: any) => void;
  onUpdate?: (taskId: string, task: any) => void;
  editTask?: ScheduledTask | null;
  prefillData?: MonitorPrefillData | null;
  watchPrefillData?: WatchPrefillData | null;
  integrations?: Array<{ id: string; name: string; type: string }>;
  stackId?: string;
  initialMode?: 'prompt' | 'structured' | 'watch';
}

export function CreateTaskModal({ open, onClose, onSubmit, onUpdate, editTask, prefillData, watchPrefillData, integrations = [], stackId, initialMode }: CreateTaskModalProps) {
  const [step, setStep] = useState(1);
  const isEditing = !!editTask;

  // Step 1: Mode + content
  const [taskMode, setTaskMode] = useState<'prompt' | 'structured' | 'watch'>('prompt');
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [monitorType, setMonitorType] = useState('');
  const [targetFqn, setTargetFqn] = useState('');
  const [config, setConfig] = useState<Record<string, any>>({});



  // Watch mode state
  const [watchType, setWatchType] = useState<WatchType>('pipeline_health');
  const [watchStep, setWatchStep] = useState(1);
  const [selectedWatchAsset, setSelectedWatchAsset] = useState<{ id: string; name: string; fqn: string; type?: string; platform?: string; platformDomain?: string } | null>(null);
  const [watchSearchQuery, setWatchSearchQuery] = useState('');
  const [watchSearchResults, setWatchSearchResults] = useState<Array<{ id: string; name: string; fqn: string }>>([]);
  const [watchSearching, setWatchSearching] = useState(false);
  const [scopeMonitors, setScopeMonitors] = useState<ScopeMonitor[]>([]);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [coveragePct, setCoveragePct] = useState<number>(0);
  const [scopeNodeCount, setScopeNodeCount] = useState<number>(0);
  const [watchName, setWatchName] = useState('');
  const scopeFetchedRef = useRef(false);
  const watchRecommendDataRef = useRef<any>(null);
  const watchSearchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Helper to reset watch state
  const resetWatchState = () => {
    setWatchType('pipeline_health');
    setWatchStep(1);
    setSelectedWatchAsset(null);
    setWatchSearchQuery('');
    setWatchSearchResults([]);
    setScopeMonitors([]);
    setCoveragePct(0);
    setScopeNodeCount(0);
    setWatchName('');
    scopeFetchedRef.current = false;
    watchRecommendDataRef.current = null;
  };

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
      resetWatchState();
    } else if (watchPrefillData && open) {
      setTaskMode('watch');
      setSelectedWatchAsset({
        id: watchPrefillData.anchorNodeId || '',
        name: watchPrefillData.anchorFqn?.split('.').pop() || '',
        fqn: watchPrefillData.anchorFqn,
        type: watchPrefillData.anchorNodeType,
        platform: watchPrefillData.anchorPlatform,
      });
      setWatchType(watchPrefillData.watchType || 'pipeline_health');
      setWatchName(`${WATCH_TYPE_LABELS[watchPrefillData.watchType || 'pipeline_health']}: ${watchPrefillData.anchorFqn?.split('.').pop() || 'Watch'}`);
      if (watchPrefillData.monitors?.length) {
        setScopeMonitors(watchPrefillData.monitors.map((m) => ({
          ...m,
          priority: 2,
          reason: 'Prefilled',
          checked: true,
        })));
        scopeFetchedRef.current = true;
        setWatchStep(2);
      } else {
        scopeFetchedRef.current = false;
        setWatchStep(1);
      }
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setName('');
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
      resetWatchState();
    } else if (open) {
      setName('');
      setTaskMode(initialMode || 'prompt');
      setPrompt('');
      setMonitorType('');
      setTargetFqn('');
      setConfig({});
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setIntegrationId('');
      setStep(1);
      resetWatchState();
    }
  }, [editTask, prefillData, watchPrefillData, open, initialMode]);

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

  // Watch: select asset and auto-detect watch type
  const handleSelectWatchAsset = useCallback(async (asset: { id: string; name: string; fqn: string }) => {
    setSelectedWatchAsset(asset);
    setWatchSearchQuery('');
    setWatchSearchResults([]);

    watchRecommendDataRef.current = null;
    scopeFetchedRef.current = false;

    if (stackId && asset.id) {
      try {
        const res = await fetch(
          `/api/pipeline/${stackId}/lineage/engine?action=recommend-monitors&id=${asset.id}&depth=3`
        );
        if (res.ok) {
          const data = await res.json();
          watchRecommendDataRef.current = data;
          const domain = data.platform_domain || '';
          const nodeType = data.asset_type || '';
          let inferred: WatchType = 'pipeline_health';
          if (['dashboard', 'report', 'workbook', 'question', 'explore'].includes(nodeType) || domain === 'bi') {
            inferred = 'dashboard_shield';
          } else if (domain === 'ingestion') {
            inferred = 'source_guard';
          } else if (domain === 'transform' && nodeType === 'model') {
            inferred = 'model_quality';
          }
          setWatchType(inferred);
          setWatchName(`${WATCH_TYPE_LABELS[inferred]}: ${asset.name}`);
        }
      } catch {
        setWatchName(`${WATCH_TYPE_LABELS[watchType]}: ${asset.name}`);
      }
    } else {
      setWatchName(`${WATCH_TYPE_LABELS[watchType]}: ${asset.name}`);
    }
  }, [stackId, watchType]);

  // Watch: populate scope monitors when entering watch step 2
  // Uses cached data from step 1 handleSelectWatchAsset, falls back to fresh fetch
  useEffect(() => {
    if (taskMode !== 'watch' || watchStep !== 2 || !selectedWatchAsset || !stackId) return;
    if (scopeFetchedRef.current) return;
    scopeFetchedRef.current = true;

    // Default monitors per watch type when the API returns nothing
    const DEFAULT_MONITORS: Record<WatchType, Array<{ monitorType: string; label: string; priority: number; reason: string }>> = {
      pipeline_health: [
        { monitorType: 'FRESHNESS', label: 'freshness', priority: 1, reason: 'Core data quality — detect stale data' },
        { monitorType: 'VOLUME', label: 'volume', priority: 2, reason: 'Core data quality — detect unexpected row count changes' },
        { monitorType: 'SCHEMA_CHANGE', label: 'schema change', priority: 2, reason: 'Core data quality — detect column changes' },
      ],
      dashboard_shield: [
        { monitorType: 'BI_FRESHNESS_PROXY', label: 'dashboard freshness', priority: 1, reason: 'Track dashboard freshness via upstream lineage' },
        { monitorType: 'BI_CONTENT_HEALTH', label: 'content health', priority: 2, reason: 'Verify BI asset exists and deliveries are not failing' },
        { monitorType: 'BI_UPSTREAM_BREAK_RISK', label: 'upstream break risk', priority: 2, reason: 'Count failing monitors on upstream warehouse tables' },
      ],
      source_guard: [
        { monitorType: 'SYNC_LAG', label: 'sync lag', priority: 1, reason: 'Track ingestion connector sync lag' },
        { monitorType: 'FAILED_SYNCS', label: 'failed syncs', priority: 1, reason: 'Detect failed syncs on this connector' },
        { monitorType: 'CONNECTOR_SCHEMA_DRIFT', label: 'schema drift', priority: 2, reason: 'Detect schema changes at the ingestion source' },
      ],
      model_quality: [
        { monitorType: 'DBT_TEST_FAILURES', label: 'test failures', priority: 1, reason: 'Watch for dbt test regressions' },
        { monitorType: 'DBT_MODEL_FRESHNESS', label: 'model freshness', priority: 2, reason: 'Detect when model builds become stale' },
        { monitorType: 'FRESHNESS', label: 'freshness', priority: 2, reason: 'Core data quality — detect stale data' },
      ],
      custom_watch: [
        { monitorType: 'FRESHNESS', label: 'freshness', priority: 1, reason: 'Custom monitor — data freshness' },
        { monitorType: 'VOLUME', label: 'volume', priority: 2, reason: 'Custom monitor — row volume' },
        { monitorType: 'SCHEMA_CHANGE', label: 'schema change', priority: 2, reason: 'Custom monitor — schema changes' },
      ],
    };

    // Monitors to add per upstream node type (data assets only — no connectors/dags/tools)
    const UPSTREAM_NODE_MONITORS: Record<string, Array<{ monitorType: string; label: string; priority: number }>> = {
      table:   [{ monitorType: 'FRESHNESS', label: 'freshness', priority: 2 }, { monitorType: 'SCHEMA_CHANGE', label: 'schema change', priority: 3 }],
      view:    [{ monitorType: 'FRESHNESS', label: 'freshness', priority: 2 }],
      materialized_view: [{ monitorType: 'FRESHNESS', label: 'freshness', priority: 2 }],
      source:  [{ monitorType: 'FRESHNESS', label: 'freshness', priority: 2 }],
      model:   [{ monitorType: 'DBT_TEST_FAILURES', label: 'test failures', priority: 2 }, { monitorType: 'FRESHNESS', label: 'freshness', priority: 3 }],
      dataset: [{ monitorType: 'FRESHNESS', label: 'freshness', priority: 2 }],
      seed:    [{ monitorType: 'FRESHNESS', label: 'freshness', priority: 2 }],
      snapshot: [{ monitorType: 'FRESHNESS', label: 'freshness', priority: 2 }],
    };

    const generateDefaults = (): ScopeMonitor[] => {
      const shortName = selectedWatchAsset.fqn.split('.').pop() || selectedWatchAsset.name;
      return (DEFAULT_MONITORS[watchType] || DEFAULT_MONITORS.pipeline_health).map((m) => ({
        name: `${m.label} — ${shortName}`,
        monitorType: m.monitorType,
        targetFqn: selectedWatchAsset.fqn,
        priority: m.priority,
        reason: m.reason,
        config: {},
        checked: true,
      }));
    };

    // Build monitors from DB lineage upstream nodes (fallback when engine graph unavailable)
    const generateFromDbLineage = async (): Promise<ScopeMonitor[]> => {
      const anchorMonitors = generateDefaults();
      try {
        const maxDepth = DEFAULT_SCOPE_CONFIGS[watchType].maxDepth;
        const res = await fetch(`/api/lineage/upstream?fqn=${encodeURIComponent(selectedWatchAsset.fqn)}&limit=${maxDepth * 10}`);
        if (!res.ok) return anchorMonitors;
        const data = await res.json();
        const allNodes: Array<{ id: string; name: string; fqn: string; nodeType: string | null }> = data.nodes || [];
        // Only keep physical data assets — exclude connectors, dags, tools, and null types
        const DATA_ASSET_TYPES = new Set(['table', 'view', 'materialized_view', 'source', 'model', 'dataset', 'seed', 'snapshot']);
        const upstreamNodes = allNodes.filter((n) => {
          if (!n.nodeType) return false;
          return DATA_ASSET_TYPES.has(n.nodeType.toLowerCase());
        });
        if (upstreamNodes.length === 0) return anchorMonitors;

        const upstreamMonitors: ScopeMonitor[] = [];
        const seen = new Set<string>(anchorMonitors.map((m) => `${m.monitorType}:${m.targetFqn}`));

        for (const node of upstreamNodes) {
          const nt = node.nodeType!.toLowerCase();
          const specs = UPSTREAM_NODE_MONITORS[nt] || UPSTREAM_NODE_MONITORS['table'];
          const shortName = node.fqn.split('.').pop() || node.name;
          for (const spec of specs) {
            const key = `${spec.monitorType}:${node.fqn}`;
            if (seen.has(key)) continue;
            seen.add(key);
            upstreamMonitors.push({
              name: `${spec.label} — ${shortName}`,
              monitorType: spec.monitorType,
              targetFqn: node.fqn,
              priority: spec.priority,
              reason: `Upstream dependency of ${selectedWatchAsset.name || selectedWatchAsset.fqn.split('.').pop()}`,
              config: {},
              checked: true,
            });
          }
        }

        setCoveragePct(upstreamNodes.length > 0
          ? Math.min((anchorMonitors.length + upstreamMonitors.length) / (upstreamNodes.length + 1), 1.0)
          : 1.0);
        return [...anchorMonitors, ...upstreamMonitors];
      } catch (err) {
        console.error('[Group Monitor] DB lineage fallback error:', err);
        return anchorMonitors;
      }
    };

    const applyMonitors = (monitors: ScopeMonitor[]) => {
      const maxMonitors = DEFAULT_SCOPE_CONFIGS[watchType].maxMonitors;
      monitors.sort((a, b) => a.priority - b.priority);
      setScopeMonitors(monitors.slice(0, maxMonitors));
      setScopeNodeCount(new Set(monitors.map((m) => m.targetFqn)).size);
    };

    const parseRecommendData = (data: any): ScopeMonitor[] => {
      const recs = data.recommendations || [];
      const dataBundles = data.bundles || [];
      const monitors: ScopeMonitor[] = [];
      const seen = new Set<string>();

      for (const rec of recs) {
        const key = `${rec.monitor_key}:${rec.target_fqn || selectedWatchAsset.fqn}`;
        if (seen.has(key)) continue;
        seen.add(key);
        monitors.push({
          name: rec.name || `${(rec.monitor_key || '').toLowerCase().replace(/_/g, ' ')} — ${(rec.target_fqn || selectedWatchAsset.fqn).split('.').pop()}`,
          monitorType: rec.monitor_key,
          targetFqn: rec.target_fqn || selectedWatchAsset.fqn,
          priority: rec.priority || 2,
          reason: rec.reason || 'Recommended',
          config: rec.config_hints,
          checked: true,
        });
      }

      for (const bundle of dataBundles) {
        for (const mon of bundle.recommendations || []) {
          const key = `${mon.monitor_key}:${mon.target_fqn}`;
          if (seen.has(key)) continue;
          seen.add(key);
          monitors.push({
            name: mon.name || `${(mon.monitor_key || '').toLowerCase().replace(/_/g, ' ')} — ${(mon.target_fqn || '').split('.').pop()}`,
            monitorType: mon.monitor_key,
            targetFqn: mon.target_fqn,
            priority: mon.priority || 3,
            reason: mon.reason || `From ${bundle.label || 'bundle'}`,
            config: mon.config_hints,
            checked: true,
          });
        }
      }

      const upstreamCount = data.upstream_count || monitors.length;
      setCoveragePct(upstreamCount > 0 ? Math.min(monitors.length / upstreamCount, 1.0) : 1.0);

      return monitors;
    };

    // If we already have cached data from step 1, use it immediately
    if (watchRecommendDataRef.current) {
      const monitors = parseRecommendData(watchRecommendDataRef.current);
      if (monitors.length > 0) {
        applyMonitors(monitors);
      } else {
        // Engine returned nothing — fall back to DB lineage
        setScopeLoading(true);
        generateFromDbLineage().then((m) => applyMonitors(m)).finally(() => setScopeLoading(false));
      }
      return;
    }

    // Fetch from engine, falling back to DB lineage when engine is unavailable
    const fetchScope = async () => {
      setScopeLoading(true);
      try {
        const res = await fetch(
          `/api/pipeline/${stackId}/lineage/engine?action=recommend-monitors&id=${selectedWatchAsset.id}&depth=${DEFAULT_SCOPE_CONFIGS[watchType].maxDepth}`
        );
        if (res.ok) {
          const data = await res.json();
          const monitors = parseRecommendData(data);
          if (monitors.length > 0) {
            applyMonitors(monitors);
          } else {
            // Engine had no recommendations — try DB lineage
            const dbMonitors = await generateFromDbLineage();
            applyMonitors(dbMonitors);
          }
        } else {
          // Engine unavailable (404 = graph not built) — use DB lineage
          const dbMonitors = await generateFromDbLineage();
          applyMonitors(dbMonitors);
        }
      } catch (err) {
        console.error('[CreateTask] Watch scope fetch error:', err);
        const dbMonitors = await generateFromDbLineage();
        applyMonitors(dbMonitors);
      } finally {
        setScopeLoading(false);
      }
    };

    fetchScope();
  }, [taskMode, watchStep, selectedWatchAsset, stackId, watchType]);

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

  const canProceedStep1 = taskMode === 'watch'
    ? true // Watch mode uses its own step navigation
    : name.trim() && (
      taskMode === 'prompt'
        ? prompt.trim()
        : (monitorType && (
            isInfraMonitor || isToolMonitor
              ? hasRequiredToolFields && !needsLogPaths
              : (targetFqn.trim() && !needsColumn && !needsSql)
          ))
    );
  const canProceedStep2 = schedule.trim();

  // Watch: search for assets (reuses searchLineageNodes pattern with engine + Prisma fallback)
  const searchWatchNodes = (query: string) => {
    if (watchSearchTimerRef.current) clearTimeout(watchSearchTimerRef.current);
    if (!query.trim()) {
      setWatchSearchResults([]);
      setWatchSearching(false);
      return;
    }
    setWatchSearching(true);
    watchSearchTimerRef.current = setTimeout(async () => {
      try {
        let results: Array<{ id: string; name: string; fqn: string }> = [];
        const VISIBLE_SEARCH_TYPES = new Set([
          'table', 'view', 'materialized_view', 'source', 'model',
          'dashboard', 'report', 'workbook', 'question', 'explore', 'dataset',
        ]);

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
              .map((r: any) => ({ id: r.id, name: r.name, fqn: r.fqn || r.name }));
          }
        }

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
              .map((r: any) => ({ id: r.id, name: r.name, fqn: r.fqn || r.name }));
          }
        }

        setWatchSearchResults(results);
      } catch {}
      setWatchSearching(false);
    }, 300);
  };

  // Watch: toggle a scope monitor
  const toggleScopeMonitor = (index: number) => {
    setScopeMonitors((prev) =>
      prev.map((m, i) => (i === index ? { ...m, checked: !m.checked } : m))
    );
  };

  const handleSubmit = () => {
    if (taskMode === 'watch') {
      const checkedMonitors = scopeMonitors.filter((m) => m.checked);
      onSubmit({
        _watch: true,
        name: watchName || `${WATCH_TYPE_LABELS[watchType]}: ${selectedWatchAsset?.name || 'Watch'}`,
        watchType,
        anchorFqn: selectedWatchAsset?.fqn || '',
        anchorNodeId: selectedWatchAsset?.id || '',
        anchorNodeType: selectedWatchAsset?.type || '',
        anchorPlatform: selectedWatchAsset?.platform || '',
        scopeConfig: DEFAULT_SCOPE_CONFIGS[watchType],
        schedule,
        timezone,
        alertChannels,
        alertOnStatus,
        monitors: checkedMonitors.map((m) => ({
          name: m.name,
          monitorType: m.monitorType,
          targetFqn: m.targetFqn,
          config: m.config,
        })),
      });
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
          {taskMode === 'watch' ? (
            // Watch mode: 4-step progress
            <>
              {[
                { n: 1, label: 'Asset' },
                { n: 2, label: 'Scope' },
                { n: 3, label: 'Schedule' },
                { n: 4, label: 'Confirm' },
              ].map(({ n, label }) => (
                <div key={n} className="flex items-center gap-2">
                  <div className={cn(
                    'w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-medium',
                    watchStep === n
                      ? 'bg-[var(--overlay-strong)] text-[var(--text)]'
                      : watchStep > n
                      ? 'bg-emerald-500/20 text-emerald-400'
                      : 'bg-[var(--overlay-bg)] text-[var(--text-faint)]'
                  )}>
                    {watchStep > n ? '\u2713' : n}
                  </div>
                  <span className={cn(
                    'text-[12px]',
                    watchStep === n ? 'text-[var(--text)]' : 'text-[var(--text-faint)]'
                  )}>{label}</span>
                  {n < 4 && <div className="w-8 h-px bg-[var(--hover-bg)]" />}
                </div>
              ))}
            </>
          ) : (
            // Normal modes: 3-step progress
            <>
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
            </>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-6 py-6 space-y-5">
          {step === 1 && (
            <>
              {/* Task name (hidden in watch mode — watch uses its own name in step 4) */}
              {taskMode !== 'watch' && (
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
              )}

              {/* Mode toggle */}
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Task Type
                </label>
                <div className="flex gap-3">
                  {([
                    { mode: 'prompt' as const, label: 'AI Prompt', sub: 'Natural language', icon: 'M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z' },
                    { mode: 'structured' as const, label: 'Monitor', sub: 'Specific check', icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' },
                    { mode: 'watch' as const, label: 'Group Monitor', sub: 'Protect an asset', icon: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z' },
                  ]).map(({ mode, label, sub, icon }) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => { setTaskMode(mode); if (mode === 'watch') setWatchStep(1); }}
                      className={cn(
                        'flex-1 flex flex-col items-center justify-center gap-1 py-2.5 rounded-lg transition-colors',
                        taskMode === mode
                          ? 'bg-[var(--overlay-medium)] border-2 border-[var(--overlay-strong)]'
                          : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                      )}
                    >
                      <svg className="w-5 h-5 text-[var(--text-tertiary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={icon} />
                      </svg>
                      <span className="text-[13px] font-medium text-[var(--text)] leading-tight">{label}</span>
                      <span className="text-[11px] text-[var(--muted)] leading-tight">{sub}</span>
                    </button>
                  ))}
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
              ) : taskMode === 'watch' ? (
                <div className="space-y-4">
                  {/* Watch has its own multi-step flow inside step 1 */}
                  {watchStep === 1 && (
                    <>
                      {/* Asset search */}
                      <div>
                        <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                          Search for an asset to protect
                        </label>
                        {selectedWatchAsset ? (
                          <div className="p-3 rounded-lg border border-blue-500/20 bg-blue-500/5">
                            <div className="flex items-center justify-between">
                              <div>
                                <p className="text-[13px] font-medium text-[var(--text)]">{selectedWatchAsset.name}</p>
                                <p className="text-[11px] text-[var(--muted)] font-mono">{selectedWatchAsset.fqn}</p>
                              </div>
                              <button
                                type="button"
                                onClick={() => { setSelectedWatchAsset(null); setWatchName(''); }}
                                className="text-[var(--muted)] hover:text-[var(--text)]"
                              >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="relative">
                            <input
                              type="text"
                              value={watchSearchQuery}
                              onChange={(e) => {
                                setWatchSearchQuery(e.target.value);
                                searchWatchNodes(e.target.value);
                              }}
                              placeholder="Search tables, dashboards, models, connectors..."
                              className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2.5 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-blue-500/50"
                              autoFocus
                            />
                            {watchSearchResults.length > 0 && (
                              <div className="absolute z-10 mt-1 w-full bg-[var(--surface)] border border-[var(--subtle-border)] rounded-lg shadow-xl max-h-48 overflow-y-auto">
                                {watchSearchResults.map((r) => (
                                  <button
                                    key={r.id}
                                    type="button"
                                    onClick={() => handleSelectWatchAsset(r)}
                                    className="w-full text-left px-3 py-2 hover:bg-[var(--hover-bg)] transition-colors"
                                  >
                                    <span className="text-[12px] text-[var(--text)] font-mono block truncate">{r.fqn}</span>
                                    <span className="text-[10px] text-[var(--muted)]">{r.name}</span>
                                  </button>
                                ))}
                              </div>
                            )}
                            {watchSearching && (
                              <div className="absolute right-3 top-3">
                                <div className="w-3.5 h-3.5 border-2 border-[var(--overlay-strong)] border-t-white/60 rounded-full animate-spin" />
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Watch type selection */}
                      {selectedWatchAsset && (
                        <div>
                          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                            Group type
                          </label>
                          <div className="space-y-2">
                            {WATCH_TYPES.map((wt) => (
                              <button
                                key={wt}
                                type="button"
                                onClick={() => {
                                  setWatchType(wt);
                                  setWatchName(`${WATCH_TYPE_LABELS[wt]}: ${selectedWatchAsset.name}`);
                                  setScopeMonitors([]);
                                  scopeFetchedRef.current = false;
                                }}
                                className={cn(
                                  'flex items-center gap-3 w-full h-[52px] px-4 rounded-lg border transition-colors text-left',
                                  wt === watchType
                                    ? 'border-blue-500/40 bg-blue-500/5'
                                    : 'border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] bg-[var(--surface)]'
                                )}
                              >
                                <svg className="w-5 h-5 text-[var(--muted)] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={WATCH_TYPE_ICONS[wt]} />
                                </svg>
                                <div className="flex-1 min-w-0">
                                  <p className="text-[13px] font-medium text-[var(--text)] leading-tight truncate">{WATCH_TYPE_LABELS[wt]}</p>
                                  <p className="text-[11px] text-[var(--muted)] leading-tight truncate">{WATCH_TYPE_DESCRIPTIONS[wt]}</p>
                                </div>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}

                  {/* Watch step 2: Scope & Monitors */}
                  {watchStep === 2 && (
                    <>
                      {/* Scope summary bar */}
                      <div className="flex items-center gap-4 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                        <div className="text-center">
                          <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">{scopeMonitors.filter((m) => m.checked).length}</p>
                          <p className="text-[10px] text-[var(--muted)] uppercase">Monitors</p>
                        </div>
                        <div className="w-px h-8 bg-[var(--subtle-border)]" />
                        <div className="text-center">
                          <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">{scopeNodeCount}</p>
                          <p className="text-[10px] text-[var(--muted)] uppercase">Assets</p>
                        </div>
                        <div className="w-px h-8 bg-[var(--subtle-border)]" />
                        <div className="text-center">
                          <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">{Math.round(coveragePct * 100)}%</p>
                          <p className="text-[10px] text-[var(--muted)] uppercase">Coverage</p>
                        </div>
                        <div className="flex-1" />
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => setScopeMonitors((prev) => prev.map((m) => ({ ...m, checked: true })))}
                            className="text-[11px] text-blue-400 hover:text-blue-300"
                          >All</button>
                          <span className="text-[var(--text-faint)]">|</span>
                          <button
                            type="button"
                            onClick={() => setScopeMonitors((prev) => prev.map((m) => ({ ...m, checked: false })))}
                            className="text-[11px] text-[var(--muted)] hover:text-[var(--text)]"
                          >None</button>
                        </div>
                      </div>

                      {/* Monitor list */}
                      {scopeLoading ? (
                        <div className="flex items-center justify-center py-10">
                          <div className="w-5 h-5 red-spinner" />
                          <span className="text-[12px] text-[var(--muted)] ml-2">Analyzing scope...</span>
                        </div>
                      ) : scopeMonitors.length === 0 ? (
                        <div className="text-center py-10">
                          <p className="text-[13px] text-[var(--muted)]">No monitors recommended for this asset.</p>
                          <p className="text-[11px] text-[var(--text-faint)] mt-1">Try a different watch type or asset.</p>
                        </div>
                      ) : (
                        <div className="space-y-1.5 max-h-[340px] overflow-y-auto">
                          {scopeMonitors.map((mon, i) => (
                            <div
                              key={i}
                              onClick={() => toggleScopeMonitor(i)}
                              className={cn(
                                'flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                                mon.checked
                                  ? 'border-[var(--subtle-border)] bg-[var(--surface)]'
                                  : 'border-transparent bg-[var(--overlay-bg)] opacity-50'
                              )}
                            >
                              <div className={cn(
                                'w-4 h-4 rounded border flex items-center justify-center shrink-0',
                                mon.checked
                                  ? 'bg-blue-500 border-blue-500'
                                  : 'border-[var(--overlay-strong)] bg-transparent'
                              )}>
                                {mon.checked && (
                                  <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                  </svg>
                                )}
                              </div>
                              <span className={cn(
                                'px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0',
                                PRIORITY_COLORS[mon.priority] || PRIORITY_COLORS[3]
                              )}>P{mon.priority}</span>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="px-1 py-0.5 rounded bg-white/5 text-[10px] uppercase text-[var(--muted)]">
                                    {(mon.monitorType || '').replace(/_/g, ' ')}
                                  </span>
                                </div>
                                <p className="text-[11px] text-[var(--muted)] mt-0.5 truncate">
                                  {mon.targetFqn}
                                  {mon.reason && ` — ${mon.reason}`}
                                </p>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}

                  {/* Watch step 3: Schedule */}
                  {watchStep === 3 && (
                    <>
                      <div>
                        <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                          How often should this watch run?
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
                          <option value="America/New_York">Eastern (US)</option>
                          <option value="America/Chicago">Central (US)</option>
                          <option value="America/Denver">Mountain (US)</option>
                          <option value="America/Los_Angeles">Pacific (US)</option>
                          <option value="Europe/London">London</option>
                          <option value="Europe/Berlin">Berlin</option>
                          <option value="Asia/Tokyo">Tokyo</option>
                        </select>
                      </div>
                    </>
                  )}

                  {/* Watch step 4: Alerts & Confirm */}
                  {watchStep === 4 && (
                    <>
                      <AlertChannelPicker
                        channels={alertChannels}
                        onChannelsChange={setAlertChannels}
                        alertOnStatus={alertOnStatus}
                        onAlertOnStatusChange={setAlertOnStatus}
                      />
                      {/* Summary card */}
                      <div className="p-4 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)]">
                        <div className="mb-3">
                          <label className="block text-[12px] font-medium text-[var(--muted)] mb-1.5">
                            Watch name
                          </label>
                          <input
                            type="text"
                            value={watchName}
                            onChange={(e) => setWatchName(e.target.value)}
                            className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)]"
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-3 text-[12px]">
                          <div>
                            <span className="text-[var(--text-faint)]">Type: </span>
                            <span className="text-[var(--text-secondary)]">{WATCH_TYPE_LABELS[watchType]}</span>
                          </div>
                          <div>
                            <span className="text-[var(--text-faint)]">Monitors: </span>
                            <span className="text-[var(--text-secondary)]">{scopeMonitors.filter((m) => m.checked).length}</span>
                          </div>
                          <div>
                            <span className="text-[var(--text-faint)]">Schedule: </span>
                            <span className="text-[var(--text-secondary)]">{schedule || 'None'}</span>
                          </div>
                          <div>
                            <span className="text-[var(--text-faint)]">Coverage: </span>
                            <span className="text-[var(--text-secondary)]">{Math.round(coveragePct * 100)}%</span>
                          </div>
                        </div>
                        {selectedWatchAsset && (
                          <div className="mt-2 pt-2 border-t border-[var(--border-faint)]">
                            <span className="text-[11px] text-[var(--text-faint)]">Anchor: </span>
                            <span className="text-[11px] text-[var(--text-secondary)] font-mono">{selectedWatchAsset.fqn}</span>
                          </div>
                        )}
                      </div>
                    </>
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

              {/* Integration selection — dynamic based on monitor type (non-watch) */}
              {taskMode !== 'watch' && renderIntegrationSelector()}
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
          {taskMode === 'watch' ? (
            // Watch mode footer — controls its own 4-step navigation
            <>
              <div>
                {watchStep > 1 && (
                  <Button variant="ghost" size="sm" onClick={() => setWatchStep((s) => s - 1)}>
                    Back
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={onClose}>
                  Cancel
                </Button>
                {watchStep < 4 ? (
                  <Button
                    size="sm"
                    disabled={
                      watchStep === 1 ? !selectedWatchAsset :
                      watchStep === 2 ? scopeMonitors.filter((m) => m.checked).length === 0 :
                      false
                    }
                    onClick={() => setWatchStep((s) => s + 1)}
                  >
                    Next
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    disabled={scopeMonitors.filter((m) => m.checked).length === 0}
                    onClick={handleSubmit}
                  >
                    Create Group Monitor
                  </Button>
                )}
              </div>
            </>
          ) : (
            // Normal mode footer — 3-step navigation
            <>
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
                    {isEditing ? 'Save Changes' : 'Create Task'}
                  </Button>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
