import type { ArtifactStatus } from '@prisma/client';

const TINT: Record<ArtifactStatus, { fg: string; bg: string }> = {
  draft:    { fg: '#9ca3af', bg: 'rgba(156, 163, 175, 0.15)' },
  proposed: { fg: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' },
  approved: { fg: '#60a5fa', bg: 'rgba(96, 165, 250, 0.15)' },
  applied:  { fg: '#34d399', bg: 'rgba(52, 211, 153, 0.15)' },
  rejected: { fg: '#f87171', bg: 'rgba(248, 113, 113, 0.15)' },
  failed:   { fg: '#f87171', bg: 'rgba(248, 113, 113, 0.18)' },
  archived: { fg: '#6b7280', bg: 'rgba(107, 114, 128, 0.15)' },
  open:     { fg: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' },
  resolved: { fg: '#34d399', bg: 'rgba(52, 211, 153, 0.15)' },
};

export function ArtefactStatusBadge({ status }: { status: ArtifactStatus }) {
  const { fg, bg } = TINT[status];
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium uppercase tracking-wide"
      style={{ color: fg, backgroundColor: bg }}
    >
      {status}
    </span>
  );
}
