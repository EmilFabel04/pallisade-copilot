'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { FindingLineageCanvas } from '@/components/lineage/FindingLineageCanvas';

// Types for the finding lineage API response
interface FindingContext {
  id: string;
  table: string;
  column: string | null;
  title: string;
  severity: string;
  findingType: string;
  value?: string;
  detectedAt?: string;
}

interface ImpactSummary {
  totalAffectedTables: number;
  totalAffectedDashboards: number;
  criticalityBreakdown: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
  affectedTeams: string[];
  propagationExplanation: string;
}

interface AffectedAsset {
  table: string;
  column: string;
  type: string;
  criticality: string;
  owner: string | null;
  impactReason: string;
  distance: number;
  transformationType?: string;
}

interface GraphNode {
  id: string;
  name: string;
  fqn?: string;
  type: string;
  criticality: string;
  owner?: string | null;
  affected_column?: string;
  is_source?: boolean;
  finding_type?: string;
  finding_severity?: string;
  impact_reason?: string;
  distance: number;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  transformation_type?: string;
  transformation?: string;
  target_criticality?: string;
}

interface FindingLineageData {
  finding: FindingContext;
  impact: ImpactSummary;
  affectedAssets: AffectedAsset[];
  graph: {
    nodes: GraphNode[];
    edges: GraphEdge[];
  };
  isEmpty: boolean;
  message?: string;
}

interface FindingLineageModalProps {
  isOpen: boolean;
  onClose: () => void;
  finding: {
    id?: string;
    table: string;
    column?: string;
    title?: string;
    severity?: string;
    findingType?: string;
    scan_type?: string;
    description?: string;
    detectedAt?: string;
  };
}

export function FindingLineageModal({ isOpen, onClose, finding }: FindingLineageModalProps) {
  const [loading, setLoading] = useState(true);
  const [lineageData, setLineageData] = useState<FindingLineageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedAsset, setSelectedAsset] = useState<AffectedAsset | null>(null);

  useEffect(() => {
    if (isOpen && finding.table) {
      fetchFindingLineage();
    }
  }, [isOpen, finding]);

  const fetchFindingLineage = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/findings/inline/lineage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          table: finding.table,
          column: finding.column,
          title: finding.title,
          severity: finding.severity || 'medium',
          findingType: finding.findingType || finding.scan_type || 'unknown',
          description: finding.description,
          detectedAt: finding.detectedAt || new Date().toISOString(),
        }),
      });
      
      if (!response.ok) {
        throw new Error('Failed to fetch lineage data');
      }
      
      const data = await response.json();
      setLineageData(data);
    } catch (err) {
      console.error('Failed to fetch finding lineage:', err);
      setError('Failed to load lineage data. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleNodeClick = useCallback((nodeId: string) => {
    if (!lineageData) return;
    const asset = lineageData.affectedAssets.find(a => 
      a.table.toLowerCase().includes(nodeId.toLowerCase()) ||
      nodeId.toLowerCase().includes(a.table.toLowerCase())
    );
    setSelectedAsset(asset || null);
  }, [lineageData]);

  if (!isOpen) return null;

  const severityConfig = {
    critical: { bg: 'bg-red-500/20', text: 'text-red-400', border: 'border-red-500/30' },
    high: { bg: 'bg-orange-500/20', text: 'text-orange-400', border: 'border-orange-500/30' },
    medium: { bg: 'bg-amber-500/20', text: 'text-amber-400', border: 'border-amber-500/30' },
    low: { bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/30' },
  };

  const severity = (finding.severity || 'medium').toLowerCase() as keyof typeof severityConfig;
  const sevColors = severityConfig[severity] || severityConfig.medium;

  // Group affected assets by criticality
  const groupedAssets = lineageData?.affectedAssets.reduce((acc, asset) => {
    const crit = (asset.criticality || 'medium').toLowerCase();
    if (!acc[crit]) acc[crit] = [];
    acc[crit].push(asset);
    return acc;
  }, {} as Record<string, AffectedAsset[]>) || {};

  const criticalityOrder = ['critical', 'high', 'medium', 'low'];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={onClose} />
      
      <div className="relative bg-[var(--surface)] border border-[var(--border-medium)] rounded-2xl w-full max-w-6xl max-h-[92vh] overflow-hidden shadow-2xl flex flex-col">
        {/* Header - Finding Context */}
        <div className="p-6 border-b border-[var(--subtle-border)] bg-gradient-to-r from-red-500/5 to-transparent">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <div className={`w-12 h-12 rounded-xl ${sevColors.bg} ${sevColors.border} border flex items-center justify-center`}>
                <svg className={`w-6 h-6 ${sevColors.text}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <h2 className="text-xl font-bold">Column Lineage Impact</h2>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-sm text-[var(--muted)] font-mono">{finding.table}</span>
                  {finding.column && (
                    <>
                      <span className="text-[var(--muted)]">.</span>
                      <span className="text-sm font-mono px-2 py-0.5 rounded bg-purple-500/20 text-purple-400 border border-purple-500/30">
                        {finding.column}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>
            
            <div className="flex items-center gap-3">
              <span className={`px-3 py-1.5 rounded-lg ${sevColors.bg} ${sevColors.text} ${sevColors.border} border text-sm font-bold uppercase`}>
                {finding.severity || 'medium'}
              </span>
              <button onClick={onClose} className="p-2 hover:bg-[var(--subtle-bg)] rounded-lg transition-colors">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
          
          {/* Finding Details */}
          <div className="mt-4 p-4 rounded-xl bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="text-sm font-medium">{finding.title || 'Data quality issue detected'}</div>
                {lineageData?.finding?.value && (
                  <div className="mt-1 text-xs text-[var(--muted)]">
                    Value: <span className="text-[var(--text)] font-mono">{lineageData.finding.value}</span>
                  </div>
                )}
              </div>
              <div className="text-xs text-[var(--muted)]">
                {finding.detectedAt ? new Date(finding.detectedAt).toLocaleString() : 'Just now'}
              </div>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden flex">
          {loading ? (
            <div className="flex-1 flex flex-col items-center justify-center py-16">
              <div className="animate-spin w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full mb-4" />
              <p className="text-[var(--muted)]">Analyzing column-level impact...</p>
            </div>
          ) : error ? (
            <div className="flex-1 flex flex-col items-center justify-center py-16">
              <svg className="w-12 h-12 text-red-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <p className="text-red-400">{error}</p>
              <button 
                onClick={fetchFindingLineage}
                className="mt-4 px-4 py-2 bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/30 rounded-lg text-sm"
              >
                Try Again
              </button>
            </div>
          ) : lineageData?.isEmpty ? (
            // Empty State - Isolated Column
            <div className="flex-1 flex flex-col items-center justify-center py-16 px-8">
              <div className="w-20 h-20 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mb-6">
                <svg className="w-10 h-10 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h3 className="text-xl font-semibold mb-2">Isolated Finding</h3>
              <p className="text-[var(--muted)] text-center max-w-md mb-6">
                This column is not used downstream. The finding is contained to this table
                and does not propagate to other assets.
              </p>
              
              {/* Still show the source node */}
              <div className="p-4 rounded-xl bg-purple-500/10 border border-purple-500/30 max-w-sm w-full">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-purple-500/20 flex items-center justify-center">
                    <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                    </svg>
                  </div>
                  <div>
                    <div className="font-mono text-sm">{finding.table}</div>
                    {finding.column && (
                      <div className="text-xs text-purple-400">Issue in: {finding.column}</div>
                    )}
                  </div>
                </div>
              </div>
              
              {lineageData.message && (
                <p className="mt-6 text-xs text-[var(--muted)] text-center">
                  {lineageData.message}
                </p>
              )}
            </div>
          ) : (
            // Full Lineage View
            <>
              {/* Left Sidebar - Affected Assets */}
              <div className="w-72 border-r border-[var(--subtle-border)] overflow-y-auto bg-[var(--overlay-faint)]">
                {/* Impact Summary */}
                <div className="p-4 border-b border-[var(--subtle-border)]">
                  <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">Impact Summary</h3>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="p-2 rounded-lg bg-[var(--overlay-bg)]">
                      <div className="text-lg font-bold">{lineageData?.impact.totalAffectedTables || 0}</div>
                      <div className="text-[10px] text-[var(--muted)]">Tables</div>
                    </div>
                    <div className="p-2 rounded-lg bg-[var(--overlay-bg)]">
                      <div className="text-lg font-bold text-blue-400">{lineageData?.impact.totalAffectedDashboards || 0}</div>
                      <div className="text-[10px] text-[var(--muted)]">Dashboards</div>
                    </div>
                  </div>
                  
                  {/* Criticality Breakdown */}
                  <div className="mt-3 flex gap-1">
                    {(lineageData?.impact.criticalityBreakdown.critical ?? 0) > 0 && (
                      <span className="px-2 py-1 rounded text-[10px] font-bold bg-red-500/20 text-red-400">
                        {lineageData!.impact.criticalityBreakdown.critical} Critical
                      </span>
                    )}
                    {(lineageData?.impact.criticalityBreakdown.high ?? 0) > 0 && (
                      <span className="px-2 py-1 rounded text-[10px] font-bold bg-orange-500/20 text-orange-400">
                        {lineageData!.impact.criticalityBreakdown.high} High
                      </span>
                    )}
                  </div>
                  
                  {/* Teams */}
                  {lineageData?.impact.affectedTeams && lineageData.impact.affectedTeams.length > 0 && (
                    <div className="mt-3">
                      <div className="text-[10px] text-[var(--muted)] mb-1">Affected Teams</div>
                      <div className="flex flex-wrap gap-1">
                        {lineageData.impact.affectedTeams.map((team, i) => (
                          <span key={i} className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            {team}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                
                {/* Affected Assets List */}
                <div className="p-4">
                  <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">Affected Assets</h3>
                  <div className="space-y-4">
                    {criticalityOrder.map(crit => {
                      const assets = groupedAssets[crit];
                      if (!assets || assets.length === 0) return null;
                      
                      const critConfigMap: Record<string, { bg: string; border: string; text: string; label: string }> = {
                        critical: { bg: 'bg-red-500/10', border: 'border-red-500/20', text: 'text-red-400', label: 'Critical' },
                        high: { bg: 'bg-orange-500/10', border: 'border-orange-500/20', text: 'text-orange-400', label: 'High' },
                        medium: { bg: 'bg-amber-500/10', border: 'border-amber-500/20', text: 'text-amber-400', label: 'Medium' },
                        low: { bg: 'bg-slate-500/10', border: 'border-slate-500/20', text: 'text-slate-400', label: 'Low' },
                      };
                      const critConfig = critConfigMap[crit] ?? critConfigMap.medium;
                      
                      return (
                        <div key={crit}>
                          <div className={`text-[10px] font-bold ${critConfig.text} uppercase mb-2`}>
                            {critConfig.label} ({assets.length})
                          </div>
                          <div className="space-y-2">
                            {assets.map((asset, i) => (
                              <button
                                key={i}
                                onClick={() => setSelectedAsset(asset)}
                                className={`w-full p-3 rounded-lg ${critConfig.bg} ${critConfig.border} border text-left transition-all hover:scale-[1.02] ${
                                  selectedAsset === asset ? 'ring-2 ring-purple-500' : ''
                                }`}
                              >
                                <div className="flex items-center gap-2 mb-1">
                                  <svg className={`w-3.5 h-3.5 ${critConfig.text}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    {asset.type === 'dashboard' || asset.type === 'report' ? (
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                                    ) : (
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                                    )}
                                  </svg>
                                  <span className="font-mono text-xs truncate">{asset.table.split('.').pop()}</span>
                                </div>
                                {asset.column && (
                                  <div className="text-[10px] text-[var(--muted)] mb-1">
                                    Column: <span className="text-[var(--text)]">{asset.column}</span>
                                  </div>
                                )}
                                <div className="text-[10px] text-[var(--muted)] line-clamp-2">
                                  {asset.impactReason}
                                </div>
                              </button>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
              
              {/* Center - Graph */}
              <div className="flex-1 flex flex-col overflow-hidden">
                {/* Propagation Explanation */}
                {lineageData?.impact.propagationExplanation && (
                  <div className="p-4 border-b border-[var(--subtle-border)] bg-amber-500/5">
                    <div className="flex items-start gap-3">
                      <svg className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <p className="text-sm text-amber-200/80">
                        {lineageData.impact.propagationExplanation}
                      </p>
                    </div>
                  </div>
                )}
                
                {/* Graph Canvas */}
                <div className="flex-1 overflow-hidden">
                  <FindingLineageCanvas
                    nodes={lineageData?.graph.nodes || []}
                    edges={lineageData?.graph.edges || []}
                    sourceTable={finding.table}
                    sourceColumn={finding.column}
                    onNodeClick={handleNodeClick}
                    selectedNodeId={selectedAsset?.table}
                  />
                </div>
              </div>
              
              {/* Right Panel - Selected Asset Details (shown when asset selected) */}
              {selectedAsset && (
                <div className="w-72 border-l border-[var(--subtle-border)] overflow-y-auto bg-[var(--overlay-faint)]">
                  <div className="p-4">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-sm font-semibold">Asset Details</h3>
                      <button 
                        onClick={() => setSelectedAsset(null)}
                        className="p-1 hover:bg-[var(--subtle-bg)] rounded"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                    
                    <div className="space-y-4">
                      {/* Table name */}
                      <div>
                        <div className="text-[10px] text-[var(--muted)] uppercase mb-1">Table</div>
                        <div className="font-mono text-sm">{selectedAsset.table}</div>
                      </div>
                      
                      {/* Column */}
                      {selectedAsset.column && (
                        <div>
                          <div className="text-[10px] text-[var(--muted)] uppercase mb-1">Affected Column</div>
                          <div className="px-2 py-1 rounded bg-purple-500/20 text-purple-400 text-sm font-mono inline-block">
                            {selectedAsset.column}
                          </div>
                        </div>
                      )}
                      
                      {/* Type */}
                      <div>
                        <div className="text-[10px] text-[var(--muted)] uppercase mb-1">Type</div>
                        <div className="text-sm capitalize">{selectedAsset.type}</div>
                      </div>
                      
                      {/* Owner */}
                      {selectedAsset.owner && (
                        <div>
                          <div className="text-[10px] text-[var(--muted)] uppercase mb-1">Owner</div>
                          <div className="text-sm">{selectedAsset.owner}</div>
                        </div>
                      )}
                      
                      {/* Distance */}
                      <div>
                        <div className="text-[10px] text-[var(--muted)] uppercase mb-1">Distance</div>
                        <div className="text-sm">{selectedAsset.distance} hop{selectedAsset.distance !== 1 ? 's' : ''} from source</div>
                      </div>
                      
                      {/* Transformation type */}
                      {selectedAsset.transformationType && (
                        <div>
                          <div className="text-[10px] text-[var(--muted)] uppercase mb-1">Transformation</div>
                          <span className="px-2 py-1 rounded text-xs font-medium bg-blue-500/20 text-blue-400">
                            {selectedAsset.transformationType}
                          </span>
                        </div>
                      )}
                      
                      {/* Impact reason */}
                      <div>
                        <div className="text-[10px] text-[var(--muted)] uppercase mb-1">Impact</div>
                        <div className="text-sm text-amber-200/80 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                          {selectedAsset.impactReason}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
