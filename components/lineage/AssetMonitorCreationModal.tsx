'use client';

import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { X, Loader2, ChevronRight, ChevronLeft } from 'lucide-react';
import { ScheduleInput } from '@/components/schedule/ScheduleInput';
import { AlertChannelPicker } from '@/components/schedule/AlertChannelPicker';
import { getMonitorDefinition, ASSET_MONITOR_TYPES } from '@/types/monitor-catalog';
import { usePipeline } from '@/contexts/PipelineContext';

interface AssetMonitorCreationModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  /** The asset's fully-qualified name */
  assetFqn: string;
  /** The asset's engine node ID */
  assetNodeId: string;
  /** Display name for the asset */
  assetName: string;
  integrations?: Array<{ id: string; name: string; type: string }>;
}

type Step = 1 | 2 | 3;

const STEP_LABELS: Record<Step, string> = {
  1: 'Monitors',
  2: 'Schedule',
  3: 'Alerts',
};

export function AssetMonitorCreationModal({
  open,
  onClose,
  onCreated,
  assetFqn,
  assetNodeId,
  assetName,
  integrations,
}: AssetMonitorCreationModalProps) {
  const { selectedPipelineId } = usePipeline();
  const [step, setStep] = useState<Step>(1);
  const [saving, setSaving] = useState(false);
  const [existingTypes, setExistingTypes] = useState<Set<string>>(new Set());
  const [existingGroupId, setExistingGroupId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Step 1: Monitor type selection
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set());

  // Step 2: Schedule
  const [schedule, setSchedule] = useState('0 */6 * * *');
  const [timezone, setTimezone] = useState('UTC');

  // Step 3: Alerts
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN']);

  // Fetch existing group for this asset on open
  const fetchExisting = useCallback(async () => {
    if (!selectedPipelineId) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/schedule/watches/by-anchor?anchorFqn=${encodeURIComponent(assetFqn)}&stackId=${selectedPipelineId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.group) {
          setExistingGroupId(data.group.id);
          setExistingTypes(new Set(data.group.monitors.map((m: any) => m.monitorType)));
          // Pre-fill schedule/alerts from existing group
          if (data.group.schedule) setSchedule(data.group.schedule);
          if (data.group.timezone) setTimezone(data.group.timezone);
          if (data.group.alertChannels?.length) setAlertChannels(data.group.alertChannels);
          if (data.group.alertOnStatus?.length) setAlertOnStatus(data.group.alertOnStatus);
        }
      }
    } catch (err) {
      console.error('[AssetMonitorCreation] fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [assetFqn, selectedPipelineId]);

  useEffect(() => {
    if (open) {
      setStep(1);
      setSelectedTypes(new Set());
      setExistingTypes(new Set());
      setExistingGroupId(null);
      setSchedule('0 */6 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN']);
      fetchExisting();
    }
  }, [open, fetchExisting]);

  const handleToggleType = (type: string) => {
    if (existingTypes.has(type)) return; // can't toggle existing
    setSelectedTypes((prev) => {
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
    if (selectedTypes.size === 0) return;
    if (!selectedPipelineId) return;
    setSaving(true);
    try {
      if (existingGroupId) {
        // Add to existing group via PATCH
        const res = await fetch(`/api/schedule/watches/${existingGroupId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            stackId: selectedPipelineId,
            schedule,
            timezone,
            alertChannels,
            alertOnStatus,
            addMonitorTypes: [...selectedTypes],
          }),
        });
        if (!res.ok) throw new Error('Failed to add monitors');
      } else {
        // Create new group via POST
        const monitors = [...selectedTypes].map((type) => ({
          monitorType: type,
          targetFqn: assetFqn,
          config: {},
          depth: 0,
          priority: 1,
        }));

        const res = await fetch('/api/schedule/watches', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            stackId: selectedPipelineId,
            name: assetName,
            watchType: 'custom_watch',
            anchorFqn: assetFqn,
            anchorNodeId: assetNodeId,
            schedule,
            timezone,
            alertChannels,
            alertOnStatus,
            monitors,
          }),
        });
        if (!res.ok) throw new Error('Failed to create monitor group');
      }

      toast.success(
        existingGroupId ? 'Monitors added to group' : 'Monitor group created'
      );
      onCreated();
      onClose();
    } catch (err: any) {
      console.error('[AssetMonitorCreation] save error:', err);
      toast.error(err.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  const newSelectionCount = selectedTypes.size;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      <div className="relative z-10 w-full max-w-lg bg-[var(--surface)] border border-[var(--subtle-border)] rounded-xl shadow-2xl max-h-[85vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div>
            <h2 className="text-base font-semibold text-[var(--text)]">Create Monitor</h2>
            <p className="text-xs text-[var(--muted)] mt-0.5">
              {existingGroupId ? 'Adding to' : 'Creating group for'}{' '}
              <span className="text-blue-400">{assetName}</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center justify-center gap-6 px-6 py-3 border-b border-[var(--subtle-border)]">
          {([1, 2, 3] as Step[]).map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${
                  s === step
                    ? 'bg-blue-600 text-white'
                    : s < step
                      ? 'bg-emerald-500/20 text-emerald-400'
                      : 'bg-[var(--overlay-medium)] text-[var(--muted)]'
                }`}
              >
                {s < step ? '✓' : s}
              </div>
              <span
                className={`text-xs ${
                  s === step ? 'text-[var(--text)] font-medium' : 'text-[var(--muted)]'
                }`}
              >
                {STEP_LABELS[s]}
              </span>
            </div>
          ))}
        </div>

        {/* Body */}
        <div className="px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-5 h-5 animate-spin text-[var(--muted)]" />
            </div>
          ) : step === 1 ? (
            /* Step 1: Monitor Types */
            <div className="space-y-1.5">
              {ASSET_MONITOR_TYPES.map((type) => {
                const def = getMonitorDefinition(type);
                if (!def) return null;
                const alreadyExists = existingTypes.has(type);
                const isSelected = selectedTypes.has(type);
                return (
                  <button
                    key={type}
                    onClick={() => handleToggleType(type)}
                    disabled={alreadyExists}
                    className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-left transition-colors ${
                      alreadyExists
                        ? 'opacity-50 cursor-not-allowed bg-[var(--overlay-light)]'
                        : isSelected
                          ? 'bg-blue-500/10 border border-blue-500/30'
                          : 'bg-[var(--overlay-light)] border border-transparent hover:border-[var(--subtle-border)]'
                    }`}
                  >
                    <div
                      className={`w-4 h-4 rounded flex items-center justify-center text-[10px] font-bold ${
                        alreadyExists
                          ? 'bg-[var(--overlay-strong)] text-[var(--muted)]'
                          : isSelected
                            ? 'bg-blue-500 text-white'
                            : 'border border-[var(--overlay-strong)]'
                      }`}
                    >
                      {(alreadyExists || isSelected) && '✓'}
                    </div>
                    <span className={`text-sm flex-1 ${alreadyExists ? 'text-[var(--muted)]' : 'text-[var(--text)]'}`}>
                      {def.label}
                    </span>
                    {alreadyExists && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--overlay-medium)] text-[var(--muted)]">
                        Already exists
                      </span>
                    )}
                    {isSelected && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-400">
                        New
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : step === 2 ? (
            /* Step 2: Schedule */
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Schedule
              </h3>
              <ScheduleInput value={schedule} onChange={setSchedule} />
            </div>
          ) : (
            /* Step 3: Alerts */
            <div className="bg-[var(--surface-inset)] rounded-lg p-4">
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider mb-3">
                Alert Platform
              </h3>
              <AlertChannelPicker
                channels={alertChannels}
                onChannelsChange={setAlertChannels}
                alertOnStatus={alertOnStatus}
                onAlertOnStatusChange={setAlertOnStatus}
                integrations={integrations}
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between px-6 py-4 border-t border-[var(--subtle-border)]">
          <button
            onClick={() => (step === 1 ? onClose() : setStep((step - 1) as Step))}
            className="flex items-center gap-1 px-4 py-2 text-sm rounded-lg text-[var(--muted)] hover:text-[var(--text)] bg-[var(--overlay-light)] hover:bg-[var(--hover-bg)]"
          >
            {step === 1 ? 'Cancel' : <><ChevronLeft className="w-3 h-3" /> Back</>}
          </button>

          {step < 3 ? (
            <button
              onClick={() => setStep((step + 1) as Step)}
              disabled={step === 1 && newSelectionCount === 0}
              className="flex items-center gap-1 px-5 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
            >
              Next <ChevronRight className="w-3 h-3" />
            </button>
          ) : (
            <button
              onClick={handleSave}
              disabled={saving || newSelectionCount === 0}
              className="px-5 py-2 text-sm font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {saving
                ? 'Creating…'
                : `Create ${newSelectionCount} Monitor${newSelectionCount !== 1 ? 's' : ''}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
