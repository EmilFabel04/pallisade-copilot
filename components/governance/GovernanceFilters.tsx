'use client';

import React, { useState } from 'react';
import { Search, Filter, X } from 'lucide-react';

interface FilterConfig {
  label: string;
  options: { value: string; label: string; dot?: string }[];
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
  totalCount: number;
  filteredCount: number;
}

export function GovernanceFilters({
  search,
  onSearchChange,
  searchPlaceholder,
  filters,
  onClearAll,
  hasActiveFilters,
  totalCount,
  filteredCount,
}: GovernanceFiltersProps) {
  const [openFilter, setOpenFilter] = useState<string | null>(null);

  return (
    <div className="space-y-3 mb-6">
      {/* Toolbar row */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-faint)]" />
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder}
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)]
                       text-sm text-[var(--text)] placeholder:text-[var(--text-faint)]
                       focus:outline-none focus:border-[var(--border-medium)]"
          />
          {search && (
            <button
              onClick={() => onSearchChange('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-[var(--hover-bg)] text-[var(--text-faint)]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Filter dropdowns */}
        {filters.map((filter) => (
          <FilterDropdown
            key={filter.label}
            label={filter.label}
            active={filter.selected.size > 0}
            count={filter.selected.size}
            open={openFilter === filter.label}
            onToggle={() => setOpenFilter(openFilter === filter.label ? null : filter.label)}
            onClear={() => {
              filter.options.forEach((opt) => {
                if (filter.selected.has(opt.value)) filter.onToggle(opt.value);
              });
            }}
          >
            {filter.options.map((opt) => (
              <FilterItem
                key={opt.value}
                label={opt.label}
                active={filter.selected.has(opt.value)}
                onClick={() => filter.onToggle(opt.value)}
                dot={opt.dot}
              />
            ))}
          </FilterDropdown>
        ))}
      </div>

      {/* Active filters summary */}
      {hasActiveFilters && (
        <div className="flex items-center gap-2 text-xs text-[var(--text-faint)]">
          <span>
            Showing {filteredCount} of {totalCount}
          </span>
          <button onClick={onClearAll} className="text-[var(--accent-2)] hover:underline">
            Clear all filters
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Reusable filter components (same pattern as sources page) ────

function FilterDropdown({
  label,
  active,
  count,
  open,
  onToggle,
  onClear,
  children,
}: {
  label: string;
  active: boolean;
  count: number;
  open: boolean;
  onToggle: () => void;
  onClear: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-sm transition-colors
          ${
            active
              ? 'border-[var(--accent)] text-[var(--accent-2)] bg-[var(--accent)]/5'
              : 'border-[var(--subtle-border)] text-[var(--text-tertiary)] hover:text-[var(--text)]'
          }`}
      >
        <Filter className="w-3.5 h-3.5" />
        {label}
        {count > 0 && (
          <span className="ml-1 px-1.5 py-0.5 rounded-full bg-[var(--accent)] text-white text-[10px] font-medium">
            {count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 w-52 rounded-lg border border-[var(--subtle-border)]
                       bg-[var(--surface)] shadow-xl z-50 py-1">
          {children}
          {active && (
            <button
              onClick={onClear}
              className="w-full px-3 py-2 text-xs text-[var(--text-faint)] hover:text-[var(--text-tertiary)]
                         border-t border-[var(--subtle-border)] transition-colors"
            >
              Clear filter
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function FilterItem({
  label,
  active,
  onClick,
  dot,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  dot?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors
        ${active ? 'bg-[var(--hover-bg)] text-[var(--text)]' : 'text-[var(--text-secondary)] hover:bg-[var(--hover-bg)]'}`}
    >
      {dot && <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: dot }} />}
      {label}
      {active && <span className="ml-auto text-[var(--accent-2)]">&#10003;</span>}
    </button>
  );
}
