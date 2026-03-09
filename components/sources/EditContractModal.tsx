'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, Save, Loader2 } from 'lucide-react';
import { ControlPlaneSource, SourceContractData, SlaTier } from './types';

const SLA_OPTIONS: { value: SlaTier; label: string }[] = [
  { value: 'T0', label: 'T0 — Critical' },
  { value: 'T1', label: 'T1 — High' },
  { value: 'T2', label: 'T2 — Medium' },
  { value: 'T3', label: 'T3 — Low' },
];

interface Props {
  source: ControlPlaneSource;
  onClose: () => void;
  onSaved: () => void;
}

export default function EditContractModal({ source, onClose, onSaved }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<SourceContractData>({
    ownerUser: source.contract?.ownerUser || null,
    ownerTeam: source.contract?.ownerTeam || null,
    contactChannel: source.contract?.contactChannel || null,
    slaTier: source.contract?.slaTier || null,
    expectedFreshnessMinutes: source.contract?.expectedFreshnessMinutes || null,
    expectedExtractionFrequencyMinutes: source.contract?.expectedExtractionFrequencyMinutes || null,
    notes: source.contract?.notes || null,
  });

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`/api/integrations/${source.id}/contract`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
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

  const update = (key: keyof SourceContractData, value: any) => {
    setForm(f => ({ ...f, [key]: value || null }));
  };

  const inputClass =
    'w-full px-4 py-3 rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)] text-[var(--text)] text-sm placeholder:text-[var(--text-faint)] focus:outline-none focus:border-[var(--border-medium)] transition-colors';

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

            {/* Ownership */}
            <Section title="Ownership">
              <Field label="Owner (User)">
                <input
                  type="text"
                  value={form.ownerUser || ''}
                  onChange={(e) => update('ownerUser', e.target.value)}
                  placeholder="e.g. jane.doe"
                  className={inputClass}
                />
              </Field>
              <Field label="Owner (Team)">
                <input
                  type="text"
                  value={form.ownerTeam || ''}
                  onChange={(e) => update('ownerTeam', e.target.value)}
                  placeholder="e.g. Data Platform"
                  className={inputClass}
                />
              </Field>
              <Field label="Contact Channel">
                <input
                  type="text"
                  value={form.contactChannel || ''}
                  onChange={(e) => update('contactChannel', e.target.value)}
                  placeholder="e.g. #data-alerts"
                  className={inputClass}
                />
              </Field>
            </Section>

            {/* SLA & Expectations */}
            <Section title="SLA & Expectations">
              <Field label="SLA Tier">
                <select
                  value={form.slaTier || ''}
                  onChange={(e) => update('slaTier', e.target.value)}
                  className={inputClass}
                >
                  <option value="">None</option>
                  {SLA_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </Field>
              <Field label="Expected Freshness (minutes)">
                <input
                  type="number"
                  min={0}
                  value={form.expectedFreshnessMinutes ?? ''}
                  onChange={(e) => update('expectedFreshnessMinutes', e.target.value ? Number(e.target.value) : null)}
                  placeholder="e.g. 60"
                  className={inputClass}
                />
              </Field>
              <Field label="Extraction Frequency (minutes)">
                <input
                  type="number"
                  min={0}
                  value={form.expectedExtractionFrequencyMinutes ?? ''}
                  onChange={(e) => update('expectedExtractionFrequencyMinutes', e.target.value ? Number(e.target.value) : null)}
                  placeholder="e.g. 360"
                  className={inputClass}
                />
              </Field>
            </Section>

            {/* Notes */}
            <Section title="Notes" noBorder>
              <textarea
                value={form.notes || ''}
                onChange={(e) => update('notes', e.target.value)}
                placeholder="Additional notes about this source..."
                rows={3}
                className={`${inputClass} resize-none`}
              />
            </Section>
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

function Section({ title, noBorder, children }: { title: string; noBorder?: boolean; children: React.ReactNode }) {
  return (
    <div className={noBorder ? '' : 'pb-6 mb-6 border-b border-[var(--subtle-border)]'}>
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
