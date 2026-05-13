'use client';

import Link from 'next/link';
import type { ArtefactRow } from '@/types/artefact-row';
import { ArtefactKindBadge } from './ArtefactKindBadge';
import { ArtefactStatusBadge } from './ArtefactStatusBadge';
import { ArtefactRiskBadge } from './ArtefactRiskBadge';
import { ArtefactRowActions } from './ArtefactRowActions';
import { ArtefactPreview } from './previews';

interface ArtefactListCardProps {
  artefact: ArtefactRow;
  onChanged: () => void;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

export function ArtefactListCard({ artefact, onChanged }: ArtefactListCardProps) {
  return (
    <Link
      href={`/dashboard/artifacts/${artefact.id}`}
      className="block rounded-xl border border-[var(--border)] hover:border-[var(--hover-bg)] transition-colors bg-[var(--surface)] px-4 py-3"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <ArtefactKindBadge kind={artefact.kind} subtype={artefact.subtype} />
            <ArtefactStatusBadge status={artefact.status} />
            {artefact.riskLevel ? <ArtefactRiskBadge risk={artefact.riskLevel} /> : null}
            {artefact.isPinned ? <span className="text-[11px] text-amber-400">Pinned</span> : null}
          </div>
          <h3 className="text-[15px] font-medium text-[var(--text)] truncate">{artefact.title}</h3>
          <div className="mt-1">
            <ArtefactPreview artefact={artefact} />
          </div>
        </div>
        <div className="text-[12px] text-[var(--muted)] whitespace-nowrap pt-0.5">
          {formatTime(artefact.createdAt)}
        </div>
      </div>
      <div className="mt-2 flex items-center justify-end">
        <ArtefactRowActions artefact={artefact} onChanged={onChanged} />
      </div>
    </Link>
  );
}
