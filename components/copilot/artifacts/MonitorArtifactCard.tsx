// components/copilot/artifacts/MonitorArtifactCard.tsx
'use client';

import { useState } from 'react';
import { UIArtifact } from '@/types/artifacts';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Check, X, Loader2, Pencil } from 'lucide-react';
import { ColumnPicker } from '@/components/schedule/ColumnPicker';

interface MonitorArtifactCardProps {
  artifact: UIArtifact;
  onConfirm: (artifactId: string, editedData?: Record<string, any>) => void;
  onCancel: (artifactId: string) => void;
}

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  pipeline_health: { label: 'Data Pipeline', color: 'bg-blue-500/20 text-blue-400' },
  dashboard_shield: { label: 'Dashboard', color: 'bg-slate-500/20 text-slate-400' },
  model_quality: { label: 'Transformation', color: 'bg-amber-500/20 text-amber-400' },
  data_drift: { label: 'Data Drift', color: 'bg-red-500/20 text-red-400' },
  custom_watch: { label: 'Custom', color: 'bg-gray-500/20 text-gray-400' },
};

const ACTION_LABELS: Record<string, { text: string; color: string }> = {
  create: { text: 'CREATE', color: 'bg-emerald-500/20 text-emerald-400' },
  update: { text: 'UPDATE', color: 'bg-blue-500/20 text-blue-400' },
  delete: { text: 'DELETE', color: 'bg-red-500/20 text-red-400' },
};

const SCHEDULE_OPTIONS = [
  { value: '*/5 * * * *', label: 'Every 5 min' },
  { value: '*/15 * * * *', label: 'Every 15 min' },
  { value: '*/30 * * * *', label: 'Every 30 min' },
  { value: '0 * * * *', label: 'Hourly' },
  { value: '0 */2 * * *', label: 'Every 2h' },
  { value: '0 */6 * * *', label: 'Every 6h' },
  { value: '0 */12 * * *', label: 'Every 12h' },
  { value: '0 0 * * *', label: 'Daily at midnight' },
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

export default function MonitorArtifactCard({ artifact, onConfirm, onCancel }: MonitorArtifactCardProps) {
  const { data, action, status } = artifact;
  const actionLabel = ACTION_LABELS[action] || ACTION_LABELS.create;
  const category = CATEGORY_LABELS[data.watchType] || CATEGORY_LABELS.custom_watch;
  const isProposed = status === 'proposed';
  const isExecuting = status === 'executing';
  const isCompleted = status === 'completed';
  const isFailed = status === 'failed';
  const isCancelled = status === 'cancelled';

  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState(data.name || 'Monitor');
  const [editSchedule, setEditSchedule] = useState(data.schedule || '0 */6 * * *');
  const [editColumn, setEditColumn] = useState('');

  const hasAnomalyMonitor = (data.monitors || []).some(
    (m: any) => (m.monitor_type || m.monitorType || '').toUpperCase() === 'ANOMALY'
  );

  const handleConfirmWithEdits = () => {
    if (isEditing) {
      const editedData = { ...data, name: editName, schedule: editSchedule };
      // Inject column into anomaly monitor configs
      if (editColumn && hasAnomalyMonitor && editedData.monitors) {
        editedData.monitors = editedData.monitors.map((m: any) => {
          const mt = (m.monitor_type || m.monitorType || '').toUpperCase();
          if (mt === 'ANOMALY') {
            return { ...m, config: { ...(m.config || {}), column: editColumn } };
          }
          return m;
        });
      }
      onConfirm(artifact.artifact_id, editedData);
    } else {
      onConfirm(artifact.artifact_id);
    }
  };

  return (
    <div className="border border-border rounded-lg p-4 my-2 bg-card">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Badge className={actionLabel.color}>
            {actionLabel.text}
          </Badge>
          {isEditing ? (
            <input
              type="text"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              className="font-semibold text-sm bg-transparent border-b border-[var(--subtle-border)] focus:border-[var(--accent)] outline-none px-1 py-0.5 text-[var(--text)]"
              autoFocus
            />
          ) : (
            <span className="font-semibold text-sm">{data.name || 'Monitor'}</span>
          )}
          {data.watchType && (
            <Badge className={category.color}>
              {category.label}
            </Badge>
          )}
        </div>
        {isProposed && (
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => setIsEditing(!isEditing)}>
              <Pencil className="h-3.5 w-3.5 mr-1" /> {isEditing ? 'Done' : 'Edit'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onCancel(artifact.artifact_id)}>
              <X className="h-3.5 w-3.5 mr-1" /> Cancel
            </Button>
            <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={handleConfirmWithEdits}>
              <Check className="h-3.5 w-3.5 mr-1" /> Confirm
            </Button>
          </div>
        )}
        {isExecuting && (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" /> Creating...
          </div>
        )}
        {isCompleted && (
          <Badge className="bg-emerald-500/20 text-emerald-400">
            <Check className="h-3 w-3 mr-1" /> Created
          </Badge>
        )}
        {isFailed && (
          <Badge className="bg-red-500/20 text-red-400">
            <X className="h-3 w-3 mr-1" /> Failed
          </Badge>
        )}
        {isCancelled && (
          <Badge className="bg-gray-500/20 text-gray-400">
            <X className="h-3 w-3 mr-1" /> Cancelled
          </Badge>
        )}
      </div>

      <div className="text-muted-foreground text-xs space-y-1">
        <div className="flex items-center gap-3">
          <code className="text-indigo-400">{data.anchorFqn}</code>
          {isEditing ? (
            <select
              value={editSchedule}
              onChange={(e) => setEditSchedule(e.target.value)}
              className="text-xs bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded px-2 py-1 text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
            >
              {SCHEDULE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : (
            data.schedule && <span>{formatCron(data.schedule)}</span>
          )}
          {data.timezone && data.timezone !== 'UTC' && <span>({data.timezone})</span>}
        </div>
        {isEditing && hasAnomalyMonitor && data.anchorFqn && (
          <div className="mt-2">
            <label className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 block">Column to monitor for outliers</label>
            <ColumnPicker
              targetFqn={data.anchorFqn}
              value={editColumn}
              onChange={setEditColumn}
              numericOnly
              className="w-full bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded px-2 py-1.5 text-[12px] text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
        )}
        {data.monitors && data.monitors.length > 0 && (
          <div className="flex gap-2 flex-wrap mt-1">
            {data.monitors.map((m: any, i: number) => (
              <Badge key={i} className="text-xs">
                {(m.monitor_type || m.monitorType || '').replace(/_/g, ' ').toLowerCase()}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
