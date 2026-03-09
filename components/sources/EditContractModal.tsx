'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Save, Loader2, ArrowDown } from 'lucide-react';
import { ControlPlaneSource, SourceContractData, SlaTier } from './types';
import {
  EffectiveContract,
  PipelineContractData,
  SourceContractWithOverrides,
  InheritanceState,
  INHERITANCE_CONFIG,
  getOverrideKey,
  OVERRIDE_LABELS,
  validateOverrides,
} from '@/components/contracts/types';
import { resolveEffectiveContract } from '@/lib/contracts/resolver';
import WarehouseOverrides from '@/components/contracts/overrides/WarehouseOverrides';
import TransformationOverrides from '@/components/contracts/overrides/TransformationOverrides';
import OrchestrationOverrides from '@/components/contracts/overrides/OrchestrationOverrides';

const SLA_OPTIONS: { value: SlaTier; label: string }[] = [
  { value: 'T0', label: 'T0 — Critical' },
  { value: 'T1', label: 'T1 — High' },
  { value: 'T2', label: 'T2 — Medium' },
  { value: 'T3', label: 'T3 — Low' },
];

interface Props {
  source: ControlPlaneSource;
  pipelineContract?: PipelineContractData | null;
  onClose: () => void;
  onSaved: () => void;
}

export default function EditContractModal({ source, pipelineContract, onClose, onSaved }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Core fields
  const [ownerUser, setOwnerUser] = useState(source.contract?.ownerUser || '');
  const [ownerTeam, setOwnerTeam] = useState(source.contract?.ownerTeam || '');
  const [contactChannel, setContactChannel] = useState(source.contract?.contactChannel || '');
  const [slaTier, setSlaTier] = useState<string>(source.contract?.slaTier || '');
  const [expectedFreshnessMinutes, setExpectedFreshnessMinutes] = useState<string>(
    source.contract?.expectedFreshnessMinutes?.toString() || ''
  );
  const [expectedExtractionFrequencyMinutes, setExpectedExtractionFrequencyMinutes] = useState<string>(
    source.contract?.expectedExtractionFrequencyMinutes?.toString() || ''
  );
  const [notes, setNotes] = useState(source.contract?.notes || '');

  // Inheritance
  const [inheritFromPipeline, setInheritFromPipeline] = useState(
    (source.contract as any)?.inheritFromPipeline ?? true
  );

  // Tool-specific overrides
  const [overrides, setOverrides] = useState<Record<string, any>>(
    (source.contract as any)?.overridesJson || {}
  );

  const overrideKey = getOverrideKey(source.integrationType);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Build effective contract preview
  const sourceForResolver: SourceContractWithOverrides = {
    ownerUser: ownerUser || null,
    ownerTeam: ownerTeam || null,
    contactChannel: contactChannel || null,
    slaTier: (slaTier || null) as SlaTier | null,
    expectedFreshnessMinutes: expectedFreshnessMinutes ? Number(expectedFreshnessMinutes) : null,
    expectedExtractionFrequencyMinutes: expectedExtractionFrequencyMinutes ? Number(expectedExtractionFrequencyMinutes) : null,
    notes: notes || null,
    inheritFromPipeline,
    pipelineStackId: source.stackId,
    overridesJson: Object.keys(overrides).length > 0 ? overrides : null,
  };
  const effective = resolveEffectiveContract(pipelineContract || null, sourceForResolver, source.integrationType);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      // Clean overrides: remove undefined values
      const cleanOverrides: Record<string, any> = {};
      for (const [k, v] of Object.entries(overrides)) {
        if (v !== undefined && v !== null && v !== '') cleanOverrides[k] = v;
      }

      const body: Record<string, any> = {
        ownerUser: ownerUser || null,
        ownerTeam: ownerTeam || null,
        contactChannel: contactChannel || null,
        slaTier: slaTier || null,
        expectedFreshnessMinutes: expectedFreshnessMinutes ? Number(expectedFreshnessMinutes) : null,
        expectedExtractionFrequencyMinutes: expectedExtractionFrequencyMinutes ? Number(expectedExtractionFrequencyMinutes) : null,
        notes: notes || null,
        inheritFromPipeline,
        pipelineStackId: source.stackId || null,
        overridesJson: Object.keys(cleanOverrides).length > 0 ? cleanOverrides : null,
      };

      const res = await fetch(`/api/integrations/${source.id}/contract`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to save contract');
      }
      onSaved();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const inputClass =
    'w-full px-4 py-3 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)] text-[var(--text)] text-sm placeholder:text-[var(--text-faint)] focus:outline-none focus:border-[var(--border-medium)] transition-colors';

  const pipelinePlaceholder = (field: keyof PipelineContractData) => {
    if (!inheritFromPipeline || !pipelineContract) return undefined;
    const val = pipelineContract[field];
    return val ? `Pipeline default: ${val}` : undefined;
  };

  return createPortal(
    <>
      <div className="fixed inset-0 bg-black/50 z-50" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="w-full max-w-2xl bg-[var(--surface)] rounded-xl border border-[var(--subtle-border)]
                     shadow-2xl overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-8 py-5 border-b border-[var(--subtle-border)]">
            <h2 className="text-base font-semibold text-[var(--text)]">
              Edit Contract &mdash; {source.name}
            </h2>
            <button onClick={onClose} className="p-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[var(--text-tertiary)] transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Form */}
          <div className="px-8 py-7 max-h-[65vh] overflow-y-auto">
            {error && (
              <div className="px-4 py-3 mb-6 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
                {error}
              </div>
            )}

            {/* Inheritance Toggle */}
            {pipelineContract && (
              <div className="pb-6 mb-6 border-b border-[var(--subtle-border)]">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-faint)] mb-1">Pipeline Inheritance</h3>
                    <p className="text-xs text-[var(--text-faint)]">
                      {inheritFromPipeline
                        ? 'Inheriting defaults from pipeline contract. Set fields below to override.'
                        : 'Standalone contract — not inheriting from pipeline.'}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setInheritFromPipeline(!inheritFromPipeline)}
                    className={`relative w-11 h-6 rounded-full transition-colors ${
                      inheritFromPipeline ? 'bg-[var(--accent)]' : 'bg-[var(--overlay-medium)]'
                    }`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                      inheritFromPipeline ? 'translate-x-5' : ''
                    }`} />
                  </button>
                </div>
              </div>
            )}

            {/* Ownership */}
            <Section title="Ownership">
              <Field label="Owner (User)">
                <input
                  type="text"
                  value={ownerUser}
                  onChange={(e) => setOwnerUser(e.target.value)}
                  placeholder={pipelinePlaceholder('ownerUser') || 'e.g. jane.doe'}
                  className={inputClass}
                />
              </Field>
              <Field label="Owner (Team)">
                <input
                  type="text"
                  value={ownerTeam}
                  onChange={(e) => setOwnerTeam(e.target.value)}
                  placeholder={pipelinePlaceholder('ownerTeam') || 'e.g. Data Platform'}
                  className={inputClass}
                />
              </Field>
              <Field label="Contact Channel">
                <input
                  type="text"
                  value={contactChannel}
                  onChange={(e) => setContactChannel(e.target.value)}
                  placeholder={pipelinePlaceholder('contactChannel') || 'e.g. #data-alerts'}
                  className={inputClass}
                />
              </Field>
            </Section>

            {/* SLA & Expectations */}
            <Section title="SLA & Expectations">
              <Field label="SLA Tier">
                <select
                  value={slaTier}
                  onChange={(e) => setSlaTier(e.target.value)}
                  className={inputClass}
                >
                  <option value="">
                    {inheritFromPipeline && pipelineContract?.slaTier
                      ? `Pipeline default: ${pipelineContract.slaTier}`
                      : 'None'}
                  </option>
                  {SLA_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </Field>
              <Field label="Expected Freshness (minutes)">
                <input
                  type="number"
                  min={0}
                  value={expectedFreshnessMinutes}
                  onChange={(e) => setExpectedFreshnessMinutes(e.target.value)}
                  placeholder={pipelinePlaceholder('expectedFreshnessMinutes') || 'e.g. 60'}
                  className={inputClass}
                />
              </Field>
              <Field label="Extraction Frequency (minutes)">
                <input
                  type="number"
                  min={0}
                  value={expectedExtractionFrequencyMinutes}
                  onChange={(e) => setExpectedExtractionFrequencyMinutes(e.target.value)}
                  placeholder={pipelinePlaceholder('expectedExtractionFrequencyMinutes') || 'e.g. 360'}
                  className={inputClass}
                />
              </Field>
            </Section>

            {/* Notes */}
            <Section title="Notes">
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Additional notes about this source..."
                rows={3}
                className={`${inputClass} resize-none`}
              />
            </Section>

            {/* Tool-Specific Overrides */}
            {overrideKey && (
              <Section title={`${OVERRIDE_LABELS[overrideKey]} Overrides`}>
                {overrideKey === 'warehouse' && (
                  <WarehouseOverrides value={overrides} onChange={setOverrides} inputClass={inputClass} />
                )}
                {overrideKey === 'transformation' && (
                  <TransformationOverrides value={overrides} onChange={setOverrides} inputClass={inputClass} />
                )}
                {overrideKey === 'orchestration' && (
                  <OrchestrationOverrides value={overrides} onChange={setOverrides} inputClass={inputClass} />
                )}
                {!['warehouse', 'transformation', 'orchestration'].includes(overrideKey) && (
                  <p className="text-xs text-[var(--text-faint)]">
                    Tool-specific overrides for {OVERRIDE_LABELS[overrideKey]} will be available soon.
                  </p>
                )}
              </Section>
            )}

            {/* Effective Contract Preview */}
            <div className="mt-2 p-4 rounded-lg bg-[var(--overlay-faint)] border border-[var(--subtle-border)]">
              <div className="flex items-center gap-2 mb-3">
                <ArrowDown className="w-3.5 h-3.5 text-[var(--text-faint)]" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-faint)]">
                  Effective Contract Preview
                </h3>
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                  INHERITANCE_CONFIG[effective.inheritanceState].bg
                } ${INHERITANCE_CONFIG[effective.inheritanceState].color}`}>
                  {INHERITANCE_CONFIG[effective.inheritanceState].label}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
                <PreviewField label="Owner" value={effective.ownerUser || effective.ownerTeam} />
                <PreviewField label="Contact" value={effective.contactChannel} />
                <PreviewField label="SLA Tier" value={effective.slaTier} />
                <PreviewField label="Freshness" value={effective.expectedFreshnessMinutes ? `${effective.expectedFreshnessMinutes}m` : null} />
                <PreviewField label="Extraction Freq" value={effective.expectedExtractionFrequencyMinutes ? `${effective.expectedExtractionFrequencyMinutes}m` : null} />
                {Object.keys(effective.toolOverrides).length > 0 && (
                  <div className="col-span-2 mt-1 pt-1 border-t border-[var(--subtle-border)]">
                    <span className="text-[var(--text-faint)]">Tool overrides: </span>
                    <span className="text-[var(--text-secondary)]">
                      {Object.entries(effective.toolOverrides).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 px-8 py-4 border-t border-[var(--subtle-border)]">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--hover-bg)] transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-5 py-2 rounded-lg bg-[var(--accent)] hover:bg-[var(--accent-2)]
                         text-white text-sm font-medium transition-colors disabled:opacity-50"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Save
            </button>
          </div>
        </div>
      </div>

    </>,
    document.body,
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="pb-6 mb-6 border-b border-[var(--subtle-border)]">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-faint)] mb-4">{title}</h3>
      <div className="space-y-5">{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[13px] font-medium text-[var(--text-tertiary)] mb-2">{label}</label>
      {children}
    </div>
  );
}

function PreviewField({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[var(--text-faint)]">{label}:</span>
      <span className={value ? 'text-[var(--text-secondary)]' : 'text-[var(--text-faint)] italic'}>
        {value || 'not set'}
      </span>
    </div>
  );
}
