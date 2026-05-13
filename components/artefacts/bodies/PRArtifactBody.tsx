import type { ArtefactRow } from '@/types/artefact-row';
import type { ArtifactPayload } from '@/types/artifact';

type PRPayload = Extract<ArtifactPayload, { kind: 'PR_CHANGE' }>;
type GroupAPayload = Extract<
  ArtifactPayload,
  { kind: 'PR_CHANGE' | 'DBT_CORE_CHANGE' | 'DAG' | 'SCHEMA_CHANGE' }
>;

function isPrCompatible(payload: GroupAPayload): payload is PRPayload {
  return payload.kind === 'PR_CHANGE';
}

export function PRArtifactBody({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as GroupAPayload;
  const ref = (artefact.externalRef ?? {}) as { pr_url?: string; pr_number?: number; branch?: string };

  return (
    <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5 space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[13px]">
        {ref.pr_number ? (
          <div>
            <div className="text-[var(--muted)]">PR</div>
            <div className="text-[var(--text)] font-medium">#{ref.pr_number}</div>
          </div>
        ) : null}
        {ref.branch ? (
          <div>
            <div className="text-[var(--muted)]">Branch</div>
            <div className="text-[var(--text)] font-medium truncate">{ref.branch}</div>
          </div>
        ) : null}
        {isPrCompatible(payload) ? (
          <div>
            <div className="text-[var(--muted)]">Files</div>
            <div className="text-[var(--text)] font-medium">{payload.filesChanged}</div>
          </div>
        ) : null}
        {payload.kind === 'DBT_CORE_CHANGE' ? (
          <div>
            <div className="text-[var(--muted)]">Models</div>
            <div className="text-[var(--text)] font-medium">{payload.modelsTouched.length}</div>
          </div>
        ) : null}
        {payload.kind === 'DAG' ? (
          <div>
            <div className="text-[var(--muted)]">Tasks</div>
            <div className="text-[var(--text)] font-medium">{payload.affectedTasks.length}</div>
          </div>
        ) : null}
        {payload.kind === 'SCHEMA_CHANGE' ? (
          <div>
            <div className="text-[var(--muted)]">Tables</div>
            <div className="text-[var(--text)] font-medium">{payload.affectedTables.length}</div>
          </div>
        ) : null}
      </div>

      {isPrCompatible(payload) && payload.diffSummary ? (
        <div>
          <div className="text-[12px] text-[var(--muted)] mb-1">Diff summary</div>
          <pre className="text-[12px] text-[var(--text)] whitespace-pre-wrap bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[400px]">
{payload.diffSummary}
          </pre>
        </div>
      ) : null}

      {isPrCompatible(payload) && payload.validationResults
        ? (
          <div>
            <div className="text-[12px] text-[var(--muted)] mb-1">Validation</div>
            <div className="flex items-center gap-2 flex-wrap">
              {(['static', 'ci', 'sandbox'] as const).map((level) => {
                const status = payload.validationResults[level];
                if (!status) return null;
                const tint =
                  status === 'passed' ? 'text-emerald-400'
                  : status === 'failed' ? 'text-rose-400'
                  : status === 'running' ? 'text-amber-400'
                  : 'text-[var(--muted)]';
                return (
                  <span key={level} className={`text-[12px] ${tint}`}>
                    {level}: {status}
                  </span>
                );
              })}
            </div>
          </div>
        )
        : null}

      {ref.pr_url ? (
        <a
          href={ref.pr_url}
          target="_blank"
          rel="noreferrer"
          className="inline-block px-3 py-1.5 rounded-md bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 text-[13px]"
        >
          View PR on GitHub ↗
        </a>
      ) : null}
    </section>
  );
}
