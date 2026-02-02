'use client';

import { useSession } from 'next-auth/react';
import Link from 'next/link';

export function DashboardHeader() {
  const { data: session } = useSession();

  return (
    <header className="dashboard-header">
      <div className="header-left">
        <button className="mobile-menu-btn lg:hidden">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>

      <div className="header-right">
        {/* Search */}
        <div className="header-search">
          <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            type="text"
            placeholder="Search..."
            className="header-search-input"
          />
          <kbd className="header-search-kbd">⌘K</kbd>
        </div>

        {/* Notifications */}
        <button className="header-icon-btn">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
          <span className="notification-badge">3</span>
        </button>

        {/* Help */}
        <button className="header-icon-btn">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
          </svg>
        </button>

        {/* User Menu */}
        <div className="header-user">
          <div className="user-avatar">
            {session?.user?.image ? (
              <img src={session.user.image} alt="" className="w-full h-full object-cover rounded-full" />
            ) : (
              <span>{session?.user?.name?.[0] || session?.user?.email?.[0] || 'U'}</span>
            )}
          </div>
          <div className="user-info">
            <span className="user-name">{session?.user?.name || 'User'}</span>
            <span className="user-email">{session?.user?.email}</span>
          </div>
        </div>
      </div>
    </header>
  );
}

