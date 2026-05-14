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

const STATUS_TINT: Record<string, string> = {
  draft:    'text-zinc-300 bg-zinc-500/10',
  proposed: 'text-amber-300 bg-amber-500/10',
  approved: 'text-blue-300 bg-blue-500/10',
  applied:  'text-emerald-300 bg-emerald-500/10',
  rejected: 'text-rose-300 bg-rose-500/10',
  failed:   'text-rose-300 bg-rose-500/10',
  archived: 'text-zinc-400 bg-zinc-500/10',
  open:     'text-amber-300 bg-amber-500/10',
  resolved: 'text-emerald-300 bg-emerald-500/10',
};

const RISK_TINT: Record<string, string> = {
  LOW:    'text-emerald-300 bg-emerald-500/10',
  MEDIUM: 'text-amber-300 bg-amber-500/10',
  HIGH:   'text-rose-300 bg-rose-500/10',
};

export function TypedArtefactCard({ envelope, onApprove, onReject }: TypedArtefactCardProps) {
  const row = envelopeToRow(envelope);
  const canConfirm = envelope.status === 'proposed';
  const kindMeta = KIND_META[envelope.kind];

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] my-2 overflow-hidden">
      {/* HEADER */}
      <div className="px-4 pt-4 pb-3 border-b border-[var(--border)]/60">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium ${kindMeta.tint}`}
                style={{ backgroundColor: 'var(--hover-bg)' }}
              >
                {kindMeta.label}
              </span>
              <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium uppercase tracking-wide ${STATUS_TINT[envelope.status] || 'text-zinc-300 bg-zinc-500/10'}`}>
                {envelope.status}
              </span>
              {envelope.riskLevel ? (
                <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider ${RISK_TINT[envelope.riskLevel] || ''}`}>
                  {envelope.riskLevel}
                </span>
              ) : null}
            </div>
            <h3 className="text-[15px] font-medium text-[var(--text)] leading-tight">
              {envelope.title}
            </h3>
            {envelope.summary ? (
              <p className="text-[12.5px] text-[var(--muted)]">{envelope.summary}</p>
            ) : null}
          </div>

          <Link
            href={`/dashboard/artifacts/${envelope.artefactId}`}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[12px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--surface-inset)] shrink-0"
          >
            Open
            <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      </div>

      {/* BODY — compact inline version for MONITOR; fall back to full ArtefactBody otherwise */}
      <div className="px-4 py-3">
        {envelope.kind === 'MONITOR' ? (
          <CompactMonitorBody payload={envelope.payload} />
        ) : (
          <ArtefactBody artefact={row} />
        )}
      </div>

      {/* FOOTER */}
      {canConfirm ? (
        <div className="px-4 pb-3 pt-1 flex items-center justify-end gap-2 border-t border-[var(--border)]/60">
          <button
            type="button"
            onClick={() => onReject?.(envelope)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[12px] text-[var(--muted)] hover:text-rose-300 hover:bg-rose-500/10"
          >
            <X className="h-3 w-3" />
            Reject
          </button>
          <button
            type="button"
            onClick={() => onApprove?.(envelope)}
            className="inline-flex items-center gap-1 px-3 py-1 rounded-md text-[12px] font-medium text-emerald-100 bg-emerald-500/20 hover:bg-emerald-500/30"
          >
            <Check className="h-3 w-3" />
            Approve
          </button>
        </div>
      ) : null}
    </div>
  );
}

// Compact, chat-friendly MONITOR body. The full MonitorArtifactBody (used on
// the detail page) shows a side-by-side before/after JSON diff which is too
// heavy for inline rendering. This version surfaces the headline facts.
function CompactMonitorBody({ payload }: { payload: ArtifactPayload }) {
  if (payload.kind !== 'MONITOR') return null;
  const diff = payload.configDiff as
    | { before?: unknown; after?: unknown; operation?: string }
    | undefined;
  const operation = diff?.operation;
  const after = (diff?.after ?? {}) as Record<string, any>;

  return (
    <div className="space-y-3 text-[13px]">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
        <Row icon={<Activity className="h-3.5 w-3.5" />} label="Kind">
          <span className="text-[var(--text)]">
            {prettyKind(payload.monitorKind)}
          </span>
        </Row>
        {payload.targetFqn ? (
          <Row icon={<Target className="h-3.5 w-3.5" />} label="Target">
            <code className="text-[12px] text-indigo-300 break-all">{payload.targetFqn}</code>
          </Row>
        ) : null}
      </div>

      {operation === 'delete' ? (
        <div className="text-[12.5px] text-rose-300 rounded-md bg-rose-500/10 px-3 py-2">
          Monitor deleted.
        </div>
      ) : Object.keys(after).length > 0 ? (
        <div className="text-[12px] font-mono text-[var(--text)] bg-[var(--surface-inset)] rounded-md px-3 py-2">
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
      <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wider text-[var(--muted)] shrink-0">
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
