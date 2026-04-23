import React from 'react';
import Link from 'next/link';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { getFlatNavItems } from './navigation';

interface Props {
  currentSlug: string;
}

export function DocsPageNav({ currentSlug }: Props) {
  const items = getFlatNavItems();
  const idx = items.findIndex((item) => item.slug === currentSlug);
  if (idx === -1) return null;

  const prev = idx > 0 ? items[idx - 1] : null;
  const next = idx < items.length - 1 ? items[idx + 1] : null;

  return (
    <div className="mt-12 flex items-center justify-between border-t border-[var(--border)] pt-6">
      {prev ? (
        <Link
          href={`/docs/${prev.slug}`}
          className="flex items-center gap-1.5 text-sm text-[var(--text-tertiary)] hover:text-[var(--text)]"
        >
          <ChevronLeft className="h-4 w-4" />
          {prev.title}
        </Link>
      ) : (
        <div />
      )}
      {next ? (
        <Link
          href={`/docs/${next.slug}`}
          className="flex items-center gap-1.5 text-sm text-[var(--text-tertiary)] hover:text-[var(--text)]"
        >
          {next.title}
          <ChevronRight className="h-4 w-4" />
        </Link>
      ) : (
        <div />
      )}
    </div>
  );
}
