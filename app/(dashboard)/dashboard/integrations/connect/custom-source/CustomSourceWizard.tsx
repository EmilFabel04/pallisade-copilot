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
import { Check, Trash2, Plus, CheckCircle2, XCircle, Loader2 } from 'lucide-react';

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
        {step === 2 && (
          <ConnectionStep
            state={state}
            onChange={updateState}
            onBack={() => setStep(1)}
            onNext={() => setStep(3)}
          />
        )}
        {step === 3 && (
          <DatasetsStep
            state={state}
            onChange={updateState}
            onBack={() => setStep(2)}
            onNext={() => setStep(4)}
          />
        )}
        {step > 3 && (
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

// ─── Step 2: Connection ────────────────────────────────────────────

function ConnectionStep({
  state,
  onChange,
  onBack,
  onNext,
}: {
  state: WizardState;
  onChange: (patch: Partial<WizardState>) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const { auth } = state;
  const isHttps = state.baseUrl.startsWith('https://');
  const hasSecret = auth.secret.length > 0;
  const hasUsername = auth.kind !== 'basic' || (auth.username ?? '').trim().length > 0;
  const canProceed = isHttps && hasSecret && hasUsername;

  const setAuth = (patch: Partial<WizardState['auth']>) => {
    onChange({ auth: { ...auth, ...patch } });
  };

  const secretLabel = auth.kind === 'basic' ? 'Password' : 'Token / key';
  const secretPlaceholder = auth.kind === 'basic' ? 'Password' : 'Paste token or key';

  const inputClass =
    'w-full px-3 py-2.5 bg-[var(--overlay-bg)] border border-[var(--border-medium)] rounded-lg ' +
    'text-[var(--text)] placeholder-[var(--text-faint)] ' +
    'focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] ' +
    'transition-colors text-sm';

  const authOptions: ReadonlyArray<{ kind: AuthKind; label: string; description: string }> = [
    { kind: 'bearer', label: 'Bearer token', description: 'Sent as Authorization: Bearer <token>.' },
    { kind: 'api_key', label: 'API key (header)', description: 'Sent as a custom header.' },
    { kind: 'basic', label: 'Basic auth', description: 'Username + password, base64-encoded.' },
  ];

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-[var(--text)]">Connection</h2>
        <p className="mt-1 text-sm text-[var(--text-tertiary)]">
          Where Pallisade should reach the source, and how to authenticate. We require HTTPS so
          credentials are never sent in the clear.
        </p>
      </div>

      <Field
        label="Base URL"
        required
        hint={
          isHttps || state.baseUrl.length === 0
            ? 'The root of the API. Endpoints in step 3 are appended to this.'
            : 'Must use https://'
        }
      >
        <input
          type="url"
          value={state.baseUrl}
          onChange={(e) => onChange({ baseUrl: e.target.value })}
          placeholder="https://portal.example.com/api/v1"
          className={inputClass}
        />
      </Field>

      <fieldset className="rounded-lg border border-[var(--subtle-border)] p-4 space-y-3">
        <legend className="px-1.5 text-sm font-medium text-[var(--text)]">Authentication</legend>

        <div className="space-y-2">
          {authOptions.map(({ kind, label, description }) => {
            const checked = auth.kind === kind;
            return (
              <label
                key={kind}
                className={`flex items-start gap-2.5 px-3 py-2 rounded-lg border cursor-pointer transition-colors
                  ${
                    checked
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                      : 'border-[var(--subtle-border)] hover:border-[var(--border-medium)]'
                  }`}
              >
                <input
                  type="radio"
                  name="auth-kind"
                  checked={checked}
                  onChange={() => setAuth({ kind })}
                  className="mt-0.5 accent-[var(--accent)]"
                />
                <span className="flex-1">
                  <span className="block text-sm font-medium text-[var(--text)]">{label}</span>
                  <span className="block text-xs text-[var(--text-faint)]">{description}</span>
                </span>
              </label>
            );
          })}
        </div>

        {auth.kind === 'api_key' && (
          <Field label="Header name" hint="Defaults to X-API-Key if left blank.">
            <input
              type="text"
              value={auth.headerName ?? ''}
              onChange={(e) => setAuth({ headerName: e.target.value })}
              placeholder="X-API-Key"
              className={inputClass}
            />
          </Field>
        )}

        {auth.kind === 'basic' && (
          <Field label="Username" required>
            <input
              type="text"
              value={auth.username ?? ''}
              onChange={(e) => setAuth({ username: e.target.value })}
              placeholder="Username"
              className={inputClass}
            />
          </Field>
        )}

        <Field label={secretLabel} required>
          <input
            type="password"
            value={auth.secret}
            onChange={(e) => setAuth({ secret: e.target.value })}
            placeholder={secretPlaceholder}
            className={inputClass}
            autoComplete="new-password"
          />
        </Field>
      </fieldset>

      <div className="flex justify-between pt-2">
        <button
          type="button"
          onClick={onBack}
          className="px-4 py-2 rounded-lg border border-[var(--border-medium)] bg-[var(--overlay-bg)]
                     text-[var(--text)] text-sm font-medium
                     hover:bg-[var(--surface-raised)] transition-colors"
        >
          Back
        </button>
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

// ─── Step 3: Datasets ──────────────────────────────────────────────

function DatasetsStep({
  state,
  onChange,
  onBack,
  onNext,
}: {
  state: WizardState;
  onChange: (patch: Partial<WizardState>) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const updateDataset = (index: number, next: DatasetSpec) => {
    const updated = [...state.datasets];
    updated[index] = next;
    onChange({ datasets: updated });
  };

  const removeDataset = (index: number) => {
    onChange({ datasets: state.datasets.filter((_, j) => j !== index) });
  };

  const addDataset = () => {
    onChange({
      datasets: [
        ...state.datasets,
        { id: '', endpoint: '', timestampColumn: '' },
      ],
    });
  };

  const incomplete = state.datasets.some(
    (d) => !d.id.trim() || !d.endpoint.trim() || !d.timestampColumn.trim(),
  );
  const canProceed = state.datasets.length > 0 && !incomplete;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-[var(--text)]">Datasets</h2>
        <p className="mt-1 text-sm text-[var(--text-tertiary)]">
          Add one or more datasets. Each dataset is a JSON endpoint Pallisade will
          probe — it becomes a monitored asset with freshness, volume, and quality
          checks.
        </p>
      </div>

      <div className="space-y-3">
        {state.datasets.map((ds, i) => (
          <DatasetCard
            key={i}
            index={i}
            dataset={ds}
            baseUrl={state.baseUrl}
            auth={state.auth}
            onChange={(next) => updateDataset(i, next)}
            onRemove={() => removeDataset(i)}
          />
        ))}
        {state.datasets.length === 0 && (
          <div className="rounded-lg border border-dashed border-[var(--subtle-border)] px-4 py-8 text-center text-sm text-[var(--text-faint)]">
            No datasets yet. Add at least one to continue.
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={addDataset}
        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-dashed
                   border-[var(--border-medium)] bg-[var(--overlay-bg)]
                   text-sm font-medium text-[var(--text-tertiary)]
                   hover:border-[var(--accent)] hover:text-[var(--accent-2)]
                   transition-colors"
      >
        <Plus className="w-4 h-4" />
        Add dataset
      </button>

      <div className="flex justify-between pt-2">
        <button
          type="button"
          onClick={onBack}
          className="px-4 py-2 rounded-lg border border-[var(--border-medium)] bg-[var(--overlay-bg)]
                     text-[var(--text)] text-sm font-medium
                     hover:bg-[var(--surface-raised)] transition-colors"
        >
          Back
        </button>
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

interface PreviewResult {
  ok: boolean;
  message: string;
  latency_ms?: number | null;
}

function DatasetCard({
  index,
  dataset,
  baseUrl,
  auth,
  onChange,
  onRemove,
}: {
  index: number;
  dataset: DatasetSpec;
  baseUrl: string;
  auth: WizardState['auth'];
  onChange: (next: DatasetSpec) => void;
  onRemove: () => void;
}) {
  const [testing, setTesting] = useState(false);
  const [lastResult, setLastResult] = useState<PreviewResult | null>(null);

  const inputClass =
    'w-full px-3 py-2.5 bg-[var(--overlay-bg)] border border-[var(--border-medium)] rounded-lg ' +
    'text-[var(--text)] placeholder-[var(--text-faint)] ' +
    'focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] ' +
    'transition-colors text-sm';

  const canTest =
    baseUrl.startsWith('https://') &&
    dataset.endpoint.trim().length > 0 &&
    dataset.timestampColumn.trim().length > 0;

  async function handleTestFetch() {
    setTesting(true);
    setLastResult(null);
    try {
      const resp = await fetch('/api/integrations/custom-source/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          config: {
            base_url: baseUrl,
            auth,
            // Send only the SINGLE dataset under test — the wizard probes
            // one at a time so a failing dataset doesn't mask others.
            datasets: [
              {
                id: dataset.id.trim() || 'preview',
                endpoint: dataset.endpoint.trim(),
                timestamp_column: dataset.timestampColumn.trim(),
                ...(dataset.cursorParam
                  ? { cursor_param: dataset.cursorParam }
                  : {}),
                ...(dataset.jsonRoot ? { json_root: dataset.jsonRoot } : {}),
                ...(dataset.landsIn ? { lands_in: dataset.landsIn } : {}),
              },
            ],
          },
        }),
      });
      const data = (await resp.json().catch(() => ({}))) as Partial<PreviewResult>;
      setLastResult({
        ok: Boolean(data.ok),
        message:
          data.message ??
          (resp.ok ? 'No message returned' : `Request failed (${resp.status})`),
        latency_ms: data.latency_ms ?? null,
      });
    } catch (err) {
      setLastResult({
        ok: false,
        message: err instanceof Error ? err.message : 'Network error',
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="rounded-lg border border-[var(--subtle-border)] bg-[var(--overlay-bg)] p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text)]">
          Dataset {index + 1}
        </span>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove dataset"
          className="p-1.5 rounded-md text-[var(--text-faint)]
                     hover:text-red-400 hover:bg-[var(--surface-raised)]
                     transition-colors"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="ID" required hint="Slug used in lineage.">
          <input
            type="text"
            value={dataset.id}
            onChange={(e) => onChange({ ...dataset, id: e.target.value })}
            placeholder="water_meters"
            className={inputClass}
          />
        </Field>

        <Field label="Endpoint" required hint="Appended to base URL.">
          <input
            type="text"
            value={dataset.endpoint}
            onChange={(e) => onChange({ ...dataset, endpoint: e.target.value })}
            placeholder="/sensors/readings"
            className={inputClass}
          />
        </Field>

        <Field
          label="Timestamp column"
          required
          hint="JSON field used for freshness."
        >
          <input
            type="text"
            value={dataset.timestampColumn}
            onChange={(e) =>
              onChange({ ...dataset, timestampColumn: e.target.value })
            }
            placeholder="reading_at"
            className={inputClass}
          />
        </Field>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          disabled={!canTest || testing}
          onClick={handleTestFetch}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md
                     border border-[var(--border-medium)] bg-[var(--surface-raised)]
                     text-xs font-medium text-[var(--text)]
                     hover:border-[var(--accent)] hover:text-[var(--accent-2)]
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors"
        >
          {testing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {testing ? 'Testing…' : 'Test fetch'}
        </button>

        {lastResult && (
          <span
            className={`inline-flex items-center gap-1.5 text-xs ${
              lastResult.ok ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {lastResult.ok ? (
              <CheckCircle2 className="w-3.5 h-3.5" />
            ) : (
              <XCircle className="w-3.5 h-3.5" />
            )}
            {lastResult.ok
              ? `Connected${
                  lastResult.latency_ms != null
                    ? ` (${lastResult.latency_ms} ms)`
                    : ''
                }`
              : lastResult.message}
          </span>
        )}
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
