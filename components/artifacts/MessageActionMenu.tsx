'use client';

import { useState, useRef, useEffect } from 'react';
import { toast } from 'sonner';

interface MessageActionMenuProps {
  content: string;
  messageId: string;
  sessionId: string | null;
  onSaveToArtifacts: () => void;
  isOpen: boolean;
  onClose: () => void;
}

export function MessageActionMenu({
  content,
  isOpen,
  onClose,
  onSaveToArtifacts,
}: MessageActionMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose();
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleEscape);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen, onClose]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    toast.success('Copied to clipboard');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div
      ref={menuRef}
      className="absolute right-0 top-8 z-20 w-44 bg-[var(--surface)] border border-[var(--subtle-border)] rounded-lg shadow-xl overflow-hidden"
    >
      <button
        onClick={onSaveToArtifacts}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[13px] text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)] transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
        Save to Artifacts
      </button>
      <button
        onClick={handleCopy}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[13px] text-[var(--text-tertiary)] hover:bg-[var(--overlay-bg)] hover:text-[var(--text)] transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
        Copy
      </button>
    </div>
  );
}

// Three-dot button component to use alongside the menu
interface MessageActionButtonProps {
  onClick: () => void;
  className?: string;
}

export function MessageActionButton({ onClick, className = '' }: MessageActionButtonProps) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`p-1.5 rounded-md opacity-0 group-hover:opacity-100 hover:bg-[var(--hover-bg)] transition-opacity ${className}`}
    >
      <svg className="w-4 h-4 text-[var(--muted)]" fill="currentColor" viewBox="0 0 20 20">
        <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
      </svg>
    </button>
  );
}
