import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getDocBySlug, getAllDocSlugs } from '@/lib/docs';
import { DocsBreadcrumbs } from '@/components/docs/DocsBreadcrumbs';
import { DocsTableOfContents } from '@/components/docs/DocsTableOfContents';
import { DocsPageNav } from '@/components/docs/DocsPageNav';
import { docsNavigation } from '@/components/docs/navigation';

interface Props {
  params: Promise<{ slug?: string[] }>;
}

export async function generateStaticParams() {
  const slugs = await getAllDocSlugs();
  return [{ slug: undefined }, ...slugs.map((s) => ({ slug: s }))];
}

export async function generateMetadata({ params }: Props) {
  const { slug } = await params;
  if (!slug) {
    return {
      title: 'Documentation - Pallisade',
      description:
        'Guides, API reference, and integration docs for the Pallisade data reliability platform.',
    };
  }

  try {
    const { frontmatter } = await getDocBySlug(slug);
    return {
      title: `${frontmatter.title} - Pallisade Docs`,
      description: frontmatter.description,
    };
  } catch {
    return {};
  }
}

const sectionDescriptions: Record<string, string> = {
  'User Guides':
    'Learn how to set up your pipeline, use Scout AI, visualize lineage, and monitor data quality.',
  Integrations:
    'Step-by-step guides for connecting your warehouses, transformation tools, orchestrators, and BI platforms.',
  'Technical Reference':
    'Architecture deep-dives, API reference, lineage engine internals, and self-hosting instructions.',
};

function DocsLanding() {
  return (
    <div>
      <h1 className="text-3xl font-bold text-[var(--text)] mb-2">
        Pallisade Documentation
      </h1>
      <p className="text-[var(--text-tertiary)] mb-10 text-base">
        Everything you need to set up, integrate, and get the most out of
        Pallisade — the AI-powered data reliability platform.
      </p>

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {docsNavigation.map((section) => (
          <div
            key={section.title}
            className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5"
          >
            <h2 className="text-lg font-semibold text-[var(--text)] mb-1.5">
              {section.title}
            </h2>
            <p className="text-sm text-[var(--muted)] mb-4">
              {sectionDescriptions[section.title]}
            </p>
            <ul className="space-y-1">
              {section.items.slice(0, 5).map((item) => (
                <li key={item.slug}>
                  <Link
                    href={`/docs/${item.slug}`}
                    className="text-sm text-[var(--text-tertiary)] hover:text-[var(--accent-2)]"
                  >
                    {item.title}
                  </Link>
                </li>
              ))}
              {section.items.length > 5 && (
                <li className="text-xs text-[var(--text-faint)]">
                  + {section.items.length - 5} more
                </li>
              )}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

export default async function DocsPage({ params }: Props) {
  const { slug } = await params;

  // No slug → landing page
  if (!slug) {
    return <DocsLanding />;
  }

  try {
    const { content, frontmatter, toc } = await getDocBySlug(slug);

    return (
      <div className="relative">
        <DocsBreadcrumbs slug={slug} title={frontmatter.title} />
        <h1 className="text-3xl font-bold text-[var(--text)] mb-2">
          {frontmatter.title}
        </h1>
        {frontmatter.description && (
          <p className="text-[var(--text-tertiary)] mb-8 text-base">
            {frontmatter.description}
          </p>
        )}

        <div className="flex gap-10">
          <div className="min-w-0 flex-1 docs-prose">{content}</div>

          <aside className="hidden xl:block w-[200px] shrink-0">
            <div className="sticky top-24">
              <DocsTableOfContents entries={toc} />
            </div>
          </aside>
        </div>

        <DocsPageNav currentSlug={slug.join('/')} />
      </div>
    );
  } catch {
    notFound();
  }
}
