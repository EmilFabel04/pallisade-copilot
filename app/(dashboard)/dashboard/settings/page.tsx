'use client';

import { useState } from 'react';
import { useSession } from 'next-auth/react';

export default function SettingsPage() {
  const { data: session } = useSession();
  const [activeTab, setActiveTab] = useState('general');
  const [savedNotification, setSavedNotification] = useState(false);

  const showSaved = () => {
    setSavedNotification(true);
    setTimeout(() => setSavedNotification(false), 2000);
  };

  const tabs = [
    { id: 'general', name: 'General', icon: '⚙️' },
    { id: 'notifications', name: 'Notifications', icon: '🔔' },
    { id: 'api', name: 'API Keys', icon: '🔑' },
    { id: 'billing', name: 'Billing', icon: '💳' },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-white mb-1">Settings</h1>
        <p className="text-white/50 text-[14px]">
          Manage your account and preferences
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-white/[0.06]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              flex items-center gap-2 px-4 py-3 text-[13px] font-medium border-b-2 -mb-px transition-colors
              ${activeTab === tab.id
                ? 'border-[var(--accent)] text-white'
                : 'border-transparent text-white/50 hover:text-white'
              }
            `}
          >
            <span>{tab.icon}</span>
            {tab.name}
          </button>
        ))}
      </div>

      {/* General Tab */}
      {activeTab === 'general' && (
        <div className="space-y-6">
          {/* Profile Section */}
          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
            <h2 className="text-[15px] font-medium text-white mb-4">Profile</h2>
            <div className="flex items-start gap-6">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center text-white text-2xl font-semibold">
                {session?.user?.name?.[0]?.toUpperCase() || 'U'}
              </div>
              <div className="flex-1 space-y-4">
                <div>
                  <label className="block text-[13px] font-medium text-white/70 mb-2">Full Name</label>
                  <input
                    type="text"
                    defaultValue={session?.user?.name || ''}
                    className="w-full max-w-md px-4 py-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white focus:outline-none focus:border-white/[0.15] text-[14px]"
                  />
                </div>
                <div>
                  <label className="block text-[13px] font-medium text-white/70 mb-2">Email</label>
                  <input
                    type="email"
                    defaultValue={session?.user?.email || ''}
                    disabled
                    className="w-full max-w-md px-4 py-2.5 rounded-lg bg-white/[0.02] border border-white/[0.04] text-white/50 text-[14px] cursor-not-allowed"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Preferences Section */}
          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
            <h2 className="text-[15px] font-medium text-white mb-4">Preferences</h2>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[14px] font-medium text-white">Default AI Model</p>
                  <p className="text-[12px] text-white/40">Choose the default model for new chats</p>
                </div>
                <select className="px-4 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white text-[13px] focus:outline-none focus:border-white/[0.15]">
                  <option value="claude-sonnet">Claude Sonnet (Fast)</option>
                  <option value="claude-opus">Claude Opus (Powerful)</option>
                </select>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[14px] font-medium text-white">Compact Mode</p>
                  <p className="text-[12px] text-white/40">Use a more compact UI layout</p>
                </div>
                <button className="relative w-11 h-6 rounded-full bg-white/[0.1] transition-colors">
                  <span className="absolute left-1 top-1 w-4 h-4 rounded-full bg-white/50 transition-transform" />
                </button>
              </div>
            </div>
          </div>

          <button
            onClick={showSaved}
            className="px-4 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white text-[13px] font-medium transition-colors"
          >
            Save Changes
          </button>
        </div>
      )}

      {/* Notifications Tab */}
      {activeTab === 'notifications' && (
        <div className="space-y-6">
          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
            <h2 className="text-[15px] font-medium text-white mb-4">Email Notifications</h2>
            <div className="space-y-4">
              {[
                { id: 'alerts', label: 'Data Alerts', desc: 'Get notified about data quality issues', enabled: true },
                { id: 'sync', label: 'Sync Failures', desc: 'Notifications when sources fail to sync', enabled: true },
                { id: 'weekly', label: 'Weekly Digest', desc: 'Weekly summary of your data health', enabled: false },
              ].map((item) => (
                <div key={item.id} className="flex items-center justify-between">
                  <div>
                    <p className="text-[14px] font-medium text-white">{item.label}</p>
                    <p className="text-[12px] text-white/40">{item.desc}</p>
                  </div>
                  <button 
                    className={`relative w-11 h-6 rounded-full transition-colors ${item.enabled ? 'bg-[var(--accent)]' : 'bg-white/[0.1]'}`}
                  >
                    <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-transform ${item.enabled ? 'left-6' : 'left-1'}`} />
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
          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[15px] font-medium text-white">API Keys</h2>
              <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.08] text-white text-[12px] font-medium transition-colors">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Create Key
              </button>
            </div>
            <div className="text-center py-8">
              <div className="w-12 h-12 rounded-xl bg-white/[0.05] flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
                </svg>
              </div>
              <p className="text-white/50 text-[14px]">No API keys created yet</p>
            </div>
          </div>
        </div>
      )}

      {/* Billing Tab */}
      {activeTab === 'billing' && (
        <div className="space-y-6">
          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
            <h2 className="text-[15px] font-medium text-white mb-4">Current Plan</h2>
            <div className="flex items-center justify-between p-4 rounded-xl bg-gradient-to-br from-[var(--accent)]/10 to-[var(--accent)]/5 border border-[var(--accent)]/20">
              <div>
                <p className="text-[18px] font-semibold text-white mb-1">Pro Plan</p>
                <p className="text-[13px] text-white/50">Unlimited sources, priority support</p>
              </div>
              <div className="text-right">
                <p className="text-[24px] font-bold text-white">$99<span className="text-[14px] font-normal text-white/50">/mo</span></p>
              </div>
            </div>
          </div>

          <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
            <h2 className="text-[15px] font-medium text-white mb-4">Usage This Month</h2>
            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[13px] text-white/70">AI Queries</span>
                  <span className="text-[13px] text-white">1,247 / 5,000</span>
                </div>
                <div className="h-2 rounded-full bg-white/[0.1]">
                  <div className="h-full w-[25%] rounded-full bg-[var(--accent)]" />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[13px] text-white/70">Data Sources</span>
                  <span className="text-[13px] text-white">3 / 10</span>
                </div>
                <div className="h-2 rounded-full bg-white/[0.1]">
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
