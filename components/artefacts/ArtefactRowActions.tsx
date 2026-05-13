'use client';

import { useState } from 'react';
import type { ArtefactRow } from '@/types/artefact-row';

interface ArtefactRowActionsProps {
  artefact: ArtefactRow;
  onChanged: () => void;
}

export function ArtefactRowActions({ artefact, onChanged }: ArtefactRowActionsProps) {
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

  async function del() {
    if (!window.confirm('Delete this artefact?')) return;
    setBusy('delete');
    try {
      await fetch(`/api/artifacts/${artefact.id}`, { method: 'DELETE' });
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  const canApprove = artefact.status === 'proposed';
  const canArchive =
    artefact.status === 'proposed' ||
    artefact.status === 'approved' ||
    artefact.status === 'applied' ||
    artefact.status === 'rejected' ||
    artefact.status === 'failed' ||
    artefact.status === 'open' ||
    artefact.status === 'resolved';

  return (
    <div
      className="flex items-center gap-2 text-[12px]"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {canApprove ? (
        <>
          <button
            disabled={!!busy}
            onClick={() => patch({ status: 'approved' })}
            className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-emerald-400 disabled:opacity-40"
          >
            Approve
          </button>
          <button
            disabled={!!busy}
            onClick={() => patch({ status: 'rejected' })}
            className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-rose-400 disabled:opacity-40"
          >
            Reject
          </button>
        </>
      ) : null}
      <button
        disabled={!!busy}
        onClick={() => patch({ isPinned: !artefact.isPinned })}
        className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-[var(--muted)] disabled:opacity-40"
        aria-label={artefact.isPinned ? 'Unpin' : 'Pin'}
      >
        {artefact.isPinned ? 'Unpin' : 'Pin'}
      </button>
      {canArchive ? (
        <button
          disabled={!!busy}
          onClick={() => patch({ status: 'archived' })}
          className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-[var(--muted)] disabled:opacity-40"
        >
          Archive
        </button>
      ) : null}
      <button
        disabled={!!busy}
        onClick={del}
        className="px-2 py-1 rounded-md hover:bg-[var(--hover-bg)] text-[var(--muted)] disabled:opacity-40"
      >
        Delete
      </button>
    </div>
  );
}
