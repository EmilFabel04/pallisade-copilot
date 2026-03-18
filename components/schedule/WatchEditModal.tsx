'use client';

import { useState } from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WatchEditModalProps {
  watch: {
    id: string;
    name: string;
    schedule?: string;
    timezone?: string;
    alertChannels: string[];
    alertOnStatus: string[];
    enabled: boolean;
  };
  onSave: (data: {
    name: string;
    schedule: string;
    timezone: string;
    alertChannels: string[];
    alertOnStatus: string[];
    enabled: boolean;
  }) => Promise<void>;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const STATUS_OPTIONS = ['FAIL', 'WARN', 'ERROR'] as const;

export function WatchEditModal({ watch, onSave, onClose }: WatchEditModalProps) {
  const [name, setName] = useState(watch.name);
  const [schedule, setSchedule] = useState(watch.schedule ?? '0 8 * * *');
  const [timezone, setTimezone] = useState(watch.timezone ?? 'UTC');
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(watch.alertOnStatus);
  const [enabled, setEnabled] = useState(watch.enabled);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const toggleStatus = (status: string) => {
    setAlertOnStatus((prev) =>
      prev.includes(status) ? prev.filter((s) => s !== status) : [...prev, status],
    );
  };

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Name is required');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await onSave({
        name: name.trim(),
        schedule,
        timezone,
        alertChannels: watch.alertChannels,
        alertOnStatus,
        enabled,
      });
      onClose();
    } catch (e: any) {
      setError(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    /* Overlay */
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-md mx-4 bg-[var(--bg-primary,var(--surface))] border border-[var(--border-primary,var(--subtle-border))] rounded-xl shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-primary,var(--subtle-border))]">
          <h2 className="text-[15px] font-semibold text-[var(--text)]">Edit Watch Settings</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-5 space-y-5">
          {/* Name */}
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-1.5">
              Watch name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Production Pipeline Health"
              className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
            />
          </div>

          {/* Schedule */}
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-1.5">
              Schedule (cron)
            </label>
            <input
              type="text"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="0 8 * * *"
              className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] font-mono"
            />
            <p className="text-[11px] text-[var(--text-faint)] mt-1">
              Standard cron format — e.g. <span className="font-mono">0 8 * * *</span> for daily at 8am
            </p>
          </div>

          {/* Timezone */}
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-1.5">
              Timezone
            </label>
            <input
              type="text"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              placeholder="UTC"
              className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
            />
            <p className="text-[11px] text-[var(--text-faint)] mt-1">
              IANA timezone, e.g. <span className="font-mono">America/New_York</span>, <span className="font-mono">Europe/London</span>
            </p>
          </div>

          {/* Alert on status */}
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
              Alert on status
            </label>
            <div className="flex gap-2">
              {STATUS_OPTIONS.map((status) => {
                const active = alertOnStatus.includes(status);
                return (
                  <button
                    key={status}
                    type="button"
                    onClick={() => toggleStatus(status)}
                    className={cn(
                      'px-3 py-1.5 rounded-lg text-[12px] font-medium border transition-colors',
                      active
                        ? status === 'FAIL'
                          ? 'bg-red-500/15 border-red-500/30 text-red-400'
                          : status === 'WARN'
                          ? 'bg-amber-500/15 border-amber-500/30 text-amber-400'
                          : 'bg-orange-500/15 border-orange-500/30 text-orange-400'
                        : 'bg-[var(--overlay-bg)] border-[var(--subtle-border)] text-[var(--text-faint)] hover:text-[var(--text)]',
                    )}
                  >
                    {status}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Enabled toggle */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[13px] font-medium text-[var(--text)]">Enabled</p>
              <p className="text-[11px] text-[var(--text-faint)]">
                Disable to pause all monitors in this watch
              </p>
            </div>
            <button
              type="button"
              onClick={() => setEnabled((v) => !v)}
              className={cn(
                'relative w-10 h-[22px] rounded-full transition-colors',
                enabled ? 'bg-emerald-500/40' : 'bg-[var(--overlay-medium)]',
              )}
            >
              <div
                className={cn(
                  'absolute top-[3px] w-[16px] h-[16px] rounded-full bg-white transition-transform',
                  enabled ? 'left-[20px]' : 'left-[3px]',
                )}
              />
            </button>
          </div>

          {/* Error */}
          {error && (
            <p className="text-[12px] text-red-400">{error}</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2.5 px-5 py-4 border-t border-[var(--border-primary,var(--subtle-border))]">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 rounded-lg text-[13px] font-medium text-[var(--text-faint)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 rounded-lg bg-violet-500/20 hover:bg-violet-500/30 text-violet-300 text-[13px] font-medium transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
