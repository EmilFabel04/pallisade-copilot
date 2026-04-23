import { DocsLayout } from '@/components/docs/DocsLayout';

export const metadata = {
  title: 'Documentation - Pallisade',
  description:
    'Guides, API reference, and integration docs for the Pallisade data reliability platform.',
};

export default function DocsRootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <DocsLayout>{children}</DocsLayout>;
}
