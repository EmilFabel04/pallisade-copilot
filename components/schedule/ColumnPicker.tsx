'use client';

import { useState, useEffect } from 'react';

const NUMERIC_TYPES = new Set([
  'int64', 'float64', 'numeric', 'bignumeric', 'integer', 'float', 'double',
  'decimal', 'number', 'real', 'smallint', 'bigint', 'int', 'tinyint',
  'double precision', 'int4', 'int8', 'float4', 'float8',
]);

interface Column {
  name: string;
  type: string;
}

interface ColumnPickerProps {
  targetFqn: string;
  stackId?: string;
  value: string;
  onChange: (column: string) => void;
  numericOnly?: boolean;
  className?: string;
}

export function ColumnPicker({ targetFqn, stackId, value, onChange, numericOnly = false, className }: ColumnPickerProps) {
  const [columns, setColumns] = useState<Column[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetched, setFetched] = useState(false);

  useEffect(() => {
    if (!targetFqn) return;
    setLoading(true);
    const params = new URLSearchParams({ fqn: targetFqn });
    if (stackId) params.set('stackId', stackId);

    fetch(`/api/lineage/columns?${params}`)
      .then(res => res.json())
      .then(data => {
        setColumns(data.columns || []);
        setFetched(true);
      })
      .catch(() => setFetched(true))
      .finally(() => setLoading(false));
  }, [targetFqn, stackId]);

  const filteredColumns = numericOnly
    ? columns.filter(c => NUMERIC_TYPES.has((c.type || '').toLowerCase()))
    : columns;

  const inputClass = className || 'w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]';

  // If we fetched but got no columns, fall back to text input
  if (fetched && columns.length === 0) {
    return (
      <div>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Enter column name (e.g. revenue)"
          className={inputClass}
        />
        <p className="text-[10px] text-[var(--text-faint)] mt-1">
          Column list not available — type the column name manually
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className={`${inputClass} flex items-center gap-2 text-[var(--muted)]`}>
        <div className="w-3 h-3 border-2 border-[var(--text-faint)] border-t-transparent rounded-full animate-spin" />
        Loading columns...
      </div>
    );
  }

  return (
    <div>
      <select
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
      >
        <option value="">Select a column...</option>
        {filteredColumns.map(col => (
          <option key={col.name} value={col.name}>
            {col.name} ({col.type})
          </option>
        ))}
      </select>
      {numericOnly && filteredColumns.length === 0 && columns.length > 0 && (
        <p className="text-[10px] text-amber-400 mt-1">
          No numeric columns found. Showing all columns:
        </p>
      )}
      {numericOnly && filteredColumns.length === 0 && columns.length > 0 && (
        <select
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          className={`${inputClass} mt-1`}
        >
          <option value="">Select any column...</option>
          {columns.map(col => (
            <option key={col.name} value={col.name}>
              {col.name} ({col.type})
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
