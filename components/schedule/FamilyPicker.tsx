'use client';

import { cn } from '@/lib/utils';
import type { FamilyEligibility } from '@/types/health-watch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FamilyPickerProps {
  families: FamilyEligibility[];
  selected: string[];
  onToggle: (familyKey: string) => void;
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Skeleton placeholder
// ---------------------------------------------------------------------------

function SkeletonCard() {
  return (
    <div className="p-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] animate-pulse">
      <div className="flex items-start gap-3">
        <div className="w-4 h-4 rounded bg-[var(--muted)]/20 shrink-0 mt-0.5" />
        <div className="flex-1 space-y-2">
          <div className="h-3 w-28 rounded bg-[var(--muted)]/20" />
          <div className="h-2.5 w-48 rounded bg-[var(--muted)]/15" />
          <div className="flex gap-2 mt-1">
            <div className="h-4 w-16 rounded bg-[var(--muted)]/10" />
            <div className="h-4 w-20 rounded bg-[var(--muted)]/10" />
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Checkbox
// ---------------------------------------------------------------------------

function Checkbox({ checked, disabled }: { checked: boolean; disabled?: boolean }) {
  return (
    <div
      className={cn(
        'w-4 h-4 rounded border flex items-center justify-center shrink-0',
        checked
          ? 'bg-[var(--accent)] border-[var(--accent)]'
          : 'border-[var(--border)] bg-transparent',
        disabled && 'opacity-40',
      )}
    >
      {checked && (
        <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
        </svg>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FamilyPicker({ families, selected, onToggle, loading }: FamilyPickerProps) {
  if (loading) {
    return (
      <div className="space-y-3">
        <div className="p-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] animate-pulse">
          <div className="flex items-center gap-3">
            <div className="w-4 h-4 rounded bg-[var(--muted)]/20" />
            <div className="h-3 w-52 rounded bg-[var(--muted)]/20" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }

  const metaFamily = families.find((f) => f.is_meta);
  const regularFamilies = families.filter((f) => !f.is_meta);
  const isFullCoverageSelected = metaFamily ? selected.includes(metaFamily.key) : false;

  return (
    <div className="space-y-3">
      {/* Full Coverage toggle (is_meta family) */}
      {metaFamily && (
        <button
          onClick={() => metaFamily.eligible && onToggle(metaFamily.key)}
          disabled={!metaFamily.eligible}
          className={cn(
            'w-full text-left p-3 rounded-lg border transition-colors',
            !metaFamily.eligible && 'opacity-40 cursor-not-allowed',
            isFullCoverageSelected
              ? 'border-[var(--accent)] bg-[var(--accent)]/5'
              : 'border-[var(--border)] hover:border-[var(--accent)] bg-[var(--surface)]',
          )}
        >
          <div className="flex items-center gap-3">
            <Checkbox checked={isFullCoverageSelected} disabled={!metaFamily.eligible} />
            <div className="flex-1 min-w-0">
              <span className="text-[13px] font-medium text-[var(--text)]">
                Full Coverage
              </span>
              <span className="text-[11px] text-[var(--muted)] ml-2">
                — enable all applicable families
              </span>
            </div>
            {metaFamily.matching_node_count > 0 && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--accent)]/10 text-[var(--accent)]">
                {metaFamily.matching_node_count} nodes
              </span>
            )}
          </div>
          {!metaFamily.eligible && metaFamily.reason && (
            <p className="text-[11px] text-[var(--muted)] mt-1 ml-7">{metaFamily.reason}</p>
          )}
        </button>
      )}

      {/* Family grid */}
      <div className="grid grid-cols-2 gap-3">
        {regularFamilies.map((family) => {
          const isSelected = isFullCoverageSelected
            ? family.eligible
            : selected.includes(family.key);

          return (
            <button
              key={family.key}
              onClick={() => family.eligible && onToggle(family.key)}
              disabled={!family.eligible}
              className={cn(
                'w-full text-left p-4 rounded-lg border transition-colors',
                !family.eligible && 'opacity-40 cursor-not-allowed',
                isSelected
                  ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                  : 'border-[var(--border)] hover:border-[var(--accent)] bg-[var(--surface)]',
              )}
            >
              <div className="flex items-start gap-3">
                <Checkbox
                  checked={isSelected}
                  disabled={!family.eligible}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[13px] font-medium text-[var(--text)]">
                      {family.label}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--muted)]/10 text-[var(--muted)]">
                      ~{family.estimated_monitors} monitors
                    </span>
                  </div>
                  <p className="text-[11px] text-[var(--muted)] mt-1 leading-relaxed">
                    {family.description}
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[var(--accent)]/10 text-[var(--accent)]">
                      {family.matching_node_count} matching node{family.matching_node_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                  {!family.eligible && family.reason && (
                    <p className="text-[11px] text-[var(--muted)] mt-2 italic">
                      {family.reason}
                    </p>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
