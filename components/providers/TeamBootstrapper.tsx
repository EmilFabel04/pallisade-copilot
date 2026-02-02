'use client';

import { useEffect, useRef } from 'react';
import { useSession } from 'next-auth/react';

// This component ensures the current user has a team membership
// It runs once when the dashboard loads
export function TeamBootstrapper() {
  const { data: session } = useSession();
  const hasBootstrapped = useRef(false);

  useEffect(() => {
    // Only bootstrap once per session
    if (hasBootstrapped.current || !session?.user) return;

    const organizationId = (session.user as any).organizationId;
    if (!organizationId) return;

    // Check and bootstrap membership
    const bootstrap = async () => {
      try {
        const checkRes = await fetch('/api/team/bootstrap');
        const checkData = await checkRes.json();

        if (checkData.hasOrg && !checkData.hasMembership) {
          // User has org but no membership - create one
          await fetch('/api/team/bootstrap', { method: 'POST' });
          console.log('[Team] Bootstrapped membership for existing user');
        }

        hasBootstrapped.current = true;
      } catch (err) {
        // Silently fail - non-critical operation
        console.warn('[Team] Bootstrap check failed:', err);
      }
    };

    bootstrap();
  }, [session]);

  // This component doesn't render anything
  return null;
}
