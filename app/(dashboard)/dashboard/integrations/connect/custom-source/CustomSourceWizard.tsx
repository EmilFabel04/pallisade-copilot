'use client';

/**
 * Custom Source Wizard
 *
 * Five-step wizard for connecting a Custom Source (HTTP probe) integration.
 * Step 1 (Identity)   — display name + platform label.
 * Step 2 (Connection) — base URL + auth.
 * Step 3 (Discovery)  — auto-discover dataset candidates via /discover;
 *                        user accepts/rejects rows and fills in lands_in.
 * Step 4 (Schedule)   — probe cadence.
 * Step 5 (Review)     — JSON summary + save.
 */

import { useState } from 'react';
import { Check, Loader2 } from 'lucide-react';

import { DiscoveryStep } from './DiscoveryStep';

type Step = 1 | 2 | 3 | 4 | 5;

type AuthKind = 'bearer' | 'api_key' | 'basic';

export interface DatasetSpec {
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
  { step: 3, label: 'Discovery' },
  { step: 4, label: 'Schedule' },
  { step: 5, label: 'Review' },
];

export default function CustomSourceWizard() {
  const [step, setStep] = useState<Step>(1);
  const [state, setState] = useState<WizardState>(INITIAL_STATE);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const updateState = (patch: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  };

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      // Split auth into credentials (the secret) and config.auth (everything else).
      // The route's POST handler encrypts the entire `credentials` object, so the
      // probe runner's _resolve_secret() will decrypt and read the `secret` key.
      // Non-secret auth metadata (kind, header_name, username) lives in config.auth
      // because it isn't sensitive and the probe runner consumes it directly.
      const { secret, ...nonSecretAuth } = state.auth;

      const r = await fetch('/api/integrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'CUSTOM_SOURCE',
          name: state.name,
          credentials: { secret },
          config: {
            platform_label: state.platformLabel,
            base_url: state.baseUrl,
            auth: nonSecretAuth,
            datasets: state.datasets.map((d) => ({
              id: d.id,
              endpoint: d.endpoint,
              timestamp_column: d.timestampColumn,
              ...(d.cursorParam ? { cursor_param: d.cursorParam } : {}),
              ...(d.jsonRoot ? { json_root: d.jsonRoot } : {}),
              ...(d.landsIn ? { lands_in: d.landsIn } : {}),
            })),
            schedule: state.schedule,
          },
          // Top-level hints that the route uses to populate Integration's
          // probeSchedule + nextProbeAt + status, so the runner picks it up.
          probeSchedule: state.schedule,
          activate: true,
        }),
      });
      if (r.ok) {
        window.location.href = '/dashboard/integrations';
      } else {
        const err = await r.json().catch(() => ({}));
        setSaveError(
          err.message || err.error || `Failed to save (HTTP ${r.status})`,
        );
      }
    } catch (exc: unknown) {
      setSaveError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  }

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
          <DiscoveryStep
            state={state}
            onChange={updateState}
            onBack={() => setStep(2)}
            onNext={() => setStep(4)}
          />
        )}
        {step === 4 && (
          <ScheduleStep
            state={state}
            onChange={updateState}
            onBack={() => setStep(3)}
            onNext={() => setStep(5)}
          />
        )}
        {step === 5 && (
          <ReviewStep
            state={state}
            saving={saving}
            saveError={saveError}
            onBack={() => setStep(4)}
            onSave={handleSave}
          />
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

// ─── Step 4: Schedule ──────────────────────────────────────────────
// Note: lands_in is now collected per-dataset in step 3 (Discovery).
// The per-dataset lands_in section has been removed from this step
// to avoid duplication, but the underlying state shape (DatasetSpec.landsIn)
// is preserved so the step 5 review payload still includes it.

function ScheduleStep({
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
  const inputClass =
    'w-full px-3 py-2.5 bg-[var(--overlay-bg)] border border-[var(--border-medium)] rounded-lg ' +
    'text-[var(--text)] placeholder-[var(--text-faint)] ' +
    'focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] ' +
    'transition-colors text-sm';

  const scheduleOptions: ReadonlyArray<{
    value: WizardState['schedule'];
    label: string;
  }> = [
    { value: 'hourly', label: 'Hourly' },
    { value: 'every_6h', label: 'Every 6 hours' },
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
  ];

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-[var(--text)]">Schedule</h2>
        <p className="mt-1 text-sm text-[var(--text-tertiary)]">
          How often Pallisade should probe these endpoints.
        </p>
      </div>

      <Field
        label="Probe schedule"
        hint="Defaults to daily. The runner advances the next probe time after each tick."
      >
        <select
          value={state.schedule}
          onChange={(e) =>
            onChange({ schedule: e.target.value as WizardState['schedule'] })
          }
          className={inputClass}
        >
          {scheduleOptions.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>

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
          onClick={onNext}
          className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium
                     hover:bg-[var(--accent-2)] transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  );
}

// ─── Step 5: Review + save ─────────────────────────────────────────

function ReviewStep({
  state,
  saving,
  saveError,
  onBack,
  onSave,
}: {
  state: WizardState;
  saving: boolean;
  saveError: string | null;
  onBack: () => void;
  onSave: () => void;
}) {
  // Mask the secret in the preview so it never appears in plaintext on screen.
  const masked = {
    ...state,
    auth: { ...state.auth, secret: state.auth.secret ? '•••' : '' },
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-[var(--text)]">Review</h2>
        <p className="mt-1 text-sm text-[var(--text-tertiary)]">
          Double-check the configuration. Saving creates the integration and the
          scheduler will probe it on the next tick.
        </p>
      </div>

      <pre
        className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg p-3
                   text-xs text-[var(--text)] overflow-auto max-h-96"
      >
        {JSON.stringify(masked, null, 2)}
      </pre>

      {saveError && (
        <p className="text-sm text-red-400" role="alert">
          {saveError}
        </p>
      )}

      <div className="flex justify-between pt-2">
        <button
          type="button"
          onClick={onBack}
          disabled={saving}
          className="px-4 py-2 rounded-lg border border-[var(--border-medium)] bg-[var(--overlay-bg)]
                     text-[var(--text)] text-sm font-medium
                     hover:bg-[var(--surface-raised)]
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors"
        >
          Back
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent)]
                     text-white text-sm font-medium
                     hover:bg-[var(--accent-2)] disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors"
        >
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  );
}

// ─── Reusable form primitives ──────────────────────────────────────

export function Field({
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
