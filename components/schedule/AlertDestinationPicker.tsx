'use client';

import { useEffect, useMemo, useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { ToolIcon } from '@/components/icons/ToolIcon';
import { usePipeline } from '@/contexts/PipelineContext';
import { cachedFetch } from '@/lib/fetch-cache';
import { Plus, Trash2 } from 'lucide-react';

/**
 * A single alert destination: one integration instance, a set of trigger states,
 * and optional per-destination config (Slack channel override, PD routing key, etc.)
 */
export interface AlertDestination {
  integrationId: string;
  channelType: string;
  triggerOn: string[];
  config?: Record<string, any>;
}

const CHANNEL_TYPE_MAP: Record<string, string> = {
  slack: 'slack',
  SLACK: 'slack',
  email: 'email',
  EMAIL: 'email',
  pagerduty: 'pagerduty',
  PAGERDUTY: 'pagerduty',
  teams: 'teams',
  TEAMS: 'teams',
  opsgenie: 'opsgenie',
  OPSGENIE: 'opsgenie',
};

const CHANNEL_LABELS: Record<string, string> = {
  slack: 'Slack',
  email: 'Email',
  pagerduty: 'PagerDuty',
  teams: 'Microsoft Teams',
  opsgenie: 'Opsgenie',
};

const ALERT_STATES = [
  { id: 'FAIL', label: 'Fail', color: 'text-red-400', description: 'Assertion or threshold breach' },
  { id: 'WARN', label: 'Warn', color: 'text-amber-400', description: 'Soft deviation below fail threshold' },
  { id: 'ERROR', label: 'Error', color: 'text-orange-400', description: 'Exception during execution' },
  { id: 'RECOVERED', label: 'Recovered', color: 'text-emerald-400', description: 'Back to PASS after a failure' },
];

/**
 * Per-channel config fields. Keys map to the `config` object on the destination
 * and are read by lib/notification-router.ts when dispatching.
 */
const CHANNEL_CONFIG_FIELDS: Record<string, Array<{ key: string; label: string; placeholder: string; help?: string }>> = {
  slack: [
    { key: 'channel', label: 'Channel override', placeholder: '#data-alerts', help: 'Optional — defaults to the integration\'s configured channel.' },
  ],
  pagerduty: [
    { key: 'routingKey', label: 'Routing key override', placeholder: 'R0UTING_KEY', help: 'Optional — defaults to the integration\'s default service.' },
    { key: 'dedupKey', label: 'Dedup key', placeholder: 'monitor-{id}', help: 'Optional — PagerDuty dedup key template.' },
  ],
  email: [
    { key: 'to', label: 'Recipients', placeholder: 'oncall@example.com,data@example.com', help: 'Comma-separated list of email addresses.' },
  ],
  teams: [
    { key: 'webhookUrl', label: 'Webhook URL override', placeholder: 'https://…/webhook', help: 'Optional — defaults to the integration webhook.' },
  ],
  opsgenie: [
    { key: 'team', label: 'Team override', placeholder: 'data-oncall', help: 'Optional Opsgenie team to route the alert to.' },
    { key: 'priority', label: 'Priority', placeholder: 'P2', help: 'Opsgenie priority (P1–P5).' },
  ],
};

interface Integration {
  id: string;
  name: string;
  type: string;
}

interface AlertDestinationPickerProps {
  destinations: AlertDestination[];
  onChange: (destinations: AlertDestination[]) => void;
  /** Defaults used when a new destination is added. */
  defaultTriggerOn?: string[];
  /** If provided, skips the self-fetch. */
  integrations?: Integration[];
}

export function AlertDestinationPicker({
  destinations,
  onChange,
  defaultTriggerOn = ['FAIL'],
  integrations,
}: AlertDestinationPickerProps) {
  const { selectedPipelineId } = usePipeline();
  const [fetched, setFetched] = useState<Integration[] | null>(null);

  useEffect(() => {
    if (integrations || !selectedPipelineId) return;
    cachedFetch(`/api/integrations?stackId=${selectedPipelineId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data?.integrations) {
          setFetched([]);
          return;
        }
        setFetched(
          (data.integrations as any[])
            .filter((i: any) => i.status === 'ACTIVE' && CHANNEL_TYPE_MAP[i.type])
            .map((i: any) => ({ id: i.id, name: i.name || i.type, type: i.type })),
        );
      })
      .catch(() => setFetched([]));
  }, [integrations, selectedPipelineId]);

  const resolved = integrations ?? fetched ?? [];

  // Group available integrations by normalized channel type
  const integrationsByChannel = useMemo(() => {
    const out: Record<string, Integration[]> = {};
    for (const i of resolved) {
      const channel = CHANNEL_TYPE_MAP[i.type] || CHANNEL_TYPE_MAP[i.type.toLowerCase()];
      if (!channel) continue;
      (out[channel] ||= []).push(i);
    }
    return out;
  }, [resolved]);

  const addDestination = useCallback(
    (integrationId: string, channelType: string) => {
      if (destinations.some((d) => d.integrationId === integrationId)) return;
      onChange([
        ...destinations,
        { integrationId, channelType, triggerOn: [...defaultTriggerOn], config: {} },
      ]);
    },
    [destinations, onChange, defaultTriggerOn],
  );

  const removeDestination = useCallback(
    (integrationId: string) => {
      onChange(destinations.filter((d) => d.integrationId !== integrationId));
    },
    [destinations, onChange],
  );

  const updateDestination = useCallback(
    (integrationId: string, patch: Partial<AlertDestination>) => {
      onChange(
        destinations.map((d) =>
          d.integrationId === integrationId ? { ...d, ...patch } : d,
        ),
      );
    },
    [destinations, onChange],
  );

  const toggleTrigger = useCallback(
    (integrationId: string, state: string) => {
      const dest = destinations.find((d) => d.integrationId === integrationId);
      if (!dest) return;
      const next = dest.triggerOn.includes(state)
        ? dest.triggerOn.filter((s) => s !== state)
        : [...dest.triggerOn, state];
      updateDestination(integrationId, { triggerOn: next });
    },
    [destinations, updateDestination],
  );

  const updateConfigField = useCallback(
    (integrationId: string, fieldKey: string, value: string) => {
      const dest = destinations.find((d) => d.integrationId === integrationId);
      if (!dest) return;
      updateDestination(integrationId, {
        config: { ...(dest.config || {}), [fieldKey]: value },
      });
    },
    [destinations, updateDestination],
  );

  const availableToAdd = useMemo(
    () => resolved.filter((i) => !destinations.some((d) => d.integrationId === i.id)),
    [resolved, destinations],
  );

  return (
    <div className="space-y-4">
      {/* Existing destinations */}
      {destinations.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--subtle-border)] px-4 py-6 text-center">
          <p className="text-[12px] text-[var(--muted)]">
            No alert destinations configured. This monitor will not notify anyone.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {destinations.map((dest) => {
            const integration = resolved.find((i) => i.id === dest.integrationId);
            const fields = CHANNEL_CONFIG_FIELDS[dest.channelType] || [];
            return (
              <div
                key={dest.integrationId}
                className="rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] p-3 space-y-3"
              >
                {/* Header */}
                <div className="flex items-center gap-2">
                  <ToolIcon toolType={dest.channelType} size={16} />
                  <div className="flex-1">
                    <p className="text-[12px] font-medium text-[var(--text)]">
                      {integration?.name || CHANNEL_LABELS[dest.channelType]}
                    </p>
                    <p className="text-[10px] text-[var(--muted)]">
                      {CHANNEL_LABELS[dest.channelType]}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeDestination(dest.integrationId)}
                    className="p-1 rounded text-[var(--muted)] hover:text-red-400 hover:bg-red-500/10 transition-colors"
                    aria-label="Remove destination"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>

                {/* Trigger states */}
                <div>
                  <p className="text-[10px] text-[var(--muted)] uppercase tracking-wide mb-1.5">
                    Alert when
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {ALERT_STATES.map((st) => {
                      const active = dest.triggerOn.includes(st.id);
                      return (
                        <button
                          key={st.id}
                          type="button"
                          onClick={() => toggleTrigger(dest.integrationId, st.id)}
                          title={st.description}
                          className={cn(
                            'px-2 py-1 rounded text-[11px] font-medium transition-colors',
                            active
                              ? `bg-[var(--overlay-strong)] border border-[var(--overlay-strong)] ${st.color}`
                              : 'bg-[var(--surface)] text-[var(--muted)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]',
                          )}
                        >
                          {st.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Per-destination config */}
                {fields.length > 0 && (
                  <div className="space-y-2">
                    {fields.map((f) => (
                      <div key={f.key}>
                        <label className="block text-[10px] text-[var(--muted)] uppercase tracking-wide mb-1">
                          {f.label}
                        </label>
                        <input
                          type="text"
                          value={(dest.config?.[f.key] as string) ?? ''}
                          onChange={(e) => updateConfigField(dest.integrationId, f.key, e.target.value)}
                          placeholder={f.placeholder}
                          className="w-full bg-[var(--surface)] border border-[var(--subtle-border)] rounded px-2 py-1 text-[11px] text-[var(--text)] placeholder:text-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)]"
                        />
                        {f.help && (
                          <p className="text-[10px] text-[var(--muted)] mt-0.5">{f.help}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Add destination */}
      {resolved.length === 0 ? (
        <p className="text-[11px] text-[var(--muted)]">
          No notification integrations connected. Add Slack, PagerDuty, Teams, Opsgenie, or Email in the Integrations tab of the pipeline first.
        </p>
      ) : availableToAdd.length > 0 ? (
        <div>
          <label className="block text-[10px] text-[var(--muted)] uppercase tracking-wide mb-1.5">
            Add destination
          </label>
          <div className="space-y-2">
            {Object.entries(integrationsByChannel).map(([channel, items]) => {
              const picks = items.filter((i) => !destinations.some((d) => d.integrationId === i.id));
              if (picks.length === 0) return null;
              return (
                <div key={channel} className="flex items-center gap-2 flex-wrap">
                  <div className="flex items-center gap-1.5 text-[11px] text-[var(--muted)] min-w-[80px]">
                    <ToolIcon toolType={channel} size={14} />
                    {CHANNEL_LABELS[channel]}
                  </div>
                  {picks.map((i) => (
                    <button
                      key={i.id}
                      type="button"
                      onClick={() => addDestination(i.id, channel)}
                      className="flex items-center gap-1 px-2 py-1 rounded text-[11px] bg-[var(--surface)] border border-[var(--subtle-border)] text-[var(--text)] hover:bg-[var(--hover-bg)]"
                    >
                      <Plus size={12} /> {i.name}
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <p className="text-[10px] text-[var(--muted)]">All connected integrations are already in use as destinations.</p>
      )}
    </div>
  );
}
