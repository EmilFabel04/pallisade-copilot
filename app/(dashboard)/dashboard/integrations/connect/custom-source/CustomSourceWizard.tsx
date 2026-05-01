'use client';

/**
 * Custom Source Wizard
 *
 * Five-step wizard for connecting a Custom Source (HTTP probe) integration.
 * Step 1 (Identity) is implemented here — display name + platform label.
 * Subsequent steps (Connection, Datasets, Schedule, Review) are scaffolded
 * by Tasks 21-23.
 */

import { useState } from 'react';
import { Check } from 'lucide-react';

type Step = 1 | 2 | 3 | 4 | 5;

type AuthKind = 'bearer' | 'api_key' | 'basic';

interface DatasetSpec {
  id: string;
  endpoint: string;
  timestampColumn: string;
  cursorParam?: string;
  jsonRoot?: string;
  landsIn?: string;
}

export interface WizardState {
  name: string;
  platformLabel: string;
  baseUrl: string;
  auth: {
    kind: AuthKind;
    secret: string;
    headerName?: string;
    username?: string;
  };
  datasets: DatasetSpec[];
  schedule: 'hourly' | 'every_6h' | 'daily' | 'weekly';
}

const INITIAL_STATE: WizardState = {
  name: '',
  platformLabel: '',
  baseUrl: '',
  auth: { kind: 'bearer', secret: '' },
  datasets: [],
  schedule: 'daily',
};

const STEP_LABELS: ReadonlyArray<{ step: Step; label: string }> = [
  { step: 1, label: 'Identity' },
  { step: 2, label: 'Connection' },
  { step: 3, label: 'Datasets' },
  { step: 4, label: 'Schedule' },
  { step: 5, label: 'Review' },
];

export default function CustomSourceWizard() {
  const [step, setStep] = useState<Step>(1);
  const [state, setState] = useState<WizardState>(INITIAL_STATE);

  const updateState = (patch: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-[var(--text)]">
          Connect a Custom Source
        </h1>
        <p className="text-sm text-[var(--text-tertiary)]">
          Probe any HTTP/JSON endpoint as a first-class data source. Pallisade will
          monitor freshness, volume, and quality — even if it isn&apos;t a warehouse.
        </p>
      </header>

      <Stepper current={step} />

      <div className="rounded-xl border border-[var(--subtle-border)] bg-[var(--surface-raised)] p-6">
        {step === 1 && (
          <IdentityStep
            state={state}
            onChange={updateState}
            onNext={() => setStep(2)}
          />
        )}
        {step > 1 && (
          <div className="text-sm text-[var(--text-faint)]">
            Step {step} not yet implemented.
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Stepper ───────────────────────────────────────────────────────

function Stepper({ current }: { current: Step }) {
  return (
    <ol className="flex items-center gap-2 text-xs">
      {STEP_LABELS.map(({ step, label }, idx) => {
        const isCompleted = step < current;
        const isActive = step === current;
        return (
          <li key={step} className="flex items-center gap-2">
            <div
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border transition-colors
                ${
                  isActive
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent-2)]'
                    : isCompleted
                      ? 'border-[var(--subtle-border)] bg-[var(--overlay-bg)] text-[var(--text-tertiary)]'
                      : 'border-[var(--subtle-border)] text-[var(--text-faint)]'
                }`}
            >
              {isCompleted ? (
                <Check className="w-3 h-3" />
              ) : (
                <span className="font-semibold">{step}</span>
              )}
              <span className={isActive ? 'font-medium' : ''}>{label}</span>
            </div>
            {idx < STEP_LABELS.length - 1 && (
              <div className="w-4 h-px bg-[var(--subtle-border)]" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ─── Step 1: Identity ──────────────────────────────────────────────

function IdentityStep({
  state,
  onChange,
  onNext,
}: {
  state: WizardState;
  onChange: (patch: Partial<WizardState>) => void;
  onNext: () => void;
}) {
  const canProceed = state.name.trim().length > 0 && state.platformLabel.trim().length > 0;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-[var(--text)]">Identity</h2>
        <p className="mt-1 text-sm text-[var(--text-tertiary)]">
          Give this source a name and a platform label. The platform label is shown in
          lineage to identify where the data comes from.
        </p>
      </div>

      <Field
        label="Display name"
        required
        hint="Shown in the integrations list and lineage."
      >
        <input
          type="text"
          value={state.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="e.g. MyCiti — water sensors"
          className="w-full px-3 py-2.5 bg-[var(--overlay-bg)] border border-[var(--border-medium)] rounded-lg
                     text-[var(--text)] placeholder-[var(--text-faint)]
                     focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]
                     transition-colors text-sm"
        />
      </Field>

      <Field
        label="Platform label"
        required
        hint="Shown in lineage as the upstream platform (e.g. MyCiti, Stripe, Shopify)."
      >
        <input
          type="text"
          value={state.platformLabel}
          onChange={(e) => onChange({ platformLabel: e.target.value })}
          placeholder="e.g. MyCiti"
          className="w-full px-3 py-2.5 bg-[var(--overlay-bg)] border border-[var(--border-medium)] rounded-lg
                     text-[var(--text)] placeholder-[var(--text-faint)]
                     focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]
                     transition-colors text-sm"
        />
      </Field>

      <div className="flex justify-end pt-2">
        <button
          type="button"
          disabled={!canProceed}
          onClick={onNext}
          className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium
                     hover:bg-[var(--accent-2)] disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  );
}

// ─── Reusable form primitives ──────────────────────────────────────

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-[var(--text)] mb-1.5">
        {label}
        {required && <span className="text-red-400 ml-0.5">*</span>}
      </span>
      {children}
      {hint && (
        <span className="mt-1 block text-xs text-[var(--text-faint)]">{hint}</span>
      )}
    </label>
  );
}
