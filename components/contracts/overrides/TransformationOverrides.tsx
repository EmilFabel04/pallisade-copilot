'use client';

import type { TransformationContractOverrides } from '../types';

interface Props {
  value: Partial<TransformationContractOverrides>;
  onChange: (overrides: Partial<TransformationContractOverrides>) => void;
  inputClass: string;
}

const TEST_OPTIONS = ['not_null', 'unique', 'relationships', 'accepted_values', 'freshness'] as const;

export default function TransformationOverrides({ value, onChange, inputClass }: Props) {
  const update = (key: keyof TransformationContractOverrides, val: any) => {
    onChange({ ...value, [key]: val });
  };

  const toggleTest = (test: string) => {
    const current = value.requiredTests || [];
    const next = current.includes(test as any)
      ? current.filter(t => t !== test)
      : [...current, test as any];
    update('requiredTests', next.length > 0 ? next : undefined);
  };

  return (
    <div className="space-y-5">
      <div>
        <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">
          Expected Run Cadence (minutes)
        </label>
        <input
          type="number"
          min={0}
          value={value.expectedRunCadenceMinutes ?? ''}
          onChange={(e) => update('expectedRunCadenceMinutes', e.target.value ? Number(e.target.value) : undefined)}
          placeholder="e.g. 360"
          className={inputClass}
        />
        <p className="text-xs text-[var(--text-faint)] mt-1">How often dbt runs are expected</p>
      </div>

      <div>
        <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">
          Required Tests
        </label>
        <div className="flex flex-wrap gap-2">
          {TEST_OPTIONS.map(test => {
            const selected = (value.requiredTests || []).includes(test);
            return (
              <button
                key={test}
                type="button"
                onClick={() => toggleTest(test)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border ${
                  selected
                    ? 'bg-[var(--accent)]/15 border-[var(--accent)]/30 text-[var(--accent)]'
                    : 'bg-[var(--surface-raised)] border-[var(--subtle-border)] text-[var(--text-tertiary)] hover:border-[var(--border-medium)]'
                }`}
              >
                {test}
              </button>
            );
          })}
        </div>
        <p className="text-xs text-[var(--text-faint)] mt-1">Tests that must be present on all models</p>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <label className="text-[13px] font-medium text-[var(--text-tertiary)]">Freshness Tests Required</label>
          <p className="text-xs text-[var(--text-faint)] mt-0.5">Sources must have freshness tests configured</p>
        </div>
        <button
          type="button"
          onClick={() => update('freshnessTestsRequired', !value.freshnessTestsRequired)}
          className={`relative w-11 h-6 rounded-full transition-colors ${
            value.freshnessTestsRequired ? 'bg-[var(--accent)]' : 'bg-[var(--overlay-medium)]'
          }`}
        >
          <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
            value.freshnessTestsRequired ? 'translate-x-5' : ''
          }`} />
        </button>
      </div>
    </div>
  );
}
