'use client';

import React from 'react';

interface FilterConfig {
  label: string;
  options: { value: string; label: string }[];
  selected: Set<string>;
  onToggle: (value: string) => void;
}

interface GovernanceFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder: string;
  filters: FilterConfig[];
  onClearAll: () => void;
  hasActiveFilters: boolean;
}

export function GovernanceFilters({
  search,
  onSearchChange,
  searchPlaceholder,
  filters,
  onClearAll,
  hasActiveFilters,
}: GovernanceFiltersProps) {
  return (
    <div className="space-y-3 mb-6">
      {/* Search */}
      <div className="relative">
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--muted)]"
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="text"
          value={search}
          onChange={e => onSearchChange(e.target.value)}
          placeholder={searchPlaceholder}
          className="w-full pl-10 pr-4 py-2 text-[13px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg text-[var(--text)] placeholder:text-[var(--muted)] focus:border-slate-500/50 focus:outline-none"
        />
      </div>

      {/* Filter chips */}
      <div className="flex items-center gap-3 flex-wrap">
        {filters.map(filter => (
          <div key={filter.label} className="flex items-center gap-1.5">
            <span className="text-[10px] text-[var(--muted)] uppercase tracking-wide">{filter.label}:</span>
            <div className="flex gap-1">
              {filter.options.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => filter.onToggle(opt.value)}
                  className={`px-2 py-0.5 text-[11px] rounded-md border transition-colors ${
                    filter.selected.has(opt.value)
                      ? 'bg-[var(--accent)]/20 border-[var(--accent)]/40 text-[var(--text)]'
                      : 'bg-transparent border-[var(--subtle-border)] text-[var(--muted)] hover:text-[var(--text)]'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        ))}

        {hasActiveFilters && (
          <button
            onClick={onClearAll}
            className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] underline ml-2"
          >
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}
