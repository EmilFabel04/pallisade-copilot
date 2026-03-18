// components/copilot/artifacts/MonitorArtifactCard.tsx
'use client';

import { UIArtifact } from '@/types/artifacts';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Pencil, Check, X, Loader2 } from 'lucide-react';

interface MonitorArtifactCardProps {
  artifact: UIArtifact;
  onConfirm: (artifactId: string, editedData?: Record<string, any>) => void;
  onCancel: (artifactId: string) => void;
  onEdit: (artifact: UIArtifact) => void;
}

const CATEGORY_LABELS: Record<string, { label: string; color: string }> = {
  pipeline_health: { label: 'Data Pipeline', color: 'bg-blue-500/20 text-blue-400' },
  dashboard_shield: { label: 'Dashboard', color: 'bg-purple-500/20 text-purple-400' },
  model_quality: { label: 'Transformation', color: 'bg-amber-500/20 text-amber-400' },
  data_drift: { label: 'Data Drift', color: 'bg-red-500/20 text-red-400' },
  custom_watch: { label: 'Custom', color: 'bg-gray-500/20 text-gray-400' },
};

const ACTION_LABELS: Record<string, { text: string; color: string }> = {
  create: { text: 'CREATE', color: 'bg-emerald-500/20 text-emerald-400' },
  update: { text: 'UPDATE', color: 'bg-blue-500/20 text-blue-400' },
  delete: { text: 'DELETE', color: 'bg-red-500/20 text-red-400' },
};

function formatCron(cron: string): string {
  const parts = cron.split(' ');
  if (parts.length !== 5) return cron;
  const [min, hour, dom, mon, dow] = parts;
  // Every minute
  if (min === '*' && hour === '*') return 'Every minute';
  // Every N minutes
  if (min.startsWith('*/') && hour === '*') return `Every ${min.slice(2)} min`;
  // Hourly
  if (min === '0' && hour === '*') return 'Hourly';
  // Every N hours
  if (min === '0' && hour.startsWith('*/')) return `Every ${hour.slice(2)}h`;
  // Daily at midnight
  if (min === '0' && hour === '0' && dom === '*') return 'Daily at midnight';
  // Daily at specific hour
  if (min === '0' && /^\d+$/.test(hour) && dom === '*') return `Daily at ${hour}:00`;
  // Weekly
  if (dom === '*' && dow !== '*') return `Weekly on ${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][parseInt(dow)] || dow}`;
  return cron;
}

export default function MonitorArtifactCard({ artifact, onConfirm, onCancel, onEdit }: MonitorArtifactCardProps) {
  const { data, action, status } = artifact;
  const actionLabel = ACTION_LABELS[action] || ACTION_LABELS.create;
  const category = CATEGORY_LABELS[data.watchType] || CATEGORY_LABELS.custom_watch;
  const isProposed = status === 'proposed';
  const isExecuting = status === 'executing';
  const isCompleted = status === 'completed';
  const isFailed = status === 'failed';
  const isCancelled = status === 'cancelled';

  return (
    <div className="border border-border rounded-lg p-4 my-2 bg-card">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Badge className={actionLabel.color}>
            {actionLabel.text}
          </Badge>
          <span className="font-semibold text-sm">{data.name || 'Monitor'}</span>
          {data.watchType && (
            <Badge className={category.color}>
              {category.label}
            </Badge>
          )}
        </div>
        {isProposed && (
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" disabled title="Editing coming soon">
              <Pencil className="h-3.5 w-3.5 mr-1" /> Edit
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onCancel(artifact.artifact_id)}>
              <X className="h-3.5 w-3.5 mr-1" /> Cancel
            </Button>
            <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => onConfirm(artifact.artifact_id)}>
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
        <div>
          <code className="text-indigo-400">{data.anchorFqn}</code>
          {data.schedule && <span className="ml-3">{formatCron(data.schedule)}</span>}
          {data.timezone && data.timezone !== 'UTC' && <span className="ml-2">({data.timezone})</span>}
        </div>
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
