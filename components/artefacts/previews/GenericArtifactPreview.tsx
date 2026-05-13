import type { ArtefactRow } from '@/types/artefact-row';

export function GenericArtifactPreview({ artefact }: { artefact: ArtefactRow }) {
  if (!artefact.summary) return null;
  return (
    <p className="text-[13px] text-[var(--muted)] line-clamp-2">{artefact.summary}</p>
  );
}
