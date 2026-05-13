// scripts/nuke_legacy_artifacts.ts
/**
 * One-shot wipe of all existing Artifact rows.
 *
 * The new schema (see prisma/schema.prisma) replaces the legacy chat-snippet
 * model with a polymorphic typed-artefact model. Existing rows have no
 * `kind`/`payload` and are incompatible. Per spec
 * (docs/superpowers/specs/2026-05-13-agentic-artefacts-design.md §10),
 * dev-only data — nuke approved.
 *
 * Run BEFORE `prisma db push`.
 */
import prisma from '../lib/db';

async function main() {
  const { count } = await prisma.artifact.deleteMany({});
  console.log(`[nuke] Deleted ${count} legacy Artifact rows`);
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error('[nuke] Failed:', err);
    process.exit(1);
  });
