'use client';

/**
 * DiscoveryStep — Step 3 of the Custom Source Wizard.
 *
 * Extracted from CustomSourceWizard.tsx to keep each file under ~750 lines.
 * Contains:
 *   - DiscoveryCandidate / DiscoveryResponse / EditableCandidate interfaces
 *   - toEditableCandidate / editableCandidateToDatasetSpec helpers
 *   - DiscoveryStep / DiscoverySection / CandidateRow components
 */

import { useEffect, useRef, useState } from 'react';
import { Trash2, Plus, X, CheckCircle2, XCircle, Loader2, ChevronDown, ChevronUp } from 'lucide-react';

import { usePipeline } from '@/contexts/PipelineContext';

import type { DatasetSpec, WizardState } from './CustomSourceWizard';
import { Field } from './CustomSourceWizard';

// ─── Discovery types ───────────────────────────────────────────────

export interface DiscoveryCandidate {
  source: 'probe' | 'warehouse' | 'ingestion';
  endpoint: string | null;
  json_root: string | null;
  timestamp_column: string | null;
  expected_schema: Array<{ name: string; data_type: string; is_nullable: boolean }>;
  lands_in: string | null;
  confidence: number;
}

export interface DiscoveryResponse {
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
export interface EditableCandidate {
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

// ─── Helpers ───────────────────────────────────────────────────────

export function toEditableCandidate(c: DiscoveryCandidate): EditableCandidate {
  return {
    candidate: c,
    endpoint: c.endpoint ?? '',
    jsonRoot: c.json_root ?? '',
    timestampColumn: c.timestamp_column ?? '',
    landsIn: c.lands_in ?? '',
    accepted: true,
  };
}

export function editableCandidateToDatasetSpec(ec: EditableCandidate, index: number): DatasetSpec {
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

// ─── Components ────────────────────────────────────────────────────

export function DiscoveryStep({
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
  const { selectedPipelineId } = usePipeline();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DiscoveryResponse | null>(null);
  const [rows, setRows] = useState<EditableCandidate[]>([]);
  const [showManualForm, setShowManualForm] = useState(false);
  const [manualEndpoint, setManualEndpoint] = useState('');
  // Warehouse hint chips — user-typed FQNs like "snowflake.raw.water_meters"
  const [warehouseHints, setWarehouseHints] = useState<string[]>([]);
  const [hintInput, setHintInput] = useState('');
  // hasFetched guards the auto-run on mount. Because CustomSourceWizard renders
  // steps with a `step === N ? <X /> : null` pattern, this component unmounts when
  // the user navigates away and re-mounts fresh on return — no reset needed.
  const hasFetched = useRef(false);

  const inputClass =
    'w-full px-3 py-2.5 bg-[var(--overlay-bg)] border border-[var(--border-medium)] rounded-lg ' +
    'text-[var(--text)] placeholder-[var(--text-faint)] ' +
    'focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] ' +
    'transition-colors text-sm';

  async function runDiscover(hints: string[] = warehouseHints) {
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
          warehouse_hints: hints,
          // stack_id is null when no pipeline profile is selected; the backend treats
          // null as the "default" cache slot, which means warehouse FQN resolution
          // falls back to whatever configs were cached during the most recent
          // no-stack investigation. Users without a selected pipeline may see no
          // candidates surface.
          stack_id: selectedPipelineId,
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
    runDiscover([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Add a warehouse hint chip and re-run discovery
  function addWarehouseHint(raw: string) {
    const fqn = raw.trim();
    if (!fqn || warehouseHints.includes(fqn)) return;
    const next = [...warehouseHints, fqn];
    setWarehouseHints(next);
    setHintInput('');
    runDiscover(next);
  }

  function removeWarehouseHint(fqn: string) {
    const next = warehouseHints.filter((h) => h !== fqn);
    setWarehouseHints(next);
    runDiscover(next);
  }

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
    acceptedRows.every((r) => r.endpoint.trim().length > 0 && r.timestampColumn.trim().length > 0);

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

      {/* Warehouse landing table hints */}
      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-[var(--text-tertiary)]">
          Warehouse landing tables{' '}
          <span className="text-[var(--text-faint)] font-normal">(optional)</span>
        </label>
        <p className="text-xs text-[var(--text-faint)]">
          Tell Pallisade which warehouse tables this source lands in. Enter FQNs like{' '}
          <code className="font-mono">snowflake.raw.water_meters</code> — one per line or
          press Enter after each. Pallisade will fetch column schemas to pre-fill the
          &quot;From your warehouse&quot; section below.
        </p>
        {/* Chips */}
        {warehouseHints.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {warehouseHints.map((fqn) => (
              <span
                key={fqn}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                           bg-[var(--surface-raised)] border border-[var(--border-medium)]
                           text-xs text-[var(--text)] font-mono"
              >
                {fqn}
                <button
                  type="button"
                  onClick={() => removeWarehouseHint(fqn)}
                  aria-label={`Remove ${fqn}`}
                  className="ml-0.5 text-[var(--text-faint)] hover:text-red-400 transition-colors"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        {/* Input */}
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={hintInput}
            onChange={(e) => setHintInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); addWarehouseHint(hintInput); }
            }}
            placeholder="warehouse.schema.table"
            className={
              'flex-1 px-3 py-2 bg-[var(--overlay-bg)] border border-[var(--border-medium)] rounded-lg ' +
              'text-[var(--text)] placeholder-[var(--text-faint)] font-mono text-xs ' +
              'focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] ' +
              'transition-colors'
            }
          />
          <button
            type="button"
            onClick={() => addWarehouseHint(hintInput)}
            disabled={!hintInput.trim()}
            className="px-3 py-2 rounded-lg bg-[var(--accent)] text-white text-xs font-medium
                       hover:bg-[var(--accent-2)] disabled:opacity-50 transition-colors"
          >
            Add
          </button>
        </div>
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
            onClick={() => runDiscover(warehouseHints)}
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
            subtitle="Column schemas from the landing tables you specified above."
            rows={warehouseRows}
            allRows={rows}
            onUpdate={updateRow}
            onRemove={removeRow}
            inputClass={inputClass}
          />

          {/* Path: ingestion */}
          <DiscoverySection
            title="From your ingestion platforms"
            subtitle="Source tables detected from Fivetran, Airbyte, or Stitch connectors that route to this host."
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

          <Field
            label="Timestamp column"
            required
            hint={
              row.accepted && row.timestampColumn.trim().length === 0
                ? 'Required — used for freshness monitoring.'
                : 'JSON field used for freshness.'
            }
          >
            <input
              type="text"
              value={row.timestampColumn}
              onChange={(e) => onUpdate({ timestampColumn: e.target.value })}
              placeholder="reading_at"
              className={
                inputClass +
                (row.accepted && row.timestampColumn.trim().length === 0
                  ? ' border-red-500 focus:border-red-500 focus:ring-red-500'
                  : '')
              }
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
