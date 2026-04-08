'use client';

import { HealthSummary } from './types';

function formatRelativeTime(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  const days = Math.ceil(diff / (1000 * 60 * 60 * 24));
  if (days <= 0) return 'Expired';
  if (days === 1) return '1 day';
  if (days < 30) return `${days} days`;
  const months = Math.floor(days / 30);
  return months === 1 ? '1 month' : `${months} months`;
}

interface Props {
  summary: HealthSummary;
}

export default function SourceSummaryBar({ summary }: Props) {
  const cards = [
    {
      label: 'Total Sources',
      value: summary.total,
      sub: 'connected',
      dot: 'bg-[var(--text-tertiary)]',
    },
    {
      label: 'Healthy',
      value: summary.healthy,
      sub: null,
      dot: 'bg-emerald-500',
    },
    {
      label: 'Next Expiry',
      value: summary.nextExpiry ? formatRelativeTime(summary.nextExpiry) : 'None',
      sub: summary.defaultWarehouse ? `Default: ${summary.defaultWarehouse}` : null,
      dot: summary.nextExpiry
        ? (() => {
            const days = Math.ceil((new Date(summary.nextExpiry!).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
            if (days <= 0) return 'bg-red-500';
            if (days <= 7) return 'bg-yellow-500';
            return 'bg-zinc-500';
          })()
        : 'bg-zinc-500',
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map((card) => (
        <div
          key={card.label}
          className="rounded-lg border border-[var(--subtle-border)] bg-[var(--surface-raised)] p-4"
        >
          <div className="flex items-center gap-2 mb-1">
            <div className={`w-2 h-2 rounded-full ${card.dot}`} />
            <span className="text-xs text-[var(--text-tertiary)] uppercase tracking-wide">
              {card.label}
            </span>
          </div>
          <div className="text-xl font-semibold text-[var(--text)]">
            {card.value}
          </div>
          {card.sub && (
            <div className="text-xs text-[var(--text-faint)] mt-0.5">{card.sub}</div>
          )}
        </div>
      ))}
    </div>
  );
}
