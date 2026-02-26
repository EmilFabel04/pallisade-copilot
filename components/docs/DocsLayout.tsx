'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { Menu, X, Sun, Moon } from 'lucide-react';
import { useTheme } from '@/contexts/ThemeContext';
import { DocsSidebar } from './DocsSidebar';

export function DocsLayout({ children }: { children: React.ReactNode }) {
  const { theme, toggleTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[var(--bg)]">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--bg)]/95 backdrop-blur">
        <div className="flex h-14 items-center justify-between px-4 lg:px-6">
          <div className="flex items-center gap-4">
            {/* Mobile sidebar toggle */}
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="lg:hidden text-[var(--muted)] hover:text-[var(--text)]"
            >
              {sidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>

            <Link href="/" className="flex items-center gap-2">
              <Image
                src="/pallisade_emblem.svg"
                alt="Pallisade"
                width={24}
                height={24}
              />
              <span className="text-sm font-semibold text-[var(--text)]">
                Pallisade
              </span>
            </Link>
            <span className="text-[var(--border)]">/</span>
            <Link
              href="/docs"
              className="text-sm font-medium text-[var(--text-tertiary)] hover:text-[var(--text)]"
            >
              Docs
            </Link>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={toggleTheme}
              className="rounded-md p-1.5 text-[var(--muted)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)]"
            >
              {theme === 'dark' ? (
                <Sun className="h-4 w-4" />
              ) : (
                <Moon className="h-4 w-4" />
              )}
            </button>
            <Link
              href="/dashboard"
              className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:bg-[var(--accent-2)]"
            >
              Open App
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-[1400px]">
        {/* Sidebar — desktop */}
        <aside className="hidden lg:block w-[260px] shrink-0 border-r border-[var(--border)] sticky top-14 h-[calc(100vh-3.5rem)] overflow-y-auto">
          <DocsSidebar />
        </aside>

        {/* Sidebar — mobile drawer */}
        {sidebarOpen && (
          <div className="lg:hidden fixed inset-0 top-14 z-30">
            <div
              className="absolute inset-0 bg-black/50"
              onClick={() => setSidebarOpen(false)}
            />
            <aside className="relative w-[280px] h-full bg-[var(--bg)] border-r border-[var(--border)] overflow-y-auto">
              <DocsSidebar />
            </aside>
          </div>
        )}

        {/* Main content */}
        <main className="min-w-0 flex-1 px-6 py-8 lg:px-12 lg:py-10">
          <div className="mx-auto max-w-3xl">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
