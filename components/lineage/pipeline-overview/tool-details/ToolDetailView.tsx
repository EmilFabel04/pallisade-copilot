'use client';

import React, { useState } from 'react';
import type { ToolDetailsResponse } from '../types';
import { getOverallHealth, HEALTH_COLORS } from '../types';
import {
  Section,
  HealthSummaryDisplay,
  ConnectionList,
  CoverageGapsList,
  formatRelativeTime,
} from './SharedDetailComponents';
import { IngestionDetailView } from './IngestionDetailView';
import { TransformDetailView } from './TransformDetailView';
import { OrchestrationDetailView } from './OrchestrationDetailView';
import { WarehouseDetailView } from './WarehouseDetailView';
import { ReportingDetailView } from './ReportingDetailView';
import { InfraDetailView } from './InfraDetailView';
import { QualityDetailView } from './QualityDetailView';
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
    default:
      return <GenericDetailView items={items} tabKey={tabKey} />;
  }
}

// ─── Overview tab (shared across all domains) ────────────────────────

function OverviewTab({ details }: { details: ToolDetailsResponse }) {
  const { summary, connections } = details;
  const health = getOverallHealth(summary.healthSummary);
  const healthColor = HEALTH_COLORS[health];

  return (
    <div className="space-y-4">
      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3">
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
      </div>

      {summary.lastRunTs && (
        <div>
          <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">Last Activity</label>
          <p className="text-[13px] text-[var(--text)] mt-1 font-mono">{formatRelativeTime(summary.lastRunTs)}</p>
        </div>
      )}

      {/* Health */}
      <Section title="Health Summary" defaultOpen>
        <HealthSummaryDisplay summary={summary.healthSummary} />
      </Section>

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

      {/* Coverage */}
      <Section title="Coverage" defaultOpen>
        <CoverageGapsList gaps={summary.coverageGaps} />
      </Section>
    </div>
  );
}

// ─── Main ToolDetailView ─────────────────────────────────────────────

export function ToolDetailView({ details }: { details: ToolDetailsResponse }) {
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
        <OverviewTab details={details} />
      ) : (
        <DomainTabContent details={details} tabKey={activeTab} />
      )}
    </div>
  );
}
