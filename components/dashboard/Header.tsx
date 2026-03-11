'use client';

import { useSession } from 'next-auth/react';
import { usePathname, useRouter } from 'next/navigation';
import { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { toast } from 'sonner';
import { PipelineSelector } from './PipelineSelector';

// Map routes to page titles
const pageTitles: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/dashboard/chat': 'Chat',
  '/dashboard/assistant': 'Scout',
  '/dashboard/lineage': 'Lineage',
  '/dashboard/sources': 'Data Sources',
  '/dashboard/pipeline': 'Pipeline',
  '/dashboard/pipeline/settings': 'Pipeline Settings',
  '/dashboard/schedule': 'Scheduled Tasks',
  '/dashboard/notifications': 'Notifications',
  '/dashboard/team': 'Team',
  '/dashboard/settings': 'Settings',
};

interface SearchResult {
  id: string;
  title: string;
  subtitle: string;
  category: string;
  href: string;
  status?: string;
  icon?: string;
}

const CATEGORY_LABELS: Record<string, string> = {
  page: 'Pages',
  feature: 'Features',
  source: 'Sources & Tools',
  artifact: 'Artifacts',
  task: 'Schedules',
};

// SVG icon paths — copied exactly from Sidebar.tsx for matching icons
// Icons with multiple <path> elements use an array
const SEARCH_ICONS: Record<string, string | string[]> = {
  // Sidebar pages (exact match)
  dashboard: 'M4 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM14 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z',
  scout: 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z',
  artifacts: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
  lineage: 'M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z',
  sources: 'M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125',
  pipeline: 'M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z',
  tasks: 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z',
  team: 'M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z',
  settings: ['M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z', 'M15 12a3 3 0 11-6 0 3 3 0 016 0z'],
  notifications: 'M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0',
  // Feature-specific
  shield: 'M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z',
  bolt: 'M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z',
  chart: 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z',
  plug: 'M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244',
  credit: 'M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z',
  user: 'M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z',
  clipboard: 'M11.35 3.836c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m8.9-4.414c.376.023.75.05 1.124.08 1.131.094 1.976 1.057 1.976 2.192V16.5A2.25 2.25 0 0118 18.75h-2.25m-7.5-10.5H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V18.75m-7.5-10.5h6.375c.621 0 1.125.504 1.125 1.125v9.375m-8.25-3l1.5 1.5 3-3.75',
};

// Static command palette items — pages, features, shortcuts
// icon keys match sidebar nav icons exactly
const STATIC_ITEMS: SearchResult[] = [
  // Pages (match sidebar nav 1:1)
  { id: 'p-dashboard', title: 'Dashboard', subtitle: 'Overview and health metrics', category: 'page', href: '/dashboard', icon: 'dashboard' },
  { id: 'p-scout', title: 'Scout', subtitle: 'AI assistant', category: 'page', href: '/dashboard/assistant', icon: 'scout' },
  { id: 'p-artifacts', title: 'Artifacts', subtitle: 'Saved queries, docs, and reports', category: 'page', href: '/dashboard/artifacts', icon: 'artifacts' },
  { id: 'p-lineage', title: 'Lineage', subtitle: 'Data lineage graph', category: 'page', href: '/dashboard/lineage', icon: 'lineage' },
  { id: 'p-sources', title: 'Sources', subtitle: 'Manage integrations and connections', category: 'page', href: '/dashboard/sources', icon: 'sources' },
  { id: 'p-pipeline', title: 'Pipeline', subtitle: 'Pipeline overview and nodes', category: 'page', href: '/dashboard/pipeline', icon: 'pipeline' },
  { id: 'p-schedule', title: 'Tasks', subtitle: 'Scan schedules and cron jobs', category: 'page', href: '/dashboard/schedule', icon: 'tasks' },
  { id: 'p-notifications', title: 'Notifications', subtitle: 'Alerts, errors, and events', category: 'page', href: '/dashboard/notifications', icon: 'notifications' },
  { id: 'p-team', title: 'Team', subtitle: 'Team members and roles', category: 'page', href: '/dashboard/team', icon: 'team' },
  { id: 'p-settings', title: 'Settings', subtitle: 'Account and pipeline settings', category: 'page', href: '/dashboard/settings', icon: 'settings' },
  // Features — icon inherits from the page they link to
  { id: 'f-monitors', title: 'Monitors', subtitle: 'Freshness, volume, quality, anomaly detection', category: 'feature', href: '/dashboard/schedule', icon: 'shield' },
  { id: 'f-freshness', title: 'Freshness Monitor', subtitle: 'Track data freshness and staleness', category: 'feature', href: '/dashboard/schedule', icon: 'tasks' },
  { id: 'f-volume', title: 'Volume Monitor', subtitle: 'Track row count changes and anomalies', category: 'feature', href: '/dashboard/schedule', icon: 'tasks' },
  { id: 'f-quality', title: 'Quality Monitor', subtitle: 'Data quality checks and validation', category: 'feature', href: '/dashboard/schedule', icon: 'tasks' },
  { id: 'f-anomaly', title: 'Anomaly Detection', subtitle: 'Detect unusual patterns in data', category: 'feature', href: '/dashboard/schedule', icon: 'tasks' },
  { id: 'f-billing', title: 'Billing', subtitle: 'Usage, tokens, and subscription', category: 'feature', href: '/dashboard/settings', icon: 'settings' },
  { id: 'f-integrations', title: 'Integrations', subtitle: 'Connect data sources and tools', category: 'feature', href: '/dashboard/sources', icon: 'sources' },
  { id: 'f-warehouse', title: 'Warehouse', subtitle: 'BigQuery, Snowflake, Postgres, Redshift', category: 'feature', href: '/dashboard/sources', icon: 'sources' },
  { id: 'f-ingestion', title: 'Ingestion', subtitle: 'Fivetran, Airbyte, Stitch', category: 'feature', href: '/dashboard/sources', icon: 'sources' },
  { id: 'f-transformation', title: 'Transformation', subtitle: 'dbt Cloud, dbt Core', category: 'feature', href: '/dashboard/sources', icon: 'sources' },
  { id: 'f-orchestration', title: 'Orchestration', subtitle: 'Airflow, Dagster, Prefect', category: 'feature', href: '/dashboard/sources', icon: 'sources' },
  { id: 'f-reporting', title: 'Reporting / BI', subtitle: 'Looker, Tableau, Power BI, Metabase', category: 'feature', href: '/dashboard/sources', icon: 'sources' },
  { id: 'f-lineage-graph', title: 'Lineage Graph', subtitle: 'Visualize data dependencies and flow', category: 'feature', href: '/dashboard/lineage', icon: 'lineage' },
  { id: 'f-alerts', title: 'Alerts & Errors', subtitle: 'Error notifications and failed monitors', category: 'feature', href: '/dashboard/notifications', icon: 'notifications' },
  { id: 'f-scans', title: 'Scans', subtitle: 'Run and schedule pipeline scans', category: 'feature', href: '/dashboard/schedule', icon: 'tasks' },
  { id: 'f-copilot', title: 'AI Copilot / Scout', subtitle: 'Ask questions about your data pipeline', category: 'feature', href: '/dashboard/assistant', icon: 'scout' },
  { id: 'f-contracts', title: 'Contracts', subtitle: 'Pipeline and source contracts', category: 'feature', href: '/dashboard/pipeline/settings', icon: 'pipeline' },
  { id: 'f-profile', title: 'Profile', subtitle: 'Your account and preferences', category: 'feature', href: '/dashboard/settings', icon: 'settings' },
];

export function DashboardHeader() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const [showSearch, setShowSearch] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const lastNotifCheckRef = useRef<string | null>(null);

  // Get page title from pathname
  const pageTitle = Object.entries(pageTitles).find(([path]) =>
    pathname === path || pathname.startsWith(path + '/')
  )?.[1] || 'Dashboard';

  // ── Notification polling (unread count + toast for new errors/failures) ──

  const fetchUnreadCount = useCallback(async () => {
    try {
      const res = await fetch('/api/notifications/unread-count');
      if (res.ok) {
        const data = await res.json();
        setUnreadCount(data.count || 0);
      }
    } catch {
      // Silently fail
    }
  }, []);

  const checkNewAlerts = useCallback(async () => {
    try {
      const res = await fetch('/api/notifications?severity=ERROR&limit=5&unreadOnly=true');
      if (!res.ok) return;
      const data = await res.json();
      const events = data.notifications || [];
      if (events.length === 0) return;

      // Only toast for events we haven't shown yet
      const latestId = events[0]?.id;
      if (latestId && latestId !== lastNotifCheckRef.current) {
        // Show toasts for new error/critical events
        for (const evt of events.slice(0, 3)) {
          if (lastNotifCheckRef.current && evt.id <= lastNotifCheckRef.current) break;
          const isCritical = evt.severity === 'CRITICAL';
          toast.error(evt.title, {
            description: evt.message?.slice(0, 120),
            duration: isCritical ? 10000 : 6000,
            action: evt.actionUrl
              ? { label: 'View', onClick: () => router.push(evt.actionUrl) }
              : undefined,
          });
        }
        lastNotifCheckRef.current = latestId;
      }
    } catch {
      // Silently fail
    }
  }, [router]);

  useEffect(() => {
    fetchUnreadCount();
    checkNewAlerts();
    const interval = setInterval(() => {
      fetchUnreadCount();
      checkNewAlerts();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchUnreadCount, checkNewAlerts]);

  // ── Cmd+K shortcut ──

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setShowSearch((prev) => !prev);
      }
      if (e.key === 'Escape') {
        setShowSearch(false);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Reset search state when modal closes
  useEffect(() => {
    if (!showSearch) {
      setSearchQuery('');
      setSearchResults([]);
      setSelectedIndex(-1);
    }
  }, [showSearch]);

  // ── Search with debounce ──

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }

    const lower = q.toLowerCase();

    // Instant: filter static items by matching title, subtitle, or category
    const staticMatches = STATIC_ITEMS.filter(
      (item) =>
        item.title.toLowerCase().includes(lower) ||
        item.subtitle.toLowerCase().includes(lower)
    ).slice(0, 8);

    // Show static results immediately
    setSearchResults(staticMatches);

    // Then fetch DB results in parallel
    setIsSearching(true);
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      const dbResults: SearchResult[] = data.results || [];

      // Merge: static first, then DB results (dedup by id)
      const seen = new Set(staticMatches.map((r) => r.id));
      const merged = [
        ...staticMatches,
        ...dbResults.filter((r) => !seen.has(r.id)),
      ];
      setSearchResults(merged);
    } catch (err) {
      console.error('Search fetch error:', err);
      // Keep static results on API failure
    } finally {
      setIsSearching(false);
    }
  }, []);

  const onSearchInput = (value: string) => {
    setSearchQuery(value);
    setSelectedIndex(-1);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => doSearch(value), 250);
  };

  const navigateToResult = (result: SearchResult) => {
    setShowSearch(false);
    router.push(result.href);
  };

  // Keyboard navigation in results
  const onSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, searchResults.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && selectedIndex >= 0 && searchResults[selectedIndex]) {
      e.preventDefault();
      navigateToResult(searchResults[selectedIndex]);
    }
  };

  // Group results by category
  const grouped = searchResults.reduce<Record<string, SearchResult[]>>((acc, r) => {
    if (!acc[r.category]) acc[r.category] = [];
    acc[r.category].push(r);
    return acc;
  }, {});

  let flatIndex = 0;

  return (
    <>
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
        <button
          onClick={() => router.push('/dashboard/notifications')}
          className="relative p-2 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] flex items-center justify-center px-1 rounded-full bg-[var(--accent)] text-white text-[10px] font-semibold leading-none">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
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

    </header>
    {showSearch && typeof document !== 'undefined' && createPortal(
        <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]">
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowSearch(false)} />
          <div className="relative w-full max-w-xl mx-4 bg-[var(--surface)] rounded-xl border border-[var(--subtle-border)] shadow-2xl">
            <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--subtle-border)]">
              <svg className="w-5 h-5 text-[var(--muted)] flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => onSearchInput(e.target.value)}
                onKeyDown={onSearchKeyDown}
                placeholder="Search pages, features, sources..."
                autoFocus
                className="flex-1 bg-transparent text-[15px] text-[var(--text)] placeholder-[var(--text-faint)] outline-none"
              />
              {isSearching && (
                <svg className="w-4 h-4 text-[var(--muted)] animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              <kbd className="px-2 py-0.5 rounded bg-[var(--hover-bg)] text-[11px] text-[var(--text-faint)] font-medium">ESC</kbd>
            </div>

            <div className="max-h-[50vh] overflow-y-auto">
              {searchResults.length > 0 ? (
                <div className="py-2">
                  {Object.entries(grouped).map(([category, items]) => (
                    <div key={category}>
                      <div className="px-4 py-1.5 text-[11px] font-medium text-[var(--text-faint)] uppercase tracking-wider">
                        {CATEGORY_LABELS[category] || category}
                      </div>
                      {items.map((result) => {
                        const idx = flatIndex++;
                        return (
                          <button
                            key={result.id}
                            onClick={() => navigateToResult(result)}
                            className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                              idx === selectedIndex
                                ? 'bg-[var(--hover-bg)]'
                                : 'hover:bg-[var(--overlay-bg)]'
                            }`}
                          >
                            <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-[var(--overlay-bg)] flex items-center justify-center">
                              <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                {(() => {
                                  const paths = SEARCH_ICONS[result.icon || 'artifacts'] || SEARCH_ICONS.artifacts;
                                  if (Array.isArray(paths)) {
                                    return paths.map((d, i) => <path key={i} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={d} />);
                                  }
                                  return <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={paths as string} />;
                                })()}
                              </svg>
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-[13px] font-medium text-[var(--text)] truncate">{result.title}</p>
                              <p className="text-[12px] text-[var(--muted)] truncate">{result.subtitle}</p>
                            </div>
                            {result.status && (
                              <span className={`flex-shrink-0 text-[11px] px-1.5 py-0.5 rounded ${
                                result.status === 'HEALTHY' || result.status === 'CONNECTED' || result.status === 'SUCCESS'
                                  ? 'bg-emerald-500/10 text-emerald-400'
                                  : result.status === 'ERROR' || result.status === 'FAILED'
                                  ? 'bg-red-500/10 text-red-400'
                                  : 'bg-amber-500/10 text-amber-400'
                              }`}>
                                {result.status}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              ) : searchQuery.length >= 2 && !isSearching ? (
                <div className="p-8 text-center text-[13px] text-[var(--text-faint)]">
                  No results for &ldquo;{searchQuery}&rdquo;
                </div>
              ) : (
                <div className="p-8 text-center text-[13px] text-[var(--text-faint)]">
                  {searchQuery.length > 0 ? 'Keep typing...' : 'Search pages, monitors, sources...'}
                </div>
              )}
            </div>

            {searchResults.length > 0 && (
              <div className="px-4 py-2 border-t border-[var(--subtle-border)] flex items-center gap-4 text-[11px] text-[var(--text-faint)]">
                <span><kbd className="px-1 py-0.5 rounded bg-[var(--hover-bg)] font-medium">↑↓</kbd> navigate</span>
                <span><kbd className="px-1 py-0.5 rounded bg-[var(--hover-bg)] font-medium">↵</kbd> open</span>
                <span><kbd className="px-1 py-0.5 rounded bg-[var(--hover-bg)] font-medium">esc</kbd> close</span>
              </div>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
