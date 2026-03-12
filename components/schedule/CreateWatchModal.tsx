'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import {
  type WatchType,
  WATCH_TYPE_LABELS,
  WATCH_TYPE_DESCRIPTIONS,
  DEFAULT_SCOPE_CONFIGS,
  type ScopeConfig,
} from '@/types/health-watch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WatchPrefillData {
  anchorFqn: string;
  anchorNodeId?: string;
  anchorNodeType?: string;
  anchorPlatform?: string;
  watchType?: WatchType;
  monitors?: Array<{
    name: string;
    monitorType: string;
    targetFqn: string;
    config?: Record<string, any>;
  }>;
}

interface CreateWatchModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (watchData: any) => void;
  prefillData?: WatchPrefillData | null;
  stackId?: string;
}

interface SearchResult {
  id: string;
  name: string;
  fqn: string;
  type?: string;
  platform?: string;
  platformDomain?: string;
}

interface ScopeMonitor {
  name: string;
  monitorType: string;
  targetFqn: string;
  priority: number;
  reason: string;
  config?: Record<string, any>;
  checked: boolean;
}

const WATCH_TYPES: WatchType[] = [
  'pipeline_health',
  'dashboard_shield',
  'source_guard',
  'model_quality',
  'custom_watch',
];

const WATCH_TYPE_ICONS: Record<WatchType, string> = {
  pipeline_health: 'M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7',
  dashboard_shield: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
  source_guard: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
  model_quality: 'M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z',
  custom_watch: 'M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4',
};

const PRIORITY_COLORS: Record<number, string> = {
  1: 'bg-red-500/15 text-red-400',
  2: 'bg-amber-500/15 text-amber-400',
  3: 'bg-white/10 text-[var(--muted)]',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CreateWatchModal({ open, onClose, onSubmit, prefillData, stackId }: CreateWatchModalProps) {
  const [step, setStep] = useState(1);

  // Step 1: Pick asset
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<SearchResult | null>(null);
  const [watchType, setWatchType] = useState<WatchType>('pipeline_health');
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Step 2: Scope & monitors
  const [scopeMonitors, setScopeMonitors] = useState<ScopeMonitor[]>([]);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [coveragePct, setCoveragePct] = useState<number>(0);
  const [scopeNodeCount, setScopeNodeCount] = useState<number>(0);
  const scopeFetchedRef = useRef(false);

  // Step 3: Schedule
  const [schedule, setSchedule] = useState('0 8 * * *');
  const [timezone, setTimezone] = useState('UTC');

  // Step 4: Alerts
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);
  const [watchName, setWatchName] = useState('');

  // Reset when modal opens
  useEffect(() => {
    if (!open) return;

    if (prefillData) {
      setSelectedAsset({
        id: prefillData.anchorNodeId || '',
        name: prefillData.anchorFqn?.split('.').pop() || '',
        fqn: prefillData.anchorFqn,
        type: prefillData.anchorNodeType,
        platform: prefillData.anchorPlatform,
      });
      setWatchType(prefillData.watchType || 'pipeline_health');
      setWatchName(`${WATCH_TYPE_LABELS[prefillData.watchType || 'pipeline_health']}: ${prefillData.anchorFqn?.split('.').pop() || 'Watch'}`);
      if (prefillData.monitors?.length) {
        setScopeMonitors(prefillData.monitors.map((m) => ({
          ...m,
          priority: 2,
          reason: 'Prefilled',
          checked: true,
        })));
        scopeFetchedRef.current = true;
      } else {
        scopeFetchedRef.current = false;
      }
      setStep(prefillData.monitors?.length ? 2 : 1);
    } else {
      setStep(1);
      setSearchQuery('');
      setSearchResults([]);
      setSelectedAsset(null);
      setWatchType('pipeline_health');
      setScopeMonitors([]);
      setCoveragePct(0);
      setScopeNodeCount(0);
      scopeFetchedRef.current = false;
      setSchedule('0 8 * * *');
      setTimezone('UTC');
      setAlertChannels([]);
      setAlertOnStatus(['FAIL', 'WARN', 'ERROR']);
      setWatchName('');
    }
  }, [open, prefillData]);

  // Search for assets
  const handleSearch = useCallback(async (query: string) => {
    setSearchQuery(query);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!query.trim() || !stackId) {
      setSearchResults([]);
      return;
    }
    searchTimerRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await fetch(
          `/api/pipeline/${stackId}/lineage/engine?action=search&q=${encodeURIComponent(query)}`
        );
        if (res.ok) {
          const data = await res.json();
          setSearchResults((data.results || []).slice(0, 15));
        }
      } catch (err) {
        console.error('[CreateWatch] Search error:', err);
      } finally {
        setSearching(false);
      }
    }, 300);
  }, [stackId]);

  // Select asset → auto-detect watch type
  const handleSelectAsset = useCallback(async (asset: SearchResult) => {
    setSelectedAsset(asset);
    setSearchQuery('');
    setSearchResults([]);

    // Auto-detect watch type
    if (stackId && asset.id) {
      try {
        const res = await fetch(
          `/api/pipeline/${stackId}/lineage/engine?action=recommend-monitors&id=${asset.id}&depth=3`
        );
        if (res.ok) {
          const data = await res.json();
          // Infer watch type from node domain
          const domain = asset.platformDomain || data.node?.platformDomain || '';
          const nodeType = asset.type || data.node?.type || '';
          let inferred: WatchType = 'pipeline_health';
          if (['dashboard', 'report', 'workbook', 'question', 'explore'].includes(nodeType) || domain === 'bi') {
            inferred = 'dashboard_shield';
          } else if (domain === 'ingestion') {
            inferred = 'source_guard';
          } else if (domain === 'transform' && nodeType === 'model') {
            inferred = 'model_quality';
          }
          setWatchType(inferred);
          setWatchName(`${WATCH_TYPE_LABELS[inferred]}: ${asset.name}`);
        }
      } catch (err) {
        console.error('[CreateWatch] Type inference error:', err);
        setWatchName(`${WATCH_TYPE_LABELS[watchType]}: ${asset.name}`);
      }
    } else {
      setWatchName(`${WATCH_TYPE_LABELS[watchType]}: ${asset.name}`);
    }
  }, [stackId, watchType]);

  // Fetch scope when entering step 2
  useEffect(() => {
    if (step !== 2 || !selectedAsset || !stackId) return;
    if (scopeFetchedRef.current) return; // Already loaded
    scopeFetchedRef.current = true;

    const fetchScope = async () => {
      setScopeLoading(true);
      try {
        // Fetch recommendations from existing engine endpoint
        const res = await fetch(
          `/api/pipeline/${stackId}/lineage/engine?action=recommend-monitors&id=${selectedAsset.id}&depth=${DEFAULT_SCOPE_CONFIGS[watchType].maxDepth}`
        );
        if (!res.ok) throw new Error('Failed to fetch scope');
        const data = await res.json();

        const recs = data.recommendations || [];
        const bundles = data.bundles || [];

        // Combine direct + bundle recommendations into scope monitors
        const monitors: ScopeMonitor[] = [];
        const seen = new Set<string>();

        for (const rec of recs) {
          const key = `${rec.monitor_type}:${rec.target_fqn || selectedAsset.fqn}`;
          if (seen.has(key)) continue;
          seen.add(key);
          monitors.push({
            name: rec.name || `${rec.monitor_type.toLowerCase().replace(/_/g, ' ')} — ${(rec.target_fqn || selectedAsset.fqn).split('.').pop()}`,
            monitorType: rec.monitor_type,
            targetFqn: rec.target_fqn || selectedAsset.fqn,
            priority: rec.priority || 2,
            reason: rec.reason || 'Recommended',
            config: rec.config_hints,
            checked: true,
          });
        }

        // Add bundle monitors
        for (const bundle of bundles) {
          for (const mon of bundle.monitors || []) {
            const key = `${mon.monitor_type}:${mon.target_fqn}`;
            if (seen.has(key)) continue;
            seen.add(key);
            monitors.push({
              name: mon.name || `${mon.monitor_type.toLowerCase().replace(/_/g, ' ')} — ${mon.target_fqn.split('.').pop()}`,
              monitorType: mon.monitor_type,
              targetFqn: mon.target_fqn,
              priority: mon.priority || 3,
              reason: mon.reason || `From ${bundle.label || 'bundle'}`,
              config: mon.config_hints,
              checked: true,
            });
          }
        }

        // Cap monitors by watch type config
        const maxMonitors = DEFAULT_SCOPE_CONFIGS[watchType].maxMonitors;
        // Sort by priority (lower = more important)
        monitors.sort((a, b) => a.priority - b.priority);

        setScopeMonitors(monitors.slice(0, maxMonitors));
        setScopeNodeCount(new Set(monitors.map((m) => m.targetFqn)).size);

        // Approximate coverage
        const upstreamCount = data.upstream_count || monitors.length;
        setCoveragePct(upstreamCount > 0 ? Math.min(monitors.length / upstreamCount, 1.0) : 1.0);
      } catch (err) {
        console.error('[CreateWatch] Scope fetch error:', err);
      } finally {
        setScopeLoading(false);
      }
    };

    fetchScope();
  }, [step, selectedAsset, stackId, watchType]);

  // Toggle monitor in scope
  const toggleMonitor = (index: number) => {
    setScopeMonitors((prev) =>
      prev.map((m, i) => (i === index ? { ...m, checked: !m.checked } : m))
    );
  };

  // Submit
  const handleSubmit = () => {
    const checkedMonitors = scopeMonitors.filter((m) => m.checked);
    onSubmit({
      name: watchName || `${WATCH_TYPE_LABELS[watchType]}: ${selectedAsset?.name || 'Watch'}`,
      watchType,
      anchorFqn: selectedAsset?.fqn || '',
      anchorNodeId: selectedAsset?.id || '',
      anchorNodeType: selectedAsset?.type || '',
      anchorPlatform: selectedAsset?.platform || '',
      scopeConfig: DEFAULT_SCOPE_CONFIGS[watchType],
      schedule,
      timezone,
      alertChannels,
      alertOnStatus,
      monitors: checkedMonitors.map((m) => ({
        name: m.name,
        monitorType: m.monitorType,
        targetFqn: m.targetFqn,
        config: m.config,
      })),
    });
    onClose();
  };

  if (!open) return null;

  const checkedCount = scopeMonitors.filter((m) => m.checked).length;
  const canProceedStep1 = !!selectedAsset;
  const canProceedStep2 = checkedCount > 0;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-[640px] max-h-[85vh] bg-[var(--surface)] border border-[var(--subtle-border)] rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--subtle-border)]">
          <div>
            <h2 className="text-[16px] font-semibold text-[var(--text)]">Create Health Watch</h2>
            <p className="text-[12px] text-[var(--muted)] mt-0.5">
              Step {step} of 4
              {step === 1 && ' — Pick your asset'}
              {step === 2 && ' — Review scope & monitors'}
              {step === 3 && ' — Schedule'}
              {step === 4 && ' — Alerts & confirm'}
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
          {[1, 2, 3, 4].map((s) => (
            <div
              key={s}
              className={cn(
                'flex-1 h-1 rounded-full transition-colors',
                s <= step ? 'bg-blue-500' : 'bg-[var(--overlay-bg)]'
              )}
            />
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {/* Step 1: Pick Asset */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  Search for an asset to protect
                </label>
                <input
                  type="text"
                  value={selectedAsset ? selectedAsset.name : searchQuery}
                  onChange={(e) => {
                    if (selectedAsset) {
                      setSelectedAsset(null);
                      setWatchName('');
                    }
                    handleSearch(e.target.value);
                  }}
                  placeholder="Search tables, dashboards, models, connectors..."
                  className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2.5 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-blue-500/50"
                  autoFocus
                />
                {/* Search results */}
                {searchResults.length > 0 && !selectedAsset && (
                  <div className="mt-1 max-h-[200px] overflow-y-auto border border-[var(--subtle-border)] rounded-lg bg-[var(--surface)]">
                    {searchResults.map((r) => (
                      <button
                        key={r.id}
                        onClick={() => handleSelectAsset(r)}
                        className="w-full text-left px-3 py-2 hover:bg-[var(--hover-bg)] transition-colors border-b border-[var(--border-faint)] last:border-b-0"
                      >
                        <p className="text-[13px] text-[var(--text)]">{r.name}</p>
                        <p className="text-[11px] text-[var(--muted)] font-mono truncate">{r.fqn}</p>
                      </button>
                    ))}
                  </div>
                )}
                {searching && (
                  <p className="text-[11px] text-[var(--muted)] mt-1">Searching...</p>
                )}
              </div>

              {/* Selected asset summary */}
              {selectedAsset && (
                <div className="p-3 rounded-lg border border-blue-500/20 bg-blue-500/5">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-[13px] font-medium text-[var(--text)]">{selectedAsset.name}</p>
                      <p className="text-[11px] text-[var(--muted)] font-mono">{selectedAsset.fqn}</p>
                    </div>
                    <button
                      onClick={() => { setSelectedAsset(null); setWatchName(''); }}
                      className="text-[var(--muted)] hover:text-[var(--text)]"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>
              )}

              {/* Watch type selection */}
              {selectedAsset && (
                <div>
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                    Watch type
                  </label>
                  <div className="grid grid-cols-1 gap-2">
                    {WATCH_TYPES.map((wt) => (
                      <button
                        key={wt}
                        onClick={() => {
                          setWatchType(wt);
                          setWatchName(`${WATCH_TYPE_LABELS[wt]}: ${selectedAsset.name}`);
                          setScopeMonitors([]); // Reset scope when type changes
                          scopeFetchedRef.current = false;
                        }}
                        className={cn(
                          'text-left p-3 rounded-lg border transition-colors',
                          wt === watchType
                            ? 'border-blue-500/40 bg-blue-500/5'
                            : 'border-[var(--subtle-border)] hover:border-[var(--overlay-strong)] bg-[var(--surface)]'
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <svg className="w-4 h-4 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={WATCH_TYPE_ICONS[wt]} />
                          </svg>
                          <span className="text-[13px] font-medium text-[var(--text)]">
                            {WATCH_TYPE_LABELS[wt]}
                          </span>
                        </div>
                        <p className="text-[11px] text-[var(--muted)] mt-1 ml-6">
                          {WATCH_TYPE_DESCRIPTIONS[wt]}
                        </p>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Step 2: Review Scope & Monitors */}
          {step === 2 && (
            <div className="space-y-4">
              {/* Scope summary */}
              <div className="flex items-center gap-4 p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
                <div className="text-center">
                  <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">{checkedCount}</p>
                  <p className="text-[10px] text-[var(--muted)] uppercase">Monitors</p>
                </div>
                <div className="w-px h-8 bg-[var(--subtle-border)]" />
                <div className="text-center">
                  <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">{scopeNodeCount}</p>
                  <p className="text-[10px] text-[var(--muted)] uppercase">Assets</p>
                </div>
                <div className="w-px h-8 bg-[var(--subtle-border)]" />
                <div className="text-center">
                  <p className="text-[18px] font-bold text-[var(--text)] tabular-nums">
                    {Math.round(coveragePct * 100)}%
                  </p>
                  <p className="text-[10px] text-[var(--muted)] uppercase">Coverage</p>
                </div>
                <div className="flex-1" />
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setScopeMonitors((prev) => prev.map((m) => ({ ...m, checked: true })))}
                    className="text-[11px] text-blue-400 hover:text-blue-300"
                  >
                    All
                  </button>
                  <span className="text-[var(--text-faint)]">|</span>
                  <button
                    onClick={() => setScopeMonitors((prev) => prev.map((m) => ({ ...m, checked: false })))}
                    className="text-[11px] text-[var(--muted)] hover:text-[var(--text)]"
                  >
                    None
                  </button>
                </div>
              </div>

              {/* Monitor list */}
              {scopeLoading ? (
                <div className="flex items-center justify-center py-10">
                  <div className="w-5 h-5 red-spinner" />
                  <span className="text-[12px] text-[var(--muted)] ml-2">Analyzing scope...</span>
                </div>
              ) : scopeMonitors.length === 0 ? (
                <div className="text-center py-10">
                  <p className="text-[13px] text-[var(--muted)]">No monitors recommended for this asset.</p>
                  <p className="text-[11px] text-[var(--text-faint)] mt-1">Try a different watch type or asset.</p>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {scopeMonitors.map((mon, i) => (
                    <div
                      key={i}
                      onClick={() => toggleMonitor(i)}
                      className={cn(
                        'flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                        mon.checked
                          ? 'border-[var(--subtle-border)] bg-[var(--surface)]'
                          : 'border-transparent bg-[var(--overlay-bg)] opacity-50'
                      )}
                    >
                      {/* Checkbox */}
                      <div className={cn(
                        'w-4 h-4 rounded border flex items-center justify-center shrink-0',
                        mon.checked
                          ? 'bg-blue-500 border-blue-500'
                          : 'border-[var(--overlay-strong)] bg-transparent'
                      )}>
                        {mon.checked && (
                          <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </div>

                      {/* Priority badge */}
                      <span className={cn(
                        'px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0',
                        PRIORITY_COLORS[mon.priority] || PRIORITY_COLORS[3]
                      )}>
                        P{mon.priority}
                      </span>

                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="px-1 py-0.5 rounded bg-white/5 text-[10px] uppercase text-[var(--muted)]">
                            {mon.monitorType.replace(/_/g, ' ')}
                          </span>
                        </div>
                        <p className="text-[11px] text-[var(--muted)] mt-0.5 truncate">
                          {mon.targetFqn}
                          {mon.reason && ` — ${mon.reason}`}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Step 3: Schedule */}
          {step === 3 && (
            <div className="space-y-4">
              <div>
                <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">
                  How often should this watch run?
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
            </div>
          )}

          {/* Step 4: Alerts & Confirm */}
          {step === 4 && (
            <div className="space-y-4">
              <AlertChannelPicker
                channels={alertChannels}
                onChannelsChange={setAlertChannels}
                alertOnStatus={alertOnStatus}
                onAlertOnStatusChange={setAlertOnStatus}
              />

              {/* Summary card */}
              <div className="p-4 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)]">
                <div className="mb-3">
                  <label className="block text-[12px] font-medium text-[var(--muted)] mb-1.5">
                    Watch name
                  </label>
                  <input
                    type="text"
                    value={watchName}
                    onChange={(e) => setWatchName(e.target.value)}
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3 text-[12px]">
                  <div>
                    <span className="text-[var(--text-faint)]">Type: </span>
                    <span className="text-[var(--text-secondary)]">{WATCH_TYPE_LABELS[watchType]}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-faint)]">Monitors: </span>
                    <span className="text-[var(--text-secondary)]">{checkedCount}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-faint)]">Schedule: </span>
                    <span className="text-[var(--text-secondary)]">{schedule || 'None'}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-faint)]">Coverage: </span>
                    <span className="text-[var(--text-secondary)]">{Math.round(coveragePct * 100)}%</span>
                  </div>
                </div>
                {selectedAsset && (
                  <div className="mt-2 pt-2 border-t border-[var(--border-faint)]">
                    <span className="text-[11px] text-[var(--text-faint)]">Anchor: </span>
                    <span className="text-[11px] text-[var(--text-secondary)] font-mono">{selectedAsset.fqn}</span>
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
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setStep((s) => s - 1)}
              >
                Back
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            {step < 4 ? (
              <Button
                size="sm"
                disabled={step === 1 ? !canProceedStep1 : step === 2 ? !canProceedStep2 : false}
                onClick={() => setStep((s) => s + 1)}
              >
                Next
              </Button>
            ) : (
              <Button
                size="sm"
                disabled={!checkedCount}
                onClick={handleSubmit}
              >
                Create Health Watch
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
