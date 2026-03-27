'use client';

import React, { useState, useMemo } from 'react';
import type { SLADomain } from '@/types/sla';
import { DOMAIN_SLA_SECTIONS } from '@/types/sla';

// ─── Tool-specific field definitions ────────────────────────────────

interface FieldDef {
  key: string;
  label: string;
  type: 'number' | 'select';
  placeholder?: string;
  options?: { value: string; label: string }[];
  unit?: string;
}

const TOOL_FIELDS: Record<string, FieldDef[]> = {
  ingestion: [
    { key: 'ingestion.syncLagToleranceMinutes', label: 'Sync Lag Tolerance', type: 'number', placeholder: '30', unit: 'min' },
    { key: 'ingestion.failureTolerance', label: 'Failure Tolerance', type: 'select', options: [
      { value: 'none', label: 'None — alert immediately' },
      { value: 'low', label: 'Low — 1 consecutive failure' },
      { value: 'medium', label: 'Medium — 2-3 consecutive' },
      { value: 'high', label: 'High — 4+ consecutive' },
    ]},
    { key: 'ingestion.schemaDriftStrictness', label: 'Schema Drift Strictness', type: 'select', options: [
      { value: 'strict', label: 'Strict — block on any drift' },
      { value: 'warn', label: 'Warn — alert but continue' },
      { value: 'relaxed', label: 'Relaxed — allow drift' },
    ]},
    { key: 'freshness.maxHours', label: 'Max Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
  ],
  orchestration: [
    { key: 'orchestration.runLatencyMinutes', label: 'Run Latency Threshold', type: 'number', placeholder: '60', unit: 'min' },
    { key: 'orchestration.scheduleLagMinutes', label: 'Schedule Lag Tolerance', type: 'number', placeholder: '15', unit: 'min' },
    { key: 'orchestration.failureTolerance', label: 'Failure Tolerance', type: 'select', options: [
      { value: 'none', label: 'None — alert immediately' },
      { value: 'low', label: 'Low — 1 consecutive failure' },
      { value: 'medium', label: 'Medium — 2-3 consecutive' },
      { value: 'high', label: 'High — 4+ consecutive' },
    ]},
  ],
  transform: [
    { key: 'transform.testFailureTolerance', label: 'Test Failure Tolerance', type: 'select', options: [
      { value: 'none', label: 'None — block on any failure' },
      { value: 'warn', label: 'Warn — alert but continue' },
      { value: 'relaxed', label: 'Relaxed — allow failures' },
    ]},
    { key: 'transform.modelFreshnessHours', label: 'Model Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
    { key: 'freshness.maxHours', label: 'Source Freshness', type: 'number', placeholder: '48', unit: 'hrs' },
  ],
  bi: [
    { key: 'bi.freshnessHours', label: 'Dashboard Freshness', type: 'number', placeholder: '12', unit: 'hrs' },
    { key: 'bi.upstreamBreakStrictness', label: 'Upstream Break Strictness', type: 'select', options: [
      { value: 'strict', label: 'Strict — flag immediately' },
      { value: 'warn', label: 'Warn — degrade gracefully' },
      { value: 'relaxed', label: 'Relaxed — ignore upstream' },
    ]},
    { key: 'bi.refreshFailureAlerting', label: 'Refresh Failure Alerting', type: 'select', options: [
      { value: 'immediate', label: 'Immediate' },
      { value: 'batched', label: 'Batched (daily digest)' },
      { value: 'off', label: 'Off' },
    ]},
  ],
  warehouse: [
    { key: 'freshness.maxHours', label: 'Max Freshness', type: 'number', placeholder: '24', unit: 'hrs' },
    { key: 'freshness.warningHours', label: 'Warning Threshold', type: 'number', placeholder: '12', unit: 'hrs' },
  ],
};

// Domain-friendly label for the header
const DOMAIN_LABELS: Record<string, string> = {
  ingestion: 'Ingestion',
  orchestration: 'Orchestration',
  transform: 'Transformation',
  bi: 'BI / Reporting',
  warehouse: 'Warehouse',
};

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
  const fields = TOOL_FIELDS[domain] || TOOL_FIELDS.warehouse;

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
          assignmentType: 'explicit',
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
