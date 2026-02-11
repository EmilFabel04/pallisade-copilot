'use client';

import React, { useState, useEffect, useRef } from 'react';
import { ArtifactType } from '@prisma/client';
import { toast } from 'sonner';

interface SaveArtifactModalProps {
  isOpen: boolean;
  onClose: () => void;
  content: string;
  sessionId: string | null;
  messageId: string;
}

const typeOptions: { value: ArtifactType; label: string; description: string; icon: React.ReactNode }[] = [
  {
    value: 'QUERY',
    label: 'Query',
    description: 'SQL queries and data explorations',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
      </svg>
    ),
  },
  {
    value: 'FIX',
    label: 'Fix',
    description: 'Bug fixes and solutions',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    value: 'INSIGHT',
    label: 'Insight',
    description: 'Analysis and explanations',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  {
    value: 'CODE',
    label: 'Code',
    description: 'Code snippets and scripts',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
      </svg>
    ),
  },
  {
    value: 'PLAN',
    label: 'Plan',
    description: 'Implementation plans and strategies',
    icon: (
      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
      </svg>
    ),
  },
];

const typeColors: Record<ArtifactType, string> = {
  QUERY: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  FIX: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  INSIGHT: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  CODE: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  PLAN: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
};

function detectType(content: string): ArtifactType {
  const lowerContent = content.toLowerCase();

  // Check for SQL patterns
  if (/```sql|select\s+[\w*]|from\s+\w+|where\s+\w+|join\s+\w+|create\s+table|insert\s+into/i.test(content)) {
    return 'QUERY';
  }

  // Check for fix patterns
  if (/fix|fixed|solution|resolve|resolved|bug|error|issue|problem|here's how to|the issue was/i.test(content)) {
    return 'FIX';
  }

  // Check for code patterns (non-SQL)
  if (/```(python|javascript|typescript|bash|yaml|json)/i.test(content)) {
    return 'CODE';
  }

  // Check for plan patterns
  if (/plan|step\s+\d|phase\s+\d|implementation|roadmap|approach|strategy|first.*then.*finally/i.test(content)) {
    return 'PLAN';
  }

  // Default to insight
  return 'INSIGHT';
}

function generateTitle(content: string): string {
  // Extract first meaningful line
  const lines = content.split('\n').filter(l => l.trim());
  let title = lines[0] || 'Untitled';

  // Clean up markdown
  title = title
    .replace(/^#+\s*/, '')
    .replace(/\*\*/g, '')
    .replace(/`/g, '')
    .trim();

  // Truncate if too long
  if (title.length > 60) {
    title = title.substring(0, 57) + '...';
  }

  return title;
}

export function SaveArtifactModal({
  isOpen,
  onClose,
  content,
  sessionId,
  messageId,
}: SaveArtifactModalProps) {
  const [title, setTitle] = useState('');
  const [type, setType] = useState<ArtifactType>('INSIGHT');
  const [tags, setTags] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);

  // Initialize values when modal opens
  useEffect(() => {
    if (isOpen && content) {
      setTitle(generateTitle(content));
      setType(detectType(content));
      setTags('');
      // Focus title input after a short delay
      setTimeout(() => titleInputRef.current?.focus(), 100);
    }
  }, [isOpen, content]);

  // Handle escape key and outside click
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    const handleClickOutside = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, onClose]);

  const handleSave = async () => {
    if (!title.trim()) {
      toast.error('Please enter a title');
      return;
    }

    setIsSaving(true);
    try {
      const response = await fetch('/api/artifacts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          content,
          type,
          tags: tags.split(',').map(t => t.trim()).filter(Boolean),
          sourceSessionId: sessionId,
          sourceMessageId: messageId,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to save artifact');
      }

      toast.success('Saved to Artifacts');
      onClose();
    } catch (error) {
      console.error('Error saving artifact:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to save artifact');
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Modal */}
      <div
        ref={modalRef}
        className="relative w-full max-w-md bg-[#0f0f14] border border-white/[0.08] rounded-xl shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
          <h2 className="text-[15px] font-semibold text-white">Save to Artifacts</h2>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-white/40 hover:text-white hover:bg-white/[0.06] transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="px-5 py-4 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-[12px] font-medium text-white/50 mb-1.5">Title</label>
            <input
              ref={titleInputRef}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Enter a title..."
              className="w-full h-10 px-3 bg-white/[0.03] border border-white/[0.08] rounded-lg text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.15] focus:ring-1 focus:ring-white/[0.06] transition-colors"
            />
          </div>

          {/* Type */}
          <div>
            <label className="block text-[12px] font-medium text-white/50 mb-1.5">Type</label>
            <div className="grid grid-cols-5 gap-2">
              {typeOptions.map((option) => (
                <button
                  key={option.value}
                  onClick={() => setType(option.value)}
                  className={`flex flex-col items-center gap-1.5 p-2.5 rounded-lg border transition-all ${
                    type === option.value
                      ? typeColors[option.value]
                      : 'border-white/[0.06] text-white/40 hover:border-white/[0.12] hover:text-white/60'
                  }`}
                  title={option.description}
                >
                  {option.icon}
                  <span className="text-[10px] font-medium">{option.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-[12px] font-medium text-white/50 mb-1.5">
              Tags <span className="text-white/30">(comma separated)</span>
            </label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g., analytics, orders, debug"
              className="w-full h-10 px-3 bg-white/[0.03] border border-white/[0.08] rounded-lg text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/[0.15] focus:ring-1 focus:ring-white/[0.06] transition-colors"
            />
          </div>

          {/* Preview */}
          <div>
            <label className="block text-[12px] font-medium text-white/50 mb-1.5">Preview</label>
            <div className="max-h-32 overflow-y-auto p-3 bg-white/[0.02] border border-white/[0.06] rounded-lg">
              <pre className="text-[11px] text-white/50 font-mono whitespace-pre-wrap break-words line-clamp-6">
                {content.length > 500 ? content.substring(0, 500) + '...' : content}
              </pre>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-white/[0.06]">
          <button
            onClick={onClose}
            className="px-4 h-9 text-[13px] font-medium text-white/60 hover:text-white hover:bg-white/[0.04] rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || !title.trim()}
            className="px-4 h-9 text-[13px] font-medium bg-white text-black rounded-lg hover:bg-white/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isSaving ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-black/30 border-t-black rounded-full animate-spin" />
                Saving...
              </>
            ) : (
              'Save'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
