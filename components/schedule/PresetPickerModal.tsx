'use client';

import { useState, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import {
  type PresetKey,
  type PresetDefinition,
  type PresetPreviewResult,
  type PresetWatchPreview,
  WATCH_TYPE_LABELS,
} from '@/types/health-watch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AnchorNode {
  id: string;
  fqn: string;
  name: string;
  platformDomain?: string;
  assetKind?: string;
  platform?: string;
}

export interface PresetPickerModalProps {
  open: boolean;
  onClose: () => void;
  onComplete: (watchIds: string[]) => void;
  anchorNode?: AnchorNode | null;
  stackId?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRESET_ICONS: Record<PresetKey, string> = {
  pipeline_health: 'M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7',
  data_drift: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6',
  ingestion_watch: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
  bi_reliability: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
  full_coverage: 'M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
};

const PRIORITY_COLORS: Record<number, string> = {
  1: 'bg-red-500/15 text-red-400',
  2: 'bg-amber-500/15 text-amber-400',
  3: 'bg-white/10 text-[var(--muted)]',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PresetPickerModal({
  open,
  onClose,
  onComplete,
  anchorNode,
  stackId,
}: PresetPickerModalProps) {
  // Steps: 1=pick preset, 2=preview, 3=schedule+create
  const [step, setStep] = useState(1);

  // Auto-anchor (resolved automatically from lineage graph)
  const [selectedAnchor, setSelectedAnchor] = useState<AnchorNode | null>(null);
  const [anchorLoading, setAnchorLoading] = useState(false);
  const [totalNodes, setTotalNodes] = useState(0);

  // Step 1: Preset selection
  const [presets, setPresets] = useState<PresetDefinition[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<PresetKey | 'smart_build' | null>(null);

  // Step 3: Preview
  const [preview, setPreview] = useState<PresetPreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [watchToggles, setWatchToggles] = useState<Record<number, boolean>>({});
  const [monitorToggles, setMonitorToggles] = useState<Record<string, boolean>>({});
  const [expandedWatch, setExpandedWatch] = useState<number | null>(null);

  // Step 4: Schedule + create
  const [schedule, setSchedule] = useState('0 8 * * *');
  const [timezone, setTimezone] = useState('UTC');
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);
  const [creating, setCreating] = useState(false);

  // Reset when modal opens — auto-detect anchor from lineage graph
  useEffect(() => {
    if (!open) return;

    setStep(1);
    setSelectedPreset(null);
    setPreview(null);
    setPreviewLoading(false);
    setWatchToggles({});
    setMonitorToggles({});
    setExpandedWatch(null);
    setSchedule('0 8 * * *');
    setTimezone('UTC');
    setAlertChannels([]);
    setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
    setCreating(false);

    if (anchorNode) {
      setSelectedAnchor(anchorNode);
      setAnchorLoading(false);
    } else if (stackId) {
      // Auto-detect best anchor from the full lineage graph
      setSelectedAnchor(null);
      setAnchorLoading(true);
      fetch(`/api/pipeline/${stackId}/lineage/engine?action=auto-anchor`)
        .then((res) => res.ok ? res.json() : null)
        .then((data) => {
          if (data?.anchor) {
            setSelectedAnchor({
              id: data.anchor.id,
              fqn: data.anchor.fqn,
              name: data.anchor.name,
              platformDomain: data.anchor.platformDomain,
            });
            setTotalNodes(data.totalNodes || 0);
          }
        })
        .catch((err) => console.error('[PresetPicker] Auto-anchor error:', err))
        .finally(() => setAnchorLoading(false));
    }
  }, [open, anchorNode, stackId]);

  // Fetch presets when entering step 1 (preset selection)
  useEffect(() => {
    if (step !== 1) return;
    const fetchPresets = async () => {
      try {
        const domain = selectedAnchor?.platformDomain || '';
        const res = await fetch(`/api/schedule/presets${domain ? `?nodeDomain=${domain}` : ''}`);
        if (res.ok) {
          const data = await res.json();
          setPresets(data.presets || []);
        }
      } catch (err) {
        console.error('[PresetPicker] Fetch presets error:', err);
      }
    };
    fetchPresets();
  }, [step, selectedAnchor]);

  // (Asset search removed — anchor is auto-detected from lineage graph)

  // Fetch preview when entering step 2
  useEffect(() => {
    if (step !== 2 || !selectedAnchor || !selectedPreset) return;

    const fetchPreview = async () => {
      setPreviewLoading(true);
      try {
        const res = await fetch('/api/schedule/presets/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            presetKey: selectedPreset === 'smart_build' ? undefined : selectedPreset,
            anchorNodeId: selectedAnchor.id,
            stackId,
            mode: selectedPreset === 'smart_build' ? 'smart_build' : undefined,
          }),
        });
        if (res.ok) {
          const data = await res.json();
          setPreview(data);
          // Initialize toggles — all watches and monitors enabled
          const wToggles: Record<number, boolean> = {};
          const mToggles: Record<string, boolean> = {};
          (data.watches || []).forEach((w: PresetWatchPreview, wi: number) => {
            wToggles[wi] = true;
            (w.scopeResult?.recommendations || []).forEach((r: any, ri: number) => {
              mToggles[`${wi}:${ri}`] = !r.already_monitored;
            });
          });
          setWatchToggles(wToggles);
          setMonitorToggles(mToggles);
          if (data.watches?.length > 0) setExpandedWatch(0);
        }
      } catch (err) {
        console.error('[PresetPicker] Preview error:', err);
      } finally {
        setPreviewLoading(false);
      }
    };
    fetchPreview();
  }, [step, selectedAnchor, selectedPreset, stackId]);

  // Toggle watch
  const toggleWatch = (watchIndex: number) => {
    const newEnabled = !watchToggles[watchIndex];
    setWatchToggles((prev) => ({ ...prev, [watchIndex]: newEnabled }));
    // Toggle all monitors in this watch
    if (preview?.watches[watchIndex]) {
      const newMonitorToggles = { ...monitorToggles };
      preview.watches[watchIndex].scopeResult.recommendations.forEach((_: any, ri: number) => {
        newMonitorToggles[`${watchIndex}:${ri}`] = newEnabled;
      });
      setMonitorToggles(newMonitorToggles);
    }
  };

  // Toggle individual monitor
  const toggleMonitor = (watchIndex: number, monitorIndex: number) => {
    const key = `${watchIndex}:${monitorIndex}`;
    setMonitorToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Submit
  const handleSubmit = async () => {
    if (!preview || creating) return;
    setCreating(true);

    try {
      // Build watches array from preview + toggles
      const watches = preview.watches
        .map((w, wi) => {
          if (!watchToggles[wi]) return null;

          const enabledMonitors = w.scopeResult.recommendations
            .filter((_: any, ri: number) => monitorToggles[`${wi}:${ri}`])
            .map((rec: any) => ({
              name: `${rec.monitor_key} — ${(rec.target_fqn || '').split('.').pop()}`,
              monitorType: rec.monitor_key,
              targetFqn: rec.target_fqn,
              config: rec.config_hints || {},
              depth: rec.source === 'direct' ? 0 : 1,
              priority: rec.priority,
            }));

          if (!enabledMonitors.length) return null;

          return {
            name: `${WATCH_TYPE_LABELS[w.watchType as keyof typeof WATCH_TYPE_LABELS] || w.watchType}: ${w.anchorName}`,
            watchType: w.watchType,
            anchorFqn: w.anchorFqn,
            anchorNodeId: w.anchorNodeId,
            anchorNodeType: w.anchorNodeType,
            anchorPlatform: w.anchorPlatform,
            anchorName: w.anchorName,
            monitors: enabledMonitors,
          };
        })
        .filter(Boolean);

      const res = await fetch('/api/schedule/presets/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          presetKey: selectedPreset === 'smart_build' ? 'smart_build' : selectedPreset,
          watches,
          schedule,
          timezone,
          alertChannels,
          alertOnStatus,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        const watchIds = (data.watches || []).map((w: any) => w.id);
        onComplete(watchIds);
        onClose();
      } else {
        const err = await res.json();
        console.error('[PresetPicker] Apply error:', err);
      }
    } catch (err) {
      console.error('[PresetPicker] Submit error:', err);
    } finally {
      setCreating(false);
    }
  };

  if (!open) return null;

  // Compute totals from toggles
  const enabledWatchCount = Object.values(watchToggles).filter(Boolean).length;
  const enabledMonitorCount = Object.values(monitorToggles).filter(Boolean).length;

  const totalSteps = 3;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-[680px] max-h-[85vh] bg-[var(--surface)] border border-[var(--subtle-border)] rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div>
            <h2 className="text-[16px] font-semibold text-[var(--text)]">Protect Pipeline</h2>
            <p className="text-[12px] text-[var(--muted)] mt-0.5">
              {step === 1 && 'Choose a protection strategy'}
              {step === 2 && 'Review monitors'}
              {step === 3 && 'Schedule & create'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex gap-1 px-6 pt-3">
          {Array.from({ length: totalSteps }, (_, i) => (
            <div
              key={i}
              className={cn(
                'flex-1 h-1 rounded-full transition-colors',
                i + 1 <= step ? 'bg-blue-500' : 'bg-[var(--overlay-bg)]'
              )}
            />
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">

          {/* Step 1: Choose Preset */}
          {step === 1 && (
            <div className="space-y-3">
              {/* Pipeline info bar */}
              {anchorLoading ? (
                <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--overlay-bg)] mb-3">
                  <div className="w-3 h-3 red-spinner" />
                  <span className="text-[11px] text-[var(--muted)]">Detecting pipeline...</span>
                </div>
              ) : selectedAnchor ? (
                <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--overlay-bg)] mb-3">
                  <svg className="w-3.5 h-3.5 text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                  <span className="text-[11px] text-[var(--text-faint)]">Full pipeline</span>
                  {totalNodes > 0 && (
                    <span className="text-[10px] text-[var(--muted)] ml-auto">{totalNodes} assets</span>
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 mb-3">
                  <svg className="w-3.5 h-3.5 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  <span className="text-[11px] text-amber-400">No lineage graph found. Build your lineage first.</span>
                </div>
              )}

              {presets.map((preset) => (
                <button
                  key={preset.key}
                  onClick={() => setSelectedPreset(preset.key)}
                  disabled={!preset.eligible}
                  className={cn(
                    'w-full text-left p-4 rounded-lg border transition-colors',
                    !preset.eligible && 'opacity-40 cursor-not-allowed',
                    selectedPreset === preset.key
                      ? 'border-blue-500/40 bg-blue-500/5'
                      : 'border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] bg-[var(--surface)]',
                  )}
                >
                  <div className="flex items-start gap-3">
                    <svg className="w-5 h-5 text-[var(--muted)] shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={PRESET_ICONS[preset.key]} />
                    </svg>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-medium text-[var(--text)]">{preset.label}</span>
                        <span className="text-[10px] text-[var(--text-faint)] bg-[var(--overlay-bg)] px-1.5 py-0.5 rounded">
                          {preset.estimatedWatches} watch{preset.estimatedWatches === '1' ? '' : 'es'}
                        </span>
                        <span className="text-[10px] text-[var(--text-faint)] bg-[var(--overlay-bg)] px-1.5 py-0.5 rounded">
                          {preset.estimatedMonitors} monitors
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--muted)] mt-1">{preset.description}</p>
                    </div>
                  </div>
                </button>
              ))}

              {/* Smart Build option */}
              <button
                onClick={() => setSelectedPreset('smart_build')}
                className={cn(
                  'w-full text-left p-4 rounded-lg border transition-colors',
                  selectedPreset === 'smart_build'
                    ? 'border-blue-500/40 bg-blue-500/5'
                    : 'border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] bg-[var(--surface)]',
                )}
              >
                <div className="flex items-start gap-3">
                  <svg className="w-5 h-5 text-[var(--muted)] shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-[var(--text)]">Smart Build</span>
                      <span className="text-[10px] text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded">auto</span>
                    </div>
                    <p className="text-[11px] text-[var(--muted)] mt-1">
                      Automatically analyze your pipeline and create the optimal set of watches based on the upstream graph shape.
                    </p>
                  </div>
                </div>
              </button>
            </div>
          )}

          {/* Step 2: Preview */}
          {step === 2 && (
            <div className="space-y-4">
              {previewLoading ? (
                <div className="flex items-center justify-center py-16">
                  <div className="w-5 h-5 red-spinner" />
                  <span className="text-[12px] text-[var(--muted)] ml-2">Analyzing pipeline...</span>
                </div>
              ) : !preview?.watches?.length ? (
                <div className="text-center py-16">
                  <p className="text-[13px] text-[var(--muted)]">No monitors could be generated.</p>
                  {preview?.warnings?.map((w, i) => (
                    <p key={i} className="text-[11px] text-amber-400 mt-1">{w}</p>
                  ))}
                  <p className="text-[11px] text-[var(--text-faint)] mt-2">Try a different asset or preset.</p>
                </div>
              ) : (
                <>
                  {/* Summary bar */}
                  <div className="flex items-center gap-4 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                    <div className="text-center">
                      <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">{enabledWatchCount}</p>
                      <p className="text-[10px] text-[var(--muted)] uppercase">Watches</p>
                    </div>
                    <div className="w-px h-8 bg-[var(--subtle-border)]" />
                    <div className="text-center">
                      <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">{enabledMonitorCount}</p>
                      <p className="text-[10px] text-[var(--muted)] uppercase">Monitors</p>
                    </div>
                    <div className="w-px h-8 bg-[var(--subtle-border)]" />
                    <div className="text-center">
                      <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">{preview.totalNodes}</p>
                      <p className="text-[10px] text-[var(--muted)] uppercase">Assets</p>
                    </div>
                    {preview.deduplicatedCount > 0 && (
                      <>
                        <div className="w-px h-8 bg-[var(--subtle-border)]" />
                        <div className="text-center">
                          <p className="text-[18px] font-bold text-emerald-400 tabular-nums">{preview.deduplicatedCount}</p>
                          <p className="text-[10px] text-[var(--muted)] uppercase">Deduped</p>
                        </div>
                      </>
                    )}
                  </div>

                  {/* Warnings */}
                  {preview.warnings?.map((w, i) => (
                    <div key={i} className="flex items-center gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                      <svg className="w-4 h-4 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                      <span className="text-[11px] text-amber-400">{w}</span>
                    </div>
                  ))}

                  {/* Watch accordions */}
                  {preview.watches.map((watch, wi) => (
                    <div key={wi} className="rounded-lg border border-[var(--subtle-border)] overflow-hidden">
                      {/* Watch header */}
                      <div
                        className={cn(
                          'flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors',
                          watchToggles[wi] ? 'bg-[var(--surface)]' : 'bg-[var(--overlay-bg)] opacity-50',
                        )}
                        onClick={() => setExpandedWatch(expandedWatch === wi ? null : wi)}
                      >
                        {/* Watch toggle */}
                        <div
                          onClick={(e) => { e.stopPropagation(); toggleWatch(wi); }}
                          className={cn(
                            'w-4 h-4 rounded border flex items-center justify-center shrink-0 cursor-pointer',
                            watchToggles[wi]
                              ? 'bg-blue-500 border-blue-500'
                              : 'border-[var(--overlay-strong)] bg-transparent',
                          )}
                        >
                          {watchToggles[wi] && (
                            <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </div>

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-[12px] font-medium text-[var(--text)]">
                              {WATCH_TYPE_LABELS[watch.watchType as keyof typeof WATCH_TYPE_LABELS] || watch.watchType}
                            </span>
                            <span className="text-[10px] text-[var(--text-faint)]">
                              {watch.anchorName}
                            </span>
                          </div>
                          <div className="flex items-center gap-3 mt-0.5">
                            <span className="text-[10px] text-[var(--muted)]">
                              {watch.scopeResult.recommendations.filter((_: any, ri: number) => monitorToggles[`${wi}:${ri}`]).length} monitors
                            </span>
                            <span className="text-[10px] text-[var(--muted)]">
                              {Math.round(watch.coveragePct * 100)}% coverage
                            </span>
                          </div>
                        </div>

                        <svg
                          className={cn('w-4 h-4 text-[var(--muted)] transition-transform', expandedWatch === wi && 'rotate-180')}
                          fill="none" stroke="currentColor" viewBox="0 0 24 24"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>

                      {/* Expanded monitor list */}
                      {expandedWatch === wi && watchToggles[wi] && (
                        <div className="border-t border-[var(--subtle-border)]">
                          {watch.scopeResult.recommendations.map((rec: any, ri: number) => {
                            const key = `${wi}:${ri}`;
                            const enabled = monitorToggles[key];
                            return (
                              <div
                                key={ri}
                                onClick={() => toggleMonitor(wi, ri)}
                                className={cn(
                                  'flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors border-b border-[var(--border-faint)] last:border-b-0',
                                  enabled ? 'bg-[var(--surface)]' : 'bg-[var(--overlay-bg)] opacity-40',
                                )}
                              >
                                <div className={cn(
                                  'w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0',
                                  enabled ? 'bg-blue-500 border-blue-500' : 'border-[var(--overlay-strong)] bg-transparent',
                                )}>
                                  {enabled && (
                                    <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                    </svg>
                                  )}
                                </div>

                                <span className={cn(
                                  'px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0',
                                  PRIORITY_COLORS[rec.priority] || PRIORITY_COLORS[3],
                                )}>
                                  P{rec.priority}
                                </span>

                                <div className="flex-1 min-w-0">
                                  <span className="px-1 py-0.5 rounded bg-white/5 text-[10px] uppercase text-[var(--muted)]">
                                    {rec.monitor_key.replace(/_/g, ' ')}
                                  </span>
                                  <p className="text-[11px] text-[var(--muted)] mt-0.5 truncate">
                                    {rec.target_fqn}
                                  </p>
                                </div>

                                {rec.already_monitored && (
                                  <span className="text-[9px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded shrink-0">
                                    exists
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  ))}
                </>
              )}
            </div>
          )}

          {/* Step 3: Schedule + Create */}
          {step === 3 && (
            <div className="space-y-4">
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  How often should these watches run?
                </label>
                <ScheduleInput value={schedule} onChange={setSchedule} />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Timezone</label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)]"
                >
                  <option value="UTC">UTC</option>
                  <option value="America/New_York">Eastern (US)</option>
                  <option value="America/Chicago">Central (US)</option>
                  <option value="America/Denver">Mountain (US)</option>
                  <option value="America/Los_Angeles">Pacific (US)</option>
                  <option value="Europe/London">London</option>
                  <option value="Europe/Berlin">Berlin</option>
                  <option value="Asia/Tokyo">Tokyo</option>
                  <option value="Asia/Shanghai">Shanghai</option>
                  <option value="Australia/Sydney">Sydney</option>
                </select>
              </div>

              <AlertChannelPicker
                channels={alertChannels}
                onChannelsChange={setAlertChannels}
                alertOnStatus={alertOnStatus}
                onAlertOnStatusChange={setAlertOnStatus}
              />

              {/* Summary */}
              <div className="p-4 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)]">
                <p className="text-[12px] font-medium text-[var(--muted)] mb-2">Summary</p>
                <div className="grid grid-cols-2 gap-3 text-[12px]">
                  <div>
                    <span className="text-[var(--text-faint)]">Preset: </span>
                    <span className="text-[var(--text-secondary)]">
                      {selectedPreset === 'smart_build' ? 'Smart Build' : presets.find((p) => p.key === selectedPreset)?.label || selectedPreset}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-faint)]">Watches: </span>
                    <span className="text-[var(--text-secondary)]">{enabledWatchCount}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-faint)]">Monitors: </span>
                    <span className="text-[var(--text-secondary)]">{enabledMonitorCount}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-faint)]">Schedule: </span>
                    <span className="text-[var(--text-secondary)]">{schedule || 'None'}</span>
                  </div>
                </div>
                {selectedAnchor && (
                  <div className="mt-2 pt-2 border-t border-[var(--border-faint)]">
                    <span className="text-[11px] text-[var(--text-faint)]">Anchor: </span>
                    <span className="text-[11px] text-[var(--text-secondary)] font-mono">{selectedAnchor.fqn}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--subtle-border)]">
          <div>
            {step > 1 && (
              <Button variant="ghost" size="sm" onClick={() => setStep((s) => s - 1)}>
                Back
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            {step < 3 ? (
              <Button
                size="sm"
                disabled={
                  (step === 1 && (!selectedPreset || !selectedAnchor || anchorLoading)) ||
                  (step === 2 && enabledMonitorCount === 0)
                }
                onClick={() => setStep((s) => s + 1)}
              >
                Next
              </Button>
            ) : (
              <Button
                size="sm"
                disabled={enabledMonitorCount === 0 || creating}
                onClick={handleSubmit}
              >
                {creating ? 'Creating...' : `Create ${enabledWatchCount} Bundle Monitor${enabledWatchCount !== 1 ? 's' : ''}`}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
