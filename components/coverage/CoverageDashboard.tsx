"use client";

/**
 * CoverageDashboard
 *
 * Full-page dashboard for lineage coverage analysis. Shows aggregate
 * scores, category breakdowns, gap prioritization, and monitor
 * recommendations in a single view.
 */

import React, { useState, useMemo } from "react";
import type {
  CoverageReportDetailed,
  CoverageGap,
  MonitorRecommendation,
  NodeCoverage,
  CoverageCategory,
  GapSeverity,
} from "./types";
import {
  getCoverageColor,
  SEVERITY_COLORS,
  CATEGORY_COLORS,
  CATEGORY_LABELS,
} from "./types";

// ---------------------------------------------------------------------------
// Main Dashboard Component
// ---------------------------------------------------------------------------

interface CoverageDashboardProps {
  report: CoverageReportDetailed;
  onNodeSelect?: (nodeId: string) => void;
  onApplyRecommendation?: (rec: MonitorRecommendation) => void;
}

export function CoverageDashboard({
  report,
  onNodeSelect,
  onApplyRecommendation,
}: CoverageDashboardProps) {
  const [activeTab, setActiveTab] = useState<
    "overview" | "gaps" | "recommendations" | "nodes"
  >("overview");
  const [severityFilter, setSeverityFilter] = useState<GapSeverity | "all">(
    "all"
  );

  const filteredGaps = useMemo(() => {
    if (severityFilter === "all") return report.gaps;
    return report.gaps.filter((g) => g.severity === severityFilter);
  }, [report.gaps, severityFilter]);

  const overallPercent = Math.round(report.overall_score * 100);

  return (
    <div className="flex h-full flex-col bg-zinc-950 text-zinc-200">
      {/* Header */}
      <div className="border-b border-zinc-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Lineage Coverage</h1>
            <p className="mt-0.5 text-xs text-zinc-500">
              Tech-agnostic observability coverage analysis across{" "}
              {report.total_nodes} data assets
            </p>
          </div>

          {/* Overall score badge */}
          <div className="flex items-center gap-3">
            <div
              className="flex h-12 w-12 items-center justify-center rounded-full text-lg font-bold text-white shadow-lg"
              style={{ backgroundColor: getCoverageColor(overallPercent) }}
            >
              {overallPercent}
            </div>
            <div className="text-right text-xs">
              <div className="font-medium text-zinc-300">
                Overall Score
              </div>
              <div className="text-zinc-500">
                {report.nodes_with_full_coverage} fully covered
              </div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="mt-4 flex gap-1">
          {(
            ["overview", "gaps", "recommendations", "nodes"] as const
          ).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === tab
                  ? "bg-zinc-800 text-white"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {tab === "overview" && "Overview"}
              {tab === "gaps" && `Gaps (${report.gaps.length})`}
              {tab === "recommendations" &&
                `Recommendations (${report.recommendations.length})`}
              {tab === "nodes" && `Nodes (${report.total_nodes})`}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeTab === "overview" && (
          <OverviewTab report={report} />
        )}
        {activeTab === "gaps" && (
          <GapsTab
            gaps={filteredGaps}
            severityFilter={severityFilter}
            onSeverityChange={setSeverityFilter}
            allGaps={report.gaps}
            onNodeSelect={onNodeSelect}
          />
        )}
        {activeTab === "recommendations" && (
          <RecommendationsTab
            recommendations={report.recommendations}
            onApply={onApplyRecommendation}
          />
        )}
        {activeTab === "nodes" && (
          <NodesTab
            nodes={report.node_coverages}
            onNodeSelect={onNodeSelect}
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

function OverviewTab({ report }: { report: CoverageReportDetailed }) {
  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        <SummaryCard
          label="Full Coverage"
          value={report.nodes_with_full_coverage}
          total={report.total_nodes}
          color="#10B981"
        />
        <SummaryCard
          label="Partial Coverage"
          value={report.nodes_with_partial_coverage}
          total={report.total_nodes}
          color="#F59E0B"
        />
        <SummaryCard
          label="No Coverage"
          value={report.nodes_with_no_coverage}
          total={report.total_nodes}
          color="#EF4444"
        />
        <SummaryCard
          label="Critical Gaps"
          value={report.gaps_summary.critical}
          total={report.gaps_summary.total}
          color="#EF4444"
        />
      </div>

      {/* Category scores */}
      <div>
        <h3 className="mb-3 text-sm font-semibold text-zinc-300">
          Coverage by Category
        </h3>
        <div className="grid grid-cols-2 gap-3">
          {(
            Object.entries(report.category_scores) as [
              CoverageCategory,
              number,
            ][]
          ).map(([cat, score]) => {
            const pct = Math.round(score * 100);
            return (
              <div
                key={cat}
                className="rounded-lg border border-zinc-800 bg-zinc-900 p-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div
                      className="h-3 w-3 rounded"
                      style={{
                        backgroundColor: CATEGORY_COLORS[cat],
                      }}
                    />
                    <span className="text-xs font-medium text-zinc-300">
                      {CATEGORY_LABELS[cat]}
                    </span>
                  </div>
                  <span
                    className="text-sm font-bold"
                    style={{ color: getCoverageColor(pct) }}
                  >
                    {pct}%
                  </span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${pct}%`,
                      backgroundColor: CATEGORY_COLORS[cat],
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Top gaps preview */}
      <div>
        <h3 className="mb-3 text-sm font-semibold text-zinc-300">
          Top Priority Gaps
        </h3>
        <div className="space-y-2">
          {report.gaps.slice(0, 5).map((gap, i) => (
            <GapRow key={`${gap.node_id}-${gap.dimension}-${i}`} gap={gap} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gaps Tab
// ---------------------------------------------------------------------------

function GapsTab({
  gaps,
  severityFilter,
  onSeverityChange,
  allGaps,
  onNodeSelect,
}: {
  gaps: CoverageGap[];
  severityFilter: GapSeverity | "all";
  onSeverityChange: (s: GapSeverity | "all") => void;
  allGaps: CoverageGap[];
  onNodeSelect?: (nodeId: string) => void;
}) {
  const counts = useMemo(() => {
    const c = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    for (const g of allGaps) c[g.severity]++;
    return c;
  }, [allGaps]);

  return (
    <div>
      {/* Severity filter */}
      <div className="mb-4 flex gap-2">
        <FilterPill
          label={`All (${allGaps.length})`}
          active={severityFilter === "all"}
          onClick={() => onSeverityChange("all")}
        />
        {(["critical", "high", "medium", "low"] as GapSeverity[]).map(
          (sev) =>
            counts[sev] > 0 ? (
              <FilterPill
                key={sev}
                label={`${sev} (${counts[sev]})`}
                active={severityFilter === sev}
                onClick={() => onSeverityChange(sev)}
                color={SEVERITY_COLORS[sev]}
              />
            ) : null
        )}
      </div>

      {/* Gap list */}
      <div className="space-y-2">
        {gaps.map((gap, i) => (
          <GapRow
            key={`${gap.node_id}-${gap.dimension}-${i}`}
            gap={gap}
            expanded
            onNodeClick={onNodeSelect}
          />
        ))}
        {gaps.length === 0 && (
          <div className="py-8 text-center text-xs text-zinc-600">
            No gaps match the current filter.
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recommendations Tab
// ---------------------------------------------------------------------------

function RecommendationsTab({
  recommendations,
  onApply,
}: {
  recommendations: MonitorRecommendation[];
  onApply?: (rec: MonitorRecommendation) => void;
}) {
  return (
    <div className="space-y-3">
      {recommendations.map((rec, i) => (
        <div
          key={`${rec.target_node_id}-${rec.monitor_type}-${i}`}
          className="rounded-lg border border-zinc-800 bg-zinc-900 p-4"
        >
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span
                  className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase text-white"
                  style={{
                    backgroundColor: SEVERITY_COLORS[rec.priority],
                  }}
                >
                  {rec.priority}
                </span>
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">
                  {rec.monitor_type.replace(/_/g, " ")}
                </span>
              </div>
              <div className="mt-1.5 text-xs text-zinc-300">
                {rec.description}
              </div>
              <div className="mt-1 text-[10px] text-zinc-600">
                Target: {rec.target_node_name}
              </div>
            </div>
            {onApply && (
              <button
                onClick={() => onApply(rec)}
                className="shrink-0 rounded bg-blue-600 px-3 py-1 text-[10px] font-medium text-white transition-colors hover:bg-blue-500"
              >
                Apply
              </button>
            )}
          </div>

          {/* SQL template preview */}
          {rec.sql_template && (
            <details className="mt-3">
              <summary className="cursor-pointer text-[10px] text-zinc-500 hover:text-zinc-400">
                SQL Template
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-zinc-950 p-2 text-[10px] text-zinc-400">
                {rec.sql_template}
              </pre>
            </details>
          )}

          {/* Closes gaps */}
          <div className="mt-2 flex flex-wrap gap-1">
            {rec.closes_gaps.map((g) => (
              <span
                key={g}
                className="rounded bg-green-950/50 px-1.5 py-0.5 text-[10px] text-green-400"
              >
                {g.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        </div>
      ))}
      {recommendations.length === 0 && (
        <div className="py-8 text-center text-xs text-zinc-600">
          No recommendations — all coverage gaps are non-monitorable
          (ownership, documentation, etc.).
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Nodes Tab
// ---------------------------------------------------------------------------

function NodesTab({
  nodes,
  onNodeSelect,
}: {
  nodes: NodeCoverage[];
  onNodeSelect?: (nodeId: string) => void;
}) {
  const [sortBy, setSortBy] = useState<"score" | "gaps" | "name">("score");

  const sorted = useMemo(() => {
    const copy = [...nodes];
    switch (sortBy) {
      case "score":
        copy.sort((a, b) => a.overall_score - b.overall_score);
        break;
      case "gaps":
        copy.sort(
          (a, b) =>
            b.uncovered_dimensions.length - a.uncovered_dimensions.length
        );
        break;
      case "name":
        copy.sort((a, b) => a.node_name.localeCompare(b.node_name));
        break;
    }
    return copy;
  }, [nodes, sortBy]);

  return (
    <div>
      {/* Sort controls */}
      <div className="mb-3 flex gap-2">
        <span className="text-[10px] text-zinc-500">Sort by:</span>
        {(["score", "gaps", "name"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setSortBy(s)}
            className={`text-[10px] ${
              sortBy === s
                ? "font-medium text-white"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {s === "score"
              ? "Lowest Score"
              : s === "gaps"
              ? "Most Gaps"
              : "Name"}
          </button>
        ))}
      </div>

      {/* Node table */}
      <div className="overflow-hidden rounded-lg border border-zinc-800">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-zinc-900 text-zinc-500">
              <th className="px-3 py-2 text-left font-medium">Asset</th>
              <th className="px-3 py-2 text-left font-medium">Type</th>
              <th className="px-3 py-2 text-center font-medium">
                Score
              </th>
              <th className="px-3 py-2 text-center font-medium">
                Coverage
              </th>
              <th className="px-3 py-2 text-center font-medium">Gaps</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((nc) => {
              const pct = Math.round(nc.coverage_percent);
              return (
                <tr
                  key={nc.node_id}
                  onClick={() => onNodeSelect?.(nc.node_id)}
                  className="cursor-pointer border-t border-zinc-800 transition-colors hover:bg-zinc-900/50"
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-zinc-300">
                      {nc.node_name}
                    </div>
                    {nc.platform && (
                      <div className="text-[10px] text-zinc-600">
                        {nc.platform}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-zinc-500">
                    {nc.node_type}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span
                      className="font-medium"
                      style={{
                        color: getCoverageColor(
                          Math.round(nc.overall_score * 100)
                        ),
                      }}
                    >
                      {Math.round(nc.overall_score * 100)}%
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-center gap-1.5">
                      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-800">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${pct}%`,
                            backgroundColor: getCoverageColor(pct),
                          }}
                        />
                      </div>
                      <span className="text-zinc-500">{pct}%</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-center text-zinc-500">
                    {nc.uncovered_dimensions.length}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function SummaryCard({
  label,
  value,
  total,
  color,
}: {
  label: string;
  value: number;
  total: number;
  color: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
      <div className="text-[10px] text-zinc-500">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="text-xl font-bold" style={{ color }}>
          {value}
        </span>
        <span className="text-xs text-zinc-600">/ {total}</span>
      </div>
    </div>
  );
}

function GapRow({
  gap,
  expanded = false,
  onNodeClick,
}: {
  gap: CoverageGap;
  expanded?: boolean;
  onNodeClick?: (nodeId: string) => void;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2">
      <div className="flex items-center gap-2">
        <div
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: SEVERITY_COLORS[gap.severity] }}
        />
        <span className="text-xs font-medium text-zinc-300">
          {gap.title}
        </span>
        <span className="ml-auto rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-500">
          {gap.category}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[10px] text-zinc-500">
        <button
          onClick={() => onNodeClick?.(gap.node_id)}
          className="text-blue-400 hover:underline"
        >
          {gap.node_name}
        </button>
        <span>&middot;</span>
        <span>{gap.node_type}</span>
        {gap.downstream_count > 0 && (
          <>
            <span>&middot;</span>
            <span>{gap.downstream_count} downstream</span>
          </>
        )}
      </div>
      {expanded && (
        <>
          <div className="mt-1.5 text-[10px] text-zinc-600">
            {gap.description}
          </div>
          <div className="mt-1 rounded bg-zinc-950 px-2 py-1 text-[10px] text-zinc-500">
            {gap.recommendation}
          </div>
        </>
      )}
    </div>
  );
}

function FilterPill({
  label,
  active,
  onClick,
  color,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  color?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-2.5 py-1 text-[10px] font-medium capitalize transition-colors ${
        active
          ? "bg-zinc-700 text-white"
          : "bg-zinc-900 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
      }`}
      style={active && color ? { backgroundColor: color } : undefined}
    >
      {label}
    </button>
  );
}
