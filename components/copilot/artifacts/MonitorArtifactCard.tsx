// components/copilot/artifacts/MonitorArtifactCard.tsx
'use client';

import { useState } from 'react';
import { UIArtifact } from '@/types/artifacts';
import { Check, X, Loader2, Pencil, Clock, Target, Activity } from 'lucide-react';
import { ColumnPicker } from '@/components/schedule/ColumnPicker';

interface MonitorArtifactCardProps {
  artifact: UIArtifact;
  onConfirm: (artifactId: string, editedData?: Record<string, any>) => void;
  onCancel: (artifactId: string) => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  pipeline_health:  'Data Pipeline',
  dashboard_shield: 'Dashboard',
  model_quality:    'Transformation',
  data_drift:       'Data Drift',
  custom_watch:     'Custom',
};

const SCHEDULE_OPTIONS = [
  { value: '*/5 * * * *',  label: 'Every 5 min' },
  { value: '*/15 * * * *', label: 'Every 15 min' },
  { value: '*/30 * * * *', label: 'Every 30 min' },
  { value: '0 * * * *',    label: 'Hourly' },
  { value: '0 */2 * * *',  label: 'Every 2h' },
  { value: '0 */6 * * *',  label: 'Every 6h' },
  { value: '0 */12 * * *', label: 'Every 12h' },
  { value: '0 0 * * *',    label: 'Daily at midnight' },
];

function formatCron(cron: string): string {
  const match = SCHEDULE_OPTIONS.find(o => o.value === cron);
  if (match) return match.label;
  const parts = cron.split(' ');
  if (parts.length !== 5) return cron;
  const [min, hour, dom, , dow] = parts;
  if (min === '*' && hour === '*') return 'Every minute';
  if (min.startsWith('*/') && hour === '*') return `Every ${min.slice(2)} min`;
  if (min === '0' && hour === '*') return 'Hourly';
  if (min === '0' && hour.startsWith('*/')) return `Every ${hour.slice(2)}h`;
  if (min === '0' && hour === '0' && dom === '*') return 'Daily at midnight';
  if (min === '0' && /^\d+$/.test(hour) && dom === '*') return `Daily at ${hour}:00`;
  if (dom === '*' && dow !== '*') return `Weekly on ${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][parseInt(dow)] || dow}`;
  return cron;
}

function prettyMonitorKind(raw: string): string {
  return raw.replace(/_/g, ' ').toLowerCase().replace(/(^|\s)\S/g, t => t.toUpperCase());
}

interface FormValues {
  name: string;
  schedule: string;
  monitors: any[];
  anomalyColumn: string;
}

const ACTION_TONE: Record<string, { label: string; fg: string; bg: string }> = {
  create: { label: 'CREATE', fg: 'var(--success-fg)', bg: 'var(--success-bg)' },
  update: { label: 'UPDATE', fg: 'var(--info-fg)',    bg: 'var(--info-bg)' },
  delete: { label: 'DELETE', fg: 'var(--danger-fg)',  bg: 'var(--danger-bg)' },
};

export default function MonitorArtifactCard({ artifact, onConfirm, onCancel }: MonitorArtifactCardProps) {
  const { data, action, status } = artifact;
  const actionTone = ACTION_TONE[action] || ACTION_TONE.create;
  const categoryLabel = CATEGORY_LABELS[data.watchType] || CATEGORY_LABELS.custom_watch;
  const isProposed  = status === 'proposed';
  const isExecuting = status === 'executing';
  const isCompleted = status === 'completed';
  const isFailed    = status === 'failed';
  const isCancelled = status === 'cancelled';

  const [isEditing, setIsEditing] = useState(false);
  const [form, setForm] = useState<FormValues>(() => ({
    name: data.name || 'Monitor',
    schedule: data.schedule || '0 */6 * * *',
    monitors: Array.isArray(data.monitors) ? data.monitors : [],
    anomalyColumn: '',
  }));

  const hasAnomalyMonitor = form.monitors.some(
    (m: any) => (m.monitor_type || m.monitorType || '').toUpperCase() === 'ANOMALY',
  );

  const handleConfirm = () => {
    const editedData: Record<string, any> = {
      ...data,
      name: form.name,
      schedule: form.schedule,
      monitors: form.monitors,
    };
    if (form.anomalyColumn && hasAnomalyMonitor) {
      editedData.monitors = editedData.monitors.map((m: any) => {
        const mt = (m.monitor_type || m.monitorType || '').toUpperCase();
        return mt === 'ANOMALY'
          ? { ...m, config: { ...(m.config || {}), column: form.anomalyColumn } }
          : m;
      });
    }
    onConfirm(artifact.artifact_id, editedData);
  };

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] my-2 overflow-hidden max-w-[640px]">
      {/* HEADER */}
      <div className="px-3 pt-3 pb-2.5 border-b border-[var(--border)]/60">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span
                className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold tracking-wider"
                style={{ color: actionTone.fg, backgroundColor: actionTone.bg }}
              >
                {actionTone.label}
              </span>
              {data.watchType ? (
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[10.5px] font-medium"
                  style={{ color: 'var(--neutral-fg)', backgroundColor: 'var(--neutral-bg)' }}
                >
                  {categoryLabel}
                </span>
              ) : null}
              <StatusPill
                isProposed={isProposed}
                isExecuting={isExecuting}
                isCompleted={isCompleted}
                isFailed={isFailed}
                isCancelled={isCancelled}
              />
            </div>
            {isEditing ? (
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))}
                className="w-full text-[14px] font-medium bg-transparent border-b border-[var(--border)] focus:border-[var(--text)] outline-none px-0 py-1 text-[var(--text)]"
                autoFocus
              />
            ) : (
              <h3 className="text-[14px] font-medium text-[var(--text)] leading-tight">
                {form.name}
              </h3>
            )}
          </div>

          {isProposed ? (
            <div className="flex items-center gap-1 shrink-0">
              <button
                type="button"
                onClick={() => setIsEditing(v => !v)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11.5px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--hover-bg)]"
              >
                <Pencil className="h-3 w-3" />
                {isEditing ? 'Done' : 'Edit'}
              </button>
              <button
                type="button"
                onClick={() => onCancel(artifact.artifact_id)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11.5px] text-[var(--muted)] hover:bg-[var(--hover-bg)]"
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--danger-fg)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--muted)'; }}
              >
                <X className="h-3 w-3" />
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11.5px] font-medium"
                style={{ color: 'var(--success-fg)', backgroundColor: 'var(--success-bg)' }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--success-bg-strong)'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--success-bg)'; }}
              >
                <Check className="h-3 w-3" />
                Confirm
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {/* META GRID */}
      <div className="px-3 py-2.5 grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 border-b border-[var(--border)]/60">
        <MetaRow icon={<Target className="h-3 w-3" />} label="Target">
          <code className="text-[11.5px] text-[var(--code-fg)] break-all">{data.anchorFqn || '—'}</code>
        </MetaRow>
        <MetaRow icon={<Clock className="h-3 w-3" />} label="Schedule">
          {isEditing ? (
            <select
              value={form.schedule}
              onChange={(e) => setForm(f => ({ ...f, schedule: e.target.value }))}
              className="text-[11.5px] bg-[var(--surface-inset)] border border-[var(--border)] rounded-md px-1.5 py-0.5 text-[var(--text)] focus:outline-none focus:border-[var(--text)]"
            >
              {SCHEDULE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : (
            <span className="text-[12px] text-[var(--text)]">
              {formatCron(form.schedule)}
              <span className="ml-1.5 text-[10.5px] text-[var(--muted)] font-mono">
                {`\`${form.schedule}\``}
              </span>
              {data.timezone && data.timezone !== 'UTC' ? (
                <span className="ml-1.5 text-[10.5px] text-[var(--muted)]">({data.timezone})</span>
              ) : null}
            </span>
          )}
        </MetaRow>
      </div>

      {/* MONITORS LIST */}
      <div className="px-3 py-2.5 space-y-1.5">
        <div className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wider text-[var(--muted)]">
          <Activity className="h-3 w-3" />
          {form.monitors.length} {form.monitors.length === 1 ? 'monitor' : 'monitors'}
        </div>
        <ul className="space-y-1">
          {form.monitors.map((m: any, i: number) => {
            const kindRaw = m.monitor_type || m.monitorType || '';
            const target  = m.target_fqn || m.targetFqn || data.anchorFqn || '';
            return (
              <li
                key={i}
                className="flex items-baseline gap-2 text-[11.5px] py-1 px-1.5 rounded-md hover:bg-[var(--hover-bg)]"
              >
                <span className="font-medium text-[var(--text)] min-w-[90px]">
                  {prettyMonitorKind(kindRaw)}
                </span>
                <code className="text-[11px] text-[var(--code-fg)] truncate" title={target}>
                  {target}
                </code>
                {m.config && Object.keys(m.config).length > 0 ? (
                  <span className="ml-auto text-[10.5px] text-[var(--muted)] font-mono">
                    {summariseConfig(m.config)}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>

        {isEditing && hasAnomalyMonitor && data.anchorFqn ? (
          <div className="mt-2.5 pt-2.5 border-t border-[var(--border)]/60">
            <label className="text-[10.5px] uppercase tracking-wider text-[var(--muted)] mb-1 block">
              Anomaly column
            </label>
            <ColumnPicker
              targetFqn={data.anchorFqn}
              value={form.anomalyColumn}
              onChange={(col) => setForm(f => ({ ...f, anomalyColumn: col }))}
              numericOnly
              className="w-full bg-[var(--surface-inset)] border border-[var(--border)] rounded-md px-2 py-1 text-[11.5px] text-[var(--text)] focus:outline-none focus:border-[var(--text)]"
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function StatusPill({
  isProposed, isExecuting, isCompleted, isFailed, isCancelled,
}: {
  isProposed: boolean;
  isExecuting: boolean;
  isCompleted: boolean;
  isFailed: boolean;
  isCancelled: boolean;
}) {
  if (isExecuting) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] font-medium"
        style={{ color: 'var(--neutral-fg)', backgroundColor: 'var(--neutral-bg)' }}
      >
        <Loader2 className="h-3 w-3 animate-spin" />
        Creating
      </span>
    );
  }
  if (isCompleted) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] font-medium"
        style={{ color: 'var(--success-fg)', backgroundColor: 'var(--success-bg)' }}
      >
        <Check className="h-3 w-3" />
        Created
      </span>
    );
  }
  if (isFailed) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] font-medium"
        style={{ color: 'var(--danger-fg)', backgroundColor: 'var(--danger-bg)' }}
      >
        <X className="h-3 w-3" />
        Failed
      </span>
    );
  }
  if (isCancelled) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] font-medium"
        style={{ color: 'var(--neutral-fg)', backgroundColor: 'var(--neutral-bg)' }}
      >
        <X className="h-3 w-3" />
        Cancelled
      </span>
    );
  }
  if (isProposed) {
    return (
      <span
        className="inline-flex items-center px-1.5 py-0.5 rounded text-[10.5px] font-medium"
        style={{ color: 'var(--warning-fg)', backgroundColor: 'var(--warning-bg)' }}
      >
        Proposed
      </span>
    );
  }
  return null;
}

function MetaRow({
  icon, label, children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2 min-w-0">
      <span className="inline-flex items-center gap-1 text-[10.5px] uppercase tracking-wider text-[var(--muted)] shrink-0">
        {icon}
        {label}
      </span>
      <span className="min-w-0 flex-1">{children}</span>
    </div>
  );
}

function summariseConfig(config: Record<string, any>): string {
  const entries = Object.entries(config).slice(0, 2);
  return entries.map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ');
}
