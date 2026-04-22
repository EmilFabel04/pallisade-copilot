'use client';

import { useState, useEffect, useCallback } from 'react';
import { cachedFetch } from '@/lib/fetch-cache';
import { Check, Bell, Info } from 'lucide-react';
import { AlertDestinationPicker, type AlertDestination } from '@/components/schedule/AlertDestinationPicker';

export default function NotificationRoutingSettings() {
  const [destinations, setDestinations] = useState<AlertDestination[]>([]);
  const [notifyOnRecovery, setNotifyOnRecovery] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [integrations, setIntegrations] = useState<Array<{ id: string; name: string; type: string }>>([]);

  // Load current org defaults
  useEffect(() => {
    setLoading(true);
    Promise.all([
      cachedFetch('/api/settings/notification-routes')
        .then((r) => r.json())
        .catch(() => ({})),
      cachedFetch('/api/integrations/saved?types=SLACK,PAGERDUTY,OPSGENIE,TEAMS,EMAIL')
        .then((r) => r.json())
        .catch(() => ({ connections: [] })),
    ]).then(([routeData, intData]) => {
      // Load destinations from the saved org defaults
      if (routeData.orgDefaults) {
        const defaults = routeData.orgDefaults;
        if (Array.isArray(defaults.destinations)) {
          setDestinations(defaults.destinations);
        }
        if (defaults.notifyOnRecovery) {
          setNotifyOnRecovery(true);
        }
      } else if (Array.isArray(routeData.routes) && routeData.routes.length > 0) {
        // Migrate from old severity-based routes: merge all enabled routes'
        // destinations into a flat list with appropriate triggerOn states.
        const migrated: AlertDestination[] = [];
        const seen = new Set<string>();
        for (const route of routeData.routes) {
          if (!route.enabled || !route.destinations?.length) continue;
          for (const dest of route.destinations) {
            if (seen.has(dest.integrationId)) {
              // Merge triggerOn states
              const existing = migrated.find((d) => d.integrationId === dest.integrationId);
              if (existing) {
                const state = severityToTrigger(route.severity);
                if (state && !existing.triggerOn.includes(state)) {
                  existing.triggerOn.push(state);
                }
              }
            } else {
              seen.add(dest.integrationId);
              const state = severityToTrigger(route.severity);
              migrated.push({
                integrationId: dest.integrationId,
                channelType: '', // will resolve from integration
                triggerOn: state ? [state] : ['FAIL', 'ERROR'],
                config: dest.config || {},
              });
            }
          }
          if (route.notifyOnRecovery) setNotifyOnRecovery(true);
        }
        if (migrated.length > 0) setDestinations(migrated);
      }

      const activeIntegrations = (intData.connections || [])
        .filter((i: any) => i.status === 'ACTIVE')
        .map((i: any) => ({ id: i.id, name: i.name || i.type, type: i.type }));
      setIntegrations(activeIntegrations);

      // Backfill channelType on migrated destinations
      if (activeIntegrations.length > 0) {
        setDestinations((prev) =>
          prev.map((d) => {
            if (d.channelType) return d;
            const int = activeIntegrations.find((i: any) => i.id === d.integrationId);
            return int ? { ...d, channelType: int.type.toLowerCase() } : d;
          }),
        );
      }

      setLoading(false);
    });
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await fetch('/api/settings/notification-routes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          orgDefaults: {
            destinations,
            notifyOnRecovery,
          },
        }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // silent
    }
    setSaving(false);
  }, [destinations, notifyOnRecovery]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-6 h-6 red-spinner" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-[var(--text)] flex items-center gap-2">
            <Bell size={18} className="text-[var(--accent)]" />
            Organization Alert Defaults
          </h3>
          <p className="text-sm text-[var(--muted)] mt-1">
            Default alert destinations for all monitors. Individual monitors and groups can override these.
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium disabled:opacity-50 flex items-center gap-2"
        >
          {saved ? <><Check className="w-4 h-4" /> Saved</> : saving ? 'Saving...' : 'Save'}
        </button>
      </div>

      {/* Info box */}
      <div className="flex items-start gap-3 p-4 rounded-lg bg-blue-500/5 border border-blue-500/20">
        <Info size={16} className="text-blue-400 mt-0.5 shrink-0" />
        <div className="text-[12px] text-[var(--muted)] space-y-1">
          <p><strong className="text-[var(--text)]">How alert routing works:</strong></p>
          <p>When a monitor fires, Pallisade checks for destinations in this order:</p>
          <ol className="list-decimal ml-4 space-y-0.5">
            <li><strong>Monitor-level</strong> — set per-monitor in the monitor edit panel</li>
            <li><strong>Group-level</strong> — set on the monitor group via its settings</li>
            <li><strong>Org defaults</strong> — configured here (applies to everything not overridden above)</li>
          </ol>
          <p>In-app notifications always appear regardless of these settings.</p>
        </div>
      </div>

      {/* Destinations */}
      <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-5">
        <h4 className="text-[13px] font-semibold text-[var(--text)] mb-1">Default destinations</h4>
        <p className="text-[11px] text-[var(--muted)] mb-4">
          Choose which platforms receive alerts and on which monitor states.
        </p>
        <AlertDestinationPicker
          destinations={destinations}
          onChange={setDestinations}
          defaultTriggerOn={['FAIL', 'ERROR']}
          integrations={integrations.length > 0 ? integrations : undefined}
        />
      </div>

      {/* Recovery toggle */}
      <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-5">
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={notifyOnRecovery}
            onChange={(e) => setNotifyOnRecovery(e.target.checked)}
            className="rounded border-[var(--border)] accent-[var(--accent)]"
          />
          <div>
            <p className="text-[13px] font-medium text-[var(--text)]">Notify on recovery</p>
            <p className="text-[11px] text-[var(--muted)]">
              Send an alert when a monitor recovers (transitions back to PASS after a failure).
              Only fires if the destination has "Recovered" in its trigger states.
            </p>
          </div>
        </label>
      </div>
    </div>
  );
}

function severityToTrigger(severity: string): string | null {
  switch (severity) {
    case 'CRITICAL': return 'FAIL';
    case 'ERROR': return 'ERROR';
    case 'WARN': return 'WARN';
    default: return null;
  }
}
