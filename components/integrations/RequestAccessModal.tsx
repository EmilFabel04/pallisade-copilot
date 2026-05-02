'use client';

import { useState, useEffect } from 'react';
import { toast } from 'sonner';

interface Props {
  connectorId: 'salesforce' | 'shopify' | 'hubspot';
  connectorName: string;
  open: boolean;
  onClose: () => void;
}

export function RequestAccessModal({ connectorId, connectorName, open, onClose }: Props) {
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    if (open) document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [open, onClose]);

  if (!open) return null;

  async function handleNotify() {
    setSubmitting(true);
    try {
      const res = await fetch('/api/v1/waitlist/source-connector', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connector_id: connectorId }),
      });
      if (!res.ok) throw new Error(await res.text());
      toast.success(`We'll notify you when ${connectorName} support ships.`);
      onClose();
    } catch (e: unknown) {
      toast.error(`Couldn't record interest: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="request-access-title"
        className="bg-[var(--surface)] border border-[var(--subtle-border)] rounded-2xl w-full max-w-md p-6 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <h2 id="request-access-title" className="text-lg font-semibold mb-2 text-[var(--text-primary)]">
          {connectorName} source &mdash; coming soon
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          We&apos;re working on first-class {connectorName} support as a Pallisade source. Click
          below to be notified when it ships.
        </p>
        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            disabled={submitting}
            className="px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-50"
          >
            Close
          </button>
          <button
            onClick={handleNotify}
            disabled={submitting}
            className="px-4 py-2 bg-slate-700 text-white rounded-lg text-sm font-medium hover:bg-slate-600 transition-colors disabled:opacity-50"
          >
            {submitting ? 'Recording…' : 'Notify me'}
          </button>
        </div>
      </div>
    </div>
  );
}
