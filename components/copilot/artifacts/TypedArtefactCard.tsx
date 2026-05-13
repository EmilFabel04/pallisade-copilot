'use client';

import Link from 'next/link';
import type { TypedArtefactEnvelope } from '@/types/artefact-row';
import { ArtefactKindBadge } from '@/components/artefacts/ArtefactKindBadge';
import { ArtefactStatusBadge } from '@/components/artefacts/ArtefactStatusBadge';
import { ArtefactRiskBadge } from '@/components/artefacts/ArtefactRiskBadge';
import { ArtefactBody } from '@/components/artefacts/bodies';
import { envelopeToRow } from './typed-artefact-adapter';

interface TypedArtefactCardProps {
  envelope: TypedArtefactEnvelope;
  onApprove?: (env: TypedArtefactEnvelope) => void;
  onReject?: (env: TypedArtefactEnvelope) => void;
}

export function TypedArtefactCard({ envelope, onApprove, onReject }: TypedArtefactCardProps) {
  const row = envelopeToRow(envelope);
  const canConfirm = envelope.status === 'proposed';

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3 my-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <ArtefactKindBadge kind={envelope.kind} />
          <ArtefactStatusBadge status={envelope.status} />
          {envelope.riskLevel ? <ArtefactRiskBadge risk={envelope.riskLevel} /> : null}
        </div>
        <Link
          href={`/dashboard/artifacts/${envelope.artefactId}`}
          className="text-[12px] text-[var(--muted)] hover:text-[var(--text)]"
        >
          Open ↗
        </Link>
      </div>

      <h3 className="text-[15px] font-medium text-[var(--text)]">{envelope.title}</h3>
      {envelope.summary ? (
        <p className="text-[13px] text-[var(--muted)]">{envelope.summary}</p>
      ) : null}

      <ArtefactBody artefact={row} />

      {canConfirm ? (
        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => onApprove?.(envelope)}
            className="px-3 py-1.5 rounded-md bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-[13px]"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => onReject?.(envelope)}
            className="px-3 py-1.5 rounded-md bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 text-[13px]"
          >
            Reject
          </button>
        </div>
      ) : null}
    </div>
  );
}
