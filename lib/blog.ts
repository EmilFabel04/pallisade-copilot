import fs from 'node:fs';
import path from 'node:path';

export type BlogPostMeta = {
  slug: string;
  title: string;
  excerpt: string;
  date?: string;
  author?: string;
  category?: string;
  description?: string;
  tags?: string[];
};

const BLOG_DIR = path.join(process.cwd(), 'content', 'blog');

function parseFrontmatter(content: string): { frontmatter: Record<string, any>; body: string } {
  const frontmatterRegex = /^---\n([\s\S]*?)\n---\n([\s\S]*)$/;
  const match = content.match(frontmatterRegex);
  
  if (!match) {
    return { frontmatter: {}, body: content };
  }

  const frontmatterStr = match[1];
  const body = match[2];
  const frontmatter: Record<string, any> = {};

  frontmatterStr.split('\n').forEach(line => {
    const colonIndex = line.indexOf(':');
    if (colonIndex > 0) {
      const key = line.slice(0, colonIndex).trim();
      let value = line.slice(colonIndex + 1).trim();
      
      // Remove quotes
      if ((value.startsWith('"') && value.endsWith('"')) || 
          (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      
      // Parse arrays
      if (value.startsWith('[') && value.endsWith(']')) {
        try {
          frontmatter[key] = JSON.parse(value);
        } catch {
          frontmatter[key] = value;
        }
      } else {
        frontmatter[key] = value;
      }
    }
  });

  return { frontmatter, body };
}

export function getAllPosts(): BlogPostMeta[] {
  if (!fs.existsSync(BLOG_DIR)) return [];
  const files = fs.readdirSync(BLOG_DIR).filter(f => f.endsWith('.md'));
  
  const posts = files.map((file) => {
    const slug = file.replace(/\.md$/, '');
    const full = fs.readFileSync(path.join(BLOG_DIR, file), 'utf8');
    const { frontmatter, body } = parseFrontmatter(full);
    
    // Get title from frontmatter or first heading
    const lines = body.split('\n');
    const titleLine = lines.find(l => l.startsWith('# '));
    const title = frontmatter.title || (titleLine ? titleLine.replace(/^#\s+/, '').trim() : slug);
    
    // Get excerpt from frontmatter description or first paragraph
    const excerpt = frontmatter.description || 
      (lines.find(l => l.trim() && !l.startsWith('#') && !l.startsWith('---')) ?? '').trim().slice(0, 200);
    
    return { 
      slug, 
      title, 
      excerpt,
      date: frontmatter.date,
      author: frontmatter.author,
      category: frontmatter.category,
      description: frontmatter.description,
      tags: frontmatter.tags
    };
  });

  // Sort by date (newest first)
  return posts.sort((a, b) => {
    if (!a.date && !b.date) return 0;
    if (!a.date) return 1;
    if (!b.date) return -1;
    return new Date(b.date).getTime() - new Date(a.date).getTime();
  });
}

export function getPostBySlug(slug: string): { meta: BlogPostMeta; content: string } | null {
  const file = path.join(BLOG_DIR, `${slug}.md`);
  if (!fs.existsSync(file)) return null;
  
  const full = fs.readFileSync(file, 'utf8');
  const { frontmatter, body } = parseFrontmatter(full);
  
  const lines = body.split('\n');
  const titleLine = lines.find(l => l.startsWith('# '));
  const title = frontmatter.title || (titleLine ? titleLine.replace(/^#\s+/, '').trim() : slug);
  
  const excerpt = frontmatter.description || 
    (lines.find(l => l.trim() && !l.startsWith('#') && !l.startsWith('---')) ?? '').trim().slice(0, 200);
  
  return { 
    meta: { 
      slug, 
      title, 
      excerpt,
      date: frontmatter.date,
      author: frontmatter.author,
      category: frontmatter.category,
      description: frontmatter.description,
      tags: frontmatter.tags
    }, 
    content: body 
  };
}

export function getPostsByCategory(category: string): BlogPostMeta[] {
  return getAllPosts().filter(post => post.category === category);
}

export function getAllCategories(): string[] {
  const posts = getAllPosts();
  const categories = new Set(posts.map(p => p.category).filter(Boolean) as string[]);
  return Array.from(categories).sort();
}

export function getAllTags(): string[] {
  const posts = getAllPosts();
  const tags = new Set(posts.flatMap(p => p.tags || []));
  return Array.from(tags).sort();
}
