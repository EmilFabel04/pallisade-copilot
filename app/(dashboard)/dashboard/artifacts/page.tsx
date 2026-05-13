'use client';

import { useState } from 'react';
import { isFeatureEnabled } from '@/lib/feature-flags';
import { useArtefacts } from '@/hooks/useArtefacts';
import {
  ArtefactFilters,
  defaultFilters,
  type ArtefactFiltersValue,
} from '@/components/artefacts/ArtefactFilters';
import { ArtefactListCard } from '@/components/artefacts/ArtefactListCard';

export default function ArtifactsPage() {
  const flagOn = isFeatureEnabled('ff_artefacts_v2');
  const [filters, setFilters] = useState<ArtefactFiltersValue>(defaultFilters);
  const { artefacts, total, isLoading, error, refresh } = useArtefacts({
    search: filters.search || undefined,
    kinds: filters.kinds.length ? filters.kinds : undefined,
    statuses: filters.statuses.length ? filters.statuses : undefined,
    source: filters.source,
    pinnedOnly: filters.pinnedOnly,
  });

  if (!flagOn) {
    return (
      <div className="min-h-screen bg-[var(--surface-inset)]">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <h1 className="text-2xl font-semibold text-[var(--text)]">Artifacts</h1>
          <p className="mt-1 text-[14px] text-[var(--muted)]">
            The new artefacts surface is being built. Check back soon.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--surface-inset)]">
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        <header>
          <h1 className="text-2xl font-semibold text-[var(--text)]">Artifacts</h1>
          <p className="mt-1 text-[14px] text-[var(--muted)]">
            Typed deliverables produced by the agent — PRs, monitors, schema changes, queries, documents.
          </p>
        </header>

        <ArtefactFilters value={filters} onChange={setFilters} />

        {error ? (
          <div className="p-4 rounded-lg border border-rose-500/30 bg-rose-500/10 text-[13px] text-rose-300">
            {error}
          </div>
        ) : null}

        {isLoading ? (
          <div className="text-[13px] text-[var(--muted)]">Loading…</div>
        ) : artefacts.length === 0 ? (
          <div className="p-8 rounded-xl border border-dashed border-[var(--border)] text-center">
            <p className="text-[14px] text-[var(--muted)]">No artefacts match these filters.</p>
          </div>
        ) : (
          <>
            <div className="text-[12px] text-[var(--muted)]">
              {total} artefact{total === 1 ? '' : 's'}
            </div>
            <div className="space-y-2">
              {artefacts.map((a) => (
                <ArtefactListCard key={a.id} artefact={a} onChanged={refresh} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
