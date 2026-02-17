'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Check, CircleAlert, CircleDashed, Search, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import PipelineCanvas from '@/components/pipeline/PipelineCanvas';
import NodeConfigModal from '@/components/pipeline/NodeConfigModal';
import { IntegrationConfigModal } from '@/components/pipeline/IntegrationConfigModal';
import {
  INTEGRATIONS,
  IntegrationDefinition,
  PipelineEdge,
  PipelineLayer,
  PipelineNode,
  PipelineStack,
  TOOLS,
  getToolById,
} from '@/components/pipeline/types';

type ConnectorStatus = 'CONNECTED' | 'NEEDS_ATTENTION' | 'NOT_CONNECTED';
type ConnectorGroup = 'WAREHOUSE' | 'TRANSFORM' | 'ORCHESTRATION' | 'BI' | 'INGESTION' | 'STORAGE' | 'ALERTS';
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

const CORE_GROUP_ORDER: ConnectorGroup[] = ['WAREHOUSE', 'TRANSFORM', 'ORCHESTRATION', 'BI', 'INGESTION', 'STORAGE', 'ALERTS'];
const LAYER_ORDER: PipelineLayer[] = ['INGESTION', 'VERSION_CONTROL', 'ORCHESTRATION', 'TRANSFORMATION', 'WAREHOUSE', 'STORAGE', 'REPORTING'];
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

function normalizeConnectorId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '_');
}

function mapIntegrationTypeToConnectorId(type: string): string {
  const map: Record<string, string> = {
    SNOWFLAKE: 'snowflake',
    BIGQUERY: 'bigquery',
    REDSHIFT: 'redshift',
    POSTGRES: 'postgres',
    SQLSERVER: 'sqlserver',
    AZURE_SQL: 'azure_sql',
    DATABRICKS: 'databricks',
    FIVETRAN: 'fivetran',
    AIRBYTE: 'airbyte',
    STITCH: 'stitch',
    DBT_CLOUD: 'dbt_cloud',
    DBT_CORE: 'dbt_core',
    AIRFLOW: 'airflow',
    DAGSTER: 'dagster',
    PREFECT: 'prefect',
    LOOKER: 'looker',
    TABLEAU: 'tableau',
    POWERBI: 'powerbi',
    METABASE: 'metabase',
    AMAZON_S3: 'amazon_s3',
    GCS: 'gcs',
    ADLS: 'adls',
    SLACK: 'slack',
    TEAMS: 'teams',
    PAGERDUTY: 'pagerduty',
    OPSGENIE: 'opsgenie',
    JIRA: 'jira',
    LINEAR: 'linear',
    ASANA: 'asana',
    GITHUB_ISSUES: 'github_issues',
    MONTE_CARLO: 'monte_carlo',
    BIGEYE: 'bigeye',
    SODA: 'soda',
    ELEMENTARY: 'elementary',
  };
  return map[type] || normalizeConnectorId(type);
}

function categoryToGroup(category: string): ConnectorGroup {
  switch (category) {
    case 'NOTIFICATIONS':
    case 'TICKETING':
    case 'OBSERVABILITY':
      return 'ALERTS';
    default:
      return 'ALERTS';
  }
}

function groupLabel(group: ConnectorGroup): string {
  switch (group) {
    case 'WAREHOUSE':
      return 'Warehouse';
    case 'TRANSFORM':
      return 'Transform';
    case 'ORCHESTRATION':
      return 'Orchestration';
    case 'BI':
      return 'BI';
    case 'INGESTION':
      return 'Ingestion';
    case 'STORAGE':
      return 'Storage';
    case 'ALERTS':
      return 'Alerts';
  }
}

function createNodeForTool(toolId: string, layer: PipelineLayer, existingNodes: PipelineNode[]): PipelineNode {
  const sameLayerCount = existingNodes.filter((n) => n.layer === layer).length;
  const layerX: Record<PipelineLayer, number> = {
    INGESTION: 120,
    VERSION_CONTROL: 300,
    ORCHESTRATION: 300,
    TRANSFORMATION: 480,
    WAREHOUSE: 760,
    STORAGE: 880,
    REPORTING: 1040,
  };

  return {
    id: `node-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: getToolById(toolId)?.name || toolId,
    layer,
    toolType: toolId,
    positionX: layerX[layer],
    positionY: 80 + sameLayerCount * 170,
    status: 'PENDING',
    config: null,
    healthScore: null,
    findingsCount: 0,
    criticalCount: 0,
    highCount: 0,
  };
}

function buildAutoEdges(nodes: PipelineNode[], existingEdges: PipelineEdge[]): PipelineEdge[] {
  if (existingEdges.length > 0) {
    return existingEdges;
  }

  const nodesByLayer = new Map<PipelineLayer, PipelineNode[]>();
  LAYER_ORDER.forEach((layer) => nodesByLayer.set(layer, nodes.filter((n) => n.layer === layer)));
  const generated: PipelineEdge[] = [];

  for (let i = 0; i < LAYER_ORDER.length - 1; i += 1) {
    const current = nodesByLayer.get(LAYER_ORDER[i]) || [];
    const next = nodesByLayer.get(LAYER_ORDER[i + 1]) || [];
    if (current.length === 0 || next.length === 0) continue;

    current.forEach((sourceNode, sourceIndex) => {
      const target = next[sourceIndex % next.length];
      generated.push({
        id: `edge-auto-${sourceNode.id}-${target.id}`,
        sourceId: sourceNode.id,
        targetId: target.id,
      });
    });
  }

  return generated;
}

export default function PipelinePage() {
  const searchParams = useSearchParams();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [stack, setStack] = useState<PipelineStack>({
    id: 'new',
    name: 'My Data Pipeline',
    description: '',
    status: 'DRAFT',
    nodes: [],
    edges: [],
  });
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

  const connectorCatalog = useMemo<ConnectorCard[]>(() => {
    const coreConnectors: ConnectorCard[] = [
      ...TOOLS.WAREHOUSE.map((tool) => ({ id: tool.id, name: tool.name, description: tool.description, group: 'WAREHOUSE' as const, mode: 'pipeline' as const, layer: tool.layer })),
      ...TOOLS.TRANSFORMATION.filter((tool) => ['dbt_cloud', 'dbt_core'].includes(tool.id)).map((tool) => ({ id: tool.id, name: tool.name, description: tool.description, group: 'TRANSFORM' as const, mode: 'pipeline' as const, layer: tool.layer })),
      ...TOOLS.TRANSFORMATION.filter((tool) => ['airflow', 'dagster', 'prefect'].includes(tool.id)).map((tool) => ({ id: tool.id, name: tool.name, description: tool.description, group: 'ORCHESTRATION' as const, mode: 'pipeline' as const, layer: 'ORCHESTRATION' as const })),
      ...TOOLS.REPORTING.map((tool) => ({ id: tool.id, name: tool.name, description: tool.description, group: 'BI' as const, mode: 'pipeline' as const, layer: tool.layer })),
      ...TOOLS.INGESTION.map((tool) => ({ id: tool.id, name: tool.name, description: tool.description, group: 'INGESTION' as const, mode: 'pipeline' as const, layer: tool.layer })),
      ...TOOLS.STORAGE.map((tool) => ({ id: tool.id, name: tool.name, description: tool.description, group: 'STORAGE' as const, mode: 'pipeline' as const, layer: tool.layer })),
    ];

    const alertConnectors: ConnectorCard[] = Object.values(INTEGRATIONS)
      .flat()
      .map((integration) => ({
        id: integration.id,
        name: integration.name,
        description: integration.description,
        group: categoryToGroup(integration.category),
        mode: 'integration' as const,
        integration,
      }));

    return [...coreConnectors, ...alertConnectors];
  }, []);

  const connectedFromStack = useMemo(() => {
    return new Set(
      stack.nodes
        .filter((node) => node.config || ['CONNECTED', 'ACTIVE'].includes(node.status))
        .map((node) => node.toolType)
    );
  }, [stack.nodes]);

  const connectorStatusById = useMemo(() => {
    const statusMap = new Map<string, ConnectorStatus>();

    connectorCatalog.forEach((connector) => statusMap.set(connector.id, 'NOT_CONNECTED'));
    connectedFromStack.forEach((id) => {
      if (statusMap.has(id)) statusMap.set(id, 'CONNECTED');
    });

    integrationRecords.forEach((record) => {
      if (!statusMap.has(record.connectorId)) return;
      if (record.status === 'ACTIVE') {
        statusMap.set(record.connectorId, 'CONNECTED');
      } else if (record.status === 'ERROR' || !!record.lastError) {
        statusMap.set(record.connectorId, 'NEEDS_ATTENTION');
      }
    });

    return statusMap;
  }, [connectorCatalog, connectedFromStack, integrationRecords]);

  const selectedTemplate = useMemo(() => STACK_TEMPLATES.find((template) => template.id === selectedTemplateId) || null, [selectedTemplateId]);

  const filteredConnectors = useMemo(() => {
    const q = search.trim().toLowerCase();
    return connectorCatalog.filter((connector) => {
      if (selectedGroup !== 'ALL' && connector.group !== selectedGroup) return false;
      if (!q) return true;
      return (
        connector.name.toLowerCase().includes(q) ||
        connector.description.toLowerCase().includes(q) ||
        connector.id.toLowerCase().includes(q)
      );
    });
  }, [connectorCatalog, search, selectedGroup]);

  const checklistProgress = useMemo(() => {
    const completed = CHECKLIST_STEPS.filter((step) =>
      step.connectorIds.some((id) => connectorStatusById.get(id) === 'CONNECTED')
    ).length;
    return {
      completed,
      total: CHECKLIST_STEPS.length,
      percent: Math.round((completed / CHECKLIST_STEPS.length) * 100),
    };
  }, [connectorStatusById]);

  const filteredMapNodes = useMemo(() => {
    let visible = [...stack.nodes];

    if (planeFilter === 'data') {
      visible = visible.filter((node) => ['INGESTION', 'TRANSFORMATION', 'WAREHOUSE', 'STORAGE', 'REPORTING'].includes(node.layer));
    }
    if (planeFilter === 'control') {
      visible = visible.filter((node) => ['ORCHESTRATION', 'VERSION_CONTROL'].includes(node.layer));
    }
    if (onlyImpacted) {
      visible = visible.filter((node) => (node.findingsCount || 0) > 0 || (node.highCount || 0) > 0 || (node.criticalCount || 0) > 0);
    }
    if (onlyCriticalPaths) {
      visible = visible.filter((node) => (node.criticalCount || 0) > 0);
    }
    if (assetSearch.trim()) {
      const q = assetSearch.toLowerCase();
      visible = visible.filter((node) => node.name.toLowerCase().includes(q) || node.toolType.toLowerCase().includes(q));
    }

    return visible;
  }, [assetSearch, onlyCriticalPaths, onlyImpacted, planeFilter, stack.nodes]);

  const filteredMapEdges = useMemo(() => {
    const visibleIds = new Set(filteredMapNodes.map((node) => node.id));
    return stack.edges.filter((edge) => visibleIds.has(edge.sourceId) && visibleIds.has(edge.targetId));
  }, [filteredMapNodes, stack.edges]);

  const savePipeline = useCallback(async (nextStack: PipelineStack, silent = false) => {
    setSaving(true);
    try {
      const res = await fetch('/api/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nextStack),
      });

      if (!res.ok) throw new Error('Failed to save pipeline');
      const data = await res.json();
      setStack((prev) => ({ ...nextStack, id: data.stack?.id || data.id || prev.id }));
      if (!silent) toast.success('Pipeline map updated');
    } catch (error) {
      if (!silent) toast.error('Failed to save pipeline');
    } finally {
      setSaving(false);
    }
  }, []);

  const fetchIntegrations = useCallback(async () => {
    try {
      const res = await fetch('/api/integrations');
      if (!res.ok) return;
      const data = await res.json();
      const records: IntegrationRecord[] = (data.integrations || []).map((row: any) => ({
        id: row.id,
        connectorId: row.source === 'pipeline' && row.type ? mapIntegrationTypeToConnectorId(row.type) : mapIntegrationTypeToConnectorId(row.type || row.id),
        status: row.status || 'INACTIVE',
        source: row.source || 'legacy',
        lastError: row.lastError,
      }));
      setIntegrationRecords(records);
    } catch (error) {
      console.error('Failed to fetch integrations', error);
    }
  }, []);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [pipelineRes] = await Promise.all([fetch('/api/pipeline'), fetchIntegrations()]);
        if (pipelineRes.ok) {
          const data = await pipelineRes.json();
          if (data.stack) {
            setStack(data.stack);
          }
        }
      } catch (error) {
        console.error('Failed to load pipeline map', error);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [fetchIntegrations]);

  useEffect(() => {
    const success = searchParams.get('success');
    const error = searchParams.get('error');
    if (success === 'github') {
      toast.success('GitHub connected successfully');
      fetchIntegrations();
      window.history.replaceState({}, '', '/dashboard/pipeline');
    } else if (error) {
      toast.error(`Authentication error: ${error}`);
      window.history.replaceState({}, '', '/dashboard/pipeline');
    }
  }, [fetchIntegrations, searchParams]);

  useEffect(() => {
    const discoveredIds = new Set(
      integrationRecords
        .filter((record) => record.status === 'ACTIVE' && !!getToolById(record.connectorId))
        .map((record) => record.connectorId)
    );
    if (discoveredIds.size === 0) return;

    setStack((prev) => {
      const existing = new Set(prev.nodes.map((node) => node.toolType));
      const missing = [...discoveredIds].filter((id) => !existing.has(id));
      if (missing.length === 0) return prev;

      const appended = [...prev.nodes];
      missing.forEach((toolId) => {
        const tool = getToolById(toolId);
        if (!tool) return;
        appended.push({
          ...createNodeForTool(toolId, tool.layer, appended),
          status: 'CONNECTED',
          config: { _autoDiscovered: true },
        });
      });

      return {
        ...prev,
        nodes: appended,
        edges: buildAutoEdges(appended, prev.edges),
      };
    });
  }, [integrationRecords]);

  const nextSuggestedStep = useMemo(() => {
    return CHECKLIST_STEPS.find((step) => !step.connectorIds.some((id) => connectorStatusById.get(id) === 'CONNECTED')) || null;
  }, [connectorStatusById]);

  const handleConnect = useCallback((connector: ConnectorCard) => {
    if (connector.mode === 'integration' && connector.integration) {
      setIntegrationModal(connector.integration);
      return;
    }

    const existingNode = stack.nodes.find((node) => node.toolType === connector.id);
    if (existingNode) {
      setNodeModal(existingNode);
      return;
    }

    const layer = connector.layer || getToolById(connector.id)?.layer;
    if (!layer) return;
    const newNode = createNodeForTool(connector.id, layer, stack.nodes);
    setStack((prev) => ({ ...prev, nodes: [...prev.nodes, newNode], edges: buildAutoEdges([...prev.nodes, newNode], prev.edges) }));
    setNodeModal(newNode);
  }, [stack.nodes]);

  const handleNodeConfigSaved = useCallback((config: Record<string, any>) => {
    if (!nodeModal) return;
    setStack((prev) => {
      const hasNode = prev.nodes.some((node) => node.id === nodeModal.id);
      const nextNodes = hasNode
        ? prev.nodes.map((node) => (node.id === nodeModal.id ? { ...node, config, status: 'CONNECTED' as const } : node))
        : [...prev.nodes, { ...nodeModal, config, status: 'CONNECTED' as const }];
      const nextStack: PipelineStack = {
        ...prev,
        nodes: nextNodes,
        edges: buildAutoEdges(nextNodes, prev.edges),
      };
      void savePipeline(nextStack, true);
      return nextStack;
    });
    setNodeModal(null);
    toast.success('Connector configured');
  }, [nodeModal, savePipeline]);

  const onNodesChange = useCallback((nodes: PipelineNode[]) => {
    setStack((prev) => ({ ...prev, nodes }));
  }, []);

  const onEdgesChange = useCallback((edges: PipelineEdge[]) => {
    setStack((prev) => ({ ...prev, edges }));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[520px]">
        <div className="text-sm text-[var(--muted)]">Loading pipeline map...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-8">
      <section className="dashboard-card p-6 space-y-5">
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
              onChange={(event) => setEnvironment(event.target.value as (typeof ENVIRONMENTS)[number])}
              className="px-3 py-2 rounded-lg bg-white/[0.04] border border-white/10 text-sm"
            >
              {ENVIRONMENTS.map((env) => (
                <option key={env} value={env}>
                  {env}
                </option>
              ))}
            </select>
            <button
              onClick={() => setEditMode((prev) => !prev)}
              className={`px-3 py-2 rounded-lg text-sm border transition-colors ${
                editMode
                  ? 'bg-[var(--accent)]/15 border-[var(--accent)]/30 text-[var(--accent)]'
                  : 'bg-white/[0.04] border-white/10 text-white'
              }`}
            >
              {editMode ? 'Edit mode on' : 'Inspect mode (read-only)'}
            </button>
            <button
              onClick={() => savePipeline(stack)}
              className="btn btn-secondary"
              disabled={saving}
            >
              {saving ? 'Saving...' : 'Save map'}
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-4 mb-3">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-[var(--accent)]" />
              <h2 className="text-sm font-medium">Setup progress</h2>
            </div>
            <div className="text-xs text-[var(--muted)]">{checklistProgress.completed}/{checklistProgress.total} complete ({checklistProgress.percent}%)</div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            {CHECKLIST_STEPS.map((step) => {
              const connected = step.connectorIds.some((id) => connectorStatusById.get(id) === 'CONNECTED');
              return (
                <div
                  key={step.key}
                  className={`px-3 py-2 rounded-lg border text-xs ${
                    connected
                      ? 'border-emerald-500/30 bg-emerald-500/10'
                      : 'border-white/10 bg-white/[0.02]'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {connected ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <CircleDashed className="w-3.5 h-3.5 text-[var(--muted)]" />}
                    <span>{step.label}</span>
                  </div>
                  <div className="mt-1 text-[10px] text-[var(--muted)]">
                    {step.required ? 'Recommended now' : 'Optional'}
                  </div>
                </div>
              );
            })}
          </div>
          {nextSuggestedStep && (
            <p className="text-xs text-[var(--muted)] mt-3">
              Next step: connect <span className="text-white">{nextSuggestedStep.label}</span>
            </p>
          )}
        </div>

        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-4 mb-3">
            <h3 className="text-sm font-medium">Stack templates</h3>
            <span className="text-xs text-[var(--muted)]">One-click starter bundles</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {STACK_TEMPLATES.map((template) => (
              <button
                key={template.id}
                onClick={() => setSelectedTemplateId(template.id)}
                className={`text-left rounded-lg border p-3 transition-colors ${
                  selectedTemplateId === template.id
                    ? 'border-[var(--accent)]/40 bg-[var(--accent)]/10'
                    : 'border-white/10 bg-white/[0.01] hover:bg-white/[0.04]'
                }`}
              >
                <div className="text-sm font-medium">{template.name}</div>
                <div className="text-xs text-[var(--muted)] mt-1">{template.description}</div>
              </button>
            ))}
          </div>
          {selectedTemplate && (
            <p className="text-xs text-[var(--muted)] mt-3">
              Template active: {selectedTemplate.name}. Recommended connectors are highlighted below.
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search connectors"
              className="w-full pl-9 pr-3 py-2 rounded-lg bg-white/[0.04] border border-white/10 text-sm"
            />
          </div>
          <button
            onClick={() => setSelectedGroup('ALL')}
            className={`px-3 py-2 rounded-lg text-xs border ${selectedGroup === 'ALL' ? 'border-[var(--accent)]/40 bg-[var(--accent)]/10' : 'border-white/10 bg-white/[0.02]'}`}
          >
            All
          </button>
          {CORE_GROUP_ORDER.map((group) => (
            <button
              key={group}
              onClick={() => setSelectedGroup(group)}
              className={`px-3 py-2 rounded-lg text-xs border ${selectedGroup === group ? 'border-[var(--accent)]/40 bg-[var(--accent)]/10' : 'border-white/10 bg-white/[0.02]'}`}
            >
              {groupLabel(group)}
            </button>
          ))}
        </div>

        {CORE_GROUP_ORDER.map((group) => {
          const connectors = filteredConnectors.filter((connector) => connector.group === group);
          if (connectors.length === 0) return null;
          return (
            <div key={group} className="space-y-2">
              <h3 className="text-sm font-medium">{groupLabel(group)}</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {connectors.map((connector) => {
                  const status = connectorStatusById.get(connector.id) || 'NOT_CONNECTED';
                  const recommended = selectedTemplate?.recommendedConnectorIds.includes(connector.id);
                  return (
                    <div key={connector.id} className={`rounded-xl border p-3 bg-white/[0.02] ${recommended ? 'border-[var(--accent)]/40' : 'border-white/10'}`}>
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h4 className="font-medium text-sm">{connector.name}</h4>
                          <p className="text-xs text-[var(--muted)] mt-1">{connector.description}</p>
                        </div>
                        {status === 'CONNECTED' ? (
                          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                            <Check className="w-3 h-3" />
                            Connected
                          </span>
                        ) : status === 'NEEDS_ATTENTION' ? (
                          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20">
                            <CircleAlert className="w-3 h-3" />
                            Needs attention
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-white/[0.04] text-[var(--muted)] border border-white/10">
                            Not connected
                          </span>
                        )}
                      </div>
                      <div className="mt-3 flex items-center justify-between gap-2">
                        <span className="text-[10px] text-[var(--muted)]">Read-only mode supported</span>
                        <button
                          onClick={() => handleConnect(connector)}
                          className="px-3 py-1.5 rounded-lg text-xs border border-white/10 hover:bg-white/[0.05]"
                        >
                          Connect
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </section>

      <section className="dashboard-card p-4">
        <div className="flex items-center justify-between gap-4 mb-4 px-1">
          <div>
            <h2 className="text-xl font-semibold">Pipeline Map</h2>
            <p className="text-sm text-[var(--muted)] mt-1">
              Auto-generated from connected integrations
            </p>
          </div>
          <div className="text-xs px-2.5 py-1 rounded-full border border-white/10 bg-white/[0.03]">
            {editMode ? 'Edit mode enabled' : 'Inspect mode (default)'}
          </div>
        </div>

        <div className="flex gap-4 h-[620px]">
          <div className="w-72 flex-shrink-0 rounded-xl border border-white/10 bg-white/[0.02] p-3 space-y-3">
            <div>
              <div className="text-xs uppercase tracking-wide text-[var(--muted)] mb-2">Filters</div>
              <div className="flex items-center gap-1">
                {(['all', 'data', 'control'] as PlaneFilter[]).map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setPlaneFilter(filter)}
                    className={`px-2.5 py-1.5 rounded-md text-xs border ${
                      planeFilter === filter
                        ? 'border-[var(--accent)]/40 bg-[var(--accent)]/10'
                        : 'border-white/10 bg-white/[0.02]'
                    }`}
                  >
                    {filter === 'all' ? 'Data + control' : `${filter} plane`}
                  </button>
                ))}
              </div>
            </div>

            <label className="flex items-center justify-between text-xs">
              <span>Only impacted assets</span>
              <input type="checkbox" checked={onlyImpacted} onChange={(event) => setOnlyImpacted(event.target.checked)} />
            </label>

            <label className="flex items-center justify-between text-xs">
              <span>Only critical paths</span>
              <input type="checkbox" checked={onlyCriticalPaths} onChange={(event) => setOnlyCriticalPaths(event.target.checked)} />
            </label>

            <div>
              <div className="text-xs text-[var(--muted)] mb-1">Search assets</div>
              <input
                value={assetSearch}
                onChange={(event) => setAssetSearch(event.target.value)}
                placeholder="table / model / dashboard"
                className="w-full px-3 py-2 rounded-md bg-white/[0.04] border border-white/10 text-xs"
              />
            </div>

            <div className="pt-2 border-t border-white/10 text-xs text-[var(--muted)]">
              Environment: <span className="text-white">{environment}</span>
            </div>

            {editMode && (
              <div className="pt-2 border-t border-white/10 text-[11px] text-[var(--muted)]">
                Edit mode allows manual node positioning and edge overrides on the map.
              </div>
            )}
          </div>

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
        onClose={() => setIntegrationModal(null)}
        onSuccess={fetchIntegrations}
      />
    </div>
  );
}
