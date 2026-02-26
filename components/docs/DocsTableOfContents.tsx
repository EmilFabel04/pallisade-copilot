'use client';

import React, { useEffect, useState } from 'react';
import type { TocEntry } from '@/lib/docs';

interface Props {
  entries: TocEntry[];
}

export function DocsTableOfContents({ entries }: Props) {
  const [activeId, setActiveId] = useState<string>('');

  useEffect(() => {
    if (!entries.length) return;

    const observer = new IntersectionObserver(
      (intersections) => {
        for (const entry of intersections) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0.1 }
    );

    for (const tocEntry of entries) {
      const el = document.getElementById(tocEntry.id);
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
  }, [entries]);

  if (!entries.length) return null;

  return (
    <nav className="py-4">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)]">
        On this page
      </p>
      <ul className="space-y-1">
        {entries.map((entry) => (
          <li key={entry.id}>
            <a
              href={`#${entry.id}`}
              className={`block text-[12px] leading-relaxed transition-colors ${
                entry.level === 3 ? 'pl-3' : ''
              } ${
                activeId === entry.id
                  ? 'font-medium text-[var(--accent-2)]'
                  : 'text-[var(--text-faint)] hover:text-[var(--text-tertiary)]'
              }`}
            >
              {entry.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
