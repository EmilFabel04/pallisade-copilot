'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

// Mock data - in production, fetch from API
const mockIntegrations = [
  { id: '1', name: 'Snowflake', type: 'SNOWFLAKE', status: 'ACTIVE', lastSync: '5 min ago' },
  { id: '2', name: 'dbt Cloud', type: 'DBT_CLOUD', status: 'ACTIVE', lastSync: '1 hour ago' },
  { id: '3', name: 'Fivetran', type: 'FIVETRAN', status: 'ACTIVE', lastSync: '10 min ago' },
];

const mockRecentChats = [
  { id: '1', title: 'Debug stale data in dim_customers', date: '2 hours ago', model: 'claude-sonnet' },
  { id: '2', title: 'What tables depend on raw.orders?', date: 'Yesterday', model: 'claude-sonnet' },
  { id: '3', title: 'Fix failing dbt test', date: '2 days ago', model: 'claude-sonnet' },
];

const integrationIcons: Record<string, React.ReactNode> = {
  SNOWFLAKE: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
    </svg>
  ),
  DBT_CLOUD: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L2 7v10l10 5 10-5V7l-10-5z" />
    </svg>
  ),
  FIVETRAN: (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <circle cx="12" cy="12" r="10" />
    </svg>
  ),
};

export default function DashboardPage() {
  const [stats, setStats] = useState({
    totalIntegrations: 3,
    healthyIntegrations: 3,
    totalTables: 47,
    activeAlerts: 2,
  });

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
          <p className="text-[13px] text-white/50">Healthy Sources</p>
        </div>

        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
              </svg>
            </div>
            <span className="text-2xl font-semibold text-white">{stats.totalTables}</span>
          </div>
          <p className="text-[13px] text-white/50">Total Tables</p>
        </div>

        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z" />
              </svg>
            </div>
            <span className="text-2xl font-semibold text-white">156</span>
          </div>
          <p className="text-[13px] text-white/50">Lineage Nodes</p>
        </div>

        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-lg bg-amber-500/10 flex items-center justify-center">
              <svg className="w-5 h-5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            <span className="text-2xl font-semibold text-white">{stats.activeAlerts}</span>
          </div>
          <p className="text-[13px] text-white/50">Active Alerts</p>
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
                <p className="text-[12px] text-white/40">Debug or explore your data</p>
              </div>
            </Link>

            <Link
              href="/dashboard/lineage"
              className="flex items-center gap-3 p-4 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.12] transition-colors group"
            >
              <div className="w-10 h-10 rounded-lg bg-white/[0.05] flex items-center justify-center group-hover:bg-white/[0.08] transition-colors">
                <svg className="w-5 h-5 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z" />
                </svg>
              </div>
              <div>
                <p className="text-[14px] font-medium text-white">Explore Lineage</p>
                <p className="text-[12px] text-white/40">View data dependencies</p>
              </div>
            </Link>

            <Link
              href="/dashboard/sources"
              className="flex items-center gap-3 p-4 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.12] transition-colors group"
            >
              <div className="w-10 h-10 rounded-lg bg-white/[0.05] flex items-center justify-center group-hover:bg-white/[0.08] transition-colors">
                <svg className="w-5 h-5 text-white/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v6m3-3H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <p className="text-[14px] font-medium text-white">Add Source</p>
                <p className="text-[12px] text-white/40">Connect a new integration</p>
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
          </div>
        </div>

        {/* Connected Sources */}
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[15px] font-medium text-white">Connected Sources</h2>
            <Link href="/dashboard/sources" className="text-[12px] text-white/40 hover:text-white transition-colors">
              View all
            </Link>
          </div>
          <div className="space-y-2">
            {mockIntegrations.map((integration) => (
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
                <div className="w-2 h-2 rounded-full bg-emerald-500" />
              </div>
            ))}
          </div>
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
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {mockRecentChats.map((chat) => (
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
                  <p className="text-[11px] text-white/40">{chat.date}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
