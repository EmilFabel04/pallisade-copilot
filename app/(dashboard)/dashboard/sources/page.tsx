'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { PipelineNode, PipelineLayer, LAYER_COLORS, LAYER_LABELS, TOOLS, getToolById } from '@/components/pipeline/types';

interface TableInfo {
  name: string;
  schema: string;
  rowCount?: number;
  lastUpdated?: string;
}

interface SourceDetails {
  node: PipelineNode;
  tables?: TableInfo[];
  syncStatus?: string;
  lastSync?: string;
  error?: string;
}

export default function SourcesPage() {
  const [nodes, setNodes] = useState<PipelineNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedNode, setExpandedNode] = useState<string | null>(null);
  const [nodeDetails, setNodeDetails] = useState<Record<string, SourceDetails>>({});
  const [loadingDetails, setLoadingDetails] = useState<string | null>(null);

  // Load pipeline nodes
  useEffect(() => {
    loadPipelineNodes();
  }, []);

  const loadPipelineNodes = async () => {
    try {
      const res = await fetch('/api/pipeline');
      if (res.ok) {
        const data = await res.json();
        if (data.stack?.nodes) {
          setNodes(data.stack.nodes);
        }
      }
    } catch (error) {
      console.error('Failed to load pipeline:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadNodeDetails = async (node: PipelineNode) => {
    if (nodeDetails[node.id]) {
      setExpandedNode(expandedNode === node.id ? null : node.id);
      return;
    }

    setExpandedNode(node.id);
    setLoadingDetails(node.id);

    try {
      // Fetch tables/schemas for this node
      const res = await fetch(`/api/pipeline/${node.id}/tables`);
      if (res.ok) {
        const data = await res.json();
        setNodeDetails((prev) => ({
          ...prev,
          [node.id]: {
            node,
            tables: data.tables || [],
            syncStatus: data.status,
            lastSync: data.lastSync,
          },
        }));
      } else {
        setNodeDetails((prev) => ({
          ...prev,
          [node.id]: {
            node,
            tables: [],
            error: 'Could not fetch details',
          },
        }));
      }
    } catch {
      setNodeDetails((prev) => ({
        ...prev,
        [node.id]: {
          node,
          tables: [],
          error: 'Failed to connect',
        },
      }));
    } finally {
      setLoadingDetails(null);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ACTIVE':
      case 'CONNECTED':
        return 'bg-emerald-500';
      case 'ERROR':
        return 'bg-red-500';
      case 'TESTING':
        return 'bg-amber-500';
      default:
        return 'bg-white/30';
    }
  };

  const getToolIcon = (toolType: string) => {
    const icons: Record<string, string> = {
      snowflake: '❄️',
      bigquery: '🔷',
      postgres: '🐘',
      redshift: '🔴',
      sqlserver: '🗄️',
      azure_sql: '☁️',
      fivetran: '🔄',
      airbyte: '🌊',
      stitch: '🪡',
      dbt_cloud: '🔧',
      dbt_core: '⚙️',
      airflow: '🌀',
      dagster: '📊',
      looker: '👀',
      tableau: '📈',
      powerbi: '📉',
      metabase: '📋',
    };
    return icons[toolType] || '📦';
  };

  // Group nodes by layer
  const nodesByLayer = nodes.reduce((acc, node) => {
    if (!acc[node.layer]) acc[node.layer] = [];
    acc[node.layer].push(node);
    return acc;
  }, {} as Record<PipelineLayer, PipelineNode[]>);

  const layerOrder: PipelineLayer[] = ['WAREHOUSE', 'INGESTION', 'TRANSFORMATION', 'REPORTING'];
  const connectedNodes = nodes.filter((n) => n.status === 'ACTIVE' || n.status === 'CONNECTED');

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-1">Data Sources</h1>
          <p className="text-white/50 text-[14px]">
            View connected sources from your pipeline configuration
          </p>
        </div>
        <Link
          href="/dashboard/pipeline"
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-[13px] font-medium transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Configure Pipeline
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white/[0.02] border border-white/[0.04] rounded-xl p-4">
          <p className="text-2xl font-semibold text-white mb-1">{connectedNodes.length}</p>
          <p className="text-[13px] text-white/40">Connected Sources</p>
        </div>
        <div className="bg-white/[0.02] border border-white/[0.04] rounded-xl p-4">
          <p className="text-2xl font-semibold text-white mb-1">{nodes.filter((n) => n.layer === 'WAREHOUSE').length}</p>
          <p className="text-[13px] text-white/40">Warehouses</p>
        </div>
        <div className="bg-white/[0.02] border border-white/[0.04] rounded-xl p-4">
          <p className="text-2xl font-semibold text-white mb-1">{nodes.filter((n) => n.layer === 'TRANSFORMATION').length}</p>
          <p className="text-[13px] text-white/40">Transformations</p>
        </div>
        <div className="bg-white/[0.02] border border-white/[0.04] rounded-xl p-4">
          <p className="text-2xl font-semibold text-white mb-1">{nodes.filter((n) => n.status === 'ERROR').length}</p>
          <p className="text-[13px] text-white/40">Errors</p>
        </div>
      </div>

      {/* Sources by Layer */}
      {nodes.length > 0 ? (
        <div className="space-y-4">
          {layerOrder.map((layer) => {
            const layerNodes = nodesByLayer[layer];
            if (!layerNodes || layerNodes.length === 0) return null;

            return (
              <div key={layer} className="bg-white/[0.02] border border-white/[0.04] rounded-xl overflow-hidden">
                {/* Layer Header */}
                <div className="px-5 py-4 border-b border-white/[0.04] flex items-center gap-3">
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: LAYER_COLORS[layer] }}
                  />
                  <h2 className="text-[15px] font-medium text-white">{LAYER_LABELS[layer]}</h2>
                  <span className="text-[12px] text-white/40">
                    {layerNodes.length} source{layerNodes.length !== 1 ? 's' : ''}
                  </span>
                </div>

                {/* Nodes */}
                <div className="divide-y divide-white/[0.03]">
                  {layerNodes.map((node) => {
                    const tool = getToolById(node.toolType);
                    const isExpanded = expandedNode === node.id;
                    const details = nodeDetails[node.id];
                    const isLoadingThis = loadingDetails === node.id;

                    return (
                      <div key={node.id}>
                        <button
                          onClick={() => loadNodeDetails(node)}
                          className="w-full px-5 py-4 flex items-center gap-4 hover:bg-white/[0.02] transition-colors text-left"
                        >
                          {/* Icon */}
                          <div className="w-10 h-10 rounded-xl bg-white/[0.04] flex items-center justify-center text-xl">
                            {getToolIcon(node.toolType)}
                          </div>

                          {/* Info */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <h3 className="text-[14px] font-medium text-white">{node.name}</h3>
                              <span className={`w-2 h-2 rounded-full ${getStatusColor(node.status)}`} />
                            </div>
                            <p className="text-[12px] text-white/40">
                              {tool?.name || node.toolType}
                              {node.config?.database && ` • ${node.config.database}`}
                              {node.config?.project_id && ` • ${node.config.project_id}`}
                            </p>
                          </div>

                          {/* Health Score */}
                          {node.healthScore !== null && (
                            <div className="text-right mr-2">
                              <p className={`text-[14px] font-medium ${
                                node.healthScore >= 90 ? 'text-emerald-400' :
                                node.healthScore >= 70 ? 'text-amber-400' : 'text-red-400'
                              }`}>
                                {node.healthScore}%
                              </p>
                              <p className="text-[11px] text-white/40">Health</p>
                            </div>
                          )}

                          {/* Findings */}
                          {node.findingsCount > 0 && (
                            <div className="text-right mr-2">
                              <p className="text-[14px] font-medium text-white">{node.findingsCount}</p>
                              <p className="text-[11px] text-white/40">Findings</p>
                            </div>
                          )}

                          {/* Expand Icon */}
                          <svg
                            className={`w-5 h-5 text-white/30 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                          </svg>
                        </button>

                        {/* Expanded Details */}
                        {isExpanded && (
                          <div className="px-5 py-4 bg-white/[0.01] border-t border-white/[0.03]">
                            {isLoadingThis ? (
                              <div className="flex items-center gap-3 py-4">
                                <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
                                <span className="text-[13px] text-white/50">Loading source details...</span>
                              </div>
                            ) : details?.error ? (
                              <div className="flex items-center gap-3 py-4 text-red-400">
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                </svg>
                                <span className="text-[13px]">{details.error}</span>
                              </div>
                            ) : details?.tables && details.tables.length > 0 ? (
                              <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                  <p className="text-[12px] text-white/50 uppercase tracking-wide">
                                    {details.tables.length} Tables Discovered
                                  </p>
                                  {details.lastSync && (
                                    <p className="text-[11px] text-white/40">Last synced: {details.lastSync}</p>
                                  )}
                                </div>
                                <div className="grid grid-cols-3 gap-2 max-h-48 overflow-y-auto">
                                  {details.tables.map((table) => (
                                    <div
                                      key={`${table.schema}.${table.name}`}
                                      className="px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.04]"
                                    >
                                      <p className="text-[12px] font-medium text-white truncate">{table.name}</p>
                                      <p className="text-[10px] text-white/40 truncate">{table.schema}</p>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ) : (
                              <div className="py-4 text-center">
                                <p className="text-[13px] text-white/40">
                                  {node.status === 'ACTIVE' || node.status === 'CONNECTED'
                                    ? 'No tables discovered yet. Run a sync to discover tables.'
                                    : 'Configure this source in the Pipeline Builder to discover tables.'}
                                </p>
                                <Link
                                  href="/dashboard/pipeline"
                                  className="inline-flex items-center gap-2 mt-3 px-4 py-2 rounded-lg bg-white/[0.05] hover:bg-white/[0.08] text-white text-[12px] transition-colors"
                                >
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                  </svg>
                                  Configure in Pipeline
                                </Link>
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
          })}
        </div>
      ) : (
        /* Empty State */
        <div className="text-center py-16 rounded-xl bg-white/[0.02] border border-white/[0.04]">
          <div className="w-16 h-16 rounded-2xl bg-white/[0.04] flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375" />
            </svg>
          </div>
          <h2 className="text-lg font-medium text-white mb-2">No sources configured</h2>
          <p className="text-white/40 text-[14px] max-w-md mx-auto mb-6">
            Connect your data warehouse, dbt project, and other tools in the Pipeline Builder to see them here.
          </p>
          <Link
            href="/dashboard/pipeline"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-[13px] font-medium transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Open Pipeline Builder
          </Link>
        </div>
      )}

      {/* Help Card */}
      <div className="bg-white/[0.02] border border-white/[0.04] border-dashed rounded-xl p-5">
        <div className="flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-[var(--accent)]/10 flex items-center justify-center">
            <svg className="w-5 h-5 text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
            </svg>
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-white">How it works</h3>
            <p className="text-[13px] text-white/40">
              Data sources are configured in the Pipeline Builder. The AI co-pilot uses these connections to explore your data, trace lineage, and help debug issues.
            </p>
          </div>
          <Link href="/dashboard/pipeline" className="text-[13px] text-[var(--accent-2)] hover:underline whitespace-nowrap">
            Go to Pipeline →
          </Link>
        </div>
      </div>
    </div>
  );
}
