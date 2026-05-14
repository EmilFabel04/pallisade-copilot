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

const CATEGORY_LABELS: Record<string, { label: string; tint: string }> = {
  pipeline_health: { label: 'Data Pipeline', tint: 'text-blue-300 bg-blue-500/10' },
  dashboard_shield: { label: 'Dashboard',    tint: 'text-slate-300 bg-slate-500/10' },
  model_quality:   { label: 'Transformation', tint: 'text-amber-300 bg-amber-500/10' },
  data_drift:      { label: 'Data Drift',    tint: 'text-rose-300 bg-rose-500/10' },
  custom_watch:    { label: 'Custom',        tint: 'text-zinc-300 bg-zinc-500/10' },
};

const ACTION_LABELS: Record<string, { text: string; tint: string }> = {
  create: { text: 'CREATE', tint: 'text-emerald-300 bg-emerald-500/10' },
  update: { text: 'UPDATE', tint: 'text-blue-300 bg-blue-500/10' },
  delete: { text: 'DELETE', tint: 'text-rose-300 bg-rose-500/10' },
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

export default function MonitorArtifactCard({ artifact, onConfirm, onCancel }: MonitorArtifactCardProps) {
  const { data, action, status } = artifact;
  const actionLabel = ACTION_LABELS[action] || ACTION_LABELS.create;
  const category    = CATEGORY_LABELS[data.watchType] || CATEGORY_LABELS.custom_watch;
  const isProposed  = status === 'proposed';
  const isExecuting = status === 'executing';
  const isCompleted = status === 'completed';
  const isFailed    = status === 'failed';
  const isCancelled = status === 'cancelled';

  const [isEditing, setIsEditing] = useState(false);
  // Single source of truth — both view and edit modes read from this. Clicking
  // "Done" simply hides the inputs; the display continues to show what the user
  // picked. Confirm sends this whole object back to the executor.
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
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] my-2 overflow-hidden">
      {/* HEADER */}
      <div className="px-4 pt-4 pb-3 border-b border-[var(--border)]/60">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold tracking-wider ${actionLabel.tint}`}>
                {actionLabel.text}
              </span>
              {data.watchType ? (
                <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium ${category.tint}`}>
                  {category.label}
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
                className="w-full text-[15px] font-medium bg-transparent border-b border-[var(--border)] focus:border-[var(--text)] outline-none px-0 py-1 text-[var(--text)]"
                autoFocus
              />
            ) : (
              <h3 className="text-[15px] font-medium text-[var(--text)] leading-tight">
                {form.name}
              </h3>
            )}
          </div>

          {isProposed ? (
            <div className="flex items-center gap-1 shrink-0">
              <button
                type="button"
                onClick={() => setIsEditing(v => !v)}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[12px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--surface-inset)]"
              >
                <Pencil className="h-3 w-3" />
                {isEditing ? 'Done' : 'Edit'}
              </button>
              <button
                type="button"
                onClick={() => onCancel(artifact.artifact_id)}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[12px] text-[var(--muted)] hover:text-rose-300 hover:bg-rose-500/10"
              >
                <X className="h-3 w-3" />
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                className="inline-flex items-center gap-1 px-3 py-1 rounded-md text-[12px] font-medium text-emerald-200 bg-emerald-500/15 hover:bg-emerald-500/25"
              >
                <Check className="h-3 w-3" />
                Confirm
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {/* META GRID */}
      <div className="px-4 py-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 border-b border-[var(--border)]/60 text-[13px]">
        <MetaRow icon={<Target className="h-3.5 w-3.5" />} label="Target">
          <code className="text-[12px] text-indigo-300 break-all">{data.anchorFqn || '—'}</code>
        </MetaRow>
        <MetaRow icon={<Clock className="h-3.5 w-3.5" />} label="Schedule">
          {isEditing ? (
            <select
              value={form.schedule}
              onChange={(e) => setForm(f => ({ ...f, schedule: e.target.value }))}
              className="text-[12px] bg-[var(--surface-inset)] border border-[var(--border)] rounded-md px-2 py-1 text-[var(--text)] focus:outline-none focus:border-[var(--text)]"
            >
              {SCHEDULE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : (
            <span className="text-[var(--text)]">
              {formatCron(form.schedule)}
              <span className="ml-1.5 text-[11px] text-[var(--muted)] font-mono">
                {`\`${form.schedule}\``}
              </span>
              {data.timezone && data.timezone !== 'UTC' ? (
                <span className="ml-1.5 text-[11px] text-[var(--muted)]">({data.timezone})</span>
              ) : null}
            </span>
          )}
        </MetaRow>
      </div>

      {/* MONITORS LIST */}
      <div className="px-4 py-3 space-y-2">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[var(--muted)]">
          <Activity className="h-3 w-3" />
          {form.monitors.length} {form.monitors.length === 1 ? 'monitor' : 'monitors'}
        </div>
        <ul className="space-y-1.5">
          {form.monitors.map((m: any, i: number) => {
            const kindRaw = m.monitor_type || m.monitorType || '';
            const target  = m.target_fqn || m.targetFqn || data.anchorFqn || '';
            return (
              <li
                key={i}
                className="flex items-baseline gap-3 text-[12.5px] py-1.5 px-2 rounded-md hover:bg-[var(--surface-inset)]/40"
              >
                <span className="font-medium text-[var(--text)] min-w-[120px]">
                  {prettyMonitorKind(kindRaw)}
                </span>
                <code className="text-[12px] text-indigo-300/80 truncate" title={target}>
                  {target}
                </code>
                {m.config && Object.keys(m.config).length > 0 ? (
                  <span className="ml-auto text-[11px] text-[var(--muted)] font-mono">
                    {summariseConfig(m.config)}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>

        {isEditing && hasAnomalyMonitor && data.anchorFqn ? (
          <div className="mt-3 pt-3 border-t border-[var(--border)]/60">
            <label className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-1.5 block">
              Anomaly column
            </label>
            <ColumnPicker
              targetFqn={data.anchorFqn}
              value={form.anomalyColumn}
              onChange={(col) => setForm(f => ({ ...f, anomalyColumn: col }))}
              numericOnly
              className="w-full bg-[var(--surface-inset)] border border-[var(--border)] rounded-md px-2 py-1.5 text-[12px] text-[var(--text)] focus:outline-none focus:border-[var(--text)]"
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
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium text-[var(--muted)] bg-[var(--surface-inset)]">
        <Loader2 className="h-3 w-3 animate-spin" />
        Creating
      </span>
    );
  }
  if (isCompleted) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium text-emerald-300 bg-emerald-500/10">
        <Check className="h-3 w-3" />
        Created
      </span>
    );
  }
  if (isFailed) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium text-rose-300 bg-rose-500/10">
        <X className="h-3 w-3" />
        Failed
      </span>
    );
  }
  if (isCancelled) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium text-[var(--muted)] bg-[var(--surface-inset)]">
        <X className="h-3 w-3" />
        Cancelled
      </span>
    );
  }
  if (isProposed) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium text-amber-300 bg-amber-500/10">
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
      <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wider text-[var(--muted)] shrink-0">
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
