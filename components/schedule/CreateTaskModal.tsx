'use client';

import { useState, useEffect, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import type { ScheduledTask } from '@/types/schedule';

export interface MonitorPrefillData {
  name: string;
  monitorType: string;
  targetFqn?: string;
  config?: Record<string, any>;
  integrationId?: string;
}

interface CreateTaskModalProps {
  open: boolean;
  onClose: () => void;
  onUpdate?: (taskId: string, task: any) => void;
  onComplete?: () => void;
  editTask?: ScheduledTask | null;
  prefillData?: MonitorPrefillData | null;
  integrations?: Array<{ id: string; name: string; type: string }>;
  stackId?: string;
  initialMode?: 'prompt';
  onPlanCreated?: (planId: string) => void;
  /** @deprecated Use onComplete instead — creation now goes through plans API */
  onSubmit?: (task: any) => void;
}

export function CreateTaskModal({ open, onClose, onSubmit, onUpdate, onComplete, editTask, prefillData, integrations = [], stackId, initialMode, onPlanCreated }: CreateTaskModalProps) {
  const [step, setStep] = useState(1);
  const isEditing = !!editTask;

  // Step 1: Prompt content
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [targetFqn, setTargetFqn] = useState('');

  // Step 2: Schedule
  const [schedule, setSchedule] = useState('0 8 * * *');
  const [timezone, setTimezone] = useState('UTC');

  // Step 3: Alerts
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);
  const [integrationId, setIntegrationId] = useState('');
  const [connectedChannels, setConnectedChannels] = useState<string[]>(['email']);
  const [creating, setCreating] = useState(false);

  // Pre-fill form when editing an existing task
  useEffect(() => {
    if (editTask) {
      setName(editTask.name);
      setPrompt(editTask.prompt || '');
      setTargetFqn(editTask.targetFqn || '');
      setSchedule(editTask.schedule);
      setTimezone(editTask.timezone);
      setAlertChannels(editTask.alertChannels || []);
      setAlertOnStatus(editTask.alertOnStatus || ['FAIL', 'WARN', 'ERROR']);
      setIntegrationId(editTask.integrationId || '');
      setStep(1);
    } else if (open) {
      setName(prefillData?.name || '');
      setPrompt('');
      setTargetFqn(prefillData?.targetFqn || '');
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setIntegrationId(prefillData?.integrationId || '');
      setStep(1);
      setCreating(false);
    }
  }, [editTask, prefillData, open]);

  // Fetch connected channel status when modal opens
  useEffect(() => {
    if (!open) return;
    const channels = ['email'];
    fetch('/api/integrations/slack')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data?.connected) channels.push('slack');
        setConnectedChannels(channels);
      })
      .catch(() => setConnectedChannels(channels));
  }, [open]);

  if (!open) return null;

  // Filter warehouse integrations for prompt mode
  const warehouseIntegrations = integrations.filter((i, idx, arr) => {
    const t = i.type.toLowerCase();
    return ['bigquery', 'snowflake', 'postgres', 'redshift'].includes(t) &&
      arr.findIndex((x) => x.id === i.id) === idx;
  });

  const canProceedStep1 = name.trim() && prompt.trim();
  const canProceedStep2 = schedule.trim();

  const handleSubmit = async () => {
    if (isEditing && onUpdate) {
      // Edit path: update existing task via PATCH
      onUpdate(editTask!.id, {
        name,
        taskMode: 'prompt',
        prompt,
        schedule,
        timezone,
        alertChannels,
        alertOnStatus,
        integrationId: integrationId || undefined,
      });
      return;
    }

    // New creation: go through plans API
    if (!name || !schedule) return;
    setCreating(true);
    try {
      const groups = [{
        anchor_name: name,
        anchor_fqn: targetFqn || name,
        anchor_id: 'prompt_monitor',
        anchor_node_type: 'prompt',
        anchor_platform: 'ai',
        watch_type: 'custom_watch',
        recommendations: [{
          monitor_key: 'AI_PROMPT',
          target_fqn: targetFqn || name,
          config_hints: {
            taskMode: 'prompt',
            prompt,
            ...(integrationId ? { integrationId } : {}),
          },
        }],
      }];

      const res = await fetch('/api/schedule/plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          scopeType: 'asset',
          mode: 'manual',
          families: [],
          schedule,
          timezone,
          alertChannels,
          alertOnStatus,
          groups,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        onPlanCreated?.(data.id);
        onComplete?.();
        onClose();
      } else {
        const err = await res.json().catch(() => ({}));
        console.error('[CreateTaskModal] Plan creation failed:', err);
      }
    } catch (err) {
      console.error('[CreateTaskModal] Prompt monitor creation failed:', err);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-3xl mx-4 bg-[var(--surface)] rounded-2xl border border-[var(--subtle-border)] shadow-2xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex-shrink-0 flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <h2 className="text-[16px] font-semibold text-[var(--text)]">{isEditing ? 'Edit Monitor' : 'Create AI Prompt Monitor'}</h2>
          <button onClick={onClose} className="text-[var(--muted)] hover:text-[var(--text)]">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Step indicators */}
        <div className="flex-shrink-0 flex items-center gap-3 px-6 py-3 border-b border-[var(--border-faint)]">
            {[1, 2, 3].map((s) => (
              <div key={s} className="flex items-center gap-2">
                <div className={cn(
                  'w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-medium',
                  step === s
                    ? 'bg-[var(--overlay-strong)] text-[var(--text)]'
                    : step > s
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : 'bg-[var(--overlay-bg)] text-[var(--text-faint)]'
                )}>
                  {step > s ? '\u2713' : s}
                </div>
                <span className={cn(
                  'text-[12px]',
                  step === s ? 'text-[var(--text)]' : 'text-[var(--text-faint)]'
                )}>
                  {s === 1 ? 'Prompt' : s === 2 ? 'Schedule' : 'Alerts'}
                </span>
                {s < 3 && <div className="w-8 h-px bg-[var(--hover-bg)]" />}
              </div>
            ))}
          </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-6 py-6 space-y-5">
          {step === 1 && (
            <>
              <div className="mb-5">
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Monitor Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Daily freshness check on orders"
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Prompt
                </label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="e.g., Check if the orders table has received fresh data in the last 24 hours. If stale, report which datasets haven't been updated."
                  rows={4}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2.5 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] resize-none"
                />
              </div>

              {/* Warehouse integration selector */}
              {warehouseIntegrations.length > 0 && (
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Run against warehouse
                  </label>
                  <select
                    value={integrationId}
                    onChange={(e) => setIntegrationId(e.target.value)}
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
                  >
                    <option value="">Auto-detect</option>
                    {warehouseIntegrations.map((i) => (
                      <option key={i.id} value={i.id}>{i.name} ({i.type})</option>
                    ))}
                  </select>
                </div>
              )}
            </>
          )}

          {step === 2 && (
            <>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Schedule
                </label>
                <ScheduleInput value={schedule} onChange={setSchedule} />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Timezone
                </label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)] appearance-none"
                >
                  <option value="UTC">UTC</option>
                  <option value="America/New_York">Eastern (ET)</option>
                  <option value="America/Chicago">Central (CT)</option>
                  <option value="America/Denver">Mountain (MT)</option>
                  <option value="America/Los_Angeles">Pacific (PT)</option>
                  <option value="Europe/London">London (GMT/BST)</option>
                  <option value="Europe/Berlin">Berlin (CET)</option>
                  <option value="Asia/Tokyo">Tokyo (JST)</option>
                </select>
              </div>
            </>
          )}

          {step === 3 && (
            <AlertChannelPicker
              channels={alertChannels}
              onChannelsChange={setAlertChannels}
              alertOnStatus={alertOnStatus}
              onAlertOnStatusChange={setAlertOnStatus}
              connectedChannels={connectedChannels}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 flex items-center justify-between px-6 py-4 border-t border-[var(--subtle-border)]">
          <div>
            {step > 1 && (
              <Button variant="ghost" size="sm" onClick={() => setStep(step - 1)}>
                Back
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            {step < 3 ? (
              <Button
                size="sm"
                onClick={() => setStep(step + 1)}
                disabled={step === 1 ? !canProceedStep1 : !canProceedStep2}
              >
                Next
              </Button>
            ) : (
              <Button size="sm" onClick={handleSubmit} disabled={creating}>
                {creating ? 'Creating...' : isEditing ? 'Save Changes' : 'Create Monitor'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
