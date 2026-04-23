'use client';

import { useState, useRef, useEffect } from 'react';
import { MoreVertical, BellOff, Send, ExternalLink } from 'lucide-react';
import { cachedFetch } from '@/lib/fetch-cache';

interface Integration {
  id: string;
  type: string;
  status: string;
  metadata?: Record<string, any>;
}

interface NotificationCardMenuProps {
  notificationId: string;
  eventType: string;
  entityType?: string;
  entityId?: string;
  onMuted?: () => void;
  onForwarded?: () => void;
}

const PLATFORM_LABELS: Record<string, string> = {
  SLACK: 'Send to Slack',
  TEAMS: 'Send to Teams',
  PAGERDUTY: 'Send to PagerDuty',
  OPSGENIE: 'Send to OpsGenie',
  EMAIL: 'Send via Email',
  JIRA: 'Create Jira ticket',
};

const NOTIFICATION_PLATFORMS = ['SLACK', 'TEAMS', 'PAGERDUTY', 'OPSGENIE', 'EMAIL'];
const TICKETING_PLATFORMS = ['JIRA'];

export default function NotificationCardMenu({
  notificationId,
  eventType,
  entityType,
  entityId,
  onMuted,
  onForwarded,
}: NotificationCardMenuProps) {
  const [open, setOpen] = useState(false);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [sending, setSending] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && integrations.length === 0) {
      cachedFetch('/api/integrations?layer=notifications,ticketing')
        .then((res) => res.json())
        .then((data) => setIntegrations((data.integrations || []).filter((i: Integration) => i.status === 'ACTIVE')))
        .catch(() => {});
    }
  }, [open]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const handleMute = async () => {
    try {
      await fetch('/api/notifications/mutes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ eventType, entityType, entityId }),
      });
      setOpen(false);
      onMuted?.();
    } catch {}
  };

  const handleForward = async (integrationId: string) => {
    setSending(integrationId);
    try {
      await fetch(`/api/notifications/${notificationId}/forward`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ integrationId }),
      });
      setOpen(false);
      onForwarded?.();
    } catch {}
    setSending(null);
  };

  const notifPlatforms = integrations.filter((i) =>
    NOTIFICATION_PLATFORMS.includes(i.type.toUpperCase()),
  );
  const ticketPlatforms = integrations.filter((i) =>
    TICKETING_PLATFORMS.includes(i.type.toUpperCase()),
  );

  return (
    <div ref={menuRef} className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className="p-1 rounded hover:bg-[var(--overlay-faint)] transition-colors"
      >
        <MoreVertical className="w-4 h-4 text-[var(--muted)]" />
      </button>

      {open && (
        <div className="absolute right-0 top-6 z-50 w-56 rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] shadow-xl py-1">
          <button
            onClick={handleMute}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--muted)] hover:bg-[var(--overlay-faint)] hover:text-[var(--text)]"
          >
            <BellOff className="w-4 h-4" />
            Mute notifications like this
          </button>

          {notifPlatforms.length > 0 && (
            <>
              <div className="border-t border-[var(--subtle-border)] my-1" />
              {notifPlatforms.map((int) => (
                <button
                  key={int.id}
                  onClick={() => handleForward(int.id)}
                  disabled={sending === int.id}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--muted)] hover:bg-[var(--overlay-faint)] hover:text-[var(--text)] disabled:opacity-50"
                >
                  <Send className="w-4 h-4" />
                  {sending === int.id ? 'Sending...' : PLATFORM_LABELS[int.type.toUpperCase()] || `Send to ${int.type}`}
                </button>
              ))}
            </>
          )}

          {ticketPlatforms.length > 0 && (
            <>
              <div className="border-t border-[var(--subtle-border)] my-1" />
              {ticketPlatforms.map((int) => (
                <button
                  key={int.id}
                  onClick={() => handleForward(int.id)}
                  disabled={sending === int.id}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-[var(--muted)] hover:bg-[var(--overlay-faint)] hover:text-[var(--text)] disabled:opacity-50"
                >
                  <ExternalLink className="w-4 h-4" />
                  {sending === int.id ? 'Creating...' : PLATFORM_LABELS[int.type.toUpperCase()] || `Create ${int.type} ticket`}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
