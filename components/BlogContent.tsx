'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { Badge } from './ui/badge';

type BlogPost = {
  slug: string;
  title: string;
  excerpt: string;
  date?: string;
  author?: string;
  category?: string;
  tags?: string[];
};

type BlogContentProps = {
  posts: BlogPost[];
  categories: string[];
  tags: string[];
};

export function BlogContent({ posts, categories, tags }: BlogContentProps) {
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState('');

  const filteredPosts = useMemo(() => {
    return posts.filter((post) => {
      // Category filter
      if (selectedCategory && post.category !== selectedCategory) {
        return false;
      }

      // Tags filter
      if (selectedTags.length > 0) {
        const postTags = post.tags || [];
        if (!selectedTags.some(tag => postTags.includes(tag))) {
          return false;
        }
      }

      // Search query filter
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        const matchesTitle = post.title.toLowerCase().includes(query);
        const matchesExcerpt = post.excerpt.toLowerCase().includes(query);
        const matchesCategory = post.category?.toLowerCase().includes(query);
        const matchesTags = post.tags?.some(tag => tag.toLowerCase().includes(query));
        
        if (!matchesTitle && !matchesExcerpt && !matchesCategory && !matchesTags) {
          return false;
        }
      }

      return true;
    });
  }, [posts, selectedCategory, selectedTags, searchQuery]);

  const toggleTag = (tag: string) => {
    setSelectedTags(prev => 
      prev.includes(tag) 
        ? prev.filter(t => t !== tag)
        : [...prev, tag]
    );
  };

  const clearFilters = () => {
    setSelectedCategory(null);
    setSelectedTags([]);
    setSearchQuery('');
  };

  const hasActiveFilters = selectedCategory || selectedTags.length > 0 || searchQuery;
  const featuredPost = filteredPosts[0];
  const otherPosts = filteredPosts.slice(1);

  return (
    <>
      {/* Search and Filters */}
      <div className="mb-10">
        {/* Search Input */}
        <div className="max-w-xl mx-auto mb-8">
          <div className="relative">
            <svg 
              className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[var(--muted)]" 
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Search articles..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="form-input w-full pl-12"
            />
          </div>
        </div>

        {/* Category Pills */}
        {categories.length > 0 && (
          <div className="flex flex-wrap justify-center gap-2 mb-6">
            <button
              onClick={() => setSelectedCategory(null)}
              className={`filter-pill ${!selectedCategory ? 'filter-pill-active' : ''}`}
            >
              All
            </button>
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
                className={`filter-pill ${selectedCategory === cat ? 'filter-pill-active' : ''}`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}

        {/* Tags */}
        {tags.length > 0 && (
          <div className="flex flex-wrap justify-center gap-2 mb-6">
            {tags.map(tag => (
              <button
                key={tag}
                onClick={() => toggleTag(tag)}
                className={`filter-tag ${selectedTags.includes(tag) ? 'filter-tag-active' : ''}`}
              >
                #{tag}
              </button>
            ))}
          </div>
        )}

        {/* Active Filters Indicator */}
        {hasActiveFilters && (
          <div className="flex items-center justify-center gap-3 text-sm">
            <span className="text-[var(--muted)]">
              {filteredPosts.length} {filteredPosts.length === 1 ? 'result' : 'results'}
            </span>
            <button 
              onClick={clearFilters}
              className="text-[var(--accent-2)] hover:underline flex items-center gap-1"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
              Clear filters
            </button>
          </div>
        )}
      </div>

      {/* Featured Post */}
      {featuredPost && (
        <Link 
          href={`/blog/${featuredPost.slug}`} 
          className="rounded-2xl border border-[var(--border)] bg-[#0a0a0a] block hover:border-[var(--accent)]/30 transition-colors"
          style={{ padding: '2.5rem', marginBottom: '3rem' }}
        >
          <div className="flex flex-wrap items-center gap-3 mb-4">
            {featuredPost.category && <Badge>{featuredPost.category}</Badge>}
            {featuredPost.tags && featuredPost.tags.slice(0, 3).map(tag => (
              <span key={tag} className="text-xs text-[var(--muted)]">#{tag}</span>
            ))}
            {featuredPost.date && (
              <span className="text-sm text-[var(--muted)]">
                {new Date(featuredPost.date).toLocaleDateString('en-US', { 
                  year: 'numeric', 
                  month: 'long', 
                  day: 'numeric' 
                })}
              </span>
            )}
          </div>
          <h2 className="text-2xl md:text-3xl font-bold mb-3">{featuredPost.title}</h2>
          <p className="text-[var(--muted)] text-lg mb-4">{featuredPost.excerpt}</p>
          <span className="text-[var(--accent-2)] font-medium">Read more →</span>
        </Link>
      )}

      {/* Post Grid */}
      {otherPosts.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {otherPosts.map((post) => (
            <Link 
              key={post.slug} 
              href={`/blog/${post.slug}`} 
              className="rounded-xl border border-[var(--border)] bg-[#0a0a0a] p-7 group hover:border-[var(--accent)]/30 transition-colors"
            >
              <div className="flex flex-wrap items-center gap-2 mb-3">
                {post.category && <Badge className="text-xs border border-[var(--border-dim)]">{post.category}</Badge>}
                {post.date && (
                  <span className="text-xs text-[var(--muted)]">
                    {new Date(post.date).toLocaleDateString('en-US', { 
                      year: 'numeric', 
                      month: 'short', 
                      day: 'numeric' 
                    })}
                  </span>
                )}
              </div>
              <h3 className="text-lg font-semibold mb-2 group-hover:text-[var(--accent-2)] transition-colors">
                {post.title}
              </h3>
              <p className="text-sm text-[var(--muted)] line-clamp-3">{post.excerpt}</p>
              {post.tags && post.tags.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {post.tags.slice(0, 3).map(tag => (
                    <span key={tag} className="text-xs text-[var(--muted)]">#{tag}</span>
                  ))}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}

      {filteredPosts.length === 0 && (
        <div className="text-center py-12">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-[var(--card)] flex items-center justify-center">
            <svg className="w-8 h-8 text-[var(--muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <p className="text-[var(--muted)] mb-4">No articles match your filters.</p>
          <button 
            onClick={clearFilters}
            className="text-[var(--accent-2)] hover:underline"
          >
            Clear all filters
          </button>
        </div>
      )}
    </>
  );
}

