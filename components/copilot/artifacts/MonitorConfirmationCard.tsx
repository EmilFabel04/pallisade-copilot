'use client';

import { useState } from 'react';
import { Activity, AlertTriangle, Check, Clock, Pencil, Target, Trash2, X } from 'lucide-react';

interface MonitorConfirmationCardProps {
  toolName: string; // create_monitor | update_monitor | delete_monitor
  args: Record<string, any>;
  onConfirm: (editedArgs?: Record<string, any>) => void;
  onDeny: () => void;
  isLoading?: boolean;
}

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
  return cron;
}

function prettyMonitorKind(raw: string): string {
  return raw.replace(/_/g, ' ').toLowerCase().replace(/(^|\s)\S/g, t => t.toUpperCase());
}

function summariseConfig(config: Record<string, any>): string {
  const entries = Object.entries(config);
  if (entries.length === 0) return '—';
  return entries.map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ');
}

export function MonitorConfirmationCard({
  toolName,
  args,
  onConfirm,
  onDeny,
  isLoading = false,
}: MonitorConfirmationCardProps) {
  if (toolName === 'delete_monitor') {
    return <DeleteMonitorPreview args={args} onConfirm={onConfirm} onDeny={onDeny} isLoading={isLoading} />;
  }
  if (toolName === 'update_monitor') {
    return <UpdateMonitorPreview args={args} onConfirm={onConfirm} onDeny={onDeny} isLoading={isLoading} />;
  }
  return <CreateMonitorPreview args={args} onConfirm={onConfirm} onDeny={onDeny} isLoading={isLoading} />;
}

// ────────────────────────────────────────────────────────────────────────────
// CREATE
// ────────────────────────────────────────────────────────────────────────────

function CreateMonitorPreview({
  args, onConfirm, onDeny, isLoading,
}: {
  args: Record<string, any>;
  onConfirm: (editedArgs?: Record<string, any>) => void;
  onDeny: () => void;
  isLoading: boolean;
}) {
  const targetFqn = args.target_fqn || '';
  const monitorKind = (args.monitor_kind || '') as string;
  const initialConfig = (args.config || {}) as Record<string, any>;

  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState<string>(args.name || `${monitorKind} on ${targetFqn}`);
  const [schedule, setSchedule] = useState<string>(args.schedule || '0 * * * *');
  const [configText, setConfigText] = useState<string>(JSON.stringify(initialConfig, null, 2));
  const [configError, setConfigError] = useState<string | null>(null);

  const handleConfirm = () => {
    let config = initialConfig;
    if (isEditing) {
      try {
        config = configText.trim() ? JSON.parse(configText) : {};
        setConfigError(null);
      } catch (e: any) {
        setConfigError(`Invalid JSON: ${e.message || e}`);
        return;
      }
    }
    onConfirm({ ...args, name, schedule, config });
  };

  return (
    <Shell tone="propose" onDeny={onDeny} isLoading={isLoading}>
      <Header
        action="CREATE"
        actionTint="text-emerald-200 bg-emerald-500/15"
        title={
          isEditing ? (
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full text-[15px] font-medium bg-transparent border-b border-[var(--border)] focus:border-[var(--text)] outline-none px-0 py-1 text-[var(--text)]"
              autoFocus
            />
          ) : name
        }
        onToggleEdit={() => setIsEditing(v => !v)}
        isEditing={isEditing}
        onConfirm={handleConfirm}
        confirmLabel={isLoading ? 'Creating…' : 'Approve & Create'}
        confirmDisabled={isLoading}
      />

      <MetaGrid>
        <MetaRow icon={<Target className="h-3.5 w-3.5" />} label="Target">
          <code className="text-[12px] text-indigo-300 break-all">{targetFqn || '—'}</code>
        </MetaRow>
        <MetaRow icon={<Activity className="h-3.5 w-3.5" />} label="Kind">
          <span className="text-[var(--text)]">{prettyMonitorKind(monitorKind)}</span>
        </MetaRow>
        <MetaRow icon={<Clock className="h-3.5 w-3.5" />} label="Schedule">
          {isEditing ? (
            <select
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              className="text-[12px] bg-[var(--surface-inset)] border border-[var(--border)] rounded-md px-2 py-1 text-[var(--text)] focus:outline-none focus:border-[var(--text)]"
            >
              {SCHEDULE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : (
            <span className="text-[var(--text)]">
              {formatCron(schedule)}
              <span className="ml-1.5 text-[11px] text-[var(--muted)] font-mono">{`\`${schedule}\``}</span>
            </span>
          )}
        </MetaRow>
      </MetaGrid>

      <ConfigBlock
        isEditing={isEditing}
        configText={configText}
        configError={configError}
        configSummary={summariseConfig(initialConfig)}
        onChange={setConfigText}
      />
    </Shell>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// UPDATE
// ────────────────────────────────────────────────────────────────────────────

function UpdateMonitorPreview({
  args, onConfirm, onDeny, isLoading,
}: {
  args: Record<string, any>;
  onConfirm: (editedArgs?: Record<string, any>) => void;
  onDeny: () => void;
  isLoading: boolean;
}) {
  const monitorId = args.monitor_id || '';
  const initialConfig = (args.config || {}) as Record<string, any>;

  const [isEditing, setIsEditing] = useState(false);
  const [configText, setConfigText] = useState<string>(JSON.stringify(initialConfig, null, 2));
  const [configError, setConfigError] = useState<string | null>(null);

  const handleConfirm = () => {
    let config = initialConfig;
    if (isEditing) {
      try {
        config = configText.trim() ? JSON.parse(configText) : {};
        setConfigError(null);
      } catch (e: any) {
        setConfigError(`Invalid JSON: ${e.message || e}`);
        return;
      }
    }
    onConfirm({ ...args, config });
  };

  return (
    <Shell tone="propose" onDeny={onDeny} isLoading={isLoading}>
      <Header
        action="UPDATE"
        actionTint="text-blue-200 bg-blue-500/15"
        title="Update monitor config"
        onToggleEdit={() => setIsEditing(v => !v)}
        isEditing={isEditing}
        onConfirm={handleConfirm}
        confirmLabel={isLoading ? 'Updating…' : 'Approve & Update'}
        confirmDisabled={isLoading}
      />

      <MetaGrid>
        <MetaRow icon={<Target className="h-3.5 w-3.5" />} label="Monitor id">
          <code className="text-[12px] text-indigo-300 break-all">{monitorId}</code>
        </MetaRow>
      </MetaGrid>

      <ConfigBlock
        isEditing={isEditing}
        configText={configText}
        configError={configError}
        configSummary={summariseConfig(initialConfig)}
        onChange={setConfigText}
        label="New config"
      />
    </Shell>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// DELETE
// ────────────────────────────────────────────────────────────────────────────

function DeleteMonitorPreview({
  args, onConfirm, onDeny, isLoading,
}: {
  args: Record<string, any>;
  onConfirm: (editedArgs?: Record<string, any>) => void;
  onDeny: () => void;
  isLoading: boolean;
}) {
  const monitorId = args.monitor_id || '';

  return (
    <Shell tone="destructive" onDeny={onDeny} isLoading={isLoading}>
      <Header
        action="DELETE"
        actionTint="text-rose-200 bg-rose-500/20"
        title="Delete monitor"
        onConfirm={() => onConfirm()}
        confirmLabel={isLoading ? 'Deleting…' : 'Approve & Delete'}
        confirmTone="destructive"
        confirmDisabled={isLoading}
      />

      <div className="flex items-start gap-2 text-[13px] text-rose-300 rounded-md bg-rose-500/10 border border-rose-500/30 px-3 py-2">
        <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
        <div>
          This will permanently delete monitor{' '}
          <code className="text-rose-200 font-mono text-[12px]">{monitorId}</code>. The
          monitor will stop running immediately and cannot be restored.
        </div>
      </div>
    </Shell>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Building blocks
// ────────────────────────────────────────────────────────────────────────────

function Shell({
  tone,
  onDeny,
  isLoading,
  children,
}: {
  tone: 'propose' | 'destructive';
  onDeny: () => void;
  isLoading: boolean;
  children: React.ReactNode;
}) {
  const borderTint = tone === 'destructive' ? 'border-rose-500/30' : 'border-amber-500/30';
  return (
    <div className={`rounded-xl border ${borderTint} bg-[var(--surface)] my-2 overflow-hidden`}>
      {children}
      <div className="px-4 pb-3 pt-1 flex items-center justify-between gap-3">
        <span className="text-[11px] uppercase tracking-wider text-[var(--muted)]">
          Action requires confirmation
        </span>
        <button
          type="button"
          onClick={onDeny}
          disabled={isLoading}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[12px] text-[var(--muted)] hover:text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
        >
          <X className="h-3 w-3" />
          Deny
        </button>
      </div>
    </div>
  );
}

function Header({
  action,
  actionTint,
  title,
  onToggleEdit,
  isEditing,
  onConfirm,
  confirmLabel,
  confirmTone,
  confirmDisabled,
}: {
  action: string;
  actionTint: string;
  title: React.ReactNode;
  onToggleEdit?: () => void;
  isEditing?: boolean;
  onConfirm: () => void;
  confirmLabel: string;
  confirmTone?: 'destructive';
  confirmDisabled?: boolean;
}) {
  const confirmClass =
    confirmTone === 'destructive'
      ? 'text-rose-100 bg-rose-500/20 hover:bg-rose-500/30'
      : 'text-emerald-100 bg-emerald-500/20 hover:bg-emerald-500/30';

  return (
    <div className="px-4 pt-4 pb-3 border-b border-[var(--border)]/60">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-2">
          <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold tracking-wider ${actionTint}`}>
            {action}
          </span>
          <h3 className="text-[15px] font-medium text-[var(--text)] leading-tight">{title}</h3>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {onToggleEdit ? (
            <button
              type="button"
              onClick={onToggleEdit}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[12px] text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--surface-inset)]"
            >
              <Pencil className="h-3 w-3" />
              {isEditing ? 'Done' : 'Edit'}
            </button>
          ) : null}
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirmDisabled}
            className={`inline-flex items-center gap-1 px-3 py-1 rounded-md text-[12px] font-medium ${confirmClass} disabled:opacity-50`}
          >
            {confirmTone === 'destructive' ? <Trash2 className="h-3 w-3" /> : <Check className="h-3 w-3" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function MetaGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 border-b border-[var(--border)]/60 text-[13px]">
      {children}
    </div>
  );
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

function ConfigBlock({
  isEditing,
  configText,
  configError,
  configSummary,
  onChange,
  label = 'Config',
}: {
  isEditing: boolean;
  configText: string;
  configError: string | null;
  configSummary: string;
  onChange: (v: string) => void;
  label?: string;
}) {
  return (
    <div className="px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-[var(--muted)] mb-1.5">
        {label}
      </div>
      {isEditing ? (
        <>
          <textarea
            value={configText}
            onChange={(e) => onChange(e.target.value)}
            rows={Math.min(8, Math.max(3, configText.split('\n').length))}
            className="w-full text-[12px] font-mono bg-[var(--surface-inset)] border border-[var(--border)] rounded-md px-2 py-1.5 text-[var(--text)] focus:outline-none focus:border-[var(--text)] resize-y"
            spellCheck={false}
          />
          {configError ? (
            <div className="mt-1 text-[11px] text-rose-300">{configError}</div>
          ) : null}
        </>
      ) : (
        <div className="text-[12px] text-[var(--text)] font-mono bg-[var(--surface-inset)] rounded-md px-3 py-2">
          {configSummary}
        </div>
      )}
    </div>
  );
}

