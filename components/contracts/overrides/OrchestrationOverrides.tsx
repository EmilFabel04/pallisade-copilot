'use client';

import type { OrchestrationOverrides as OrchestrationOverridesType } from '../types';

interface Props {
  value: Partial<OrchestrationOverridesType>;
  onChange: (overrides: Partial<OrchestrationOverridesType>) => void;
  inputClass: string;
}

export default function OrchestrationOverrides({ value, onChange, inputClass }: Props) {
  const update = (key: keyof OrchestrationOverridesType, val: any) => {
    onChange({ ...value, [key]: val });
  };

  return (
    <div className="space-y-5">
      <div>
        <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">
          Max Retries
        </label>
        <input
          type="number"
          min={0}
          max={10}
          value={value.maxRetries ?? ''}
          onChange={(e) => update('maxRetries', e.target.value ? Number(e.target.value) : undefined)}
          placeholder="e.g. 3"
          className={inputClass}
        />
        <p className="text-xs text-[var(--text-faint)] mt-1">Maximum task retry attempts on failure</p>
      </div>

      <div>
        <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">
          Retry Backoff (minutes)
        </label>
        <input
          type="number"
          min={0}
          value={value.retryBackoffMinutes ?? ''}
          onChange={(e) => update('retryBackoffMinutes', e.target.value ? Number(e.target.value) : undefined)}
          placeholder="e.g. 5"
          className={inputClass}
        />
        <p className="text-xs text-[var(--text-faint)] mt-1">Wait time between retries</p>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <label className="text-[13px] font-medium text-[var(--text-tertiary)]">On-Call Required</label>
          <p className="text-xs text-[var(--text-faint)] mt-0.5">Failures escalate to on-call rotation</p>
        </div>
        <button
          type="button"
          onClick={() => update('oncallRequired', !value.oncallRequired)}
          className={`relative w-11 h-6 rounded-full transition-colors ${
            value.oncallRequired ? 'bg-[var(--accent)]' : 'bg-[var(--overlay-medium)]'
          }`}
        >
          <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
            value.oncallRequired ? 'translate-x-5' : ''
          }`} />
        </button>
      </div>
    </div>
  );
}
