import type { ArtefactRow } from '@/types/artefact-row';

export function GenericArtifactBody({ artefact }: { artefact: ArtefactRow }) {
  const payload = artefact.payload as Record<string, unknown>;
  return (
    <section className="rounded-xl bg-[var(--surface)] border border-[var(--border)] p-5">
      <h2 className="text-[14px] font-semibold text-[var(--text)] mb-3">Payload</h2>
      <pre className="text-[12px] text-[var(--muted)] whitespace-pre-wrap break-words bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[400px]">
{JSON.stringify(payload, null, 2)}
      </pre>
      {artefact.externalRef ? (
        <>
          <h3 className="text-[13px] font-semibold text-[var(--text)] mt-4 mb-2">External reference</h3>
          <pre className="text-[12px] text-[var(--muted)] whitespace-pre-wrap break-words bg-[var(--surface-inset)] rounded-md p-3 overflow-auto max-h-[200px]">
{JSON.stringify(artefact.externalRef, null, 2)}
          </pre>
        </>
      ) : null}
    </section>
  );
}
