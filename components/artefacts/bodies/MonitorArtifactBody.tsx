import type { ArtefactRow } from '@/types/artefact-row';
import type { ArtifactPayload } from '@/types/artifact';

type MonitorPayload = Extract<ArtifactPayload, { kind: 'MONITOR' }>;

function formatJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export function MonitorArtifactBody({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as MonitorPayload;
  const diff = payload.configDiff as { before?: unknown; after?: unknown; operation?: string } | undefined;
  const operation = diff?.operation;

  return (
    <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-[13px]">
        <div>
          <div className="text-[var(--muted)]">Kind</div>
          <div className="text-[var(--text)] font-medium">{payload.monitorKind}</div>
        </div>
        {payload.targetFqn ? (
          <div>
            <div className="text-[var(--muted)]">Target</div>
            <div className="text-[var(--text)] font-medium truncate" title={payload.targetFqn}>
              {payload.targetFqn}
            </div>
          </div>
        ) : null}
        <div>
          <div className="text-[var(--muted)]">Monitor id</div>
          <div className="text-[var(--text)] font-mono text-[12px]">{payload.monitorId}</div>
        </div>
      </div>

      {operation === 'delete' ? (
        <div className="text-[13px] text-rose-300 rounded-md bg-rose-500/10 px-3 py-2">
          This monitor was deleted.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <div className="text-[12px] text-[var(--muted)] mb-1">Before</div>
            <pre className="text-[12px] text-[var(--text)] whitespace-pre-wrap bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[260px]">
{diff?.before !== undefined ? formatJson(diff.before) : '—'}
            </pre>
          </div>
          <div>
            <div className="text-[12px] text-[var(--muted)] mb-1">After</div>
            <pre className="text-[12px] text-[var(--text)] whitespace-pre-wrap bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[260px]">
{diff?.after !== undefined ? formatJson(diff.after) : '—'}
            </pre>
          </div>
        </div>
      )}
    </section>
  );
}
