import type { ArtifactKind } from '@prisma/client';
import { KIND_META } from '@/lib/artefacts/kinds';

export function ArtefactKindBadge({ kind, subtype }: { kind: ArtifactKind; subtype?: string | null }) {
  const meta = KIND_META[kind];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ${meta.tint}`}
      style={{ backgroundColor: 'var(--hover-bg)' }}
    >
      {meta.label}
      {subtype ? <span className="text-[var(--muted)] font-normal">· {subtype}</span> : null}
    </span>
  );
}
