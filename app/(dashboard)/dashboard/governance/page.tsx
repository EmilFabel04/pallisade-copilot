'use client';

import React, { useState } from 'react';
import { DataSLAsTab } from '@/components/sources/DataSLAsTab';

type GovernanceTab = 'data-slas' | 'pipeline-slas';

export default function GovernancePage() {
  const [activeTab, setActiveTab] = useState<GovernanceTab>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get('tab');
      if (tab === 'pipeline-slas') return 'pipeline-slas';
    }
    return 'data-slas';
  });

  return (
    <div className="flex-1 overflow-y-auto p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-[var(--text)]">Governance</h1>
          <p className="text-[13px] text-[var(--muted)]">
            Manage data SLAs and pipeline SLA expectations
          </p>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => {
              setActiveTab('data-slas');
              window.history.replaceState(null, '', '/dashboard/governance?tab=data-slas');
            }}
            className={`px-4 py-2 text-[13px] font-medium rounded-lg transition-colors ${
              activeTab === 'data-slas'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--subtle-bg)]'
            }`}
          >
            Data SLAs
          </button>
          <button
            onClick={() => {
              setActiveTab('pipeline-slas');
              window.history.replaceState(null, '', '/dashboard/governance?tab=pipeline-slas');
            }}
            className={`px-4 py-2 text-[13px] font-medium rounded-lg transition-colors ${
              activeTab === 'pipeline-slas'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-[var(--subtle-bg)]'
            }`}
          >
            Pipeline SLAs
          </button>
        </div>

        {/* Tab content */}
        {activeTab === 'data-slas' ? (
          <DataSLAsTab />
        ) : (
          <div className="text-center py-12 text-[var(--muted)]">
            Pipeline SLAs — coming soon
          </div>
        )}
      </div>
    </div>
  );
}
