'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { PipelineNode, getToolById } from '@/components/pipeline/types';

// Cache TTL: 5 minutes
const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_KEY = 'pallisade_sources_cache';

interface TableInfo {
  name: string;
  schema: string;
  dataset?: string;
  database?: string;
  rowCount?: number | null;
  columns?: number | null;
  type?: string; // TABLE, VIEW, MATERIALIZED VIEW, etc.
  lastUpdated?: string;
}

interface DbtModel {
  name: string;
  schema: string;
  materialization: string;
  description?: string;
  tags?: string[];
  testCount?: number;
}

interface ConnectorInfo {
  name: string;
  status: string;
  lastSync?: string;
}

interface SourceData {
  tables: TableInfo[];
  models: DbtModel[];
  connectors: ConnectorInfo[];
  datasets: string[];
  source?: string;
  connected?: boolean;
  error?: string;
  message?: string; // Helpful message explaining the status
  fetchedAt?: number;
}

interface CacheEntry {
  data: Record<string, SourceData>;
  nodes: PipelineNode[];
  stackId: string;
  timestamp: number;
}

// Load cache from localStorage
function loadCache(): CacheEntry | null {
  if (typeof window === 'undefined') return null;
  try {
    const cached = localStorage.getItem(CACHE_KEY);
    if (!cached) return null;
    const entry: CacheEntry = JSON.parse(cached);
    // Check if cache is still valid
    if (Date.now() - entry.timestamp < CACHE_TTL_MS) {
      return entry;
    }
    // Cache expired
    localStorage.removeItem(CACHE_KEY);
    return null;
  } catch {
    return null;
  }
}

// Save cache to localStorage
function saveCache(data: Record<string, SourceData>, nodes: PipelineNode[], stackId: string): void {
  if (typeof window === 'undefined') return;
  try {
    const entry: CacheEntry = {
      data,
      nodes,
      stackId,
      timestamp: Date.now(),
    };
    localStorage.setItem(CACHE_KEY, JSON.stringify(entry));
  } catch {
    // localStorage might be full or disabled
  }
}

export default function SourcesPage() {
  const [nodes, setNodes] = useState<PipelineNode[]>([]);
  const [currentStackId, setCurrentStackId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [nodeData, setNodeData] = useState<Record<string, SourceData>>({});
  const [loadingData, setLoadingData] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'tables' | 'models' | 'connectors'>('tables');
  const [searchQuery, setSearchQuery] = useState('');
  const initializedRef = useRef(false);

  // Load node data function
  const loadNodeData = useCallback(async (nodeId: string, stackId: string, forceRefresh = false) => {
    // Check if already have data and not forcing refresh
    if (nodeData[nodeId] && !forceRefresh) return;
    
    setLoadingData(nodeId);
    try {
      const res = await fetch(`/api/pipeline/${stackId}/nodes/${nodeId}/tables`);
      if (res.ok) {
        const data = await res.json();
        const newData: SourceData = {
          tables: data.tables || [],
          models: data.models || [],
          connectors: data.connectors || [],
          datasets: data.datasets || [],
          source: data.source,
          connected: data.connected,
          message: data.message,
          fetchedAt: Date.now(),
        };
        setNodeData((prev) => {
          const updated = { ...prev, [nodeId]: newData };
          // Save to cache
          saveCache(updated, nodes, stackId);
          return updated;
        });
      } else {
        const errorData = await res.json().catch(() => ({}));
        setNodeData((prev) => ({
          ...prev,
          [nodeId]: { 
            tables: [], 
            models: [], 
            connectors: [], 
            datasets: [],
            error: errorData.error || 'Failed to fetch data',
            fetchedAt: Date.now(),
          },
        }));
      }
    } catch {
      setNodeData((prev) => ({
        ...prev,
        [nodeId]: { 
          tables: [], 
          models: [], 
          connectors: [], 
          datasets: [],
          error: 'Connection failed',
          fetchedAt: Date.now(),
        },
      }));
    } finally {
      setLoadingData(null);
    }
  }, [nodeData, nodes]);

  // Get the best default tab for a given node
  const getDefaultTab = (node: PipelineNode): 'tables' | 'models' | 'connectors' => {
    if (node.toolType === 'dbt_cloud' || node.toolType === 'dbt_core') return 'models';
    if (node.toolType === 'fivetran' || node.toolType === 'airbyte' || node.toolType === 'stitch') return 'connectors';
    return 'tables';
  };

  // Initialize from cache or fetch fresh data
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;

    const initialize = async () => {
      // Try to load from cache first
      const cached = loadCache();

      if (cached) {
        setNodes(cached.nodes);
        setCurrentStackId(cached.stackId);
        setNodeData(cached.data);

        // Auto-select first node
        const firstConnected = cached.nodes.find((n: PipelineNode) =>
          n.status === 'ACTIVE' || n.status === 'CONNECTED'
        ) || cached.nodes[0];

        if (firstConnected) {
          setSelectedNode(firstConnected.id);
          setActiveTab(getDefaultTab(firstConnected));
        }
        setLoading(false);
        return;
      }

      // No cache, fetch fresh
      try {
        const res = await fetch('/api/pipeline');
        if (res.ok) {
          const data = await res.json();
          if (data.stack) {
            setCurrentStackId(data.stack.id);
            if (data.stack.nodes && data.stack.nodes.length > 0) {
              setNodes(data.stack.nodes);

              const firstConnected = data.stack.nodes.find((n: PipelineNode) =>
                n.status === 'ACTIVE' || n.status === 'CONNECTED'
              ) || data.stack.nodes[0];

              if (firstConnected) {
                setSelectedNode(firstConnected.id);
                setActiveTab(getDefaultTab(firstConnected));
              }
            }
          }
        }
      } catch (error) {
        console.error('Failed to load pipeline:', error);
      } finally {
        setLoading(false);
      }
    };

    initialize();
  }, []);

  // Load data when node is selected (only if not cached)
  useEffect(() => {
    if (selectedNode && currentStackId && !nodeData[selectedNode] && !loadingData) {
      loadNodeData(selectedNode, currentStackId);
    }
  }, [selectedNode, currentStackId, nodeData, loadNodeData, loadingData]);

  const handleSelectNode = (node: PipelineNode) => {
    setSelectedNode(node.id);
    setSearchQuery('');
    setActiveTab(getDefaultTab(node));
  };

  const handleRefresh = () => {
    if (selectedNode && currentStackId) {
      // Force refresh the selected node
      loadNodeData(selectedNode, currentStackId, true);
    }
  };

  const getStatusIndicator = (status: string) => {
    switch (status) {
      case 'ACTIVE':
      case 'CONNECTED':
        return <span className="w-2 h-2 rounded-full bg-emerald-500" />;
      case 'ERROR':
        return <span className="w-2 h-2 rounded-full bg-red-500" />;
      case 'TESTING':
        return <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />;
      default:
        return <span className="w-2 h-2 rounded-full bg-[var(--overlay-strong)]" />;
    }
  };

  const getToolName = (toolType: string) => {
    const tool = getToolById(toolType);
    return tool?.name || toolType;
  };

  const formatRowCount = (rowCount: number | null | undefined): string => {
    if (rowCount === null || rowCount === undefined) return '—';
    if (rowCount === 0) return '0';
    return rowCount.toLocaleString();
  };

  const selectedNodeObj = nodes.find((n) => n.id === selectedNode);
  const currentData = selectedNode ? nodeData[selectedNode] : null;

  // Get configured datasets from node config
  const getConfiguredDatasets = (node: PipelineNode): string[] => {
    if (!node.config) return [];
    const config = node.config as Record<string, unknown>;
    if (config.datasets && Array.isArray(config.datasets)) {
      return config.datasets as string[];
    }
    if (config.schemas && Array.isArray(config.schemas)) {
      return config.schemas as string[];
    }
    return [];
  };

  // Filter tables by search
  const filteredTables = currentData?.tables?.filter(t => 
    !searchQuery || 
    t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (t.schema && t.schema.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (t.dataset && t.dataset.toLowerCase().includes(searchQuery.toLowerCase()))
  ) || [];

  const filteredModels = currentData?.models?.filter(m =>
    !searchQuery ||
    m.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    m.schema.toLowerCase().includes(searchQuery.toLowerCase())
  ) || [];

  // Organize nodes by category
  const warehouses = nodes.filter((n) => n.layer === 'WAREHOUSE');
  const transformations = nodes.filter((n) => n.layer === 'TRANSFORMATION');
  const ingestion = nodes.filter((n) => n.layer === 'INGESTION');
  const reporting = nodes.filter((n) => n.layer === 'REPORTING');

  // Format cache age
  const getCacheAge = (): string | null => {
    if (!currentData?.fetchedAt) return null;
    const seconds = Math.floor((Date.now() - currentData.fetchedAt) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ago`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin w-6 h-6 border-2 border-[var(--text-faint)] border-t-[var(--text-tertiary)] rounded-full" />
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20">
        <div className="w-14 h-14 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)] flex items-center justify-center mx-auto mb-5">
          <svg className="w-7 h-7 text-[var(--text-faint)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375" />
          </svg>
        </div>
        <h1 className="text-xl font-semibold text-[var(--text)] mb-2">No data sources configured</h1>
        <p className="text-[var(--muted)] text-[14px] mb-6 max-w-md mx-auto">
          Configure your data warehouse, transformation tools, and other integrations in the Pipeline Builder to see what data is available.
        </p>
        <Link
          href="/dashboard/pipeline"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-[13px] font-medium transition-colors"
        >
          Open Pipeline Builder
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-56px)] -m-6">
      {/* Left Panel - Source List */}
      <div className="w-64 flex-shrink-0 border-r border-[var(--border-faint)] bg-[var(--surface-sunken)] flex flex-col">
        <div className="p-4 border-b border-[var(--border-faint)]">
          <h1 className="text-[15px] font-medium text-[var(--text)]">Data Sources</h1>
          <p className="text-[12px] text-[var(--muted)] mt-0.5">
            {nodes.filter((n) => n.status === 'ACTIVE' || n.status === 'CONNECTED').length} of {nodes.length} connected
          </p>
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {/* Warehouses */}
          {warehouses.length > 0 && (
            <div className="mb-3">
              <div className="px-4 py-1.5 text-[10px] font-medium text-[var(--muted)] uppercase tracking-wider">
                Warehouses
              </div>
              {warehouses.map((node) => (
                <button
                  key={node.id}
                  onClick={() => handleSelectNode(node)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    selectedNode === node.id
                      ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                      : 'text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)]'
                  }`}
                >
                  {getStatusIndicator(node.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium truncate">{node.name}</p>
                    <p className="text-[11px] text-[var(--muted)] truncate">{getToolName(node.toolType)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Transformation */}
          {transformations.length > 0 && (
            <div className="mb-3">
              <div className="px-4 py-1.5 text-[10px] font-medium text-[var(--muted)] uppercase tracking-wider">
                Transformation
              </div>
              {transformations.map((node) => (
                <button
                  key={node.id}
                  onClick={() => handleSelectNode(node)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    selectedNode === node.id
                      ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                      : 'text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)]'
                  }`}
                >
                  {getStatusIndicator(node.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium truncate">{node.name}</p>
                    <p className="text-[11px] text-[var(--muted)] truncate">{getToolName(node.toolType)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Ingestion */}
          {ingestion.length > 0 && (
            <div className="mb-3">
              <div className="px-4 py-1.5 text-[10px] font-medium text-[var(--muted)] uppercase tracking-wider">
                Ingestion
              </div>
              {ingestion.map((node) => (
                <button
                  key={node.id}
                  onClick={() => handleSelectNode(node)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    selectedNode === node.id
                      ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                      : 'text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)]'
                  }`}
                >
                  {getStatusIndicator(node.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium truncate">{node.name}</p>
                    <p className="text-[11px] text-[var(--muted)] truncate">{getToolName(node.toolType)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Reporting */}
          {reporting.length > 0 && (
            <div className="mb-3">
              <div className="px-4 py-1.5 text-[10px] font-medium text-[var(--muted)] uppercase tracking-wider">
                Reporting
              </div>
              {reporting.map((node) => (
                <button
                  key={node.id}
                  onClick={() => handleSelectNode(node)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    selectedNode === node.id
                      ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                      : 'text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)]'
                  }`}
                >
                  {getStatusIndicator(node.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium truncate">{node.name}</p>
                    <p className="text-[11px] text-[var(--muted)] truncate">{getToolName(node.toolType)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Configure Link */}
        <div className="p-3 border-t border-[var(--border-faint)]">
          <Link
            href="/dashboard/pipeline"
            className="flex items-center justify-center gap-2 w-full px-3 py-2 rounded-lg bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] text-[var(--text-tertiary)] hover:text-[var(--text)] text-[12px] font-medium transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.204-.107-.397.165-.71.505-.78.929l-.15.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.107-1.204l-.527-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            Configure Sources
          </Link>
        </div>
      </div>

      {/* Right Panel - Details */}
      <div className="flex-1 flex flex-col min-w-0 bg-[var(--bg)]">
        {selectedNodeObj ? (
          <>
            {/* Source Header */}
            <div className="px-6 py-4 border-b border-[var(--border-faint)]">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-3 mb-1">
                    <h2 className="text-lg font-medium text-[var(--text)]">{selectedNodeObj.name}</h2>
                    {getStatusIndicator(selectedNodeObj.status)}
                    {currentData?.source === 'demo' && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-400" title="Scanner service unavailable - showing sample data">
                        Demo Data
                      </span>
                    )}
                    {currentData?.source === 'live' && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400">
                        Live
                      </span>
                    )}
                    {currentData?.source === 'unconfigured' && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400">
                        Not Configured
                      </span>
                    )}
                    {currentData?.source === 'disconnected' && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-gray-500/10 text-gray-400">
                        Disconnected
                      </span>
                    )}
                    {currentData?.source === 'misconfigured' && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-400">
                        Configuration Error
                      </span>
                    )}
                    {currentData?.source === 'error' && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-400">
                        Connection Error
                      </span>
                    )}
                  </div>
                  <p className="text-[13px] text-[var(--muted)]">
                    {getToolName(selectedNodeObj.toolType)}
                    {selectedNodeObj.config && (selectedNodeObj.config as Record<string, unknown>).project_id ? (
                      <span> · {String((selectedNodeObj.config as Record<string, unknown>).project_id)}</span>
                    ) : null}
                    {selectedNodeObj.config && (selectedNodeObj.config as Record<string, unknown>).database ? (
                      <span> · {String((selectedNodeObj.config as Record<string, unknown>).database)}</span>
                    ) : null}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {getCacheAge() && (
                    <span className="text-[11px] text-[var(--text-faint)]">
                      Updated {getCacheAge()}
                    </span>
                  )}
                  <button
                    onClick={handleRefresh}
                    disabled={loadingData === selectedNode}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-colors disabled:opacity-50"
                  >
                    <svg className={`w-4 h-4 ${loadingData === selectedNode ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                    </svg>
                    Refresh
                  </button>
                  <Link
                    href="/dashboard/pipeline"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-colors"
                  >
                    Edit
                  </Link>
                </div>
              </div>

              {/* Show configured datasets/schemas */}
              {selectedNodeObj.config && getConfiguredDatasets(selectedNodeObj).length > 0 && (
                <div className="flex flex-wrap gap-2 mb-3">
                  {getConfiguredDatasets(selectedNodeObj).map((ds, i) => (
                    <span key={i} className="px-2 py-1 rounded bg-[var(--overlay-bg)] text-[11px] text-[var(--text-tertiary)] font-mono">
                      {ds}
                    </span>
                  ))}
                </div>
              )}

              {/* Status message banner */}
              {currentData?.message && currentData.source !== 'live' && (
                <div className={`flex items-center gap-2 px-3 py-2 rounded-lg mb-3 text-[12px] ${
                  currentData.source === 'demo' ? 'bg-amber-500/10 text-amber-300' :
                  currentData.source === 'unconfigured' ? 'bg-blue-500/10 text-blue-300' :
                  currentData.source === 'disconnected' ? 'bg-gray-500/10 text-gray-300' :
                  'bg-red-500/10 text-red-300'
                }`}>
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>{currentData.message}</span>
                  {currentData.source === 'unconfigured' && (
                    <Link href="/dashboard/pipeline" className="ml-auto underline hover:no-underline">
                      Configure
                    </Link>
                  )}
                </div>
              )}

              {/* Tabs */}
              <div className="flex items-center gap-4">
                <div className="flex gap-1">
                  <button
                    onClick={() => setActiveTab('tables')}
                    className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors ${
                      activeTab === 'tables'
                        ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                        : 'text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)]'
                    }`}
                  >
                    Tables {currentData?.tables && currentData.tables.length > 0 && `(${currentData.tables.length})`}
                  </button>
                  {(selectedNodeObj.toolType === 'dbt_cloud' || selectedNodeObj.toolType === 'dbt_core') && (
                    <button
                      onClick={() => setActiveTab('models')}
                      className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors ${
                        activeTab === 'models'
                          ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                          : 'text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)]'
                      }`}
                    >
                      Models {currentData?.models && currentData.models.length > 0 && `(${currentData.models.length})`}
                    </button>
                  )}
                  {(selectedNodeObj.toolType === 'fivetran' || selectedNodeObj.toolType === 'airbyte' || selectedNodeObj.toolType === 'stitch') && (
                    <button
                      onClick={() => setActiveTab('connectors')}
                      className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors ${
                        activeTab === 'connectors'
                          ? 'bg-[var(--hover-bg)] text-[var(--text)]'
                          : 'text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)]'
                      }`}
                    >
                      Connectors {currentData?.connectors && currentData.connectors.length > 0 && `(${currentData.connectors.length})`}
                    </button>
                  )}
                </div>

                {/* Search */}
                <div className="flex-1 max-w-xs">
                  <div className="relative">
                    <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-faint)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    <input
                      type="text"
                      placeholder="Search..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-9 pr-3 py-1.5 rounded-md bg-[var(--overlay-bg)] border border-[var(--subtle-border)] text-[12px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
              {loadingData === selectedNode ? (
                <div className="flex items-center justify-center h-64">
                  <div className="flex items-center gap-3 text-[var(--muted)]">
                    <div className="animate-spin w-5 h-5 border-2 border-[var(--text-faint)] border-t-[var(--text-tertiary)] rounded-full" />
                    <span className="text-[13px]">Loading data...</span>
                  </div>
                </div>
              ) : currentData?.error ? (
                <div className="flex items-center justify-center h-64">
                  <div className="text-center">
                    <svg className="w-10 h-10 text-red-500/50 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                    </svg>
                    <p className="text-[13px] text-[var(--muted)]">{currentData.error}</p>
                    <button
                      onClick={handleRefresh}
                      className="mt-3 text-[12px] text-[var(--muted)] hover:text-[var(--text)] underline"
                    >
                      Try again
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {/* Tables Tab */}
                  {activeTab === 'tables' && (
                    <div className="p-6">
                      {filteredTables.length > 0 ? (
                        <div className="border border-[var(--subtle-border)] rounded-lg overflow-hidden">
                          <table className="w-full">
                            <thead>
                              <tr className="border-b border-[var(--subtle-border)] bg-[var(--overlay-faint)]">
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">Table Name</th>
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">
                                  {selectedNodeObj.toolType === 'bigquery' ? 'Dataset' : 'Schema'}
                                </th>
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">Type</th>
                                <th className="text-right px-4 py-3 text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">Columns</th>
                                <th className="text-right px-4 py-3 text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">Row Count</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-white/[0.04]">
                              {filteredTables.map((table, i) => (
                                <tr key={i} className="hover:bg-[var(--overlay-faint)] transition-colors">
                                  <td className="px-4 py-3">
                                    <code className="text-[13px] text-[var(--text)]">{table.name}</code>
                                  </td>
                                  <td className="px-4 py-3">
                                    <code className="text-[13px] text-[var(--muted)]">{table.dataset || table.schema}</code>
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-medium ${
                                      table.type === 'VIEW' ? 'bg-purple-500/10 text-purple-400' :
                                      table.type === 'MATERIALIZED VIEW' ? 'bg-blue-500/10 text-blue-400' :
                                      table.type === 'EXTERNAL' ? 'bg-amber-500/10 text-amber-400' :
                                      'bg-[var(--hover-bg)] text-[var(--muted)]'
                                    }`}>
                                      {table.type || 'TABLE'}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-right">
                                    <span className="text-[13px] text-[var(--muted)]">{table.columns ?? '—'}</span>
                                  </td>
                                  <td className="px-4 py-3 text-right">
                                    <span className="text-[13px] text-[var(--muted)]">
                                      {formatRowCount(table.rowCount)}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <div className="text-center py-16 border border-[var(--border-faint)] border-dashed rounded-lg">
                          <svg className="w-10 h-10 text-[var(--text-faint)] mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125" />
                          </svg>
                          <p className="text-[13px] text-[var(--muted)]">
                            {searchQuery ? 'No tables match your search' : 'No tables found'}
                          </p>
                          {!searchQuery && (
                            <p className="text-[12px] text-[var(--text-faint)] mt-1">
                              Configure datasets in Pipeline Builder to discover tables
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Models Tab (for dbt) */}
                  {activeTab === 'models' && (
                    <div className="p-6">
                      {filteredModels.length > 0 ? (
                        <DbtModelsVisual models={filteredModels} />
                      ) : (
                        <div className="text-center py-16 border border-[var(--border-faint)] border-dashed rounded-lg">
                          <p className="text-[13px] text-[var(--muted)]">No dbt models found</p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Connectors Tab */}
                  {activeTab === 'connectors' && (
                    <div className="p-6">
                      {currentData?.connectors && currentData.connectors.length > 0 ? (
                        <div className="border border-[var(--subtle-border)] rounded-lg overflow-hidden">
                          <table className="w-full">
                            <thead>
                              <tr className="border-b border-[var(--subtle-border)] bg-[var(--overlay-faint)]">
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">Connector</th>
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">Status</th>
                                <th className="text-right px-4 py-3 text-[11px] font-medium text-[var(--muted)] uppercase tracking-wider">Last Sync</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-white/[0.04]">
                              {currentData.connectors.map((connector, i) => (
                                <tr key={i} className="hover:bg-[var(--overlay-faint)] transition-colors">
                                  <td className="px-4 py-3">
                                    <span className="text-[13px] text-[var(--text)]">{connector.name}</span>
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium ${
                                      connector.status === 'active' || connector.status === 'syncing' 
                                        ? 'bg-emerald-500/10 text-emerald-400' 
                                        : connector.status === 'paused' 
                                        ? 'bg-amber-500/10 text-amber-400'
                                        : 'bg-red-500/10 text-red-400'
                                    }`}>
                                      <span className={`w-1.5 h-1.5 rounded-full ${
                                        connector.status === 'active' || connector.status === 'syncing' 
                                          ? 'bg-emerald-500' 
                                          : connector.status === 'paused' 
                                          ? 'bg-amber-500'
                                          : 'bg-red-500'
                                      }`} />
                                      {connector.status}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-right">
                                    <span className="text-[13px] text-[var(--muted)]">{connector.lastSync ?? '—'}</span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <div className="text-center py-16 border border-[var(--border-faint)] border-dashed rounded-lg">
                          <p className="text-[13px] text-[var(--muted)]">No connectors found</p>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <p className="text-[13px] text-[var(--muted)]">Select a source to view details</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ==========================================
// dbt Models Visual Display
// ==========================================

const MATERIALIZATION_CONFIG: Record<string, { color: string; bg: string; icon: string }> = {
  table: { color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20', icon: 'M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125' },
  view: { color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20', icon: 'M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178zM15 12a3 3 0 11-6 0 3 3 0 016 0z' },
  incremental: { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20', icon: 'M3 4.5h14.25M3 9h9.75M3 13.5h9.75m4.5-4.5v12m0 0l-3.75-3.75M17.25 21L21 17.25' },
  ephemeral: { color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20', icon: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z' },
};

function DbtModelsVisual({ models }: { models: DbtModel[] }) {
  const [expandedSchema, setExpandedSchema] = useState<string | null>(null);

  // Group by schema
  const grouped: Record<string, DbtModel[]> = {};
  models.forEach((m) => {
    if (!grouped[m.schema]) grouped[m.schema] = [];
    grouped[m.schema].push(m);
  });
  const schemaNames = Object.keys(grouped).sort();

  // Stats
  const matCounts: Record<string, number> = {};
  models.forEach((m) => {
    matCounts[m.materialization] = (matCounts[m.materialization] || 0) + 1;
  });
  const totalTests = models.reduce((sum, m) => sum + (m.testCount ?? 0), 0);

  return (
    <div className="space-y-6">
      {/* Summary row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-faint)] p-4">
          <div className="text-[11px] text-[var(--muted)] uppercase tracking-wider mb-1">Models</div>
          <div className="text-2xl font-semibold text-[var(--text)]">{models.length}</div>
        </div>
        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-faint)] p-4">
          <div className="text-[11px] text-[var(--muted)] uppercase tracking-wider mb-1">Schemas</div>
          <div className="text-2xl font-semibold text-[var(--text)]">{schemaNames.length}</div>
        </div>
        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-faint)] p-4">
          <div className="text-[11px] text-[var(--muted)] uppercase tracking-wider mb-1">Tests</div>
          <div className="text-2xl font-semibold text-[var(--text)]">{totalTests}</div>
        </div>
        <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-faint)] p-4">
          <div className="text-[11px] text-[var(--muted)] uppercase tracking-wider mb-1">Materialization</div>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {Object.entries(matCounts).map(([mat, count]) => {
              const cfg = MATERIALIZATION_CONFIG[mat] || MATERIALIZATION_CONFIG.table;
              return (
                <span key={mat} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border ${cfg.bg} ${cfg.color}`}>
                  {count} {mat}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      {/* Schema groups */}
      {schemaNames.map((schema) => {
        const schemaModels = grouped[schema];
        const isExpanded = expandedSchema === null || expandedSchema === schema;

        return (
          <div key={schema} className="rounded-lg border border-[var(--subtle-border)] overflow-hidden">
            {/* Schema header */}
            <button
              onClick={() => setExpandedSchema(expandedSchema === schema ? null : schema)}
              className="w-full flex items-center justify-between px-5 py-3.5 bg-[var(--overlay-faint)] hover:bg-[var(--overlay-bg)] transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-orange-500/10 border border-orange-500/20 flex items-center justify-center">
                  <span className="text-[10px] font-bold text-orange-400">dbt</span>
                </div>
                <div className="text-left">
                  <div className="text-[13px] font-medium text-[var(--text)]">{schema}</div>
                  <div className="text-[11px] text-[var(--muted)]">{schemaModels.length} model{schemaModels.length !== 1 ? 's' : ''}</div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {/* Mini materialization summary */}
                <div className="flex gap-1.5">
                  {Object.entries(
                    schemaModels.reduce<Record<string, number>>((acc, m) => {
                      acc[m.materialization] = (acc[m.materialization] || 0) + 1;
                      return acc;
                    }, {})
                  ).map(([mat, count]) => {
                    const cfg = MATERIALIZATION_CONFIG[mat] || MATERIALIZATION_CONFIG.table;
                    return (
                      <span key={mat} className={`w-5 h-5 rounded flex items-center justify-center text-[10px] font-medium ${cfg.bg} ${cfg.color}`} title={`${count} ${mat}`}>
                        {count}
                      </span>
                    );
                  })}
                </div>
                <svg className={`w-4 h-4 text-[var(--text-faint)] transition-transform ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </button>

            {/* Model cards */}
            {isExpanded && (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 p-4">
                {schemaModels.map((model) => {
                  const cfg = MATERIALIZATION_CONFIG[model.materialization] || MATERIALIZATION_CONFIG.table;
                  return (
                    <div
                      key={model.name}
                      className={`rounded-lg border p-4 hover:bg-[var(--overlay-faint)] transition-colors ${cfg.bg}`}
                    >
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <svg className={`w-4 h-4 flex-shrink-0 ${cfg.color}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={cfg.icon} />
                          </svg>
                          <code className="text-[13px] font-medium text-[var(--text)] truncate">{model.name}</code>
                        </div>
                        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded flex-shrink-0 ${cfg.color} bg-[var(--overlay-bg)]`}>
                          {model.materialization}
                        </span>
                      </div>
                      {model.description && (
                        <p className="text-[11px] text-[var(--muted)] mb-2 line-clamp-2">{model.description}</p>
                      )}
                      <div className="flex items-center gap-3 mt-auto">
                        {model.tags && model.tags.length > 0 && (
                          <div className="flex gap-1 flex-wrap">
                            {model.tags.slice(0, 3).map((tag) => (
                              <span key={tag} className="px-1.5 py-0.5 rounded bg-[var(--hover-bg)] text-[10px] text-[var(--muted)]">{tag}</span>
                            ))}
                          </div>
                        )}
                        {(model.testCount ?? 0) > 0 && (
                          <div className="flex items-center gap-1 ml-auto">
                            <svg className="w-3 h-3 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            <span className="text-[10px] text-emerald-400">{model.testCount} tests</span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
