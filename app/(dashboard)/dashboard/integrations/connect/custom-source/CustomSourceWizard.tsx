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

import { useEffect, useRef, useState } from 'react';
import { Check, Trash2, Plus, CheckCircle2, XCircle, Loader2, ChevronDown, ChevronUp } from 'lucide-react';

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

// ─── Step 3: Discovery ─────────────────────────────────────────────

interface DiscoveryCandidate {
  source: 'probe' | 'warehouse' | 'ingestion';
  endpoint: string | null;
  json_root: string | null;
  timestamp_column: string | null;
  expected_schema: Array<{ name: string; data_type: string; is_nullable: boolean }>;
  lands_in: string | null;
  confidence: number;
}

interface DiscoveryResponse {
  candidates_by_path: {
    probe?: DiscoveryCandidate[];
    warehouse?: DiscoveryCandidate[];
    ingestion?: DiscoveryCandidate[];
  };
  errors_by_path: {
    probe?: { code: string; message: string } | null;
    warehouse?: { code: string; message: string } | null;
    ingestion?: { code: string; message: string } | null;
  };
}

/**
 * A candidate row that the user can accept/reject and edit.
 */
interface EditableCandidate {
  /** original data from the discovery API */
  candidate: DiscoveryCandidate;
  /** user-editable fields */
  endpoint: string;
  jsonRoot: string;
  timestampColumn: string;
  landsIn: string;
  /** whether this row is accepted (will be added to state.datasets) */
  accepted: boolean;
}

function toEditableCandidate(c: DiscoveryCandidate): EditableCandidate {
  return {
    candidate: c,
    endpoint: c.endpoint ?? '',
    jsonRoot: c.json_root ?? '',
    timestampColumn: c.timestamp_column ?? '',
    landsIn: c.lands_in ?? '',
    accepted: true,
  };
}

function editableCandidateToDatasetSpec(ec: EditableCandidate, index: number): DatasetSpec {
  // Derive an ID slug from the endpoint path
  const slug = ec.endpoint
    .replace(/^\//, '')
    .replace(/[^a-z0-9_]/gi, '_')
    .toLowerCase() || `dataset_${index + 1}`;
  return {
    id: slug,
    endpoint: ec.endpoint,
    timestampColumn: ec.timestampColumn,
    ...(ec.jsonRoot ? { jsonRoot: ec.jsonRoot } : {}),
    ...(ec.landsIn ? { landsIn: ec.landsIn } : {}),
  };
}

function DiscoveryStep({
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DiscoveryResponse | null>(null);
  const [rows, setRows] = useState<EditableCandidate[]>([]);
  const [showManualForm, setShowManualForm] = useState(false);
  const [manualEndpoint, setManualEndpoint] = useState('');
  const hasFetched = useRef(false);

  const inputClass =
    'w-full px-3 py-2.5 bg-[var(--overlay-bg)] border border-[var(--border-medium)] rounded-lg ' +
    'text-[var(--text)] placeholder-[var(--text-faint)] ' +
    'focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] ' +
    'transition-colors text-sm';

  async function runDiscover() {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch('/api/v1/integrations/source/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base_url: state.baseUrl,
          endpoint: '/',
          auth: {
            kind: state.auth.kind,
            header_name: state.auth.headerName ?? null,
            // secret is passed as secret_ref — the backend uses it directly for now
            // (Task 6 will wire proper secret resolution)
            secret_ref: state.auth.secret,
          },
          ingestion_hints: [],
          warehouse_hints: [],
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({})) as { detail?: string; error?: string };
        setError(err.detail ?? err.error ?? `Discovery failed (HTTP ${resp.status})`);
        return;
      }
      const data = (await resp.json()) as DiscoveryResponse;
      setResult(data);

      // Build editable rows from all paths
      const allCandidates: EditableCandidate[] = [
        ...(data.candidates_by_path.probe ?? []).map(toEditableCandidate),
        ...(data.candidates_by_path.warehouse ?? []).map(toEditableCandidate),
        ...(data.candidates_by_path.ingestion ?? []).map(toEditableCandidate),
      ];
      setRows(allCandidates);
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'Network error');
    } finally {
      setLoading(false);
    }
  }

  // Run discovery automatically on mount
  useEffect(() => {
    if (hasFetched.current) return;
    hasFetched.current = true;
    runDiscover();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateRow = (index: number, patch: Partial<EditableCandidate>) => {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  };

  const removeRow = (index: number) => {
    setRows((prev) => prev.filter((_, i) => i !== index));
  };

  const addManualEndpoint = () => {
    if (!manualEndpoint.trim()) return;
    const manual: DiscoveryCandidate = {
      source: 'probe',
      endpoint: manualEndpoint.trim(),
      json_root: null,
      timestamp_column: null,
      expected_schema: [],
      lands_in: null,
      confidence: 1.0,
    };
    setRows((prev) => [...prev, toEditableCandidate(manual)]);
    setManualEndpoint('');
    setShowManualForm(false);
  };

  const acceptedRows = rows.filter((r) => r.accepted);
  const canProceed = acceptedRows.length > 0 &&
    acceptedRows.every((r) => r.endpoint.trim().length > 0);

  const handleNext = () => {
    const datasets = acceptedRows.map(editableCandidateToDatasetSpec);
    onChange({ datasets });
    onNext();
  };

  const probeRows = rows.filter((r) => r.candidate.source === 'probe');
  const warehouseRows = rows.filter((r) => r.candidate.source === 'warehouse');
  const ingestionRows = rows.filter((r) => r.candidate.source === 'ingestion');

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-[var(--text)]">Discovery</h2>
        <p className="mt-1 text-sm text-[var(--text-tertiary)]">
          Pallisade probes your source to discover dataset candidates. Accept the rows
          you want to monitor and fill in any missing details.
        </p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-[var(--text-tertiary)]">
          <Loader2 className="w-4 h-4 animate-spin" />
          Discovering datasets…
        </div>
      )}

      {error && !loading && (
        <div className="flex items-center gap-2">
          <p className="text-sm text-red-400">{error}</p>
          <button
            type="button"
            onClick={runDiscover}
            className="text-xs text-[var(--accent-2)] underline"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && result && (
        <div className="space-y-6">
          {/* Path: probe */}
          <DiscoverySection
            title="From source probe"
            subtitle="Discovered by probing your API directly."
            rows={probeRows}
            allRows={rows}
            onUpdate={updateRow}
            onRemove={removeRow}
            inputClass={inputClass}
          />

          {/* Path: warehouse */}
          <DiscoverySection
            title="From your warehouse"
            subtitle="Tables that appear to receive data from this source. (Available in a future update.)"
            rows={warehouseRows}
            allRows={rows}
            onUpdate={updateRow}
            onRemove={removeRow}
            inputClass={inputClass}
          />

          {/* Path: ingestion */}
          <DiscoverySection
            title="From Fivetran / Airbyte / Stitch"
            subtitle="Connectors detected in your ingestion tools. (Available in a future update.)"
            rows={ingestionRows}
            allRows={rows}
            onUpdate={updateRow}
            onRemove={removeRow}
            inputClass={inputClass}
          />
        </div>
      )}

      {/* Manual add */}
      {!loading && (
        <div className="space-y-2">
          {showManualForm ? (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={manualEndpoint}
                onChange={(e) => setManualEndpoint(e.target.value)}
                placeholder="/your/endpoint"
                className={inputClass + ' flex-1'}
                onKeyDown={(e) => e.key === 'Enter' && addManualEndpoint()}
                autoFocus
              />
              <button
                type="button"
                onClick={addManualEndpoint}
                disabled={!manualEndpoint.trim()}
                className="px-3 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium
                           hover:bg-[var(--accent-2)] disabled:opacity-50 transition-colors"
              >
                Add
              </button>
              <button
                type="button"
                onClick={() => { setShowManualForm(false); setManualEndpoint(''); }}
                className="px-3 py-2 rounded-lg border border-[var(--border-medium)] text-sm
                           text-[var(--text)] hover:bg-[var(--surface-raised)] transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowManualForm(true)}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-dashed
                         border-[var(--border-medium)] bg-[var(--overlay-bg)]
                         text-sm font-medium text-[var(--text-tertiary)]
                         hover:border-[var(--accent)] hover:text-[var(--accent-2)]
                         transition-colors"
            >
              <Plus className="w-4 h-4" />
              Add endpoint manually
            </button>
          )}
        </div>
      )}

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
          disabled={!canProceed || loading}
          onClick={handleNext}
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

function DiscoverySection({
  title,
  subtitle,
  rows,
  allRows,
  onUpdate,
  onRemove,
  inputClass,
}: {
  title: string;
  subtitle: string;
  rows: EditableCandidate[];
  allRows: EditableCandidate[];
  onUpdate: (index: number, patch: Partial<EditableCandidate>) => void;
  onRemove: (index: number) => void;
  inputClass: string;
}) {
  if (rows.length === 0) return null;

  return (
    <div className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold text-[var(--text)]">{title}</h3>
        <p className="text-xs text-[var(--text-faint)]">{subtitle}</p>
      </div>
      <div className="space-y-2">
        {rows.map((row) => {
          const globalIdx = allRows.indexOf(row);
          return (
            <CandidateRow
              key={globalIdx}
              row={row}
              inputClass={inputClass}
              onUpdate={(patch) => onUpdate(globalIdx, patch)}
              onRemove={() => onRemove(globalIdx)}
            />
          );
        })}
      </div>
    </div>
  );
}

function CandidateRow({
  row,
  inputClass,
  onUpdate,
  onRemove,
}: {
  row: EditableCandidate;
  inputClass: string;
  onUpdate: (patch: Partial<EditableCandidate>) => void;
  onRemove: () => void;
}) {
  const [showSchema, setShowSchema] = useState(false);
  const hasSchema = row.candidate.expected_schema.length > 0;

  return (
    <div
      className={`rounded-lg border p-4 space-y-3 transition-colors ${
        row.accepted
          ? 'border-[var(--subtle-border)] bg-[var(--overlay-bg)]'
          : 'border-[var(--subtle-border)] bg-[var(--surface-raised)] opacity-60'
      }`}
    >
      {/* Header row: accept toggle + remove */}
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={row.accepted}
            onChange={(e) => onUpdate({ accepted: e.target.checked })}
            className="accent-[var(--accent)] w-4 h-4"
          />
          <span className="text-sm font-medium text-[var(--text)]">
            {row.endpoint || '(no endpoint)'}
          </span>
          <span className="text-xs text-[var(--text-faint)]">
            confidence {Math.round(row.candidate.confidence * 100)}%
          </span>
        </label>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove candidate"
          className="p-1.5 rounded-md text-[var(--text-faint)]
                     hover:text-red-400 hover:bg-[var(--surface-raised)]
                     transition-colors"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {row.accepted && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Endpoint" required hint="Appended to base URL.">
            <input
              type="text"
              value={row.endpoint}
              onChange={(e) => onUpdate({ endpoint: e.target.value })}
              placeholder="/sensors/readings"
              className={inputClass}
            />
          </Field>

          <Field label="JSON root" hint="Dotted path to the array (leave blank for top-level array).">
            <input
              type="text"
              value={row.jsonRoot}
              onChange={(e) => onUpdate({ jsonRoot: e.target.value })}
              placeholder="data.items"
              className={inputClass}
            />
          </Field>

          <Field label="Timestamp column" hint="JSON field used for freshness.">
            <input
              type="text"
              value={row.timestampColumn}
              onChange={(e) => onUpdate({ timestampColumn: e.target.value })}
              placeholder="reading_at"
              className={inputClass}
            />
          </Field>

          <Field
            label="Lands in (optional)"
            hint="warehouse.schema.table — leave blank to skip auto-edges."
          >
            <input
              type="text"
              value={row.landsIn}
              onChange={(e) => onUpdate({ landsIn: e.target.value })}
              placeholder="e.g. snowflake.raw.water_meters"
              className={inputClass}
            />
          </Field>
        </div>
      )}

      {/* Schema preview */}
      {row.accepted && hasSchema && (
        <div>
          <button
            type="button"
            onClick={() => setShowSchema((s) => !s)}
            className="inline-flex items-center gap-1 text-xs text-[var(--text-faint)]
                       hover:text-[var(--text-tertiary)] transition-colors"
          >
            {showSchema ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {row.candidate.expected_schema.length} column
            {row.candidate.expected_schema.length !== 1 ? 's' : ''} detected
          </button>
          {showSchema && (
            <div className="mt-1.5 rounded-md border border-[var(--subtle-border)] overflow-auto max-h-36">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[var(--subtle-border)] bg-[var(--surface-raised)]">
                    <th className="px-3 py-1.5 text-left font-medium text-[var(--text-tertiary)]">Column</th>
                    <th className="px-3 py-1.5 text-left font-medium text-[var(--text-tertiary)]">Type</th>
                    <th className="px-3 py-1.5 text-left font-medium text-[var(--text-tertiary)]">Nullable</th>
                  </tr>
                </thead>
                <tbody>
                  {row.candidate.expected_schema.map((col) => (
                    <tr key={col.name} className="border-b border-[var(--subtle-border)] last:border-0">
                      <td className="px-3 py-1.5 text-[var(--text)] font-mono">{col.name}</td>
                      <td className="px-3 py-1.5 text-[var(--text-tertiary)]">{col.data_type}</td>
                      <td className="px-3 py-1.5">
                        {col.is_nullable ? (
                          <CheckCircle2 className="w-3 h-3 text-[var(--text-faint)]" />
                        ) : (
                          <XCircle className="w-3 h-3 text-[var(--text-faint)]" />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
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
