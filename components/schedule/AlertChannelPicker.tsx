'use client';

import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { ToolIcon } from '@/components/icons/ToolIcon';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch } from '@/lib/fetch-cache';

const ALERT_CHANNELS = [
  { id: 'slack', label: 'Slack', types: ['slack', 'SLACK'] },
  { id: 'email', label: 'Email', types: ['email', 'EMAIL'] },
  { id: 'pagerduty', label: 'PagerDuty', types: ['pagerduty', 'PAGERDUTY'] },
  { id: 'teams', label: 'Teams', types: ['teams', 'TEAMS'] },
  { id: 'opsgenie', label: 'Opsgenie', types: ['opsgenie', 'OPSGENIE'] },
];

const ALERT_STATUSES = [
  { id: 'FAIL', label: 'Failure', color: 'text-red-400' },
  { id: 'WARN', label: 'Warning', color: 'text-amber-400' },
  { id: 'ERROR', label: 'Error', color: 'text-red-300' },
];

interface AlertChannelPickerProps {
  channels: string[];
  onChannelsChange: (channels: string[]) => void;
  alertOnStatus: string[];
  onAlertOnStatusChange: (statuses: string[]) => void;
  /** @deprecated Use integrations instead */
  connectedChannels?: string[];
  /** Active integrations from the pipeline — only matching channels will be shown */
  integrations?: Array<{ id: string; name: string; type: string }>;
}

export function AlertChannelPicker({
  channels,
  onChannelsChange,
  alertOnStatus,
  onAlertOnStatusChange,
  connectedChannels,
  integrations,
}: AlertChannelPickerProps) {
  const { selectedPipelineId } = usePipeline();
  const [fetchedIntegrations, setFetchedIntegrations] = useState<Array<{ id: string; name: string; type: string }> | null>(null);

  // Self-fetch integrations when none are provided
  useEffect(() => {
    if (integrations || connectedChannels || !selectedPipelineId) return;
    cachedFetch(`/api/integrations?stackId=${selectedPipelineId}`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!data?.integrations) { setFetchedIntegrations([]); return; }
        setFetchedIntegrations(
          (data.integrations as any[])
            .filter((i: any) => i.status === 'ACTIVE')
            .map((i: any) => ({ id: i.id, name: i.name || i.type, type: i.type }))
        );
      })
      .catch(() => setFetchedIntegrations([]));
  }, [integrations, connectedChannels, selectedPipelineId]);

  const resolvedIntegrations = integrations ?? fetchedIntegrations;

  // Determine which channels to show based on connected integrations
  const visibleChannels = useMemo(() => {
    if (resolvedIntegrations) {
      return ALERT_CHANNELS.filter((ch) =>
        resolvedIntegrations.some((i) => ch.types.includes(i.type.toLowerCase()) || ch.types.includes(i.type))
      );
    }
    if (connectedChannels) {
      return ALERT_CHANNELS.filter((ch) => connectedChannels.includes(ch.id));
    }
    return [];
  }, [resolvedIntegrations, connectedChannels]);

  const toggleChannel = (id: string) => {
    if (channels.includes(id)) {
      onChannelsChange(channels.filter((c) => c !== id));
    } else {
      onChannelsChange([...channels, id]);
    }
  };

  const toggleStatus = (id: string) => {
    if (alertOnStatus.includes(id)) {
      onAlertOnStatusChange(alertOnStatus.filter((s) => s !== id));
    } else {
      onAlertOnStatusChange([...alertOnStatus, id]);
    }
  };

  return (
    <div className="space-y-4">
      {/* Channels */}
      <div>
        <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
          Alert Channels
        </label>
        {visibleChannels.length === 0 ? (
          <p className="text-[12px] text-[var(--muted)]">
            No notification platforms connected. Connect Slack, PagerDuty, or other alert channels in your pipeline integrations first.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {visibleChannels.map((ch) => {
              const isSelected = channels.includes(ch.id);
              return (
                <button
                  key={ch.id}
                  type="button"
                  onClick={() => toggleChannel(ch.id)}
                  className={cn(
                    'flex items-center gap-2 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors',
                    isSelected
                      ? 'bg-[var(--overlay-strong)] text-[var(--text)] border border-[var(--overlay-strong)]'
                      : 'bg-[var(--overlay-bg)] text-[var(--muted)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                  )}
                >
                  <ToolIcon toolType={ch.id} size={16} />
                  {ch.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Alert on status */}
      {channels.length > 0 && (
        <div>
          <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
            Alert when status is
          </label>
          <div className="flex flex-wrap gap-2">
            {ALERT_STATUSES.map((st) => (
              <button
                key={st.id}
                type="button"
                onClick={() => toggleStatus(st.id)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors',
                  alertOnStatus.includes(st.id)
                    ? `bg-[var(--overlay-strong)] border border-[var(--overlay-strong)] ${st.color}`
                    : 'bg-[var(--overlay-bg)] text-[var(--muted)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]'
                )}
              >
                {st.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
