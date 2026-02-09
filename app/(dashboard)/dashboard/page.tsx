'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePipeline } from '@/contexts/PipelineContext';

interface Integration {
  id: string;
  name: string;
  type: string;
  status: string;
  lastSync?: string;
}

interface ChatSession {
  id: string;
  title: string;
  updatedAt: string;
  lastMessage?: string;
}

interface DashboardStats {
  totalIntegrations: number;
  healthyIntegrations: number;
  totalTables: number;
  totalChats: number;
}

const integrationIcons: Record<string, React.ReactNode> = {
  SNOWFLAKE: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
    </svg>
  ),
  BIGQUERY: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
    </svg>
  ),
  DBT_CLOUD: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L2 7v10l10 5 10-5V7l-10-5z" />
    </svg>
  ),
  POSTGRES: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
    </svg>
  ),
};

export default function DashboardPage() {
  const { selectedPipelineId, selectedPipeline, loading: pipelineLoading } = usePipeline();
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [recentChats, setRecentChats] = useState<ChatSession[]>([]);
  const [stats, setStats] = useState<DashboardStats>({
    totalIntegrations: 0,
    healthyIntegrations: 0,
    totalTables: 0,
    totalChats: 0,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Wait for pipeline context to load
    if (pipelineLoading) return;
    if (!selectedPipelineId) {
      setLoading(false);
      return;
    }

    const fetchDashboardData = async () => {
      let pipelineData: any = null;

      try {
        // Fetch pipeline and chat sessions in parallel (optimized with excludeConfigs and no stacks list)
        const [pipelineRes, chatsRes] = await Promise.all([
          fetch(`/api/pipeline?stackId=${selectedPipelineId}&excludeConfigs=true&includeStacksList=false`),
          fetch(`/api/copilot/sessions?limit=6&pipelineStackId=${selectedPipelineId}`),
        ]);

        if (pipelineRes.ok) {
          pipelineData = await pipelineRes.json();
          const nodes = pipelineData.stack?.nodes || [];
          const connectedNodes = nodes.filter((n: any) => n.status === 'CONNECTED');

          setIntegrations(connectedNodes.map((node: any) => ({
            id: node.id,
            name: node.name,
            type: node.toolType?.toUpperCase() || 'UNKNOWN',
            status: node.status,
            lastSync: 'Connected',
          })));

          setStats(prev => ({
            ...prev,
            totalIntegrations: nodes.length,
            healthyIntegrations: connectedNodes.length,
          }));
        }

        if (chatsRes.ok) {
          const chatsData = await chatsRes.json();
          const sessions = chatsData.sessions || [];

          setRecentChats(sessions.slice(0, 3).map((session: any) => ({
            id: session.id,
            title: session.title || 'New Chat',
            updatedAt: formatTimeAgo(session.updatedAt),
            lastMessage: session.lastMessage,
          })));

          setStats(prev => ({
            ...prev,
            totalChats: sessions.length,
          }));
        }

        // Fetch table count from sources (if available)
        // First try cached data from the sources page (scoped by pipeline)
        const cachedSources = localStorage.getItem(`pallisade_sources_cache_${selectedPipelineId}`);
        let tableCountFound = false;
        
        if (cachedSources) {
          try {
            const sourcesData = JSON.parse(cachedSources);
            let tableCount = 0;
            // The cache structure has "data" not "nodeData"
            Object.values(sourcesData.data || {}).forEach((nodeData: any) => {
              tableCount += nodeData.tables?.length || 0;
            });
            if (tableCount > 0) {
              setStats(prev => ({
                ...prev,
                totalTables: tableCount,
              }));
              tableCountFound = true;
            }
          } catch (e) {
            console.error('Error parsing cached sources:', e);
          }
        }
        
        // Fallback to generic cache
        if (!tableCountFound) {
          const genericCache = localStorage.getItem('pallisade_sources_cache');
          if (genericCache) {
            try {
              const sourcesData = JSON.parse(genericCache);
              let tableCount = 0;
              Object.values(sourcesData.data || {}).forEach((nodeData: any) => {
                tableCount += nodeData.tables?.length || 0;
              });
              if (tableCount > 0) {
                setStats(prev => ({
                  ...prev,
                  totalTables: tableCount,
                }));
                tableCountFound = true;
              }
            } catch (e) {
              console.error('Error parsing cached sources:', e);
            }
          }
        }
        
        // If no cache, fetch tables from connected warehouse nodes
        if (!tableCountFound && pipelineData) {
          const nodes = pipelineData.stack?.nodes || [];
          const connectedWarehouse = nodes.find((n: any) => 
            (n.status === 'CONNECTED' || n.status === 'ACTIVE') && n.layer === 'WAREHOUSE'
          );
          
          if (connectedWarehouse && selectedPipelineId) {
            try {
              const tablesRes = await fetch(`/api/pipeline/${selectedPipelineId}/nodes/${connectedWarehouse.id}/tables`);
              if (tablesRes.ok) {
                const tablesData = await tablesRes.json();
                const tableCount = tablesData.tables?.length || 0;
                if (tableCount > 0) {
                  setStats(prev => ({
                    ...prev,
                    totalTables: tableCount,
                  }));
                }
              }
            } catch (e) {
              console.error('Error fetching tables:', e);
            }
          }
        }

      } catch (error) {
        console.error('Failed to fetch dashboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, [selectedPipelineId, pipelineLoading]);

  const formatTimeAgo = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    return date.toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-white/50">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Welcome Section */}
      <div>
        <h1 className="text-2xl font-semibold text-white mb-1">Welcome back</h1>
        <p className="text-white/50 text-[15px]">
          Here&apos;s an overview of your data stack
        </p>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <span className="text-2xl font-semibold text-white">{stats.healthyIntegrations}</span>
          </div>
          <p className="text-[13px] text-white/50">Connected Sources</p>
        </div>

        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
              </svg>
            </div>
            <span className="text-2xl font-semibold text-white">{stats.totalTables || '—'}</span>
          </div>
          <p className="text-[13px] text-white/50">Total Tables</p>
        </div>

        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <span className="text-2xl font-semibold text-white">{stats.totalChats}</span>
          </div>
          <p className="text-[13px] text-white/50">AI Conversations</p>
        </div>

        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
              </svg>
            </div>
            <span className="text-2xl font-semibold text-white">{stats.totalIntegrations}</span>
          </div>
          <p className="text-[13px] text-white/50">Pipeline Nodes</p>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Quick Actions */}
        <div className="lg:col-span-2 bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
          <h2 className="text-[15px] font-medium text-white mb-4">Quick Actions</h2>
          <div className="grid grid-cols-2 gap-3">
            <Link
              href="/dashboard/chat"
              className="flex items-center gap-3 p-4 rounded-lg bg-gradient-to-br from-[var(--accent)]/15 to-[var(--accent)]/5 border border-[var(--accent)]/30 hover:border-[var(--accent)]/50 transition-colors group"
            >
              <div className="w-10 h-10 rounded-lg bg-[var(--accent)]/20 flex items-center justify-center group-hover:bg-[var(--accent)]/30 transition-colors">
                <svg className="w-5 h-5 text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
              <div>
                <p className="text-[14px] font-medium text-white">Ask AI</p>
                <p className="text-[12px] text-white/40">Query your data warehouse</p>
              </div>
            </Link>

            <Link
              href="/dashboard/sources"
              className="flex items-center gap-3 p-4 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.12] transition-colors group"
            >
              <div className="w-10 h-10 rounded-lg bg-white/[0.05] flex items-center justify-center group-hover:bg-white/[0.08] transition-colors">
                <svg className="w-5 h-5 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                </svg>
              </div>
              <div>
                <p className="text-[14px] font-medium text-white">View Sources</p>
                <p className="text-[12px] text-white/40">Browse your tables</p>
              </div>
            </Link>

            <Link
              href="/dashboard/pipeline"
              className="flex items-center gap-3 p-4 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.12] transition-colors group"
            >
              <div className="w-10 h-10 rounded-lg bg-white/[0.05] flex items-center justify-center group-hover:bg-white/[0.08] transition-colors">
                <svg className="w-5 h-5 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
                </svg>
              </div>
              <div>
                <p className="text-[14px] font-medium text-white">Build Pipeline</p>
                <p className="text-[12px] text-white/40">Design your data flow</p>
              </div>
            </Link>

            <Link
              href="/dashboard/settings"
              className="flex items-center gap-3 p-4 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.12] transition-colors group"
            >
              <div className="w-10 h-10 rounded-lg bg-white/[0.05] flex items-center justify-center group-hover:bg-white/[0.08] transition-colors">
                <svg className="w-5 h-5 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.204-.107-.397.165-.71.505-.78.929l-.15.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.107-1.204l-.527-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </div>
              <div>
                <p className="text-[14px] font-medium text-white">Settings</p>
                <p className="text-[12px] text-white/40">Configure your workspace</p>
              </div>
            </Link>
          </div>
        </div>

        {/* Connected Sources */}
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[15px] font-medium text-white">Connected Sources</h2>
            <Link href="/dashboard/pipeline" className="text-[12px] text-white/40 hover:text-white transition-colors">
              Manage
            </Link>
          </div>
          {integrations.length === 0 ? (
            <div className="text-center py-8">
              <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-white/[0.05] flex items-center justify-center">
                <svg className="w-6 h-6 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v6m3-3H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <p className="text-[13px] text-white/50 mb-3">No sources connected</p>
              <Link href="/dashboard/pipeline" className="text-[12px] text-[var(--accent-2)] hover:underline">
                Add your first source →
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {integrations.map((integration) => (
                <div
                  key={integration.id}
                  className="flex items-center gap-3 p-3 rounded-lg bg-white/[0.02] border border-white/[0.04]"
                >
                  <div className="w-8 h-8 rounded-lg bg-white/[0.05] flex items-center justify-center text-white/60">
                    {integrationIcons[integration.type] || (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7" />
                      </svg>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-white truncate">{integration.name}</p>
                    <p className="text-[11px] text-white/40">{integration.lastSync}</p>
                  </div>
                  <div className={`w-2 h-2 rounded-full ${integration.status === 'CONNECTED' ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recent Chats */}
      <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[15px] font-medium text-white">Recent Conversations</h2>
          <Link href="/dashboard/chat" className="text-[12px] text-white/40 hover:text-white transition-colors">
            View all
          </Link>
        </div>
        {recentChats.length === 0 ? (
          <div className="text-center py-8">
            <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-[var(--accent)]/10 flex items-center justify-center">
              <svg className="w-6 h-6 text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <p className="text-[13px] text-white/50 mb-3">No conversations yet</p>
            <Link href="/dashboard/chat" className="text-[12px] text-[var(--accent-2)] hover:underline">
              Start your first chat →
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {recentChats.map((chat) => (
              <Link
                key={chat.id}
                href={`/dashboard/chat?session=${chat.id}`}
                className="p-4 rounded-lg bg-white/[0.02] border border-white/[0.04] hover:border-white/[0.08] transition-colors"
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-lg bg-[var(--accent)]/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <svg className="w-4 h-4 text-[var(--accent-2)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-white line-clamp-2 mb-1">{chat.title}</p>
                    <p className="text-[11px] text-white/40">{chat.updatedAt}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
