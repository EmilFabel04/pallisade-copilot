'use client';

export type SeverityFilter = 'ALL' | 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';
export type CategoryFilter = 'ALL' | 'MONITOR' | 'SOURCE' | 'ASSET' | 'CHANGE_PLAN' | 'INVITE';
export type ReadFilter = 'ALL' | 'UNREAD';

interface NotificationFiltersProps {
  severity: SeverityFilter;
  category: CategoryFilter;
  readFilter: ReadFilter;
  onSeverityChange: (s: SeverityFilter) => void;
  onCategoryChange: (c: CategoryFilter) => void;
  onReadFilterChange: (r: ReadFilter) => void;
}

const severities: { value: SeverityFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'INFO', label: 'Info' },
  { value: 'WARN', label: 'Warning' },
  { value: 'ERROR', label: 'Error' },
  { value: 'CRITICAL', label: 'Critical' },
];

const categories: { value: CategoryFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'MONITOR', label: 'Tasks' },
  { value: 'SOURCE', label: 'Sources' },
  { value: 'ASSET', label: 'Lineage' },
  { value: 'CHANGE_PLAN', label: 'Plans' },
  { value: 'INVITE', label: 'Access' },
];

export function NotificationFilters({
  severity,
  category,
  readFilter,
  onSeverityChange,
  onCategoryChange,
  onReadFilterChange,
}: NotificationFiltersProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Severity chips */}
      <div className="flex items-center gap-1">
        {severities.map((s) => (
          <button
            key={s.value}
            onClick={() => onSeverityChange(s.value)}
            className={`text-[11px] px-2.5 py-1 rounded-full transition-colors ${
              severity === s.value
                ? 'bg-[var(--accent)] text-white'
                : 'bg-[var(--overlay-bg)] text-[var(--text-tertiary)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="w-px h-4 bg-[var(--border-faint)]" />

      {/* Category dropdown */}
      <select
        value={category}
        onChange={(e) => onCategoryChange(e.target.value as CategoryFilter)}
        className="text-[11px] px-2 py-1 rounded-lg bg-[var(--overlay-bg)] text-[var(--text-secondary)] border border-[var(--subtle-border)] outline-none cursor-pointer"
      >
        {categories.map((c) => (
          <option key={c.value} value={c.value}>{c.label}</option>
        ))}
      </select>

      <div className="w-px h-4 bg-[var(--border-faint)]" />

      {/* Read toggle */}
      <div className="flex items-center gap-1">
        {(['ALL', 'UNREAD'] as ReadFilter[]).map((r) => (
          <button
            key={r}
            onClick={() => onReadFilterChange(r)}
            className={`text-[11px] px-2.5 py-1 rounded-full transition-colors ${
              readFilter === r
                ? 'bg-[var(--accent)] text-white'
                : 'bg-[var(--overlay-bg)] text-[var(--text-tertiary)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]'
            }`}
          >
            {r === 'ALL' ? 'All' : 'Unread'}
          </button>
        ))}
      </div>
    </div>
  );
}
