'use client';

import React, { useState, useEffect, useCallback, useMemo, useRef, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { cachedFetch, invalidateCache } from '@/lib/fetch-cache';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  Position,
  MarkerType,
  BackgroundVariant,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { usePipeline } from '@/contexts/PipelineContext';
import { layoutGraph, layoutRenderedViewOrphans, ORPHAN_GROUP_ID } from '@/components/lineage/layoutGraph';
import { LAYER_COLORS, type PipelineLayer } from '@/components/pipeline/types';
import { unifiedNodeTypes } from '@/components/lineage/UnifiedNodes';
import { DataAssetDetailPanel } from '@/components/lineage/DataAssetDetailPanel';
import { EdgeDetailPanel } from '@/components/lineage/EdgeDetailPanel';
import {
  type UnifiedLineageNode,
  type UnifiedLineageEdge,
  type UnifiedLineageResponse,
  type LineageFilterState,
  type UnifiedNodeCategory,
  type EngineCoverageStats,
  type ControlPlaneOverviewResponse,
  type ControlPlaneNode as CPNode,
  type ControlPlaneEdge as CPEdge,
  type RenderedViewResponse,
  type ViewNode,
  type ViewEdge,
  type LaneMeta,
  type OrchestratorOverlay,
  getDefaultFilterState,
  isToolCategory,
  isDataAssetCategory,
  nodePassesFilter,
  edgePassesFilter,
  getConfidenceColor,
  CATEGORY_VISUALS,
} from '@/components/lineage/types';
import { InspectorPanel } from '@/components/lineage/pipeline-overview/InspectorPanel';
import { SEMANTIC_EDGE_STYLES, type InspectorTarget } from '@/components/lineage/pipeline-overview/types';
import { SLAEditorPanel, type ApplyScope } from '@/components/lineage/SLAEditorPanel';
import { SLAModeToolbar } from '@/components/lineage/SLAModeToolbar';
import type { EffectiveSLAPolicy, SLAAssignRequest, SLAStatus } from '@/types/sla';
import { categoryToSLADomain, DOMAIN_SLA_SECTIONS } from '@/types/sla';
import { evaluateNodeCompliance } from '@/lib/compliance/evaluate';
import type { ComplianceBadgeStatus } from '@/components/lineage/ComplianceBadge';
import { CreateTaskModal } from '@/components/schedule/CreateTaskModal';
import { MultiMonitorModal } from '@/components/schedule/MultiMonitorModal';
import type { NodeMeta } from '@/components/schedule/NodeSelectionSurface';
import type { AssetPrefill } from '@/types/monitor-catalog';
import { SlaProfileModal } from '@/components/lineage/SlaProfileModal';

// Compute compliance status for a node given its resolved SLA policy
function computeNodeCompliance(
  sla: EffectiveSLAPolicy | undefined,
  category: string,
): ComplianceBadgeStatus {
  if (!sla || sla.status === 'none') return 'none';

  const domain = categoryToSLADomain(category);
  if (!domain) return 'none';

  const sections = DOMAIN_SLA_SECTIONS[domain] || [];
  const slaValues: Record<string, unknown> = {};
  for (const section of sections) {
    const config = (sla as any)[section] as Record<string, unknown> | undefined;
    if (!config) continue;
    if ('enabled' in config && config.enabled === false) continue;
    for (const [k, v] of Object.entries(config)) {
      if (k === 'enabled' || v == null) continue;
      slaValues[`${section}.${k}`] = v;
    }
  }

  if (Object.keys(slaValues).length === 0) return 'none';

  const compliance = evaluateNodeCompliance(slaValues, null, null);
  if (compliance.fields.length === 0) return 'none';
  if (compliance.overallStatus === 'unknown') return 'missing_sla';
  return compliance.overallStatus as ComplianceBadgeStatus;
}

// Map a ViewNode's canonical type + metadata to a UnifiedNodeCategory for rendering
function _viewNodeToCategory(vn: ViewNode): UnifiedNodeCategory {
  // Ingestion-domain datasets should use 'source' category (green)
  if (vn.platformDomain === 'ingestion' &&
      (vn.originalType === 'table' || vn.originalType === 'source')) {
    return 'source';
  }

  // Use originalType when it maps directly to a known category
  const ot = vn.originalType as UnifiedNodeCategory;
  const knownCategories: UnifiedNodeCategory[] = [
    'table', 'view', 'source', 'model', 'dag', 'task', 'workflow',
    'connector', 'workbook', 'dataset', 'question', 'notebook',
    'file', 'test', 'dashboard', 'report',
  ];
  if (knownCategories.includes(ot)) return ot;

  // Unknown platform flagged as needs_mapping — show as uncategorized
  if (vn.needsMapping) return 'uncategorized';

  // Fall back on canonical type → category mapping
  switch (vn.canonicalType) {
    case 'dataset': return 'table';
    case 'semantic': return 'dashboard';
    case 'job': return 'workflow';
    case 'service': return vn.platformDomain === 'warehouse' ? 'warehouse'
      : vn.platformDomain === 'transform' ? 'transformation'
      : vn.platformDomain === 'bi' ? 'reporting'
      : vn.platformDomain === 'ingestion' ? 'ingestion'
      : 'uncategorized';
    case 'system': return 'infrastructure';
    default: return 'table';
  }
}

// Get edge style based on type and plane
function getEdgeStyle(edge: UnifiedLineageEdge, sourceNode?: UnifiedLineageNode) {
  const edgeType = edge.edgeType;

  // Cross-plane edges (task ↔ table): dashed, orange-tinted
  if (edge.plane === 'cross') {
    return {
      stroke: '#F9731680',
      strokeWidth: 2,
      strokeDasharray: '6,4',
      animated: false,
    };
  }

  // Control-plane edges (DAG → task, task → task)
  if (edge.plane === 'control') {
    const layerColor = LAYER_COLORS.ORCHESTRATION;
    return {
      stroke: layerColor,
      strokeWidth: edgeType === 'depends_on' ? 3 : 2,
      animated: edgeType === 'depends_on',
    };
  }

  // Tool-to-tool pipeline edges
  if (edgeType === 'pipeline_flow') {
    const layerColor = sourceNode ? LAYER_COLORS[sourceNode.layer] : '#6366F1';
    return {
      stroke: layerColor,
      strokeWidth: 3,
      animated: true,
    };
  }

  // Synthetic edges (tool-to-table or table-to-tool)
  if (edgeType === 'contains' || edgeType === 'produces' || edgeType === 'reads_from') {
    const layerColor = sourceNode ? LAYER_COLORS[sourceNode.layer] : '#6366F1';
    return {
      stroke: `${layerColor}80`,
      strokeWidth: 2,
      strokeDasharray: '5,5',
      animated: false,
    };
  }

  // Table-to-table lineage edges — color by confidence when available
  const confidenceColor = getConfidenceColor(edge.confidence);
  return {
    stroke: confidenceColor,
    strokeWidth: 2,
    animated: true,
  };
}

// ---------------------------------------------------------------------------
// Lane Overview Canvas — extracted to components/lineage/pipeline-overview/
// ---------------------------------------------------------------------------

function LineagePageInner() {
  const { selectedPipelineId: stackId, loading: pipelineLoading } = usePipeline();
  const searchParams = useSearchParams();
  const router = useRouter();
  const filterIntegrationId = searchParams.get('integrationId');
  const [lineageData, setLineageData] = useState<UnifiedLineageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<UnifiedLineageNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<UnifiedLineageEdge | null>(null);
  const [filters, setFilters] = useState<LineageFilterState>(getDefaultFilterState());
  const [activeTab, setActiveTab] = useState<'data' | 'control-plane'>('data');
  const [controlPlaneData, setControlPlaneData] = useState<ControlPlaneOverviewResponse | null>(null);
  const [controlPlaneLoading, setControlPlaneLoading] = useState(false);
  // Rendered view data (from ViewBuilder backend — pre-positioned, canonical types)
  const [renderedView, setRenderedView] = useState<RenderedViewResponse | null>(null);
  const [renderedOverview, setRenderedOverview] = useState<RenderedViewResponse | null>(null);
  // Lane-based pipeline overview
  const [laneOverview, setLaneOverview] = useState<RenderedViewResponse | null>(null);
  // laneOverview is now populated by fetchControlPlane (lane view is the primary Pipeline Overview)
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  // Data SLA settings (affect SLA editor behavior)
  const [dataSLAsEnabled, setDataSLAsEnabled] = useState(false);
  const [slaAllowOverrides, setSlaAllowOverrides] = useState(false);

  // Pipeline Overview inspector state
  const [pipelineInspectorTarget, setPipelineInspectorTarget] = useState<InspectorTarget>(null);

  // Monitor creation modal states — three paths
  const [multiMonitorModalOpen, setMultiMonitorModalOpen] = useState(false);
  const [multiMonitorPreselect, setMultiMonitorPreselect] = useState<string[]>([]);
  const [multiMonitorPreMeta, setMultiMonitorPreMeta] = useState<NodeMeta[] | undefined>(undefined);
  const [promptModalOpen, setPromptModalOpen] = useState(false);

  const handleCreateSingleMonitor = useCallback((prefill: AssetPrefill) => {
    // Route through MultiMonitorModal with the node pre-selected + metadata
    setMultiMonitorPreselect([prefill.nodeId]);
    setMultiMonitorPreMeta([{
      id: prefill.nodeId,
      name: prefill.name,
      fqn: prefill.fqn,
      platform: prefill.platform || '',
      domain: prefill.domain || 'warehouse',
      subNodeIds: prefill.subNodeIds,
      childItems: prefill.childItems,
    }]);
    setMultiMonitorModalOpen(true);
  }, []);

  const handleCreateMultiMonitor = useCallback((preselectedNodeIds: string[]) => {
    setMultiMonitorPreselect(preselectedNodeIds);
    setMultiMonitorPreMeta(undefined); // No pre-built metadata for multi-select
    setMultiMonitorModalOpen(true);
  }, []);

  // Fetch data SLA settings for this pipeline
  useEffect(() => {
    if (!stackId) return;
    fetch(`/api/pipeline/${stackId}/data-slas`)
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data) {
          setDataSLAsEnabled(data.dataSLAsEnabled ?? false);
          setSlaAllowOverrides(data.slaAllowOverrides ?? false);
        }
      })
      .catch(() => {});
  }, [stackId]);

  // Normal-mode multi-select (Shift+Click outside of SLA editor mode)
  const [multiSelectedNodeIds, setMultiSelectedNodeIds] = useState<Set<string>>(new Set());

  // Policy mode state (isolated from normal lineage state)
  const [slaMode, setSlaMode] = useState(false);
  const [slaSelectedNodeIds, setSlaSelectedNodeIds] = useState<Set<string>>(new Set());
  const [nodeSLAs, setNodeSLAs] = useState<Map<string, EffectiveSLAPolicy>>(new Map());
  const [policySaving, setPolicySaving] = useState(false);
  const [slaDiscoveryDefaults, setSlaDiscoveryDefaults] = useState<Record<string, any> | null>(null);

  // SLA profile modal state
  const [selectedSlaNodeId, setSelectedSlaNodeId] = useState<string | null>(null);

  // Pipeline SLA mode state (control-plane tab)

  // Exit policy mode on Escape
  useEffect(() => {
    if (!slaMode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSlaMode(false);
        setSlaSelectedNodeIds(new Set());
        setSlaDiscoveryDefaults(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [slaMode]);

  // Load existing policy assignments from DB on page load
  useEffect(() => {
    if (!lineageData?.nodes?.length) return;
    let cancelled = false;

    (async () => {
      try {
        const nodesPayload = lineageData.nodes.map((n) => ({
          fqn: n.fullName || n.name,
          domain: n.layer?.toLowerCase() || 'warehouse',
          criticality: n.criticality?.toLowerCase() || 'medium',
        }));
        const res = await fetch('/api/schedule/policies/resolve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nodes: nodesPayload, stackId }),
        });
        if (res.ok && !cancelled) {
          const data = await res.json();
          const policies = data.policies || {};
          const map = new Map<string, EffectiveSLAPolicy>();
          for (const [fqn, pol] of Object.entries(policies)) {
            if ((pol as any).status !== 'none') {
              map.set(fqn, pol as EffectiveSLAPolicy);
            }
          }
          if (map.size > 0) setNodeSLAs(map);
        }
      } catch {
        // Non-critical — policies will load next time
      }
    })();

    return () => { cancelled = true; };
  }, [lineageData?.nodes]);

  // Re-fetch SLA policies (used after pipeline SLA edits)
  const refreshSLAs = async () => {
    if (!lineageData?.nodes?.length) return;
    try {
      const nodesPayload = lineageData.nodes.map((n) => ({
        fqn: n.fullName || n.name,
        domain: n.layer?.toLowerCase() || 'warehouse',
        criticality: n.criticality?.toLowerCase() || 'medium',
      }));
      const res = await fetch('/api/schedule/policies/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nodes: nodesPayload, stackId }),
      });
      if (res.ok) {
        const data = await res.json();
        const policies = data.policies || {};
        const map = new Map<string, EffectiveSLAPolicy>();
        for (const [fqn, pol] of Object.entries(policies)) {
          if ((pol as any).status !== 'none') {
            map.set(fqn, pol as EffectiveSLAPolicy);
          }
        }
        setNodeSLAs(map);
      }
    } catch {
      // Non-critical
    }
  };

  // LLM extraction state
  const [llmExtracting, setLlmExtracting] = useState(false);
  const [llmProgress, setLlmProgress] = useState<Array<{type: string; message: string; ts?: number}>>([]);
  const [llmNodeCount, setLlmNodeCount] = useState(0);
  const [llmEdgeCount, setLlmEdgeCount] = useState(0);

  // Track fetch version to ignore stale responses on rapid tab switches
  const fetchVersionRef = useRef(0);

  // Fetch unified lineage data — tries rendered view first, falls back to unified
  const fetchLineage = useCallback(async () => {
    if (!stackId) return;

    const thisVersion = ++fetchVersionRef.current;
    setLoading(true);
    setError(null);

    try {
      // Try rendered data-plane view first (pre-positioned, canonical types)
      let usedRenderedView = false;
      try {
        const viewRes = await cachedFetch(`/api/pipeline/${stackId}/lineage/engine?action=view-data-plane`);
        if (fetchVersionRef.current !== thisVersion) return;
        if (viewRes.ok) {
          const viewData: RenderedViewResponse = await viewRes.json();
          if (fetchVersionRef.current !== thisVersion) return;
          if (viewData.nodes && viewData.nodes.length > 0) {
            console.log('[Lineage] Data Lineage: using data-plane view');
            setRenderedView(viewData);
            usedRenderedView = true;
          }
        }
      } catch {
        // Non-fatal — fall through to unified endpoint
      }

      // Always fetch unified data (for detail panels, filters, and fallback)
      const res = await cachedFetch(`/api/pipeline/${stackId}/lineage/unified?plane=data`);
      if (fetchVersionRef.current !== thisVersion) return;

      if (res.ok) {
        const data: UnifiedLineageResponse = await res.json();
        if (fetchVersionRef.current !== thisVersion) return;

        setLineageData(data);

        // Update filter with available layers
        if (data.availableLayers.length > 0) {
          setFilters((prev) => ({
            ...prev,
            layers: new Set(data.availableLayers),
          }));
        }
      } else {
        // If we got rendered view, this isn't fatal
        if (!usedRenderedView) {
          const errorData = await res.json().catch(() => ({}));
          setError(errorData.error || 'Failed to fetch lineage');
        }
      }
    } catch (err) {
      if (fetchVersionRef.current !== thisVersion) return;
      setError('Failed to connect to server');
    } finally {
      if (fetchVersionRef.current === thisVersion) {
        setLoading(false);
      }
    }
  }, [stackId]);

  // Fetch pipeline overview — tries lane-based view first (swimlane layout),
  // then falls back to tool-sequence pipeline-overview, then legacy merge.
  const fetchControlPlane = useCallback(async () => {
    if (!stackId) return;
    setControlPlaneLoading(true);
    try {
      // Try lane-based pipeline overview first (swimlane: n8n → BQ raw → dbt → analytics)
      try {
        const laneRes = await cachedFetch(`/api/pipeline/${stackId}/lineage/engine?action=view-lane-pipeline-overview`);
        if (laneRes.ok) {
          const laneData: RenderedViewResponse = await laneRes.json();
          if (laneData.nodes && laneData.nodes.length > 0) {
            console.log('[Lineage] Pipeline Overview: using lane-pipeline-overview view');
            setLaneOverview(laneData);
            setControlPlaneLoading(false);
            return;
          }
        }
      } catch {
        // Non-fatal — fall through
      }

      // Try rendered pipeline overview (tool clusters)
      try {
        const viewRes = await cachedFetch(`/api/pipeline/${stackId}/lineage/engine?action=view-pipeline-overview`);
        if (viewRes.ok) {
          const viewData: RenderedViewResponse = await viewRes.json();
          if (viewData.nodes && viewData.nodes.length > 0) {
            console.log('[Lineage] Pipeline Overview: using pipeline-overview view (fallback)');
            setRenderedOverview(viewData);
            // Also set controlPlaneData for compatibility with side panels
            setControlPlaneData({
              nodes: viewData.nodes.map((n: ViewNode) => ({
                id: n.id,
                name: n.name,
                toolType: n.platform || n.originalType,
                platformDomain: n.platformDomain,
                integrationId: n.metadata?.integrationId,
                assetCount: n.metadata?.assetCount || 0,
                healthSummary: n.metadata?.healthSummary || { healthy: 0, degraded: 0, failing: 0, unknown: 0 },
                position: 0,
              })),
              edges: viewData.edges.map((e: ViewEdge) => ({
                id: e.id,
                source: e.sourceId,
                target: e.targetId,
                dataFlowCount: e.metadata?.dataFlowCount ?? e.evidenceCount ?? 0,
                sampleAssets: [],
              })),
              stats: {
                tool_count: viewData.nodes.length,
                flow_count: viewData.edges.length,
              },
            });
            setControlPlaneLoading(false);
            return;
          }
        }
      } catch {
        // Non-fatal — fall through to legacy path
      }

      // Fetch engine control plane data and pipeline stack in parallel
      const [engineRes, stackRes] = await Promise.all([
        cachedFetch(`/api/pipeline/${stackId}/lineage/engine?action=control-plane-overview`).catch(() => null),
        cachedFetch(`/api/pipeline/${stackId}/lineage/unified?plane=data`).catch(() => null),
      ]);

      const engineData: ControlPlaneOverviewResponse | null = engineRes?.ok
        ? await engineRes.json()
        : null;

      // Build a map of engine tool nodes by toolType for merging
      const engineNodesByType = new Map<string, CPNode>();
      if (engineData?.nodes) {
        for (const n of engineData.nodes) {
          engineNodesByType.set(n.toolType, n);
        }
      }

      // Get pipeline stack tool nodes from the unified response
      const stackData: UnifiedLineageResponse | null = stackRes?.ok
        ? await stackRes.json()
        : null;

      const pipelineToolNodes = (stackData?.nodes || []).filter(
        (n) => isToolCategory(n.category)
      );

      // Map pipeline layer to control plane domain
      const layerToDomain: Record<string, string> = {
        INGESTION: 'ingestion',
        TRANSFORMATION: 'transform',
        WAREHOUSE: 'warehouse',
        REPORTING: 'bi',
        ORCHESTRATION: 'orchestration',
        VERSION_CONTROL: 'version_control',
        INFRASTRUCTURE: 'infrastructure',
        STORAGE: 'storage',
      };

      // Domain ordering for position
      const domainOrder: Record<string, number> = {
        ingestion: 0, warehouse: 1, transform: 2,
        orchestration: 3, bi: 4, version_control: 5,
        infrastructure: 6, storage: 0, other: 7,
      };

      // Build merged nodes: start with pipeline tool nodes as the base
      const mergedNodes: CPNode[] = [];
      const seenToolTypes = new Set<string>();

      for (const toolNode of pipelineToolNodes) {
        const toolType = (toolNode.toolType || toolNode.category || '').toLowerCase();
        if (seenToolTypes.has(toolType)) continue;
        seenToolTypes.add(toolType);

        const domain = layerToDomain[toolNode.layer] || 'other';
        const engineNode = engineNodesByType.get(toolType);

        mergedNodes.push({
          id: engineNode?.id || `pipeline:${toolType}`,
          name: toolNode.name,
          toolType: toolType,
          platformDomain: domain,
          integrationId: toolNode.integrationId,
          assetCount: engineNode?.assetCount || 0,
          healthSummary: engineNode?.healthSummary || { healthy: 0, degraded: 0, failing: 0, unknown: 0 },
          position: domainOrder[domain] ?? 7,
        });
      }

      // Add any engine nodes that don't have a matching pipeline tool node
      // (e.g., dbt adapter might discover data but no pipeline tool node exists)
      if (engineData?.nodes) {
        for (const engNode of engineData.nodes) {
          if (!seenToolTypes.has(engNode.toolType)) {
            seenToolTypes.add(engNode.toolType);
            mergedNodes.push(engNode);
          }
        }
      }

      // Use engine edges (data flow counts between tools)
      const edges = engineData?.edges || [];

      // Also create pipeline-flow edges from pipeline stack edges for tools
      // that don't have engine-derived data flows
      const edgeKeys = new Set(edges.map((e) => `${e.source}→${e.target}`));
      const pipelineEdges = (stackData?.edges || []).filter(
        (e) => e.edgeType === 'pipeline_flow'
      );

      // Map pipeline node IDs to control plane tool IDs
      const pipelineIdToToolType = new Map<string, string>();
      for (const tn of pipelineToolNodes) {
        const toolType = (tn.toolType || tn.category || '').toLowerCase();
        pipelineIdToToolType.set(tn.id, toolType);
      }

      const nodeIdMap = new Map(mergedNodes.map((n) => [n.toolType, n.id]));
      const syntheticEdges: CPEdge[] = [];
      for (const pe of pipelineEdges) {
        const srcTool = pipelineIdToToolType.get(pe.source);
        const tgtTool = pipelineIdToToolType.get(pe.target);
        if (!srcTool || !tgtTool) continue;
        const srcId = nodeIdMap.get(srcTool);
        const tgtId = nodeIdMap.get(tgtTool);
        if (!srcId || !tgtId) continue;
        const key = `${srcId}→${tgtId}`;
        if (edgeKeys.has(key)) continue; // Engine already has this edge
        edgeKeys.add(key);
        syntheticEdges.push({
          id: key,
          source: srcId,
          target: tgtId,
          dataFlowCount: 0, // Pipeline edge, no data flow count yet
          sampleAssets: [],
        });
      }

      setControlPlaneData({
        nodes: mergedNodes.sort((a, b) => a.position - b.position),
        edges: [...edges, ...syntheticEdges],
        stats: {
          tool_count: mergedNodes.length,
          flow_count: edges.length + syntheticEdges.length,
        },
      });
    } catch {
      // Non-fatal
    } finally {
      setControlPlaneLoading(false);
    }
  }, [stackId]);

  // Clear all cached data when switching pipelines
  const prevStackIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (stackId !== prevStackIdRef.current) {
      prevStackIdRef.current = stackId;
      // Reset all state so previous pipeline's data doesn't persist
      setLineageData(null);
      setRenderedView(null);
      setRenderedOverview(null);
      setLaneOverview(null);
      setControlPlaneData(null);
      setSelectedNode(null);
      setSelectedEdge(null);
      setError(null);
      setActiveRunId(null);
      setLlmProgress([]);
      setLlmNodeCount(0);
      setLlmEdgeCount(0);
    }
    if (stackId) {
      // Always fetch unified lineage (provides allMonitors for pipeline overview tool cards)
      fetchLineage();
      if (activeTab === 'control-plane') {
        fetchControlPlane();
      }
    }
  }, [stackId, activeTab, fetchLineage, fetchControlPlane]);

  // Clear selection when switching tabs
  const handleTabChange = useCallback((tab: 'data' | 'control-plane') => {
    setActiveTab(tab);
    setSelectedNode(null);
    setSelectedEdge(null);
    setLineageData(null); // Clear stale data to prevent wrong-layout flash
    setRenderedView(null);
    setRenderedOverview(null);
    setLaneOverview(null);
  }, []);

  // Extract lineage from warehouse (uses original endpoint)
  const extractLineage = async () => {
    if (!stackId) return;

    setExtracting(true);
    setError(null);
    // Keep old view visible during extraction (atomic swap on completion)

    try {
      // Clear existing lineage first
      await fetch(`/api/pipeline/${stackId}/lineage`, { method: 'DELETE' });

      const res = await fetch(`/api/pipeline/${stackId}/lineage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          options: {
            region: 'auto',
            days_back: 30,
          },
        }),
      });

      if (res.ok) {
        const result = await res.json();
        if (result.run_id) {
          // Pipeline completed with run_id — poll for completion
          setActiveRunId(result.run_id);
        } else if (result.success) {
          // Backward compat: old response format without run_id
          await fetchLineage();
          setExtracting(false);
        } else {
          setError(result.results?.[0]?.error || 'Extraction failed');
          setExtracting(false);
        }
      } else {
        const errorData = await res.json().catch(() => ({}));
        setError(errorData.error || 'Extraction request failed');
        setExtracting(false);
      }
    } catch (err) {
      setError('Failed to extract lineage');
      setExtracting(false);
    }
  };

  // Adapter-based extraction (calls adapters directly, LLM only for reconciliation)
  const extractWithLLM = async () => {
    if (!stackId) return;

    setLlmExtracting(true);
    setLlmProgress([]);
    setLlmNodeCount(0);
    setLlmEdgeCount(0);
    setError(null);

    try {
      // Clear existing lineage first
      await fetch(`/api/pipeline/${stackId}/lineage`, { method: 'DELETE' });

      setLlmProgress([{ type: 'phase', message: 'Starting adapter-based extraction...' }]);

      const res = await fetch(`/api/pipeline/${stackId}/lineage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        setError(errorData.error || 'Extraction failed');
        setLlmExtracting(false);
        return;
      }

      const data = await res.json();
      const totalNodes = data.stats?.total_nodes || 0;
      const totalEdges = data.stats?.total_edges || 0;

      setLlmNodeCount(totalNodes);
      setLlmEdgeCount(totalEdges);
      setLlmProgress(prev => [
        ...prev,
        { type: 'complete', message: `Done: ${totalNodes} nodes, ${totalEdges} edges` },
      ]);

      // Save snapshot and refresh
      try {
        await fetch(`/api/pipeline/${stackId}/lineage/engine?action=save-snapshot`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
      } catch {
        console.warn('[LINEAGE] Failed to save snapshot (non-fatal)');
      }
      // Invalidate cache so fetchLineage gets fresh post-build data
      invalidateCache(`/api/pipeline/${stackId}/lineage`);
      await fetchLineage();
      await fetchControlPlane();

      setLlmExtracting(false);
    } catch (err) {
      setError('Extraction failed');
      setLlmExtracting(false);
    }
  };

  // Poll run status and atomically swap views when complete
  useEffect(() => {
    if (!activeRunId || !stackId) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(
          `/api/pipeline/${stackId}/lineage/engine?action=run-status&id=${activeRunId}`
        );
        if (!res.ok) return;
        const status = await res.json();

        if (status.status === 'completed') {
          clearInterval(interval);
          setActiveRunId(null);
          // Invalidate cache so we get fresh post-build data
          invalidateCache(`/api/pipeline/${stackId}/lineage`);
          // Atomic swap: fetch new views, then update state
          await fetchLineage();
          await fetchControlPlane();
          setExtracting(false);
        } else if (status.status === 'failed') {
          clearInterval(interval);
          setActiveRunId(null);
          setError(status.errors?.[0] || 'Extraction failed');
          setExtracting(false);
        }
      } catch {
        // Polling error — continue trying
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [activeRunId, stackId]);

  // Apply filters to nodes
  const filteredNodes = useMemo(() => {
    if (!lineageData?.nodes) return [];
    let nodes = lineageData.nodes.filter((node) => nodePassesFilter(node, filters));
    if (filterIntegrationId) {
      nodes = nodes.filter((node) => node.integrationId === filterIntegrationId);
    }
    return nodes;
  }, [lineageData?.nodes, filters, filterIntegrationId]);

  // Build filtered stats from what's actually visible on the graph.
  // Nodes can count in multiple categories — e.g. a BigQuery view that is also
  // a dbt model counts as both a View and a Model.
  const filteredStats = useMemo(() => {
    const _DASHBOARD_CATS = new Set(['dashboard', 'report', 'workbook', 'question']);
    const _DBT_MODEL_TYPES = new Set(['model', 'seed', 'snapshot']);

    // Helper: check if a ViewNode is also a dbt model (merged node)
    const _isDbtModel = (vn: ViewNode) => {
      const dbtType = (vn as any).metadata?.dbtResourceType;
      return dbtType && _DBT_MODEL_TYPES.has(dbtType);
    };

    if (renderedView && renderedView.nodes.length > 0) {
      const visible = renderedView.nodes.filter(
        (n) =>
          (filters.showInferred || !n.inferred) &&
          n.canonicalType !== 'job' &&
          n.canonicalType !== 'service' &&
          n.canonicalType !== 'system'
      );
      const cats = visible.map((vn) => _viewNodeToCategory(vn));
      // Models: nodes with dbt metadata OR source/model category
      const modelCount = visible.filter((vn, i) =>
        _isDbtModel(vn) || cats[i] === 'model' || cats[i] === 'source'
      ).length;
      return {
        toolNodes: cats.filter((c) => isToolCategory(c)).length,
        tableNodes: cats.filter((c) => c === 'table').length,
        viewNodes: cats.filter((c) => c === 'view').length,
        modelNodes: modelCount,
        dashboardNodes: cats.filter((c) => _DASHBOARD_CATS.has(c)).length,
        dagNodes: cats.filter((c) => c === 'dag').length,
        taskNodes: cats.filter((c) => c === 'task').length,
      };
    }
    // Fallback: count from unified lineage nodes
    return {
      toolNodes: filteredNodes.filter((n) => isToolCategory(n.category)).length,
      tableNodes: filteredNodes.filter((n) => n.category === 'table').length,
      viewNodes: filteredNodes.filter((n) => n.category === 'view').length,
      modelNodes: filteredNodes.filter((n) => n.category === 'model' || n.category === 'source')
        .length,
      dashboardNodes: filteredNodes.filter((n) => _DASHBOARD_CATS.has(n.category)).length,
      dagNodes: filteredNodes.filter((n) => n.category === 'dag').length,
      taskNodes: filteredNodes.filter((n) => n.category === 'task').length,
    };
  }, [filteredNodes, renderedView, filters.showInferred]);

  // Build edges for the detail panel with transitive reduction applied.
  // Removes shortcut edges (e.g., raw table → intermediate model) so BFS
  // shows the correct multi-hop path through intermediate views.
  const panelEdges = useMemo(() => {
    const allEdges = lineageData?.edges || [];
    if (!allEdges.length) return allEdges;

    // Separate data-level edges from synthetic tool edges
    const dataEdges = allEdges.filter(
      (e) =>
        e.edgeType !== 'pipeline_flow' &&
        e.edgeType !== 'contains' &&
        e.edgeType !== 'produces' &&
        e.edgeType !== 'reads_from'
    );
    const nonDataEdges = allEdges.filter(
      (e) =>
        e.edgeType === 'pipeline_flow' ||
        e.edgeType === 'contains' ||
        e.edgeType === 'produces' ||
        e.edgeType === 'reads_from'
    );

    // Transitive reduction: remove edge A→C when a 2-hop path A→B→C exists
    const adj = new Map<string, Set<string>>();
    for (const e of dataEdges) {
      if (!adj.has(e.source)) adj.set(e.source, new Set());
      adj.get(e.source)!.add(e.target);
    }

    const reduced = dataEdges.filter((edge) => {
      const neighbors = adj.get(edge.source);
      if (!neighbors) return true;
      for (const mid of neighbors) {
        if (mid !== edge.target && adj.get(mid)?.has(edge.target)) {
          return false; // shortcut — a multi-hop path exists
        }
      }
      return true;
    });

    return [...reduced, ...nonDataEdges];
  }, [lineageData?.edges]);

  const panelNodes = useMemo(() => {
    const unifiedNodes = lineageData?.nodes || [];
    if (unifiedNodes.length > 0) return unifiedNodes;

    // Fallback: adapt rendered view nodes to unified format
    if (!renderedView?.nodes?.length) return unifiedNodes;

    return renderedView.nodes.map((vn): UnifiedLineageNode => ({
      id: `lineage-${vn.id}`,
      name: vn.name,
      fullName: vn.metadata?.fqn as string || vn.name,
      category: _viewNodeToCategory(vn),
      layer: (vn.layer || 'WAREHOUSE') as any,
      toolType: vn.platform || undefined,
      database: (vn.metadata?.database as string) || undefined,
      schema: (vn.metadata?.schema as string) || undefined,
      tableName: vn.name,
    }));
  }, [lineageData?.nodes, renderedView?.nodes]);

  // Aggregate monitor statuses per integration AND per layer for pipeline overview
  // Keyed by integrationId (for monitors with one) and by layer (for infra monitors without)
  const monitorsByKey = useMemo(() => {
    const map = new Map<string, { total: number; passing: number; warning: number; failing: number; error: number }>();

    // Monitor type → pipeline layer mapping for monitors without an integrationId
    const MONITOR_TYPE_TO_LAYER: Record<string, string> = {
      // Infrastructure
      SERVER_HEALTH: 'INFRASTRUCTURE',
      CERTIFICATE: 'INFRASTRUCTURE',
      LOG_ANALYSIS: 'INFRASTRUCTURE',
      // Ingestion
      FAILED_SYNCS: 'INGESTION',
      SYNC_LAG: 'INGESTION',
      CONNECTOR_SCHEMA_DRIFT: 'INGESTION',
      // Orchestration
      DAG_LAST_RUN: 'ORCHESTRATION',
      DAG_SCHEDULE_LAG: 'ORCHESTRATION',
      TASK_FAILURE_RATE: 'ORCHESTRATION',
      // Transformation
      DBT_TEST_FAILURES: 'TRANSFORMATION',
      DBT_MODEL_FRESHNESS: 'TRANSFORMATION',
      DBT_SOURCE_FRESHNESS: 'TRANSFORMATION',
    };

    function addToMap(key: string, status: string | null) {
      const existing = map.get(key) || { total: 0, passing: 0, warning: 0, failing: 0, error: 0 };
      existing.total += 1;
      if (status === 'PASS') existing.passing += 1;
      else if (status === 'WARN') existing.warning += 1;
      else if (status === 'FAIL') existing.failing += 1;
      else if (status === 'ERROR') existing.error += 1;
      map.set(key, existing);
    }

    for (const m of lineageData?.allMonitors || []) {
      // Key by integrationId (backend resolves config.serverNodeId/toolNodeId → integrationId)
      if (m.integrationId) {
        addToMap(m.integrationId, m.lastStatus);
      }
      // Key by pipeline layer as fallback (infra nodes without integrationId)
      if (!m.integrationId && m.monitorType) {
        const layer = MONITOR_TYPE_TO_LAYER[m.monitorType];
        if (layer) {
          addToMap(`layer:${layer}`, m.lastStatus);
        }
      }
    }
    return map;
  }, [lineageData?.allMonitors]);

  // Build React Flow nodes and edges
  // Uses pre-positioned rendered view when available, falls back to Dagre
  const { flowNodes, flowEdges } = useMemo(() => {
    // Rendered view path: use backend-computed positions
    if (renderedView && renderedView.nodes.length > 0) {
      // Build lookup from unified nodes for enrichment (monitor status, issues, etc.)
      const unifiedByEngineId = new Map<string, UnifiedLineageNode>();
      for (const n of lineageData?.nodes || []) {
        unifiedByEngineId.set(n.id, n);
        if (n.id.startsWith('lineage-')) unifiedByEngineId.set(n.id.slice(8), n);
      }

      // Filter by inferred toggle and exclude orchestration nodes from data plane
      const visibleViewNodes = renderedView.nodes.filter(
        (n) =>
          (filters.showInferred || !n.inferred) &&
          n.canonicalType !== 'job' &&
          n.canonicalType !== 'service' &&
          n.canonicalType !== 'system'
      );
      const visibleIds = new Set(visibleViewNodes.map((n) => n.id));

      const nodes: Node[] = visibleViewNodes.map((vn) => {
        const unified = unifiedByEngineId.get(vn.id);
        return {
          id: vn.id,
          type: vn.canonicalType === 'service' ? 'toolNode' : 'dataAssetNode',
          position: { x: vn.x, y: vn.y },
          targetPosition: Position.Left,
          sourcePosition: Position.Right,
          data: {
            name: vn.name,
            fullName: vn.metadata?.fqn || vn.name,
            category: _viewNodeToCategory(vn),
            layer: vn.layer as any,
            toolType: vn.platform,
            database: vn.metadata?.database,
            schema: vn.metadata?.schema,
            tableName: vn.name,
            nodeType: vn.originalType,
            criticality: vn.metadata?.criticality,
            rowCount: vn.metadata?.rowCount,
            upstreamCount: vn.metadata?.upstreamCount,
            downstreamCount: vn.metadata?.downstreamCount,
            healthStatus: vn.metadata?.healthStatus,
            owner: vn.metadata?.owner,
            tags: vn.metadata?.tags,
            platforms: vn.metadata?.platforms,
            columnCount: vn.metadata?.columnCount,
            materialization: vn.metadata?.materialization,
            // Enriched from unified data (monitor status, issues)
            issues: unified?.issues,
            monitorStatus: unified?.monitorStatus,
            hasUpstreamFailure: unified?.hasUpstreamFailure,
            freshnessStatus: unified?.freshnessStatus,
            freshnessHours: unified?.freshnessHours,
            lastUpdated: unified?.lastUpdated,
            // Visual flags
            isInferred: vn.inferred,
            isOverlay: vn.inferred,
            // Policy mode data
            isSLAMode: slaMode,
            isSLASelected: slaMode && slaSelectedNodeIds.has(vn.id),
            slaStatus: (nodeSLAs.get(vn.metadata?.fqn || vn.name)?.status as any) || 'none',
            slaProfileName: nodeSLAs.get(vn.metadata?.fqn || vn.name)?.profileName || null,
            onSLABadgeClick: nodeSLAs.has(vn.metadata?.fqn || vn.name) ? () => setSelectedSlaNodeId(vn.id) : undefined,
            complianceStatus: computeNodeCompliance(
              nodeSLAs.get(vn.metadata?.fqn || vn.name),
              vn.platformDomain || vn.originalType || '',
            ),
          },
        };
      });

      const edges: Edge[] = renderedView.edges
        .filter(
          (e) =>
            visibleIds.has(e.sourceId) &&
            visibleIds.has(e.targetId) &&
            (filters.showInferred || !e.inferred) &&
            e.confidence >= filters.minConfidence
        )
        .map((ve) => {
          const confidenceColor = getConfidenceColor(ve.confidence);
          const isInferred = ve.inferred;
          return {
            id: ve.id,
            source: ve.sourceId,
            target: ve.targetId,
            type: 'smoothstep',
            animated: !isInferred,
            style: {
              stroke: isInferred ? 'var(--text-faint)' : confidenceColor,
              strokeWidth: isInferred ? 1.5 : 2,
              strokeDasharray: isInferred ? '6,4' : undefined,
            },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: isInferred ? 'var(--text-faint)' : confidenceColor,
            },
            label: ve.confidence !== undefined
              ? `${Math.round(ve.confidence * 100)}%`
              : undefined,
          };
        });

      const withOrphans = layoutRenderedViewOrphans(nodes, edges, renderedView.unmappedNodes);
      return { flowNodes: withOrphans.nodes, flowEdges: withOrphans.edges };
    }

    // Fallback: use unified data + Dagre layout
    if (!filteredNodes.length) return { flowNodes: [], flowEdges: [] };

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const nodeMap = new Map(filteredNodes.map((n) => [n.id, n]));

    // Convert to ReactFlow nodes
    const nodes: Node[] = filteredNodes.map((node) => ({
      id: node.id,
      type: isToolCategory(node.category) ? 'toolNode' : 'dataAssetNode',
      position: { x: 0, y: 0 },
      data: {
        name: node.name,
        fullName: node.fullName,
        category: node.category,
        layer: node.layer,
        toolType: node.toolType,
        status: node.status,
        healthScore: node.healthScore,
        findingsCount: node.findingsCount,
        criticalCount: node.criticalCount,
        highCount: node.highCount,
        database: node.database,
        schema: node.schema,
        tableName: node.tableName,
        nodeType: node.nodeType,
        criticality: node.criticality,
        rowCount: node.rowCount,
        upstreamCount: node.upstreamCount,
        downstreamCount: node.downstreamCount,
        // Health & freshness data
        lastUpdated: node.lastUpdated,
        freshnessStatus: node.freshnessStatus,
        freshnessHours: node.freshnessHours,
        issues: node.issues,
        monitorStatus: node.monitorStatus,
        hasUpstreamFailure: node.hasUpstreamFailure,
        owner: node.owner,
        tags: node.tags,
        platforms: node.platforms,
        columnCount: node.columns?.length || 0,
        materialization: node.materialization,
        // Policy mode data
        isSLAMode: slaMode,
        isSLASelected: slaMode && slaSelectedNodeIds.has(node.id),
        slaStatus: (nodeSLAs.get(node.fullName || node.name)?.status as any) || 'none',
        slaProfileName: nodeSLAs.get(node.fullName || node.name)?.profileName || null,
        onSLABadgeClick: nodeSLAs.has(node.fullName || node.name) ? () => setSelectedSlaNodeId(node.id) : undefined,
        complianceStatus: computeNodeCompliance(
          nodeSLAs.get(node.fullName || node.name),
          node.category || '',
        ),
      },
    }));

    // Data graph: show everything except pure control-plane edges
    // (pipeline/synthetic edges have no plane field — always show them)
    const isDisplayPlane = (e: UnifiedLineageEdge): boolean => {
      return e.plane !== 'control';
    };

    // Filter and convert edges (apply node membership + plane + engine-level filters)
    const edges: Edge[] = (lineageData?.edges || [])
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target) && isDisplayPlane(e) && edgePassesFilter(e, filters))
      .map((edge) => {
        const sourceNode = nodeMap.get(edge.source);
        const style = getEdgeStyle(edge, sourceNode);
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: 'smoothstep',
          animated: style.animated,
          style: {
            stroke: style.stroke,
            strokeWidth: style.strokeWidth,
            strokeDasharray: style.strokeDasharray,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: style.stroke,
          },
          label: edge.confidence !== undefined
            ? `${Math.round(edge.confidence * 100)}%`
            : edge.label,
        };
      });

    if (nodes.length === 0) return { flowNodes: [], flowEdges: [] };

    const layouted = layoutGraph(nodes, edges, { direction: 'LR' });
    return { flowNodes: layouted.nodes, flowEdges: layouted.edges };
  }, [filteredNodes, lineageData?.edges, lineageData?.nodes, filters, renderedView, slaMode, slaSelectedNodeIds, nodeSLAs]);

  // Build control plane flow nodes/edges
  // Uses rendered overview positions when available, falls back to Dagre
  const { cpFlowNodes, cpFlowEdges } = useMemo(() => {
    // Lane overview path (primary): use dagre layout + enriched metadata
    if (laneOverview && laneOverview.nodes.length > 0) {
      const cpNodes: Node[] = laneOverview.nodes.map((vn) => {
        const layerColor = LAYER_COLORS[vn.layer as PipelineLayer] || '#6366F1';
        return {
          id: vn.id,
          type: 'toolNode',
          position: { x: 0, y: 0 },
          data: {
            name: vn.name,
            category: vn.platformDomain as UnifiedNodeCategory || 'warehouse',
            layer: vn.layer as PipelineLayer,
            toolType: vn.platform || vn.originalType,
            integrationId: vn.metadata?.integrationId,
            assetCount: vn.metadata?.assetCount,
            healthSummary: vn.metadata?.healthSummary,
            jobCount: vn.metadata?.jobCount,
            coverageGaps: vn.metadata?.coverageGaps,
            monitorSummary: (() => {
              const byIntegration = vn.metadata?.integrationId ? monitorsByKey.get(vn.metadata.integrationId) : undefined;
              return byIntegration || monitorsByKey.get(`layer:${vn.layer}`) || undefined;
            })(),
            isControlPlane: true,
            domainColor: layerColor,
          },
        };
      });

      const cpEdges: Edge[] = laneOverview.edges.map((ve) => {
        // Use semantic edge color when available, fallback to indigo/gray
        const semanticLabel = ve.metadata?.label?.toLowerCase?.() ?? '';
        const semanticStyle = SEMANTIC_EDGE_STYLES[semanticLabel] ?? null;
        const edgeColor = semanticStyle?.color
          ?? (ve.evidenceCount > 0 ? '#6366F1' : '#6B7280');
        const dashArray = semanticStyle?.dashArray;

        const hasFlows = ve.evidenceCount > 0;
        const label = ve.metadata?.label
          ? `${ve.metadata.label}${hasFlows ? ` · ${ve.evidenceCount}` : ''}`
          : hasFlows ? `${ve.evidenceCount} flows` : '';

        return {
          id: ve.id,
          source: ve.sourceId,
          target: ve.targetId,
          type: 'smoothstep',
          animated: hasFlows,
          data: { isDataFlow: (ve.metadata?.dataFlowCount ?? ve.evidenceCount) > 0 },
          label,
          labelStyle: {
            fontSize: 11,
            fontWeight: 600,
            fill: 'var(--text)',
          },
          labelBgStyle: {
            fill: 'var(--surface-raised)',
            stroke: edgeColor,
            strokeWidth: 1,
            rx: 6,
            ry: 6,
            opacity: 0.95,
          },
          labelBgPadding: [6, 4] as [number, number],
          style: {
            stroke: edgeColor,
            strokeWidth: hasFlows
              ? Math.min(3 + Math.log2(ve.evidenceCount + 1), 7)
              : 2,
            strokeDasharray: dashArray ?? (hasFlows ? undefined : '6,4'),
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: edgeColor,
            width: 20,
            height: 20,
          },
        };
      });

      if (cpNodes.length === 0) return { cpFlowNodes: [], cpFlowEdges: [] };
      const layouted = layoutGraph(cpNodes, cpEdges, {
        direction: 'LR',
        ranksep: 280,
        nodesep: 100,
      });
      return { cpFlowNodes: layouted.nodes, cpFlowEdges: layouted.edges };
    }

    // Rendered overview path (fallback): use backend positions
    if (renderedOverview && renderedOverview.nodes.length > 0) {
      const cpNodes: Node[] = renderedOverview.nodes.map((vn) => ({
        id: vn.id,
        type: 'toolNode',
        position: { x: vn.x, y: vn.y },
        targetPosition: Position.Left,
        sourcePosition: Position.Right,
        data: {
          name: vn.name,
          category: vn.platformDomain as UnifiedNodeCategory || 'warehouse',
          layer: vn.layer as PipelineLayer,
          toolType: vn.platform || vn.originalType,
          assetCount: vn.metadata?.assetCount,
          healthSummary: vn.metadata?.healthSummary,
          monitorSummary: (() => {
            const byIntegration = vn.metadata?.integrationId ? monitorsByKey.get(vn.metadata.integrationId) : undefined;
            return byIntegration || monitorsByKey.get(`layer:${vn.layer}`) || undefined;
          })(),
          isControlPlane: true,
          domainColor: LAYER_COLORS[vn.layer as PipelineLayer] || '#6366F1',
        },
      }));

      const cpEdges: Edge[] = renderedOverview.edges.map((ve) => {
        const semanticLabel = ve.metadata?.label?.toLowerCase?.() ?? '';
        const semanticStyle = SEMANTIC_EDGE_STYLES[semanticLabel] ?? null;
        const edgeColor = semanticStyle?.color
          ?? (ve.evidenceCount > 0 ? '#6366F1' : '#6B7280');
        const hasFlows = ve.evidenceCount > 0;
        return {
          id: ve.id,
          source: ve.sourceId,
          target: ve.targetId,
          type: 'smoothstep',
          animated: hasFlows,
          label: hasFlows ? `${ve.evidenceCount} flows` : 'connected',
          labelStyle: { fontSize: 11, fontWeight: 600, fill: 'var(--text)' },
          labelBgStyle: {
            fill: 'var(--surface-raised)', stroke: edgeColor,
            strokeWidth: 1, rx: 6, ry: 6, opacity: 0.95,
          },
          labelBgPadding: [6, 4] as [number, number],
          style: {
            stroke: edgeColor,
            strokeWidth: hasFlows
              ? Math.min(3 + Math.log2(ve.evidenceCount + 1), 7)
              : 2,
            strokeDasharray: semanticStyle?.dashArray ?? (hasFlows ? undefined : '6,4'),
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: edgeColor,
            width: 20,
            height: 20,
          },
        };
      });

      return { cpFlowNodes: cpNodes, cpFlowEdges: cpEdges };
    }

    // Fallback: use controlPlaneData + Dagre
    if (!controlPlaneData?.nodes?.length) return { cpFlowNodes: [], cpFlowEdges: [] };

    const cpNodes: Node[] = controlPlaneData.nodes.map((n: CPNode) => ({
      id: n.id,
      type: 'toolNode',
      position: { x: 0, y: 0 },
      data: {
        name: n.name,
        category: n.platformDomain as UnifiedNodeCategory || 'warehouse',
        layer: 'WAREHOUSE' as PipelineLayer,
        toolType: n.toolType,
        assetCount: n.assetCount,
        healthSummary: n.healthSummary,
        monitorSummary: (() => {
          const byIntegration = n.integrationId ? monitorsByKey.get(n.integrationId) : undefined;
          // Reverse lookup: platformDomain → layer for fallback
          const domainToLayer: Record<string, string> = {
            ingestion: 'INGESTION', warehouse: 'WAREHOUSE', transform: 'TRANSFORMATION',
            orchestration: 'ORCHESTRATION', bi: 'REPORTING', version_control: 'VERSION_CONTROL',
            infrastructure: 'INFRASTRUCTURE', storage: 'STORAGE',
          };
          const layer = domainToLayer[n.platformDomain] || '';
          return byIntegration || monitorsByKey.get(`layer:${layer}`) || undefined;
        })(),
        isControlPlane: true,
        domainColor: LAYER_COLORS['WAREHOUSE'] || '#6366F1',
      },
    }));

    const cpEdges: Edge[] = controlPlaneData.edges.map((e: CPEdge) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: e.dataFlowCount > 0,
      label: e.dataFlowCount > 0 ? `${e.dataFlowCount} flows` : 'connected',
      style: {
        stroke: e.dataFlowCount > 0 ? '#6366F180' : 'var(--text-faint)',
        strokeWidth: e.dataFlowCount > 0
          ? Math.min(2 + Math.log2(e.dataFlowCount + 1), 6)
          : 2,
        strokeDasharray: e.dataFlowCount > 0 ? undefined : '6,4',
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: e.dataFlowCount > 0 ? '#6366F1' : 'var(--text-faint)',
      },
    }));

    if (cpNodes.length === 0) return { cpFlowNodes: [], cpFlowEdges: [] };
    const layouted = layoutGraph(cpNodes, cpEdges, { direction: 'LR' });
    return { cpFlowNodes: layouted.nodes, cpFlowEdges: layouted.edges };
  }, [controlPlaneData, renderedOverview, laneOverview, monitorsByKey]);

  // Pick the right flow data based on active tab
  const activeFlowNodes = activeTab === 'control-plane' ? cpFlowNodes : flowNodes;
  const activeFlowEdges = activeTab === 'control-plane' ? cpFlowEdges : flowEdges;

  const [nodes, setNodes, onNodesChangeBase] = useNodesState(activeFlowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(activeFlowEdges);

  // In policy mode, filter out ReactFlow's internal selection changes
  // so they don't interfere with our custom multi-select
  const onNodesChange = useCallback(
    (changes: any[]) => {
      if (slaMode) {
        const filtered = changes.filter((c: any) => c.type !== 'select');
        if (filtered.length > 0) onNodesChangeBase(filtered);
      } else {
        onNodesChangeBase(changes);
      }
    },
    [slaMode, onNodesChangeBase]
  );

  useEffect(() => {
    setNodes(activeFlowNodes);
    setEdges(activeFlowEdges);
  }, [activeFlowNodes, activeFlowEdges, setNodes, setEdges]);

  const handleNodeClick = useCallback(
    (event: React.MouseEvent, node: Node) => {
      if (node.id === ORPHAN_GROUP_ID) return; // Ignore clicks on orphan group background

      // Policy mode: manage multi-select
      // Shift/Cmd/Ctrl+click to add/remove from selection, plain click to replace
      if (slaMode) {
        setSlaSelectedNodeIds((prev) => {
          const next = new Set(prev);
          const isMultiKey = event.shiftKey || event.metaKey || event.ctrlKey;
          if (isMultiKey) {
            // Toggle this node in/out of selection
            if (next.has(node.id)) {
              next.delete(node.id);
            } else {
              next.add(node.id);
            }
          } else {
            // Plain click: replace selection with this node
            next.clear();
            next.add(node.id);
          }
          return next;
        });
        return;
      }

      // Normal mode: Shift+Click for multi-select (only on control-plane tab where
      // ViewNodes and the InspectorPanel are available)
      if (event.shiftKey && activeTab === 'control-plane') {
        const viewNode = laneOverview?.nodes.find(n => n.id === node.id)
          || renderedOverview?.nodes.find(n => n.id === node.id);
        if (viewNode) {
          setMultiSelectedNodeIds((prev) => {
            const next = new Set(prev);
            if (next.has(node.id)) {
              next.delete(node.id);
            } else {
              next.add(node.id);
            }
            return next;
          });
          setSelectedNode(null);
          setSelectedEdge(null);
          return;
        }
      }

      // Plain click: clear multi-select and proceed with single-node inspection
      setMultiSelectedNodeIds(new Set());

      if (activeTab === 'control-plane') {
        // Use InspectorPanel for control-plane nodes
        const viewNode = laneOverview?.nodes.find(n => n.id === node.id)
          || renderedOverview?.nodes.find(n => n.id === node.id);
        if (viewNode) {
          setPipelineInspectorTarget({ kind: 'node', node: viewNode });
          setSelectedNode(null);
          setSelectedEdge(null);
          return;
        }
        // Fallback for legacy controlPlaneData
        const cpNode = controlPlaneData?.nodes?.find((n: CPNode) => n.id === node.id);
        if (cpNode) {
          setSelectedNode({
            id: cpNode.id,
            name: cpNode.name,
            category: cpNode.platformDomain as UnifiedNodeCategory || 'warehouse',
            layer: 'WAREHOUSE',
            toolType: cpNode.toolType,
            integrationId: cpNode.integrationId,
          });
        }
      } else {
        setPipelineInspectorTarget(null);
        // Rendered view uses raw engine IDs, unified data uses `lineage-` prefix
        const unifiedNode = lineageData?.nodes.find((n) => n.id === node.id)
          || lineageData?.nodes.find((n) => n.id === `lineage-${node.id}`);
        setSelectedNode(unifiedNode || null);
      }
      setSelectedEdge(null);
    },
    [lineageData?.nodes, activeTab, controlPlaneData?.nodes, laneOverview, renderedOverview, slaMode]
  );

  const handleEdgeClick = useCallback(
    (event: React.MouseEvent, edge: Edge) => {
      if (activeTab === 'control-plane') {
        const viewEdge = laneOverview?.edges.find(e => e.id === edge.id)
          || renderedOverview?.edges.find(e => e.id === edge.id);
        if (viewEdge) {
          setPipelineInspectorTarget({ kind: 'edge', edge: viewEdge });
          setSelectedNode(null);
          setSelectedEdge(null);
          return;
        }
      }
      setPipelineInspectorTarget(null);
      const unifiedEdge = lineageData?.edges.find((e) => e.id === edge.id);
      setSelectedEdge(unifiedEdge || null);
      setSelectedNode(null);
    },
    [lineageData?.edges, activeTab, laneOverview, renderedOverview]
  );

  // Navigate to a node from the detail panel (e.g. clicking an upstream/downstream node)
  const handleNavigateToNode = useCallback(
    (nodeId: string) => {
      const targetNode = lineageData?.nodes.find((n) => n.id === nodeId)
        || lineageData?.nodes.find((n) => n.id === `lineage-${nodeId}`);
      if (targetNode) {
        setSelectedNode(targetNode);
        setSelectedEdge(null);
      }
    },
    [lineageData?.nodes]
  );

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  if (loading && !lineageData) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 red-spinner" />
          <p className="text-sm text-[var(--muted)]">Loading lineage...</p>
        </div>
      </div>
    );
  }

  // Compute the effective inspector target: multi-select takes priority when ≥2 nodes selected
  const allViewNodes = [...(laneOverview?.nodes || []), ...(renderedOverview?.nodes || [])];
  const multiNodes = Array.from(multiSelectedNodeIds)
    .map(id => allViewNodes.find(n => n.id === id))
    .filter((n): n is ViewNode => n !== undefined);
  const effectiveInspectorTarget: InspectorTarget =
    multiNodes.length >= 2
      ? { kind: 'multi', nodeIds: Array.from(multiSelectedNodeIds), nodes: multiNodes }
      : pipelineInspectorTarget;

  return (
    <div className="h-[calc(100vh-56px)] flex flex-col -m-6">
      {/* Integration filter banner */}
      {filterIntegrationId && (
        <div className="px-6 py-2.5 bg-[var(--accent)]/10 border-b border-[var(--accent)]/20 flex items-center justify-between">
          <span className="text-sm text-[var(--text-secondary)]">
            Filtered to integration <span className="font-medium text-[var(--text)]">{filterIntegrationId}</span>
          </span>
          <button
            onClick={() => {
              const url = new URL(window.location.href);
              url.searchParams.delete('integrationId');
              window.history.replaceState({}, '', url.pathname);
              router.replace('/dashboard/lineage');
            }}
            className="text-xs text-[var(--accent-2)] hover:underline"
          >
            Clear filter
          </button>
        </div>
      )}
      {/* Header */}
      <div className={`px-6 py-4 border-b border-[var(--subtle-border)] bg-[var(--surface-sunken)] ${slaMode ? 'ring-1 ring-inset ring-slate-500/20' : ''}`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-lg font-semibold text-[var(--text)]">Pipeline Lineage</h1>
            <p className="text-[13px] text-[var(--muted)]">
              Visualize your complete data pipeline from ingestion to reporting
            </p>
          </div>
          <div className="flex items-center gap-3">
            {lineageData?.lastExtracted && (
              <span className="text-[12px] text-[var(--muted)]">
                Last extracted: {formatDate(lineageData.lastExtracted)}
              </span>
            )}
            {/* Data SLA button */}
            {lineageData && lineageData.nodes.length > 0 && !slaMode && activeTab === 'data' && (
              <button
                onClick={() => {
                  setSlaMode(true);
                  setSlaSelectedNodeIds(new Set());
                  setSelectedNode(null);
                  setSelectedEdge(null);
                }}
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-500/30 text-slate-300 hover:bg-slate-500/10 text-[13px] font-medium transition-all"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
                Data SLA
              </button>
            )}
            <button
              onClick={extractWithLLM}
              disabled={llmExtracting || extracting || !stackId}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 disabled:cursor-not-allowed text-white text-[13px] font-medium transition-all"
            >
              {llmExtracting ? (
                <>
                  <div className="w-4 h-4 red-spinner" />
                  Building...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                  Build Lineage
                </>
              )}
            </button>
          </div>
        </div>

        {/* Removed: LLM extraction progress panel (always showed 0/0) */}

        {/* Tab bar */}
        <div className="flex items-center gap-1 mb-4">
          <button
            onClick={() => handleTabChange('data')}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-medium transition-all border
              ${activeTab === 'data'
                ? 'bg-indigo-500/15 border-indigo-500/30 text-indigo-300'
                : 'border-transparent text-[var(--muted)] hover:text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)]'}
            `}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            Data Lineage
          </button>
          <button
            onClick={() => handleTabChange('control-plane')}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-[13px] font-medium transition-all border
              ${activeTab === 'control-plane'
                ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                : 'border-transparent text-[var(--muted)] hover:text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)]'}
            `}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
            </svg>
            Pipeline Overview
          </button>
        </div>

        {/* Stats / Policy toolbar */}
        {slaMode ? (
          <SLAModeToolbar
            selectedCount={slaSelectedNodeIds.size}
            totalNodes={lineageData?.nodes?.length || 0}
            saving={policySaving}
            onSaveAll={() => {
              // TODO: batch save all pending policies
            }}
            onExit={() => {
              setSlaMode(false);
              setSlaSelectedNodeIds(new Set());
              setSlaDiscoveryDefaults(null);
            }}
          />
        ) : (
        <div className="flex items-center gap-6 mt-4 pt-4 border-t border-[var(--border-faint)]">
          {activeTab === 'control-plane' ? (
            <>
              <div className="text-center">
                <div className="text-xl font-semibold text-emerald-400">
                  {new Set(cpFlowNodes
                    .filter(n => n.id !== ORPHAN_GROUP_ID)
                    .map(n => {
                      const intId = n.data?.integrationId;
                      return (intId && intId !== '') ? intId : (n.data?.toolType || n.id);
                    })
                  ).size}
                </div>
                <div className="text-[11px] text-[var(--muted)]">Integrations</div>
              </div>
              <div className="text-center">
                <div className="text-xl font-semibold text-[var(--text)]">
                  {cpFlowEdges.filter(e => (e as any).data?.isDataFlow).length}
                </div>
                <div className="text-[11px] text-[var(--muted)]">Data Flows</div>
              </div>
            </>
          ) : (
            <>
              <div className="text-center">
                <div className="text-xl font-semibold text-[var(--text)]">{filteredStats.tableNodes}</div>
                <div className="text-[11px] text-[var(--muted)]">Tables</div>
              </div>
              {filteredStats.viewNodes > 0 && (
                <div className="text-center">
                  <div className="text-xl font-semibold text-[var(--text)]">{filteredStats.viewNodes}</div>
                  <div className="text-[11px] text-[var(--muted)]">Views</div>
                </div>
              )}
              {filteredStats.modelNodes > 0 && (
                <div className="text-center">
                  <div className="text-xl font-semibold text-[var(--text)]">{filteredStats.modelNodes}</div>
                  <div className="text-[11px] text-[var(--muted)]">Models</div>
                </div>
              )}
              {filteredStats.dashboardNodes > 0 && (
                <div className="text-center">
                  <div className="text-xl font-semibold text-[var(--text)]">{filteredStats.dashboardNodes}</div>
                  <div className="text-[11px] text-[var(--muted)]">Dashboards</div>
                </div>
              )}
              <div className="text-center">
                <div className="text-xl font-semibold text-[var(--text)]">
                  {flowEdges.length}
                </div>
                <div className="text-[11px] text-[var(--muted)]">Dependencies</div>
              </div>
            </>
          )}
        </div>
        )}
      </div>

      {/* Error message */}
      {error && (
        <div className="mx-6 mt-4 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-[13px]">
          {error}
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex min-h-0">
        {/* Canvas */}
        <div className="flex-1 relative">
          {controlPlaneLoading && activeTab === 'control-plane' ? (
            <div className="flex items-center justify-center h-full">
              <div className="flex flex-col items-center gap-4">
                <div className="w-10 h-10 red-spinner" />
                <p className="text-sm text-[var(--muted)]">Loading pipeline overview...</p>
              </div>
            </div>
          ) : nodes.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full">
              <svg
                className="w-16 h-16 text-[var(--text-faint)] mb-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1}
                  d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                />
              </svg>
              {activeTab === 'control-plane' ? (
                <>
                  <p className="text-[var(--muted)] text-[15px] mb-2">No pipeline overview available</p>
                  <p className="text-[var(--text-faint)] text-[13px] mb-4">
                    Extract lineage from the Data Lineage tab first to generate the pipeline overview
                  </p>
                </>
              ) : lineageData && lineageData.nodes.length > 0 ? (
                <>
                  <p className="text-[var(--muted)] text-[15px] mb-2">No nodes match current filters</p>
                  <p className="text-[var(--text-faint)] text-[13px]">
                    Try adjusting the layer or node type filters
                  </p>
                </>
              ) : (
                <>
                  <p className="text-[var(--muted)] text-[15px] mb-2">No lineage data yet</p>
                  <p className="text-[var(--text-faint)] text-[13px] mb-4">
                    Configure your pipeline and click &quot;Build Lineage&quot; to discover dependencies
                  </p>
                  <button
                    onClick={extractWithLLM}
                    disabled={llmExtracting || !stackId}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] disabled:opacity-50 text-white text-[13px] font-medium"
                  >
                    {llmExtracting ? 'Building...' : 'Build Lineage'}
                  </button>
                </>
              )}
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={handleNodeClick}
              onEdgeClick={handleEdgeClick}
              nodeTypes={unifiedNodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.1}
              maxZoom={2}
              defaultEdgeOptions={{
                type: 'smoothstep',
              }}
              proOptions={{ hideAttribution: true }}
              // In policy mode: disable ReactFlow's built-in multi-select so shift+click
              // reaches our handler instead of being consumed by ReactFlow's selection system
              multiSelectionKeyCode={slaMode ? null : 'Shift'}
              selectionKeyCode={slaMode ? null : 'Shift'}
            >
              <Controls className="!bg-[var(--subtle-bg)] !border-[var(--border-medium)] !rounded-lg [&>button]:!bg-[var(--subtle-bg)] [&>button]:!border-[var(--border-medium)] [&>button]:!text-[var(--text-tertiary)]" />
              <MiniMap
                nodeColor={(n) => {
                  if (n.id === ORPHAN_GROUP_ID) return 'rgba(148, 163, 184, 0.2)';
                  const category = n.data.category as string;
                  if (CATEGORY_VISUALS[category as keyof typeof CATEGORY_VISUALS]) {
                    return CATEGORY_VISUALS[category as keyof typeof CATEGORY_VISUALS].color;
                  }
                  return '#6366F1';
                }}
                maskColor="var(--overlay-strong)"
                className="!bg-[var(--subtle-bg)] !border-[var(--border-medium)] !rounded-lg"
              />
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={2}
                color="var(--text-faint)"
              />
            </ReactFlow>
          )}

          {/* Legend */}
          {nodes.length > 0 && (
            <div className="absolute bottom-4 left-16 flex flex-wrap items-center gap-3 px-3 py-2 bg-[var(--surface)]/80 backdrop-blur-sm rounded-lg border border-[var(--border-medium)] text-[10px] max-w-md">
              {activeTab === 'control-plane' ? (
                <>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#10B981' }} />
                    <span className="text-[var(--muted)]">Ingestion</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#6366F1' }} />
                    <span className="text-[var(--muted)]">Warehouse</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#F59E0B' }} />
                    <span className="text-[var(--muted)]">Transform</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#F97316' }} />
                    <span className="text-[var(--muted)]">Orchestration</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#06B6D4' }} />
                    <span className="text-[var(--muted)]">BI</span>
                  </div>
                  <div className="w-px h-3 bg-[var(--overlay-strong)]" />
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#6366F1' }} />
                    <span className="text-[var(--muted)]">Data Flow</span>
                  </div>
                </>
              ) : (
                <>
                  {/* Layer colors */}
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.INGESTION }} />
                    <span className="text-[var(--muted)]">Ingestion</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.TRANSFORMATION }} />
                    <span className="text-[var(--muted)]">Transform</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.WAREHOUSE }} />
                    <span className="text-[var(--muted)]">Warehouse</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: LAYER_COLORS.REPORTING }} />
                    <span className="text-[var(--muted)]">Reporting</span>
                  </div>
                  <div className="w-px h-3 bg-[var(--overlay-strong)]" />
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.table.color }} />
                    <span className="text-[var(--muted)]">Table</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.view.color }} />
                    <span className="text-[var(--muted)]">View</span>
                  </div>
                </>
              )}
              {/* Inferred legend (shows when rendered view has inferred nodes) */}
              {activeTab === 'data' && renderedView?.stats?.inferredNodeCount > 0 && (
                <>
                  <div className="w-px h-3 bg-[var(--overlay-strong)]" />
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ borderTop: '1.5px dashed #F59E0B' }} />
                    <span className="text-[var(--muted)]">Inferred</span>
                  </div>
                </>
              )}
              {/* Confidence legend (shows when engine data present, data tab) */}
              {activeTab === 'data' && lineageData?.engineStats && (
                <>
                  <div className="w-px h-3 bg-[var(--overlay-strong)]" />
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#10B981' }} />
                    <span className="text-[var(--muted)]">&ge;80%</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#F59E0B' }} />
                    <span className="text-[var(--muted)]">50-80%</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-4 h-0.5 rounded" style={{ backgroundColor: '#EF4444' }} />
                    <span className="text-[var(--muted)]">&lt;50%</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Side panel - Edge evidence */}
        {selectedEdge && (
          <EdgeDetailPanel
            edge={selectedEdge}
            allNodes={lineageData?.nodes || []}
            onClose={() => setSelectedEdge(null)}
          />
        )}

        {/* Side panel - Pipeline Overview inspector */}
        {activeTab === 'control-plane' && effectiveInspectorTarget && (
          <InspectorPanel
            target={effectiveInspectorTarget}
            laneOverview={laneOverview}
            stackId={stackId}
            allMonitors={lineageData?.allMonitors}
            onClose={() => {
              setPipelineInspectorTarget(null);
              setMultiSelectedNodeIds(new Set());
            }}
            onCreateSingleMonitor={handleCreateSingleMonitor}
            onCreateMultiMonitor={(nodeIds: string[]) => handleCreateMultiMonitor(nodeIds)}
          />
        )}


        {/* Side panel - Policy editor */}
        {slaMode && (
          <SLAEditorPanel
            selectedNodeIds={slaSelectedNodeIds}
            allNodes={lineageData?.nodes || []}
            allEdges={lineageData?.edges || []}
            stackId={stackId || ''}
            nodeSLAs={nodeSLAs}
            saving={policySaving}
            discoveryDefaults={slaDiscoveryDefaults}
            onRemoveSLA={async (nodeFqns: string[]) => {
              try {
                const res = await fetch('/api/schedule/policies/assign?' + new URLSearchParams({ stackId: stackId || '' }), {
                  method: 'DELETE',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ nodeFqns }),
                });
                if (res.ok) {
                  toast.success('Data SLA removed');
                  const newPolicies = new Map(nodeSLAs);
                  for (const fqn of nodeFqns) newPolicies.delete(fqn);
                  setNodeSLAs(newPolicies);
                } else {
                  toast.error('Failed to remove SLA');
                }
              } catch {
                toast.error('Failed to remove SLA');
              }
            }}
            onApply={async (request: SLAAssignRequest, scope: ApplyScope) => {
              setPolicySaving(true);
              try {
                // If the profileId is a generated placeholder (not a real DB profile),
                // route through the discovery endpoint which upserts profiles automatically
                const isPlaceholderProfile = request.profileId.startsWith('auto-discovered-') || request.profileId.startsWith('manual-');
                let res: Response;
                let count = 0;

                if (isPlaceholderProfile && request.nodeFqns && request.nodeFqns.length > 0) {
                  // Use discovery endpoint to upsert profile + assignment
                  const discoveryResults = request.nodeFqns.map((fqn) => ({
                    nodeFqn: fqn,
                    freshness: request.overrides?.freshnessConfig || null,
                    volume: request.overrides?.volumeConfig || null,
                    quality: request.overrides?.qualityConfig || null,
                    schema: request.overrides?.schemaConfig || null,
                  }));
                  res = await fetch('/api/lineage/discovery', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ results: discoveryResults }),
                  });
                  if (res.ok) {
                    const data = await res.json();
                    count = data.persisted || 0;
                  }
                } else {
                  res = await fetch('/api/schedule/policies/assign', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ...request, stackId }),
                  });
                  if (res.ok) {
                    const data = await res.json();
                    count = data.assignments?.length || 0;
                  }
                }

                if (res.ok) {
                  toast.success(`SLA applied to ${count} node${count !== 1 ? 's' : ''}`);

                  // Re-fetch resolved policies from DB so local state has full config
                  try {
                    const nodesPayload = (lineageData?.nodes || []).map((n) => ({
                      fqn: n.fullName || n.name,
                      domain: n.layer?.toLowerCase() || 'warehouse',
                      criticality: n.criticality?.toLowerCase() || 'medium',
                    }));
                    const resolveRes = await fetch('/api/schedule/policies/resolve', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ nodes: nodesPayload, stackId }),
                    });
                    if (resolveRes.ok) {
                      const resolveData = await resolveRes.json();
                      const policies = resolveData.policies || {};
                      const map = new Map<string, EffectiveSLAPolicy>();
                      for (const [fqn, pol] of Object.entries(policies)) {
                        if ((pol as any).status !== 'none') {
                          map.set(fqn, pol as EffectiveSLAPolicy);
                        }
                      }
                      setNodeSLAs(map);
                    }
                  } catch {
                    // Non-critical — badges still show from assign response
                    const newPolicies = new Map(nodeSLAs);
                    const profileName = (request as any)._profileName || null;
                    for (const a of data.assignments || []) {
                      if (a.nodeFqn) {
                        newPolicies.set(a.nodeFqn, {
                          source: 'direct_profile',
                          profileId: request.profileId,
                          profileName,
                          status: 'assigned',
                          freshness: {}, schema: {}, volume: {}, anomaly: {},
                          quality: {}, ingestion: {}, bi: {}, orchestration: {}, transform: {}, infrastructure: {},
                        });
                      }
                    }
                    setNodeSLAs(newPolicies);
                  }
                } else {
                  const errText = await res.text().catch(() => '');
                  let errMsg = `Failed to apply SLA (${res.status})`;
                  try {
                    const errData = JSON.parse(errText);
                    errMsg = errData.error || errMsg;
                    console.error('[Policy] Assignment failed:', res.status, errData);
                  } catch {
                    console.error('[Policy] Assignment failed:', res.status, errText.slice(0, 500));
                  }
                  toast.error(errMsg);
                }
              } catch (err) {
                console.error('[Policy] Error assigning:', err);
                toast.error('Failed to apply SLA');
              } finally {
                setPolicySaving(false);
              }
            }}
            onApplyBulkDiscovery={async (entries) => {
              setPolicySaving(true);
              try {
                // Use /api/lineage/discovery which upserts profiles + assignments in one call
                // (the /api/schedule/policies/assign endpoint requires pre-existing profiles)
                const discoveryResults = entries.map((entry) => ({
                  nodeFqn: entry.nodeFqn,
                  freshness: entry.overrides.freshnessConfig || null,
                  volume: entry.overrides.volumeConfig || null,
                  quality: entry.overrides.qualityConfig || null,
                  schema: entry.overrides.schemaConfig || null,
                }));

                console.log('[Policy] Bulk discovery payload:', discoveryResults.map(r => ({ fqn: r.nodeFqn, hasF: !!r.freshness, hasV: !!r.volume, hasQ: !!r.quality, hasS: !!r.schema })));
                const res = await fetch('/api/lineage/discovery', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ results: discoveryResults }),
                });

                if (res.ok) {
                  const data = await res.json();
                  const persisted = data.persisted || 0;
                  console.log('[Policy] Bulk discovery persisted:', persisted);
                  toast.success(`SLA applied to ${persisted} node${persisted !== 1 ? 's' : ''}`);
                } else {
                  const errText = await res.text().catch(() => '');
                  console.error('[Policy] Bulk discovery failed:', res.status, errText);
                  toast.error('Failed to apply SLAs');
                }

                // Re-fetch resolved policies
                try {
                  const nodesPayload = (lineageData?.nodes || []).map((n) => ({
                    fqn: n.fullName || n.name,
                    domain: n.layer?.toLowerCase() || 'warehouse',
                    criticality: n.criticality?.toLowerCase() || 'medium',
                  }));
                  const resolveRes = await fetch('/api/schedule/policies/resolve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ nodes: nodesPayload, stackId }),
                  });
                  if (resolveRes.ok) {
                    const resolveData = await resolveRes.json();
                    const policies = resolveData.policies || {};
                    const map = new Map<string, EffectiveSLAPolicy>();
                    const assigned: string[] = [];
                    for (const [fqn, pol] of Object.entries(policies)) {
                      if ((pol as any).status !== 'none') {
                        map.set(fqn, pol as EffectiveSLAPolicy);
                        assigned.push(fqn);
                      }
                    }
                    console.log('[Policy] Resolve after bulk: total policies =', Object.keys(policies).length, ', assigned =', assigned.length, ', assigned FQNs:', assigned);
                    const publicNodes = nodesPayload.filter(n => n.fqn.includes('.public.'));
                    console.log('[Policy] Resolve: public.* nodes in payload:', publicNodes.map(n => n.fqn));
                    // Check which stored FQNs have matching policies
                    const storedFqns = ['acme-484520.public.customers', 'acme-484520.public.events', 'acme-484520.public.orders', 'acme-484520.public.products'];
                    for (const fqn of storedFqns) {
                      console.log(`[Policy] Resolve result for ${fqn}:`, policies[fqn] || 'NOT IN RESPONSE');
                    }
                    setNodeSLAs(map);
                  }
                } catch {
                  // Non-critical
                }
              } catch (err) {
                console.error('[Policy] Bulk assign error:', err);
                toast.error('Failed to apply SLAs');
              } finally {
                setPolicySaving(false);
              }
            }}
            onClose={() => {
              setSlaMode(false);
              setSlaSelectedNodeIds(new Set());
              setSlaDiscoveryDefaults(null);
            }}
            onClearSelection={() => setSlaSelectedNodeIds(new Set())}
          />
        )}

        {/* Side panel - Node details */}
        {!slaMode && activeTab !== 'control-plane' && selectedNode && !selectedEdge && (
          (selectedNode.category === 'dag' || selectedNode.category === 'task') ? (
            <div className="w-80 border-l border-[var(--subtle-border)] bg-[var(--surface-sunken)] p-4 overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[15px] font-medium text-[var(--text)]">
                  {selectedNode.category === 'dag' ? 'DAG Details' : 'Task Details'}
                </h3>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 hover:bg-[var(--subtle-bg)] rounded"
                >
                  <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Name</label>
                  <p className="text-[13px] text-[var(--text)] font-mono mt-1 break-all">{selectedNode.name}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Type</label>
                    <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{selectedNode.category}</p>
                  </div>
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Layer</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.layer}</p>
                  </div>
                </div>

                {/* Run summary */}
                {selectedNode.runSummary && (
                  <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] space-y-3">
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Run Summary</label>
                    {selectedNode.runSummary.lastRunState && (
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`
                          px-2 py-0.5 text-[11px] font-medium rounded
                          ${selectedNode.runSummary.lastRunState === 'success'
                            ? 'bg-emerald-500/20 text-emerald-300'
                            : selectedNode.runSummary.lastRunState === 'failed'
                            ? 'bg-red-500/20 text-red-300'
                            : 'bg-blue-500/20 text-blue-300'}
                        `}>
                          {selectedNode.runSummary.lastRunState}
                        </span>
                        {selectedNode.runSummary.lastRunDate && (
                          <span className="text-[11px] text-[var(--muted)]">
                            {new Date(selectedNode.runSummary.lastRunDate).toLocaleString()}
                          </span>
                        )}
                      </div>
                    )}
                    {selectedNode.runSummary.successRate !== undefined && (
                      <div>
                        <div className="flex items-center justify-between text-[11px] text-[var(--muted)] mb-1">
                          <span>Success Rate</span>
                          <span>{Math.round(selectedNode.runSummary.successRate)}%</span>
                        </div>
                        <div className="h-1.5 bg-[var(--overlay-medium)] rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${selectedNode.runSummary.successRate}%`,
                              backgroundColor: selectedNode.runSummary.successRate >= 80 ? '#10B981' : selectedNode.runSummary.successRate >= 60 ? '#F59E0B' : '#EF4444',
                            }}
                          />
                        </div>
                      </div>
                    )}
                    {selectedNode.runSummary.avgDurationMinutes !== undefined && (
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] text-[var(--muted)]">Avg Duration</span>
                        <span className="text-[11px] text-[var(--text)]">{selectedNode.runSummary.avgDurationMinutes.toFixed(1)} min</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Orchestration dependencies (control-plane edges) */}
                {(() => {
                  const allEdges = lineageData?.edges || [];
                  const nodeMap = new Map((lineageData?.nodes || []).map(n => [n.id, n]));

                  // For DAGs: tasks contained in this DAG
                  // For Tasks: upstream deps (what this depends on) + downstream deps (what depends on this)
                  const controlEdges = allEdges.filter(
                    e => e.plane === 'control' && (e.source === selectedNode.id || e.target === selectedNode.id)
                  );

                  if (selectedNode.category === 'dag') {
                    // DAG → show contained tasks
                    const tasks = controlEdges
                      .filter(e => e.source === selectedNode.id)
                      .map(e => nodeMap.get(e.target))
                      .filter((n): n is UnifiedLineageNode => !!n && n.category === 'task');

                    if (tasks.length === 0) return null;
                    return (
                      <div>
                        <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Tasks ({tasks.length})</label>
                        <div className="mt-2 space-y-1.5">
                          {tasks.map(task => (
                            <button
                              key={task.id}
                              onClick={() => handleNavigateToNode(task.id)}
                              className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-left transition-colors"
                            >
                              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                              <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{task.name}</span>
                              {task.runSummary?.lastRunState && (
                                <span className={`
                                  px-1.5 py-0.5 text-[10px] font-medium rounded
                                  ${task.runSummary.lastRunState === 'success' ? 'bg-emerald-500/20 text-emerald-300'
                                    : task.runSummary.lastRunState === 'failed' ? 'bg-red-500/20 text-red-300'
                                    : 'bg-blue-500/20 text-blue-300'}
                                `}>
                                  {task.runSummary.lastRunState}
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  }

                  // Task: show parent DAG, upstream tasks, downstream tasks
                  const parentDag = controlEdges
                    .filter(e => e.target === selectedNode.id)
                    .map(e => nodeMap.get(e.source))
                    .find(n => n?.category === 'dag');

                  const upstreamTasks = controlEdges
                    .filter(e => e.target === selectedNode.id)
                    .map(e => nodeMap.get(e.source))
                    .filter((n): n is UnifiedLineageNode => !!n && n.category === 'task');

                  const downstreamTasks = controlEdges
                    .filter(e => e.source === selectedNode.id)
                    .map(e => nodeMap.get(e.target))
                    .filter((n): n is UnifiedLineageNode => !!n && n.category === 'task');

                  const hasAny = parentDag || upstreamTasks.length > 0 || downstreamTasks.length > 0;
                  if (!hasAny) return null;

                  return (
                    <div className="space-y-3">
                      {parentDag && (
                        <div>
                          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Parent DAG</label>
                          <button
                            onClick={() => handleNavigateToNode(parentDag.id)}
                            className="w-full flex items-center gap-2 px-2 py-1.5 mt-1 rounded bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-left transition-colors"
                          >
                            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.dag.color }} />
                            <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{parentDag.name}</span>
                          </button>
                        </div>
                      )}
                      {upstreamTasks.length > 0 && (
                        <div>
                          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Depends On ({upstreamTasks.length})</label>
                          <div className="mt-2 space-y-1.5">
                            {upstreamTasks.map(task => (
                              <button
                                key={task.id}
                                onClick={() => handleNavigateToNode(task.id)}
                                className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-left transition-colors"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{task.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                      {downstreamTasks.length > 0 && (
                        <div>
                          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Required By ({downstreamTasks.length})</label>
                          <div className="mt-2 space-y-1.5">
                            {downstreamTasks.map(task => (
                              <button
                                key={task.id}
                                onClick={() => handleNavigateToNode(task.id)}
                                className="w-full flex items-center gap-2 px-2 py-1.5 rounded bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-left transition-colors"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS.task.color }} />
                                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{task.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* Cross-linked data assets with data-plane lineage context */}
                {(() => {
                  const allEdges = lineageData?.edges || [];
                  const crossEdges = allEdges.filter(
                    e => e.plane === 'cross' && (e.source === selectedNode.id || e.target === selectedNode.id)
                  );
                  if (crossEdges.length === 0) return null;
                  const nodeMap = new Map((lineageData?.nodes || []).map(n => [n.id, n]));
                  return (
                    <div>
                      <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Data Assets ({crossEdges.length})</label>
                      <div className="mt-2 space-y-2">
                        {crossEdges.map(edge => {
                          const linkedId = edge.source === selectedNode.id ? edge.target : edge.source;
                          const linked = nodeMap.get(linkedId);
                          if (!linked) return null;

                          // Find data-plane neighbors of this linked table
                          const dataUpstream = allEdges
                            .filter(e => e.plane === 'data' && e.target === linkedId)
                            .map(e => nodeMap.get(e.source))
                            .filter((n): n is UnifiedLineageNode => !!n);
                          const dataDownstream = allEdges
                            .filter(e => e.plane === 'data' && e.source === linkedId)
                            .map(e => nodeMap.get(e.target))
                            .filter((n): n is UnifiedLineageNode => !!n);

                          return (
                            <div key={edge.id} className="p-2 rounded-lg bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
                              <button
                                onClick={() => handleNavigateToNode(linkedId)}
                                className="w-full flex items-center gap-2 text-left"
                              >
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: CATEGORY_VISUALS[linked.category]?.color || '#6366F1' }} />
                                <span className="text-[12px] text-[var(--text)] font-mono truncate flex-1">{linked.name}</span>
                                <span className="text-[10px] text-[var(--text-faint)] capitalize">{edge.edgeType.replace(/_/g, ' ')}</span>
                              </button>
                              {/* Data-plane lineage for this asset */}
                              {(dataUpstream.length > 0 || dataDownstream.length > 0) && (
                                <div className="mt-1.5 pt-1.5 border-t border-[var(--border-faint)] space-y-1">
                                  {dataUpstream.length > 0 && (
                                    <div className="flex items-start gap-1.5">
                                      <span className="text-[10px] text-[var(--text-faint)] shrink-0 mt-0.5">from</span>
                                      <div className="flex flex-wrap gap-1">
                                        {dataUpstream.map(n => (
                                          <button
                                            key={n.id}
                                            onClick={() => handleNavigateToNode(n.id)}
                                            className="px-1.5 py-0.5 text-[10px] text-blue-300/70 bg-blue-500/10 rounded hover:bg-blue-500/20 transition-colors font-mono truncate max-w-[120px]"
                                          >
                                            {n.name}
                                          </button>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                  {dataDownstream.length > 0 && (
                                    <div className="flex items-start gap-1.5">
                                      <span className="text-[10px] text-[var(--text-faint)] shrink-0 mt-0.5">to</span>
                                      <div className="flex flex-wrap gap-1">
                                        {dataDownstream.map(n => (
                                          <button
                                            key={n.id}
                                            onClick={() => handleNavigateToNode(n.id)}
                                            className="px-1.5 py-0.5 text-[10px] text-emerald-300/70 bg-emerald-500/10 rounded hover:bg-emerald-500/20 transition-colors font-mono truncate max-w-[120px]"
                                          >
                                            {n.name}
                                          </button>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}

                {selectedNode.description && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Description</label>
                    <p className="text-[13px] text-[var(--text-tertiary)] mt-1">{selectedNode.description}</p>
                  </div>
                )}
                {selectedNode.owner && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Owner</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.owner}</p>
                  </div>
                )}
                {selectedNode.tags && selectedNode.tags.length > 0 && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Tags</label>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {selectedNode.tags.map(tag => (
                        <span key={tag} className="px-2 py-0.5 text-[10px] bg-[var(--overlay-medium)] text-[var(--text-tertiary)] rounded">{tag}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : isToolCategory(selectedNode.category) ? (
            <div className="w-80 border-l border-[var(--subtle-border)] bg-[var(--surface-sunken)] p-4 overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-[15px] font-medium text-[var(--text)]">Tool Details</h3>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 hover:bg-[var(--subtle-bg)] rounded"
                >
                  <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="space-y-4">
                <div>
                  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Name</label>
                  <p className="text-[13px] text-[var(--text)] font-mono mt-1 break-all">{selectedNode.fullName || selectedNode.name}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Type</label>
                    <p className="text-[13px] text-[var(--text)] mt-1 capitalize">{selectedNode.category}</p>
                  </div>
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Layer</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.layer}</p>
                  </div>
                </div>
                {selectedNode.toolType && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Tool Type</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.toolType}</p>
                  </div>
                )}
                {selectedNode.status && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Status</label>
                    <p className="text-[13px] text-[var(--text)] mt-1">{selectedNode.status}</p>
                  </div>
                )}
                {selectedNode.healthScore !== undefined && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Health Score</label>
                    <div className="flex items-center gap-2 mt-1">
                      <div className="flex-1 h-2 bg-[var(--overlay-medium)] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${selectedNode.healthScore}%`,
                            backgroundColor: selectedNode.healthScore >= 80 ? '#10B981' : selectedNode.healthScore >= 60 ? '#F59E0B' : '#EF4444',
                          }}
                        />
                      </div>
                      <span className="text-[13px] text-[var(--text)]">{Math.round(selectedNode.healthScore)}%</span>
                    </div>
                  </div>
                )}
                {(selectedNode.findingsCount ?? 0) > 0 && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Findings</label>
                    <div className="flex items-center gap-2 mt-1">
                      {(selectedNode.criticalCount ?? 0) > 0 && (
                        <span className="px-2 py-1 text-[11px] bg-red-500/20 text-red-400 rounded">{selectedNode.criticalCount} Critical</span>
                      )}
                      {(selectedNode.highCount ?? 0) > 0 && (
                        <span className="px-2 py-1 text-[11px] bg-orange-500/20 text-orange-400 rounded">{selectedNode.highCount} High</span>
                      )}
                    </div>
                  </div>
                )}
                {selectedNode.description && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Description</label>
                    <p className="text-[13px] text-[var(--text-tertiary)] mt-1">{selectedNode.description}</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <DataAssetDetailPanel
              key={selectedNode.id}
              node={selectedNode}
              allNodes={panelNodes}
              allEdges={panelEdges}
              stackId={stackId || ''}
              onClose={() => setSelectedNode(null)}
              onNodeNavigate={handleNavigateToNode}
              onCreateSingleMonitor={handleCreateSingleMonitor}
              onCreateMultiMonitor={handleCreateMultiMonitor}
              slaInfo={(() => {
                const fqn = selectedNode.fullName || selectedNode.name;
                const p = nodeSLAs.get(fqn);
                if (!p) return null;
                return {
                  profileName: p.profileName || null,
                  status: p.status as 'assigned' | 'inherited' | 'override' | 'none',
                  source: p.source || undefined,
                };
              })()}
              onEditSLA={(nodeId, discoveryDefaults) => {
                setSlaMode(true);
                // Find the engine view node ID (without lineage- prefix)
                const viewNodeId = nodeId.replace('lineage-', '');
                setSlaSelectedNodeIds(new Set([viewNodeId]));
                setSlaDiscoveryDefaults(discoveryDefaults || null);
                setSelectedNode(null);
              }}
            />
          )
        )}
      </div>

      {/* Multi Monitor modal */}
      <MultiMonitorModal
        open={multiMonitorModalOpen}
        onClose={() => { setMultiMonitorModalOpen(false); setMultiMonitorPreMeta(undefined); }}
        onComplete={() => invalidateCache('/api/schedule')}
        stackId={stackId || undefined}
        preselectedNodeIds={multiMonitorPreselect}
        preselectedNodeMeta={multiMonitorPreMeta}
      />

      {/* AI Prompt Monitor modal */}
      <CreateTaskModal
        open={promptModalOpen}
        onClose={() => setPromptModalOpen(false)}
        onComplete={() => invalidateCache('/api/schedule')}
        stackId={stackId || undefined}
        initialMode="prompt"
      />

      {/* SLA Profile modal */}
      {selectedSlaNodeId != null && (() => {
        // Resolve node name and FQN from rendered view or unified data
        const viewNode = renderedView?.nodes.find(n => n.id === selectedSlaNodeId);
        const unifiedNode = lineageData?.nodes.find(n => n.id === selectedSlaNodeId);
        const fqn = viewNode?.metadata?.fqn || viewNode?.name || unifiedNode?.fullName || unifiedNode?.name || selectedSlaNodeId;
        const displayName = viewNode?.name || unifiedNode?.name || selectedSlaNodeId;
        const policy = nodeSLAs.get(fqn);
        if (!policy) return null;
        return (
          <SlaProfileModal
            nodeId={selectedSlaNodeId}
            nodeName={displayName}
            slaPolicy={policy}
            onClose={() => setSelectedSlaNodeId(null)}
            onEdit={(nodeId) => {
              setSlaMode(true);
              const viewNodeId = nodeId.replace('lineage-', '');
              setSlaSelectedNodeIds(new Set([viewNodeId]));
            }}
          />
        );
      })()}
    </div>
  );
}

export default function LineagePage() {
  return (
    <Suspense fallback={<div className="h-[calc(100vh-56px)] flex items-center justify-center"><div className="w-6 h-6 border-2 border-[var(--overlay-strong)] border-t-[var(--text-tertiary)] rounded-full animate-spin" /></div>}>
      <LineagePageInner />
    </Suspense>
  );
}
