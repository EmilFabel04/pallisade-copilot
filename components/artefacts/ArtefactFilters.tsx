'use client';

import { useState } from 'react';
import type { ArtifactKind, ArtifactStatus } from '@prisma/client';
import { ALL_KINDS, KIND_META } from '@/lib/artefacts/kinds';
import type { ArtefactSourceFilter } from '@/hooks/useArtefacts';

const DEFAULT_STATUSES: ArtifactStatus[] = ['proposed', 'approved', 'applied', 'open', 'resolved'];
const ALL_STATUSES: ArtifactStatus[] = [
  'proposed', 'approved', 'applied', 'rejected', 'failed', 'archived', 'open', 'resolved',
];

export interface ArtefactFiltersValue {
  search: string;
  kinds: ArtifactKind[];
  statuses: ArtifactStatus[];
  source: ArtefactSourceFilter;
  pinnedOnly: boolean;
}

export function defaultFilters(): ArtefactFiltersValue {
  return { search: '', kinds: [], statuses: DEFAULT_STATUSES, source: 'all', pinnedOnly: false };
}

interface ArtefactFiltersProps {
  value: ArtefactFiltersValue;
  onChange: (v: ArtefactFiltersValue) => void;
}

export function ArtefactFilters({ value, onChange }: ArtefactFiltersProps) {
  const [showAllStatuses, setShowAllStatuses] = useState(false);

  function toggleKind(k: ArtifactKind) {
    onChange({
      ...value,
      kinds: value.kinds.includes(k) ? value.kinds.filter((x) => x !== k) : [...value.kinds, k],
    });
  }

  function toggleStatus(s: ArtifactStatus) {
    onChange({
      ...value,
      statuses: value.statuses.includes(s)
        ? value.statuses.filter((x) => x !== s)
        : [...value.statuses, s],
    });
  }

  const visibleStatuses = showAllStatuses ? ALL_STATUSES : DEFAULT_STATUSES;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          value={value.search}
          onChange={(e) => onChange({ ...value, search: e.target.value })}
          placeholder="Search artefacts…"
          className="flex-1 min-w-[200px] px-3 py-1.5 rounded-md bg-[var(--surface)] border border-[var(--border)] text-[14px] text-[var(--text)] placeholder:text-[var(--muted)] focus:outline-none focus:border-[var(--hover-bg)]"
        />
        <select
          value={value.source}
          onChange={(e) => onChange({ ...value, source: e.target.value as ArtefactSourceFilter })}
          className="px-2 py-1.5 rounded-md bg-[var(--surface)] border border-[var(--border)] text-[13px] text-[var(--text)]"
        >
          <option value="all">All sources</option>
          <option value="agent">Agent-produced</option>
          <option value="user">User-saved</option>
        </select>
        <label className="flex items-center gap-1.5 text-[13px] text-[var(--muted)] cursor-pointer">
          <input
            type="checkbox"
            checked={value.pinnedOnly}
            onChange={(e) => onChange({ ...value, pinnedOnly: e.target.checked })}
          />
          Pinned only
        </label>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[12px] text-[var(--muted)] mr-1">Kind:</span>
        {ALL_KINDS.map((k) => {
          const active = value.kinds.includes(k);
          return (
            <button
              key={k}
              type="button"
              onClick={() => toggleKind(k)}
              className={`px-2 py-0.5 rounded-md text-[11px] font-medium border transition-colors ${
                active
                  ? 'border-[var(--hover-bg)] bg-[var(--hover-bg)] text-[var(--text)]'
                  : 'border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)]'
              }`}
            >
              {KIND_META[k].label}
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[12px] text-[var(--muted)] mr-1">Status:</span>
        {visibleStatuses.map((s) => {
          const active = value.statuses.includes(s);
          return (
            <button
              key={s}
              type="button"
              onClick={() => toggleStatus(s)}
              className={`px-2 py-0.5 rounded-md text-[11px] font-medium border uppercase tracking-wide ${
                active
                  ? 'border-[var(--hover-bg)] bg-[var(--hover-bg)] text-[var(--text)]'
                  : 'border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)]'
              }`}
            >
              {s}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setShowAllStatuses((v) => !v)}
          className="px-2 py-0.5 text-[11px] text-[var(--muted)] hover:text-[var(--text)]"
        >
          {showAllStatuses ? 'Less' : 'More…'}
        </button>
      </div>
    </div>
  );
}
