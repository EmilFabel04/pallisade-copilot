'use client';

import { useState } from 'react';
import { AssetHealthRow } from './AssetHealthRow';

interface AssetTrend {
  name: string;
  fqn: string;
  total: number;
  passing: number;
  warning: number;
  failing: number;
  status: string;
  monitors: any[];
}

interface Props {
  assets: AssetTrend[];
  expandedFqn: string | null;
  onToggle: (fqn: string) => void;
  activeCategories: Set<string>;
  onRunAnalysis: () => void;
}

export function AssetHealthLean({ assets, expandedFqn, onToggle, activeCategories, onRunAnalysis }: Props) {
  const [showHealthy, setShowHealthy] = useState(false);
  const unhealthy = assets.filter((a) => a.status !== 'stable' && a.status !== 'healthy');
  const healthy = assets.filter((a) => a.status === 'stable' || a.status === 'healthy');

  return (
    <div className="mb-6">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-2 font-semibold">
        Asset health <span className="text-[var(--text-faint)] normal-case tracking-normal">· {assets.length} monitored, {healthy.length} healthy</span>
      </div>
      <div className="space-y-2">
        {unhealthy.map((asset) => (
          <AssetHealthRow
            key={asset.fqn}
            asset={asset}
            expanded={expandedFqn === asset.fqn}
            onToggle={() => onToggle(asset.fqn)}
            activeCategories={activeCategories}
            onRunAnalysis={onRunAnalysis}
          />
        ))}
        {healthy.length > 0 && (
          <button
            onClick={() => setShowHealthy((v) => !v)}
            className="text-[11px] text-[var(--muted)] hover:text-[var(--text)] block py-1"
          >
            {showHealthy ? '−' : '+'} {healthy.length} healthy asset{healthy.length === 1 ? '' : 's'}
          </button>
        )}
        {showHealthy && healthy.map((asset) => (
          <AssetHealthRow
            key={asset.fqn}
            asset={asset}
            expanded={expandedFqn === asset.fqn}
            onToggle={() => onToggle(asset.fqn)}
            activeCategories={activeCategories}
            onRunAnalysis={onRunAnalysis}
          />
        ))}
      </div>
    </div>
  );
}
