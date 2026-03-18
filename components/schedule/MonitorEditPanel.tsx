'use client';

import { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { MONITOR_CATALOG } from '@/types/monitor-catalog';
import { PolicyFieldBadge } from './PolicyFieldBadge';
import {
  POLICY_FIELD_MAP,
  getPolicyValueForField,
  isLessStrictClient,
} from '@/lib/policy-utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MonitorEditPanelProps {
  monitor: {
    id: string;
    name: string;
    monitorType: string;
    targetFqn?: string;
    config: Record<string, any>;
    policyOverrides: string[];
  };
  resolvedPolicy: {
    profileName?: string;
    status?: string;
    freshness?: any;
    schema?: any;
    volume?: any;
    anomaly?: any;
    quality?: any;
    ingestion?: any;
    bi?: any;
    orchestration?: any;
    transform?: any;
    [key: string]: any;
  } | null;
  onSave: (monitorId: string, config: Record<string, any>, policyOverrides: string[]) => Promise<void>;
}

// POLICY_FIELD_MAP, getPolicyValueForField, isLessStrictClient imported from @/lib/policy-utils

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const inputClass =
  'w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-lg px-3 py-2 text-[13px] text-[var(--text)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--overlay-strong)]';

export function MonitorEditPanel({ monitor, resolvedPolicy, onSave }: MonitorEditPanelProps) {
  const [config, setConfig] = useState<Record<string, any>>(monitor.config);
  const [overrides, setOverrides] = useState<string[]>(monitor.policyOverrides);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const def = MONITOR_CATALOG.find((m) => m.key === monitor.monitorType);
  const profileName = resolvedPolicy?.profileName;
  const fieldMap = POLICY_FIELD_MAP[monitor.monitorType] || {};

  // Get policy value for a config field key (delegates to shared util)
  const getPolicyValue = useCallback(
    (fieldKey: string): any => {
      return getPolicyValueForField(monitor.monitorType, fieldKey, resolvedPolicy);
    },
    [monitor.monitorType, resolvedPolicy],
  );

  // Update a single config field and track overrides
  const handleFieldChange = useCallback(
    (fieldKey: string, value: any) => {
      setConfig((prev) => ({ ...prev, [fieldKey]: value }));

      const policyValue = getPolicyValue(fieldKey);
      if (policyValue === undefined) return; // no policy mapping, don't track overrides

      const sameAsPolicy = String(value) === String(policyValue);
      setOverrides((prev) => {
        if (sameAsPolicy) {
          return prev.filter((k) => k !== fieldKey);
        } else {
          return prev.includes(fieldKey) ? prev : [...prev, fieldKey];
        }
      });
    },
    [getPolicyValue],
  );

  // Reset a single field to its policy value
  const handleResetField = useCallback(
    (fieldKey: string) => {
      const policyValue = getPolicyValue(fieldKey);
      if (policyValue !== undefined) {
        setConfig((prev) => ({ ...prev, [fieldKey]: policyValue }));
        setOverrides((prev) => prev.filter((k) => k !== fieldKey));
      }
    },
    [getPolicyValue],
  );

  // Reset all policy-mapped fields to policy values
  const handleResetAll = useCallback(() => {
    setConfig((prev) => {
      const next = { ...prev };
      for (const fieldKey of Object.keys(fieldMap)) {
        const pv = getPolicyValue(fieldKey);
        if (pv !== undefined) next[fieldKey] = pv;
      }
      return next;
    });
    setOverrides([]);
  }, [fieldMap, getPolicyValue]);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await onSave(monitor.id, config, overrides);
    } catch (e: any) {
      setError(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const hasPolicyOverrides = overrides.length > 0;

  if (!def) {
    return (
      <div className="text-[12px] text-[var(--text-faint)] py-4">
        Unknown monitor type: {monitor.monitorType}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h3 className="text-[14px] font-medium text-[var(--text)]">{monitor.name}</h3>
        <p className="text-[12px] text-[var(--text-faint)] mt-0.5">
          {def.label} · {monitor.targetFqn || 'No target'}
        </p>
      </div>

      {/* Policy status banner */}
      {resolvedPolicy && (
        <div className="flex items-center justify-between px-3 py-2 bg-violet-500/[0.06] border border-violet-500/[0.12] rounded-lg">
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-violet-400 font-medium">
              {profileName ? `Policy: ${profileName}` : 'Policy applied'}
            </span>
            {hasPolicyOverrides && (
              <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 text-[10px] font-medium">
                {overrides.length} override{overrides.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          {hasPolicyOverrides && (
            <button
              type="button"
              onClick={handleResetAll}
              className="text-[11px] text-violet-400 hover:text-violet-300 underline underline-offset-2 transition-colors"
            >
              Reset all to policy
            </button>
          )}
        </div>
      )}

      {/* Config fields */}
      {def.config_schema.length > 0 ? (
        <div className="space-y-4">
          {def.config_schema.map((field) => {
            const policyValue = getPolicyValue(field.key);
            const isOverridden = overrides.includes(field.key);
            const currentValue = config[field.key];
            const isLessStrict = isLessStrictClient(field.key, currentValue, policyValue);
            const hasPolicyMapping = policyValue !== undefined;

            return (
              <div key={field.key}>
                <div className="flex items-center gap-2 mb-1.5">
                  <label className="text-[12px] font-medium text-[var(--muted)]">
                    {field.label}
                    {field.required && <span className="text-red-400 ml-0.5">*</span>}
                  </label>
                  {hasPolicyMapping && (
                    <PolicyFieldBadge
                      fieldKey={field.key}
                      currentValue={currentValue}
                      policyValue={policyValue}
                      profileName={profileName}
                      isOverridden={isOverridden}
                      isLessStrict={isLessStrict}
                      onReset={() => handleResetField(field.key)}
                    />
                  )}
                </div>

                {field.type === 'text' && (
                  <input
                    type="text"
                    value={currentValue ?? ''}
                    onChange={(e) => handleFieldChange(field.key, e.target.value || undefined)}
                    placeholder={field.placeholder}
                    className={inputClass}
                  />
                )}

                {field.type === 'number' && (
                  <input
                    type="number"
                    value={currentValue ?? ''}
                    onChange={(e) => {
                      const val = e.target.value;
                      handleFieldChange(field.key, val === '' ? undefined : Number(val));
                    }}
                    placeholder={field.placeholder}
                    className={inputClass}
                  />
                )}

                {field.type === 'select' && field.options && (
                  <select
                    value={currentValue ?? field.options[0]?.value ?? ''}
                    onChange={(e) => handleFieldChange(field.key, e.target.value)}
                    className={inputClass}
                  >
                    {field.options.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                )}

                {field.type === 'textarea' && (
                  <textarea
                    value={currentValue ?? ''}
                    onChange={(e) => handleFieldChange(field.key, e.target.value)}
                    placeholder={field.placeholder}
                    rows={3}
                    className={cn(inputClass, 'font-mono')}
                  />
                )}

                {field.type === 'checkbox' && (
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!currentValue}
                      onChange={(e) => handleFieldChange(field.key, e.target.checked)}
                      className="w-4 h-4 rounded border-[var(--overlay-strong)] bg-[var(--overlay-bg)] text-violet-500 focus:ring-violet-500/30 focus:ring-offset-0"
                    />
                    <span className="text-[12px] text-[var(--text-tertiary)]">
                      {field.placeholder || field.label}
                    </span>
                  </label>
                )}

                {field.type === 'multi-text' && (
                  <textarea
                    value={
                      Array.isArray(currentValue)
                        ? currentValue.join('\n')
                        : (currentValue ?? '')
                    }
                    onChange={(e) =>
                      handleFieldChange(
                        field.key,
                        e.target.value.split('\n').filter((v) => v.trim()),
                      )
                    }
                    placeholder={field.placeholder}
                    rows={3}
                    className={inputClass}
                  />
                )}

                {field.help_text && (
                  <p className="text-[11px] text-[var(--text-faint)] mt-1">{field.help_text}</p>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="px-3 py-2.5 bg-emerald-500/[0.06] border border-emerald-500/[0.12] rounded-lg">
          <p className="text-[12px] text-emerald-300/80">
            This monitor is fully auto-configured — no manual fields required.
          </p>
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="text-[12px] text-red-400">{error}</p>
      )}

      {/* Save button */}
      <div className="flex justify-end pt-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 rounded-lg bg-violet-500/20 hover:bg-violet-500/30 text-violet-300 text-[13px] font-medium transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </div>
    </div>
  );
}
