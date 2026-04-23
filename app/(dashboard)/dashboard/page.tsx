'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { usePipeline } from '@/contexts/PipelineContext';
import { cn } from '@/lib/utils';
import { cachedFetch } from '@/lib/fetch-cache';
import { SetupBanner } from '../../../components/dashboard/SetupBanner';
import { ToolIcon } from '@/components/icons/ToolIcon';
import {
  MessageSquare,
  Database,
  GitBranch,
  Workflow,
  Clock,
  FileText,
  Users,
  Settings,
  CheckCircle2,
  BarChart3,
  ArrowUpRight,
  Sparkles,
  Plus,
} from 'lucide-react';

// --- Types ---

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

// --- Static data ---

const quickNavCards = [
  {
    name: 'AI Assistant',
    description: 'Chat with your data',
    href: '/dashboard/assistant',
    icon: MessageSquare,
    color: 'from-[var(--accent)]/20 to-[var(--accent)]/5',
    borderColor: 'border-[var(--accent)]/30 hover:border-[var(--accent)]/50',
    iconBg: 'bg-[var(--accent)]/20',
    iconColor: 'text-[var(--accent-2)]',
    highlighted: true,
  },
  {
    name: 'Sources',
    description: 'Browse tables & schemas',
    href: '/dashboard/sources',
    icon: Database,
    color: 'from-blue-500/10 to-blue-500/5',
    borderColor: 'border-blue-500/20 hover:border-blue-500/40',
    iconBg: 'bg-blue-500/10',
    iconColor: 'text-blue-400',
    highlighted: false,
  },
  {
    name: 'Lineage',
    description: 'Trace data flow',
    href: '/dashboard/lineage',
    icon: GitBranch,
    color: 'from-purple-500/10 to-purple-500/5',
    borderColor: 'border-purple-500/20 hover:border-purple-500/40',
    iconBg: 'bg-purple-500/10',
    iconColor: 'text-purple-400',
    highlighted: false,
  },
  {
    name: 'Pipeline',
    description: 'Manage connectors',
    href: '/dashboard/pipeline',
    icon: Workflow,
    color: 'from-indigo-500/10 to-indigo-500/5',
    borderColor: 'border-indigo-500/20 hover:border-indigo-500/40',
    iconBg: 'bg-indigo-500/10',
    iconColor: 'text-indigo-400',
    highlighted: false,
  },
  {
    name: 'Scheduled Tasks',
    description: 'Automated checks',
    href: '/dashboard/schedule',
    icon: Clock,
    color: 'from-amber-500/10 to-amber-500/5',
    borderColor: 'border-amber-500/20 hover:border-amber-500/40',
    iconBg: 'bg-amber-500/10',
    iconColor: 'text-amber-400',
    highlighted: false,
  },
  {
    name: 'Artifacts',
    description: 'Saved queries & insights',
    href: '/dashboard/artifacts',
    icon: FileText,
    color: 'from-emerald-500/10 to-emerald-500/5',
    borderColor: 'border-emerald-500/20 hover:border-emerald-500/40',
    iconBg: 'bg-emerald-500/10',
    iconColor: 'text-emerald-400',
    highlighted: false,
  },
  {
    name: 'Team',
    description: 'Manage members',
    href: '/dashboard/team',
    icon: Users,
    color: 'from-cyan-500/10 to-cyan-500/5',
    borderColor: 'border-cyan-500/20 hover:border-cyan-500/40',
    iconBg: 'bg-cyan-500/10',
    iconColor: 'text-cyan-400',
    highlighted: false,
  },
  {
    name: 'Settings',
    description: 'Workspace config',
    href: '/dashboard/settings',
    icon: Settings,
    color: 'from-[var(--subtle-bg)] to-[var(--overlay-faint)]',
    borderColor: 'border-[var(--subtle-border)] hover:border-[var(--overlay-strong)]',
    iconBg: 'bg-[var(--hover-bg)]',
    iconColor: 'text-[var(--text-tertiary)]',
    highlighted: false,
  },
];

// --- Animations ---

const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.06 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: 'easeOut' as const } },
};

// --- Component ---

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
          cachedFetch(`/api/pipeline?stackId=${selectedPipelineId}&excludeConfigs=true&includeStacksList=false`),
          cachedFetch(`/api/copilot/sessions?limit=6&pipelineStackId=${selectedPipelineId}`),
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

          setRecentChats(sessions.slice(0, 4).map((session: any) => ({
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
              const tablesRes = await cachedFetch(`/api/pipeline/${selectedPipelineId}/nodes/${connectedWarehouse.id}/tables`);
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

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto flex items-center justify-center min-h-[400px]">
        <div className="w-8 h-8 red-spinner" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <SetupBanner />
      {/* Welcome Section */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <h1 className="text-2xl font-semibold text-[var(--text)] mb-1">{getGreeting()}</h1>
        <p className="text-[var(--muted)] text-[15px]">
          {selectedPipeline
            ? <>Working on <span className="text-[var(--text-tertiary)] font-medium">{selectedPipeline.name}</span></>
            : "Here\u2019s an overview of your data stack"
          }
        </p>
      </motion.div>

      {/* Quick Navigation Cards */}
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3"
      >
        {quickNavCards.map((card) => {
          const Icon = card.icon;
          return (
            <motion.div key={card.name} variants={itemVariants}>
              <Link
                href={card.href}
                className={cn(
                  'group relative flex items-center gap-3 p-4 rounded-xl',
                  'bg-gradient-to-br border transition-all duration-200',
                  'hover:-translate-y-1 hover:shadow-lg hover:shadow-black/20',
                  card.color,
                  card.borderColor,
                )}
              >
                <div className={cn(
                  'w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0',
                  'transition-transform duration-200 group-hover:scale-105',
                  card.iconBg,
                )}>
                  <Icon className={cn('w-5 h-5', card.iconColor)} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <p className="text-[14px] font-medium text-[var(--text)] truncate">{card.name}</p>
                    {card.highlighted && (
                      <Sparkles className="w-3.5 h-3.5 text-[var(--accent-2)] flex-shrink-0" />
                    )}
                  </div>
                  <p className="text-[12px] text-[var(--muted)] truncate">{card.description}</p>
                </div>
                <ArrowUpRight className="w-4 h-4 text-transparent group-hover:text-[var(--muted)] transition-colors flex-shrink-0" />
              </Link>
            </motion.div>
          );
        })}
      </motion.div>

      {/* Stats Row */}
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 md:grid-cols-4 gap-3"
      >
        <motion.div variants={itemVariants}>
          <Link
            href="/dashboard/pipeline"
            className="flex items-center gap-3 p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] transition-all group"
          >
            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            </div>
            <div>
              <span className="text-xl font-semibold text-[var(--text)]">{stats.healthyIntegrations}</span>
              <p className="text-[12px] text-[var(--muted)]">Connected Sources</p>
            </div>
          </Link>
        </motion.div>

        <motion.div variants={itemVariants}>
          <Link
            href="/dashboard/sources"
            className="flex items-center gap-3 p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] transition-all group"
          >
            <div className="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center">
              <Database className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <span className="text-xl font-semibold text-[var(--text)]">{stats.totalTables || '\u2014'}</span>
              <p className="text-[12px] text-[var(--muted)]">Total Tables</p>
            </div>
          </Link>
        </motion.div>

        <motion.div variants={itemVariants}>
          <Link
            href="/dashboard/assistant"
            className="flex items-center gap-3 p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] transition-all group"
          >
            <div className="w-9 h-9 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <MessageSquare className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <span className="text-xl font-semibold text-[var(--text)]">{stats.totalChats}</span>
              <p className="text-[12px] text-[var(--muted)]">AI Conversations</p>
            </div>
          </Link>
        </motion.div>

        <motion.div variants={itemVariants}>
          <Link
            href="/dashboard/pipeline"
            className="flex items-center gap-3 p-4 rounded-xl bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] transition-all group"
          >
            <div className="w-9 h-9 rounded-lg bg-indigo-500/10 flex items-center justify-center">
              <BarChart3 className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <span className="text-xl font-semibold text-[var(--text)]">{stats.totalIntegrations}</span>
              <p className="text-[12px] text-[var(--muted)]">Pipeline Nodes</p>
            </div>
          </Link>
        </motion.div>
      </motion.div>

      {/* Activity Section — Two Column */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.3 }}
        className="grid grid-cols-1 lg:grid-cols-5 gap-6"
      >
        {/* Recent Conversations */}
        <div className="lg:col-span-3 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[15px] font-medium text-[var(--text)]">Recent Conversations</h2>
            <Link href="/dashboard/assistant" className="text-[12px] text-[var(--muted)] hover:text-[var(--text-tertiary)] transition-colors">
              View all
            </Link>
          </div>
          {recentChats.length === 0 ? (
            <div className="text-center py-8">
              <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-[var(--accent)]/10 flex items-center justify-center">
                <MessageSquare className="w-6 h-6 text-[var(--accent-2)]" />
              </div>
              <p className="text-[13px] text-[var(--muted)] mb-3">No conversations yet</p>
              <Link href="/dashboard/assistant" className="text-[12px] text-[var(--accent-2)] hover:underline">
                Start your first chat &rarr;
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {recentChats.map((chat) => (
                <Link
                  key={chat.id}
                  href={`/dashboard/assistant?session=${chat.id}`}
                  className="flex items-center gap-3 p-3 rounded-lg bg-[var(--overlay-faint)] border border-[var(--border-faint)] hover:border-[var(--border-medium)] transition-colors"
                >
                  <div className="w-8 h-8 rounded-lg bg-[var(--accent)]/10 flex items-center justify-center flex-shrink-0">
                    <MessageSquare className="w-4 h-4 text-[var(--accent-2)]" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-[var(--text)] truncate">{chat.title}</p>
                    <p className="text-[11px] text-[var(--muted)]">{chat.updatedAt}</p>
                  </div>
                  <ArrowUpRight className="w-3.5 h-3.5 text-transparent group-hover:text-[var(--text-faint)] flex-shrink-0" />
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Connected Sources */}
        <div className="lg:col-span-2 bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[15px] font-medium text-[var(--text)]">Connected Sources</h2>
            <Link href="/dashboard/pipeline" className="text-[12px] text-[var(--muted)] hover:text-[var(--text-tertiary)] transition-colors">
              Manage
            </Link>
          </div>
          {integrations.length === 0 ? (
            <div className="text-center py-8">
              <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-[var(--subtle-bg)] flex items-center justify-center">
                <Plus className="w-6 h-6 text-[var(--text-faint)]" />
              </div>
              <p className="text-[13px] text-[var(--muted)] mb-3">No sources connected</p>
              <Link href="/dashboard/pipeline" className="text-[12px] text-[var(--accent-2)] hover:underline">
                Add your first source &rarr;
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {integrations.map((integration) => (
                <div
                  key={integration.id}
                  className="flex items-center gap-3 p-3 rounded-lg bg-[var(--overlay-faint)] border border-[var(--border-faint)]"
                >
                  <ToolIcon
                    toolType={integration.type}
                    size={32}
                    className="bg-[var(--subtle-bg)]"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-[var(--text)] truncate">{integration.name}</p>
                    <p className="text-[11px] text-[var(--muted)]">{integration.lastSync}</p>
                  </div>
                  <div className={`w-2 h-2 rounded-full ${integration.status === 'CONNECTED' ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                </div>
              ))}
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
