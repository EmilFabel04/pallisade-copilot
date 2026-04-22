'use client';

import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { X, Loader2 } from 'lucide-react';
import { ScheduleInput } from './ScheduleInput';
import { AlertDestinationPicker, type AlertDestination } from './AlertDestinationPicker';
import { getMonitorDefinition, ASSET_MONITOR_TYPES } from '@/types/monitor-catalog';

interface MonitorGroupSettingsModalProps {
  watchId: string;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  integrations?: Array<{ id: string; name: string; type: string }>;
}

interface WatchDetail {
  id: string;
  name: string;
  anchorFqn: string | null;
  schedule: string | null;
  timezone: string | null;
  alertChannels: string[];
  alertOnStatus: string[];
  alertConfig: Record<string, any> | null;
  enabled: boolean;
  monitors: Array<{
    id: string;
    name: string;
    monitorType: string;
    enabled: boolean;
    lastStatus: string | null;
  }>;
}

export function MonitorGroupSettingsModal({
  watchId,
  open,
  onClose,
  onSaved,
  integrations,
}: MonitorGroupSettingsModalProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [watch, setWatch] = useState<WatchDetail | null>(null);

  // Form state
  const [schedule, setSchedule] = useState('');
  const [timezone, setTimezone] = useState('UTC');
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>([]);
  const [alertDestinations, setAlertDestinations] = useState<AlertDestination[]>([]);
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set());

  // Track original state for dirty detection
  const [originalTypes, setOriginalTypes] = useState<Set<string>>(new Set());

  const fetchWatch = useCallback(async () => {
    if (!watchId) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/schedule/watches/${watchId}`);
      if (!res.ok) throw new Error('Failed to fetch watch');
      const data = await res.json();
      const w = data.watch || data;
      setWatch(w);
      setSchedule(w.schedule || '');
      setTimezone(w.timezone || 'UTC');
      setAlertChannels(w.alertChannels || []);
      setAlertOnStatus(w.alertOnStatus || []);
      const existingDests = Array.isArray((w.alertConfig as any)?.destinations)
        ? ((w.alertConfig as any).destinations as AlertDestination[])
        : [];
      setAlertDestinations(existingDests);
      const types = new Set<string>(w.monitors?.map((m: any) => m.monitorType) || []);
      setActiveTypes(types);
      setOriginalTypes(new Set(types));
    } catch (err) {
      console.error('[MonitorGroupSettings] fetch error:', err);
      toast.error('Failed to load group settings');
    } finally {
      setLoading(false);
    }
  }, [watchId]);

  useEffect(() => {
    if (open) fetchWatch();
  }, [open, fetchWatch]);

  const handleToggleType = (type: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (!watch) return;
    setSaving(true);
    try {
      // Compute diffs
      const addMonitorTypes = [...activeTypes].filter((t) => !originalTypes.has(t));
      const removedTypes = [...originalTypes].filter((t) => !activeTypes.has(t));
      const removeMonitorIds = watch.monitors
        .filter((m) => removedTypes.includes(m.monitorType))
        .map((m) => m.id);

      const res = await fetch(`/api/schedule/watches/${watchId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          schedule: schedule || undefined,
          timezone: timezone || undefined,
          alertChannels: alertDestinations.length > 0
            ? Array.from(new Set(alertDestinations.map((d) => d.channelType)))
            : alertChannels,
          alertOnStatus: alertDestinations.length > 0
            ? Array.from(new Set(alertDestinations.flatMap((d) => d.triggerOn)))
            : alertOnStatus,
          alertConfig: alertDestinations.length > 0 ? { destinations: alertDestinations } : null,
          ...(addMonitorTypes.length > 0 && { addMonitorTypes }),
          ...(removeMonitorIds.length > 0 && { removeMonitorIds }),
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Failed to save');
      }

      toast.success('Group settings saved');
      onSaved();
      onClose();
    } catch (err: any) {
      console.error('[MonitorGroupSettings] save error:', err);
      toast.error(err.message || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-lg bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl shadow-2xl max-h-[85vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div>
            <h2 className="text-base font-semibold text-[var(--text)]">Group Settings</h2>
            {watch && (
              <p className="text-xs text-[var(--muted)] mt-0.5">
                {watch.name}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
          </div>
        ) : (
          <div className="px-6 py-4 space-y-4">
            {/* Schedule Section */}
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Schedule
              </h3>
              <ScheduleInput value={schedule} onChange={setSchedule} />
            </div>

            {/* Alert Destinations */}
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Alert Destinations
              </h3>
              <p className="text-[11px] text-[var(--muted)] mb-3">
                Default destinations for every monitor in this group. Individual monitors can override these.
              </p>
              <AlertDestinationPicker
                destinations={alertDestinations}
                onChange={setAlertDestinations}
                defaultTriggerOn={alertOnStatus.length > 0 ? alertOnStatus : ['FAIL', 'ERROR']}
                integrations={integrations}
              />
            </div>

            {/* Monitor Types Section */}
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Monitors
              </h3>
              <div className="space-y-1.5">
                {ASSET_MONITOR_TYPES.map((type) => {
                  const def = getMonitorDefinition(type);
                  if (!def) return null;
                  const isActive = activeTypes.has(type);
                  return (
                    <button
                      key={type}
                      onClick={() => handleToggleType(type)}
                      className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-left transition-colors ${
                        isActive
                          ? 'bg-emerald-500/10 border border-emerald-500/30'
                          : 'bg-[var(--overlay-light)] border border-transparent hover:border-[var(--subtle-border)]'
                      }`}
                    >
                      <div
                        className={`w-4 h-4 rounded flex items-center justify-center text-[10px] font-bold ${
                          isActive
                            ? 'bg-emerald-500 text-white'
                            : 'border border-[var(--overlay-strong)]'
                        }`}
                      >
                        {isActive && '✓'}
                      </div>
                      <span
                        className={`text-sm flex-1 ${
                          isActive ? 'text-[var(--text)]' : 'text-[var(--muted)]'
                        }`}
                      >
                        {def.label}
                      </span>
                      {isActive && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400">
                          Active
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-[var(--subtle-border)]">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg text-[var(--muted)] hover:text-[var(--text)] bg-[var(--overlay-light)] hover:bg-[var(--hover-bg)]"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
