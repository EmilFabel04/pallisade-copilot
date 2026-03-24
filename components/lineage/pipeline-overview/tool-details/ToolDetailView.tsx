'use client';

import React, { useState, useMemo } from 'react';
import type { ToolDetailsResponse } from '../types';
import { getOverallHealth, HEALTH_COLORS } from '../types';
import {
  Section,
  HealthSummaryDisplay,
  ConnectionList,
  CoverageGapsList,
  formatRelativeTime,
} from './SharedDetailComponents';
import { computeMonitorScoring, resolveAssetCategory } from '@/lib/monitor-scoring';
import { IngestionDetailView } from './IngestionDetailView';
import { TransformDetailView } from './TransformDetailView';
import { OrchestrationDetailView } from './OrchestrationDetailView';
import { WarehouseDetailView } from './WarehouseDetailView';
import { ReportingDetailView } from './ReportingDetailView';
import { InfraDetailView } from './InfraDetailView';
import { QualityDetailView } from './QualityDetailView';
import { VersionControlDetailView } from './VersionControlDetailView';
import { GenericDetailView } from './GenericDetailView';

// ─── Domain tab content router ───────────────────────────────────────

function DomainTabContent({
  details,
  tabKey,
}: {
  details: ToolDetailsResponse;
  tabKey: string;
}) {
  const items = details.groups[tabKey] || [];

  switch (details.category) {
    case 'ingestion':
      return <IngestionDetailView items={items} tabKey={tabKey} />;
    case 'transformation':
      return <TransformDetailView items={items} tabKey={tabKey} />;
    case 'orchestration':
      return <OrchestrationDetailView items={items} tabKey={tabKey} />;
    case 'warehouse':
      return <WarehouseDetailView items={items} tabKey={tabKey} />;
    case 'reporting':
      return <ReportingDetailView items={items} tabKey={tabKey} />;
    case 'infrastructure':
      return <InfraDetailView items={items} tabKey={tabKey} />;
    case 'quality':
      return <QualityDetailView items={items} tabKey={tabKey} />;
    case 'version_control':
      return <VersionControlDetailView items={items} tabKey={tabKey} />;
    default:
      return <GenericDetailView items={items} tabKey={tabKey} />;
  }
}

// ─── Overview tab (shared across all domains) ────────────────────────

const STATUS_COLORS: Record<string, string> = {
  PASS: '#10B981',
  WARN: '#F59E0B',
  FAIL: '#EF4444',
  ERROR: '#EF4444',
  RUNNING: '#6366F1',
  SKIPPED: '#6B7280',
};

function OverviewTab({ details, monitors }: { details: ToolDetailsResponse; monitors?: MonitorInfo[] }) {
  const { summary, connections } = details;
  const health = getOverallHealth(summary.healthSummary);
  const healthColor = HEALTH_COLORS[health];
  const [showAllMonitors, setShowAllMonitors] = useState(false);
  const MONITOR_VISIBLE_LIMIT = 5;

  const passing = monitors?.filter(m => m.lastStatus === 'PASS').length || 0;
  const warning = monitors?.filter(m => m.lastStatus === 'WARN').length || 0;
  const failing = monitors?.filter(m => m.lastStatus === 'FAIL' || m.lastStatus === 'ERROR').length || 0;

  // Monitor-based health & coverage scoring
  const scoring = useMemo(() => {
    if (!monitors?.length) return null;
    const category = resolveAssetCategory(undefined, details.platformDomain, details.platform);
    if (!category) return null;
    return computeMonitorScoring(
      monitors.map(m => ({ monitorType: m.monitorType || '', lastStatus: m.lastStatus })),
      category,
    );
  }, [monitors, details.platformDomain, details.platform]);

  return (
    <div className="space-y-4">
      {/* Stats grid — platform-relevant labels */}
      <div className="grid grid-cols-2 gap-3">
        {(() => {
          const p = (details.platform || '').toLowerCase();
          // Ingestion: show connectors only
          if (['fivetran', 'airbyte', 'stitch'].includes(p)) {
            return summary.jobCount > 0 ? (
              <div>
                <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Connectors</label>
                <p className="text-2xl font-semibold text-[var(--text)] mt-1">{summary.jobCount}</p>
              </div>
            ) : null;
          }
          // Orchestration: DAGs/Workflows + Tasks — use tab counts for accuracy
          if (['airflow', 'dagster', 'prefect', 'n8n'].includes(p)) {
            const dagLabel = p === 'airflow' ? 'DAGs' : 'Workflows';
            const dagTab = details.tabs.find(t => t.key === 'dags' || t.key === 'flows' || t.key === 'dags_flows');
            const taskTab = details.tabs.find(t => t.key === 'tasks');
            const dagCount = dagTab?.count ?? 0;
            const taskCount = taskTab?.count ?? 0;
            return (
              <>
                {dagCount > 0 && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">{dagLabel}</label>
                    <p className="text-2xl font-semibold text-[var(--text)] mt-1">{dagCount}</p>
                  </div>
                )}
                {taskCount > 0 && (
                  <div>
                    <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Tasks</label>
                    <p className="text-2xl font-semibold text-[var(--text)] mt-1">{taskCount}</p>
                  </div>
                )}
              </>
            );
          }
          // BI: dashboards
          if (['metabase', 'looker', 'tableau', 'powerbi'].includes(p)) {
            return (
              <div>
                <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Dashboards</label>
                <p className="text-2xl font-semibold text-[var(--text)] mt-1">{summary.totalAssets}</p>
              </div>
            );
          }
          // VCS: repos
          if (['github', 'gitlab', 'bitbucket'].includes(p)) {
            return summary.totalAssets > 0 ? (
              <div>
                <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Repositories</label>
                <p className="text-2xl font-semibold text-[var(--text)] mt-1">{summary.totalAssets}</p>
              </div>
            ) : null;
          }
          // Warehouse / transformation: assets only (no "jobs" — dbt models are assets, not jobs)
          if (['bigquery', 'snowflake', 'postgres', 'redshift', 'databricks', 'dbt', 'dbt_core'].includes(p)) {
            return (
              <div>
                <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Assets</label>
                <p className="text-2xl font-semibold text-[var(--text)] mt-1">{summary.totalAssets}</p>
              </div>
            );
          }
          // Default: Assets + Jobs
          return (
            <>
              <div>
                <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Assets</label>
                <p className="text-2xl font-semibold text-[var(--text)] mt-1">{summary.totalAssets}</p>
              </div>
              {summary.jobCount > 0 && (
                <div>
                  <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Jobs</label>
                  <p className="text-2xl font-semibold text-[var(--text)] mt-1">{summary.jobCount}</p>
                </div>
              )}
            </>
          );
        })()}
      </div>

      {summary.lastRunTs && (
        <div>
          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Last Activity</label>
          <p className="text-[13px] text-[var(--text)] mt-1 font-mono">{formatRelativeTime(summary.lastRunTs)}</p>
        </div>
      )}

      {/* Monitor Health & Coverage */}
      {scoring && scoring.healthScore != null && (
        <div className="p-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Monitor Health</span>
            <div className="flex items-center gap-2">
              <div className="w-16 h-1.5 rounded-full bg-[var(--subtle-bg)] overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${scoring.healthScore}%`,
                    backgroundColor: scoring.healthStatus === 'healthy' ? '#10B981'
                      : scoring.healthStatus === 'degraded' ? '#F59E0B'
                      : scoring.healthStatus === 'at_risk' ? '#F97316'
                      : '#EF4444',
                  }}
                />
              </div>
              <span
                className="text-[11px] font-medium"
                style={{
                  color: scoring.healthStatus === 'healthy' ? '#10B981'
                    : scoring.healthStatus === 'degraded' ? '#F59E0B'
                    : scoring.healthStatus === 'at_risk' ? '#F97316'
                    : '#EF4444',
                }}
              >
                {Math.round(scoring.healthScore)}%
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Coverage</span>
            <div className="flex items-center gap-2">
              <div className="w-16 h-1.5 rounded-full bg-[var(--subtle-bg)] overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(scoring.coveragePct, 100)}%`,
                    backgroundColor: scoring.coverageStatus === 'good' ? '#10B981'
                      : scoring.coverageStatus === 'partial' ? '#F59E0B'
                      : '#6B7280',
                  }}
                />
              </div>
              <span
                className="text-[11px] font-medium"
                style={{
                  color: scoring.coverageStatus === 'good' ? '#10B981'
                    : scoring.coverageStatus === 'partial' ? '#F59E0B'
                    : '#6B7280',
                }}
              >
                {scoring.configured}/{scoring.available}
              </span>
            </div>
          </div>
          {scoring.missingTypes.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {scoring.missingTypes.slice(0, 4).map(t => (
                <span key={t} className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--text-faint)] uppercase">
                  {t.replace(/_/g, ' ')}
                </span>
              ))}
              {scoring.missingTypes.length > 4 && (
                <span className="text-[9px] text-[var(--text-faint)]">+{scoring.missingTypes.length - 4}</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Monitors */}
      {monitors && monitors.length > 0 && (
        <Section title="Monitors" count={monitors.length} defaultOpen>
          <div className="space-y-1.5">
            {/* Status summary badges */}
            <div className="flex items-center gap-2 mb-2">
              {failing > 0 && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium text-red-400 bg-red-500/10">
                  {failing} failing
                </span>
              )}
              {warning > 0 && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium text-amber-400 bg-amber-500/10">
                  {warning} warning
                </span>
              )}
              {passing > 0 && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium text-emerald-400 bg-emerald-500/10">
                  {passing} passing
                </span>
              )}
            </div>

            {/* Per-monitor cards */}
            {(showAllMonitors ? monitors : monitors.slice(0, MONITOR_VISIBLE_LIMIT)).map(m => {
              const statusColor = STATUS_COLORS[m.lastStatus || ''] || '#6B7280';
              const lastRunAgo = m.lastRunAt ? formatRelativeTime(m.lastRunAt) : null;
              return (
                <a
                  key={m.id}
                  href={`/dashboard/schedule?monitor=${m.id}`}
                  className="block px-2.5 py-2 rounded-lg bg-[var(--overlay-bg)] hover:bg-[var(--overlay-medium)] transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: statusColor, boxShadow: `0 0 4px ${statusColor}40` }}
                    />
                    <span className="text-[12px] text-[var(--text)] font-medium truncate flex-1">
                      {m.name}
                    </span>
                    {m.monitorType && (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-[var(--overlay-faint)] text-[var(--muted)] uppercase shrink-0">
                        {m.monitorType.replace(/_/g, ' ')}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-1 ml-4">
                    {lastRunAgo && (
                      <span className="text-[10px] text-[var(--muted)]">
                        Last evaluated {lastRunAgo}
                      </span>
                    )}
                  </div>
                  {m.lastMessage && (
                    <p className="text-[10px] text-[var(--muted)] mt-1 ml-4 truncate">
                      {m.lastMessage}
                    </p>
                  )}
                </a>
              );
            })}

            {/* Show all toggle */}
            {monitors.length > MONITOR_VISIBLE_LIMIT && (
              <button
                onClick={() => setShowAllMonitors(!showAllMonitors)}
                className="text-[11px] text-[var(--text-secondary)] hover:text-[var(--text)] mt-1"
              >
                {showAllMonitors ? 'Show less' : `Show all ${monitors.length} monitors`}
              </button>
            )}
          </div>
        </Section>
      )}

      {/* Health — monitor-based when monitors exist, graph-based fallback */}
      {scoring ? (
        <Section title="Health Summary" defaultOpen>
          {scoring.healthScore != null ? (
            <div className="flex items-center gap-2">
              <span
                className="text-[13px] font-semibold"
                style={{
                  color: scoring.healthStatus === 'healthy' ? '#10B981'
                    : scoring.healthStatus === 'degraded' ? '#F59E0B'
                    : scoring.healthStatus === 'at_risk' ? '#F97316'
                    : '#EF4444',
                }}
              >
                {Math.round(scoring.healthScore)}% — {scoring.healthStatus?.replace('_', ' ')}
              </span>
            </div>
          ) : (
            <p className="text-[12px] text-[var(--muted)] italic">Monitors configured but no results yet</p>
          )}
        </Section>
      ) : (
        <Section title="Health Summary" defaultOpen>
          <HealthSummaryDisplay summary={summary.healthSummary} />
        </Section>
      )}

      {/* Connections */}
      {(connections.upstream.length > 0 || connections.downstream.length > 0) && (
        <>
          {connections.upstream.length > 0 && (
            <Section title="Upstream Tools" count={connections.upstream.length} defaultOpen>
              <ConnectionList connections={connections.upstream} direction="upstream" />
            </Section>
          )}
          {connections.downstream.length > 0 && (
            <Section title="Downstream Tools" count={connections.downstream.length} defaultOpen>
              <ConnectionList connections={connections.downstream} direction="downstream" />
            </Section>
          )}
        </>
      )}

      {/* Coverage — monitor-based when scoring available, lineage-gap fallback */}
      <Section title="Coverage" defaultOpen>
        {scoring ? (
          scoring.coveragePct > 0 ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-[var(--text)]">
                  {scoring.configured}/{scoring.available} monitor types configured
                </span>
                <span
                  className="text-[11px] font-medium"
                  style={{
                    color: scoring.coverageStatus === 'good' ? '#10B981'
                      : scoring.coverageStatus === 'partial' ? '#F59E0B'
                      : '#6B7280',
                  }}
                >
                  {Math.round(scoring.coveragePct)}%
                </span>
              </div>
              {scoring.missingTypes.length > 0 && (
                <div>
                  <p className="text-[10px] text-[var(--muted)] mb-1">Missing:</p>
                  <div className="flex flex-wrap gap-1">
                    {scoring.missingTypes.map(t => (
                      <span key={t} className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 uppercase">
                        {t.replace(/_/g, ' ')}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3 py-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <div className="w-2 h-2 rounded-full bg-[#6B7280]" />
              <span className="text-[12px] text-[var(--text-faint)]">No checks configured</span>
            </div>
          )
        ) : (
          /* No monitors at all — show unmonitored state instead of misleading "Full coverage" */
          (!monitors || monitors.length === 0) ? (
            <div className="flex items-center gap-2 px-3 py-3 rounded-lg bg-[var(--overlay-bg)] border border-[var(--subtle-border)]">
              <div className="w-2 h-2 rounded-full bg-[#6B7280]" />
              <span className="text-[12px] text-[var(--text-faint)]">Unmonitored — no checks configured</span>
            </div>
          ) : (
            <CoverageGapsList gaps={summary.coverageGaps} />
          )
        )}
      </Section>
    </div>
  );
}

// ─── Main ToolDetailView ─────────────────────────────────────────────

type MonitorInfo = {
  id: string;
  name: string;
  monitorType: string | null;
  targetFqn: string | null;
  lastStatus: string | null;
  lastRunAt: string | null;
  lastMessage?: string;
  integrationId: string | null;
};

export function ToolDetailView({ details, monitors }: { details: ToolDetailsResponse; monitors?: MonitorInfo[] }) {
  const [activeTab, setActiveTab] = useState('overview');

  const allTabs = [
    { key: 'overview', label: 'Overview', count: -1 },
    ...details.tabs,
  ];

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex gap-0.5 p-0.5 rounded-lg bg-[var(--overlay-faint)]">
        {allTabs.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`flex-1 px-2 py-1.5 rounded-md text-[11px] font-medium transition-colors ${
              activeTab === t.key
                ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm'
                : 'text-[var(--muted)] hover:text-[var(--text-secondary)]'
            }`}
          >
            {t.label}
            {t.count >= 0 && <span className="ml-1 text-[10px] opacity-60">({t.count})</span>}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'overview' ? (
        <OverviewTab details={details} monitors={monitors} />
      ) : (
        <DomainTabContent details={details} tabKey={activeTab} />
      )}
    </div>
  );
}
