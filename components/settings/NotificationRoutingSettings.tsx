'use client';

import { useState, useEffect } from 'react';
import { cachedFetch } from '@/lib/fetch-cache';
import { X, Check } from 'lucide-react';

interface Integration {
  id: string;
  type: string;
  status: string;
  metadata?: Record<string, any>;
}

interface Destination {
  integrationId: string;
  channel?: string;
}

interface Route {
  severity: string;
  enabled: boolean;
  notifyOnRecovery: boolean;
  destinations: Destination[];
}

const SEVERITIES = ['CRITICAL', 'ERROR', 'WARN', 'INFO'];
const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: 'bg-red-500/20 text-red-400 border-red-500/30',
  ERROR: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  WARN: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  INFO: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
};

export default function NotificationRoutingSettings() {
  const [routes, setRoutes] = useState<Route[]>(
    SEVERITIES.map((s) => ({ severity: s, enabled: false, notifyOnRecovery: false, destinations: [] })),
  );
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    cachedFetch('/api/settings/notification-routes')
      .then((r) => r.json())
      .then((data) => {
        if (data.routes?.length) {
          setRoutes((prev) =>
            prev.map((r) => {
              const existing = data.routes.find((er: any) => er.severity === r.severity);
              return existing
                ? { ...r, enabled: existing.enabled, notifyOnRecovery: existing.notifyOnRecovery, destinations: existing.destinations || [] }
                : r;
            }),
          );
        }
      })
      .catch(() => {});

    cachedFetch('/api/integrations?layer=notifications')
      .then((r) => r.json())
      .then((data) => setIntegrations((data.integrations || []).filter((i: Integration) => i.status === 'ACTIVE')))
      .catch(() => {});
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch('/api/settings/notification-routes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ routes }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {}
    setSaving(false);
  };

  const updateRoute = (severity: string, updates: Partial<Route>) => {
    setRoutes((prev) => prev.map((r) => (r.severity === severity ? { ...r, ...updates } : r)));
  };

  const addDestination = (severity: string, integrationId: string) => {
    setRoutes((prev) =>
      prev.map((r) => {
        if (r.severity !== severity) return r;
        if (r.destinations.some((d) => d.integrationId === integrationId)) return r;
        return { ...r, destinations: [...r.destinations, { integrationId }] };
      }),
    );
  };

  const removeDestination = (severity: string, integrationId: string) => {
    setRoutes((prev) =>
      prev.map((r) => {
        if (r.severity !== severity) return r;
        return { ...r, destinations: r.destinations.filter((d) => d.integrationId !== integrationId) };
      }),
    );
  };

  const getIntegrationLabel = (id: string) => {
    const int = integrations.find((i) => i.id === id);
    if (!int) return 'Unknown';
    const name = int.metadata?.teamName || int.metadata?.workspace || int.type;
    return `${int.type} — ${name}`;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-[var(--text)]">Notification Routing</h3>
          <p className="text-sm text-[var(--muted)] mt-1">
            Configure where monitor group results are sent based on severity. In-app notifications always appear regardless of these settings.
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

      <div className="space-y-4">
        {routes.map((route) => (
          <div
            key={route.severity}
            className="rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-faint)] p-4"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <span className={`px-2 py-0.5 rounded text-xs font-medium border ${SEVERITY_COLORS[route.severity]}`}>
                  {route.severity}
                </span>
                <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
                  <input
                    type="checkbox"
                    checked={route.enabled}
                    onChange={(e) => updateRoute(route.severity, { enabled: e.target.checked })}
                    className="rounded"
                  />
                  Enabled
                </label>
                <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
                  <input
                    type="checkbox"
                    checked={route.notifyOnRecovery}
                    onChange={(e) => updateRoute(route.severity, { notifyOnRecovery: e.target.checked })}
                    className="rounded"
                  />
                  Notify on recovery
                </label>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 items-center">
              {route.destinations.map((dest) => (
                <span
                  key={dest.integrationId}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-[var(--overlay-faint)] border border-[var(--subtle-border)] text-sm text-[var(--muted)]"
                >
                  {getIntegrationLabel(dest.integrationId)}
                  <button
                    onClick={() => removeDestination(route.severity, dest.integrationId)}
                    className="hover:text-red-400"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}

              {integrations.filter(
                (i) => !route.destinations.some((d) => d.integrationId === i.id),
              ).length > 0 && (
                <select
                  onChange={(e) => {
                    if (e.target.value) addDestination(route.severity, e.target.value);
                    e.target.value = '';
                  }}
                  className="px-2 py-1 rounded-md bg-[var(--overlay-faint)] border border-[var(--subtle-border)] text-sm text-[var(--muted)] cursor-pointer"
                  defaultValue=""
                >
                  <option value="" disabled>
                    + Add platform
                  </option>
                  {integrations
                    .filter((i) => !route.destinations.some((d) => d.integrationId === i.id))
                    .map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.type} — {i.metadata?.teamName || i.metadata?.workspace || i.type}
                      </option>
                    ))}
                </select>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
