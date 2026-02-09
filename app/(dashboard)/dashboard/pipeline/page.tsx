'use client';

/**
 * Pipeline Canvas Page
 * 
 * Visual builder for mapping your complete data pipeline
 * n8n / Make.com style - add nodes, connect them, then configure
 * Features: Auto-layout, keyboard shortcuts, templates
 */

import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { toast } from 'sonner';
import PipelineCanvas from '@/components/pipeline/PipelineCanvas';
import NodeSidebar from '@/components/pipeline/NodeSidebar';
import { IntegrationConfigModal } from '@/components/pipeline/IntegrationConfigModal';
import {
  PipelineStack,
  PipelineNode,
  PipelineEdge,
  PipelineLayer,
  getToolById,
  INTEGRATIONS,
  INTEGRATION_COLORS,
  INTEGRATION_LABELS,
  IntegrationType,
  IntegrationDefinition,
} from '@/components/pipeline/types';
import { BookTemplate, ChevronDown, Bell, Ticket, Eye, Plus, Check } from 'lucide-react';

// Pipeline templates for quick start
const PIPELINE_TEMPLATES = [
  {
    id: 'modern-stack',
    name: 'Modern Data Stack',
    description: 'Fivetran → dbt Cloud → Snowflake → Looker',
    nodes: [
      { id: 'tpl-1', name: 'Fivetran', layer: 'INGESTION' as PipelineLayer, toolType: 'fivetran' },
      { id: 'tpl-2', name: 'dbt Cloud', layer: 'TRANSFORMATION' as PipelineLayer, toolType: 'dbt_cloud' },
      { id: 'tpl-3', name: 'Snowflake', layer: 'WAREHOUSE' as PipelineLayer, toolType: 'snowflake' },
      { id: 'tpl-4', name: 'Looker', layer: 'REPORTING' as PipelineLayer, toolType: 'looker' },
    ],
    edges: [
      { id: 'tpl-e1', sourceId: 'tpl-1', targetId: 'tpl-2' },
      { id: 'tpl-e2', sourceId: 'tpl-2', targetId: 'tpl-3' },
      { id: 'tpl-e3', sourceId: 'tpl-3', targetId: 'tpl-4' },
    ],
  },
  {
    id: 'azure-stack',
    name: 'Azure Data Stack',
    description: 'Airbyte → dbt Core → Azure SQL → Power BI',
    nodes: [
      { id: 'tpl-1', name: 'Airbyte', layer: 'INGESTION' as PipelineLayer, toolType: 'airbyte' },
      { id: 'tpl-2', name: 'dbt Core', layer: 'TRANSFORMATION' as PipelineLayer, toolType: 'dbt_core' },
      { id: 'tpl-3', name: 'Azure SQL', layer: 'WAREHOUSE' as PipelineLayer, toolType: 'azure_sql' },
      { id: 'tpl-4', name: 'Power BI', layer: 'REPORTING' as PipelineLayer, toolType: 'powerbi' },
    ],
    edges: [
      { id: 'tpl-e1', sourceId: 'tpl-1', targetId: 'tpl-2' },
      { id: 'tpl-e2', sourceId: 'tpl-2', targetId: 'tpl-3' },
      { id: 'tpl-e3', sourceId: 'tpl-3', targetId: 'tpl-4' },
    ],
  },
  {
    id: 'gcp-stack',
    name: 'GCP Data Stack',
    description: 'Stitch → dbt Cloud → BigQuery → Tableau',
    nodes: [
      { id: 'tpl-1', name: 'Stitch', layer: 'INGESTION' as PipelineLayer, toolType: 'stitch' },
      { id: 'tpl-2', name: 'dbt Cloud', layer: 'TRANSFORMATION' as PipelineLayer, toolType: 'dbt_cloud' },
      { id: 'tpl-3', name: 'BigQuery', layer: 'WAREHOUSE' as PipelineLayer, toolType: 'bigquery' },
      { id: 'tpl-4', name: 'Tableau', layer: 'REPORTING' as PipelineLayer, toolType: 'tableau' },
    ],
    edges: [
      { id: 'tpl-e1', sourceId: 'tpl-1', targetId: 'tpl-2' },
      { id: 'tpl-e2', sourceId: 'tpl-2', targetId: 'tpl-3' },
      { id: 'tpl-e3', sourceId: 'tpl-3', targetId: 'tpl-4' },
    ],
  },
  {
    id: 'warehouse-only',
    name: 'Warehouse + BI',
    description: 'Start with just warehouse and reporting',
    nodes: [
      { id: 'tpl-1', name: 'Snowflake', layer: 'WAREHOUSE' as PipelineLayer, toolType: 'snowflake' },
      { id: 'tpl-2', name: 'Metabase', layer: 'REPORTING' as PipelineLayer, toolType: 'metabase' },
    ],
    edges: [
      { id: 'tpl-e1', sourceId: 'tpl-1', targetId: 'tpl-2' },
    ],
  },
];

// Grid positions for each layer (X positions)
const LAYER_X_POSITIONS: Record<PipelineLayer, number> = {
  INGESTION: 100,
  TRANSFORMATION: 400,
  WAREHOUSE: 700,
  REPORTING: 1000,
  VERSION_CONTROL: 250,  // Between Ingestion and Transformation (connects to dbt)
};

// Category icons for integrations
const CATEGORY_ICONS: Record<IntegrationType, React.ReactNode> = {
  NOTIFICATIONS: <Bell className="w-4 h-4" />,
  TICKETING: <Ticket className="w-4 h-4" />,
  OBSERVABILITY: <Eye className="w-4 h-4" />,
};

// Track how many nodes are in each layer for Y positioning
function getNextYPosition(nodes: PipelineNode[], layer: PipelineLayer): number {
  const layerNodes = nodes.filter(n => n.layer === layer);
  const baseY = 80;
  const spacing = 200;
  return baseY + (layerNodes.length * spacing);
}

export default function PipelinePage() {
  const [stack, setStack] = useState<PipelineStack>({
    id: 'new',
    name: 'My Data Pipeline',
    description: '',
    status: 'DRAFT',
    nodes: [],
    edges: [],
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [configModal, setConfigModal] = useState<{ integration: IntegrationDefinition } | null>(null);
  const [connectedIntegrationIds, setConnectedIntegrationIds] = useState<string[]>([]);
  const searchParams = useSearchParams();

  // Fetch connected integrations (for the integration cards)
  const fetchConnectedIntegrations = useCallback(async () => {
    try {
      const res = await fetch('/api/integrations');
      if (res.ok) {
        const data = await res.json();
        const connected = data.integrations
          ?.filter((i: any) => i.status === 'ACTIVE')
          .map((i: any) => i.type.toLowerCase()) || [];
        setConnectedIntegrationIds(connected);
      }
    } catch (error) {
      console.error('Failed to fetch integrations:', error);
    }
  }, []);

  // Handle OAuth callback URL parameters
  useEffect(() => {
    const success = searchParams.get('success');
    const error = searchParams.get('error');

    if (success === 'github') {
      toast.success('GitHub connected successfully!');
      fetchConnectedIntegrations();

      // Update any GitHub nodes on the canvas to mark as connected and auto-save
      setStack(prev => {
        const updatedStack = {
          ...prev,
          nodes: prev.nodes.map(node => {
            if (node.toolType === 'github') {
              return {
                ...node,
                status: 'CONNECTED' as const,
                config: { ...node.config, _oauth_linked: true },
              };
            }
            return node;
          }),
        };

        // Auto-save if there are GitHub nodes
        if (prev.nodes.some(n => n.toolType === 'github') && prev.id && prev.id !== 'new') {
          fetch('/api/pipeline', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updatedStack),
          }).catch(e => console.error('Failed to save GitHub node status:', e));
        }

        return updatedStack;
      });

      // Clean up URL
      window.history.replaceState({}, '', '/dashboard/pipeline');
    } else if (error) {
      const errorMessages: Record<string, string> = {
        invalid_state: 'GitHub authentication failed: Invalid state',
        no_code: 'GitHub authentication failed: No authorization code',
        callback_failed: 'GitHub authentication failed: Callback error',
      };
      toast.error(errorMessages[error] || `GitHub authentication failed: ${error}`);
      window.history.replaceState({}, '', '/dashboard/pipeline');
    }
  }, [searchParams, fetchConnectedIntegrations]);

  // Load existing pipeline stack and integrations in parallel
  useEffect(() => {
    const loadData = async () => {
      try {
        // Fetch pipeline and integrations in parallel
        const [pipelineRes] = await Promise.all([
          fetch('/api/pipeline'),
          fetchConnectedIntegrations(),
        ]);

        if (pipelineRes.ok) {
          const data = await pipelineRes.json();
          if (data.stack) {
            setStack(data.stack);
          }
        }
      } catch (error) {
        console.error('Failed to load pipeline:', error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [fetchConnectedIntegrations]);

  // Save pipeline changes
  const savePipeline = useCallback(async () => {
    setSaving(true);
    try {
      const res = await fetch('/api/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(stack),
      });
      
      if (res.ok) {
        const data = await res.json();
        setStack(prev => ({ ...prev, id: data.id }));
        toast.success('Pipeline saved successfully');
      } else {
        throw new Error('Failed to save');
      }
    } catch (error) {
      toast.error('Failed to save pipeline');
    } finally {
      setSaving(false);
    }
  }, [stack]);

  // Handle node changes from canvas
  const onNodesChange = useCallback((nodes: PipelineNode[]) => {
    setStack(prev => ({ ...prev, nodes }));
  }, []);

  // Handle edge changes from canvas
  const onEdgesChange = useCallback((edges: PipelineEdge[]) => {
    setStack(prev => ({ ...prev, edges }));
  }, []);

  // Handle adding a new node from sidebar - NO MODAL, just add to canvas
  const onAddNode = useCallback((toolId: string, layer: string) => {
    const layerKey = layer as PipelineLayer;
    const tool = getToolById(toolId);
    
    // Calculate position in grid
    const xPos = LAYER_X_POSITIONS[layerKey];
    const yPos = getNextYPosition(stack.nodes, layerKey);
    
    const newNode: PipelineNode = {
      id: `node-${Date.now()}`,
      name: tool?.name || toolId,
      layer: layerKey,
      toolType: toolId,
      positionX: xPos,
      positionY: yPos,
      status: 'PENDING',
      config: null,
      healthScore: null,
      findingsCount: 0,
      criticalCount: 0,
      highCount: 0,
    };

    // Add node to canvas immediately
    setStack(prev => ({
      ...prev,
      nodes: [...prev.nodes, newNode],
    }));
    
    toast.success(`Added ${tool?.name || toolId} to canvas`);
  }, [stack.nodes]);

  // Scan the entire pipeline
  const scanPipeline = useCallback(async () => {
    if (stack.nodes.length === 0) {
      toast.error('Add some nodes to your pipeline first');
      return;
    }

    const configuredNodes = stack.nodes.filter(n => n.config !== null);
    if (configuredNodes.length === 0) {
      toast.error('Configure at least one node before scanning');
      return;
    }

    toast.info('Starting pipeline scan...');
    
    try {
      const res = await fetch('/api/pipeline/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stackId: stack.id }),
      });
      
      if (res.ok) {
        toast.success('Pipeline scan started');
      } else {
        throw new Error('Failed to start scan');
      }
    } catch (error) {
      toast.error('Failed to start pipeline scan');
    }
  }, [stack]);

  // Apply a template
  const applyTemplate = useCallback((templateId: string) => {
    const template = PIPELINE_TEMPLATES.find(t => t.id === templateId);
    if (!template) return;

    // Generate new IDs and positions
    const nodeIdMap = new Map<string, string>();
    const newNodes: PipelineNode[] = template.nodes.map((node, idx) => {
      const newId = `node-${Date.now()}-${idx}`;
      nodeIdMap.set(node.id, newId);
      
      const xPos = LAYER_X_POSITIONS[node.layer];
      const yPos = 80 + (idx % 2) * 180; // Stagger vertically
      
      return {
        id: newId,
        name: node.name,
        layer: node.layer,
        toolType: node.toolType,
        positionX: xPos,
        positionY: yPos,
        status: 'PENDING' as const,
        config: null,
        healthScore: null,
        findingsCount: 0,
        criticalCount: 0,
        highCount: 0,
      };
    });

    const newEdges: PipelineEdge[] = template.edges.map((edge, idx) => ({
      id: `edge-${Date.now()}-${idx}`,
      sourceId: nodeIdMap.get(edge.sourceId) || edge.sourceId,
      targetId: nodeIdMap.get(edge.targetId) || edge.targetId,
    }));

    setStack(prev => ({
      ...prev,
      nodes: [...prev.nodes, ...newNodes],
      edges: [...prev.edges, ...newEdges],
    }));

    setShowTemplates(false);
    toast.success(`Applied "${template.name}" template`);
  }, []);

  // These hooks must be before any conditional returns
  const openConfigModal = useCallback((integration: IntegrationDefinition) => {
    setConfigModal({ integration });
  }, []);

  const handleIntegrationSuccess = useCallback(() => {
    fetchConnectedIntegrations();
  }, [fetchConnectedIntegrations]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[600px]">
        <div className="flex flex-col items-center gap-4">
          <div className="relative w-16 h-16">
            <div className="absolute inset-0 rounded-full border-2 border-[var(--accent)]/20"></div>
            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-[var(--accent)] animate-spin"></div>
          </div>
          <p className="text-sm text-[var(--muted)]">Loading pipeline...</p>
        </div>
      </div>
    );
  }

  const unconfiguredCount = stack.nodes.filter(n => !n.config).length;

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 px-1">
        <div>
          <h1 className="text-2xl font-bold bg-gradient-to-r from-white to-white/60 bg-clip-text text-transparent">
            Pipeline Canvas
          </h1>
          <p className="text-sm text-[var(--muted)] mt-1">
            Build your data flow • {stack.nodes.length} nodes
            {unconfiguredCount > 0 && (
              <span className="ml-2 text-amber-400">• {unconfiguredCount} need configuration</span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Templates Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowTemplates(!showTemplates)}
              className="btn btn-secondary flex items-center gap-2"
            >
              <BookTemplate className="w-4 h-4" />
              Templates
              <ChevronDown className={`w-4 h-4 transition-transform ${showTemplates ? 'rotate-180' : ''}`} />
            </button>

            {showTemplates && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowTemplates(false)} />
                <div className="absolute right-0 top-full mt-2 w-80 rounded-xl bg-[#1a1a24] border border-[rgba(255,255,255,0.1)] shadow-xl z-20 overflow-hidden">
                  <div className="p-3 border-b border-[rgba(255,255,255,0.06)]">
                    <h4 className="text-sm font-medium">Quick Start Templates</h4>
                    <p className="text-xs text-[var(--muted)] mt-1">Choose a template to get started</p>
                  </div>
                  <div className="max-h-[300px] overflow-y-auto">
                    {PIPELINE_TEMPLATES.map(template => (
                      <button
                        key={template.id}
                        onClick={() => applyTemplate(template.id)}
                        className="w-full p-3 text-left hover:bg-[rgba(255,255,255,0.03)] transition-colors border-b border-[rgba(255,255,255,0.04)] last:border-b-0"
                      >
                        <div className="font-medium text-sm">{template.name}</div>
                        <div className="text-xs text-[var(--muted)] mt-1">{template.description}</div>
                        <div className="text-xs text-[var(--accent-2)] mt-1.5">{template.nodes.length} nodes</div>
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>

          <button
            onClick={savePipeline}
            disabled={saving}
            className="btn btn-secondary"
          >
            {saving ? (
              <>
                <svg className="w-4 h-4 mr-2 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
                </svg>
                Saving...
              </>
            ) : (
              <>
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                </svg>
                Save Pipeline
              </>
            )}
          </button>

          <button
            onClick={scanPipeline}
            disabled={stack.nodes.length === 0}
            className="btn btn-primary"
          >
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      {/* Main Content - Pipeline Canvas */}
      <div className="flex gap-4 h-[600px]">
        {/* Sidebar */}
        <NodeSidebar onAddNode={onAddNode} />

        {/* Canvas */}
        <div className="flex-1 dashboard-card overflow-hidden">
          <PipelineCanvas
            nodes={stack.nodes}
            edges={stack.edges}
            stackId={stack.id}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onSave={savePipeline}
          />
        </div>
      </div>

      {/* Integrations Section */}
      <div className="mt-8 pb-8">
        <div className="mb-4">
          <h2 className="text-xl font-semibold">Integrations</h2>
          <p className="text-sm text-[var(--muted)] mt-1">
            Connect notifications, ticketing, and observability tools
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {(Object.keys(INTEGRATIONS) as IntegrationType[]).map((category) => (
            <IntegrationCategory
              key={category}
              category={category}
              integrations={INTEGRATIONS[category]}
              connectedIds={connectedIntegrationIds}
              onConfigureIntegration={openConfigModal}
            />
          ))}
        </div>
      </div>

      {/* Integration Config Modal */}
      <IntegrationConfigModal
        integration={configModal?.integration || null}
        isOpen={configModal !== null}
        onClose={() => setConfigModal(null)}
        onSuccess={handleIntegrationSuccess}
      />
    </div>
  );
}

// Integration Category Component
function IntegrationCategory({
  category,
  integrations,
  connectedIds,
  onConfigureIntegration,
}: {
  category: IntegrationType;
  integrations: IntegrationDefinition[];
  connectedIds: string[];
  onConfigureIntegration: (integration: IntegrationDefinition) => void;
}) {

  return (
    <div
      className="dashboard-card p-4"
      style={{
        borderTop: `3px solid ${INTEGRATION_COLORS[category]}`,
      }}
    >
      <div className="flex items-center gap-2 mb-4">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{
            backgroundColor: `${INTEGRATION_COLORS[category]}20`,
            color: INTEGRATION_COLORS[category],
          }}
        >
          {CATEGORY_ICONS[category]}
        </div>
        <div>
          <h3 className="font-medium">{INTEGRATION_LABELS[category]}</h3>
          <p className="text-xs text-[var(--muted)]">{integrations.length} available</p>
        </div>
      </div>

      <div className="space-y-2">
        {integrations.map((integration) => {
          const isConnected = connectedIds.includes(integration.id);
          return (
            <div
              key={integration.id}
              className="flex items-center justify-between p-3 rounded-lg bg-[rgba(255,255,255,0.02)] hover:bg-[rgba(255,255,255,0.04)] transition-colors cursor-pointer"
              onClick={() => onConfigureIntegration(integration)}
            >
              <div className="flex items-center gap-3">
                <IntegrationIcon id={integration.id} />
                <div>
                  <div className="text-sm font-medium">{integration.name}</div>
                  <div className="text-xs text-[var(--muted)]">{integration.description}</div>
                </div>
              </div>
              {isConnected ? (
                <div className="flex items-center gap-1 text-xs text-emerald-400">
                  <Check className="w-3 h-3" />
                  Connected
                </div>
              ) : (
                <button
                  className="p-1.5 rounded-lg hover:bg-[rgba(255,255,255,0.06)] transition-colors text-[var(--muted)] hover:text-white"
                  onClick={(e) => {
                    e.stopPropagation();
                    onConfigureIntegration(integration);
                  }}
                >
                  <Plus className="w-4 h-4" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Integration Icon Component
function IntegrationIcon({ id }: { id: string }) {
  const icons: Record<string, { icon: string; color: string }> = {
    slack: { icon: 'S', color: '#4A154B' },
    teams: { icon: 'T', color: '#6264A7' },
    pagerduty: { icon: 'PD', color: '#06AC38' },
    opsgenie: { icon: 'OG', color: '#2684FF' },
    jira: { icon: 'J', color: '#0052CC' },
    linear: { icon: 'L', color: '#5E6AD2' },
    asana: { icon: 'A', color: '#F06A6A' },
    github_issues: { icon: 'GH', color: '#24292e' },
    monte_carlo: { icon: 'MC', color: '#00D4AA' },
    bigeye: { icon: 'BE', color: '#FF6B35' },
    soda: { icon: 'SD', color: '#00C7B7' },
    elementary: { icon: 'EL', color: '#FF914D' },
  };

  const config = icons[id] || { icon: id.slice(0, 2).toUpperCase(), color: '#6B7280' };

  return (
    <div
      className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0"
      style={{ backgroundColor: config.color }}
    >
      {config.icon}
    </div>
  );
}
