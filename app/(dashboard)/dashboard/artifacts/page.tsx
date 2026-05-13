'use client';

// The legacy artefact UI was removed when the artefact backend was rewritten
// for the new polymorphic schema. The new agentic artefacts surface is being
// built — until it lands this page renders a placeholder so the route stays
// reachable but doesn't drag along stale code.

export default function ArtifactsPage() {
  return (
    <div className="min-h-screen bg-[var(--surface-inset)]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-[var(--text)]">Artifacts</h1>
          <p className="mt-1 text-[14px] text-[var(--muted)]">
            The new artefacts surface is being built. Check back soon.
          </p>
        </div>
      </div>
    </div>
  );
}
