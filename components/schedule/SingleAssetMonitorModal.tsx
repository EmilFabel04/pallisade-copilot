'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { cn } from '@/lib/utils';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AssetPrefill {
  nodeId: string;
  fqn: string;
  name: string;
  platform?: string;
}

export interface SingleAssetMonitorModalProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
  stackId?: string;
  prefill?: AssetPrefill | null;
}

interface MonitorRecommendation {
  monitor_key: string;
  target_fqn: string;
  source: string;
  priority: number;
  reason: string;
  already_monitored: boolean;
  config_hints?: Record<string, any>;
}

type Step = 1 | 2 | 3 | 4;

const STEP_LABELS: Record<Step, string> = {
  1: 'Pick Asset',
  2: 'Select Monitors',
  3: 'Schedule',
  4: 'Create',
};

// ---------------------------------------------------------------------------
// Monitor type labels
// ---------------------------------------------------------------------------

const MONITOR_TYPE_LABELS: Record<string, string> = {
  FRESHNESS: 'Freshness',
  VOLUME: 'Volume',
  SCHEMA_CHANGE: 'Schema Change',
  NULL_RATE: 'Null Rate',
  UNIQUENESS: 'Uniqueness',
  DISTRIBUTION: 'Distribution',
  CUSTOM_SQL: 'Custom SQL',
  ANOMALY: 'Anomaly',
  REFERENTIAL: 'Referential Integrity',
  SYNC_LAG: 'Sync Lag',
  FAILED_SYNCS: 'Failed Syncs',
  CONNECTOR_SCHEMA_DRIFT: 'Connector Schema Drift',
  DAG_LAST_RUN: 'DAG Last Run',
  DAG_SCHEDULE_LAG: 'DAG Schedule Lag',
  TASK_FAILURE_RATE: 'Task Failure Rate',
  DBT_TEST_FAILURES: 'dbt Test Failures',
  DBT_MODEL_FRESHNESS: 'dbt Model Freshness',
  DBT_SOURCE_FRESHNESS: 'dbt Source Freshness',
  BI_FRESHNESS_PROXY: 'BI Freshness',
  BI_UPSTREAM_BREAK_RISK: 'BI Upstream Risk',
  BI_CONTENT_HEALTH: 'BI Content Health',
  BI_REFRESH_FAILURE: 'BI Refresh Failure',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SingleAssetMonitorModal({
  open,
  onClose,
  onComplete,
  stackId,
  prefill,
}: SingleAssetMonitorModalProps) {
  const [step, setStep] = useState<Step>(prefill ? 2 : 1);

  // Step 1: Asset search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<AssetPrefill[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<AssetPrefill | null>(
    prefill || null,
  );

  // Step 2: Monitor selection
  const [recommendations, setRecommendations] = useState<MonitorRecommendation[]>([]);
  const [selectedMonitors, setSelectedMonitors] = useState<Set<string>>(new Set());
  const [recsLoading, setRecsLoading] = useState(false);

  // Step 3: Schedule
  const [schedule, setSchedule] = useState('0 */6 * * *');
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  );

  // Step 4: Alerts & Create
  const [alertChannels, setAlertChannels] = useState<string[]>([]);
  const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);
  const [watchName, setWatchName] = useState('');
  const [creating, setCreating] = useState(false);

  // Reset on open
  useEffect(() => {
    if (open) {
      const asset = prefill || null;
      setSelectedAsset(asset);
      setStep(asset ? 2 : 1);
      setSearchQuery('');
      setSearchResults([]);
      setRecommendations([]);
      setSelectedMonitors(new Set());
      setWatchName(asset ? `Monitors — ${asset.name}` : '');
      setCreating(false);
    }
  }, [open, prefill]);

  // Fetch recommendations when asset is selected and entering step 2
  const fetchRecommendations = useCallback(async () => {
    if (!stackId || !selectedAsset) return;
    setRecsLoading(true);
    try {
      const params = new URLSearchParams({
        action: 'recommend-monitors',
        id: selectedAsset.nodeId,
      });
      const res = await fetch(
        `/api/pipeline/${stackId}/lineage/engine?${params}`,
      );
      if (res.ok) {
        const data = await res.json();
        const recs: MonitorRecommendation[] = data.recommendations || [];
        setRecommendations(recs);
        // Pre-select non-already-monitored recommendations
        const preSelected = new Set<string>();
        recs.forEach((rec, i) => {
          if (!rec.already_monitored) {
            preSelected.add(`${i}`);
          }
        });
        setSelectedMonitors(preSelected);
      }
    } catch (err) {
      console.error('[SingleAssetMonitor] recommendations error:', err);
    } finally {
      setRecsLoading(false);
    }
  }, [stackId, selectedAsset]);

  // Search assets
  const handleSearch = useCallback(async () => {
    if (!stackId || !searchQuery.trim()) return;
    setSearchLoading(true);
    try {
      const params = new URLSearchParams({
        action: 'search',
        q: searchQuery,
      });
      const res = await fetch(
        `/api/pipeline/${stackId}/lineage/engine?${params}`,
      );
      if (res.ok) {
        const data = await res.json();
        const results: AssetPrefill[] = (data.results || []).map((r: any) => ({
          nodeId: r.id,
          fqn: r.fqn || r.name,
          name: r.name,
          platform: r.platform,
        }));
        setSearchResults(results);
      }
    } catch (err) {
      console.error('[SingleAssetMonitor] search error:', err);
    } finally {
      setSearchLoading(false);
    }
  }, [stackId, searchQuery]);

  // Step navigation
  const goToStep = useCallback(
    (target: Step) => {
      if (target === 2) fetchRecommendations();
      setStep(target);
    },
    [fetchRecommendations],
  );

  const canGoNext = useMemo(() => {
    switch (step) {
      case 1: return selectedAsset !== null;
      case 2: return selectedMonitors.size > 0;
      case 3: return schedule.trim().length > 0;
      case 4: return watchName.trim().length > 0;
      default: return false;
    }
  }, [step, selectedAsset, selectedMonitors, schedule, watchName]);

  // Toggle monitor
  const toggleMonitor = useCallback((key: string) => {
    setSelectedMonitors((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Create watch
  const handleCreate = useCallback(async () => {
    if (!stackId || !selectedAsset) return;
    setCreating(true);
    try {
      const monitors = recommendations
        .filter((_, i) => selectedMonitors.has(`${i}`))
        .map((rec) => ({
          name: `${rec.monitor_key} — ${rec.target_fqn}`,
          monitorType: rec.monitor_key,
          targetFqn: rec.target_fqn,
          config: rec.config_hints || {},
          priority: rec.priority,
        }));

      const res = await fetch('/api/schedule/watches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: watchName,
          watchType: 'custom_watch',
          anchorFqn: selectedAsset.fqn,
          anchorNodeId: selectedAsset.nodeId,
          schedule,
          timezone,
          alertChannels,
          alertOnStatus,
          monitors,
        }),
      });

      if (res.ok) {
        onComplete();
        onClose();
      } else {
        const err = await res.json();
        console.error('[SingleAssetMonitor] create error:', err);
      }
    } catch (err) {
      console.error('[SingleAssetMonitor] create error:', err);
    } finally {
      setCreating(false);
    }
  }, [
    stackId, selectedAsset, recommendations, selectedMonitors,
    watchName, schedule, timezone, alertChannels, alertOnStatus,
    onComplete, onClose,
  ]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-[640px] max-h-[85vh] bg-[var(--bg)] border border-[var(--border)] rounded-xl shadow-2xl flex flex-col overflow-hidden">
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-4">
            <h2 className="text-[16px] font-semibold text-[var(--text)]">
              Single Asset Monitor
            </h2>
            <div className="flex items-center gap-1">
              {([1, 2, 3, 4] as Step[]).map((s) => (
                <span
                  key={s}
                  className={cn(
                    'w-2 h-2 rounded-full',
                    s === step ? 'bg-[var(--accent)]' : s < step ? 'bg-[var(--accent)]/40' : 'bg-[var(--muted)]/20',
                  )}
                />
              ))}
            </div>
          </div>
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
        <div className="flex-1 overflow-y-auto p-6">
          {/* Step 1: Pick Asset */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Pick an Asset
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Search for the asset you want to monitor.
                </p>
              </div>

              {/* Search */}
              <div className="flex gap-2">
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  placeholder="Search by name or FQN..."
                  className="flex-1 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] placeholder:text-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)]"
                />
                <button
                  onClick={handleSearch}
                  disabled={!searchQuery.trim() || searchLoading}
                  className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-[13px] font-medium disabled:opacity-40"
                >
                  {searchLoading ? '...' : 'Search'}
                </button>
              </div>

              {/* Results */}
              {searchResults.length > 0 && (
                <div className="space-y-1 max-h-[300px] overflow-y-auto">
                  {searchResults.map((asset) => (
                    <button
                      key={asset.nodeId}
                      onClick={() => {
                        setSelectedAsset(asset);
                        setWatchName(`Monitors — ${asset.name}`);
                      }}
                      className={cn(
                        'w-full text-left px-3 py-2.5 rounded-lg border transition-colors',
                        selectedAsset?.nodeId === asset.nodeId
                          ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                          : 'border-[var(--border)] hover:border-[var(--accent)] bg-[var(--surface)]',
                      )}
                    >
                      <p className="text-[13px] font-medium text-[var(--text)]">
                        {asset.name}
                      </p>
                      <p className="text-[11px] text-[var(--muted)] font-mono truncate">
                        {asset.fqn}
                      </p>
                      {asset.platform && (
                        <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] bg-[var(--muted)]/10 text-[var(--muted)]">
                          {asset.platform}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}

              {/* Selected asset indicator */}
              {selectedAsset && (
                <div className="rounded-lg border border-[var(--accent)]/30 bg-[var(--accent)]/5 p-3">
                  <p className="text-[12px] text-[var(--muted)]">Selected asset:</p>
                  <p className="text-[13px] font-medium text-[var(--text)] mt-0.5">
                    {selectedAsset.name}
                  </p>
                  <p className="text-[11px] text-[var(--muted)] font-mono">
                    {selectedAsset.fqn}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Step 2: Select Monitors */}
          {step === 2 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Select Monitors
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Choose which monitors to create for{' '}
                  <span className="font-medium text-[var(--text)]">
                    {selectedAsset?.name}
                  </span>
                </p>
              </div>

              {recsLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="p-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] animate-pulse">
                      <div className="flex gap-3">
                        <div className="w-4 h-4 rounded bg-[var(--muted)]/20 shrink-0" />
                        <div className="flex-1 space-y-1.5">
                          <div className="h-3 w-32 rounded bg-[var(--muted)]/20" />
                          <div className="h-2.5 w-48 rounded bg-[var(--muted)]/15" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : recommendations.length === 0 ? (
                <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-center">
                  <p className="text-[13px] text-[var(--muted)]">
                    No monitor recommendations found for this asset.
                  </p>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {recommendations.map((rec, idx) => {
                    const key = `${idx}`;
                    const isSelected = selectedMonitors.has(key);
                    const disabled = rec.already_monitored;

                    return (
                      <label
                        key={key}
                        className={cn(
                          'flex items-start gap-3 p-3 rounded-lg border transition-colors cursor-pointer',
                          disabled && 'opacity-50 cursor-default',
                          isSelected && !disabled
                            ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                            : 'border-[var(--border)] hover:border-[var(--accent)] bg-[var(--surface)]',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected && !disabled}
                          disabled={disabled}
                          onChange={() => !disabled && toggleMonitor(key)}
                          className="accent-[var(--accent)] w-4 h-4 shrink-0 mt-0.5"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-[13px] font-medium text-[var(--text)]">
                              {MONITOR_TYPE_LABELS[rec.monitor_key] || rec.monitor_key}
                            </span>
                            {disabled && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/15 text-amber-400">
                                Already monitored
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-[var(--muted)] mt-0.5">
                            {rec.reason}
                          </p>
                          <p className="text-[10px] text-[var(--muted)] font-mono mt-0.5 truncate">
                            {rec.target_fqn}
                          </p>
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Step 3: Schedule */}
          {step === 3 && (
            <div className="space-y-6">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Schedule
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Set how often these monitors should run.
                </p>
              </div>

              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Frequency
                </label>
                <ScheduleInput value={schedule} onChange={setSchedule} />
              </div>

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
            </div>
          )}

          {/* Step 4: Alerts & Create */}
          {step === 4 && (
            <div className="space-y-6">
              <div>
                <h3 className="text-[14px] font-medium text-[var(--text)]">
                  Alerts & Create
                </h3>
                <p className="text-[12px] text-[var(--muted)] mt-1">
                  Configure alert channels and finalize your monitor group.
                </p>
              </div>

              {/* Name */}
              <div className="space-y-2">
                <label className="text-[12px] font-medium text-[var(--text)]">
                  Monitor Group Name
                </label>
                <input
                  value={watchName}
                  onChange={(e) => setWatchName(e.target.value)}
                  placeholder="e.g. orders_table monitors"
                  className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] text-[13px] placeholder:text-[var(--muted)]/50 focus:outline-none focus:border-[var(--accent)]"
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
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 space-y-1">
                <p className="text-[13px] text-[var(--text)]">
                  <span className="font-medium">{selectedMonitors.size}</span> monitor
                  {selectedMonitors.size !== 1 ? 's' : ''} for{' '}
                  <span className="font-medium">{selectedAsset?.name}</span>
                </p>
                <p className="text-[11px] text-[var(--muted)]">
                  {schedule} ({timezone})
                </p>
              </div>
            </div>
          )}
        </div>

        {/* ---- Footer ---- */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-[var(--border)] bg-[var(--surface)]">
          <button
            onClick={() => (step === 1 || (step === 2 && prefill) ? onClose() : goToStep((step - 1) as Step))}
            className="px-4 py-2 text-[13px] text-[var(--muted)] hover:text-[var(--text)] transition-colors"
          >
            {step === 1 || (step === 2 && prefill) ? 'Cancel' : 'Back'}
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
              {creating ? 'Creating...' : 'Create Monitors'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
