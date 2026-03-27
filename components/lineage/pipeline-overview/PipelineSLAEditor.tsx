'use client';

import React, { useState, useMemo } from 'react';
import type { SLADomain } from '@/types/sla';
import { DOMAIN_SLA_SECTIONS } from '@/types/sla';
import { PIPELINE_SLA_FIELDS, DOMAIN_LABELS, type PipelineSLAFieldDef } from '@/lib/pipeline-sla-fields';

interface PipelineSLAEditorProps {
  domain: SLADomain;
  nodeFqn: string;
  nodeName: string;
  platform: string;
  stackId: string;
  /** Current overrides from the resolved SLA (if any) */
  currentValues?: Record<string, unknown>;
  onSaved: () => void;
  onCancel: () => void;
}

export function PipelineSLAEditor({
  domain,
  nodeFqn,
  nodeName,
  platform,
  stackId,
  currentValues,
  onSaved,
  onCancel,
}: PipelineSLAEditorProps) {
  const fields = PIPELINE_SLA_FIELDS[domain] || PIPELINE_SLA_FIELDS.warehouse;

  // Initialize values from current SLA or empty
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of fields) {
      const current = currentValues?.[f.key];
      init[f.key] = current != null ? String(current) : '';
    }
    return init;
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasChanges = useMemo(() => {
    return fields.some(f => {
      const current = currentValues?.[f.key];
      const val = values[f.key];
      if (!val && current == null) return false;
      return val !== String(current ?? '');
    });
  }, [values, currentValues, fields]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      // Build overrides object grouped by section
      const overrides: Record<string, Record<string, unknown>> = {};
      for (const f of fields) {
        const val = values[f.key];
        if (!val) continue;
        const [section, field] = f.key.split('.');
        if (!overrides[section]) overrides[section] = {};
        overrides[section][field] = f.type === 'number' ? Number(val) : val;
      }

      const res = await fetch('/api/schedule/policies/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stackId,
          profileId: '__custom',
          assignmentType: 'direct',
          nodeFqns: [nodeFqn],
          nodeDomain: domain,
          overrides,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      onSaved();
    } catch (e: any) {
      setError(e.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-[var(--foreground)] uppercase tracking-wide">
          Pipeline SLA
        </h4>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--subtle-bg)] text-[var(--muted)] border border-[var(--subtle-border)]">
          {DOMAIN_LABELS[domain] || domain}
        </span>
      </div>

      <p className="text-[10px] text-[var(--muted)]">
        Set operational expectations for <span className="font-medium text-[var(--foreground)]">{nodeName}</span> ({platform})
      </p>

      <div className="space-y-2.5">
        {fields.map(f => (
          <div key={f.key}>
            <label className="text-[10px] text-[var(--muted)] block mb-1">
              {f.label}{f.unit ? ` (${f.unit})` : ''}
            </label>
            {f.type === 'select' ? (
              <select
                value={values[f.key]}
                onChange={e => setValues(prev => ({ ...prev, [f.key]: e.target.value }))}
                className="w-full px-2 py-1.5 text-[11px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
              >
                <option value="">Not set</option>
                {f.options?.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            ) : (
              <input
                type="number"
                value={values[f.key]}
                onChange={e => setValues(prev => ({ ...prev, [f.key]: e.target.value }))}
                placeholder={f.placeholder}
                className="w-full px-2 py-1.5 text-[11px] bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-md text-[var(--text)] focus:border-slate-500/50 focus:outline-none"
              />
            )}
          </div>
        ))}
      </div>

      {error && (
        <p className="text-[11px] text-red-400">{error}</p>
      )}

      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={handleSave}
          disabled={saving || !hasChanges}
          className="flex-1 px-3 py-1.5 text-[11px] font-medium rounded-md bg-[var(--accent)] hover:bg-[var(--accent-2)] text-white transition-all disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Expectations'}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-[11px] font-medium rounded-md text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--overlay-bg)] transition-all"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
