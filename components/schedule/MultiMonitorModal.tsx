'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { NodeSelectionSurface, type SelectionViewMode } from './NodeSelectionSurface';
import { FamilyPicker } from './FamilyPicker';
import { PlanPreview } from './PlanPreview';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import type {
  FamilyEligibility,
  MonitoringPlanPreview,
  GroupPreview,
} from '@/types/health-watch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MultiMonitorModalProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
  stackId?: string;
  preselectedNodeIds?: string[];
}

type Step = 1 | 2 | 3 | 4;

const STEP_LABELS: Record<Step, string> = {
  1: 'Select Assets',
  2: 'Choose Monitor Types',
  3: 'Review',
  4: 'Schedule & Create',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MultiMonitorModal({
  open,
  onClose,
  onComplete,
  stackId,
  preselectedNodeIds,
}: MultiMonitorModalProps) {
  const [step, setStep] = useState<Step>(1);
  const [viewMode, setViewMode] = useState<SelectionViewMode>('lineage');

  // Step 1: Node selection
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>(
    preselectedNodeIds || [],
  );

  // Step 2: Family selection
  const [families, setFamilies] = useState<FamilyEligibility[]>([]);
  const [selectedFamilies, setSelectedFamilies] = useState<string[]>([]);
  const [familiesLoading, setFamiliesLoading] = useState(false);

  // Step 3: Preview
  const [preview, setPreview] = useState<MonitoringPlanPreview | null>(null);
  const [monitorToggles, setMonitorToggles] = useState<Record<string, boolean>>({});
  const [previewLoading, setPreviewLoading] = useState(false);

  // Step 4: Schedule & Create
  const [schedule, setSchedule] = useState('0 */6 * * *');
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  );
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);
  const [planName, setPlanName] = useState('');
  const [creating, setCreating] = useState(false);

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setStep(1);
      setSelectedNodeIds(preselectedNodeIds || []);
      setSelectedFamilies([]);
      setFamilies([]);
      setPreview(null);
      setMonitorToggles({});
      setPlanName('');
      setCreating(false);
    }
  }, [open, preselectedNodeIds]);

  // ---- Step 2: Fetch families when entering step 2 ----
  const fetchFamilies = useCallback(async () => {
    if (!stackId || selectedNodeIds.length === 0) return;
    setFamiliesLoading(true);
    try {
      const nodeIdsParam = selectedNodeIds.join(',');
      const params = new URLSearchParams({
        stackId,
        nodeIds: nodeIdsParam,
      });
      const res = await fetch(`/api/schedule/plans/families?${params}`);
      if (res.ok) {
        const data = await res.json();
        setFamilies(data.families || []);
      }
    } catch (err) {
      console.error('[MultiMonitor] Failed to fetch families:', err);
    } finally {
      setFamiliesLoading(false);
    }
  }, [stackId, selectedNodeIds]);

  // ---- Step 3: Fetch preview when entering step 3 ----
  const fetchPreview = useCallback(async () => {
    if (!stackId || selectedNodeIds.length === 0 || selectedFamilies.length === 0)
      return;
    setPreviewLoading(true);
    try {
      const res = await fetch('/api/schedule/plans/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scopeType: 'custom',
          scopeConfig: { nodeIds: selectedNodeIds },
          mode: 'recommended',
          families: selectedFamilies,
          stackId,
        }),
      });
      if (res.ok) {
        const data: MonitoringPlanPreview = await res.json();
        setPreview(data);
        // Initialize toggles — all enabled by default (unless already_monitored)
        const toggles: Record<string, boolean> = {};
        data.groups.forEach((g, gi) => {
          g.recommendations.forEach((rec, mi) => {
            if (!rec.already_monitored) {
              toggles[`${gi}:${mi}`] = true;
            }
          });
        });
        setMonitorToggles(toggles);
      }
    } catch (err) {
      console.error('[MultiMonitor] Failed to fetch preview:', err);
    } finally {
      setPreviewLoading(false);
    }
  }, [stackId, selectedNodeIds, selectedFamilies]);

  // ---- Step navigation ----
  const goToStep = useCallback(
    (target: Step) => {
      if (target === 2) fetchFamilies();
      if (target === 3) fetchPreview();
      setStep(target);
    },
    [fetchFamilies, fetchPreview],
  );

  const canGoNext = useMemo(() => {
    switch (step) {
      case 1: return selectedNodeIds.length > 0;
      case 2: return selectedFamilies.length > 0;
      case 3: return preview !== null && Object.values(monitorToggles).some(Boolean);
      case 4: return planName.trim().length > 0 && schedule.trim().length > 0;
      default: return false;
    }
  }, [step, selectedNodeIds, selectedFamilies, preview, monitorToggles, planName, schedule]);

  // ---- Family toggle ----
  const handleFamilyToggle = useCallback((familyKey: string) => {
    setSelectedFamilies((prev) =>
      prev.includes(familyKey)
        ? prev.filter((k) => k !== familyKey)
        : [...prev, familyKey],
    );
  }, []);

  // ---- Monitor toggle ----
  const handleMonitorToggle = useCallback((key: string) => {
    setMonitorToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // ---- Create plan ----
  const handleCreate = useCallback(async () => {
    if (!stackId || !preview) return;
    setCreating(true);
    try {
      // Filter groups to only include toggled-on monitors
      const filteredGroups = preview.groups.map((g, gi) => ({
        ...g,
        recommendations: g.recommendations.filter((_, mi) => {
          const key = `${gi}:${mi}`;
          return monitorToggles[key] ?? false;
        }),
      })).filter((g) => g.recommendations.length > 0);

      const res = await fetch('/api/schedule/plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: planName,
          scopeType: 'custom',
          scopeConfig: { nodeIds: selectedNodeIds },
          mode: 'recommended',
          families: selectedFamilies,
          schedule,
          timezone,
          alertChannels,
          alertOnStatus,
          groups: filteredGroups,
        }),
      });

      if (res.ok) {
        onComplete();
        onClose();
      } else {
        const err = await res.json();
        console.error('[MultiMonitor] Create failed:', err);
      }
    } catch (err) {
      console.error('[MultiMonitor] Create error:', err);
    } finally {
      setCreating(false);
    }
  }, [
    stackId, preview, monitorToggles, planName, selectedNodeIds,
    selectedFamilies, schedule, timezone, alertChannels, alertOnStatus,
    onComplete, onClose,
  ]);

  if (!open) return null;

  const enabledMonitorCount = Object.values(monitorToggles).filter(Boolean).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-[90vw] max-w-[1200px] h-[85vh] bg-[var(--bg)] border border-[var(--border)] rounded-xl shadow-2xl flex flex-col overflow-hidden">
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-4">
            <h2 className="text-[16px] font-semibold text-[var(--text)]">
              Multi Monitor
            </h2>

            {/* Step indicators */}
            <div className="flex items-center gap-1">
              {([1, 2, 3, 4] as Step[]).map((s) => (
                <button
                  key={s}
                  onClick={() => s < step && goToStep(s)}
                  disabled={s > step}
                  className={cn(
                    'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors',
                    s === step
                      ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                      : s < step
                        ? 'text-[var(--muted)] hover:text-[var(--text)] cursor-pointer'
                        : 'text-[var(--muted)]/40 cursor-default',
                  )}
                >
                  <span
                    className={cn(
                      'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold',
                      s === step
                        ? 'bg-[var(--accent)] text-white'
                        : s < step
                          ? 'bg-[var(--muted)]/20 text-[var(--text)]'
                          : 'bg-[var(--muted)]/10 text-[var(--muted)]/40',
                    )}
                  >
                    {s < step ? (
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : (
                      s
                    )}
                  </span>
                  <span className="hidden sm:inline">{STEP_LABELS[s]}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Close button */}
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-[var(--subtle-bg)] rounded-lg transition-colors"
          >
            <svg className="w-5 h-5 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* ---- Body ---- */}
        <div className="flex-1 overflow-y-auto">
          {/* Step 1: Select Assets */}
          {step === 1 && stackId && (
            <div className="h-full flex flex-col">
              {/* View mode toggle */}
              <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--border)]">
                <span className="text-[11px] text-[var(--muted)] mr-1">View:</span>
                <button
                  onClick={() => setViewMode('lineage')}
                  className={cn(
                    'px-2.5 py-1 rounded text-[11px] font-medium transition-colors',
                    viewMode === 'lineage'
                      ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                      : 'text-[var(--muted)] hover:text-[var(--text)]',
                  )}
                >
                  Lineage
                </button>
                <button
                  onClick={() => setViewMode('pipeline-overview')}
                  className={cn(
                    'px-2.5 py-1 rounded text-[11px] font-medium transition-colors',
                    viewMode === 'pipeline-overview'
                      ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                      : 'text-[var(--muted)] hover:text-[var(--text)]',
                  )}
                >
                  Pipeline Overview
                </button>
              </div>
              <div className="flex-1">
                <NodeSelectionSurface
                  stackId={stackId}
                  mode={viewMode}
                  selectedNodeIds={selectedNodeIds}
                  onSelectionChange={setSelectedNodeIds}
                  preselectedNodeIds={preselectedNodeIds}
                />
              </div>
            </div>
          )}

          {/* Step 2: Choose Monitor Types */}
          {step === 2 && (
            <div className="p-6 max-w-2xl mx-auto space-y-4">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Choose Monitor Types
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Select which monitor families to apply across your{' '}
                  {selectedNodeIds.length} selected asset
                  {selectedNodeIds.length !== 1 ? 's' : ''}.
                </p>
              </div>
              <FamilyPicker
                families={families}
                selected={selectedFamilies}
                onToggle={handleFamilyToggle}
                loading={familiesLoading}
              />
            </div>
          )}

          {/* Step 3: Review */}
          {step === 3 && (
            <div className="p-6 max-w-3xl mx-auto space-y-4">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Review Monitor Plan
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Review the generated monitor groups. Toggle individual monitors on or off.
                </p>
              </div>
              <PlanPreview
                preview={preview}
                monitorToggles={monitorToggles}
                onToggleMonitor={handleMonitorToggle}
                loading={previewLoading}
              />
            </div>
          )}

          {/* Step 4: Schedule & Create */}
          {step === 4 && (
            <div className="p-6 max-w-2xl mx-auto space-y-6">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Schedule & Create
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Set a schedule, configure alerts, and create your monitoring plan.
                </p>
              </div>

              {/* Plan name */}
              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Plan Name
                </label>
                <input
                  value={planName}
                  onChange={(e) => setPlanName(e.target.value)}
                  placeholder="e.g. Production Pipeline Monitors"
                  className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] placeholder:text-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              {/* Schedule */}
              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Schedule
                </label>
                <ScheduleInput value={schedule} onChange={setSchedule} />
              </div>

              {/* Timezone */}
              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Timezone
                </label>
                <input
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              {/* Alerts */}
              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Alerts
                </label>
                <AlertChannelPicker
                  channels={alertChannels}
                  onChannelsChange={setAlertChannels}
                  alertOnStatus={alertOnStatus}
                  onAlertOnStatusChange={setAlertOnStatus}
                />
              </div>

              {/* Summary */}
              {preview && (
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
                  <p className="text-[13px] text-[var(--text)]">
                    <span className="font-medium">{enabledMonitorCount}</span> monitors
                    across{' '}
                    <span className="font-medium">{preview.groups.length}</span> groups
                    covering{' '}
                    <span className="font-medium">{selectedNodeIds.length}</span> assets
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ---- Footer ---- */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-[var(--border)] bg-[var(--surface)]">
          <button
            onClick={() => (step === 1 ? onClose() : goToStep((step - 1) as Step))}
            className="px-4 py-2 text-[13px] text-[var(--muted)] hover:text-[var(--text)] transition-colors"
          >
            {step === 1 ? 'Cancel' : 'Back'}
          </button>

          {step < 4 ? (
            <button
              onClick={() => goToStep((step + 1) as Step)}
              disabled={!canGoNext}
              className={cn(
                'px-5 py-2 rounded-lg text-[13px] font-medium transition-colors',
                canGoNext
                  ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90'
                  : 'bg-[var(--muted)]/20 text-[var(--muted)] cursor-not-allowed',
              )}
            >
              Next
            </button>
          ) : (
            <button
              onClick={handleCreate}
              disabled={!canGoNext || creating}
              className={cn(
                'px-5 py-2 rounded-lg text-[13px] font-medium transition-colors',
                canGoNext && !creating
                  ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent)]/90'
                  : 'bg-[var(--muted)]/20 text-[var(--muted)] cursor-not-allowed',
              )}
            >
              {creating ? 'Creating...' : 'Create Monitoring Plan'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
