'use client';

import { useState, useEffect, useCallback, useImperativeHandle, forwardRef } from 'react';
import { cn } from '@/lib/utils';
import { ScheduleInput } from './ScheduleInput';
import { AlertChannelPicker } from './AlertChannelPicker';
import { FamilyPicker } from './FamilyPicker';
import { PlanPreview } from './PlanPreview';
import { ManualMonitorPicker, type ManualNode } from './ManualMonitorPicker';
import type {
  PlanScopeType,
  MonitoringPlanMode,
  FamilyEligibility,
  MonitoringPlanPreview,
} from '@/types/health-watch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MultiMonitorFormRef {
  canCreate: () => boolean;
  create: () => void;
}

interface MultiMonitorFormProps {
  stackId?: string;
  prefillScopeType?: PlanScopeType;
  prefillAnchorNodeId?: string;
  prefillAnchorFqn?: string;
  prefillAnchorName?: string;
  onComplete: (planId: string) => void;
  onCanCreateChange?: (canCreate: boolean) => void;
}

const SCOPE_TYPES: { key: PlanScopeType; label: string; description: string }[] = [
  { key: 'pipeline', label: 'Entire Pipeline', description: 'Monitor all assets across your pipeline.' },
  { key: 'stream', label: 'Upstream Stream', description: 'Monitor an asset and its upstream lineage.' },
  { key: 'asset', label: 'Single Asset', description: 'Monitor one asset and its immediate neighbors.' },
  { key: 'tool', label: 'Tool / Platform', description: 'Monitor all assets from a specific tool.' },
];

type SectionKey = 'scope' | 'mode' | 'review' | 'schedule' | 'create';

const SECTIONS: { key: SectionKey; label: string; number: number }[] = [
  { key: 'scope', label: 'Scope', number: 1 },
  { key: 'mode', label: 'Monitor Selection', number: 2 },
  { key: 'review', label: 'Review', number: 3 },
  { key: 'schedule', label: 'Schedule & Alerts', number: 4 },
  { key: 'create', label: 'Plan Details', number: 5 },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const MultiMonitorForm = forwardRef<MultiMonitorFormRef, MultiMonitorFormProps>(
  function MultiMonitorForm({ stackId, prefillScopeType, prefillAnchorNodeId, prefillAnchorFqn, prefillAnchorName, onComplete, onCanCreateChange }, ref) {
    const [expandedSection, setExpandedSection] = useState<SectionKey>('scope');

    // Scope
    const [scopeType, setScopeType] = useState<PlanScopeType>(prefillScopeType || 'pipeline');
    const [anchorNodeId, setAnchorNodeId] = useState(prefillAnchorNodeId || '');
    const [anchorFqn, setAnchorFqn] = useState(prefillAnchorFqn || '');
    const [anchorName, setAnchorName] = useState(prefillAnchorName || '');
    const [anchorSearch, setAnchorSearch] = useState('');
    const [anchorResults, setAnchorResults] = useState<any[]>([]);
    const [anchorSearching, setAnchorSearching] = useState(false);

    // Mode
    const [mode, setMode] = useState<MonitoringPlanMode>('recommended');
    const [selectedFamilies, setSelectedFamilies] = useState<string[]>([]);
    const [familyEligibility, setFamilyEligibility] = useState<FamilyEligibility[]>([]);
    const [familiesLoading, setFamiliesLoading] = useState(false);
    const [manualNodes, setManualNodes] = useState<ManualNode[]>([]);
    const [manualSelections, setManualSelections] = useState<Record<string, string[]>>({});

    // Preview
    const [preview, setPreview] = useState<MonitoringPlanPreview | null>(null);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [monitorToggles, setMonitorToggles] = useState<Record<string, boolean>>({});

    // Schedule
    const [schedule, setSchedule] = useState('0 */6 * * *');
    const [timezone, setTimezone] = useState('UTC');
    const [alertChannels, setAlertChannels] = useState<string[]>([]);
    const [alertOnStatus, setAlertOnStatus] = useState<string[]>(['FAIL', 'WARN', 'ERROR']);

    // Create
    const [planName, setPlanName] = useState('');
    const [planDescription, setPlanDescription] = useState('');
    const [creating, setCreating] = useState(false);

    // Fetch families when mode section opens (re-fetch if scope changed)
    const [lastFetchedScope, setLastFetchedScope] = useState('');
    useEffect(() => {
      if (expandedSection === 'mode' && mode === 'recommended') {
        const scopeKey = `${scopeType}:${anchorNodeId}`;
        if (familyEligibility.length === 0 || lastFetchedScope !== scopeKey) {
          setLastFetchedScope(scopeKey);
          fetchFamilies();
        }
      }
    }, [expandedSection, mode, scopeType, anchorNodeId]);

    // Fetch preview
    useEffect(() => {
      if (expandedSection === 'review') fetchPreview();
    }, [expandedSection]);

    // Auto-generate plan name
    useEffect(() => {
      if (expandedSection === 'create' && !planName) {
        const scopeLabel = SCOPE_TYPES.find((s) => s.key === scopeType)?.label || scopeType;
        const suffix = anchorName ? ` — ${anchorName}` : '';
        setPlanName(`${scopeLabel} Monitoring${suffix}`);
      }
    }, [expandedSection]);

    // Expose imperative API
    useImperativeHandle(ref, () => ({
      canCreate: () => !!planName && !creating,
      create: () => { handleCreate(); },
    }));

    // Notify parent of canCreate changes
    useEffect(() => {
      onCanCreateChange?.(!!planName && !creating);
    }, [planName, creating, onCanCreateChange]);

    // ---------------------------------------------------------------------------
    // API calls
    // ---------------------------------------------------------------------------

    const fetchFamilies = useCallback(async () => {
      setFamiliesLoading(true);
      try {
        const params = new URLSearchParams();
        if (stackId) params.set('stackId', stackId);
        params.set('scopeType', scopeType);
        if (anchorNodeId) params.set('anchorNodeId', anchorNodeId);
        const qs = params.toString() ? `?${params.toString()}` : '';
        const res = await fetch(`/api/schedule/plans/families${qs}`);
        if (res.ok) {
          const data = await res.json();
          setFamilyEligibility(data.families || []);
        }
      } catch (err) {
        console.error('[MultiMonitor] Families fetch error:', err);
      } finally {
        setFamiliesLoading(false);
      }
    }, [stackId]);

    const fetchPreview = useCallback(async () => {
      setPreviewLoading(true);
      try {
        const res = await fetch('/api/schedule/plans/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scopeType,
            scopeConfig: anchorNodeId ? { anchorNodeIds: [anchorNodeId] } : {},
            mode,
            families: mode === 'recommended' ? selectedFamilies : [],
            manualSelections: mode === 'manual' ? manualSelections : {},
            stackId,
          }),
        });
        if (res.ok) {
          const data: MonitoringPlanPreview = await res.json();
          setPreview(data);
          const toggles: Record<string, boolean> = {};
          data.groups.forEach((group, gi) => {
            group.recommendations.forEach((_, mi) => {
              toggles[`${gi}:${mi}`] = !group.recommendations[mi].already_monitored;
            });
          });
          setMonitorToggles(toggles);
        }
      } catch (err) {
        console.error('[MultiMonitor] Preview fetch error:', err);
      } finally {
        setPreviewLoading(false);
      }
    }, [scopeType, anchorNodeId, mode, selectedFamilies, manualSelections, stackId]);

    const searchAnchors = useCallback(async (query: string) => {
      if (!query || query.length < 2) { setAnchorResults([]); return; }
      setAnchorSearching(true);
      try {
        const qs = stackId ? `&stackId=${encodeURIComponent(stackId)}` : '';
        const res = await fetch(`/api/pipeline/lineage/search?q=${encodeURIComponent(query)}${qs}`);
        if (res.ok) {
          const data = await res.json();
          setAnchorResults(data.results || []);
        }
      } catch (err) {
        console.error('[MultiMonitor] Search error:', err);
      } finally {
        setAnchorSearching(false);
      }
    }, [stackId]);

    const handleCreate = useCallback(async () => {
      if (creating) return;
      setCreating(true);
      try {
        const enabledGroups = (preview?.groups || []).map((group, gi) => {
          const enabledRecs = group.recommendations.filter(
            (_, mi) => monitorToggles[`${gi}:${mi}`] !== false,
          );
          return { ...group, recommendations: enabledRecs };
        }).filter((g) => g.recommendations.length > 0);

        const res = await fetch('/api/schedule/plans', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: planName,
            description: planDescription || undefined,
            scopeType,
            scopeConfig: anchorNodeId ? { anchorNodeIds: [anchorNodeId] } : {},
            anchorFqn: anchorFqn || undefined,
            anchorNodeId: anchorNodeId || undefined,
            mode,
            families: selectedFamilies,
            schedule,
            timezone,
            alertChannels,
            alertOnStatus,
            groups: enabledGroups,
          }),
        });
        if (res.ok) {
          const data = await res.json();
          onComplete(data.id);
        } else {
          const err = await res.json();
          console.error('[MultiMonitor] Create error:', err);
        }
      } catch (err) {
        console.error('[MultiMonitor] Create error:', err);
      } finally {
        setCreating(false);
      }
    }, [
      preview, monitorToggles, planName, planDescription, scopeType,
      anchorNodeId, anchorFqn, mode, selectedFamilies, schedule,
      timezone, alertChannels, alertOnStatus, creating, onComplete,
    ]);

    // ---------------------------------------------------------------------------
    // Handlers
    // ---------------------------------------------------------------------------

    const handleFamilyToggle = (familyKey: string) => {
      setSelectedFamilies((prev) => {
        if (familyKey === 'full_coverage') {
          const eligible: string[] = familyEligibility.filter((f) => f.eligible && !f.is_meta).map((f) => f.key);
          const allSelected = eligible.every((k) => prev.includes(k));
          if (allSelected) return prev.filter((k) => !eligible.includes(k) && k !== 'full_coverage');
          return [...new Set([...prev, ...eligible, 'full_coverage'])];
        }
        if (prev.includes(familyKey)) return prev.filter((k) => k !== familyKey && k !== 'full_coverage');
        return [...prev, familyKey];
      });
    };

    const handleToggleMonitor = (key: string) => {
      setMonitorToggles((prev) => ({ ...prev, [key]: !prev[key] }));
    };

    // ---------------------------------------------------------------------------
    // Validation helpers
    // ---------------------------------------------------------------------------

    const needsAnchor = scopeType === 'stream' || scopeType === 'asset';
    const scopeComplete = scopeType === 'pipeline' || (needsAnchor && !!anchorNodeId);
    const modeComplete = mode === 'recommended'
      ? selectedFamilies.length > 0
      : Object.values(manualSelections).some((v) => v.length > 0);
    const reviewComplete = (preview?.total_monitors ?? 0) > 0;

    const scopeSummary = (() => {
      const label = SCOPE_TYPES.find((s) => s.key === scopeType)?.label || scopeType;
      return anchorName ? `${label} — ${anchorName}` : label;
    })();

    const modeSummary = (() => {
      if (!modeComplete) return '';
      if (mode === 'recommended') {
        const count = selectedFamilies.filter((f) => f !== 'full_coverage').length;
        return `Recommended — ${count} famil${count === 1 ? 'y' : 'ies'}`;
      }
      const count = Object.values(manualSelections).reduce((sum, v) => sum + v.length, 0);
      return `Manual — ${count} monitor${count === 1 ? '' : 's'}`;
    })();

    const enabledMonitorCount = preview
      ? Object.entries(monitorToggles).filter(([, v]) => v).length
      : 0;
    const groupCount = preview?.groups.filter((g, gi) =>
      g.recommendations.some((_, mi) => monitorToggles[`${gi}:${mi}`] !== false),
    ).length ?? 0;

    function isSectionComplete(key: SectionKey): boolean {
      switch (key) {
        case 'scope': return scopeComplete;
        case 'mode': return modeComplete;
        case 'review': return reviewComplete;
        case 'schedule': return true;
        case 'create': return !!planName;
      }
    }

    function getSectionSummary(key: SectionKey): string {
      switch (key) {
        case 'scope': return scopeComplete ? scopeSummary : '';
        case 'mode': return modeSummary;
        case 'review': return reviewComplete ? `${enabledMonitorCount} monitors in ${groupCount} groups` : '';
        case 'schedule': return schedule || 'No schedule';
        case 'create': return planName || '';
      }
    }

    // ---------------------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------------------

    return (
      <div>
        {SECTIONS.map((section) => {
          const isExpanded = expandedSection === section.key;
          const isComplete = isSectionComplete(section.key);
          const summary = getSectionSummary(section.key);

          return (
            <div key={section.key} className="border-b border-[var(--border-faint)] last:border-b-0">
              {/* Section header */}
              <button
                onClick={() => setExpandedSection(section.key)}
                className={cn(
                  'w-full flex items-center gap-3 px-6 py-3.5 text-left transition-colors',
                  isExpanded ? 'bg-[var(--overlay-bg)]' : 'hover:bg-[var(--hover-bg)]',
                )}
              >
                <div className={cn(
                  'w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-medium flex-shrink-0',
                  isExpanded
                    ? 'bg-blue-500/20 text-blue-400'
                    : isComplete
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : 'bg-[var(--overlay-bg)] text-[var(--text-faint)]',
                )}>
                  {!isExpanded && isComplete ? '\u2713' : section.number}
                </div>
                <div className="flex-1 min-w-0">
                  <span className="text-[13px] font-medium text-[var(--text)]">
                    {section.label}
                  </span>
                  {!isExpanded && summary && (
                    <span className="text-[12px] text-[var(--muted)] ml-2">{summary}</span>
                  )}
                </div>
                <svg
                  className={cn('w-4 h-4 text-[var(--text-faint)] transition-transform', isExpanded && 'rotate-180')}
                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {isExpanded && (
                <div className="px-6 pb-5 pt-2">
                  {section.key === 'scope' && renderScope()}
                  {section.key === 'mode' && renderMode()}
                  {section.key === 'review' && renderReview()}
                  {section.key === 'schedule' && renderSchedule()}
                  {section.key === 'create' && renderCreate()}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );

    // ---------------------------------------------------------------------------
    // Section renderers
    // ---------------------------------------------------------------------------

    function renderScope() {
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2">
            {SCOPE_TYPES.map((scope) => (
              <button
                key={scope.key}
                onClick={() => {
                  setScopeType(scope.key);
                  if (scope.key === 'pipeline') { setAnchorNodeId(''); setAnchorFqn(''); setAnchorName(''); }
                }}
                className={cn(
                  'text-left px-4 py-3 rounded-lg transition-colors',
                  scopeType === scope.key
                    ? 'bg-[var(--overlay-medium)] border-2 border-[var(--overlay-strong)]'
                    : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]',
                )}
              >
                <div className="text-[13px] font-medium text-[var(--text)]">{scope.label}</div>
                <div className="text-[11px] text-[var(--muted)] mt-0.5">{scope.description}</div>
              </button>
            ))}
          </div>

          {needsAnchor && (
            <div className="space-y-2">
              <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Anchor asset</label>
              {anchorNodeId ? (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--overlay-medium)] border border-[var(--overlay-strong)]">
                  <span className="text-[13px] text-[var(--text)] flex-1 truncate">{anchorName || anchorFqn}</span>
                  <button
                    onClick={() => { setAnchorNodeId(''); setAnchorFqn(''); setAnchorName(''); setAnchorSearch(''); }}
                    className="text-[var(--muted)] hover:text-[var(--text)] text-[11px]"
                  >Change</button>
                </div>
              ) : (
                <div className="relative">
                  <input
                    type="text"
                    value={anchorSearch}
                    onChange={(e) => { setAnchorSearch(e.target.value); searchAnchors(e.target.value); }}
                    placeholder="Search for an asset..."
                    className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
                  />
                  {anchorResults.length > 0 && (
                    <div className="absolute top-full left-0 right-0 mt-1 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface)] shadow-lg max-h-[200px] overflow-y-auto z-10">
                      {anchorResults.map((result: any) => (
                        <button
                          key={result.id}
                          onClick={() => { setAnchorNodeId(result.id); setAnchorFqn(result.fqn); setAnchorName(result.name); setAnchorResults([]); setAnchorSearch(''); }}
                          className="w-full text-left px-3 py-2 hover:bg-[var(--hover-bg)] text-[13px] text-[var(--text)] border-b border-[var(--border-faint)] last:border-b-0"
                        >
                          <div className="truncate">{result.name}</div>
                          <div className="text-[10px] text-[var(--muted)] font-mono truncate">{result.fqn}</div>
                        </button>
                      ))}
                    </div>
                  )}
                  {anchorSearching && (
                    <div className="absolute right-3 top-1/2 -translate-y-1/2">
                      <div className="w-4 h-4 border-2 border-[var(--muted)] border-t-transparent rounded-full animate-spin" />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      );
    }

    function renderMode() {
      return (
        <div className="space-y-4">
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Selection Mode</label>
            <div className="flex gap-3">
              {([
                { m: 'recommended' as const, label: 'Recommended', sub: 'Auto-select by family', icon: 'M13 10V3L4 14h7v7l9-11h-7z' },
                { m: 'manual' as const, label: 'Manual', sub: 'Pick per asset', icon: 'M4 6h16M4 12h16M4 18h7' },
              ]).map(({ m, label, sub, icon }) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={cn(
                    'flex-1 flex flex-col items-center justify-center gap-1 py-2.5 rounded-lg transition-colors',
                    mode === m
                      ? 'bg-[var(--overlay-medium)] border-2 border-[var(--overlay-strong)]'
                      : 'bg-[var(--overlay-bg)] border border-[var(--subtle-border)] hover:bg-[var(--hover-bg)]',
                  )}
                >
                  <svg className="w-5 h-5 text-[var(--text-tertiary)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={icon} />
                  </svg>
                  <span className="text-[13px] font-medium text-[var(--text)] leading-tight">{label}</span>
                  <span className="text-[11px] text-[var(--muted)] leading-tight">{sub}</span>
                </button>
              ))}
            </div>
          </div>

          {mode === 'recommended' ? (
            <FamilyPicker
              families={familyEligibility}
              selected={selectedFamilies}
              onToggle={handleFamilyToggle}
              loading={familiesLoading}
            />
          ) : (
            <ManualMonitorPicker
              nodes={manualNodes}
              selections={manualSelections}
              onSelectionChange={setManualSelections}
            />
          )}
        </div>
      );
    }

    function renderReview() {
      return (
        <PlanPreview
          preview={preview}
          monitorToggles={monitorToggles}
          onToggleMonitor={handleToggleMonitor}
          loading={previewLoading}
        />
      );
    }

    function renderSchedule() {
      return (
        <div className="space-y-5">
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Schedule</label>
            <ScheduleInput value={schedule} onChange={setSchedule} />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Timezone</label>
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
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Alerts</label>
            <AlertChannelPicker
              channels={alertChannels}
              onChannelsChange={setAlertChannels}
              alertOnStatus={alertOnStatus}
              onAlertOnStatusChange={setAlertOnStatus}
            />
          </div>
        </div>
      );
    }

    function renderCreate() {
      return (
        <div className="space-y-4">
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Plan Name</label>
            <input
              type="text"
              value={planName}
              onChange={(e) => setPlanName(e.target.value)}
              placeholder="e.g., Pipeline Health Monitoring"
              className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]"
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-[var(--muted)] mb-2">Description (optional)</label>
            <textarea
              value={planDescription}
              onChange={(e) => setPlanDescription(e.target.value)}
              rows={2}
              placeholder="What this monitoring plan covers..."
              className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2.5 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)] resize-none"
            />
          </div>
          <div className="rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] p-4 space-y-2">
            <h3 className="text-[12px] font-medium text-[var(--muted)] uppercase tracking-wider">Summary</h3>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
              <span className="text-[var(--text-faint)]">Scope</span>
              <span className="text-[var(--text)]">{scopeSummary}</span>
              <span className="text-[var(--text-faint)]">Mode</span>
              <span className="text-[var(--text)] capitalize">{mode}</span>
              {mode === 'recommended' && (
                <>
                  <span className="text-[var(--text-faint)]">Families</span>
                  <span className="text-[var(--text)]">
                    {selectedFamilies.filter((f) => f !== 'full_coverage').join(', ') || '\u2014'}
                  </span>
                </>
              )}
              <span className="text-[var(--text-faint)]">Groups</span>
              <span className="text-[var(--text)]">{groupCount}</span>
              <span className="text-[var(--text-faint)]">Monitors</span>
              <span className="text-[var(--text)]">{enabledMonitorCount}</span>
              <span className="text-[var(--text-faint)]">Schedule</span>
              <span className="text-[var(--text)]">{schedule || 'None'}</span>
            </div>
          </div>
        </div>
      );
    }
  },
);
