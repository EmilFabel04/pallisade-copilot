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
        return <span className="w-2 h-2 rounded-full bg-white/20" />;
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
        <div className="animate-spin w-6 h-6 border-2 border-white/20 border-t-white/60 rounded-full" />
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20">
        <div className="w-14 h-14 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mx-auto mb-5">
          <svg className="w-7 h-7 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375" />
          </svg>
        </div>
        <h1 className="text-xl font-semibold text-white mb-2">No data sources configured</h1>
        <p className="text-white/50 text-[14px] mb-6 max-w-md mx-auto">
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
      <div className="w-64 flex-shrink-0 border-r border-white/[0.04] bg-[#030303] flex flex-col">
        <div className="p-4 border-b border-white/[0.04]">
          <h1 className="text-[15px] font-medium text-white">Data Sources</h1>
          <p className="text-[12px] text-white/40 mt-0.5">
            {nodes.filter((n) => n.status === 'ACTIVE' || n.status === 'CONNECTED').length} of {nodes.length} connected
          </p>
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {/* Warehouses */}
          {warehouses.length > 0 && (
            <div className="mb-3">
              <div className="px-4 py-1.5 text-[10px] font-medium text-white/40 uppercase tracking-wider">
                Warehouses
              </div>
              {warehouses.map((node) => (
                <button
                  key={node.id}
                  onClick={() => handleSelectNode(node)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    selectedNode === node.id
                      ? 'bg-white/[0.08] text-white'
                      : 'text-white/70 hover:bg-white/[0.04] hover:text-white'
                  }`}
                >
                  {getStatusIndicator(node.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium truncate">{node.name}</p>
                    <p className="text-[11px] text-white/40 truncate">{getToolName(node.toolType)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Transformation */}
          {transformations.length > 0 && (
            <div className="mb-3">
              <div className="px-4 py-1.5 text-[10px] font-medium text-white/40 uppercase tracking-wider">
                Transformation
              </div>
              {transformations.map((node) => (
                <button
                  key={node.id}
                  onClick={() => handleSelectNode(node)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    selectedNode === node.id
                      ? 'bg-white/[0.08] text-white'
                      : 'text-white/70 hover:bg-white/[0.04] hover:text-white'
                  }`}
                >
                  {getStatusIndicator(node.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium truncate">{node.name}</p>
                    <p className="text-[11px] text-white/40 truncate">{getToolName(node.toolType)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Ingestion */}
          {ingestion.length > 0 && (
            <div className="mb-3">
              <div className="px-4 py-1.5 text-[10px] font-medium text-white/40 uppercase tracking-wider">
                Ingestion
              </div>
              {ingestion.map((node) => (
                <button
                  key={node.id}
                  onClick={() => handleSelectNode(node)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    selectedNode === node.id
                      ? 'bg-white/[0.08] text-white'
                      : 'text-white/70 hover:bg-white/[0.04] hover:text-white'
                  }`}
                >
                  {getStatusIndicator(node.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium truncate">{node.name}</p>
                    <p className="text-[11px] text-white/40 truncate">{getToolName(node.toolType)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Reporting */}
          {reporting.length > 0 && (
            <div className="mb-3">
              <div className="px-4 py-1.5 text-[10px] font-medium text-white/40 uppercase tracking-wider">
                Reporting
              </div>
              {reporting.map((node) => (
                <button
                  key={node.id}
                  onClick={() => handleSelectNode(node)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    selectedNode === node.id
                      ? 'bg-white/[0.08] text-white'
                      : 'text-white/70 hover:bg-white/[0.04] hover:text-white'
                  }`}
                >
                  {getStatusIndicator(node.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium truncate">{node.name}</p>
                    <p className="text-[11px] text-white/40 truncate">{getToolName(node.toolType)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Configure Link */}
        <div className="p-3 border-t border-white/[0.04]">
          <Link
            href="/dashboard/pipeline"
            className="flex items-center justify-center gap-2 w-full px-3 py-2 rounded-lg bg-white/[0.04] hover:bg-white/[0.06] text-white/60 hover:text-white text-[12px] font-medium transition-colors"
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
      <div className="flex-1 flex flex-col min-w-0 bg-[#020202]">
        {selectedNodeObj ? (
          <>
            {/* Source Header */}
            <div className="px-6 py-4 border-b border-white/[0.04]">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-3 mb-1">
                    <h2 className="text-lg font-medium text-white">{selectedNodeObj.name}</h2>
                    {getStatusIndicator(selectedNodeObj.status)}
                    {currentData?.source === 'demo' && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-400">
                        Demo Data
                      </span>
                    )}
                    {currentData?.source === 'live' && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400">
                        Live
                      </span>
                    )}
                  </div>
                  <p className="text-[13px] text-white/40">
                    {getToolName(selectedNodeObj.toolType)}
                    {selectedNodeObj.config && (selectedNodeObj.config as Record<string, unknown>).project_id && (
                      <span> · {(selectedNodeObj.config as Record<string, unknown>).project_id as string}</span>
                    )}
                    {selectedNodeObj.config && (selectedNodeObj.config as Record<string, unknown>).database && (
                      <span> · {(selectedNodeObj.config as Record<string, unknown>).database as string}</span>
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {getCacheAge() && (
                    <span className="text-[11px] text-white/30">
                      Updated {getCacheAge()}
                    </span>
                  )}
                  <button
                    onClick={handleRefresh}
                    disabled={loadingData === selectedNode}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] text-white/50 hover:text-white hover:bg-white/[0.04] transition-colors disabled:opacity-50"
                  >
                    <svg className={`w-4 h-4 ${loadingData === selectedNode ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                    </svg>
                    Refresh
                  </button>
                  <Link
                    href="/dashboard/pipeline"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] text-white/50 hover:text-white hover:bg-white/[0.04] transition-colors"
                  >
                    Edit
                  </Link>
                </div>
              </div>

              {/* Show configured datasets/schemas */}
              {selectedNodeObj.config && getConfiguredDatasets(selectedNodeObj).length > 0 && (
                <div className="flex flex-wrap gap-2 mb-3">
                  {getConfiguredDatasets(selectedNodeObj).map((ds, i) => (
                    <span key={i} className="px-2 py-1 rounded bg-white/[0.04] text-[11px] text-white/60 font-mono">
                      {ds}
                    </span>
                  ))}
                </div>
              )}

              {/* Tabs */}
              <div className="flex items-center gap-4">
                <div className="flex gap-1">
                  <button
                    onClick={() => setActiveTab('tables')}
                    className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors ${
                      activeTab === 'tables'
                        ? 'bg-white/[0.08] text-white'
                        : 'text-white/50 hover:text-white hover:bg-white/[0.04]'
                    }`}
                  >
                    Tables {currentData?.tables && currentData.tables.length > 0 && `(${currentData.tables.length})`}
                  </button>
                  {(selectedNodeObj.toolType === 'dbt_cloud' || selectedNodeObj.toolType === 'dbt_core') && (
                    <button
                      onClick={() => setActiveTab('models')}
                      className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors ${
                        activeTab === 'models'
                          ? 'bg-white/[0.08] text-white'
                          : 'text-white/50 hover:text-white hover:bg-white/[0.04]'
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
                          ? 'bg-white/[0.08] text-white'
                          : 'text-white/50 hover:text-white hover:bg-white/[0.04]'
                      }`}
                    >
                      Connectors {currentData?.connectors && currentData.connectors.length > 0 && `(${currentData.connectors.length})`}
                    </button>
                  )}
                </div>

                {/* Search */}
                <div className="flex-1 max-w-xs">
                  <div className="relative">
                    <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    <input
                      type="text"
                      placeholder="Search..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-9 pr-3 py-1.5 rounded-md bg-white/[0.04] border border-white/[0.06] text-[12px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.12]"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
              {loadingData === selectedNode ? (
                <div className="flex items-center justify-center h-64">
                  <div className="flex items-center gap-3 text-white/50">
                    <div className="animate-spin w-5 h-5 border-2 border-white/20 border-t-white/60 rounded-full" />
                    <span className="text-[13px]">Loading data...</span>
                  </div>
                </div>
              ) : currentData?.error ? (
                <div className="flex items-center justify-center h-64">
                  <div className="text-center">
                    <svg className="w-10 h-10 text-red-500/50 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                    </svg>
                    <p className="text-[13px] text-white/50">{currentData.error}</p>
                    <button
                      onClick={handleRefresh}
                      className="mt-3 text-[12px] text-white/40 hover:text-white underline"
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
                        <div className="border border-white/[0.06] rounded-lg overflow-hidden">
                          <table className="w-full">
                            <thead>
                              <tr className="border-b border-white/[0.06] bg-white/[0.02]">
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Table Name</th>
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">
                                  {selectedNodeObj.toolType === 'bigquery' ? 'Dataset' : 'Schema'}
                                </th>
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Type</th>
                                <th className="text-right px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Columns</th>
                                <th className="text-right px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Row Count</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-white/[0.04]">
                              {filteredTables.map((table, i) => (
                                <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                                  <td className="px-4 py-3">
                                    <code className="text-[13px] text-white">{table.name}</code>
                                  </td>
                                  <td className="px-4 py-3">
                                    <code className="text-[13px] text-white/50">{table.dataset || table.schema}</code>
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-medium ${
                                      table.type === 'VIEW' ? 'bg-purple-500/10 text-purple-400' :
                                      table.type === 'MATERIALIZED VIEW' ? 'bg-blue-500/10 text-blue-400' :
                                      table.type === 'EXTERNAL' ? 'bg-amber-500/10 text-amber-400' :
                                      'bg-white/[0.06] text-white/50'
                                    }`}>
                                      {table.type || 'TABLE'}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-right">
                                    <span className="text-[13px] text-white/50">{table.columns ?? '—'}</span>
                                  </td>
                                  <td className="px-4 py-3 text-right">
                                    <span className="text-[13px] text-white/50">
                                      {formatRowCount(table.rowCount)}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <div className="text-center py-16 border border-white/[0.04] border-dashed rounded-lg">
                          <svg className="w-10 h-10 text-white/15 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125" />
                          </svg>
                          <p className="text-[13px] text-white/40">
                            {searchQuery ? 'No tables match your search' : 'No tables found'}
                          </p>
                          {!searchQuery && (
                            <p className="text-[12px] text-white/25 mt-1">
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
                        <div className="border border-white/[0.06] rounded-lg overflow-hidden">
                          <table className="w-full">
                            <thead>
                              <tr className="border-b border-white/[0.06] bg-white/[0.02]">
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Model</th>
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Schema</th>
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Materialization</th>
                                <th className="text-right px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Tests</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-white/[0.04]">
                              {filteredModels.map((model, i) => (
                                <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                                  <td className="px-4 py-3">
                                    <code className="text-[13px] text-white">{model.name}</code>
                                    {model.description && (
                                      <p className="text-[11px] text-white/40 mt-0.5 max-w-md truncate">{model.description}</p>
                                    )}
                                  </td>
                                  <td className="px-4 py-3">
                                    <code className="text-[13px] text-white/50">{model.schema}</code>
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex px-2 py-0.5 rounded text-[11px] font-medium ${
                                      model.materialization === 'table' ? 'bg-blue-500/10 text-blue-400' :
                                      model.materialization === 'view' ? 'bg-purple-500/10 text-purple-400' :
                                      model.materialization === 'incremental' ? 'bg-emerald-500/10 text-emerald-400' :
                                      'bg-white/10 text-white/60'
                                    }`}>
                                      {model.materialization}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3 text-right">
                                    <span className="text-[13px] text-white/50">{model.testCount ?? 0}</span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <div className="text-center py-16 border border-white/[0.04] border-dashed rounded-lg">
                          <p className="text-[13px] text-white/40">No dbt models found</p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Connectors Tab */}
                  {activeTab === 'connectors' && (
                    <div className="p-6">
                      {currentData?.connectors && currentData.connectors.length > 0 ? (
                        <div className="border border-white/[0.06] rounded-lg overflow-hidden">
                          <table className="w-full">
                            <thead>
                              <tr className="border-b border-white/[0.06] bg-white/[0.02]">
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Connector</th>
                                <th className="text-left px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Status</th>
                                <th className="text-right px-4 py-3 text-[11px] font-medium text-white/50 uppercase tracking-wider">Last Sync</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-white/[0.04]">
                              {currentData.connectors.map((connector, i) => (
                                <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                                  <td className="px-4 py-3">
                                    <span className="text-[13px] text-white">{connector.name}</span>
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
                                    <span className="text-[13px] text-white/50">{connector.lastSync ?? '—'}</span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <div className="text-center py-16 border border-white/[0.04] border-dashed rounded-lg">
                          <p className="text-[13px] text-white/40">No connectors found</p>
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
              <p className="text-[13px] text-white/40">Select a source to view details</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
