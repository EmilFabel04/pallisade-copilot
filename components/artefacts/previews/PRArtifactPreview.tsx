import type { ArtefactRow } from '@/types/artefact-row';

export function PRArtifactPreview({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as Extract<ArtefactRow['payload'], { kind: 'PR_CHANGE' }>;
  const ref = (artefact.externalRef ?? {}) as { pr_url?: string; pr_number?: number; branch?: string };

  return (
    <div className="space-y-1">
      {artefact.summary ? (
        <p className="text-[13px] text-[var(--text)] line-clamp-2">{artefact.summary}</p>
      ) : null}
      <div className="flex items-center gap-3 text-[12px] text-[var(--muted)]">
        {ref.pr_number ? <span>#{ref.pr_number}</span> : null}
        {ref.branch ? <span>{ref.branch}</span> : null}
        <span>{payload.filesChanged} file{payload.filesChanged === 1 ? '' : 's'}</span>
        {ref.pr_url ? (
          <a
            href={ref.pr_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-emerald-400 hover:underline"
          >
            View PR
          </a>
        ) : null}
      </div>
    </div>
  );
}
