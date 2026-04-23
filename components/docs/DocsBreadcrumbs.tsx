import React from 'react';
import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { findSectionForSlug } from './navigation';

interface Props {
  slug: string[];
  title: string;
}

export function DocsBreadcrumbs({ slug, title }: Props) {
  const slugStr = slug.join('/');
  const section = findSectionForSlug(slugStr);

  return (
    <nav className="mb-4 flex items-center gap-1.5 text-[12px] text-[var(--muted)]">
      <Link href="/docs" className="hover:text-[var(--text-tertiary)]">
        Docs
      </Link>
      {section && (
        <>
          <ChevronRight className="h-3 w-3" />
          <span>{section.title}</span>
        </>
      )}
      <ChevronRight className="h-3 w-3" />
      <span className="text-[var(--text-tertiary)]">{title}</span>
    </nav>
  );
}
