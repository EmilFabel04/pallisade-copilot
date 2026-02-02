'use client';

import React, { useState } from 'react';

interface Scanner {
  id: string;
  name: string;
  description: string;
  category: 'data' | 'pipeline' | 'code' | 'security';
  icon: React.ReactNode;
  requiresIntegration?: string;
  mlPowered?: boolean;
}

interface ScannerSelectorProps {
  availableScanners?: string[];
  selectedScanners: string[];
  onSelectionChange: (selected: string[]) => void;
  disabled?: boolean;
}

const SCANNERS: Scanner[] = [
  // Data Scanners
  {
    id: 'freshness',
    name: 'Data Freshness',
    description: 'Check if data is up-to-date against SLOs',
    category: 'data',
    requiresIntegration: 'warehouse',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    id: 'quality',
    name: 'Data Quality',
    description: 'Detect nulls, duplicates, and invalid values',
    category: 'data',
    requiresIntegration: 'warehouse',
    mlPowered: true,
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    id: 'schema',
    name: 'Schema Drift',
    description: 'Detect column changes and type modifications',
    category: 'data',
    requiresIntegration: 'warehouse',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
      </svg>
    ),
  },
  {
    id: 'volume',
    name: 'Volume Anomaly',
    description: 'Detect unexpected changes in row counts',
    category: 'data',
    requiresIntegration: 'warehouse',
    mlPowered: true,
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
      </svg>
    ),
  },
  // Security Scanners
  {
    id: 'pii',
    name: 'PII Detection',
    description: 'Find exposed personal information',
    category: 'security',
    requiresIntegration: 'warehouse',
    mlPowered: true,
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
      </svg>
    ),
  },
  {
    id: 'secrets',
    name: 'Secrets Scanner',
    description: 'Find exposed credentials in code',
    category: 'code',
    requiresIntegration: 'github',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
      </svg>
    ),
  },
  // Pipeline Scanners
  {
    id: 'pipeline',
    name: 'Pipeline Health',
    description: 'Monitor dbt, Airflow, and Fivetran',
    category: 'pipeline',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    ),
  },
  {
    id: 'coverage',
    name: 'Test Coverage',
    description: 'Find untested dbt models',
    category: 'pipeline',
    requiresIntegration: 'dbt',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
      </svg>
    ),
  },
];

const categoryLabels = {
  data: { label: 'Data Quality', color: 'text-blue-400' },
  security: { label: 'Security', color: 'text-red-400' },
  pipeline: { label: 'Pipeline', color: 'text-purple-400' },
  code: { label: 'Code', color: 'text-green-400' },
};

export function ScannerSelector({
  availableScanners,
  selectedScanners,
  onSelectionChange,
  disabled = false,
}: ScannerSelectorProps) {
  const [filter, setFilter] = useState<'all' | 'data' | 'security' | 'pipeline' | 'code'>('all');

  const filteredScanners = SCANNERS.filter(
    s => filter === 'all' || s.category === filter
  );

  const isAvailable = (scanner: Scanner) => {
    if (!availableScanners) return true;
    return availableScanners.includes(scanner.id);
  };

  const toggleScanner = (scannerId: string) => {
    if (disabled) return;
    
    if (selectedScanners.includes(scannerId)) {
      onSelectionChange(selectedScanners.filter(s => s !== scannerId));
    } else {
      onSelectionChange([...selectedScanners, scannerId]);
    }
  };

  const selectAll = () => {
    if (disabled) return;
    const available = filteredScanners.filter(s => isAvailable(s)).map(s => s.id);
    onSelectionChange([...new Set([...selectedScanners, ...available])]);
  };

  const selectNone = () => {
    if (disabled) return;
    const filtered = filteredScanners.map(s => s.id);
    onSelectionChange(selectedScanners.filter(s => !filtered.includes(s)));
  };

  return (
    <div className="space-y-4">
      {/* Filter tabs */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 bg-black/20 rounded-lg p-0.5">
          {(['all', 'data', 'security', 'pipeline', 'code'] as const).map((cat) => (
            <button
              key={cat}
              onClick={() => setFilter(cat)}
              className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                filter === cat
                  ? 'bg-[var(--card-bg)] text-white'
                  : 'text-[var(--muted)] hover:text-white'
              }`}
            >
              {cat === 'all' ? 'All' : categoryLabels[cat].label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={selectAll}
            disabled={disabled}
            className="text-[var(--accent)] hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Select all
          </button>
          <span className="text-[var(--muted)]">|</span>
          <button
            onClick={selectNone}
            disabled={disabled}
            className="text-[var(--muted)] hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Scanner grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {filteredScanners.map((scanner) => {
          const available = isAvailable(scanner);
          const selected = selectedScanners.includes(scanner.id);

          return (
            <button
              key={scanner.id}
              onClick={() => available && toggleScanner(scanner.id)}
              disabled={disabled || !available}
              className={`p-4 rounded-lg border text-left transition-all ${
                selected
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                  : available
                  ? 'border-[var(--border-dim)] bg-[var(--card-bg)] hover:border-[var(--accent)]/50'
                  : 'border-[var(--border-dim)] bg-[var(--card-bg)] opacity-50 cursor-not-allowed'
              }`}
            >
              <div className="flex items-start gap-3">
                {/* Checkbox */}
                <div className={`mt-0.5 w-5 h-5 rounded border flex items-center justify-center ${
                  selected
                    ? 'bg-[var(--accent)] border-[var(--accent)]'
                    : 'border-[var(--border-dim)]'
                }`}>
                  {selected && (
                    <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <div className={available ? 'text-white' : 'text-[var(--muted)]'}>
                      {scanner.icon}
                    </div>
                    <span className={`text-sm font-medium ${available ? 'text-white' : 'text-[var(--muted)]'}`}>
                      {scanner.name}
                    </span>
                    {scanner.mlPowered && (
                      <span className="px-1 py-0.5 bg-purple-500/20 text-purple-400 text-[10px] rounded">
                        ML
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-[var(--muted)] mt-1">
                    {scanner.description}
                  </p>
                  {!available && scanner.requiresIntegration && (
                    <p className="text-xs text-amber-400 mt-1">
                      Requires {scanner.requiresIntegration} integration
                    </p>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Selection summary */}
      <div className="flex items-center justify-between pt-2 border-t border-[var(--border-dim)]">
        <p className="text-sm text-[var(--muted)]">
          <span className="text-white font-medium">{selectedScanners.length}</span> scanner{selectedScanners.length !== 1 ? 's' : ''} selected
        </p>
        {selectedScanners.some(s => SCANNERS.find(sc => sc.id === s)?.mlPowered) && (
          <p className="text-xs text-purple-400 flex items-center gap-1">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            ML-powered analysis enabled
          </p>
        )}
      </div>
    </div>
  );
}

