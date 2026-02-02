'use client';

import { useState } from 'react';
import { useSession } from 'next-auth/react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

export default function SettingsPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState('profile');

  const tabs = [
    { id: 'profile', label: 'Profile' },
    { id: 'organization', label: 'Organization' },
    { id: 'security', label: 'Security' },
    { id: 'notifications', label: 'Notifications' },
    { id: 'billing', label: 'Billing' },
  ];

  const externalLinks = [
    { href: '/dashboard/settings/audit', label: 'Audit Logs', icon: '📋' },
    { href: '/terms', label: 'Terms of Service', icon: '📄', external: true },
    { href: '/privacy', label: 'Privacy Policy', icon: '🔒', external: true },
  ];

  return (
    <div className="space-y-8 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-[var(--muted)] mt-1">Manage your account and preferences</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[rgba(255,255,255,0.06)] pb-px overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium transition-all relative whitespace-nowrap ${
              activeTab === tab.id 
                ? 'text-[var(--text)]' 
                : 'text-[var(--muted)] hover:text-[var(--text)]'
            }`}
          >
            {tab.label}
            {activeTab === tab.id && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-[var(--accent)] to-[var(--accent-2)]" />
            )}
          </button>
        ))}
      </div>

      {/* Profile Tab */}
      {activeTab === 'profile' && (
        <div className="space-y-6">
          <div className="dashboard-card p-6">
            <h2 className="text-lg font-semibold mb-6">Profile Information</h2>
            <div className="flex items-start gap-6 mb-6">
              <div className="w-20 h-20 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center text-2xl font-bold flex-shrink-0">
                {session?.user?.name?.[0] || session?.user?.email?.[0] || 'U'}
              </div>
              <div>
                <button className="btn btn-secondary text-sm mb-2">Upload Photo</button>
                <p className="text-xs text-[var(--muted)]">JPG, PNG or GIF. Max 2MB.</p>
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Full Name</label>
                <input 
                  type="text" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all" 
                  defaultValue={session?.user?.name || ''} 
                  placeholder="Your name"
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Email</label>
                <input 
                  type="email" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--muted)] focus:outline-none transition-all cursor-not-allowed" 
                  defaultValue={session?.user?.email || ''} 
                  disabled
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Job Title</label>
                <input 
                  type="text" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all" 
                  placeholder="e.g. Security Engineer" 
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Phone</label>
                <input 
                  type="tel" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all" 
                  placeholder="+1 (555) 000-0000" 
                />
              </div>
            </div>
            <div className="flex justify-end mt-6 pt-6 border-t border-[rgba(255,255,255,0.06)]">
              <button className="btn btn-elevated">Save Changes</button>
            </div>
          </div>
        </div>
      )}

      {/* Organization Tab */}
      {activeTab === 'organization' && (
        <div className="space-y-6">
          <div className="dashboard-card p-6">
            <h2 className="text-lg font-semibold mb-6">Organization Details</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Company Name</label>
                <input 
                  type="text" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all" 
                  placeholder="Acme Inc." 
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Industry</label>
                <select className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all appearance-none cursor-pointer">
                  <option>Select industry...</option>
                  <option>Technology / SaaS</option>
                  <option>Financial Services</option>
                  <option>Healthcare</option>
                  <option>E-commerce</option>
                  <option>Other</option>
                </select>
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Company Size</label>
                <select className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all appearance-none cursor-pointer">
                  <option>Select size...</option>
                  <option>1-10 employees</option>
                  <option>11-50 employees</option>
                  <option>51-200 employees</option>
                  <option>201-500 employees</option>
                  <option>500+ employees</option>
                </select>
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Website</label>
                <input 
                  type="url" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all" 
                  placeholder="https://example.com" 
                />
              </div>
            </div>
            <div className="flex justify-end mt-6 pt-6 border-t border-[rgba(255,255,255,0.06)]">
              <button className="btn btn-elevated">Save Changes</button>
            </div>
          </div>

          <div className="dashboard-card p-6">
            <h2 className="text-lg font-semibold mb-4">Team Members</h2>
            <p className="text-sm text-[var(--muted)] mb-6">Manage who has access to your organization's data.</p>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-4 bg-[rgba(0,0,0,0.3)] rounded-xl">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center font-semibold flex-shrink-0">
                    {session?.user?.name?.[0] || 'U'}
                  </div>
                  <div className="min-w-0">
                    <p className="font-medium truncate">{session?.user?.name || 'You'}</p>
                    <p className="text-sm text-[var(--muted)] truncate">{session?.user?.email}</p>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-[var(--accent)]/15 text-[var(--accent-2)] flex-shrink-0">
                  Owner
                </span>
              </div>
            </div>
            <button 
              onClick={() => router.push('/dashboard/settings/team')}
              className="btn btn-secondary mt-4"
            >
              <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Invite Team Member
            </button>
          </div>
        </div>
      )}

      {/* Security Tab */}
      {activeTab === 'security' && (
        <div className="space-y-6">
          <div className="dashboard-card p-6">
            <h2 className="text-lg font-semibold mb-6">Password</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2 md:col-span-2 md:max-w-md">
                <label className="block text-sm font-medium text-[var(--muted)]">Current Password</label>
                <input 
                  type="password" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all" 
                  placeholder="••••••••" 
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">New Password</label>
                <input 
                  type="password" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all" 
                  placeholder="••••••••" 
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-[var(--muted)]">Confirm New Password</label>
                <input 
                  type="password" 
                  className="w-full px-4 py-3 bg-[rgba(0,0,0,0.4)] border border-[rgba(255,255,255,0.1)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20 transition-all" 
                  placeholder="••••••••" 
                />
              </div>
            </div>
            <div className="flex justify-end mt-6 pt-6 border-t border-[rgba(255,255,255,0.06)]">
              <button className="btn btn-elevated">Update Password</button>
            </div>
          </div>

          <div className="dashboard-card p-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold">Two-Factor Authentication</h2>
                <p className="text-sm text-[var(--muted)] mt-1">Add an extra layer of security to your account</p>
              </div>
              <button className="btn btn-secondary">Enable 2FA</button>
            </div>
          </div>

          <div className="dashboard-card p-6">
            <h2 className="text-lg font-semibold mb-4">Active Sessions</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-4 bg-[rgba(0,0,0,0.3)] rounded-xl">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-[rgba(255,255,255,0.05)] flex items-center justify-center flex-shrink-0">
                    <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-medium">Current Session</p>
                    <p className="text-sm text-[var(--muted)]">macOS • Chrome • Last active now</p>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-green-500/15 text-green-400 flex-shrink-0">
                  Active
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Notifications Tab */}
      {activeTab === 'notifications' && (
        <div className="space-y-6">
          <div className="dashboard-card p-6">
            <h2 className="text-lg font-semibold mb-6">Email Notifications</h2>
            <div className="space-y-4">
              {[
                { id: 'reports', label: 'Report Completed', desc: 'When a security scan finishes' },
                { id: 'critical', label: 'Critical Findings', desc: 'Immediate alerts for critical issues' },
                { id: 'tasks', label: 'Task Reminders', desc: 'When tasks are due or overdue' },
                { id: 'weekly', label: 'Weekly Summary', desc: 'Weekly security posture digest' },
              ].map((item) => (
                <div key={item.id} className="flex items-center justify-between p-4 bg-[rgba(0,0,0,0.3)] rounded-xl">
                  <div>
                    <p className="font-medium">{item.label}</p>
                    <p className="text-sm text-[var(--muted)]">{item.desc}</p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer flex-shrink-0">
                    <input type="checkbox" className="sr-only peer" defaultChecked />
                    <div className="w-11 h-6 bg-[rgba(255,255,255,0.1)] peer-focus:ring-2 peer-focus:ring-[var(--accent)]/50 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent)]"></div>
                  </label>
                </div>
              ))}
            </div>
          </div>

          <div className="dashboard-card p-6">
            <h2 className="text-lg font-semibold mb-4">Slack Notifications</h2>
            <p className="text-sm text-[var(--muted)] mb-4">Connect Slack to receive real-time alerts</p>
            <button className="btn btn-secondary">
              <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24">
                <path fill="currentColor" d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52z"/>
              </svg>
              Connect Slack
            </button>
          </div>
        </div>
      )}

      {/* Billing Tab */}
      {activeTab === 'billing' && (
        <div className="space-y-6">
          <div className="dashboard-card p-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
              <div>
                <h2 className="text-lg font-semibold">Current Plan</h2>
                <p className="text-sm text-[var(--muted)]">Manage your subscription</p>
              </div>
              <span className="px-4 py-2 rounded-full text-sm font-semibold bg-gradient-to-r from-[var(--accent)] to-[var(--accent-2)] text-white self-start">
                Professional
              </span>
            </div>
            <div className="grid grid-cols-3 gap-4 mb-6">
              <div className="p-4 bg-[rgba(0,0,0,0.3)] rounded-xl text-center">
                <p className="text-2xl font-bold">5</p>
                <p className="text-sm text-[var(--muted)]">Reports/month</p>
              </div>
              <div className="p-4 bg-[rgba(0,0,0,0.3)] rounded-xl text-center">
                <p className="text-2xl font-bold">3</p>
                <p className="text-sm text-[var(--muted)]">Team members</p>
              </div>
              <div className="p-4 bg-[rgba(0,0,0,0.3)] rounded-xl text-center">
                <p className="text-2xl font-bold">∞</p>
                <p className="text-sm text-[var(--muted)]">AI queries</p>
              </div>
            </div>
            <div className="flex gap-3">
              <button className="btn btn-elevated">Upgrade Plan</button>
              <button className="btn btn-secondary">View Plans</button>
            </div>
          </div>

          <div className="dashboard-card p-6">
            <h2 className="text-lg font-semibold mb-4">Billing History</h2>
            <div className="space-y-3">
              {[
                { date: 'Nov 1, 2025', amount: '$79', status: 'Paid' },
                { date: 'Oct 1, 2025', amount: '$79', status: 'Paid' },
                { date: 'Sep 1, 2025', amount: '$79', status: 'Paid' },
              ].map((invoice, i) => (
                <div key={i} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-[rgba(0,0,0,0.3)] rounded-xl">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-lg bg-[rgba(255,255,255,0.05)] flex items-center justify-center flex-shrink-0">
                      <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                    </div>
                    <div>
                      <p className="font-medium">{invoice.date}</p>
                      <p className="text-sm text-[var(--muted)]">Professional Plan</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 pl-14 sm:pl-0">
                    <span className="font-semibold">{invoice.amount}</span>
                    <span className="px-2 py-1 rounded text-xs font-medium bg-green-500/15 text-green-400">
                      {invoice.status}
                    </span>
                    <button className="text-[var(--accent-2)] text-sm hover:underline">Download</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Quick Links Section */}
      <div className="border-t border-[rgba(255,255,255,0.06)] pt-8">
        <h3 className="text-sm font-medium text-[var(--muted)] mb-4">Quick Links</h3>
        <div className="flex flex-wrap gap-3">
          {externalLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              target={link.external ? '_blank' : undefined}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[rgba(255,255,255,0.03)] hover:bg-[rgba(255,255,255,0.06)] transition-colors text-sm"
            >
              <span>{link.icon}</span>
              <span>{link.label}</span>
              {link.external && (
                <svg className="w-3 h-3 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              )}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
