'use client';

import { UIArtifact } from '@/types/artifacts';
import MonitorArtifactCard from './artifacts/MonitorArtifactCard';

interface ArtifactRendererProps {
  artifacts: UIArtifact[];
  onConfirm: (artifactId: string, editedData?: Record<string, any>) => void;
  onCancel: (artifactId: string) => void;
  onEdit: (artifact: UIArtifact) => void;
}

export default function ArtifactRenderer({ artifacts, onConfirm, onCancel, onEdit }: ArtifactRendererProps) {
  if (!artifacts || artifacts.length === 0) return null;

  return (
    <div className="space-y-2">
      {artifacts.map((artifact) => {
        switch (artifact.type) {
          case 'watch_preview':
          case 'monitor_card':
            return (
              <MonitorArtifactCard
                key={artifact.artifact_id}
                artifact={artifact}
                onConfirm={onConfirm}
                onCancel={onCancel}
                onEdit={onEdit}
              />
            );
          default:
            return (
              <div key={artifact.artifact_id} className="border border-border rounded-lg p-3 my-2 bg-card text-sm text-muted-foreground">
                Unknown artifact type: {artifact.type}
              </div>
            );
        }
      })}
    </div>
  );
}
