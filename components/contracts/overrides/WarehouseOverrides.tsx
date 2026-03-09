'use client';

import type { WarehouseContractOverrides } from '../types';

interface Props {
  value: Partial<WarehouseContractOverrides>;
  onChange: (overrides: Partial<WarehouseContractOverrides>) => void;
  inputClass: string;
}

export default function WarehouseOverrides({ value, onChange, inputClass }: Props) {
  const update = (key: keyof WarehouseContractOverrides, val: any) => {
    onChange({ ...value, [key]: val });
  };

  return (
    <div className="space-y-5">
      <div>
        <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">
          Max Query Cost (USD)
        </label>
        <input
          type="number"
          min={0}
          step={0.01}
          value={value.maxQueryCostUsd ?? ''}
          onChange={(e) => update('maxQueryCostUsd', e.target.value ? Number(e.target.value) : undefined)}
          placeholder="e.g. 10.00"
          className={inputClass}
        />
        <p className="text-xs text-[var(--text-faint)] mt-1">Queries exceeding this cost will be flagged</p>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <label className="text-[13px] font-medium text-[var(--text-tertiary)]">Require Dry Run</label>
          <p className="text-xs text-[var(--text-faint)] mt-0.5">Run cost estimation before executing queries (BigQuery)</p>
        </div>
        <button
          type="button"
          onClick={() => update('requireDryRun', !value.requireDryRun)}
          className={`relative w-11 h-6 rounded-full transition-colors ${
            value.requireDryRun ? 'bg-[var(--accent)]' : 'bg-[var(--overlay-medium)]'
          }`}
        >
          <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
            value.requireDryRun ? 'translate-x-5' : ''
          }`} />
        </button>
      </div>

      <div>
        <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">
          Default Dataset / Schema
        </label>
        <input
          type="text"
          value={value.defaultDataset || ''}
          onChange={(e) => update('defaultDataset', e.target.value || undefined)}
          placeholder="e.g. analytics"
          className={inputClass}
        />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <label className="text-[13px] font-medium text-[var(--text-tertiary)]">Read-Only Enforced</label>
          <p className="text-xs text-[var(--text-faint)] mt-0.5">Block write operations through the copilot</p>
        </div>
        <button
          type="button"
          onClick={() => update('readOnlyEnforced', !value.readOnlyEnforced)}
          className={`relative w-11 h-6 rounded-full transition-colors ${
            value.readOnlyEnforced ? 'bg-[var(--accent)]' : 'bg-[var(--overlay-medium)]'
          }`}
        >
          <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
            value.readOnlyEnforced ? 'translate-x-5' : ''
          }`} />
        </button>
      </div>
    </div>
  );
}
