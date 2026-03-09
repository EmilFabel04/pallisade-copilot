'use client';

import { useRouter } from 'next/navigation';

export interface NotificationItem {
  id: string;
  eventType: string;
  severity: 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';
  title: string;
  message: string;
  entityType: string | null;
  entityId: string | null;
  actionUrl: string | null;
  metadata: Record<string, any> | null;
  pipelineStackId: string | null;
  createdAt: string;
  isRead: boolean;
  readAt: string | null;
  actor: { name: string | null; email: string | null; image: string | null } | null;
}

const SEVERITY_STYLES: Record<string, { bar: string; badge: string; label: string }> = {
  INFO: { bar: 'bg-blue-500', badge: 'bg-blue-500/10 text-blue-400', label: 'Info' },
  WARN: { bar: 'bg-amber-500', badge: 'bg-amber-500/10 text-amber-400', label: 'Warning' },
  ERROR: { bar: 'bg-red-500', badge: 'bg-red-500/10 text-red-400', label: 'Error' },
  CRITICAL: { bar: 'bg-red-700', badge: 'bg-red-700/10 text-red-300', label: 'Critical' },
};

const ENTITY_LABELS: Record<string, string> = {
  MONITOR: 'Monitor',
  SOURCE: 'Source',
  ASSET: 'Asset',
  TASK: 'Task',
  CHANGE_PLAN: 'Change Plan',
  INVITE: 'Team',
};

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

export function NotificationCard({
  notification,
  onMarkRead,
}: {
  notification: NotificationItem;
  onMarkRead: (id: string) => void;
}) {
  const router = useRouter();
  const sev = SEVERITY_STYLES[notification.severity] || SEVERITY_STYLES.INFO;

  const handleClick = () => {
    if (!notification.isRead) {
      onMarkRead(notification.id);
    }
    if (notification.actionUrl) {
      router.push(notification.actionUrl);
    }
  };

  return (
    <div
      onClick={handleClick}
      className={`
        flex gap-3 p-4 rounded-lg border transition-colors cursor-pointer
        ${notification.isRead
          ? 'border-[var(--border-faint)] bg-transparent hover:bg-[var(--overlay-bg)]'
          : 'border-[var(--subtle-border)] bg-[var(--surface-raised)] hover:bg-[var(--hover-bg)]'
        }
      `}
    >
      {/* Severity bar */}
      <div className={`w-1 rounded-full flex-shrink-0 ${sev.bar}`} />

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <h3
            className={`text-[13px] leading-snug truncate ${
              notification.isRead
                ? 'text-[var(--text-secondary)] font-normal'
                : 'text-[var(--text)] font-medium'
            }`}
          >
            {notification.title}
          </h3>
          <span
            className="text-[11px] text-[var(--text-faint)] flex-shrink-0"
            title={new Date(notification.createdAt).toLocaleString()}
          >
            {relativeTime(notification.createdAt)}
          </span>
        </div>

        <p className="text-[12px] text-[var(--text-tertiary)] mt-0.5 line-clamp-2">
          {notification.message}
        </p>

        {/* Chips row */}
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${sev.badge}`}>
            {sev.label}
          </span>
          {notification.entityType && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--overlay-bg)] text-[var(--text-tertiary)]">
              {ENTITY_LABELS[notification.entityType] || notification.entityType}
            </span>
          )}
          {notification.actor && (
            <span className="text-[10px] text-[var(--text-faint)]">
              by {notification.actor.name || notification.actor.email}
            </span>
          )}
          {notification.actionUrl && (
            <span className="text-[10px] text-[var(--accent)] ml-auto">
              View &rarr;
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
