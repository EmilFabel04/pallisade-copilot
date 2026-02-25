'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { LineageCanvas } from '@/components/lineage/LineageCanvas';

interface LineageTable {
  name: string;
  criticality?: string;
  distance?: number;
  type?: string;
  platform?: string;
  health?: 'healthy' | 'degraded' | 'failing' | 'unknown';
}

interface ImpactData {
  table: string;
  database?: string;
  schema?: string;
  criticality?: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  dataTier?: string;
  owner?: string;
  businessDomain?: string;
  businessImpact?: string;
  downstreamCount?: number;
  downstreamCritical?: number;
  impactScore?: number;
  priority?: string;
  stakeholders?: string[];
  slackChannel?: string;
  pagerDutyService?: string;
  usedInReports?: string[];
  downstreamTables?: LineageTable[];
  upstreamTables?: LineageTable[];
  riskFactors?: string[];
  recommendedActions?: string[];
}

interface ImpactModalProps {
  isOpen: boolean;
  onClose: () => void;
  tableName: string;
  findingTitle?: string;
  findingSeverity?: string;
}

export function ImpactModal({ isOpen, onClose, tableName, findingTitle, findingSeverity }: ImpactModalProps) {
  const [loading, setLoading] = useState(true);
  const [impactData, setImpactData] = useState<ImpactData | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'lineage' | 'actions'>('overview');
  const [lineageViewMode, setLineageViewMode] = useState<'canvas' | 'list'>('canvas');
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  // Handle node click in lineage canvas
  const handleNodeClick = useCallback((nodeName: string) => {
    setSelectedNode(nodeName);
    // Could navigate to that table's lineage or show details
  }, []);

  useEffect(() => {
    if (isOpen && tableName) {
      fetchImpactData();
      setActiveTab('overview');
    }
  }, [isOpen, tableName]);

  const fetchImpactData = async () => {
    setLoading(true);
    
    try {
      const res = await fetch(`/api/tables/impact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tableName, fullName: tableName }),
      });
      const data = await res.json();
      
      if (data.found && data.impact) {
        // Use REAL lineage data from the API
        const impact = data.impact;
        
        setImpactData({
          table: tableName,
          database: impact.database,
          schema: impact.schema,
          criticality: impact.criticality,
          dataTier: impact.dataTier,
          owner: impact.owner,
          businessDomain: impact.businessDomain,
          businessImpact: impact.businessImpact,
          downstreamCount: impact.downstreamCount || 0,
          downstreamCritical: impact.downstreamCritical || 0,
          impactScore: impact.impactScore,
          priority: impact.priority,
          stakeholders: impact.stakeholders || [],
          slackChannel: impact.slackChannel,
          pagerDutyService: impact.pagerDutyService,
          usedInReports: impact.usedInReports || [],
          // Real lineage tables
          upstreamTables: impact.upstreamTables || [],
          downstreamTables: impact.downstreamTables || [],
          riskFactors: impact.riskFactors || [],
          recommendedActions: impact.recommendedActions || [],
        });
      } else {
        // Fallback to smart mock if no real data
        setImpactData(generateSmartImpact(tableName, findingSeverity));
      }
    } catch (err) {
      console.error('Failed to fetch impact:', err);
      setImpactData(generateSmartImpact(tableName, findingSeverity));
    } finally {
      setLoading(false);
    }
  };

  const generateSmartImpact = (table: string, severity?: string): ImpactData => {
    const tableNameLower = (table || '').toLowerCase();
    const isOrders = tableNameLower.includes('order');
    const isUsers = tableNameLower.includes('user') || tableNameLower.includes('customer');
    const isPayments = tableNameLower.includes('payment') || tableNameLower.includes('transaction');
    const isProducts = tableNameLower.includes('product') || tableNameLower.includes('inventory');
    const isEvents = tableNameLower.includes('event') || tableNameLower.includes('log');

    const criticality = isOrders || isPayments ? 'CRITICAL' : isUsers || isProducts ? 'HIGH' : isEvents ? 'MEDIUM' : 'LOW';
    const downstreamCount = isOrders ? 15 : isUsers ? 10 : isPayments ? 12 : isProducts ? 8 : 4;
    const downstreamCritical = isOrders ? 5 : isPayments ? 4 : isUsers ? 3 : 1;

    // Calculate impact score
    let impactScore = 0;
    if (criticality === 'CRITICAL') impactScore += 35;
    else if (criticality === 'HIGH') impactScore += 25;
    else if (criticality === 'MEDIUM') impactScore += 15;
    else impactScore += 5;
    impactScore += Math.min(downstreamCount * 3, 30);
    impactScore += downstreamCritical * 7;
    if (severity === 'critical') impactScore += 15;
    else if (severity === 'high') impactScore += 10;

    const priority = impactScore >= 80 ? 'P0' : impactScore >= 60 ? 'P1' : impactScore >= 40 ? 'P2' : 'P3';

    return {
      table,
      database: 'ANALYTICS',
      schema: 'PUBLIC',
      criticality,
      dataTier: isOrders || isPayments ? 'GOLD' : isUsers || isProducts ? 'SILVER' : 'BRONZE',
      owner: isOrders ? 'Revenue Team' : isUsers ? 'Customer Platform' : isPayments ? 'Finance Team' : 'Data Engineering',
      businessDomain: isOrders ? 'Revenue' : isUsers ? 'Customer' : isPayments ? 'Finance' : isProducts ? 'Operations' : 'Analytics',
      businessImpact: isOrders 
        ? 'Critical revenue tracking - impacts executive dashboards, sales forecasting, and financial reporting'
        : isPayments
        ? 'Payment processing data - affects reconciliation, fraud detection, and revenue recognition'
        : isUsers 
        ? 'Core customer data - impacts personalization, marketing campaigns, and customer analytics'
        : isProducts
        ? 'Product catalog and inventory - affects e-commerce, recommendations, and supply chain'
        : 'Operational data used for monitoring and analytics',
      downstreamCount,
      downstreamCritical,
      impactScore: Math.min(impactScore, 100),
      priority,
      stakeholders: isOrders 
        ? ['CFO Office', 'Sales Ops', 'Revenue Ops', 'FP&A'] 
        : isPayments
        ? ['Finance', 'Accounting', 'Risk Team', 'Treasury']
        : isUsers 
        ? ['Marketing', 'Product', 'Customer Success', 'Growth']
        : ['Data Team', 'Analytics'],
      slackChannel: criticality === 'CRITICAL' ? '#data-alerts-critical' : '#data-alerts',
      pagerDutyService: criticality === 'CRITICAL' ? 'data-platform-oncall' : undefined,
      usedInReports: isOrders 
        ? ['Executive Dashboard', 'Revenue Report', 'Sales Forecast', 'Monthly KPIs', 'Board Deck']
        : isPayments
        ? ['Financial Report', 'Reconciliation Dashboard', 'Fraud Monitoring', 'Revenue Recognition']
        : isUsers
        ? ['Customer Analytics', 'Marketing Dashboard', 'Churn Prediction', 'Cohort Analysis']
        : ['Operational Dashboard'],
      downstreamTables: generateDownstreamTables(table, downstreamCount),
      upstreamTables: generateUpstreamTables(table),
      riskFactors: generateRiskFactors(criticality, downstreamCount, severity),
      recommendedActions: generateRecommendedActions(criticality, findingTitle),
    };
  };

  const generateDownstreamTables = (table: string, count: number) => {
    const prefix = table.split('.')[0] || 'ANALYTICS';
    const types = ['MART', 'AGG', 'RPT', 'DIM', 'FCT'];
    const names = ['DAILY', 'WEEKLY', 'METRICS', 'SUMMARY', 'ANALYSIS', 'KPI', 'TRENDS', 'FORECAST'];
    
    return Array.from({ length: Math.min(count, 8) }, (_, i) => ({
      name: `${prefix}.${types[i % types.length]}_${names[i % names.length]}`,
      criticality: i < 2 ? 'CRITICAL' : i < 4 ? 'HIGH' : 'MEDIUM',
      distance: Math.ceil((i + 1) / 3),
    }));
  };

  const generateUpstreamTables = (table: string) => {
    return [
      { name: 'RAW.PRODUCTION.SOURCE_DATA', criticality: 'HIGH' },
      { name: 'RAW.EVENTS.STREAM_DATA', criticality: 'MEDIUM' },
    ];
  };

  const generateRiskFactors = (criticality: string, downstream: number, severity?: string) => {
    const factors = [];
    if (criticality === 'CRITICAL') factors.push('This is a business-critical table');
    if (downstream > 10) factors.push(`High blast radius: ${downstream} downstream dependencies`);
    if (severity === 'critical' || severity === 'high') factors.push('Issue severity increases urgency');
    if (downstream > 5) factors.push('Multiple reports and dashboards affected');
    factors.push('Data freshness SLAs may be breached');
    return factors;
  };

  const generateRecommendedActions = (criticality: string, finding?: string) => {
    const actions = [];
    if (criticality === 'CRITICAL') {
      actions.push('Notify on-call engineer immediately');
      actions.push('Alert stakeholders via Slack #data-alerts-critical');
    }
    actions.push('Investigate root cause in upstream pipelines');
    actions.push('Check recent schema changes or deployments');
    if (finding?.toLowerCase().includes('stale') || finding?.toLowerCase().includes('fresh')) {
      actions.push('Review pipeline scheduling and dependencies');
      actions.push('Check source system connectivity');
    }
    if (finding?.toLowerCase().includes('null')) {
      actions.push('Add data validation tests to pipeline');
      actions.push('Review source data quality');
    }
    actions.push('Document incident and resolution');
    return actions;
  };

  if (!isOpen) return null;

  const criticalityConfig = {
    CRITICAL: { bg: 'bg-red-500/20', text: 'text-red-400', border: 'border-red-500/30', ring: 'ring-red-500/20' },
    HIGH: { bg: 'bg-orange-500/20', text: 'text-orange-400', border: 'border-orange-500/30', ring: 'ring-orange-500/20' },
    MEDIUM: { bg: 'bg-amber-500/20', text: 'text-amber-400', border: 'border-amber-500/30', ring: 'ring-amber-500/20' },
    LOW: { bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/30', ring: 'ring-emerald-500/20' },
  };

  const priorityConfig = {
    P0: { bg: 'bg-red-500', text: 'text-white', label: 'Critical' },
    P1: { bg: 'bg-orange-500', text: 'text-white', label: 'High' },
    P2: { bg: 'bg-amber-500', text: 'text-black', label: 'Medium' },
    P3: { bg: 'bg-slate-500', text: 'text-white', label: 'Low' },
  };

  const criticality = impactData?.criticality || 'MEDIUM';
  const critColors = criticalityConfig[criticality];
  const priority = impactData?.priority || 'P2';
  const prioColors = priorityConfig[priority as keyof typeof priorityConfig] || priorityConfig.P2;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={onClose} />
      
      <div className="relative bg-[var(--surface)] border border-[var(--border-medium)] rounded-2xl w-full max-w-4xl max-h-[92vh] overflow-hidden shadow-2xl flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-[var(--subtle-border)] bg-gradient-to-r from-purple-500/5 to-transparent">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <div className={`w-12 h-12 rounded-xl ${critColors.bg} ${critColors.border} border flex items-center justify-center`}>
                <svg className={`w-6 h-6 ${critColors.text}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <h2 className="text-xl font-bold">Impact Analysis</h2>
                <p className="text-sm text-[var(--muted)] font-mono">{tableName}</p>
              </div>
            </div>
            
            {/* Priority Badge */}
            {impactData && (
              <div className="flex items-center gap-3">
                <div className={`px-3 py-1.5 rounded-lg ${prioColors.bg} ${prioColors.text} text-sm font-bold`}>
                  {priority} - {prioColors.label}
                </div>
                <button onClick={onClose} className="p-2 hover:bg-[var(--subtle-bg)] rounded-lg transition-colors">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            )}
          </div>
          
          {findingTitle && (
            <div className="mt-4 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <div className="text-xs text-[var(--muted)] mb-1">Triggered by</div>
              <div className="text-sm font-medium">{findingTitle}</div>
            </div>
          )}
        </div>

        {/* Tabs */}
        {!loading && impactData && (
          <div className="flex border-b border-[var(--subtle-border)] sticky top-0 z-10 bg-[var(--surface)]">
            {(['overview', 'lineage', 'actions'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`flex-1 px-4 py-3 text-sm font-medium transition-all ${
                  activeTab === tab 
                    ? 'text-[var(--text)] border-b-2 border-purple-500 bg-purple-500/5'
                    : 'text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--subtle-bg)]'
                }`}
              >
                {tab === 'overview' && 'Overview'}
                {tab === 'lineage' && 'Dependencies'}
                {tab === 'actions' && 'Recommended Actions'}
              </button>
            ))}
          </div>
        )}

        {/* Content */}
        <div className="p-6 overflow-y-auto flex-1 overscroll-contain min-h-[55vh] max-h-[78vh]">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <div className="animate-spin w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full mb-4" />
              <p className="text-[var(--muted)]">Analyzing impact...</p>
            </div>
          ) : impactData ? (
            <>
              {/* Overview Tab */}
              {activeTab === 'overview' && (
                <div className="space-y-6">
                  {/* Impact Score Card */}
                  <div className={`p-5 rounded-xl ${critColors.bg} ${critColors.border} border`}>
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${critColors.text} ${critColors.bg}`}>
                            {criticality}
                          </span>
                          {impactData.dataTier && (
                            <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-500/20 text-blue-400">
                              {impactData.dataTier} Tier
                            </span>
                          )}
                        </div>
                        <div className="text-sm text-[var(--muted)] mt-2">
                          {impactData.businessDomain && <span className="mr-3">Domain: {impactData.businessDomain}</span>}
                          {impactData.owner && <span>Owner: {impactData.owner}</span>}
                        </div>
                      </div>
                      
                      {/* Impact Score Gauge */}
                      <div className="text-center">
                        <div className="relative w-20 h-20">
                          <svg className="w-20 h-20 -rotate-90">
                            <circle cx="40" cy="40" r="32" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="8" />
                            <circle 
                              cx="40" cy="40" r="32" fill="none" 
                              stroke={impactData.impactScore! >= 80 ? '#ef4444' : impactData.impactScore! >= 60 ? '#f97316' : impactData.impactScore! >= 40 ? '#eab308' : '#22c55e'}
                              strokeWidth="8" 
                              strokeDasharray={`${(impactData.impactScore || 0) * 2.01} 201`}
                              strokeLinecap="round"
                            />
                          </svg>
                          <div className="absolute inset-0 flex items-center justify-center">
                            <span className="text-2xl font-bold">{impactData.impactScore}</span>
                          </div>
                        </div>
                        <div className="text-xs text-[var(--muted)] mt-1">Impact Score</div>
                      </div>
                    </div>
                    
                    {impactData.businessImpact && (
                      <p className="text-sm leading-relaxed">{impactData.businessImpact}</p>
                    )}
                  </div>

                  {/* Quick Stats */}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="p-4 rounded-xl bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
                      <div className="text-3xl font-bold">{impactData.downstreamCount || 0}</div>
                      <div className="text-sm text-[var(--muted)]">Downstream Tables</div>
                    </div>
                    <div className="p-4 rounded-xl bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
                      <div className="text-3xl font-bold text-red-400">{impactData.downstreamCritical || 0}</div>
                      <div className="text-sm text-[var(--muted)]">Critical Deps</div>
                    </div>
                    <div className="p-4 rounded-xl bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
                      <div className="text-3xl font-bold text-blue-400">{impactData.usedInReports?.length || 0}</div>
                      <div className="text-sm text-[var(--muted)]">Reports Affected</div>
                    </div>
                  </div>

                  {/* Risk Factors */}
                  {impactData.riskFactors && impactData.riskFactors.length > 0 && (
                    <div className="p-4 rounded-xl bg-red-500/5 border border-red-500/20">
                      <h3 className="text-sm font-semibold text-red-400 mb-3 flex items-center gap-2">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                        Risk Factors
                      </h3>
                      <ul className="space-y-2">
                        {impactData.riskFactors.map((factor, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm">
                            <span className="text-red-400 mt-1">•</span>
                            <span>{factor}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Stakeholders & Channels */}
                  <div className="grid grid-cols-2 gap-4">
                    {impactData.stakeholders && impactData.stakeholders.length > 0 && (
                      <div>
                        <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-2">Stakeholders</h3>
                        <div className="flex flex-wrap gap-2">
                          {impactData.stakeholders.map((s, i) => (
                            <span key={i} className="px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400">
                              {s}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    
                    {(impactData.slackChannel || impactData.pagerDutyService) && (
                      <div>
                        <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-2">Alert Channels</h3>
                        <div className="flex flex-wrap gap-2">
                          {impactData.slackChannel && (
                            <span className="px-2.5 py-1 rounded-lg bg-purple-500/10 border border-purple-500/20 text-xs text-purple-400">
                              {impactData.slackChannel}
                            </span>
                          )}
                          {impactData.pagerDutyService && (
                            <span className="px-2.5 py-1 rounded-lg bg-green-500/10 border border-green-500/20 text-xs text-green-400">
                              🔔 {impactData.pagerDutyService}
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Lineage Tab */}
              {activeTab === 'lineage' && (
                <div className="space-y-4">
                  {/* View Mode Toggle */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-[var(--muted)]">View:</span>
                      <div className="flex bg-[var(--subtle-bg)] rounded-lg p-0.5">
                        <button
                          onClick={() => setLineageViewMode('canvas')}
                          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                            lineageViewMode === 'canvas'
                              ? 'bg-purple-500/20 text-purple-400'
                              : 'text-[var(--muted)] hover:text-[var(--text)]'
                          }`}
                        >
                          <svg className="w-3.5 h-3.5 inline mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                          </svg>
                          Pipeline
                        </button>
                        <button
                          onClick={() => setLineageViewMode('list')}
                          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                            lineageViewMode === 'list'
                              ? 'bg-purple-500/20 text-purple-400'
                              : 'text-[var(--muted)] hover:text-[var(--text)]'
                          }`}
                        >
                          <svg className="w-3.5 h-3.5 inline mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                          </svg>
                          List
                        </button>
                      </div>
                    </div>
                    
                    {/* Selected node info */}
                    {selectedNode && (
                      <div className="flex items-center gap-2 px-3 py-1.5 bg-purple-500/10 border border-purple-500/20 rounded-lg">
                        <span className="text-xs text-purple-400">Selected:</span>
                        <span className="text-xs font-mono text-[var(--text)]">{selectedNode.split('.').pop()}</span>
                        <button 
                          onClick={() => setSelectedNode(null)}
                          className="text-purple-400 hover:text-purple-300"
                        >
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    )}
                  </div>

                  {/* No lineage notice */}
                  {(!impactData.upstreamTables || impactData.upstreamTables.length === 0) && 
                   (!impactData.downstreamTables || impactData.downstreamTables.length === 0) && (
                    <div className="text-center py-8 text-[var(--muted)]">
                      <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                      </svg>
                      <p>No lineage data available yet.</p>
                      <p className="text-sm mt-1">Run a lineage scan to populate upstream/downstream dependencies.</p>
                    </div>
                  )}

                  {/* Canvas View - Pipeline Visualization */}
                  {lineageViewMode === 'canvas' && 
                   ((impactData.upstreamTables && impactData.upstreamTables.length > 0) || 
                    (impactData.downstreamTables && impactData.downstreamTables.length > 0)) && (
                    <div className="rounded-xl overflow-hidden border border-[var(--border-medium)]">
                      <LineageCanvas
                        centerTable={impactData.table}
                        upstreamTables={impactData.upstreamTables || []}
                        downstreamTables={impactData.downstreamTables || []}
                        onNodeClick={handleNodeClick}
                        className="h-[450px]"
                      />
                    </div>
                  )}

                  {/* List View - Traditional Display */}
                  {lineageViewMode === 'list' && (
                    <div className="space-y-6">
                      {/* Upstream */}
                      {impactData.upstreamTables && impactData.upstreamTables.length > 0 && (
                        <div>
                          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                            <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 11l5-5m0 0l5 5m-5-5v12" />
                            </svg>
                            Upstream Sources ({impactData.upstreamTables.length})
                          </h3>
                          <div className="space-y-2">
                            {impactData.upstreamTables.map((t, i) => {
                              const crit = (t.criticality as keyof typeof criticalityConfig) || 'MEDIUM';
                              const colors = criticalityConfig[crit] || criticalityConfig.MEDIUM;
                              return (
                                <div key={i} className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/20 flex items-center gap-3">
                                  <svg className="w-4 h-4 text-blue-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                                  </svg>
                                  <span className="font-mono text-sm flex-1 truncate">{t.name}</span>
                                  {t.type && t.type !== 'table' && (
                                    <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/20 text-blue-400">
                                      {t.type}
                                    </span>
                                  )}
                                  {t.platform && (
                                    <span className="text-xs text-[var(--muted)]">{t.platform}</span>
                                  )}
                                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${colors.text}`}>{crit}</span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Current Table */}
                      <div className="p-4 rounded-xl bg-purple-500/10 border-2 border-purple-500/30">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-lg bg-purple-500/20 flex items-center justify-center">
                            <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                            </svg>
                          </div>
                          <div>
                            <div className="font-mono font-semibold">{impactData.table}</div>
                            <div className="text-xs text-purple-400">Current Table (Issue Source)</div>
                          </div>
                        </div>
                      </div>

                      {/* Downstream */}
                      {impactData.downstreamTables && impactData.downstreamTables.length > 0 && (
                        <div>
                          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                            <svg className="w-4 h-4 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 13l-5 5m0 0l-5-5m5 5V6" />
                            </svg>
                            Downstream Impact ({impactData.downstreamTables.length})
                            {impactData.downstreamCritical! > 0 && (
                              <span className="ml-2 px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/20 text-red-400">
                                {impactData.downstreamCritical} critical
                              </span>
                            )}
                          </h3>
                          <div className="space-y-2 max-h-[300px] overflow-y-auto pr-2">
                            {impactData.downstreamTables.map((t, i) => {
                              const crit = (t.criticality as keyof typeof criticalityConfig) || 'MEDIUM';
                              const colors = criticalityConfig[crit] || criticalityConfig.MEDIUM;
                              const isReport = t.type === 'dashboard' || t.type === 'report';
                              return (
                                <div key={i} className={`p-3 rounded-lg ${colors.bg} ${colors.border} border flex items-center gap-3`}>
                                  <svg className={`w-4 h-4 ${colors.text} flex-shrink-0`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    {isReport ? (
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                                    ) : (
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                                    )}
                                  </svg>
                                  <span className="font-mono text-sm flex-1 truncate">{t.name}</span>
                                  {t.type && t.type !== 'table' && (
                                    <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                                      isReport ? 'bg-purple-500/20 text-purple-400' : 'bg-blue-500/20 text-blue-400'
                                    }`}>
                                      {t.type}
                                    </span>
                                  )}
                                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${colors.text}`}>{crit}</span>
                                  {t.distance && (
                                    <span className="text-xs text-[var(--muted)] whitespace-nowrap">{t.distance} hop{t.distance > 1 ? 's' : ''}</span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                          {impactData.downstreamTables.length > 8 && (
                            <p className="text-xs text-[var(--muted)] mt-2 text-center">
                              Showing all {impactData.downstreamTables.length} downstream dependencies
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Affected Reports - shown in both views */}
                  {impactData.usedInReports && impactData.usedInReports.length > 0 && (
                    <div className="pt-4 border-t border-[var(--subtle-border)]">
                      <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                        <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        Affected Reports & Dashboards
                      </h3>
                      <div className="flex flex-wrap gap-2">
                        {impactData.usedInReports.map((r, i) => (
                          <span key={i} className="px-3 py-1.5 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] text-sm">
                            {r}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Actions Tab */}
              {activeTab === 'actions' && (
                <div className="space-y-6">
                  {impactData.recommendedActions && impactData.recommendedActions.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                        <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                        </svg>
                        Recommended Actions
                      </h3>
                      <div className="space-y-3">
                        {impactData.recommendedActions.map((action, i) => (
                          <div key={i} className="p-4 rounded-lg bg-[var(--overlay-faint)] border border-[var(--subtle-border)] flex items-start gap-3">
                            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-xs font-bold">
                              {i + 1}
                            </span>
                            <span className="text-sm">{action}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Quick Actions */}
                  <div>
                    <h3 className="text-sm font-semibold mb-4">Quick Actions</h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 items-stretch">
                      <button className="p-4 rounded-lg bg-purple-500/10 border border-purple-500/20 hover:bg-purple-500/20 transition-colors text-left h-full flex flex-col gap-2 min-h-[130px]">
                        <div className="flex items-center gap-2">
                          <svg className="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                          </svg>
                          <span className="font-medium text-sm">Notify Slack</span>
                        </div>
                        <p className="text-xs text-[var(--muted)] leading-relaxed">Alert team via {impactData.slackChannel || '#data-alerts'}</p>
                      </button>
                      
                      <button className="p-4 rounded-lg bg-blue-500/10 border border-blue-500/20 hover:bg-blue-500/20 transition-colors text-left h-full flex flex-col gap-2 min-h-[130px]">
                        <div className="flex items-center gap-2">
                          <svg className="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                          </svg>
                          <span className="font-medium text-sm">Create Incident</span>
                        </div>
                        <p className="text-xs text-[var(--muted)] leading-relaxed">Open incident ticket</p>
                      </button>
                      
                      <button className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors text-left h-full flex flex-col gap-2 min-h-[130px]">
                        <div className="flex items-center gap-2">
                          <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                          <span className="font-medium text-sm">Apply Auto-Fix</span>
                        </div>
                        <p className="text-xs text-[var(--muted)] leading-relaxed">Run suggested remediation</p>
                      </button>
                      
                      <button className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/20 transition-colors text-left h-full flex flex-col gap-2 min-h-[130px]">
                        <div className="flex items-center gap-2">
                          <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          <span className="font-medium text-sm">Snooze Alert</span>
                        </div>
                        <p className="text-xs text-[var(--muted)] leading-relaxed">Silence for investigation</p>
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-12 text-[var(--muted)]">
              No impact data available.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
