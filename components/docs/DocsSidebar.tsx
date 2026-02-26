'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { docsNavigation, type NavSection } from './navigation';

function SidebarSection({ section }: { section: NavSection }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(true);

  const isActive = (slug: string) => pathname === `/docs/${slug}`;

  return (
    <div className="mb-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)] hover:text-[var(--text-tertiary)]"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        {section.title}
      </button>
      {open && (
        <ul className="mt-0.5 space-y-0.5">
          {section.items.map((item) => (
            <li key={item.slug}>
              <Link
                href={`/docs/${item.slug}`}
                className={`block rounded-md px-3 py-1.5 text-[13px] transition-colors ${
                  isActive(item.slug)
                    ? 'bg-[var(--overlay-bg)] font-medium text-[var(--text)]'
                    : 'text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)]'
                }`}
              >
                {item.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function DocsSidebar() {
  return (
    <nav className="h-full overflow-y-auto py-4 pr-2">
      <Link
        href="/docs"
        className="mb-6 block px-3 text-sm font-semibold text-[var(--text)] hover:text-[var(--accent-2)]"
      >
        Documentation
      </Link>
      {docsNavigation.map((section) => (
        <SidebarSection key={section.title} section={section} />
      ))}
    </nav>
  );
}
