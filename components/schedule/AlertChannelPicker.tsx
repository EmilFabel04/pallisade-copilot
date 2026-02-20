'use client';

import { cn } from '@/lib/utils';

const ALERT_CHANNELS = [
  { id: 'slack', label: 'Slack', icon: '💬' },
  { id: 'email', label: 'Email', icon: '📧' },
  { id: 'pagerduty', label: 'PagerDuty', icon: '🚨' },
  { id: 'teams', label: 'Teams', icon: '👥' },
  { id: 'opsgenie', label: 'Opsgenie', icon: '📟' },
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
  connectedChannels?: string[];
}

export function AlertChannelPicker({
  channels,
  onChannelsChange,
  alertOnStatus,
  onAlertOnStatusChange,
  connectedChannels,
}: AlertChannelPickerProps) {
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
        <label className="block text-[12px] font-medium text-white/50 mb-2">
          Alert Channels
        </label>
        <div className="flex flex-wrap gap-2">
          {ALERT_CHANNELS.map((ch) => {
            const isSelected = channels.includes(ch.id);
            const isConnected = !connectedChannels || connectedChannels.includes(ch.id);
            return (
              <button
                key={ch.id}
                type="button"
                onClick={() => toggleChannel(ch.id)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors',
                  isSelected
                    ? 'bg-white/[0.12] text-white border border-white/[0.15]'
                    : 'bg-white/[0.04] text-white/40 border border-white/[0.06] hover:bg-white/[0.08]'
                )}
              >
                <span>{ch.icon}</span>
                {ch.label}
                {isSelected && !isConnected && (
                  <span className="text-[10px] text-amber-400 ml-1">(not connected)</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Alert on status */}
      {channels.length > 0 && (
        <div>
          <label className="block text-[12px] font-medium text-white/50 mb-2">
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
                    ? `bg-white/[0.12] border border-white/[0.15] ${st.color}`
                    : 'bg-white/[0.04] text-white/40 border border-white/[0.06] hover:bg-white/[0.08]'
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
