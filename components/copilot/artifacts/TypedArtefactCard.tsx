'use client';

import Link from 'next/link';
import { Activity, Check, ExternalLink, Target, X } from 'lucide-react';
import type { TypedArtefactEnvelope } from '@/types/artefact-row';
import type { ArtifactPayload } from '@/types/artifact';
import { ArtefactBody } from '@/components/artefacts/bodies';
import { envelopeToRow } from './typed-artefact-adapter';
import { KIND_META } from '@/lib/artefacts/kinds';

interface TypedArtefactCardProps {
  envelope: TypedArtefactEnvelope;
  onApprove?: (env: TypedArtefactEnvelope) => void;
  onReject?: (env: TypedArtefactEnvelope) => void;
}

const STATUS_TONE: Record<string, { fg: string; bg: string }> = {
  draft:    { fg: 'var(--neutral-fg)', bg: 'var(--neutral-bg)' },
  proposed: { fg: 'var(--warning-fg)', bg: 'var(--warning-bg)' },
  approved: { fg: 'var(--info-fg)',    bg: 'var(--info-bg)' },
  applied:  { fg: 'var(--success-fg)', bg: 'var(--success-bg)' },
  rejected: { fg: 'var(--danger-fg)',  bg: 'var(--danger-bg)' },
  failed:   { fg: 'var(--danger-fg)',  bg: 'var(--danger-bg)' },
  archived: { fg: 'var(--neutral-fg)', bg: 'var(--neutral-bg)' },
  open:     { fg: 'var(--warning-fg)', bg: 'var(--warning-bg)' },
  resolved: { fg: 'var(--success-fg)', bg: 'var(--success-bg)' },
};

const RISK_TONE: Record<string, { fg: string; bg: string }> = {
  LOW:    { fg: 'var(--success-fg)', bg: 'var(--success-bg)' },
  MEDIUM: { fg: 'var(--warning-fg)', bg: 'var(--warning-bg)' },
  HIGH:   { fg: 'var(--danger-fg)',  bg: 'var(--danger-bg)' },
};

export function TypedArtefactCard({ envelope, onApprove, onReject }: TypedArtefactCardProps) {
  const row = envelopeToRow(envelope);
  const canConfirm = envelope.status === 'proposed';
  const kindMeta = KIND_META[envelope.kind];
  const statusTone = STATUS_TONE[envelope.status] || STATUS_TONE.draft;
  const riskTone = envelope.riskLevel ? RISK_TONE[envelope.riskLevel] : null;

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] my-2 overflow-hidden max-w-[640px]">
      {/* HEADER */}
      <div className="px-3 pt-3 pb-2.5 border-b border-[var(--border)]/60">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span
                className="inline-flex items-center px-1.5 py-0.5 rounded text-[10.5px] font-medium"
                style={{ color: 'var(--neutral-fg)', backgroundColor: 'var(--neutral-bg)' }}
              >
                {kindMeta.label}
              </span>
              <span
                className="inline-flex items-center px-1.5 py-0.5 rounded text-[10.5px] font-medium uppercase tracking-wide"
                style={{ color: statusTone.fg, backgroundColor: statusTone.bg }}
              >
                {envelope.status}
              </span>
              {riskTone ? (
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: riskTone.fg, backgroundColor: riskTone.bg }}
                >
                  {envelope.riskLevel}
                </span>
              ) : null}
            </div>
            <h3 className="text-[14px] font-medium text-[var(--text)] leading-tight">
              {envelope.title}
            </h3>
            {envelope.summary ? (
              <p className="text-[12px] text-[var(--muted)]">{envelope.summary}</p>
            ) : null}
          </div>

          <Link
            href={`/dashboard/artifacts/${envelope.artefactId}`}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11.5px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)] shrink-0"
          >
            Open
            <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      </div>

      {/* BODY — compact inline version for MONITOR; fall back to full ArtefactBody otherwise */}
      <div className="px-3 py-2.5">
        {envelope.kind === 'MONITOR' ? (
          <CompactMonitorBody payload={envelope.payload} />
        ) : (
          <ArtefactBody artefact={row} />
        )}
      </div>

      {/* FOOTER */}
      {canConfirm ? (
        <div className="px-3 pb-2.5 pt-1.5 flex items-center justify-end gap-2 border-t border-[var(--border)]/60">
          <button
            type="button"
            onClick={() => onReject?.(envelope)}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11.5px] text-[var(--muted)] hover:bg-[var(--hover-bg)]"
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--danger-fg)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--muted)'; }}
          >
            <X className="h-3 w-3" />
            Reject
          </button>
          <button
            type="button"
            onClick={() => onApprove?.(envelope)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11.5px] font-medium"
            style={{ color: 'var(--success-fg)', backgroundColor: 'var(--success-bg)' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--success-bg-strong)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--success-bg)'; }}
          >
            <Check className="h-3 w-3" />
            Approve
          </button>
        </div>
      ) : null}
    </div>
  );
}

function CompactMonitorBody({ payload }: { payload: ArtifactPayload }) {
  if (payload.kind !== 'MONITOR') return null;
  const diff = payload.configDiff as
    | { before?: unknown; after?: unknown; operation?: string }
    | undefined;
  const operation = diff?.operation;
  const after = (diff?.after ?? {}) as Record<string, any>;

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5">
        <Row icon={<Activity className="h-3 w-3" />} label="Kind">
          <span className="text-[12px] text-[var(--text)]">
            {prettyKind(payload.monitorKind)}
          </span>
        </Row>
        {payload.targetFqn ? (
          <Row icon={<Target className="h-3 w-3" />} label="Target">
            <code className="text-[11.5px] text-[var(--code-fg)] break-all">{payload.targetFqn}</code>
          </Row>
        ) : null}
      </div>

      {operation === 'delete' ? (
        <div
          className="text-[11.5px] rounded-md px-2.5 py-1.5"
          style={{ color: 'var(--danger-fg)', backgroundColor: 'var(--danger-bg)' }}
        >
          Monitor deleted.
        </div>
      ) : Object.keys(after).length > 0 ? (
        <div className="text-[11.5px] font-mono text-[var(--text)] bg-[var(--surface-inset)] rounded-md px-2.5 py-1.5">
          {summariseConfig(after)}
        </div>
      ) : null}
    </div>
  );
}

function Row({
  icon, label, children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2 min-w-0">
      <span className="inline-flex items-center gap-1 text-[10.5px] uppercase tracking-wider text-[var(--muted)] shrink-0">
        {icon}
        {label}
      </span>
      <span className="min-w-0 flex-1">{children}</span>
    </div>
  );
}

function prettyKind(raw: string): string {
  return raw.replace(/_/g, ' ').toLowerCase().replace(/(^|\s)\S/g, t => t.toUpperCase());
}

function summariseConfig(config: Record<string, any>): string {
  const entries = Object.entries(config);
  if (entries.length === 0) return '—';
  return entries
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(' · ');
}
