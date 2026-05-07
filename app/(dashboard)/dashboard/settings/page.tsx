'use client';

import { useState, type ReactNode } from 'react';
import { useSearchParams } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { useTheme } from '@/contexts/ThemeContext';
import { Settings as SettingsIcon, Bell, Key, CreditCard, User, SlidersHorizontal } from 'lucide-react';
import NotificationRoutingSettings from '@/components/settings/NotificationRoutingSettings';
import ConnectedAccounts from '@/components/settings/ConnectedAccounts';
import BillingSettings from '@/components/settings/BillingSettings';

const VALID_TABS = ['general', 'notifications', 'api', 'billing'] as const;

export default function SettingsPage() {
  const { data: session } = useSession();
  const { theme, toggleTheme } = useTheme();
  const searchParams = useSearchParams();
  // Honour ?tab= deep-links (BillingBanner, etc.). Falls back to 'general'.
  const initialTab = (() => {
    const t = searchParams.get('tab');
    return t && (VALID_TABS as readonly string[]).includes(t) ? t : 'general';
  })();
  const [activeTab, setActiveTab] = useState(initialTab);
  const [savedNotification, setSavedNotification] = useState(false);

  const showSaved = () => {
    setSavedNotification(true);
    setTimeout(() => setSavedNotification(false), 2000);
  };

  const tabs: { id: string; name: string; icon: ReactNode }[] = [
    { id: 'general', name: 'General', icon: <SettingsIcon size={16} /> },
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
              <div className="relative w-20 h-20 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center text-white text-2xl font-semibold overflow-hidden">
                {session?.user?.name?.[0]?.toUpperCase() || session?.user?.email?.[0]?.toUpperCase() || 'U'}
                {session?.user?.image && (
                  <img
                    src={session.user.image}
                    alt=""
                    className="absolute inset-0 w-full h-full rounded-2xl object-cover"
                    referrerPolicy="no-referrer"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />
                )}
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

          {/* Connected Accounts Section */}
          <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-6">
            <ConnectedAccounts />
          </div>
        </div>
      )}

      {/* Notifications Tab */}
      {activeTab === 'notifications' && (
        <NotificationRoutingSettings />
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
      {activeTab === 'billing' && <BillingSettings />}

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
