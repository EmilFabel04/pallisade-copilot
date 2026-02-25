'use client';

import { useSession } from 'next-auth/react';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { PipelineSelector } from './PipelineSelector';

// Map routes to page titles
const pageTitles: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/dashboard/chat': 'Chat',
  '/dashboard/assistant': 'AI Assistant',
  '/dashboard/lineage': 'Lineage',
  '/dashboard/sources': 'Data Sources',
  '/dashboard/pipeline': 'Pipeline',
  '/dashboard/pipeline/settings': 'Pipeline Settings',
  '/dashboard/schedule': 'Scheduled Tasks',
  '/dashboard/team': 'Team',
  '/dashboard/settings': 'Settings',
};

export function DashboardHeader() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const [showSearch, setShowSearch] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  // Get page title from pathname
  const pageTitle = Object.entries(pageTitles).find(([path]) => 
    pathname === path || pathname.startsWith(path + '/')
  )?.[1] || 'Dashboard';

  return (
    <header className="h-14 flex items-center justify-between px-6 border-b border-[var(--border-faint)] bg-[var(--surface-inset)]/90 backdrop-blur-sm sticky top-0 z-30">
      {/* Left - Pipeline Selector & Page Title */}
      <div className="flex items-center gap-4">
        <PipelineSelector />
        <div className="w-px h-6 bg-[var(--hover-bg)]" />
        <h1 className="text-[15px] font-medium text-[var(--text)]">{pageTitle}</h1>
      </div>

      {/* Right - Actions */}
      <div className="flex items-center gap-2">
        {/* Search Button */}
        <button 
          onClick={() => setShowSearch(true)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] border border-[var(--subtle-border)] transition-colors"
        >
          <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <span className="text-[13px] text-[var(--muted)] hidden sm:block">Search...</span>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-[var(--hover-bg)] text-[10px] text-[var(--text-faint)] font-medium">
            <span className="text-[11px]">⌘</span>K
          </kbd>
        </button>

        {/* Notifications */}
        <button className="relative p-2 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-colors">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-[var(--accent)] rounded-full" />
        </button>

        {/* User Menu */}
        <div className="relative">
          <button 
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-[var(--overlay-bg)] transition-colors"
          >
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] flex items-center justify-center text-white text-[11px] font-medium">
              {session?.user?.image ? (
                <img src={session.user.image} alt="" className="w-full h-full rounded-full object-cover" />
              ) : (
                session?.user?.name?.[0]?.toUpperCase() || session?.user?.email?.[0]?.toUpperCase() || 'U'
              )}
            </div>
            <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {/* User Dropdown */}
          {showUserMenu && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowUserMenu(false)} />
              <div className="absolute right-0 top-full mt-1 w-56 py-1 rounded-lg bg-[var(--surface)] border border-[var(--subtle-border)] shadow-xl z-50">
                <div className="px-3 py-2 border-b border-[var(--subtle-border)]">
                  <p className="text-[13px] font-medium text-[var(--text)] truncate">
                    {session?.user?.name || 'User'}
                  </p>
                  <p className="text-[12px] text-[var(--muted)] truncate">
                    {session?.user?.email}
                  </p>
                </div>
                <div className="py-1">
                  <a href="/dashboard/settings" className="flex items-center gap-2 px-3 py-2 text-[13px] text-[var(--text-tertiary)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)]">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.204-.107-.397.165-.71.505-.78.929l-.15.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.107-1.204l-.527-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    Settings
                  </a>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Search Modal */}
      {showSearch && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowSearch(false)} />
          <div className="relative w-full max-w-xl mx-4 bg-[var(--surface)] rounded-xl border border-[var(--subtle-border)] shadow-2xl">
            <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--subtle-border)]">
              <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                placeholder="Search tables, models, pipelines..."
                autoFocus
                className="flex-1 bg-transparent text-[15px] text-[var(--text)] placeholder-[var(--text-faint)] outline-none"
              />
              <kbd className="px-2 py-0.5 rounded bg-[var(--hover-bg)] text-[11px] text-[var(--text-faint)] font-medium">ESC</kbd>
            </div>
            <div className="p-2 text-center text-[13px] text-[var(--text-faint)] py-8">
              Start typing to search...
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
