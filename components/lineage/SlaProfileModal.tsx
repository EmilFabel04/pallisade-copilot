'use client';

import React from 'react';
import { X } from 'lucide-react';
import type { EffectiveSLAPolicy } from '@/types/sla';

interface SlaProfileModalProps {
  nodeId: string;
  nodeName: string;
  slaPolicy: EffectiveSLAPolicy;
  onClose: () => void;
  onEdit: (nodeId: string) => void;
}

const SOURCE_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  direct_override: { label: 'User-defined', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
  direct_profile: { label: 'User-defined', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
  imported_dbt: { label: 'Imported (dbt)', color: 'text-blue-400', bg: 'bg-blue-500/15' },
  branch: { label: 'Branch', color: 'text-amber-400', bg: 'bg-amber-500/15' },
  auto_discovered: { label: 'Auto-discovered', color: 'text-cyan-400', bg: 'bg-cyan-500/15' },
  criticality_default: { label: 'Auto-discovered', color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
  domain_default: { label: 'Auto-discovered', color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
  builtin: { label: 'Auto-discovered', color: 'text-zinc-400', bg: 'bg-zinc-500/15' },
};

function Row({ label, value }: { label: string; value: string | number | boolean | undefined | null }) {
  if (value === undefined || value === null) return null;
  return (
    <div className="flex items-center justify-between py-1.5 text-[13px]">
      <span className="text-[var(--muted)]">{label}</span>
      <span className="text-[var(--text)] font-medium">{String(value)}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  // Filter out null children (rows with no value)
  const filtered = React.Children.toArray(children).filter(Boolean);
  if (filtered.length === 0) return null;
  return (
    <div className="mb-4">
      <h4 className="text-[11px] uppercase tracking-wide text-[var(--muted)] font-semibold mb-1">{title}</h4>
      <div className="divide-y divide-[var(--subtle-border)]">{filtered}</div>
    </div>
  );
}

export function SlaProfileModal({ nodeId, nodeName, slaPolicy, onClose, onEdit }: SlaProfileModalProps) {
  const sourceInfo = SOURCE_LABELS[slaPolicy.source] || { label: slaPolicy.source, color: 'text-zinc-400', bg: 'bg-zinc-500/15' };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div
        className="relative w-full max-w-md rounded-xl border border-[var(--subtle-border)] bg-[var(--surface-raised)] shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--subtle-border)]">
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold text-[var(--text)] truncate">{nodeName}</h3>
            {slaPolicy.profileName && (
              <p className="text-[12px] text-[var(--muted)] mt-0.5">{slaPolicy.profileName}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Source badge */}
        <div className="px-5 pt-3">
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium ${sourceInfo.color} ${sourceInfo.bg}`}>
            {sourceInfo.label}
          </span>
        </div>

        {/* SLA categories */}
        <div className="px-5 py-4 max-h-[60vh] overflow-y-auto">
          <Section title="Freshness">
            <Row label="Enabled" value={slaPolicy.freshness?.enabled} />
            <Row label="Max hours" value={slaPolicy.freshness?.maxHours} />
            <Row label="Warning hours" value={slaPolicy.freshness?.warningHours} />
          </Section>

          <Section title="Volume">
            <Row label="Enabled" value={slaPolicy.volume?.enabled} />
            <Row label="Min rows" value={slaPolicy.volume?.minRows} />
            <Row label="Max rows" value={slaPolicy.volume?.maxRows} />
            <Row label="Growth rate threshold" value={slaPolicy.volume?.growthRateThreshold} />
          </Section>

          <Section title="Quality">
            <Row label="Enabled" value={slaPolicy.quality?.enabled} />
            <Row label="Max null rate" value={slaPolicy.quality?.maxNullRate} />
            <Row label="Max duplicate rate" value={slaPolicy.quality?.maxDuplicateRate} />
          </Section>

          <Section title="Schema">
            <Row label="Enabled" value={slaPolicy.schema?.enabled} />
            <Row label="Strictness" value={slaPolicy.schema?.strictness} />
            <Row label="Allow evolution" value={slaPolicy.schema?.allowEvolution} />
          </Section>

          <Section title="Anomaly">
            <Row label="Enabled" value={slaPolicy.anomaly?.enabled} />
            <Row label="Sensitivity" value={slaPolicy.anomaly?.sensitivity} />
            <Row label="Lookback days" value={slaPolicy.anomaly?.lookbackDays} />
          </Section>

          <Section title="Ingestion">
            <Row label="Sync lag tolerance (min)" value={slaPolicy.ingestion?.syncLagToleranceMinutes} />
            <Row label="Failure tolerance" value={slaPolicy.ingestion?.failureTolerance} />
            <Row label="Schema drift strictness" value={slaPolicy.ingestion?.schemaDriftStrictness} />
          </Section>

          <Section title="BI">
            <Row label="Freshness hours" value={slaPolicy.bi?.freshnessHours} />
            <Row label="Content health" value={slaPolicy.bi?.contentHealthEnabled} />
            <Row label="Upstream break strictness" value={slaPolicy.bi?.upstreamBreakStrictness} />
          </Section>

          <Section title="Orchestration">
            <Row label="Run latency (min)" value={slaPolicy.orchestration?.runLatencyMinutes} />
            <Row label="Schedule lag (min)" value={slaPolicy.orchestration?.scheduleLagMinutes} />
            <Row label="Failure tolerance" value={slaPolicy.orchestration?.failureTolerance} />
          </Section>

          <Section title="Transform">
            <Row label="Test failure tolerance" value={slaPolicy.transform?.testFailureTolerance} />
            <Row label="Model freshness hours" value={slaPolicy.transform?.modelFreshnessHours} />
          </Section>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-[var(--subtle-border)] flex justify-end">
          <button
            onClick={() => {
              onClose();
              onEdit(nodeId);
            }}
            className="px-4 py-1.5 text-[13px] font-medium rounded-lg bg-[var(--accent)] text-white hover:brightness-110 transition-all"
          >
            Edit
          </button>
        </div>
      </div>
    </div>
  );
}
