'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/**
 * Redirect to the main assistant page.
 * This page exists for backwards compatibility with old links/bookmarks.
 */
export default function ChatRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/dashboard/assistant');
  }, [router]);

  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        <div className="w-8 h-8 red-spinner mx-auto mb-4" />
        <p className="text-sm text-[var(--muted)]">Redirecting to AI Chat...</p>
      </div>
    </div>
  );
}
