'use client';

import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { isFeatureEnabled } from '@/lib/feature-flags';
import { useArtefact } from '@/hooks/useArtefact';
import { ArtefactHeader } from '@/components/artefacts/ArtefactHeader';
import { ArtefactBody } from '@/components/artefacts/bodies';
import { EmbeddedAgentSession } from '@/components/artefacts/EmbeddedAgentSession';

export default function ArtefactDetailPage() {
  const params = useParams<{ artifactId: string }>();
  const router = useRouter();
  const flagOn = isFeatureEnabled('ff_artefacts_v2');
  const { artefact, isLoading, error, refresh } = useArtefact(params.artifactId ?? null);

  if (!flagOn) {
    return (
      <div className="min-h-screen bg-[var(--surface-inset)] flex items-center justify-center">
        <p className="text-[14px] text-[var(--muted)]">Artifacts v2 is not enabled.</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--surface-inset)]">
      <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        <div>
          <button
            onClick={() => router.push('/dashboard/artifacts')}
            className="text-[13px] text-[var(--muted)] hover:text-[var(--text)]"
          >
            ← Back to artefacts
          </button>
        </div>

        {isLoading ? (
          <div className="text-[14px] text-[var(--muted)]">Loading artefact…</div>
        ) : error ? (
          <div className="p-4 rounded-lg border border-rose-500/30 bg-rose-500/10 text-[13px] text-rose-300">
            {error}
          </div>
        ) : !artefact ? (
          <div className="p-8 rounded-xl border border-dashed border-[var(--border)] text-center">
            <p className="text-[14px] text-[var(--muted)]">Artefact not found.</p>
            <Link href="/dashboard/artifacts" className="text-[13px] text-emerald-400 hover:underline">
              Back to list
            </Link>
          </div>
        ) : (
          <>
            <ArtefactHeader artefact={artefact} onChanged={refresh} />
            <ArtefactBody artefact={artefact} />
            {artefact.agentSessionId ? (
              <EmbeddedAgentSession agentSessionId={artefact.agentSessionId} />
            ) : (
              <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5">
                <h2 className="text-[14px] font-semibold text-[var(--text)] mb-1">Agent session</h2>
                <p className="text-[13px] text-[var(--muted)]">
                  This artefact does not have an agent session. It was either user-saved or created before
                  agent forking was wired up.
                </p>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
