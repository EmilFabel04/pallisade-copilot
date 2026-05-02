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

import { useCallback, useRef, useState } from 'react';
import { Check, Loader2, XCircle, Clock } from 'lucide-react';

import { usePipeline } from '@/contexts/PipelineContext';
import { DiscoveryStep } from './DiscoveryStep';

type Step = 1 | 2 | 3 | 4 | 5;

// ─── Verify types ───────────────────────────────────────────────────

type DatasetVerifyStatus =
  | 'pending'
  | 'ok'
  | { status: 'error'; code: string; message: string };

interface VerifyState {
  inFlight: boolean;
  /** undefined = verify hasn't started yet */
  allPass: boolean | undefined;
  datasets: Record<string, DatasetVerifyStatus>;
}

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
  const { selectedPipelineId } = usePipeline();
  const [step, setStep] = useState<Step>(1);
  const [state, setState] = useState<WizardState>(INITIAL_STATE);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [verifyState, setVerifyState] = useState<VerifyState>({
    inFlight: false,
    allPass: undefined,
    datasets: {},
  });
  // Track the current verify run to avoid double-firing on re-renders.
  const verifyRunRef = useRef<symbol | null>(null);

  const updateState = (patch: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  };

  /** Fire the /verify SSE stream and update verifyState as events arrive. */
  const runVerify = useCallback(
    async (currentState: WizardState) => {
      const runId = Symbol('verify-run');
      verifyRunRef.current = runId;

      // Initialise all datasets to pending.
      const initialDatasets: Record<string, DatasetVerifyStatus> = {};
      for (const ds of currentState.datasets) {
        initialDatasets[ds.id] = 'pending';
      }
      setVerifyState({ inFlight: true, allPass: undefined, datasets: initialDatasets });

      const body = {
        name: currentState.name,
        platform_label: currentState.platformLabel,
        base_url: currentState.baseUrl,
        auth: {
          kind: currentState.auth.kind,
          header_name: currentState.auth.headerName ?? null,
          username: currentState.auth.username ?? null,
          secret_ref: currentState.auth.secret,
        },
        schedule: currentState.schedule,
        stack_id: selectedPipelineId,
        datasets: currentState.datasets.map((d) => ({
          id: d.id,
          endpoint: d.endpoint,
          json_root: d.jsonRoot ?? null,
          timestamp_column: d.timestampColumn,
          lands_in: d.landsIn ?? null,
          cursor_param: d.cursorParam ?? null,
        })),
      };

      try {
        const resp = await fetch('/api/v1/integrations/source/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
          body: JSON.stringify(body),
        });

        if (!resp.ok || !resp.body) {
          setVerifyState((prev) => ({ ...prev, inFlight: false, allPass: false }));
          return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        // SSE parsing: accumulate lines into a rolling buffer.
        // Each SSE message is separated by a blank line.
        let currentEventName = '';
        let currentDataLine = '';

        const processMessage = (eventName: string, dataLine: string) => {
          if (!dataLine) return;
          try {
            const payload = JSON.parse(dataLine);

            if (eventName === 'dataset_result') {
              setVerifyState((prev) => {
                if (verifyRunRef.current !== runId) return prev;
                const ds: DatasetVerifyStatus =
                  payload.status === 'ok'
                    ? 'ok'
                    : { status: 'error', code: payload.code, message: payload.message };
                return {
                  ...prev,
                  datasets: { ...prev.datasets, [payload.dataset_id]: ds },
                };
              });
            } else if (eventName === 'complete') {
              setVerifyState((prev) => {
                if (verifyRunRef.current !== runId) return prev;
                return { ...prev, inFlight: false, allPass: payload.all_pass as boolean };
              });
            }
          } catch {
            // Malformed JSON in SSE data — ignore.
          }
        };

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });

          // Split on newlines and process complete lines.
          const lines = buf.split('\n');
          buf = lines.pop() ?? ''; // last element may be an incomplete line

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEventName = line.slice('event: '.length).trim();
            } else if (line.startsWith('data: ')) {
              currentDataLine = line.slice('data: '.length).trim();
            } else if (line.trim() === '') {
              // Blank line = end of SSE event block.
              processMessage(currentEventName, currentDataLine);
              currentEventName = '';
              currentDataLine = '';
            }
          }
        }
        // Flush any remaining buffered event (stream ended without trailing blank line).
        if (currentEventName && currentDataLine) {
          processMessage(currentEventName, currentDataLine);
        }

        // Stream ended. If we exited without seeing a `complete` event,
        // inFlight is still true — clear it and surface as failure so the
        // user can retry rather than the Save button hanging forever.
        if (verifyRunRef.current === runId) {
          setVerifyState((prev) => {
            if (!prev.inFlight) return prev; // already finalized by `complete` event
            return { ...prev, inFlight: false, allPass: false };
          });
        }
      } catch {
        if (verifyRunRef.current === runId) {
          setVerifyState((prev) => ({ ...prev, inFlight: false, allPass: false }));
        }
      }
    },
    [],
  );

  // Save can only be invoked when verifyState.allPass === true (gated in canSave below). No persist-on-fail path exists.
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
            onNext={() => {
              setStep(5);
              // Reset verify state and kick off the SSE stream whenever the user
              // enters the Review step (including if they go back and come forward again).
              setVerifyState({ inFlight: false, allPass: undefined, datasets: {} });
              runVerify(state);
            }}
          />
        )}
        {step === 5 && (
          <ReviewStep
            state={state}
            saving={saving}
            saveError={saveError}
            verifyState={verifyState}
            onBack={() => setStep(4)}
            onBackToDiscovery={() => setStep(3)}
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
  verifyState,
  onBack,
  onBackToDiscovery,
  onSave,
}: {
  state: WizardState;
  saving: boolean;
  saveError: string | null;
  verifyState: VerifyState;
  onBack: () => void;
  onBackToDiscovery: () => void;
  onSave: () => void;
}) {
  // Mask the secret in the preview so it never appears in plaintext on screen.
  const masked = {
    ...state,
    auth: { ...state.auth, secret: state.auth.secret ? '•••' : '' },
  };

  const hasAnyError = Object.values(verifyState.datasets).some(
    (s) => typeof s === 'object' && s.status === 'error',
  );
  // Save is only enabled when verify has completed with all-pass.
  const canSave = !saving && verifyState.allPass === true;
  const saveLabel =
    verifyState.inFlight
      ? 'Verifying…'
      : saving
        ? 'Saving…'
        : verifyState.allPass === false
          ? 'Save (blocked)'
          : 'Save';

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-[var(--text)]">Review</h2>
        <p className="mt-1 text-sm text-[var(--text-tertiary)]">
          Pallisade is probing each endpoint before saving. All datasets must pass
          before the integration is persisted.
        </p>
      </div>

      {/* Per-dataset verification status */}
      {state.datasets.length > 0 && (
        <div className="rounded-lg border border-[var(--subtle-border)] overflow-hidden">
          <div className="px-3 py-2 bg-[var(--overlay-bg)] border-b border-[var(--subtle-border)]">
            <span className="text-xs font-medium text-[var(--text-tertiary)] uppercase tracking-wide">
              Endpoint verification
            </span>
          </div>
          <ul className="divide-y divide-[var(--subtle-border)]">
            {state.datasets.map((ds) => {
              const status = verifyState.datasets[ds.id] ?? 'pending';
              const isOk = status === 'ok';
              const isError = typeof status === 'object' && status.status === 'error';
              const isPending = status === 'pending';

              return (
                <li key={ds.id} className="px-3 py-2.5 space-y-1">
                  <div className="flex items-center gap-2">
                    {isPending && (
                      <Clock className="w-4 h-4 text-[var(--text-faint)] shrink-0" />
                    )}
                    {isOk && (
                      <Check className="w-4 h-4 text-green-400 shrink-0" />
                    )}
                    {isError && (
                      <XCircle className="w-4 h-4 text-red-400 shrink-0" />
                    )}
                    <span className="text-sm text-[var(--text)] font-medium">{ds.id}</span>
                    <span className="text-xs text-[var(--text-faint)]">{ds.endpoint}</span>
                    <span
                      className={`ml-auto text-xs font-medium px-1.5 py-0.5 rounded-full
                        ${isPending ? 'bg-[var(--overlay-bg)] text-[var(--text-faint)]' : ''}
                        ${isOk ? 'bg-green-500/10 text-green-400' : ''}
                        ${isError ? 'bg-red-500/10 text-red-400' : ''}
                      `}
                    >
                      {isPending ? 'pending' : isOk ? 'ok' : 'error'}
                    </span>
                  </div>
                  {isError && typeof status === 'object' && (
                    <p className="text-xs text-red-400 pl-6">
                      <span className="font-mono">{status.code}</span>: {status.message}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* "Back to Discovery" shortcut when any dataset errored */}
      {hasAnyError && !verifyState.inFlight && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
          <XCircle className="w-4 h-4 text-red-400 shrink-0" />
          <span className="text-sm text-red-400 flex-1">
            One or more endpoints failed verification. Fix the endpoint configuration and re-run.
          </span>
          <button
            type="button"
            onClick={onBackToDiscovery}
            className="text-xs text-red-400 underline whitespace-nowrap hover:text-red-300 transition-colors"
          >
            Back to Discovery to fix
          </button>
        </div>
      )}

      {/* Inline loading indicator while SSE is in flight */}
      {verifyState.inFlight && (
        <div className="flex items-center gap-2 text-sm text-[var(--text-tertiary)]">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>Verifying endpoints…</span>
        </div>
      )}

      {/* Config JSON preview */}
      <pre
        className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg p-3
                   text-xs text-[var(--text)] overflow-auto max-h-72"
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
          disabled={!canSave}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent)]
                     text-white text-sm font-medium
                     hover:bg-[var(--accent-2)] disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors"
        >
          {(verifyState.inFlight || saving) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {saveLabel}
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
