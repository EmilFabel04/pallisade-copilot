'use client';

import { useState, useRef, useEffect } from 'react';
import { ExternalLink } from 'lucide-react';
import { QuickLink } from './types';

interface Props {
  links: QuickLink[];
  sourceName: string;
}

export default function QuickLinkButton({ links, sourceName }: Props) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingLink, setPendingLink] = useState<QuickLink | null>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!pickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setPickerOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [pickerOpen]);

  if (!links || links.length === 0) return null;

  const onIconClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (links.length === 1) {
      setPendingLink(links[0]);
    } else {
      setPickerOpen((v) => !v);
    }
  };

  const confirm = () => {
    if (!pendingLink) return;
    window.open(pendingLink.url, '_blank', 'noopener,noreferrer');
    setPendingLink(null);
  };

  return (
    <>
      <div className="relative" ref={pickerRef}>
        <button
          onClick={onIconClick}
          title={links.length === 1 ? `Open ${links[0].label}` : 'Quick links'}
          className="p-1.5 rounded-md hover:bg-[var(--hover-bg)] text-[var(--text-tertiary)] hover:text-[var(--text)]
                     transition-colors"
        >
          <ExternalLink className="w-4 h-4" />
        </button>
        {pickerOpen && links.length > 1 && (
          <div
            className="absolute right-0 top-full mt-1 w-56 rounded-lg border border-[var(--subtle-border)]
                       bg-[var(--surface)] shadow-xl z-50 py-1 overflow-hidden"
          >
            <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-[var(--text-faint)]">
              Quick Links
            </div>
            {links.map((link, i) => (
              <button
                key={`${link.url}-${i}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setPickerOpen(false);
                  setPendingLink(link);
                }}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-[var(--text-secondary)]
                           hover:bg-[var(--hover-bg)] hover:text-[var(--text)] transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate text-left flex-1">{link.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {pendingLink && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={(e) => {
            e.stopPropagation();
            setPendingLink(null);
          }}
        >
          <div
            className="w-[420px] max-w-[90vw] rounded-xl border border-[var(--subtle-border)] bg-[var(--surface)]
                       shadow-2xl p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-[15px] font-semibold text-[var(--text)] mb-2">
              Open external link?
            </h3>
            <p className="text-[13px] text-[var(--text-secondary)] mb-1">
              You are about to leave Pallisade for <span className="font-medium text-[var(--text)]">{sourceName}</span>’s quick link:
            </p>
            <p className="text-[12px] text-[var(--accent)] font-mono break-all mb-4 px-2 py-1.5 rounded bg-[var(--overlay-bg)]">
              {pendingLink.label} · {pendingLink.url}
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => setPendingLink(null)}
                className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-[var(--muted)]
                           hover:text-[var(--text)] hover:bg-[var(--hover-bg)] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirm}
                className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-white bg-[var(--accent)]
                           hover:bg-[var(--accent-2)] transition-colors inline-flex items-center gap-1.5"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Open in new tab
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
