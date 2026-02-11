'use client';

import { useState, useRef, useEffect } from 'react';
import { ArtifactType } from '@prisma/client';

interface ArtifactFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  selectedType: ArtifactType | null;
  onTypeChange: (type: ArtifactType | null) => void;
  showPinnedOnly: boolean;
  onPinnedChange: (value: boolean) => void;
}

const typeOptions: { value: ArtifactType | null; label: string }[] = [
  { value: null, label: 'All types' },
  { value: 'QUERY', label: 'Queries' },
  { value: 'FIX', label: 'Fixes' },
  { value: 'INSIGHT', label: 'Insights' },
  { value: 'CODE', label: 'Code' },
  { value: 'PLAN', label: 'Plans' },
];

export function ArtifactFilters({
  search,
  onSearchChange,
  selectedType,
  onTypeChange,
  showPinnedOnly,
  onPinnedChange,
}: ArtifactFiltersProps) {
  const [isTypeOpen, setIsTypeOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsTypeOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selectedTypeLabel = typeOptions.find(t => t.value === selectedType)?.label || 'All types';

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Search */}
      <div className="relative flex-1 min-w-[200px] max-w-[400px]">
        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <svg className="w-4 h-4 text-white/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search artifacts..."
          className="w-full h-9 pl-9 pr-4 bg-white/[0.03] border border-white/[0.06] rounded-lg text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.12] focus:ring-1 focus:ring-white/[0.06] transition-colors"
        />
        {search && (
          <button
            onClick={() => onSearchChange('')}
            className="absolute inset-y-0 right-0 pr-3 flex items-center text-white/30 hover:text-white/50"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Type dropdown */}
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => setIsTypeOpen(!isTypeOpen)}
          className="h-9 px-3 flex items-center gap-2 bg-white/[0.03] border border-white/[0.06] rounded-lg text-[13px] text-white/70 hover:border-white/[0.12] transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
          </svg>
          {selectedTypeLabel}
          <svg className={`w-4 h-4 transition-transform ${isTypeOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {isTypeOpen && (
          <div className="absolute left-0 top-full mt-1 z-20 w-40 bg-[#1a1a24] border border-white/[0.06] rounded-lg shadow-xl overflow-hidden">
            {typeOptions.map((option) => (
              <button
                key={option.value || 'all'}
                onClick={() => {
                  onTypeChange(option.value);
                  setIsTypeOpen(false);
                }}
                className={`w-full px-3 py-2 text-left text-[13px] transition-colors ${
                  selectedType === option.value
                    ? 'bg-white/[0.08] text-white'
                    : 'text-white/70 hover:bg-white/[0.04] hover:text-white'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Pinned toggle */}
      <button
        onClick={() => onPinnedChange(!showPinnedOnly)}
        className={`h-9 px-3 flex items-center gap-2 border rounded-lg text-[13px] transition-colors ${
          showPinnedOnly
            ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
            : 'bg-white/[0.03] border-white/[0.06] text-white/70 hover:border-white/[0.12]'
        }`}
      >
        <svg className="w-4 h-4" fill={showPinnedOnly ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
        </svg>
        Pinned
      </button>
    </div>
  );
}
