'use client';

import { useState, useEffect, type ReactNode } from 'react';
import { useSession } from 'next-auth/react';
import { useTheme } from '@/contexts/ThemeContext';
import { cachedFetch } from '@/lib/fetch-cache';
import { Settings as SettingsIcon, Plug, Bell, Key, CreditCard, MessageSquare, ClipboardList, Link, AlertTriangle, User, SlidersHorizontal } from 'lucide-react';

interface OAuthIntegration {
  id: string;
  name: string;
  type: string;
  status: string;
  metadata?: {
    username?: string;
    avatar?: string;
    repoCount?: number;
  };
  createdAt: string;
}

interface SlackConfig {
  connected: boolean;
  channel?: string;
  teamName?: string;
  alertOnCritical: boolean;
  alertOnHigh: boolean;
  alertOnScanComplete: boolean;
  alertOnPrCreated: boolean;
  alertOnTeamInvite: boolean;
}

export default function SettingsPage() {
  const { data: session } = useSession();
  const { theme, toggleTheme } = useTheme();
  const [activeTab, setActiveTab] = useState('general');
  const [savedNotification, setSavedNotification] = useState(false);
  const [oauthIntegrations, setOauthIntegrations] = useState<OAuthIntegration[]>([]);
  const [loadingIntegrations, setLoadingIntegrations] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  // Slack state (preferences only — connection managed on Pipeline page)
  const [slackConfig, setSlackConfig] = useState<SlackConfig | null>(null);
  const [slackLoading, setSlackLoading] = useState(false);

  const showSaved = () => {
    setSavedNotification(true);
    setTimeout(() => setSavedNotification(false), 2000);
  };

  const fetchSlackConfig = async () => {
    setSlackLoading(true);
    try {
      const res = await cachedFetch('/api/integrations/slack');
      if (res.ok) {
        const data = await res.json();
        setSlackConfig(data);
      }
    } catch (error) {
      console.error('Failed to fetch Slack config:', error);
    } finally {
      setSlackLoading(false);
    }
  };

  const handleSlackToggle = async (key: string, value: boolean) => {
    if (!slackConfig) return;
    setSlackConfig({ ...slackConfig, [key]: value });
    try {
      await fetch('/api/integrations/slack', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      });
    } catch (error) {
      console.error('Failed to update Slack preference:', error);
      // Revert on failure
      setSlackConfig({ ...slackConfig, [key]: !value });
    }
  };

  // Fetch OAuth integrations when the integrations tab is active
  useEffect(() => {
    if (activeTab === 'integrations') {
      fetchIntegrations();
    }
    if (activeTab === 'notifications') {
      fetchSlackConfig();
    }
  }, [activeTab]);

  const fetchIntegrations = async () => {
    setLoadingIntegrations(true);
    try {
      const res = await cachedFetch('/api/integrations');
      if (res.ok) {
        const data = await res.json();
        // Filter to only OAuth integrations (not pipeline nodes)
        const oauth = data.integrations?.filter((i: any) =>
          ['GITHUB', 'SLACK', 'JIRA', 'TEAMS', 'PAGERDUTY', 'OPSGENIE'].includes(i.type)
        ) || [];
        setOauthIntegrations(oauth);
      }
    } catch (error) {
      console.error('Failed to fetch integrations:', error);
    } finally {
      setLoadingIntegrations(false);
    }
  };

  const handleDisconnect = async (id: string) => {
    setDeletingId(id);
    try {
      const res = await fetch(`/api/integrations/${id}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setOauthIntegrations(prev => prev.filter(i => i.id !== id));
        setConfirmDelete(null);
      } else {
        alert('Failed to disconnect integration');
      }
    } catch (error) {
      console.error('Failed to disconnect:', error);
      alert('Failed to disconnect integration');
    } finally {
      setDeletingId(null);
    }
  };

  const getIntegrationIcon = (type: string) => {
    switch (type) {
      case 'GITHUB':
        return (
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
          </svg>
        );
      case 'SLACK':
        return <MessageSquare size={20} />;
      case 'JIRA':
        return <ClipboardList size={20} />;
      default:
        return <Link size={20} />;
    }
  };

  const tabs: { id: string; name: string; icon: ReactNode }[] = [
    { id: 'general', name: 'General', icon: <SettingsIcon size={16} /> },
    { id: 'integrations', name: 'Integrations', icon: <Plug size={16} /> },
    { id: 'notifications', name: 'Notifications', icon: <Bell size={16} /> },
    { id: 'api', name: 'API Keys', icon: <Key size={16} /> },
    { id: 'billing', name: 'Billing', icon: <CreditCard size={16} /> },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-[var(--text)] mb-1">Settings</h1>
        <p className="text-[var(--muted)] text-[14px]">
          Manage your account and preferences
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-xl bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              flex items-center gap-2 px-4 py-2 text-[13px] font-medium rounded-lg transition-all
              ${activeTab === tab.id
                ? 'bg-[var(--subtle-bg)] text-[var(--text)] shadow-sm'
                : 'text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-faint)]'
              }
            `}
          >
            {tab.icon}
            {tab.name}
          </button>
        ))}
      </div>

      {/* General Tab */}
      {activeTab === 'general' && (
        <div className="space-y-6">
          {/* Profile Section */}
          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2"><User size={16} className="text-[var(--muted)]" /> Profile</h2>
            <div className="flex items-start gap-6">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center text-white text-2xl font-semibold">
                {session?.user?.name?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="flex-1 space-y-4">
                <div>
                  <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">Full Name</label>
                  <input
                    type="text"
                    defaultValue={session?.user?.name || ''}
                    className="w-full max-w-md px-4 py-2.5 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 text-[14px] transition-all"
                  />
                </div>
                <div>
                  <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">Email</label>
                  <input
                    type="email"
                    defaultValue={session?.user?.email || ''}
                    disabled
                    className="w-full max-w-md px-4 py-2.5 rounded-lg bg-[var(--overlay-faint)] border border-[var(--border-faint)] text-[var(--muted)] text-[14px] cursor-not-allowed"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Preferences Section */}
          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2"><SlidersHorizontal size={16} className="text-[var(--muted)]" /> Preferences</h2>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[14px] font-medium text-[var(--text)]">Light Mode</p>
                  <p className="text-[12px] text-[var(--muted)]">Use a lighter background</p>
                </div>
                <button
                  onClick={toggleTheme}
                  className={`relative w-9 h-5 rounded-full transition-colors ${
                    theme === 'light' ? 'bg-[var(--accent)]' : 'bg-[var(--overlay-medium)]'
                  }`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
                    theme === 'light' ? 'translate-x-4' : 'translate-x-0'
                  }`} />
                </button>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[14px] font-medium text-[var(--text)]">Compact Mode</p>
                  <p className="text-[12px] text-[var(--muted)]">Use a more compact UI layout</p>
                </div>
                <button className="relative w-9 h-5 rounded-full bg-[var(--overlay-medium)] transition-colors">
                  <span className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform translate-x-0" />
                </button>
              </div>
            </div>
          </div>

          <button
            onClick={showSaved}
            className="px-6 py-2.5 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-[13px] font-medium transition-all shadow-sm hover:shadow-md"
          >
            Save Changes
          </button>
        </div>
      )}

      {/* Integrations Tab */}
      {activeTab === 'integrations' && (
        <div className="space-y-6">
          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-[15px] font-semibold text-[var(--text)] flex items-center gap-2"><Plug size={16} className="text-[var(--muted)]" /> Connected Accounts</h2>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Manage OAuth connections for GitHub, Slack, and other services
                </p>
              </div>
            </div>

            {loadingIntegrations ? (
              <div className="flex items-center justify-center py-8">
                <div className="w-8 h-8 red-spinner" />
              </div>
            ) : oauthIntegrations.length === 0 ? (
              <div className="text-center py-8">
                <div className="w-12 h-12 rounded-xl bg-[var(--subtle-bg)] flex items-center justify-center mx-auto mb-3">
                  <svg className="w-6 h-6 text-[var(--text-faint)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                </div>
                <p className="text-[var(--muted)] text-[14px]">No OAuth integrations connected</p>
                <p className="text-[var(--text-faint)] text-[12px] mt-1">
                  Connect GitHub, Slack, or other services from the Pipeline page
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {oauthIntegrations.map((integration) => (
                  <div
                    key={integration.id}
                    className="flex items-center justify-between p-4 rounded-xl bg-[var(--overlay-faint)] border border-[var(--subtle-border)]"
                  >
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 rounded-lg bg-[var(--subtle-bg)] flex items-center justify-center text-[var(--text)]">
                        {integration.metadata?.avatar ? (
                          <img
                            src={integration.metadata.avatar}
                            alt=""
                            className="w-10 h-10 rounded-lg"
                          />
                        ) : (
                          getIntegrationIcon(integration.type)
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="text-[14px] font-medium text-[var(--text)]">{integration.type}</p>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                            integration.status === 'ACTIVE'
                              ? 'bg-emerald-500/20 text-emerald-400'
                              : 'bg-yellow-500/20 text-yellow-400'
                          }`}>
                            {integration.status}
                          </span>
                          {(integration as any).managedByPipeline && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/20 text-blue-400">
                              Pipeline-managed
                            </span>
                          )}
                        </div>
                        {integration.metadata?.username && (
                          <p className="text-[12px] text-[var(--muted)]">@{integration.metadata.username}</p>
                        )}
                        {integration.metadata?.repoCount && (
                          <p className="text-[11px] text-[var(--text-faint)]">{integration.metadata.repoCount} repositories</p>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {(integration as any).managedByPipeline ? (
                        <span className="px-3 py-1.5 text-[12px] text-[var(--text-faint)] italic">
                          Manage in Pipeline
                        </span>
                      ) : confirmDelete === integration.id ? (
                        <>
                          <button
                            onClick={() => setConfirmDelete(null)}
                            className="px-3 py-1.5 rounded-lg bg-[var(--subtle-bg)] hover:bg-[var(--hover-bg)] text-[var(--text-tertiary)] text-[12px] font-medium transition-colors"
                          >
                            Cancel
                          </button>
                          <button
                            onClick={() => handleDisconnect(integration.id)}
                            disabled={deletingId === integration.id}
                            className="px-3 py-1.5 rounded-lg bg-red-500/20 hover:bg-red-500/30 text-red-400 text-[12px] font-medium transition-colors disabled:opacity-50"
                          >
                            {deletingId === integration.id ? 'Disconnecting...' : 'Confirm Disconnect'}
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => setConfirmDelete(integration.id)}
                          className="px-3 py-1.5 rounded-lg bg-[var(--subtle-bg)] hover:bg-red-500/10 text-[var(--muted)] hover:text-red-400 text-[12px] font-medium transition-colors"
                        >
                          Disconnect
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle size={18} className="text-amber-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-[13px] font-medium text-amber-400">Disconnecting an integration</p>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Disconnecting will remove the OAuth token and revoke access. The AI assistant will no longer be able to access repositories or create pull requests using this connection.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Notifications Tab */}
      {activeTab === 'notifications' && (
        <div className="space-y-6">
          {/* Slack Notifications */}
          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <h2 className="text-[15px] font-semibold text-[var(--text)]">Slack Notifications</h2>
                {slackLoading ? (
                  <div className="w-4 h-4 border-2 border-[var(--text-faint)] border-t-[var(--text-tertiary)] rounded-full animate-spin" />
                ) : slackConfig?.connected ? (
                  <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/20 text-emerald-400">
                    Connected
                  </span>
                ) : (
                  <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/20 text-amber-400">
                    Not Connected
                  </span>
                )}
              </div>
              {!slackConfig?.connected && (
                <a
                  href="/dashboard/pipeline"
                  className="text-[12px] text-[var(--muted)] hover:text-[var(--text-tertiary)] underline transition-colors"
                >
                  Connect on Pipeline page
                </a>
              )}
            </div>
            <div className="space-y-4">
              {[
                { key: 'alertOnCritical', label: 'Monitor Alerts (Critical)', desc: 'When a scheduled monitor reports a critical failure' },
                { key: 'alertOnHigh', label: 'Monitor Alerts (High)', desc: 'When a scheduled monitor reports a high-severity issue' },
                { key: 'alertOnScanComplete', label: 'Scan Completion', desc: 'When a data scan finishes running' },
                { key: 'alertOnPrCreated', label: 'Change Plan PR Created', desc: 'When a change plan is applied and a PR is opened' },
                { key: 'alertOnTeamInvite', label: 'Team Invites', desc: 'When a new team member is invited' },
              ].map((item) => {
                const enabled = slackConfig?.[item.key as keyof SlackConfig] as boolean ?? true;
                const disabled = !slackConfig?.connected;
                return (
                  <div key={item.key} className={`flex items-center justify-between ${disabled ? 'opacity-40' : ''}`}>
                    <div>
                      <p className="text-[14px] font-medium text-[var(--text)]">{item.label}</p>
                      <p className="text-[12px] text-[var(--muted)]">{item.desc}</p>
                    </div>
                    <button
                      onClick={() => !disabled && handleSlackToggle(item.key, !enabled)}
                      disabled={disabled}
                      className={`relative w-9 h-5 rounded-full transition-colors ${
                        enabled ? 'bg-[var(--accent)]' : 'bg-[var(--overlay-medium)]'
                      } ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                    >
                      <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${enabled ? 'translate-x-4' : 'translate-x-0'}`} />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Email Notifications */}
          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[15px] font-semibold text-[var(--text)]">Email Notifications</h2>
              <span className="text-[11px] text-[var(--text-faint)] px-2 py-0.5 rounded bg-[var(--overlay-bg)]">Coming soon</span>
            </div>
            <div className="space-y-4 opacity-50">
              {[
                { id: 'alerts', label: 'Data Alerts', desc: 'Get notified about data quality issues', enabled: true },
                { id: 'sync', label: 'Sync Failures', desc: 'Notifications when sources fail to sync', enabled: true },
                { id: 'weekly', label: 'Weekly Digest', desc: 'Weekly summary of your data health', enabled: false },
              ].map((item) => (
                <div key={item.id} className="flex items-center justify-between">
                  <div>
                    <p className="text-[14px] font-medium text-[var(--text)]">{item.label}</p>
                    <p className="text-[12px] text-[var(--muted)]">{item.desc}</p>
                  </div>
                  <button
                    disabled
                    className={`relative w-9 h-5 rounded-full transition-colors cursor-not-allowed ${item.enabled ? 'bg-[var(--accent)]' : 'bg-[var(--overlay-medium)]'}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${item.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* API Keys Tab */}
      {activeTab === 'api' && (
        <div className="space-y-6">
          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[15px] font-semibold text-[var(--text)] flex items-center gap-2"><Key size={16} className="text-[var(--muted)]" /> API Keys</h2>
              <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--subtle-bg)] hover:bg-[var(--hover-bg)] text-[var(--text)] text-[12px] font-medium transition-colors">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Create Key
              </button>
            </div>
            <div className="text-center py-8">
              <div className="w-12 h-12 rounded-xl bg-[var(--subtle-bg)] flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6 text-[var(--text-faint)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
                </svg>
              </div>
              <p className="text-[var(--muted)] text-[14px]">No API keys created yet</p>
            </div>
          </div>
        </div>
      )}

      {/* Billing Tab */}
      {activeTab === 'billing' && (
        <div className="space-y-6">
          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4 flex items-center gap-2"><CreditCard size={16} className="text-[var(--muted)]" /> Current Plan</h2>
            <div className="flex items-center justify-between p-4 rounded-xl bg-gradient-to-br from-[var(--accent)]/10 to-[var(--accent)]/5 border border-[var(--accent)]/20">
              <div>
                <p className="text-[18px] font-semibold text-[var(--text)] mb-1">Pro Plan</p>
                <p className="text-[13px] text-[var(--muted)]">Unlimited sources, priority support</p>
              </div>
              <div className="text-right">
                <p className="text-[24px] font-bold text-[var(--text)]">$99<span className="text-[14px] font-normal text-[var(--muted)]">/mo</span></p>
              </div>
            </div>
          </div>

          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <h2 className="text-[15px] font-semibold text-[var(--text)] mb-4">Usage This Month</h2>
            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[13px] text-[var(--text-tertiary)]">AI Queries</span>
                  <span className="text-[13px] text-[var(--text)]">1,247 / 5,000</span>
                </div>
                <div className="h-2 rounded-full bg-[var(--overlay-medium)]">
                  <div className="h-full w-[25%] rounded-full bg-[var(--accent)]" />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[13px] text-[var(--text-tertiary)]">Data Sources</span>
                  <span className="text-[13px] text-[var(--text)]">3 / 10</span>
                </div>
                <div className="h-2 rounded-full bg-[var(--overlay-medium)]">
                  <div className="h-full w-[30%] rounded-full bg-blue-500" />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Saved Notification */}
      {savedNotification && (
        <div className="fixed bottom-6 right-6 flex items-center gap-2 px-4 py-3 rounded-lg bg-emerald-500 text-white text-[13px] font-medium shadow-lg animate-fade-in">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Changes saved
        </div>
      )}
    </div>
  );
}
