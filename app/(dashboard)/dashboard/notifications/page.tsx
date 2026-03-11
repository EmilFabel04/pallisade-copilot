'use client';

import { useSession } from 'next-auth/react';
import { useState, useEffect, useCallback } from 'react';
import { cachedFetch } from '@/lib/fetch-cache';
import { NotificationCard, type NotificationItem } from '@/components/notifications/NotificationCard';
import {
  NotificationFilters,
  type SeverityFilter,
  type CategoryFilter,
  type ReadFilter,
} from '@/components/notifications/NotificationFilters';

export default function NotificationsPage() {
  const { data: session } = useSession();

  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [nextCursorId, setNextCursorId] = useState<string | null>(null);

  // Filters
  const [severity, setSeverity] = useState<SeverityFilter>('ALL');
  const [category, setCategory] = useState<CategoryFilter>('ALL');
  const [readFilter, setReadFilter] = useState<ReadFilter>('ALL');

  const fetchNotifications = useCallback(
    async (cursor?: string | null, cursorId?: string | null, append = false) => {
      if (!append) setLoading(true);

      try {
        const params = new URLSearchParams();
        params.set('limit', '25');
        if (severity !== 'ALL') params.set('severity', severity);
        if (category !== 'ALL') params.set('eventType', getCategoryEventPrefix(category));
        if (readFilter === 'UNREAD') params.set('unreadOnly', 'true');
        if (cursor) params.set('cursor', cursor);
        if (cursorId) params.set('cursorId', cursorId);

        const res = await cachedFetch(`/api/notifications?${params.toString()}`);
        const data = await res.json();

        if (append) {
          setNotifications((prev) => [...prev, ...data.notifications]);
        } else {
          setNotifications(data.notifications);
        }
        setNextCursor(data.nextCursor);
        setNextCursorId(data.nextCursorId);
        setHasMore(!!data.nextCursor);
      } catch (error) {
        console.error('Failed to fetch notifications:', error);
      } finally {
        setLoading(false);
      }
    },
    [severity, category, readFilter],
  );

  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  const handleMarkRead = useCallback(async (id: string) => {
    try {
      await fetch('/api/notifications/mark-read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notificationIds: [id] }),
      });
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, isRead: true } : n)),
      );
    } catch {
      // Silently fail
    }
  }, []);

  const handleMarkAllRead = useCallback(async () => {
    try {
      await fetch('/api/notifications/mark-all-read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      setNotifications((prev) => prev.map((n) => ({ ...n, isRead: true })));
    } catch {
      // Silently fail
    }
  }, []);

  const handleLoadMore = useCallback(() => {
    if (hasMore && nextCursor) {
      fetchNotifications(nextCursor, nextCursorId, true);
    }
  }, [fetchNotifications, hasMore, nextCursor, nextCursorId]);

  const unreadCount = notifications.filter((n) => !n.isRead).length;

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text)]">Notifications</h1>
          <p className="text-[13px] text-[var(--text-tertiary)] mt-1">
            {unreadCount > 0 ? `${unreadCount} unread` : 'All caught up'}
          </p>
        </div>
        {unreadCount > 0 && (
          <button
            onClick={handleMarkAllRead}
            className="text-[12px] px-3 py-1.5 rounded-lg bg-[var(--overlay-bg)] text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] border border-[var(--subtle-border)] transition-colors"
          >
            Mark all as read
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="mb-6">
        <NotificationFilters
          severity={severity}
          category={category}
          readFilter={readFilter}
          onSeverityChange={setSeverity}
          onCategoryChange={setCategory}
          onReadFilterChange={setReadFilter}
        />
      </div>

      {/* Notification list */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="animate-pulse flex gap-3 p-4 rounded-lg border border-[var(--border-faint)]">
              <div className="w-1 rounded-full bg-[var(--hover-bg)]" />
              <div className="flex-1 space-y-2">
                <div className="h-3.5 bg-[var(--hover-bg)] rounded w-2/3" />
                <div className="h-3 bg-[var(--hover-bg)] rounded w-full" />
                <div className="flex gap-2">
                  <div className="h-4 bg-[var(--hover-bg)] rounded w-12" />
                  <div className="h-4 bg-[var(--hover-bg)] rounded w-16" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : notifications.length === 0 ? (
        <div className="text-center py-20">
          <svg className="w-12 h-12 mx-auto text-[var(--text-faint)] mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
          <h3 className="text-[15px] font-medium text-[var(--text-secondary)] mb-1">No notifications yet</h3>
          <p className="text-[13px] text-[var(--text-faint)]">
            Notifications will appear here when events occur in your pipeline.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {notifications.map((n) => (
            <NotificationCard
              key={n.id}
              notification={n}
              onMarkRead={handleMarkRead}
            />
          ))}
          {hasMore && (
            <button
              onClick={handleLoadMore}
              className="w-full py-3 text-[13px] text-[var(--text-tertiary)] hover:text-[var(--text)] rounded-lg bg-[var(--overlay-bg)] hover:bg-[var(--hover-bg)] transition-colors mt-4"
            >
              Load more
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Map category filter to eventType prefix for API filtering.
 * The API uses eventType string matching, so we pass the prefix.
 */
function getCategoryEventPrefix(category: CategoryFilter): string {
  switch (category) {
    case 'MONITOR': return 'monitor';
    case 'SOURCE': return 'integration';
    case 'ASSET': return 'lineage';
    case 'CHANGE_PLAN': return 'plan';
    case 'INVITE': return 'team';
    default: return '';
  }
}
