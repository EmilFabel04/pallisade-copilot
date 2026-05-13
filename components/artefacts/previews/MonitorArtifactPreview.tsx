import type { ArtefactRow } from '@/types/artefact-row';
import type { ArtifactPayload } from '@/types/artifact';

type MonitorPayload = Extract<ArtifactPayload, { kind: 'MONITOR' }>;

export function MonitorArtifactPreview({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as MonitorPayload;
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
        <span className="text-[var(--text)] font-medium">{payload.monitorKind}</span>
        {payload.targetFqn ? <span>on {payload.targetFqn}</span> : null}
      </div>
      {artefact.summary ? (
        <p className="text-[13px] text-[var(--muted)] line-clamp-2">{artefact.summary}</p>
      ) : null}
    </div>
  );
}
