'use client';

import React from 'react';
import { Database, GitBranch, BarChart3, X } from 'lucide-react';

interface DiscoveredScope {
  scope: 'schema' | 'dbt_model_group' | 'dashboard';
  items: string[];
}

interface AutoDiscoveryPromptProps {
  discovered: DiscoveredScope;
  onCreateAll: (scope: string, items: string[]) => void;
  onCreateSelected: (scope: string, items: string[]) => void;
  onDismiss: () => void;
}

const SCOPE_CONFIG = {
  schema: { icon: Database, label: 'schemas', verb: 'found' },
  dbt_model_group: { icon: GitBranch, label: 'dbt model groups', verb: 'found' },
  dashboard: { icon: BarChart3, label: 'dashboards', verb: 'found' },
};

export function AutoDiscoveryPrompt({ discovered, onCreateAll, onCreateSelected, onDismiss }: AutoDiscoveryPromptProps) {
  const config = SCOPE_CONFIG[discovered.scope];
  const Icon = config.icon;

  return (
    <div className="p-4 rounded-lg border border-blue-500/30 bg-blue-500/10">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-medium text-[var(--foreground)]">
            We {config.verb} {discovered.items.length} {config.label}
          </span>
        </div>
        <button onClick={onDismiss} className="text-[var(--muted)] hover:text-[var(--foreground)]">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <p className="text-xs text-[var(--muted)] mt-1 mb-3">
        Create data contracts for these {config.label}?
      </p>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {discovered.items.slice(0, 8).map(item => (
          <span key={item} className="text-[10px] px-2 py-1 rounded bg-[var(--subtle-bg)] text-[var(--foreground)]">
            {item}
          </span>
        ))}
        {discovered.items.length > 8 && (
          <span className="text-[10px] px-2 py-1 rounded bg-[var(--subtle-bg)] text-[var(--muted)]">
            +{discovered.items.length - 8} more
          </span>
        )}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => onCreateAll(discovered.scope, discovered.items)}
          className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:opacity-90"
        >
          Create for All
        </button>
        <button
          onClick={() => onCreateSelected(discovered.scope, discovered.items)}
          className="px-3 py-1.5 text-xs font-medium rounded-md border border-[var(--subtle-border)] text-[var(--foreground)] hover:bg-[var(--subtle-bg)]"
        >
          Pick &amp; Choose
        </button>
      </div>
    </div>
  );
}
