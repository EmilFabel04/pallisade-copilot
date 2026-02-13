"use client";

/**
 * CoverageOverlay
 *
 * A ReactFlow-compatible overlay that augments lineage graph nodes
 * with coverage score badges and color-coded borders. Designed to
 * work alongside the existing DataAssetNode and ToolNode components.
 *
 * Usage: wrap the lineage graph's ReactFlow instance and pass in
 * the coverage report data. The overlay adds visual indicators
 * without modifying the underlying node components.
 */

import React, { useMemo } from "react";
import type {
  NodeCoverage,
  CoverageReportSummary,
  CoverageGap,
  GapSeverity,
} from "./types";
import {
  getCoverageColor,
  SEVERITY_COLORS,
  CATEGORY_COLORS,
  CATEGORY_LABELS,
} from "./types";
import type { CoverageCategory } from "./types";

// ---------------------------------------------------------------------------
// CoverageScoreBadge — small badge overlaid on a lineage node
// ---------------------------------------------------------------------------

interface CoverageScoreBadgeProps {
  coverage: NodeCoverage;
  onClick?: (nodeId: string) => void;
}

export function CoverageScoreBadge({
  coverage,
  onClick,
}: CoverageScoreBadgeProps) {
  const percent = Math.round(coverage.coverage_percent);
  const color = getCoverageColor(percent);
  const gapCount = coverage.uncovered_dimensions.length;

  return (
    <div
      className="absolute -top-2 -right-2 z-10 cursor-pointer"
      onClick={() => onClick?.(coverage.node_id)}
      title={`Coverage: ${percent}% (${gapCount} gaps)`}
    >
      <div
        className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold text-white shadow-md"
        style={{ backgroundColor: color }}
      >
        <span>{percent}%</span>
        {gapCount > 0 && (
          <span className="rounded-full bg-white/20 px-1">{gapCount}</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CoverageSummaryBar — top-of-page summary bar
// ---------------------------------------------------------------------------

interface CoverageSummaryBarProps {
  report: CoverageReportSummary;
  onCategoryClick?: (category: CoverageCategory) => void;
}

export function CoverageSummaryBar({
  report,
  onCategoryClick,
}: CoverageSummaryBarProps) {
  const overallPercent = Math.round(report.overall_score * 100);
  const overallColor = getCoverageColor(overallPercent);

  return (
    <div className="flex items-center gap-4 rounded-lg border border-zinc-800 bg-zinc-900/80 px-4 py-2 text-xs backdrop-blur">
      {/* Overall score */}
      <div className="flex items-center gap-2">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold text-white"
          style={{ backgroundColor: overallColor }}
        >
          {overallPercent}
        </div>
        <div>
          <div className="font-medium text-zinc-300">Coverage</div>
          <div className="text-zinc-500">
            {report.total_nodes} assets
          </div>
        </div>
      </div>

      <div className="h-6 w-px bg-zinc-700" />

      {/* Category breakdown */}
      <div className="flex gap-3">
        {(
          Object.entries(report.category_scores) as [
            CoverageCategory,
            number,
          ][]
        ).map(([cat, score]) => {
          const pct = Math.round(score * 100);
          return (
            <button
              key={cat}
              onClick={() => onCategoryClick?.(cat)}
              className="flex items-center gap-1.5 rounded px-1.5 py-0.5 transition-colors hover:bg-zinc-800"
              title={`${CATEGORY_LABELS[cat]}: ${pct}%`}
            >
              <div
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: CATEGORY_COLORS[cat] }}
              />
              <span className="text-zinc-400">
                {CATEGORY_LABELS[cat]}
              </span>
              <span
                className="font-medium"
                style={{ color: getCoverageColor(pct) }}
              >
                {pct}%
              </span>
            </button>
          );
        })}
      </div>

      <div className="h-6 w-px bg-zinc-700" />

      {/* Gap counts */}
      <div className="flex gap-2">
        {report.gaps_summary.critical > 0 && (
          <span
            className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-white"
            style={{ backgroundColor: SEVERITY_COLORS.critical }}
          >
            {report.gaps_summary.critical} Critical
          </span>
        )}
        {report.gaps_summary.high > 0 && (
          <span
            className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-white"
            style={{ backgroundColor: SEVERITY_COLORS.high }}
          >
            {report.gaps_summary.high} High
          </span>
        )}
        {report.gaps_summary.medium > 0 && (
          <span
            className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
            style={{
              backgroundColor: SEVERITY_COLORS.medium,
              color: "#1a1a1a",
            }}
          >
            {report.gaps_summary.medium} Medium
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CoverageGapPanel — side panel showing gap details
// ---------------------------------------------------------------------------

interface CoverageGapPanelProps {
  gaps: CoverageGap[];
  onClose: () => void;
  onGapClick?: (gap: CoverageGap) => void;
}

export function CoverageGapPanel({
  gaps,
  onClose,
  onGapClick,
}: CoverageGapPanelProps) {
  const grouped = useMemo(() => {
    const groups: Record<GapSeverity, CoverageGap[]> = {
      critical: [],
      high: [],
      medium: [],
      low: [],
      info: [],
    };
    for (const gap of gaps) {
      groups[gap.severity].push(gap);
    }
    return groups;
  }, [gaps]);

  return (
    <div className="flex h-full w-80 flex-col border-l border-zinc-800 bg-zinc-950">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <h3 className="text-sm font-semibold text-zinc-200">
          Coverage Gaps ({gaps.length})
        </h3>
        <button
          onClick={onClose}
          className="text-zinc-500 hover:text-zinc-300"
        >
          &times;
        </button>
      </div>

      {/* Gap list */}
      <div className="flex-1 overflow-y-auto p-2">
        {(["critical", "high", "medium", "low", "info"] as GapSeverity[]).map(
          (severity) => {
            const gapList = grouped[severity];
            if (gapList.length === 0) return null;
            return (
              <div key={severity} className="mb-3">
                <div className="mb-1 flex items-center gap-2 px-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                  <div
                    className="h-1.5 w-1.5 rounded-full"
                    style={{
                      backgroundColor: SEVERITY_COLORS[severity],
                    }}
                  />
                  {severity} ({gapList.length})
                </div>
                {gapList.map((gap, i) => (
                  <button
                    key={`${gap.node_id}-${gap.dimension}-${i}`}
                    onClick={() => onGapClick?.(gap)}
                    className="mb-1 w-full rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-left transition-colors hover:border-zinc-700 hover:bg-zinc-800/80"
                  >
                    <div className="text-xs font-medium text-zinc-300">
                      {gap.title}
                    </div>
                    <div className="mt-0.5 text-[10px] text-zinc-500">
                      {gap.node_name}
                    </div>
                    <div className="mt-1 text-[10px] text-zinc-600 line-clamp-2">
                      {gap.recommendation}
                    </div>
                  </button>
                ))}
              </div>
            );
          }
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// NodeCoverageDetail — detailed view for a single node
// ---------------------------------------------------------------------------

interface NodeCoverageDetailProps {
  coverage: NodeCoverage;
  gaps: CoverageGap[];
  onClose: () => void;
}

export function NodeCoverageDetail({
  coverage,
  gaps,
  onClose,
}: NodeCoverageDetailProps) {
  const percent = Math.round(coverage.coverage_percent);

  return (
    <div className="flex h-full w-80 flex-col border-l border-zinc-800 bg-zinc-950">
      {/* Header */}
      <div className="border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-zinc-200">
            Node Coverage
          </h3>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-300"
          >
            &times;
          </button>
        </div>
        <div className="mt-1 text-xs text-zinc-500">
          {coverage.node_name}
        </div>
      </div>

      {/* Score ring */}
      <div className="flex items-center gap-4 border-b border-zinc-800 px-4 py-3">
        <div
          className="flex h-14 w-14 items-center justify-center rounded-full text-lg font-bold text-white"
          style={{ backgroundColor: getCoverageColor(percent) }}
        >
          {percent}%
        </div>
        <div className="text-xs">
          <div className="text-zinc-300">
            {coverage.covered_count} / {coverage.applicable_dimensions}{" "}
            dimensions covered
          </div>
          <div className="mt-1 text-zinc-500">
            {coverage.node_type} &middot; {coverage.criticality} criticality
          </div>
        </div>
      </div>

      {/* Category breakdown */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="mb-3 text-xs font-semibold text-zinc-400">
          Category Scores
        </div>
        {(
          Object.entries(coverage.category_scores) as [
            string,
            { score: number; dimensions_covered: number; dimensions_total: number }
          ][]
        ).map(([cat, cs]) => {
          const catKey = cat as CoverageCategory;
          const pct = Math.round(cs.score * 100);
          return (
            <div key={cat} className="mb-2">
              <div className="flex items-center justify-between text-xs">
                <span className="text-zinc-400">
                  {CATEGORY_LABELS[catKey] || cat}
                </span>
                <span style={{ color: getCoverageColor(pct) }}>
                  {cs.dimensions_covered}/{cs.dimensions_total}
                </span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${pct}%`,
                    backgroundColor:
                      CATEGORY_COLORS[catKey] || "#6B7280",
                  }}
                />
              </div>
            </div>
          );
        })}

        {/* Uncovered dimensions */}
        {coverage.uncovered_dimensions.length > 0 && (
          <>
            <div className="mb-2 mt-4 text-xs font-semibold text-zinc-400">
              Missing Coverage ({coverage.uncovered_dimensions.length})
            </div>
            {coverage.uncovered_dimensions.map((dim) => (
              <div
                key={dim}
                className="mb-1 rounded border border-red-900/30 bg-red-950/20 px-2 py-1 text-[10px] text-red-400"
              >
                {dim.replace(/_/g, " ")}
              </div>
            ))}
          </>
        )}

        {/* Node-specific gaps */}
        {gaps.length > 0 && (
          <>
            <div className="mb-2 mt-4 text-xs font-semibold text-zinc-400">
              Gaps ({gaps.length})
            </div>
            {gaps.map((gap, i) => (
              <div
                key={`${gap.dimension}-${i}`}
                className="mb-2 rounded border border-zinc-800 bg-zinc-900 p-2"
              >
                <div className="flex items-center gap-1.5">
                  <div
                    className="h-1.5 w-1.5 rounded-full"
                    style={{
                      backgroundColor: SEVERITY_COLORS[gap.severity],
                    }}
                  />
                  <span className="text-[10px] font-medium text-zinc-300">
                    {gap.title}
                  </span>
                </div>
                <div className="mt-1 text-[10px] text-zinc-600">
                  {gap.recommendation}
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
