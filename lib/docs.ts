import fs from 'fs/promises';
import path from 'path';
import { compileMDX } from 'next-mdx-remote/rsc';
import remarkGfm from 'remark-gfm';
import rehypeSlug from 'rehype-slug';
import rehypeAutolinkHeadings from 'rehype-autolink-headings';
import { mdxComponents } from '@/components/docs/MdxComponents';

const CONTENT_DIR = path.join(process.cwd(), 'content', 'docs');

export interface DocFrontmatter {
  title: string;
  description: string;
  section?: 'guides' | 'integrations' | 'reference';
  order?: number;
}

export interface TocEntry {
  id: string;
  text: string;
  level: number;
}

export async function getDocBySlug(slug: string[]) {
  const filePath = path.join(CONTENT_DIR, ...slug) + '.mdx';
  const source = await fs.readFile(filePath, 'utf-8');

  const { content, frontmatter } = await compileMDX<DocFrontmatter>({
    source,
    options: {
      parseFrontmatter: true,
      mdxOptions: {
        remarkPlugins: [remarkGfm],
        rehypePlugins: [
          rehypeSlug,
          [rehypeAutolinkHeadings, { behavior: 'wrap' }],
        ],
      },
    },
    components: mdxComponents,
  });

  const toc = extractTocFromSource(source);

  return { content, frontmatter, toc };
}

export function extractTocFromSource(source: string): TocEntry[] {
  const headingRegex = /^(#{2,3})\s+(.+)$/gm;
  const entries: TocEntry[] = [];
  let match;

  while ((match = headingRegex.exec(source)) !== null) {
    const level = match[1].length;
    const text = match[2].trim();
    const id = text
      .toLowerCase()
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-');
    entries.push({ id, text, level });
  }

  return entries;
}

export async function getAllDocSlugs(): Promise<string[][]> {
  const slugs: string[][] = [];

  async function walk(dir: string, segments: string[]) {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory()) {
        await walk(path.join(dir, entry.name), [...segments, entry.name]);
      } else if (entry.name.endsWith('.mdx') && entry.name !== 'index.mdx') {
        const name = entry.name.replace(/\.mdx$/, '');
        slugs.push([...segments, name]);
      }
    }
  }

  await walk(CONTENT_DIR, []);
  return slugs;
}
