'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Check, CircleAlert, CircleDashed, Loader2, Pencil, Search, Sparkles, Trash2, Unplug, Zap } from 'lucide-react';
import { toast } from 'sonner';
import PipelineCanvas from '@/components/pipeline/PipelineCanvas';
import NodeConfigModal from '@/components/pipeline/NodeConfigModal';
import { IntegrationConfigModal } from '@/components/pipeline/IntegrationConfigModal';
import {
  INTEGRATIONS,
  IntegrationDefinition,
  LAYER_COLORS,
  PipelineEdge,
  PipelineLayer,
  PipelineNode,
  PipelineStack,
  TOOLS,
  getToolById,
} from '@/components/pipeline/types';

type ConnectorStatus = 'CONNECTED' | 'NEEDS_ATTENTION' | 'NOT_CONNECTED';
type ConnectorGroup = 'WAREHOUSE' | 'TRANSFORM' | 'ORCHESTRATION' | 'BI' | 'INGESTION' | 'STORAGE' | 'INFRASTRUCTURE' | 'ALERTS';
type PlaneFilter = 'all' | 'data' | 'control';

interface ConnectorCard {
  id: string;
  name: string;
  description: string;
  group: ConnectorGroup;
  mode: 'pipeline' | 'integration';
  layer?: PipelineLayer;
  integration?: IntegrationDefinition;
}

interface IntegrationRecord {
  id: string;
  connectorId: string;
  status: string;
  source: 'pipeline' | 'legacy';
  lastError?: string | null;
}

const CORE_GROUP_ORDER: ConnectorGroup[] = ['WAREHOUSE', 'TRANSFORM', 'ORCHESTRATION', 'BI', 'INGESTION', 'STORAGE', 'INFRASTRUCTURE', 'ALERTS'];
const LAYER_ORDER: PipelineLayer[] = ['INGESTION', 'VERSION_CONTROL', 'ORCHESTRATION', 'TRANSFORMATION', 'WAREHOUSE', 'STORAGE', 'REPORTING', 'INFRASTRUCTURE'];
const ENVIRONMENTS = ['Dev', 'Staging', 'Prod'] as const;

const STACK_TEMPLATES = [
  {
    id: 'gcp-analytics-stack',
    name: 'GCP Analytics Stack',
    description: 'BigQuery + dbt Cloud + Airflow + Looker',
    recommendedConnectorIds: ['bigquery', 'dbt_cloud', 'airflow', 'looker'],
  },
  {
    id: 'snowflake-stack',
    name: 'Snowflake Stack',
    description: 'Snowflake + dbt Cloud + Tableau',
    recommendedConnectorIds: ['snowflake', 'dbt_cloud', 'tableau'],
  },
  {
    id: 'oss-stack',
    name: 'OSS Stack',
    description: 'Airbyte + dbt Core + Apache Airflow + Microsoft Power BI',
    recommendedConnectorIds: ['airbyte', 'dbt_core', 'airflow', 'powerbi'],
  },
];

const CHECKLIST_STEPS: Array<{ key: string; label: string; connectorIds: string[]; required: boolean }> = [
  { key: 'warehouse', label: 'Warehouse', connectorIds: ['bigquery', 'snowflake', 'postgres', 'redshift', 'sqlserver', 'azure_sql', 'databricks'], required: true },
  { key: 'transform', label: 'Transform', connectorIds: ['dbt_cloud', 'dbt_core'], required: true },
  { key: 'orchestration', label: 'Orchestration', connectorIds: ['airflow', 'dagster', 'prefect'], required: false },
  { key: 'bi', label: 'BI', connectorIds: ['looker', 'tableau', 'powerbi', 'metabase'], required: false },
  { key: 'alerts', label: 'Alerts', connectorIds: ['slack', 'teams', 'pagerduty', 'opsgenie', 'jira', 'linear', 'asana', 'github_issues', 'monte_carlo', 'bigeye', 'soda', 'elementary'], required: false },
];

const GROUP_COLORS: Record<ConnectorGroup, string> = {
  WAREHOUSE: LAYER_COLORS.WAREHOUSE,
  TRANSFORM: LAYER_COLORS.TRANSFORMATION,
  ORCHESTRATION: LAYER_COLORS.ORCHESTRATION,
  BI: LAYER_COLORS.REPORTING,
  INGESTION: LAYER_COLORS.INGESTION,
  STORAGE: LAYER_COLORS.STORAGE,
  INFRASTRUCTURE: LAYER_COLORS.INFRASTRUCTURE,
  ALERTS: '#EF4444',
};

function normalizeConnectorId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '_');
}

function mapIntegrationTypeToConnectorId(type: string): string {
  const map: Record<string, string> = {
    SNOWFLAKE: 'snowflake', BIGQUERY: 'bigquery', REDSHIFT: 'redshift', POSTGRES: 'postgres',
    SQLSERVER: 'sqlserver', AZURE_SQL: 'azure_sql', DATABRICKS: 'databricks',
    FIVETRAN: 'fivetran', AIRBYTE: 'airbyte', STITCH: 'stitch',
    DBT_CLOUD: 'dbt_cloud', DBT_CORE: 'dbt_core',
    AIRFLOW: 'airflow', DAGSTER: 'dagster', PREFECT: 'prefect',
    LOOKER: 'looker', TABLEAU: 'tableau', POWERBI: 'powerbi', METABASE: 'metabase',
    AMAZON_S3: 'amazon_s3', GCS: 'gcs', ADLS: 'adls',
    LINUX_SERVER: 'linux_server',
    SLACK: 'slack', TEAMS: 'teams', PAGERDUTY: 'pagerduty', OPSGENIE: 'opsgenie',
    JIRA: 'jira', LINEAR: 'linear', ASANA: 'asana', GITHUB_ISSUES: 'github_issues',
    MONTE_CARLO: 'monte_carlo', BIGEYE: 'bigeye', SODA: 'soda', ELEMENTARY: 'elementary',
  };
  return map[type] || normalizeConnectorId(type);
}

function categoryToGroup(category: string): ConnectorGroup {
  switch (category) {
    case 'NOTIFICATIONS': case 'TICKETING': case 'OBSERVABILITY': return 'ALERTS';
    default: return 'ALERTS';
  }
}

function groupLabel(group: ConnectorGroup): string {
  const labels: Record<ConnectorGroup, string> = {
    WAREHOUSE: 'Warehouse', TRANSFORM: 'Transform', ORCHESTRATION: 'Orchestration',
    BI: 'BI / Reporting', INGESTION: 'Ingestion', STORAGE: 'Storage', INFRASTRUCTURE: 'Infrastructure', ALERTS: 'Alerts & Integrations',
  };
  return labels[group];
}

function createNodeForTool(toolId: string, layer: PipelineLayer, existingNodes: PipelineNode[]): PipelineNode {
  const sameLayerCount = existingNodes.filter((n) => n.layer === layer).length;
  const layerX: Record<PipelineLayer, number> = {
    INGESTION: 120, VERSION_CONTROL: 300, ORCHESTRATION: 300, TRANSFORMATION: 480,
    WAREHOUSE: 760, STORAGE: 880, REPORTING: 1040, INFRASTRUCTURE: 1160,
  };
  return {
    id: `node-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: getToolById(toolId)?.name || toolId,
    layer, toolType: toolId,
    positionX: layerX[layer], positionY: 80 + sameLayerCount * 170,
    status: 'PENDING', config: null, healthScore: null,
    findingsCount: 0, criticalCount: 0, highCount: 0,
  };
}

function buildAutoEdges(nodes: PipelineNode[], existingEdges: PipelineEdge[]): PipelineEdge[] {
  if (existingEdges.length > 0) return existingEdges;
  const nodesByLayer = new Map<PipelineLayer, PipelineNode[]>();
  LAYER_ORDER.forEach((layer) => nodesByLayer.set(layer, nodes.filter((n) => n.layer === layer)));
  const generated: PipelineEdge[] = [];
  for (let i = 0; i < LAYER_ORDER.length - 1; i += 1) {
    const current = nodesByLayer.get(LAYER_ORDER[i]) || [];
    const next = nodesByLayer.get(LAYER_ORDER[i + 1]) || [];
    if (current.length === 0 || next.length === 0) continue;
    current.forEach((sourceNode, sourceIndex) => {
      const target = next[sourceIndex % next.length];
      generated.push({ id: `edge-auto-${sourceNode.id}-${target.id}`, sourceId: sourceNode.id, targetId: target.id });
    });
  }
  return generated;
}

export default function PipelinePage() {
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [stack, setStack] = useState<PipelineStack>({ id: 'new', name: 'My Data Pipeline', description: '', status: 'DRAFT', nodes: [], edges: [] });
  const [integrationRecords, setIntegrationRecords] = useState<IntegrationRecord[]>([]);
  const [search, setSearch] = useState('');
  const [selectedGroup, setSelectedGroup] = useState<ConnectorGroup | 'ALL'>('ALL');
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [environment, setEnvironment] = useState<(typeof ENVIRONMENTS)[number]>('Prod');
  const [editMode, setEditMode] = useState(false);
  const [planeFilter, setPlaneFilter] = useState<PlaneFilter>('all');
  const [onlyImpacted, setOnlyImpacted] = useState(false);
  const [onlyCriticalPaths, setOnlyCriticalPaths] = useState(false);
  const [assetSearch, setAssetSearch] = useState('');
  const [nodeModal, setNodeModal] = useState<PipelineNode | null>(null);
  const [integrationModal, setIntegrationModal] = useState<IntegrationDefinition | null>(null);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [expandedConnector, setExpandedConnector] = useState<string | null>(null);

  // ─── Derived data ─────────────────────────────────────────
  const connectorCatalog = useMemo<ConnectorCard[]>(() => {
    const coreConnectors: ConnectorCard[] = [
      ...TOOLS.WAREHOUSE.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'WAREHOUSE' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.TRANSFORMATION.filter((t) => ['dbt_cloud', 'dbt_core'].includes(t.id)).map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'TRANSFORM' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.TRANSFORMATION.filter((t) => ['airflow', 'dagster', 'prefect'].includes(t.id)).map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'ORCHESTRATION' as const, mode: 'pipeline' as const, layer: 'ORCHESTRATION' as const })),
      ...TOOLS.REPORTING.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'BI' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.INGESTION.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'INGESTION' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.STORAGE.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'STORAGE' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.INFRASTRUCTURE.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'INFRASTRUCTURE' as const, mode: 'pipeline' as const, layer: t.layer })),
    ];
    const alertConnectors: ConnectorCard[] = Object.values(INTEGRATIONS).flat().map((i) => ({
      id: i.id, name: i.name, description: i.description, group: categoryToGroup(i.category), mode: 'integration' as const, integration: i,
    }));
    return [...coreConnectors, ...alertConnectors];
  }, []);

  const connectedFromStack = useMemo(() => new Set(
    stack.nodes.filter((n) => n.config || ['CONNECTED', 'ACTIVE'].includes(n.status)).map((n) => n.toolType)
  ), [stack.nodes]);

  const connectorStatusById = useMemo(() => {
    const m = new Map<string, ConnectorStatus>();
    connectorCatalog.forEach((c) => m.set(c.id, 'NOT_CONNECTED'));
    connectedFromStack.forEach((id) => { if (m.has(id)) m.set(id, 'CONNECTED'); });
    integrationRecords.forEach((r) => {
      if (!m.has(r.connectorId)) return;
      if (r.status === 'ACTIVE') m.set(r.connectorId, 'CONNECTED');
      else if (r.status === 'ERROR' || !!r.lastError) m.set(r.connectorId, 'NEEDS_ATTENTION');
    });
    return m;
  }, [connectorCatalog, connectedFromStack, integrationRecords]);

  const selectedTemplate = useMemo(() => STACK_TEMPLATES.find((t) => t.id === selectedTemplateId) || null, [selectedTemplateId]);

  const filteredConnectors = useMemo(() => {
    const q = search.trim().toLowerCase();
    return connectorCatalog.filter((c) => {
      if (selectedGroup !== 'ALL' && c.group !== selectedGroup) return false;
      if (!q) return true;
      return c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q) || c.id.toLowerCase().includes(q);
    });
  }, [connectorCatalog, search, selectedGroup]);

  const checklistProgress = useMemo(() => {
    const completed = CHECKLIST_STEPS.filter((s) => s.connectorIds.some((id) => connectorStatusById.get(id) === 'CONNECTED')).length;
    return { completed, total: CHECKLIST_STEPS.length, percent: Math.round((completed / CHECKLIST_STEPS.length) * 100) };
  }, [connectorStatusById]);

  const filteredMapNodes = useMemo(() => {
    let visible = [...stack.nodes];
    if (planeFilter === 'data') visible = visible.filter((n) => ['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'STORAGE', 'REPORTING'].includes(n.layer));
    if (planeFilter === 'control') visible = visible.filter((n) => ['ORCHESTRATION', 'VERSION_CONTROL'].includes(n.layer));
    if (onlyImpacted) visible = visible.filter((n) => (n.findingsCount || 0) > 0 || (n.highCount || 0) > 0 || (n.criticalCount || 0) > 0);
    if (onlyCriticalPaths) visible = visible.filter((n) => (n.criticalCount || 0) > 0);
    if (assetSearch.trim()) { const q = assetSearch.toLowerCase(); visible = visible.filter((n) => n.name.toLowerCase().includes(q) || n.toolType.toLowerCase().includes(q)); }
    return visible;
  }, [assetSearch, onlyCriticalPaths, onlyImpacted, planeFilter, stack.nodes]);

  const filteredMapEdges = useMemo(() => {
    const ids = new Set(filteredMapNodes.map((n) => n.id));
    return stack.edges.filter((e) => ids.has(e.sourceId) && ids.has(e.targetId));
  }, [filteredMapNodes, stack.edges]);

  // ─── Actions ──────────────────────────────────────────────
  const savePipeline = useCallback(async (nextStack: PipelineStack, silent = false) => {
    setSaving(true);
    try {
      const res = await fetch('/api/pipeline', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(nextStack) });
      if (!res.ok) throw new Error('save failed');
      const data = await res.json();
      setStack((prev) => ({ ...nextStack, id: data.stack?.id || data.id || prev.id }));
      if (!silent) toast.success('Pipeline saved');
    } catch { if (!silent) toast.error('Failed to save pipeline'); }
    finally { setSaving(false); }
  }, []);

  const fetchIntegrations = useCallback(async () => {
    try {
      const res = await fetch('/api/integrations');
      if (!res.ok) return;
      const data = await res.json();
      setIntegrationRecords((data.integrations || []).map((row: any) => ({
        id: row.id,
        connectorId: mapIntegrationTypeToConnectorId(row.type || row.id),
        status: row.status || 'INACTIVE', source: row.source || 'legacy', lastError: row.lastError,
      })));
    } catch (e) { console.error('Failed to fetch integrations', e); }
  }, []);

  const handleDisconnect = useCallback(async (connector: ConnectorCard) => {
    if (connector.mode === 'integration') {
      const record = integrationRecords.find((r) => r.connectorId === connector.id);
      if (!record) return;
      setDisconnecting(connector.id);
      try {
        const res = await fetch(`/api/integrations/${record.id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('delete failed');
        await fetchIntegrations();
        toast.success(`${connector.name} disconnected`);
      } catch { toast.error(`Failed to disconnect ${connector.name}`); }
      finally { setDisconnecting(null); }
    } else {
      const node = stack.nodes.find((n) => n.toolType === connector.id);
      if (!node) return;
      setDisconnecting(connector.id);
      const nextNodes = stack.nodes.filter((n) => n.id !== node.id);
      const nextEdges = stack.edges.filter((e) => e.sourceId !== node.id && e.targetId !== node.id);
      const nextStack: PipelineStack = { ...stack, nodes: nextNodes, edges: nextEdges };
      setStack(nextStack);
      await savePipeline(nextStack, true);
      setDisconnecting(null);
      toast.success(`${connector.name} removed from pipeline`);
    }
    setExpandedConnector(null);
  }, [fetchIntegrations, integrationRecords, savePipeline, stack]);

  // ─── Effects ──────────────────────────────────────────────
  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [pipelineRes] = await Promise.all([fetch('/api/pipeline'), fetchIntegrations()]);
        if (pipelineRes.ok) { const data = await pipelineRes.json(); if (data.stack) setStack(data.stack); }
      } catch (e) { console.error('Failed to load pipeline map', e); }
      finally { setLoading(false); }
    };
    load();
  }, [fetchIntegrations]);

  useEffect(() => {
    const success = searchParams.get('success');
    const error = searchParams.get('error');
    if (success === 'github') { toast.success('GitHub connected successfully'); fetchIntegrations(); window.history.replaceState({}, '', '/dashboard/pipeline'); }
    else if (error) { toast.error(`Authentication error: ${error}`); window.history.replaceState({}, '', '/dashboard/pipeline'); }
  }, [fetchIntegrations, searchParams]);

  useEffect(() => {
    const discoveredIds = new Set(
      integrationRecords.filter((r) => r.status === 'ACTIVE' && !!getToolById(r.connectorId)).map((r) => r.connectorId)
    );
    if (discoveredIds.size === 0) return;
    setStack((prev) => {
      const existing = new Set(prev.nodes.map((n) => n.toolType));
      const missing = [...discoveredIds].filter((id) => !existing.has(id));
      if (missing.length === 0) return prev;
      const appended = [...prev.nodes];
      missing.forEach((toolId) => { const tool = getToolById(toolId); if (!tool) return; appended.push({ ...createNodeForTool(toolId, tool.layer, appended), status: 'CONNECTED', config: { _autoDiscovered: true } }); });
      return { ...prev, nodes: appended, edges: buildAutoEdges(appended, prev.edges) };
    });
  }, [integrationRecords]);

  const nextSuggestedStep = useMemo(() => CHECKLIST_STEPS.find((s) => !s.connectorIds.some((id) => connectorStatusById.get(id) === 'CONNECTED')) || null, [connectorStatusById]);

  // ─── Handlers ─────────────────────────────────────────────
  const handleConnect = useCallback((connector: ConnectorCard) => {
    if (connector.mode === 'integration' && connector.integration) { setIntegrationModal(connector.integration); return; }
    const existingNode = stack.nodes.find((n) => n.toolType === connector.id);
    if (existingNode) { setNodeModal(existingNode); return; }
    const layer = connector.layer || getToolById(connector.id)?.layer;
    if (!layer) return;
    const newNode = createNodeForTool(connector.id, layer, stack.nodes);
    setStack((prev) => ({ ...prev, nodes: [...prev.nodes, newNode], edges: buildAutoEdges([...prev.nodes, newNode], prev.edges) }));
    setNodeModal(newNode);
  }, [stack.nodes]);

  const handleNodeConfigSaved = useCallback((config: Record<string, any>) => {
    if (!nodeModal) return;
    setStack((prev) => {
      const hasNode = prev.nodes.some((n) => n.id === nodeModal.id);
      const nextNodes = hasNode
        ? prev.nodes.map((n) => (n.id === nodeModal.id ? { ...n, config, status: 'CONNECTED' as const } : n))
        : [...prev.nodes, { ...nodeModal, config, status: 'CONNECTED' as const }];
      const nextStack: PipelineStack = { ...prev, nodes: nextNodes, edges: buildAutoEdges(nextNodes, prev.edges) };
      void savePipeline(nextStack, true);
      return nextStack;
    });
    setNodeModal(null);
    fetchIntegrations();
    toast.success('Connector configured');
  }, [nodeModal, savePipeline, fetchIntegrations]);

  const onNodesChange = useCallback((nodes: PipelineNode[]) => setStack((prev) => ({ ...prev, nodes })), []);
  const onEdgesChange = useCallback((edges: PipelineEdge[]) => setStack((prev) => ({ ...prev, edges })), []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[520px]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-[var(--accent-2)]" />
          <span className="text-sm text-[var(--muted)]">Loading pipeline...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-8">
      {/* ── Connectors Section ─────────────────────────────── */}
      <section className="dashboard-card p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Connectors</h1>
            <p className="text-sm text-[var(--muted)] mt-1">
              Connect tools first. Pallisade auto-discovers and renders your pipeline map.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={environment}
              onChange={(e) => setEnvironment(e.target.value as (typeof ENVIRONMENTS)[number])}
              className="form-select !py-2 !text-sm !rounded-lg"
            >
              {ENVIRONMENTS.map((env) => <option key={env} value={env}>{env}</option>)}
            </select>
            <button
              onClick={() => setEditMode((p) => !p)}
              className={`px-3 py-2 rounded-lg text-sm border transition-all ${
                editMode
                  ? 'border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--accent-2)] shadow-accent'
                  : 'border-white/10 bg-white/[0.04] text-white hover:border-white/20'
              }`}
            >
              {editMode ? 'Edit mode' : 'Inspect mode'}
            </button>
            <button onClick={() => savePipeline(stack)} className="btn btn-primary !py-2 !px-4 !text-sm" disabled={saving}>
              {saving ? <><Loader2 className="w-4 h-4 mr-1.5 animate-spin" />Saving...</> : 'Save map'}
            </button>
          </div>
        </div>

        {/* Setup Progress */}
        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-4 mb-3">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-[var(--accent-2)]" />
              <h2 className="text-sm font-medium">Setup progress</h2>
            </div>
            <div className="text-xs text-[var(--muted)]">{checklistProgress.completed}/{checklistProgress.total} complete ({checklistProgress.percent}%)</div>
          </div>

          {/* Progress bar */}
          <div className="h-1.5 rounded-full bg-white/[0.06] mb-3 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700 ease-out"
              style={{ width: `${checklistProgress.percent}%`, background: checklistProgress.percent === 100 ? '#10B981' : 'var(--accent-2)' }}
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            {CHECKLIST_STEPS.map((step) => {
              const connected = step.connectorIds.some((id) => connectorStatusById.get(id) === 'CONNECTED');
              return (
                <div
                  key={step.key}
                  className={`px-3 py-2 rounded-lg border text-xs transition-all ${
                    connected
                      ? 'border-emerald-500/30 bg-emerald-500/10'
                      : 'border-white/10 bg-white/[0.02]'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {connected ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <CircleDashed className="w-3.5 h-3.5 text-[var(--muted)]" />}
                    <span>{step.label}</span>
                  </div>
                  <div className="mt-1 text-[10px] text-[var(--muted)]">{step.required ? 'Required' : 'Optional'}</div>
                </div>
              );
            })}
          </div>
          {nextSuggestedStep && (
            <p className="text-xs text-[var(--muted)] mt-3">
              Next step: connect <span className="text-[var(--accent-2)] font-medium">{nextSuggestedStep.label}</span>
            </p>
          )}
        </div>

        {/* Stack Templates */}
        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-4 mb-3">
            <h3 className="text-sm font-medium">Stack templates</h3>
            <span className="text-xs text-[var(--muted)]">One-click starter bundles</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {STACK_TEMPLATES.map((template) => {
              const active = selectedTemplateId === template.id;
              return (
                <button
                  key={template.id}
                  onClick={() => setSelectedTemplateId(active ? null : template.id)}
                  className={`text-left rounded-lg border p-3 transition-all ${
                    active
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10 shadow-accent'
                      : 'border-white/10 bg-white/[0.01] hover:bg-white/[0.04] hover:border-white/20'
                  }`}
                >
                  <div className="text-sm font-medium">{template.name}</div>
                  <div className="text-xs text-[var(--muted)] mt-1">{template.description}</div>
                  {active && <div className="text-[10px] text-[var(--accent-2)] mt-2 font-medium">Selected — recommended tools highlighted below</div>}
                </button>
              );
            })}
          </div>
        </div>

        {/* Search + Filters */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search connectors..."
              className="form-input !pl-9 !py-2 !text-sm !rounded-lg"
            />
          </div>
          {(['ALL', ...CORE_GROUP_ORDER] as const).map((group) => {
            const active = selectedGroup === group;
            const color = group === 'ALL' ? 'var(--accent-2)' : GROUP_COLORS[group as ConnectorGroup];
            return (
              <button
                key={group}
                onClick={() => setSelectedGroup(group as ConnectorGroup | 'ALL')}
                className={`px-3 py-2 rounded-lg text-xs border transition-all ${
                  active
                    ? 'text-white font-medium'
                    : 'border-white/10 bg-white/[0.02] text-[var(--muted)] hover:text-white hover:border-white/20'
                }`}
                style={active ? { borderColor: `${color}50`, backgroundColor: `${color}18`, color: 'white' } : undefined}
              >
                {group === 'ALL' ? 'All' : groupLabel(group as ConnectorGroup)}
              </button>
            );
          })}
        </div>

        {/* Connector Cards by Group */}
        {CORE_GROUP_ORDER.map((group) => {
          const connectors = filteredConnectors.filter((c) => c.group === group);
          if (connectors.length === 0) return null;
          const gColor = GROUP_COLORS[group];
          return (
            <div key={group} className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: gColor }} />
                <h3 className="text-sm font-medium">{groupLabel(group)}</h3>
                <span className="text-[10px] text-[var(--muted)]">({connectors.length})</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {connectors.map((connector) => {
                  const status = connectorStatusById.get(connector.id) || 'NOT_CONNECTED';
                  const recommended = selectedTemplate?.recommendedConnectorIds.includes(connector.id);
                  const isExpanded = expandedConnector === connector.id;
                  const isDisconnecting = disconnecting === connector.id;

                  return (
                    <div
                      key={connector.id}
                      className={`rounded-xl border p-4 transition-all cursor-pointer group ${
                        status === 'CONNECTED'
                          ? 'border-emerald-500/30 bg-emerald-500/[0.04] hover:bg-emerald-500/[0.07]'
                          : status === 'NEEDS_ATTENTION'
                          ? 'border-amber-500/30 bg-amber-500/[0.04] hover:bg-amber-500/[0.07]'
                          : recommended
                          ? 'border-[var(--accent)]/40 bg-[var(--accent)]/[0.04] hover:bg-[var(--accent)]/[0.08] hover:border-[var(--accent)]/60'
                          : 'border-white/10 bg-white/[0.02] hover:bg-white/[0.05] hover:border-white/20'
                      }`}
                      onClick={() => setExpandedConnector(isExpanded ? null : connector.id)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-3 min-w-0">
                          <div
                            className="w-9 h-9 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                            style={{ backgroundColor: `${gColor}30`, color: gColor }}
                          >
                            {connector.name.charAt(0)}
                          </div>
                          <div className="min-w-0">
                            <h4 className="font-medium text-sm truncate">{connector.name}</h4>
                            <p className="text-xs text-[var(--muted)] mt-0.5 truncate">{connector.description}</p>
                          </div>
                        </div>
                        {status === 'CONNECTED' ? (
                          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/25 flex-shrink-0">
                            <Check className="w-3 h-3" />
                            Connected
                          </span>
                        ) : status === 'NEEDS_ATTENTION' ? (
                          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/25 flex-shrink-0">
                            <CircleAlert className="w-3 h-3" />
                            Error
                          </span>
                        ) : recommended ? (
                          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-[var(--accent)]/15 text-[var(--accent-2)] border border-[var(--accent)]/30 flex-shrink-0">
                            <Zap className="w-3 h-3" />
                            Recommended
                          </span>
                        ) : null}
                      </div>

                      {/* Action buttons — always visible at bottom */}
                      <div className="mt-3 pt-3 border-t border-white/[0.06] flex items-center gap-2">
                        {status === 'CONNECTED' ? (
                          <>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleConnect(connector); }}
                              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs border border-white/10 hover:bg-white/[0.06] hover:border-white/20 transition-all"
                            >
                              <Pencil className="w-3 h-3" />
                              Edit config
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleDisconnect(connector); }}
                              disabled={isDisconnecting}
                              className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs border border-red-500/20 text-red-400 hover:bg-red-500/10 hover:border-red-500/30 transition-all disabled:opacity-50"
                            >
                              {isDisconnecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Unplug className="w-3 h-3" />}
                              Disconnect
                            </button>
                          </>
                        ) : status === 'NEEDS_ATTENTION' ? (
                          <>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleConnect(connector); }}
                              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs bg-amber-500/10 border border-amber-500/20 text-amber-300 hover:bg-amber-500/20 transition-all"
                            >
                              <Pencil className="w-3 h-3" />
                              Fix connection
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleDisconnect(connector); }}
                              disabled={isDisconnecting}
                              className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs border border-red-500/20 text-red-400 hover:bg-red-500/10 transition-all disabled:opacity-50"
                            >
                              {isDisconnecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                            </button>
                          </>
                        ) : (
                          <button
                            onClick={(e) => { e.stopPropagation(); handleConnect(connector); }}
                            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs btn-primary !py-2 !text-xs !shadow-none transition-all"
                          >
                            <Zap className="w-3 h-3" />
                            Connect
                          </button>
                        )}
                      </div>

                      {/* Expanded details */}
                      {isExpanded && status === 'CONNECTED' && (
                        <div className="mt-3 pt-3 border-t border-white/[0.06] text-xs text-[var(--muted)]">
                          <div className="flex items-center gap-2">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                            <span>Active connection — credentials stored securely</span>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </section>

      {/* ── Pipeline Map Section ───────────────────────────── */}
      <section className="dashboard-card p-4">
        <div className="flex items-center justify-between gap-4 mb-4 px-1">
          <div>
            <h2 className="text-xl font-semibold">Pipeline Map</h2>
            <p className="text-sm text-[var(--muted)] mt-1">Auto-generated from connected integrations</p>
          </div>
          <div className={`text-xs px-2.5 py-1 rounded-full border ${
            editMode
              ? 'border-[var(--accent)]/30 bg-[var(--accent)]/10 text-[var(--accent-2)]'
              : 'border-white/10 bg-white/[0.03] text-[var(--muted)]'
          }`}>
            {editMode ? 'Edit mode' : 'Inspect mode'}
          </div>
        </div>

        <div className="flex gap-4 h-[620px]">
          {/* Filter Sidebar */}
          <div className="w-72 flex-shrink-0 rounded-xl border border-white/10 bg-white/[0.02] p-3 space-y-3 overflow-y-auto">
            <div>
              <div className="text-xs uppercase tracking-wide text-[var(--muted)] mb-2">Plane filter</div>
              <div className="flex items-center gap-1">
                {(['all', 'data', 'control'] as PlaneFilter[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setPlaneFilter(f)}
                    className={`px-2.5 py-1.5 rounded-md text-xs border transition-all ${
                      planeFilter === f
                        ? 'border-[var(--accent)] bg-[var(--accent)]/15 text-white'
                        : 'border-white/10 bg-white/[0.02] text-[var(--muted)] hover:text-white'
                    }`}
                  >
                    {f === 'all' ? 'All planes' : `${f.charAt(0).toUpperCase()}${f.slice(1)} plane`}
                  </button>
                ))}
              </div>
            </div>

            <label className="flex items-center justify-between text-xs cursor-pointer group/toggle">
              <span className="text-[var(--muted)] group-hover/toggle:text-white transition-colors">Only impacted assets</span>
              <input
                type="checkbox"
                checked={onlyImpacted}
                onChange={(e) => setOnlyImpacted(e.target.checked)}
                className="accent-[var(--accent-2)]"
              />
            </label>

            <label className="flex items-center justify-between text-xs cursor-pointer group/toggle">
              <span className="text-[var(--muted)] group-hover/toggle:text-white transition-colors">Only critical paths</span>
              <input
                type="checkbox"
                checked={onlyCriticalPaths}
                onChange={(e) => setOnlyCriticalPaths(e.target.checked)}
                className="accent-[var(--accent-2)]"
              />
            </label>

            <div>
              <div className="text-xs text-[var(--muted)] mb-1">Search assets</div>
              <input
                value={assetSearch}
                onChange={(e) => setAssetSearch(e.target.value)}
                placeholder="table / model / dashboard"
                className="form-input !px-3 !py-2 !text-xs !rounded-md"
              />
            </div>

            <div className="pt-2 border-t border-white/10 text-xs text-[var(--muted)]">
              Environment: <span className="text-white font-medium">{environment}</span>
            </div>

            {/* Map legend */}
            <div className="pt-2 border-t border-white/10">
              <div className="text-xs text-[var(--muted)] mb-2">Legend</div>
              <div className="space-y-1.5">
                {(['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'STORAGE', 'REPORTING', 'INFRASTRUCTURE'] as PipelineLayer[]).map((layer) => (
                  <div key={layer} className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS[layer] }} />
                    <span className="text-[11px] text-[var(--muted)]">{layer.charAt(0) + layer.slice(1).toLowerCase()}</span>
                  </div>
                ))}
              </div>
            </div>

            {editMode && (
              <div className="pt-2 border-t border-white/10 text-[11px] text-[var(--muted)]">
                Drag nodes to reposition. Connect handles to create edges.
              </div>
            )}
          </div>

          {/* Canvas */}
          <div className="flex-1 rounded-xl overflow-hidden border border-white/10">
            <PipelineCanvas
              nodes={filteredMapNodes}
              edges={filteredMapEdges}
              stackId={stack.id}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onSave={() => savePipeline(stack, true)}
              readOnly={!editMode}
            />
          </div>
        </div>
      </section>

      {/* ── Modals ─────────────────────────────────────────── */}
      {nodeModal && (
        <NodeConfigModal
          node={nodeModal}
          stackId={stack.id === 'new' ? undefined : stack.id}
          onSave={handleNodeConfigSaved}
          onClose={() => setNodeModal(null)}
        />
      )}
      <IntegrationConfigModal
        integration={integrationModal}
        isOpen={integrationModal !== null}
        onClose={() => { setIntegrationModal(null); fetchIntegrations(); }}
        onSuccess={fetchIntegrations}
      />
    </div>
  );
}
