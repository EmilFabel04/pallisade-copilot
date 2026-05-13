import type { ArtifactRisk } from '@prisma/client';

const TINT: Record<ArtifactRisk, { fg: string; bg: string }> = {
  LOW:    { fg: '#34d399', bg: 'rgba(52, 211, 153, 0.12)' },
  MEDIUM: { fg: '#fbbf24', bg: 'rgba(251, 191, 36, 0.12)' },
  HIGH:   { fg: '#f87171', bg: 'rgba(248, 113, 113, 0.12)' },
};

export function ArtefactRiskBadge({ risk }: { risk: ArtifactRisk }) {
  const { fg, bg } = TINT[risk];
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider"
      style={{ color: fg, backgroundColor: bg }}
    >
      {risk}
    </span>
  );
}
