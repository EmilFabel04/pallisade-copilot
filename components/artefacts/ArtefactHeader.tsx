'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { ArtefactRow } from '@/types/artefact-row';
import { ArtefactKindBadge } from './ArtefactKindBadge';
import { ArtefactStatusBadge } from './ArtefactStatusBadge';
import { ArtefactRiskBadge } from './ArtefactRiskBadge';

interface ArtefactHeaderProps {
  artefact: ArtefactRow;
  onChanged: () => void;
}

function externalLink(ref: Record<string, unknown> | null): { href: string; label: string } | null {
  if (!ref) return null;
  if (typeof ref.pr_url === 'string') {
    return { href: ref.pr_url as string, label: `PR${ref.pr_number ? ` #${ref.pr_number}` : ''}` };
  }
  if (typeof ref.ticket_url === 'string') {
    return { href: ref.ticket_url as string, label: 'Ticket' };
  }
  if (typeof ref.url === 'string') {
    return { href: ref.url as string, label: 'Open' };
  }
  return null;
}

export function ArtefactHeader({ artefact, onChanged }: ArtefactHeaderProps) {
  const [busy, setBusy] = useState<string | null>(null);

  async function patch(body: Record<string, unknown>) {
    setBusy('patch');
    try {
      await fetch(`/api/artifacts/${artefact.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  const ext = externalLink(artefact.externalRef);
  const canApprove = artefact.status === 'proposed';
  const canArchive = artefact.status !== 'draft' && artefact.status !== 'archived';

  return (
    <header className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <ArtefactKindBadge kind={artefact.kind} subtype={artefact.subtype} />
        <ArtefactStatusBadge status={artefact.status} />
        {artefact.riskLevel ? <ArtefactRiskBadge risk={artefact.riskLevel} /> : null}
        {artefact.integration ? (
          <span className="text-[11px] text-[var(--muted)]">
            via {artefact.integration.type}
          </span>
        ) : null}
        {artefact.isPinned ? <span className="text-[11px] text-amber-400">Pinned</span> : null}
      </div>

      <h1 className="text-[20px] font-semibold text-[var(--text)] break-words">{artefact.title}</h1>

      {artefact.summary ? (
        <p className="text-[14px] text-[var(--muted)] whitespace-pre-wrap">{artefact.summary}</p>
      ) : null}

      {artefact.rollbackHint ? (
        <div className="text-[12px] text-[var(--muted)] rounded-md bg-[var(--hover-bg)] px-3 py-2">
          <span className="font-medium text-[var(--text)]">Rollback: </span>
          {artefact.rollbackHint}
        </div>
      ) : null}

      <div className="flex items-center gap-2 flex-wrap pt-1">
        {ext ? (
          <a
            href={ext.href}
            target="_blank"
            rel="noreferrer"
            className="px-3 py-1.5 rounded-md bg-[var(--hover-bg)] hover:bg-[var(--border)] text-[13px] text-[var(--text)]"
          >
            Open {ext.label} ↗
          </a>
        ) : null}
        {artefact.sourceSession ? (
          <Link
            href={`/dashboard/assistant?session=${artefact.sourceSessionId}`}
            className="px-3 py-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[13px] text-[var(--muted)] hover:text-[var(--text)]"
          >
            Open source session
          </Link>
        ) : null}
        {canApprove ? (
          <>
            <button
              disabled={!!busy}
              onClick={() => patch({ status: 'approved' })}
              className="px-3 py-1.5 rounded-md bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-[13px] disabled:opacity-50"
            >
              Approve
            </button>
            <button
              disabled={!!busy}
              onClick={() => patch({ status: 'rejected' })}
              className="px-3 py-1.5 rounded-md bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 text-[13px] disabled:opacity-50"
            >
              Reject
            </button>
          </>
        ) : null}
        <button
          disabled={!!busy}
          onClick={() => patch({ isPinned: !artefact.isPinned })}
          className="px-3 py-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[13px] text-[var(--muted)] hover:text-[var(--text)] disabled:opacity-50"
        >
          {artefact.isPinned ? 'Unpin' : 'Pin'}
        </button>
        {canArchive ? (
          <button
            disabled={!!busy}
            onClick={() => patch({ status: 'archived' })}
            className="px-3 py-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[13px] text-[var(--muted)] hover:text-[var(--text)] disabled:opacity-50"
          >
            Archive
          </button>
        ) : null}
      </div>
    </header>
  );
}
