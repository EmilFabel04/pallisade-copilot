'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Check, ChevronDown, CircleAlert, Info, Loader2, Pencil, Search, Trash2, Unplug, X } from 'lucide-react';
import { ToolIcon } from '@/components/icons/ToolIcon';
import { usePipeline } from '@/contexts/PipelineContext';
import { toast } from 'sonner';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import NodeConfigModal from '@/components/pipeline/NodeConfigModal';
import { IntegrationConfigModal } from '@/components/pipeline/IntegrationConfigModal';
import {
  INTEGRATIONS,
  IntegrationDefinition,
  LAYER_COLORS,
  MULTI_ROLE_TOOLS,
  PipelineEdge,
  PipelineLayer,
  PipelineNode,
  PipelineStack,
  TOOLS,
  getToolById,
  isMultiRoleTool,
} from '@/components/pipeline/types';

type ConnectorStatus = 'CONNECTED' | 'NEEDS_ATTENTION' | 'NOT_CONNECTED';
type ConnectorGroup = 'WAREHOUSE' | 'TRANSFORM' | 'ORCHESTRATION' | 'BI' | 'INGESTION' | 'STORAGE' | 'VERSION_CONTROL' | 'INFRASTRUCTURE' | 'ALERTS';

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

const CORE_GROUP_ORDER: ConnectorGroup[] = ['WAREHOUSE', 'TRANSFORM', 'ORCHESTRATION', 'VERSION_CONTROL', 'BI', 'INGESTION', 'STORAGE', 'INFRASTRUCTURE', 'ALERTS'];
const LAYER_ORDER: PipelineLayer[] = ['INGESTION', 'VERSION_CONTROL', 'ORCHESTRATION', 'TRANSFORMATION', 'WAREHOUSE', 'STORAGE', 'REPORTING', 'INFRASTRUCTURE'];
const ENVIRONMENTS = ['Dev', 'Staging', 'Prod'] as const;

const CONNECTION_STATUS_CATEGORIES: Array<{ key: string; label: string; connectorIds: string[] }> = [
  { key: 'warehouse', label: 'Warehouse', connectorIds: ['bigquery', 'snowflake', 'postgres', 'redshift', 'sqlserver', 'azure_sql', 'databricks'] },
  { key: 'transform', label: 'Transform', connectorIds: ['dbt_cloud', 'dbt_core'] },
  { key: 'orchestration', label: 'Orchestration', connectorIds: ['airflow', 'dagster', 'prefect'] },
  { key: 'version_control', label: 'Version Control', connectorIds: ['github', 'gitlab', 'bitbucket'] },
  { key: 'bi', label: 'BI', connectorIds: ['looker', 'tableau', 'powerbi', 'metabase'] },
  { key: 'ingestion', label: 'Ingestion', connectorIds: ['fivetran', 'airbyte', 'stitch'] },
  { key: 'storage', label: 'Storage', connectorIds: ['amazon_s3', 'gcs', 'adls'] },
  { key: 'alerts', label: 'Alerts', connectorIds: ['slack', 'teams', 'pagerduty', 'opsgenie', 'jira', 'linear', 'asana', 'github_issues'] },
];

const VCS_PROVIDERS = [
  { id: 'github', name: 'GitHub' },
  { id: 'gitlab', name: 'GitLab' },
  { id: 'bitbucket', name: 'Bitbucket' },
];

const GROUP_COLORS: Record<ConnectorGroup, string> = {
  WAREHOUSE: LAYER_COLORS.WAREHOUSE,
  TRANSFORM: LAYER_COLORS.TRANSFORMATION,
  ORCHESTRATION: LAYER_COLORS.ORCHESTRATION,
  BI: LAYER_COLORS.REPORTING,
  INGESTION: LAYER_COLORS.INGESTION,
  STORAGE: LAYER_COLORS.STORAGE,
  VERSION_CONTROL: LAYER_COLORS.VERSION_CONTROL,
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
    AIRFLOW: 'airflow', DAGSTER: 'dagster', PREFECT: 'prefect', N8N: 'n8n',
    LOOKER: 'looker', TABLEAU: 'tableau', POWERBI: 'powerbi', METABASE: 'metabase',
    AMAZON_S3: 'amazon_s3', GCS: 'gcs', ADLS: 'adls',
    GITHUB: 'github', GITLAB: 'gitlab', BITBUCKET: 'bitbucket',
    LINUX_SERVER: 'linux_server',
    SLACK: 'slack', TEAMS: 'teams', PAGERDUTY: 'pagerduty', OPSGENIE: 'opsgenie',
    JIRA: 'jira', LINEAR: 'linear', ASANA: 'asana', GITHUB_ISSUES: 'github_issues',
  };
  return map[type] || normalizeConnectorId(type);
}

function categoryToGroup(category: string): ConnectorGroup {
  switch (category) {
    case 'NOTIFICATIONS': case 'TICKETING': return 'ALERTS';
    default: return 'ALERTS';
  }
}

function groupLabel(group: ConnectorGroup): string {
  const labels: Record<ConnectorGroup, string> = {
    WAREHOUSE: 'Warehouse', TRANSFORM: 'Transform', ORCHESTRATION: 'Orchestration', VERSION_CONTROL: 'Version Control',
    BI: 'BI / Reporting', INGESTION: 'Ingestion', STORAGE: 'Storage', INFRASTRUCTURE: 'Infrastructure', ALERTS: 'Alerts & Integrations',
  };
  return labels[group];
}

function createNodeForTool(toolId: string, layer: PipelineLayer, existingNodes: PipelineNode[]): PipelineNode {
  const sameLayerCount = existingNodes.filter((n) => n.layer === layer).length;
  const layerX: Record<PipelineLayer, number> = {
    INGESTION: 120, VERSION_CONTROL: 300, ORCHESTRATION: 300, TRANSFORMATION: 480,
    WAREHOUSE: 760, STORAGE: 880, REPORTING: 1040, INFRASTRUCTURE: 1160, UNCATEGORIZED: 0,
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
  const { selectedPipelineId, loading: pipelineLoading } = usePipeline();
  const lastPipelineIdRef = useRef<string | null>(null);
  const saveInFlightRef = useRef<Promise<void> | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [stack, setStack] = useState<PipelineStack>({ id: 'new', name: 'My Data Pipeline', description: '', status: 'DRAFT', nodes: [], edges: [] });
  const [integrationRecords, setIntegrationRecords] = useState<IntegrationRecord[]>([]);
  const [search, setSearch] = useState('');
  const [selectedGroup, setSelectedGroup] = useState<ConnectorGroup | 'ALL'>('ALL');
  const [environment, setEnvironment] = useState<(typeof ENVIRONMENTS)[number]>('Prod');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<ConnectorGroup>>(new Set(CORE_GROUP_ORDER));
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
      ...TOOLS.ORCHESTRATION.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'ORCHESTRATION' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.REPORTING.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'BI' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.INGESTION.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'INGESTION' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.STORAGE.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'STORAGE' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.INFRASTRUCTURE.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'INFRASTRUCTURE' as const, mode: 'pipeline' as const, layer: t.layer })),
      ...TOOLS.VERSION_CONTROL.map((t) => ({ id: t.id, name: t.name, description: t.description, group: 'VERSION_CONTROL' as const, mode: 'pipeline' as const, layer: t.layer })),
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

  const filteredConnectors = useMemo(() => {
    const q = search.trim().toLowerCase();
    return connectorCatalog.filter((c) => {
      if (selectedGroup !== 'ALL' && c.group !== selectedGroup) return false;
      if (!q) return true;
      return c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q) || c.id.toLowerCase().includes(q);
    });
  }, [connectorCatalog, search, selectedGroup]);

  const hasVcsConnected = useMemo(() => VCS_PROVIDERS.some((p) => connectorStatusById.get(p.id) === 'CONNECTED'), [connectorStatusById]);


  // ─── Actions ──────────────────────────────────────────────
  const savePipeline = useCallback(async (nextStack: PipelineStack, silent = false) => {
    // Wait for any in-flight save to finish before starting a new one
    if (saveInFlightRef.current) {
      try { await saveInFlightRef.current; } catch { /* ignore */ }
    }
    setSaving(true);
    const doSave = async () => {
      try {
        const res = await fetch('/api/pipeline', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(nextStack) });
        if (!res.ok) throw new Error('save failed');
        const data = await res.json();
        setStack((prev) => ({ ...nextStack, id: data.stack?.id || data.id || prev.id }));
        invalidateCache('/api/pipeline');
        invalidateCache('/api/integrations');
        if (!silent) toast.success('Pipeline saved');
      } catch { toast.error('Failed to save pipeline'); }
      finally { setSaving(false); saveInFlightRef.current = null; }
    };
    saveInFlightRef.current = doSave();
    return saveInFlightRef.current;
  }, []);

  const fetchIntegrations = useCallback(async () => {
    if (!selectedPipelineId) return;
    try {
      const res = await cachedFetch(`/api/integrations?stackId=${selectedPipelineId}`);
      if (!res.ok) return;
      const data = await res.json();
      setIntegrationRecords((data.integrations || []).map((row: any) => ({
        id: row.id,
        connectorId: mapIntegrationTypeToConnectorId(row.type || row.id),
        status: row.status || 'INACTIVE', source: row.source || 'legacy', lastError: row.lastError,
      })));
    } catch (e) { console.error('Failed to fetch integrations', e); }
  }, [selectedPipelineId]);

  const handleDisconnect = useCallback(async (connector: ConnectorCard) => {
    if (connector.mode === 'integration') {
      const record = integrationRecords.find((r) => r.connectorId === connector.id);
      if (!record) return;
      setDisconnecting(connector.id);
      // Optimistic: immediately remove from UI
      setIntegrationRecords(prev => prev.filter(r => r.connectorId !== connector.id));
      try {
        const res = await fetch(`/api/integrations/${record.id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('delete failed');
        // Clear config on nodes that referenced this integration so they show as disconnected
        setStack(prev => ({
          ...prev,
          nodes: prev.nodes.map(n =>
            (n as any).integrationId === record.id || n.toolType === connector.id
              ? { ...n, config: null, status: 'PENDING' as const }
              : n
          ),
        }));
        await fetchIntegrations();
        toast.success(`${connector.name} disconnected`);
      } catch {
        // Rollback on failure
        setIntegrationRecords(prev => [...prev, record]);
        toast.error(`Failed to disconnect ${connector.name}`);
      }
      finally { setDisconnecting(null); }
    } else {
      const node = stack.nodes.find((n) => n.toolType === connector.id);
      if (!node) return;
      setDisconnecting(connector.id);
      const nextNodes = stack.nodes.filter((n) => n.id !== node.id);
      const nextEdges = stack.edges.filter((e) => e.sourceId !== node.id && e.targetId !== node.id);
      const nextStack: PipelineStack = { ...stack, nodes: nextNodes, edges: nextEdges };
      setStack(nextStack);
      // Delete the associated integration record if one exists — await to ensure
      // it's gone before the pipeline save invalidates cache and triggers refetch
      const intRecord = integrationRecords.find((r) => r.connectorId === connector.id);
      if (intRecord) {
        setIntegrationRecords(prev => prev.filter(r => r.connectorId !== connector.id));
        try {
          await fetch(`/api/integrations/${intRecord.id}`, { method: 'DELETE' });
        } catch {}
      }
      await savePipeline(nextStack, true);
      setDisconnecting(null);
      toast.success(`${connector.name} removed from pipeline`);
    }
    setExpandedConnector(null);
  }, [fetchIntegrations, integrationRecords, savePipeline, stack]);

  // ─── Effects ──────────────────────────────────────────────
  // Re-load when pipeline profile changes
  useEffect(() => {
    if (pipelineLoading) return;
    if (!selectedPipelineId) {
      setStack({ id: 'new', name: 'My Data Pipeline', description: '', status: 'DRAFT', nodes: [], edges: [] });
      setIntegrationRecords([]);
      setLoading(false);
      return;
    }
    // Skip if pipeline hasn't changed
    if (lastPipelineIdRef.current === selectedPipelineId) return;
    lastPipelineIdRef.current = selectedPipelineId;

    const load = async () => {
      setLoading(true);
      initialLoadRef.current = false;
      // Reset state for new pipeline
      setStack({ id: 'new', name: 'My Data Pipeline', description: '', status: 'DRAFT', nodes: [], edges: [] });
      setIntegrationRecords([]);
      setExpandedConnector(null);
      try {
        const [pipelineRes] = await Promise.all([
          cachedFetch(`/api/pipeline?stackId=${selectedPipelineId}`),
          fetchIntegrations(),
        ]);
        if (pipelineRes.ok) {
          const data = await pipelineRes.json();
          if (data.stack) {
            // Deduplicate nodes by toolType — auto-discovery race may have created duplicates.
            // Keep the node with real config (not _autoDiscovered) when duplicates exist.
            const seen = new Map<string, any>();
            const dedupedNodes: any[] = [];
            for (const node of data.stack.nodes) {
              const existing = seen.get(node.toolType);
              if (!existing) {
                seen.set(node.toolType, node);
                dedupedNodes.push(node);
              } else {
                const hasRealConfig = node.config && !node.config._autoDiscovered;
                const existingHasReal = existing.config && !existing.config._autoDiscovered;
                if (hasRealConfig && !existingHasReal) {
                  const idx = dedupedNodes.indexOf(existing);
                  dedupedNodes[idx] = node;
                  seen.set(node.toolType, node);
                }
              }
            }

            // Filter edges to only reference surviving node IDs
            const survivingIds = new Set(dedupedNodes.map((n: any) => n.id));
            const dedupedEdges = (data.stack.edges || []).filter(
              (e: any) => survivingIds.has(e.sourceId) && survivingIds.has(e.targetId)
            );

            const deduped = { ...data.stack, nodes: dedupedNodes, edges: dedupedEdges };
            setStack(deduped);

            // Pre-populate autoDiscoveredRef so auto-discovery won't re-create these
            deduped.nodes.forEach((n: any) => autoDiscoveredRef.current.add(n.toolType));

            // If duplicates were removed, persist the clean stack
            if (dedupedNodes.length < data.stack.nodes.length) {
              void savePipeline(deduped, true);
            }
          }
        }
      } catch (e) { console.error('Failed to load pipeline map', e); }
      finally { setLoading(false); initialLoadRef.current = true; }
    };
    load();
  }, [selectedPipelineId, pipelineLoading, fetchIntegrations]);

  useEffect(() => {
    const success = searchParams.get('success');
    const error = searchParams.get('error');
    if (success === 'github') {
      toast.success('GitHub connected successfully');
      fetchIntegrations();
      // Re-open the dbt Core config modal if GitHub was connected from there
      const pending = sessionStorage.getItem('pending_github_node');
      if (pending) {
        try {
          const { nodeId } = JSON.parse(pending);
          sessionStorage.removeItem('pending_github_node');
          const targetNode = stack.nodes.find((n) => n.id === nodeId);
          if (targetNode) {
            // Small delay to let integrations refresh before opening modal
            setTimeout(() => setNodeModal(targetNode), 300);
          }
        } catch { /* ignore parse errors */ }
      }
      window.history.replaceState({}, '', '/dashboard/pipeline');
    }
    else if (success === 'slack') { toast.success('Slack connected successfully'); fetchIntegrations(); window.history.replaceState({}, '', '/dashboard/pipeline'); }
    else if (error) { toast.error(`Authentication error: ${error}`); window.history.replaceState({}, '', '/dashboard/pipeline'); }
  }, [fetchIntegrations, searchParams, stack.nodes]);

  // Deep-link: open a specific tool's config modal via ?openConfig=<toolType>
  useEffect(() => {
    if (loading) return;
    const openConfig = searchParams.get('openConfig');
    if (!openConfig) return;
    // Expand the group containing this connector so it's visible behind the modal
    const connector = connectorCatalog.find((c) => c.id === openConfig);
    if (connector) {
      setCollapsedGroups((prev) => {
        const next = new Set(prev);
        next.delete(connector.group);
        return next;
      });
    }
    const existingNode = stack.nodes.find((n) => n.toolType === openConfig);
    if (existingNode) {
      setNodeModal(existingNode);
    } else {
      // Check if it's an integration (Slack, etc.)
      const integrationDef = Object.values(INTEGRATIONS).flat().find((i) => i.id === openConfig);
      if (integrationDef) {
        setIntegrationModal(integrationDef);
      }
    }
    window.history.replaceState({}, '', '/dashboard/pipeline');
  }, [loading, searchParams, stack.nodes, connectorCatalog]);

  // Track which tool types have already been auto-discovered to avoid re-running on every refetch
  const autoDiscoveredRef = useRef<Set<string>>(new Set());
  // Gate auto-discovery: don't run until the initial pipeline load is complete
  const initialLoadRef = useRef(false);

  // Reset when pipeline changes
  useEffect(() => { autoDiscoveredRef.current = new Set(); initialLoadRef.current = false; }, [selectedPipelineId]);

  useEffect(() => {
    // Don't run until the initial pipeline load is complete — prevents creating
    // duplicate nodes if the integrations API responds before the pipeline API.
    if (!initialLoadRef.current) return;
    const discoveredIds = new Set(
      integrationRecords.filter((r) => r.status === 'ACTIVE' && !!getToolById(r.connectorId)).map((r) => r.connectorId)
    );
    if (discoveredIds.size === 0) return;
    // Only process tool types we haven't already auto-discovered
    const newIds = [...discoveredIds].filter((id) => !autoDiscoveredRef.current.has(id));
    if (newIds.length === 0) return;
    setStack((prev) => {
      const existing = new Set(prev.nodes.map((n) => n.toolType));
      const missing = newIds.filter((id) => !existing.has(id));
      // Mark all as discovered regardless (they exist either via prior load or just now)
      newIds.forEach((id) => autoDiscoveredRef.current.add(id));
      if (missing.length === 0) return prev;
      const appended = [...prev.nodes];
      missing.forEach((toolId) => { const tool = getToolById(toolId); if (!tool) return; appended.push({ ...createNodeForTool(toolId, tool.layer, appended), status: 'CONNECTED', config: { _autoDiscovered: true } }); });
      return { ...prev, nodes: appended, edges: buildAutoEdges(appended, prev.edges) };
    });
  }, [integrationRecords]);


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
    toast.success('Connector configured');
  }, [nodeModal, savePipeline]);


  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[520px]">
        <div className="w-8 h-8 red-spinner" />
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
            <button onClick={() => savePipeline(stack)} className="btn btn-primary !py-2 !px-4 !text-sm" disabled={saving}>
              {saving ? <><Loader2 className="w-4 h-4 mr-1.5 animate-spin" />Saving...</> : 'Save'}
            </button>
          </div>
        </div>

        {/* Connected Status */}
        <div className="flex items-center gap-2 flex-wrap">
          {CONNECTION_STATUS_CATEGORIES.map((cat) => {
            const connected = cat.connectorIds.some((id) => connectorStatusById.get(id) === 'CONNECTED');
            return (
              <div
                key={cat.key}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs transition-all ${
                  connected
                    ? 'border-emerald-500/30 bg-emerald-500/10'
                    : 'border-[var(--border-medium)] bg-[var(--overlay-faint)] text-[var(--muted)]'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400' : 'bg-[var(--muted)]'}`} />
                <span>{cat.label}</span>
              </div>
            );
          })}
        </div>

        {/* VCS Integration Callout */}
        <div className={`rounded-xl border p-4 ${hasVcsConnected ? 'border-emerald-500/25 bg-emerald-500/[0.04]' : 'border-blue-500/25 bg-blue-500/[0.06]'}`}>
          <div className="flex items-start gap-3">
            <Info className={`w-5 h-5 flex-shrink-0 mt-0.5 ${hasVcsConnected ? 'text-emerald-400' : 'text-blue-400'}`} />
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-medium">
                {hasVcsConnected ? 'Version control connected' : 'Connect version control for richer tool context'}
              </h3>
              <p className="text-xs text-[var(--muted)] mt-1 leading-relaxed">
                {hasVcsConnected
                  ? 'Your VCS is linked — open source tools like dbt, Airflow, and Dagster can access their code repos. Configure repo paths here as a universal source instead of reconfiguring in each tool.'
                  : 'Link your VCS to give open source tools like dbt, Airflow, and Dagster access to their code repos. This acts as a universal source — configure repo paths here instead of reconfiguring version control in each tool separately.'}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
            {VCS_PROVIDERS.map((provider) => {
              const connector = connectorCatalog.find((c) => c.id === provider.id);
              const isConnected = connectorStatusById.get(provider.id) === 'CONNECTED';
              return (
                <button
                  key={provider.id}
                  onClick={() => connector && handleConnect(connector)}
                  className={`flex items-center gap-3 rounded-lg border p-3 text-left transition-all ${
                    isConnected
                      ? 'border-emerald-500/30 bg-emerald-500/[0.06] hover:bg-emerald-500/[0.1]'
                      : 'border-[var(--border-medium)] bg-[var(--overlay-faint)] hover:bg-[var(--overlay-bg)] hover:border-[var(--overlay-strong)]'
                  }`}
                >
                  <ToolIcon toolType={provider.id} className="w-8 h-8" />
                  <div>
                    <div className="text-sm font-medium">{provider.name}</div>
                    {isConnected ? (
                      <div className="text-[10px] text-emerald-400 flex items-center gap-1">
                        <Check className="w-3 h-3" /> Connected
                      </div>
                    ) : (
                      <div className="text-[10px] text-blue-400">Connect →</div>
                    )}
                  </div>
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
                    ? 'text-[var(--text)] font-medium'
                    : 'border-[var(--border-medium)] bg-[var(--overlay-faint)] text-[var(--muted)] hover:text-[var(--text)] hover:border-[var(--overlay-strong)]'
                }`}
                style={active ? { borderColor: `${color}50`, backgroundColor: `${color}18`, color: 'var(--text)' } : undefined}
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
              <button
                onClick={() => setCollapsedGroups(prev => {
                  const next = new Set(prev);
                  next.has(group) ? next.delete(group) : next.add(group);
                  return next;
                })}
                className="flex items-center gap-2 w-full text-left group/hdr"
              >
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: gColor }} />
                <h3 className="text-sm font-medium">{groupLabel(group)}</h3>
                <span className="text-[10px] text-[var(--muted)]">({connectors.length})</span>
                <ChevronDown className={`w-3.5 h-3.5 text-[var(--muted)] ml-auto transition-transform ${collapsedGroups.has(group) ? '-rotate-90' : ''}`} />
              </button>
              {!collapsedGroups.has(group) && <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {connectors.map((connector) => {
                  const status = connectorStatusById.get(connector.id) || 'NOT_CONNECTED';
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
                          : 'border-[var(--border-medium)] bg-[var(--overlay-faint)] hover:bg-[var(--subtle-bg)] hover:border-[var(--overlay-strong)]'
                      }`}
                      onClick={() => setExpandedConnector(isExpanded ? null : connector.id)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-3 min-w-0">
                          <ToolIcon toolType={connector.id} size={36} />
                          <div className="min-w-0">
                            <h4 className="font-medium text-sm truncate">{connector.name}</h4>
                            <p className="text-xs text-[var(--muted)] mt-0.5 truncate">{connector.description}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          {isMultiRoleTool(connector.id) && status !== 'CONNECTED' && (
                            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20" title="Supports multiple pipeline roles">
                              Multi-role
                            </span>
                          )}
                          {status === 'CONNECTED' ? (
                            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/25">
                              <Check className="w-3 h-3" />
                              Connected
                            </span>
                          ) : status === 'NEEDS_ATTENTION' ? (
                            <span className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/25">
                              <CircleAlert className="w-3 h-3" />
                              Error
                            </span>
                          ) : null}
                        </div>
                      </div>

                      {/* Action buttons — always visible at bottom */}
                      <div className="mt-3 pt-3 border-t border-[var(--subtle-border)] flex items-center gap-2">
                        {status === 'CONNECTED' ? (
                          <>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleConnect(connector); }}
                              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs border border-[var(--border-medium)] hover:bg-[var(--hover-bg)] hover:border-[var(--overlay-strong)] transition-all"
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
                            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs border border-[var(--border-medium)] text-[var(--text)] hover:bg-[var(--hover-bg)] hover:border-[var(--overlay-strong)] transition-all"
                          >
                            Connect
                          </button>
                        )}
                      </div>

                      {/* Multi-role badges — shown for connected multi-role tools */}
                      {status === 'CONNECTED' && isMultiRoleTool(connector.id) && (
                        <div className="mt-3 pt-3 border-t border-[var(--subtle-border)]">
                          <div className="text-[10px] text-[var(--muted)] mb-2 uppercase tracking-wider font-medium">Detected Roles</div>
                          <div className="flex flex-wrap gap-1.5">
                            {MULTI_ROLE_TOOLS[connector.id].map((role) => (
                              <span
                                key={role.layer}
                                className="inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded-full border"
                                style={{
                                  borderColor: `${role.color}40`,
                                  backgroundColor: `${role.color}15`,
                                  color: role.color,
                                }}
                                title={role.description}
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: role.color }} />
                                {role.label}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Expanded details */}
                      {isExpanded && status === 'CONNECTED' && (
                        <div className="mt-3 pt-3 border-t border-[var(--subtle-border)] text-xs text-[var(--muted)]">
                          <div className="flex items-center gap-2">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                            <span>Active connection — credentials stored securely</span>
                          </div>
                          {isMultiRoleTool(connector.id) && (
                            <div className="mt-2 text-[var(--muted)]">
                              This tool serves multiple roles in your pipeline. Roles are auto-detected based on your workspace configuration.
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>}
            </div>
          );
        })}

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
        onClose={() => setIntegrationModal(null)}
        onSuccess={fetchIntegrations}
      />
    </div>
  );
}
